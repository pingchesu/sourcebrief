from __future__ import annotations

from sourcebrief_api.main import app

EXPECTED_ROUTE_SIGNATURES = {
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
    for method, path, _name in EXPECTED_ROUTE_SIGNATURES:
        if path in {"/healthz", "/provider-health"}:
            continue
        operation = openapi["paths"][path][method.lower()]
        assert "tags" not in operation
