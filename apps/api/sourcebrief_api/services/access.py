from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from sourcebrief_api.auth import (
    Principal,
    require_scope,
    require_workspace_member,
    token_allows_project,
    token_allows_resource,
)
from sourcebrief_shared.models import AgentProfile, Project, ProjectMembership, Resource


def normalize_email(email: str) -> str:
    return email.strip().lower()


def resolve_project(session: Session, workspace_id: UUID, project_id: UUID) -> Project:
    project = session.scalar(
        select(Project).where(Project.id == project_id, Project.workspace_id == workspace_id)
    )
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def ensure_agent_profile(
    session: Session, workspace_id: UUID, project: Project, user_id: UUID
) -> AgentProfile:
    profile = session.scalar(
        select(AgentProfile).where(
            AgentProfile.workspace_id == workspace_id,
            AgentProfile.project_id == project.id,
        )
    )
    if profile is not None:
        return profile
    profile = AgentProfile(
        workspace_id=workspace_id,
        project_id=project.id,
        name=project.name,
        description=project.description,
        default_runtime="hermes",
        system_prompt=None,
        tool_policy={"production_mutations": "external_approval_required"},
        created_by=user_id,
        updated_by=user_id,
    )
    session.add(profile)
    session.flush()
    return profile


def current_project_resources(session: Session, workspace_id: UUID, project_id: UUID) -> list[Resource]:
    return list(
        session.scalars(
            select(Resource)
            .where(
                Resource.workspace_id == workspace_id,
                Resource.project_id == project_id,
                Resource.deleted_at.is_(None),
            )
            .order_by(Resource.type.asc(), Resource.name.asc())
        )
    )


def require_project_access(
    session: Session, workspace_id: UUID, project_id: UUID, principal: Principal
) -> Project:
    """Resolve a project and enforce visibility/membership plus token project scope."""
    require_workspace_member(session, workspace_id, principal)
    if not token_allows_project(principal, project_id):
        raise HTTPException(status_code=404, detail="project not found")
    project = resolve_project(session, workspace_id, project_id)
    if project.visibility in {"workspace", "public"}:
        return project
    membership = session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.workspace_id == workspace_id,
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == principal.user.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def require_project_member(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    *,
    required_scopes: set[str] | None = None,
) -> Project:
    """Resolve a project and require explicit project membership plus token/project scope for mutations."""
    membership = require_workspace_member(session, workspace_id, principal)
    for required_scope in required_scopes or set():
        require_scope(principal, required_scope, membership)
    if not token_allows_project(principal, project_id):
        raise HTTPException(status_code=404, detail="project not found")
    project = resolve_project(session, workspace_id, project_id)
    membership = session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.workspace_id == workspace_id,
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == principal.user.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def resolve_resource(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal | None = None,
    *,
    include_deleted: bool = False,
) -> Resource:
    if principal is not None and not token_allows_resource(principal, resource_id):
        raise HTTPException(status_code=404, detail="resource not found")
    resource = session.scalar(
        select(Resource).where(
            Resource.id == resource_id,
            Resource.project_id == project_id,
            Resource.workspace_id == workspace_id,
        )
    )
    if resource is None or (resource.deleted_at is not None and not include_deleted):
        raise HTTPException(status_code=404, detail="resource not found")
    return resource


def require_requested_resources_allowed(
    principal: Principal, resource_ids: list[UUID] | None
) -> None:
    if not resource_ids:
        return
    denied = [
        resource_id for resource_id in resource_ids if not token_allows_resource(principal, resource_id)
    ]
    if denied:
        raise HTTPException(status_code=404, detail="resource not found")


def effective_resource_ids(
    principal: Principal, resource_ids: list[UUID] | None
) -> list[UUID] | None:
    token = principal.api_token
    requested = resource_ids
    if token is None or token.allowed_resource_ids is None:
        require_requested_resources_allowed(principal, requested)
        return requested
    if requested is None:
        return list(token.allowed_resource_ids)
    require_requested_resources_allowed(principal, requested)
    return requested


def is_empty_scope(resource_ids: list[UUID] | None) -> bool:
    return resource_ids is not None and len(resource_ids) == 0
