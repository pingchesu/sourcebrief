from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal, require_principal, require_scope, token_allows_resource
from sourcebrief_api.resource_map import (
    ARTIFACT_TYPE_RESOURCE_MAP,
    build_resource_map,
    latest_same_hash_artifact,
    next_artifact_revision,
)
from sourcebrief_api.schemas import (
    ArtifactApprovalRequest,
    ArtifactRejectRequest,
    ContextArtifactCitationRead,
    ContextArtifactRead,
    ContextArtifactSourceRead,
)
from sourcebrief_shared.db import get_session
from sourcebrief_shared.models import (
    AuditEvent,
    ContextArtifact,
    ContextArtifactCitation,
    ContextArtifactSource,
    Resource,
    ResourceManifest,
    SourceSnapshot,
)

ProjectAccessAuthorizer = Callable[[Session, UUID, UUID, Principal], object]
ProjectMemberAuthorizer = Callable[..., object]
ResourceResolver = Callable[..., Resource]
ReviewWriteAuthorizer = Callable[[Session, UUID, UUID, Principal], None]


@dataclass(frozen=True)
class ResourceArtifactRouterDeps:
    require_project_access: ProjectAccessAuthorizer
    require_project_member: ProjectMemberAuthorizer
    resolve_resource: ResourceResolver
    require_review_write: ReviewWriteAuthorizer


def context_artifact_read(
    session: Session, artifact: ContextArtifact, *, include_rows: bool = True
) -> ContextArtifactRead:
    sources: list[ContextArtifactSourceRead] = []
    citations: list[ContextArtifactCitationRead] = []
    if include_rows:
        source_rows = list(
            session.scalars(
                select(ContextArtifactSource)
                .where(ContextArtifactSource.context_artifact_id == artifact.id)
                .order_by(ContextArtifactSource.normalized_path.asc())
            )
        )
        sources = [
            ContextArtifactSourceRead(
                id=source.id,
                normalized_path=source.normalized_path,
                status=source.status,
                coverage_status=source.coverage_status,
                section_count=source.section_count,
                metadata_json=source.metadata_json,
            )
            for source in source_rows
        ]
        citation_rows = list(
            session.scalars(
                select(ContextArtifactCitation)
                .where(ContextArtifactCitation.context_artifact_id == artifact.id)
                .order_by(
                    ContextArtifactCitation.normalized_path.asc(),
                    ContextArtifactCitation.ordinal.asc(),
                )
            )
        )
        citations = [
            ContextArtifactCitationRead(
                id=citation.id,
                normalized_path=citation.normalized_path,
                ordinal=citation.ordinal,
                title=citation.title,
                content_hash=citation.content_hash,
                line_start=citation.line_start,
                line_end=citation.line_end,
            )
            for citation in citation_rows
        ]
    return ContextArtifactRead(
        id=artifact.id,
        resource_id=artifact.resource_id,
        source_snapshot_id=artifact.source_snapshot_id,
        resource_manifest_id=artifact.resource_manifest_id,
        artifact_type=artifact.artifact_type,
        artifact_revision=artifact.artifact_revision,
        status=artifact.status,
        artifact_hash=artifact.artifact_hash,
        title=artifact.title,
        summary=artifact.summary,
        coverage_json=artifact.coverage_json,
        validation_json=artifact.validation_json,
        error_message=artifact.error_message,
        review_comment=artifact.review_comment,
        approved_at=artifact.approved_at,
        rejected_at=artifact.rejected_at,
        created_at=artifact.created_at,
        sources=sources,
        citations=citations,
    )


def resolve_context_artifact(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    artifact_id: UUID,
    principal: Principal,
    deps: ResourceArtifactRouterDeps,
) -> ContextArtifact:
    artifact = session.scalar(
        select(ContextArtifact).where(
            ContextArtifact.id == artifact_id,
            ContextArtifact.workspace_id == workspace_id,
            ContextArtifact.project_id == project_id,
        )
    )
    if artifact is None or not token_allows_resource(principal, artifact.resource_id):
        raise HTTPException(status_code=404, detail="context artifact not found")
    deps.require_project_access(session, workspace_id, project_id, principal)
    return artifact


def create_router(deps: ResourceArtifactRouterDeps) -> APIRouter:
    router = APIRouter()

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/context-artifacts/resource-map",
        response_model=ContextArtifactRead,
    )
    def compile_resource_map_artifact(
        workspace_id: UUID,
        project_id: UUID,
        resource_id: UUID,
        force: bool = False,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> ContextArtifactRead:
        require_scope(principal, "resource:refresh")
        deps.require_project_member(
            session, workspace_id, project_id, principal, required_scopes={"resource:refresh"}
        )
        resource = deps.resolve_resource(session, workspace_id, project_id, resource_id, principal)
        if resource.type not in {"folder_bundle", "git"}:
            raise HTTPException(
                status_code=422,
                detail="Resource Map compile is only available for manifest-backed folder bundle or Git sources",
            )
        if resource.current_snapshot_id is None:
            raise HTTPException(status_code=409, detail="source has no current snapshot to compile")
        snapshot = session.scalar(
            select(SourceSnapshot).where(
                SourceSnapshot.id == resource.current_snapshot_id,
                SourceSnapshot.workspace_id == workspace_id,
                SourceSnapshot.project_id == project_id,
                SourceSnapshot.resource_id == resource.id,
            )
        )
        if snapshot is None:
            raise HTTPException(status_code=409, detail="source snapshot is missing")
        manifest = session.scalar(
            select(ResourceManifest).where(
                ResourceManifest.workspace_id == workspace_id,
                ResourceManifest.project_id == project_id,
                ResourceManifest.resource_id == resource.id,
                ResourceManifest.source_snapshot_id == snapshot.id,
            )
        )
        if manifest is None:
            raise HTTPException(
                status_code=409,
                detail="source manifest is missing; index the source before compiling a Resource Map",
            )
        build = build_resource_map(session, resource, manifest, snapshot)
        existing = latest_same_hash_artifact(session, resource, snapshot.id, build.artifact_hash)
        if existing is not None:
            if existing.status == "failed" and not force:
                raise HTTPException(
                    status_code=409,
                    detail={"message": existing.error_message, "artifact_id": str(existing.id)},
                )
            if not (force and existing.status in {"failed", "rejected"}):
                return context_artifact_read(session, existing)
        artifact = ContextArtifact(
            workspace_id=workspace_id,
            project_id=project_id,
            resource_id=resource.id,
            source_snapshot_id=snapshot.id,
            resource_manifest_id=manifest.id,
            artifact_type=ARTIFACT_TYPE_RESOURCE_MAP,
            artifact_revision=next_artifact_revision(
                session, resource, snapshot.id, build.artifact_hash
            ),
            status=build.status,
            artifact_hash=build.artifact_hash,
            title=build.title,
            summary=build.summary,
            content_json=build.content_json,
            coverage_json=build.coverage_json,
            validation_json=build.validation_json,
            error_message=build.error_message,
            created_by=principal.user.id,
        )
        session.add(artifact)
        session.flush()
        sources_by_file_id: dict[UUID, ContextArtifactSource] = {}
        for source_input in build.sources:
            source = ContextArtifactSource(
                workspace_id=workspace_id,
                project_id=project_id,
                context_artifact_id=artifact.id,
                resource_id=resource.id,
                source_snapshot_id=snapshot.id,
                resource_manifest_id=manifest.id,
                resource_manifest_file_id=source_input["resource_manifest_file_id"],
                normalized_path=source_input["normalized_path"],
                status=source_input["status"],
                section_count=source_input["section_count"],
                coverage_status=source_input["coverage_status"],
                metadata_json=source_input["metadata_json"],
            )
            session.add(source)
            sources_by_file_id[source.resource_manifest_file_id] = source
        session.flush()
        for citation_input in build.citations:
            citation_source = sources_by_file_id.get(citation_input["resource_manifest_file_id"])
            if citation_source is None:
                continue
            session.add(
                ContextArtifactCitation(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    context_artifact_id=artifact.id,
                    context_artifact_source_id=citation_source.id,
                    resource_id=resource.id,
                    section_family_resource_id=citation_input["section_family_resource_id"],
                    source_snapshot_id=snapshot.id,
                    resource_manifest_id=manifest.id,
                    resource_manifest_file_id=citation_input["resource_manifest_file_id"],
                    section_id=citation_input["section_id"],
                    snapshot_section_id=citation_input["snapshot_section_id"],
                    normalized_path=citation_input["normalized_path"],
                    ordinal=citation_input["ordinal"],
                    title=citation_input["title"],
                    content_hash=citation_input["content_hash"],
                    line_start=citation_input["line_start"],
                    line_end=citation_input["line_end"],
                )
            )
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="context_artifact.compile",
                target_type="context_artifact",
                target_id=artifact.id,
                meta={"artifact_type": artifact.artifact_type, "status": artifact.status},
            )
        )
        session.commit()
        if artifact.status == "failed":
            raise HTTPException(
                status_code=409,
                detail={"message": artifact.error_message, "artifact_id": str(artifact.id)},
            )
        return context_artifact_read(session, artifact)

    @router.get(
        "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/context-artifacts",
        response_model=list[ContextArtifactRead],
    )
    def list_resource_context_artifacts(
        workspace_id: UUID,
        project_id: UUID,
        resource_id: UUID,
        artifact_type: str | None = None,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> list[ContextArtifactRead]:
        require_scope(principal, "resource:read")
        deps.require_project_access(session, workspace_id, project_id, principal)
        deps.resolve_resource(session, workspace_id, project_id, resource_id, principal)
        predicates = [
            ContextArtifact.workspace_id == workspace_id,
            ContextArtifact.project_id == project_id,
            ContextArtifact.resource_id == resource_id,
        ]
        if artifact_type:
            predicates.append(ContextArtifact.artifact_type == artifact_type)
        rows = list(
            session.scalars(
                select(ContextArtifact)
                .where(*predicates)
                .order_by(ContextArtifact.created_at.desc())
                .limit(20)
            )
        )
        return [context_artifact_read(session, artifact, include_rows=False) for artifact in rows]

    @router.get(
        "/workspaces/{workspace_id}/projects/{project_id}/context-artifacts/{artifact_id}",
        response_model=ContextArtifactRead,
    )
    def get_context_artifact(
        workspace_id: UUID,
        project_id: UUID,
        artifact_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> ContextArtifactRead:
        require_scope(principal, "resource:read")
        artifact = resolve_context_artifact(
            session, workspace_id, project_id, artifact_id, principal, deps
        )
        return context_artifact_read(session, artifact)

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/context-artifacts/{artifact_id}/approve",
        response_model=ContextArtifactRead,
    )
    def approve_context_artifact(
        workspace_id: UUID,
        project_id: UUID,
        artifact_id: UUID,
        payload: ArtifactApprovalRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> ContextArtifactRead:
        deps.require_review_write(session, workspace_id, project_id, principal)
        artifact = resolve_context_artifact(
            session, workspace_id, project_id, artifact_id, principal, deps
        )
        if artifact.status != "draft":
            raise HTTPException(status_code=409, detail="only draft artifacts can be approved")
        warnings = (
            artifact.validation_json.get("warnings")
            if isinstance(artifact.validation_json, dict)
            else []
        )
        errors = (
            artifact.validation_json.get("errors")
            if isinstance(artifact.validation_json, dict)
            else []
        )
        if errors:
            raise HTTPException(status_code=422, detail="artifact validation errors block approval")
        if warnings and not payload.acknowledge_warnings:
            raise HTTPException(
                status_code=422,
                detail={"message": "warnings require acknowledgement", "warnings": warnings},
            )
        artifact.status = "approved"
        artifact.approved_by = principal.user.id
        artifact.approved_at = datetime.now(UTC)
        artifact.review_comment = payload.comment
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="context_artifact.approve",
                target_type="context_artifact",
                target_id=artifact.id,
            )
        )
        session.commit()
        return context_artifact_read(session, artifact)

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/context-artifacts/{artifact_id}/reject",
        response_model=ContextArtifactRead,
    )
    def reject_context_artifact(
        workspace_id: UUID,
        project_id: UUID,
        artifact_id: UUID,
        payload: ArtifactRejectRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> ContextArtifactRead:
        deps.require_review_write(session, workspace_id, project_id, principal)
        artifact = resolve_context_artifact(
            session, workspace_id, project_id, artifact_id, principal, deps
        )
        if artifact.status != "draft":
            raise HTTPException(status_code=409, detail="only draft artifacts can be rejected")
        artifact.status = "rejected"
        artifact.rejected_by = principal.user.id
        artifact.rejected_at = datetime.now(UTC)
        artifact.review_comment = payload.reason.strip()
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="context_artifact.reject",
                target_type="context_artifact",
                target_id=artifact.id,
            )
        )
        session.commit()
        return context_artifact_read(session, artifact)

    return router
