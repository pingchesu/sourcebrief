from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal, require_principal, require_scope
from sourcebrief_api.context_packs import (
    PACK_STATUS_PUBLISHED,
    PACK_STATUS_ROLLED_BACK,
    PACK_STATUS_SUPERSEDED,
)
from sourcebrief_api.repo_agents import (
    REPO_AGENT_STATUS_ACTIVE,
    REPO_AGENT_STATUS_ARCHIVED,
    REPO_AGENT_VERSION_DRAFT,
    REPO_AGENT_VERSION_FAILED,
    REPO_AGENT_VERSION_INVALIDATED,
    REPO_AGENT_VERSION_PUBLISHED,
    REPO_AGENT_VERSION_SUPERSEDED,
    compile_repo_agent_version,
    normalize_agent_key,
)
from sourcebrief_api.schemas import (
    RepoAgentActionRequest,
    RepoAgentCreateRequest,
    RepoAgentRead,
    RepoAgentRefreshResponse,
    RepoAgentVersionRead,
)
from sourcebrief_api.skill_exports import SKILL_EXPORT_STATUS_APPROVED
from sourcebrief_shared.db import get_session
from sourcebrief_shared.models import (
    AuditEvent,
    ContextPackVersion,
    RepoAgent,
    RepoAgentVersion,
    Resource,
    SkillExport,
)

ProjectMemberAuthorizer = Callable[..., object]
ResourceResolver = Callable[..., Resource]
ReviewWriteAuthorizer = Callable[[Session, UUID, UUID, Principal], None]


@dataclass(frozen=True)
class RepoAgentRouterDeps:
    require_project_member: ProjectMemberAuthorizer
    resolve_resource: ResourceResolver
    require_review_write: ReviewWriteAuthorizer


def repo_agent_version_read(version: RepoAgentVersion) -> RepoAgentVersionRead:
    return RepoAgentVersionRead(
        id=version.id,
        repo_agent_id=version.repo_agent_id,
        resource_id=version.resource_id,
        version=version.version,
        status=version.status,
        source_snapshot_id=version.source_snapshot_id,
        resource_manifest_id=version.resource_manifest_id,
        context_pack_version_id=version.context_pack_version_id,
        skill_export_id=version.skill_export_id,
        version_hash=version.version_hash,
        summary_json=version.summary_json,
        diff_json=version.diff_json,
        validation_json=version.validation_json,
        install_json=version.install_json,
        rollback_from_version_id=version.rollback_from_version_id,
        status_reason=version.status_reason,
        created_at=version.created_at,
        published_at=version.published_at,
        scrubbed_at=version.scrubbed_at,
    )


def repo_agent_read(session: Session, agent: RepoAgent) -> RepoAgentRead:
    versions = list(
        session.scalars(
            select(RepoAgentVersion)
            .where(RepoAgentVersion.repo_agent_id == agent.id)
            .order_by(RepoAgentVersion.version.desc())
        )
    )
    current = next(
        (version for version in versions if version.id == agent.current_version_id), None
    )
    return RepoAgentRead(
        id=agent.id,
        workspace_id=agent.workspace_id,
        project_id=agent.project_id,
        resource_id=agent.resource_id,
        agent_key=agent.agent_key,
        pack_key=agent.pack_key,
        title=agent.title,
        description=agent.description,
        status=agent.status,
        update_policy_json=agent.update_policy_json,
        current_version_id=agent.current_version_id,
        current=repo_agent_version_read(current) if current else None,
        versions=[repo_agent_version_read(version) for version in versions],
        created_at=agent.created_at,
        updated_at=agent.updated_at,
    )


def resolve_repo_agent(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    agent_key: str,
    *,
    for_update: bool = False,
) -> RepoAgent:
    stmt = select(RepoAgent).where(
        RepoAgent.workspace_id == workspace_id,
        RepoAgent.project_id == project_id,
        RepoAgent.agent_key == agent_key,
    )
    if for_update:
        stmt = stmt.with_for_update()
    agent = session.scalar(stmt)
    if agent is None:
        raise HTTPException(status_code=404, detail="repo agent not found")
    return agent


def repo_agent_resource_allowed(
    session: Session, agent: RepoAgent, principal: Principal, deps: RepoAgentRouterDeps
) -> Resource | None:
    if agent.resource_id is None:
        if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
            raise HTTPException(status_code=404, detail="repo agent not found")
        return None
    return deps.resolve_resource(
        session,
        agent.workspace_id,
        agent.project_id,
        agent.resource_id,
        principal,
        include_deleted=True,
    )


def require_repo_agent_read(
    session: Session, agent: RepoAgent, principal: Principal, deps: RepoAgentRouterDeps
) -> Resource | None:
    require_scope(principal, "resource:read")
    deps.require_project_member(
        session, agent.workspace_id, agent.project_id, principal, required_scopes={"resource:read"}
    )
    return repo_agent_resource_allowed(session, agent, principal, deps)


def require_repo_agent_write(
    session: Session, agent: RepoAgent, principal: Principal, deps: RepoAgentRouterDeps
) -> Resource | None:
    require_scope(principal, "resource:write")
    deps.require_project_member(
        session, agent.workspace_id, agent.project_id, principal, required_scopes={"resource:write"}
    )
    if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
        raise HTTPException(
            status_code=403, detail="resource-scoped tokens cannot mutate repo agents"
        )
    return repo_agent_resource_allowed(session, agent, principal, deps)


def require_repo_agent_review_write(
    session: Session, agent: RepoAgent, principal: Principal, deps: RepoAgentRouterDeps
) -> Resource | None:
    deps.require_review_write(session, agent.workspace_id, agent.project_id, principal)
    if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
        raise HTTPException(
            status_code=403,
            detail="resource-scoped tokens cannot publish, rollback, archive, invalidate, or scrub repo agents",
        )
    return repo_agent_resource_allowed(session, agent, principal, deps)


def assert_repo_agent_active(agent: RepoAgent) -> None:
    if agent.status == REPO_AGENT_STATUS_ARCHIVED:
        raise HTTPException(
            status_code=422,
            detail="archived repo agents cannot create or publish retained versions",
        )


def validate_repo_agent_version_dependencies_for_publish(
    session: Session, version: RepoAgentVersion
) -> None:
    pack = (
        session.get(ContextPackVersion, version.context_pack_version_id)
        if version.context_pack_version_id
        else None
    )
    allowed_pack_statuses = {PACK_STATUS_PUBLISHED}
    if version.rollback_from_version_id:
        allowed_pack_statuses = {
            PACK_STATUS_PUBLISHED,
            PACK_STATUS_SUPERSEDED,
            PACK_STATUS_ROLLED_BACK,
        }
    if pack is None or pack.status not in allowed_pack_statuses:
        raise HTTPException(
            status_code=422,
            detail="repo agent draft references a Context Pack that is no longer publishable; refresh or create a rollback draft again",
        )
    if version.skill_export_id:
        skill_export = session.get(SkillExport, version.skill_export_id)
        if (
            skill_export is None
            or skill_export.status != SKILL_EXPORT_STATUS_APPROVED
            or not skill_export.files_json
        ):
            raise HTTPException(
                status_code=422,
                detail="repo agent draft references a generated skill export that is no longer approved/retained; refresh the draft",
            )


def validate_repo_agent_version_dependencies_for_rollback_target(
    session: Session, version: RepoAgentVersion
) -> None:
    pack = (
        session.get(ContextPackVersion, version.context_pack_version_id)
        if version.context_pack_version_id
        else None
    )
    if pack is None or pack.status not in {
        PACK_STATUS_PUBLISHED,
        PACK_STATUS_SUPERSEDED,
        PACK_STATUS_ROLLED_BACK,
    }:
        raise HTTPException(
            status_code=422,
            detail="rollback target references a Context Pack that is no longer retained",
        )
    if version.skill_export_id:
        skill_export = session.get(SkillExport, version.skill_export_id)
        if (
            skill_export is None
            or skill_export.status != SKILL_EXPORT_STATUS_APPROVED
            or not skill_export.files_json
        ):
            raise HTTPException(
                status_code=422,
                detail="rollback target references a generated skill export that is no longer approved/retained",
            )


def create_router(deps: RepoAgentRouterDeps) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/workspaces/{workspace_id}/projects/{project_id}/repo-agents",
        response_model=list[RepoAgentRead],
    )
    def list_repo_agents(
        workspace_id: UUID,
        project_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> list[RepoAgentRead]:
        require_scope(principal, "resource:read")
        deps.require_project_member(
            session, workspace_id, project_id, principal, required_scopes={"resource:read"}
        )
        agents = list(
            session.scalars(
                select(RepoAgent)
                .where(RepoAgent.workspace_id == workspace_id, RepoAgent.project_id == project_id)
                .order_by(RepoAgent.created_at.desc())
            )
        )
        visible = []
        for agent in agents:
            try:
                repo_agent_resource_allowed(session, agent, principal, deps)
            except HTTPException:
                continue
            visible.append(repo_agent_read(session, agent))
        return visible

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/repo-agent",
        response_model=RepoAgentRead,
    )
    def create_repo_agent(
        workspace_id: UUID,
        project_id: UUID,
        resource_id: UUID,
        payload: RepoAgentCreateRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> RepoAgentRead:
        require_scope(principal, "resource:write")
        if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
            raise HTTPException(
                status_code=403, detail="resource-scoped tokens cannot create repo agents"
            )
        deps.require_project_member(
            session, workspace_id, project_id, principal, required_scopes={"resource:write"}
        )
        resource = deps.resolve_resource(session, workspace_id, project_id, resource_id, principal)
        if resource.type.lower() != "git":
            raise HTTPException(status_code=422, detail="Repo Agent V0 requires a Git resource")
        try:
            key = normalize_agent_key(payload.agent_key or resource.name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        agent = RepoAgent(
            workspace_id=workspace_id,
            project_id=project_id,
            resource_id=resource_id,
            agent_key=key,
            pack_key=payload.pack_key,
            title=payload.title or f"{resource.name} Repo Agent",
            description=payload.description,
            status=REPO_AGENT_STATUS_ACTIVE,
            update_policy_json={"mode": "manual"},
            created_by=principal.user.id,
        )
        session.add(agent)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=409, detail="repo agent already exists for this key or source/pack"
            ) from exc
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="repo_agent.create",
                target_type="repo_agent",
                target_id=agent.id,
                meta={
                    "agent_key": agent.agent_key,
                    "resource_id": str(resource_id),
                    "pack_key": agent.pack_key,
                },
            )
        )
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(
                status_code=409, detail="repo agent already exists for this key or source/pack"
            ) from exc
        return repo_agent_read(session, agent)

    @router.get(
        "/workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}",
        response_model=RepoAgentRead,
    )
    def get_repo_agent(
        workspace_id: UUID,
        project_id: UUID,
        agent_key: str,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> RepoAgentRead:
        agent = resolve_repo_agent(session, workspace_id, project_id, agent_key)
        require_repo_agent_read(session, agent, principal, deps)
        return repo_agent_read(session, agent)

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}/refresh",
        response_model=RepoAgentRefreshResponse,
    )
    def refresh_repo_agent(
        workspace_id: UUID,
        project_id: UUID,
        agent_key: str,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> RepoAgentRefreshResponse:
        agent = resolve_repo_agent(session, workspace_id, project_id, agent_key, for_update=True)
        resource = require_repo_agent_write(session, agent, principal, deps)
        assert_repo_agent_active(agent)
        result = compile_repo_agent_version(session, agent, resource, actor_id=principal.user.id)
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="repo_agent.refresh",
                target_type="repo_agent",
                target_id=agent.id,
                meta={
                    "agent_key": agent.agent_key,
                    "version": result.version.version,
                    "unchanged": result.unchanged,
                },
            )
        )
        session.commit()
        return RepoAgentRefreshResponse(
            status="unchanged" if result.unchanged else result.version.status,
            unchanged=result.unchanged,
            version=repo_agent_version_read(result.version),
        )

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}/versions/{version_number}/publish",
        response_model=RepoAgentRead,
    )
    def publish_repo_agent_version(
        workspace_id: UUID,
        project_id: UUID,
        agent_key: str,
        version_number: int,
        payload: RepoAgentActionRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> RepoAgentRead:
        agent = resolve_repo_agent(session, workspace_id, project_id, agent_key, for_update=True)
        require_repo_agent_review_write(session, agent, principal, deps)
        assert_repo_agent_active(agent)
        version = session.scalar(
            select(RepoAgentVersion)
            .where(
                RepoAgentVersion.repo_agent_id == agent.id,
                RepoAgentVersion.version == version_number,
            )
            .with_for_update()
        )
        if version is None:
            raise HTTPException(status_code=404, detail="repo agent version not found")
        if version.status != REPO_AGENT_VERSION_DRAFT:
            raise HTTPException(
                status_code=422, detail="only draft repo agent versions can be published"
            )
        latest_draft = session.scalar(
            select(func.max(RepoAgentVersion.version)).where(
                RepoAgentVersion.repo_agent_id == agent.id,
                RepoAgentVersion.status == REPO_AGENT_VERSION_DRAFT,
            )
        )
        if latest_draft and version.version < latest_draft:
            raise HTTPException(
                status_code=409, detail="older drafts cannot be published; refresh/regenerate first"
            )
        if not version.validation_json.get("ok"):
            raise HTTPException(
                status_code=422, detail="repo agent version validation must pass before publish"
            )
        validate_repo_agent_version_dependencies_for_publish(session, version)
        current = (
            session.get(RepoAgentVersion, agent.current_version_id)
            if agent.current_version_id
            else None
        )
        if current and current.status == REPO_AGENT_VERSION_PUBLISHED:
            current.status = REPO_AGENT_VERSION_SUPERSEDED
            current.status_reason = f"Superseded by v{version.version}: {payload.comment}"
        version.status = REPO_AGENT_VERSION_PUBLISHED
        version.published_by = principal.user.id
        version.published_at = datetime.now(UTC)
        version.status_reason = payload.comment
        agent.current_version_id = version.id
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="repo_agent_version.publish",
                target_type="repo_agent_version",
                target_id=version.id,
                meta={"agent_key": agent.agent_key, "version": version.version},
            )
        )
        session.commit()
        return repo_agent_read(session, agent)

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}/versions/{version_number}/rollback-draft",
        response_model=RepoAgentRefreshResponse,
    )
    def create_repo_agent_rollback_draft(
        workspace_id: UUID,
        project_id: UUID,
        agent_key: str,
        version_number: int,
        payload: RepoAgentActionRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> RepoAgentRefreshResponse:
        agent = resolve_repo_agent(session, workspace_id, project_id, agent_key, for_update=True)
        resource = require_repo_agent_review_write(session, agent, principal, deps)
        assert_repo_agent_active(agent)
        target = session.scalar(
            select(RepoAgentVersion).where(
                RepoAgentVersion.repo_agent_id == agent.id,
                RepoAgentVersion.version == version_number,
            )
        )
        if (
            target is None
            or target.status not in {REPO_AGENT_VERSION_PUBLISHED, REPO_AGENT_VERSION_SUPERSEDED}
            or target.scrubbed_at is not None
        ):
            raise HTTPException(
                status_code=422,
                detail="rollback target must be retained published or superseded version",
            )
        validate_repo_agent_version_dependencies_for_rollback_target(session, target)
        result = compile_repo_agent_version(
            session, agent, resource, actor_id=principal.user.id, rollback_from=target
        )
        result.version.status_reason = f"Rollback draft from v{target.version}: {payload.comment}"
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="repo_agent_version.rollback_draft",
                target_type="repo_agent_version",
                target_id=result.version.id,
                meta={"agent_key": agent.agent_key, "target_version": target.version},
            )
        )
        session.commit()
        return RepoAgentRefreshResponse(
            status="unchanged" if result.unchanged else result.version.status,
            unchanged=result.unchanged,
            version=repo_agent_version_read(result.version),
        )

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}/archive",
        response_model=RepoAgentRead,
    )
    def archive_repo_agent(
        workspace_id: UUID,
        project_id: UUID,
        agent_key: str,
        payload: RepoAgentActionRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> RepoAgentRead:
        agent = resolve_repo_agent(session, workspace_id, project_id, agent_key, for_update=True)
        require_repo_agent_review_write(session, agent, principal, deps)
        agent.status = REPO_AGENT_STATUS_ARCHIVED
        retained_versions = session.scalar(
            select(func.count())
            .select_from(RepoAgentVersion)
            .where(RepoAgentVersion.repo_agent_id == agent.id)
        )
        if not retained_versions:
            agent.resource_id = None
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="repo_agent.archive",
                target_type="repo_agent",
                target_id=agent.id,
                meta={
                    "agent_key": agent.agent_key,
                    "comment": payload.comment,
                    "zero_version_tombstone": not bool(retained_versions),
                },
            )
        )
        session.commit()
        return repo_agent_read(session, agent)

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}/versions/{version_number}/invalidate",
        response_model=RepoAgentRead,
    )
    def invalidate_repo_agent_version(
        workspace_id: UUID,
        project_id: UUID,
        agent_key: str,
        version_number: int,
        payload: RepoAgentActionRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> RepoAgentRead:
        agent = resolve_repo_agent(session, workspace_id, project_id, agent_key, for_update=True)
        require_repo_agent_review_write(session, agent, principal, deps)
        version = session.scalar(
            select(RepoAgentVersion)
            .where(
                RepoAgentVersion.repo_agent_id == agent.id,
                RepoAgentVersion.version == version_number,
            )
            .with_for_update()
        )
        if version is None:
            raise HTTPException(status_code=404, detail="repo agent version not found")
        if (
            version.status == REPO_AGENT_VERSION_PUBLISHED
            and agent.current_version_id == version.id
            and agent.status != REPO_AGENT_STATUS_ARCHIVED
        ):
            raise HTTPException(
                status_code=422,
                detail="archive the repo agent or publish another version before invalidating current",
            )
        version.status = REPO_AGENT_VERSION_INVALIDATED
        version.status_reason = payload.comment
        if agent.current_version_id == version.id:
            agent.current_version_id = None
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="repo_agent_version.invalidate",
                target_type="repo_agent_version",
                target_id=version.id,
                meta={"agent_key": agent.agent_key, "version": version.version},
            )
        )
        session.commit()
        return repo_agent_read(session, agent)

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}/versions/{version_number}/scrub",
        response_model=RepoAgentRead,
    )
    def scrub_repo_agent_version(
        workspace_id: UUID,
        project_id: UUID,
        agent_key: str,
        version_number: int,
        payload: RepoAgentActionRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> RepoAgentRead:
        agent = resolve_repo_agent(session, workspace_id, project_id, agent_key, for_update=True)
        require_repo_agent_review_write(session, agent, principal, deps)
        if agent.status != REPO_AGENT_STATUS_ARCHIVED:
            raise HTTPException(
                status_code=422, detail="archive repo agent before scrubbing versions"
            )
        repo_agent_resource_allowed(session, agent, principal, deps)
        version = session.scalar(
            select(RepoAgentVersion)
            .where(
                RepoAgentVersion.repo_agent_id == agent.id,
                RepoAgentVersion.version == version_number,
            )
            .with_for_update()
        )
        if version is None:
            raise HTTPException(status_code=404, detail="repo agent version not found")
        if version.status not in {REPO_AGENT_VERSION_INVALIDATED, REPO_AGENT_VERSION_FAILED}:
            raise HTTPException(
                status_code=422, detail="only invalidated or failed versions can be scrubbed"
            )
        version.summary_json = {"scrubbed": True, "reason": payload.comment}
        version.diff_json = {"scrubbed": True}
        version.validation_json = {"scrubbed": True}
        version.install_json = {"scrubbed": True}
        version.resource_id = None
        version.source_snapshot_id = None
        version.resource_manifest_id = None
        version.context_pack_version_id = None
        version.skill_export_id = None
        version.scrubbed_at = datetime.now(UTC)
        remaining = session.scalar(
            select(func.count())
            .select_from(RepoAgentVersion)
            .where(
                RepoAgentVersion.repo_agent_id == agent.id,
                RepoAgentVersion.resource_id.is_not(None),
                RepoAgentVersion.id != version.id,
            )
        )
        if not remaining:
            agent.resource_id = None
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="repo_agent_version.scrub",
                target_type="repo_agent_version",
                target_id=version.id,
                meta={"agent_key": agent.agent_key, "version": version.version},
            )
        )
        session.commit()
        return repo_agent_read(session, agent)

    return router
