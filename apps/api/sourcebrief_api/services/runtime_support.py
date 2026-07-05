from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal, token_allows_resource
from sourcebrief_api.context_packs import PACK_STATUS_PUBLISHED
from sourcebrief_api.schemas import AgentContextRequest, SearchRequest
from sourcebrief_shared.models import (
    ContextArtifact,
    ContextArtifactCitation,
    ContextPackVersion,
    Resource,
)


@dataclass(frozen=True)
class RuntimeSupportDeps:
    resolve_pack_version: Callable[[Session, UUID, UUID, str, int | str], ContextPackVersion | None]
    require_pack_read: Callable[[Session, UUID, UUID, Principal, ContextPackVersion], None]


def mcp_tool_error(rpc_id: object | None, status_code: int, detail: object) -> dict:
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


def runtime_cursor(cursor: str | None) -> int:
    if cursor in (None, ""):
        return 0
    try:
        value = int(str(cursor))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_cursor", "message": "cursor must be an integer offset"}) from exc
    if value < 0:
        raise HTTPException(status_code=422, detail={"code": "invalid_cursor", "message": "cursor must be non-negative"})
    return value


def runtime_limit(value: object, *, default: int = 100, max_value: int = 500) -> int:
    try:
        parsed = int(str(value)) if value is not None else default
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail={"code": "invalid_limit", "message": "limit must be an integer"}) from exc
    return max(1, min(parsed, max_value))


def runtime_resource_allowed_or_404(principal: Principal, resource_id: UUID) -> None:
    if not token_allows_resource(principal, resource_id):
        raise HTTPException(status_code=404, detail={"code": "not_found", "message": "resource not found"})


def runtime_resource_rows_allowed(principal: Principal, resource_ids: list[UUID]) -> bool:
    return all(token_allows_resource(principal, resource_id) for resource_id in resource_ids)


def runtime_resource_freshness(session: Session, resource: Resource, snapshot_id: UUID | None = None) -> dict[str, Any]:
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


def runtime_freshness(status: str = "current", *, warnings: list[str] | None = None, resources: list[dict[str, Any]] | None = None, pack: dict[str, Any] | None = None, artifact: dict[str, Any] | None = None, graph: dict[str, Any] | None = None) -> dict[str, Any]:
    computed_warnings = list(warnings or [])
    if resources:
        for resource in resources:
            warning = resource.get("warning")
            if warning:
                computed_warnings.append(str(warning))
        if any(resource.get("status") not in {"current", None} for resource in resources) and status == "current":
            status = "partial" if len(resources) > 1 else "stale"
    return {"status": status, "warnings": sorted(set(computed_warnings)), "generated_at": datetime.now(UTC), "pack": pack, "artifact": artifact, "graph": graph, "resources": resources or [], "coverage_complete": True}


def runtime_citation_locator(citation: ContextArtifactCitation) -> dict[str, Any]:
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


def resource_ref_values(resource_ref: Any = None, resource_refs: Any = None) -> list[str]:
    values: list[str] = []
    if resource_ref is not None and str(resource_ref).strip():
        values.append(str(resource_ref).strip())
    if resource_refs:
        if not isinstance(resource_refs, list):
            raise HTTPException(status_code=422, detail={"code": "invalid_resource_refs", "message": "resource_refs must be an array of names/refs"})
        values.extend(str(ref).strip() for ref in resource_refs if str(ref).strip())
    return list(dict.fromkeys(values))


def dedupe_uuid_values(values: list[Any]) -> list[UUID]:
    result: list[UUID] = []
    seen: set[UUID] = set()
    for value in values:
        item = value if isinstance(value, UUID) else UUID(str(value))
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def resolve_resource_ref_ids(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, *, resource_ref: Any = None, resource_refs: Any = None) -> list[UUID]:
    ids: list[UUID] = []
    for ref in resource_ref_values(resource_ref, resource_refs):
        ids.append(runtime_resolve_resource_ref(session, workspace_id, project_id, principal, {"resource_ref": ref}).id)
    return dedupe_uuid_values(ids)


def request_with_resource_refs(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    payload: SearchRequest | AgentContextRequest,
) -> SearchRequest | AgentContextRequest:
    ref_ids = resolve_resource_ref_ids(
        session,
        workspace_id,
        project_id,
        principal,
        resource_ref=payload.resource_ref,
        resource_refs=payload.resource_refs,
    )
    if not ref_ids:
        return payload
    resource_ids = dedupe_uuid_values([*(payload.resource_ids or []), *ref_ids])
    return payload.model_copy(update={"resource_ids": resource_ids, "resource_ref": None, "resource_refs": None})


def runtime_resolve_resource_ref(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any]) -> Resource:
    resource_id = args.get("resource_id")
    artifact_id = args.get("artifact_id")
    if artifact_id:
        artifact = session.scalar(select(ContextArtifact).where(ContextArtifact.id == UUID(str(artifact_id)), ContextArtifact.workspace_id == workspace_id, ContextArtifact.project_id == project_id))
        if artifact is None:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "resource not found"})
        runtime_resource_allowed_or_404(principal, artifact.resource_id)
        resource_id = artifact.resource_id
    if resource_id and not looks_like_uuid(str(resource_id)):
        args = {**args, "resource_ref": str(resource_id), "resource_id": None}
        resource_id = None
    if resource_id:
        resource = session.scalar(select(Resource).where(Resource.id == UUID(str(resource_id)), Resource.workspace_id == workspace_id, Resource.project_id == project_id, Resource.deleted_at.is_(None), Resource.archived_at.is_(None)))
        if resource is None:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "resource not found"})
        runtime_resource_allowed_or_404(principal, resource.id)
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


def runtime_args_with_resource_ref(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: dict[str, Any],
    *,
    single: bool,
) -> dict[str, Any]:
    refs = resource_ref_values(args.get("resource_ref"), args.get("resource_refs"))
    if not refs:
        return args
    if single:
        if len(refs) > 1:
            raise HTTPException(status_code=422, detail={"code": "too_many_resource_refs", "message": "this tool accepts one resource_ref"})
        if args.get("resource_id"):
            raise HTTPException(status_code=422, detail={"code": "conflicting_resource_locator", "message": "use resource_id or resource_ref, not both"})
        resource = runtime_resolve_resource_ref(session, workspace_id, project_id, principal, {"resource_ref": refs[0]})
        updated = dict(args)
        updated.pop("resource_ref", None)
        updated.pop("resource_refs", None)
        updated["resource_id"] = str(resource.id)
        return updated
    ref_ids = resolve_resource_ref_ids(session, workspace_id, project_id, principal, resource_refs=refs)
    current_ids = list(args.get("resource_ids") or [])
    updated = dict(args)
    updated.pop("resource_ref", None)
    updated.pop("resource_refs", None)
    updated["resource_ids"] = [str(item) for item in dedupe_uuid_values([*current_ids, *ref_ids])]
    return updated


def runtime_resolve_pack(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any], deps: RuntimeSupportDeps) -> ContextPackVersion:
    pack_key = args.get("pack_key")
    version_arg = args.get("version")
    version: ContextPackVersion | None
    if pack_key:
        version = deps.resolve_pack_version(session, workspace_id, project_id, str(pack_key), int(version_arg) if version_arg is not None else "current")
    else:
        version = session.scalar(select(ContextPackVersion).where(ContextPackVersion.workspace_id == workspace_id, ContextPackVersion.project_id == project_id, ContextPackVersion.status == PACK_STATUS_PUBLISHED).order_by(ContextPackVersion.created_at.desc()))
    if version is None:
        raise HTTPException(status_code=404, detail={"code": "pack_not_found", "message": "published context pack not found; call list_sources"})
    deps.require_pack_read(session, workspace_id, project_id, principal, version)
    return version


def looks_like_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True
