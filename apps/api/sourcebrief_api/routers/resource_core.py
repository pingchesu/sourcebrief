from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from redis import Redis
from rq import Queue
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal, require_principal, require_scope, token_allows_resource
from sourcebrief_api.constants import FOLDER_BUNDLE_RESOURCE_TYPES, URL_RESOURCE_TYPES
from sourcebrief_api.schemas import (
    DeletedFileImpactStubRead,
    DueRefreshResponse,
    FolderBundleUploadResponse,
    IndexRunRead,
    ManifestDiffRead,
    ManifestDiffRowRead,
    ResourceCreate,
    ResourceManifestFileRead,
    ResourceManifestRead,
    ResourceRead,
    SectionImpactRead,
    SnapshotSectionRead,
    SnapshotSectionsRead,
)
from sourcebrief_shared.config import get_settings
from sourcebrief_shared.db import get_session
from sourcebrief_shared.lifecycle import compute_next_refresh_at
from sourcebrief_shared.models import (
    AuditEvent,
    IndexRun,
    Resource,
    ResourceManifest,
    ResourceManifestFile,
    Section,
    SnapshotSection,
    SourceSnapshot,
)
from sourcebrief_worker.bundle_ingest import (
    HARD_MAX_ZIP_UPLOAD_BYTES,
    ZipRejectionError,
    cleanup_stale_uploads,
    validate_upload_staging_dir,
    validate_zip_before_extract,
)
from sourcebrief_worker.ingestion import _work_base, sanitize_remote_url
from sourcebrief_worker.manifest_diff import VALID_CHANGE_TYPES, build_manifest_diff, page_diff_rows

ProjectMemberAuthorizer = Callable[..., object]
ProjectAccessAuthorizer = Callable[..., object]
ResourceResolver = Callable[..., Resource]
SourceConfigValidator = Callable[[str, str, dict], dict]


@dataclass(frozen=True)
class ResourceCoreRouterDeps:
    require_project_member: ProjectMemberAuthorizer
    require_project_access: ProjectAccessAuthorizer
    resolve_resource: ResourceResolver
    validate_source_config: SourceConfigValidator


router = APIRouter()
ACTIVE_INDEX_RUN_STATUSES = ("enqueueing", "queued", "running")
_deps: ResourceCoreRouterDeps


def create_router(deps: ResourceCoreRouterDeps) -> APIRouter:
    global _deps
    _deps = deps
    return router


@router.post(
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
    _deps.require_project_member(session, workspace_id, project_id, principal, required_scopes={"resource:write"})
    source_config = _deps.validate_source_config(payload.type, payload.uri, payload.source_config)
    resource_uri = sanitize_remote_url(source_config["url"]) if payload.type.lower() in URL_RESOURCE_TYPES | {"git"} else payload.uri
    resource = Resource(
        workspace_id=workspace_id,
        project_id=project_id,
        type=payload.type,
        name=payload.name,
        uri=resource_uri,
        update_frequency=payload.update_frequency,
        source_config=source_config,
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


def _manifest_read(manifest: ResourceManifest, files: list[ResourceManifestFile]) -> ResourceManifestRead:
    return ResourceManifestRead(
        id=manifest.id,
        resource_id=manifest.resource_id,
        source_snapshot_id=manifest.source_snapshot_id,
        manifest_hash=manifest.manifest_hash,
        file_count=manifest.file_count,
        total_bytes=manifest.total_bytes,
        parser_warning_count=manifest.parser_warning_count,
        unsupported_file_count=manifest.unsupported_file_count,
        section_count=manifest.section_count,
        sections_reused_count=manifest.sections_reused_count,
        sections_extracted_count=manifest.sections_extracted_count,
        sections_from_deleted_files_count=manifest.sections_from_deleted_files_count,
        sections_absent_count=manifest.sections_absent_count,
        created_at=manifest.created_at,
        files=[
            ResourceManifestFileRead(
                id=file.id,
                normalized_path=file.normalized_path,
                display_path=file.display_path,
                size_bytes=file.size_bytes,
                content_hash=file.content_hash,
                mime_type=file.mime_type,
                status=file.status,
                warnings_json=file.warnings_json or [],
            )
            for file in files
        ],
    )


def _source_family_id(resource: Resource) -> str:
    config = resource.source_config or {}
    value = config.get("source_family_id")
    return str(value or resource.id)


def _source_family_label(resource: Resource) -> str | None:
    config = resource.source_config or {}
    label = config.get("source_family_label")
    return str(label) if isinstance(label, str) and label.strip() else (resource.name if resource.type.lower() in FOLDER_BUNDLE_RESOURCE_TYPES else None)


def _version_label(resource: Resource) -> str | None:
    config = resource.source_config or {}
    label = config.get("version_label")
    return str(label) if isinstance(label, str) and label.strip() else None


def _family_manifest_count(session: Session, resource: Resource, principal: Principal | None = None) -> int:
    if resource.type.lower() not in FOLDER_BUNDLE_RESOURCE_TYPES:
        return 0
    family_id = _source_family_id(resource)
    candidates = list(
        session.scalars(
            select(Resource.id)
            .join(ResourceManifest, ResourceManifest.resource_id == Resource.id)
            .where(
                Resource.workspace_id == resource.workspace_id,
                Resource.project_id == resource.project_id,
                Resource.deleted_at.is_(None),
                Resource.type.in_(FOLDER_BUNDLE_RESOURCE_TYPES),
                Resource.source_config["source_family_id"].astext == family_id,
            )
            .distinct()
        )
    )
    if principal is not None:
        candidates = [resource_id for resource_id in candidates if token_allows_resource(principal, resource_id)]
    return len(candidates)


def _apply_snapshot_coverage(data: ResourceRead, snapshot_meta: dict | None) -> ResourceRead:
    meta = snapshot_meta or {}
    raw_file_stats = meta.get("file_budget_stats")
    file_stats: dict[str, Any] = raw_file_stats if isinstance(raw_file_stats, dict) else {}
    raw_index_stats = meta.get("index_budget_stats")
    index_stats: dict[str, Any] = raw_index_stats if isinstance(raw_index_stats, dict) else {}
    truncated = bool(
        meta.get("coverage_truncated")
        or file_stats.get("truncated_by_max_files")
        or file_stats.get("skipped_total_bytes")
        or file_stats.get("skipped_max_file_bytes")
        or index_stats.get("chunk_budget_exceeded")
        or index_stats.get("symbol_budget_exceeded")
    )
    if not truncated:
        return data
    warnings = list(data.coverage_warnings)
    primary_warning = "current snapshot was truncated by import/index budgets; evidence may be partial"
    for coverage_warning in [primary_warning, *[str(item) for item in meta.get("coverage_warnings") or []]]:
        if coverage_warning not in warnings:
            warnings.append(coverage_warning)
    budgets = dict(data.index_diagnostics.get("configured_budgets", {}))
    for key in ("max_files", "max_total_bytes", "max_file_bytes"):
        if file_stats.get(key) is not None:
            budgets[key] = file_stats[key]
        elif meta.get(key) is not None:
            budgets[key] = meta[key]
    for key in ("max_chunks", "max_symbols"):
        if index_stats.get(key) is not None:
            budgets[key] = index_stats[key]
    diagnostics = dict(data.index_diagnostics)
    diagnostics["configured_budgets"] = budgets
    diagnostics["file_budget_stats"] = file_stats
    diagnostics["index_budget_stats"] = index_stats
    diagnostics["suggested_retry"] = str(
        meta.get("suggested_retry")
        or "retry with narrower include/exclude filters, a source subpath, or an intentional higher import budget"
    )
    data.coverage_status = "partial" if data.queryable else data.coverage_status
    data.coverage_warnings = warnings
    data.index_diagnostics = diagnostics
    return data


def _resource_read(session: Session, resource: Resource, principal: Principal | None = None) -> ResourceRead:
    data = ResourceRead.model_validate(resource, from_attributes=True)
    if resource.current_snapshot_id is not None:
        snapshot_meta = session.scalar(
            select(SourceSnapshot.meta).where(
                SourceSnapshot.id == resource.current_snapshot_id,
                SourceSnapshot.workspace_id == resource.workspace_id,
                SourceSnapshot.project_id == resource.project_id,
            )
        )
        data = _apply_snapshot_coverage(data, snapshot_meta)
    if resource.type.lower() in FOLDER_BUNDLE_RESOURCE_TYPES:
        data.source_family_label = _source_family_label(resource)
        data.version_label = _version_label(resource)
        data.has_manifest_diff = _family_manifest_count(session, resource, principal) >= 2
    return data


def _folder_bundle_version_name(session: Session, project_id: UUID, family_label: str) -> tuple[str, str]:
    base = family_label.strip() or "Folder bundle"
    existing = set(session.scalars(select(Resource.name).where(Resource.project_id == project_id, Resource.name.like(f"{base}%"))).all())
    if base not in existing:
        return base, "v1"
    version = 2
    while True:
        candidate = f"{base} · v{version}"
        if candidate not in existing:
            return candidate, f"v{version}"
        version += 1


@router.post(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/upload-folder-bundle",
    response_model=FolderBundleUploadResponse,
    status_code=202,
)
def upload_folder_bundle(
    workspace_id: UUID,
    project_id: UUID,
    name: str | None = Form(default=None),
    update_frequency: str = Form(default="manual"),
    supersedes_resource_id: UUID | None = Form(default=None),
    source_family_id: str | None = Form(default=None),
    zip_file: UploadFile = File(...),
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> FolderBundleUploadResponse:
    user = principal.user
    require_scope(principal, "resource:write")
    require_scope(principal, "resource:refresh")
    if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
        raise HTTPException(status_code=403, detail="resource-scoped tokens cannot create new resources")
    _deps.require_project_member(session, workspace_id, project_id, principal, required_scopes={"resource:refresh", "resource:write"})
    if update_frequency != "manual":
        raise HTTPException(status_code=422, detail="folder bundle uploads are manual-only in A2; re-upload a new zip to update")
    if source_family_id is not None:
        raise HTTPException(status_code=422, detail="source_family_id is server-derived; upload a new version with supersedes_resource_id")

    superseded: Resource | None = None
    family_label = (name or "").strip()
    family_id: str | None = None
    if supersedes_resource_id is not None:
        superseded = _deps.resolve_resource(session, workspace_id, project_id, supersedes_resource_id, principal)
        if superseded.type.lower() not in FOLDER_BUNDLE_RESOURCE_TYPES:
            raise HTTPException(status_code=422, detail="superseded resource must be a folder bundle")
        existing_label = _source_family_label(superseded) or superseded.name
        if family_label and family_label != existing_label:
            raise HTTPException(status_code=422, detail="family label changes are not supported in A3")
        family_label = existing_label
        family_id = _source_family_id(superseded)
    elif not family_label:
        raise HTTPException(status_code=422, detail="name is required for first folder bundle upload")

    resource_name, version_label = _folder_bundle_version_name(session, project_id, family_label)

    work_base = _work_base()
    try:
        upload_dir = validate_upload_staging_dir(work_base)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    cleanup_stale_uploads(work_base)
    original_filename = os.path.basename(zip_file.filename or "upload.zip") or "upload.zip"
    staged_path = upload_dir / f"{uuid4()}.zip"
    incoming_path = upload_dir / f".incoming-{staged_path.name}"
    total_bytes = 0
    try:
        with open(incoming_path, "wb") as fh:
            while True:
                chunk = zip_file.file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > HARD_MAX_ZIP_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="folder bundle zip exceeds upload size limit")
                fh.write(chunk)
        if total_bytes == 0:
            raise HTTPException(status_code=422, detail="folder bundle zip is empty")
        with open(incoming_path, "rb") as fh:
            magic = fh.read(4)
        if not magic.startswith(b"PK"):
            raise HTTPException(status_code=422, detail="folder bundle upload must be a zip archive")
        try:
            validate_zip_before_extract(incoming_path)
        except ZipRejectionError as exc:
            detail = f"zip rejected: {exc.reason}"
            if exc.detail:
                detail = f"{detail}: {exc.detail}"
            raise HTTPException(status_code=422, detail=detail) from exc
        os.replace(incoming_path, staged_path)
    except HTTPException:
        try:
            os.unlink(incoming_path)
        except OSError:
            pass
        raise

    resource = Resource(
        workspace_id=workspace_id,
        project_id=project_id,
        type=next(iter(FOLDER_BUNDLE_RESOURCE_TYPES)),
        name=resource_name,
        uri=f"folder-bundle://{original_filename}",
        update_frequency=update_frequency,
        source_config={
            "staged_zip_path": str(staged_path),
            "original_filename": original_filename,
            "zip_size_bytes": total_bytes,
            "source_family_id": family_id or "pending",
            "source_family_label": family_label,
            "supersedes_resource_id": str(superseded.id) if superseded is not None else None,
            "version_label": version_label,
        },
        created_by=user.id,
    )
    session.add(resource)
    session.flush()
    if family_id is None:
        config = dict(resource.source_config or {})
        config["source_family_id"] = str(resource.id)
        resource.source_config = config
    resource.next_refresh_at = compute_next_refresh_at(resource)
    run = IndexRun(
        workspace_id=workspace_id,
        project_id=project_id,
        resource_id=resource.id,
        trigger="upload",
        status="enqueueing",
    )
    session.add(run)
    session.flush()
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="resource.upload",
            target_type="resource",
            target_id=resource.id,
            meta={"index_run_id": str(run.id), "zip_size_bytes": total_bytes},
        )
    )
    session.commit()
    queue = Queue("default", connection=Redis.from_url(get_settings().redis_url))
    try:
        queue.enqueue("sourcebrief_worker.jobs.run_index", str(run.id), job_timeout=600)
    except Exception as exc:
        try:
            os.unlink(staged_path)
        except OSError:
            pass
        resource.status = "error"
        resource.deleted_at = datetime.now(UTC)
        run.status = "failed"
        run.error_message = f"failed to enqueue index job: {exc}"[:1000]
        session.add_all([resource, run])
        session.commit()
        raise HTTPException(status_code=503, detail="failed to enqueue index job") from exc
    run.status = "queued"
    session.add(run)
    session.commit()
    return FolderBundleUploadResponse(
        resource=_resource_read(session, resource, principal),
        index_run=IndexRunRead.model_validate(run),
    )


@router.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}",
    response_model=ResourceRead,
)
def get_resource(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ResourceRead:
    require_scope(principal, "resource:read")
    _deps.require_project_access(session, workspace_id, project_id, principal)
    return _resource_read(session, _deps.resolve_resource(session, workspace_id, project_id, resource_id, principal), principal)


@router.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/manifest",
    response_model=ResourceManifestRead,
)
def get_resource_manifest(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ResourceManifestRead:
    require_scope(principal, "resource:read")
    _deps.require_project_access(session, workspace_id, project_id, principal)
    resource = _deps.resolve_resource(session, workspace_id, project_id, resource_id, principal)
    if resource.current_snapshot_id is None:
        raise HTTPException(status_code=404, detail="resource manifest not found")
    manifest = session.scalar(
        select(ResourceManifest).where(
            ResourceManifest.workspace_id == workspace_id,
            ResourceManifest.project_id == project_id,
            ResourceManifest.resource_id == resource_id,
            ResourceManifest.source_snapshot_id == resource.current_snapshot_id,
        )
    )
    if manifest is None:
        raise HTTPException(status_code=404, detail="resource manifest not found")
    files = list(
        session.scalars(
            select(ResourceManifestFile)
            .where(
                ResourceManifestFile.workspace_id == workspace_id,
                ResourceManifestFile.project_id == project_id,
                ResourceManifestFile.resource_id == resource_id,
                ResourceManifestFile.resource_manifest_id == manifest.id,
            )
            .order_by(ResourceManifestFile.normalized_path.asc())
        )
    )
    return _manifest_read(manifest, files)


def _manifest_files(session: Session, manifest: ResourceManifest) -> list[ResourceManifestFile]:
    return list(
        session.scalars(
            select(ResourceManifestFile)
            .where(ResourceManifestFile.resource_manifest_id == manifest.id)
            .order_by(ResourceManifestFile.normalized_path.asc())
        )
    )


def _latest_family_manifests(session: Session, resource: Resource) -> list[ResourceManifest]:
    family_id = _source_family_id(resource)
    family_uuid = UUID(family_id)
    return list(
        session.scalars(
            select(ResourceManifest)
            .join(Resource, ResourceManifest.resource_id == Resource.id)
            .where(
                ResourceManifest.workspace_id == resource.workspace_id,
                ResourceManifest.project_id == resource.project_id,
                Resource.deleted_at.is_(None),
                Resource.type.in_(FOLDER_BUNDLE_RESOURCE_TYPES),
                (Resource.source_config["source_family_id"].astext == family_id) | (Resource.id == family_uuid),
            )
            .order_by(ResourceManifest.created_at.desc())
            .limit(2)
        )
    )


def _manifest_diff_read(
    session: Session,
    *,
    base_manifest: ResourceManifest,
    head_manifest: ResourceManifest,
    source_family_label: str | None,
    limit: int,
    cursor: str | None,
    change_types: set[str] | None,
) -> ManifestDiffRead:
    result = build_manifest_diff(_manifest_files(session, base_manifest), _manifest_files(session, head_manifest))
    page, next_cursor, filtered_count = page_diff_rows(result.rows, change_types=change_types, limit=limit, cursor=cursor)
    return ManifestDiffRead(
        base_manifest_id=base_manifest.id,
        head_manifest_id=head_manifest.id,
        base_resource_id=base_manifest.resource_id,
        head_resource_id=head_manifest.resource_id,
        source_family_label=source_family_label,
        added_count=result.added_count,
        changed_count=result.changed_count,
        deleted_count=result.deleted_count,
        unchanged_count=result.unchanged_count,
        warning_changed_count=result.warning_changed_count,
        base_file_count=result.base_file_count,
        head_file_count=result.head_file_count,
        total_row_count=filtered_count,
        row_count_returned=len(page),
        limit=limit,
        next_cursor=next_cursor,
        rows=[
            ManifestDiffRowRead(
                normalized_path=row.normalized_path,
                change_type=row.change_type,
                base_file_id=row.base_file_id,
                head_file_id=row.head_file_id,
                base_status=row.base_status,
                head_status=row.head_status,
                base_size_bytes=row.base_size_bytes,
                head_size_bytes=row.head_size_bytes,
                base_content_hash=row.base_content_hash,
                head_content_hash=row.head_content_hash,
                warning_changed=row.warning_changed,
                reason=row.reason,
            )
            for row in page
        ],
        deleted_file_impact=DeletedFileImpactStubRead(
            deleted_file_count=result.deleted_file_impact.deleted_file_count,
            impacted_sections_known=result.deleted_file_impact.impacted_sections_known,
            message=result.deleted_file_impact.message,
        ),
    )


@router.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/manifest-diff",
    response_model=ManifestDiffRead,
)
def get_resource_manifest_diff(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    change_type: list[str] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None),
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ManifestDiffRead:
    require_scope(principal, "resource:read")
    _deps.require_project_access(session, workspace_id, project_id, principal)
    resource = _deps.resolve_resource(session, workspace_id, project_id, resource_id, principal)
    if resource.type.lower() not in FOLDER_BUNDLE_RESOURCE_TYPES:
        raise HTTPException(status_code=422, detail="manifest diff is only available for folder bundles in A3")
    requested = set(change_type or [])
    invalid = requested - VALID_CHANGE_TYPES
    if invalid:
        raise HTTPException(status_code=422, detail=f"invalid change_type: {', '.join(sorted(invalid))}")
    manifests = _latest_family_manifests(session, resource)
    if len(manifests) < 2:
        raise HTTPException(status_code=409, detail="not enough manifests to diff")
    head_manifest, base_manifest = manifests[0], manifests[1]
    for compared_resource_id in (head_manifest.resource_id, base_manifest.resource_id):
        if not token_allows_resource(principal, compared_resource_id):
            raise HTTPException(status_code=404, detail="manifest diff not found")
    try:
        return _manifest_diff_read(
            session,
            base_manifest=base_manifest,
            head_manifest=head_manifest,
            source_family_label=_source_family_label(resource),
            limit=limit,
            cursor=cursor,
            change_types=requested or None,
        )
    except Exception as exc:
        if cursor:
            raise HTTPException(status_code=422, detail="invalid diff cursor") from exc
        raise


def _section_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        value = int(str(cursor))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid section cursor") from exc
    if value < 0:
        raise HTTPException(status_code=422, detail="invalid section cursor")
    return value


def _section_preview(text: str, limit: int = 240) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _section_impact_read(session: Session, resource: Resource, manifest: ResourceManifest) -> SectionImpactRead:
    deleted_paths = list(
        session.execute(
            text(
                """
                SELECT normalized_path, section_count
                FROM resource_manifest_files
                WHERE workspace_id = :ws
                  AND project_id = :proj
                  AND resource_id = :res
                  AND resource_manifest_id = :manifest
                  AND status = 'skipped'
                ORDER BY normalized_path ASC
                LIMIT 20
                """
            ),
            {"ws": resource.workspace_id, "proj": resource.project_id, "res": resource.id, "manifest": manifest.id},
        ).mappings().all()
    )
    return SectionImpactRead(
        sections_from_deleted_files_count=manifest.sections_from_deleted_files_count,
        sections_absent_count=manifest.sections_absent_count,
        impacted_artifacts_known=False,
        message="Section-level absence is known. Artifact citation impact is not available yet.",
        deleted_paths=[dict(row) for row in deleted_paths],
        changed_paths_with_absent_sections=[],
    )


@router.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/snapshot-sections",
    response_model=SnapshotSectionsRead,
)
def get_resource_snapshot_sections(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    version_resource_id: UUID | None = Query(default=None),
    source_snapshot_id: UUID | None = Query(default=None),
    reuse_status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None),
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> SnapshotSectionsRead:
    require_scope(principal, "resource:read")
    _deps.require_project_access(session, workspace_id, project_id, principal)
    resource = _deps.resolve_resource(session, workspace_id, project_id, version_resource_id or resource_id, principal)
    if resource.type.lower() not in FOLDER_BUNDLE_RESOURCE_TYPES:
        raise HTTPException(status_code=422, detail="snapshot sections are only available for folder bundles")
    if source_snapshot_id is None:
        source_snapshot_id = resource.current_snapshot_id
    if source_snapshot_id is None:
        raise HTTPException(status_code=404, detail="snapshot sections not found")
    if not token_allows_resource(principal, resource.id):
        raise HTTPException(status_code=404, detail="snapshot sections not found")
    if reuse_status is not None and reuse_status not in {"reused", "extracted"}:
        raise HTTPException(status_code=422, detail="invalid reuse_status")
    predicates = [
        SnapshotSection.workspace_id == workspace_id,
        SnapshotSection.project_id == project_id,
        SnapshotSection.version_resource_id == resource.id,
        SnapshotSection.source_snapshot_id == source_snapshot_id,
    ]
    if reuse_status:
        predicates.append(SnapshotSection.reuse_status == reuse_status)
    offset = _section_cursor(cursor)
    total = int(session.scalar(select(func.count(SnapshotSection.id)).where(*predicates)) or 0)
    rows = list(
        session.execute(
            select(SnapshotSection, Section)
            .join(Section, SnapshotSection.section_id == Section.id)
            .where(*predicates)
            .order_by(SnapshotSection.normalized_path.asc(), SnapshotSection.ordinal.asc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    next_cursor = str(offset + len(rows)) if offset + len(rows) < total else None
    return SnapshotSectionsRead(
        source_snapshot_id=source_snapshot_id,
        version_resource_id=resource.id,
        section_count=total,
        total_row_count=total,
        row_count_returned=len(rows),
        limit=limit,
        next_cursor=next_cursor,
        rows=[
            SnapshotSectionRead(
                id=snapshot_section.id,
                normalized_path=snapshot_section.normalized_path,
                ordinal=snapshot_section.ordinal,
                title=section.title,
                reuse_status=snapshot_section.reuse_status,
                start_line=section.start_line,
                end_line=section.end_line,
                content_preview=_section_preview(section.content_text),
            )
            for snapshot_section, section in rows
        ],
    )


@router.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/section-impact",
    response_model=SectionImpactRead,
)
def get_resource_section_impact(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> SectionImpactRead:
    require_scope(principal, "resource:read")
    _deps.require_project_access(session, workspace_id, project_id, principal)
    resource = _deps.resolve_resource(session, workspace_id, project_id, resource_id, principal)
    if resource.current_snapshot_id is None:
        raise HTTPException(status_code=404, detail="section impact not found")
    manifest = session.scalar(
        select(ResourceManifest).where(
            ResourceManifest.workspace_id == workspace_id,
            ResourceManifest.project_id == project_id,
            ResourceManifest.resource_id == resource.id,
            ResourceManifest.source_snapshot_id == resource.current_snapshot_id,
        )
    )
    if manifest is None:
        raise HTTPException(status_code=404, detail="section impact not found")
    return _section_impact_read(session, resource, manifest)


@router.post(
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
    _deps.require_project_member(session, workspace_id, project_id, principal, required_scopes={"resource:refresh"})
    resource = _deps.resolve_resource(session, workspace_id, project_id, resource_id, principal)
    # Serialize manual refresh creation per resource so repeated clicks/API retries do not
    # enqueue duplicate work. If a refresh is already enqueueing/queued/running, return that
    # run idempotently instead of mutating the queue again.
    session.execute(
        select(Resource.id)
        .where(
            Resource.id == resource.id,
            Resource.workspace_id == workspace_id,
            Resource.project_id == project_id,
        )
        .with_for_update()
    ).scalar_one()
    active_run = session.scalar(
        select(IndexRun)
        .where(
            IndexRun.workspace_id == workspace_id,
            IndexRun.project_id == project_id,
            IndexRun.resource_id == resource_id,
            IndexRun.status.in_(ACTIVE_INDEX_RUN_STATUSES),
        )
        .order_by(IndexRun.created_at.desc())
        .limit(1)
    )
    if active_run is not None:
        return active_run
    if resource.type.lower() in FOLDER_BUNDLE_RESOURCE_TYPES:
        raise HTTPException(status_code=422, detail="folder bundle resources are updated by uploading a new zip, not by refresh")
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
        queue.enqueue("sourcebrief_worker.jobs.run_index", str(run.id), job_timeout=600)
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


@router.post(
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
    _deps.require_project_member(session, workspace_id, project_id, principal, required_scopes={"resource:refresh"})
    allowed_resource_ids = principal.api_token.allowed_resource_ids if principal.api_token is not None else None
    if allowed_resource_ids is not None:
        allowed = list(allowed_resource_ids)
    else:
        allowed = None
    from sourcebrief_worker.maintenance import enqueue_due_refreshes

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


