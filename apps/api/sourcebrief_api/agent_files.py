from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from sourcebrief_api.agent_packs import file_slug, public_source_uri, public_text
from sourcebrief_api.schemas import AgentFileRead, AgentFilesResponse
from sourcebrief_shared.models import AgentProfile, Project, Resource


def _sanitize_metadata_text(value: str | None) -> str:
    return public_text(value, "unknown")


def agent_file_response(
    session: Session,
    workspace_id: UUID,
    project: Project,
    profile: AgentProfile,
    resources: list[Resource],
) -> AgentFilesResponse:
    repo_resources = [resource for resource in resources if resource.type.lower() == "git"]
    safe_profile_name = _sanitize_metadata_text(profile.name)
    safe_description = _sanitize_metadata_text(profile.description or project.description or "Generated SourceBrief project agent.")
    resource_rows = [
        {
            "id": str(resource.id),
            "name": _sanitize_metadata_text(resource.name),
            "type": resource.type,
            "uri": public_source_uri(resource.uri),
            "status": resource.status,
            "retrieval_enabled": resource.retrieval_enabled,
            "update_frequency": resource.update_frequency,
            "current_snapshot_id": str(resource.current_snapshot_id) if resource.current_snapshot_id else None,
        }
        for resource in resources
    ]
    manifest = {
        "schema": "sourcebrief.agent_manifest.v1",
        "workspace_id": str(workspace_id),
        "project_id": str(project.id),
        "agent_name": safe_profile_name,
        "default_runtime": profile.default_runtime,
        "mcp_endpoint": f"/mcp/{workspace_id}/{project.id}",
        "agent_context_endpoint": f"/workspaces/{workspace_id}/projects/{project.id}/agent-context",
        "resources": resource_rows,
        "repo_agents": [str(resource.id) for resource in repo_resources],
    }
    resources_md = "\n".join(
        f"- `{resource.type}` **{_sanitize_metadata_text(resource.name)}** (`{resource.id}`): {public_source_uri(resource.uri)}; refresh={resource.update_frequency}; snapshot={resource.current_snapshot_id or 'none'}"
        for resource in resources
    ) or "- No resources imported yet."
    repo_skill_files = []
    for resource in repo_resources:
        source_config = resource.source_config or {}
        safe_resource_name = _sanitize_metadata_text(resource.name)
        repo_slug = file_slug(safe_resource_name)
        repo_skill_files.append(
            AgentFileRead(
                path=f"skills/{repo_slug}/SKILL.md",
                kind="repo-skill",
                description=f"Hermes/Codex specialist skill for {safe_resource_name}",
                content=(
                    "---\n"
                    f"name: {repo_slug}\n"
                    f"description: Use when answering or reviewing work related to the {safe_resource_name} repository.\n"
                    "---\n\n"
                    f"# {safe_resource_name} repo agent\n\n"
                    "## Scope\n"
                    f"- Resource ID: `{resource.id}`\n"
                    f"- URI: `{public_source_uri(resource.uri)}`\n"
                    f"- Branch/ref: `{public_text(str(source_config.get('branch') or source_config.get('ref')) if source_config.get('branch') or source_config.get('ref') else None, 'default')}`\n"
                    f"- Current snapshot: `{resource.current_snapshot_id or 'none'}`\n"
                    f"- Update frequency: `{resource.update_frequency}`\n\n"
                    "## How to use\n"
                    "Query SourceBrief with this resource_id as the only resource scope when the task is repo-specific.\n"
                    "Ask for cited files, symbols, entrypoints, config, runbooks, and operational boundaries before editing.\n\n"
                    "## Generated operating brief\n"
                    f"Fetch `/workspaces/{workspace_id}/projects/{project.id}/repo-agents/{resource.id}/brief` for the current deterministic operating brief, readiness, quality gates, entrypoints, configs, runbooks, and symbol samples.\n\n"
                    "## Safety boundary\n"
                    "This skill provides context only. Production mutations still require Hermes approval, typed MCP tools, and evidence.\n"
                ),
            )
        )
    files = [
        AgentFileRead(
            path="sourcebrief-agent.json",
            kind="manifest",
            description="Machine-readable project agent manifest for routers and external runtimes.",
            content=json.dumps(manifest, indent=2, sort_keys=True),
        ),
        AgentFileRead(
            path="AGENTS.md",
            kind="agent-instructions",
            description="Human-readable generated project agent instructions.",
            content=(
                f"# {safe_profile_name}\n\n"
                f"{safe_description}\n\n"
                "## Runtime contract\n"
                f"- Default runtime: `{profile.default_runtime}`\n"
                f"- Agent context endpoint: `/workspaces/{workspace_id}/projects/{project.id}/agent-context`\n"
                f"- MCP endpoint: `/mcp/{workspace_id}/{project.id}`\n"
                "- Repos are resources. Repo-agent is a generated feature on top of `type=git` resources.\n\n"
                "## Resources\n"
                f"{resources_md}\n\n"
                "## Production boundary\n"
                "Do not execute production mutations from generated context. Use Hermes approval + typed MCP + evidence workflow.\n"
            ),
        ),
        AgentFileRead(
            path="skills/project-agent/SKILL.md",
            kind="project-skill",
            description="Hermes/Codex project-level skill that routes to SourceBrief.",
            content=(
                "---\n"
                f"name: {file_slug(safe_profile_name)}\n"
                f"description: Use when answering cross-resource questions for {safe_profile_name}.\n"
                "---\n\n"
                f"# {safe_profile_name}\n\n"
                "Use SourceBrief agent-context for cross-resource answers. Prefer scoped repo-resource queries when the task names a repo/service.\n\n"
                "## Resource routing\n"
                f"{resources_md}\n"
            ),
        ),
        AgentFileRead(
            path=".env.sourcebrief.example",
            kind="env-example",
            description="Environment variables for external runtimes and git import workers.",
            content=(
                "SOURCEBRIEF_API_BASE_URL=http://localhost:18000\n"
                f"SOURCEBRIEF_WORKSPACE_ID={workspace_id}\n"
                f"SOURCEBRIEF_PROJECT_ID={project.id}\n"
                "SOURCEBRIEF_API_TOKEN=replace-with-project-query-token\n"
                "# Optional: set this on workers, then reference its name in a repo's Git Env auth_token_env.\n"
                "GITHUB_TOKEN_FOR_SOURCEBRIEF=replace-with-git-token\n"
            ),
        ),
        *repo_skill_files,
    ]
    return AgentFilesResponse(
        workspace_id=workspace_id,
        project_id=project.id,
        generated_at=datetime.now(UTC),
        resource_count=len(resources),
        repo_agent_count=len(repo_resources),
        files=files,
    )
