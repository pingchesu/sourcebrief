from __future__ import annotations

import os
import subprocess
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, status
from redis import Redis
from rq import Queue
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from contextsmith_api.auth import get_or_create_user, require_principal, require_workspace_member
from contextsmith_api.schemas import (
    AuditEventRead,
    IndexRunRead,
    ProjectCreate,
    ProjectRead,
    ResourceCreate,
    ResourceRead,
    WorkspaceCreate,
    WorkspaceRead,
)
from contextsmith_shared.config import get_settings
from contextsmith_shared.db import get_session
from contextsmith_shared.models import (
    AuditEvent,
    IndexRun,
    Project,
    ProjectMembership,
    Resource,
    Workspace,
    WorkspaceMembership,
)

app = FastAPI(title="ContextSmith API", version="0.1.0")


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


@app.post("/workspaces", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate,
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Workspace:
    user = get_or_create_user(session, email)
    workspace = Workspace(name=payload.name, slug=payload.slug)
    session.add(workspace)
    session.flush()
    session.add(WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role="owner"))
    session.add(
        AuditEvent(
            workspace_id=workspace.id,
            actor_user_id=user.id,
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
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Workspace:
    user = get_or_create_user(session, email)
    require_workspace_member(session, workspace_id, user)
    workspace = session.get(Workspace, workspace_id)
    if workspace is None or workspace.deleted_at is not None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return workspace


@app.post("/workspaces/{workspace_id}/projects", response_model=ProjectRead, status_code=201)
def create_project(
    workspace_id: UUID,
    payload: ProjectCreate,
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Project:
    user = get_or_create_user(session, email)
    require_workspace_member(session, workspace_id, user)
    project = Project(
        workspace_id=workspace_id,
        name=payload.name,
        description=payload.description,
        created_by=user.id,
    )
    session.add(project)
    session.flush()
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
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Project:
    user = get_or_create_user(session, email)
    require_workspace_member(session, workspace_id, user)
    project = session.scalar(
        select(Project).where(Project.id == project_id, Project.workspace_id == workspace_id)
    )
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/resources",
    response_model=ResourceRead,
    status_code=201,
)
def create_resource(
    workspace_id: UUID,
    project_id: UUID,
    payload: ResourceCreate,
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Resource:
    user = get_or_create_user(session, email)
    require_workspace_member(session, workspace_id, user)
    project = session.scalar(
        select(Project).where(Project.id == project_id, Project.workspace_id == workspace_id)
    )
    if project is None:
        raise HTTPException(status_code=404, detail="project not found")
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
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
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
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Resource:
    user = get_or_create_user(session, email)
    require_workspace_member(session, workspace_id, user)
    resource = session.scalar(
        select(Resource).where(
            Resource.id == resource_id,
            Resource.project_id == project_id,
            Resource.workspace_id == workspace_id,
        )
    )
    if resource is None or resource.deleted_at is not None:
        raise HTTPException(status_code=404, detail="resource not found")
    return resource


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
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> IndexRun:
    user = get_or_create_user(session, email)
    require_workspace_member(session, workspace_id, user)
    resource = session.scalar(
        select(Resource).where(
            Resource.id == resource_id,
            Resource.project_id == project_id,
            Resource.workspace_id == workspace_id,
        )
    )
    if resource is None:
        raise HTTPException(status_code=404, detail="resource not found")
    run = IndexRun(
        workspace_id=workspace_id,
        project_id=project_id,
        resource_id=resource_id,
        trigger="manual",
        status="queued",
        meta={"fail": fail},
    )
    session.add(run)
    session.flush()
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            action="resource.refresh",
            target_type="resource",
            target_id=resource.id,
            meta={"index_run_id": str(run.id)},
        )
    )
    session.commit()
    queue = Queue("default", connection=Redis.from_url(get_settings().redis_url))
    queue.enqueue("contextsmith_worker.jobs.run_placeholder_index", str(run.id), job_timeout=120)
    return run


@app.get("/workspaces/{workspace_id}/audit-events", response_model=list[AuditEventRead])
def list_audit_events(
    workspace_id: UUID,
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> list[AuditEvent]:
    user = get_or_create_user(session, email)
    require_workspace_member(session, workspace_id, user)
    return list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.workspace_id == workspace_id)
            .order_by(AuditEvent.created_at.asc())
        )
    )


@app.get("/workspaces/{workspace_id}/index-runs/{index_run_id}", response_model=IndexRunRead)
def get_index_run(
    workspace_id: UUID,
    index_run_id: UUID,
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> IndexRun:
    user = get_or_create_user(session, email)
    require_workspace_member(session, workspace_id, user)
    run = session.scalar(
        select(IndexRun).where(IndexRun.workspace_id == workspace_id, IndexRun.id == index_run_id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="index run not found")
    return run
