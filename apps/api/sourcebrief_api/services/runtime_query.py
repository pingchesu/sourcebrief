from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal, require_scope, token_allows_resource
from sourcebrief_api.remote_code import line_range, validate_repo_path
from sourcebrief_api.schemas import (
    RemoteFindSymbolRequest,
    RemoteGrepCodeRequest,
    RemoteSearchCodeRequest,
)
from sourcebrief_shared.models import (
    ContextArtifactCitation,
    ContextPackResourceCoverage,
    ContextPackVersion,
    Resource,
    Section,
    SnapshotFile,
    SnapshotSection,
)

RuntimeLimit = Callable[..., int]
RuntimeResolvePack = Callable[[Session, UUID, UUID, Principal, dict[str, Any]], ContextPackVersion]
EffectiveResourceIds = Callable[[Principal, list[UUID] | None], list[UUID] | None]
IsEmptyScope = Callable[[list[UUID] | None], bool]
RuntimeFreshness = Callable[..., dict[str, Any]]
ResourceFreshness = Callable[[Session, Resource, UUID | None], dict[str, Any]]
MakeSnippet = Callable[[str], str]
ResourceAllowedOr404 = Callable[[Principal, UUID], None]
CitationLocator = Callable[[ContextArtifactCitation], dict[str, Any]]
RuntimeArgsWithResourceRef = Callable[..., dict[str, Any]]
RuntimeRemoteArgs = Callable[[dict[str, Any], set[str]], dict[str, Any]]
RuntimeHasScope = Callable[[Principal, str], bool]
LookupSoftWarning = Callable[..., dict[str, Any] | None]
RuntimeAction = Callable[..., dict[str, Any]]
RemoteAction = Callable[..., Any]


@dataclass(frozen=True)
class RuntimeQueryDeps:
    runtime_limit: RuntimeLimit
    runtime_resolve_pack: RuntimeResolvePack
    effective_resource_ids: EffectiveResourceIds
    is_empty_scope: IsEmptyScope
    runtime_freshness: RuntimeFreshness
    runtime_resource_freshness: ResourceFreshness
    make_snippet: MakeSnippet
    runtime_resource_allowed_or_404: ResourceAllowedOr404
    runtime_citation_locator: CitationLocator
    runtime_args_with_resource_ref: RuntimeArgsWithResourceRef
    runtime_remote_args: RuntimeRemoteArgs
    runtime_has_scope: RuntimeHasScope
    lookup_soft_warning: LookupSoftWarning
    runtime_list_sources: RuntimeAction
    runtime_graph_overview: RuntimeAction
    remote_search_code: RemoteAction
    remote_grep_code: RemoteAction
    remote_find_symbol: RemoteAction

def snapshot_section_locator(snapshot_section: SnapshotSection, section: Section, file_row: SnapshotFile | None = None) -> dict[str, Any]:
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


def require_pack_covers_locator(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any], deps: RuntimeQueryDeps, *, resource_id: UUID, source_snapshot_id: UUID) -> None:
    if not args.get("context_pack_key"):
        return
    pack_args = {"pack_key": args.get("context_pack_key"), "version": args.get("context_pack_version")}
    version = deps.runtime_resolve_pack(session, workspace_id, project_id, principal, pack_args)
    covered = session.scalar(
        select(ContextPackResourceCoverage.id).where(
            ContextPackResourceCoverage.context_pack_version_id == version.id,
            ContextPackResourceCoverage.resource_id == resource_id,
            ContextPackResourceCoverage.source_snapshot_id == source_snapshot_id,
        )
    )
    if covered is None:
        raise HTTPException(status_code=404, detail={"code": "section_not_found", "message": "section not found in context pack"})


def search(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any], deps: RuntimeQueryDeps) -> dict[str, Any]:
    require_scope(principal, "project:query")
    require_scope(principal, "resource:read")
    query = str(args.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=422, detail={"code": "invalid_query", "message": "query is required"})
    top_k = deps.runtime_limit(args.get("top_k"), default=8, max_value=50)
    requested_resource_ids = [UUID(str(value)) for value in args.get("resource_ids") or []]
    pack_version = None
    snapshot_ids: list[UUID] = []
    if args.get("context_pack_key"):
        pack_args = {"pack_key": args.get("context_pack_key"), "version": args.get("context_pack_version")}
        pack_version = deps.runtime_resolve_pack(session, workspace_id, project_id, principal, pack_args)
        coverage = list(session.scalars(select(ContextPackResourceCoverage).where(ContextPackResourceCoverage.context_pack_version_id == pack_version.id)))
        if requested_resource_ids:
            requested_set = set(requested_resource_ids)
            coverage = [row for row in coverage if row.resource_id in requested_set]
        requested_resource_ids = [row.resource_id for row in coverage]
        snapshot_ids = [row.source_snapshot_id for row in coverage]
        if not requested_resource_ids:
            return {"query": query, "profile": args.get("profile") or "hybrid", "hits": [], "freshness": deps.runtime_freshness("current")}
    effective_resource_ids = deps.effective_resource_ids(principal, requested_resource_ids or None)
    if deps.is_empty_scope(effective_resource_ids):
        return {"query": query, "profile": args.get("profile") or "hybrid", "hits": [], "freshness": deps.runtime_freshness("current")}
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
        hits.append({**locator, "snippet": deps.make_snippet(row["content"]), "score": float(row["score"]), "version": row["version"], "version_kind": row["version_kind"], "commit": snap_meta.get("commit"), "freshness": deps.runtime_freshness("current", resources=[deps.runtime_resource_freshness(session, resource, row["source_snapshot_id"])])})
    return {"query": query, "profile": args.get("profile") or "hybrid", "hits": hits, "freshness": deps.runtime_freshness("current")}


def read_section(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any], deps: RuntimeQueryDeps) -> dict[str, Any]:
    require_scope(principal, "project:query")
    require_scope(principal, "resource:read")
    resource_id_arg = args.get("resource_id")
    if not resource_id_arg:
        raise HTTPException(status_code=422, detail={"code": "missing_resource_locator", "message": "provide resource_id or resource_ref with the section locator"})
    resource_id = UUID(str(resource_id_arg))
    resource = session.scalar(select(Resource).where(Resource.id == resource_id, Resource.workspace_id == workspace_id, Resource.project_id == project_id))
    if resource is None:
        raise HTTPException(status_code=404, detail={"code": "section_not_found", "message": "section not found"})
    deps.runtime_resource_allowed_or_404(principal, resource.id)
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
        require_pack_covers_locator(session, workspace_id, project_id, principal, args, deps, resource_id=resource.id, source_snapshot_id=file_row.source_snapshot_id)
        content, start, end, total, truncated = line_range(file_row.content, int(args.get("start_line") or 1), int(args.get("end_line") or min(file_row.line_count, 500)))
        return {"locator": {"resource_id": str(resource.id), "source_snapshot_id": str(file_row.source_snapshot_id), "path": file_row.path, "start_line": start, "end_line": end, "content_hash": file_row.content_hash}, "resource": {"resource_id": str(resource.id), "name": resource.name, "type": resource.type}, "section": {"title": args.get("heading"), "path": file_row.path, "start_line": start, "end_line": end, "total_lines": total}, "content": content[:20000], "freshness": deps.runtime_freshness("current", resources=[deps.runtime_resource_freshness(session, resource, file_row.source_snapshot_id)]), "truncated": truncated or len(content) > 20000}
    elif args.get("allow_current_fallback") and args.get("path") and resource.current_snapshot_id:
        path = validate_repo_path(str(args["path"]))
        file_row = session.scalar(select(SnapshotFile).where(SnapshotFile.resource_id == resource.id, SnapshotFile.source_snapshot_id == resource.current_snapshot_id, SnapshotFile.path == path, SnapshotFile.deleted_at.is_(None)))
        if file_row is None:
            raise HTTPException(status_code=404, detail={"code": "section_not_found", "message": "section not found"})
        require_pack_covers_locator(session, workspace_id, project_id, principal, args, deps, resource_id=resource.id, source_snapshot_id=file_row.source_snapshot_id)
        content, start, end, total, truncated = line_range(file_row.content, int(args.get("start_line") or 1), int(args.get("end_line") or min(file_row.line_count, 500)))
        return {"locator": {"resource_id": str(resource.id), "source_snapshot_id": str(file_row.source_snapshot_id), "path": file_row.path, "start_line": start, "end_line": end, "content_hash": file_row.content_hash}, "resource": {"resource_id": str(resource.id), "name": resource.name, "type": resource.type}, "section": {"title": args.get("heading"), "path": file_row.path, "start_line": start, "end_line": end, "total_lines": total}, "content": content[:20000], "freshness": deps.runtime_freshness("current", resources=[deps.runtime_resource_freshness(session, resource, file_row.source_snapshot_id)]), "truncated": truncated or len(content) > 20000}
    else:
        raise HTTPException(status_code=422, detail={"code": "ambiguous_section", "message": "provide a pinned snapshot_section_id, context_artifact_citation_id, or exact source_snapshot/path/content_hash locator"})
    if snapshot_section is None:
        raise HTTPException(status_code=404, detail={"code": "section_not_found", "message": "section not found"})
    section = session.scalar(select(Section).where(Section.id == snapshot_section.section_id))
    file_row = session.scalar(select(SnapshotFile).where(SnapshotFile.resource_id == resource.id, SnapshotFile.source_snapshot_id == snapshot_section.source_snapshot_id, SnapshotFile.path == snapshot_section.normalized_path, SnapshotFile.deleted_at.is_(None)))
    if file_row is None or file_row.is_binary:
        raise HTTPException(status_code=404, detail={"code": "section_content_unavailable", "message": "retained section content is unavailable"})
    require_pack_covers_locator(session, workspace_id, project_id, principal, args, deps, resource_id=resource.id, source_snapshot_id=snapshot_section.source_snapshot_id)
    content, start, end, total, truncated = line_range(file_row.content, int(args.get("start_line") or citation.line_start if citation and citation.line_start else 1), int(args.get("end_line") or citation.line_end if citation and citation.line_end else min(file_row.line_count, 500)))
    locator = deps.runtime_citation_locator(citation) if citation else snapshot_section_locator(snapshot_section, section, file_row)  # type: ignore[arg-type]
    locator.update({"start_line": start, "end_line": end})
    return {"locator": locator, "resource": {"resource_id": str(resource.id), "name": resource.name, "type": resource.type}, "section": {"title": section.title if section else citation.title if citation else None, "path": file_row.path, "start_line": start, "end_line": end, "total_lines": total}, "content": content[:20000], "freshness": deps.runtime_freshness("current", resources=[deps.runtime_resource_freshness(session, resource, snapshot_section.source_snapshot_id)]), "truncated": truncated or len(content) > 20000}


def lookup(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any], deps: RuntimeQueryDeps) -> dict[str, Any]:
    query = str(args.get("query") or "").strip()
    if not query:
        raise HTTPException(status_code=422, detail={"code": "invalid_query", "message": "query is required"})
    search_in = str(args.get("search_in") or args.get("kind") or "all")
    base_args = deps.runtime_args_with_resource_ref(session, workspace_id, project_id, principal, args, single=False)
    if search_in == "docs":
        return {"mode": "docs", "docs": search(session, workspace_id, project_id, principal, base_args, deps)}
    if search_in == "code":
        code_args = deps.runtime_remote_args(base_args, {"query", "resource_ids", "top_k", "cursor"})
        return {"mode": "code", "code": jsonable_encoder(deps.remote_search_code(workspace_id, project_id, RemoteSearchCodeRequest(**code_args), principal, session))}
    if search_in == "grep":
        grep_args = deps.runtime_remote_args(base_args, {"pattern", "resource_ids", "path_glob", "max_matches", "cursor", "regex", "context_lines"})
        grep_args.setdefault("pattern", query)
        return {"mode": "grep", "grep": jsonable_encoder(deps.remote_grep_code(workspace_id, project_id, RemoteGrepCodeRequest(**grep_args), principal, session))}
    if search_in == "symbols":
        symbol_args = deps.runtime_remote_args(base_args, {"name", "kind", "resource_ids", "top_k"})
        symbol_args.setdefault("name", query)
        return {"mode": "symbols", "symbols": jsonable_encoder(deps.remote_find_symbol(workspace_id, project_id, RemoteFindSymbolRequest(**symbol_args), principal, session))}
    if search_in != "all":
        raise HTTPException(status_code=422, detail={"code": "invalid_lookup_mode", "message": "search_in must be one of all, docs, code, grep, symbols"})
    docs = search(session, workspace_id, project_id, principal, base_args, deps)
    if not deps.runtime_has_scope(principal, "code:read"):
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
    code_args = deps.runtime_remote_args(base_args, {"query", "resource_ids", "top_k", "cursor"})
    code_args.setdefault("top_k", min(int(base_args.get("top_k") or 5), 10))
    symbols_args = deps.runtime_remote_args(base_args, {"name", "kind", "resource_ids", "top_k"})
    symbols_args.setdefault("name", query)
    symbols_args.setdefault("top_k", 10)
    warnings: list[dict[str, Any]] = []
    code: dict[str, Any] | None = None
    try:
        code = jsonable_encoder(deps.remote_search_code(workspace_id, project_id, RemoteSearchCodeRequest(**code_args), principal, session))
    except HTTPException as exc:
        warning = deps.lookup_soft_warning(exc, facet="code")
        if warning is None:
            raise
        warnings.append(warning)
    symbols = jsonable_encoder(deps.remote_find_symbol(workspace_id, project_id, RemoteFindSymbolRequest(**symbols_args), principal, session))
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


def discover(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any], deps: RuntimeQueryDeps) -> dict[str, Any]:
    return {
        "sources": deps.runtime_list_sources(session, workspace_id, project_id, principal, args),
        "architecture": deps.runtime_graph_overview(session, workspace_id, project_id, principal, {"max_resources": args.get("max_resources") or 20, "max_items": args.get("max_items") or 20}),
        "next_steps": [
            {"name": "sourcebrief.ask", "reason": "Ask a cited project question after choosing a source scope."},
            {"name": "sourcebrief.lookup", "reason": "Search docs/code/symbols with an optional human resource_ref."},
        ],
    }
