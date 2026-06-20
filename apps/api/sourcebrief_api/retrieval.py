from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from sourcebrief_shared.embeddings import (
    current_embedding_config,
    embed_text,
    embedding_namespace,
    is_dev_embedding_provider,
    rerank_score,
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
        use_graph=False,
    ),
    "hybrid_rerank": RetrievalProfile(
        name="hybrid_rerank",
        description="Hybrid retrieval with stronger rerank influence for eval-backed answer quality experiments.",
        lexical_weight=0.35,
        vector_weight=0.35,
        graph_weight=0.0,
        rerank_weight=0.30,
        use_graph=False,
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
    score: float = 0.0


def make_snippet(content: str, limit: int = 420) -> str:
    collapsed = " ".join(content.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + "…"


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
    candidate_limit = max(top_k * 4, 20)
    base_params: dict = {
        "ws": str(workspace_id),
        "proj": str(project_id),
        "q": query,
        "limit": candidate_limit,
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
               ts_rank(to_tsvector('english', c.content), plainto_tsquery('english', :q)) AS score
        {common_from}
          AND to_tsvector('english', c.content) @@ plainto_tsquery('english', :q)
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
          AND to_tsvector('simple', n.label || ' ' || coalesce(n.path, ''))
              @@ plainto_tsquery('simple', :q)
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
    require_text_overlap = is_dev_embedding_provider(embedding_config)
    for candidate in candidates.values():
        candidate.rerank_score = rerank_score(query, candidate.content) if retrieval_profile.use_rerank else 0.0
        # The offline hashing provider is not a true semantic model; avoid
        # returning random vector-nearest chunks that share no query terms. Real
        # embedding providers may legitimately return semantic-only matches.
        if require_text_overlap and candidate.lexical_score <= 0 and candidate.rerank_score <= 0 and candidate.graph_score <= 0:
            continue
        candidate.score = (
            retrieval_profile.lexical_weight * candidate.lexical_score
            + retrieval_profile.vector_weight * candidate.vector_score
            + retrieval_profile.graph_weight * candidate.graph_score
            + retrieval_profile.rerank_weight * candidate.rerank_score
        )
        filtered.append(candidate)
    return sorted(
        filtered,
        key=lambda item: (-item.score, item.resource_id, item.ordinal, item.chunk_id),
    )[:top_k]
