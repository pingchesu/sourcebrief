from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from sourcebrief_api.remote_code import query_identifier_tokens
from sourcebrief_shared.embeddings import (
    current_embedding_config,
    embed_text,
    embedding_namespace,
    is_dev_embedding_provider,
    rerank_scores,
    vector_literal,
)


@dataclass(frozen=True)
class RetrievalProfile:
    name: str
    description: str
    lexical_weight: float
    vector_weight: float
    graph_weight: float
    rerank_weight: float
    use_lexical: bool = True
    use_vector: bool = True
    use_graph: bool = True
    use_rerank: bool = True


RETRIEVAL_PROFILES: dict[str, RetrievalProfile] = {
    "lexical": RetrievalProfile(
        name="lexical",
        description="Keyword-first retrieval for exact identifiers, errors, config keys, and literal text.",
        lexical_weight=1.0,
        vector_weight=0.0,
        graph_weight=0.0,
        rerank_weight=0.0,
        use_vector=False,
        use_graph=False,
        use_rerank=False,
    ),
    "vector": RetrievalProfile(
        name="vector",
        description="Embedding-first retrieval for semantic questions when exact words may differ.",
        lexical_weight=0.0,
        vector_weight=0.85,
        graph_weight=0.0,
        rerank_weight=0.15,
        use_lexical=False,
        use_graph=False,
    ),
    "hybrid": RetrievalProfile(
        name="hybrid",
        description="Balanced lexical and embedding retrieval for general agent context.",
        lexical_weight=0.45,
        vector_weight=0.40,
        graph_weight=0.0,
        rerank_weight=0.15,
    ),
    "hybrid_rerank": RetrievalProfile(
        name="hybrid_rerank",
        description="Hybrid retrieval with stronger rerank influence for eval-backed answer quality experiments.",
        lexical_weight=0.35,
        vector_weight=0.35,
        graph_weight=0.0,
        rerank_weight=0.30,
    ),
    "graph": RetrievalProfile(
        name="graph",
        description="Hybrid retrieval boosted by graph/code-structure evidence for architecture and impact questions.",
        lexical_weight=0.35,
        vector_weight=0.30,
        graph_weight=0.25,
        rerank_weight=0.10,
    ),
}
DEFAULT_RETRIEVAL_PROFILE = "hybrid"


def normalize_retrieval_profile(profile: str | None) -> RetrievalProfile:
    key = (profile or DEFAULT_RETRIEVAL_PROFILE).strip().lower().replace("-", "_")
    if key not in RETRIEVAL_PROFILES:
        allowed = ", ".join(sorted(RETRIEVAL_PROFILES))
        raise ValueError(f"unsupported retrieval profile {profile!r}; allowed: {allowed}")
    return RETRIEVAL_PROFILES[key]


def retrieval_profile_manifest() -> dict[str, dict[str, object]]:
    return {
        name: {
            "description": profile.description,
            "weights": {
                "lexical": profile.lexical_weight,
                "vector": profile.vector_weight,
                "graph": profile.graph_weight,
                "rerank": profile.rerank_weight,
            },
        }
        for name, profile in RETRIEVAL_PROFILES.items()
    }


@dataclass
class RetrievalCandidate:
    chunk_id: UUID
    resource_id: UUID
    snapshot_id: UUID
    path: str | None
    title: str | None
    ordinal: int
    content_hash: str
    content: str
    version: str
    version_kind: str
    snapshot_metadata: dict
    lexical_score: float = 0.0
    vector_score: float = 0.0
    rerank_score: float = 0.0
    graph_score: float = 0.0
    path_prior_score: float = 0.0
    diversity_penalty: float = 0.0
    score: float = 0.0
    ranking_diagnostics: dict | None = None


def make_snippet(content: str, limit: int = 420) -> str:
    collapsed = " ".join(content.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + "…"


INSTALL_TERMS = (
    "install",
    "setup",
    "set up",
    "setting up",
    "quickstart",
    "quick start",
    "activate",
    "activation",
    "getting started",
    "onboarding",
)
ARCHITECTURE_TERMS = ("architecture", "design", "system", "overview", "harness", "long-horizon", "long horizon")
SKILL_TERMS = ("skill", "tool", "agent", "coding agent", "workflow")
LOW_SIGNAL_PATH_PARTS = (
    ".github/issue_template",
    "issue_template",
    "pull_request_template",
    "todo",
    "todos",
    "changelog",
    "claude.md",
    "agents.md",
)
LOCALIZED_README_NAMES = ("readme_", "readme-", "readme.")


def _normalized_path(path: str | None) -> str:
    return (path or "").replace("\\", "/").strip().lower()


def _path_family(path: str | None) -> str:
    normalized = _normalized_path(path)
    if not normalized:
        return "unknown"
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return "unknown"
    filename = parts[-1]
    if filename.startswith("readme"):
        return "readme"
    if "architecture" in filename or "architecture" in normalized:
        return "architecture"
    if len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0]


def path_prior_score(query: str, path: str | None, title: str | None = None) -> tuple[float, list[str]]:
    """Return a small, explainable path/type prior for retrieval quality."""
    q = query.lower()
    normalized = _normalized_path(path)
    name = normalized.rsplit("/", 1)[-1]
    title_text = (title or "").lower()
    prior = 0.0
    reasons: list[str] = []
    is_install = any(term in q for term in INSTALL_TERMS)
    is_architecture = any(term in q for term in ARCHITECTURE_TERMS)
    is_skill = any(term in q for term in SKILL_TERMS)

    if name in {"readme.md", "readme"}:
        if is_install or is_architecture or "overview" in q:
            prior += 0.16
            reasons.append("primary_readme")
        else:
            prior += 0.06
            reasons.append("readme")
    elif name.startswith(LOCALIZED_README_NAMES):
        prior -= 0.08
        reasons.append("localized_readme_downrank")

    if "quickstart" in normalized or "quick-start" in normalized or "getting-started" in normalized or "installation" in normalized:
        if is_install:
            prior += 0.16
            reasons.append("install_doc")
        else:
            prior += 0.04
            reasons.append("setup_doc")
    if "architecture" in normalized or "design" in normalized:
        if is_architecture:
            prior += 0.18
            reasons.append("architecture_doc")
        else:
            prior += 0.04
            reasons.append("design_doc")
    if is_skill and ("skill" in normalized or "tool" in normalized or "skill" in title_text):
        prior += 0.08
        reasons.append("skill_tool_doc")
    if any(part in normalized for part in LOW_SIGNAL_PATH_PARTS):
        prior -= 0.14
        reasons.append("low_signal_path")
    if normalized.endswith(('.py', '.ts', '.tsx', '.go', '.rs')) and (is_install or is_architecture):
        prior -= 0.04
        reasons.append("source_file_below_docs")
    return prior, reasons


def diversify_ranked_candidates(candidates: list[RetrievalCandidate], *, top_k: int) -> tuple[list[RetrievalCandidate], dict]:
    """Prefer citation breadth before filling remaining slots with near-duplicates."""
    selected: list[RetrievalCandidate] = []
    deferred: list[tuple[RetrievalCandidate, list[str]]] = []
    seen_hashes: set[str] = set()
    seen_paths: set[str] = set()
    path_family_counts: dict[str, int] = {}
    resource_counts: dict[UUID, int] = {}
    candidate_resources = {candidate.resource_id for candidate in candidates}
    target_resource_count = min(len(candidate_resources), top_k) or 1
    per_resource_soft_cap = (top_k + target_resource_count - 1) // target_resource_count
    for candidate in candidates:
        reasons: list[str] = []
        path_key = _normalized_path(candidate.path)
        family = _path_family(candidate.path)
        if candidate.content_hash and candidate.content_hash in seen_hashes:
            reasons.append("duplicate_content_hash")
        if path_key and path_key in seen_paths:
            reasons.append("duplicate_path")
        if path_family_counts.get(family, 0) >= 2:
            reasons.append("path_family_saturated")
        if resource_counts.get(candidate.resource_id, 0) >= per_resource_soft_cap:
            reasons.append("resource_saturated")
        if reasons:
            candidate.diversity_penalty = max(candidate.diversity_penalty, 0.05 * len(reasons))
            deferred.append((candidate, reasons))
            continue
        candidate.ranking_diagnostics = {**(candidate.ranking_diagnostics or {}), "diversity": "selected"}
        selected.append(candidate)
        if candidate.content_hash:
            seen_hashes.add(candidate.content_hash)
        if path_key:
            seen_paths.add(path_key)
        path_family_counts[family] = path_family_counts.get(family, 0) + 1
        resource_counts[candidate.resource_id] = resource_counts.get(candidate.resource_id, 0) + 1
        if len(selected) >= top_k:
            break
    if len(selected) < top_k:
        selected_ids = {candidate.chunk_id for candidate in selected}
        for candidate, reasons in deferred:
            if candidate.chunk_id in selected_ids:
                continue
            candidate.ranking_diagnostics = {
                **(candidate.ranking_diagnostics or {}),
                "diversity": "backfill",
                "backfill_reasons": reasons,
            }
            selected.append(candidate)
            selected_ids.add(candidate.chunk_id)
            if len(selected) >= top_k:
                break
    unique_paths = {_normalized_path(candidate.path) for candidate in selected if candidate.path}
    duplicate_path_count = max(0, len(selected) - len(unique_paths))
    candidate_resource_counts: dict[str, int] = {}
    for candidate in candidates:
        key = str(candidate.resource_id)
        candidate_resource_counts[key] = candidate_resource_counts.get(key, 0) + 1
    selected_resource_counts: dict[str, int] = {}
    for candidate in selected:
        key = str(candidate.resource_id)
        selected_resource_counts[key] = selected_resource_counts.get(key, 0) + 1
    return selected, {
        "candidate_pool_count": len(candidates),
        "selected_count": len(selected),
        "unique_citation_paths": len(unique_paths),
        "duplicate_citation_count": duplicate_path_count,
        "deduped_from_count": max(0, len(candidates) - len(selected)),
        "candidate_resource_counts": candidate_resource_counts,
        "selected_resource_counts": selected_resource_counts,
    }


def _resource_filter_clause(resource_ids: list[UUID] | None, params: dict) -> str:
    if resource_ids is None:
        return ""
    if not resource_ids:
        return "AND false"
    params["rids"] = [str(resource_id) for resource_id in resource_ids]
    return "AND r.id = ANY(CAST(:rids AS uuid[]))"


def _upsert_candidate(
    candidates: dict[UUID, RetrievalCandidate],
    row,
    *,
    lexical_score: float = 0.0,
    vector_score: float = 0.0,
) -> None:
    chunk_id = row["chunk_id"]
    snap_meta = row["snap_meta"] if isinstance(row["snap_meta"], dict) else {}
    candidate = candidates.get(chunk_id)
    if candidate is None:
        candidate = RetrievalCandidate(
            chunk_id=chunk_id,
            resource_id=row["resource_id"],
            snapshot_id=row["source_snapshot_id"],
            path=row["path"],
            title=row["title"],
            ordinal=row["ordinal"],
            content_hash=row["content_hash"],
            content=row["content"],
            version=row["version"],
            version_kind=row["version_kind"],
            snapshot_metadata=snap_meta,
        )
        candidates[chunk_id] = candidate
    candidate.lexical_score = max(candidate.lexical_score, lexical_score)
    candidate.vector_score = max(candidate.vector_score, vector_score)


def embedding_namespace_diagnostics(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    resource_ids: list[UUID] | None = None,
) -> dict:
    embedding_config = current_embedding_config()
    active_namespace = embedding_namespace(embedding_config)
    params: dict = {
        "ws": str(workspace_id),
        "proj": str(project_id),
        "namespace": active_namespace,
    }
    resource_clause = _resource_filter_clause(resource_ids, params)
    rows = session.execute(
        text(
            f"""
            SELECT e.namespace, count(*) AS count
            FROM chunk_embeddings e
            JOIN chunks c ON c.id = e.chunk_id
            WHERE c.workspace_id = CAST(:ws AS uuid)
              AND c.project_id = CAST(:proj AS uuid)
              AND c.deleted_at IS NULL
              AND c.source_snapshot_id IN (
                  SELECT r.current_snapshot_id FROM resources r
                  WHERE r.workspace_id = CAST(:ws AS uuid)
                    AND r.project_id = CAST(:proj AS uuid)
                    AND r.deleted_at IS NULL
                    AND r.archived_at IS NULL
                    AND r.retrieval_enabled = true
                    AND r.current_snapshot_id IS NOT NULL
                    {resource_clause}
              )
            GROUP BY e.namespace
            """
        ),
        params,
    ).mappings().all()
    namespaces = {str(row["namespace"]): int(row["count"] or 0) for row in rows}
    matching = namespaces.get(active_namespace, 0)
    total = sum(namespaces.values())
    if matching > 0:
        vector_status = "ok"
    elif total > 0:
        vector_status = "namespace_mismatch"
    else:
        vector_status = "no_embeddings"
    return {
        "embedding_namespace": active_namespace,
        "embedding_dimensions": embedding_config.dimensions,
        "embedding_normalized": embedding_config.normalized,
        "embedding_deployment_id": embedding_config.deployment_id,
        "vector_status": vector_status,
        "matching_embedding_count": matching,
        "total_embedding_count": total,
        "available_embedding_namespaces": sorted(namespaces),
    }


def retrieve_context_candidates(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    query: str,
    top_k: int,
    resource_ids: list[UUID] | None = None,
    profile: str | None = None,
) -> list[RetrievalCandidate]:
    """Profile-aware lexical/vector/graph retrieval scoped to current snapshots only."""
    retrieval_profile = normalize_retrieval_profile(profile)
    candidate_limit = max(top_k * 8, 40)
    base_params: dict = {
        "ws": str(workspace_id),
        "proj": str(project_id),
        "q": query,
        "limit": candidate_limit,
        "query_tokens": query_identifier_tokens(query),
    }
    resource_clause = _resource_filter_clause(resource_ids, base_params)
    common_from = f"""
        FROM chunks c
        JOIN source_snapshots s ON s.id = c.source_snapshot_id
        WHERE c.workspace_id = CAST(:ws AS uuid)
          AND c.project_id = CAST(:proj AS uuid)
          AND c.deleted_at IS NULL
          AND c.source_snapshot_id IN (
              SELECT r.current_snapshot_id FROM resources r
              WHERE r.workspace_id = CAST(:ws AS uuid)
                AND r.project_id = CAST(:proj AS uuid)
                AND r.deleted_at IS NULL
                AND r.archived_at IS NULL
                AND r.retrieval_enabled = true
                AND r.current_snapshot_id IS NOT NULL
                {resource_clause}
          )
    """
    select_columns = """
        SELECT c.id AS chunk_id, c.resource_id, c.source_snapshot_id, c.path, c.title,
               c.ordinal, c.content_hash, c.content, s.version, s.version_kind,
               s.metadata AS snap_meta
    """

    candidates: dict[UUID, RetrievalCandidate] = {}
    lexical_sql = text(
        f"""
        {select_columns},
               ts_rank(to_tsvector('english', c.content), plainto_tsquery('english', :q)) + (
                   SELECT count(*)
                   FROM unnest(CAST(:query_tokens AS text[])) AS qt(token)
                   WHERE lower(c.path || ' ' || coalesce(c.title, '') || ' ' || c.content) LIKE '%' || qt.token || '%'
               ) AS score
        {common_from}
          AND (
              to_tsvector('english', c.content) @@ plainto_tsquery('english', :q)
              OR (
                  cardinality(CAST(:query_tokens AS text[])) > 0
                  AND (
                      SELECT count(*)
                      FROM unnest(CAST(:query_tokens AS text[])) AS qt(token)
                      WHERE lower(c.path || ' ' || coalesce(c.title, '') || ' ' || c.content) LIKE '%' || qt.token || '%'
                  ) >= LEAST(2, cardinality(CAST(:query_tokens AS text[])))
              )
          )
        ORDER BY score DESC, c.resource_id, c.ordinal ASC
        LIMIT :limit
        """
    )
    if retrieval_profile.use_lexical:
        for row in session.execute(lexical_sql, base_params).mappings().all():
            _upsert_candidate(candidates, row, lexical_score=float(row["score"] or 0.0))

    embedding_config = current_embedding_config()
    if retrieval_profile.use_vector:
        vector_params = {
            **base_params,
            "embedding": vector_literal(embed_text(query, config=embedding_config)),
            "provider": embedding_config.provider,
            "model": embedding_config.model,
            "dimensions": embedding_config.dimensions,
            "namespace": embedding_namespace(embedding_config),
        }
        vector_sql = text(
            f"""
            {select_columns},
                   1 - (e.embedding <=> CAST(:embedding AS vector)) AS score
            FROM chunks c
            JOIN source_snapshots s ON s.id = c.source_snapshot_id
            JOIN chunk_embeddings e ON e.chunk_id = c.id
            WHERE c.workspace_id = CAST(:ws AS uuid)
              AND c.project_id = CAST(:proj AS uuid)
              AND c.deleted_at IS NULL
              AND c.source_snapshot_id IN (
                  SELECT r.current_snapshot_id FROM resources r
                  WHERE r.workspace_id = CAST(:ws AS uuid)
                    AND r.project_id = CAST(:proj AS uuid)
                    AND r.deleted_at IS NULL
                    AND r.archived_at IS NULL
                    AND r.retrieval_enabled = true
                    AND r.current_snapshot_id IS NOT NULL
                    {resource_clause}
              )
              AND e.provider = :provider
              AND e.model = :model
              AND e.dimensions = :dimensions
              AND e.namespace = :namespace
            ORDER BY e.embedding <=> CAST(:embedding AS vector), c.resource_id, c.ordinal ASC
            LIMIT :limit
            """
        )
        for row in session.execute(vector_sql, vector_params).mappings().all():
            _upsert_candidate(candidates, row, vector_score=float(row["score"] or 0.0))

    graph_sql = text(
        """
        SELECT c.id AS chunk_id,
               LEAST(1.0, COALESCE(MAX(
                   CASE
                     WHEN n.node_type = 'symbol' THEN 0.80
                     WHEN n.node_type = 'file' THEN 0.55
                     WHEN n.node_type = 'directory' THEN 0.30
                     ELSE 0.15
                   END * ge.weight
               ), 0.0)) AS graph_score
        FROM chunks c
        JOIN graph_nodes n ON n.source_snapshot_id = c.source_snapshot_id
          AND n.resource_id = c.resource_id
          AND (n.path = c.path OR n.node_type = 'resource')
        LEFT JOIN graph_edges ge ON (ge.target_node_id = n.id OR ge.source_node_id = n.id)
          AND ge.workspace_id = c.workspace_id
          AND ge.project_id = c.project_id
          AND ge.resource_id = c.resource_id
          AND ge.source_snapshot_id = c.source_snapshot_id
        WHERE c.workspace_id = CAST(:ws AS uuid)
          AND c.project_id = CAST(:proj AS uuid)
          AND c.deleted_at IS NULL
          AND c.id = ANY(CAST(:chunk_ids AS uuid[]))
          AND (
              to_tsvector('simple', n.label || ' ' || coalesce(n.path, ''))
                  @@ plainto_tsquery('simple', :q)
              OR (
                  cardinality(CAST(:query_tokens AS text[])) > 0
                  AND (
                      SELECT count(*)
                      FROM unnest(CAST(:query_tokens AS text[])) AS qt(token)
                      WHERE lower(n.label || ' ' || coalesce(n.path, '')) LIKE '%' || qt.token || '%'
                  ) >= LEAST(2, cardinality(CAST(:query_tokens AS text[])))
              )
          )
        GROUP BY c.id
        """
    )
    if candidates and retrieval_profile.use_graph:
        graph_params = {
            **base_params,
            "chunk_ids": [str(chunk_id) for chunk_id in candidates.keys()],
        }
        for row in session.execute(graph_sql, graph_params).mappings().all():
            candidate = candidates.get(row["chunk_id"])
            if candidate is not None:
                candidate.graph_score = max(candidate.graph_score, float(row["graph_score"] or 0.0))

    filtered: list[RetrievalCandidate] = []
    rerank_by_chunk: dict[UUID, float] = {}
    if retrieval_profile.use_rerank and candidates:
        candidate_list = list(candidates.values())
        batch_scores = rerank_scores(query, [candidate.content for candidate in candidate_list])
        rerank_by_chunk = {
            candidate.chunk_id: score for candidate, score in zip(candidate_list, batch_scores, strict=True)
        }
    require_text_overlap = is_dev_embedding_provider(embedding_config)
    for candidate in candidates.values():
        candidate.rerank_score = rerank_by_chunk.get(candidate.chunk_id, 0.0)
        # The offline hashing provider is not a true semantic model; avoid
        # returning random vector-nearest chunks that share no query terms. Real
        # embedding providers may legitimately return semantic-only matches.
        if require_text_overlap and candidate.lexical_score <= 0 and candidate.rerank_score <= 0 and candidate.graph_score <= 0:
            continue
        candidate.path_prior_score, prior_reasons = path_prior_score(query, candidate.path, candidate.title)
        base_score = (
            retrieval_profile.lexical_weight * candidate.lexical_score
            + retrieval_profile.vector_weight * candidate.vector_score
            + retrieval_profile.graph_weight * candidate.graph_score
            + retrieval_profile.rerank_weight * candidate.rerank_score
        )
        candidate.score = base_score + candidate.path_prior_score
        candidate.ranking_diagnostics = {
            "base_score": round(base_score, 6),
            "path_prior_score": round(candidate.path_prior_score, 6),
            "path_prior_reasons": prior_reasons,
            "lexical_score": round(candidate.lexical_score, 6),
            "vector_score": round(candidate.vector_score, 6),
            "graph_score": round(candidate.graph_score, 6),
            "rerank_score": round(candidate.rerank_score, 6),
        }
        filtered.append(candidate)
    ranked = sorted(
        filtered,
        key=lambda item: (-item.score, item.resource_id, item.ordinal, item.chunk_id),
    )
    selected, diversity_metadata = diversify_ranked_candidates(ranked, top_k=top_k)
    for candidate in selected:
        candidate.ranking_diagnostics = {
            **(candidate.ranking_diagnostics or {}),
            "retrieval_diversity": diversity_metadata,
            "final_score": round(candidate.score - candidate.diversity_penalty, 6),
        }
    return selected
