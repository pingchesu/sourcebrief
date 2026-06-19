from __future__ import annotations

import difflib
import hashlib
import io
import json
import os
import re
import subprocess
import zipfile
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID, uuid4

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import ValidationError
from redis import Redis
from rq import Queue
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, load_only

from contextsmith_api.auth import (
    Principal,
    hash_password,
    hash_token,
    new_plaintext_token,
    require_any_scope,
    require_principal,
    require_scope,
    require_workspace_member,
    token_allows_project,
    token_allows_resource,
    verify_password,
)
from contextsmith_api.constants import (
    ACTIVE_INDEX_STATUSES,
    ALLOWED_TOKEN_SCOPES,
    COMMON_AGENT_INSTRUCTION,
    FOLDER_BUNDLE_RESOURCE_TYPES,
    RUNTIME_INSTRUCTIONS,
    UPLOAD_RESOURCE_TYPES,
    URL_RESOURCE_TYPES,
)
from contextsmith_api.remote_code import (
    MAX_SCANNED_BYTES,
    MAX_SCANNED_FILES,
    MAX_SEARCH_LINE_CHARS,
    RemoteCodeError,
    check_scan_budget,
    compile_safe_regex,
    line_range,
    line_window,
    path_matches,
    snippet_for_line,
    validate_path_glob,
    validate_repo_path,
)
from contextsmith_api.resource_map import (
    ARTIFACT_TYPE_RESOURCE_MAP,
    build_resource_map,
    latest_same_hash_artifact,
    next_artifact_revision,
)
from contextsmith_api.retrieval import (
    DEFAULT_RETRIEVAL_PROFILE,
    RETRIEVAL_PROFILES,
    RetrievalCandidate,
    embedding_namespace_diagnostics,
    make_snippet,
    normalize_retrieval_profile,
    retrieval_profile_manifest,
    retrieve_context_candidates,
)
from contextsmith_api.routers import system as system_router
from contextsmith_api.schemas import (
    AgentCardSummaryAcknowledgeRequest,
    AgentCardSummaryListResponse,
    AgentCardSummaryRead,
    AgentContextCitation,
    AgentContextRequest,
    AgentContextResponse,
    AgentFileRead,
    AgentFilesResponse,
    AgentProfileRead,
    AgentProfileUpdate,
    ApiTokenCreate,
    ApiTokenCreateResponse,
    ApiTokenRead,
    ArtifactApprovalRequest,
    ArtifactRejectRequest,
    AuditEventRead,
    AuthLoginRequest,
    AuthLoginResponse,
    AuthLogoutResponse,
    CodeSearchRequest,
    CodeSearchResponse,
    CodeSymbolHit,
    ContextArtifactCitationRead,
    ContextArtifactRead,
    ContextArtifactSourceRead,
    ContextPacketItemRead,
    ContextPacketRead,
    ContextPacketRequest,
    CurrentUserResponse,
    DeletedFileImpactStubRead,
    DueRefreshResponse,
    FolderBundleUploadResponse,
    GeneratePatchRequest,
    GitResourceEnvRead,
    GitResourceEnvUpdate,
    GraphEdgeRead,
    GraphNodeRead,
    GraphRead,
    IndexRunRead,
    ManifestDiffRead,
    ManifestDiffRowRead,
    OpenPrRequest,
    PatchProposalFileRead,
    PatchProposalRead,
    ProjectCreate,
    ProjectRead,
    PrRequestRead,
    PurgeResourceResponse,
    RemoteFindSymbolRequest,
    RemoteFindSymbolResponse,
    RemoteGrepCodeMatch,
    RemoteGrepCodeRequest,
    RemoteGrepCodeResponse,
    RemoteReadFileRequest,
    RemoteReadFileResponse,
    RemoteSearchCodeHit,
    RemoteSearchCodeRequest,
    RemoteSearchCodeResponse,
    RepoAgentBriefRead,
    ResourceCreate,
    ResourceManifestFileRead,
    ResourceManifestRead,
    ResourceRead,
    ResourceReviewItem,
    ResourceReviewRequest,
    ResourceReviewResponse,
    ResourceUpdate,
    ResourceUsageItem,
    ResourceUsageResponse,
    RetrievalEvalRequest,
    RetrievalEvalResponse,
    RetrievalEvalResult,
    RetrievalEvalRunListResponse,
    RetrievalEvalRunRead,
    RetrievalEvalRunSummaryRead,
    RetrievalEvalSummary,
    RetrievalProfileRead,
    RetrievalProfilesResponse,
    SearchHit,
    SearchRequest,
    SearchResponse,
    SectionImpactRead,
    SnapshotRead,
    SnapshotSectionRead,
    SnapshotSectionsRead,
    UserRead,
    WorkspaceCreate,
    WorkspaceMemberCreate,
    WorkspaceMemberRead,
    WorkspaceMemberUpdate,
    WorkspaceRead,
)
from contextsmith_shared.agent_card_auditor import run_agent_card_auditor
from contextsmith_shared.config import get_settings
from contextsmith_shared.db import get_session, get_sessionmaker
from contextsmith_shared.embeddings import current_embedding_config
from contextsmith_shared.lifecycle import compute_next_refresh_at
from contextsmith_shared.models import (
    AgentCardSummary,
    AgentProfile,
    ApiToken,
    AuditEvent,
    CodeSymbol,
    ContextArtifact,
    ContextArtifactCitation,
    ContextArtifactSource,
    ContextPacket,
    ContextPacketItem,
    GraphEdge,
    GraphNode,
    IndexRun,
    PatchProposal,
    Project,
    ProjectMembership,
    PrRequest,
    QueryRun,
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
from contextsmith_worker.bundle_ingest import (
    HARD_MAX_ZIP_UPLOAD_BYTES,
    ZipRejectionError,
    cleanup_stale_uploads,
    validate_upload_staging_dir,
    validate_zip_before_extract,
)
from contextsmith_worker.ingestion import (
    DEFAULT_MAX_DOCUMENT_BYTES,
    DEFAULT_MAX_URL_BYTES,
    HARD_MAX_DOCUMENT_BYTES,
    HARD_MAX_URL_BYTES,
    _work_base,
    parse_positive_int,
    sanitize_remote_url,
    validate_base64_size,
    validate_git_url,
    validate_http_url,
)
from contextsmith_worker.manifest_diff import (
    VALID_CHANGE_TYPES,
    build_manifest_diff,
    page_diff_rows,
)

app = FastAPI(title="ContextSmith API", version="0.1.0")

def _cors_origins() -> list[str]:
    raw = os.getenv("CONTEXTSMITH_CORS_ORIGINS")
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    return ["http://localhost:13000", "http://127.0.0.1:13000"]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(system_router.router)


def run_migrations_if_requested() -> None:
    if os.getenv("CONTEXTSMITH_AUTO_MIGRATE", "false").lower() == "true":
        subprocess.run(["alembic", "upgrade", "head"], check=True)


@app.on_event("startup")
def on_startup() -> None:
    run_migrations_if_requested()
    try:
        _bootstrap_default_admin()
    except IntegrityError:
        # A concurrent API replica may have inserted the same bootstrap rows first.
        # Treat that as benign; the next readiness/login path will observe those rows.
        return


def _sanitize_public_uri(uri: str) -> str:
    return _agent_pack_public_source_uri(sanitize_remote_url(uri))


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
    if settings.admin_password in {"change-me-before-compose-up", "contextsmith-admin"}:
        raise RuntimeError("CONTEXTSMITH_ADMIN_PASSWORD must be changed from the sample/default value before startup")
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
        admin.display_name = admin.display_name or settings.admin_display_name
        admin.password_hash = hash_password(settings.admin_password)
        admin.is_active = True
        admin.is_platform_admin = True

        workspace = session.scalar(select(Workspace).where(Workspace.slug == settings.bootstrap_workspace_slug))
        if workspace is None:
            workspace = Workspace(name=settings.bootstrap_workspace_name, slug=settings.bootstrap_workspace_slug)
            session.add(workspace)
            session.flush()
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
                description="Bootstrap project for the initial ContextSmith console.",
                created_by=admin.id,
            )
            session.add(project)
            session.flush()
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


_SAFE_FILE_SLUG = re.compile(r"[^a-z0-9._-]+")


def _file_slug(value: str) -> str:
    slug = _SAFE_FILE_SLUG.sub("-", value.strip().lower()).strip("-._")
    return slug or "agent"


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


def _agent_file_response(
    session: Session,
    workspace_id: UUID,
    project: Project,
    profile: AgentProfile,
    resources: list[Resource],
) -> AgentFilesResponse:
    repo_resources = [resource for resource in resources if resource.type.lower() == "git"]
    safe_profile_name = _sanitize_metadata_text(profile.name)
    safe_description = _sanitize_metadata_text(profile.description or project.description or "Generated ContextSmith project agent.")
    resource_rows = [
        {
            "id": str(resource.id),
            "name": _sanitize_metadata_text(resource.name),
            "type": resource.type,
            "uri": _agent_pack_public_source_uri(resource.uri),
            "status": resource.status,
            "retrieval_enabled": resource.retrieval_enabled,
            "update_frequency": resource.update_frequency,
            "current_snapshot_id": str(resource.current_snapshot_id) if resource.current_snapshot_id else None,
        }
        for resource in resources
    ]
    manifest = {
        "schema": "contextsmith.agent_manifest.v1",
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
        f"- `{resource.type}` **{_sanitize_metadata_text(resource.name)}** (`{resource.id}`): {_agent_pack_public_source_uri(resource.uri)}; refresh={resource.update_frequency}; snapshot={resource.current_snapshot_id or 'none'}"
        for resource in resources
    ) or "- No resources imported yet."
    repo_skill_files = []
    for resource in repo_resources:
        source_config = resource.source_config or {}
        safe_resource_name = _sanitize_metadata_text(resource.name)
        repo_slug = _file_slug(safe_resource_name)
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
                    f"- URI: `{_agent_pack_public_source_uri(resource.uri)}`\n"
                    f"- Branch/ref: `{_agent_pack_public_text(str(source_config.get('branch') or source_config.get('ref')) if source_config.get('branch') or source_config.get('ref') else None, 'default')}`\n"
                    f"- Current snapshot: `{resource.current_snapshot_id or 'none'}`\n"
                    f"- Update frequency: `{resource.update_frequency}`\n\n"
                    "## How to use\n"
                    "Query ContextSmith with this resource_id as the only resource scope when the task is repo-specific.\n"
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
            path="contextsmith-agent.json",
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
            description="Hermes/Codex project-level skill that routes to ContextSmith.",
            content=(
                "---\n"
                f"name: {_file_slug(safe_profile_name)}\n"
                f"description: Use when answering cross-resource questions for {safe_profile_name}.\n"
                "---\n\n"
                f"# {safe_profile_name}\n\n"
                "Use ContextSmith agent-context for cross-resource answers. Prefer scoped repo-resource queries when the task names a repo/service.\n\n"
                "## Resource routing\n"
                f"{resources_md}\n"
            ),
        ),
        AgentFileRead(
            path=".env.contextsmith.example",
            kind="env-example",
            description="Environment variables for external runtimes and git import workers.",
            content=(
                "CONTEXTSMITH_API_BASE_URL=http://localhost:18000\n"
                f"CONTEXTSMITH_WORKSPACE_ID={workspace_id}\n"
                f"CONTEXTSMITH_PROJECT_ID={project.id}\n"
                "CONTEXTSMITH_API_TOKEN=replace-with-project-query-token\n"
                "# Optional: set this on workers, then reference its name in a repo's Git Env auth_token_env.\n"
                "GITHUB_TOKEN_FOR_CONTEXTSMITH=replace-with-git-token\n"
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


_AGENT_PACK_BLOCKED_TEXT_MARKERS = (
    "file://",
    "/home",
    "/tmp",
    "/qa-fixtures",
    "/var",
    "/opt",
    "/srv",
    "/data",
    "/mnt",
    "/users/",
    "c:\\",
    "\\\\",
)
_AGENT_PACK_PUBLIC_URI_SCHEMES = {"http", "https", "git", "ssh"}
_AGENT_PACK_BLOCKED_SECRET_MARKERS = (
    "x-access-token",
    "access_token",
    "secret-token",
    "api_key",
    "apikey",
    "private_key",
    "client_secret",
)
_AGENT_PACK_SECRET_RE = re.compile(
    r"(x-access-token|access[_-]?token|secret[_-]?token|api[_-]?key|private[_-]?key|client[_-]?secret|bearer\s*[:= ]|gh[pousr]_[A-Za-z0-9_]+)",
    re.IGNORECASE,
)
_AGENT_PACK_HASH_RE = re.compile(r"^[A-Fa-f0-9]{7,64}$")


def _agent_pack_has_blocked_text(value: str) -> bool:
    lower_value = value.lower()
    return any(marker in lower_value for marker in _AGENT_PACK_BLOCKED_TEXT_MARKERS) or any(
        marker in lower_value for marker in _AGENT_PACK_BLOCKED_SECRET_MARKERS
    ) or bool(_AGENT_PACK_SECRET_RE.search(value))


def _agent_pack_public_source_uri(uri: str) -> str:
    compact_uri = " ".join(uri.split())
    lower_uri = compact_uri.lower()
    if _agent_pack_has_blocked_text(lower_uri):
        return "private-or-worker-managed-source"
    try:
        parsed = urlsplit(compact_uri)
    except ValueError:
        return "private-or-worker-managed-source"
    if parsed.scheme and parsed.scheme.lower() not in _AGENT_PACK_PUBLIC_URI_SCHEMES:
        return "private-or-worker-managed-source"
    if not parsed.scheme:
        return "private-or-worker-managed-source"
    netloc = parsed.hostname or parsed.netloc
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def _agent_pack_public_commit(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    compact = " ".join(value.split())
    if _AGENT_PACK_HASH_RE.fullmatch(compact):
        return compact
    return None


def _agent_pack_public_text(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    compact = " ".join(value.split())
    if _agent_pack_has_blocked_text(compact):
        return fallback
    return compact


def _agent_pack_public_description(description: str | None) -> str:
    return _agent_pack_public_text(description, "Generated ContextSmith remote repo agent.")


def _agent_pack_resources(resources: list[Resource], principal: Principal) -> list[Resource]:
    return [
        resource
        for resource in resources
        if resource.archived_at is None and token_allows_resource(principal, resource.id)
    ]


def _agent_pack_snapshot_metadata(session: Session, resources: list[Resource]) -> dict[UUID, dict[str, Any]]:
    snapshot_ids = [resource.current_snapshot_id for resource in resources if resource.current_snapshot_id]
    if not snapshot_ids:
        return {}
    rows = session.execute(
        select(SourceSnapshot.id, SourceSnapshot.meta).where(SourceSnapshot.id.in_(snapshot_ids))
    ).all()
    return {
        snapshot_id: cast(dict[str, Any], metadata if isinstance(metadata, dict) else {})
        for snapshot_id, metadata in rows
    }


def _agent_pack_source(resource: Resource, snapshot_metadata: Mapping[UUID, dict[str, Any]]) -> dict[str, Any]:
    source_config = cast(dict[str, Any], resource.source_config or {})
    metadata = snapshot_metadata.get(resource.current_snapshot_id) if resource.current_snapshot_id else None
    metadata = metadata or {}
    branch = source_config.get("branch") or source_config.get("ref") or metadata.get("branch")
    commit = _agent_pack_public_commit(metadata.get("commit") or metadata.get("version"))
    status = "ready" if resource.current_snapshot_id and resource.status == "active" else resource.status
    return {
        "resource_id": str(resource.id),
        "name": _agent_pack_public_text(resource.name, f"Resource {resource.id}"),
        "type": resource.type,
        "source_uri": _agent_pack_public_source_uri(resource.uri),
        "default_branch": _agent_pack_public_text(str(branch) if branch else None, "default"),
        "indexed_commit": commit,
        "current_snapshot_id": str(resource.current_snapshot_id) if resource.current_snapshot_id else None,
        "status": status,
    }


def _agent_pack_manifest_dict(
    workspace_id: UUID,
    project: Project,
    agent_name: str,
    agent_description: str | None,
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    generated_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    slug = _file_slug(agent_name or project.name)
    public_name = _agent_pack_public_text(agent_name or project.name, f"ContextSmith Project {project.id}")
    return {
        "kind": "contextsmith.repo-agent",
        "version": 1,
        "identity": {
            "name": public_name,
            "slug": slug,
            "description": _agent_pack_public_description(agent_description or project.description),
            "workspace_id": str(workspace_id),
            "project_id": str(project.id),
            "agent_card_url": "${CONTEXTSMITH_API_BASE_URL}" + f"/workspaces/{workspace_id}/projects/{project.id}/repo-agents",
        },
        "contextsmith": {
            "api_base_url": "${CONTEXTSMITH_API_BASE_URL}",
            "mcp_endpoint": "${CONTEXTSMITH_API_BASE_URL}" + f"/mcp/{workspace_id}/{project.id}",
            "agent_context_endpoint": "${CONTEXTSMITH_API_BASE_URL}" + f"/workspaces/{workspace_id}/projects/{project.id}/agent-context",
            "auth": {"type": "bearer", "token_env": "CONTEXTSMITH_TOKEN"},
        },
        "runtime_access": {
            "mode": "remote_only",
            "local_repo_required": False,
            "local_grep_allowed": False,
        },
        "capabilities": {
            "required": ["get_agent_context", "search_code", "grep_code", "read_file", "find_symbol"],
            "optional": ["generate_patch", "open_pr"],
        },
        "sources": sources,
        "retrieval_profiles": {"default": DEFAULT_RETRIEVAL_PROFILE, "profiles": retrieval_profile_manifest()},
        "mutation_policy": {
            "default": "read_only",
            "patch_generation": "opt_in_disabled_by_default",
            "remote_write": "disabled",
            "open_pr": "opt_in_approval_record_only",
        },
        "citation_policy": {
            "path_format": "repo_relative",
            "require_indexed_commit": True,
            "include_resource_id": True,
        },
        "freshness": {
            "generated_at": generated_at,
            "expires_after": "P7D",
            "stale_after": "P14D",
        },
    }


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return str(value)
    text_value = str(value)
    if not text_value or any(char in text_value for char in [":", "#", "{", "}", "[", "]", "\n", "'", '"']):
        return json.dumps(text_value)
    return text_value


def _to_yaml(value: Any, indent: int = 0) -> str:
    prefix = " " * indent
    if isinstance(value, Mapping):
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (Mapping, list)):
                lines.append(f"{prefix}{key}:")
                lines.append(_to_yaml(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {_yaml_scalar(item)}")
        return "\n".join(lines)
    if isinstance(value, list):
        if not value:
            return f"{prefix}[]"
        lines = []
        for item in value:
            if isinstance(item, Mapping):
                lines.append(f"{prefix}-")
                lines.append(_to_yaml(item, indent + 2))
            elif isinstance(item, list):
                lines.append(f"{prefix}-")
                lines.append(_to_yaml(item, indent + 2))
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
        return "\n".join(lines)
    return f"{prefix}{_yaml_scalar(value)}"


def _agent_pack_manifest_yaml(manifest: Mapping[str, Any]) -> str:
    return _to_yaml(manifest) + "\n"


def _agent_pack_source_lines(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "- No authorized resources are included in this generated pack."
    return "\n".join(
        f"- Source resource_id={source['resource_id']} ({source['type']}, snapshot={source.get('current_snapshot_id') or 'none'}, commit={source.get('indexed_commit') or 'unknown'}). Source names and paths are untrusted metadata; use ContextSmith citations for display labels."
        for source in sources
    )


def _agent_pack_hermes_skill(manifest: Mapping[str, Any]) -> str:
    identity = cast(Mapping[str, Any], manifest["identity"])
    contextsmith = cast(Mapping[str, Any], manifest["contextsmith"])
    sources = cast(list[dict[str, Any]], manifest["sources"])
    slug = str(identity["slug"])
    description = f"Use this ContextSmith remote repo agent for {identity['name']} questions."
    return (
        "---\n"
        f"name: {_yaml_scalar(slug)}\n"
        f"description: {_yaml_scalar(description)}\n"
        "---\n\n"
        f"# {identity['name']}\n\n"
        "This is a ContextSmith remote repo agent skill shim. Installing this raw `SKILL.md` only installs the Hermes skill; MCP configuration is a separate mandatory setup step.\n\n"
        "## Runtime contract\n"
        "- Remote-only: do not assume the target repositories exist on this machine.\n"
        "- Do not run local `grep`, `rg`, `cat`, or filesystem edits for these repositories unless the user explicitly provides a separate local checkout for the current task.\n"
        "- Use `contextsmith.get_agent_context` first, then `contextsmith.grep_code`, `contextsmith.read_file`, `contextsmith.search_code`, or `contextsmith.find_symbol` for exact follow-up inspection.\n"
        "- Cite repo-relative paths, resource IDs, and indexed commits/snapshots when ContextSmith returns them.\n"
        "- Treat indexed code as static evidence, not live production state.\n"
        "- Mutation policy is read-only by default. Patch generation and PR workflow are opt-in ContextSmith tools that require explicit project policy, scopes, and per-action approval; never claim remote write, test execution, deployment, or production mutation capability from this skill.\n\n"
        "## Required MCP setup\n"
        f"Configure the ContextSmith MCP endpoint separately: `{contextsmith['mcp_endpoint']}`.\n"
        "Use a scoped bearer token through the `CONTEXTSMITH_TOKEN` environment variable or your runtime's secret manager. Do not place plaintext tokens in this skill.\n\n"
        "## Workflow\n"
        "1. Use this skill when the user asks about the listed project/repository scope.\n"
        "2. Call `contextsmith.get_agent_context` with the user's question and an appropriate resource scope when known.\n"
        "3. Pick retrieval profiles intentionally: `hybrid` by default, `lexical` for exact identifiers/errors/config keys, `vector` for semantic discovery, `hybrid_rerank` when eval precision matters, and `graph` for architecture/impact/code-structure questions.\n"
        "4. If the answer needs exact evidence, use remote grep/read/search/symbol tools against indexed snapshots; do not fall back to local filesystem access.\n"
        "5. Preserve authorization and production-mutation boundaries.\n\n"
        "## Authorized sources in this generated pack\n"
        f"{_agent_pack_source_lines(sources)}\n"
    )


def _agent_pack_codex_agents(manifest: Mapping[str, Any]) -> str:
    identity = cast(Mapping[str, Any], manifest["identity"])
    sources = cast(list[dict[str, Any]], manifest["sources"])
    return (
        f"# {identity['name']} ContextSmith Remote Repo Agent\n\n"
        "You are using a ContextSmith remote repo agent. The checked-out Skill Pack is not the target source repository.\n\n"
        "- Remote-only: do not assume repository files exist in the current working directory.\n"
        "- Do not run local `grep`, `rg`, `cat`, or edits for target repositories unless the user explicitly provides a separate local checkout.\n"
        "- Use `contextsmith.get_agent_context` first, then remote grep/read/search/symbol tools for exact follow-up inspection.\n"
        "- Retrieval profile guide: `hybrid` default, `lexical` exact identifiers/errors/config, `vector` semantic discovery, `hybrid_rerank` eval precision, `graph` architecture/impact.\n"
        "- Cite repo-relative paths, resource IDs, and indexed commits/snapshots from ContextSmith.\n"
        "- Treat indexed code as static evidence, not live production truth.\n"
        "- Read-only by default. Patch generation and PR workflow are opt-in only, require ContextSmith policy/scopes/per-action approval, and do not grant remote write/deploy/test execution by themselves.\n\n"
        "## Authorized sources\n"
        f"{_agent_pack_source_lines(sources)}\n"
    )


def _agent_pack_claude_md(manifest: Mapping[str, Any]) -> str:
    identity = cast(Mapping[str, Any], manifest["identity"])
    sources = cast(list[dict[str, Any]], manifest["sources"])
    return (
        f"# {identity['name']} ContextSmith Remote Repo Agent\n\n"
        "Use ContextSmith MCP for this repo agent. This instruction file is not a source checkout.\n\n"
        "- Remote-only: do not assume target repositories are local.\n"
        "- Do not use local `grep`, `rg`, `cat`, or filesystem edits for the target repos unless the user provides a separate checkout.\n"
        "- Call `contextsmith.get_agent_context` first, then remote grep/read/search/symbol tools for exact follow-up inspection.\n"
        "- Retrieval profile guide: `hybrid` default, `lexical` exact identifiers/errors/config, `vector` semantic discovery, `hybrid_rerank` eval precision, `graph` architecture/impact.\n"
        "- Cite repo-relative paths, indexed commits/snapshots, and resource IDs.\n"
        "- Static indexed evidence is not live production state.\n"
        "- Ask for explicit approval before any mutation; patch generation and PR workflow are opt-in ContextSmith tools and do not grant remote write/deploy/test execution by themselves.\n\n"
        "## Authorized sources\n"
        f"{_agent_pack_source_lines(sources)}\n"
    )


def _agent_pack_mcp_json(manifest: Mapping[str, Any]) -> dict[str, Any]:
    identity = cast(Mapping[str, Any], manifest["identity"])
    contextsmith = cast(Mapping[str, Any], manifest["contextsmith"])
    server_name = f"contextsmith-{identity['slug']}"
    server = {
        "url": contextsmith["mcp_endpoint"],
        "headers": {"Authorization": "Bearer ${CONTEXTSMITH_TOKEN}"},
    }
    return {
        "hermes": {"mcp_servers": {server_name: server}},
        "claude": {"mcpServers": {server_name: server}},
        "codex": {"mcp_servers": {server_name: server}},
    }


def _agent_pack_stable_manifest(manifest: Mapping[str, Any]) -> dict[str, Any]:
    stable = json.loads(json.dumps(manifest, sort_keys=True))
    freshness = stable.get("freshness")
    if isinstance(freshness, dict):
        freshness.pop("generated_at", None)
    return cast(dict[str, Any], stable)


def _agent_pack_manifest_digest(manifest: Mapping[str, Any]) -> str:
    payload = json.dumps(_agent_pack_stable_manifest(manifest), sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode()).hexdigest()


def _agent_pack_readme(manifest: Mapping[str, Any], digest: str) -> str:
    identity = cast(Mapping[str, Any], manifest["identity"])
    contextsmith = cast(Mapping[str, Any], manifest["contextsmith"])
    slug = str(identity["slug"])
    return (
        f"# {identity['name']} Skill Pack\n\n"
        "This Skill Pack installs thin runtime adapters for a ContextSmith remote repo agent. "
        "It does not contain repository source, indexes, embeddings, eval history, or bearer tokens.\n\n"
        "## Files\n"
        "- `contextsmith-agent.yaml` - canonical portable manifest.\n"
        "- `hermes/SKILL.md` - Hermes skill shim.\n"
        "- `codex/AGENTS.md` - Codex instruction adapter.\n"
        "- `claude/CLAUDE.md` - Claude Code instruction adapter.\n"
        "- `mcp.json` - MCP config snippets with token placeholders.\n\n"
        "## Hermes install\n"
        "Publish this pack to GitHub and install the pinned raw skill file, then configure MCP separately:\n\n"
        "```bash\n"
        f"hermes skills install https://raw.githubusercontent.com/<org>/<pack>/<tag-or-sha>/hermes/SKILL.md --name {slug}\n"
        "```\n\n"
        "## Codex\n"
        "Check out or copy this Skill Pack repository, then run Codex in a directory where `codex/AGENTS.md` is loaded. "
        "The checked-out pack is instruction/config material, not the target source repository.\n\n"
        "## Claude\n"
        "Use `claude/CLAUDE.md` as Claude Code instruction context for alpha support. Native Claude skill packaging is not claimed by this pack.\n\n"
        "## MCP and token setup\n"
        f"Configure MCP endpoint `{contextsmith['mcp_endpoint']}` in your runtime. "
        "Set a scoped token through `CONTEXTSMITH_TOKEN` or your runtime secret manager. Do not commit plaintext tokens.\n\n"
        "## Pinning and drift\n"
        f"Manifest digest: `{digest}`. Pin GitHub installs to a tag or commit SHA for reproducibility. "
        "Mutable `main` installs are for development only. Regenerate the pack when the manifest digest changes.\n\n"
        "## Publishing boundary\n"
        "This zip is download-only. Future GitHub PR publishing must require explicit user approval, show the diff, "
        "and keep tokens as environment placeholders only. Patch generation and PR workflow remain opt-in and require explicit policy plus per-action approval records.\n"
    )


def _agent_pack_changelog(manifest: Mapping[str, Any], digest: str) -> str:
    freshness = cast(Mapping[str, Any], manifest["freshness"])
    return (
        "# Changelog\n\n"
        "## Generated Skill Pack\n"
        f"- Generated at: `{freshness['generated_at']}`\n"
        f"- Manifest digest: `{digest}`\n"
        "- Phase 2 export package for GitHub-hosted, pinned runtime installation.\n"
    )


def _agent_pack_golden_questions(manifest: Mapping[str, Any]) -> str:
    identity = cast(Mapping[str, Any], manifest["identity"])
    return (
        "# Placeholder golden evals for this remote repo agent.\n"
        "# Add project-specific questions after observing real usage.\n"
        f"agent: {json.dumps(str(identity['slug']))}\n"
        "questions: []\n"
    )


def _agent_pack_zip_files(manifest: Mapping[str, Any]) -> dict[str, str]:
    digest = _agent_pack_manifest_digest(manifest)
    return {
        "README.md": _agent_pack_readme(manifest, digest),
        "contextsmith-agent.yaml": _agent_pack_manifest_yaml(manifest),
        "mcp.json": json.dumps(_agent_pack_mcp_json(manifest), indent=2, sort_keys=True) + "\n",
        "hermes/SKILL.md": _agent_pack_hermes_skill(manifest),
        "codex/AGENTS.md": _agent_pack_codex_agents(manifest),
        "claude/CLAUDE.md": _agent_pack_claude_md(manifest),
        "evals/golden-questions.yaml": _agent_pack_golden_questions(manifest),
        "CHANGELOG.md": _agent_pack_changelog(manifest, digest),
    }


def _agent_pack_zip_bytes(manifest: Mapping[str, Any]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path, content in _agent_pack_zip_files(manifest).items():
            info = zipfile.ZipInfo(path, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return buffer.getvalue()


def _agent_pack_prepare(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
) -> tuple[Project, dict[str, Any]]:
    require_scope(principal, "project:read")
    project = _require_project_access(session, workspace_id, project_id, principal)
    profile = session.scalar(
        select(AgentProfile).where(
            AgentProfile.workspace_id == workspace_id,
            AgentProfile.project_id == project.id,
        )
    )
    agent_name = profile.name if profile is not None else project.name
    agent_description = profile.description if profile is not None else project.description
    resources = _agent_pack_resources(_current_project_resources(session, workspace_id, project_id), principal)
    snapshot_metadata = _agent_pack_snapshot_metadata(session, resources)
    sources = [_agent_pack_source(resource, snapshot_metadata) for resource in resources]
    return project, _agent_pack_manifest_dict(workspace_id, project, agent_name, agent_description, sources)


def _git_env_read(resource: Resource) -> GitResourceEnvRead:
    source_config = resource.source_config or {}
    return GitResourceEnvRead(
        resource_id=resource.id,
        name=_sanitize_metadata_text(resource.name),
        uri=_sanitize_public_uri(resource.uri),
        branch=source_config.get("branch") or source_config.get("ref"),
        auth_token_env=source_config.get("auth_token_env"),
        clone_timeout=source_config.get("clone_timeout"),
        max_file_bytes=source_config.get("max_file_bytes"),
        max_repo_files=source_config.get("max_repo_files"),
        max_repo_bytes=source_config.get("max_repo_bytes"),
        update_frequency=resource.update_frequency,
        next_refresh_at=resource.next_refresh_at,
    )


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


def _require_project_member(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal) -> Project:
    """Resolve a project and require explicit project membership plus token project scope for mutations."""
    require_workspace_member(session, workspace_id, principal)
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
            _is_local, target = validate_git_url(config.get("url") or uri, allow_local=os.getenv("CONTEXTSMITH_ALLOW_LOCAL_GIT", "false").lower() == "true")
            config["url"] = target if _is_local else sanitize_remote_url(target)
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
    statements = [
        ("resources_current_snapshot", "UPDATE resources SET current_snapshot_id = NULL WHERE id = :resource_id"),
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
    if role in {"owner", "admin"}:
        return sorted(ALLOWED_TOKEN_SCOPES)
    if role == "member":
        return sorted(ALLOWED_TOKEN_SCOPES - {"token:admin"})
    return sorted({"project:read", "project:query", "resource:read", "review:read", "code:read"})


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
    project = _require_project_member(session, workspace_id, project_id, principal)
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


@app.get(
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
    project = _require_project_access(session, workspace_id, project_id, principal)
    profile = _ensure_agent_profile(session, workspace_id, project, principal.user.id)
    resources = [resource for resource in _current_project_resources(session, workspace_id, project_id) if token_allows_resource(principal, resource.id)]
    session.commit()
    return _agent_file_response(session, workspace_id, project, profile, resources)


@app.post(
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
    project = _require_project_member(session, workspace_id, project_id, principal)
    profile = _ensure_agent_profile(session, workspace_id, project, principal.user.id)
    resources = [resource for resource in _current_project_resources(session, workspace_id, project_id) if token_allows_resource(principal, resource.id)]
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
    return _agent_file_response(session, workspace_id, project, profile, resources)


@app.get("/workspaces/{workspace_id}/projects/{project_id}/agent-pack/manifest")
def get_agent_pack_manifest(
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> PlainTextResponse:
    _, manifest = _agent_pack_prepare(session, workspace_id, project_id, principal)
    return PlainTextResponse(_agent_pack_manifest_yaml(manifest), media_type="application/x-yaml")


@app.get("/workspaces/{workspace_id}/projects/{project_id}/agent-pack/hermes/SKILL.md")
def get_agent_pack_hermes_skill(
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> PlainTextResponse:
    _, manifest = _agent_pack_prepare(session, workspace_id, project_id, principal)
    return PlainTextResponse(_agent_pack_hermes_skill(manifest), media_type="text/markdown")


@app.get("/workspaces/{workspace_id}/projects/{project_id}/agent-pack/codex/AGENTS.md")
def get_agent_pack_codex_agents(
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> PlainTextResponse:
    _, manifest = _agent_pack_prepare(session, workspace_id, project_id, principal)
    return PlainTextResponse(_agent_pack_codex_agents(manifest), media_type="text/markdown")


@app.get("/workspaces/{workspace_id}/projects/{project_id}/agent-pack/claude/CLAUDE.md")
def get_agent_pack_claude_md(
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> PlainTextResponse:
    _, manifest = _agent_pack_prepare(session, workspace_id, project_id, principal)
    return PlainTextResponse(_agent_pack_claude_md(manifest), media_type="text/markdown")


@app.get("/workspaces/{workspace_id}/projects/{project_id}/agent-pack/mcp.json")
def get_agent_pack_mcp_json(
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> JSONResponse:
    _, manifest = _agent_pack_prepare(session, workspace_id, project_id, principal)
    return JSONResponse(_agent_pack_mcp_json(manifest))


@app.get("/workspaces/{workspace_id}/projects/{project_id}/agent-pack.zip")
def get_agent_pack_zip(
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Response:
    project, manifest = _agent_pack_prepare(session, workspace_id, project_id, principal)
    identity = cast(Mapping[str, Any], manifest["identity"])
    content = _agent_pack_zip_bytes(manifest)
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=principal.user.id,
            actor_token_id=principal.token_id,
            action="agent_pack.download",
            target_type="project",
            target_id=project.id,
            meta={"artifact": "zip", "manifest_digest": _agent_pack_manifest_digest(manifest)},
        )
    )
    session.commit()
    filename = f"{identity['slug']}-skill-pack.zip"
    return Response(
        content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get(
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
    _require_project_access(session, workspace_id, project_id, principal)
    resources = [
        resource
        for resource in _current_project_resources(session, workspace_id, project_id)
        if resource.type.lower() == "git" and token_allows_resource(principal, resource.id)
    ]
    return [_git_env_read(resource) for resource in resources]


@app.patch(
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
    _require_project_member(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal)
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
    resource.source_config = _validate_source_config(resource.type, resource.uri, source_config)
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
    return _git_env_read(resource)


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
    _require_project_member(session, workspace_id, project_id, principal)
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


def _resource_read(session: Session, resource: Resource, principal: Principal | None = None) -> ResourceRead:
    data = ResourceRead.model_validate(resource)
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
    _require_project_member(session, workspace_id, project_id, principal)
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
        queue.enqueue("contextsmith_worker.jobs.run_index", str(run.id), job_timeout=600)
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
        value = int(cursor)
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


def _context_artifact_read(session: Session, artifact: ContextArtifact, *, include_rows: bool = True) -> ContextArtifactRead:
    sources: list[ContextArtifactSourceRead] = []
    citations: list[ContextArtifactCitationRead] = []
    if include_rows:
        source_rows = list(
            session.scalars(
                select(ContextArtifactSource)
                .where(ContextArtifactSource.context_artifact_id == artifact.id)
                .order_by(ContextArtifactSource.normalized_path.asc())
            )
        )
        sources = [
            ContextArtifactSourceRead(
                id=source.id,
                normalized_path=source.normalized_path,
                status=source.status,
                coverage_status=source.coverage_status,
                section_count=source.section_count,
                metadata_json=source.metadata_json,
            )
            for source in source_rows
        ]
        citation_rows = list(
            session.scalars(
                select(ContextArtifactCitation)
                .where(ContextArtifactCitation.context_artifact_id == artifact.id)
                .order_by(ContextArtifactCitation.normalized_path.asc(), ContextArtifactCitation.ordinal.asc())
            )
        )
        citations = [
            ContextArtifactCitationRead(
                id=citation.id,
                normalized_path=citation.normalized_path,
                ordinal=citation.ordinal,
                title=citation.title,
                content_hash=citation.content_hash,
                line_start=citation.line_start,
                line_end=citation.line_end,
            )
            for citation in citation_rows
        ]
    return ContextArtifactRead(
        id=artifact.id,
        resource_id=artifact.resource_id,
        source_snapshot_id=artifact.source_snapshot_id,
        resource_manifest_id=artifact.resource_manifest_id,
        artifact_type=artifact.artifact_type,
        artifact_revision=artifact.artifact_revision,
        status=artifact.status,
        artifact_hash=artifact.artifact_hash,
        title=artifact.title,
        summary=artifact.summary,
        coverage_json=artifact.coverage_json,
        validation_json=artifact.validation_json,
        error_message=artifact.error_message,
        review_comment=artifact.review_comment,
        approved_at=artifact.approved_at,
        rejected_at=artifact.rejected_at,
        created_at=artifact.created_at,
        sources=sources,
        citations=citations,
    )


def _resolve_context_artifact(session: Session, workspace_id: UUID, project_id: UUID, artifact_id: UUID, principal: Principal) -> ContextArtifact:
    artifact = session.scalar(
        select(ContextArtifact).where(
            ContextArtifact.id == artifact_id,
            ContextArtifact.workspace_id == workspace_id,
            ContextArtifact.project_id == project_id,
        )
    )
    if artifact is None or not token_allows_resource(principal, artifact.resource_id):
        raise HTTPException(status_code=404, detail="context artifact not found")
    _require_project_access(session, workspace_id, project_id, principal)
    return artifact


def _require_review_write(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal) -> None:
    require_scope(principal, "review:write")
    _require_project_member(session, workspace_id, project_id, principal)


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/context-artifacts/resource-map",
    response_model=ContextArtifactRead,
)
def compile_resource_map_artifact(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    force: bool = False,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ContextArtifactRead:
    require_scope(principal, "resource:refresh")
    _require_project_member(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    if resource.type != "folder_bundle":
        raise HTTPException(status_code=422, detail="Resource Map compile is only available for folder bundles")
    if resource.current_snapshot_id is None:
        raise HTTPException(status_code=409, detail="source has no current snapshot to compile")
    snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.id == resource.current_snapshot_id, SourceSnapshot.workspace_id == workspace_id, SourceSnapshot.project_id == project_id, SourceSnapshot.resource_id == resource.id))
    if snapshot is None:
        raise HTTPException(status_code=409, detail="source snapshot is missing")
    manifest = session.scalar(select(ResourceManifest).where(ResourceManifest.workspace_id == workspace_id, ResourceManifest.project_id == project_id, ResourceManifest.resource_id == resource.id, ResourceManifest.source_snapshot_id == snapshot.id))
    if manifest is None:
        raise HTTPException(status_code=409, detail="source manifest is missing; index the source before compiling a Resource Map")
    build = build_resource_map(session, resource, manifest, snapshot)
    existing = latest_same_hash_artifact(session, resource, snapshot.id, build.artifact_hash)
    if existing is not None:
        if existing.status == "failed" and not force:
            raise HTTPException(status_code=409, detail={"message": existing.error_message, "artifact_id": str(existing.id)})
        if not (force and existing.status in {"failed", "rejected"}):
            return _context_artifact_read(session, existing)
    artifact = ContextArtifact(
        workspace_id=workspace_id,
        project_id=project_id,
        resource_id=resource.id,
        source_snapshot_id=snapshot.id,
        resource_manifest_id=manifest.id,
        artifact_type=ARTIFACT_TYPE_RESOURCE_MAP,
        artifact_revision=next_artifact_revision(session, resource, snapshot.id, build.artifact_hash),
        status=build.status,
        artifact_hash=build.artifact_hash,
        title=build.title,
        summary=build.summary,
        content_json=build.content_json,
        coverage_json=build.coverage_json,
        validation_json=build.validation_json,
        error_message=build.error_message,
        created_by=principal.user.id,
    )
    session.add(artifact)
    session.flush()
    sources_by_file_id: dict[UUID, ContextArtifactSource] = {}
    for source_input in build.sources:
        source = ContextArtifactSource(
            workspace_id=workspace_id,
            project_id=project_id,
            context_artifact_id=artifact.id,
            resource_id=resource.id,
            source_snapshot_id=snapshot.id,
            resource_manifest_id=manifest.id,
            resource_manifest_file_id=source_input["resource_manifest_file_id"],
            normalized_path=source_input["normalized_path"],
            status=source_input["status"],
            section_count=source_input["section_count"],
            coverage_status=source_input["coverage_status"],
            metadata_json=source_input["metadata_json"],
        )
        session.add(source)
        sources_by_file_id[source.resource_manifest_file_id] = source
    session.flush()
    for citation_input in build.citations:
        citation_source = sources_by_file_id.get(citation_input["resource_manifest_file_id"])
        if citation_source is None:
            continue
        session.add(
            ContextArtifactCitation(
                workspace_id=workspace_id,
                project_id=project_id,
                context_artifact_id=artifact.id,
                context_artifact_source_id=citation_source.id,
                resource_id=resource.id,
                section_family_resource_id=citation_input["section_family_resource_id"],
                source_snapshot_id=snapshot.id,
                resource_manifest_id=manifest.id,
                resource_manifest_file_id=citation_input["resource_manifest_file_id"],
                section_id=citation_input["section_id"],
                snapshot_section_id=citation_input["snapshot_section_id"],
                normalized_path=citation_input["normalized_path"],
                ordinal=citation_input["ordinal"],
                title=citation_input["title"],
                content_hash=citation_input["content_hash"],
                line_start=citation_input["line_start"],
                line_end=citation_input["line_end"],
            )
        )
    session.add(AuditEvent(workspace_id=workspace_id, actor_user_id=principal.user.id, actor_token_id=principal.token_id, action="context_artifact.compile", target_type="context_artifact", target_id=artifact.id, meta={"artifact_type": artifact.artifact_type, "status": artifact.status}))
    session.commit()
    if artifact.status == "failed":
        raise HTTPException(status_code=409, detail={"message": artifact.error_message, "artifact_id": str(artifact.id)})
    return _context_artifact_read(session, artifact)


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/context-artifacts",
    response_model=list[ContextArtifactRead],
)
def list_resource_context_artifacts(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    artifact_type: str | None = None,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> list[ContextArtifactRead]:
    require_scope(principal, "resource:read")
    _require_project_access(session, workspace_id, project_id, principal)
    _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    predicates = [ContextArtifact.workspace_id == workspace_id, ContextArtifact.project_id == project_id, ContextArtifact.resource_id == resource_id]
    if artifact_type:
        predicates.append(ContextArtifact.artifact_type == artifact_type)
    rows = list(session.scalars(select(ContextArtifact).where(*predicates).order_by(ContextArtifact.created_at.desc()).limit(20)))
    return [_context_artifact_read(session, artifact, include_rows=False) for artifact in rows]


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/context-artifacts/{artifact_id}",
    response_model=ContextArtifactRead,
)
def get_context_artifact(
    workspace_id: UUID,
    project_id: UUID,
    artifact_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ContextArtifactRead:
    require_scope(principal, "resource:read")
    artifact = _resolve_context_artifact(session, workspace_id, project_id, artifact_id, principal)
    return _context_artifact_read(session, artifact)


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/context-artifacts/{artifact_id}/approve",
    response_model=ContextArtifactRead,
)
def approve_context_artifact(
    workspace_id: UUID,
    project_id: UUID,
    artifact_id: UUID,
    payload: ArtifactApprovalRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ContextArtifactRead:
    _require_review_write(session, workspace_id, project_id, principal)
    artifact = _resolve_context_artifact(session, workspace_id, project_id, artifact_id, principal)
    if artifact.status != "draft":
        raise HTTPException(status_code=409, detail="only draft artifacts can be approved")
    warnings = artifact.validation_json.get("warnings") if isinstance(artifact.validation_json, dict) else []
    errors = artifact.validation_json.get("errors") if isinstance(artifact.validation_json, dict) else []
    if errors:
        raise HTTPException(status_code=422, detail="artifact validation errors block approval")
    if warnings and not payload.acknowledge_warnings:
        raise HTTPException(status_code=422, detail={"message": "warnings require acknowledgement", "warnings": warnings})
    artifact.status = "approved"
    artifact.approved_by = principal.user.id
    artifact.approved_at = datetime.now(UTC)
    artifact.review_comment = payload.comment
    session.add(AuditEvent(workspace_id=workspace_id, actor_user_id=principal.user.id, actor_token_id=principal.token_id, action="context_artifact.approve", target_type="context_artifact", target_id=artifact.id))
    session.commit()
    return _context_artifact_read(session, artifact)


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/context-artifacts/{artifact_id}/reject",
    response_model=ContextArtifactRead,
)
def reject_context_artifact(
    workspace_id: UUID,
    project_id: UUID,
    artifact_id: UUID,
    payload: ArtifactRejectRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ContextArtifactRead:
    _require_review_write(session, workspace_id, project_id, principal)
    artifact = _resolve_context_artifact(session, workspace_id, project_id, artifact_id, principal)
    if artifact.status != "draft":
        raise HTTPException(status_code=409, detail="only draft artifacts can be rejected")
    artifact.status = "rejected"
    artifact.rejected_by = principal.user.id
    artifact.rejected_at = datetime.now(UTC)
    artifact.review_comment = payload.reason.strip()
    session.add(AuditEvent(workspace_id=workspace_id, actor_user_id=principal.user.id, actor_token_id=principal.token_id, action="context_artifact.reject", target_type="context_artifact", target_id=artifact.id))
    session.commit()
    return _context_artifact_read(session, artifact)


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
    _require_project_member(session, workspace_id, project_id, principal)
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
        queue.enqueue("contextsmith_worker.jobs.run_index", str(run.id), job_timeout=600)
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
    _require_project_member(session, workspace_id, project_id, principal)
    allowed_resource_ids = principal.api_token.allowed_resource_ids if principal.api_token is not None else None
    if allowed_resource_ids is not None:
        allowed = list(allowed_resource_ids)
    else:
        allowed = None
    from contextsmith_worker.maintenance import enqueue_due_refreshes

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
    require_workspace_member(session, workspace_id, principal)
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


@app.patch(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}",
    response_model=ResourceRead,
)
def update_resource(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    payload: ResourceUpdate,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Resource:
    user = principal.user
    require_scope(principal, "resource:write")
    _require_project_member(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    fields = payload.model_dump(exclude_unset=True)
    if resource.archived_at is not None and fields.get("retrieval_enabled") is True:
        raise HTTPException(status_code=409, detail="archived resources cannot be re-enabled")
    if resource.type.lower() in FOLDER_BUNDLE_RESOURCE_TYPES and fields.get("update_frequency") not in (None, "manual"):
        raise HTTPException(status_code=422, detail="folder bundle resources are manual-only; upload a new zip to update")
    nullable_rejected = {"name", "uri", "update_frequency", "source_config"}
    for key, value in fields.items():
        if key in nullable_rejected and value is None:
            raise HTTPException(status_code=422, detail=f"{key} cannot be null")
    if any(key in fields for key in ("type", "uri", "source_config")):
        effective_type = fields.get("type", resource.type)
        effective_uri = fields.get("uri", resource.uri)
        effective_source_config = dict(fields.get("source_config", resource.source_config or {}))
        if str(effective_type).lower() == "git" and "uri" in fields:
            effective_source_config["url"] = str(fields["uri"])
        fields["source_config"] = _validate_source_config(effective_type, effective_uri, effective_source_config)
        if effective_type.lower() in URL_RESOURCE_TYPES | {"git"}:
            fields["uri"] = sanitize_remote_url(fields["source_config"]["url"])
    for key, value in fields.items():
        setattr(resource, key, value)
    if "update_frequency" in fields or "source_config" in fields:
        resource.next_refresh_at = compute_next_refresh_at(resource)
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="resource.update",
            target_type="resource",
            target_id=resource.id,
            meta={"fields": sorted(fields.keys())},
        )
    )
    session.commit()
    return resource


@app.delete(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}",
    status_code=204,
)
def delete_resource(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> None:
    user = principal.user
    require_scope(principal, "resource:write")
    _require_project_member(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    now = datetime.now(UTC)
    previous = {
        "status": resource.status,
        "retrieval_enabled": resource.retrieval_enabled,
        "archived_at": resource.archived_at.isoformat() if resource.archived_at else None,
    }
    resource.deleted_at = now
    resource.retrieval_enabled = False
    resource.status = "deleted"
    resource.archived_at = resource.archived_at or now
    resource.next_refresh_at = None
    new = {
        "status": resource.status,
        "retrieval_enabled": resource.retrieval_enabled,
        "archived_at": resource.archived_at.isoformat() if resource.archived_at else None,
        "deleted_at": resource.deleted_at.isoformat() if resource.deleted_at else None,
    }
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="resource.delete",
            target_type="resource",
            target_id=resource.id,
            meta={"previous": previous, "new": new, "deleted_at": now.isoformat()},
        )
    )
    session.commit()
    return None


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/archive",
    response_model=ResourceRead,
)
def archive_resource(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Resource:
    user = principal.user
    require_scope(principal, "resource:write")
    _require_project_member(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    now = datetime.now(UTC)
    previous = {
        "status": resource.status,
        "retrieval_enabled": resource.retrieval_enabled,
        "archived_at": resource.archived_at.isoformat() if resource.archived_at else None,
    }
    resource.archived_at = now
    resource.status = "archived"
    resource.retrieval_enabled = False
    resource.next_refresh_at = None
    new = {
        "status": resource.status,
        "retrieval_enabled": resource.retrieval_enabled,
        "archived_at": resource.archived_at.isoformat() if resource.archived_at else None,
    }
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="resource.archive",
            target_type="resource",
            target_id=resource.id,
            meta={"previous": previous, "new": new, "archived_at": now.isoformat()},
        )
    )
    session.commit()
    return resource


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/restore",
    response_model=ResourceRead,
)
def restore_resource(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Resource:
    user = principal.user
    require_scope(principal, "resource:write")
    _require_project_member(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal, include_deleted=True)
    if resource.deleted_at is None and resource.archived_at is None and resource.status not in {"deleted", "archived"}:
        raise HTTPException(status_code=409, detail="resource is not archived or deleted")
    previous = {
        "status": resource.status,
        "retrieval_enabled": resource.retrieval_enabled,
        "archived_at": resource.archived_at.isoformat() if resource.archived_at else None,
        "deleted_at": resource.deleted_at.isoformat() if resource.deleted_at else None,
    }
    resource.deleted_at = None
    resource.archived_at = None
    resource.status = "active"
    resource.retrieval_enabled = True
    resource.next_refresh_at = compute_next_refresh_at(resource)
    new = {
        "status": resource.status,
        "retrieval_enabled": resource.retrieval_enabled,
        "archived_at": None,
        "deleted_at": None,
        "next_refresh_at": resource.next_refresh_at.isoformat() if resource.next_refresh_at else None,
    }
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="resource.restore",
            target_type="resource",
            target_id=resource.id,
            meta={"previous": previous, "new": new},
        )
    )
    session.commit()
    return resource


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/purge",
    response_model=PurgeResourceResponse,
)
def purge_resource(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> PurgeResourceResponse:
    user = principal.user
    require_scope(principal, "resource:write")
    _require_project_member(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal, include_deleted=True)
    if resource.deleted_at is None and resource.status != "deleted":
        raise HTTPException(status_code=409, detail="resource must be soft-deleted before purge")
    active_run = session.scalar(
        select(IndexRun.id)
        .where(
            IndexRun.workspace_id == workspace_id,
            IndexRun.project_id == project_id,
            IndexRun.resource_id == resource_id,
            IndexRun.status.in_(ACTIVE_INDEX_STATUSES),
        )
        .limit(1)
    )
    if active_run is not None:
        raise HTTPException(status_code=409, detail="resource has an active index run")
    previous = {
        "status": resource.status,
        "retrieval_enabled": resource.retrieval_enabled,
        "archived_at": resource.archived_at.isoformat() if resource.archived_at else None,
        "deleted_at": resource.deleted_at.isoformat() if resource.deleted_at else None,
    }
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="resource.purge",
            target_type="resource",
            target_id=resource.id,
            meta={"previous": previous},
        )
    )
    session.flush()
    counts = _purge_resource_artifacts(session, resource)
    session.commit()
    return PurgeResourceResponse(resource_id=resource_id, purged=counts.get("resources", 0) == 1, counts=counts)


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/review",
    response_model=ResourceRead,
)
def review_resource(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    payload: ResourceReviewRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> Resource:
    user = principal.user
    require_scope(principal, "review:write")
    _require_project_member(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    if resource.archived_at is not None and payload.retrieval_enabled is True:
        raise HTTPException(status_code=409, detail="archived resources cannot be re-enabled")
    previous = {
        "review_status": resource.review_status,
        "review_note": resource.review_note,
        "retrieval_enabled": resource.retrieval_enabled,
        "stale_after_days": resource.stale_after_days,
    }
    resource.review_status = payload.review_status
    resource.review_note = payload.review_note
    resource.last_reviewed_at = datetime.now(UTC)
    resource.last_reviewed_by = user.id
    if payload.retrieval_enabled is not None:
        resource.retrieval_enabled = payload.retrieval_enabled
    if payload.stale_after_days is not None:
        resource.stale_after_days = payload.stale_after_days
    new = {
        "review_status": resource.review_status,
        "review_note": resource.review_note,
        "retrieval_enabled": resource.retrieval_enabled,
        "stale_after_days": resource.stale_after_days,
        "last_reviewed_at": resource.last_reviewed_at.isoformat() if resource.last_reviewed_at else None,
        "last_reviewed_by": str(resource.last_reviewed_by) if resource.last_reviewed_by else None,
    }
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=user.id,
            actor_token_id=principal.token_id,
            action="resource.review",
            target_type="resource",
            target_id=resource.id,
            meta={
                "previous": previous,
                "new": new,
                "review_status": payload.review_status,
                "review_note": payload.review_note,
                "retrieval_enabled": payload.retrieval_enabled,
                "stale_after_days": payload.stale_after_days,
            },
        )
    )
    session.commit()
    return resource


def _resource_review_item(session: Session, resource: Resource) -> ResourceReviewItem:
    usage = session.execute(
        text(
            """
            SELECT COUNT(*) AS hit_count, MAX(created_at) AS last_used_at
            FROM retrieval_hits
            WHERE workspace_id = :ws AND project_id = :proj AND resource_id = :res
            """
        ),
        {"ws": resource.workspace_id, "proj": resource.project_id, "res": resource.id},
    ).mappings().one()
    last_index = session.execute(
        text(
            """
            SELECT status, finished_at
            FROM index_runs
            WHERE workspace_id = :ws AND project_id = :proj AND resource_id = :res
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"ws": resource.workspace_id, "proj": resource.project_id, "res": resource.id},
    ).mappings().first()
    now = datetime.now(UTC)
    age_days = None
    reasons: list[str] = []
    freshness_status = "fresh"
    if resource.archived_at is not None:
        freshness_status = "archived"
        reasons.append("archived")
    elif resource.current_snapshot_id is None:
        freshness_status = "stale"
        reasons.append("no_current_snapshot")
    else:
        base = resource.last_refresh_finished_at or resource.created_at
        if base is not None:
            if base.tzinfo is None:
                base = base.replace(tzinfo=UTC)
            age_days = max(0, (now - base).days)
            if age_days > resource.stale_after_days:
                freshness_status = "stale"
                reasons.append("refresh_age_exceeded")
        if resource.review_status in {"stale", "needs_update"}:
            freshness_status = "stale"
            reasons.append(f"review_status:{resource.review_status}")
    return ResourceReviewItem(
        resource=ResourceRead.model_validate(resource, from_attributes=True),
        freshness_status=freshness_status,
        freshness_age_days=age_days,
        usage_count=int(usage["hit_count"] or 0),
        last_used_at=usage["last_used_at"],
        last_index_status=last_index["status"] if last_index else None,
        last_index_finished_at=last_index["finished_at"] if last_index else None,
        stale_reasons=reasons,
    )


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resource-review",
    response_model=ResourceReviewResponse,
)
def list_resource_review(
    workspace_id: UUID,
    project_id: UUID,
    include_archived: bool = Query(default=False),
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ResourceReviewResponse:
    require_scope(principal, "review:read")
    _require_project_access(session, workspace_id, project_id, principal)
    predicates = [
        Resource.workspace_id == workspace_id,
        Resource.project_id == project_id,
        Resource.deleted_at.is_(None),
    ]
    if not include_archived:
        predicates.append(Resource.archived_at.is_(None))
    if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
        predicates.append(Resource.id.in_(principal.api_token.allowed_resource_ids))
    resources = list(session.scalars(select(Resource).where(*predicates).order_by(Resource.created_at.asc())))
    items = [_resource_review_item(session, resource) for resource in resources]
    return ResourceReviewResponse(count=len(items), resources=items)


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resource-usage",
    response_model=ResourceUsageResponse,
)
def resource_usage(
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ResourceUsageResponse:
    require_scope(principal, "review:read")
    _require_project_access(session, workspace_id, project_id, principal)
    rows = session.execute(
        text(
            """
            SELECT r.id AS resource_id,
                   COUNT(DISTINCT rh.query_run_id) AS query_count,
                   COUNT(DISTINCT rh.id) AS hit_count,
                   COUNT(DISTINCT cpi.context_packet_id) AS context_packet_count,
                   MAX(rh.created_at) AS last_used_at
            FROM resources r
            LEFT JOIN retrieval_hits rh ON rh.resource_id = r.id
              AND rh.workspace_id = r.workspace_id
              AND rh.project_id = r.project_id
            LEFT JOIN context_packet_items cpi ON cpi.resource_id = r.id
              AND cpi.workspace_id = r.workspace_id
              AND cpi.project_id = r.project_id
            WHERE r.workspace_id = :ws
              AND r.project_id = :proj
              AND r.deleted_at IS NULL
            GROUP BY r.id
            ORDER BY hit_count DESC, r.id ASC
            """
        ),
        {"ws": workspace_id, "proj": project_id},
    ).mappings().all()
    allowed_resource_ids = principal.api_token.allowed_resource_ids if principal.api_token is not None else None
    if allowed_resource_ids is not None:
        allowed = set(allowed_resource_ids)
        rows = [row for row in rows if row["resource_id"] in allowed]
    items = [
        ResourceUsageItem(
            resource_id=row["resource_id"],
            query_count=int(row["query_count"] or 0),
            hit_count=int(row["hit_count"] or 0),
            context_packet_count=int(row["context_packet_count"] or 0),
            last_used_at=row["last_used_at"],
        )
        for row in rows
    ]
    return ResourceUsageResponse(count=len(items), resources=items)


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resources",
    response_model=list[ResourceRead],
)
def list_resources(
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> list[ResourceRead]:
    require_scope(principal, "resource:read")
    _require_project_access(session, workspace_id, project_id, principal)
    predicates = [
        Resource.workspace_id == workspace_id,
        Resource.project_id == project_id,
        Resource.deleted_at.is_(None),
    ]
    if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
        predicates.append(Resource.id.in_(principal.api_token.allowed_resource_ids))
    resources = list(
        session.scalars(
            select(Resource)
            .where(*predicates)
            .order_by(Resource.created_at.asc())
        )
    )
    return [_resource_read(session, resource, principal) for resource in resources]


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/snapshots",
    response_model=list[SnapshotRead],
)
def list_snapshots(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> list[SnapshotRead]:
    require_scope(principal, "resource:read")
    _require_project_access(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    snapshots = session.scalars(
        select(SourceSnapshot)
        .where(
            SourceSnapshot.workspace_id == workspace_id,
            SourceSnapshot.resource_id == resource_id,
        )
        .order_by(SourceSnapshot.created_at.desc())
    )
    return [
        SnapshotRead(
            id=snapshot.id,
            workspace_id=snapshot.workspace_id,
            project_id=snapshot.project_id,
            resource_id=snapshot.resource_id,
            version=snapshot.version,
            version_kind=snapshot.version_kind,
            status=snapshot.status,
            metadata=snapshot.meta or {},
            fetched_at=snapshot.fetched_at,
            indexed_at=snapshot.indexed_at,
            created_at=snapshot.created_at,
            is_current=snapshot.id == resource.current_snapshot_id,
        )
        for snapshot in snapshots
    ]


@app.get(
    "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/graph",
    response_model=GraphRead,
)
def get_resource_graph(
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    limit: int = Query(default=200, ge=1, le=1000),
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> GraphRead:
    require_scope(principal, "resource:read")
    _require_project_access(session, workspace_id, project_id, principal)
    resource = _resolve_resource(session, workspace_id, project_id, resource_id, principal)
    if resource.current_snapshot_id is None:
        return GraphRead(node_count=0, edge_count=0, nodes=[], edges=[])
    nodes = list(
        session.scalars(
            select(GraphNode)
            .where(
                GraphNode.workspace_id == workspace_id,
                GraphNode.project_id == project_id,
                GraphNode.resource_id == resource_id,
                GraphNode.source_snapshot_id == resource.current_snapshot_id,
            )
            .order_by(GraphNode.node_type.asc(), GraphNode.label.asc())
            .limit(limit)
        )
    )
    edges = list(
        session.scalars(
            select(GraphEdge)
            .where(
                GraphEdge.workspace_id == workspace_id,
                GraphEdge.project_id == project_id,
                GraphEdge.resource_id == resource_id,
                GraphEdge.source_snapshot_id == resource.current_snapshot_id,
            )
            .order_by(GraphEdge.edge_type.asc(), GraphEdge.created_at.asc())
            .limit(limit)
        )
    )
    return GraphRead(
        node_count=len(nodes),
        edge_count=len(edges),
        nodes=[
            GraphNodeRead(
                id=node.id,
                resource_id=node.resource_id,
                snapshot_id=node.source_snapshot_id,
                node_key=node.node_key,
                node_type=node.node_type,
                label=node.label,
                path=node.path,
                metadata=node.meta,
            )
            for node in nodes
        ],
        edges=[
            GraphEdgeRead(
                id=edge.id,
                resource_id=edge.resource_id,
                snapshot_id=edge.source_snapshot_id,
                source_node_id=edge.source_node_id,
                target_node_id=edge.target_node_id,
                edge_type=edge.edge_type,
                weight=edge.weight,
                metadata=edge.meta,
            )
            for edge in edges
        ],
    )


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


def _make_snippet(content: str, limit: int = 320) -> str:
    collapsed = " ".join(content.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + "…"


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/search",
    response_model=SearchResponse,
)
def search_project(
    workspace_id: UUID,
    project_id: UUID,
    payload: SearchRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> SearchResponse:
    require_scope(principal, "project:query")
    resource_ids = _effective_resource_ids(principal, payload.resource_ids)
    _require_project_access(session, workspace_id, project_id, principal)

    resource_clause = ""
    params: dict = {
        "ws": str(workspace_id),
        "proj": str(project_id),
        "q": payload.query,
        "k": payload.top_k,
    }
    if resource_ids:
        resource_clause = "AND r.id = ANY(CAST(:rids AS uuid[]))"
        params["rids"] = [str(rid) for rid in resource_ids]
    elif _is_empty_scope(resource_ids):
        return SearchResponse(query=payload.query, count=0, hits=[])

    sql = text(
        f"""
        SELECT c.resource_id, c.source_snapshot_id, c.path, c.title, c.ordinal,
               c.content_hash, c.content,
               s.version, s.version_kind, s.metadata AS snap_meta,
               ts_rank(to_tsvector('english', c.content),
                       plainto_tsquery('english', :q)) AS score
        FROM chunks c
        JOIN source_snapshots s ON s.id = c.source_snapshot_id
        WHERE c.workspace_id = CAST(:ws AS uuid)
          AND c.project_id = CAST(:proj AS uuid)
          AND c.deleted_at IS NULL
          AND c.source_snapshot_id IN (
              SELECT r.current_snapshot_id FROM resources r
              WHERE r.workspace_id = CAST(:ws AS uuid)
                AND r.project_id = CAST(:proj AS uuid)
                AND r.deleted_at IS NULL
                AND r.archived_at IS NULL
                AND r.retrieval_enabled = true
                AND r.current_snapshot_id IS NOT NULL
                {resource_clause}
          )
          AND to_tsvector('english', c.content) @@ plainto_tsquery('english', :q)
        ORDER BY score DESC, c.resource_id, c.ordinal ASC
        LIMIT :k
        """
    )
    rows = session.execute(sql, params).mappings().all()
    hits = []
    for row in rows:
        snap_meta = row["snap_meta"] if isinstance(row["snap_meta"], dict) else {}
        hits.append(
            SearchHit(
                resource_id=row["resource_id"],
                snapshot_id=row["source_snapshot_id"],
                path=row["path"],
                title=row["title"],
                ordinal=row["ordinal"],
                content_hash=row["content_hash"],
                version=row["version"],
                version_kind=row["version_kind"],
                commit=snap_meta.get("commit"),
                snippet=_make_snippet(row["content"]),
                score=float(row["score"]),
            )
        )
    return SearchResponse(query=payload.query, count=len(hits), hits=hits)


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/code-search",
    response_model=CodeSearchResponse,
)
def code_search_project(
    workspace_id: UUID,
    project_id: UUID,
    payload: CodeSearchRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> CodeSearchResponse:
    """Search extracted code symbols with file/line/commit citations.

    This endpoint returns deterministic source-derived symbols only. It does not
    infer call edges or behavior with an LLM.
    """
    require_scope(principal, "project:query")
    resource_ids = _effective_resource_ids(principal, payload.resource_ids)
    _require_project_access(session, workspace_id, project_id, principal)
    resource_clause = ""
    params: dict = {
        "ws": str(workspace_id),
        "proj": str(project_id),
        "q": payload.query,
        "limit": payload.limit,
    }
    if resource_ids:
        resource_clause = "AND r.id = ANY(CAST(:rids AS uuid[]))"
        params["rids"] = [str(rid) for rid in resource_ids]
    elif _is_empty_scope(resource_ids):
        return CodeSearchResponse(query=payload.query, count=0, symbols=[])
    rows = session.execute(
        text(
            f"""
            SELECT sym.resource_id, sym.source_snapshot_id, sym.path, sym.name,
                   sym.kind, sym.language, sym.line_start, sym.line_end,
                   sym.signature, sym.content_hash,
                   snap.version, snap.version_kind, snap.metadata AS snap_meta,
                   ts_rank(
                     to_tsvector('simple', sym.name || ' ' || sym.path || ' ' || sym.signature),
                     plainto_tsquery('simple', :q)
                   ) AS score
            FROM code_symbols sym
            JOIN resources r ON r.current_snapshot_id = sym.source_snapshot_id
              AND r.id = sym.resource_id
              AND r.workspace_id = sym.workspace_id
              AND r.project_id = sym.project_id
            JOIN source_snapshots snap ON snap.id = sym.source_snapshot_id
              AND snap.workspace_id = sym.workspace_id
              AND snap.project_id = sym.project_id
              AND snap.resource_id = sym.resource_id
            WHERE sym.workspace_id = CAST(:ws AS uuid)
              AND sym.project_id = CAST(:proj AS uuid)
              AND sym.deleted_at IS NULL
              AND r.deleted_at IS NULL
              AND r.archived_at IS NULL
              AND r.retrieval_enabled = true
              AND r.current_snapshot_id IS NOT NULL
              {resource_clause}
              AND to_tsvector('simple', sym.name || ' ' || sym.path || ' ' || sym.signature)
                  @@ plainto_tsquery('simple', :q)
            ORDER BY score DESC, sym.path ASC, sym.line_start ASC
            LIMIT :limit
            """
        ),
        params,
    ).mappings().all()
    symbols: list[CodeSymbolHit] = []
    for row in rows:
        snap_meta = row["snap_meta"] if isinstance(row["snap_meta"], dict) else {}
        symbols.append(
            CodeSymbolHit(
                resource_id=row["resource_id"],
                snapshot_id=row["source_snapshot_id"],
                path=row["path"],
                name=row["name"],
                kind=row["kind"],
                language=row["language"],
                line_start=row["line_start"],
                line_end=row["line_end"],
                signature=row["signature"],
                content_hash=row["content_hash"],
                version=row["version"],
                version_kind=row["version_kind"],
                commit=snap_meta.get("commit"),
                score=float(row["score"] or 0.0),
            )
        )
    return CodeSearchResponse(query=payload.query, count=len(symbols), symbols=symbols)


def _remote_code_error(exc: RemoteCodeError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message})


def _snapshot_commit(snapshot: SourceSnapshot | None) -> str | None:
    if snapshot is None or not isinstance(snapshot.meta, dict):
        return None
    return snapshot.meta.get("commit") or snapshot.meta.get("version")


def _safe_branch_name(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if not re.match(r"^[A-Za-z0-9._/-]{1,200}$", value) or ".." in value or value.startswith("/") or value.endswith("/"):
        raise HTTPException(status_code=422, detail="invalid branch name")
    return value


def _patch_policy_profile(session: Session, workspace_id: UUID, project_id: UUID) -> AgentProfile | None:
    return session.scalar(select(AgentProfile).where(AgentProfile.workspace_id == workspace_id, AgentProfile.project_id == project_id))


def _patch_file_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _build_unified_file_diff(path: str, original: str, updated: str) -> str:
    old_lines = original.splitlines(keepends=True)
    new_lines = updated.splitlines(keepends=True)
    if old_lines and not old_lines[-1].endswith("\n"):
        old_lines[-1] += "\n"
    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"
    return "".join(difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{path}", tofile=f"b/{path}"))


def _patch_proposal_read(proposal: PatchProposal) -> PatchProposalRead:
    files_payload = [PatchProposalFileRead(**dict(item)) for item in cast(list[dict[str, Any]], proposal.files or [])]
    return PatchProposalRead(
        id=proposal.id,
        workspace_id=proposal.workspace_id,
        project_id=proposal.project_id,
        resource_id=proposal.resource_id,
        source_snapshot_id=proposal.source_snapshot_id,
        status=proposal.status,
        scope=proposal.scope,
        source_branch=proposal.source_branch,
        target_branch=proposal.target_branch,
        indexed_commit=proposal.indexed_commit,
        base_commit=proposal.base_commit,
        branch_moved=proposal.branch_moved,
        warnings=list(proposal.warnings or []),
        files=files_payload,
        unified_diff=proposal.unified_diff,
        diff_summary=proposal.diff_summary,
        created_at=proposal.created_at,
    )


def _pr_request_read(pr_request: PrRequest) -> PrRequestRead:
    return PrRequestRead(
        id=pr_request.id,
        workspace_id=pr_request.workspace_id,
        project_id=pr_request.project_id,
        resource_id=pr_request.resource_id,
        patch_proposal_id=pr_request.patch_proposal_id,
        status=pr_request.status,
        source_branch=pr_request.source_branch,
        target_branch=pr_request.target_branch,
        scope=pr_request.scope,
        diff_summary=pr_request.diff_summary,
        approval_note=pr_request.approval_note,
        github_pr_url=pr_request.github_pr_url,
        external_ref=pr_request.external_ref,
        created_at=pr_request.created_at,
    )


def _current_snapshot_files(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    resource_ids: list[UUID] | None,
    path_glob: str | None = None,
) -> list[tuple[SnapshotFile, SourceSnapshot]]:
    effective_resource_ids = _effective_resource_ids(principal, resource_ids)
    if _is_empty_scope(effective_resource_ids):
        return []
    predicates = [
        SnapshotFile.workspace_id == workspace_id,
        SnapshotFile.project_id == project_id,
        SnapshotFile.deleted_at.is_(None),
        Resource.workspace_id == workspace_id,
        Resource.project_id == project_id,
        Resource.id == SnapshotFile.resource_id,
        Resource.current_snapshot_id == SnapshotFile.source_snapshot_id,
        Resource.deleted_at.is_(None),
        Resource.archived_at.is_(None),
        Resource.retrieval_enabled.is_(True),
        Resource.type == "git",
        SourceSnapshot.id == SnapshotFile.source_snapshot_id,
        SourceSnapshot.workspace_id == workspace_id,
        SourceSnapshot.project_id == project_id,
    ]
    if effective_resource_ids is not None:
        predicates.append(SnapshotFile.resource_id.in_(effective_resource_ids))
    if path_glob is not None:
        if "*" not in path_glob and "?" not in path_glob and "[" not in path_glob:
            predicates.append(SnapshotFile.path == path_glob)
        else:
            predicates.append(SnapshotFile.path.like(path_glob.replace("%", "\\%").replace("_", "\\_").replace("*", "%").replace("?", "_"), escape="\\"))
    rows = session.execute(
        select(SnapshotFile, SourceSnapshot)
        .options(
            load_only(
                SnapshotFile.id,
                SnapshotFile.byte_size,
                SnapshotFile.resource_id,
                SnapshotFile.source_snapshot_id,
            )
        )
        .where(*predicates)
        .order_by(SnapshotFile.path.asc())
        .limit(MAX_SCANNED_FILES + 1)
    ).all()
    selected_ids: list[UUID] = []
    snapshots_by_file_id: dict[UUID, SourceSnapshot] = {}
    total_bytes = 0
    for file_row, snapshot in rows:
        total_bytes += int(file_row.byte_size or 0)
        if len(selected_ids) >= MAX_SCANNED_FILES or total_bytes > MAX_SCANNED_BYTES:
            raise RemoteCodeError("scan_budget_exceeded", "remote code scan exceeds file/byte budget", status_code=422)
        selected_ids.append(file_row.id)
        snapshots_by_file_id[file_row.id] = snapshot
    if not selected_ids:
        return []
    content_rows = session.execute(
        select(SnapshotFile)
        .where(SnapshotFile.id.in_(selected_ids))
        .order_by(SnapshotFile.path.asc())
    ).scalars().all()
    return [(file_row, snapshots_by_file_id[file_row.id]) for file_row in content_rows]


def _record_remote_code_audit(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    tool_name: str,
    status_value: str,
    result_count: int = 0,
    latency_ms: float = 0.0,
    denied_reason: str | None = None,
) -> None:
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=principal.user.id,
            actor_token_id=principal.token_id,
            action="remote_code_tool.invoke" if status_value == "succeeded" else "remote_code_tool.denied",
            target_type="project",
            target_id=project_id,
            meta={
                "tool_name": tool_name,
                "status": status_value,
                "result_count": result_count,
                "latency_ms": round(latency_ms, 2),
                **({"denied_reason": denied_reason} if denied_reason else {}),
            },
        )
    )
    session.commit()


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/remote-code/generate_patch",
    response_model=PatchProposalRead,
)
def remote_generate_patch(
    workspace_id: UUID,
    project_id: UUID,
    payload: GeneratePatchRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> PatchProposalRead:
    require_scope(principal, "project:query")
    require_scope(principal, "code:read")
    require_scope(principal, "patch:generate")
    project = _require_project_member(session, workspace_id, project_id, principal)
    _ = project
    profile = _patch_policy_profile(session, workspace_id, project_id)
    _require_patch_generation_enabled(profile)
    source_branch = _safe_branch_name(payload.source_branch)
    target_branch = _safe_branch_name(payload.target_branch)
    resource = _resolve_resource(session, workspace_id, project_id, payload.resource_id, principal)
    if (
        resource.type.lower() != "git"
        or resource.current_snapshot_id is None
        or resource.deleted_at is not None
        or resource.archived_at is not None
        or not resource.retrieval_enabled
    ):
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "git snapshot not found"})
    snapshot = session.get(SourceSnapshot, resource.current_snapshot_id)
    indexed_commit = _snapshot_commit(snapshot)
    warnings: list[str] = []
    base_commit_required = bool(source_branch or target_branch)
    if base_commit_required and not payload.base_commit:
        warnings.append("base_commit_required_for_pr_approval")
    branch_moved = bool(payload.base_commit and indexed_commit and payload.base_commit != indexed_commit)
    if branch_moved:
        warnings.append("source_branch_moved_since_base_commit")
    diffs: list[str] = []
    files_payload: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for file_change in payload.files:
        try:
            path = validate_repo_path(file_change.path)
        except RemoteCodeError as exc:
            raise _remote_code_error(exc) from exc
        if path in seen_paths:
            raise HTTPException(status_code=422, detail="duplicate patch path")
        seen_paths.add(path)
        row = session.scalar(
            select(SnapshotFile).where(
                SnapshotFile.workspace_id == workspace_id,
                SnapshotFile.project_id == project_id,
                SnapshotFile.resource_id == resource.id,
                SnapshotFile.source_snapshot_id == resource.current_snapshot_id,
                SnapshotFile.path == path,
                SnapshotFile.deleted_at.is_(None),
                SnapshotFile.is_binary.is_(False),
            )
        )
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": f"file not found: {path}"})
        lines = row.content.splitlines()
        start = file_change.start_line
        end = file_change.end_line if file_change.end_line is not None else len(lines)
        if start > len(lines) + 1 or end > len(lines):
            raise HTTPException(status_code=422, detail="patch line range is outside indexed file")
        replacement_lines = file_change.new_content.splitlines()
        updated_lines = lines[: start - 1] + replacement_lines + lines[end:]
        updated = "\n".join(updated_lines)
        if row.content.endswith("\n"):
            updated += "\n"
        diff = _build_unified_file_diff(path, row.content, updated)
        if not diff:
            warnings.append(f"no_change:{path}")
        diffs.append(diff)
        files_payload.append(
            {
                "path": path,
                "start_line": start,
                "end_line": end,
                "original_hash": _patch_file_hash(row.content),
                "new_hash": _patch_file_hash(updated),
                "rationale": file_change.rationale,
            }
        )
    unified_diff = "\n".join(diff for diff in diffs if diff).strip() + "\n"
    if not unified_diff.strip():
        raise HTTPException(status_code=422, detail="patch has no file changes")
    diff_summary = f"{len(files_payload)} file(s): " + ", ".join(item["path"] for item in files_payload)
    proposal = PatchProposal(
        workspace_id=workspace_id,
        project_id=project_id,
        resource_id=resource.id,
        source_snapshot_id=resource.current_snapshot_id,
        actor_user_id=principal.user.id,
        actor_token_id=principal.token_id,
        status="draft",
        scope=payload.scope,
        source_branch=source_branch,
        target_branch=target_branch,
        indexed_commit=indexed_commit,
        base_commit=payload.base_commit,
        branch_moved=branch_moved,
        warnings=warnings,
        files=files_payload,
        unified_diff=unified_diff,
        diff_summary=diff_summary,
        request={"approval_note_present": bool(payload.approval_note)},
    )
    session.add(proposal)
    session.flush()
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=principal.user.id,
            actor_token_id=principal.token_id,
            action="patch.generate",
            target_type="patch_proposal",
            target_id=proposal.id,
            meta={"resource_id": str(resource.id), "scope": payload.scope, "branch_moved": branch_moved, "diff_summary": diff_summary},
        )
    )
    session.commit()
    return _patch_proposal_read(proposal)


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/remote-code/open_pr",
    response_model=PrRequestRead,
)
def remote_open_pr(
    workspace_id: UUID,
    project_id: UUID,
    payload: OpenPrRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> PrRequestRead:
    require_scope(principal, "pr:write")
    project = _require_project_member(session, workspace_id, project_id, principal)
    _ = project
    profile = _patch_policy_profile(session, workspace_id, project_id)
    _require_pr_workflow_enabled(profile)
    source_branch = _safe_branch_name(payload.source_branch)
    target_branch = _safe_branch_name(payload.target_branch)
    assert source_branch is not None and target_branch is not None
    proposal = session.get(PatchProposal, payload.patch_proposal_id)
    if proposal is None or proposal.workspace_id != workspace_id or proposal.project_id != project_id:
        raise HTTPException(status_code=404, detail="patch proposal not found")
    resource = _resolve_resource(session, workspace_id, project_id, proposal.resource_id, principal)
    if (
        resource.type.lower() != "git"
        or resource.current_snapshot_id is None
        or resource.deleted_at is not None
        or resource.archived_at is not None
        or not resource.retrieval_enabled
    ):
        raise HTTPException(status_code=404, detail="patch proposal not found")
    current_snapshot = session.get(SourceSnapshot, resource.current_snapshot_id)
    current_commit = _snapshot_commit(current_snapshot)
    if proposal.indexed_commit and current_commit != proposal.indexed_commit:
        raise HTTPException(status_code=409, detail="indexed commit changed; regenerate patch before PR approval")
    if proposal.status == "pr_opened":
        raise HTTPException(status_code=409, detail="patch proposal already has a PR approval record")
    if proposal.source_branch and source_branch != proposal.source_branch:
        raise HTTPException(status_code=422, detail="source branch must match patch proposal")
    if proposal.target_branch and target_branch != proposal.target_branch:
        raise HTTPException(status_code=422, detail="target branch must match patch proposal")
    if proposal.branch_moved:
        raise HTTPException(status_code=409, detail="source branch moved; regenerate patch before PR approval")
    if proposal.indexed_commit and not proposal.base_commit:
        raise HTTPException(status_code=409, detail="base commit required; regenerate patch with indexed commit before PR approval")
    pr_request = PrRequest(
        workspace_id=workspace_id,
        project_id=project_id,
        resource_id=proposal.resource_id,
        patch_proposal_id=proposal.id,
        approver_user_id=principal.user.id,
        approver_token_id=principal.token_id,
        status="opened" if payload.github_pr_url else "recorded",
        source_branch=source_branch,
        target_branch=target_branch,
        scope=proposal.scope,
        diff_summary=proposal.diff_summary,
        approval_note=payload.approval_note,
        github_pr_url=payload.github_pr_url,
        external_ref={"integration": "manual_record", "source": "contextsmith"},
    )
    proposal.status = "pr_opened"
    session.add(pr_request)
    session.add(proposal)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="patch proposal already has a PR approval record") from exc
    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=principal.user.id,
            actor_token_id=principal.token_id,
            action="pr.open_record",
            target_type="pr_request",
            target_id=pr_request.id,
            meta={
                "patch_proposal_id": str(proposal.id),
                "resource_id": str(proposal.resource_id),
                "source_branch": source_branch,
                "target_branch": target_branch,
                "diff_summary": proposal.diff_summary,
            },
        )
    )
    session.commit()
    return _pr_request_read(pr_request)


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/remote-code/search_code",
    response_model=RemoteSearchCodeResponse,
)
def remote_search_code(
    workspace_id: UUID,
    project_id: UUID,
    payload: RemoteSearchCodeRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> RemoteSearchCodeResponse:
    started = perf_counter()
    require_scope(principal, "project:query")
    require_scope(principal, "code:read")
    _require_project_access(session, workspace_id, project_id, principal)
    try:
        pattern = compile_safe_regex(payload.query, regex=False)
        files = _current_snapshot_files(session, workspace_id, project_id, principal, payload.resource_ids)
    except RemoteCodeError as exc:
        _record_remote_code_audit(session, workspace_id=workspace_id, project_id=project_id, principal=principal, tool_name="search_code", status_value="denied", denied_reason=exc.code)
        raise _remote_code_error(exc) from exc
    results: list[RemoteSearchCodeHit] = []
    for file_row, snapshot in files:
        check_scan_budget(started)
        lines = file_row.content.splitlines()
        for idx, line in enumerate(lines, start=1):
            if len(line) > MAX_SEARCH_LINE_CHARS:
                continue
            if pattern.search(line):
                results.append(
                    RemoteSearchCodeHit(
                        resource_id=file_row.resource_id,
                        snapshot_id=file_row.source_snapshot_id,
                        indexed_commit=_snapshot_commit(snapshot),
                        path=file_row.path,
                        line_start=idx,
                        line_end=idx,
                        snippet=snippet_for_line(line),
                        score=1.0,
                        score_components={"lexical": 1.0},
                    )
                )
                break
        if len(results) >= payload.top_k:
            break
    _record_remote_code_audit(session, workspace_id=workspace_id, project_id=project_id, principal=principal, tool_name="search_code", status_value="succeeded", result_count=len(results), latency_ms=(perf_counter() - started) * 1000)
    return RemoteSearchCodeResponse(results=results)


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/remote-code/grep_code",
    response_model=RemoteGrepCodeResponse,
)
def remote_grep_code(
    workspace_id: UUID,
    project_id: UUID,
    payload: RemoteGrepCodeRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> RemoteGrepCodeResponse:
    started = perf_counter()
    require_scope(principal, "project:query")
    require_scope(principal, "code:read")
    _require_project_access(session, workspace_id, project_id, principal)
    try:
        path_glob = validate_path_glob(payload.path_glob)
        pattern = compile_safe_regex(payload.pattern, regex=payload.regex)
        files = _current_snapshot_files(session, workspace_id, project_id, principal, payload.resource_ids, path_glob)
    except RemoteCodeError as exc:
        _record_remote_code_audit(session, workspace_id=workspace_id, project_id=project_id, principal=principal, tool_name="grep_code", status_value="denied", denied_reason=exc.code)
        raise _remote_code_error(exc) from exc
    matches: list[RemoteGrepCodeMatch] = []
    truncated = False
    try:
        for file_row, snapshot in files:
            if not path_matches(file_row.path, path_glob):
                continue
            lines = file_row.content.splitlines()
            for idx, line in enumerate(lines, start=1):
                check_scan_budget(started)
                if len(line) > MAX_SEARCH_LINE_CHARS:
                    continue
                if pattern.search(line):
                    before, after = line_window(lines, idx, payload.context_lines)
                    matches.append(
                        RemoteGrepCodeMatch(
                            resource_id=file_row.resource_id,
                            snapshot_id=file_row.source_snapshot_id,
                            indexed_commit=_snapshot_commit(snapshot),
                            path=file_row.path,
                            line_start=idx,
                            line_end=idx,
                            line_text=snippet_for_line(line),
                            before=[snippet_for_line(item) for item in before],
                            after=[snippet_for_line(item) for item in after],
                        )
                    )
                    if len(matches) >= payload.max_matches:
                        truncated = True
                        break
            if truncated:
                break
    except RemoteCodeError as exc:
        _record_remote_code_audit(session, workspace_id=workspace_id, project_id=project_id, principal=principal, tool_name="grep_code", status_value="denied", denied_reason=exc.code)
        raise _remote_code_error(exc) from exc
    _record_remote_code_audit(session, workspace_id=workspace_id, project_id=project_id, principal=principal, tool_name="grep_code", status_value="succeeded", result_count=len(matches), latency_ms=(perf_counter() - started) * 1000)
    return RemoteGrepCodeResponse(matches=matches, truncated=truncated)


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/remote-code/read_file",
    response_model=RemoteReadFileResponse,
)
def remote_read_file(
    workspace_id: UUID,
    project_id: UUID,
    payload: RemoteReadFileRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> RemoteReadFileResponse:
    started = perf_counter()
    require_scope(principal, "resource:read")
    require_scope(principal, "code:read")
    _require_project_access(session, workspace_id, project_id, principal)
    try:
        path = validate_repo_path(payload.path)
    except RemoteCodeError as exc:
        _record_remote_code_audit(session, workspace_id=workspace_id, project_id=project_id, principal=principal, tool_name="read_file", status_value="denied", denied_reason=exc.code)
        raise _remote_code_error(exc) from exc
    resource = _resolve_resource(session, workspace_id, project_id, payload.resource_id, principal)
    if resource.current_snapshot_id is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "file not found"})
    row = session.execute(
        select(SnapshotFile, SourceSnapshot).where(
            SnapshotFile.workspace_id == workspace_id,
            SnapshotFile.project_id == project_id,
            SnapshotFile.resource_id == payload.resource_id,
            SnapshotFile.source_snapshot_id == resource.current_snapshot_id,
            SnapshotFile.path == path,
            SnapshotFile.deleted_at.is_(None),
            Resource.id == SnapshotFile.resource_id,
            Resource.type == "git",
            Resource.retrieval_enabled.is_(True),
            Resource.deleted_at.is_(None),
            Resource.archived_at.is_(None),
            SourceSnapshot.id == SnapshotFile.source_snapshot_id,
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "file not found"})
    file_row = row[0]
    snapshot = row[1]
    if file_row.is_binary:
        raise HTTPException(status_code=422, detail={"code": "binary_unsupported", "message": "binary files are not supported"})
    try:
        content, start, end, total, truncated = line_range(file_row.content, payload.start_line, payload.end_line)
    except RemoteCodeError as exc:
        _record_remote_code_audit(session, workspace_id=workspace_id, project_id=project_id, principal=principal, tool_name="read_file", status_value="denied", denied_reason=exc.code)
        raise _remote_code_error(exc) from exc
    _record_remote_code_audit(session, workspace_id=workspace_id, project_id=project_id, principal=principal, tool_name="read_file", status_value="succeeded", result_count=1, latency_ms=(perf_counter() - started) * 1000)
    return RemoteReadFileResponse(resource_id=file_row.resource_id, snapshot_id=file_row.source_snapshot_id, indexed_commit=_snapshot_commit(snapshot), path=file_row.path, start_line=start, end_line=end, total_lines=total, content=content, truncated=truncated)


@app.post(
    "/workspaces/{workspace_id}/projects/{project_id}/remote-code/find_symbol",
    response_model=RemoteFindSymbolResponse,
)
def remote_find_symbol(
    workspace_id: UUID,
    project_id: UUID,
    payload: RemoteFindSymbolRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> RemoteFindSymbolResponse:
    started = perf_counter()
    require_scope(principal, "project:query")
    require_scope(principal, "code:read")
    _require_project_access(session, workspace_id, project_id, principal)
    effective_resource_ids = _effective_resource_ids(principal, payload.resource_ids)
    if _is_empty_scope(effective_resource_ids):
        return RemoteFindSymbolResponse(symbols=[])
    predicates = [
        CodeSymbol.workspace_id == workspace_id,
        CodeSymbol.project_id == project_id,
        CodeSymbol.deleted_at.is_(None),
        CodeSymbol.name.ilike(f"%{payload.name}%"),
        Resource.id == CodeSymbol.resource_id,
        Resource.current_snapshot_id == CodeSymbol.source_snapshot_id,
        Resource.deleted_at.is_(None),
        Resource.archived_at.is_(None),
        Resource.retrieval_enabled.is_(True),
        Resource.type == "git",
        SourceSnapshot.id == CodeSymbol.source_snapshot_id,
    ]
    if payload.kind:
        predicates.append(CodeSymbol.kind == payload.kind)
    if effective_resource_ids is not None:
        predicates.append(CodeSymbol.resource_id.in_(effective_resource_ids))
    rows = session.execute(select(CodeSymbol, SourceSnapshot).where(*predicates).order_by(CodeSymbol.path.asc(), CodeSymbol.line_start.asc()).limit(payload.top_k)).all()
    symbols = []
    for symbol, snapshot in rows:
        symbols.append(
            CodeSymbolHit(
                resource_id=symbol.resource_id,
                snapshot_id=symbol.source_snapshot_id,
                path=symbol.path,
                name=symbol.name,
                kind=symbol.kind,
                language=symbol.language,
                line_start=symbol.line_start,
                line_end=symbol.line_end,
                signature=symbol.signature,
                content_hash=symbol.content_hash,
                version=snapshot.version,
                version_kind=snapshot.version_kind,
                commit=_snapshot_commit(snapshot),
                score=1.0,
            )
        )
    _record_remote_code_audit(session, workspace_id=workspace_id, project_id=project_id, principal=principal, tool_name="find_symbol", status_value="succeeded", result_count=len(symbols), latency_ms=(perf_counter() - started) * 1000)
    return RemoteFindSymbolResponse(symbols=symbols)



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
                version=candidate.version,
                version_kind=candidate.version_kind,
                commit=candidate.snapshot_metadata.get("commit"),
                score=candidate.score,
                graph_score=candidate.graph_score,
            )
        )
    symbols: list[CodeSymbolHit] = []
    if payload.include_code_symbols:
        symbol_response = code_search_project(
            workspace_id=workspace_id,
            project_id=project_id,
            payload=CodeSearchRequest(query=payload.query, resource_ids=payload.resource_ids, limit=min(payload.top_k, 20)),
            principal=principal,
            session=session,
        )
        symbols = symbol_response.symbols
    profile = session.scalar(
        select(AgentProfile).where(
            AgentProfile.workspace_id == workspace_id,
            AgentProfile.project_id == project_id,
        )
    )
    actual_runtime = payload.runtime or (profile.default_runtime if profile else "api")
    instruction_parts = [COMMON_AGENT_INSTRUCTION, RUNTIME_INSTRUCTIONS[actual_runtime]]
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
        citations=citations,
        symbols=symbols,
        token_budget_hint=max(1, payload.max_chars // 4),
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
    resource_ids = _effective_resource_ids(principal, payload.resource_ids)
    payload = payload.model_copy(update={"resource_ids": resource_ids})
    _require_project_access(session, workspace_id, project_id, principal)
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
        _require_project_member(session, workspace_id, project_id, principal)
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
    _require_project_member(session, workspace_id, project_id, principal)
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
    payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else result
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


def _mcp_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "contextsmith.get_agent_context",
            "description": "Return permission-scoped cited context for a ContextSmith project.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "runtime": {"type": "string", "enum": ["api", "hermes", "claude", "codex", "cursor"]},
                    "profile": {"type": "string", "enum": sorted(RETRIEVAL_PROFILES)},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
                    "resource_ids": {"type": "array", "items": {"type": "string"}},
                    "include_code_symbols": {"type": "boolean"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "contextsmith.search_code",
            "description": "Search indexed snapshot files without local repository access.",
            "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "resource_ids": {"type": "array", "items": {"type": "string"}}, "top_k": {"type": "integer", "minimum": 1, "maximum": 50}}, "required": ["query"]},
        },
        {
            "name": "contextsmith.grep_code",
            "description": "Run bounded grep over indexed snapshot files without local repository access.",
            "inputSchema": {"type": "object", "properties": {"pattern": {"type": "string"}, "resource_ids": {"type": "array", "items": {"type": "string"}}, "path_glob": {"type": "string"}, "max_matches": {"type": "integer", "minimum": 1, "maximum": 100}, "regex": {"type": "boolean"}}, "required": ["pattern"]},
        },
        {
            "name": "contextsmith.read_file",
            "description": "Read a line range from an indexed repo-relative file snapshot.",
            "inputSchema": {"type": "object", "properties": {"resource_id": {"type": "string"}, "path": {"type": "string"}, "start_line": {"type": "integer", "minimum": 1}, "end_line": {"type": "integer", "minimum": 1}}, "required": ["resource_id", "path"]},
        },
        {
            "name": "contextsmith.find_symbol",
            "description": "Find indexed code symbols by name and optional kind.",
            "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "kind": {"type": "string"}, "resource_ids": {"type": "array", "items": {"type": "string"}}, "top_k": {"type": "integer", "minimum": 1, "maximum": 100}}, "required": ["name"]},
        },
        {
            "name": "contextsmith.generate_patch",
            "description": "Generate a patch proposal from authorized indexed snapshot files. Opt-in only; does not mutate a source repo.",
            "inputSchema": {"type": "object", "properties": {"resource_id": {"type": "string"}, "scope": {"type": "string"}, "files": {"type": "array", "items": {"type": "object"}}, "source_branch": {"type": "string"}, "target_branch": {"type": "string"}, "base_commit": {"type": "string"}}, "required": ["resource_id", "scope", "files"]},
        },
        {
            "name": "contextsmith.open_pr",
            "description": "Record explicit approval for opening a PR from a generated patch. Opt-in approval record only; source-control mutation is handled by a separate approved integration.",
            "inputSchema": {"type": "object", "properties": {"patch_proposal_id": {"type": "string"}, "source_branch": {"type": "string"}, "target_branch": {"type": "string"}, "approval_note": {"type": "string"}, "github_pr_url": {"type": "string"}}, "required": ["patch_proposal_id", "source_branch", "target_branch", "approval_note"]},
        },
    ]


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
                "serverInfo": {"name": "contextsmith", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            },
        }
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": _mcp_tools()}}
    if method == "tools/call":
        params = body.get("params", {})
        if not isinstance(params, dict):
            return _json_rpc_error(rpc_id, -32602, "invalid params")
        tool_name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return _json_rpc_error(rpc_id, -32602, "invalid params")
        result: Any
        try:
            if tool_name == "contextsmith.get_agent_context":
                payload = AgentContextRequest(**arguments)
                resource_ids = _effective_resource_ids(principal, payload.resource_ids)
                payload = payload.model_copy(update={"resource_ids": resource_ids})
                result = _build_agent_context_response(
                    session,
                    workspace_id=workspace_id,
                    project_id=project_id,
                    payload=payload,
                    principal=principal,
                )
            elif tool_name == "contextsmith.search_code":
                result = remote_search_code(workspace_id, project_id, RemoteSearchCodeRequest(**arguments), principal, session)
            elif tool_name == "contextsmith.grep_code":
                result = remote_grep_code(workspace_id, project_id, RemoteGrepCodeRequest(**arguments), principal, session)
            elif tool_name == "contextsmith.read_file":
                result = remote_read_file(workspace_id, project_id, RemoteReadFileRequest(**arguments), principal, session)
            elif tool_name == "contextsmith.find_symbol":
                result = remote_find_symbol(workspace_id, project_id, RemoteFindSymbolRequest(**arguments), principal, session)
            elif tool_name == "contextsmith.generate_patch":
                result = remote_generate_patch(workspace_id, project_id, GeneratePatchRequest(**arguments), principal, session)
            elif tool_name == "contextsmith.open_pr":
                result = remote_open_pr(workspace_id, project_id, OpenPrRequest(**arguments), principal, session)
            else:
                return _json_rpc_error(rpc_id, -32601, "unknown tool")
        except ValidationError as exc:
            return _json_rpc_error(rpc_id, -32602, f"invalid params: {exc.errors()[0]['msg']}")
        except HTTPException as exc:
            return _mcp_tool_error(rpc_id, exc.status_code, exc.detail)
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
