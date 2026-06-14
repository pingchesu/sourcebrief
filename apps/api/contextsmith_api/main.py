from __future__ import annotations

import os
import subprocess
from datetime import UTC, datetime
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from redis import Redis
from rq import Queue
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from contextsmith_api.auth import get_or_create_user, require_principal, require_workspace_member
from contextsmith_api.retrieval import make_snippet, retrieve_context_candidates
from contextsmith_api.schemas import (
    AuditEventRead,
    CodeSearchRequest,
    CodeSearchResponse,
    CodeSymbolHit,
    ContextPacketItemRead,
    ContextPacketRead,
    ContextPacketRequest,
    IndexRunRead,
    ProjectCreate,
    ProjectRead,
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
from contextsmith_shared.models import (
    AuditEvent,
    ContextPacket,
    ContextPacketItem,
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


def _require_project_access(session: Session, workspace_id: UUID, project_id: UUID, user) -> Project:
    """Resolve a project and enforce visibility/membership for reads/search."""
    require_workspace_member(session, workspace_id, user)
    project = _resolve_project(session, workspace_id, project_id)
    if project.visibility in {"workspace", "public"}:
        return project
    membership = session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.workspace_id == workspace_id,
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _require_project_member(session: Session, workspace_id: UUID, project_id: UUID, user) -> Project:
    """Resolve a project and require explicit project membership for mutations."""
    require_workspace_member(session, workspace_id, user)
    project = _resolve_project(session, workspace_id, project_id)
    membership = session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.workspace_id == workspace_id,
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == user.id,
        )
    )
    if membership is None:
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
    return _require_project_access(session, workspace_id, project_id, user)


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
    _require_project_member(session, workspace_id, project_id, user)
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
    _require_project_access(session, workspace_id, project_id, user)
    return _resolve_resource(session, workspace_id, project_id, resource_id)


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
    _require_project_member(session, workspace_id, project_id, user)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id)
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


@app.get("/workspaces/{workspace_id}/audit-events", response_model=list[AuditEventRead])
def list_audit_events(
    workspace_id: UUID,
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> list[AuditEventRead]:
    user = get_or_create_user(session, email)
    require_workspace_member(session, workspace_id, user)
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
    _require_project_access(session, workspace_id, run.project_id, user)
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
    _require_project_member(session, workspace_id, project_id, user)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id)
    fields = payload.model_dump(exclude_unset=True)
    if resource.archived_at is not None and fields.get("retrieval_enabled") is True:
        raise HTTPException(status_code=409, detail="archived resources cannot be re-enabled")
    nullable_rejected = {"name", "uri", "update_frequency", "source_config"}
    for key, value in fields.items():
        if key in nullable_rejected and value is None:
            raise HTTPException(status_code=422, detail=f"{key} cannot be null")
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


@app.delete(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}",
    status_code=204,
)
def delete_resource(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> None:
    user = get_or_create_user(session, email)
    _require_project_member(session, workspace_id, project_id, user)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id)
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
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Resource:
    user = get_or_create_user(session, email)
    _require_project_member(session, workspace_id, project_id, user)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id)
    now = datetime.now(UTC)
    previous = {
        "status": resource.status,
        "retrieval_enabled": resource.retrieval_enabled,
        "archived_at": resource.archived_at.isoformat() if resource.archived_at else None,
    }
    resource.archived_at = now
    resource.status = "archived"
    resource.retrieval_enabled = False
    new = {
        "status": resource.status,
        "retrieval_enabled": resource.retrieval_enabled,
        "archived_at": resource.archived_at.isoformat() if resource.archived_at else None,
    }
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            action="resource.archive",
            target_type="resource",
            target_id=resource.id,
            meta={"previous": previous, "new": new, "archived_at": now.isoformat()},
        )
    )
    session.commit()
    return resource


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/review",
    response_model=ResourceRead,
)
def review_resource(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    payload: ResourceReviewRequest,
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Resource:
    user = get_or_create_user(session, email)
    _require_project_member(session, workspace_id, project_id, user)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id)
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
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ResourceReviewResponse:
    user = get_or_create_user(session, email)
    _require_project_access(session, workspace_id, project_id, user)
    predicates = [
        Resource.workspace_id == workspace_id,
        Resource.project_id == project_id,
        Resource.deleted_at.is_(None),
    ]
    if not include_archived:
        predicates.append(Resource.archived_at.is_(None))
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
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ResourceUsageResponse:
    user = get_or_create_user(session, email)
    _require_project_access(session, workspace_id, project_id, user)
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
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> list[Resource]:
    user = get_or_create_user(session, email)
    _require_project_access(session, workspace_id, project_id, user)
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
    _require_project_access(session, workspace_id, project_id, user)
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
    _require_project_access(session, workspace_id, project_id, user)
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
    _require_project_access(session, workspace_id, project_id, user)

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
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> CodeSearchResponse:
    """Search extracted code symbols with file/line/commit citations.

    This endpoint returns deterministic source-derived symbols only. It does not
    infer call edges or behavior with an LLM.
    """
    user = get_or_create_user(session, email)
    _require_project_access(session, workspace_id, project_id, user)
    resource_clause = ""
    params: dict = {
        "ws": str(workspace_id),
        "proj": str(project_id),
        "q": payload.query,
        "limit": payload.limit,
    }
    if payload.resource_ids:
        resource_clause = "AND r.id = ANY(CAST(:rids AS uuid[]))"
        params["rids"] = [str(rid) for rid in payload.resource_ids]
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


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/context-packets",
    response_model=ContextPacketRead,
    status_code=201,
)
def create_context_packet(
    workspace_id: UUID,
    project_id: UUID,
    payload: ContextPacketRequest,
    email: str = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ContextPacketRead:
    """Build a cited context packet through permission-scoped hybrid retrieval."""
    if payload.mode != "hybrid":
        raise HTTPException(status_code=422, detail="only hybrid context packets are supported")
    user = get_or_create_user(session, email)
    _require_project_access(session, workspace_id, project_id, user)

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
