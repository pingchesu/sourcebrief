from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal, require_principal, require_scope, token_allows_resource
from sourcebrief_api.context_packs import (
    PACK_STATUS_DRAFT,
    PACK_STATUS_INVALIDATED,
    PACK_STATUS_PUBLISHED,
    PACK_STATUS_ROLLED_BACK,
    PACK_STATUS_SUPERSEDED,
    attach_pack_rows,
    build_pack_from_artifacts,
    citation_counts_for_artifacts,
    get_or_create_locked_pack,
    next_pack_version,
    validate_pack_key,
)
from sourcebrief_api.schemas import (
    ContextArtifactCitationRead,
    ContextPackArtifactRead,
    ContextPackCoverageRead,
    ContextPackDraftRequest,
    ContextPackInvalidateRequest,
    ContextPackPublishRequest,
    ContextPackRollbackRequest,
    ContextPackSummaryRead,
    ContextPackVersionRead,
)
from sourcebrief_shared.db import get_session
from sourcebrief_shared.models import (
    AuditEvent,
    ContextArtifact,
    ContextArtifactCitation,
    ContextPack,
    ContextPackArtifact,
    ContextPackResourceCoverage,
    ContextPackVersion,
    Project,
    Resource,
)

ProjectAccessAuthorizer = Callable[[Session, UUID, UUID, Principal], Project]
ReviewWriteAuthorizer = Callable[[Session, UUID, UUID, Principal], None]


@dataclass(frozen=True)
class ContextPackRouterDeps:
    require_project_access: ProjectAccessAuthorizer
    require_review_write: ReviewWriteAuthorizer


def pack_artifact_read(session: Session, row: ContextPackArtifact) -> ContextPackArtifactRead:
    artifact = session.scalar(select(ContextArtifact).where(ContextArtifact.id == row.context_artifact_id))
    resource = session.scalar(select(Resource).where(Resource.id == row.resource_id))
    citations = list(
        session.scalars(
            select(ContextArtifactCitation)
            .where(ContextArtifactCitation.context_artifact_id == row.context_artifact_id)
            .order_by(ContextArtifactCitation.normalized_path.asc(), ContextArtifactCitation.ordinal.asc())
            .limit(12)
        )
    )
    return ContextPackArtifactRead(
        id=row.id,
        context_artifact_id=row.context_artifact_id,
        resource_id=row.resource_id,
        resource_name=resource.name if resource else None,
        source_snapshot_id=row.source_snapshot_id,
        resource_manifest_id=row.resource_manifest_id,
        artifact_type=row.artifact_type,
        artifact_hash=row.artifact_hash,
        artifact_title=artifact.title if artifact else None,
        artifact_status=artifact.status if artifact else None,
        ordinal=row.ordinal,
        citations=[
            ContextArtifactCitationRead(
                id=citation.id,
                normalized_path=citation.normalized_path,
                ordinal=citation.ordinal,
                title=citation.title,
                content_hash=citation.content_hash,
                line_start=citation.line_start,
                line_end=citation.line_end,
            )
            for citation in citations
        ],
    )


def pack_coverage_read(session: Session, row: ContextPackResourceCoverage) -> ContextPackCoverageRead:
    resource = session.scalar(select(Resource).where(Resource.id == row.resource_id))
    return ContextPackCoverageRead(
        id=row.id,
        resource_id=row.resource_id,
        resource_name=resource.name if resource else None,
        source_family_label=None,
        source_snapshot_id=row.source_snapshot_id,
        resource_manifest_id=row.resource_manifest_id,
        artifact_count=row.artifact_count,
        citation_count=row.citation_count,
    )


def pack_version_read(session: Session, version: ContextPackVersion) -> ContextPackVersionRead:
    artifacts = list(
        session.scalars(
            select(ContextPackArtifact)
            .where(ContextPackArtifact.context_pack_version_id == version.id)
            .order_by(ContextPackArtifact.ordinal.asc())
        )
    )
    coverage = list(
        session.scalars(
            select(ContextPackResourceCoverage)
            .where(ContextPackResourceCoverage.context_pack_version_id == version.id)
            .order_by(ContextPackResourceCoverage.resource_id.asc(), ContextPackResourceCoverage.source_snapshot_id.asc())
        )
    )
    return ContextPackVersionRead(
        id=version.id,
        pack_key=version.pack_key,
        version=version.version,
        status=version.status,
        title=version.title,
        description=version.description,
        pack_hash=version.pack_hash,
        coverage_json=version.coverage_json,
        validation_json=version.validation_json,
        status_reason=version.status_reason,
        published_at=version.published_at,
        rolled_back_at=version.rolled_back_at,
        invalidated_at=version.invalidated_at,
        created_at=version.created_at,
        artifacts=[pack_artifact_read(session, row) for row in artifacts],
        coverage=[pack_coverage_read(session, row) for row in coverage],
    )


def pack_resources_allowed(session: Session, version: ContextPackVersion, principal: Principal) -> bool:
    rows = session.scalars(
        select(ContextPackResourceCoverage.resource_id).where(ContextPackResourceCoverage.context_pack_version_id == version.id)
    ).all()
    return all(token_allows_resource(principal, resource_id) for resource_id in rows)


def require_pack_read(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    version: ContextPackVersion,
    deps: ContextPackRouterDeps,
) -> None:
    require_scope(principal, "resource:read")
    deps.require_project_access(session, workspace_id, project_id, principal)
    if not pack_resources_allowed(session, version, principal):
        raise HTTPException(status_code=404, detail="context pack not found")


def resolve_pack_version(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    pack_key: str,
    version: int | str,
    *,
    for_update: bool = False,
) -> ContextPackVersion:
    key = validate_pack_key(pack_key)
    stmt = select(ContextPackVersion).where(
        ContextPackVersion.workspace_id == workspace_id,
        ContextPackVersion.project_id == project_id,
        ContextPackVersion.pack_key == key,
    )
    if version == "current":
        stmt = stmt.where(ContextPackVersion.status == PACK_STATUS_PUBLISHED)
    else:
        stmt = stmt.where(ContextPackVersion.version == int(version))
    if for_update:
        stmt = stmt.with_for_update()
    resolved = session.scalar(stmt.order_by(ContextPackVersion.version.desc()))
    if resolved is None:
        raise HTTPException(status_code=404, detail="context pack version not found")
    return resolved


def lock_pack_parent(session: Session, workspace_id: UUID, project_id: UUID, pack_key: str) -> ContextPack:
    key = validate_pack_key(pack_key)
    pack = session.scalar(
        select(ContextPack)
        .where(ContextPack.workspace_id == workspace_id, ContextPack.project_id == project_id, ContextPack.pack_key == key)
        .with_for_update()
    )
    if pack is None:
        raise HTTPException(status_code=404, detail="context pack not found")
    return pack


def create_router(deps: ContextPackRouterDeps) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions",
        response_model=ContextPackVersionRead,
        status_code=201,
    )
    def create_context_pack_version(
        workspace_id: UUID,
        project_id: UUID,
        pack_key: str,
        payload: ContextPackDraftRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> ContextPackVersionRead:
        deps.require_review_write(session, workspace_id, project_id, principal)
        key = validate_pack_key(pack_key)
        artifacts = list(
            session.scalars(
                select(ContextArtifact).where(
                    ContextArtifact.workspace_id == workspace_id,
                    ContextArtifact.project_id == project_id,
                    ContextArtifact.id.in_(payload.artifact_ids),
                )
            )
        )
        if len(artifacts) != len(set(payload.artifact_ids)):
            raise HTTPException(status_code=404, detail="one or more context artifacts were not found")
        for artifact in artifacts:
            if artifact.status != "approved":
                raise HTTPException(status_code=422, detail="Context Pack can include approved artifacts only")
            if not token_allows_resource(principal, artifact.resource_id):
                raise HTTPException(status_code=404, detail="one or more context artifacts were not found")
        pack = get_or_create_locked_pack(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            pack_key=key,
            title=payload.title,
            description=payload.description,
            created_by=principal.user.id,
        )
        citation_counts = citation_counts_for_artifacts(session, [artifact.id for artifact in artifacts])
        build = build_pack_from_artifacts(artifacts, citation_counts)
        version = ContextPackVersion(
            workspace_id=workspace_id,
            project_id=project_id,
            context_pack_id=pack.id,
            pack_key=key,
            version=next_pack_version(session, workspace_id, project_id, key),
            status=PACK_STATUS_DRAFT if build.validation_json.get("ok") else "failed",
            title=payload.title,
            description=payload.description,
            pack_hash=build.pack_hash,
            coverage_json=build.coverage_json,
            validation_json=build.validation_json,
            created_by=principal.user.id,
        )
        session.add(version)
        session.flush()
        attach_pack_rows(session, version, artifacts, citation_counts)
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="context_pack.create_draft",
                target_type="context_pack_version",
                target_id=version.id,
                meta={"pack_key": key, "version": version.version},
            )
        )
        session.commit()
        return pack_version_read(session, version)

    @router.get("/workspaces/{workspace_id}/projects/{project_id}/context-packs", response_model=list[ContextPackSummaryRead])
    def list_context_packs(
        workspace_id: UUID,
        project_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> list[ContextPackSummaryRead]:
        require_scope(principal, "resource:read")
        deps.require_project_access(session, workspace_id, project_id, principal)
        packs = list(session.scalars(select(ContextPack).where(ContextPack.workspace_id == workspace_id, ContextPack.project_id == project_id).order_by(ContextPack.pack_key.asc())))
        results: list[ContextPackSummaryRead] = []
        for pack in packs:
            versions = list(session.scalars(select(ContextPackVersion).where(ContextPackVersion.context_pack_id == pack.id).order_by(ContextPackVersion.version.desc())))
            visible = [version for version in versions if pack_resources_allowed(session, version, principal)]
            if not visible:
                continue
            current = next((version for version in visible if version.status == PACK_STATUS_PUBLISHED), None)
            latest = visible[0] if visible else None
            results.append(
                ContextPackSummaryRead(
                    pack_key=pack.pack_key,
                    title=pack.title,
                    description=pack.description,
                    current=pack_version_read(session, current) if current else None,
                    latest=pack_version_read(session, latest) if latest else None,
                    versions=[pack_version_read(session, version) for version in visible],
                )
            )
        return results

    @router.get("/workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions", response_model=list[ContextPackVersionRead])
    def list_context_pack_versions(
        workspace_id: UUID,
        project_id: UUID,
        pack_key: str,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> list[ContextPackVersionRead]:
        require_scope(principal, "resource:read")
        deps.require_project_access(session, workspace_id, project_id, principal)
        key = validate_pack_key(pack_key)
        versions = list(session.scalars(select(ContextPackVersion).where(ContextPackVersion.workspace_id == workspace_id, ContextPackVersion.project_id == project_id, ContextPackVersion.pack_key == key).order_by(ContextPackVersion.version.desc())))
        return [pack_version_read(session, version) for version in versions if pack_resources_allowed(session, version, principal)]

    @router.get("/workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/current", response_model=ContextPackVersionRead)
    def get_current_context_pack_version(
        workspace_id: UUID,
        project_id: UUID,
        pack_key: str,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> ContextPackVersionRead:
        version = resolve_pack_version(session, workspace_id, project_id, pack_key, "current")
        require_pack_read(session, workspace_id, project_id, principal, version, deps)
        return pack_version_read(session, version)

    @router.get("/workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions/{version_number}", response_model=ContextPackVersionRead)
    def get_context_pack_version_by_number(
        workspace_id: UUID,
        project_id: UUID,
        pack_key: str,
        version_number: int,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> ContextPackVersionRead:
        version = resolve_pack_version(session, workspace_id, project_id, pack_key, version_number)
        require_pack_read(session, workspace_id, project_id, principal, version, deps)
        return pack_version_read(session, version)

    @router.post("/workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions/{version_number}/publish", response_model=ContextPackVersionRead)
    def publish_context_pack_version(
        workspace_id: UUID,
        project_id: UUID,
        pack_key: str,
        version_number: int,
        payload: ContextPackPublishRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> ContextPackVersionRead:
        deps.require_review_write(session, workspace_id, project_id, principal)
        lock_pack_parent(session, workspace_id, project_id, pack_key)
        version = resolve_pack_version(session, workspace_id, project_id, pack_key, version_number, for_update=True)
        if version.status != PACK_STATUS_DRAFT:
            raise HTTPException(status_code=422, detail="only draft pack versions can be published")
        if not version.validation_json.get("ok", False):
            raise HTTPException(status_code=422, detail="pack validation failed")
        if not pack_resources_allowed(session, version, principal):
            raise HTTPException(status_code=404, detail="context pack version not found")
        current = session.scalar(select(ContextPackVersion).where(ContextPackVersion.workspace_id == workspace_id, ContextPackVersion.project_id == project_id, ContextPackVersion.pack_key == validate_pack_key(pack_key), ContextPackVersion.status == PACK_STATUS_PUBLISHED).with_for_update())
        if current is not None and not pack_resources_allowed(session, current, principal):
            raise HTTPException(status_code=404, detail="context pack version not found")
        if current is not None:
            current.status = PACK_STATUS_SUPERSEDED
            current.status_reason = f"Superseded by v{version.version}: {payload.comment}"
            session.flush()
        version.status = PACK_STATUS_PUBLISHED
        version.published_by = principal.user.id
        version.published_at = datetime.now(UTC)
        version.status_reason = payload.comment
        session.add(AuditEvent(workspace_id=workspace_id, actor_user_id=principal.user.id, actor_token_id=principal.token_id, action="context_pack.publish", target_type="context_pack_version", target_id=version.id, meta={"pack_key": version.pack_key, "version": version.version, "comment": payload.comment}))
        session.commit()
        return pack_version_read(session, version)

    @router.post("/workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions/{version_number}/rollback", response_model=ContextPackVersionRead)
    def rollback_context_pack_version(
        workspace_id: UUID,
        project_id: UUID,
        pack_key: str,
        version_number: int,
        payload: ContextPackRollbackRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> ContextPackVersionRead:
        deps.require_review_write(session, workspace_id, project_id, principal)
        lock_pack_parent(session, workspace_id, project_id, pack_key)
        target = resolve_pack_version(session, workspace_id, project_id, pack_key, version_number, for_update=True)
        if target.status != PACK_STATUS_SUPERSEDED:
            raise HTTPException(status_code=422, detail="rollback target must be a superseded version")
        if not pack_resources_allowed(session, target, principal):
            raise HTTPException(status_code=404, detail="context pack version not found")
        current = session.scalar(select(ContextPackVersion).where(ContextPackVersion.workspace_id == workspace_id, ContextPackVersion.project_id == project_id, ContextPackVersion.pack_key == target.pack_key, ContextPackVersion.status == PACK_STATUS_PUBLISHED).with_for_update())
        if current is not None and not pack_resources_allowed(session, current, principal):
            raise HTTPException(status_code=404, detail="context pack version not found")
        if current is None or current.id == target.id:
            raise HTTPException(status_code=422, detail="rollback requires a different current published version")
        current.status = PACK_STATUS_ROLLED_BACK
        current.rolled_back_by = principal.user.id
        current.rolled_back_at = datetime.now(UTC)
        current.status_reason = payload.reason
        session.flush()
        target.status = PACK_STATUS_PUBLISHED
        target.status_reason = f"Rollback: {payload.reason}"
        target.published_by = principal.user.id
        target.published_at = datetime.now(UTC)
        session.add(AuditEvent(workspace_id=workspace_id, actor_user_id=principal.user.id, actor_token_id=principal.token_id, action="context_pack.rollback", target_type="context_pack_version", target_id=target.id, meta={"pack_key": target.pack_key, "version": target.version, "reason": payload.reason}))
        session.commit()
        return pack_version_read(session, target)

    @router.post("/workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions/{version_number}/invalidate", response_model=ContextPackVersionRead)
    def invalidate_context_pack_version(
        workspace_id: UUID,
        project_id: UUID,
        pack_key: str,
        version_number: int,
        payload: ContextPackInvalidateRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> ContextPackVersionRead:
        deps.require_review_write(session, workspace_id, project_id, principal)
        lock_pack_parent(session, workspace_id, project_id, pack_key)
        version = resolve_pack_version(session, workspace_id, project_id, pack_key, version_number, for_update=True)
        if not pack_resources_allowed(session, version, principal):
            raise HTTPException(status_code=404, detail="context pack not found")
        if version.status == PACK_STATUS_INVALIDATED:
            raise HTTPException(status_code=422, detail="pack version is already invalidated")
        version.status = PACK_STATUS_INVALIDATED
        version.invalidated_by = principal.user.id
        version.invalidated_at = datetime.now(UTC)
        version.status_reason = payload.reason
        session.add(AuditEvent(workspace_id=workspace_id, actor_user_id=principal.user.id, actor_token_id=principal.token_id, action="context_pack.invalidate", target_type="context_pack_version", target_id=version.id, meta={"pack_key": version.pack_key, "version": version.version, "reason": payload.reason}))
        session.commit()
        return pack_version_read(session, version)

    return router
