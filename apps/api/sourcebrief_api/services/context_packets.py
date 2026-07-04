from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal, require_principal, require_scope
from sourcebrief_api.retrieval import (
    embedding_namespace_diagnostics,
    make_snippet,
    normalize_retrieval_profile,
    retrieval_profile_manifest,
    retrieve_context_candidates,
)
from sourcebrief_api.schemas import ContextPacketItemRead, ContextPacketRead, ContextPacketRequest
from sourcebrief_api.services.access import effective_resource_ids, require_project_access
from sourcebrief_shared.db import get_session
from sourcebrief_shared.embeddings import current_embedding_config
from sourcebrief_shared.models import (
    AuditEvent,
    ContextPacket,
    ContextPacketItem,
    QueryRun,
    RetrievalHit,
)


def create_context_packet_action(
    workspace_id: UUID,
    project_id: UUID,
    payload: ContextPacketRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ContextPacketRead:
    """Build a cited context packet through permission-scoped hybrid retrieval."""
    if payload.mode != "hybrid":
        raise HTTPException(status_code=422, detail="only hybrid context packets are supported")
    user = principal.user
    require_scope(principal, "project:query")
    resource_ids = effective_resource_ids(principal, payload.resource_ids)
    payload = payload.model_copy(update={"resource_ids": resource_ids})
    require_project_access(session, workspace_id, project_id, principal)

    retrieval_profile = normalize_retrieval_profile(payload.profile)
    embedding_config = current_embedding_config()
    vector_diagnostics = embedding_namespace_diagnostics(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        resource_ids=payload.resource_ids,
    )
    query_run = QueryRun(
        workspace_id=workspace_id,
        project_id=project_id,
        actor_user_id=user.id,
        query=payload.query,
        mode=payload.mode,
        top_k=payload.top_k,
        provider=embedding_config.provider,
        model=embedding_config.model,
        status="running",
        meta={
            "resource_ids": [str(rid) for rid in payload.resource_ids or []],
            "retrieval_profile": retrieval_profile.name,
            **vector_diagnostics,
        },
    )
    session.add(query_run)
    session.commit()
    query_run_id = query_run.id

    try:
        candidates = retrieve_context_candidates(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            query=payload.query,
            top_k=payload.top_k,
            resource_ids=payload.resource_ids,
            profile=retrieval_profile.name,
        )
        packet = ContextPacket(
            workspace_id=workspace_id,
            project_id=project_id,
            query_run_id=query_run_id,
            status="succeeded",
            item_count=len(candidates),
            meta={"builder": "m3-hybrid-context-packet", "retrieval_profile": retrieval_profile.name},
        )
        session.add(packet)
        session.flush()

        items: list[ContextPacketItemRead] = []
        for rank, candidate in enumerate(candidates, start=1):
            citation = {
                "resource_id": str(candidate.resource_id),
                "snapshot_id": str(candidate.snapshot_id),
                "chunk_id": str(candidate.chunk_id),
                "path": candidate.path,
                "title": candidate.title,
                "ordinal": candidate.ordinal,
                "content_hash": candidate.content_hash,
                "version": candidate.version,
                "version_kind": candidate.version_kind,
                "commit": candidate.snapshot_metadata.get("commit"),
            }
            hit = RetrievalHit(
                workspace_id=workspace_id,
                project_id=project_id,
                query_run_id=query_run_id,
                resource_id=candidate.resource_id,
                source_snapshot_id=candidate.snapshot_id,
                chunk_id=candidate.chunk_id,
                rank=rank,
                lexical_score=candidate.lexical_score,
                vector_score=candidate.vector_score,
                graph_score=candidate.graph_score,
                rerank_score=candidate.rerank_score,
                score=candidate.score,
                meta={"path": candidate.path, "content_hash": candidate.content_hash},
            )
            session.add(hit)
            session.flush()
            snippet = make_snippet(candidate.content)
            session.add(
                ContextPacketItem(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    context_packet_id=packet.id,
                    retrieval_hit_id=hit.id,
                    resource_id=candidate.resource_id,
                    source_snapshot_id=candidate.snapshot_id,
                    chunk_id=candidate.chunk_id,
                    rank=rank,
                    citation=citation,
                    snippet=snippet,
                    score=candidate.score,
                )
            )
            items.append(
                ContextPacketItemRead(
                    rank=rank,
                    resource_id=candidate.resource_id,
                    snapshot_id=candidate.snapshot_id,
                    chunk_id=candidate.chunk_id,
                    path=candidate.path,
                    title=candidate.title,
                    ordinal=candidate.ordinal,
                    content_hash=candidate.content_hash,
                    version=candidate.version,
                    version_kind=candidate.version_kind,
                    commit=candidate.snapshot_metadata.get("commit"),
                    snippet=snippet,
                    score=candidate.score,
                    lexical_score=candidate.lexical_score,
                    vector_score=candidate.vector_score,
                    graph_score=candidate.graph_score,
                    rerank_score=candidate.rerank_score,
                    citation=citation,
                )
            )

        finished_query_run = session.get(QueryRun, query_run_id)
        if finished_query_run is None:
            raise RuntimeError("query_run disappeared during context packet build")
        finished_query_run.status = "succeeded"
        finished_query_run.hit_count = len(candidates)
        finished_query_run.finished_at = datetime.now(UTC)
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=user.id,
                actor_token_id=principal.token_id,
                action="context_packet.create",
                target_type="context_packet",
                target_id=packet.id,
                meta={"query_run_id": str(query_run_id), "hit_count": len(candidates)},
            )
        )
        session.commit()
        return ContextPacketRead(
            id=packet.id,
            query_run_id=query_run_id,
            workspace_id=workspace_id,
            project_id=project_id,
            query=payload.query,
            mode=payload.mode,
            provider=embedding_config.provider,
            model=embedding_config.model,
            count=len(items),
            diagnostics={
                **vector_diagnostics,
                "retrieval_profile": retrieval_profile.name,
                "retrieval_profile_weights": retrieval_profile_manifest()[retrieval_profile.name]["weights"],
                "rerank_score_range": [0.0, 1.0],
            },
            items=items,
        )
    except HTTPException:
        raise
    except Exception as exc:
        session.rollback()
        failed = session.get(QueryRun, query_run_id)
        if failed is not None:
            failed.status = "failed"
            failed.finished_at = datetime.now(UTC)
            failed.meta = {**(failed.meta or {}), "error": str(exc)[:500]}
            session.add(failed)
            session.commit()
        raise HTTPException(status_code=500, detail="context packet retrieval failed") from exc
