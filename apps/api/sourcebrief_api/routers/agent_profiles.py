from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from sourcebrief_api.auth import (
    Principal,
    require_principal,
    require_scope,
    require_workspace_member,
)
from sourcebrief_api.schemas import AgentProfileRead, AgentProfileUpdate
from sourcebrief_shared.db import get_session
from sourcebrief_shared.models import AgentProfile, AuditEvent, Project

ProjectAccessAuthorizer = Callable[[Session, UUID, UUID, Principal], Project]
ProjectMemberAuthorizer = Callable[..., Project]
AgentProfileEnsurer = Callable[[Session, UUID, Project, UUID], AgentProfile]


@dataclass(frozen=True)
class AgentProfileRouterDeps:
    require_project_access: ProjectAccessAuthorizer
    require_project_member: ProjectMemberAuthorizer
    ensure_agent_profile: AgentProfileEnsurer


def agent_profile_read(
    session: Session, workspace_id: UUID, project: Project, profile: AgentProfile
) -> AgentProfileRead:
    stats = cast(
        Mapping[str, Any],
        session.execute(
            text(
                """
            WITH current_snapshots AS (
              SELECT current_snapshot_id
              FROM resources
              WHERE workspace_id = :ws
                AND project_id = :proj
                AND deleted_at IS NULL
                AND current_snapshot_id IS NOT NULL
            )
            SELECT
              (
                SELECT COUNT(*)
                FROM resources r
                WHERE r.workspace_id = :ws
                  AND r.project_id = :proj
                  AND r.deleted_at IS NULL
              ) AS resource_count,
              (SELECT COUNT(*) FROM current_snapshots) AS current_snapshot_count,
              (
                SELECT COUNT(*)
                FROM graph_nodes gn
                WHERE gn.workspace_id = :ws
                  AND gn.project_id = :proj
                  AND gn.source_snapshot_id IN (SELECT current_snapshot_id FROM current_snapshots)
              ) AS graph_node_count,
              (
                SELECT COUNT(*)
                FROM graph_edges ge
                WHERE ge.workspace_id = :ws
                  AND ge.project_id = :proj
                  AND ge.source_snapshot_id IN (SELECT current_snapshot_id FROM current_snapshots)
              ) AS graph_edge_count,
              (
                SELECT MAX(ir.finished_at)
                FROM index_runs ir
                WHERE ir.workspace_id = :ws
                  AND ir.project_id = :proj
                  AND ir.status = 'succeeded'
              ) AS last_index_finished_at
            """
            ),
            {"ws": workspace_id, "proj": project.id},
        ).mappings().first()
        or {},
    )
    return AgentProfileRead(
        id=profile.id,
        workspace_id=profile.workspace_id,
        project_id=profile.project_id,
        name=profile.name,
        description=profile.description,
        default_runtime=profile.default_runtime,
        system_prompt=profile.system_prompt,
        tool_policy=profile.tool_policy,
        resource_count=int(stats.get("resource_count") or 0),
        current_snapshot_count=int(stats.get("current_snapshot_count") or 0),
        graph_node_count=int(stats.get("graph_node_count") or 0),
        graph_edge_count=int(stats.get("graph_edge_count") or 0),
        last_index_finished_at=stats.get("last_index_finished_at"),
        mcp_endpoint=f"/mcp/{workspace_id}/{project.id}",
        agent_context_endpoint=f"/workspaces/{workspace_id}/projects/{project.id}/agent-context",
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def create_router(deps: AgentProfileRouterDeps) -> APIRouter:
    router = APIRouter()

    @router.get("/workspaces/{workspace_id}/agents", response_model=list[AgentProfileRead])
    def list_agents(
        workspace_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> list[AgentProfileRead]:
        user = principal.user
        require_scope(principal, "project:read")
        require_workspace_member(session, workspace_id, principal)
        projects = list(
            session.scalars(
                select(Project)
                .where(Project.workspace_id == workspace_id, Project.deleted_at.is_(None))
                .order_by(Project.created_at.asc())
            )
        )
        agents: list[AgentProfileRead] = []
        for project in projects:
            try:
                deps.require_project_access(session, workspace_id, project.id, principal)
            except HTTPException:
                continue
            profile = deps.ensure_agent_profile(session, workspace_id, project, user.id)
            agents.append(agent_profile_read(session, workspace_id, project, profile))
        session.commit()
        return agents

    @router.get(
        "/workspaces/{workspace_id}/projects/{project_id}/agent-profile",
        response_model=AgentProfileRead,
    )
    def get_agent_profile(
        workspace_id: UUID,
        project_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> AgentProfileRead:
        user = principal.user
        require_scope(principal, "project:read")
        project = deps.require_project_access(session, workspace_id, project_id, principal)
        profile = deps.ensure_agent_profile(session, workspace_id, project, user.id)
        session.commit()
        return agent_profile_read(session, workspace_id, project, profile)

    @router.patch(
        "/workspaces/{workspace_id}/projects/{project_id}/agent-profile",
        response_model=AgentProfileRead,
    )
    def update_agent_profile(
        workspace_id: UUID,
        project_id: UUID,
        payload: AgentProfileUpdate,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> AgentProfileRead:
        user = principal.user
        require_scope(principal, "token:admin")
        project = deps.require_project_member(
            session, workspace_id, project_id, principal, required_scopes={"token:admin"}
        )
        profile = deps.ensure_agent_profile(session, workspace_id, project, user.id)
        fields = payload.model_dump(exclude_unset=True)
        nullable_forbidden = {"name", "default_runtime", "tool_policy"}
        bad_null = sorted(key for key in nullable_forbidden if key in fields and fields[key] is None)
        if bad_null:
            raise HTTPException(status_code=422, detail=f"fields cannot be null: {', '.join(bad_null)}")
        for key, value in fields.items():
            setattr(profile, key, value)
        profile.updated_by = user.id
        profile.updated_at = datetime.now(UTC)
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=user.id,
                actor_token_id=principal.token_id,
                action="agent_profile.update",
                target_type="agent_profile",
                target_id=profile.id,
                meta={"fields": sorted(fields.keys())},
            )
        )
        session.commit()
        return agent_profile_read(session, workspace_id, project, profile)

    return router
