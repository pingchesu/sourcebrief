from __future__ import annotations

import json
import os
import re
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from fastapi import (
    HTTPException,
)
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sourcebrief_api import agent_files, agent_packs, git_env, runtime_install
from sourcebrief_api.app_factory import cors_origins, create_app, run_migrations_if_requested
from sourcebrief_api.auth import (
    Principal,
    hash_password,
    require_scope,
    token_allows_resource,
)
from sourcebrief_api.constants import (
    COMMON_AGENT_INSTRUCTION,
    FOLDER_BUNDLE_RESOURCE_TYPES,
    RUNTIME_INSTRUCTIONS,
    UPLOAD_RESOURCE_TYPES,
    URL_RESOURCE_TYPES,
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
    CodeSearchRequest,
    CodeSymbolHit,
    GeneratePatchRequest,
    GitResourceEnvRead,
    GraphMergeReviewRequest,
    OpenPrRequest,
    RemoteFindSymbolRequest,
    RemoteFindSymbolResponse,
    RemoteGrepCodeRequest,
    RemoteGrepCodeResponse,
    RemoteReadFileRequest,
    RemoteReadFileResponse,
    RemoteSearchCodeRequest,
    RemoteSearchCodeResponse,
    RepoAgentBriefRead,
    RuntimeInstallPlanCapability,
    RuntimeInstallPlanRequest,
    RuntimeInstallPlanResponse,
    SearchRequest,
    SkillExportGenerateRequest,
    SkillExportRead,
    SkillExportReviewRequest,
)
from sourcebrief_api.services import access as access_service
from sourcebrief_api.services import (
    agent_context_runtime,
    mcp_runtime_contract,
    runtime_content,
    runtime_graphs,
    runtime_query,
    runtime_skill_packs,
)
from sourcebrief_api.services import context_packets as context_packet_service
from sourcebrief_api.services import mcp_endpoint as mcp_endpoint_service
from sourcebrief_shared.config import get_settings
from sourcebrief_shared.db import get_sessionmaker
from sourcebrief_shared.embeddings import current_embedding_config
from sourcebrief_shared.models import (
    AgentProfile,
    ContextArtifact,
    ContextArtifactCitation,
    ContextPackArtifact,
    ContextPackVersion,
    Graph,
    GraphMerge,
    GraphMergeVersion,
    GraphVersion,
    IndexRun,
    Project,
    ProjectMembership,
    QueryRun,
    RepoAgent,
    Resource,
    RetrievalHit,
    SnapshotFile,
    User,
    Workspace,
    WorkspaceMembership,
)
from sourcebrief_worker.ingestion import (
    DEFAULT_MAX_CHUNKS,
    DEFAULT_MAX_DOCUMENT_BYTES,
    DEFAULT_MAX_SYMBOLS,
    DEFAULT_MAX_URL_BYTES,
    HARD_MAX_CHUNKS,
    HARD_MAX_DOCUMENT_BYTES,
    HARD_MAX_SYMBOLS,
    HARD_MAX_URL_BYTES,
    parse_positive_int,
    sanitize_remote_url,
    validate_base64_size,
    validate_git_url,
    validate_http_url,
)


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








def _bootstrap_default_admin() -> None:
    settings = get_settings()
    if not settings.admin_email or not settings.admin_password:
        return
    if settings.admin_password in {"change-me-before-compose-up", "sourcebrief-admin"}:
        raise RuntimeError("SOURCEBRIEF_ADMIN_PASSWORD must be changed from the sample/default value before startup")
    SessionLocal = get_sessionmaker()
    with SessionLocal() as session:
        email = _normalize_email(settings.admin_email)
        admin = session.scalar(select(User).where(User.email == email))
        if admin is None:
            admin = User(
                email=email,
                display_name=settings.admin_display_name,
                password_hash=hash_password(settings.admin_password),
                is_active=True,
                is_platform_admin=True,
            )
            session.add(admin)
            session.flush()
        if not admin.display_name or admin.display_name == "ContextSmith Admin":
            admin.display_name = settings.admin_display_name
        admin.password_hash = hash_password(settings.admin_password)
        admin.is_active = True
        admin.is_platform_admin = True

        workspace = session.scalar(select(Workspace).where(Workspace.slug == settings.bootstrap_workspace_slug))
        if workspace is None and settings.bootstrap_workspace_slug == "sourcebrief":
            legacy_workspace = session.scalar(select(Workspace).where(Workspace.slug == "contextsmith"))
            if legacy_workspace is not None and legacy_workspace.name == "ContextSmith":
                legacy_workspace.name = settings.bootstrap_workspace_name
                legacy_workspace.slug = settings.bootstrap_workspace_slug
                workspace = legacy_workspace
        if workspace is None:
            workspace = Workspace(name=settings.bootstrap_workspace_name, slug=settings.bootstrap_workspace_slug)
            session.add(workspace)
            session.flush()
        elif workspace.name == "ContextSmith" and settings.bootstrap_workspace_name == "SourceBrief":
            workspace.name = settings.bootstrap_workspace_name
        membership = session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace.id,
                WorkspaceMembership.user_id == admin.id,
            )
        )
        if membership is None:
            session.add(WorkspaceMembership(workspace_id=workspace.id, user_id=admin.id, role="owner"))
        elif membership.role not in {"owner", "admin"}:
            membership.role = "owner"

        project = session.scalar(
            select(Project).where(
                Project.workspace_id == workspace.id,
                Project.name == settings.bootstrap_project_name,
                Project.deleted_at.is_(None),
            )
        )
        if project is None:
            project = Project(
                workspace_id=workspace.id,
                name=settings.bootstrap_project_name,
                description="Bootstrap project for the initial SourceBrief console.",
                created_by=admin.id,
            )
            session.add(project)
            session.flush()
        elif project.description == "Bootstrap project for the initial ContextSmith console.":
            project.description = "Bootstrap project for the initial SourceBrief console."
        project_membership = session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project.id,
                ProjectMembership.user_id == admin.id,
            )
        )
        if project_membership is None:
            session.add(
                ProjectMembership(
                    workspace_id=workspace.id,
                    project_id=project.id,
                    user_id=admin.id,
                    role="owner",
                )
            )
        elif project_membership.role not in {"owner", "admin"}:
            project_membership.role = "owner"
        _ensure_agent_profile(session, workspace.id, project, admin.id)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()


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
    rtype = (resource_type or "").lower()
    config = dict(source_config or {})
    if rtype in URL_RESOURCE_TYPES:
        url = config.get("url") or uri
        try:
            config["url"] = validate_http_url(url)
            config["max_url_bytes"] = parse_positive_int(
                config.get("max_url_bytes"),
                default=DEFAULT_MAX_URL_BYTES,
                hard_limit=HARD_MAX_URL_BYTES,
                name="max_url_bytes",
            )
            if "fetch_timeout" in config:
                config["fetch_timeout"] = parse_positive_int(
                    config.get("fetch_timeout"), default=20, hard_limit=60, name="fetch_timeout"
                )
            if "max_redirects" in config:
                config["max_redirects"] = parse_positive_int(
                    config.get("max_redirects"), default=3, hard_limit=10, name="max_redirects"
                )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if rtype == "git":
        try:
            _is_local, target = validate_git_url(
                config.get("url") or uri,
                allow_local=os.getenv("SOURCEBRIEF_ALLOW_LOCAL_GIT", os.getenv("CONTEXTSMITH_ALLOW_LOCAL_GIT", "false")).lower() == "true",
            )
            config["url"] = target if _is_local else sanitize_remote_url(target)
            auth_token_env = _validate_auth_token_env(config.get("auth_token_env"))
            if auth_token_env is None:
                config.pop("auth_token_env", None)
            else:
                config["auth_token_env"] = auth_token_env
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if rtype in UPLOAD_RESOURCE_TYPES:
        if any(key in config for key in ("path", "file_path", "local_path")):
            raise HTTPException(status_code=422, detail="upload connector does not accept local file paths")
        if not any(isinstance(value := config.get(key), str) and value.strip() for key in ("content", "text", "base64")):
            raise HTTPException(status_code=422, detail="upload connector requires content, text, or base64")
        try:
            max_document_bytes = parse_positive_int(
                config.get("max_document_bytes"),
                default=DEFAULT_MAX_DOCUMENT_BYTES,
                hard_limit=HARD_MAX_DOCUMENT_BYTES,
                name="max_document_bytes",
            )
            config["max_document_bytes"] = max_document_bytes
            if isinstance(config.get("base64"), str):
                validate_base64_size(config["base64"], max_bytes=max_document_bytes)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if rtype in FOLDER_BUNDLE_RESOURCE_TYPES:
        raise HTTPException(status_code=422, detail="folder bundles must be created through the zip upload endpoint")
    try:
        if "max_chunks" in config:
            config["max_chunks"] = parse_positive_int(
                config.get("max_chunks"), default=DEFAULT_MAX_CHUNKS, hard_limit=HARD_MAX_CHUNKS, name="max_chunks"
            )
        if "max_symbols" in config:
            config["max_symbols"] = parse_positive_int(
                config.get("max_symbols"), default=DEFAULT_MAX_SYMBOLS, hard_limit=HARD_MAX_SYMBOLS, name="max_symbols"
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return config




_ENTRYPOINT_RE = re.compile(r"(^|/)(main|app|server|cli|manage|index|worker|run|startup)\.(py|ts|tsx|js|go|rs|java)$", re.I)
_CONFIG_RE = re.compile(r"(^|/)(Dockerfile|docker-compose.*\.ya?ml|compose.*\.ya?ml|pyproject\.toml|package\.json|Makefile|.*config.*\.(ya?ml|json|toml|py|ts)|\.github/workflows/.*\.ya?ml)$", re.I)
_RUNTIME_RE = re.compile(r"(^|/)(deploy|deployment|runtime|infra|scripts|helm|k8s|compose|docker|\.github/workflows)(/|$)", re.I)
_RUNBOOK_RE = re.compile(r"(^|/)(README|RUNBOOK|OPERATION|OPERATIONS|docs/.*|.*runbook.*)\.(md|rst|txt)$", re.I)


def _collect_matching_paths(session: Session, resource: Resource, pattern: re.Pattern[str], *, limit: int = 8) -> list[str]:
    if resource.current_snapshot_id is None:
        return []
    rows = session.execute(
        text(
            """
            SELECT DISTINCT COALESCE(NULLIF(path, ''), title) AS path
            FROM chunks
            WHERE workspace_id = :ws
              AND project_id = :proj
              AND resource_id = :res
              AND source_snapshot_id = :snap
              AND deleted_at IS NULL
              AND COALESCE(NULLIF(path, ''), title) IS NOT NULL
            ORDER BY path ASC
            """
        ),
        {"ws": resource.workspace_id, "proj": resource.project_id, "res": resource.id, "snap": resource.current_snapshot_id},
    ).mappings().all()
    matches = [str(row["path"]) for row in rows if pattern.search(str(row["path"]))]
    return matches[:limit]


def _repo_agent_readiness(resource: Resource, stats: Mapping[str, Any]) -> str:
    if resource.status != "active" or resource.archived_at is not None:
        return "inactive"
    if not resource.retrieval_enabled:
        return "retrieval-off"
    if resource.current_snapshot_id is None:
        return "not-indexed"
    if int(stats.get("chunk_count") or 0) == 0:
        return "empty-index"
    if int(stats.get("embedding_count") or 0) == 0:
        return "no-embeddings"
    if resource.review_status in {"needs_update", "stale"}:
        return "needs-review"
    return "ready"


def _repo_agent_brief_response(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    resource: Resource,
) -> RepoAgentBriefRead:
    if resource.type.lower() != "git":
        raise HTTPException(status_code=422, detail="repo-agent brief is only available for git resources")
    stats = cast(
        Mapping[str, Any],
        session.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM chunks c WHERE c.workspace_id = :ws AND c.project_id = :proj AND c.resource_id = :res AND c.source_snapshot_id = :snap AND c.deleted_at IS NULL) AS chunk_count,
                  (SELECT COUNT(*) FROM code_symbols cs WHERE cs.workspace_id = :ws AND cs.project_id = :proj AND cs.resource_id = :res AND cs.source_snapshot_id = :snap AND cs.deleted_at IS NULL) AS symbol_count,
                  (SELECT COUNT(*) FROM graph_nodes gn WHERE gn.workspace_id = :ws AND gn.project_id = :proj AND gn.resource_id = :res AND gn.source_snapshot_id = :snap) AS graph_node_count,
                  (SELECT COUNT(*) FROM graph_edges ge WHERE ge.workspace_id = :ws AND ge.project_id = :proj AND ge.resource_id = :res AND ge.source_snapshot_id = :snap) AS graph_edge_count,
                  (SELECT COUNT(*) FROM chunk_embeddings ce WHERE ce.workspace_id = :ws AND ce.project_id = :proj AND ce.resource_id = :res AND ce.source_snapshot_id = :snap) AS embedding_count,
                  (SELECT MAX(finished_at) FROM index_runs ir WHERE ir.workspace_id = :ws AND ir.project_id = :proj AND ir.resource_id = :res AND ir.status = 'succeeded') AS last_index_finished_at,
                  (SELECT status FROM index_runs ir WHERE ir.workspace_id = :ws AND ir.project_id = :proj AND ir.resource_id = :res ORDER BY created_at DESC LIMIT 1) AS last_index_status,
                  (SELECT metadata FROM source_snapshots ss WHERE ss.id = :snap AND ss.workspace_id = :ws AND ss.project_id = :proj AND ss.resource_id = :res) AS snapshot_metadata
                """
            ),
            {"ws": workspace_id, "proj": project_id, "res": resource.id, "snap": resource.current_snapshot_id},
        ).mappings().first()
        or {},
    )
    snapshot_metadata = cast(dict[str, Any], stats.get("snapshot_metadata") if isinstance(stats.get("snapshot_metadata"), dict) else {})
    source_config = cast(dict[str, Any], resource.source_config or {})
    entrypoints = _collect_matching_paths(session, resource, _ENTRYPOINT_RE)
    configs = _collect_matching_paths(session, resource, _CONFIG_RE)
    runtime_paths = _collect_matching_paths(session, resource, _RUNTIME_RE)
    runbooks = _collect_matching_paths(session, resource, _RUNBOOK_RE)
    symbol_rows = session.execute(
        text(
            """
            SELECT path, name, kind, language, line_start, line_end, signature, content_hash
            FROM code_symbols
            WHERE workspace_id = :ws
              AND project_id = :proj
              AND resource_id = :res
              AND source_snapshot_id = :snap
              AND deleted_at IS NULL
            ORDER BY CASE kind WHEN 'class' THEN 0 WHEN 'function' THEN 1 ELSE 2 END, path ASC, line_start ASC
            LIMIT 12
            """
        ),
        {"ws": workspace_id, "proj": project_id, "res": resource.id, "snap": resource.current_snapshot_id},
    ).mappings().all()
    symbol_samples = [
        {
            "path": row["path"],
            "name": row["name"],
            "kind": row["kind"],
            "language": row["language"],
            "line_start": row["line_start"],
            "line_end": row["line_end"],
            "signature": row["signature"],
            "content_hash": row["content_hash"],
        }
        for row in symbol_rows
    ]
    readiness = _repo_agent_readiness(resource, stats)
    branch = source_config.get("branch") or source_config.get("ref") or snapshot_metadata.get("branch")
    commit = snapshot_metadata.get("commit") or snapshot_metadata.get("version")
    last_index_finished_at = stats.get("last_index_finished_at")
    suggested_questions = [
        f"What is {resource.name} responsible for? Cite exact files.",
        f"Show {resource.name}'s main entrypoints, configs, and runtime/deployment boundaries.",
        f"What tests or checks should run before changing {resource.name}?",
        f"Find runbooks, operational risks, and production-mutation boundaries for {resource.name}.",
    ]
    quality_gates = [
        "current_snapshot_id is present" if resource.current_snapshot_id else "missing current_snapshot_id",
        f"chunks={int(stats.get('chunk_count') or 0)}",
        f"embeddings={int(stats.get('embedding_count') or 0)}",
        f"symbols={int(stats.get('symbol_count') or 0)}",
        f"last_index_status={stats.get('last_index_status') or 'unknown'}",
        f"review_status={resource.review_status}",
    ]
    brief_lines = [
        f"{resource.name} is a git-backed repo sub-agent scoped to resource `{resource.id}`.",
        f"Readiness: {readiness}. Branch/ref: {branch or 'default'}. Commit/version: {commit or resource.current_snapshot_id or 'none'}.",
        f"Index shape: {int(stats.get('chunk_count') or 0)} chunks, {int(stats.get('symbol_count') or 0)} symbols, {int(stats.get('graph_node_count') or 0)} graph nodes, {int(stats.get('embedding_count') or 0)} embeddings.",
    ]
    if entrypoints:
        brief_lines.append("Likely entrypoints: " + ", ".join(entrypoints[:5]) + ".")
    if configs:
        brief_lines.append("Likely config/build files: " + ", ".join(configs[:5]) + ".")
    if runtime_paths:
        brief_lines.append("Likely runtime/deployment paths: " + ", ".join(runtime_paths[:5]) + ".")
    if runbooks:
        brief_lines.append("Likely docs/runbooks: " + ", ".join(runbooks[:5]) + ".")
    brief_lines.append("Use this repo-agent for repo-specific explanation, code navigation, cited operating briefs, and change-impact questions. Do not use it as authorization for production mutations.")
    return RepoAgentBriefRead(
        resource_id=resource.id,
        name=_sanitize_metadata_text(resource.name),
        uri=_sanitize_public_uri(resource.uri),
        readiness=readiness,
        current_snapshot_id=resource.current_snapshot_id,
        branch=branch,
        commit=commit,
        update_frequency=resource.update_frequency,
        freshness={
            "review_status": resource.review_status,
            "last_refresh_finished_at": resource.last_refresh_finished_at.isoformat() if resource.last_refresh_finished_at else None,
            "next_refresh_at": resource.next_refresh_at.isoformat() if resource.next_refresh_at else None,
            "last_index_finished_at": last_index_finished_at.isoformat() if isinstance(last_index_finished_at, datetime) else None,
            "last_index_status": stats.get("last_index_status"),
        },
        stats={
            "chunk_count": int(stats.get("chunk_count") or 0),
            "symbol_count": int(stats.get("symbol_count") or 0),
            "graph_node_count": int(stats.get("graph_node_count") or 0),
            "graph_edge_count": int(stats.get("graph_edge_count") or 0),
            "embedding_count": int(stats.get("embedding_count") or 0),
        },
        operating_brief="\n".join(brief_lines),
        entrypoint_paths=entrypoints,
        config_paths=configs,
        runtime_paths=runtime_paths,
        runbook_paths=runbooks,
        symbol_samples=symbol_samples,
        suggested_questions=suggested_questions,
        invocation={
            "endpoint": f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
            "body": {"runtime": "hermes", "resource_ids": [str(resource.id)], "include_code_symbols": True},
        },
        safety_boundary="Context only. Production mutations require Hermes approval, typed MCP tools, and evidence workflow.",
        quality_gates=quality_gates,
    )


def _purge_resource_artifacts(session: Session, resource: Resource) -> dict[str, int]:
    params = {"resource_id": resource.id}
    family_ref = session.execute(
        text(
            """
            SELECT 1
            FROM snapshot_sections
            WHERE section_family_resource_id = :resource_id
              AND version_resource_id <> :resource_id
            UNION ALL
            SELECT 1
            FROM context_artifact_citations
            WHERE section_family_resource_id = :resource_id
              AND resource_id <> :resource_id
            LIMIT 1
            """
        ),
        params,
    ).first()
    if family_ref is not None:
        raise HTTPException(status_code=409, detail="This source family still has compiled versions. Delete dependent versions first.")
    pack_refs = session.execute(
        text(
            """
            SELECT cpv.pack_key, cpv.version, cpv.status
            FROM context_pack_resource_coverage cprc
            JOIN context_pack_versions cpv ON cpv.id = cprc.context_pack_version_id
            WHERE cprc.resource_id = :resource_id
              AND cpv.status <> 'invalidated'
            ORDER BY cpv.pack_key, cpv.version
            """
        ),
        params,
    ).mappings().all()
    if pack_refs:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Resource is covered by Context Pack versions. Invalidate those pack versions before hard purge.",
                "context_packs": [dict(row) for row in pack_refs],
            },
        )
    skill_export_refs = session.execute(
        text(
            """
            SELECT se.pack_key, se.pack_version, se.export_version, se.status, se.package_hash
            FROM skill_exports se
            JOIN context_pack_resource_coverage cprc ON cprc.context_pack_version_id = se.context_pack_version_id
            WHERE cprc.resource_id = :resource_id
              AND se.files_json <> '[]'::jsonb
            ORDER BY se.pack_key, se.pack_version, se.export_version
            """
        ),
        params,
    ).mappings().all()
    if skill_export_refs:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Resource is referenced by generated skill exports with retained files. Invalidate/scrub those exports before hard purge.",
                "skill_exports": [dict(row) for row in skill_export_refs],
            },
        )
    repo_agent_refs = session.execute(
        text(
            """
            SELECT ra.agent_key, COALESCE(rav.version, 0) AS version, COALESCE(rav.status, ra.status) AS status
            FROM repo_agents ra
            LEFT JOIN repo_agent_versions rav ON rav.repo_agent_id = ra.id AND rav.resource_id = :resource_id
            WHERE ra.resource_id = :resource_id OR rav.resource_id = :resource_id
            ORDER BY ra.agent_key, rav.version
            """
        ),
        params,
    ).mappings().all()
    if repo_agent_refs:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Resource is referenced by Repo Agent versions. Archive, invalidate, and scrub those versions before hard purge.",
                "repo_agents": [dict(row) for row in repo_agent_refs],
            },
        )
    graph_merge_refs = session.execute(
        text(
            """
            SELECT gm.merge_key, gmv.version, gmv.status
            FROM graph_merge_inputs gmi
            JOIN graph_merge_versions gmv ON gmv.id = gmi.graph_merge_version_id
            JOIN graph_merges gm ON gm.id = gmv.graph_merge_id
            WHERE gmi.input_resource_id = :resource_id
            ORDER BY gm.merge_key, gmv.version
            """
        ),
        params,
    ).mappings().all()
    if graph_merge_refs:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Resource is referenced by retained graph merge versions. E1 retains merge provenance, so hard purge remains blocked until a later scrub/delete lifecycle removes those versions.",
                "graph_merges": [dict(row) for row in graph_merge_refs],
            },
        )
    graph_refs = session.execute(
        text(
            """
            SELECT g.graph_key, COALESCE(gv.version, 0) AS version, COALESCE(gv.status, g.status) AS status
            FROM graphs g
            LEFT JOIN graph_versions gv ON gv.graph_id = g.id AND gv.resource_id = :resource_id
            WHERE g.resource_id = :resource_id OR gv.resource_id = :resource_id
            ORDER BY g.graph_key, gv.version
            """
        ),
        params,
    ).mappings().all()
    if graph_refs:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Resource is referenced by retained graph streams or graph versions. Archive zero-version graphs, or invalidate/retain graph versions before hard purge.",
                "graphs": [dict(row) for row in graph_refs],
            },
        )
    statements = [
        ("resources_current_snapshot", "UPDATE resources SET current_snapshot_id = NULL WHERE id = :resource_id"),
        (
            "context_pack_resource_coverage",
            "DELETE FROM context_pack_resource_coverage WHERE resource_id = :resource_id",
        ),
        (
            "context_pack_artifacts",
            "DELETE FROM context_pack_artifacts WHERE resource_id = :resource_id OR context_artifact_id IN (SELECT id FROM context_artifacts WHERE resource_id = :resource_id)",
        ),
        (
            "context_artifact_citations",
            """
            DELETE FROM context_artifact_citations
            WHERE resource_id = :resource_id
               OR context_artifact_id IN (SELECT id FROM context_artifacts WHERE resource_id = :resource_id)
            """,
        ),
        (
            "context_artifact_sources",
            """
            DELETE FROM context_artifact_sources
            WHERE resource_id = :resource_id
               OR context_artifact_id IN (SELECT id FROM context_artifacts WHERE resource_id = :resource_id)
            """,
        ),
        ("context_artifacts", "DELETE FROM context_artifacts WHERE resource_id = :resource_id"),
        ("snapshot_sections", "DELETE FROM snapshot_sections WHERE version_resource_id = :resource_id"),
        (
            "orphan_sections",
            """
            DELETE FROM sections s
            WHERE s.section_family_resource_id = :resource_id
              AND NOT EXISTS (SELECT 1 FROM snapshot_sections ss WHERE ss.section_id = s.id)
              AND NOT EXISTS (SELECT 1 FROM context_artifact_citations cac WHERE cac.section_id = s.id)
            """,
        ),
        ("pr_requests", "DELETE FROM pr_requests WHERE resource_id = :resource_id"),
        ("patch_proposals", "DELETE FROM patch_proposals WHERE resource_id = :resource_id"),
        ("agent_card_summaries", "DELETE FROM agent_card_summaries WHERE resource_id = :resource_id"),
        ("context_packet_items", "DELETE FROM context_packet_items WHERE resource_id = :resource_id"),
        ("retrieval_hits", "DELETE FROM retrieval_hits WHERE resource_id = :resource_id"),
        ("chunk_embeddings", "DELETE FROM chunk_embeddings WHERE resource_id = :resource_id"),
        ("graph_edges", "DELETE FROM graph_edges WHERE resource_id = :resource_id"),
        ("graph_nodes", "DELETE FROM graph_nodes WHERE resource_id = :resource_id"),
        ("code_symbols", "DELETE FROM code_symbols WHERE resource_id = :resource_id"),
        ("resource_manifest_files", "DELETE FROM resource_manifest_files WHERE resource_id = :resource_id"),
        ("resource_manifests", "DELETE FROM resource_manifests WHERE resource_id = :resource_id"),
        ("snapshot_files", "DELETE FROM snapshot_files WHERE resource_id = :resource_id"),
        ("chunks", "DELETE FROM chunks WHERE resource_id = :resource_id"),
        ("index_runs", "DELETE FROM index_runs WHERE resource_id = :resource_id"),
        ("source_snapshots", "DELETE FROM source_snapshots WHERE resource_id = :resource_id"),
    ]
    counts: dict[str, int] = {}
    for name, sql in statements:
        result = session.execute(text(sql), params)
        counts[name] = int(result.rowcount or 0)  # type: ignore[attr-defined]
    result = session.execute(text("DELETE FROM resources WHERE id = :resource_id"), params)
    counts["resources"] = int(result.rowcount or 0)  # type: ignore[attr-defined]
    return counts


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


def remote_search_code(
    workspace_id: UUID,
    project_id: UUID,
    payload: RemoteSearchCodeRequest,
    principal: Principal,
    session: Session,
) -> RemoteSearchCodeResponse:
    return remote_code_router.remote_search_code(workspace_id, project_id, payload, principal, session)


def search_project(
    workspace_id: UUID,
    project_id: UUID,
    payload: SearchRequest,
    principal: Principal,
    session: Session,
) -> Any:
    return remote_code_router.search_project(workspace_id, project_id, payload, principal, session)


def code_search_project(
    workspace_id: UUID,
    project_id: UUID,
    payload: CodeSearchRequest,
    principal: Principal,
    session: Session,
) -> Any:
    return remote_code_router.code_search_project(workspace_id, project_id, payload, principal, session)


def remote_generate_patch(
    workspace_id: UUID,
    project_id: UUID,
    payload: GeneratePatchRequest,
    principal: Principal,
    session: Session,
) -> Any:
    return remote_code_router.remote_generate_patch(workspace_id, project_id, payload, principal, session)


def remote_open_pr(
    workspace_id: UUID,
    project_id: UUID,
    payload: OpenPrRequest,
    principal: Principal,
    session: Session,
) -> Any:
    return remote_code_router.remote_open_pr(workspace_id, project_id, payload, principal, session)


def remote_grep_code(
    workspace_id: UUID,
    project_id: UUID,
    payload: RemoteGrepCodeRequest,
    principal: Principal,
    session: Session,
) -> RemoteGrepCodeResponse:
    return remote_code_router.remote_grep_code(workspace_id, project_id, payload, principal, session)


def remote_read_file(
    workspace_id: UUID,
    project_id: UUID,
    payload: RemoteReadFileRequest,
    principal: Principal,
    session: Session,
) -> RemoteReadFileResponse:
    return remote_code_router.remote_read_file(workspace_id, project_id, payload, principal, session)


def remote_find_symbol(
    workspace_id: UUID,
    project_id: UUID,
    payload: RemoteFindSymbolRequest,
    principal: Principal,
    session: Session,
) -> RemoteFindSymbolResponse:
    return remote_code_router.remote_find_symbol(workspace_id, project_id, payload, principal, session)


def _execute_remote_code_rpc_call(
    workspace_id: UUID,
    project_id: UUID,
    call_method: str,
    params: dict[str, Any],
    principal: Principal,
    session: Session,
) -> dict[str, Any]:
    return remote_code_router._execute_remote_code_rpc_call(workspace_id, project_id, call_method, params, principal, session)


def remote_code_rpc_spec(
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    session: Session,
) -> Any:
    return remote_code_router.remote_code_rpc_spec(workspace_id, project_id, principal, session)


def remote_code_rpc(
    workspace_id: UUID,
    project_id: UUID,
    payload: Any,
    principal: Principal,
    session: Session,
) -> Any:
    return remote_code_router.remote_code_rpc(workspace_id, project_id, payload, principal, session)


app.include_router(remote_code_router.create_router(_remote_code_router_deps))


def _record_agent_context_usage(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    payload: AgentContextRequest,
    principal: Principal,
    candidates: list[RetrievalCandidate],
) -> None:
    """Persist usage rows for agent-context without creating a context packet artifact."""
    embedding_config = current_embedding_config()
    vector_diagnostics = embedding_namespace_diagnostics(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        resource_ids=payload.resource_ids,
    )
    query_run = QueryRun(
        workspace_id=workspace_id,
        project_id=project_id,
        actor_user_id=principal.user.id,
        query=payload.query,
        mode=f"agent-context:{payload.runtime or 'default'}",
        top_k=payload.top_k,
        provider=embedding_config.provider,
        model=embedding_config.model,
        status="succeeded",
        hit_count=len(candidates),
        finished_at=datetime.now(UTC),
        meta={
            "resource_ids": [str(rid) for rid in payload.resource_ids or []],
            "runtime": payload.runtime,
            "retrieval_profile": normalize_retrieval_profile(payload.profile).name,
            "context_max_chars": payload.max_chars,
            "include_code_symbols": payload.include_code_symbols,
            "source": "agent-context",
            **vector_diagnostics,
        },
    )
    session.add(query_run)
    session.flush()
    for rank, candidate in enumerate(candidates, start=1):
        session.add(
            RetrievalHit(
                workspace_id=workspace_id,
                project_id=project_id,
                query_run_id=query_run.id,
                resource_id=candidate.resource_id,
                source_snapshot_id=candidate.snapshot_id,
                chunk_id=candidate.chunk_id,
                rank=rank,
                lexical_score=candidate.lexical_score,
                vector_score=candidate.vector_score,
                graph_score=candidate.graph_score,
                rerank_score=candidate.rerank_score,
                score=candidate.score,
                meta={
                    "path": candidate.path,
                    "content_hash": candidate.content_hash,
                    "source": "agent-context",
                },
            )
        )
    session.commit()




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






















def _resource_coverage_entry(session: Session, resource: Resource) -> dict[str, Any]:
    read = _resource_read(session, resource)
    diagnostics = read.index_diagnostics or {}
    last_index = session.scalar(
        select(IndexRun)
        .where(
            IndexRun.workspace_id == resource.workspace_id,
            IndexRun.project_id == resource.project_id,
            IndexRun.resource_id == resource.id,
        )
        .order_by(IndexRun.created_at.desc())
        .limit(1)
    )
    entry: dict[str, Any] = {
        "resource_id": str(resource.id),
        "name": resource.name,
        "queryable": read.queryable,
        "coverage_status": read.coverage_status,
        "coverage_warnings": read.coverage_warnings,
        "current_snapshot_id": str(resource.current_snapshot_id) if resource.current_snapshot_id else None,
        "retrieval_enabled": resource.retrieval_enabled,
        "configured_budgets": diagnostics.get("configured_budgets", {}),
        "limited_budget_keys": diagnostics.get("limited_budget_keys", []),
        "budget_reason": _coverage_budget_reason(read),
        "suggested_retry": diagnostics.get("suggested_retry"),
        "file_budget_stats": diagnostics.get("file_budget_stats", {}),
    }
    if last_index is not None:
        safe_failure = _runtime_safe_index_failure(last_index.error_message) if last_index.status == "failed" else None
        entry["last_index"] = {
            "status": last_index.status,
            "failure_summary": safe_failure,
            "documents_seen": last_index.documents_seen,
            "chunks_created": last_index.chunks_created,
            "symbols_created": last_index.symbols_created,
            "embeddings_created": last_index.embeddings_created,
            "started_at": last_index.started_at.isoformat() if last_index.started_at else None,
            "finished_at": last_index.finished_at.isoformat() if last_index.finished_at else None,
        }
        if safe_failure:
            entry.setdefault("coverage_warnings", []).append(safe_failure)
    return entry


def _agent_context_resource_coverage(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    resource_ids: list[UUID] | None,
    citations: list[AgentContextCitation],
    principal: Principal,
) -> tuple[list[dict[str, Any]], list[str]]:
    if resource_ids:
        ids = list(dict.fromkeys(resource_ids))
        predicates = [Resource.id.in_(ids)]
    else:
        ids = []
        predicates = []
    resources = list(
        session.scalars(
            select(Resource).where(
                Resource.workspace_id == workspace_id,
                Resource.project_id == project_id,
                Resource.deleted_at.is_(None),
                *predicates,
            )
        )
    )
    resources = [resource for resource in resources if token_allows_resource(principal, resource.id)]
    by_id = {resource.id: resource for resource in resources}
    ordered_ids = ids or [resource.id for resource in resources]
    citation_counts = Counter(citation.resource_id for citation in citations)
    explicit_multi_resource_request = bool(resource_ids and len(ids) > 1)
    coverage = []
    for rid in ordered_ids:
        if rid not in by_id:
            continue
        entry = _resource_coverage_entry(session, by_id[rid])
        citation_count = int(citation_counts.get(rid, 0))
        entry["citation_count"] = citation_count
        entry["evidence_status"] = "cited" if citation_count > 0 else "missing_citations"
        coverage.append(entry)
    warnings: list[str] = []
    for entry in coverage:
        for warning in entry.get("coverage_warnings", []):
            warnings.append(f"{entry['name']}: {warning}")
        if explicit_multi_resource_request and entry.get("citation_count", 0) == 0:
            warnings.append(
                "missing_requested_resources: "
                f"{entry['name']} ({entry['resource_id']}) returned zero citations for this query; "
                "narrow the query, raise top_k, or inspect the resource directly before making a comparison claim"
            )
    return coverage, warnings


def _looks_like_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


def _agent_context_with_resource_ref(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    payload: AgentContextRequest,
) -> AgentContextRequest:
    return cast(AgentContextRequest, _request_with_resource_refs(session, workspace_id, project_id, principal, payload))


def _build_pack_agent_context_response(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    payload: AgentContextRequest,
    principal: Principal,
    pack_version: ContextPackVersion,
) -> AgentContextResponse:
    predicates = [
        ContextPackArtifact.context_pack_version_id == pack_version.id,
        ContextArtifactCitation.workspace_id == workspace_id,
        ContextArtifactCitation.project_id == project_id,
    ]
    if payload.resource_ids:
        predicates.append(ContextArtifactCitation.resource_id.in_(payload.resource_ids))
    rows = session.execute(
        select(ContextArtifactCitation, SnapshotFile)
        .join(
            SnapshotFile,
            (SnapshotFile.source_snapshot_id == ContextArtifactCitation.source_snapshot_id)
            & (SnapshotFile.path == ContextArtifactCitation.normalized_path),
        )
        .join(ContextPackArtifact, ContextPackArtifact.context_artifact_id == ContextArtifactCitation.context_artifact_id)
        .where(*predicates)
        .order_by(ContextPackArtifact.ordinal.asc(), ContextArtifactCitation.normalized_path.asc(), ContextArtifactCitation.ordinal.asc())
        .limit(payload.top_k)
    ).all()
    citations: list[AgentContextCitation] = []
    context_parts: list[str] = []
    used_chars = 0
    for rank, (citation, snapshot_file) in enumerate(rows, start=1):
        if not token_allows_resource(principal, citation.resource_id):
            continue
        header = f"[{rank}] pack={pack_version.pack_key} v{pack_version.version} resource={citation.resource_id} snapshot={citation.source_snapshot_id} path={citation.normalized_path} ordinal={citation.ordinal}\n"
        remaining = payload.max_chars - used_chars - (2 if context_parts else 0)
        if remaining <= len(header):
            break
        snippet = make_snippet(snapshot_file.content, limit=min(1200, max(120, remaining - len(header))))
        entry = header + snippet
        if len(entry) > remaining:
            entry = entry[:remaining]
        context_parts.append(entry)
        used_chars += len(entry) + (2 if len(context_parts) > 1 else 0)
        citations.append(
            AgentContextCitation(
                resource_id=citation.resource_id,
                snapshot_id=citation.source_snapshot_id,
                chunk_id=citation.section_id,
                path=citation.normalized_path,
                title=citation.title,
                ordinal=citation.ordinal,
                content_hash=citation.content_hash,
                version=pack_version.pack_hash,
                version_kind="context_pack",
                commit=None,
                score=1.0,
                graph_score=0.0,
            )
        )
    profile = session.scalar(select(AgentProfile).where(AgentProfile.workspace_id == workspace_id, AgentProfile.project_id == project_id))
    actual_runtime = payload.runtime or (profile.default_runtime if profile else "api")
    resource_coverage, coverage_warnings = _agent_context_resource_coverage(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        resource_ids=payload.resource_ids,
        citations=citations,
        principal=principal,
    )
    instruction_parts = [COMMON_AGENT_INSTRUCTION, RUNTIME_INSTRUCTIONS[actual_runtime], f"Use published Context Pack `{pack_version.pack_key}` v{pack_version.version}. Snapshot pinning is enforced; do not use newer source snapshots for this answer."]
    if coverage_warnings:
        instruction_parts.append("Coverage warning: " + " ".join(coverage_warnings))
    if profile and profile.system_prompt:
        instruction_parts.append(profile.system_prompt)
    can_read_code = _principal_has_scope(principal, "code:read")
    return AgentContextResponse(
        query=payload.query,
        profile="context_pack",
        runtime=actual_runtime,
        instruction=" ".join(instruction_parts),
        context="\n\n".join(context_parts),
        answer=(
            _synthesize_agent_answer(
                query=payload.query,
                context_parts=context_parts,
                citations=citations,
                resource_coverage=resource_coverage,
                coverage_warnings=coverage_warnings,
            )
            if payload.include_answer
            else None
        ),
        citations=citations,
        symbols=[],
        suggested_tool_calls=_agent_context_suggested_tool_calls(citations, payload.query, include_code_tools=can_read_code),
        token_budget_hint=max(1, payload.max_chars // 4),
        resource_coverage=resource_coverage,
        coverage_warnings=coverage_warnings,
        context_pack_key=pack_version.pack_key,
        context_pack_version=pack_version.version,
        context_pack_version_id=pack_version.id,
        context_pack_status=pack_version.status,
        context_pack_snapshot_pin_enforced=True,
    )




def _build_agent_context_response(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    payload: AgentContextRequest,
    principal: Principal,
) -> AgentContextResponse:
    retrieval_profile = normalize_retrieval_profile(payload.profile)
    candidates = retrieve_context_candidates(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        query=payload.query,
        top_k=payload.top_k,
        resource_ids=payload.resource_ids,
        profile=retrieval_profile.name,
    )
    citations: list[AgentContextCitation] = []
    context_parts: list[str] = []
    used_candidates: list[RetrievalCandidate] = []
    used_chars = 0
    for rank, candidate in enumerate(candidates, start=1):
        header = (
            f"[{rank}] resource={candidate.resource_id} snapshot={candidate.snapshot_id} "
            f"path={candidate.path or '-'} ordinal={candidate.ordinal} score={candidate.score:.4f}\n"
        )
        remaining = payload.max_chars - used_chars - (2 if context_parts else 0)
        if remaining <= len(header):
            break
        snippet = make_snippet(candidate.content, limit=min(1200, max(120, remaining - len(header))))
        entry = header + snippet
        if len(entry) > remaining:
            entry = entry[:remaining]
        if not entry.strip():
            break
        context_parts.append(entry)
        used_candidates.append(candidate)
        used_chars += len(entry) + (2 if len(context_parts) > 1 else 0)
        citations.append(
            AgentContextCitation(
                resource_id=candidate.resource_id,
                snapshot_id=candidate.snapshot_id,
                chunk_id=candidate.chunk_id,
                path=candidate.path,
                title=candidate.title,
                ordinal=candidate.ordinal,
                content_hash=candidate.content_hash,
                version=candidate.version,
                version_kind=candidate.version_kind,
                commit=candidate.snapshot_metadata.get("commit"),
                score=candidate.score,
                graph_score=candidate.graph_score,
                score_components=candidate.ranking_diagnostics or {},
            )
        )
    symbols: list[CodeSymbolHit] = []
    can_read_code = _principal_has_scope(principal, "code:read")
    code_symbol_warning: str | None = None
    if payload.include_code_symbols and can_read_code:
        symbol_response = code_search_project(
            workspace_id=workspace_id,
            project_id=project_id,
            payload=CodeSearchRequest(query=payload.query, resource_ids=payload.resource_ids, limit=min(payload.top_k, 20)),
            principal=principal,
            session=session,
        )
        symbols = symbol_response.symbols
    elif payload.include_code_symbols:
        code_symbol_warning = "code symbols omitted: missing required scope code:read"
    profile = session.scalar(
        select(AgentProfile).where(
            AgentProfile.workspace_id == workspace_id,
            AgentProfile.project_id == project_id,
        )
    )
    actual_runtime = payload.runtime or (profile.default_runtime if profile else "api")
    resource_coverage, coverage_warnings = _agent_context_resource_coverage(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        resource_ids=payload.resource_ids,
        citations=citations,
        principal=principal,
    )
    if code_symbol_warning:
        coverage_warnings = [*coverage_warnings, code_symbol_warning]
    instruction_parts = [COMMON_AGENT_INSTRUCTION, RUNTIME_INSTRUCTIONS[actual_runtime]]
    if coverage_warnings:
        instruction_parts.append("Coverage warning: " + " ".join(coverage_warnings))
    if profile and profile.system_prompt:
        instruction_parts.append(profile.system_prompt)
    _record_agent_context_usage(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        payload=payload,
        principal=principal,
        candidates=used_candidates,
    )
    return AgentContextResponse(
        query=payload.query,
        profile=retrieval_profile.name,
        runtime=actual_runtime,
        instruction=" ".join(instruction_parts),
        context="\n\n".join(context_parts),
        answer=(
            _synthesize_agent_answer(
                query=payload.query,
                context_parts=context_parts,
                citations=citations,
                resource_coverage=resource_coverage,
                coverage_warnings=coverage_warnings,
            )
            if payload.include_answer
            else None
        ),
        citations=citations,
        symbols=symbols,
        suggested_tool_calls=_agent_context_suggested_tool_calls(citations, payload.query, include_code_tools=can_read_code),
        token_budget_hint=max(1, payload.max_chars // 4),
        resource_coverage=resource_coverage,
        coverage_warnings=coverage_warnings,
        retrieval_metadata={
            **_agent_context_retrieval_metadata(used_candidates, payload.resource_ids),
            "code_symbols_requested": payload.include_code_symbols,
            "code_symbols_returned": len(symbols),
            "code_symbols_omitted_reason": "missing_scope:code:read" if code_symbol_warning else None,
        },
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





def _mcp_tool_error(rpc_id: object | None, status_code: int, detail: object) -> dict:
    payload = {"status_code": status_code, "detail": detail}
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "structuredContent": payload,
            "isError": True,
        },
    }




def _runtime_cursor(cursor: str | None) -> int:
    if cursor in (None, ""):
        return 0
    try:
        value = int(str(cursor))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_cursor", "message": "cursor must be an integer offset"}) from exc
    if value < 0:
        raise HTTPException(status_code=422, detail={"code": "invalid_cursor", "message": "cursor must be non-negative"})
    return value


def _runtime_limit(value: object, *, default: int = 100, max_value: int = 500) -> int:
    try:
        parsed = int(str(value)) if value is not None else default
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_limit", "message": "limit must be an integer"}) from exc
    return max(1, min(parsed, max_value))


def _runtime_resource_allowed_or_404(principal: Principal, resource_id: UUID) -> None:
    if not token_allows_resource(principal, resource_id):
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "resource not found"})


def _runtime_resource_rows_allowed(principal: Principal, resource_ids: list[UUID]) -> bool:
    return all(token_allows_resource(principal, resource_id) for resource_id in resource_ids)


def _runtime_resource_freshness(session: Session, resource: Resource, snapshot_id: UUID | None = None) -> dict[str, Any]:
    effective_snapshot_id = snapshot_id or resource.current_snapshot_id
    status = "current" if effective_snapshot_id is not None and effective_snapshot_id == resource.current_snapshot_id else "stale"
    warnings: list[str] = []
    if resource.deleted_at is not None:
        status = "deleted"
        warnings.append("resource is deleted")
    elif resource.archived_at is not None:
        status = "archived"
        warnings.append("resource is archived")
    elif status == "stale":
        warnings.append("artifact is based on a non-current source snapshot")
    return {
        "resource_id": str(resource.id),
        "name": resource.name,
        "artifact_snapshot_id": str(effective_snapshot_id) if effective_snapshot_id else None,
        "current_snapshot_id": str(resource.current_snapshot_id) if resource.current_snapshot_id else None,
        "status": status,
        "warning": "; ".join(warnings) if warnings else None,
    }


def _runtime_freshness(status: str = "current", *, warnings: list[str] | None = None, resources: list[dict[str, Any]] | None = None, pack: dict[str, Any] | None = None, artifact: dict[str, Any] | None = None, graph: dict[str, Any] | None = None) -> dict[str, Any]:
    computed_warnings = list(warnings or [])
    if resources:
        for resource in resources:
            warning = resource.get("warning")
            if warning:
                computed_warnings.append(str(warning))
        if any(resource.get("status") not in {"current", None} for resource in resources) and status == "current":
            status = "partial" if len(resources) > 1 else "stale"
    return {"status": status, "warnings": sorted(set(computed_warnings)), "generated_at": datetime.now(UTC), "pack": pack, "artifact": artifact, "graph": graph, "resources": resources or [], "coverage_complete": True}


def _runtime_citation_locator(citation: ContextArtifactCitation) -> dict[str, Any]:
    return {
        "resource_id": str(citation.resource_id),
        "source_snapshot_id": str(citation.source_snapshot_id),
        "snapshot_section_id": str(citation.snapshot_section_id),
        "context_artifact_id": str(citation.context_artifact_id),
        "context_artifact_citation_id": str(citation.id),
        "path": citation.normalized_path,
        "title": citation.title,
        "start_line": citation.line_start,
        "end_line": citation.line_end,
        "content_hash": citation.content_hash,
    }






def _resource_ref_values(resource_ref: Any = None, resource_refs: Any = None) -> list[str]:
    values: list[str] = []
    if resource_ref is not None and str(resource_ref).strip():
        values.append(str(resource_ref).strip())
    if resource_refs:
        if not isinstance(resource_refs, list):
            raise HTTPException(status_code=422, detail={"code": "invalid_resource_refs", "message": "resource_refs must be an array of names/refs"})
        values.extend(str(ref).strip() for ref in resource_refs if str(ref).strip())
    return list(dict.fromkeys(values))


def _dedupe_uuid_values(values: list[Any]) -> list[UUID]:
    result: list[UUID] = []
    seen: set[UUID] = set()
    for value in values:
        item = value if isinstance(value, UUID) else UUID(str(value))
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _resolve_resource_ref_ids(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, *, resource_ref: Any = None, resource_refs: Any = None) -> list[UUID]:
    ids: list[UUID] = []
    for ref in _resource_ref_values(resource_ref, resource_refs):
        ids.append(_runtime_resolve_resource_ref(session, workspace_id, project_id, principal, {"resource_ref": ref}).id)
    return _dedupe_uuid_values(ids)


def _request_with_resource_refs(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    payload: SearchRequest | AgentContextRequest,
) -> SearchRequest | AgentContextRequest:
    ref_ids = _resolve_resource_ref_ids(
        session,
        workspace_id,
        project_id,
        principal,
        resource_ref=payload.resource_ref,
        resource_refs=payload.resource_refs,
    )
    if not ref_ids:
        return payload
    resource_ids = _dedupe_uuid_values([*(payload.resource_ids or []), *ref_ids])
    return payload.model_copy(update={"resource_ids": resource_ids, "resource_ref": None, "resource_refs": None})


def _runtime_resolve_resource_ref(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any]) -> Resource:
    resource_id = args.get("resource_id")
    artifact_id = args.get("artifact_id")
    if artifact_id:
        artifact = session.scalar(select(ContextArtifact).where(ContextArtifact.id == UUID(str(artifact_id)), ContextArtifact.workspace_id == workspace_id, ContextArtifact.project_id == project_id))
        if artifact is None:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "resource not found"})
        _runtime_resource_allowed_or_404(principal, artifact.resource_id)
        resource_id = artifact.resource_id
    if resource_id and not _looks_like_uuid(str(resource_id)):
        args = {**args, "resource_ref": str(resource_id), "resource_id": None}
        resource_id = None
    if resource_id:
        resource = session.scalar(select(Resource).where(Resource.id == UUID(str(resource_id)), Resource.workspace_id == workspace_id, Resource.project_id == project_id, Resource.deleted_at.is_(None), Resource.archived_at.is_(None)))
        if resource is None:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "resource not found"})
        _runtime_resource_allowed_or_404(principal, resource.id)
        return resource
    ref = str(args.get("resource_ref") or "").strip()
    if not ref:
        raise HTTPException(status_code=422, detail={"code": "missing_resource", "message": "resource_id, resource_ref, or artifact_id is required"})
    predicates = [Resource.workspace_id == workspace_id, Resource.project_id == project_id, Resource.deleted_at.is_(None), Resource.archived_at.is_(None)]
    try:
        ref_uuid = UUID(ref)
    except ValueError:
        ref_uuid = None
    if ref_uuid:
        predicates.append(Resource.id == ref_uuid)
    else:
        predicates.append(Resource.name.ilike(f"%{ref}%"))
    rows = [row for row in session.scalars(select(Resource).where(*predicates).order_by(Resource.name.asc()).limit(11)) if token_allows_resource(principal, row.id)]
    if len(rows) == 1:
        return rows[0]
    if len(rows) > 1:
        raise HTTPException(status_code=409, detail={"code": "ambiguous_resource", "candidates": [{"resource_id": str(row.id), "name": row.name, "type": row.type} for row in rows[:10]]})
    raise HTTPException(status_code=404, detail={"code": "not_found", "message": "resource not found"})


def _runtime_args_with_resource_ref(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: dict[str, Any],
    *,
    single: bool,
) -> dict[str, Any]:
    refs = _resource_ref_values(args.get("resource_ref"), args.get("resource_refs"))
    if not refs:
        return args
    if single:
        if len(refs) > 1:
            raise HTTPException(status_code=422, detail={"code": "too_many_resource_refs", "message": "this tool accepts one resource_ref"})
        if args.get("resource_id"):
            raise HTTPException(status_code=422, detail={"code": "conflicting_resource_locator", "message": "use resource_id or resource_ref, not both"})
        resource = _runtime_resolve_resource_ref(session, workspace_id, project_id, principal, {"resource_ref": refs[0]})
        updated = dict(args)
        updated.pop("resource_ref", None)
        updated.pop("resource_refs", None)
        updated["resource_id"] = str(resource.id)
        return updated
    ref_ids = _resolve_resource_ref_ids(session, workspace_id, project_id, principal, resource_refs=refs)
    current_ids = list(args.get("resource_ids") or [])
    updated = dict(args)
    updated.pop("resource_ref", None)
    updated.pop("resource_refs", None)
    updated["resource_ids"] = [str(item) for item in _dedupe_uuid_values([*current_ids, *ref_ids])]
    return updated


def _runtime_resolve_pack(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any]) -> ContextPackVersion:
    pack_key = args.get("pack_key")
    version_arg = args.get("version")
    version: ContextPackVersion | None
    if pack_key:
        version = _resolve_pack_version(session, workspace_id, project_id, str(pack_key), int(version_arg) if version_arg is not None else "current")
    else:
        version = session.scalar(select(ContextPackVersion).where(ContextPackVersion.workspace_id == workspace_id, ContextPackVersion.project_id == project_id, ContextPackVersion.status == PACK_STATUS_PUBLISHED).order_by(ContextPackVersion.created_at.desc()))
    if version is None:
        raise HTTPException(status_code=404, detail={"code": "pack_not_found", "message": "published context pack not found; call list_sources"})
    _require_pack_read(session, workspace_id, project_id, principal, version)
    return version






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
