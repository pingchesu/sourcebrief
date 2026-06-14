from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from redis import Redis
from rq import Queue
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from contextsmith_api.auth import (
    Principal,
    hash_token,
    new_plaintext_token,
    require_any_scope,
    require_principal,
    require_scope,
    require_workspace_member,
    token_allows_project,
    token_allows_resource,
)
from contextsmith_api.retrieval import make_snippet, retrieve_context_candidates
from contextsmith_api.schemas import (
    AgentContextCitation,
    AgentContextRequest,
    AgentContextResponse,
    AgentProfileRead,
    AgentProfileUpdate,
    ApiTokenCreate,
    ApiTokenCreateResponse,
    ApiTokenRead,
    AuditEventRead,
    CodeSearchRequest,
    CodeSearchResponse,
    CodeSymbolHit,
    ContextPacketItemRead,
    ContextPacketRead,
    ContextPacketRequest,
    DueRefreshResponse,
    GraphEdgeRead,
    GraphNodeRead,
    GraphRead,
    IndexRunRead,
    ProjectCreate,
    ProjectRead,
    PurgeResourceResponse,
    ResourceCreate,
    ResourceRead,
    ResourceReviewItem,
    ResourceReviewRequest,
    ResourceReviewResponse,
    ResourceUpdate,
    ResourceUsageItem,
    ResourceUsageResponse,
    SearchHit,
    SearchRequest,
    SearchResponse,
    SnapshotRead,
    WorkspaceCreate,
    WorkspaceRead,
)
from contextsmith_shared.config import get_settings
from contextsmith_shared.db import get_session
from contextsmith_shared.embeddings import DEFAULT_EMBEDDING_MODEL, DEFAULT_EMBEDDING_PROVIDER
from contextsmith_shared.lifecycle import compute_next_refresh_at
from contextsmith_shared.models import (
    AgentProfile,
    ApiToken,
    AuditEvent,
    ContextPacket,
    ContextPacketItem,
    GraphEdge,
    GraphNode,
    IndexRun,
    Project,
    ProjectMembership,
    QueryRun,
    Resource,
    RetrievalHit,
    SourceSnapshot,
    Workspace,
    WorkspaceMembership,
)

app = FastAPI(title="ContextSmith API", version="0.1.0")

ALLOWED_TOKEN_SCOPES = {
    "project:read",
    "project:query",
    "resource:read",
    "resource:write",
    "resource:refresh",
    "review:read",
    "review:write",
    "token:admin",
}
ACTIVE_INDEX_STATUSES = {"enqueueing", "queued", "running"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:13000", "http://127.0.0.1:13000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def run_migrations_if_requested() -> None:
    if os.getenv("CONTEXTSMITH_AUTO_MIGRATE", "false").lower() == "true":
        subprocess.run(["alembic", "upgrade", "head"], check=True)


@app.on_event("startup")
def on_startup() -> None:
    run_migrations_if_requested()


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz(session: Session = Depends(get_session)) -> dict[str, str]:
    session.execute(text("select 1"))
    Redis.from_url(get_settings().redis_url).ping()
    return {"status": "ready"}


def _resolve_project(session: Session, workspace_id: UUID, project_id: UUID) -> Project:
    project = session.scalar(
        select(Project).where(Project.id == project_id, Project.workspace_id == workspace_id)
    )
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _ensure_agent_profile(
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


def _agent_profile_read(session: Session, workspace_id: UUID, project: Project, profile: AgentProfile) -> AgentProfileRead:
    stats = session.execute(
        text(
            """
            SELECT
              COUNT(DISTINCT r.id) AS resource_count,
              COUNT(DISTINCT r.current_snapshot_id) FILTER (WHERE r.current_snapshot_id IS NOT NULL) AS current_snapshot_count,
              COUNT(DISTINCT gn.id) AS graph_node_count,
              COUNT(DISTINCT ge.id) AS graph_edge_count,
              MAX(ir.finished_at) AS last_index_finished_at
            FROM projects p
            LEFT JOIN resources r ON r.project_id = p.id
              AND r.workspace_id = p.workspace_id
              AND r.deleted_at IS NULL
            LEFT JOIN graph_nodes gn ON gn.project_id = p.id
              AND gn.workspace_id = p.workspace_id
              AND gn.source_snapshot_id = r.current_snapshot_id
            LEFT JOIN graph_edges ge ON ge.project_id = p.id
              AND ge.workspace_id = p.workspace_id
              AND ge.source_snapshot_id = r.current_snapshot_id
            LEFT JOIN index_runs ir ON ir.project_id = p.id
              AND ir.workspace_id = p.workspace_id
              AND ir.status = 'succeeded'
            WHERE p.workspace_id = :ws AND p.id = :proj
            GROUP BY p.id
            """
        ),
        {"ws": workspace_id, "proj": project.id},
    ).mappings().first() or {}
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


def _require_project_access(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal) -> Project:
    """Resolve a project and enforce visibility/membership plus token project scope."""
    require_workspace_member(session, workspace_id, principal)
    if not token_allows_project(principal, project_id):
        raise HTTPException(status_code=404, detail="project not found")
    project = _resolve_project(session, workspace_id, project_id)
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


def _require_project_member(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal) -> Project:
    """Resolve a project and require explicit project membership plus token project scope for mutations."""
    require_workspace_member(session, workspace_id, principal)
    if not token_allows_project(principal, project_id):
        raise HTTPException(status_code=404, detail="project not found")
    project = _resolve_project(session, workspace_id, project_id)
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


def _resolve_resource(
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


def _purge_resource_artifacts(session: Session, resource: Resource) -> dict[str, int]:
    params = {"resource_id": resource.id}
    statements = [
        ("resources_current_snapshot", "UPDATE resources SET current_snapshot_id = NULL WHERE id = :resource_id"),
        ("context_packet_items", "DELETE FROM context_packet_items WHERE resource_id = :resource_id"),
        ("retrieval_hits", "DELETE FROM retrieval_hits WHERE resource_id = :resource_id"),
        ("chunk_embeddings", "DELETE FROM chunk_embeddings WHERE resource_id = :resource_id"),
        ("graph_edges", "DELETE FROM graph_edges WHERE resource_id = :resource_id"),
        ("graph_nodes", "DELETE FROM graph_nodes WHERE resource_id = :resource_id"),
        ("code_symbols", "DELETE FROM code_symbols WHERE resource_id = :resource_id"),
        ("chunks", "DELETE FROM chunks WHERE resource_id = :resource_id"),
        ("index_runs", "DELETE FROM index_runs WHERE resource_id = :resource_id"),
        ("source_snapshots", "DELETE FROM source_snapshots WHERE resource_id = :resource_id"),
    ]
    counts: dict[str, int] = {}
    for name, sql in statements:
        result = session.execute(text(sql), params)
        counts[name] = int(result.rowcount or 0)
    result = session.execute(text("DELETE FROM resources WHERE id = :resource_id"), params)
    counts["resources"] = int(result.rowcount or 0)
    return counts


def _require_workspace_admin(session: Session, workspace_id: UUID, principal: Principal) -> WorkspaceMembership:
    membership = require_workspace_member(session, workspace_id, principal)
    if membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="workspace admin role required")
    return membership


def _validate_token_scopes(scopes: list[str]) -> list[str]:
    normalized = sorted(set(scopes))
    invalid = sorted(set(normalized) - ALLOWED_TOKEN_SCOPES)
    if invalid:
        raise HTTPException(status_code=422, detail=f"invalid token scopes: {', '.join(invalid)}")
    if not normalized:
        raise HTTPException(status_code=422, detail="token scopes cannot be empty")
    return normalized


def _api_token_read(token: ApiToken) -> ApiTokenRead:
    return ApiTokenRead(
        id=token.id,
        workspace_id=token.workspace_id,
        name=token.name,
        scopes=list(token.scopes or []),
        allowed_project_ids=token.allowed_project_ids,
        allowed_resource_ids=token.allowed_resource_ids,
        created_by=token.created_by,
        expires_at=token.expires_at,
        last_used_at=token.last_used_at,
        revoked_at=token.revoked_at,
        created_at=token.created_at,
    )


def _require_requested_resources_allowed(principal: Principal, resource_ids: list[UUID] | None) -> None:
    if not resource_ids:
        return
    denied = [resource_id for resource_id in resource_ids if not token_allows_resource(principal, resource_id)]
    if denied:
        raise HTTPException(status_code=404, detail="resource not found")


def _effective_resource_ids(principal: Principal, resource_ids: list[UUID] | None) -> list[UUID] | None:
    token = principal.api_token
    requested = resource_ids or None
    if token is None or token.allowed_resource_ids is None:
        _require_requested_resources_allowed(principal, requested)
        return requested
    if requested is None:
        return list(token.allowed_resource_ids)
    _require_requested_resources_allowed(principal, requested)
    return requested


@app.post("/workspaces", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Workspace:
    if principal.is_token:
        raise HTTPException(status_code=403, detail="workspace creation requires user authentication")
    user = principal.user
    workspace = Workspace(name=payload.name, slug=payload.slug)
    session.add(workspace)
    session.flush()
    session.add(WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role="owner"))
    session.add(
        AuditEvent(
            workspace_id=workspace.id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="workspace.create",
            target_type="workspace",
            target_id=workspace.id,
        )
    )
    session.commit()
    return workspace


@app.get("/workspaces/{workspace_id}", response_model=WorkspaceRead)
def get_workspace(
    workspace_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Workspace:
    require_scope(principal, "project:read")
    require_workspace_member(session, workspace_id, principal)
    workspace = session.get(Workspace, workspace_id)
    if workspace is None or workspace.deleted_at is not None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return workspace


@app.post("/workspaces/{workspace_id}/api-tokens", response_model=ApiTokenCreateResponse, status_code=201)
def create_api_token(
    workspace_id: UUID,
    payload: ApiTokenCreate,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ApiTokenCreateResponse:
    if principal.is_token:
        raise HTTPException(status_code=403, detail="token creation requires user authentication")
    require_scope(principal, "token:admin")
    _require_workspace_admin(session, workspace_id, principal)
    scopes = _validate_token_scopes(payload.scopes)
    for project_id in payload.allowed_project_ids or []:
        _require_project_access(session, workspace_id, project_id, principal)
    for resource_id in payload.allowed_resource_ids or []:
        resource = session.get(Resource, resource_id)
        if resource is None or resource.workspace_id != workspace_id or resource.deleted_at is not None:
            raise HTTPException(status_code=404, detail="resource not found")
        _require_project_access(session, workspace_id, resource.project_id, principal)
    plaintext = new_plaintext_token()
    token = ApiToken(
        workspace_id=workspace_id,
        name=payload.name,
        token_hash=hash_token(plaintext),
        scopes=scopes,
        allowed_project_ids=payload.allowed_project_ids,
        allowed_resource_ids=payload.allowed_resource_ids,
        created_by=principal.user.id,
        expires_at=payload.expires_at,
    )
    session.add(token)
    session.flush()
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=principal.user.id,
            actor_token_id=principal.token_id,
            action="api_token.create",
            target_type="api_token",
            target_id=token.id,
            meta={"scopes": scopes, "name": payload.name},
        )
    )
    session.commit()
    return ApiTokenCreateResponse(token=plaintext, api_token=_api_token_read(token))


@app.get("/workspaces/{workspace_id}/api-tokens", response_model=list[ApiTokenRead])
def list_api_tokens(
    workspace_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> list[ApiTokenRead]:
    require_scope(principal, "token:admin")
    _require_workspace_admin(session, workspace_id, principal)
    tokens = list(
        session.scalars(
            select(ApiToken)
            .where(ApiToken.workspace_id == workspace_id)
            .order_by(ApiToken.created_at.asc())
        )
    )
    return [_api_token_read(token) for token in tokens]


@app.delete("/workspaces/{workspace_id}/api-tokens/{token_id}", response_model=ApiTokenRead)
def revoke_api_token(
    workspace_id: UUID,
    token_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ApiTokenRead:
    require_scope(principal, "token:admin")
    _require_workspace_admin(session, workspace_id, principal)
    token = session.scalar(select(ApiToken).where(ApiToken.workspace_id == workspace_id, ApiToken.id == token_id))
    if token is None:
        raise HTTPException(status_code=404, detail="token not found")
    if token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=principal.user.id,
            actor_token_id=principal.token_id,
            action="api_token.revoke",
            target_type="api_token",
            target_id=token.id,
            meta={"name": token.name},
        )
    )
    session.commit()
    return _api_token_read(token)


@app.post("/workspaces/{workspace_id}/projects", response_model=ProjectRead, status_code=201)
def create_project(
    workspace_id: UUID,
    payload: ProjectCreate,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Project:
    if principal.is_token:
        raise HTTPException(status_code=403, detail="project creation requires user authentication")
    user = principal.user
    require_scope(principal, "token:admin")
    _require_workspace_admin(session, workspace_id, principal)
    project = Project(
        workspace_id=workspace_id,
        name=payload.name,
        description=payload.description,
        created_by=user.id,
    )
    session.add(project)
    session.flush()
    _ensure_agent_profile(session, workspace_id, project, user.id)
    session.add(
        ProjectMembership(
            workspace_id=workspace_id,
            project_id=project.id,
            user_id=user.id,
            role="owner",
        )
    )
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="project.create",
            target_type="project",
            target_id=project.id,
        )
    )
    session.commit()
    return project


@app.get("/workspaces/{workspace_id}/projects/{project_id}", response_model=ProjectRead)
def get_project(
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Project:
    require_scope(principal, "project:read")
    return _require_project_access(session, workspace_id, project_id, principal)


@app.get("/workspaces/{workspace_id}/agents", response_model=list[AgentProfileRead])
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
            _require_project_access(session, workspace_id, project.id, principal)
        except HTTPException:
            continue
        profile = _ensure_agent_profile(session, workspace_id, project, user.id)
        agents.append(_agent_profile_read(session, workspace_id, project, profile))
    session.commit()
    return agents


@app.get("/workspaces/{workspace_id}/projects/{project_id}/agent-profile", response_model=AgentProfileRead)
def get_agent_profile(
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> AgentProfileRead:
    user = principal.user
    require_scope(principal, "project:read")
    project = _require_project_access(session, workspace_id, project_id, principal)
    profile = _ensure_agent_profile(session, workspace_id, project, user.id)
    session.commit()
    return _agent_profile_read(session, workspace_id, project, profile)


@app.patch("/workspaces/{workspace_id}/projects/{project_id}/agent-profile", response_model=AgentProfileRead)
def update_agent_profile(
    workspace_id: UUID,
    project_id: UUID,
    payload: AgentProfileUpdate,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> AgentProfileRead:
    user = principal.user
    require_scope(principal, "token:admin")
    project = _require_project_member(session, workspace_id, project_id, principal)
    profile = _ensure_agent_profile(session, workspace_id, project, user.id)
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
    return _agent_profile_read(session, workspace_id, project, profile)


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/resources",
    response_model=ResourceRead,
    status_code=201,
)
def create_resource(
    workspace_id: UUID,
    project_id: UUID,
    payload: ResourceCreate,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Resource:
    user = principal.user
    require_scope(principal, "resource:write")
    if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
        raise HTTPException(status_code=403, detail="resource-scoped tokens cannot create new resources")
    _require_project_member(session, workspace_id, project_id, principal)
    resource = Resource(
        workspace_id=workspace_id,
        project_id=project_id,
        type=payload.type,
        name=payload.name,
        uri=payload.uri,
        update_frequency=payload.update_frequency,
        source_config=payload.source_config,
        created_by=user.id,
    )
    session.add(resource)
    session.flush()
    resource.next_refresh_at = compute_next_refresh_at(resource)
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="resource.create",
            target_type="resource",
            target_id=resource.id,
        )
    )
    session.commit()
    return resource


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}",
    response_model=ResourceRead,
)
def get_resource(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Resource:
    require_scope(principal, "resource:read")
    _require_project_access(session, workspace_id, project_id, principal)
    return _resolve_resource(session, workspace_id, project_id, resource_id, principal)


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/refresh",
    response_model=IndexRunRead,
    status_code=202,
)
def refresh_resource(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    fail: bool = Query(default=False),
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> IndexRun:
    user = principal.user
    require_scope(principal, "resource:refresh")
    _require_project_member(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    run = IndexRun(
        workspace_id=workspace_id,
        project_id=project_id,
        resource_id=resource_id,
        trigger="manual",
        status="enqueueing",
        meta={"fail": fail},
    )
    session.add(run)
    session.flush()
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="resource.refresh",
            target_type="resource",
            target_id=resource.id,
            meta={"index_run_id": str(run.id)},
        )
    )
    session.commit()
    queue = Queue("default", connection=Redis.from_url(get_settings().redis_url))
    try:
        queue.enqueue("contextsmith_worker.jobs.run_index", str(run.id), job_timeout=600)
    except Exception as exc:
        run.status = "failed"
        run.error_message = f"failed to enqueue index job: {exc}"[:1000]
        session.add(run)
        session.commit()
        raise HTTPException(status_code=503, detail="failed to enqueue index job") from exc
    run.status = "queued"
    session.add(run)
    session.commit()
    return run


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/scheduled-refreshes",
    response_model=DueRefreshResponse,
    status_code=202,
)
def enqueue_scheduled_refreshes(
    workspace_id: UUID,
    project_id: UUID,
    dry_run: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> DueRefreshResponse:
    require_scope(principal, "resource:refresh")
    _require_project_member(session, workspace_id, project_id, principal)
    allowed_resource_ids = principal.api_token.allowed_resource_ids if principal.api_token is not None else None
    if allowed_resource_ids is not None:
        allowed = list(allowed_resource_ids)
    else:
        allowed = None
    from contextsmith_worker.maintenance import enqueue_due_refreshes

    result = enqueue_due_refreshes(
        workspace_id=workspace_id,
        project_id=project_id,
        resource_ids=allowed,
        limit=limit,
        dry_run=dry_run,
    )
    if not dry_run:
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="resource.scheduled_refresh",
                target_type="project",
                target_id=project_id,
                meta=result,
            )
        )
        session.commit()
    return DueRefreshResponse.model_validate(result)


@app.get("/workspaces/{workspace_id}/audit-events", response_model=list[AuditEventRead])
def list_audit_events(
    workspace_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> list[AuditEventRead]:
    require_scope(principal, "token:admin")
    require_workspace_member(session, workspace_id, principal)
    events = list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.workspace_id == workspace_id)
            .order_by(AuditEvent.created_at.asc())
        )
    )
    return [
        AuditEventRead(
            id=event.id,
            workspace_id=event.workspace_id,
            actor_user_id=event.actor_user_id,
            actor_token_id=event.actor_token_id,
            action=event.action,
            target_type=event.target_type,
            target_id=event.target_id,
            target_ref=event.target_ref,
            metadata=event.meta,
            created_at=event.created_at,
        )
        for event in events
    ]


@app.get("/workspaces/{workspace_id}/index-runs/{index_run_id}", response_model=IndexRunRead)
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
    _require_project_access(session, workspace_id, run.project_id, principal)
    return run


@app.patch(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}",
    response_model=ResourceRead,
)
def update_resource(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    payload: ResourceUpdate,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Resource:
    user = principal.user
    require_scope(principal, "resource:write")
    _require_project_member(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    fields = payload.model_dump(exclude_unset=True)
    if resource.archived_at is not None and fields.get("retrieval_enabled") is True:
        raise HTTPException(status_code=409, detail="archived resources cannot be re-enabled")
    nullable_rejected = {"name", "uri", "update_frequency", "source_config"}
    for key, value in fields.items():
        if key in nullable_rejected and value is None:
            raise HTTPException(status_code=422, detail=f"{key} cannot be null")
        setattr(resource, key, value)
    if "update_frequency" in fields or "source_config" in fields:
        resource.next_refresh_at = compute_next_refresh_at(resource)
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="resource.update",
            target_type="resource",
            target_id=resource.id,
            meta={"fields": sorted(fields.keys())},
        )
    )
    session.commit()
    return resource


@app.delete(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}",
    status_code=204,
)
def delete_resource(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> None:
    user = principal.user
    require_scope(principal, "resource:write")
    _require_project_member(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    now = datetime.now(UTC)
    previous = {
        "status": resource.status,
        "retrieval_enabled": resource.retrieval_enabled,
        "archived_at": resource.archived_at.isoformat() if resource.archived_at else None,
    }
    resource.deleted_at = now
    resource.retrieval_enabled = False
    resource.status = "deleted"
    resource.archived_at = resource.archived_at or now
    resource.next_refresh_at = None
    new = {
        "status": resource.status,
        "retrieval_enabled": resource.retrieval_enabled,
        "archived_at": resource.archived_at.isoformat() if resource.archived_at else None,
        "deleted_at": resource.deleted_at.isoformat() if resource.deleted_at else None,
    }
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="resource.delete",
            target_type="resource",
            target_id=resource.id,
            meta={"previous": previous, "new": new, "deleted_at": now.isoformat()},
        )
    )
    session.commit()
    return None


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/archive",
    response_model=ResourceRead,
)
def archive_resource(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Resource:
    user = principal.user
    require_scope(principal, "resource:write")
    _require_project_member(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    now = datetime.now(UTC)
    previous = {
        "status": resource.status,
        "retrieval_enabled": resource.retrieval_enabled,
        "archived_at": resource.archived_at.isoformat() if resource.archived_at else None,
    }
    resource.archived_at = now
    resource.status = "archived"
    resource.retrieval_enabled = False
    resource.next_refresh_at = None
    new = {
        "status": resource.status,
        "retrieval_enabled": resource.retrieval_enabled,
        "archived_at": resource.archived_at.isoformat() if resource.archived_at else None,
    }
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="resource.archive",
            target_type="resource",
            target_id=resource.id,
            meta={"previous": previous, "new": new, "archived_at": now.isoformat()},
        )
    )
    session.commit()
    return resource


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/restore",
    response_model=ResourceRead,
)
def restore_resource(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Resource:
    user = principal.user
    require_scope(principal, "resource:write")
    _require_project_member(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal, include_deleted=True)
    if resource.deleted_at is None and resource.archived_at is None and resource.status not in {"deleted", "archived"}:
        raise HTTPException(status_code=409, detail="resource is not archived or deleted")
    previous = {
        "status": resource.status,
        "retrieval_enabled": resource.retrieval_enabled,
        "archived_at": resource.archived_at.isoformat() if resource.archived_at else None,
        "deleted_at": resource.deleted_at.isoformat() if resource.deleted_at else None,
    }
    resource.deleted_at = None
    resource.archived_at = None
    resource.status = "active"
    resource.retrieval_enabled = True
    resource.next_refresh_at = compute_next_refresh_at(resource)
    new = {
        "status": resource.status,
        "retrieval_enabled": resource.retrieval_enabled,
        "archived_at": None,
        "deleted_at": None,
        "next_refresh_at": resource.next_refresh_at.isoformat() if resource.next_refresh_at else None,
    }
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="resource.restore",
            target_type="resource",
            target_id=resource.id,
            meta={"previous": previous, "new": new},
        )
    )
    session.commit()
    return resource


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/purge",
    response_model=PurgeResourceResponse,
)
def purge_resource(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> PurgeResourceResponse:
    user = principal.user
    require_scope(principal, "resource:write")
    _require_project_member(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal, include_deleted=True)
    if resource.deleted_at is None and resource.status != "deleted":
        raise HTTPException(status_code=409, detail="resource must be soft-deleted before purge")
    active_run = session.scalar(
        select(IndexRun.id)
        .where(
            IndexRun.workspace_id == workspace_id,
            IndexRun.project_id == project_id,
            IndexRun.resource_id == resource_id,
            IndexRun.status.in_(ACTIVE_INDEX_STATUSES),
        )
        .limit(1)
    )
    if active_run is not None:
        raise HTTPException(status_code=409, detail="resource has an active index run")
    previous = {
        "status": resource.status,
        "retrieval_enabled": resource.retrieval_enabled,
        "archived_at": resource.archived_at.isoformat() if resource.archived_at else None,
        "deleted_at": resource.deleted_at.isoformat() if resource.deleted_at else None,
    }
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="resource.purge",
            target_type="resource",
            target_id=resource.id,
            meta={"previous": previous},
        )
    )
    session.flush()
    counts = _purge_resource_artifacts(session, resource)
    session.commit()
    return PurgeResourceResponse(resource_id=resource_id, purged=counts.get("resources", 0) == 1, counts=counts)


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/review",
    response_model=ResourceRead,
)
def review_resource(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    payload: ResourceReviewRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Resource:
    user = principal.user
    require_scope(principal, "review:write")
    _require_project_member(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    if resource.archived_at is not None and payload.retrieval_enabled is True:
        raise HTTPException(status_code=409, detail="archived resources cannot be re-enabled")
    previous = {
        "review_status": resource.review_status,
        "review_note": resource.review_note,
        "retrieval_enabled": resource.retrieval_enabled,
        "stale_after_days": resource.stale_after_days,
    }
    resource.review_status = payload.review_status
    resource.review_note = payload.review_note
    resource.last_reviewed_at = datetime.now(UTC)
    resource.last_reviewed_by = user.id
    if payload.retrieval_enabled is not None:
        resource.retrieval_enabled = payload.retrieval_enabled
    if payload.stale_after_days is not None:
        resource.stale_after_days = payload.stale_after_days
    new = {
        "review_status": resource.review_status,
        "review_note": resource.review_note,
        "retrieval_enabled": resource.retrieval_enabled,
        "stale_after_days": resource.stale_after_days,
        "last_reviewed_at": resource.last_reviewed_at.isoformat() if resource.last_reviewed_at else None,
        "last_reviewed_by": str(resource.last_reviewed_by) if resource.last_reviewed_by else None,
    }
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="resource.review",
            target_type="resource",
            target_id=resource.id,
            meta={
                "previous": previous,
                "new": new,
                "review_status": payload.review_status,
                "review_note": payload.review_note,
                "retrieval_enabled": payload.retrieval_enabled,
                "stale_after_days": payload.stale_after_days,
            },
        )
    )
    session.commit()
    return resource


def _resource_review_item(session: Session, resource: Resource) -> ResourceReviewItem:
    usage = session.execute(
        text(
            """
            SELECT COUNT(*) AS hit_count, MAX(created_at) AS last_used_at
            FROM retrieval_hits
            WHERE workspace_id = :ws AND project_id = :proj AND resource_id = :res
            """
        ),
        {"ws": resource.workspace_id, "proj": resource.project_id, "res": resource.id},
    ).mappings().one()
    last_index = session.execute(
        text(
            """
            SELECT status, finished_at
            FROM index_runs
            WHERE workspace_id = :ws AND project_id = :proj AND resource_id = :res
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"ws": resource.workspace_id, "proj": resource.project_id, "res": resource.id},
    ).mappings().first()
    now = datetime.now(UTC)
    age_days = None
    reasons: list[str] = []
    freshness_status = "fresh"
    if resource.archived_at is not None:
        freshness_status = "archived"
        reasons.append("archived")
    elif resource.current_snapshot_id is None:
        freshness_status = "stale"
        reasons.append("no_current_snapshot")
    else:
        base = resource.last_refresh_finished_at or resource.created_at
        if base is not None:
            if base.tzinfo is None:
                base = base.replace(tzinfo=UTC)
            age_days = max(0, (now - base).days)
            if age_days > resource.stale_after_days:
                freshness_status = "stale"
                reasons.append("refresh_age_exceeded")
        if resource.review_status in {"stale", "needs_update"}:
            freshness_status = "stale"
            reasons.append(f"review_status:{resource.review_status}")
    return ResourceReviewItem(
        resource=ResourceRead.model_validate(resource, from_attributes=True),
        freshness_status=freshness_status,
        freshness_age_days=age_days,
        usage_count=int(usage["hit_count"] or 0),
        last_used_at=usage["last_used_at"],
        last_index_status=last_index["status"] if last_index else None,
        last_index_finished_at=last_index["finished_at"] if last_index else None,
        stale_reasons=reasons,
    )


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resource-review",
    response_model=ResourceReviewResponse,
)
def list_resource_review(
    workspace_id: UUID,
    project_id: UUID,
    include_archived: bool = Query(default=False),
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ResourceReviewResponse:
    require_scope(principal, "review:read")
    _require_project_access(session, workspace_id, project_id, principal)
    predicates = [
        Resource.workspace_id == workspace_id,
        Resource.project_id == project_id,
        Resource.deleted_at.is_(None),
    ]
    if not include_archived:
        predicates.append(Resource.archived_at.is_(None))
    if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
        predicates.append(Resource.id.in_(principal.api_token.allowed_resource_ids))
    resources = list(session.scalars(select(Resource).where(*predicates).order_by(Resource.created_at.asc())))
    items = [_resource_review_item(session, resource) for resource in resources]
    return ResourceReviewResponse(count=len(items), resources=items)


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resource-usage",
    response_model=ResourceUsageResponse,
)
def resource_usage(
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ResourceUsageResponse:
    require_scope(principal, "review:read")
    _require_project_access(session, workspace_id, project_id, principal)
    rows = session.execute(
        text(
            """
            SELECT r.id AS resource_id,
                   COUNT(DISTINCT rh.query_run_id) AS query_count,
                   COUNT(DISTINCT rh.id) AS hit_count,
                   COUNT(DISTINCT cpi.context_packet_id) AS context_packet_count,
                   MAX(rh.created_at) AS last_used_at
            FROM resources r
            LEFT JOIN retrieval_hits rh ON rh.resource_id = r.id
              AND rh.workspace_id = r.workspace_id
              AND rh.project_id = r.project_id
            LEFT JOIN context_packet_items cpi ON cpi.resource_id = r.id
              AND cpi.workspace_id = r.workspace_id
              AND cpi.project_id = r.project_id
            WHERE r.workspace_id = :ws
              AND r.project_id = :proj
              AND r.deleted_at IS NULL
            GROUP BY r.id
            ORDER BY hit_count DESC, r.id ASC
            """
        ),
        {"ws": workspace_id, "proj": project_id},
    ).mappings().all()
    allowed_resource_ids = principal.api_token.allowed_resource_ids if principal.api_token is not None else None
    if allowed_resource_ids is not None:
        allowed = set(allowed_resource_ids)
        rows = [row for row in rows if row["resource_id"] in allowed]
    items = [
        ResourceUsageItem(
            resource_id=row["resource_id"],
            query_count=int(row["query_count"] or 0),
            hit_count=int(row["hit_count"] or 0),
            context_packet_count=int(row["context_packet_count"] or 0),
            last_used_at=row["last_used_at"],
        )
        for row in rows
    ]
    return ResourceUsageResponse(count=len(items), resources=items)


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resources",
    response_model=list[ResourceRead],
)
def list_resources(
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> list[Resource]:
    require_scope(principal, "resource:read")
    _require_project_access(session, workspace_id, project_id, principal)
    predicates = [
        Resource.workspace_id == workspace_id,
        Resource.project_id == project_id,
        Resource.deleted_at.is_(None),
    ]
    if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
        predicates.append(Resource.id.in_(principal.api_token.allowed_resource_ids))
    return list(
        session.scalars(
            select(Resource)
            .where(*predicates)
            .order_by(Resource.created_at.asc())
        )
    )


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/snapshots",
    response_model=list[SnapshotRead],
)
def list_snapshots(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> list[SnapshotRead]:
    require_scope(principal, "resource:read")
    _require_project_access(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    snapshots = session.scalars(
        select(SourceSnapshot)
        .where(
            SourceSnapshot.workspace_id == workspace_id,
            SourceSnapshot.resource_id == resource_id,
        )
        .order_by(SourceSnapshot.created_at.desc())
    )
    return [
        SnapshotRead(
            id=snapshot.id,
            workspace_id=snapshot.workspace_id,
            project_id=snapshot.project_id,
            resource_id=snapshot.resource_id,
            version=snapshot.version,
            version_kind=snapshot.version_kind,
            status=snapshot.status,
            metadata=snapshot.meta or {},
            fetched_at=snapshot.fetched_at,
            indexed_at=snapshot.indexed_at,
            created_at=snapshot.created_at,
            is_current=snapshot.id == resource.current_snapshot_id,
        )
        for snapshot in snapshots
    ]


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/graph",
    response_model=GraphRead,
)
def get_resource_graph(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    limit: int = Query(default=200, ge=1, le=1000),
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> GraphRead:
    require_scope(principal, "resource:read")
    _require_project_access(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    if resource.current_snapshot_id is None:
        return GraphRead(node_count=0, edge_count=0, nodes=[], edges=[])
    nodes = list(
        session.scalars(
            select(GraphNode)
            .where(
                GraphNode.workspace_id == workspace_id,
                GraphNode.project_id == project_id,
                GraphNode.resource_id == resource_id,
                GraphNode.source_snapshot_id == resource.current_snapshot_id,
            )
            .order_by(GraphNode.node_type.asc(), GraphNode.label.asc())
            .limit(limit)
        )
    )
    edges = list(
        session.scalars(
            select(GraphEdge)
            .where(
                GraphEdge.workspace_id == workspace_id,
                GraphEdge.project_id == project_id,
                GraphEdge.resource_id == resource_id,
                GraphEdge.source_snapshot_id == resource.current_snapshot_id,
            )
            .order_by(GraphEdge.edge_type.asc(), GraphEdge.created_at.asc())
            .limit(limit)
        )
    )
    return GraphRead(
        node_count=len(nodes),
        edge_count=len(edges),
        nodes=[
            GraphNodeRead(
                id=node.id,
                resource_id=node.resource_id,
                snapshot_id=node.source_snapshot_id,
                node_key=node.node_key,
                node_type=node.node_type,
                label=node.label,
                path=node.path,
                metadata=node.meta,
            )
            for node in nodes
        ],
        edges=[
            GraphEdgeRead(
                id=edge.id,
                resource_id=edge.resource_id,
                snapshot_id=edge.source_snapshot_id,
                source_node_id=edge.source_node_id,
                target_node_id=edge.target_node_id,
                edge_type=edge.edge_type,
                weight=edge.weight,
                metadata=edge.meta,
            )
            for edge in edges
        ],
    )


@app.get(
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
    _require_project_access(session, workspace_id, project_id, principal)
    _resolve_resource(session, workspace_id, project_id, resource_id, principal)
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


def _make_snippet(content: str, limit: int = 320) -> str:
    collapsed = " ".join(content.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + "…"


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/search",
    response_model=SearchResponse,
)
def search_project(
    workspace_id: UUID,
    project_id: UUID,
    payload: SearchRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> SearchResponse:
    require_scope(principal, "project:query")
    resource_ids = _effective_resource_ids(principal, payload.resource_ids)
    _require_project_access(session, workspace_id, project_id, principal)

    resource_clause = ""
    params: dict = {
        "ws": str(workspace_id),
        "proj": str(project_id),
        "q": payload.query,
        "k": payload.top_k,
    }
    if resource_ids:
        resource_clause = "AND r.id = ANY(CAST(:rids AS uuid[]))"
        params["rids"] = [str(rid) for rid in resource_ids]

    sql = text(
        f"""
        SELECT c.resource_id, c.source_snapshot_id, c.path, c.title, c.ordinal,
               c.content_hash, c.content,
               s.version, s.version_kind, s.metadata AS snap_meta,
               ts_rank(to_tsvector('english', c.content),
                       plainto_tsquery('english', :q)) AS score
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
          AND to_tsvector('english', c.content) @@ plainto_tsquery('english', :q)
        ORDER BY score DESC, c.resource_id, c.ordinal ASC
        LIMIT :k
        """
    )
    rows = session.execute(sql, params).mappings().all()
    hits = []
    for row in rows:
        snap_meta = row["snap_meta"] if isinstance(row["snap_meta"], dict) else {}
        hits.append(
            SearchHit(
                resource_id=row["resource_id"],
                snapshot_id=row["source_snapshot_id"],
                path=row["path"],
                title=row["title"],
                ordinal=row["ordinal"],
                content_hash=row["content_hash"],
                version=row["version"],
                version_kind=row["version_kind"],
                commit=snap_meta.get("commit"),
                snippet=_make_snippet(row["content"]),
                score=float(row["score"]),
            )
        )
    return SearchResponse(query=payload.query, count=len(hits), hits=hits)


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/code-search",
    response_model=CodeSearchResponse,
)
def code_search_project(
    workspace_id: UUID,
    project_id: UUID,
    payload: CodeSearchRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> CodeSearchResponse:
    """Search extracted code symbols with file/line/commit citations.

    This endpoint returns deterministic source-derived symbols only. It does not
    infer call edges or behavior with an LLM.
    """
    require_scope(principal, "project:query")
    resource_ids = _effective_resource_ids(principal, payload.resource_ids)
    _require_project_access(session, workspace_id, project_id, principal)
    resource_clause = ""
    params: dict = {
        "ws": str(workspace_id),
        "proj": str(project_id),
        "q": payload.query,
        "limit": payload.limit,
    }
    if resource_ids:
        resource_clause = "AND r.id = ANY(CAST(:rids AS uuid[]))"
        params["rids"] = [str(rid) for rid in resource_ids]
    rows = session.execute(
        text(
            f"""
            SELECT sym.resource_id, sym.source_snapshot_id, sym.path, sym.name,
                   sym.kind, sym.language, sym.line_start, sym.line_end,
                   sym.signature, sym.content_hash,
                   snap.version, snap.version_kind, snap.metadata AS snap_meta,
                   ts_rank(
                     to_tsvector('simple', sym.name || ' ' || sym.path || ' ' || sym.signature),
                     plainto_tsquery('simple', :q)
                   ) AS score
            FROM code_symbols sym
            JOIN resources r ON r.current_snapshot_id = sym.source_snapshot_id
              AND r.id = sym.resource_id
              AND r.workspace_id = sym.workspace_id
              AND r.project_id = sym.project_id
            JOIN source_snapshots snap ON snap.id = sym.source_snapshot_id
              AND snap.workspace_id = sym.workspace_id
              AND snap.project_id = sym.project_id
              AND snap.resource_id = sym.resource_id
            WHERE sym.workspace_id = CAST(:ws AS uuid)
              AND sym.project_id = CAST(:proj AS uuid)
              AND sym.deleted_at IS NULL
              AND r.deleted_at IS NULL
              AND r.archived_at IS NULL
              AND r.retrieval_enabled = true
              AND r.current_snapshot_id IS NOT NULL
              {resource_clause}
              AND to_tsvector('simple', sym.name || ' ' || sym.path || ' ' || sym.signature)
                  @@ plainto_tsquery('simple', :q)
            ORDER BY score DESC, sym.path ASC, sym.line_start ASC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    symbols: list[CodeSymbolHit] = []
    for row in rows:
        snap_meta = row["snap_meta"] if isinstance(row["snap_meta"], dict) else {}
        symbols.append(
            CodeSymbolHit(
                resource_id=row["resource_id"],
                snapshot_id=row["source_snapshot_id"],
                path=row["path"],
                name=row["name"],
                kind=row["kind"],
                language=row["language"],
                line_start=row["line_start"],
                line_end=row["line_end"],
                signature=row["signature"],
                content_hash=row["content_hash"],
                version=row["version"],
                version_kind=row["version_kind"],
                commit=snap_meta.get("commit"),
                score=float(row["score"] or 0.0),
            )
        )
    return CodeSearchResponse(query=payload.query, count=len(symbols), symbols=symbols)


_COMMON_AGENT_INSTRUCTION = (
    "ContextSmith is a read-only context provider. Use only cited project context for factual claims, "
    "do not treat this packet as authorization for production mutations, and preserve external approval/MCP boundaries."
)

_RUNTIME_INSTRUCTIONS = {
    "api": "If evidence is insufficient, say what is missing.",
    "hermes": "You are a Hermes specialist agent. Keep production discipline explicit.",
    "claude": "Use this packet as project context. Prefer cited evidence over prior assumptions and ask for missing runtime state when needed.",
    "codex": "Use this packet as repository context. Do not edit files unless the caller explicitly asks; cite paths and snapshots when explaining.",
    "cursor": "Use this packet for editor assistance. Prefer precise file/path citations and avoid broad rewrites without evidence.",
}


def _build_agent_context_response(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    payload: AgentContextRequest,
    principal: Principal,
) -> AgentContextResponse:
    candidates = retrieve_context_candidates(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        query=payload.query,
        top_k=payload.top_k,
        resource_ids=payload.resource_ids,
    )
    citations: list[AgentContextCitation] = []
    context_parts: list[str] = []
    used_chars = 0
    for rank, candidate in enumerate(candidates, start=1):
        header = (
            f"[{rank}] resource={candidate.resource_id} snapshot={candidate.snapshot_id} "
            f"path={candidate.path or '-'} ordinal={candidate.ordinal} score={candidate.score:.4f}\n"
        )
        remaining = payload.max_chars - used_chars - (2 if context_parts else 0)
        if remaining <= len(header):
            break
        snippet = make_snippet(candidate.content, limit=min(1200, max(120, remaining - len(header))))
        entry = header + snippet
        if len(entry) > remaining:
            entry = entry[:remaining]
        if not entry.strip():
            break
        context_parts.append(entry)
        used_chars += len(entry) + (2 if len(context_parts) > 1 else 0)
        citations.append(
            AgentContextCitation(
                resource_id=candidate.resource_id,
                snapshot_id=candidate.snapshot_id,
                chunk_id=candidate.chunk_id,
                path=candidate.path,
                title=candidate.title,
                ordinal=candidate.ordinal,
                version=candidate.version,
                version_kind=candidate.version_kind,
                commit=candidate.snapshot_metadata.get("commit"),
                score=candidate.score,
                graph_score=candidate.graph_score,
            )
        )
    symbols: list[CodeSymbolHit] = []
    if payload.include_code_symbols:
        symbol_response = code_search_project(
            workspace_id=workspace_id,
            project_id=project_id,
            payload=CodeSearchRequest(query=payload.query, resource_ids=payload.resource_ids, limit=min(payload.top_k, 20)),
            principal=principal,
            session=session,
        )
        symbols = symbol_response.symbols
    profile = session.scalar(
        select(AgentProfile).where(
            AgentProfile.workspace_id == workspace_id,
            AgentProfile.project_id == project_id,
        )
    )
    actual_runtime = payload.runtime or (profile.default_runtime if profile else "api")
    instruction_parts = [_COMMON_AGENT_INSTRUCTION, _RUNTIME_INSTRUCTIONS[actual_runtime]]
    if profile and profile.system_prompt:
        instruction_parts.append(profile.system_prompt)
    return AgentContextResponse(
        query=payload.query,
        runtime=actual_runtime,
        instruction=" ".join(instruction_parts),
        context="\n\n".join(context_parts),
        citations=citations,
        symbols=symbols,
        token_budget_hint=max(1, payload.max_chars // 4),
    )


@app.post(
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
    resource_ids = _effective_resource_ids(principal, payload.resource_ids)
    payload = payload.model_copy(update={"resource_ids": resource_ids})
    _require_project_access(session, workspace_id, project_id, principal)
    return _build_agent_context_response(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        payload=payload,
        principal=principal,
    )


def _json_rpc_error(rpc_id: object | None, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


@app.post("/mcp/{workspace_id}/{project_id}", response_model=None)
async def mcp_endpoint(
    workspace_id: UUID,
    project_id: UUID,
    request: Request,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> dict | Response:
    """Minimal central MCP-compatible JSON-RPC endpoint for project context.

    This intentionally exposes one typed operation; production/external actions
    remain outside repo agents and must use dedicated MCP tools.
    """
    require_scope(principal, "project:query")
    _require_project_access(session, workspace_id, project_id, principal)
    try:
        body = await request.json()
    except Exception:
        return _json_rpc_error(None, -32700, "parse error")
    if not isinstance(body, dict):
        return _json_rpc_error(None, -32600, "invalid request")
    rpc_id = body.get("id")
    has_id = "id" in body
    if body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
        return _json_rpc_error(rpc_id if has_id else None, -32600, "invalid request")
    method = body["method"]
    if not has_id:
        # JSON-RPC notifications do not receive responses. MCP clients commonly
        # send notifications/initialized after initialize.
        return Response(status_code=204)
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "contextsmith", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            },
        }
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "tools": [
                    {
                        "name": "contextsmith.get_agent_context",
                        "description": "Return permission-scoped cited context for a ContextSmith project.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string"},
                                "runtime": {"type": "string", "enum": ["api", "hermes", "claude", "codex", "cursor"]},
                                "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
                                "resource_ids": {"type": "array", "items": {"type": "string"}},
                                "include_code_symbols": {"type": "boolean"},
                            },
                            "required": ["query"],
                        },
                    }
                ]
            },
        }
    if method == "tools/call":
        params = body.get("params", {})
        if not isinstance(params, dict):
            return _json_rpc_error(rpc_id, -32602, "invalid params")
        if params.get("name") != "contextsmith.get_agent_context":
            return _json_rpc_error(rpc_id, -32601, "unknown tool")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _json_rpc_error(rpc_id, -32602, "invalid params")
        try:
            payload = AgentContextRequest(**arguments)
        except ValidationError as exc:
            return _json_rpc_error(rpc_id, -32602, f"invalid params: {exc.errors()[0]['msg']}")
        try:
            resource_ids = _effective_resource_ids(principal, payload.resource_ids)
        except HTTPException:
            return _json_rpc_error(rpc_id, -32603, "resource not found")
        payload = payload.model_copy(update={"resource_ids": resource_ids})
        result = _build_agent_context_response(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            payload=payload,
            principal=principal,
        )
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "content": [{"type": "text", "text": result.model_dump_json()}],
                "structuredContent": result.model_dump(mode="json"),
            },
        }
    return _json_rpc_error(rpc_id, -32601, "method not found")


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/context-packets",
    response_model=ContextPacketRead,
    status_code=201,
)
def create_context_packet(
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
    resource_ids = _effective_resource_ids(principal, payload.resource_ids)
    payload = payload.model_copy(update={"resource_ids": resource_ids})
    _require_project_access(session, workspace_id, project_id, principal)

    query_run = QueryRun(
        workspace_id=workspace_id,
        project_id=project_id,
        actor_user_id=user.id,
        query=payload.query,
        mode=payload.mode,
        top_k=payload.top_k,
        provider=DEFAULT_EMBEDDING_PROVIDER,
        model=DEFAULT_EMBEDDING_MODEL,
        status="running",
        meta={"resource_ids": [str(rid) for rid in payload.resource_ids or []]},
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
        )
        packet = ContextPacket(
            workspace_id=workspace_id,
            project_id=project_id,
            query_run_id=query_run_id,
            status="succeeded",
            item_count=len(candidates),
            meta={"builder": "m3-hybrid-context-packet"},
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

        query_run = session.get(QueryRun, query_run_id)
        if query_run is None:
            raise RuntimeError("query_run disappeared during context packet build")
        query_run.status = "succeeded"
        query_run.hit_count = len(candidates)
        query_run.finished_at = datetime.now(UTC)
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
            provider=DEFAULT_EMBEDDING_PROVIDER,
            model=DEFAULT_EMBEDDING_MODEL,
            count=len(items),
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
