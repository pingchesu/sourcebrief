from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal, require_principal, require_scope, token_allows_resource
from sourcebrief_api.schemas import (
    AgentFilesResponse,
    GitResourceEnvRead,
    GitResourceEnvUpdate,
    RuntimeInstallPlanRequest,
    RuntimeInstallPlanResponse,
)
from sourcebrief_shared.db import get_session
from sourcebrief_shared.lifecycle import compute_next_refresh_at
from sourcebrief_shared.models import AgentProfile, AuditEvent, Project, Resource

ProjectAccessGetter = Callable[[Session, UUID, UUID, Principal], Project]
ProjectMemberGetter = Callable[..., Project]
AgentProfileEnsurer = Callable[[Session, UUID, Project, UUID], AgentProfile]
ProjectResourcesGetter = Callable[[Session, UUID, UUID], list[Resource]]
AgentFilesBuilder = Callable[[Session, UUID, Project, AgentProfile, list[Resource]], AgentFilesResponse]
RuntimePlanBuilder = Callable[[Session, UUID, UUID, RuntimeInstallPlanRequest, Principal], RuntimeInstallPlanResponse]
AgentPackPreparer = Callable[[Session, UUID, UUID, Principal], tuple[Project, dict[str, Any]]]
ManifestTextBuilder = Callable[[dict[str, Any]], str]
McpJsonBuilder = Callable[[dict[str, Any]], dict[str, Any]]
ZipBytesBuilder = Callable[[dict[str, Any]], bytes]
ManifestDigestBuilder = Callable[[dict[str, Any]], str]
ResourceResolver = Callable[[Session, UUID, UUID, UUID, Principal], Resource]
SourceConfigValidator = Callable[[str, str, dict], dict]
GitEnvReader = Callable[[Resource], GitResourceEnvRead]


@dataclass(frozen=True)
class RuntimeAgentRouterDeps:
    require_project_access: ProjectAccessGetter
    require_project_member: ProjectMemberGetter
    ensure_agent_profile: AgentProfileEnsurer
    current_project_resources: ProjectResourcesGetter
    agent_file_response: AgentFilesBuilder
    runtime_plan_response: RuntimePlanBuilder
    agent_pack_prepare: AgentPackPreparer
    agent_pack_manifest_yaml: ManifestTextBuilder
    agent_pack_hermes_skill: ManifestTextBuilder
    agent_pack_codex_agents: ManifestTextBuilder
    agent_pack_claude_md: ManifestTextBuilder
    agent_pack_mcp_json: McpJsonBuilder
    agent_pack_zip_bytes: ZipBytesBuilder
    agent_pack_manifest_digest: ManifestDigestBuilder
    resolve_resource: ResourceResolver
    validate_source_config: SourceConfigValidator
    git_env_read: GitEnvReader


def create_router(deps: RuntimeAgentRouterDeps) -> APIRouter:
    router = APIRouter(tags=["runtime-agent"])

    @router.get(
        "/workspaces/{workspace_id}/projects/{project_id}/agent-files",
        response_model=AgentFilesResponse,
    )
    def get_agent_files(
        workspace_id: UUID,
        project_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> AgentFilesResponse:
        require_scope(principal, "project:read")
        project = deps.require_project_access(session, workspace_id, project_id, principal)
        profile = deps.ensure_agent_profile(session, workspace_id, project, principal.user.id)
        resources = [
            resource
            for resource in deps.current_project_resources(session, workspace_id, project_id)
            if token_allows_resource(principal, resource.id)
        ]
        session.commit()
        return deps.agent_file_response(session, workspace_id, project, profile, resources)

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/agent-files/regenerate",
        response_model=AgentFilesResponse,
    )
    def regenerate_agent_files(
        workspace_id: UUID,
        project_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> AgentFilesResponse:
        require_scope(principal, "resource:refresh")
        project = deps.require_project_member(session, workspace_id, project_id, principal, required_scopes={"resource:refresh"})
        profile = deps.ensure_agent_profile(session, workspace_id, project, principal.user.id)
        resources = [
            resource
            for resource in deps.current_project_resources(session, workspace_id, project_id)
            if token_allows_resource(principal, resource.id)
        ]
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="agent_files.regenerate",
                target_type="project",
                target_id=project_id,
                meta={"resource_count": len(resources), "repo_agent_count": len([r for r in resources if r.type.lower() == "git"])},
            )
        )
        session.commit()
        return deps.agent_file_response(session, workspace_id, project, profile, resources)

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/runtime-install-plan",
        response_model=RuntimeInstallPlanResponse,
    )
    def runtime_install_plan(
        workspace_id: UUID,
        project_id: UUID,
        payload: RuntimeInstallPlanRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> RuntimeInstallPlanResponse:
        return deps.runtime_plan_response(session, workspace_id, project_id, payload, principal)

    @router.get("/workspaces/{workspace_id}/projects/{project_id}/agent-pack/manifest")
    def get_agent_pack_manifest(
        workspace_id: UUID,
        project_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> PlainTextResponse:
        _, manifest = deps.agent_pack_prepare(session, workspace_id, project_id, principal)
        return PlainTextResponse(deps.agent_pack_manifest_yaml(manifest), media_type="application/x-yaml")

    @router.get("/workspaces/{workspace_id}/projects/{project_id}/agent-pack/hermes/SKILL.md")
    def get_agent_pack_hermes_skill(
        workspace_id: UUID,
        project_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> PlainTextResponse:
        _, manifest = deps.agent_pack_prepare(session, workspace_id, project_id, principal)
        return PlainTextResponse(deps.agent_pack_hermes_skill(manifest), media_type="text/markdown")

    @router.get("/workspaces/{workspace_id}/projects/{project_id}/agent-pack/codex/AGENTS.md")
    def get_agent_pack_codex_agents(
        workspace_id: UUID,
        project_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> PlainTextResponse:
        _, manifest = deps.agent_pack_prepare(session, workspace_id, project_id, principal)
        return PlainTextResponse(deps.agent_pack_codex_agents(manifest), media_type="text/markdown")

    @router.get("/workspaces/{workspace_id}/projects/{project_id}/agent-pack/claude/CLAUDE.md")
    def get_agent_pack_claude_md(
        workspace_id: UUID,
        project_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> PlainTextResponse:
        _, manifest = deps.agent_pack_prepare(session, workspace_id, project_id, principal)
        return PlainTextResponse(deps.agent_pack_claude_md(manifest), media_type="text/markdown")

    @router.get("/workspaces/{workspace_id}/projects/{project_id}/agent-pack/mcp.json")
    def get_agent_pack_mcp_json(
        workspace_id: UUID,
        project_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> JSONResponse:
        _, manifest = deps.agent_pack_prepare(session, workspace_id, project_id, principal)
        return JSONResponse(deps.agent_pack_mcp_json(manifest))

    @router.get("/workspaces/{workspace_id}/projects/{project_id}/agent-pack.zip")
    def get_agent_pack_zip(
        workspace_id: UUID,
        project_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> Response:
        project, manifest = deps.agent_pack_prepare(session, workspace_id, project_id, principal)
        identity = cast_mapping(manifest["identity"])
        content = deps.agent_pack_zip_bytes(manifest)
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="agent_pack.download",
                target_type="project",
                target_id=project.id,
                meta={"artifact": "zip", "manifest_digest": deps.agent_pack_manifest_digest(manifest)},
            )
        )
        session.commit()
        filename = f"{identity['slug']}-skill-pack.zip"
        return Response(
            content,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @router.get(
        "/workspaces/{workspace_id}/projects/{project_id}/git-env",
        response_model=list[GitResourceEnvRead],
    )
    def list_git_env(
        workspace_id: UUID,
        project_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> list[GitResourceEnvRead]:
        require_scope(principal, "resource:read")
        deps.require_project_access(session, workspace_id, project_id, principal)
        resources = [
            resource
            for resource in deps.current_project_resources(session, workspace_id, project_id)
            if resource.type.lower() == "git" and token_allows_resource(principal, resource.id)
        ]
        return [deps.git_env_read(resource) for resource in resources]

    @router.patch(
        "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/git-env",
        response_model=GitResourceEnvRead,
    )
    def update_git_env(
        workspace_id: UUID,
        project_id: UUID,
        resource_id: UUID,
        payload: GitResourceEnvUpdate,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> GitResourceEnvRead:
        require_scope(principal, "resource:write")
        deps.require_project_member(session, workspace_id, project_id, principal, required_scopes={"resource:write"})
        resource = deps.resolve_resource(session, workspace_id, project_id, resource_id, principal)
        if resource.type.lower() != "git":
            raise HTTPException(status_code=422, detail="git env can only be configured for git resources")
        fields = payload.model_dump(exclude_unset=True)
        source_config = dict(resource.source_config or {})
        source_config.setdefault("url", resource.uri)
        for key in ("branch", "auth_token_env", "clone_timeout", "max_file_bytes", "max_repo_files", "max_repo_bytes"):
            if key in fields:
                value = fields[key]
                if value is None or value == "":
                    source_config.pop(key, None)
                else:
                    source_config[key] = value
        if "update_frequency" in fields and fields["update_frequency"] is not None:
            resource.update_frequency = fields["update_frequency"]
        resource.source_config = deps.validate_source_config(resource.type, resource.uri, source_config)
        resource.next_refresh_at = compute_next_refresh_at(resource)
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="resource.git_env.update",
                target_type="resource",
                target_id=resource.id,
                meta={"fields": sorted(fields.keys())},
            )
        )
        session.commit()
        return deps.git_env_read(resource)

    return router


def cast_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}
