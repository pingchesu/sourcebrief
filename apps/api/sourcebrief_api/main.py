from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast
from uuid import UUID

from fastapi import (
    HTTPException,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sourcebrief_api import agent_files, agent_packs, git_env, runtime_install
from sourcebrief_api.app_factory import cors_origins, create_app, run_migrations_if_requested
from sourcebrief_api.auth import (
    Principal,
    require_scope,
)
from sourcebrief_api.context_packs import (
    PACK_STATUS_PUBLISHED,
)
from sourcebrief_api.retrieval import (
    RetrievalCandidate,
    embedding_namespace_diagnostics,
    make_snippet,
    normalize_retrieval_profile,
    retrieve_context_candidates,
)
from sourcebrief_api.routers import agent_context as agent_context_router
from sourcebrief_api.routers import agent_profiles as agent_profile_router
from sourcebrief_api.routers import architecture as architecture_router
from sourcebrief_api.routers import audit_index as audit_index_router
from sourcebrief_api.routers import auth_workspace as auth_workspace_router
from sourcebrief_api.routers import context_packs as context_pack_router
from sourcebrief_api.routers import graphs as graph_router
from sourcebrief_api.routers import mcp_context as mcp_context_router
from sourcebrief_api.routers import remote_code as remote_code_router
from sourcebrief_api.routers import repo_agents as repo_agent_router
from sourcebrief_api.routers import resource_artifacts as resource_artifact_router
from sourcebrief_api.routers import resource_core as resource_core_router
from sourcebrief_api.routers import resource_lifecycle as resource_lifecycle_router
from sourcebrief_api.routers import retrieval_evals as retrieval_eval_router
from sourcebrief_api.routers import runtime_agent as runtime_agent_router
from sourcebrief_api.routers import self_improvement as self_improvement_router
from sourcebrief_api.routers import skill_exports as skill_export_router
from sourcebrief_api.routers import system as system_router
from sourcebrief_api.schemas import (
    AgentContextCitation,
    AgentContextRequest,
    AgentContextResponse,
    GitResourceEnvRead,
    GraphMergeReviewRequest,
    RepoAgentBriefRead,
    RuntimeInstallPlanCapability,
    RuntimeInstallPlanRequest,
    RuntimeInstallPlanResponse,
    SkillExportGenerateRequest,
    SkillExportRead,
    SkillExportReviewRequest,
)
from sourcebrief_api.services import access as access_service
from sourcebrief_api.services import (
    agent_context_builders,
    agent_context_runtime,
    agent_context_usage,
    bootstrap_admin,
    mcp_runtime_contract,
    remote_code_actions,
    repo_agent_brief,
    resource_purge,
    runtime_content,
    runtime_graphs,
    runtime_query,
    runtime_skill_packs,
    runtime_support,
)
from sourcebrief_api.services import context_packets as context_packet_service
from sourcebrief_api.services import mcp_endpoint as mcp_endpoint_service
from sourcebrief_api.services import source_config as source_config_service
from sourcebrief_shared.embeddings import current_embedding_config
from sourcebrief_shared.models import (
    AgentProfile,
    ContextArtifact,
    ContextPackVersion,
    Graph,
    GraphMerge,
    GraphMergeVersion,
    GraphVersion,
    Project,
    RepoAgent,
    Resource,
)
from sourcebrief_worker.ingestion import sanitize_remote_url


def on_startup() -> None:
    run_migrations_if_requested()
    try:
        _bootstrap_default_admin()
    except IntegrityError:
        # A concurrent API replica may have inserted the same bootstrap rows first.
        # Treat that as benign; the next readiness/login path will observe those rows.
        return


_cors_origins = cors_origins
app = create_app(startup_handler=on_startup, routers=[system_router.router])

_file_slug = agent_packs.file_slug
_agent_pack_has_blocked_text = agent_packs.has_blocked_text
_agent_pack_public_source_uri = agent_packs.public_source_uri
_agent_pack_public_commit = agent_packs.public_commit
_agent_pack_public_text = agent_packs.public_text
_agent_pack_public_description = agent_packs.public_description
_agent_pack_resources = agent_packs.agent_pack_resources
_agent_pack_snapshot_metadata = agent_packs.snapshot_metadata
_agent_pack_source = agent_packs.source_entry
_agent_pack_manifest_dict = agent_packs.manifest_dict
_yaml_scalar = agent_packs.yaml_scalar
_to_yaml = agent_packs.to_yaml
_agent_pack_manifest_yaml = agent_packs.manifest_yaml
_agent_pack_source_lines = agent_packs.source_lines
_agent_pack_hermes_skill = agent_packs.hermes_skill
_agent_pack_codex_agents = agent_packs.codex_agents
_agent_pack_claude_md = agent_packs.claude_md
_agent_pack_mcp_json = agent_packs.mcp_json
_agent_pack_stable_manifest = agent_packs.stable_manifest
_agent_pack_manifest_digest = agent_packs.manifest_digest
_agent_pack_readme = agent_packs.readme
_agent_pack_changelog = agent_packs.changelog
_agent_pack_golden_questions = agent_packs.golden_questions
_agent_pack_zip_files = agent_packs.zip_files
_agent_pack_zip_bytes = agent_packs.zip_bytes

_resolve_project = access_service.resolve_project
_ensure_agent_profile = access_service.ensure_agent_profile
_normalize_email = access_service.normalize_email
_current_project_resources = access_service.current_project_resources
_require_project_access = access_service.require_project_access
_require_project_member = access_service.require_project_member
_resolve_resource = access_service.resolve_resource
_require_requested_resources_allowed = access_service.require_requested_resources_allowed
_effective_resource_ids = access_service.effective_resource_ids
_is_empty_scope = access_service.is_empty_scope

_agent_context_suggested_tool_calls = agent_context_runtime.agent_context_suggested_tool_calls
_agent_answer_snippets = agent_context_runtime.agent_answer_snippets
_agent_answer_caveats = agent_context_runtime.agent_answer_caveats
_NEGATED_EVIDENCE_MARKERS = agent_context_runtime.NEGATED_EVIDENCE_MARKERS
_UNSUPPORTED_CLAIM_FAMILIES = agent_context_runtime.UNSUPPORTED_CLAIM_FAMILIES
_agent_unsupported_claim_terms = agent_context_runtime.agent_unsupported_claim_terms
_agent_answer_citations_used = agent_context_runtime.agent_answer_citations_used
_synthesize_agent_answer = agent_context_runtime.synthesize_agent_answer
_runtime_safe_index_failure = agent_context_runtime.runtime_safe_index_failure
_coverage_budget_reason = agent_context_runtime.coverage_budget_reason
_agent_context_retrieval_metadata = agent_context_runtime.agent_context_retrieval_metadata

_json_rpc_error = mcp_runtime_contract.json_rpc_error
_mcp_tool_result = mcp_runtime_contract.mcp_tool_result
_runtime_remote_args = mcp_runtime_contract.runtime_remote_args
_runtime_has_scope = mcp_runtime_contract.runtime_has_scope
_mcp_tools = mcp_runtime_contract.mcp_tools
_runtime_help = mcp_runtime_contract.runtime_help

_create_context_packet_action = context_packet_service.create_context_packet_action


def _agent_pack_prepare(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
) -> tuple[Project, dict[str, Any]]:
    return agent_packs.prepare_agent_pack(
        session,
        workspace_id,
        project_id,
        principal,
        require_project_access=_require_project_access,
        current_project_resources=_current_project_resources,
    )


RUNTIME_INSTALL_REQUIRED_SCOPES = runtime_install.RUNTIME_INSTALL_REQUIRED_SCOPES
RUNTIME_INSTALL_CORE_TOOLS = runtime_install.RUNTIME_INSTALL_CORE_TOOLS
RUNTIME_INSTALL_OPTIONAL_TOOLS = runtime_install.RUNTIME_INSTALL_OPTIONAL_TOOLS
_runtime_public_api_base = runtime_install.public_api_base
_runtime_server_name = runtime_install.server_name
_runtime_config = runtime_install.config
_runtime_validator_commands = runtime_install.validator_commands


def _runtime_capabilities(
    profile: AgentProfile | None,
    include_optional_tools: bool,
) -> list[RuntimeInstallPlanCapability]:
    return runtime_install.capabilities(
        profile,
        include_optional_tools,
        mcp_tools=_mcp_tools,
        tool_policy_patch_generation_enabled=_tool_policy_patch_generation_enabled,
        tool_policy_pr_enabled=_tool_policy_pr_enabled,
    )


def _runtime_resource_scope(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    requested_resource_ids: list[UUID] | None,
) -> tuple[str, list[Resource]]:
    return runtime_install.resource_scope(
        session,
        workspace_id,
        project_id,
        principal,
        requested_resource_ids,
        current_project_resources=_current_project_resources,
        resolve_resource=_resolve_resource,
        effective_resource_ids=_effective_resource_ids,
        is_empty_scope=_is_empty_scope,
    )


def _runtime_plan_response(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    payload: RuntimeInstallPlanRequest,
    principal: Principal,
) -> RuntimeInstallPlanResponse:
    return runtime_install.plan_response(
        session,
        workspace_id,
        project_id,
        payload,
        principal,
        deps=runtime_install.RuntimeInstallDependencies(
            require_project_access=_require_project_access,
            ensure_agent_profile=_ensure_agent_profile,
            current_project_resources=_current_project_resources,
            resolve_resource=_resolve_resource,
            effective_resource_ids=_effective_resource_ids,
            is_empty_scope=_is_empty_scope,
            sanitize_metadata_text=_sanitize_metadata_text,
            mcp_tools=_mcp_tools,
            tool_policy_patch_generation_enabled=_tool_policy_patch_generation_enabled,
            tool_policy_pr_enabled=_tool_policy_pr_enabled,
        ),
    )


def _sanitize_public_uri(uri: str) -> str:
    return _agent_pack_public_source_uri(sanitize_remote_url(uri))


def _git_env_read(resource: Resource) -> GitResourceEnvRead:
    return git_env.git_env_read(
        resource,
        sanitize_metadata_text=_sanitize_metadata_text,
        sanitize_public_uri=_sanitize_public_uri,
    )


_validate_auth_token_env = git_env.validate_auth_token_env


def _sanitize_metadata_text(value: str | None) -> str:
    return _agent_pack_public_text(value, "unknown")











_bootstrap_admin_deps = bootstrap_admin.default_bootstrap_admin_deps(
    normalize_email=_normalize_email,
    ensure_agent_profile=_ensure_agent_profile,
)


def _bootstrap_default_admin() -> None:
    return bootstrap_admin.bootstrap_default_admin(_bootstrap_admin_deps)

def _tool_policy_patch_generation_enabled(profile: AgentProfile | None) -> bool:
    policy = cast(dict[str, Any], profile.tool_policy if profile is not None else {})
    return policy.get("patch_generation") == "enabled"


def _tool_policy_pr_enabled(profile: AgentProfile | None) -> bool:
    policy = cast(dict[str, Any], profile.tool_policy if profile is not None else {})
    return policy.get("open_pr") == "enabled"


def _require_patch_generation_enabled(profile: AgentProfile | None) -> None:
    if not _tool_policy_patch_generation_enabled(profile):
        raise HTTPException(status_code=403, detail="patch generation is disabled for this project")


def _require_pr_workflow_enabled(profile: AgentProfile | None) -> None:
    if not _tool_policy_pr_enabled(profile):
        raise HTTPException(status_code=403, detail="PR workflow is disabled for this project")


_agent_profile_read = agent_profile_router.agent_profile_read




_agent_file_response = agent_files.agent_file_response


def _validate_source_config(resource_type: str, uri: str, source_config: dict) -> dict:
    return source_config_service.validate_source_config(resource_type, uri, source_config)



















_repo_agent_brief_deps = repo_agent_brief.RepoAgentBriefDeps(
    sanitize_metadata_text=_sanitize_metadata_text,
    sanitize_public_uri=_sanitize_public_uri,
)
_ENTRYPOINT_RE = repo_agent_brief.ENTRYPOINT_RE
_CONFIG_RE = repo_agent_brief.CONFIG_RE
_RUNTIME_RE = repo_agent_brief.RUNTIME_RE
_RUNBOOK_RE = repo_agent_brief.RUNBOOK_RE
_collect_matching_paths = repo_agent_brief.collect_matching_paths
_repo_agent_readiness = repo_agent_brief.repo_agent_readiness


def _repo_agent_brief_response(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    resource: Resource,
) -> RepoAgentBriefRead:
    return repo_agent_brief.repo_agent_brief_response(
        session,
        workspace_id,
        project_id,
        resource,
        deps=_repo_agent_brief_deps,
    )





def _purge_resource_artifacts(session: Session, resource: Resource) -> dict[str, int]:
    return resource_purge.purge_resource_artifacts(session, resource)

_require_workspace_admin = auth_workspace_router.require_workspace_admin
_validate_token_scopes = auth_workspace_router.validate_token_scopes
_user_read = auth_workspace_router.user_read
_workspace_member_read = auth_workspace_router.workspace_member_read
_api_token_read = auth_workspace_router.api_token_read
_current_user_response = auth_workspace_router.current_user_response
_session_scopes_for_role = auth_workspace_router.session_scopes_for_role_alias






_revoke_user_sessions = auth_workspace_router.revoke_user_sessions
_admin_count = auth_workspace_router.admin_count
_is_admin_role = auth_workspace_router.is_admin_role
_assert_login_capable_admin = auth_workspace_router.assert_login_capable_admin
_assert_not_last_admin_transition = auth_workspace_router.assert_not_last_admin_transition

_auth_workspace_router_deps = auth_workspace_router.AuthWorkspaceRouterDeps(
    require_project_access=_require_project_access,
    ensure_agent_profile=_ensure_agent_profile,
)

app.include_router(auth_workspace_router.create_router(_auth_workspace_router_deps))

_self_improvement_project_root = self_improvement_router.self_improvement_project_root
_history_response = self_improvement_router.history_response
_run_dir = self_improvement_router.run_dir

_self_improvement_router_deps = self_improvement_router.SelfImprovementRouterDeps(
    require_project_access=_require_project_access,
    require_project_member=_require_project_member,
)

app.include_router(self_improvement_router.create_router(_self_improvement_router_deps))

_agent_profile_router_deps = agent_profile_router.AgentProfileRouterDeps(
    require_project_access=_require_project_access,
    require_project_member=_require_project_member,
    ensure_agent_profile=_ensure_agent_profile,
)

app.include_router(agent_profile_router.create_router(_agent_profile_router_deps))

app.include_router(
    runtime_agent_router.create_router(
        runtime_agent_router.RuntimeAgentRouterDeps(
            require_project_access=_require_project_access,
            require_project_member=_require_project_member,
            ensure_agent_profile=_ensure_agent_profile,
            current_project_resources=_current_project_resources,
            agent_file_response=_agent_file_response,
            runtime_plan_response=_runtime_plan_response,
            agent_pack_prepare=_agent_pack_prepare,
            agent_pack_manifest_yaml=_agent_pack_manifest_yaml,
            agent_pack_hermes_skill=_agent_pack_hermes_skill,
            agent_pack_codex_agents=_agent_pack_codex_agents,
            agent_pack_claude_md=_agent_pack_claude_md,
            agent_pack_mcp_json=_agent_pack_mcp_json,
            agent_pack_zip_bytes=_agent_pack_zip_bytes,
            agent_pack_manifest_digest=_agent_pack_manifest_digest,
            resolve_resource=_resolve_resource,
            validate_source_config=_validate_source_config,
            git_env_read=_git_env_read,
        )
    )
)


_manifest_read = resource_core_router._manifest_read
_source_family_id = resource_core_router._source_family_id
_source_family_label = resource_core_router._source_family_label
_version_label = resource_core_router._version_label
_family_manifest_count = resource_core_router._family_manifest_count
_apply_snapshot_coverage = resource_core_router._apply_snapshot_coverage
_resource_read = resource_core_router._resource_read
_folder_bundle_version_name = resource_core_router._folder_bundle_version_name
_manifest_files = resource_core_router._manifest_files
_latest_family_manifests = resource_core_router._latest_family_manifests
_manifest_diff_read = resource_core_router._manifest_diff_read
_section_cursor = resource_core_router._section_cursor
_section_preview = resource_core_router._section_preview
_section_impact_read = resource_core_router._section_impact_read

_resource_core_router_deps = resource_core_router.ResourceCoreRouterDeps(
    require_project_member=_require_project_member,
    require_project_access=_require_project_access,
    resolve_resource=_resolve_resource,
    validate_source_config=_validate_source_config,
)

app.include_router(resource_core_router.create_router(_resource_core_router_deps))

def _require_review_write(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal) -> None:
    require_scope(principal, "review:write")
    _require_project_member(session, workspace_id, project_id, principal, required_scopes={"review:write"})


_context_artifact_read = resource_artifact_router.context_artifact_read

_resource_artifact_router_deps = resource_artifact_router.ResourceArtifactRouterDeps(
    require_project_access=_require_project_access,
    require_project_member=_require_project_member,
    resolve_resource=_resolve_resource,
    require_review_write=_require_review_write,
)


def _resolve_context_artifact(session: Session, workspace_id: UUID, project_id: UUID, artifact_id: UUID, principal: Principal) -> ContextArtifact:
    return resource_artifact_router.resolve_context_artifact(session, workspace_id, project_id, artifact_id, principal, _resource_artifact_router_deps)


app.include_router(resource_artifact_router.create_router(_resource_artifact_router_deps))




_pack_artifact_read = context_pack_router.pack_artifact_read
_pack_coverage_read = context_pack_router.pack_coverage_read
_pack_version_read = context_pack_router.pack_version_read
_pack_resources_allowed = context_pack_router.pack_resources_allowed
_resolve_pack_version = context_pack_router.resolve_pack_version
_lock_pack_parent = context_pack_router.lock_pack_parent

_context_pack_router_deps = context_pack_router.ContextPackRouterDeps(
    require_project_access=_require_project_access,
    require_review_write=_require_review_write,
)


def _require_pack_read(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, version: ContextPackVersion) -> None:
    return context_pack_router.require_pack_read(session, workspace_id, project_id, principal, version, _context_pack_router_deps)


app.include_router(context_pack_router.create_router(_context_pack_router_deps))



_skill_export_router_deps = skill_export_router.SkillExportRouterDeps(
    resolve_pack_version=_resolve_pack_version,
    require_pack_read=_require_pack_read,
    require_review_write=_require_review_write,
    pack_resources_allowed=_pack_resources_allowed,
)

_skill_export_file_read = skill_export_router.skill_export_file_read
_skill_export_read = skill_export_router.skill_export_read
_resolve_skill_export = skill_export_router.resolve_skill_export
_pack_for_export = skill_export_router.pack_for_export
_require_skill_export_read = skill_export_router.require_skill_export_read
_require_skill_export_review = skill_export_router.require_skill_export_review
_scrub_skill_export = skill_export_router.scrub_skill_export
_skill_export_file_is_safe = skill_export_router.skill_export_file_is_safe
_skill_export_zip_bytes = skill_export_router.skill_export_zip_bytes


def generate_skill_export(
    workspace_id: UUID,
    project_id: UUID,
    pack_key: str,
    version_number: int,
    payload: SkillExportGenerateRequest,
    principal: Principal,
    session: Session,
) -> SkillExportRead:
    return skill_export_router.generate_skill_export_action(workspace_id, project_id, pack_key, version_number, payload, principal, session, _skill_export_router_deps)


def approve_skill_export(
    workspace_id: UUID,
    project_id: UUID,
    export_id: UUID,
    payload: SkillExportReviewRequest,
    principal: Principal,
    session: Session,
) -> SkillExportRead:
    return skill_export_router.approve_skill_export_action(workspace_id, project_id, export_id, payload, principal, session, _skill_export_router_deps)


app.include_router(skill_export_router.create_router(_skill_export_router_deps))


_repo_agent_version_read = repo_agent_router.repo_agent_version_read
_repo_agent_read = repo_agent_router.repo_agent_read
_resolve_repo_agent = repo_agent_router.resolve_repo_agent
_validate_repo_agent_version_dependencies_for_publish = repo_agent_router.validate_repo_agent_version_dependencies_for_publish
_validate_repo_agent_version_dependencies_for_rollback_target = repo_agent_router.validate_repo_agent_version_dependencies_for_rollback_target

_repo_agent_router_deps = repo_agent_router.RepoAgentRouterDeps(
    require_project_member=_require_project_member,
    resolve_resource=_resolve_resource,
    require_review_write=_require_review_write,
)


def _repo_agent_resource_allowed(session: Session, agent: RepoAgent, principal: Principal) -> Resource | None:
    return repo_agent_router.repo_agent_resource_allowed(session, agent, principal, _repo_agent_router_deps)


def _require_repo_agent_read(session: Session, agent: RepoAgent, principal: Principal) -> Resource | None:
    return repo_agent_router.require_repo_agent_read(session, agent, principal, _repo_agent_router_deps)


def _require_repo_agent_write(session: Session, agent: RepoAgent, principal: Principal) -> Resource | None:
    return repo_agent_router.require_repo_agent_write(session, agent, principal, _repo_agent_router_deps)


def _require_repo_agent_review_write(session: Session, agent: RepoAgent, principal: Principal) -> Resource | None:
    return repo_agent_router.require_repo_agent_review_write(session, agent, principal, _repo_agent_router_deps)


def _assert_repo_agent_active(agent: RepoAgent) -> None:
    return repo_agent_router.assert_repo_agent_active(agent)


app.include_router(repo_agent_router.create_router(_repo_agent_router_deps))


_audit_index_router_deps = audit_index_router.AuditIndexRouterDeps(
    require_workspace_admin=_require_workspace_admin,
    require_project_access=_require_project_access,
    resolve_resource=_resolve_resource,
)

app.include_router(audit_index_router.create_router(_audit_index_router_deps))

_resource_review_item = resource_lifecycle_router.resource_review_item

_resource_lifecycle_router_deps = resource_lifecycle_router.ResourceLifecycleRouterDeps(
    require_project_access=_require_project_access,
    require_project_member=_require_project_member,
    resolve_resource=_resolve_resource,
    resource_read=_resource_read,
    purge_resource_artifacts=_purge_resource_artifacts,
    validate_source_config=_validate_source_config,
)

app.include_router(resource_lifecycle_router.create_router(_resource_lifecycle_router_deps))



_graph_version_read = graph_router.graph_version_read
_graph_stream_read = graph_router.graph_stream_read
_resolve_graph = graph_router.resolve_graph
_graph_merge_version_read = graph_router.graph_merge_version_read
_graph_merge_read = graph_router.graph_merge_read
_resolve_graph_merge = graph_router.resolve_graph_merge
_graph_merge_input_resource_ids = graph_router.graph_merge_input_resource_ids
_resolve_graph_merge_version = graph_router.resolve_graph_merge_version
_assert_graph_active = graph_router.assert_graph_active

_graph_router_deps = graph_router.GraphRouterDeps(
    require_project_access=_require_project_access,
    require_project_member=_require_project_member,
    resolve_resource=_resolve_resource,
    require_review_write=_require_review_write,
)


def _require_graph_read(session: Session, graph: Graph, principal: Principal) -> Resource | None:
    return graph_router.require_graph_read(session, graph, principal, _graph_router_deps)


def _require_graph_review_write(session: Session, graph: Graph, principal: Principal) -> Resource | None:
    return graph_router.require_graph_review_write(session, graph, principal, _graph_router_deps)


def _require_graph_merge_read(session: Session, merge: GraphMerge, principal: Principal) -> None:
    return graph_router.require_graph_merge_read(session, merge, principal, _graph_router_deps)


def _require_graph_merge_write(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal) -> None:
    return graph_router.require_graph_merge_write(session, workspace_id, project_id, principal, _graph_router_deps)


def _require_graph_merge_review(session: Session, merge: GraphMerge, principal: Principal) -> None:
    return graph_router.require_graph_merge_review(session, merge, principal, _graph_router_deps)


def _assert_graph_merge_publishable(session: Session, version: GraphMergeVersion, payload: GraphMergeReviewRequest) -> None:
    return graph_router.assert_graph_merge_publishable(session, version, payload)


app.include_router(graph_router.create_router(_graph_router_deps))

_make_snippet = remote_code_router._make_snippet
_remote_code_error = remote_code_router._remote_code_error
_scan_budget_exceeded_error = remote_code_router._scan_budget_exceeded_error
_lookup_soft_warning = remote_code_router._lookup_soft_warning
_snapshot_commit = remote_code_router._snapshot_commit
_safe_branch_name = remote_code_router._safe_branch_name
_patch_policy_profile = remote_code_router._patch_policy_profile
_patch_file_hash = remote_code_router._patch_file_hash
_build_unified_file_diff = remote_code_router._build_unified_file_diff
_patch_proposal_read = remote_code_router._patch_proposal_read
_pr_request_read = remote_code_router._pr_request_read
_current_snapshot_files = remote_code_router._current_snapshot_files
_record_remote_code_audit = remote_code_router._record_remote_code_audit
_remote_code_rpc_spec = remote_code_router._remote_code_rpc_spec
_remote_code_rpc_error_payload = remote_code_router._remote_code_rpc_error_payload
_remote_code_lookup_plan = remote_code_router._remote_code_lookup_plan

_runtime_support_deps = runtime_support.RuntimeSupportDeps(
    resolve_pack_version=_resolve_pack_version,
    require_pack_read=_require_pack_read,
)

_mcp_tool_error = runtime_support.mcp_tool_error
_runtime_cursor = runtime_support.runtime_cursor
_runtime_limit = runtime_support.runtime_limit
_runtime_resource_allowed_or_404 = runtime_support.runtime_resource_allowed_or_404
_runtime_resource_rows_allowed = runtime_support.runtime_resource_rows_allowed
_runtime_resource_freshness = runtime_support.runtime_resource_freshness
_runtime_freshness = runtime_support.runtime_freshness
_runtime_citation_locator = runtime_support.runtime_citation_locator
_resource_ref_values = runtime_support.resource_ref_values
_dedupe_uuid_values = runtime_support.dedupe_uuid_values
_looks_like_uuid = runtime_support.looks_like_uuid
_runtime_resolve_resource_ref = runtime_support.runtime_resolve_resource_ref
_resolve_resource_ref_ids = runtime_support.resolve_resource_ref_ids
_request_with_resource_refs = runtime_support.request_with_resource_refs
_runtime_args_with_resource_ref = runtime_support.runtime_args_with_resource_ref


def _runtime_resolve_pack(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any]) -> ContextPackVersion:
    return runtime_support.runtime_resolve_pack(session, workspace_id, project_id, principal, args, _runtime_support_deps)


_remote_code_router_deps = remote_code_router.RemoteCodeRouterDeps(
    require_project_access=_require_project_access,
    require_project_member=_require_project_member,
    resolve_resource=_resolve_resource,
    request_with_resource_refs=lambda *args, **kwargs: _request_with_resource_refs(*args, **kwargs),
    runtime_args_with_resource_ref=lambda *args, **kwargs: _runtime_args_with_resource_ref(*args, **kwargs),
    effective_resource_ids=_effective_resource_ids,
    is_empty_scope=_is_empty_scope,
    require_pr_workflow_enabled=_require_pr_workflow_enabled,
    require_patch_generation_enabled=_require_patch_generation_enabled,
)

























remote_search_code = remote_code_actions.remote_search_code
search_project = remote_code_actions.search_project
code_search_project = remote_code_actions.code_search_project
remote_generate_patch = remote_code_actions.remote_generate_patch
remote_open_pr = remote_code_actions.remote_open_pr
remote_grep_code = remote_code_actions.remote_grep_code
remote_read_file = remote_code_actions.remote_read_file
remote_find_symbol = remote_code_actions.remote_find_symbol
_execute_remote_code_rpc_call = remote_code_actions.execute_remote_code_rpc_call
remote_code_rpc_spec = remote_code_actions.remote_code_rpc_spec
remote_code_rpc = remote_code_actions.remote_code_rpc

app.include_router(remote_code_router.create_router(_remote_code_router_deps))







_agent_context_usage_deps = agent_context_usage.AgentContextUsageDeps(
    current_embedding_config=current_embedding_config,
    embedding_namespace_diagnostics=embedding_namespace_diagnostics,
    normalize_retrieval_profile=normalize_retrieval_profile,
    resource_read=_resource_read,
    runtime_safe_index_failure=_runtime_safe_index_failure,
    coverage_budget_reason=_coverage_budget_reason,
)


def _record_agent_context_usage(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    payload: AgentContextRequest,
    principal: Principal,
    candidates: list[RetrievalCandidate],
) -> None:
    return agent_context_usage.record_agent_context_usage(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        payload=payload,
        principal=principal,
        candidates=candidates,
        deps=_agent_context_usage_deps,
    )


def _resource_coverage_entry(session: Session, resource: Resource) -> dict[str, Any]:
    return agent_context_usage.resource_coverage_entry(session, resource, _agent_context_usage_deps)


def _agent_context_resource_coverage(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    resource_ids: list[UUID] | None,
    citations: list[AgentContextCitation],
    principal: Principal,
) -> tuple[list[dict[str, Any]], list[str]]:
    return agent_context_usage.agent_context_resource_coverage(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        resource_ids=resource_ids,
        citations=citations,
        principal=principal,
        deps=_agent_context_usage_deps,
    )

def _resolve_runtime_pack_version(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    payload: AgentContextRequest,
    principal: Principal,
) -> ContextPackVersion | None:
    if payload.context_pack_key is None and payload.context_pack_version_id is None:
        return None
    if payload.context_pack_version_id is not None:
        version = session.scalar(
            select(ContextPackVersion).where(
                ContextPackVersion.id == payload.context_pack_version_id,
                ContextPackVersion.workspace_id == workspace_id,
                ContextPackVersion.project_id == project_id,
            )
        )
        if version is None:
            raise HTTPException(status_code=404, detail="context pack version not found")
    else:
        selector: int | str = payload.context_pack_version if payload.context_pack_version is not None else "current"
        version = _resolve_pack_version(session, workspace_id, project_id, payload.context_pack_key or "default", selector)
    if version.status != PACK_STATUS_PUBLISHED:
        raise HTTPException(status_code=409, detail="runtime context requires a published Context Pack version")
    _require_pack_read(session, workspace_id, project_id, principal, version)
    return version


def _principal_has_scope(principal: Principal, scope: str) -> bool:
    scopes = principal.scopes
    return "*" in scopes or scope in scopes




























def _agent_context_with_resource_ref(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    payload: AgentContextRequest,
) -> AgentContextRequest:
    return cast(AgentContextRequest, _request_with_resource_refs(session, workspace_id, project_id, principal, payload))







_agent_context_builder_deps = agent_context_builders.AgentContextBuilderDeps(
    make_snippet=make_snippet,
    agent_context_resource_coverage=_agent_context_resource_coverage,
    principal_has_scope=_principal_has_scope,
    synthesize_agent_answer=_synthesize_agent_answer,
    agent_context_suggested_tool_calls=_agent_context_suggested_tool_calls,
    normalize_retrieval_profile=normalize_retrieval_profile,
    retrieve_context_candidates=retrieve_context_candidates,
    code_search_project=code_search_project,
    record_agent_context_usage=_record_agent_context_usage,
    agent_context_retrieval_metadata=_agent_context_retrieval_metadata,
)


def _build_pack_agent_context_response(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    payload: AgentContextRequest,
    principal: Principal,
    pack_version: ContextPackVersion,
) -> AgentContextResponse:
    return agent_context_builders.build_pack_agent_context_response(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        payload=payload,
        principal=principal,
        pack_version=pack_version,
        deps=_agent_context_builder_deps,
    )





def _build_agent_context_response(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    payload: AgentContextRequest,
    principal: Principal,
) -> AgentContextResponse:
    return agent_context_builders.build_agent_context_response(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        payload=payload,
        principal=principal,
        deps=_agent_context_builder_deps,
    )

_agent_card_summary_read = agent_context_router.agent_card_summary_read

_agent_context_router_deps = agent_context_router.AgentContextRouterDeps(
    require_project_access=_require_project_access,
    require_project_member=_require_project_member,
    resolve_resource=_resolve_resource,
    effective_resource_ids=_effective_resource_ids,
    agent_context_with_resource_ref=_agent_context_with_resource_ref,
    resolve_runtime_pack_version=_resolve_runtime_pack_version,
    build_agent_context_response=_build_agent_context_response,
    build_pack_agent_context_response=_build_pack_agent_context_response,
    repo_agent_brief_response=_repo_agent_brief_response,
)


def agent_context(
    workspace_id: UUID,
    project_id: UUID,
    payload: AgentContextRequest,
    principal: Principal,
    session: Session,
) -> AgentContextResponse:
    return agent_context_router.create_router(_agent_context_router_deps).routes[0].endpoint(workspace_id, project_id, payload, principal, session)  # type: ignore[attr-defined]


app.include_router(agent_context_router.create_router(_agent_context_router_deps))

_eval_run_visible_to_principal = retrieval_eval_router._eval_run_visible_to_principal
_retrieval_eval_run_summary_read = retrieval_eval_router._retrieval_eval_run_summary_read
_retrieval_eval_run_read = retrieval_eval_router._retrieval_eval_run_read
_persist_retrieval_eval_run = retrieval_eval_router._persist_retrieval_eval_run

_retrieval_eval_router_deps = retrieval_eval_router.RetrievalEvalRouterDeps(
    require_project_access=_require_project_access,
    resolve_resource=_resolve_resource,
    effective_resource_ids=_effective_resource_ids,
    build_agent_context_response=_build_agent_context_response,
)

app.include_router(retrieval_eval_router.create_router(_retrieval_eval_router_deps))














































_runtime_graph_deps = runtime_graphs.RuntimeGraphDeps(
    runtime_limit=_runtime_limit,
    runtime_cursor=_runtime_cursor,
    require_project_access=_require_project_access,
    runtime_resource_freshness=_runtime_resource_freshness,
    runtime_freshness=_runtime_freshness,
    runtime_resource_rows_allowed=_runtime_resource_rows_allowed,
    runtime_resource_allowed_or_404=_runtime_resource_allowed_or_404,
)


def _runtime_graph_overview(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: dict[str, Any],
) -> dict[str, Any]:
    return runtime_graphs.graph_overview(session, workspace_id, project_id, principal, args, _runtime_graph_deps)


def _runtime_get_graph_inventory(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: dict[str, Any],
) -> dict[str, Any]:
    return runtime_graphs.get_graph_inventory(session, workspace_id, project_id, principal, args, _runtime_graph_deps)


def _runtime_resolve_graph_target(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: dict[str, Any],
) -> tuple[str, Graph | GraphMerge, GraphVersion | GraphMergeVersion]:
    return runtime_graphs.resolve_graph_target(session, workspace_id, project_id, principal, args, _runtime_graph_deps)


def _runtime_graph_query(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: dict[str, Any],
) -> dict[str, Any]:
    return runtime_graphs.graph_query(session, workspace_id, project_id, principal, args, _runtime_graph_deps)


def _runtime_graph_path(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: dict[str, Any],
) -> dict[str, Any]:
    return runtime_graphs.graph_path(session, workspace_id, project_id, principal, args, _runtime_graph_deps)

_architecture_router_deps = architecture_router.ArchitectureRouterDeps(
    runtime_graph_overview=_runtime_graph_overview,
)

app.include_router(architecture_router.create_router(_architecture_router_deps))











_runtime_content_deps = runtime_content.RuntimeContentDeps(
    runtime_limit=_runtime_limit,
    runtime_cursor=_runtime_cursor,
    runtime_resolve_pack=_runtime_resolve_pack,
    runtime_resource_rows_allowed=_runtime_resource_rows_allowed,
    runtime_citation_locator=_runtime_citation_locator,
    runtime_resource_freshness=_runtime_resource_freshness,
    runtime_freshness=_runtime_freshness,
    runtime_get_graph_inventory=_runtime_get_graph_inventory,
    runtime_resolve_resource_ref=_runtime_resolve_resource_ref,
)


def _runtime_list_sources(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: dict[str, Any],
) -> dict[str, Any]:
    return runtime_content.list_sources(session, workspace_id, project_id, principal, args, _runtime_content_deps)


def _runtime_get_context_pack(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: dict[str, Any],
) -> dict[str, Any]:
    return runtime_content.get_context_pack(session, workspace_id, project_id, principal, args, _runtime_content_deps)


def _runtime_get_resource_map(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: dict[str, Any],
) -> dict[str, Any]:
    return runtime_content.get_resource_map(session, workspace_id, project_id, principal, args, _runtime_content_deps)































_runtime_query_deps = runtime_query.RuntimeQueryDeps(
    runtime_limit=_runtime_limit,
    runtime_resolve_pack=_runtime_resolve_pack,
    effective_resource_ids=_effective_resource_ids,
    is_empty_scope=_is_empty_scope,
    runtime_freshness=_runtime_freshness,
    runtime_resource_freshness=_runtime_resource_freshness,
    make_snippet=_make_snippet,
    runtime_resource_allowed_or_404=_runtime_resource_allowed_or_404,
    runtime_citation_locator=_runtime_citation_locator,
    runtime_args_with_resource_ref=_runtime_args_with_resource_ref,
    runtime_remote_args=_runtime_remote_args,
    runtime_has_scope=_runtime_has_scope,
    lookup_soft_warning=_lookup_soft_warning,
    runtime_list_sources=_runtime_list_sources,
    runtime_graph_overview=_runtime_graph_overview,
    remote_search_code=remote_search_code,
    remote_grep_code=remote_grep_code,
    remote_find_symbol=remote_find_symbol,
)

_runtime_snapshot_section_locator = runtime_query.snapshot_section_locator


def _runtime_require_pack_covers_locator(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: dict[str, Any],
    *,
    resource_id: UUID,
    source_snapshot_id: UUID,
) -> None:
    return runtime_query.require_pack_covers_locator(
        session,
        workspace_id,
        project_id,
        principal,
        args,
        _runtime_query_deps,
        resource_id=resource_id,
        source_snapshot_id=source_snapshot_id,
    )


def _runtime_search(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: dict[str, Any],
) -> dict[str, Any]:
    return runtime_query.search(session, workspace_id, project_id, principal, args, _runtime_query_deps)


def _runtime_read_section(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: dict[str, Any],
) -> dict[str, Any]:
    return runtime_query.read_section(session, workspace_id, project_id, principal, args, _runtime_query_deps)


def _runtime_lookup(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: dict[str, Any],
) -> dict[str, Any]:
    return runtime_query.lookup(session, workspace_id, project_id, principal, args, _runtime_query_deps)


def _runtime_discover(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: dict[str, Any],
) -> dict[str, Any]:
    return runtime_query.discover(session, workspace_id, project_id, principal, args, _runtime_query_deps)

_runtime_skill_pack_deps = runtime_skill_packs.RuntimeSkillPackDeps(
    resolve_pack_version=_resolve_pack_version,
    generate_skill_export=generate_skill_export,
    approve_skill_export=approve_skill_export,
)


def _runtime_generate_skill_pack(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: Mapping[str, Any],
) -> dict[str, Any]:
    return runtime_skill_packs.generate_skill_pack(
        session,
        workspace_id,
        project_id,
        principal,
        args,
        _runtime_skill_pack_deps,
    )

_mcp_endpoint_deps = mcp_endpoint_service.McpEndpointDeps(
    require_project_access=_require_project_access,
    json_rpc_error=_json_rpc_error,
    mcp_tool_result=_mcp_tool_result,
    mcp_tool_error=_mcp_tool_error,
    mcp_tools=_mcp_tools,
    runtime_args_with_resource_ref=_runtime_args_with_resource_ref,
    runtime_remote_args=_runtime_remote_args,
    agent_context=agent_context,
    runtime_discover=_runtime_discover,
    runtime_lookup=_runtime_lookup,
    runtime_get_context_pack=_runtime_get_context_pack,
    runtime_list_sources=_runtime_list_sources,
    runtime_get_resource_map=_runtime_get_resource_map,
    runtime_search=_runtime_search,
    runtime_read_section=_runtime_read_section,
    runtime_graph_overview=_runtime_graph_overview,
    runtime_get_graph_inventory=_runtime_get_graph_inventory,
    runtime_graph_query=_runtime_graph_query,
    runtime_graph_path=_runtime_graph_path,
    runtime_generate_skill_pack=_runtime_generate_skill_pack,
    remote_search_code=remote_search_code,
    remote_grep_code=remote_grep_code,
    remote_read_file=remote_read_file,
    remote_find_symbol=remote_find_symbol,
    remote_code_rpc_spec=remote_code_rpc_spec,
    runtime_help=_runtime_help,
    remote_generate_patch=remote_generate_patch,
    remote_open_pr=remote_open_pr,
)
_mcp_endpoint_action = mcp_endpoint_service.build_mcp_endpoint_action(_mcp_endpoint_deps)

_mcp_context_router_deps = mcp_context_router.McpContextRouterDeps(
    mcp_endpoint_action=_mcp_endpoint_action,
    create_context_packet_action=_create_context_packet_action,
)

app.include_router(mcp_context_router.create_router(_mcp_context_router_deps))
