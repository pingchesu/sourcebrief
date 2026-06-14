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
    ResourceUpdate,
    SearchHit,
    SearchRequest,
    SearchResponse,
    SnapshotRead,
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
    SourceSnapshot,
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


def _resolve_project(session: Session, workspace_id: UUID, project_id: UUID) -> Project:
    project = session.scalar(
        select(Project).where(Project.id == project_id, Project.workspace_id == workspace_id)
    )
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _resolve_resource(
    session: Session, workspace_id: UUID, project_id: UUID, resource_id: UUID
) -> Resource:
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
    queue.enqueue("contextsmith_worker.jobs.run_index", str(run.id), job_timeout=600)
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


@app.patch(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}",
    response_model=ResourceRead,
)
def update_resource(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    payload: ResourceUpdate,
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Resource:
    user = get_or_create_user(session, email)
    require_workspace_member(session, workspace_id, user)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id)
    fields = payload.model_dump(exclude_unset=True)
    for key, value in fields.items():
        setattr(resource, key, value)
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            action="resource.update",
            target_type="resource",
            target_id=resource.id,
            meta={"fields": sorted(fields.keys())},
        )
    )
    session.commit()
    return resource


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resources",
    response_model=list[ResourceRead],
)
def list_resources(
    workspace_id: UUID,
    project_id: UUID,
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> list[Resource]:
    user = get_or_create_user(session, email)
    require_workspace_member(session, workspace_id, user)
    _resolve_project(session, workspace_id, project_id)
    return list(
        session.scalars(
            select(Resource)
            .where(
                Resource.workspace_id == workspace_id,
                Resource.project_id == project_id,
                Resource.deleted_at.is_(None),
            )
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
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> list[SnapshotRead]:
    user = get_or_create_user(session, email)
    require_workspace_member(session, workspace_id, user)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id)
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
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/index-runs",
    response_model=list[IndexRunRead],
)
def list_resource_index_runs(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> list[IndexRun]:
    user = get_or_create_user(session, email)
    require_workspace_member(session, workspace_id, user)
    _resolve_resource(session, workspace_id, project_id, resource_id)
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
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> SearchResponse:
    user = get_or_create_user(session, email)
    require_workspace_member(session, workspace_id, user)
    _resolve_project(session, workspace_id, project_id)

    resource_clause = ""
    params: dict = {
        "ws": str(workspace_id),
        "proj": str(project_id),
        "q": payload.query,
        "k": payload.top_k,
    }
    if payload.resource_ids:
        resource_clause = "AND r.id = ANY(CAST(:rids AS uuid[]))"
        params["rids"] = [str(rid) for rid in payload.resource_ids]

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
