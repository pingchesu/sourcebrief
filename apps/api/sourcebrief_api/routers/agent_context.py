from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal, require_principal, require_scope, token_allows_resource
from sourcebrief_api.schemas import (
    AgentCardSummaryAcknowledgeRequest,
    AgentCardSummaryListResponse,
    AgentCardSummaryRead,
    AgentContextRequest,
    AgentContextResponse,
    RepoAgentBriefRead,
)
from sourcebrief_shared.agent_card_auditor import run_agent_card_auditor
from sourcebrief_shared.db import get_session
from sourcebrief_shared.models import AgentCardSummary, AuditEvent, Resource

ProjectAccessAuthorizer = Callable[[Session, UUID, UUID, Principal], object]
ProjectMemberAuthorizer = Callable[..., object]
ResourceResolver = Callable[..., Resource]
EffectiveResourceIdsResolver = Callable[[Principal, list[UUID] | None], list[UUID] | None]
AgentContextRefResolver = Callable[
    [Session, UUID, UUID, Principal, AgentContextRequest], AgentContextRequest
]
PackVersionResolver = Callable[..., object | None]
AgentContextBuilder = Callable[..., AgentContextResponse]
PackAgentContextBuilder = Callable[..., AgentContextResponse]
RepoAgentBriefBuilder = Callable[[Session, UUID, UUID, Resource], RepoAgentBriefRead]


@dataclass(frozen=True)
class AgentContextRouterDeps:
    require_project_access: ProjectAccessAuthorizer
    require_project_member: ProjectMemberAuthorizer
    resolve_resource: ResourceResolver
    effective_resource_ids: EffectiveResourceIdsResolver
    agent_context_with_resource_ref: AgentContextRefResolver
    resolve_runtime_pack_version: PackVersionResolver
    build_agent_context_response: AgentContextBuilder
    build_pack_agent_context_response: PackAgentContextBuilder
    repo_agent_brief_response: RepoAgentBriefBuilder


def agent_card_summary_read(summary: AgentCardSummary) -> AgentCardSummaryRead:
    return AgentCardSummaryRead(
        id=summary.id,
        workspace_id=summary.workspace_id,
        project_id=summary.project_id,
        resource_id=summary.resource_id,
        status=summary.status,
        severity=summary.severity,
        summary=summary.summary,
        findings=list(summary.findings or []),
        metrics=dict(summary.metrics or {}),
        source=summary.source,
        acknowledged_at=summary.acknowledged_at,
        acknowledged_by=summary.acknowledged_by,
        suppressed_until=summary.suppressed_until,
        created_at=summary.created_at,
    )


def create_router(deps: AgentContextRouterDeps) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/agent-context",
        response_model=AgentContextResponse,
    )
    def agent_context(
        workspace_id: UUID,
        project_id: UUID,
        payload: AgentContextRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> AgentContextResponse:
        require_scope(principal, "project:query")
        deps.require_project_access(session, workspace_id, project_id, principal)
        payload = deps.agent_context_with_resource_ref(
            session, workspace_id, project_id, principal, payload
        )
        resource_ids = deps.effective_resource_ids(principal, payload.resource_ids)
        payload = payload.model_copy(update={"resource_ids": resource_ids})
        pack_version = deps.resolve_runtime_pack_version(
            session, workspace_id, project_id, payload, principal
        )
        if pack_version is not None:
            return deps.build_pack_agent_context_response(
                session,
                workspace_id=workspace_id,
                project_id=project_id,
                payload=payload,
                principal=principal,
                pack_version=pack_version,
            )
        return deps.build_agent_context_response(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            payload=payload,
            principal=principal,
        )

    @router.get(
        "/workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries",
        response_model=AgentCardSummaryListResponse,
    )
    def list_agent_card_summaries(
        workspace_id: UUID,
        project_id: UUID,
        latest_only: bool = Query(default=True),
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> AgentCardSummaryListResponse:
        require_scope(principal, "review:read")
        deps.require_project_access(session, workspace_id, project_id, principal)
        predicates = [
            AgentCardSummary.workspace_id == workspace_id,
            AgentCardSummary.project_id == project_id,
            Resource.id == AgentCardSummary.resource_id,
            Resource.workspace_id == AgentCardSummary.workspace_id,
            Resource.project_id == AgentCardSummary.project_id,
            Resource.deleted_at.is_(None),
            Resource.archived_at.is_(None),
        ]
        if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
            predicates.append(
                AgentCardSummary.resource_id.in_(principal.api_token.allowed_resource_ids)
            )
        summaries = list(
            session.scalars(
                select(AgentCardSummary)
                .where(*predicates)
                .order_by(AgentCardSummary.resource_id.asc(), AgentCardSummary.created_at.desc())
                .limit(300)
            )
        )
        if latest_only:
            latest_by_resource: dict[UUID, AgentCardSummary] = {}
            for summary in summaries:
                latest_by_resource.setdefault(summary.resource_id, summary)
            items = [agent_card_summary_read(summary) for summary in latest_by_resource.values()]
        else:
            items = [agent_card_summary_read(summary) for summary in summaries[:100]]
        return AgentCardSummaryListResponse(count=len(items), summaries=items)

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries/run",
        response_model=AgentCardSummaryListResponse,
    )
    def run_agent_card_summary_audit(
        workspace_id: UUID,
        project_id: UUID,
        dry_run: bool = Query(default=True),
        resource_ids: list[UUID] | None = Query(default=None),
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> AgentCardSummaryListResponse:
        require_scope(principal, "review:read")
        if not dry_run:
            require_scope(principal, "review:write")
            deps.require_project_member(
                session,
                workspace_id,
                project_id,
                principal,
                required_scopes={"review:read", "review:write"},
            )
        else:
            deps.require_project_access(session, workspace_id, project_id, principal)
        effective_resource_ids = deps.effective_resource_ids(principal, resource_ids)
        summaries = run_agent_card_auditor(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            resource_ids=effective_resource_ids,
            actor_user_id=principal.user.id,
            actor_token_id=principal.token_id,
            persist=not dry_run,
        )
        return AgentCardSummaryListResponse(
            count=len(summaries),
            summaries=[agent_card_summary_read(summary) for summary in summaries],
        )

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries/{summary_id}/acknowledge",
        response_model=AgentCardSummaryRead,
    )
    def acknowledge_agent_card_summary(
        workspace_id: UUID,
        project_id: UUID,
        summary_id: UUID,
        payload: AgentCardSummaryAcknowledgeRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> AgentCardSummaryRead:
        require_scope(principal, "review:write")
        deps.require_project_member(
            session, workspace_id, project_id, principal, required_scopes={"review:write"}
        )
        summary = session.scalar(
            select(AgentCardSummary).where(
                AgentCardSummary.id == summary_id,
                AgentCardSummary.workspace_id == workspace_id,
                AgentCardSummary.project_id == project_id,
            )
        )
        if summary is None:
            raise HTTPException(status_code=404, detail="agent card summary not found")
        if not token_allows_resource(principal, summary.resource_id):
            raise HTTPException(
                status_code=403, detail="token is not allowed to access this resource"
            )
        previous = {
            "acknowledged_at": summary.acknowledged_at.isoformat()
            if summary.acknowledged_at
            else None,
            "acknowledged_by": str(summary.acknowledged_by) if summary.acknowledged_by else None,
            "suppressed_until": summary.suppressed_until.isoformat()
            if summary.suppressed_until
            else None,
        }
        now = datetime.now(UTC)
        summary.acknowledged_at = now
        summary.acknowledged_by = principal.user.id
        summary.suppressed_until = (
            now + timedelta(hours=payload.suppress_for_hours)
            if payload.suppress_for_hours
            else None
        )
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="agent_card.summary_acknowledged",
                target_type="agent_card_summary",
                target_id=summary.id,
                target_ref={"resource_id": str(summary.resource_id)},
                meta={
                    "previous": previous,
                    "new": {
                        "acknowledged_at": summary.acknowledged_at.isoformat(),
                        "acknowledged_by": str(summary.acknowledged_by),
                        "suppressed_until": summary.suppressed_until.isoformat()
                        if summary.suppressed_until
                        else None,
                    },
                },
            )
        )
        session.commit()
        return agent_card_summary_read(summary)

    @router.get(
        "/workspaces/{workspace_id}/projects/{project_id}/repo-agents/{resource_id}/brief",
        response_model=RepoAgentBriefRead,
    )
    def get_repo_agent_brief(
        workspace_id: UUID,
        project_id: UUID,
        resource_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> RepoAgentBriefRead:
        require_scope(principal, "project:read")
        deps.require_project_access(session, workspace_id, project_id, principal)
        resource = deps.resolve_resource(session, workspace_id, project_id, resource_id, principal)
        return deps.repo_agent_brief_response(session, workspace_id, project_id, resource)

    return router
