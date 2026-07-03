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


EXPECTED_RESOURCE_LIFECYCLE_ROUTE_SIGNATURES = {
    ("PATCH", "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}", "update_resource"),
    ("DELETE", "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}", "delete_resource"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/archive", "archive_resource"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/restore", "restore_resource"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/purge", "purge_resource"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/review", "review_resource"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/resource-review", "list_resource_review"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/resource-usage", "resource_usage"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/resources", "list_resources"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/snapshots", "list_snapshots"),
}


EXPECTED_GRAPH_ROUTE_SIGNATURES = {
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/graph-merges", "list_graph_merges"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}", "get_graph_merge"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/graph-merges", "compile_graph_merge_endpoint"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/versions/{version_number}/publish", "publish_graph_merge"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/versions/{version_number}/invalidate", "invalidate_graph_merge_version"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/archive", "archive_graph_merge"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/versions/{version_number}/data", "get_graph_merge_data"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/versions/{version_number}/candidates/{candidate_key}/review", "review_graph_merge_candidate"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/versions/{version_number}/path", "get_graph_merge_path"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/graphs", "list_graph_streams"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/graphs/{graph_key}", "get_graph_stream"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/graph/versions", "compile_resource_graph_version"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/graphs/{graph_key}/versions/{version_number}/publish", "publish_graph_version"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/graphs/{graph_key}/versions/{version_number}/invalidate", "invalidate_graph_version"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/graphs/{graph_key}/archive", "archive_graph_stream"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/graph", "get_resource_graph"),
}


EXPECTED_REMOTE_CODE_ROUTE_SIGNATURES = {
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/search", "search_project"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/code-search", "code_search_project"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/remote-code/generate_patch", "remote_generate_patch"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/remote-code/open_pr", "remote_open_pr"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/remote-code/search_code", "remote_search_code"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/remote-code/grep_code", "remote_grep_code"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/remote-code/read_file", "remote_read_file"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/remote-code/find_symbol", "remote_find_symbol"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/code/rpc/spec", "remote_code_rpc_spec"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/code/rpc", "remote_code_rpc"),
}


EXPECTED_AGENT_CONTEXT_ROUTE_SIGNATURES = {
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/agent-context", "agent_context"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries", "list_agent_card_summaries"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries/run", "run_agent_card_summary_audit"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries/{summary_id}/acknowledge", "acknowledge_agent_card_summary"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/repo-agents/{resource_id}/brief", "get_repo_agent_brief"),
}

EXPECTED_RETRIEVAL_EVAL_ROUTE_SIGNATURES = {
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/retrieval-evals", "list_retrieval_eval_runs"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/retrieval-evals/{run_id}", "get_retrieval_eval_run"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/retrieval-profiles", "list_retrieval_profiles"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/retrieval-evals", "run_retrieval_eval"),
}

EXPECTED_AUDIT_INDEX_ROUTE_SIGNATURES = {
    ("GET", "/workspaces/{workspace_id}/audit-events", "list_audit_events"),
    ("GET", "/workspaces/{workspace_id}/index-runs/{index_run_id}", "get_index_run"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/index-runs", "list_resource_index_runs"),
}

EXPECTED_SELF_IMPROVEMENT_ROUTE_SIGNATURES = {
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/self-improvement", "get_self_improvement_overview"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/self-improvement/history", "list_self_improvement_history"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/self-improvement/artifacts/{artifact_id}", "get_self_improvement_artifact"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/self-improvement/mvp-smoke", "run_self_improvement_mvp_smoke"),
    ("POST", "/workspaces/{workspace_id}/projects/{project_id}/self-improvement/sleep", "run_self_improvement_sleep"),
}

EXPECTED_AGENT_PROFILE_ROUTE_SIGNATURES = {
    ("GET", "/workspaces/{workspace_id}/agents", "list_agents"),
    ("GET", "/workspaces/{workspace_id}/projects/{project_id}/agent-profile", "get_agent_profile"),
    ("PATCH", "/workspaces/{workspace_id}/projects/{project_id}/agent-profile", "update_agent_profile"),
}

EXPECTED_ROUTE_SIGNATURES = EXPECTED_RUNTIME_AGENT_ROUTE_SIGNATURES | EXPECTED_SKILL_EXPORT_ROUTE_SIGNATURES | EXPECTED_CONTEXT_PACK_ROUTE_SIGNATURES | EXPECTED_REPO_AGENT_ROUTE_SIGNATURES | EXPECTED_RESOURCE_ARTIFACT_ROUTE_SIGNATURES | EXPECTED_RESOURCE_LIFECYCLE_ROUTE_SIGNATURES | EXPECTED_GRAPH_ROUTE_SIGNATURES | EXPECTED_REMOTE_CODE_ROUTE_SIGNATURES | EXPECTED_AGENT_CONTEXT_ROUTE_SIGNATURES | EXPECTED_RETRIEVAL_EVAL_ROUTE_SIGNATURES | EXPECTED_AUDIT_INDEX_ROUTE_SIGNATURES | EXPECTED_SELF_IMPROVEMENT_ROUTE_SIGNATURES | EXPECTED_AGENT_PROFILE_ROUTE_SIGNATURES


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


def test_resource_lifecycle_openapi_metadata_remains_untagged() -> None:
    openapi = app.openapi()
    for method, path, _name in EXPECTED_RESOURCE_LIFECYCLE_ROUTE_SIGNATURES:
        operation = openapi["paths"][path][method.lower()]
        assert "tags" not in operation


def test_graph_openapi_metadata_remains_untagged() -> None:
    openapi = app.openapi()
    for method, path, _name in EXPECTED_GRAPH_ROUTE_SIGNATURES:
        operation = openapi["paths"][path][method.lower()]
        assert "tags" not in operation


def test_remote_code_openapi_metadata_remains_untagged() -> None:
    openapi = app.openapi()
    for method, path, _name in EXPECTED_REMOTE_CODE_ROUTE_SIGNATURES:
        operation = openapi["paths"][path][method.lower()]
        assert "tags" not in operation


def test_agent_context_openapi_metadata_remains_untagged() -> None:
    openapi = app.openapi()
    for method, path, _name in EXPECTED_AGENT_CONTEXT_ROUTE_SIGNATURES:
        operation = openapi["paths"][path][method.lower()]
        assert "tags" not in operation


def test_retrieval_eval_openapi_metadata_remains_untagged() -> None:
    openapi = app.openapi()
    for method, path, _name in EXPECTED_RETRIEVAL_EVAL_ROUTE_SIGNATURES:
        operation = openapi["paths"][path][method.lower()]
        assert "tags" not in operation


def test_audit_index_openapi_metadata_remains_untagged() -> None:
    openapi = app.openapi()
    for method, path, _name in EXPECTED_AUDIT_INDEX_ROUTE_SIGNATURES:
        operation = openapi["paths"][path][method.lower()]
        assert "tags" not in operation


def test_self_improvement_openapi_metadata_remains_untagged() -> None:
    openapi = app.openapi()
    for method, path, _name in EXPECTED_SELF_IMPROVEMENT_ROUTE_SIGNATURES:
        operation = openapi["paths"][path][method.lower()]
        assert "tags" not in operation


def test_agent_profile_openapi_metadata_remains_untagged() -> None:
    openapi = app.openapi()
    for method, path, _name in EXPECTED_AGENT_PROFILE_ROUTE_SIGNATURES:
        operation = openapi["paths"][path][method.lower()]
        assert "tags" not in operation
