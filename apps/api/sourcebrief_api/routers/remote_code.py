from __future__ import annotations

import difflib
import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Literal, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, load_only

from sourcebrief_api.auth import Principal, require_principal, require_scope
from sourcebrief_api.remote_code import (
    MAX_GREP_MATCHES,
    MAX_READ_LINES,
    MAX_REGEX_SCAN_SECONDS,
    MAX_SCANNED_BYTES,
    MAX_SCANNED_FILES,
    MAX_SEARCH_LINE_CHARS,
    MAX_SEARCH_RESULTS,
    MAX_SYMBOL_RESULTS,
    RemoteCodeError,
    check_scan_budget,
    compile_safe_regex,
    identifier_score,
    line_range,
    line_window,
    path_matches,
    query_identifier_tokens,
    snippet_for_line,
    validate_path_glob,
    validate_repo_path,
)
from sourcebrief_api.schemas import (
    CodeSearchRequest,
    CodeSearchResponse,
    CodeSymbolHit,
    GeneratePatchRequest,
    OpenPrRequest,
    PatchProposalFileRead,
    PatchProposalRead,
    PrRequestRead,
    RemoteCodeRpcCallResult,
    RemoteCodeRpcRequest,
    RemoteCodeRpcResponse,
    RemoteCodeRpcSpecResponse,
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
    SearchHit,
    SearchRequest,
    SearchResponse,
)
from sourcebrief_shared.db import get_session
from sourcebrief_shared.models import (
    AgentProfile,
    AuditEvent,
    CodeSymbol,
    PatchProposal,
    PrRequest,
    Resource,
    SnapshotFile,
    SourceSnapshot,
)

router = APIRouter()

ProjectAccessAuthorizer = Callable[[Session, UUID, UUID, Principal], object]
ProjectMemberAuthorizer = Callable[..., object]
ResourceResolver = Callable[..., Resource]
ResourceRefRequestResolver = Callable[..., Any]
RuntimeResourceRefResolver = Callable[..., dict[str, Any]]
EffectiveResourceIdsResolver = Callable[[Principal, list[UUID] | None], list[UUID] | None]
EmptyScopePredicate = Callable[[list[UUID] | None], bool]
PrWorkflowAuthorizer = Callable[[AgentProfile | None], None]
PatchGenerationAuthorizer = Callable[[AgentProfile | None], None]


@dataclass(frozen=True)
class RemoteCodeRouterDeps:
    require_project_access: ProjectAccessAuthorizer
    require_project_member: ProjectMemberAuthorizer
    resolve_resource: ResourceResolver
    request_with_resource_refs: ResourceRefRequestResolver
    runtime_args_with_resource_ref: RuntimeResourceRefResolver
    effective_resource_ids: EffectiveResourceIdsResolver
    is_empty_scope: EmptyScopePredicate
    require_pr_workflow_enabled: PrWorkflowAuthorizer
    require_patch_generation_enabled: PatchGenerationAuthorizer


_deps: RemoteCodeRouterDeps


def create_router(deps: RemoteCodeRouterDeps) -> APIRouter:
    global _deps
    _deps = deps
    return router


def _make_snippet(content: str, limit: int = 320) -> str:
    collapsed = " ".join(content.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit].rstrip() + "…"


@router.post(
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
    _deps.require_project_access(session, workspace_id, project_id, principal)
    payload = _deps.request_with_resource_refs(
        session, workspace_id, project_id, principal, payload
    )  # type: ignore[assignment]
    resource_ids = _deps.effective_resource_ids(principal, payload.resource_ids)

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
    elif _deps.is_empty_scope(resource_ids):
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


@router.post(
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
    require_scope(principal, "code:read")
    resource_ids = _deps.effective_resource_ids(principal, payload.resource_ids)
    _deps.require_project_access(session, workspace_id, project_id, principal)
    resource_clause = ""
    query_tokens = query_identifier_tokens(payload.query)
    params: dict = {
        "ws": str(workspace_id),
        "proj": str(project_id),
        "q": payload.query,
        "limit": payload.limit,
        "query_tokens": query_tokens,
    }
    if resource_ids:
        resource_clause = "AND r.id = ANY(CAST(:rids AS uuid[]))"
        params["rids"] = [str(rid) for rid in resource_ids]
    elif _deps.is_empty_scope(resource_ids):
        return CodeSearchResponse(query=payload.query, count=0, symbols=[])
    rows = (
        session.execute(
            text(
                f"""
            SELECT sym.resource_id, sym.source_snapshot_id, sym.path, sym.name,
                   sym.kind, sym.language, sym.line_start, sym.line_end,
                   sym.signature, sym.content_hash,
                   snap.version, snap.version_kind, snap.metadata AS snap_meta,
                   ts_rank(
                     to_tsvector('simple', sym.name || ' ' || sym.path || ' ' || sym.signature),
                     plainto_tsquery('simple', :q)
                   ) AS lexical_score,
                   (
                     SELECT count(*)
                     FROM unnest(CAST(:query_tokens AS text[])) AS qt(token)
                     WHERE lower(sym.name || ' ' || sym.path || ' ' || sym.signature) LIKE '%' || qt.token || '%'
                   ) AS token_hit_count
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
              AND (
                to_tsvector('simple', sym.name || ' ' || sym.path || ' ' || sym.signature)
                  @@ plainto_tsquery('simple', :q)
                OR (
                  cardinality(CAST(:query_tokens AS text[])) > 0
                  AND (
                    SELECT count(*)
                    FROM unnest(CAST(:query_tokens AS text[])) AS qt(token)
                    WHERE lower(sym.name || ' ' || sym.path || ' ' || sym.signature) LIKE '%' || qt.token || '%'
                  ) >= LEAST(2, cardinality(CAST(:query_tokens AS text[])))
                )
              )
            ORDER BY token_hit_count DESC, lexical_score DESC, sym.path ASC, sym.line_start ASC
            LIMIT :limit
            """
            ),
            params,
        )
        .mappings()
        .all()
    )
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
                score=float(row["lexical_score"] or 0.0) + float(row["token_hit_count"] or 0.0),
            )
        )
    return CodeSearchResponse(query=payload.query, count=len(symbols), symbols=symbols)


def _remote_code_error(exc: RemoteCodeError) -> HTTPException:
    detail: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if exc.details:
        detail.update(exc.details)
    return HTTPException(status_code=exc.status_code, detail=detail)


def _scan_budget_exceeded_error(
    session: Session,
    predicates: list[Any],
    *,
    path_glob: str | None,
    scanned_files: int,
    scanned_bytes: int,
) -> RemoteCodeError:
    eligible_files, eligible_bytes = session.execute(
        select(
            func.count(SnapshotFile.id), func.coalesce(func.sum(SnapshotFile.byte_size), 0)
        ).where(*predicates)
    ).one()
    return RemoteCodeError(
        "scan_budget_exceeded",
        "remote code scan exceeds file/byte budget; narrow the search to cited paths before broad code drilldown",
        status_code=422,
        details={
            "scan_budget": {"max_files": MAX_SCANNED_FILES, "max_bytes": MAX_SCANNED_BYTES},
            "eligible_files": int(eligible_files or 0),
            "eligible_bytes": int(eligible_bytes or 0),
            "scanned_files_before_limit": scanned_files,
            "scanned_bytes_at_limit": scanned_bytes,
            "path_glob": path_glob,
            "retry_guidance": [
                "Use sourcebrief.ask or sourcebrief.lookup(search_in='docs') first, then drill into cited files/directories.",
                "For grep_code, retry with path_glob set to a cited file or directory, for example README.md, docs/**, or src/**.",
                "For search_code budget failures, switch to grep_code with path_glob or read_file with an exact cited path; search_code intentionally stays broad and does not accept path_glob.",
            ],
        },
    )


def _lookup_soft_warning(exc: HTTPException, *, facet: str) -> dict[str, Any] | None:
    detail: dict[str, Any] = exc.detail if isinstance(exc.detail, dict) else {}
    if detail.get("code") != "scan_budget_exceeded":
        return None
    return {
        "code": f"{facet}_scan_budget_exceeded",
        "message": f"{facet} facet exceeded the remote-code scan budget; returning the available lookup facets instead.",
        "detail": detail,
        "retry_guidance": [
            "Use search_in='docs' first when docs are enough.",
            "For code drilldown, retry sourcebrief.grep_code with resource_ref/resource_ids and a path_glob from cited paths, or sourcebrief.read_file with an exact cited path.",
        ],
    }


def _snapshot_commit(snapshot: SourceSnapshot | None) -> str | None:
    if snapshot is None or not isinstance(snapshot.meta, dict):
        return None
    return snapshot.meta.get("commit") or snapshot.meta.get("version")


def _safe_branch_name(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    if (
        not re.match(r"^[A-Za-z0-9._/-]{1,200}$", value)
        or ".." in value
        or value.startswith("/")
        or value.endswith("/")
    ):
        raise HTTPException(status_code=422, detail="invalid branch name")
    return value


def _patch_policy_profile(
    session: Session, workspace_id: UUID, project_id: UUID
) -> AgentProfile | None:
    return session.scalar(
        select(AgentProfile).where(
            AgentProfile.workspace_id == workspace_id, AgentProfile.project_id == project_id
        )
    )


def _patch_file_hash(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _build_unified_file_diff(path: str, original: str, updated: str) -> str:
    old_lines = original.splitlines(keepends=True)
    new_lines = updated.splitlines(keepends=True)
    if old_lines and not old_lines[-1].endswith("\n"):
        old_lines[-1] += "\n"
    if new_lines and not new_lines[-1].endswith("\n"):
        new_lines[-1] += "\n"
    return "".join(
        difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{path}", tofile=f"b/{path}")
    )


def _patch_proposal_read(proposal: PatchProposal) -> PatchProposalRead:
    files_payload = [
        PatchProposalFileRead(**dict(item))
        for item in cast(list[dict[str, Any]], proposal.files or [])
    ]
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
    effective_resource_ids = _deps.effective_resource_ids(principal, resource_ids)
    if _deps.is_empty_scope(effective_resource_ids):
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
            predicates.append(
                SnapshotFile.path.like(
                    path_glob.replace("%", "\\%")
                    .replace("_", "\\_")
                    .replace("*", "%")
                    .replace("?", "_"),
                    escape="\\",
                )
            )
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
            raise _scan_budget_exceeded_error(
                session,
                predicates,
                path_glob=path_glob,
                scanned_files=len(selected_ids),
                scanned_bytes=total_bytes,
            )
        selected_ids.append(file_row.id)
        snapshots_by_file_id[file_row.id] = snapshot
    if not selected_ids:
        return []
    content_rows = (
        session.execute(
            select(SnapshotFile)
            .where(SnapshotFile.id.in_(selected_ids))
            .order_by(SnapshotFile.path.asc())
        )
        .scalars()
        .all()
    )
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
            action="remote_code_tool.invoke"
            if status_value == "succeeded"
            else "remote_code_tool.denied",
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


@router.post(
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
    project = _deps.require_project_member(
        session,
        workspace_id,
        project_id,
        principal,
        required_scopes={"code:read", "patch:generate", "project:query"},
    )
    _ = project
    profile = _patch_policy_profile(session, workspace_id, project_id)
    _deps.require_patch_generation_enabled(profile)
    source_branch = _safe_branch_name(payload.source_branch)
    target_branch = _safe_branch_name(payload.target_branch)
    resource = _deps.resolve_resource(
        session, workspace_id, project_id, payload.resource_id, principal
    )
    if (
        resource.type.lower() != "git"
        or resource.current_snapshot_id is None
        or resource.deleted_at is not None
        or resource.archived_at is not None
        or not resource.retrieval_enabled
    ):
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "git snapshot not found"}
        )
    snapshot = session.get(SourceSnapshot, resource.current_snapshot_id)
    indexed_commit = _snapshot_commit(snapshot)
    warnings: list[str] = []
    base_commit_required = bool(source_branch or target_branch)
    if base_commit_required and not payload.base_commit:
        warnings.append("base_commit_required_for_pr_approval")
    branch_moved = bool(
        payload.base_commit and indexed_commit and payload.base_commit != indexed_commit
    )
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
            raise HTTPException(
                status_code=404, detail={"code": "not_found", "message": f"file not found: {path}"}
            )
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
    diff_summary = f"{len(files_payload)} file(s): " + ", ".join(
        item["path"] for item in files_payload
    )
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
            meta={
                "resource_id": str(resource.id),
                "scope": payload.scope,
                "branch_moved": branch_moved,
                "diff_summary": diff_summary,
            },
        )
    )
    session.commit()
    return _patch_proposal_read(proposal)


@router.post(
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
    project = _deps.require_project_member(
        session, workspace_id, project_id, principal, required_scopes={"pr:write"}
    )
    _ = project
    profile = _patch_policy_profile(session, workspace_id, project_id)
    _deps.require_pr_workflow_enabled(profile)
    source_branch = _safe_branch_name(payload.source_branch)
    target_branch = _safe_branch_name(payload.target_branch)
    assert source_branch is not None and target_branch is not None
    proposal = session.get(PatchProposal, payload.patch_proposal_id)
    if (
        proposal is None
        or proposal.workspace_id != workspace_id
        or proposal.project_id != project_id
    ):
        raise HTTPException(status_code=404, detail="patch proposal not found")
    resource = _deps.resolve_resource(
        session, workspace_id, project_id, proposal.resource_id, principal
    )
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
        raise HTTPException(
            status_code=409, detail="indexed commit changed; regenerate patch before PR approval"
        )
    if proposal.status == "pr_opened":
        raise HTTPException(
            status_code=409, detail="patch proposal already has a PR approval record"
        )
    if proposal.source_branch and source_branch != proposal.source_branch:
        raise HTTPException(status_code=422, detail="source branch must match patch proposal")
    if proposal.target_branch and target_branch != proposal.target_branch:
        raise HTTPException(status_code=422, detail="target branch must match patch proposal")
    if proposal.branch_moved:
        raise HTTPException(
            status_code=409, detail="source branch moved; regenerate patch before PR approval"
        )
    if proposal.indexed_commit and not proposal.base_commit:
        raise HTTPException(
            status_code=409,
            detail="base commit required; regenerate patch with indexed commit before PR approval",
        )
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
        external_ref={"integration": "manual_record", "source": "sourcebrief"},
    )
    proposal.status = "pr_opened"
    session.add(pr_request)
    session.add(proposal)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409, detail="patch proposal already has a PR approval record"
        ) from exc
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


@router.post(
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
    payload = RemoteSearchCodeRequest(
        **_deps.runtime_args_with_resource_ref(
            session,
            workspace_id,
            project_id,
            principal,
            payload.model_dump(mode="json", exclude_none=True),
            single=False,
        )
    )
    require_scope(principal, "project:query")
    require_scope(principal, "code:read")
    _deps.require_project_access(session, workspace_id, project_id, principal)
    try:
        pattern = compile_safe_regex(payload.query, regex=False)
        files = _current_snapshot_files(
            session, workspace_id, project_id, principal, payload.resource_ids
        )
    except RemoteCodeError as exc:
        _record_remote_code_audit(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            principal=principal,
            tool_name="search_code",
            status_value="denied",
            denied_reason=exc.code,
        )
        raise _remote_code_error(exc) from exc
    results: list[RemoteSearchCodeHit] = []
    for file_row, snapshot in files:
        check_scan_budget(started)
        best: tuple[float, int, str, dict[str, float]] | None = None
        for idx, line in enumerate(file_row.content.splitlines(), start=1):
            if len(line) > MAX_SEARCH_LINE_CHARS:
                continue
            token_score, components = identifier_score(
                payload.query, path=file_row.path, content=line
            )
            exact_score = 1.0 if pattern.search(line) else 0.0
            score = max(exact_score, token_score)
            if score <= 0.0:
                continue
            combined_components = {**components, "lexical": exact_score}
            if best is None or score > best[0]:
                best = (score, idx, line, combined_components)
        if best is None:
            continue
        score, line_number, line, components = best
        results.append(
            RemoteSearchCodeHit(
                resource_id=file_row.resource_id,
                snapshot_id=file_row.source_snapshot_id,
                indexed_commit=_snapshot_commit(snapshot),
                path=file_row.path,
                line_start=line_number,
                line_end=line_number,
                snippet=snippet_for_line(line),
                score=score,
                score_components=components,
            )
        )
    results.sort(key=lambda hit: (-hit.score, hit.path, hit.line_start))
    results = results[: payload.top_k]
    _record_remote_code_audit(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        principal=principal,
        tool_name="search_code",
        status_value="succeeded",
        result_count=len(results),
        latency_ms=(perf_counter() - started) * 1000,
    )
    return RemoteSearchCodeResponse(results=results)


@router.post(
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
    payload = RemoteGrepCodeRequest(
        **_deps.runtime_args_with_resource_ref(
            session,
            workspace_id,
            project_id,
            principal,
            payload.model_dump(mode="json", exclude_none=True),
            single=False,
        )
    )
    require_scope(principal, "project:query")
    require_scope(principal, "code:read")
    _deps.require_project_access(session, workspace_id, project_id, principal)
    try:
        path_glob = validate_path_glob(payload.path_glob)
        pattern = compile_safe_regex(payload.pattern, regex=payload.regex)
        files = _current_snapshot_files(
            session, workspace_id, project_id, principal, payload.resource_ids, path_glob
        )
    except RemoteCodeError as exc:
        _record_remote_code_audit(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            principal=principal,
            tool_name="grep_code",
            status_value="denied",
            denied_reason=exc.code,
        )
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
        _record_remote_code_audit(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            principal=principal,
            tool_name="grep_code",
            status_value="denied",
            denied_reason=exc.code,
        )
        raise _remote_code_error(exc) from exc
    _record_remote_code_audit(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        principal=principal,
        tool_name="grep_code",
        status_value="succeeded",
        result_count=len(matches),
        latency_ms=(perf_counter() - started) * 1000,
    )
    return RemoteGrepCodeResponse(matches=matches, truncated=truncated)


@router.post(
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
    payload = RemoteReadFileRequest(
        **_deps.runtime_args_with_resource_ref(
            session,
            workspace_id,
            project_id,
            principal,
            payload.model_dump(mode="json", exclude_none=True),
            single=True,
        )
    )
    require_scope(principal, "resource:read")
    require_scope(principal, "code:read")
    _deps.require_project_access(session, workspace_id, project_id, principal)
    try:
        path = validate_repo_path(payload.path)
    except RemoteCodeError as exc:
        _record_remote_code_audit(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            principal=principal,
            tool_name="read_file",
            status_value="denied",
            denied_reason=exc.code,
        )
        raise _remote_code_error(exc) from exc
    if payload.resource_id is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "missing_resource",
                "message": "resource_id or resource_ref is required",
            },
        )
    resource = _deps.resolve_resource(
        session, workspace_id, project_id, payload.resource_id, principal
    )
    if resource.current_snapshot_id is None:
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "file not found"}
        )
    row = session.execute(
        select(SnapshotFile, SourceSnapshot).where(
            SnapshotFile.workspace_id == workspace_id,
            SnapshotFile.project_id == project_id,
            SnapshotFile.resource_id == resource.id,
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
        raise HTTPException(
            status_code=404, detail={"code": "not_found", "message": "file not found"}
        )
    file_row = row[0]
    snapshot = row[1]
    if file_row.is_binary:
        raise HTTPException(
            status_code=422,
            detail={"code": "binary_unsupported", "message": "binary files are not supported"},
        )
    try:
        content, start, end, total, truncated = line_range(
            file_row.content, payload.start_line, payload.end_line
        )
    except RemoteCodeError as exc:
        _record_remote_code_audit(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            principal=principal,
            tool_name="read_file",
            status_value="denied",
            denied_reason=exc.code,
        )
        raise _remote_code_error(exc) from exc
    _record_remote_code_audit(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        principal=principal,
        tool_name="read_file",
        status_value="succeeded",
        result_count=1,
        latency_ms=(perf_counter() - started) * 1000,
    )
    return RemoteReadFileResponse(
        resource_id=file_row.resource_id,
        snapshot_id=file_row.source_snapshot_id,
        indexed_commit=_snapshot_commit(snapshot),
        path=file_row.path,
        start_line=start,
        end_line=end,
        total_lines=total,
        content=content,
        truncated=truncated,
    )


@router.post(
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
    payload = RemoteFindSymbolRequest(
        **_deps.runtime_args_with_resource_ref(
            session,
            workspace_id,
            project_id,
            principal,
            payload.model_dump(mode="json", exclude_none=True),
            single=False,
        )
    )
    require_scope(principal, "project:query")
    require_scope(principal, "code:read")
    _deps.require_project_access(session, workspace_id, project_id, principal)
    effective_resource_ids = _deps.effective_resource_ids(principal, payload.resource_ids)
    if _deps.is_empty_scope(effective_resource_ids):
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
    rows = session.execute(
        select(CodeSymbol, SourceSnapshot)
        .where(*predicates)
        .order_by(CodeSymbol.path.asc(), CodeSymbol.line_start.asc())
        .limit(payload.top_k)
    ).all()
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
    _record_remote_code_audit(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        principal=principal,
        tool_name="find_symbol",
        status_value="succeeded",
        result_count=len(symbols),
        latency_ms=(perf_counter() - started) * 1000,
    )
    return RemoteFindSymbolResponse(symbols=symbols)


def _remote_code_rpc_spec(workspace_id: UUID, project_id: UUID) -> RemoteCodeRpcSpecResponse:
    base = f"/workspaces/{workspace_id}/projects/{project_id}"
    return RemoteCodeRpcSpecResponse(
        schema_version="sourcebrief.remote-code-rpc.v1",
        transport="HTTP JSON over session/API-token auth; MCP remains the default agent orchestration layer.",
        endpoints={
            "json_rpc_batch": f"{base}/code/rpc",
            "legacy_search": f"{base}/remote-code/search_code",
            "legacy_grep": f"{base}/remote-code/grep_code",
            "legacy_read": f"{base}/remote-code/read_file",
            "legacy_symbols": f"{base}/remote-code/find_symbol",
        },
        methods={
            "sourcebrief.code.search": {
                "params": "RemoteSearchCodeRequest: query, resource_ref/resource_refs/resource_ids, top_k, cursor",
                "result_key": "results",
                "purpose": "Lexical/identifier code search over authorized current git snapshots.",
            },
            "sourcebrief.code.grep": {
                "params": "RemoteGrepCodeRequest: pattern, resource_ref/resource_refs/resource_ids, path_glob, max_matches, regex, context_lines",
                "result_key": "matches",
                "purpose": "Bounded grep; broad scans may return budget_exceeded with retry guidance.",
            },
            "sourcebrief.code.read_batch": {
                "params": "{files:[{resource_ref or resource_id, path, start_line?, end_line?}]} (max 20 files)",
                "result_key": "files",
                "purpose": "Batch exact reads after search/grep/citation drilldown.",
            },
            "sourcebrief.code.lookup_plan": {
                "params": "{query, resource_ref/resource_refs/resource_ids?, path_glob?}",
                "result_key": "plan",
                "purpose": "Return suggested search/grep/read RPC calls without leaking snippets.",
            },
        },
        auth={
            "required_scopes": ["project:query", "code:read"],
            "read_file_extra_scope": "resource:read",
            "resource_resolution": "Prefer resource_ref/resource_refs in user-facing clients; raw UUIDs remain advanced/debug escape hatches and resolve only inside the caller's workspace/project scope.",
        },
        budgets={
            "max_calls_per_batch": 20,
            "max_read_files_per_call": 20,
            "max_scanned_files": MAX_SCANNED_FILES,
            "max_scanned_bytes": MAX_SCANNED_BYTES,
            "max_regex_scan_seconds": MAX_REGEX_SCAN_SECONDS,
            "max_matches": MAX_GREP_MATCHES,
            "max_search_results": MAX_SEARCH_RESULTS,
            "max_symbol_results": MAX_SYMBOL_RESULTS,
            "max_read_lines": MAX_READ_LINES,
        },
        failure_modes={
            "budget_exceeded": "status=error on the call with retry_guidance and scanned file/byte counts; clients should retry with path_glob or exact read.",
            "partial": "batch-level status=partial when at least one call succeeds and at least one call errors.",
            "not_queryable": "no current git snapshot or disabled retrieval returns a structured not_found/not_queryable error without backend paths.",
            "forbidden": "missing scopes or resource boundaries return errors and never include code snippets.",
            "ambiguous_resource": "resource_ref ambiguity fails closed with candidates visible only within authorized scope.",
        },
    )


def _remote_code_rpc_error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, HTTPException):
        detail = exc.detail if isinstance(exc.detail, dict) else {"message": str(exc.detail)}
        return {"status_code": exc.status_code, "detail": jsonable_encoder(detail)}
    if isinstance(exc, ValidationError):
        return {
            "status_code": 422,
            "detail": {
                "code": "invalid_request",
                "message": "invalid RPC params",
                "errors": jsonable_encoder(exc.errors()),
            },
        }
    return {"status_code": 500, "detail": {"code": "internal_error", "message": str(exc)}}


def _remote_code_lookup_plan(params: dict[str, Any]) -> dict[str, Any]:
    query = str(params.get("query") or params.get("pattern") or "").strip()
    path_glob = params.get("path_glob")
    top_k = min(int(params.get("top_k") or 10), MAX_SEARCH_RESULTS)
    max_matches = min(int(params.get("max_matches") or 20), MAX_GREP_MATCHES)
    base_locator = {
        key: value
        for key, value in {
            "resource_ref": params.get("resource_ref"),
            "resource_refs": params.get("resource_refs"),
            "resource_ids": params.get("resource_ids"),
        }.items()
        if value
    }
    return {
        "query": query,
        "recommended_sequence": [
            {
                "method": "sourcebrief.code.search",
                "params": {"query": query, **base_locator, "top_k": top_k},
                "why": "Find likely files/symbol-adjacent lines first with low result volume.",
            },
            {
                "method": "sourcebrief.code.grep",
                "params": {
                    "pattern": query,
                    **base_locator,
                    **({"path_glob": path_glob} if path_glob else {}),
                    "max_matches": max_matches,
                },
                "why": "Drill into cited paths or a narrowed glob; avoid broad scans when the corpus is large.",
            },
            {
                "method": "sourcebrief.code.read_batch",
                "params": {
                    "files": [
                        {
                            **base_locator,
                            "path": "<path from search/grep>",
                            "start_line": 1,
                            "end_line": 80,
                        }
                    ]
                },
                "why": "Read exact retained snapshot lines after discovering paths; no checkout mutation is exposed.",
            },
        ],
        "budget_guidance": _remote_code_rpc_spec(UUID(int=0), UUID(int=0)).budgets,
    }


def _execute_remote_code_rpc_call(
    workspace_id: UUID,
    project_id: UUID,
    call_method: str,
    params: dict[str, Any],
    principal: Principal,
    session: Session,
) -> dict[str, Any]:
    if call_method == "sourcebrief.code.search":
        search_payload = RemoteSearchCodeRequest(**params)
        return {
            "results": jsonable_encoder(
                remote_search_code(
                    workspace_id, project_id, search_payload, principal, session
                ).results
            )
        }
    if call_method == "sourcebrief.code.grep":
        grep_payload = RemoteGrepCodeRequest(**params)
        response = remote_grep_code(workspace_id, project_id, grep_payload, principal, session)
        return {
            "matches": jsonable_encoder(response.matches),
            "truncated": response.truncated,
            "next_cursor": response.next_cursor,
        }
    if call_method == "sourcebrief.code.read_batch":
        files = params.get("files")
        if not isinstance(files, list) or not files:
            raise HTTPException(
                status_code=422,
                detail={"code": "invalid_request", "message": "files must be a non-empty array"},
            )
        if len(files) > 20:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "batch_too_large",
                    "message": "read_batch accepts at most 20 files",
                },
            )
        reads = []
        for item in files:
            if not isinstance(item, dict):
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "invalid_request",
                        "message": "each files item must be an object",
                    },
                )
            reads.append(
                jsonable_encoder(
                    remote_read_file(
                        workspace_id, project_id, RemoteReadFileRequest(**item), principal, session
                    )
                )
            )
        return {"files": reads}
    if call_method == "sourcebrief.code.lookup_plan":
        require_scope(principal, "project:query")
        require_scope(principal, "code:read")
        _deps.require_project_access(session, workspace_id, project_id, principal)
        return {"plan": _remote_code_lookup_plan(params)}
    raise HTTPException(
        status_code=422,
        detail={"code": "unknown_method", "message": f"unsupported code RPC method: {call_method}"},
    )


@router.get(
    "/workspaces/{workspace_id}/projects/{project_id}/code/rpc/spec",
    response_model=RemoteCodeRpcSpecResponse,
)
def remote_code_rpc_spec(
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> RemoteCodeRpcSpecResponse:
    require_scope(principal, "project:query")
    _deps.require_project_access(session, workspace_id, project_id, principal)
    return _remote_code_rpc_spec(workspace_id, project_id)


@router.post(
    "/workspaces/{workspace_id}/projects/{project_id}/code/rpc",
    response_model=RemoteCodeRpcResponse,
)
def remote_code_rpc(
    workspace_id: UUID,
    project_id: UUID,
    payload: RemoteCodeRpcRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> RemoteCodeRpcResponse:
    started = perf_counter()
    results: list[RemoteCodeRpcCallResult] = []
    for call in payload.calls:
        call_started = perf_counter()
        try:
            result = _execute_remote_code_rpc_call(
                workspace_id, project_id, call.method, call.params, principal, session
            )
            results.append(
                RemoteCodeRpcCallResult(
                    id=call.id,
                    method=call.method,
                    status="ok",
                    result=result,
                    telemetry={"elapsed_ms": round((perf_counter() - call_started) * 1000, 2)},
                )
            )
        except Exception as exc:  # noqa: BLE001 - RPC batches must serialize per-call errors.
            results.append(
                RemoteCodeRpcCallResult(
                    id=call.id,
                    method=call.method,
                    status="error",
                    error=_remote_code_rpc_error_payload(exc),
                    telemetry={"elapsed_ms": round((perf_counter() - call_started) * 1000, 2)},
                )
            )
            if payload.fail_fast:
                break
    error_count = sum(1 for item in results if item.status == "error")
    status_value: Literal["ok", "partial", "error"] = (
        "ok" if error_count == 0 else "error" if error_count == len(results) else "partial"
    )
    return RemoteCodeRpcResponse(
        workspace_id=workspace_id,
        project_id=project_id,
        status=status_value,
        results=results,
        telemetry={
            "elapsed_ms": round((perf_counter() - started) * 1000, 2),
            "call_count": len(results),
            "error_count": error_count,
        },
    )
