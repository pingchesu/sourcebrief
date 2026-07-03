from __future__ import annotations

import json
import os
import re
from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, cast
from uuid import UUID, uuid4

from fastapi import (
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from redis import Redis
from rq import Queue
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sourcebrief_api import agent_files, agent_packs, git_env, runtime_install
from sourcebrief_api.app_factory import cors_origins, create_app, run_migrations_if_requested
from sourcebrief_api.auth import (
    Principal,
    hash_password,
    hash_token,
    new_plaintext_token,
    require_any_scope,
    require_principal,
    require_scope,
    require_workspace_member,
    session_scopes_for_role,
    token_allows_project,
    token_allows_resource,
    verify_password,
)
from sourcebrief_api.constants import (
    ALLOWED_TOKEN_SCOPES,
    COMMON_AGENT_INSTRUCTION,
    FOLDER_BUNDLE_RESOURCE_TYPES,
    RUNTIME_INSTRUCTIONS,
    UPLOAD_RESOURCE_TYPES,
    URL_RESOURCE_TYPES,
)
from sourcebrief_api.context_packs import (
    PACK_STATUS_PUBLISHED,
)
from sourcebrief_api.graph_merges import (
    GRAPH_MERGE_VERSION_PUBLISHED,
    find_path,
)
from sourcebrief_api.graph_versions import (
    GRAPH_VERSION_PUBLISHED,
)
from sourcebrief_api.remote_code import (
    line_range,
    validate_repo_path,
)
from sourcebrief_api.resource_map import (
    ARTIFACT_TYPE_RESOURCE_MAP,
)
from sourcebrief_api.retrieval import (
    DEFAULT_RETRIEVAL_PROFILE,
    RETRIEVAL_PROFILES,
    RetrievalCandidate,
    embedding_namespace_diagnostics,
    make_snippet,
    normalize_retrieval_profile,
    retrieval_profile_manifest,
    retrieve_context_candidates,
)
from sourcebrief_api.routers import context_packs as context_pack_router
from sourcebrief_api.routers import graphs as graph_router
from sourcebrief_api.routers import remote_code as remote_code_router
from sourcebrief_api.routers import repo_agents as repo_agent_router
from sourcebrief_api.routers import resource_artifacts as resource_artifact_router
from sourcebrief_api.routers import resource_lifecycle as resource_lifecycle_router
from sourcebrief_api.routers import runtime_agent as runtime_agent_router
from sourcebrief_api.routers import skill_exports as skill_export_router
from sourcebrief_api.routers import system as system_router
from sourcebrief_api.schemas import (
    AgentCardSummaryAcknowledgeRequest,
    AgentCardSummaryListResponse,
    AgentCardSummaryRead,
    AgentContextAnswer,
    AgentContextCitation,
    AgentContextRequest,
    AgentContextResponse,
    AgentProfileRead,
    AgentProfileUpdate,
    ApiTokenCreate,
    ApiTokenCreateResponse,
    ApiTokenRead,
    AuditEventRead,
    AuthLoginRequest,
    AuthLoginResponse,
    AuthLogoutResponse,
    CodeSearchRequest,
    CodeSymbolHit,
    ContextPacketItemRead,
    ContextPacketRead,
    ContextPacketRequest,
    CurrentUserResponse,
    DeletedFileImpactStubRead,
    DueRefreshResponse,
    FolderBundleUploadResponse,
    GeneratePatchRequest,
    GitResourceEnvRead,
    GraphMergeReviewRequest,
    IndexRunRead,
    ManifestDiffRead,
    ManifestDiffRowRead,
    OpenPrRequest,
    ProjectCreate,
    ProjectRead,
    RemoteFindSymbolRequest,
    RemoteFindSymbolResponse,
    RemoteGrepCodeRequest,
    RemoteGrepCodeResponse,
    RemoteReadFileRequest,
    RemoteReadFileResponse,
    RemoteSearchCodeRequest,
    RemoteSearchCodeResponse,
    RepoAgentBriefRead,
    ResourceCreate,
    ResourceManifestFileRead,
    ResourceManifestRead,
    ResourceRead,
    RetrievalEvalRequest,
    RetrievalEvalResponse,
    RetrievalEvalResult,
    RetrievalEvalRunListResponse,
    RetrievalEvalRunRead,
    RetrievalEvalRunSummaryRead,
    RetrievalEvalSummary,
    RetrievalProfileRead,
    RetrievalProfilesResponse,
    RuntimeInstallPlanCapability,
    RuntimeInstallPlanRequest,
    RuntimeInstallPlanResponse,
    SearchRequest,
    SectionImpactRead,
    SelfImprovementArtifactResponse,
    SelfImprovementHistoryResponse,
    SelfImprovementOverviewResponse,
    SelfImprovementRunRequest,
    SelfImprovementRunResponse,
    SelfImprovementSleepRequest,
    SkillExportGenerateRequest,
    SkillExportRead,
    SkillExportReviewRequest,
    SnapshotSectionRead,
    SnapshotSectionsRead,
    UserRead,
    WorkspaceCreate,
    WorkspaceMemberCreate,
    WorkspaceMemberRead,
    WorkspaceMemberUpdate,
    WorkspaceRead,
)
from sourcebrief_api.skill_exports import (
    SKILL_EXPORT_STATUS_APPROVED,
)
from sourcebrief_shared.agent_card_auditor import run_agent_card_auditor
from sourcebrief_shared.config import get_settings
from sourcebrief_shared.db import get_session, get_sessionmaker
from sourcebrief_shared.embeddings import current_embedding_config
from sourcebrief_shared.lifecycle import compute_next_refresh_at
from sourcebrief_shared.models import (
    AgentCardSummary,
    AgentProfile,
    ApiToken,
    AuditEvent,
    ContextArtifact,
    ContextArtifactCitation,
    ContextArtifactSource,
    ContextPackArtifact,
    ContextPacket,
    ContextPacketItem,
    ContextPackResourceCoverage,
    ContextPackVersion,
    Graph,
    GraphEdge,
    GraphMerge,
    GraphMergeEdge,
    GraphMergeInput,
    GraphMergeNode,
    GraphMergeReconcileCandidate,
    GraphMergeVersion,
    GraphNode,
    GraphVersion,
    IndexRun,
    Project,
    ProjectMembership,
    QueryRun,
    RepoAgent,
    Resource,
    ResourceManifest,
    ResourceManifestFile,
    RetrievalEvalItem,
    RetrievalEvalRun,
    RetrievalHit,
    Section,
    SnapshotFile,
    SnapshotSection,
    SourceSnapshot,
    User,
    Workspace,
    WorkspaceMembership,
)
from sourcebrief_shared.review_history import (
    ReviewHistoryError,
    scan_review_history,
    show_review_history_record,
)
from sourcebrief_shared.self_improvement_mvp import run_mvp_smoke_path
from sourcebrief_shared.self_improvement_sleep import (
    SleepReplayError,
    run_sleep_replay,
    write_sleep_replay_summary,
)
from sourcebrief_worker.bundle_ingest import (
    HARD_MAX_ZIP_UPLOAD_BYTES,
    ZipRejectionError,
    cleanup_stale_uploads,
    validate_upload_staging_dir,
    validate_zip_before_extract,
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
    _work_base,
    parse_positive_int,
    sanitize_remote_url,
    validate_base64_size,
    validate_git_url,
    validate_http_url,
)
from sourcebrief_worker.manifest_diff import (
    VALID_CHANGE_TYPES,
    build_manifest_diff,
    page_diff_rows,
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


def _resolve_project(session: Session, workspace_id: UUID, project_id: UUID) -> Project:
    project = session.scalar(
        select(Project).where(Project.id == project_id, Project.workspace_id == workspace_id)
    )
    if project is None or project.deleted_at is not None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _ensure_agent_profile(
    session: Session, workspace_id: UUID, project: Project, user_id: UUID
) -> AgentProfile:
    profile = session.scalar(
        select(AgentProfile).where(
            AgentProfile.workspace_id == workspace_id,
            AgentProfile.project_id == project.id,
        )
    )
    if profile is not None:
        return profile
    profile = AgentProfile(
        workspace_id=workspace_id,
        project_id=project.id,
        name=project.name,
        description=project.description,
        default_runtime="hermes",
        system_prompt=None,
        tool_policy={"production_mutations": "external_approval_required"},
        created_by=user_id,
        updated_by=user_id,
    )
    session.add(profile)
    session.flush()
    return profile


def _normalize_email(email: str) -> str:
    return email.strip().lower()


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


def _agent_profile_read(session: Session, workspace_id: UUID, project: Project, profile: AgentProfile) -> AgentProfileRead:
    stats = cast(
        Mapping[str, Any],
        session.execute(
            text(
                """
            WITH current_snapshots AS (
              SELECT current_snapshot_id
              FROM resources
              WHERE workspace_id = :ws
                AND project_id = :proj
                AND deleted_at IS NULL
                AND current_snapshot_id IS NOT NULL
            )
            SELECT
              (
                SELECT COUNT(*)
                FROM resources r
                WHERE r.workspace_id = :ws
                  AND r.project_id = :proj
                  AND r.deleted_at IS NULL
              ) AS resource_count,
              (SELECT COUNT(*) FROM current_snapshots) AS current_snapshot_count,
              (
                SELECT COUNT(*)
                FROM graph_nodes gn
                WHERE gn.workspace_id = :ws
                  AND gn.project_id = :proj
                  AND gn.source_snapshot_id IN (SELECT current_snapshot_id FROM current_snapshots)
              ) AS graph_node_count,
              (
                SELECT COUNT(*)
                FROM graph_edges ge
                WHERE ge.workspace_id = :ws
                  AND ge.project_id = :proj
                  AND ge.source_snapshot_id IN (SELECT current_snapshot_id FROM current_snapshots)
              ) AS graph_edge_count,
              (
                SELECT MAX(ir.finished_at)
                FROM index_runs ir
                WHERE ir.workspace_id = :ws
                  AND ir.project_id = :proj
                  AND ir.status = 'succeeded'
              ) AS last_index_finished_at
            """
            ),
            {"ws": workspace_id, "proj": project.id},
        ).mappings().first()
        or {},
    )
    return AgentProfileRead(
        id=profile.id,
        workspace_id=profile.workspace_id,
        project_id=profile.project_id,
        name=profile.name,
        description=profile.description,
        default_runtime=profile.default_runtime,
        system_prompt=profile.system_prompt,
        tool_policy=profile.tool_policy,
        resource_count=int(stats.get("resource_count") or 0),
        current_snapshot_count=int(stats.get("current_snapshot_count") or 0),
        graph_node_count=int(stats.get("graph_node_count") or 0),
        graph_edge_count=int(stats.get("graph_edge_count") or 0),
        last_index_finished_at=stats.get("last_index_finished_at"),
        mcp_endpoint=f"/mcp/{workspace_id}/{project.id}",
        agent_context_endpoint=f"/workspaces/{workspace_id}/projects/{project.id}/agent-context",
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _current_project_resources(session: Session, workspace_id: UUID, project_id: UUID) -> list[Resource]:
    return list(
        session.scalars(
            select(Resource)
            .where(
                Resource.workspace_id == workspace_id,
                Resource.project_id == project_id,
                Resource.deleted_at.is_(None),
            )
            .order_by(Resource.type.asc(), Resource.name.asc())
        )
    )


_agent_file_response = agent_files.agent_file_response


def _require_project_access(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal) -> Project:
    """Resolve a project and enforce visibility/membership plus token project scope."""
    require_workspace_member(session, workspace_id, principal)
    if not token_allows_project(principal, project_id):
        raise HTTPException(status_code=404, detail="project not found")
    project = _resolve_project(session, workspace_id, project_id)
    if project.visibility in {"workspace", "public"}:
        return project
    membership = session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.workspace_id == workspace_id,
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == principal.user.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _require_project_member(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    *,
    required_scopes: set[str] | None = None,
) -> Project:
    """Resolve a project and require explicit project membership plus token/project scope for mutations."""
    membership = require_workspace_member(session, workspace_id, principal)
    for required_scope in required_scopes or set():
        require_scope(principal, required_scope, membership)
    if not token_allows_project(principal, project_id):
        raise HTTPException(status_code=404, detail="project not found")
    project = _resolve_project(session, workspace_id, project_id)
    membership = session.scalar(
        select(ProjectMembership).where(
            ProjectMembership.workspace_id == workspace_id,
            ProjectMembership.project_id == project_id,
            ProjectMembership.user_id == principal.user.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=404, detail="project not found")
    return project


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


def _resolve_resource(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal | None = None,
    *,
    include_deleted: bool = False,
) -> Resource:
    if principal is not None and not token_allows_resource(principal, resource_id):
        raise HTTPException(status_code=404, detail="resource not found")
    resource = session.scalar(
        select(Resource).where(
            Resource.id == resource_id,
            Resource.project_id == project_id,
            Resource.workspace_id == workspace_id,
        )
    )
    if resource is None or (resource.deleted_at is not None and not include_deleted):
        raise HTTPException(status_code=404, detail="resource not found")
    return resource


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


def _require_workspace_admin(session: Session, workspace_id: UUID, principal: Principal) -> WorkspaceMembership:
    membership = require_workspace_member(session, workspace_id, principal)
    if membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="workspace admin role required")
    return membership


def _validate_token_scopes(scopes: list[str]) -> list[str]:
    normalized = sorted(set(scopes))
    invalid = sorted(set(normalized) - ALLOWED_TOKEN_SCOPES)
    if invalid:
        raise HTTPException(status_code=422, detail=f"invalid token scopes: {', '.join(invalid)}")
    if not normalized:
        raise HTTPException(status_code=422, detail="token scopes cannot be empty")
    return normalized


def _user_read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_active=getattr(user, "is_active", True),
        is_platform_admin=getattr(user, "is_platform_admin", False),
        created_at=user.created_at,
    )


def _workspace_member_read(session: Session, membership: WorkspaceMembership) -> WorkspaceMemberRead:
    user = session.get(User, membership.user_id)
    if user is None:
        raise HTTPException(status_code=500, detail="workspace membership references missing user")
    return WorkspaceMemberRead(
        id=membership.id,
        workspace_id=membership.workspace_id,
        user=_user_read(user),
        role=membership.role,
        created_at=membership.created_at,
    )


def _audit_event_read(event: AuditEvent) -> AuditEventRead:
    return AuditEventRead(
        id=event.id,
        workspace_id=event.workspace_id,
        actor_user_id=event.actor_user_id,
        actor_token_id=event.actor_token_id,
        action=event.action,
        target_type=event.target_type,
        target_id=event.target_id,
        target_ref=event.target_ref or {},
        metadata=event.meta or {},
        created_at=event.created_at,
    )


def _api_token_read(token: ApiToken) -> ApiTokenRead:
    return ApiTokenRead(
        id=token.id,
        workspace_id=token.workspace_id,
        name=token.name,
        scopes=list(token.scopes or []),
        allowed_project_ids=token.allowed_project_ids,
        allowed_resource_ids=token.allowed_resource_ids,
        created_by=token.created_by,
        expires_at=token.expires_at,
        last_used_at=token.last_used_at,
        revoked_at=token.revoked_at,
        created_at=token.created_at,
    )


def _require_requested_resources_allowed(principal: Principal, resource_ids: list[UUID] | None) -> None:
    if not resource_ids:
        return
    denied = [resource_id for resource_id in resource_ids if not token_allows_resource(principal, resource_id)]
    if denied:
        raise HTTPException(status_code=404, detail="resource not found")


def _effective_resource_ids(principal: Principal, resource_ids: list[UUID] | None) -> list[UUID] | None:
    token = principal.api_token
    requested = resource_ids
    if token is None or token.allowed_resource_ids is None:
        _require_requested_resources_allowed(principal, requested)
        return requested
    if requested is None:
        return list(token.allowed_resource_ids)
    _require_requested_resources_allowed(principal, requested)
    return requested


def _is_empty_scope(resource_ids: list[UUID] | None) -> bool:
    return resource_ids is not None and len(resource_ids) == 0


def _current_user_response(session: Session, principal: Principal) -> CurrentUserResponse:
    memberships = list(
        session.scalars(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.user_id == principal.user.id)
            .order_by(WorkspaceMembership.created_at.asc())
        )
    )
    workspace_ids = [membership.workspace_id for membership in memberships]
    workspaces: list[Workspace] = []
    projects_by_workspace: dict[UUID, list[ProjectRead]] = {}
    if workspace_ids:
        workspaces = list(
            session.scalars(
                select(Workspace)
                .where(Workspace.id.in_(workspace_ids), Workspace.deleted_at.is_(None))
                .order_by(Workspace.created_at.asc())
            )
        )
        for workspace in workspaces:
            project_membership_ids = set(
                session.scalars(
                    select(ProjectMembership.project_id).where(
                        ProjectMembership.workspace_id == workspace.id,
                        ProjectMembership.user_id == principal.user.id,
                    )
                )
            )
            projects = list(
                session.scalars(
                    select(Project)
                    .where(Project.workspace_id == workspace.id, Project.deleted_at.is_(None))
                    .order_by(Project.created_at.asc())
                )
            )
            visible_projects = [
                project
                for project in projects
                if project.visibility in {"workspace", "public"} or project.id in project_membership_ids
            ]
            projects_by_workspace[workspace.id] = [ProjectRead.model_validate(project, from_attributes=True) for project in visible_projects]
    default_workspace_id = workspaces[0].id if workspaces else None
    default_project_id = None
    if default_workspace_id is not None and projects_by_workspace.get(default_workspace_id):
        default_project_id = projects_by_workspace[default_workspace_id][0].id
    return CurrentUserResponse(
        user=_user_read(principal.user),
        workspaces=[WorkspaceRead.model_validate(workspace, from_attributes=True) for workspace in workspaces],
        memberships=[_workspace_member_read(session, membership) for membership in memberships],
        projects_by_workspace=projects_by_workspace,
        default_workspace_id=default_workspace_id,
        default_project_id=default_project_id,
    )


def _session_scopes_for_role(role: str) -> list[str]:
    return sorted(session_scopes_for_role(role))


def _revoke_user_sessions(session: Session, workspace_id: UUID, user_id: UUID) -> None:
    now = datetime.now(UTC)
    for token in session.scalars(
        select(ApiToken).where(
            ApiToken.workspace_id == workspace_id,
            ApiToken.created_by == user_id,
            ApiToken.token_type == "session",
            ApiToken.revoked_at.is_(None),
        )
    ):
        token.revoked_at = now


def _admin_count(session: Session, workspace_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(WorkspaceMembership)
            .join(User, WorkspaceMembership.user_id == User.id)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.role.in_(["owner", "admin"]),
                User.is_active.is_(True),
                User.password_hash.is_not(None),
            )
        )
        or 0
    )


def _is_admin_role(role: str | None) -> bool:
    return role in {"owner", "admin"}


def _assert_login_capable_admin(user: User, role: str) -> None:
    if _is_admin_role(role) and (not user.is_active or not user.password_hash):
        raise HTTPException(status_code=422, detail="admin users must be active and have a password")


def _assert_not_last_admin_transition(session: Session, workspace_id: UUID, membership: WorkspaceMembership, next_role: str, next_active: bool, next_password_hash: str | None) -> None:
    current_user = session.get(User, membership.user_id)
    current_is_login_admin = current_user is not None and _is_admin_role(membership.role) and current_user.is_active and current_user.password_hash is not None
    next_is_login_admin = _is_admin_role(next_role) and next_active and next_password_hash is not None
    if current_is_login_admin and not next_is_login_admin and _admin_count(session, workspace_id) <= 1:
        raise HTTPException(status_code=422, detail="cannot remove the final active admin")


@app.post("/auth/login", response_model=AuthLoginResponse)
def login(payload: AuthLoginRequest, session: Session = Depends(get_session)) -> AuthLoginResponse:
    email = _normalize_email(payload.email)
    user = session.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password")
    membership = session.scalar(
        select(WorkspaceMembership).where(WorkspaceMembership.user_id == user.id).order_by(WorkspaceMembership.created_at.asc())
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user has no workspace access")
    plaintext = new_plaintext_token()
    token = ApiToken(
        workspace_id=membership.workspace_id,
        name=f"Web session for {user.email}",
        token_type="session",
        token_hash=hash_token(plaintext),
        scopes=_session_scopes_for_role(membership.role),
        allowed_project_ids=None,
        allowed_resource_ids=None,
        created_by=user.id,
        expires_at=datetime.now(UTC) + timedelta(hours=12),
    )
    session.add(token)
    session.flush()
    response = _current_user_response(session, Principal(user=user, api_token=token))
    session.commit()
    return AuthLoginResponse(session_token=plaintext, **response.model_dump())


@app.get("/auth/me", response_model=CurrentUserResponse)
def me(principal: Principal = Depends(require_principal), session: Session = Depends(get_session)) -> CurrentUserResponse:
    if principal.is_token:
        raise HTTPException(status_code=403, detail="account session required")
    return _current_user_response(session, principal)


@app.post("/auth/logout", response_model=AuthLogoutResponse)
def logout(
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> AuthLogoutResponse:
    if principal.api_token is not None and principal.api_token.revoked_at is None:
        principal.api_token.revoked_at = datetime.now(UTC)
        session.commit()
    return AuthLogoutResponse(status="ok")


@app.post("/workspaces", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Workspace:
    if principal.is_token:
        raise HTTPException(status_code=403, detail="workspace creation requires user authentication")
    user = principal.user
    workspace = Workspace(name=payload.name, slug=payload.slug)
    session.add(workspace)
    session.flush()
    session.add(WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role="owner"))
    session.add(
        AuditEvent(
            workspace_id=workspace.id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="workspace.create",
            target_type="workspace",
            target_id=workspace.id,
        )
    )
    session.commit()
    return workspace


@app.get("/workspaces", response_model=list[WorkspaceRead])
def list_workspaces(
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> list[Workspace]:
    require_scope(principal, "project:read")
    if principal.is_token:
        token = principal.api_token
        if token is None:
            return []
        workspace = session.get(Workspace, token.workspace_id)
        if workspace is None or workspace.deleted_at is not None:
            return []
        return [workspace]
    memberships = session.scalars(
        select(WorkspaceMembership).where(WorkspaceMembership.user_id == principal.user.id)
    ).all()
    workspace_ids = [membership.workspace_id for membership in memberships]
    if not workspace_ids:
        return []
    return list(
        session.scalars(
            select(Workspace)
            .where(Workspace.id.in_(workspace_ids), Workspace.deleted_at.is_(None))
            .order_by(Workspace.created_at.asc())
        )
    )


@app.get("/workspaces/{workspace_id}", response_model=WorkspaceRead)
def get_workspace(
    workspace_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Workspace:
    require_scope(principal, "project:read")
    require_workspace_member(session, workspace_id, principal)
    workspace = session.get(Workspace, workspace_id)
    if workspace is None or workspace.deleted_at is not None:
        raise HTTPException(status_code=404, detail="workspace not found")
    return workspace


@app.post("/workspaces/{workspace_id}/api-tokens", response_model=ApiTokenCreateResponse, status_code=201)
def create_api_token(
    workspace_id: UUID,
    payload: ApiTokenCreate,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ApiTokenCreateResponse:
    if principal.is_token:
        raise HTTPException(status_code=403, detail="token creation requires user authentication")
    require_scope(principal, "token:admin")
    _require_workspace_admin(session, workspace_id, principal)
    scopes = _validate_token_scopes(payload.scopes)
    for project_id in payload.allowed_project_ids or []:
        _require_project_access(session, workspace_id, project_id, principal)
    for resource_id in payload.allowed_resource_ids or []:
        resource = session.get(Resource, resource_id)
        if resource is None or resource.workspace_id != workspace_id or resource.deleted_at is not None:
            raise HTTPException(status_code=404, detail="resource not found")
        _require_project_access(session, workspace_id, resource.project_id, principal)
    if payload.name.startswith("Web session for "):
        raise HTTPException(status_code=422, detail="token name uses a reserved session prefix")
    plaintext = new_plaintext_token()
    token = ApiToken(
        workspace_id=workspace_id,
        name=payload.name,
        token_hash=hash_token(plaintext),
        scopes=scopes,
        allowed_project_ids=payload.allowed_project_ids,
        allowed_resource_ids=payload.allowed_resource_ids,
        created_by=principal.user.id,
        expires_at=payload.expires_at,
    )
    session.add(token)
    session.flush()
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=principal.user.id,
            actor_token_id=principal.token_id,
            action="api_token.create",
            target_type="api_token",
            target_id=token.id,
            meta={"scopes": scopes, "name": payload.name},
        )
    )
    session.commit()
    return ApiTokenCreateResponse(token=plaintext, api_token=_api_token_read(token))


@app.get("/workspaces/{workspace_id}/api-tokens", response_model=list[ApiTokenRead])
def list_api_tokens(
    workspace_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> list[ApiTokenRead]:
    require_scope(principal, "token:admin")
    _require_workspace_admin(session, workspace_id, principal)
    tokens = list(
        session.scalars(
            select(ApiToken)
            .where(ApiToken.workspace_id == workspace_id, ApiToken.token_type == "api")
            .order_by(ApiToken.created_at.asc())
        )
    )
    return [_api_token_read(token) for token in tokens]


@app.delete("/workspaces/{workspace_id}/api-tokens/{token_id}", response_model=ApiTokenRead)
def revoke_api_token(
    workspace_id: UUID,
    token_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ApiTokenRead:
    require_scope(principal, "token:admin")
    _require_workspace_admin(session, workspace_id, principal)
    token = session.scalar(select(ApiToken).where(ApiToken.workspace_id == workspace_id, ApiToken.id == token_id, ApiToken.token_type == "api"))
    if token is None:
        raise HTTPException(status_code=404, detail="token not found")
    if token.revoked_at is None:
        token.revoked_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=principal.user.id,
            actor_token_id=principal.token_id,
            action="api_token.revoke",
            target_type="api_token",
            target_id=token.id,
            meta={"name": token.name},
        )
    )
    session.commit()
    return _api_token_read(token)


@app.get("/workspaces/{workspace_id}/projects", response_model=list[ProjectRead])
def list_projects(
    workspace_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> list[Project]:
    require_scope(principal, "project:read")
    require_workspace_member(session, workspace_id, principal)
    predicates = [Project.workspace_id == workspace_id, Project.deleted_at.is_(None)]
    projects = list(session.scalars(select(Project).where(*predicates).order_by(Project.created_at.asc())))
    visible: list[Project] = []
    for project in projects:
        if not token_allows_project(principal, project.id):
            continue
        try:
            visible.append(_require_project_access(session, workspace_id, project.id, principal))
        except HTTPException as exc:
            if exc.status_code == status.HTTP_404_NOT_FOUND:
                continue
            raise
    return visible


@app.get("/workspaces/{workspace_id}/members", response_model=list[WorkspaceMemberRead])
def list_workspace_members(
    workspace_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> list[WorkspaceMemberRead]:
    require_scope(principal, "project:read")
    if principal.is_token:
        require_scope(principal, "token:admin")
    _require_workspace_admin(session, workspace_id, principal)
    memberships = list(
        session.scalars(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .order_by(WorkspaceMembership.created_at.asc())
        )
    )
    return [_workspace_member_read(session, membership) for membership in memberships]


@app.post("/workspaces/{workspace_id}/members", response_model=WorkspaceMemberRead, status_code=201)
def create_workspace_member(
    workspace_id: UUID,
    payload: WorkspaceMemberCreate,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> WorkspaceMemberRead:
    if principal.is_token:
        raise HTTPException(status_code=403, detail="user management requires user authentication")
    _require_workspace_admin(session, workspace_id, principal)
    email = _normalize_email(payload.email)
    user = session.scalar(select(User).where(User.email == email))
    user_created = False
    if user is None:
        user = User(
            email=email,
            display_name=payload.display_name or email.split("@")[0],
            password_hash=hash_password(payload.password) if payload.password else None,
            is_active=True,
        )
        session.add(user)
        session.flush()
        user_created = True
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if not user_created and payload.password:
        if not principal.user.is_platform_admin:
            raise HTTPException(status_code=403, detail="existing-user password reset requires platform admin")
        user.password_hash = hash_password(payload.password)
    if user_created:
        user.is_active = True
    if _is_admin_role(payload.role) and not user.password_hash:
        raise HTTPException(status_code=422, detail="admin users require a password")
    membership = session.scalar(
        select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id, WorkspaceMembership.user_id == user.id)
    )
    if membership is None:
        membership = WorkspaceMembership(workspace_id=workspace_id, user_id=user.id, role=payload.role)
        session.add(membership)
    else:
        _assert_not_last_admin_transition(session, workspace_id, membership, payload.role, user.is_active, user.password_hash)
        if membership.role != payload.role:
            _revoke_user_sessions(session, workspace_id, user.id)
        membership.role = payload.role
    projects = list(session.scalars(select(Project).where(Project.workspace_id == workspace_id, Project.deleted_at.is_(None))))
    for project in projects:
        project_membership = session.scalar(
            select(ProjectMembership).where(ProjectMembership.project_id == project.id, ProjectMembership.user_id == user.id)
        )
        if project_membership is None:
            session.add(ProjectMembership(workspace_id=workspace_id, project_id=project.id, user_id=user.id, role=payload.role))
        else:
            project_membership.role = payload.role
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=principal.user.id,
            actor_token_id=principal.token_id,
            action="workspace_member.upsert",
            target_type="user",
            target_id=user.id,
            meta={"email": user.email, "role": payload.role},
        )
    )
    session.commit()
    return _workspace_member_read(session, membership)


@app.patch("/workspaces/{workspace_id}/members/{membership_id}", response_model=WorkspaceMemberRead)
def update_workspace_member(
    workspace_id: UUID,
    membership_id: UUID,
    payload: WorkspaceMemberUpdate,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> WorkspaceMemberRead:
    if principal.is_token:
        raise HTTPException(status_code=403, detail="user management requires user authentication")
    _require_workspace_admin(session, workspace_id, principal)
    membership = session.scalar(select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id, WorkspaceMembership.id == membership_id))
    if membership is None:
        raise HTTPException(status_code=404, detail="member not found")
    user = session.get(User, membership.user_id)
    if user is None:
        raise HTTPException(status_code=500, detail="workspace membership references missing user")
    next_role = payload.role if payload.role is not None else membership.role
    next_active = payload.is_active if payload.is_active is not None else user.is_active
    next_password_hash: str | None
    if payload.password:
        if not principal.user.is_platform_admin:
            raise HTTPException(status_code=403, detail="password reset requires platform admin")
        next_password_hash = hash_password(payload.password)
    else:
        next_password_hash = user.password_hash
    _assert_not_last_admin_transition(session, workspace_id, membership, next_role, next_active, next_password_hash)
    if _is_admin_role(next_role) and (not next_active or not next_password_hash):
        raise HTTPException(status_code=422, detail="admin users must be active and have a password")
    sessions_should_revoke = bool(payload.password or payload.is_active is not None or payload.role is not None)
    if sessions_should_revoke:
        _revoke_user_sessions(session, workspace_id, user.id)
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.password:
        if not principal.user.is_platform_admin:
            raise HTTPException(status_code=403, detail="password reset requires platform admin")
        user.password_hash = hash_password(payload.password)
    if payload.is_active is not None:
        if not principal.user.is_platform_admin:
            raise HTTPException(status_code=403, detail="user activation changes require platform admin")
        user.is_active = payload.is_active
    if payload.role is not None:
        membership.role = payload.role
        projects = list(session.scalars(select(Project).where(Project.workspace_id == workspace_id, Project.deleted_at.is_(None))))
        for project in projects:
            project_membership = session.scalar(
                select(ProjectMembership).where(ProjectMembership.project_id == project.id, ProjectMembership.user_id == user.id)
            )
            if project_membership is None:
                session.add(ProjectMembership(workspace_id=workspace_id, project_id=project.id, user_id=user.id, role=payload.role))
            else:
                project_membership.role = payload.role
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=principal.user.id,
            actor_token_id=principal.token_id,
            action="workspace_member.update",
            target_type="user",
            target_id=user.id,
            meta={"role": membership.role, "is_active": user.is_active},
        )
    )
    session.commit()
    return _workspace_member_read(session, membership)


@app.post("/workspaces/{workspace_id}/projects", response_model=ProjectRead, status_code=201)
def create_project(
    workspace_id: UUID,
    payload: ProjectCreate,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Project:
    if principal.is_token:
        raise HTTPException(status_code=403, detail="project creation requires user authentication")
    user = principal.user
    require_scope(principal, "token:admin")
    _require_workspace_admin(session, workspace_id, principal)
    project = Project(
        workspace_id=workspace_id,
        name=payload.name,
        description=payload.description,
        created_by=user.id,
    )
    session.add(project)
    session.flush()
    _ensure_agent_profile(session, workspace_id, project, user.id)
    session.add(
        ProjectMembership(
            workspace_id=workspace_id,
            project_id=project.id,
            user_id=user.id,
            role="owner",
        )
    )
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="project.create",
            target_type="project",
            target_id=project.id,
        )
    )
    session.commit()
    return project


@app.get("/workspaces/{workspace_id}/projects/{project_id}", response_model=ProjectRead)
def get_project(
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Project:
    require_scope(principal, "project:read")
    return _require_project_access(session, workspace_id, project_id, principal)


def _self_improvement_project_root(workspace_id: UUID, project_id: UUID) -> Path:
    configured = Path(get_settings().self_improvement_root).expanduser()
    base = configured if configured.is_absolute() else Path.cwd() / configured
    return base / str(workspace_id) / str(project_id)


def _history_response(root: Path) -> dict[str, Any]:
    if not root.exists():
        return {"root": str(root), "records": [], "metrics": {"record_count": 0}, "provenance": []}
    return scan_review_history(root).model_dump(mode="json")


def _run_dir(root: Path, prefix: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return root / "runs" / f"{prefix}-{stamp}"


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/self-improvement",
    response_model=SelfImprovementOverviewResponse,
)
def get_self_improvement_overview(
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    require_scope(principal, "review:read")
    _require_project_access(session, workspace_id, project_id, principal)
    root = _self_improvement_project_root(workspace_id, project_id)
    return {
        "workspace_id": workspace_id,
        "project_id": project_id,
        "root": str(root),
        "no_silent_mutation": True,
        "shipped_surfaces": [
            "review-bundle capture",
            "local reviewer report",
            "regression proposal",
            "deterministic validation gate",
            "staged patch/receipt",
            "review history",
            "MVP smoke",
            "sleep/replay dry-run",
        ],
        "next_safe_actions": [
            "Run MVP smoke to create a complete local artifact chain.",
            "Inspect redacted artifact history before adopting any proposed improvement.",
            "Run sleep/replay dry-run only after multiple proposal artifacts exist.",
        ],
        "history": _history_response(root),
    }


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/self-improvement/history",
    response_model=SelfImprovementHistoryResponse,
)
def list_self_improvement_history(
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    require_scope(principal, "review:read")
    _require_project_access(session, workspace_id, project_id, principal)
    return _history_response(_self_improvement_project_root(workspace_id, project_id))


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/self-improvement/artifacts/{artifact_id}",
    response_model=SelfImprovementArtifactResponse,
)
def get_self_improvement_artifact(
    workspace_id: UUID,
    project_id: UUID,
    artifact_id: str,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    require_scope(principal, "review:read")
    _require_project_access(session, workspace_id, project_id, principal)
    root = _self_improvement_project_root(workspace_id, project_id)
    try:
        return show_review_history_record(root, artifact_id)
    except ReviewHistoryError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/self-improvement/mvp-smoke",
    response_model=SelfImprovementRunResponse,
)
def run_self_improvement_mvp_smoke(
    workspace_id: UUID,
    project_id: UUID,
    payload: SelfImprovementRunRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    require_scope(principal, "review:write")
    _require_project_member(session, workspace_id, project_id, principal, required_scopes={"review:write"})
    root = _self_improvement_project_root(workspace_id, project_id)
    out_dir = _run_dir(root, "mvp-smoke")
    try:
        summary = run_mvp_smoke_path(out_dir=out_dir, finding_id=payload.finding_id, owner=payload.owner)
        history = _history_response(root)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=principal.user.id,
            actor_token_id=principal.token_id,
            action="self_improvement.mvp_smoke",
            target_type="project",
            target_id=project_id,
            meta={"out_dir": str(out_dir), "proposal_id": summary.get("proposal_id"), "gate_decision": summary.get("gate_decision")},
        )
    )
    session.commit()
    return {"status": "completed", "out_dir": str(out_dir), "summary": summary, "history": history}


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/self-improvement/sleep",
    response_model=SelfImprovementRunResponse,
)
def run_self_improvement_sleep(
    workspace_id: UUID,
    project_id: UUID,
    payload: SelfImprovementSleepRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    require_scope(principal, "review:write")
    _require_project_member(session, workspace_id, project_id, principal, required_scopes={"review:write"})
    root = _self_improvement_project_root(workspace_id, project_id)
    root.mkdir(parents=True, exist_ok=True)
    out_dir = _run_dir(root, "sleep")
    try:
        summary_model = run_sleep_replay(
            root,
            out_dir=out_dir,
            min_occurrences=payload.min_occurrences,
            max_artifacts=payload.max_artifacts,
            dry_run=True,
        )
        summary_path = out_dir / "summary.json"
        write_sleep_replay_summary(summary_path, summary_model)
        history = _history_response(root)
    except (OSError, SleepReplayError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    summary = summary_model.model_dump(mode="json")
    summary["summary_path"] = str(summary_path)
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=principal.user.id,
            actor_token_id=principal.token_id,
            action="self_improvement.sleep_dry_run",
            target_type="project",
            target_id=project_id,
            meta={"out_dir": str(out_dir), "candidate_count": len(summary_model.candidates)},
        )
    )
    session.commit()
    return {"status": "completed", "out_dir": str(out_dir), "summary": summary, "history": history}


@app.get("/workspaces/{workspace_id}/agents", response_model=list[AgentProfileRead])
def list_agents(
    workspace_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> list[AgentProfileRead]:
    user = principal.user
    require_scope(principal, "project:read")
    require_workspace_member(session, workspace_id, principal)
    projects = list(
        session.scalars(
            select(Project)
            .where(Project.workspace_id == workspace_id, Project.deleted_at.is_(None))
            .order_by(Project.created_at.asc())
        )
    )
    agents: list[AgentProfileRead] = []
    for project in projects:
        try:
            _require_project_access(session, workspace_id, project.id, principal)
        except HTTPException:
            continue
        profile = _ensure_agent_profile(session, workspace_id, project, user.id)
        agents.append(_agent_profile_read(session, workspace_id, project, profile))
    session.commit()
    return agents


@app.get("/workspaces/{workspace_id}/projects/{project_id}/agent-profile", response_model=AgentProfileRead)
def get_agent_profile(
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> AgentProfileRead:
    user = principal.user
    require_scope(principal, "project:read")
    project = _require_project_access(session, workspace_id, project_id, principal)
    profile = _ensure_agent_profile(session, workspace_id, project, user.id)
    session.commit()
    return _agent_profile_read(session, workspace_id, project, profile)


@app.patch("/workspaces/{workspace_id}/projects/{project_id}/agent-profile", response_model=AgentProfileRead)
def update_agent_profile(
    workspace_id: UUID,
    project_id: UUID,
    payload: AgentProfileUpdate,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> AgentProfileRead:
    user = principal.user
    require_scope(principal, "token:admin")
    project = _require_project_member(session, workspace_id, project_id, principal, required_scopes={"token:admin"})
    profile = _ensure_agent_profile(session, workspace_id, project, user.id)
    fields = payload.model_dump(exclude_unset=True)
    nullable_forbidden = {"name", "default_runtime", "tool_policy"}
    bad_null = sorted(key for key in nullable_forbidden if key in fields and fields[key] is None)
    if bad_null:
        raise HTTPException(status_code=422, detail=f"fields cannot be null: {', '.join(bad_null)}")
    for key, value in fields.items():
        setattr(profile, key, value)
    profile.updated_by = user.id
    profile.updated_at = datetime.now(UTC)
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="agent_profile.update",
            target_type="agent_profile",
            target_id=profile.id,
            meta={"fields": sorted(fields.keys())},
        )
    )
    session.commit()
    return _agent_profile_read(session, workspace_id, project, profile)


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


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/resources",
    response_model=ResourceRead,
    status_code=201,
)
def create_resource(
    workspace_id: UUID,
    project_id: UUID,
    payload: ResourceCreate,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Resource:
    user = principal.user
    require_scope(principal, "resource:write")
    if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
        raise HTTPException(status_code=403, detail="resource-scoped tokens cannot create new resources")
    _require_project_member(session, workspace_id, project_id, principal, required_scopes={"resource:write"})
    source_config = _validate_source_config(payload.type, payload.uri, payload.source_config)
    resource_uri = sanitize_remote_url(source_config["url"]) if payload.type.lower() in URL_RESOURCE_TYPES | {"git"} else payload.uri
    resource = Resource(
        workspace_id=workspace_id,
        project_id=project_id,
        type=payload.type,
        name=payload.name,
        uri=resource_uri,
        update_frequency=payload.update_frequency,
        source_config=source_config,
        created_by=user.id,
    )
    session.add(resource)
    session.flush()
    resource.next_refresh_at = compute_next_refresh_at(resource)
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="resource.create",
            target_type="resource",
            target_id=resource.id,
        )
    )
    session.commit()
    return resource


def _manifest_read(manifest: ResourceManifest, files: list[ResourceManifestFile]) -> ResourceManifestRead:
    return ResourceManifestRead(
        id=manifest.id,
        resource_id=manifest.resource_id,
        source_snapshot_id=manifest.source_snapshot_id,
        manifest_hash=manifest.manifest_hash,
        file_count=manifest.file_count,
        total_bytes=manifest.total_bytes,
        parser_warning_count=manifest.parser_warning_count,
        unsupported_file_count=manifest.unsupported_file_count,
        section_count=manifest.section_count,
        sections_reused_count=manifest.sections_reused_count,
        sections_extracted_count=manifest.sections_extracted_count,
        sections_from_deleted_files_count=manifest.sections_from_deleted_files_count,
        sections_absent_count=manifest.sections_absent_count,
        created_at=manifest.created_at,
        files=[
            ResourceManifestFileRead(
                id=file.id,
                normalized_path=file.normalized_path,
                display_path=file.display_path,
                size_bytes=file.size_bytes,
                content_hash=file.content_hash,
                mime_type=file.mime_type,
                status=file.status,
                warnings_json=file.warnings_json or [],
            )
            for file in files
        ],
    )


def _source_family_id(resource: Resource) -> str:
    config = resource.source_config or {}
    value = config.get("source_family_id")
    return str(value or resource.id)


def _source_family_label(resource: Resource) -> str | None:
    config = resource.source_config or {}
    label = config.get("source_family_label")
    return str(label) if isinstance(label, str) and label.strip() else (resource.name if resource.type.lower() in FOLDER_BUNDLE_RESOURCE_TYPES else None)


def _version_label(resource: Resource) -> str | None:
    config = resource.source_config or {}
    label = config.get("version_label")
    return str(label) if isinstance(label, str) and label.strip() else None


def _family_manifest_count(session: Session, resource: Resource, principal: Principal | None = None) -> int:
    if resource.type.lower() not in FOLDER_BUNDLE_RESOURCE_TYPES:
        return 0
    family_id = _source_family_id(resource)
    candidates = list(
        session.scalars(
            select(Resource.id)
            .join(ResourceManifest, ResourceManifest.resource_id == Resource.id)
            .where(
                Resource.workspace_id == resource.workspace_id,
                Resource.project_id == resource.project_id,
                Resource.deleted_at.is_(None),
                Resource.type.in_(FOLDER_BUNDLE_RESOURCE_TYPES),
                Resource.source_config["source_family_id"].astext == family_id,
            )
            .distinct()
        )
    )
    if principal is not None:
        candidates = [resource_id for resource_id in candidates if token_allows_resource(principal, resource_id)]
    return len(candidates)


def _apply_snapshot_coverage(data: ResourceRead, snapshot_meta: dict | None) -> ResourceRead:
    meta = snapshot_meta or {}
    raw_file_stats = meta.get("file_budget_stats")
    file_stats: dict[str, Any] = raw_file_stats if isinstance(raw_file_stats, dict) else {}
    raw_index_stats = meta.get("index_budget_stats")
    index_stats: dict[str, Any] = raw_index_stats if isinstance(raw_index_stats, dict) else {}
    truncated = bool(
        meta.get("coverage_truncated")
        or file_stats.get("truncated_by_max_files")
        or file_stats.get("skipped_total_bytes")
        or file_stats.get("skipped_max_file_bytes")
        or index_stats.get("chunk_budget_exceeded")
        or index_stats.get("symbol_budget_exceeded")
    )
    if not truncated:
        return data
    warnings = list(data.coverage_warnings)
    primary_warning = "current snapshot was truncated by import/index budgets; evidence may be partial"
    for coverage_warning in [primary_warning, *[str(item) for item in meta.get("coverage_warnings") or []]]:
        if coverage_warning not in warnings:
            warnings.append(coverage_warning)
    budgets = dict(data.index_diagnostics.get("configured_budgets", {}))
    for key in ("max_files", "max_total_bytes", "max_file_bytes"):
        if file_stats.get(key) is not None:
            budgets[key] = file_stats[key]
        elif meta.get(key) is not None:
            budgets[key] = meta[key]
    for key in ("max_chunks", "max_symbols"):
        if index_stats.get(key) is not None:
            budgets[key] = index_stats[key]
    diagnostics = dict(data.index_diagnostics)
    diagnostics["configured_budgets"] = budgets
    diagnostics["file_budget_stats"] = file_stats
    diagnostics["index_budget_stats"] = index_stats
    diagnostics["suggested_retry"] = str(
        meta.get("suggested_retry")
        or "retry with narrower include/exclude filters, a source subpath, or an intentional higher import budget"
    )
    data.coverage_status = "partial" if data.queryable else data.coverage_status
    data.coverage_warnings = warnings
    data.index_diagnostics = diagnostics
    return data


def _resource_read(session: Session, resource: Resource, principal: Principal | None = None) -> ResourceRead:
    data = ResourceRead.model_validate(resource, from_attributes=True)
    if resource.current_snapshot_id is not None:
        snapshot_meta = session.scalar(
            select(SourceSnapshot.meta).where(
                SourceSnapshot.id == resource.current_snapshot_id,
                SourceSnapshot.workspace_id == resource.workspace_id,
                SourceSnapshot.project_id == resource.project_id,
            )
        )
        data = _apply_snapshot_coverage(data, snapshot_meta)
    if resource.type.lower() in FOLDER_BUNDLE_RESOURCE_TYPES:
        data.source_family_label = _source_family_label(resource)
        data.version_label = _version_label(resource)
        data.has_manifest_diff = _family_manifest_count(session, resource, principal) >= 2
    return data


def _folder_bundle_version_name(session: Session, project_id: UUID, family_label: str) -> tuple[str, str]:
    base = family_label.strip() or "Folder bundle"
    existing = set(session.scalars(select(Resource.name).where(Resource.project_id == project_id, Resource.name.like(f"{base}%"))).all())
    if base not in existing:
        return base, "v1"
    version = 2
    while True:
        candidate = f"{base} · v{version}"
        if candidate not in existing:
            return candidate, f"v{version}"
        version += 1


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/upload-folder-bundle",
    response_model=FolderBundleUploadResponse,
    status_code=202,
)
def upload_folder_bundle(
    workspace_id: UUID,
    project_id: UUID,
    name: str | None = Form(default=None),
    update_frequency: str = Form(default="manual"),
    supersedes_resource_id: UUID | None = Form(default=None),
    source_family_id: str | None = Form(default=None),
    zip_file: UploadFile = File(...),
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> FolderBundleUploadResponse:
    user = principal.user
    require_scope(principal, "resource:write")
    require_scope(principal, "resource:refresh")
    if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
        raise HTTPException(status_code=403, detail="resource-scoped tokens cannot create new resources")
    _require_project_member(session, workspace_id, project_id, principal, required_scopes={"resource:refresh", "resource:write"})
    if update_frequency != "manual":
        raise HTTPException(status_code=422, detail="folder bundle uploads are manual-only in A2; re-upload a new zip to update")
    if source_family_id is not None:
        raise HTTPException(status_code=422, detail="source_family_id is server-derived; upload a new version with supersedes_resource_id")

    superseded: Resource | None = None
    family_label = (name or "").strip()
    family_id: str | None = None
    if supersedes_resource_id is not None:
        superseded = _resolve_resource(session, workspace_id, project_id, supersedes_resource_id, principal)
        if superseded.type.lower() not in FOLDER_BUNDLE_RESOURCE_TYPES:
            raise HTTPException(status_code=422, detail="superseded resource must be a folder bundle")
        existing_label = _source_family_label(superseded) or superseded.name
        if family_label and family_label != existing_label:
            raise HTTPException(status_code=422, detail="family label changes are not supported in A3")
        family_label = existing_label
        family_id = _source_family_id(superseded)
    elif not family_label:
        raise HTTPException(status_code=422, detail="name is required for first folder bundle upload")

    resource_name, version_label = _folder_bundle_version_name(session, project_id, family_label)

    work_base = _work_base()
    try:
        upload_dir = validate_upload_staging_dir(work_base)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    cleanup_stale_uploads(work_base)
    original_filename = os.path.basename(zip_file.filename or "upload.zip") or "upload.zip"
    staged_path = upload_dir / f"{uuid4()}.zip"
    incoming_path = upload_dir / f".incoming-{staged_path.name}"
    total_bytes = 0
    try:
        with open(incoming_path, "wb") as fh:
            while True:
                chunk = zip_file.file.read(1024 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > HARD_MAX_ZIP_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="folder bundle zip exceeds upload size limit")
                fh.write(chunk)
        if total_bytes == 0:
            raise HTTPException(status_code=422, detail="folder bundle zip is empty")
        with open(incoming_path, "rb") as fh:
            magic = fh.read(4)
        if not magic.startswith(b"PK"):
            raise HTTPException(status_code=422, detail="folder bundle upload must be a zip archive")
        try:
            validate_zip_before_extract(incoming_path)
        except ZipRejectionError as exc:
            detail = f"zip rejected: {exc.reason}"
            if exc.detail:
                detail = f"{detail}: {exc.detail}"
            raise HTTPException(status_code=422, detail=detail) from exc
        os.replace(incoming_path, staged_path)
    except HTTPException:
        try:
            os.unlink(incoming_path)
        except OSError:
            pass
        raise

    resource = Resource(
        workspace_id=workspace_id,
        project_id=project_id,
        type=next(iter(FOLDER_BUNDLE_RESOURCE_TYPES)),
        name=resource_name,
        uri=f"folder-bundle://{original_filename}",
        update_frequency=update_frequency,
        source_config={
            "staged_zip_path": str(staged_path),
            "original_filename": original_filename,
            "zip_size_bytes": total_bytes,
            "source_family_id": family_id or "pending",
            "source_family_label": family_label,
            "supersedes_resource_id": str(superseded.id) if superseded is not None else None,
            "version_label": version_label,
        },
        created_by=user.id,
    )
    session.add(resource)
    session.flush()
    if family_id is None:
        config = dict(resource.source_config or {})
        config["source_family_id"] = str(resource.id)
        resource.source_config = config
    resource.next_refresh_at = compute_next_refresh_at(resource)
    run = IndexRun(
        workspace_id=workspace_id,
        project_id=project_id,
        resource_id=resource.id,
        trigger="upload",
        status="enqueueing",
    )
    session.add(run)
    session.flush()
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="resource.upload",
            target_type="resource",
            target_id=resource.id,
            meta={"index_run_id": str(run.id), "zip_size_bytes": total_bytes},
        )
    )
    session.commit()
    queue = Queue("default", connection=Redis.from_url(get_settings().redis_url))
    try:
        queue.enqueue("sourcebrief_worker.jobs.run_index", str(run.id), job_timeout=600)
    except Exception as exc:
        try:
            os.unlink(staged_path)
        except OSError:
            pass
        resource.status = "error"
        resource.deleted_at = datetime.now(UTC)
        run.status = "failed"
        run.error_message = f"failed to enqueue index job: {exc}"[:1000]
        session.add_all([resource, run])
        session.commit()
        raise HTTPException(status_code=503, detail="failed to enqueue index job") from exc
    run.status = "queued"
    session.add(run)
    session.commit()
    return FolderBundleUploadResponse(
        resource=_resource_read(session, resource, principal),
        index_run=IndexRunRead.model_validate(run),
    )


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}",
    response_model=ResourceRead,
)
def get_resource(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ResourceRead:
    require_scope(principal, "resource:read")
    _require_project_access(session, workspace_id, project_id, principal)
    return _resource_read(session, _resolve_resource(session, workspace_id, project_id, resource_id, principal), principal)


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/manifest",
    response_model=ResourceManifestRead,
)
def get_resource_manifest(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ResourceManifestRead:
    require_scope(principal, "resource:read")
    _require_project_access(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    if resource.current_snapshot_id is None:
        raise HTTPException(status_code=404, detail="resource manifest not found")
    manifest = session.scalar(
        select(ResourceManifest).where(
            ResourceManifest.workspace_id == workspace_id,
            ResourceManifest.project_id == project_id,
            ResourceManifest.resource_id == resource_id,
            ResourceManifest.source_snapshot_id == resource.current_snapshot_id,
        )
    )
    if manifest is None:
        raise HTTPException(status_code=404, detail="resource manifest not found")
    files = list(
        session.scalars(
            select(ResourceManifestFile)
            .where(
                ResourceManifestFile.workspace_id == workspace_id,
                ResourceManifestFile.project_id == project_id,
                ResourceManifestFile.resource_id == resource_id,
                ResourceManifestFile.resource_manifest_id == manifest.id,
            )
            .order_by(ResourceManifestFile.normalized_path.asc())
        )
    )
    return _manifest_read(manifest, files)


def _manifest_files(session: Session, manifest: ResourceManifest) -> list[ResourceManifestFile]:
    return list(
        session.scalars(
            select(ResourceManifestFile)
            .where(ResourceManifestFile.resource_manifest_id == manifest.id)
            .order_by(ResourceManifestFile.normalized_path.asc())
        )
    )


def _latest_family_manifests(session: Session, resource: Resource) -> list[ResourceManifest]:
    family_id = _source_family_id(resource)
    family_uuid = UUID(family_id)
    return list(
        session.scalars(
            select(ResourceManifest)
            .join(Resource, ResourceManifest.resource_id == Resource.id)
            .where(
                ResourceManifest.workspace_id == resource.workspace_id,
                ResourceManifest.project_id == resource.project_id,
                Resource.deleted_at.is_(None),
                Resource.type.in_(FOLDER_BUNDLE_RESOURCE_TYPES),
                (Resource.source_config["source_family_id"].astext == family_id) | (Resource.id == family_uuid),
            )
            .order_by(ResourceManifest.created_at.desc())
            .limit(2)
        )
    )


def _manifest_diff_read(
    session: Session,
    *,
    base_manifest: ResourceManifest,
    head_manifest: ResourceManifest,
    source_family_label: str | None,
    limit: int,
    cursor: str | None,
    change_types: set[str] | None,
) -> ManifestDiffRead:
    result = build_manifest_diff(_manifest_files(session, base_manifest), _manifest_files(session, head_manifest))
    page, next_cursor, filtered_count = page_diff_rows(result.rows, change_types=change_types, limit=limit, cursor=cursor)
    return ManifestDiffRead(
        base_manifest_id=base_manifest.id,
        head_manifest_id=head_manifest.id,
        base_resource_id=base_manifest.resource_id,
        head_resource_id=head_manifest.resource_id,
        source_family_label=source_family_label,
        added_count=result.added_count,
        changed_count=result.changed_count,
        deleted_count=result.deleted_count,
        unchanged_count=result.unchanged_count,
        warning_changed_count=result.warning_changed_count,
        base_file_count=result.base_file_count,
        head_file_count=result.head_file_count,
        total_row_count=filtered_count,
        row_count_returned=len(page),
        limit=limit,
        next_cursor=next_cursor,
        rows=[
            ManifestDiffRowRead(
                normalized_path=row.normalized_path,
                change_type=row.change_type,
                base_file_id=row.base_file_id,
                head_file_id=row.head_file_id,
                base_status=row.base_status,
                head_status=row.head_status,
                base_size_bytes=row.base_size_bytes,
                head_size_bytes=row.head_size_bytes,
                base_content_hash=row.base_content_hash,
                head_content_hash=row.head_content_hash,
                warning_changed=row.warning_changed,
                reason=row.reason,
            )
            for row in page
        ],
        deleted_file_impact=DeletedFileImpactStubRead(
            deleted_file_count=result.deleted_file_impact.deleted_file_count,
            impacted_sections_known=result.deleted_file_impact.impacted_sections_known,
            message=result.deleted_file_impact.message,
        ),
    )


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/manifest-diff",
    response_model=ManifestDiffRead,
)
def get_resource_manifest_diff(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    change_type: list[str] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None),
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ManifestDiffRead:
    require_scope(principal, "resource:read")
    _require_project_access(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    if resource.type.lower() not in FOLDER_BUNDLE_RESOURCE_TYPES:
        raise HTTPException(status_code=422, detail="manifest diff is only available for folder bundles in A3")
    requested = set(change_type or [])
    invalid = requested - VALID_CHANGE_TYPES
    if invalid:
        raise HTTPException(status_code=422, detail=f"invalid change_type: {', '.join(sorted(invalid))}")
    manifests = _latest_family_manifests(session, resource)
    if len(manifests) < 2:
        raise HTTPException(status_code=409, detail="not enough manifests to diff")
    head_manifest, base_manifest = manifests[0], manifests[1]
    for compared_resource_id in (head_manifest.resource_id, base_manifest.resource_id):
        if not token_allows_resource(principal, compared_resource_id):
            raise HTTPException(status_code=404, detail="manifest diff not found")
    try:
        return _manifest_diff_read(
            session,
            base_manifest=base_manifest,
            head_manifest=head_manifest,
            source_family_label=_source_family_label(resource),
            limit=limit,
            cursor=cursor,
            change_types=requested or None,
        )
    except Exception as exc:
        if cursor:
            raise HTTPException(status_code=422, detail="invalid diff cursor") from exc
        raise


def _section_cursor(cursor: str | None) -> int:
    if cursor is None:
        return 0
    try:
        value = int(str(cursor))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="invalid section cursor") from exc
    if value < 0:
        raise HTTPException(status_code=422, detail="invalid section cursor")
    return value


def _section_preview(text: str, limit: int = 240) -> str:
    compact = " ".join(text.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _section_impact_read(session: Session, resource: Resource, manifest: ResourceManifest) -> SectionImpactRead:
    deleted_paths = list(
        session.execute(
            text(
                """
                SELECT normalized_path, section_count
                FROM resource_manifest_files
                WHERE workspace_id = :ws
                  AND project_id = :proj
                  AND resource_id = :res
                  AND resource_manifest_id = :manifest
                  AND status = 'skipped'
                ORDER BY normalized_path ASC
                LIMIT 20
                """
            ),
            {"ws": resource.workspace_id, "proj": resource.project_id, "res": resource.id, "manifest": manifest.id},
        ).mappings().all()
    )
    return SectionImpactRead(
        sections_from_deleted_files_count=manifest.sections_from_deleted_files_count,
        sections_absent_count=manifest.sections_absent_count,
        impacted_artifacts_known=False,
        message="Section-level absence is known. Artifact citation impact is not available yet.",
        deleted_paths=[dict(row) for row in deleted_paths],
        changed_paths_with_absent_sections=[],
    )


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/snapshot-sections",
    response_model=SnapshotSectionsRead,
)
def get_resource_snapshot_sections(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    version_resource_id: UUID | None = Query(default=None),
    source_snapshot_id: UUID | None = Query(default=None),
    reuse_status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    cursor: str | None = Query(default=None),
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> SnapshotSectionsRead:
    require_scope(principal, "resource:read")
    _require_project_access(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, version_resource_id or resource_id, principal)
    if resource.type.lower() not in FOLDER_BUNDLE_RESOURCE_TYPES:
        raise HTTPException(status_code=422, detail="snapshot sections are only available for folder bundles")
    if source_snapshot_id is None:
        source_snapshot_id = resource.current_snapshot_id
    if source_snapshot_id is None:
        raise HTTPException(status_code=404, detail="snapshot sections not found")
    if not token_allows_resource(principal, resource.id):
        raise HTTPException(status_code=404, detail="snapshot sections not found")
    if reuse_status is not None and reuse_status not in {"reused", "extracted"}:
        raise HTTPException(status_code=422, detail="invalid reuse_status")
    predicates = [
        SnapshotSection.workspace_id == workspace_id,
        SnapshotSection.project_id == project_id,
        SnapshotSection.version_resource_id == resource.id,
        SnapshotSection.source_snapshot_id == source_snapshot_id,
    ]
    if reuse_status:
        predicates.append(SnapshotSection.reuse_status == reuse_status)
    offset = _section_cursor(cursor)
    total = int(session.scalar(select(func.count(SnapshotSection.id)).where(*predicates)) or 0)
    rows = list(
        session.execute(
            select(SnapshotSection, Section)
            .join(Section, SnapshotSection.section_id == Section.id)
            .where(*predicates)
            .order_by(SnapshotSection.normalized_path.asc(), SnapshotSection.ordinal.asc())
            .offset(offset)
            .limit(limit)
        ).all()
    )
    next_cursor = str(offset + len(rows)) if offset + len(rows) < total else None
    return SnapshotSectionsRead(
        source_snapshot_id=source_snapshot_id,
        version_resource_id=resource.id,
        section_count=total,
        total_row_count=total,
        row_count_returned=len(rows),
        limit=limit,
        next_cursor=next_cursor,
        rows=[
            SnapshotSectionRead(
                id=snapshot_section.id,
                normalized_path=snapshot_section.normalized_path,
                ordinal=snapshot_section.ordinal,
                title=section.title,
                reuse_status=snapshot_section.reuse_status,
                start_line=section.start_line,
                end_line=section.end_line,
                content_preview=_section_preview(section.content_text),
            )
            for snapshot_section, section in rows
        ],
    )


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/section-impact",
    response_model=SectionImpactRead,
)
def get_resource_section_impact(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> SectionImpactRead:
    require_scope(principal, "resource:read")
    _require_project_access(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    if resource.current_snapshot_id is None:
        raise HTTPException(status_code=404, detail="section impact not found")
    manifest = session.scalar(
        select(ResourceManifest).where(
            ResourceManifest.workspace_id == workspace_id,
            ResourceManifest.project_id == project_id,
            ResourceManifest.resource_id == resource.id,
            ResourceManifest.source_snapshot_id == resource.current_snapshot_id,
        )
    )
    if manifest is None:
        raise HTTPException(status_code=404, detail="section impact not found")
    return _section_impact_read(session, resource, manifest)


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


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/refresh",
    response_model=IndexRunRead,
    status_code=202,
)
def refresh_resource(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    fail: bool = Query(default=False),
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> IndexRun:
    user = principal.user
    require_scope(principal, "resource:refresh")
    _require_project_member(session, workspace_id, project_id, principal, required_scopes={"resource:refresh"})
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    if resource.type.lower() in FOLDER_BUNDLE_RESOURCE_TYPES:
        raise HTTPException(status_code=422, detail="folder bundle resources are updated by uploading a new zip, not by refresh")
    run = IndexRun(
        workspace_id=workspace_id,
        project_id=project_id,
        resource_id=resource_id,
        trigger="manual",
        status="enqueueing",
        meta={"fail": fail},
    )
    session.add(run)
    session.flush()
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="resource.refresh",
            target_type="resource",
            target_id=resource.id,
            meta={"index_run_id": str(run.id)},
        )
    )
    session.commit()
    queue = Queue("default", connection=Redis.from_url(get_settings().redis_url))
    try:
        queue.enqueue("sourcebrief_worker.jobs.run_index", str(run.id), job_timeout=600)
    except Exception as exc:
        run.status = "failed"
        run.error_message = f"failed to enqueue index job: {exc}"[:1000]
        session.add(run)
        session.commit()
        raise HTTPException(status_code=503, detail="failed to enqueue index job") from exc
    run.status = "queued"
    session.add(run)
    session.commit()
    return run


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/scheduled-refreshes",
    response_model=DueRefreshResponse,
    status_code=202,
)
def enqueue_scheduled_refreshes(
    workspace_id: UUID,
    project_id: UUID,
    dry_run: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> DueRefreshResponse:
    require_scope(principal, "resource:refresh")
    _require_project_member(session, workspace_id, project_id, principal, required_scopes={"resource:refresh"})
    allowed_resource_ids = principal.api_token.allowed_resource_ids if principal.api_token is not None else None
    if allowed_resource_ids is not None:
        allowed = list(allowed_resource_ids)
    else:
        allowed = None
    from sourcebrief_worker.maintenance import enqueue_due_refreshes

    result = enqueue_due_refreshes(
        workspace_id=workspace_id,
        project_id=project_id,
        resource_ids=allowed,
        limit=limit,
        dry_run=dry_run,
    )
    if not dry_run:
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="resource.scheduled_refresh",
                target_type="project",
                target_id=project_id,
                meta=result,
            )
        )
        session.commit()
    return DueRefreshResponse.model_validate(result)


@app.get("/workspaces/{workspace_id}/audit-events", response_model=list[AuditEventRead])
def list_audit_events(
    workspace_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> list[AuditEventRead]:
    require_scope(principal, "token:admin")
    _require_workspace_admin(session, workspace_id, principal)
    events = list(
        session.scalars(
            select(AuditEvent)
            .where(AuditEvent.workspace_id == workspace_id)
            .order_by(AuditEvent.created_at.desc())
        )
    )
    return [
        AuditEventRead(
            id=event.id,
            workspace_id=event.workspace_id,
            actor_user_id=event.actor_user_id,
            actor_token_id=event.actor_token_id,
            action=event.action,
            target_type=event.target_type,
            target_id=event.target_id,
            target_ref=event.target_ref,
            metadata=event.meta,
            created_at=event.created_at,
        )
        for event in events
    ]


@app.get("/workspaces/{workspace_id}/index-runs/{index_run_id}", response_model=IndexRunRead)
def get_index_run(
    workspace_id: UUID,
    index_run_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> IndexRun:
    require_any_scope(principal, {"project:read", "resource:read", "resource:refresh"})
    require_workspace_member(session, workspace_id, principal)
    run = session.scalar(
        select(IndexRun).where(IndexRun.workspace_id == workspace_id, IndexRun.id == index_run_id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="index run not found")
    if not token_allows_resource(principal, run.resource_id):
        raise HTTPException(status_code=404, detail="index run not found")
    _require_project_access(session, workspace_id, run.project_id, principal)
    return run


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

@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/index-runs",
    response_model=list[IndexRunRead],
)
def list_resource_index_runs(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> list[IndexRun]:
    require_scope(principal, "resource:read")
    _require_project_access(session, workspace_id, project_id, principal)
    _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    return list(
        session.scalars(
            select(IndexRun)
            .where(
                IndexRun.workspace_id == workspace_id,
                IndexRun.resource_id == resource_id,
            )
            .order_by(IndexRun.created_at.desc())
        )
    )


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


def _agent_context_suggested_tool_calls(citations: list[AgentContextCitation], query: str, *, include_code_tools: bool = True) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = [
        {
            "name": "sourcebrief.search",
            "reason": "Find additional cited sections if the initial context is insufficient.",
            "arguments": {"query": query, "top_k": 8},
        },
        {
            "name": "sourcebrief.list_sources",
            "reason": "Discover human source names/resource IDs before narrowing follow-up calls.",
            "arguments": {"limit": 20},
        },
    ]
    if citations:
        first = citations[0]
        if first.path and first.content_hash:
            calls.insert(
                0,
                {
                    "name": "sourcebrief.read_section",
                    "reason": "Read the first cited section exactly from the cited snapshot before making source claims.",
                    "arguments": {
                        "resource_id": str(first.resource_id),
                        "source_snapshot_id": str(first.snapshot_id),
                        "path": first.path,
                        "content_hash": first.content_hash,
                    },
                },
            )
        if include_code_tools:
            calls.append(
                {
                    "name": "sourcebrief.read_file",
                    "reason": "Inspect the cited file from the indexed source snapshot when code detail is needed.",
                    "arguments": {"resource_id": str(first.resource_id), "path": first.path or "<path>", "start_line": 1, "end_line": 120},
                }
            )
    return calls


def _agent_answer_snippets(context_parts: list[str], *, limit: int = 3) -> list[tuple[int, str]]:
    snippets: list[tuple[int, str]] = []
    for citation_index, part in enumerate(context_parts, start=1):
        lines = []
        for raw_line in part.splitlines()[1:]:
            line = raw_line.strip().strip("` ")
            if not line or line.startswith(("|", "---")):
                continue
            if line.startswith("#"):
                line = line.lstrip("# ").strip()
                if not line:
                    continue
            if re.match(r"^[{}();,]+$", line):
                continue
            lines.append(line)
        text = " ".join(lines)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip()
        if len(sentence) < 24:
            sentence = text[:240].strip()
        if len(sentence) > 280:
            sentence = sentence[:277].rstrip() + "..."
        if sentence:
            snippets.append((citation_index, sentence))
        if len(snippets) >= limit:
            break
    return snippets


def _agent_answer_caveats(resource_coverage: list[dict[str, Any]], coverage_warnings: list[str]) -> list[str]:
    caveats: list[str] = []
    for warning in coverage_warnings:
        if warning and warning not in caveats:
            caveats.append(warning)
    for entry in resource_coverage:
        status = entry.get("coverage_status")
        if status and status != "full":
            name = entry.get("name") or entry.get("resource_id")
            caveat = f"{name}: coverage_status={status}; evidence may be partial."
            if caveat not in caveats:
                caveats.append(caveat)
    return caveats[:5]


_NEGATED_EVIDENCE_MARKERS = (
    "not documented",
    "not provide",
    "not include",
    "not guarantee",
    "does not document",
    "does not provide",
    "does not include",
    "no audit report",
    "no auditor",
    "no sla",
    "no uptime",
    "no fedramp",
    "no threat model",
    "without evidence",
    "without a cited",
    "not supported",
)


_UNSUPPORTED_CLAIM_FAMILIES: tuple[tuple[str, tuple[str, ...], tuple[tuple[str, ...], ...]], ...] = (
    ("SOC 2 audit report/auditor", ("soc 2", "soc2", "type ii", "auditor", "audit report"), (("soc 2 type ii", "soc 2 audit report", "soc 2 report", "signed soc 2"), ("auditor is", "auditor:", "auditor named", "auditor was", "audited by"))),
    ("HIPAA compliance/deployment checklist", ("hipaa", "covered entity", "covered-entity", "compliance", "deployment checklist"), (("hipaa compliance", "hipaa compliant"), ("covered-entity deployment checklist", "covered entity deployment checklist"))),
    ("hosted cloud service SLA/uptime dashboard", ("hosted", "cloud service", "sla", "uptime", "dashboard"), (("hosted cloud service",), ("sla", "service level agreement"), ("uptime dashboard",))),
    ("FedRAMP authorization/sponsoring agency", ("fedramp", "authorization", "sponsoring agency", "agency"), (("fedramp authorization", "fedramp authorized"), ("sponsoring agency", "agency sponsor"))),
    ("production Kubernetes multi-tenant isolation/threat model", ("kubernetes", "k8s", "multi-tenant", "multitenant", "tenant isolation", "threat model"), (("production kubernetes", "production k8s"), ("multi-tenant isolation", "multitenant isolation", "tenant isolation"), ("threat model",))),
)


def _agent_unsupported_claim_terms(query: str, context_parts: list[str]) -> list[str]:
    query_text = query.lower()
    context_text = "\n".join(context_parts).lower()
    unsupported: list[str] = []
    for label, query_terms, required_groups in _UNSUPPORTED_CLAIM_FAMILIES:
        if not any(term in query_text for term in query_terms):
            continue
        negated = any(marker in context_text for marker in _NEGATED_EVIDENCE_MARKERS)
        supported = not negated and all(any(term in context_text for term in group) for group in required_groups)
        if not supported:
            unsupported.append(label)
    return unsupported


def _agent_answer_citations_used(
    citations: list[AgentContextCitation],
    *,
    count: int | None = None,
    citation_indices: list[int] | None = None,
) -> list[dict[str, Any]]:
    if citation_indices:
        indices = [idx for idx in dict.fromkeys(citation_indices) if 1 <= idx <= len(citations)]
    else:
        indices = list(range(1, min(len(citations), max(1, count or 0)) + 1))
    return [
        {
            "label": f"[{idx}]",
            "resource_id": str(citation.resource_id),
            "snapshot_id": str(citation.snapshot_id),
            "path": citation.path or citation.title or str(citation.resource_id),
            "content_hash": citation.content_hash,
            "score": citation.score,
        }
        for idx in indices
        for citation in [citations[idx - 1]]
    ]


def _synthesize_agent_answer(
    *,
    query: str,
    context_parts: list[str],
    citations: list[AgentContextCitation],
    resource_coverage: list[dict[str, Any]],
    coverage_warnings: list[str],
) -> AgentContextAnswer:
    caveats = _agent_answer_caveats(resource_coverage, coverage_warnings)
    unsupported_terms = _agent_unsupported_claim_terms(query, context_parts)
    if unsupported_terms:
        reason = "Retrieved SourceBrief evidence does not directly support the requested high-assurance claim."
        text = (
            "Insufficient evidence: the cited SourceBrief context does not support the requested claim "
            f"about {', '.join(unsupported_terms)}. Do not answer this as true unless a cited source explicitly provides that evidence."
        )
        if caveats:
            text += " Caveat: " + " ".join(caveats[:2])
        return AgentContextAnswer(
            outcome="unsupported_by_sources",
            text=text,
            citations_used=_agent_answer_citations_used(citations, count=min(len(citations), 3)),
            caveats=caveats,
            confidence="none",
            abstention_reason=reason,
            unsupported_claim_terms=unsupported_terms,
        )
    if not citations:
        text = f"No grounded answer is available from the selected SourceBrief evidence for: {query}"
        if caveats:
            text += " Caveat: " + " ".join(caveats[:2])
        return AgentContextAnswer(
            outcome="insufficient_evidence",
            text=text,
            citations_used=[],
            caveats=caveats,
            confidence="none",
            abstention_reason="No cited SourceBrief evidence was retrieved for this question.",
        )
    snippets = _agent_answer_snippets(context_parts)
    if snippets:
        claims = [f"{snippet} [{idx}]" for idx, snippet in snippets]
        text = f"Based on the cited SourceBrief context for `{query}`: " + " ".join(claims)
    else:
        text = "SourceBrief found cited context for this question; inspect the cited sections before making claims."
    if caveats:
        text += " Caveat: " + " ".join(caveats[:2])
    citations_used = _agent_answer_citations_used(
        citations,
        count=3,
        citation_indices=[idx for idx, _snippet in snippets] if snippets else None,
    )
    return AgentContextAnswer(
        text=text,
        citations_used=citations_used,
        caveats=caveats,
        confidence="low" if caveats else "medium",
    )


def _runtime_safe_index_failure(error_message: str | None) -> str:
    if not error_message:
        return "latest index failed; inspect Index activity with read scope for details"
    lowered = error_message.lower()
    if "chunk budget exceeded" in lowered:
        parts = ["latest index failed: chunk budget exceeded"]
        for key in ("max_chunks", "documents_collected", "chunks_created"):
            match = re.search(rf"{key}=([0-9]+)", error_message)
            if match:
                parts.append(f"{key}={match.group(1)}")
        parts.append("suggested retry: narrow include/exclude filters, use a source subpath, or intentionally raise max_chunks")
        return "; ".join(parts)
    if "symbol budget exceeded" in lowered:
        parts = ["latest index failed: symbol budget exceeded"]
        for key in ("max_symbols", "documents_collected", "symbols_created"):
            match = re.search(rf"{key}=([0-9]+)", error_message)
            if match:
                parts.append(f"{key}={match.group(1)}")
        parts.append("suggested retry: use docs-only/source-subpath import, include/exclude filters, or intentionally raise max_symbols")
        return "; ".join(parts)
    return "latest index failed; inspect Index activity with read scope for details"


def _coverage_budget_reason(read: ResourceRead) -> str | None:
    diagnostics = read.index_diagnostics or {}
    configured_budgets = diagnostics.get("configured_budgets") or {}
    limited_keys = diagnostics.get("limited_budget_keys") or [key for key in configured_budgets if configured_budgets.get(key) is not None]
    if read.coverage_status != "partial":
        return None
    if limited_keys:
        details = ", ".join(f"{key}={configured_budgets.get(key)}" for key in limited_keys if configured_budgets.get(key) is not None)
        return f"limited import budget ({details})" if details else "limited import budget"
    if diagnostics.get("file_budget_stats"):
        return "current snapshot was truncated by file/byte import budgets"
    return "partial corpus; evidence may be incomplete"


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


def _agent_context_retrieval_metadata(candidates: list[RetrievalCandidate], requested_resource_ids: list[UUID] | None = None) -> dict[str, Any]:
    paths = [candidate.path for candidate in candidates if candidate.path]
    unique_paths = {path for path in paths}
    diversity = candidates[0].ranking_diagnostics.get("retrieval_diversity") if candidates and candidates[0].ranking_diagnostics else None
    path_prior_hits: dict[str, int] = {}
    cited_resource_counts = Counter(str(candidate.resource_id) for candidate in candidates)
    for candidate in candidates:
        diagnostics = candidate.ranking_diagnostics or {}
        for reason in diagnostics.get("path_prior_reasons", []) or []:
            path_prior_hits[reason] = path_prior_hits.get(reason, 0) + 1
    requested_ids = [str(rid) for rid in requested_resource_ids or []]
    missing_requested_ids = [rid for rid in requested_ids if cited_resource_counts.get(rid, 0) == 0]
    metadata = {
        "selected_count": len(candidates),
        "unique_citation_paths": len(unique_paths),
        "duplicate_citation_count": max(0, len(paths) - len(unique_paths)),
        "path_prior_hits": path_prior_hits,
        "requested_resource_ids": requested_ids,
        "cited_resource_counts": dict(sorted(cited_resource_counts.items())),
        "missing_requested_resource_ids": missing_requested_ids,
    }
    if isinstance(diversity, dict):
        metadata["candidate_pool_count"] = diversity.get("candidate_pool_count", len(candidates))
        metadata["deduped_from_count"] = diversity.get("deduped_from_count", 0)
        metadata["retriever_selected_count"] = diversity.get("selected_count")
        metadata["retriever_unique_citation_paths"] = diversity.get("unique_citation_paths")
        metadata["retriever_duplicate_citation_count"] = diversity.get("duplicate_citation_count")
        metadata["candidate_resource_counts"] = diversity.get("candidate_resource_counts", {})
        metadata["retriever_selected_resource_counts"] = diversity.get("selected_resource_counts", {})
    else:
        metadata["candidate_pool_count"] = len(candidates)
        metadata["deduped_from_count"] = 0
        metadata["candidate_resource_counts"] = dict(sorted(cited_resource_counts.items()))
        metadata["retriever_selected_resource_counts"] = dict(sorted(cited_resource_counts.items()))
    return metadata


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


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/agent-context",
    response_model=AgentContextResponse,
)
def agent_context(
    workspace_id: UUID,
    project_id: UUID,
    payload: AgentContextRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> AgentContextResponse:
    require_scope(principal, "project:query")
    _require_project_access(session, workspace_id, project_id, principal)
    payload = _agent_context_with_resource_ref(session, workspace_id, project_id, principal, payload)
    resource_ids = _effective_resource_ids(principal, payload.resource_ids)
    payload = payload.model_copy(update={"resource_ids": resource_ids})
    pack_version = _resolve_runtime_pack_version(session, workspace_id, project_id, payload, principal)
    if pack_version is not None:
        return _build_pack_agent_context_response(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            payload=payload,
            principal=principal,
            pack_version=pack_version,
        )
    return _build_agent_context_response(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        payload=payload,
        principal=principal,
    )


def _agent_card_summary_read(summary: AgentCardSummary) -> AgentCardSummaryRead:
    return AgentCardSummaryRead(
        id=summary.id,
        workspace_id=summary.workspace_id,
        project_id=summary.project_id,
        resource_id=summary.resource_id,
        status=summary.status,
        severity=summary.severity,
        summary=summary.summary,
        findings=list(summary.findings or []),
        metrics=dict(summary.metrics or {}),
        source=summary.source,
        acknowledged_at=summary.acknowledged_at,
        acknowledged_by=summary.acknowledged_by,
        suppressed_until=summary.suppressed_until,
        created_at=summary.created_at,
    )


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries",
    response_model=AgentCardSummaryListResponse,
)
def list_agent_card_summaries(
    workspace_id: UUID,
    project_id: UUID,
    latest_only: bool = Query(default=True),
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> AgentCardSummaryListResponse:
    require_scope(principal, "review:read")
    _require_project_access(session, workspace_id, project_id, principal)
    predicates = [
        AgentCardSummary.workspace_id == workspace_id,
        AgentCardSummary.project_id == project_id,
        Resource.id == AgentCardSummary.resource_id,
        Resource.workspace_id == AgentCardSummary.workspace_id,
        Resource.project_id == AgentCardSummary.project_id,
        Resource.deleted_at.is_(None),
        Resource.archived_at.is_(None),
    ]
    if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
        predicates.append(AgentCardSummary.resource_id.in_(principal.api_token.allowed_resource_ids))
    summaries = list(
        session.scalars(
            select(AgentCardSummary)
            .where(*predicates)
            .order_by(AgentCardSummary.resource_id.asc(), AgentCardSummary.created_at.desc())
            .limit(300)
        )
    )
    if latest_only:
        latest_by_resource: dict[UUID, AgentCardSummary] = {}
        for summary in summaries:
            latest_by_resource.setdefault(summary.resource_id, summary)
        items = [_agent_card_summary_read(summary) for summary in latest_by_resource.values()]
    else:
        items = [_agent_card_summary_read(summary) for summary in summaries[:100]]
    return AgentCardSummaryListResponse(count=len(items), summaries=items)


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries/run",
    response_model=AgentCardSummaryListResponse,
)
def run_agent_card_summary_audit(
    workspace_id: UUID,
    project_id: UUID,
    dry_run: bool = Query(default=True),
    resource_ids: list[UUID] | None = Query(default=None),
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> AgentCardSummaryListResponse:
    require_scope(principal, "review:read")
    if not dry_run:
        require_scope(principal, "review:write")
        _require_project_member(session, workspace_id, project_id, principal, required_scopes={"review:read", "review:write"})
    else:
        _require_project_access(session, workspace_id, project_id, principal)
    effective_resource_ids = _effective_resource_ids(principal, resource_ids)
    summaries = run_agent_card_auditor(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        resource_ids=effective_resource_ids,
        actor_user_id=principal.user.id,
        actor_token_id=principal.token_id,
        persist=not dry_run,
    )
    return AgentCardSummaryListResponse(count=len(summaries), summaries=[_agent_card_summary_read(summary) for summary in summaries])


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries/{summary_id}/acknowledge",
    response_model=AgentCardSummaryRead,
)
def acknowledge_agent_card_summary(
    workspace_id: UUID,
    project_id: UUID,
    summary_id: UUID,
    payload: AgentCardSummaryAcknowledgeRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> AgentCardSummaryRead:
    require_scope(principal, "review:write")
    _require_project_member(session, workspace_id, project_id, principal, required_scopes={"review:write"})
    summary = session.scalar(
        select(AgentCardSummary).where(
            AgentCardSummary.id == summary_id,
            AgentCardSummary.workspace_id == workspace_id,
            AgentCardSummary.project_id == project_id,
        )
    )
    if summary is None:
        raise HTTPException(status_code=404, detail="agent card summary not found")
    if not token_allows_resource(principal, summary.resource_id):
        raise HTTPException(status_code=403, detail="token is not allowed to access this resource")
    previous = {
        "acknowledged_at": summary.acknowledged_at.isoformat() if summary.acknowledged_at else None,
        "acknowledged_by": str(summary.acknowledged_by) if summary.acknowledged_by else None,
        "suppressed_until": summary.suppressed_until.isoformat() if summary.suppressed_until else None,
    }
    now = datetime.now(UTC)
    summary.acknowledged_at = now
    summary.acknowledged_by = principal.user.id
    summary.suppressed_until = now + timedelta(hours=payload.suppress_for_hours) if payload.suppress_for_hours else None
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=principal.user.id,
            actor_token_id=principal.token_id,
            action="agent_card.summary_acknowledged",
            target_type="agent_card_summary",
            target_id=summary.id,
            target_ref={"resource_id": str(summary.resource_id)},
            meta={
                "previous": previous,
                "new": {
                    "acknowledged_at": summary.acknowledged_at.isoformat(),
                    "acknowledged_by": str(summary.acknowledged_by),
                    "suppressed_until": summary.suppressed_until.isoformat() if summary.suppressed_until else None,
                },
            },
        )
    )
    session.commit()
    return _agent_card_summary_read(summary)


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/repo-agents/{resource_id}/brief",
    response_model=RepoAgentBriefRead,
)
def get_repo_agent_brief(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> RepoAgentBriefRead:
    require_scope(principal, "project:read")
    _require_project_access(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    return _repo_agent_brief_response(session, workspace_id, project_id, resource)


def _eval_run_visible_to_principal(principal: Principal, run: RetrievalEvalRun) -> bool:
    token = principal.api_token
    if token is None or token.allowed_resource_ids is None:
        return True
    if run.project_wide:
        return False
    return set(run.resource_ids or []).issubset(set(token.allowed_resource_ids))


def _retrieval_eval_run_summary_read(run: RetrievalEvalRun) -> RetrievalEvalRunSummaryRead:
    summary = run.summary or {}
    return RetrievalEvalRunSummaryRead(
        id=run.id,
        profile=run.profile,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        created_at=run.created_at,
        runtime=run.runtime,
        provider=run.provider,
        model=run.model,
        status=run.status,
        question_count=run.question_count,
        passed_count=run.passed_count,
        failed_count=run.failed_count,
        pass_rate=run.pass_rate,
        max_latency_ms=run.max_latency_ms,
        avg_latency_ms=run.avg_latency_ms,
        project_wide=run.project_wide,
        resource_ids=run.resource_ids or [],
        failure_reasons=list(summary.get("failure_reasons") or []),
    )


def _retrieval_eval_run_read(session: Session, run: RetrievalEvalRun) -> RetrievalEvalRunRead:
    items = list(
        session.scalars(
            select(RetrievalEvalItem)
            .where(
                RetrievalEvalItem.workspace_id == run.workspace_id,
                RetrievalEvalItem.project_id == run.project_id,
                RetrievalEvalItem.eval_run_id == run.id,
            )
            .order_by(RetrievalEvalItem.ordinal.asc())
        )
    )
    return RetrievalEvalRunRead(
        run_id=run.id,
        profile=run.profile,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        created_at=run.created_at,
        runtime=run.runtime,
        provider=run.provider,
        model=run.model,
        diagnostics=run.diagnostics or {},
        summary=RetrievalEvalSummary(**(run.summary or {})),
        results=[
            RetrievalEvalResult(
                id=item.question_id,
                query=item.query,
                passed=item.passed,
                failure_reasons=item.failure_reasons or [],
                latency_ms=item.latency_ms,
                citation_count=item.citation_count,
                context_chars=item.context_chars,
                symbol_count=item.symbol_count,
                expected_resource_ids=item.expected_resource_ids or [],
                cited_resource_ids=item.cited_resource_ids or [],
                forbidden_resource_ids=item.forbidden_resource_ids or [],
                hit_quality=item.hit_quality or [],
            )
            for item in items
        ],
    )


def _persist_retrieval_eval_run(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    payload: RetrievalEvalRequest,
    response: RetrievalEvalResponse,
    project_wide: bool,
    resource_ids: set[UUID],
) -> RetrievalEvalResponse:
    run = RetrievalEvalRun(
        workspace_id=workspace_id,
        project_id=project_id,
        actor_user_id=principal.user.id,
        actor_token_id=principal.token_id,
        runtime=payload.runtime,
        profile=response.profile,
        provider=response.provider,
        model=response.model,
        status=response.summary.status,
        question_count=response.summary.question_count,
        passed_count=response.summary.passed_count,
        failed_count=response.summary.failed_count,
        pass_rate=response.summary.pass_rate,
        max_latency_ms=response.summary.max_latency_ms,
        avg_latency_ms=response.summary.avg_latency_ms,
        max_chars=payload.max_chars,
        project_wide=project_wide,
        resource_ids=sorted(resource_ids),
        summary=response.summary.model_dump(mode="json"),
        diagnostics=response.diagnostics,
    )
    session.add(run)
    session.flush()
    for ordinal, result in enumerate(response.results):
        session.add(
            RetrievalEvalItem(
                workspace_id=workspace_id,
                project_id=project_id,
                eval_run_id=run.id,
                ordinal=ordinal,
                question_id=result.id,
                query=result.query,
                passed=result.passed,
                latency_ms=result.latency_ms,
                citation_count=result.citation_count,
                context_chars=result.context_chars,
                symbol_count=result.symbol_count,
                expected_resource_ids=result.expected_resource_ids,
                cited_resource_ids=result.cited_resource_ids,
                forbidden_resource_ids=result.forbidden_resource_ids,
                failure_reasons=result.failure_reasons,
                hit_quality=result.hit_quality,
            )
        )
    session.commit()
    return response.model_copy(update={"run_id": run.id})


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/retrieval-evals",
    response_model=RetrievalEvalRunListResponse,
)
def list_retrieval_eval_runs(
    workspace_id: UUID,
    project_id: UUID,
    limit: int = Query(default=20, ge=1, le=100),
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> RetrievalEvalRunListResponse:
    require_scope(principal, "project:query")
    _require_project_access(session, workspace_id, project_id, principal)
    stmt = select(RetrievalEvalRun).where(
        RetrievalEvalRun.workspace_id == workspace_id,
        RetrievalEvalRun.project_id == project_id,
    )
    token = principal.api_token
    if token is not None and token.allowed_resource_ids is not None:
        resource_ids_column = cast(Any, RetrievalEvalRun.resource_ids)
        stmt = stmt.where(
            RetrievalEvalRun.project_wide.is_(False),
            resource_ids_column.contained_by(token.allowed_resource_ids),
        )
    rows = list(session.scalars(stmt.order_by(RetrievalEvalRun.created_at.desc()).limit(limit)))
    return RetrievalEvalRunListResponse(count=len(rows), runs=[_retrieval_eval_run_summary_read(run) for run in rows])


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/retrieval-evals/{run_id}",
    response_model=RetrievalEvalRunRead,
)
def get_retrieval_eval_run(
    workspace_id: UUID,
    project_id: UUID,
    run_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> RetrievalEvalRunRead:
    require_scope(principal, "project:query")
    _require_project_access(session, workspace_id, project_id, principal)
    run = session.scalar(
        select(RetrievalEvalRun).where(
            RetrievalEvalRun.id == run_id,
            RetrievalEvalRun.workspace_id == workspace_id,
            RetrievalEvalRun.project_id == project_id,
        )
    )
    if run is None or not _eval_run_visible_to_principal(principal, run):
        raise HTTPException(status_code=404, detail="eval run not found")
    return _retrieval_eval_run_read(session, run)


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/retrieval-profiles",
    response_model=RetrievalProfilesResponse,
)
def list_retrieval_profiles(
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> RetrievalProfilesResponse:
    require_scope(principal, "project:read")
    _require_project_access(session, workspace_id, project_id, principal)
    profiles = [
        RetrievalProfileRead(
            name=name,
            description=profile.description,
            weights={
                "lexical": profile.lexical_weight,
                "vector": profile.vector_weight,
                "graph": profile.graph_weight,
                "rerank": profile.rerank_weight,
            },
            candidate_pool={
                "multiplier": profile.candidate_multiplier,
                "min": profile.candidate_pool_min,
                "max": profile.candidate_pool_max,
            },
            second_stage_rerank=profile.second_stage_rerank,
            promote_sequence_siblings=profile.promote_sequence_siblings,
        )
        for name, profile in RETRIEVAL_PROFILES.items()
    ]
    return RetrievalProfilesResponse(default=DEFAULT_RETRIEVAL_PROFILE, profiles=profiles)


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/retrieval-evals",
    response_model=RetrievalEvalResponse,
)
def run_retrieval_eval(
    workspace_id: UUID,
    project_id: UUID,
    payload: RetrievalEvalRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> RetrievalEvalResponse:
    require_scope(principal, "project:query")
    _require_project_access(session, workspace_id, project_id, principal)
    effective_resource_ids_by_question: list[list[UUID] | None] = []
    referenced_ids: set[UUID] = set()
    for question in payload.questions:
        effective_resource_ids = _effective_resource_ids(principal, question.resource_ids)
        effective_resource_ids_by_question.append(effective_resource_ids)
        referenced_ids.update(question.expected_resource_ids)
        referenced_ids.update(question.forbidden_resource_ids)
        referenced_ids.update(effective_resource_ids or [])
    for rid in referenced_ids:
        _resolve_resource(session, workspace_id, project_id, rid, principal)
    embedding_config = current_embedding_config()
    diagnostics_resource_ids: list[UUID] | None
    if any(resource_ids is None for resource_ids in effective_resource_ids_by_question):
        diagnostics_resource_ids = None
    else:
        diagnostics_resource_ids = sorted({rid for resource_ids in effective_resource_ids_by_question for rid in (resource_ids or [])})
    diagnostics = embedding_namespace_diagnostics(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        resource_ids=diagnostics_resource_ids,
    )
    results: list[RetrievalEvalResult] = []
    all_failure_reasons: list[str] = []
    question_resource_coverage: list[dict[str, Any]] = []
    for question, effective_resource_ids in zip(payload.questions, effective_resource_ids_by_question, strict=True):
        started = perf_counter()
        response = _build_agent_context_response(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            payload=AgentContextRequest(
                query=question.query,
                profile=payload.profile,
                top_k=question.top_k,
                resource_ids=effective_resource_ids,
                runtime=payload.runtime,
                include_code_symbols=question.include_code_symbols,
                max_chars=payload.max_chars,
            ),
            principal=principal,
        )
        latency_ms = round((perf_counter() - started) * 1000, 2)
        cited_resource_ids = {citation.resource_id for citation in response.citations}
        cited_paths = {citation.path for citation in response.citations if citation.path}
        cited_symbol_names = {symbol.name for symbol in response.symbols}
        requested_for_question = effective_resource_ids or []
        resource_count_by_id = Counter(str(citation.resource_id) for citation in response.citations)
        missing_requested_for_question = [str(rid) for rid in requested_for_question if resource_count_by_id.get(str(rid), 0) == 0]
        question_resource_coverage.append(
            {
                "question_id": question.id,
                "requested_resource_ids": [str(rid) for rid in requested_for_question],
                "cited_resource_counts": dict(sorted(resource_count_by_id.items())),
                "missing_requested_resource_ids": missing_requested_for_question,
                "coverage_warnings": response.coverage_warnings,
            }
        )
        failures: list[str] = []
        if len(response.citations) < question.min_citations:
            failures.append("missing_citations")
        missing_expected = sorted(rid for rid in question.expected_resource_ids if rid not in cited_resource_ids)
        if missing_expected:
            failures.append("missing_expected_resources:" + ",".join(str(rid) for rid in missing_expected))
        forbidden_hits = sorted(rid for rid in question.forbidden_resource_ids if rid in cited_resource_ids)
        if forbidden_hits:
            failures.append("forbidden_resources_cited:" + ",".join(str(rid) for rid in forbidden_hits))
        missing_paths = [path for path in question.expected_paths if path not in cited_paths]
        if missing_paths:
            failures.append("missing_expected_paths:" + ",".join(path[:128] for path in missing_paths))
        missing_symbols = [symbol for symbol in question.expected_symbols if symbol not in cited_symbol_names]
        if missing_symbols:
            failures.append("missing_expected_symbols:" + ",".join(symbol[:128] for symbol in missing_symbols))
        lower_context = response.context.lower()
        for required in question.required_texts:
            if required.lower() not in lower_context:
                failures.append(f"missing_required_text:{required[:128]}")
        all_failure_reasons.extend(failures)
        results.append(
            RetrievalEvalResult(
                id=question.id,
                query=question.query,
                passed=not failures,
                failure_reasons=failures,
                latency_ms=latency_ms,
                citation_count=len(response.citations),
                context_chars=len(response.context),
                symbol_count=len(response.symbols),
                expected_resource_ids=question.expected_resource_ids,
                cited_resource_ids=sorted(cited_resource_ids),
                forbidden_resource_ids=question.forbidden_resource_ids,
                hit_quality=[
                    {
                        "resource_id": str(citation.resource_id),
                        "snapshot_id": str(citation.snapshot_id),
                        "path": citation.path,
                        "title": citation.title,
                        "ordinal": citation.ordinal,
                        "version": citation.version,
                        "score": citation.score,
                        "graph_score": citation.graph_score,
                        "score_components": citation.score_components,
                    }
                    for citation in response.citations
                ],
            )
        )
    passed_count = sum(1 for result in results if result.passed)
    latencies = [result.latency_ms for result in results]
    eval_profile = normalize_retrieval_profile(payload.profile)
    eval_response = RetrievalEvalResponse(
        profile=eval_profile.name,
        workspace_id=workspace_id,
        project_id=project_id,
        generated_at=datetime.now(UTC),
        provider=embedding_config.provider,
        model=embedding_config.model,
        diagnostics={
            **diagnostics,
            "retrieval_profile": eval_profile.name,
            "retrieval_profile_weights": retrieval_profile_manifest()[eval_profile.name]["weights"],
            "rerank_score_range": [0.0, 1.0],
            "question_resource_coverage": question_resource_coverage,
        },
        summary=RetrievalEvalSummary(
            status="passed" if passed_count == len(results) else "failed",
            question_count=len(results),
            passed_count=passed_count,
            failed_count=len(results) - passed_count,
            pass_rate=round(passed_count / len(results), 4) if results else 0.0,
            max_latency_ms=max(latencies) if latencies else 0.0,
            avg_latency_ms=round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
            failure_reasons=sorted(set(all_failure_reasons)),
        ),
        results=results,
    )
    persisted_resource_ids = set(referenced_ids)
    project_wide = False
    for effective_resource_ids in effective_resource_ids_by_question:
        if effective_resource_ids is None:
            project_wide = True
        else:
            persisted_resource_ids.update(effective_resource_ids)
    for result in results:
        persisted_resource_ids.update(result.cited_resource_ids)
    return _persist_retrieval_eval_run(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        principal=principal,
        payload=payload,
        response=eval_response,
        project_wide=project_wide,
        resource_ids=persisted_resource_ids,
    )


def _json_rpc_error(rpc_id: object | None, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


def _mcp_tool_result(rpc_id: object | None, result: Any) -> dict:
    payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else jsonable_encoder(result)
    text_payload = result.model_dump_json() if hasattr(result, "model_dump_json") else json.dumps(payload)
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {"content": [{"type": "text", "text": text_payload}], "structuredContent": payload},
    }


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


def _runtime_snapshot_section_locator(snapshot_section: SnapshotSection, section: Section, file_row: SnapshotFile | None = None) -> dict[str, Any]:
    return {
        "resource_id": str(snapshot_section.version_resource_id),
        "source_snapshot_id": str(snapshot_section.source_snapshot_id),
        "snapshot_section_id": str(snapshot_section.id),
        "path": snapshot_section.normalized_path,
        "title": section.title,
        "start_line": 1,
        "end_line": file_row.line_count if file_row else None,
        "content_hash": file_row.content_hash if file_row else None,
    }


def _runtime_require_pack_covers_locator(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any], *, resource_id: UUID, source_snapshot_id: UUID) -> None:
    if not args.get("context_pack_key"):
        return
    pack_args = {"pack_key": args.get("context_pack_key"), "version": args.get("context_pack_version")}
    version = _runtime_resolve_pack(session, workspace_id, project_id, principal, pack_args)
    covered = session.scalar(
        select(ContextPackResourceCoverage.id).where(
            ContextPackResourceCoverage.context_pack_version_id == version.id,
            ContextPackResourceCoverage.resource_id == resource_id,
            ContextPackResourceCoverage.source_snapshot_id == source_snapshot_id,
        )
    )
    if covered is None:
        raise HTTPException(status_code=404, detail={"code": "section_not_found", "message": "section not found in context pack"})


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


def _sample_counter(counter: Counter[str], limit: int = 20) -> dict[str, int]:
    return dict(counter.most_common(limit))


def _runtime_graph_overview(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any]) -> dict[str, Any]:
    require_scope(principal, "project:query")
    require_scope(principal, "resource:read")
    _require_project_access(session, workspace_id, project_id, principal)
    max_resources = _runtime_limit(args.get("max_resources"), default=20, max_value=50)
    max_items = _runtime_limit(args.get("max_items"), default=20, max_value=50)

    predicates = [
        Resource.workspace_id == workspace_id,
        Resource.project_id == project_id,
        Resource.deleted_at.is_(None),
        Resource.archived_at.is_(None),
    ]
    if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
        allowed_ids = list(principal.api_token.allowed_resource_ids)
        if not allowed_ids:
            return {
                "project": {"scope": "authorized_project", "locator": {"workspace_id": str(workspace_id), "project_id": str(project_id)}},
                "freshness": _runtime_freshness("current"),
                "resources": [],
                "graphs": [],
                "schema_hints": {"node_types": {}, "edge_types": {}},
                "topology": {"top_directories": [], "entry_like_files": [], "hotspots": []},
                "merge_graphs": [],
                "unresolved_reconcile_candidates": [],
                "stale_or_missing": [],
                "guidance": "No resources are authorized for this token.",
                "limits": {"max_resources": max_resources, "max_items": max_items},
                "truncated": False,
            }
        predicates.append(Resource.id.in_(allowed_ids))

    visible = list(
        session.scalars(
            select(Resource)
            .where(*predicates)
            .order_by(Resource.name.asc())
            .limit(max_resources + 1)
        )
    )
    truncated = len(visible) > max_resources
    visible = visible[:max_resources]
    visible_ids = {resource.id for resource in visible}

    resource_cards: list[dict[str, Any]] = []
    freshness_resources: list[dict[str, Any]] = []
    node_types: Counter[str] = Counter()
    edge_types: Counter[str] = Counter()
    directories: Counter[str] = Counter()
    hotspots: Counter[str] = Counter()
    entries: list[dict[str, Any]] = []
    graphs: list[dict[str, Any]] = []
    stale_or_missing: list[dict[str, Any]] = []

    for resource in visible:
        row = session.execute(
            select(Graph, GraphVersion)
            .join(GraphVersion, Graph.current_version_id == GraphVersion.id)
            .where(
                Graph.workspace_id == workspace_id,
                Graph.project_id == project_id,
                Graph.resource_id == resource.id,
                Graph.status == "active",
                GraphVersion.status == GRAPH_VERSION_PUBLISHED,
            )
        ).first()
        graph_payload = None
        if row:
            graph, version = row
            graph_payload = {
                "kind": "resource",
                "resource_name": resource.name,
                "graph_key": graph.graph_key,
                "title": graph.title,
                "version": version.version,
                "version_hash": version.version_hash,
                "node_count": version.node_count,
                "edge_count": version.edge_count,
                "source_snapshot_id": str(version.source_snapshot_id),
                "status": version.status,
            }
            graphs.append(graph_payload)
            freshness = _runtime_resource_freshness(session, resource, version.source_snapshot_id)
            freshness_resources.append(freshness)
            if freshness["status"] != "current":
                stale_or_missing.append(
                    {
                        "resource_name": resource.name,
                        "status": "stale_published_graph",
                        "graph_key": graph.graph_key,
                        "graph_snapshot_id": str(version.source_snapshot_id),
                        "current_snapshot_id": str(resource.current_snapshot_id) if resource.current_snapshot_id else None,
                    }
                )
            for node_type, count in session.execute(
                select(GraphNode.node_type, func.count())
                .where(
                    GraphNode.workspace_id == workspace_id,
                    GraphNode.project_id == project_id,
                    GraphNode.resource_id == resource.id,
                    GraphNode.source_snapshot_id == version.source_snapshot_id,
                )
                .group_by(GraphNode.node_type)
            ):
                node_types[str(node_type)] += int(count)
            for edge_type, count in session.execute(
                select(GraphEdge.edge_type, func.count())
                .where(
                    GraphEdge.workspace_id == workspace_id,
                    GraphEdge.project_id == project_id,
                    GraphEdge.resource_id == resource.id,
                    GraphEdge.source_snapshot_id == version.source_snapshot_id,
                )
                .group_by(GraphEdge.edge_type)
            ):
                edge_types[str(edge_type)] += int(count)
            nodes = list(
                session.scalars(
                    select(GraphNode)
                    .where(
                        GraphNode.workspace_id == workspace_id,
                        GraphNode.project_id == project_id,
                        GraphNode.resource_id == resource.id,
                        GraphNode.source_snapshot_id == version.source_snapshot_id,
                    )
                    .order_by(GraphNode.node_type.asc(), GraphNode.label.asc())
                    .limit(max_items * 10)
                )
            )
            for node in nodes:
                if node.path and "/" in node.path:
                    directories[node.path.rsplit("/", 1)[0]] += 1
                if node.path and node.path.rsplit("/", 1)[-1].lower() in {"readme.md", "main.py", "app.py", "index.ts", "index.tsx", "server.ts", "package.json", "pyproject.toml"}:
                    entries.append(
                        {
                            "resource_name": resource.name,
                            "path": node.path,
                            "label": node.label,
                            "locator": {
                                "resource_id": str(resource.id),
                                "source_snapshot_id": str(version.source_snapshot_id),
                                "path": node.path,
                            },
                        }
                    )
                hotspots[node.path or node.label] += 1
        else:
            freshness_resources.append(_runtime_resource_freshness(session, resource, resource.current_snapshot_id))
            stale_or_missing.append(
                {
                    "resource_name": resource.name,
                    "status": "missing_published_graph",
                    "current_snapshot_id": str(resource.current_snapshot_id) if resource.current_snapshot_id else None,
                }
            )
        resource_cards.append(
            {
                "name": resource.name,
                "type": resource.type,
                "status": resource.status,
                "current_snapshot_id": str(resource.current_snapshot_id) if resource.current_snapshot_id else None,
                "graph": graph_payload,
                "resource_id": str(resource.id),
            }
        )

    merge_graphs: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    merge_rows = session.execute(
        select(GraphMerge, GraphMergeVersion)
        .join(GraphMergeVersion, GraphMerge.current_version_id == GraphMergeVersion.id)
        .where(
            GraphMerge.workspace_id == workspace_id,
            GraphMerge.project_id == project_id,
            GraphMerge.status == "active",
            GraphMergeVersion.status == GRAPH_MERGE_VERSION_PUBLISHED,
        )
        .order_by(GraphMerge.merge_key.asc())
        .limit(max_resources)
    ).all()
    for merge, version in merge_rows:
        inputs = session.execute(
            select(GraphMergeInput, Resource)
            .join(Resource, GraphMergeInput.input_resource_id == Resource.id)
            .where(GraphMergeInput.graph_merge_version_id == version.id)
            .order_by(GraphMergeInput.ordinal.asc())
        ).all()
        input_resources = [resource for _input, resource in inputs]
        if not input_resources or not all(resource.id in visible_ids for resource in input_resources):
            continue
        payload = {
            "kind": "merge",
            "merge_key": merge.merge_key,
            "title": merge.title,
            "version": version.version,
            "version_hash": version.version_hash,
            "node_count": version.node_count,
            "edge_count": version.edge_count,
            "unresolved_candidate_count": version.unresolved_candidate_count,
            "input_sources": [resource.name for resource in input_resources],
        }
        graphs.append(payload)
        merge_graphs.append(payload)
        for candidate in session.scalars(
            select(GraphMergeReconcileCandidate)
            .where(
                GraphMergeReconcileCandidate.graph_merge_version_id == version.id,
                GraphMergeReconcileCandidate.status == "open",
            )
            .order_by(GraphMergeReconcileCandidate.confidence.desc())
            .limit(max_items)
        ):
            unresolved.append(
                {
                    "merge_key": merge.merge_key,
                    "candidate_key": candidate.candidate_key,
                    "candidate_type": candidate.candidate_type,
                    "confidence": candidate.confidence,
                    "left": candidate.left_origin_json,
                    "right": candidate.right_origin_json,
                }
            )

    status_value = "missing_graphs" if visible and not graphs else "partial" if stale_or_missing else "current"
    truncated = truncated or len(entries) > max_items or len(unresolved) > max_items
    return {
        "project": {"scope": "authorized_project", "locator": {"workspace_id": str(workspace_id), "project_id": str(project_id)}},
        "freshness": _runtime_freshness(status_value, resources=freshness_resources),
        "resources": resource_cards,
        "graphs": graphs[:max_resources],
        "schema_hints": {
            "node_types": _sample_counter(node_types, max_items),
            "edge_types": _sample_counter(edge_types, max_items),
        },
        "topology": {
            "top_directories": [{"path": path, "count": count} for path, count in directories.most_common(max_items)],
            "entry_like_files": entries[:max_items],
            "hotspots": [{"path_or_label": key, "count": count} for key, count in hotspots.most_common(max_items)],
        },
        "merge_graphs": merge_graphs,
        "unresolved_reconcile_candidates": unresolved[:max_items],
        "stale_or_missing": stale_or_missing[:max_items],
        "guidance": "Use graph_query for node drilldown, graph_path for published merge graphs, and read_file/read_section with returned locators for evidence.",
        "limits": {"max_resources": max_resources, "max_items": max_items},
        "truncated": truncated,
    }

@app.get("/workspaces/{workspace_id}/projects/{project_id}/architecture")
def get_project_architecture(workspace_id: UUID, project_id: UUID, max_resources: int = 20, max_items: int = 20, principal: Principal = Depends(require_principal), session: Session = Depends(get_session)) -> dict[str, Any]:
    return _runtime_graph_overview(session, workspace_id, project_id, principal, {"max_resources": max_resources, "max_items": max_items})


def _runtime_get_graph_inventory(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any]) -> dict[str, Any]:
    require_scope(principal, "project:query")
    require_scope(principal, "resource:read")
    kind = str(args.get("kind") or "all")
    query = str(args.get("query") or "").strip().lower()
    limit = _runtime_limit(args.get("limit"), default=100, max_value=100)
    offset = _runtime_cursor(args.get("cursor"))
    resource_graphs: list[dict[str, Any]] = []
    merge_graphs: list[dict[str, Any]] = []
    if kind in {"all", "resource"}:
        resource_rows = session.execute(select(Graph, GraphVersion, Resource).join(GraphVersion, Graph.current_version_id == GraphVersion.id).join(Resource, Graph.resource_id == Resource.id).where(Graph.workspace_id == workspace_id, Graph.project_id == project_id, Graph.status == "active", GraphVersion.status == GRAPH_VERSION_PUBLISHED, Resource.deleted_at.is_(None), Resource.archived_at.is_(None)).order_by(Graph.graph_key.asc()).offset(offset).limit(limit)).all()
        for graph, version, resource in resource_rows:
            if not token_allows_resource(principal, resource.id):
                continue
            if query and query not in graph.graph_key.lower() and query not in graph.title.lower() and query not in resource.name.lower():
                continue
            resource_graphs.append({"graph_key": graph.graph_key, "title": graph.title, "resource_id": str(resource.id), "resource_name": resource.name, "current_version": version.version, "node_count": version.node_count, "edge_count": version.edge_count})
    if kind in {"all", "merge"}:
        merge_rows = session.execute(select(GraphMerge, GraphMergeVersion).join(GraphMergeVersion, GraphMerge.current_version_id == GraphMergeVersion.id).where(GraphMerge.workspace_id == workspace_id, GraphMerge.project_id == project_id, GraphMerge.status == "active", GraphMergeVersion.status == GRAPH_MERGE_VERSION_PUBLISHED).order_by(GraphMerge.merge_key.asc()).offset(offset).limit(limit)).all()
        for merge, version in merge_rows:
            inputs = session.execute(select(GraphMergeInput, Resource).join(Resource, GraphMergeInput.input_resource_id == Resource.id).where(GraphMergeInput.graph_merge_version_id == version.id).order_by(GraphMergeInput.ordinal.asc())).all()
            resources = [resource for _input, resource in inputs]
            if not _runtime_resource_rows_allowed(principal, [resource.id for resource in resources]):
                continue
            if query and query not in merge.merge_key.lower() and query not in merge.title.lower():
                continue
            merge_graphs.append({"merge_key": merge.merge_key, "title": merge.title, "current_version": version.version, "node_count": version.node_count, "edge_count": version.edge_count, "input_sources": [resource.name for resource in resources]})
    returned = len(resource_graphs) + len(merge_graphs)
    return {"resource_graphs": resource_graphs, "merge_graphs": merge_graphs, "next_cursor": str(offset + limit) if returned >= limit else None}


def _runtime_list_sources(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any]) -> dict[str, Any]:
    require_scope(principal, "project:query")
    require_scope(principal, "resource:read")
    limit = _runtime_limit(args.get("limit"), default=100, max_value=100)
    offset = _runtime_cursor(args.get("cursor"))
    query = str(args.get("query") or "").strip().lower()
    resource_type = args.get("resource_type")
    predicates = [Resource.workspace_id == workspace_id, Resource.project_id == project_id, Resource.deleted_at.is_(None), Resource.archived_at.is_(None)]
    if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
        allowed_resource_ids = list(principal.api_token.allowed_resource_ids)
        if not allowed_resource_ids:
            return {"sources": [], "next_cursor": None}
        predicates.append(Resource.id.in_(allowed_resource_ids))
    if resource_type:
        predicates.append(Resource.type == str(resource_type))
    rows = list(session.scalars(select(Resource).where(*predicates).order_by(Resource.name.asc()).offset(offset).limit(limit + 1)))
    sources: list[dict[str, Any]] = []
    for resource in rows[:limit]:
        if not token_allows_resource(principal, resource.id):
            continue
        if query and query not in resource.name.lower() and query not in resource.uri.lower():
            continue
        maps = list(session.scalars(select(ContextArtifact).where(ContextArtifact.resource_id == resource.id, ContextArtifact.artifact_type == ARTIFACT_TYPE_RESOURCE_MAP, ContextArtifact.status == "approved").order_by(ContextArtifact.created_at.desc()).limit(3)))
        graph = session.execute(select(Graph, GraphVersion).join(GraphVersion, Graph.current_version_id == GraphVersion.id).where(Graph.resource_id == resource.id, Graph.status == "active", GraphVersion.status == GRAPH_VERSION_PUBLISHED)).first()
        sources.append({"resource_id": str(resource.id), "name": resource.name, "type": resource.type, "status": resource.status, "current_snapshot_id": str(resource.current_snapshot_id) if resource.current_snapshot_id else None, "resource_maps": [{"artifact_id": str(artifact.id), "status": artifact.status, "artifact_hash": artifact.artifact_hash} for artifact in maps], "graphs": [{"graph_key": graph[0].graph_key, "current_version": graph[1].version}] if graph else []})
    return {"sources": sources, "next_cursor": str(offset + limit) if len(rows) > limit else None}


def _runtime_get_context_pack(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any]) -> dict[str, Any]:
    require_scope(principal, "project:query")
    require_scope(principal, "resource:read")
    version = _runtime_resolve_pack(session, workspace_id, project_id, principal, args)
    limit = _runtime_limit(args.get("limit"), default=100, max_value=200)
    offset = _runtime_cursor(args.get("cursor"))
    coverage_rows = list(session.execute(select(ContextPackResourceCoverage, Resource).join(Resource, ContextPackResourceCoverage.resource_id == Resource.id).where(ContextPackResourceCoverage.context_pack_version_id == version.id).order_by(Resource.name.asc()).offset(offset).limit(limit + 1)).all())
    resources = [resource for _coverage, resource in coverage_rows[:limit]]
    if not _runtime_resource_rows_allowed(principal, [resource.id for resource in resources]):
        raise HTTPException(status_code=404, detail={"code": "pack_not_found", "message": "context pack not found"})
    artifact_rows = list(session.execute(select(ContextPackArtifact, ContextArtifact).join(ContextArtifact, ContextPackArtifact.context_artifact_id == ContextArtifact.id).where(ContextPackArtifact.context_pack_version_id == version.id).order_by(ContextPackArtifact.ordinal.asc()).offset(offset).limit(limit)).all()) if args.get("include_artifacts", True) else []
    artifacts = []
    for pack_artifact, artifact in artifact_rows:
        citations = list(session.scalars(select(ContextArtifactCitation).where(ContextArtifactCitation.context_artifact_id == artifact.id).order_by(ContextArtifactCitation.ordinal.asc()).limit(5)))
        artifacts.append({"id": str(artifact.id), "pack_artifact_id": str(pack_artifact.id), "artifact_type": artifact.artifact_type, "resource_id": str(artifact.resource_id), "source_snapshot_id": str(artifact.source_snapshot_id), "status": artifact.status, "artifact_hash": artifact.artifact_hash, "title": artifact.title, "citation_locators": [_runtime_citation_locator(citation) for citation in citations]})
    sources = [{"resource_id": str(resource.id), "name": resource.name, "type": resource.type, "current_snapshot_id": str(resource.current_snapshot_id) if resource.current_snapshot_id else None} for _coverage, resource in coverage_rows[:limit]]
    coverage = [{"resource_id": str(coverage.resource_id), "source_snapshot_id": str(coverage.source_snapshot_id), "resource_manifest_id": str(coverage.resource_manifest_id), "artifact_count": coverage.artifact_count, "citation_count": coverage.citation_count} for coverage, _resource in coverage_rows[:limit]] if args.get("include_coverage", True) else []
    freshness_resources = [_runtime_resource_freshness(session, resource, coverage.source_snapshot_id) for coverage, resource in coverage_rows[:limit]]
    return {"pack": {"id": str(version.id), "pack_key": version.pack_key, "version": version.version, "status": version.status, "title": version.title, "pack_hash": version.pack_hash}, "freshness": _runtime_freshness(version.status if version.status != PACK_STATUS_PUBLISHED else "current", resources=freshness_resources, pack={"pack_key": version.pack_key, "version": version.version, "status": version.status}), "sources": sources, "artifacts": artifacts, "coverage": coverage, "graph_inventory": _runtime_get_graph_inventory(session, workspace_id, project_id, principal, {"limit": 50}) if args.get("include_graph_inventory", True) else {"resource_graphs": [], "merge_graphs": []}, "runtime_guidance": "Start with search, then read_section using the returned locator. Use graph tools for architecture/impact questions.", "next_cursor": str(offset + limit) if len(coverage_rows) > limit else None, "truncated": len(coverage_rows) > limit}


def _runtime_get_resource_map(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any]) -> dict[str, Any]:
    require_scope(principal, "project:query")
    require_scope(principal, "resource:read")
    resource = _runtime_resolve_resource_ref(session, workspace_id, project_id, principal, args)
    artifact_id = args.get("artifact_id")
    stmt = select(ContextArtifact).where(ContextArtifact.workspace_id == workspace_id, ContextArtifact.project_id == project_id, ContextArtifact.resource_id == resource.id, ContextArtifact.artifact_type == ARTIFACT_TYPE_RESOURCE_MAP, ContextArtifact.status == "approved")
    if artifact_id:
        stmt = stmt.where(ContextArtifact.id == UUID(str(artifact_id)))
    elif args.get("source_snapshot_id"):
        stmt = stmt.where(ContextArtifact.source_snapshot_id == UUID(str(args["source_snapshot_id"])))
    elif resource.current_snapshot_id:
        stmt = stmt.where(ContextArtifact.source_snapshot_id == resource.current_snapshot_id)
    artifact = session.scalar(stmt.order_by(ContextArtifact.created_at.desc()))
    if artifact is None:
        raise HTTPException(status_code=404, detail={"code": "resource_map_not_found", "message": "approved resource map not found"})
    limit = _runtime_limit(args.get("limit"), default=200, max_value=200)
    offset = _runtime_cursor(args.get("cursor"))
    citations = list(session.scalars(select(ContextArtifactCitation).where(ContextArtifactCitation.context_artifact_id == artifact.id).order_by(ContextArtifactCitation.normalized_path.asc(), ContextArtifactCitation.ordinal.asc()).offset(offset).limit(limit + 1)))
    entries = [{"title": citation.title, "path": citation.normalized_path, "summary": None, "locator": _runtime_citation_locator(citation)} for citation in citations[:limit]]
    sources = list(session.scalars(select(ContextArtifactSource).where(ContextArtifactSource.context_artifact_id == artifact.id).order_by(ContextArtifactSource.normalized_path.asc()).limit(limit))) if args.get("include_sources", True) else []
    freshness_resource = _runtime_resource_freshness(session, resource, artifact.source_snapshot_id)
    raw_resource_map = artifact.content_json
    resource_map_text = json.dumps(jsonable_encoder(raw_resource_map), sort_keys=True)
    map_truncated = len(resource_map_text) > 20_000
    resource_map_payload = raw_resource_map if not map_truncated else {"truncated": True, "top_level_keys": sorted(raw_resource_map.keys()) if isinstance(raw_resource_map, dict) else [], "entry_count": len(raw_resource_map) if isinstance(raw_resource_map, list) else None}
    return {"artifact": {"id": str(artifact.id), "artifact_type": artifact.artifact_type, "status": artifact.status, "artifact_hash": artifact.artifact_hash, "artifact_revision": artifact.artifact_revision, "resource_id": str(artifact.resource_id), "source_snapshot_id": str(artifact.source_snapshot_id), "title": artifact.title, "approved_at": artifact.approved_at}, "freshness": _runtime_freshness("current", resources=[freshness_resource], artifact={"id": str(artifact.id), "status": artifact.status, "artifact_hash": artifact.artifact_hash}), "resource_map": resource_map_payload, "entries": entries, "sources": [{"path": source.normalized_path, "status": source.status, "coverage_status": source.coverage_status} for source in sources], "citations": [{"locator": _runtime_citation_locator(citation), "snippet": None} for citation in citations[:limit]] if args.get("include_citations", True) else [], "next_cursor": str(offset + limit) if len(citations) > limit else None, "truncated": len(citations) > limit or map_truncated}


def _runtime_search(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any]) -> dict[str, Any]:
    require_scope(principal, "project:query")
    require_scope(principal, "resource:read")
    query = str(args.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=422, detail={"code": "invalid_query", "message": "query is required"})
    top_k = _runtime_limit(args.get("top_k"), default=8, max_value=50)
    requested_resource_ids = [UUID(str(value)) for value in args.get("resource_ids") or []]
    pack_version = None
    snapshot_ids: list[UUID] = []
    if args.get("context_pack_key"):
        pack_args = {"pack_key": args.get("context_pack_key"), "version": args.get("context_pack_version")}
        pack_version = _runtime_resolve_pack(session, workspace_id, project_id, principal, pack_args)
        coverage = list(session.scalars(select(ContextPackResourceCoverage).where(ContextPackResourceCoverage.context_pack_version_id == pack_version.id)))
        if requested_resource_ids:
            requested_set = set(requested_resource_ids)
            coverage = [row for row in coverage if row.resource_id in requested_set]
        requested_resource_ids = [row.resource_id for row in coverage]
        snapshot_ids = [row.source_snapshot_id for row in coverage]
        if not requested_resource_ids:
            return {"query": query, "profile": args.get("profile") or "hybrid", "hits": [], "freshness": _runtime_freshness("current")}
    effective_resource_ids = _effective_resource_ids(principal, requested_resource_ids or None)
    if _is_empty_scope(effective_resource_ids):
        return {"query": query, "profile": args.get("profile") or "hybrid", "hits": [], "freshness": _runtime_freshness("current")}
    resource_clause = ""
    snapshot_clause = ""
    params: dict[str, Any] = {"ws": str(workspace_id), "proj": str(project_id), "q": query, "k": top_k}
    if effective_resource_ids:
        resource_clause = "AND c.resource_id = ANY(CAST(:rids AS uuid[]))"
        params["rids"] = [str(rid) for rid in effective_resource_ids]
    if snapshot_ids:
        snapshot_clause = "AND c.source_snapshot_id = ANY(CAST(:sids AS uuid[]))"
        params["sids"] = [str(sid) for sid in snapshot_ids]
    rows = session.execute(text(f"""
        SELECT c.resource_id, c.source_snapshot_id, c.path, c.title, c.ordinal, c.content_hash, c.content,
               s.version, s.version_kind, s.metadata AS snap_meta,
               ts_rank(to_tsvector('english', c.content), plainto_tsquery('english', :q)) AS score
        FROM chunks c
        JOIN source_snapshots s ON s.id = c.source_snapshot_id
        JOIN resources r ON r.id = c.resource_id
        WHERE c.workspace_id = CAST(:ws AS uuid)
          AND c.project_id = CAST(:proj AS uuid)
          AND c.deleted_at IS NULL
          AND r.deleted_at IS NULL
          AND r.archived_at IS NULL
          AND r.retrieval_enabled = true
          {resource_clause}
          {snapshot_clause}
          AND to_tsvector('english', c.content) @@ plainto_tsquery('english', :q)
        ORDER BY score DESC, c.resource_id, c.ordinal ASC
        LIMIT :k
        """), params).mappings().all()
    hits: list[dict[str, Any]] = []
    for row in rows:
        resource = session.scalar(select(Resource).where(Resource.id == row["resource_id"]))
        if resource is None or not token_allows_resource(principal, resource.id):
            continue
        section_row = session.execute(select(SnapshotSection, Section).join(Section, SnapshotSection.section_id == Section.id).where(SnapshotSection.source_snapshot_id == row["source_snapshot_id"], SnapshotSection.version_resource_id == row["resource_id"], SnapshotSection.normalized_path == row["path"]).order_by(SnapshotSection.ordinal.asc()).limit(1)).first()
        snapshot_section_id = section_row[0].id if section_row else None
        snap_meta = row["snap_meta"] if isinstance(row["snap_meta"], dict) else {}
        locator = {"resource_id": str(row["resource_id"]), "source_snapshot_id": str(row["source_snapshot_id"]), "snapshot_section_id": str(snapshot_section_id) if snapshot_section_id else None, "context_pack_key": pack_version.pack_key if pack_version else None, "context_pack_version": pack_version.version if pack_version else None, "path": row["path"], "title": row["title"], "start_line": 1, "end_line": None, "content_hash": row["content_hash"]}
        hits.append({**locator, "snippet": _make_snippet(row["content"]), "score": float(row["score"]), "version": row["version"], "version_kind": row["version_kind"], "commit": snap_meta.get("commit"), "freshness": _runtime_freshness("current", resources=[_runtime_resource_freshness(session, resource, row["source_snapshot_id"])])})
    return {"query": query, "profile": args.get("profile") or "hybrid", "hits": hits, "freshness": _runtime_freshness("current")}


def _runtime_read_section(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any]) -> dict[str, Any]:
    require_scope(principal, "project:query")
    require_scope(principal, "resource:read")
    resource_id_arg = args.get("resource_id")
    if not resource_id_arg:
        raise HTTPException(status_code=422, detail={"code": "missing_resource_locator", "message": "provide resource_id or resource_ref with the section locator"})
    resource_id = UUID(str(resource_id_arg))
    resource = session.scalar(select(Resource).where(Resource.id == resource_id, Resource.workspace_id == workspace_id, Resource.project_id == project_id))
    if resource is None:
        raise HTTPException(status_code=404, detail={"code": "section_not_found", "message": "section not found"})
    _runtime_resource_allowed_or_404(principal, resource.id)
    citation = None
    snapshot_section = None
    section = None
    if args.get("context_artifact_citation_id"):
        citation = session.scalar(select(ContextArtifactCitation).where(ContextArtifactCitation.id == UUID(str(args["context_artifact_citation_id"])), ContextArtifactCitation.workspace_id == workspace_id, ContextArtifactCitation.project_id == project_id, ContextArtifactCitation.resource_id == resource.id))
        if citation is None:
            raise HTTPException(status_code=404, detail={"code": "section_not_found", "message": "section not found"})
        snapshot_section = session.scalar(select(SnapshotSection).where(SnapshotSection.id == citation.snapshot_section_id))
    elif args.get("snapshot_section_id") and args.get("source_snapshot_id"):
        snapshot_section = session.scalar(select(SnapshotSection).where(SnapshotSection.id == UUID(str(args["snapshot_section_id"])), SnapshotSection.source_snapshot_id == UUID(str(args["source_snapshot_id"])), SnapshotSection.version_resource_id == resource.id, SnapshotSection.workspace_id == workspace_id, SnapshotSection.project_id == project_id))
    elif args.get("source_snapshot_id") and args.get("path") and args.get("content_hash"):
        path = validate_repo_path(str(args["path"]))
        file_row = session.scalar(select(SnapshotFile).where(SnapshotFile.resource_id == resource.id, SnapshotFile.source_snapshot_id == UUID(str(args["source_snapshot_id"])), SnapshotFile.path == path, SnapshotFile.content_hash == str(args["content_hash"]), SnapshotFile.deleted_at.is_(None)))
        if file_row is None:
            raise HTTPException(status_code=404, detail={"code": "section_not_found", "message": "section not found"})
        _runtime_require_pack_covers_locator(session, workspace_id, project_id, principal, args, resource_id=resource.id, source_snapshot_id=file_row.source_snapshot_id)
        content, start, end, total, truncated = line_range(file_row.content, int(args.get("start_line") or 1), int(args.get("end_line") or min(file_row.line_count, 500)))
        return {"locator": {"resource_id": str(resource.id), "source_snapshot_id": str(file_row.source_snapshot_id), "path": file_row.path, "start_line": start, "end_line": end, "content_hash": file_row.content_hash}, "resource": {"resource_id": str(resource.id), "name": resource.name, "type": resource.type}, "section": {"title": args.get("heading"), "path": file_row.path, "start_line": start, "end_line": end, "total_lines": total}, "content": content[:20000], "freshness": _runtime_freshness("current", resources=[_runtime_resource_freshness(session, resource, file_row.source_snapshot_id)]), "truncated": truncated or len(content) > 20000}
    elif args.get("allow_current_fallback") and args.get("path") and resource.current_snapshot_id:
        path = validate_repo_path(str(args["path"]))
        file_row = session.scalar(select(SnapshotFile).where(SnapshotFile.resource_id == resource.id, SnapshotFile.source_snapshot_id == resource.current_snapshot_id, SnapshotFile.path == path, SnapshotFile.deleted_at.is_(None)))
        if file_row is None:
            raise HTTPException(status_code=404, detail={"code": "section_not_found", "message": "section not found"})
        _runtime_require_pack_covers_locator(session, workspace_id, project_id, principal, args, resource_id=resource.id, source_snapshot_id=file_row.source_snapshot_id)
        content, start, end, total, truncated = line_range(file_row.content, int(args.get("start_line") or 1), int(args.get("end_line") or min(file_row.line_count, 500)))
        return {"locator": {"resource_id": str(resource.id), "source_snapshot_id": str(file_row.source_snapshot_id), "path": file_row.path, "start_line": start, "end_line": end, "content_hash": file_row.content_hash}, "resource": {"resource_id": str(resource.id), "name": resource.name, "type": resource.type}, "section": {"title": args.get("heading"), "path": file_row.path, "start_line": start, "end_line": end, "total_lines": total}, "content": content[:20000], "freshness": _runtime_freshness("current", resources=[_runtime_resource_freshness(session, resource, file_row.source_snapshot_id)]), "truncated": truncated or len(content) > 20000}
    else:
        raise HTTPException(status_code=422, detail={"code": "ambiguous_section", "message": "provide a pinned snapshot_section_id, context_artifact_citation_id, or exact source_snapshot/path/content_hash locator"})
    if snapshot_section is None:
        raise HTTPException(status_code=404, detail={"code": "section_not_found", "message": "section not found"})
    section = session.scalar(select(Section).where(Section.id == snapshot_section.section_id))
    file_row = session.scalar(select(SnapshotFile).where(SnapshotFile.resource_id == resource.id, SnapshotFile.source_snapshot_id == snapshot_section.source_snapshot_id, SnapshotFile.path == snapshot_section.normalized_path, SnapshotFile.deleted_at.is_(None)))
    if file_row is None or file_row.is_binary:
        raise HTTPException(status_code=404, detail={"code": "section_content_unavailable", "message": "retained section content is unavailable"})
    _runtime_require_pack_covers_locator(session, workspace_id, project_id, principal, args, resource_id=resource.id, source_snapshot_id=snapshot_section.source_snapshot_id)
    content, start, end, total, truncated = line_range(file_row.content, int(args.get("start_line") or citation.line_start if citation and citation.line_start else 1), int(args.get("end_line") or citation.line_end if citation and citation.line_end else min(file_row.line_count, 500)))
    locator = _runtime_citation_locator(citation) if citation else _runtime_snapshot_section_locator(snapshot_section, section, file_row)  # type: ignore[arg-type]
    locator.update({"start_line": start, "end_line": end})
    return {"locator": locator, "resource": {"resource_id": str(resource.id), "name": resource.name, "type": resource.type}, "section": {"title": section.title if section else citation.title if citation else None, "path": file_row.path, "start_line": start, "end_line": end, "total_lines": total}, "content": content[:20000], "freshness": _runtime_freshness("current", resources=[_runtime_resource_freshness(session, resource, snapshot_section.source_snapshot_id)]), "truncated": truncated or len(content) > 20000}


def _runtime_resolve_graph_target(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any]) -> tuple[str, Graph | GraphMerge, GraphVersion | GraphMergeVersion]:
    key = str(args.get("graph_key") or "").strip()
    if not key:
        raise HTTPException(status_code=422, detail={"code": "missing_graph_key", "message": "graph_key is required"})
    kind = str(args.get("graph_kind") or "auto")
    version_number = args.get("version")
    if kind in {"auto", "resource"}:
        graph = session.scalar(select(Graph).where(Graph.workspace_id == workspace_id, Graph.project_id == project_id, Graph.graph_key == key, Graph.status == "active"))
        if graph is not None:
            _runtime_resource_allowed_or_404(principal, graph.resource_id)  # type: ignore[arg-type]
            if version_number is None:
                graph_version = session.scalar(select(GraphVersion).where(GraphVersion.id == graph.current_version_id, GraphVersion.status == GRAPH_VERSION_PUBLISHED))
            else:
                graph_version = session.scalar(select(GraphVersion).where(GraphVersion.graph_id == graph.id, GraphVersion.version == int(version_number), GraphVersion.status == GRAPH_VERSION_PUBLISHED))
            if graph_version is None:
                raise HTTPException(status_code=404, detail={"code": "graph_not_found", "message": "published graph version not found"})
            return "resource", graph, graph_version
    if kind in {"auto", "merge"}:
        merge = session.scalar(select(GraphMerge).where(GraphMerge.workspace_id == workspace_id, GraphMerge.project_id == project_id, GraphMerge.merge_key == key, GraphMerge.status == "active"))
        if merge is not None:
            if version_number is None:
                merge_version = session.scalar(select(GraphMergeVersion).where(GraphMergeVersion.id == merge.current_version_id, GraphMergeVersion.status == GRAPH_MERGE_VERSION_PUBLISHED))
            else:
                merge_version = session.scalar(select(GraphMergeVersion).where(GraphMergeVersion.graph_merge_id == merge.id, GraphMergeVersion.version == int(version_number), GraphMergeVersion.status == GRAPH_MERGE_VERSION_PUBLISHED))
            if merge_version is None:
                raise HTTPException(status_code=404, detail={"code": "graph_not_found", "message": "published merge graph version not found"})
            inputs = list(session.scalars(select(GraphMergeInput.input_resource_id).where(GraphMergeInput.graph_merge_version_id == merge_version.id)))
            if not _runtime_resource_rows_allowed(principal, inputs):
                raise HTTPException(status_code=404, detail={"code": "graph_not_found", "message": "published graph not found"})
            return "merge", merge, merge_version
    raise HTTPException(status_code=404, detail={"code": "graph_not_found", "message": "published graph not found"})


def _runtime_graph_query(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any]) -> dict[str, Any]:
    require_scope(principal, "project:query")
    require_scope(principal, "resource:read")
    kind, graph, version = _runtime_resolve_graph_target(session, workspace_id, project_id, principal, args)
    limit = _runtime_limit(args.get("limit"), default=50, max_value=100)
    offset = _runtime_cursor(args.get("cursor"))
    query = str(args.get("query") or "").strip().lower()
    node_type = args.get("node_type")
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    freshness_resources: list[dict[str, Any]] = []
    if kind == "resource":
        resource_graph = cast(Graph, graph)
        resource_version = cast(GraphVersion, version)
        predicates = [GraphNode.workspace_id == workspace_id, GraphNode.project_id == project_id, GraphNode.resource_id == resource_version.resource_id, GraphNode.source_snapshot_id == resource_version.source_snapshot_id]
        if node_type:
            predicates.append(GraphNode.node_type == str(node_type))
        resource_node_rows = list(session.scalars(select(GraphNode).where(*predicates).order_by(GraphNode.label.asc()).offset(offset).limit(limit + 1)))
        for resource_node in resource_node_rows[:limit]:
            if query and query not in resource_node.label.lower() and query not in resource_node.node_key.lower() and query not in (resource_node.path or "").lower():
                continue
            nodes.append({"key": resource_node.node_key, "label": resource_node.label, "node_type": resource_node.node_type, "path": resource_node.path, "origin": {"resource_id": str(resource_node.resource_id), "source_snapshot_id": str(resource_node.source_snapshot_id), "path": resource_node.path}})
        node_ids = [resource_node.id for resource_node in resource_node_rows[:limit]]
        resource_edge_rows = list(session.scalars(select(GraphEdge).where(GraphEdge.source_node_id.in_(node_ids)).limit(limit))) if node_ids else []
        for resource_edge in resource_edge_rows:
            edges.append({"source": str(resource_edge.source_node_id), "target": str(resource_edge.target_node_id), "edge_type": resource_edge.edge_type, "origin": {"resource_id": str(resource_edge.resource_id), "source_snapshot_id": str(resource_edge.source_snapshot_id)}})
        resource = session.scalar(select(Resource).where(Resource.id == resource_version.resource_id))
        if resource:
            freshness_resources.append(_runtime_resource_freshness(session, resource, resource_version.source_snapshot_id))
        next_cursor = str(offset + limit) if len(resource_node_rows) > limit else None
        graph_key = resource_graph.graph_key
        graph_title = resource_graph.title
    else:
        merge_graph = cast(GraphMerge, graph)
        merge_version = cast(GraphMergeVersion, version)
        predicates = [GraphMergeNode.graph_merge_version_id == merge_version.id]
        if node_type:
            predicates.append(GraphMergeNode.node_type == str(node_type))
        merge_node_rows = list(session.scalars(select(GraphMergeNode).where(*predicates).order_by(GraphMergeNode.display_label.asc()).offset(offset).limit(limit + 1)))
        for merge_node in merge_node_rows[:limit]:
            if query and query not in merge_node.display_label.lower() and query not in merge_node.merged_node_key.lower() and query not in (merge_node.path or "").lower():
                continue
            origin = (merge_node.origin_json or [{}])[0] if isinstance(merge_node.origin_json, list) and merge_node.origin_json else {}
            nodes.append({"key": merge_node.merged_node_key, "label": merge_node.display_label, "node_type": merge_node.node_type, "path": merge_node.path, "origin": origin})
        merge_edge_rows = list(session.scalars(select(GraphMergeEdge).where(GraphMergeEdge.graph_merge_version_id == merge_version.id).order_by(GraphMergeEdge.edge_type.asc()).limit(limit)))
        for merge_edge in merge_edge_rows:
            origin = (merge_edge.origin_json or [{}])[0] if isinstance(merge_edge.origin_json, list) and merge_edge.origin_json else {}
            edges.append({"source": merge_edge.source_merged_node_key, "target": merge_edge.target_merged_node_key, "edge_type": merge_edge.edge_type, "origin": origin})
        inputs = session.execute(select(GraphMergeInput, Resource).join(Resource, GraphMergeInput.input_resource_id == Resource.id).where(GraphMergeInput.graph_merge_version_id == merge_version.id)).all()
        freshness_resources = [_runtime_resource_freshness(session, resource, input_row.input_source_snapshot_id) for input_row, resource in inputs]
        next_cursor = str(offset + limit) if len(merge_node_rows) > limit else None
        graph_key = merge_graph.merge_key
        graph_title = merge_graph.title
    return {"graph": {"key": graph_key, "kind": kind, "version": version.version, "status": version.status, "title": graph_title}, "freshness": _runtime_freshness("current", resources=freshness_resources, graph={"graph_key": graph_key, "kind": kind, "version": version.version, "status": version.status}), "nodes": nodes, "edges": edges, "next_cursor": next_cursor, "truncated": next_cursor is not None}


def _runtime_graph_path(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any]) -> dict[str, Any]:
    require_scope(principal, "project:query")
    require_scope(principal, "resource:read")
    kind, graph, version = _runtime_resolve_graph_target(session, workspace_id, project_id, principal, args)
    if kind != "merge":
        raise HTTPException(status_code=422, detail={"code": "unsupported_graph_path", "message": "resource graph paths are not supported by MCP F; use graph_query"})
    merge_graph = cast(GraphMerge, graph)
    merge_version = cast(GraphMergeVersion, version)
    from_key = args.get("from_node_key")
    to_key = args.get("to_node_key")
    if not from_key and args.get("from_label"):
        matches = list(session.scalars(select(GraphMergeNode).where(GraphMergeNode.graph_merge_version_id == merge_version.id, GraphMergeNode.display_label.ilike(f"%{args['from_label']}%")).limit(11)))
        if len(matches) != 1:
            raise HTTPException(status_code=409, detail={"code": "ambiguous_node", "candidates": [{"key": row.merged_node_key, "label": row.display_label, "path": row.path} for row in matches[:10]]})
        from_key = matches[0].merged_node_key
    if not to_key and args.get("to_label"):
        matches = list(session.scalars(select(GraphMergeNode).where(GraphMergeNode.graph_merge_version_id == merge_version.id, GraphMergeNode.display_label.ilike(f"%{args['to_label']}%")).limit(11)))
        if len(matches) != 1:
            raise HTTPException(status_code=409, detail={"code": "ambiguous_node", "candidates": [{"key": row.merged_node_key, "label": row.display_label, "path": row.path} for row in matches[:10]]})
        to_key = matches[0].merged_node_key
    if not from_key or not to_key:
        raise HTTPException(status_code=422, detail={"code": "missing_nodes", "message": "from/to node key or label are required"})
    path_result = find_path(session, merge_version, str(from_key), str(to_key), min(int(args.get("max_depth") or 4), 8))
    return {"graph": {"key": merge_graph.merge_key, "kind": "merge", "version": merge_version.version, "status": merge_version.status}, "freshness": _runtime_freshness("current", graph={"graph_key": merge_graph.merge_key, "kind": "merge", "version": merge_version.version, "status": merge_version.status}), **path_result, "truncated": False}


def _runtime_remote_args(args: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    return {key: value for key, value in args.items() if key in allowed and value is not None}


def _runtime_has_scope(principal: Principal, scope: str) -> bool:
    scopes = principal.scopes
    return "*" in scopes or scope in scopes


def _runtime_lookup(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=422, detail={"code": "invalid_query", "message": "query is required"})
    search_in = str(args.get("search_in") or args.get("kind") or "all")
    base_args = _runtime_args_with_resource_ref(session, workspace_id, project_id, principal, args, single=False)
    if search_in == "docs":
        return {"mode": "docs", "docs": _runtime_search(session, workspace_id, project_id, principal, base_args)}
    if search_in == "code":
        code_args = _runtime_remote_args(base_args, {"query", "resource_ids", "top_k", "cursor"})
        return {"mode": "code", "code": jsonable_encoder(remote_search_code(workspace_id, project_id, RemoteSearchCodeRequest(**code_args), principal, session))}
    if search_in == "grep":
        grep_args = _runtime_remote_args(base_args, {"pattern", "resource_ids", "path_glob", "max_matches", "cursor", "regex", "context_lines"})
        grep_args.setdefault("pattern", query)
        return {"mode": "grep", "grep": jsonable_encoder(remote_grep_code(workspace_id, project_id, RemoteGrepCodeRequest(**grep_args), principal, session))}
    if search_in == "symbols":
        symbol_args = _runtime_remote_args(base_args, {"name", "kind", "resource_ids", "top_k"})
        symbol_args.setdefault("name", query)
        return {"mode": "symbols", "symbols": jsonable_encoder(remote_find_symbol(workspace_id, project_id, RemoteFindSymbolRequest(**symbol_args), principal, session))}
    if search_in != "all":
        raise HTTPException(status_code=422, detail={"code": "invalid_lookup_mode", "message": "search_in must be one of all, docs, code, grep, symbols"})
    docs = _runtime_search(session, workspace_id, project_id, principal, base_args)
    if not _runtime_has_scope(principal, "code:read"):
        return {
            "mode": "all",
            "docs": docs,
            "code": None,
            "symbols": None,
            "warnings": [
                {
                    "code": "code_read_not_authorized",
                    "message": "Token lacks code:read; returning docs results only. Use search_in='docs' for docs-only lookup or mint a read-code runtime token for code/symbols.",
                }
            ],
            "next_steps": [{"name": "sourcebrief.read_section", "reason": "Read a cited docs hit exactly before making claims."}],
        }
    code_args = _runtime_remote_args(base_args, {"query", "resource_ids", "top_k", "cursor"})
    code_args.setdefault("top_k", min(int(base_args.get("top_k") or 5), 10))
    symbols_args = _runtime_remote_args(base_args, {"name", "kind", "resource_ids", "top_k"})
    symbols_args.setdefault("name", query)
    symbols_args.setdefault("top_k", 10)
    warnings: list[dict[str, Any]] = []
    code: dict[str, Any] | None = None
    try:
        code = jsonable_encoder(remote_search_code(workspace_id, project_id, RemoteSearchCodeRequest(**code_args), principal, session))
    except HTTPException as exc:
        warning = _lookup_soft_warning(exc, facet="code")
        if warning is None:
            raise
        warnings.append(warning)
    symbols = jsonable_encoder(remote_find_symbol(workspace_id, project_id, RemoteFindSymbolRequest(**symbols_args), principal, session))
    next_steps = [
        {"name": "sourcebrief.read_section", "reason": "Read a cited docs hit exactly before making claims."},
        {"name": "sourcebrief.read_file", "reason": "Read a code hit exactly by resource_ref/resource_id and path."},
    ]
    if warnings:
        next_steps.insert(
            1,
            {
                "name": "sourcebrief.grep_code",
                "reason": "For large repos, retry code drilldown with a cited path_glob instead of broad search.",
            },
        )
    response: dict[str, Any] = {
        "mode": "all",
        "docs": docs,
        "code": code,
        "symbols": symbols,
        "next_steps": next_steps,
    }
    if warnings:
        response["warnings"] = warnings
    return response


def _runtime_discover(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any]) -> dict[str, Any]:
    return {
        "sources": _runtime_list_sources(session, workspace_id, project_id, principal, args),
        "architecture": _runtime_graph_overview(session, workspace_id, project_id, principal, {"max_resources": args.get("max_resources") or 20, "max_items": args.get("max_items") or 20}),
        "next_steps": [
            {"name": "sourcebrief.ask", "reason": "Ask a cited project question after choosing a source scope."},
            {"name": "sourcebrief.lookup", "reason": "Search docs/code/symbols with an optional human resource_ref."},
        ],
    }


def _mcp_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "sourcebrief.ask",
            "description": "Golden-path answer: ask a project question and receive a synthesized cited answer, cited context, and suggested next tool calls. Code symbols are returned only when the caller has code:read; context-only tokens receive cited context plus an omission warning. Set include_answer=false to get the raw context packet without synthesis.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "runtime": {"type": "string", "enum": ["api", "hermes", "claude", "codex", "cursor"]},
                    "profile": {"type": "string", "enum": sorted(RETRIEVAL_PROFILES)},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
                    "resource_ids": {"type": "array", "items": {"type": "string"}},
                    "resource_ref": {"type": "string"}, "resource_refs": {"type": "array", "items": {"type": "string"}},
                    "context_pack_key": {"type": "string"},
                    "context_pack_version": {"type": "integer", "minimum": 1},
                    "max_chars": {"type": "integer", "minimum": 1000, "maximum": 50000},
                    "include_code_symbols": {"type": "boolean"},
                    "include_answer": {"type": "boolean"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "sourcebrief.discover",
            "description": "Golden-path discovery: list authorized sources and return a compact architecture/graph overview before choosing lower-level tools.",
            "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "resource_type": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}, "cursor": {"type": "string"}, "max_resources": {"type": "integer", "minimum": 1, "maximum": 50}, "max_items": {"type": "integer", "minimum": 1, "maximum": 50}}},
        },
        {
            "name": "sourcebrief.lookup",
            "description": "Golden-path lookup router for docs, code, grep, and symbols; accepts optional human resource_ref for unambiguous source selection.",
            "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "search_in": {"type": "string", "enum": ["all", "docs", "code", "grep", "symbols"]}, "resource_ref": {"type": "string"}, "resource_refs": {"type": "array", "items": {"type": "string"}}, "resource_ids": {"type": "array", "items": {"type": "string"}}, "top_k": {"type": "integer", "minimum": 1, "maximum": 50}, "path_glob": {"type": "string"}, "regex": {"type": "boolean"}}, "required": ["query"]},
        },
        {
            "name": "sourcebrief.get_context_pack",
            "description": "Fetch a published SourceBrief context pack with bounded source/artifact/graph inventory and freshness metadata.",
            "inputSchema": {"type": "object", "properties": {"pack_key": {"type": "string"}, "version": {"type": "integer", "minimum": 1}, "include_artifacts": {"type": "boolean"}, "include_coverage": {"type": "boolean"}, "include_graph_inventory": {"type": "boolean"}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}, "cursor": {"type": "string"}}},
        },
        {
            "name": "sourcebrief.list_sources",
            "description": "List authorized human source names/resources so agents do not need UUID-first workflows.",
            "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "resource_type": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}, "cursor": {"type": "string"}}},
        },
        {
            "name": "sourcebrief.get_resource_map",
            "description": "Fetch an approved resource-map artifact by resource id, human resource reference, or artifact id with canonical read_section locators.",
            "inputSchema": {"type": "object", "properties": {"resource_id": {"type": "string"}, "resource_ref": {"type": "string"}, "resource_refs": {"type": "array", "items": {"type": "string"}}, "artifact_id": {"type": "string"}, "source_snapshot_id": {"type": "string"}, "include_sources": {"type": "boolean"}, "include_citations": {"type": "boolean"}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}, "cursor": {"type": "string"}}},
        },
        {
            "name": "sourcebrief.search",
            "description": "Search indexed sections/artifacts with cited canonical locators for read_section.",
            "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "resource_ids": {"type": "array", "items": {"type": "string"}}, "resource_ref": {"type": "string"}, "resource_refs": {"type": "array", "items": {"type": "string"}}, "context_pack_key": {"type": "string"}, "context_pack_version": {"type": "integer", "minimum": 1}, "profile": {"type": "string", "enum": sorted(RETRIEVAL_PROFILES)}, "top_k": {"type": "integer", "minimum": 1, "maximum": 50}, "include_code_symbols": {"type": "boolean"}}, "required": ["query"]},
        },
        {
            "name": "sourcebrief.read_section",
            "description": "Read exact retained section evidence from a canonical locator returned by search/resource-map/context-pack tools.",
            "inputSchema": {"type": "object", "properties": {"resource_id": {"type": "string"}, "resource_ref": {"type": "string"}, "resource_refs": {"type": "array", "items": {"type": "string"}}, "source_snapshot_id": {"type": "string"}, "snapshot_section_id": {"type": "string"}, "context_artifact_id": {"type": "string"}, "context_artifact_citation_id": {"type": "string"}, "context_pack_key": {"type": "string"}, "context_pack_version": {"type": "integer"}, "path": {"type": "string"}, "heading": {"type": "string"}, "content_hash": {"type": "string"}, "start_line": {"type": "integer", "minimum": 1}, "end_line": {"type": "integer", "minimum": 1}, "allow_current_fallback": {"type": "boolean"}}, "allOf": [{"anyOf": [{"required": ["resource_id"]}, {"required": ["resource_ref"]}]}, {"anyOf": [{"required": ["context_artifact_citation_id"]}, {"required": ["snapshot_section_id", "source_snapshot_id"]}, {"required": ["source_snapshot_id", "path", "content_hash"]}]}]},
        },
        {
            "name": "sourcebrief.get_architecture",
            "description": "Return a compact permission-scoped architecture and graph overview before ad hoc search.",
            "inputSchema": {"type": "object", "properties": {"max_resources": {"type": "integer", "minimum": 1, "maximum": 50}, "max_items": {"type": "integer", "minimum": 1, "maximum": 50}}},
        },
        {
            "name": "sourcebrief.get_graph_inventory",
            "description": "Discover authorized published resource graphs and merge graphs by human key/title.",
            "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "kind": {"type": "string", "enum": ["resource", "merge", "all"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}, "cursor": {"type": "string"}}},
        },
        {
            "name": "sourcebrief.graph_query",
            "description": "Inspect a published resource or merge graph by human graph key with provenance/freshness.",
            "inputSchema": {"type": "object", "properties": {"graph_key": {"type": "string"}, "graph_kind": {"type": "string", "enum": ["resource", "merge", "auto"]}, "version": {"type": "integer", "minimum": 1}, "query": {"type": "string"}, "node_type": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}, "cursor": {"type": "string"}}, "required": ["graph_key"]},
        },
        {
            "name": "sourcebrief.graph_path",
            "description": "Find a bounded path through a published merge graph by node keys or human labels.",
            "inputSchema": {"type": "object", "properties": {"graph_key": {"type": "string"}, "graph_kind": {"type": "string", "enum": ["merge", "auto"]}, "version": {"type": "integer", "minimum": 1}, "from_node_key": {"type": "string"}, "to_node_key": {"type": "string"}, "from_label": {"type": "string"}, "to_label": {"type": "string"}, "max_depth": {"type": "integer", "minimum": 1, "maximum": 8}}, "required": ["graph_key"]},
        },
        {
            "name": "sourcebrief.get_agent_context",
            "description": "Return permission-scoped cited context for a SourceBrief project. By default the packet includes an extractive cited answer; set include_answer=false for raw context-only behavior. Code symbols require code:read and are omitted with a structured warning for context-only tokens.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "runtime": {"type": "string", "enum": ["api", "hermes", "claude", "codex", "cursor"]},
                    "profile": {"type": "string", "enum": sorted(RETRIEVAL_PROFILES)},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
                    "resource_ids": {"type": "array", "items": {"type": "string"}},
                    "resource_ref": {"type": "string"}, "resource_refs": {"type": "array", "items": {"type": "string"}},
                    "context_pack_key": {"type": "string"},
                    "context_pack_version": {"type": "integer", "minimum": 1},
                    "max_chars": {"type": "integer", "minimum": 1000, "maximum": 50000},
                    "include_code_symbols": {"type": "boolean"},
                    "include_answer": {"type": "boolean"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "sourcebrief.search_code",
            "description": "Search indexed snapshot files without local repository access.",
            "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "resource_ids": {"type": "array", "items": {"type": "string"}}, "resource_ref": {"type": "string"}, "resource_refs": {"type": "array", "items": {"type": "string"}}, "top_k": {"type": "integer", "minimum": 1, "maximum": 50}}, "required": ["query"]},
        },
        {
            "name": "sourcebrief.grep_code",
            "description": "Run bounded grep over indexed snapshot files without local repository access.",
            "inputSchema": {"type": "object", "properties": {"pattern": {"type": "string"}, "resource_ids": {"type": "array", "items": {"type": "string"}}, "resource_ref": {"type": "string"}, "resource_refs": {"type": "array", "items": {"type": "string"}}, "path_glob": {"type": "string"}, "max_matches": {"type": "integer", "minimum": 1, "maximum": 100}, "regex": {"type": "boolean"}}, "required": ["pattern"]},
        },
        {
            "name": "sourcebrief.read_file",
            "description": "Read a line range from an indexed repo-relative file snapshot.",
            "inputSchema": {"type": "object", "properties": {"resource_id": {"type": "string"}, "resource_ref": {"type": "string"}, "resource_refs": {"type": "array", "items": {"type": "string"}}, "path": {"type": "string"}, "start_line": {"type": "integer", "minimum": 1}, "end_line": {"type": "integer", "minimum": 1}}, "required": ["path"], "anyOf": [{"required": ["resource_id"]}, {"required": ["resource_ref"]}]},
        },
        {
            "name": "sourcebrief.find_symbol",
            "description": "Find indexed code symbols by name and optional kind.",
            "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "kind": {"type": "string"}, "resource_ids": {"type": "array", "items": {"type": "string"}}, "resource_ref": {"type": "string"}, "resource_refs": {"type": "array", "items": {"type": "string"}}, "top_k": {"type": "integer", "minimum": 1, "maximum": 100}}, "required": ["name"]},
        },
        {
            "name": "sourcebrief.generate_skill_pack",
            "description": "Generate a project-specific Hermes skill pack from a published context pack. This creates server-side preview/download artifacts only; it never writes local runtime files.",
            "inputSchema": {"type": "object", "properties": {"pack_key": {"type": "string"}, "version": {"type": "integer", "minimum": 1}, "title": {"type": "string"}, "summary": {"type": "string"}, "approve_comment": {"type": "string"}}},
        },
        {
            "name": "sourcebrief.get_rpc_spec",
            "description": "Return the exact HTTP/JSON-RPC batch code-access schema, auth requirements, budgets, and failure-mode contract. MCP remains the default agent orchestration layer; this is for SDK/high-throughput clients.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "sourcebrief.get_runtime_help",
            "description": "Return CLI-first instructions for installing generated SourceBrief skill packs and MCP runtime config locally.",
            "inputSchema": {"type": "object", "properties": {"target": {"type": "string", "enum": ["hermes"]}}},
        },
        {
            "name": "sourcebrief.generate_patch",
            "description": "Generate a patch proposal from authorized indexed snapshot files. Opt-in only; does not mutate a source repo.",
            "inputSchema": {"type": "object", "properties": {"resource_id": {"type": "string"}, "scope": {"type": "string"}, "files": {"type": "array", "items": {"type": "object"}}, "source_branch": {"type": "string"}, "target_branch": {"type": "string"}, "base_commit": {"type": "string"}}, "required": ["resource_id", "scope", "files"]},
        },
        {
            "name": "sourcebrief.open_pr",
            "description": "Record explicit approval for opening a PR from a generated patch. Opt-in approval record only; source-control mutation is handled by a separate approved integration.",
            "inputSchema": {"type": "object", "properties": {"patch_proposal_id": {"type": "string"}, "source_branch": {"type": "string"}, "target_branch": {"type": "string"}, "approval_note": {"type": "string"}, "github_pr_url": {"type": "string"}}, "required": ["patch_proposal_id", "source_branch", "target_branch", "approval_note"]},
        },
    ]


def _runtime_generate_skill_pack(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: Mapping[str, Any],
) -> dict[str, Any]:
    pack_key = str(args.get("pack_key") or "default")
    version_number = int(args["version"]) if args.get("version") is not None else _resolve_pack_version(session, workspace_id, project_id, pack_key, "current").version
    payload = SkillExportGenerateRequest(
        title=str(args.get("title") or "SourceBrief runtime skill"),
        summary=str(args["summary"]) if args.get("summary") is not None else None,
    )
    export = generate_skill_export(workspace_id, project_id, pack_key, version_number, payload, principal, session)
    approve_comment = args.get("approve_comment")
    if approve_comment:
        export = approve_skill_export(
            workspace_id,
            project_id,
            export.id,
            SkillExportReviewRequest(comment=str(approve_comment)),
            principal,
            session,
        )
    export_dict = jsonable_encoder(export)
    download_path = f"/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export.id}/download.zip"
    return {
        "status": export.status,
        "skill_export": export_dict,
        "download_path": download_path,
        "download_available": export.status == SKILL_EXPORT_STATUS_APPROVED,
        "local_install": {
            "dry_run": "sourcebrief skill install --package <package-dir-or-zip> --target hermes --dry-run",
            "apply": "sourcebrief skill install --package <package-dir-or-zip> --target hermes --apply",
            "uninstall": "sourcebrief skill uninstall --receipt <receipt.json>",
        },
        "mutation_boundary": "MCP generation never writes local runtime files; install is a separate local CLI action.",
    }


def _runtime_help(args: Mapping[str, Any]) -> dict[str, Any]:
    target = str(args.get("target") or "hermes")
    if target != "hermes":
        raise HTTPException(status_code=422, detail="runtime help currently supports target=hermes")
    return {
        "target": "hermes",
        "flow": [
            "Generate and approve a project skill pack from a published context pack.",
            "Download or export the package locally; inspect SKILL.md, manifest.json, and references/.",
            "Run sourcebrief skill install --package <package> --target hermes --dry-run.",
            "Apply only with --apply; the installer writes a receipt without plaintext tokens.",
            "Rollback with sourcebrief skill uninstall --receipt <receipt.json>.",
        ],
        "commands": {
            "export": "sourcebrief skill export --workspace \"<name>\" --project \"<name>\" --pack-key default --approve-comment \"Approved\" --out ./sourcebrief-skill",
            "dry_run": "sourcebrief skill install --package ./sourcebrief-skill --target hermes --dry-run",
            "apply": "sourcebrief skill install --package ./sourcebrief-skill --target hermes --apply",
            "uninstall": "sourcebrief skill uninstall --receipt <receipt.json>",
        },
        "boundaries": [
            "The remote MCP server never mutates local files.",
            "Tokens stay in environment variables/runtime secret managers and are not embedded in the skill package or receipt.",
            "Non-default Hermes profiles require explicit --profile or --skills-dir.",
        ],
    }


@app.post("/mcp/{workspace_id}/{project_id}", response_model=None)
async def mcp_endpoint(
    workspace_id: UUID,
    project_id: UUID,
    request: Request,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> dict | Response:
    """Minimal central MCP-compatible JSON-RPC endpoint for project context.

    This intentionally exposes one typed operation; production/external actions
    remain outside repo agents and must use dedicated MCP tools.
    """
    _require_project_access(session, workspace_id, project_id, principal)
    try:
        body = await request.json()
    except Exception:
        return _json_rpc_error(None, -32700, "parse error")
    if not isinstance(body, dict):
        return _json_rpc_error(None, -32600, "invalid request")
    rpc_id = body.get("id")
    has_id = "id" in body
    if body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
        return _json_rpc_error(rpc_id if has_id else None, -32600, "invalid request")
    method = body["method"]
    if not has_id:
        # JSON-RPC notifications do not receive responses. MCP clients commonly
        # send notifications/initialized after initialize.
        return Response(status_code=204)
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "sourcebrief", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            },
        }
    if method == "tools/list":
        priority = {
            "sourcebrief.ask": 0,
            "sourcebrief.discover": 1,
            "sourcebrief.lookup": 2,
            "sourcebrief.get_agent_context": 3,
            "sourcebrief.list_sources": 4,
            "sourcebrief.get_architecture": 5,
            "sourcebrief.get_context_pack": 6,
            "sourcebrief.search": 7,
            "sourcebrief.read_section": 8,
            "sourcebrief.read_file": 9,
            "sourcebrief.search_code": 10,
            "sourcebrief.grep_code": 11,
            "sourcebrief.find_symbol": 12,
            "sourcebrief.get_resource_map": 13,
            "sourcebrief.get_graph_inventory": 14,
            "sourcebrief.graph_query": 15,
            "sourcebrief.graph_path": 16,
            "sourcebrief.generate_skill_pack": 20,
            "sourcebrief.get_rpc_spec": 21,
            "sourcebrief.get_runtime_help": 22,
            "sourcebrief.generate_patch": 30,
            "sourcebrief.open_pr": 31,
        }
        tools = sorted(
            _mcp_tools(),
            key=lambda tool: (priority.get(str(tool.get("name")), 50), str(tool.get("name"))),
        )
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": tools}}
    if method == "tools/call":
        params = body.get("params", {})
        if not isinstance(params, dict):
            return _json_rpc_error(rpc_id, -32602, "invalid params")
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _json_rpc_error(rpc_id, -32602, "invalid params")
        # Accept legacy contextsmith.* calls for existing agent configs, but list only sourcebrief.* names.
        if isinstance(tool_name, str) and tool_name.startswith("contextsmith."):
            tool_name = "sourcebrief." + tool_name[len("contextsmith."):]
        result: Any
        try:
            if tool_name == "sourcebrief.ask":
                payload = AgentContextRequest(**_runtime_args_with_resource_ref(session, workspace_id, project_id, principal, arguments, single=False))
                result = agent_context(workspace_id, project_id, payload, principal, session)
            elif tool_name == "sourcebrief.discover":
                result = _runtime_discover(session, workspace_id, project_id, principal, arguments)
            elif tool_name == "sourcebrief.lookup":
                result = _runtime_lookup(session, workspace_id, project_id, principal, arguments)
            elif tool_name == "sourcebrief.get_context_pack":
                result = _runtime_get_context_pack(session, workspace_id, project_id, principal, arguments)
            elif tool_name == "sourcebrief.list_sources":
                result = _runtime_list_sources(session, workspace_id, project_id, principal, arguments)
            elif tool_name == "sourcebrief.get_resource_map":
                result = _runtime_get_resource_map(session, workspace_id, project_id, principal, arguments)
            elif tool_name == "sourcebrief.search":
                result = _runtime_search(session, workspace_id, project_id, principal, _runtime_args_with_resource_ref(session, workspace_id, project_id, principal, arguments, single=False))
            elif tool_name == "sourcebrief.read_section":
                result = _runtime_read_section(session, workspace_id, project_id, principal, _runtime_args_with_resource_ref(session, workspace_id, project_id, principal, arguments, single=True))
            elif tool_name == "sourcebrief.get_architecture":
                result = _runtime_graph_overview(session, workspace_id, project_id, principal, arguments)
            elif tool_name == "sourcebrief.get_graph_inventory":
                result = _runtime_get_graph_inventory(session, workspace_id, project_id, principal, arguments)
            elif tool_name == "sourcebrief.graph_query":
                result = _runtime_graph_query(session, workspace_id, project_id, principal, arguments)
            elif tool_name == "sourcebrief.graph_path":
                result = _runtime_graph_path(session, workspace_id, project_id, principal, arguments)
            elif tool_name == "sourcebrief.get_agent_context":
                payload = AgentContextRequest(**_runtime_args_with_resource_ref(session, workspace_id, project_id, principal, arguments, single=False))
                result = agent_context(workspace_id, project_id, payload, principal, session)
            elif tool_name == "sourcebrief.search_code":
                code_args = _runtime_args_with_resource_ref(session, workspace_id, project_id, principal, arguments, single=False)
                result = remote_search_code(workspace_id, project_id, RemoteSearchCodeRequest(**_runtime_remote_args(code_args, {"query", "resource_ids", "top_k", "cursor"})), principal, session)
            elif tool_name == "sourcebrief.grep_code":
                grep_args = _runtime_args_with_resource_ref(session, workspace_id, project_id, principal, arguments, single=False)
                result = remote_grep_code(workspace_id, project_id, RemoteGrepCodeRequest(**_runtime_remote_args(grep_args, {"pattern", "resource_ids", "path_glob", "max_matches", "cursor", "regex", "context_lines"})), principal, session)
            elif tool_name == "sourcebrief.read_file":
                read_args = _runtime_args_with_resource_ref(session, workspace_id, project_id, principal, arguments, single=True)
                result = remote_read_file(workspace_id, project_id, RemoteReadFileRequest(**_runtime_remote_args(read_args, {"resource_id", "path", "start_line", "end_line"})), principal, session)
            elif tool_name == "sourcebrief.find_symbol":
                symbol_args = _runtime_args_with_resource_ref(session, workspace_id, project_id, principal, arguments, single=False)
                result = remote_find_symbol(workspace_id, project_id, RemoteFindSymbolRequest(**_runtime_remote_args(symbol_args, {"name", "kind", "resource_ids", "top_k"})), principal, session)
            elif tool_name == "sourcebrief.generate_skill_pack":
                result = _runtime_generate_skill_pack(session, workspace_id, project_id, principal, arguments)
            elif tool_name == "sourcebrief.get_rpc_spec":
                result = remote_code_rpc_spec(workspace_id, project_id, principal, session)
            elif tool_name == "sourcebrief.get_runtime_help":
                result = _runtime_help(arguments)
            elif tool_name == "sourcebrief.generate_patch":
                result = remote_generate_patch(workspace_id, project_id, GeneratePatchRequest(**arguments), principal, session)
            elif tool_name == "sourcebrief.open_pr":
                result = remote_open_pr(workspace_id, project_id, OpenPrRequest(**arguments), principal, session)
            else:
                return _json_rpc_error(rpc_id, -32601, "unknown tool")
        except ValidationError as exc:
            return _json_rpc_error(rpc_id, -32602, f"invalid params: {exc.errors()[0]['msg']}")
        except HTTPException as exc:
            return _mcp_tool_error(rpc_id, exc.status_code, exc.detail)
        except (TypeError, ValueError) as exc:
            return _mcp_tool_error(rpc_id, 422, {"code": "invalid_params", "message": str(exc)})
        return _mcp_tool_result(rpc_id, result)
    return _json_rpc_error(rpc_id, -32601, "method not found")


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/context-packets",
    response_model=ContextPacketRead,
    status_code=201,
)
def create_context_packet(
    workspace_id: UUID,
    project_id: UUID,
    payload: ContextPacketRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ContextPacketRead:
    """Build a cited context packet through permission-scoped hybrid retrieval."""
    if payload.mode != "hybrid":
        raise HTTPException(status_code=422, detail="only hybrid context packets are supported")
    user = principal.user
    require_scope(principal, "project:query")
    resource_ids = _effective_resource_ids(principal, payload.resource_ids)
    payload = payload.model_copy(update={"resource_ids": resource_ids})
    _require_project_access(session, workspace_id, project_id, principal)

    retrieval_profile = normalize_retrieval_profile(payload.profile)
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
        actor_user_id=user.id,
        query=payload.query,
        mode=payload.mode,
        top_k=payload.top_k,
        provider=embedding_config.provider,
        model=embedding_config.model,
        status="running",
        meta={
            "resource_ids": [str(rid) for rid in payload.resource_ids or []],
            "retrieval_profile": retrieval_profile.name,
            **vector_diagnostics,
        },
    )
    session.add(query_run)
    session.commit()
    query_run_id = query_run.id

    try:
        candidates = retrieve_context_candidates(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            query=payload.query,
            top_k=payload.top_k,
            resource_ids=payload.resource_ids,
            profile=retrieval_profile.name,
        )
        packet = ContextPacket(
            workspace_id=workspace_id,
            project_id=project_id,
            query_run_id=query_run_id,
            status="succeeded",
            item_count=len(candidates),
            meta={"builder": "m3-hybrid-context-packet", "retrieval_profile": retrieval_profile.name},
        )
        session.add(packet)
        session.flush()

        items: list[ContextPacketItemRead] = []
        for rank, candidate in enumerate(candidates, start=1):
            citation = {
                "resource_id": str(candidate.resource_id),
                "snapshot_id": str(candidate.snapshot_id),
                "chunk_id": str(candidate.chunk_id),
                "path": candidate.path,
                "title": candidate.title,
                "ordinal": candidate.ordinal,
                "content_hash": candidate.content_hash,
                "version": candidate.version,
                "version_kind": candidate.version_kind,
                "commit": candidate.snapshot_metadata.get("commit"),
            }
            hit = RetrievalHit(
                workspace_id=workspace_id,
                project_id=project_id,
                query_run_id=query_run_id,
                resource_id=candidate.resource_id,
                source_snapshot_id=candidate.snapshot_id,
                chunk_id=candidate.chunk_id,
                rank=rank,
                lexical_score=candidate.lexical_score,
                vector_score=candidate.vector_score,
                graph_score=candidate.graph_score,
                rerank_score=candidate.rerank_score,
                score=candidate.score,
                meta={"path": candidate.path, "content_hash": candidate.content_hash},
            )
            session.add(hit)
            session.flush()
            snippet = make_snippet(candidate.content)
            session.add(
                ContextPacketItem(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    context_packet_id=packet.id,
                    retrieval_hit_id=hit.id,
                    resource_id=candidate.resource_id,
                    source_snapshot_id=candidate.snapshot_id,
                    chunk_id=candidate.chunk_id,
                    rank=rank,
                    citation=citation,
                    snippet=snippet,
                    score=candidate.score,
                )
            )
            items.append(
                ContextPacketItemRead(
                    rank=rank,
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
                    snippet=snippet,
                    score=candidate.score,
                    lexical_score=candidate.lexical_score,
                    vector_score=candidate.vector_score,
                    graph_score=candidate.graph_score,
                    rerank_score=candidate.rerank_score,
                    citation=citation,
                )
            )

        finished_query_run = session.get(QueryRun, query_run_id)
        if finished_query_run is None:
            raise RuntimeError("query_run disappeared during context packet build")
        finished_query_run.status = "succeeded"
        finished_query_run.hit_count = len(candidates)
        finished_query_run.finished_at = datetime.now(UTC)
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=user.id,
                actor_token_id=principal.token_id,
                action="context_packet.create",
                target_type="context_packet",
                target_id=packet.id,
                meta={"query_run_id": str(query_run_id), "hit_count": len(candidates)},
            )
        )
        session.commit()
        return ContextPacketRead(
            id=packet.id,
            query_run_id=query_run_id,
            workspace_id=workspace_id,
            project_id=project_id,
            query=payload.query,
            mode=payload.mode,
            provider=embedding_config.provider,
            model=embedding_config.model,
            count=len(items),
            diagnostics={
                **vector_diagnostics,
                "retrieval_profile": retrieval_profile.name,
                "retrieval_profile_weights": retrieval_profile_manifest()[retrieval_profile.name]["weights"],
                "rerank_score_range": [0.0, 1.0],
            },
            items=items,
        )
    except HTTPException:
        raise
    except Exception as exc:
        session.rollback()
        failed = session.get(QueryRun, query_run_id)
        if failed is not None:
            failed.status = "failed"
            failed.finished_at = datetime.now(UTC)
            failed.meta = {**(failed.meta or {}), "error": str(exc)[:500]}
            session.add(failed)
            session.commit()
        raise HTTPException(status_code=500, detail="context packet retrieval failed") from exc
