from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from contextsmith_shared.embeddings import embed_text, term_overlap_score, vector_literal


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
    score: float = 0.0


def make_snippet(content: str, limit: int = 420) -> str:
    collapsed = " ".join(content.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + "…"


def _resource_filter_clause(resource_ids: list[UUID] | None, params: dict) -> str:
    if not resource_ids:
        return ""
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


def retrieve_context_candidates(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    query: str,
    top_k: int,
    resource_ids: list[UUID] | None = None,
) -> list[RetrievalCandidate]:
    """Hybrid lexical + vector retrieval scoped to current snapshots only."""
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
    for row in session.execute(lexical_sql, base_params).mappings().all():
        _upsert_candidate(candidates, row, lexical_score=float(row["score"] or 0.0))

    vector_params = {**base_params, "embedding": vector_literal(embed_text(query))}
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
        ORDER BY e.embedding <=> CAST(:embedding AS vector), c.resource_id, c.ordinal ASC
        LIMIT :limit
        """
    )
    for row in session.execute(vector_sql, vector_params).mappings().all():
        _upsert_candidate(candidates, row, vector_score=float(row["score"] or 0.0))

    filtered: list[RetrievalCandidate] = []
    for candidate in candidates.values():
        candidate.rerank_score = term_overlap_score(query, candidate.content)
        # The offline hashing provider is not a true semantic model; avoid
        # returning random vector-nearest chunks that share no query terms. A
        # future HF/vLLM/SGLang provider can relax this with calibrated scores.
        if candidate.lexical_score <= 0 and candidate.rerank_score <= 0:
            continue
        candidate.score = (
            0.45 * candidate.lexical_score
            + 0.45 * candidate.vector_score
            + 0.10 * candidate.rerank_score
        )
        filtered.append(candidate)
    return sorted(
        filtered,
        key=lambda item: (-item.score, item.resource_id, item.ordinal, item.chunk_id),
    )[:top_k]
