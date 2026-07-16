from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal, require_principal, require_scope
from sourcebrief_api.constants import (
    ACTIVE_INDEX_STATUSES,
    FOLDER_BUNDLE_RESOURCE_TYPES,
    GIT_RESOURCE_TYPES,
    URL_RESOURCE_TYPES,
)
from sourcebrief_api.schemas import (
    PurgeResourceResponse,
    ResourceRead,
    ResourceReviewItem,
    ResourceReviewRequest,
    ResourceReviewResponse,
    ResourceUpdate,
    ResourceUsageItem,
    ResourceUsageResponse,
    SnapshotRead,
)
from sourcebrief_shared.db import get_session
from sourcebrief_shared.lifecycle import compute_next_refresh_at
from sourcebrief_shared.models import AuditEvent, IndexRun, Resource, SourceSnapshot
from sourcebrief_worker.ingestion import sanitize_remote_url

ProjectAccessAuthorizer = Callable[[Session, UUID, UUID, Principal], object]
ProjectMemberAuthorizer = Callable[..., object]
ResourceResolver = Callable[..., Resource]
ResourceReader = Callable[[Session, Resource, Principal], ResourceRead]
ResourceArtifactsPurger = Callable[[Session, Resource], dict[str, int]]
SourceConfigValidator = Callable[[str, str, dict], dict]


@dataclass(frozen=True)
class ResourceLifecycleRouterDeps:
    require_project_access: ProjectAccessAuthorizer
    require_project_member: ProjectMemberAuthorizer
    resolve_resource: ResourceResolver
    resource_read: ResourceReader
    purge_resource_artifacts: ResourceArtifactsPurger
    validate_source_config: SourceConfigValidator


def resource_review_item(session: Session, resource: Resource) -> ResourceReviewItem:
    usage = (
        session.execute(
            text(
                """
            SELECT COUNT(*) AS hit_count, MAX(created_at) AS last_used_at
            FROM retrieval_hits
            WHERE workspace_id = :ws AND project_id = :proj AND resource_id = :res
            """
            ),
            {"ws": resource.workspace_id, "proj": resource.project_id, "res": resource.id},
        )
        .mappings()
        .one()
    )
    last_index = (
        session.execute(
            text(
                """
            SELECT status, finished_at, error_message, log_ref
            FROM index_runs
            WHERE workspace_id = :ws AND project_id = :proj AND resource_id = :res
            ORDER BY created_at DESC
            LIMIT 1
            """
            ),
            {"ws": resource.workspace_id, "proj": resource.project_id, "res": resource.id},
        )
        .mappings()
        .first()
    )
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
        last_index_error_message=last_index["error_message"] if last_index else None,
        last_index_log_ref=last_index["log_ref"] if last_index else None,
        stale_reasons=reasons,
    )


def create_router(deps: ResourceLifecycleRouterDeps) -> APIRouter:
    router = APIRouter()

    @router.patch(
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
        deps.require_project_member(
            session, workspace_id, project_id, principal, required_scopes={"resource:write"}
        )
        resource = deps.resolve_resource(session, workspace_id, project_id, resource_id, principal)
        fields = payload.model_dump(exclude_unset=True)
        if resource.archived_at is not None and fields.get("retrieval_enabled") is True:
            raise HTTPException(status_code=409, detail="archived resources cannot be re-enabled")
        if resource.type.lower() in FOLDER_BUNDLE_RESOURCE_TYPES and fields.get(
            "update_frequency"
        ) not in (None, "manual"):
            raise HTTPException(
                status_code=422,
                detail="folder bundle resources are manual-only; upload a new zip to update",
            )
        nullable_rejected = {"name", "uri", "update_frequency", "source_config"}
        for key, value in fields.items():
            if key in nullable_rejected and value is None:
                raise HTTPException(status_code=422, detail=f"{key} cannot be null")
        if any(key in fields for key in ("type", "uri", "source_config")):
            effective_type = fields.get("type", resource.type)
            effective_uri = fields.get("uri", resource.uri)
            effective_source_config = dict(
                fields.get("source_config", resource.source_config or {})
            )
            if str(effective_type).lower() in GIT_RESOURCE_TYPES and "uri" in fields:
                effective_source_config["url"] = str(fields["uri"])
            fields["source_config"] = deps.validate_source_config(
                effective_type, effective_uri, effective_source_config
            )
            if effective_type.lower() in URL_RESOURCE_TYPES | GIT_RESOURCE_TYPES:
                fields["uri"] = sanitize_remote_url(fields["source_config"]["url"])
        for key, value in fields.items():
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

    @router.delete(
        "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}", status_code=204
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
        deps.require_project_member(
            session, workspace_id, project_id, principal, required_scopes={"resource:write"}
        )
        resource = deps.resolve_resource(session, workspace_id, project_id, resource_id, principal)
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

    @router.post(
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
        deps.require_project_member(
            session, workspace_id, project_id, principal, required_scopes={"resource:write"}
        )
        resource = deps.resolve_resource(session, workspace_id, project_id, resource_id, principal)
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

    @router.post(
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
        deps.require_project_member(
            session, workspace_id, project_id, principal, required_scopes={"resource:write"}
        )
        resource = deps.resolve_resource(
            session, workspace_id, project_id, resource_id, principal, include_deleted=True
        )
        if (
            resource.deleted_at is None
            and resource.archived_at is None
            and resource.status not in {"deleted", "archived"}
        ):
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
            "next_refresh_at": resource.next_refresh_at.isoformat()
            if resource.next_refresh_at
            else None,
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

    @router.post(
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
        deps.require_project_member(
            session, workspace_id, project_id, principal, required_scopes={"resource:write"}
        )
        resource = deps.resolve_resource(
            session, workspace_id, project_id, resource_id, principal, include_deleted=True
        )
        if resource.deleted_at is None and resource.status != "deleted":
            raise HTTPException(
                status_code=409, detail="resource must be soft-deleted before purge"
            )
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
        counts = deps.purge_resource_artifacts(session, resource)
        session.commit()
        return PurgeResourceResponse(
            resource_id=resource_id, purged=counts.get("resources", 0) == 1, counts=counts
        )

    @router.post(
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
        deps.require_project_member(
            session, workspace_id, project_id, principal, required_scopes={"review:write"}
        )
        resource = deps.resolve_resource(session, workspace_id, project_id, resource_id, principal)
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
            "last_reviewed_at": resource.last_reviewed_at.isoformat()
            if resource.last_reviewed_at
            else None,
            "last_reviewed_by": str(resource.last_reviewed_by)
            if resource.last_reviewed_by
            else None,
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

    @router.get(
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
        deps.require_project_access(session, workspace_id, project_id, principal)
        predicates = [
            Resource.workspace_id == workspace_id,
            Resource.project_id == project_id,
            Resource.deleted_at.is_(None),
        ]
        if not include_archived:
            predicates.append(Resource.archived_at.is_(None))
        if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
            predicates.append(Resource.id.in_(principal.api_token.allowed_resource_ids))
        resources = list(
            session.scalars(select(Resource).where(*predicates).order_by(Resource.created_at.asc()))
        )
        items = [resource_review_item(session, resource) for resource in resources]
        return ResourceReviewResponse(count=len(items), resources=items)

    @router.get(
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
        deps.require_project_access(session, workspace_id, project_id, principal)
        rows = (
            session.execute(
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
            )
            .mappings()
            .all()
        )
        allowed_resource_ids = (
            principal.api_token.allowed_resource_ids if principal.api_token is not None else None
        )
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

    @router.get(
        "/workspaces/{workspace_id}/projects/{project_id}/resources",
        response_model=list[ResourceRead],
    )
    def list_resources(
        workspace_id: UUID,
        project_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> list[ResourceRead]:
        require_scope(principal, "resource:read")
        deps.require_project_access(session, workspace_id, project_id, principal)
        predicates = [
            Resource.workspace_id == workspace_id,
            Resource.project_id == project_id,
            Resource.deleted_at.is_(None),
        ]
        if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
            predicates.append(Resource.id.in_(principal.api_token.allowed_resource_ids))
        resources = list(
            session.scalars(select(Resource).where(*predicates).order_by(Resource.created_at.asc()))
        )
        return [deps.resource_read(session, resource, principal) for resource in resources]

    @router.get(
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
        deps.require_project_access(session, workspace_id, project_id, principal)
        resource = deps.resolve_resource(session, workspace_id, project_id, resource_id, principal)
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

    return router
