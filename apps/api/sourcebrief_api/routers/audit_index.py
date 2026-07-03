from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from sourcebrief_api.auth import (
    Principal,
    require_any_scope,
    require_principal,
    require_scope,
    require_workspace_member,
    token_allows_resource,
)
from sourcebrief_api.schemas import AuditEventRead, IndexRunRead
from sourcebrief_shared.db import get_session
from sourcebrief_shared.models import AuditEvent, IndexRun, Resource

WorkspaceAdminAuthorizer = Callable[[Session, UUID, Principal], object]
ProjectAccessAuthorizer = Callable[[Session, UUID, UUID, Principal], object]
ResourceResolver = Callable[..., Resource]


@dataclass(frozen=True)
class AuditIndexRouterDeps:
    require_workspace_admin: WorkspaceAdminAuthorizer
    require_project_access: ProjectAccessAuthorizer
    resolve_resource: ResourceResolver


def audit_event_read(event: AuditEvent) -> AuditEventRead:
    return AuditEventRead(
        id=event.id,
        workspace_id=event.workspace_id,
        actor_user_id=event.actor_user_id,
        actor_token_id=event.actor_token_id,
        action=event.action,
        target_type=event.target_type,
        target_id=event.target_id,
        target_ref=event.target_ref or {},
        metadata=event.meta or {},
        created_at=event.created_at,
    )


def create_router(deps: AuditIndexRouterDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/workspaces/{workspace_id}/audit-events", response_model=list[AuditEventRead])
    def list_audit_events(
        workspace_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> list[AuditEventRead]:
        require_scope(principal, "token:admin")
        deps.require_workspace_admin(session, workspace_id, principal)
        events = list(
            session.scalars(
                select(AuditEvent)
                .where(AuditEvent.workspace_id == workspace_id)
                .order_by(AuditEvent.created_at.desc())
            )
        )
        return [audit_event_read(event) for event in events]

    @router.get("/workspaces/{workspace_id}/index-runs/{index_run_id}", response_model=IndexRunRead)
    def get_index_run(
        workspace_id: UUID,
        index_run_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> IndexRun:
        require_any_scope(principal, {"project:read", "resource:read", "resource:refresh"})
        require_workspace_member(session, workspace_id, principal)
        run = session.scalar(
            select(IndexRun).where(IndexRun.workspace_id == workspace_id, IndexRun.id == index_run_id)
        )
        if run is None:
            raise HTTPException(status_code=404, detail="index run not found")
        if not token_allows_resource(principal, run.resource_id):
            raise HTTPException(status_code=404, detail="index run not found")
        deps.require_project_access(session, workspace_id, run.project_id, principal)
        return run

    @router.get(
        "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/index-runs",
        response_model=list[IndexRunRead],
    )
    def list_resource_index_runs(
        workspace_id: UUID,
        project_id: UUID,
        resource_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> list[IndexRun]:
        require_scope(principal, "resource:read")
        deps.require_project_access(session, workspace_id, project_id, principal)
        deps.resolve_resource(session, workspace_id, project_id, resource_id, principal)
        return list(
            session.scalars(
                select(IndexRun)
                .where(
                    IndexRun.workspace_id == workspace_id,
                    IndexRun.resource_id == resource_id,
                )
                .order_by(IndexRun.created_at.desc())
            )
        )

    return router
