from __future__ import annotations

from sourcebrief_api.main import app

EXPECTED_RUNTIME_AGENT_ROUTE_SIGNATURES = {
    ("GET", "/healthz", "healthz"),
    ("GET", "/provider-health", "provider_health"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/agent-files", "get_agent_files"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/agent-files/regenerate", "regenerate_agent_files"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/runtime-install-plan", "runtime_install_plan"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/agent-pack/manifest", "get_agent_pack_manifest"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/agent-pack/hermes/SKILL.md", "get_agent_pack_hermes_skill"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/agent-pack/codex/AGENTS.md", "get_agent_pack_codex_agents"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/agent-pack/claude/CLAUDE.md", "get_agent_pack_claude_md"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/agent-pack/mcp.json", "get_agent_pack_mcp_json"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/agent-pack.zip", "get_agent_pack_zip"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/git-env", "list_git_env"),
    ("PATCH", "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/git-env", "update_git_env"),
}

EXPECTED_SKILL_EXPORT_ROUTE_SIGNATURES = {
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions/{version_number}/skill-exports", "generate_skill_export"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions/{version_number}/skill-exports", "list_skill_exports"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_id}", "get_skill_export"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_id}/approve", "approve_skill_export"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_id}/reject", "reject_skill_export"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_id}/invalidate", "invalidate_skill_export"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_id}/files/{file_path:path}", "download_skill_export_file"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_id}/download.zip", "download_skill_export_package"),
}

EXPECTED_CONTEXT_PACK_ROUTE_SIGNATURES = {
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions", "create_context_pack_version"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/context-packs", "list_context_packs"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions", "list_context_pack_versions"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/current", "get_current_context_pack_version"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions/{version_number}", "get_context_pack_version_by_number"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions/{version_number}/publish", "publish_context_pack_version"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions/{version_number}/rollback", "rollback_context_pack_version"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions/{version_number}/invalidate", "invalidate_context_pack_version"),
}

EXPECTED_REPO_AGENT_ROUTE_SIGNATURES = {
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/repo-agents", "list_repo_agents"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/repo-agent", "create_repo_agent"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}", "get_repo_agent"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}/refresh", "refresh_repo_agent"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}/versions/{version_number}/publish", "publish_repo_agent_version"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}/versions/{version_number}/rollback-draft", "create_repo_agent_rollback_draft"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}/archive", "archive_repo_agent"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}/versions/{version_number}/invalidate", "invalidate_repo_agent_version"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}/versions/{version_number}/scrub", "scrub_repo_agent_version"),
}


EXPECTED_RESOURCE_ARTIFACT_ROUTE_SIGNATURES = {
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/context-artifacts/resource-map", "compile_resource_map_artifact"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/context-artifacts", "list_resource_context_artifacts"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/context-artifacts/{artifact_id}", "get_context_artifact"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/context-artifacts/{artifact_id}/approve", "approve_context_artifact"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/context-artifacts/{artifact_id}/reject", "reject_context_artifact"),
}

EXPECTED_ROUTE_SIGNATURES = EXPECTED_RUNTIME_AGENT_ROUTE_SIGNATURES | EXPECTED_SKILL_EXPORT_ROUTE_SIGNATURES | EXPECTED_CONTEXT_PACK_ROUTE_SIGNATURES | EXPECTED_REPO_AGENT_ROUTE_SIGNATURES | EXPECTED_RESOURCE_ARTIFACT_ROUTE_SIGNATURES


def _route_signatures() -> set[tuple[str, str, str]]:
    signatures: set[tuple[str, str, str]] = set()

    def visit(routes: object) -> None:
        for route in routes:  # type: ignore[union-attr]
            nested = getattr(route, "routes", None)
            if nested is None:
                original_router = getattr(route, "original_router", None)
                nested = getattr(original_router, "routes", None)
            if nested is not None:
                visit(nested)
                continue
            path = getattr(route, "path", None)
            name = getattr(route, "name", None)
            methods = getattr(route, "methods", None) or set()
            if path is None or name is None:
                continue
            for method in methods:
                if method in {"HEAD", "OPTIONS"}:
                    continue
                signatures.add((method, path, name))

    visit(app.routes)
    return signatures


def test_runtime_agent_route_contract_is_stable() -> None:
    signatures = _route_signatures()
    missing = EXPECTED_ROUTE_SIGNATURES - signatures
    assert not missing


def test_recursive_route_signature_count_is_stable() -> None:
    assert len(_route_signatures()) == 131


def test_runtime_agent_openapi_metadata_remains_untagged() -> None:
    openapi = app.openapi()
    for method, path, _name in EXPECTED_RUNTIME_AGENT_ROUTE_SIGNATURES:
        if path in {"/healthz", "/provider-health"}:
            continue
        openapi_path = path.replace("{file_path:path}", "{file_path}")
        operation = openapi["paths"][openapi_path][method.lower()]
        assert "tags" not in operation


def test_skill_export_openapi_metadata_remains_untagged() -> None:
    openapi = app.openapi()
    for method, path, _name in EXPECTED_SKILL_EXPORT_ROUTE_SIGNATURES:
        openapi_path = path.replace("{file_path:path}", "{file_path}")
        operation = openapi["paths"][openapi_path][method.lower()]
        assert "tags" not in operation


def test_context_pack_openapi_metadata_remains_untagged() -> None:
    openapi = app.openapi()
    for method, path, _name in EXPECTED_CONTEXT_PACK_ROUTE_SIGNATURES:
        operation = openapi["paths"][path][method.lower()]
        assert "tags" not in operation


def test_repo_agent_openapi_metadata_remains_untagged() -> None:
    openapi = app.openapi()
    for method, path, _name in EXPECTED_REPO_AGENT_ROUTE_SIGNATURES:
        operation = openapi["paths"][path][method.lower()]
        assert "tags" not in operation


def test_resource_artifact_openapi_metadata_remains_untagged() -> None:
    openapi = app.openapi()
    for method, path, _name in EXPECTED_RESOURCE_ARTIFACT_ROUTE_SIGNATURES:
        operation = openapi["paths"][path][method.lower()]
        assert "tags" not in operation
