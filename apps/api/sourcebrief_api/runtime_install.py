from __future__ import annotations

import json
import os
import shlex
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from sourcebrief_api.agent_packs import file_slug
from sourcebrief_api.auth import Principal, require_scope, token_allows_resource
from sourcebrief_api.schemas import (
    RuntimeInstallPlanCapability,
    RuntimeInstallPlanConfig,
    RuntimeInstallPlanEndpoint,
    RuntimeInstallPlanRequest,
    RuntimeInstallPlanResource,
    RuntimeInstallPlanResponse,
    RuntimeInstallPlanScope,
)
from sourcebrief_shared.models import AgentProfile, Project, Resource

RUNTIME_INSTALL_REQUIRED_SCOPES = ["project:read", "project:query", "resource:read", "review:read", "code:read"]
RUNTIME_INSTALL_CORE_TOOLS = {
    "sourcebrief.get_agent_context",
    "sourcebrief.search",
    "sourcebrief.read_section",
    "sourcebrief.search_code",
    "sourcebrief.grep_code",
    "sourcebrief.read_file",
    "sourcebrief.find_symbol",
}
RUNTIME_INSTALL_OPTIONAL_TOOLS = {"sourcebrief.generate_patch", "sourcebrief.open_pr"}

ProjectAccessGetter = Callable[[Session, UUID, UUID, Principal], Project]
AgentProfileEnsurer = Callable[[Session, UUID, Project, UUID], AgentProfile]
CurrentProjectResourcesGetter = Callable[[Session, UUID, UUID], list[Resource]]
ResourceResolver = Callable[[Session, UUID, UUID, UUID, Principal], Resource]
EffectiveResourceIdsResolver = Callable[[Principal, list[UUID] | None], list[UUID] | None]
EmptyScopeChecker = Callable[[list[UUID] | None], bool]
MetadataSanitizer = Callable[[str | None], str]
McpToolsGetter = Callable[[], list[dict[str, Any]]]
ToolPolicyChecker = Callable[[AgentProfile | None], bool]


@dataclass(frozen=True)
class RuntimeInstallDependencies:
    require_project_access: ProjectAccessGetter
    ensure_agent_profile: AgentProfileEnsurer
    current_project_resources: CurrentProjectResourcesGetter
    resolve_resource: ResourceResolver
    effective_resource_ids: EffectiveResourceIdsResolver
    is_empty_scope: EmptyScopeChecker
    sanitize_metadata_text: MetadataSanitizer
    mcp_tools: McpToolsGetter
    tool_policy_patch_generation_enabled: ToolPolicyChecker
    tool_policy_pr_enabled: ToolPolicyChecker


def public_api_base(public_api_url: str | None) -> str:
    raw = (
        public_api_url
        or os.getenv("SOURCEBRIEF_PUBLIC_API_URL")
        or os.getenv("CONTEXTSMITH_PUBLIC_API_URL")
        or os.getenv("SOURCEBRIEF_API_URL")
        or os.getenv("CONTEXTSMITH_API_URL")
        or "http://localhost:18000"
    ).strip()
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=422, detail="public_api_url must be an http(s) URL")
    try:
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="public_api_url has an invalid port") from exc
    netloc = parsed.hostname
    if port:
        netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", "")).rstrip("/")


def server_name(project: Project, value: str | None) -> str:
    raw = value or f"sourcebrief-{project.name}"
    return file_slug(raw)[:80]


def config(target: str, server_name: str, mcp_url: str) -> RuntimeInstallPlanConfig:
    auth = "Bearer ${SOURCEBRIEF_TOKEN}"
    if target == "hermes":
        content = (
            "mcp_servers:\n"
            f"  {server_name}:\n"
            f"    url: {json.dumps(mcp_url)}\n"
            "    headers:\n"
            f"      Authorization: {json.dumps(auth)}\n"
            "    timeout: 120\n"
            "    connect_timeout: 30\n"
        )
        return RuntimeInstallPlanConfig(format="yaml", content=content)
    if target == "claude":
        server = {"type": "http", "url": mcp_url, "headers": {"Authorization": auth}}
        return RuntimeInstallPlanConfig(
            format="json",
            content=json.dumps({"mcpServers": {server_name: server}}, indent=2),
        )
    content = (
        f"[mcp_servers.{json.dumps(server_name)}]\n"
        f"url = {json.dumps(mcp_url)}\n"
        'bearer_token_env_var = "SOURCEBRIEF_TOKEN"\n'
    )
    return RuntimeInstallPlanConfig(format="toml", content=content)


def validator_commands(
    target: str,
    api_base_url: str,
    workspace_id: UUID,
    project_id: UUID,
    resource_ids: list[UUID],
) -> list[str]:
    base = [
        "python",
        "scripts/hermes_integration.py",
        "--api-url",
        api_base_url,
        "--workspace-id",
        str(workspace_id),
        "--project-id",
        str(project_id),
        "--query",
        "SourceBrief runtime install plan validation",
        "--token-env",
        "SOURCEBRIEF_TOKEN",
        "--redact-token",
    ]
    if not resource_ids:
        base.append("--allow-empty")
    for resource_id in resource_ids:
        base.extend(["--resource-id", str(resource_id)])
    return [" ".join(shlex.quote(part) for part in base)]


def capabilities(
    profile: AgentProfile | None,
    include_optional_tools: bool,
    *,
    mcp_tools: McpToolsGetter,
    tool_policy_patch_generation_enabled: ToolPolicyChecker,
    tool_policy_pr_enabled: ToolPolicyChecker,
) -> list[RuntimeInstallPlanCapability]:
    runtime_capabilities: list[RuntimeInstallPlanCapability] = []
    for tool in mcp_tools():
        name = str(tool.get("name"))
        if name in RUNTIME_INSTALL_OPTIONAL_TOOLS and not include_optional_tools:
            continue
        policy = "read_only"
        enabled = True
        if name == "sourcebrief.generate_patch":
            enabled = tool_policy_patch_generation_enabled(profile)
            policy = "opt_in_enabled" if enabled else "opt_in_disabled_by_default"
        elif name == "sourcebrief.open_pr":
            enabled = tool_policy_pr_enabled(profile)
            policy = "opt_in_approval_record_enabled" if enabled else "opt_in_approval_record_disabled_by_default"
        elif name == "sourcebrief.generate_skill_pack":
            policy = "server_artifact_generation_requires_review_write; never mutates local files"
        elif name == "sourcebrief.get_rpc_spec":
            policy = "read_only_schema_guidance_for_batch_code_access"
        elif name == "sourcebrief.get_runtime_help":
            policy = "read_only_setup_guidance"
        runtime_capabilities.append(
            RuntimeInstallPlanCapability(
                name=name,
                description=str(tool.get("description") or ""),
                required=name in RUNTIME_INSTALL_CORE_TOOLS,
                enabled=enabled,
                policy=policy,
            )
        )
    return runtime_capabilities


def resource_scope(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    requested_resource_ids: list[UUID] | None,
    *,
    current_project_resources: CurrentProjectResourcesGetter,
    resolve_resource: ResourceResolver,
    effective_resource_ids: EffectiveResourceIdsResolver,
    is_empty_scope: EmptyScopeChecker,
) -> tuple[str, list[Resource]]:
    effective_ids = effective_resource_ids(principal, requested_resource_ids)
    if requested_resource_ids is not None:
        mode = "selected_resources"
    elif principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
        mode = "token_allowed_resources"
    else:
        mode = "project_resources"
    if is_empty_scope(effective_ids):
        return mode, []
    if effective_ids is None:
        resources = [
            resource
            for resource in current_project_resources(session, workspace_id, project_id)
            if resource.archived_at is None and token_allows_resource(principal, resource.id)
        ]
        return mode, resources
    resources = [resolve_resource(session, workspace_id, project_id, resource_id, principal) for resource_id in effective_ids]
    return mode, [resource for resource in resources if resource.archived_at is None]


def plan_response(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    payload: RuntimeInstallPlanRequest,
    principal: Principal,
    *,
    deps: RuntimeInstallDependencies,
) -> RuntimeInstallPlanResponse:
    require_scope(principal, "project:read")
    require_scope(principal, "resource:read")
    project = deps.require_project_access(session, workspace_id, project_id, principal)
    profile = deps.ensure_agent_profile(session, workspace_id, project, principal.user.id)
    api_base_url = public_api_base(payload.public_api_url)
    install_server_name = server_name(project, payload.server_name)
    mcp_url = f"{api_base_url}/mcp/{workspace_id}/{project_id}"
    agent_context_url = f"{api_base_url}/workspaces/{workspace_id}/projects/{project_id}/agent-context"
    agent_pack_url = f"{api_base_url}/workspaces/{workspace_id}/projects/{project_id}/agent-pack.zip"
    scope_mode, resources = resource_scope(
        session,
        workspace_id,
        project_id,
        principal,
        payload.resource_ids,
        current_project_resources=deps.current_project_resources,
        resolve_resource=deps.resolve_resource,
        effective_resource_ids=deps.effective_resource_ids,
        is_empty_scope=deps.is_empty_scope,
    )
    resource_ids = [resource.id for resource in resources]
    warnings = [
        "Dry-run only: SourceBrief did not edit any runtime config.",
        "Use a secret manager or environment variable for SOURCEBRIEF_TOKEN; do not paste plaintext tokens into repo files.",
    ]
    if not resources:
        warnings.append("No active resources are in this plan scope; validation may pass discovery but return empty context.")
    if payload.public_api_url is None:
        warnings.append("public_api_url was not supplied; verify that the generated API base URL is reachable from the target runtime.")
    return RuntimeInstallPlanResponse(
        target=payload.target,
        workspace_id=workspace_id,
        project_id=project_id,
        project_name=deps.sanitize_metadata_text(project.name),
        generated_at=datetime.now(UTC),
        mode="dry_run_plan",
        server_name=install_server_name,
        endpoints=RuntimeInstallPlanEndpoint(
            api_base_url=api_base_url,
            mcp_url=mcp_url,
            agent_context_url=agent_context_url,
            agent_pack_url=agent_pack_url,
        ),
        required_scopes=RUNTIME_INSTALL_REQUIRED_SCOPES,
        suggested_token_request={
            "name": f"SourceBrief {payload.target.title()} read-only runtime",
            "scopes": RUNTIME_INSTALL_REQUIRED_SCOPES,
            "allowed_project_ids": [str(project_id)],
            "allowed_resource_ids": [str(resource_id) for resource_id in resource_ids],
        },
        mcp_config=config(payload.target, install_server_name, mcp_url),
        validator_commands=validator_commands(payload.target, api_base_url, workspace_id, project_id, resource_ids),
        capabilities=capabilities(
            profile,
            payload.include_optional_tools,
            mcp_tools=deps.mcp_tools,
            tool_policy_patch_generation_enabled=deps.tool_policy_patch_generation_enabled,
            tool_policy_pr_enabled=deps.tool_policy_pr_enabled,
        ),
        resource_scope=RuntimeInstallPlanScope(
            mode=scope_mode,
            resources=[
                RuntimeInstallPlanResource(
                    resource_id=resource.id,
                    name=deps.sanitize_metadata_text(resource.name),
                    type=resource.type,
                    status="ready" if resource.current_snapshot_id and resource.status == "active" else resource.status,
                    current_snapshot_id=resource.current_snapshot_id,
                )
                for resource in resources
            ],
        ),
        warnings=warnings,
        rollback_steps=[
            f"Remove the MCP server entry named {install_server_name} from the {payload.target} runtime config.",
            "Unset SOURCEBRIEF_TOKEN from the target runtime environment or secret manager.",
            "Restart or reload the target runtime MCP configuration.",
            "Revoke the SourceBrief API token if it was created only for this runtime.",
        ],
    )
