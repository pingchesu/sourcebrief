from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal, require_principal
from sourcebrief_api.context_packs import PACK_STATUS_PUBLISHED
from sourcebrief_api.schemas import (
    SkillExportFileRead,
    SkillExportGenerateRequest,
    SkillExportRead,
    SkillExportRejectRequest,
    SkillExportReviewRequest,
)
from sourcebrief_api.skill_exports import (
    SKILL_EXPORT_STATUS_APPROVED,
    SKILL_EXPORT_STATUS_DRAFT,
    SKILL_EXPORT_STATUS_FAILED,
    SKILL_EXPORT_STATUS_INVALIDATED,
    SKILL_EXPORT_STATUS_REJECTED,
    compile_skill_export,
    next_export_version,
)
from sourcebrief_shared.db import get_session
from sourcebrief_shared.models import AuditEvent, ContextPackVersion, SkillExport

PackVersionResolver = Callable[..., ContextPackVersion]
PackReadAuthorizer = Callable[[Session, UUID, UUID, Principal, ContextPackVersion], None]
ReviewWriteAuthorizer = Callable[[Session, UUID, UUID, Principal], None]
PackResourcesAllowed = Callable[[Session, ContextPackVersion, Principal], bool]


@dataclass(frozen=True)
class SkillExportRouterDeps:
    resolve_pack_version: PackVersionResolver
    require_pack_read: PackReadAuthorizer
    require_review_write: ReviewWriteAuthorizer
    pack_resources_allowed: PackResourcesAllowed


def skill_export_file_read(file: dict[str, Any], include_content: bool = True) -> SkillExportFileRead:
    return SkillExportFileRead(
        path=str(file.get("path", "")),
        kind=str(file.get("kind", "text")),
        sha256=str(file.get("sha256", "")),
        bytes=int(file.get("bytes", 0)),
        content=str(file.get("content", "")) if include_content else None,
    )


def skill_export_read(export: SkillExport, include_content: bool = True) -> SkillExportRead:
    return SkillExportRead(
        id=export.id,
        context_pack_version_id=export.context_pack_version_id,
        pack_key=export.pack_key,
        pack_version=export.pack_version,
        export_type=export.export_type,
        export_version=export.export_version,
        status=export.status,
        title=export.title,
        summary=export.summary,
        package_hash=export.package_hash,
        manifest_json=export.manifest_json,
        files=[skill_export_file_read(cast(dict[str, Any], file), include_content=include_content) for file in export.files_json],
        validation_json=export.validation_json,
        leak_scan_json=export.leak_scan_json,
        approved_at=export.approved_at,
        rejected_at=export.rejected_at,
        invalidated_at=export.invalidated_at,
        review_comment=export.review_comment,
        created_at=export.created_at,
    )


def resolve_skill_export(session: Session, workspace_id: UUID, project_id: UUID, export_id: UUID, *, for_update: bool = False) -> SkillExport:
    stmt = select(SkillExport).where(SkillExport.id == export_id, SkillExport.workspace_id == workspace_id, SkillExport.project_id == project_id)
    if for_update:
        stmt = stmt.with_for_update()
    export = session.scalar(stmt)
    if export is None:
        raise HTTPException(status_code=404, detail="skill export not found")
    return export


def pack_for_export(session: Session, export: SkillExport) -> ContextPackVersion:
    version = session.scalar(select(ContextPackVersion).where(ContextPackVersion.id == export.context_pack_version_id, ContextPackVersion.workspace_id == export.workspace_id, ContextPackVersion.project_id == export.project_id))
    if version is None:
        raise HTTPException(status_code=404, detail="context pack not found")
    return version


def require_skill_export_read(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, export: SkillExport, deps: SkillExportRouterDeps) -> ContextPackVersion:
    version = pack_for_export(session, export)
    deps.require_pack_read(session, workspace_id, project_id, principal, version)
    return version


def require_skill_export_review(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, export: SkillExport, deps: SkillExportRouterDeps) -> ContextPackVersion:
    deps.require_review_write(session, workspace_id, project_id, principal)
    version = pack_for_export(session, export)
    if not deps.pack_resources_allowed(session, version, principal):
        raise HTTPException(status_code=404, detail="skill export not found")
    return version


def scrub_skill_export(export: SkillExport, reason: str) -> None:
    export.files_json = []
    export.manifest_json = {"scrubbed": True, "reason": reason, "pack_key": export.pack_key, "pack_version": export.pack_version, "package_hash": export.package_hash}


def generate_skill_export_action(
    workspace_id: UUID,
    project_id: UUID,
    pack_key: str,
    version_number: int,
    payload: SkillExportGenerateRequest,
    principal: Principal,
    session: Session,
    deps: SkillExportRouterDeps,
) -> SkillExportRead:
    deps.require_review_write(session, workspace_id, project_id, principal)
    version = deps.resolve_pack_version(session, workspace_id, project_id, pack_key, version_number, for_update=True)
    if version.status != PACK_STATUS_PUBLISHED:
        raise HTTPException(status_code=422, detail="only published context pack versions can be exported")
    if not deps.pack_resources_allowed(session, version, principal):
        raise HTTPException(status_code=404, detail="context pack version not found")
    compiled = compile_skill_export(session, version, title=payload.title, summary=payload.summary, export_type=payload.export_type)
    existing = session.scalar(
        select(SkillExport).where(
            SkillExport.workspace_id == workspace_id,
            SkillExport.project_id == project_id,
            SkillExport.context_pack_version_id == version.id,
            SkillExport.export_type == payload.export_type,
            SkillExport.package_hash == compiled.package_hash,
        )
    )
    if existing is not None:
        return skill_export_read(existing)
    export = SkillExport(
        workspace_id=workspace_id,
        project_id=project_id,
        context_pack_version_id=version.id,
        pack_key=version.pack_key,
        pack_version=version.version,
        export_type=payload.export_type,
        export_version=next_export_version(session, version, payload.export_type),
        status=compiled.status,
        title=payload.title,
        summary=payload.summary,
        package_hash=compiled.package_hash,
        manifest_json=compiled.manifest,
        files_json=compiled.files,
        validation_json=compiled.validation,
        leak_scan_json=compiled.leak_scan,
        created_by=principal.user.id,
    )
    session.add(export)
    session.add(AuditEvent(workspace_id=workspace_id, actor_user_id=principal.user.id, actor_token_id=principal.token_id, action="skill_export.generate", target_type="skill_export", target_id=export.id, meta={"pack_key": version.pack_key, "pack_version": version.version, "status": compiled.status, "package_hash": compiled.package_hash}))
    session.commit()
    return skill_export_read(export)


def approve_skill_export_action(
    workspace_id: UUID,
    project_id: UUID,
    export_id: UUID,
    payload: SkillExportReviewRequest,
    principal: Principal,
    session: Session,
    deps: SkillExportRouterDeps,
) -> SkillExportRead:
    export = resolve_skill_export(session, workspace_id, project_id, export_id, for_update=True)
    require_skill_export_review(session, workspace_id, project_id, principal, export, deps)
    if export.status != SKILL_EXPORT_STATUS_DRAFT:
        raise HTTPException(status_code=422, detail="only draft exports can be approved")
    if not export.validation_json.get("ok") or not export.leak_scan_json.get("ok"):
        raise HTTPException(status_code=422, detail="validation and leak scan must pass before approval")
    export.status = SKILL_EXPORT_STATUS_APPROVED
    export.approved_by = principal.user.id
    export.approved_at = datetime.now(UTC)
    export.review_comment = payload.comment
    manifest = dict(export.manifest_json)
    manifest["export_status"] = SKILL_EXPORT_STATUS_APPROVED
    manifest["approval"] = {"approved_at": export.approved_at.isoformat(), "comment": payload.comment}
    export.manifest_json = manifest
    manifest_content = json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    updated_files = []
    for file in export.files_json:
        record = dict(cast(dict[str, Any], file))
        if record.get("path") == "manifest.json":
            record["content"] = manifest_content
            record["bytes"] = len(manifest_content.encode("utf-8"))
            record["sha256"] = "sha256:" + hashlib.sha256(manifest_content.encode("utf-8")).hexdigest()
        updated_files.append(record)
    export.files_json = updated_files
    session.add(AuditEvent(workspace_id=workspace_id, actor_user_id=principal.user.id, actor_token_id=principal.token_id, action="skill_export.approve", target_type="skill_export", target_id=export.id, meta={"previous_status": SKILL_EXPORT_STATUS_DRAFT, "new_status": export.status, "pack_key": export.pack_key, "pack_version": export.pack_version, "package_hash": export.package_hash}))
    session.commit()
    return skill_export_read(export)


def reject_skill_export_action(
    workspace_id: UUID,
    project_id: UUID,
    export_id: UUID,
    payload: SkillExportRejectRequest,
    principal: Principal,
    session: Session,
    deps: SkillExportRouterDeps,
) -> SkillExportRead:
    export = resolve_skill_export(session, workspace_id, project_id, export_id, for_update=True)
    require_skill_export_review(session, workspace_id, project_id, principal, export, deps)
    if export.status not in {SKILL_EXPORT_STATUS_DRAFT, SKILL_EXPORT_STATUS_FAILED}:
        raise HTTPException(status_code=422, detail="only draft or failed exports can be rejected")
    previous = export.status
    export.status = SKILL_EXPORT_STATUS_REJECTED
    export.rejected_by = principal.user.id
    export.rejected_at = datetime.now(UTC)
    export.review_comment = payload.reason
    session.add(AuditEvent(workspace_id=workspace_id, actor_user_id=principal.user.id, actor_token_id=principal.token_id, action="skill_export.reject", target_type="skill_export", target_id=export.id, meta={"previous_status": previous, "new_status": export.status, "pack_key": export.pack_key, "pack_version": export.pack_version, "package_hash": export.package_hash, "reason": payload.reason}))
    session.commit()
    return skill_export_read(export)


def invalidate_skill_export_action(
    workspace_id: UUID,
    project_id: UUID,
    export_id: UUID,
    payload: SkillExportRejectRequest,
    principal: Principal,
    session: Session,
    deps: SkillExportRouterDeps,
) -> SkillExportRead:
    export = resolve_skill_export(session, workspace_id, project_id, export_id, for_update=True)
    require_skill_export_review(session, workspace_id, project_id, principal, export, deps)
    if export.status == SKILL_EXPORT_STATUS_INVALIDATED:
        raise HTTPException(status_code=422, detail="skill export is already invalidated")
    previous = export.status
    export.status = SKILL_EXPORT_STATUS_INVALIDATED
    export.invalidated_by = principal.user.id
    export.invalidated_at = datetime.now(UTC)
    export.review_comment = payload.reason
    scrub_skill_export(export, payload.reason)
    session.add(AuditEvent(workspace_id=workspace_id, actor_user_id=principal.user.id, actor_token_id=principal.token_id, action="skill_export.invalidate", target_type="skill_export", target_id=export.id, meta={"previous_status": previous, "new_status": export.status, "pack_key": export.pack_key, "pack_version": export.pack_version, "package_hash": export.package_hash, "reason": payload.reason}))
    session.commit()
    return skill_export_read(export)


def skill_export_file_is_safe(path: str) -> bool:
    parts = [part for part in path.replace("\\", "/").split("/") if part]
    return bool(parts) and not path.startswith("/") and ".." not in parts


def skill_export_zip_bytes(export: SkillExport) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for item in export.files_json:
            file = cast(dict[str, Any], item)
            path = str(file.get("path") or "")
            if not skill_export_file_is_safe(path):
                raise HTTPException(status_code=500, detail="skill export contains invalid file path")
            info = zipfile.ZipInfo(path, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, str(file.get("content") or ""))
    return buffer.getvalue()


def create_router(deps: SkillExportRouterDeps) -> APIRouter:
    router = APIRouter()

    @router.post("/workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions/{version_number}/skill-exports", response_model=SkillExportRead)
    def generate_skill_export(
        workspace_id: UUID,
        project_id: UUID,
        pack_key: str,
        version_number: int,
        payload: SkillExportGenerateRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> SkillExportRead:
        return generate_skill_export_action(workspace_id, project_id, pack_key, version_number, payload, principal, session, deps)

    @router.get("/workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions/{version_number}/skill-exports", response_model=list[SkillExportRead])
    def list_skill_exports(
        workspace_id: UUID,
        project_id: UUID,
        pack_key: str,
        version_number: int,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> list[SkillExportRead]:
        version = deps.resolve_pack_version(session, workspace_id, project_id, pack_key, version_number)
        deps.require_pack_read(session, workspace_id, project_id, principal, version)
        exports = list(
            session.scalars(
                select(SkillExport)
                .where(SkillExport.workspace_id == workspace_id, SkillExport.project_id == project_id, SkillExport.context_pack_version_id == version.id)
                .order_by(SkillExport.export_version.desc())
            )
        )
        return [skill_export_read(export) for export in exports]

    @router.get("/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_id}", response_model=SkillExportRead)
    def get_skill_export(
        workspace_id: UUID,
        project_id: UUID,
        export_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> SkillExportRead:
        export = resolve_skill_export(session, workspace_id, project_id, export_id)
        require_skill_export_read(session, workspace_id, project_id, principal, export, deps)
        return skill_export_read(export)

    @router.post("/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_id}/approve", response_model=SkillExportRead)
    def approve_skill_export(
        workspace_id: UUID,
        project_id: UUID,
        export_id: UUID,
        payload: SkillExportReviewRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> SkillExportRead:
        return approve_skill_export_action(workspace_id, project_id, export_id, payload, principal, session, deps)

    @router.post("/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_id}/reject", response_model=SkillExportRead)
    def reject_skill_export(
        workspace_id: UUID,
        project_id: UUID,
        export_id: UUID,
        payload: SkillExportRejectRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> SkillExportRead:
        return reject_skill_export_action(workspace_id, project_id, export_id, payload, principal, session, deps)

    @router.post("/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_id}/invalidate", response_model=SkillExportRead)
    def invalidate_skill_export(
        workspace_id: UUID,
        project_id: UUID,
        export_id: UUID,
        payload: SkillExportRejectRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> SkillExportRead:
        return invalidate_skill_export_action(workspace_id, project_id, export_id, payload, principal, session, deps)

    @router.get("/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_id}/files/{file_path:path}")
    def download_skill_export_file(
        workspace_id: UUID,
        project_id: UUID,
        export_id: UUID,
        file_path: str,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> Response:
        export = resolve_skill_export(session, workspace_id, project_id, export_id)
        require_skill_export_read(session, workspace_id, project_id, principal, export, deps)
        if export.status != SKILL_EXPORT_STATUS_APPROVED:
            raise HTTPException(status_code=403, detail="skill export must be approved before download")
        if ".." in file_path or file_path.startswith("/"):
            raise HTTPException(status_code=400, detail="invalid export file path")
        file = next((cast(dict[str, Any], item) for item in export.files_json if str(cast(dict[str, Any], item).get("path")) == file_path), None)
        if file is None:
            raise HTTPException(status_code=404, detail="export file not found")
        media_type = "application/json" if file_path.endswith(".json") else "text/plain"
        return Response(content=str(file.get("content", "")), media_type=media_type)

    @router.get("/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_id}/download.zip")
    def download_skill_export_package(
        workspace_id: UUID,
        project_id: UUID,
        export_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> Response:
        export = resolve_skill_export(session, workspace_id, project_id, export_id)
        require_skill_export_read(session, workspace_id, project_id, principal, export, deps)
        if export.status != SKILL_EXPORT_STATUS_APPROVED:
            raise HTTPException(status_code=403, detail="skill export must be approved before download")
        content = skill_export_zip_bytes(export)
        filename = f"sourcebrief-{export.pack_key}-v{export.pack_version}-skill.zip"
        return Response(
            content=content,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    return router
