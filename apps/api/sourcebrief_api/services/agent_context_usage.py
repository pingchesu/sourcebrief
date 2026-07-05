from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal, token_allows_resource
from sourcebrief_api.retrieval import RetrievalCandidate
from sourcebrief_api.schemas import AgentContextCitation, AgentContextRequest
from sourcebrief_shared.models import IndexRun, QueryRun, Resource, RetrievalHit

RuntimeCallable = Callable[..., Any]


@dataclass(frozen=True)
class AgentContextUsageDeps:
    current_embedding_config: RuntimeCallable
    embedding_namespace_diagnostics: RuntimeCallable
    normalize_retrieval_profile: RuntimeCallable
    resource_read: RuntimeCallable
    runtime_safe_index_failure: Callable[[str | None], str]
    coverage_budget_reason: RuntimeCallable

def record_agent_context_usage(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    payload: AgentContextRequest,
    principal: Principal,
    candidates: list[RetrievalCandidate],
    deps: AgentContextUsageDeps,
) -> None:
    """Persist usage rows for agent-context without creating a context packet artifact."""
    embedding_config = deps.current_embedding_config()
    vector_diagnostics = deps.embedding_namespace_diagnostics(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        resource_ids=payload.resource_ids,
    )
    query_run = QueryRun(
        workspace_id=workspace_id,
        project_id=project_id,
        actor_user_id=principal.user.id,
        query=payload.query,
        mode=f"agent-context:{payload.runtime or 'default'}",
        top_k=payload.top_k,
        provider=embedding_config.provider,
        model=embedding_config.model,
        status="succeeded",
        hit_count=len(candidates),
        finished_at=datetime.now(UTC),
        meta={
            "resource_ids": [str(rid) for rid in payload.resource_ids or []],
            "runtime": payload.runtime,
            "retrieval_profile": deps.normalize_retrieval_profile(payload.profile).name,
            "context_max_chars": payload.max_chars,
            "include_code_symbols": payload.include_code_symbols,
            "source": "agent-context",
            **vector_diagnostics,
        },
    )
    session.add(query_run)
    session.flush()
    for rank, candidate in enumerate(candidates, start=1):
        session.add(
            RetrievalHit(
                workspace_id=workspace_id,
                project_id=project_id,
                query_run_id=query_run.id,
                resource_id=candidate.resource_id,
                source_snapshot_id=candidate.snapshot_id,
                chunk_id=candidate.chunk_id,
                rank=rank,
                lexical_score=candidate.lexical_score,
                vector_score=candidate.vector_score,
                graph_score=candidate.graph_score,
                rerank_score=candidate.rerank_score,
                score=candidate.score,
                meta={
                    "path": candidate.path,
                    "content_hash": candidate.content_hash,
                    "source": "agent-context",
                },
            )
        )
    session.commit()


def resource_coverage_entry(session: Session, resource: Resource, deps: AgentContextUsageDeps) -> dict[str, Any]:
    read = deps.resource_read(session, resource)
    diagnostics = read.index_diagnostics or {}
    last_index = session.scalar(
        select(IndexRun)
        .where(
            IndexRun.workspace_id == resource.workspace_id,
            IndexRun.project_id == resource.project_id,
            IndexRun.resource_id == resource.id,
        )
        .order_by(IndexRun.created_at.desc())
        .limit(1)
    )
    entry: dict[str, Any] = {
        "resource_id": str(resource.id),
        "name": resource.name,
        "queryable": read.queryable,
        "coverage_status": read.coverage_status,
        "coverage_warnings": read.coverage_warnings,
        "current_snapshot_id": str(resource.current_snapshot_id) if resource.current_snapshot_id else None,
        "retrieval_enabled": resource.retrieval_enabled,
        "configured_budgets": diagnostics.get("configured_budgets", {}),
        "limited_budget_keys": diagnostics.get("limited_budget_keys", []),
        "budget_reason": deps.coverage_budget_reason(read),
        "suggested_retry": diagnostics.get("suggested_retry"),
        "file_budget_stats": diagnostics.get("file_budget_stats", {}),
    }
    if last_index is not None:
        safe_failure = deps.runtime_safe_index_failure(last_index.error_message) if last_index.status == "failed" else None
        entry["last_index"] = {
            "status": last_index.status,
            "failure_summary": safe_failure,
            "documents_seen": last_index.documents_seen,
            "chunks_created": last_index.chunks_created,
            "symbols_created": last_index.symbols_created,
            "embeddings_created": last_index.embeddings_created,
            "started_at": last_index.started_at.isoformat() if last_index.started_at else None,
            "finished_at": last_index.finished_at.isoformat() if last_index.finished_at else None,
        }
        if safe_failure:
            entry.setdefault("coverage_warnings", []).append(safe_failure)
    return entry


def agent_context_resource_coverage(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    resource_ids: list[UUID] | None,
    citations: list[AgentContextCitation],
    principal: Principal,
    deps: AgentContextUsageDeps,
) -> tuple[list[dict[str, Any]], list[str]]:
    if resource_ids:
        ids = list(dict.fromkeys(resource_ids))
        predicates = [Resource.id.in_(ids)]
    else:
        ids = []
        predicates = []
    resources = list(
        session.scalars(
            select(Resource).where(
                Resource.workspace_id == workspace_id,
                Resource.project_id == project_id,
                Resource.deleted_at.is_(None),
                *predicates,
            )
        )
    )
    resources = [resource for resource in resources if token_allows_resource(principal, resource.id)]
    by_id = {resource.id: resource for resource in resources}
    ordered_ids = ids or [resource.id for resource in resources]
    citation_counts = Counter(citation.resource_id for citation in citations)
    explicit_multi_resource_request = bool(resource_ids and len(ids) > 1)
    coverage = []
    for rid in ordered_ids:
        if rid not in by_id:
            continue
        entry = resource_coverage_entry(session, by_id[rid], deps)
        citation_count = int(citation_counts.get(rid, 0))
        entry["citation_count"] = citation_count
        entry["evidence_status"] = "cited" if citation_count > 0 else "missing_citations"
        coverage.append(entry)
    warnings: list[str] = []
    for entry in coverage:
        for warning in entry.get("coverage_warnings", []):
            warnings.append(f"{entry['name']}: {warning}")
        if explicit_multi_resource_request and entry.get("citation_count", 0) == 0:
            warnings.append(
                "missing_requested_resources: "
                f"{entry['name']} ({entry['resource_id']}) returned zero citations for this query; "
                "narrow the query, raise top_k, or inspect the resource directly before making a comparison claim"
            )
    return coverage, warnings
