from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal, require_scope, token_allows_resource
from sourcebrief_api.context_packs import PACK_STATUS_PUBLISHED
from sourcebrief_api.graph_versions import GRAPH_VERSION_PUBLISHED
from sourcebrief_api.resource_map import ARTIFACT_TYPE_RESOURCE_MAP
from sourcebrief_shared.models import (
    ContextArtifact,
    ContextArtifactCitation,
    ContextArtifactSource,
    ContextPackArtifact,
    ContextPackResourceCoverage,
    ContextPackVersion,
    Graph,
    GraphVersion,
    Resource,
)

RuntimeLimit = Callable[..., int]
RuntimeCursor = Callable[..., int]

ResolvePack = Callable[[Session, UUID, UUID, Principal, dict[str, Any]], ContextPackVersion]
ResourceRowsAllowed = Callable[[Principal, list[UUID]], bool]
CitationLocator = Callable[[ContextArtifactCitation], dict[str, Any]]
ResourceFreshness = Callable[[Session, Resource, UUID | None], dict[str, Any]]
RuntimeFreshness = Callable[..., dict[str, Any]]
GraphInventory = Callable[[Session, UUID, UUID, Principal, dict[str, Any]], dict[str, Any]]
ResolveResourceRef = Callable[[Session, UUID, UUID, Principal, dict[str, Any]], Resource]


@dataclass(frozen=True)
class RuntimeContentDeps:
    runtime_limit: RuntimeLimit
    runtime_cursor: RuntimeCursor
    runtime_resolve_pack: ResolvePack
    runtime_resource_rows_allowed: ResourceRowsAllowed
    runtime_citation_locator: CitationLocator
    runtime_resource_freshness: ResourceFreshness
    runtime_freshness: RuntimeFreshness
    runtime_get_graph_inventory: GraphInventory
    runtime_resolve_resource_ref: ResolveResourceRef


def list_sources(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: dict[str, Any],
    deps: RuntimeContentDeps,
) -> dict[str, Any]:
    require_scope(principal, "project:query")
    require_scope(principal, "resource:read")
    limit = deps.runtime_limit(args.get("limit"), default=100, max_value=100)
    offset = deps.runtime_cursor(args.get("cursor"))
    query = str(args.get("query") or "").strip().lower()
    resource_type = args.get("resource_type")
    predicates = [
        Resource.workspace_id == workspace_id,
        Resource.project_id == project_id,
        Resource.deleted_at.is_(None),
        Resource.archived_at.is_(None),
    ]
    if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
        allowed_resource_ids = list(principal.api_token.allowed_resource_ids)
        if not allowed_resource_ids:
            return {"sources": [], "next_cursor": None}
        predicates.append(Resource.id.in_(allowed_resource_ids))
    if resource_type:
        predicates.append(Resource.type == str(resource_type))
    rows = list(
        session.scalars(
            select(Resource)
            .where(*predicates)
            .order_by(Resource.name.asc())
            .offset(offset)
            .limit(limit + 1)
        )
    )
    sources: list[dict[str, Any]] = []
    for resource in rows[:limit]:
        if not token_allows_resource(principal, resource.id):
            continue
        if query and query not in resource.name.lower() and query not in resource.uri.lower():
            continue
        maps = list(
            session.scalars(
                select(ContextArtifact)
                .where(
                    ContextArtifact.resource_id == resource.id,
                    ContextArtifact.artifact_type == ARTIFACT_TYPE_RESOURCE_MAP,
                    ContextArtifact.status == "approved",
                )
                .order_by(ContextArtifact.created_at.desc())
                .limit(3)
            )
        )
        graph = session.execute(
            select(Graph, GraphVersion)
            .join(GraphVersion, Graph.current_version_id == GraphVersion.id)
            .where(
                Graph.resource_id == resource.id,
                Graph.status == "active",
                GraphVersion.status == GRAPH_VERSION_PUBLISHED,
            )
        ).first()
        sources.append(
            {
                "resource_id": str(resource.id),
                "name": resource.name,
                "type": resource.type,
                "status": resource.status,
                "current_snapshot_id": str(resource.current_snapshot_id) if resource.current_snapshot_id else None,
                "resource_maps": [
                    {
                        "artifact_id": str(artifact.id),
                        "status": artifact.status,
                        "artifact_hash": artifact.artifact_hash,
                    }
                    for artifact in maps
                ],
                "graphs": [{"graph_key": graph[0].graph_key, "current_version": graph[1].version}] if graph else [],
            }
        )
    return {"sources": sources, "next_cursor": str(offset + limit) if len(rows) > limit else None}


def get_context_pack(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: dict[str, Any],
    deps: RuntimeContentDeps,
) -> dict[str, Any]:
    require_scope(principal, "project:query")
    require_scope(principal, "resource:read")
    version = deps.runtime_resolve_pack(session, workspace_id, project_id, principal, args)
    limit = deps.runtime_limit(args.get("limit"), default=100, max_value=200)
    offset = deps.runtime_cursor(args.get("cursor"))
    coverage_rows = list(
        session.execute(
            select(ContextPackResourceCoverage, Resource)
            .join(Resource, ContextPackResourceCoverage.resource_id == Resource.id)
            .where(ContextPackResourceCoverage.context_pack_version_id == version.id)
            .order_by(Resource.name.asc())
            .offset(offset)
            .limit(limit + 1)
        ).all()
    )
    resources = [resource for _coverage, resource in coverage_rows[:limit]]
    if not deps.runtime_resource_rows_allowed(principal, [resource.id for resource in resources]):
        raise HTTPException(status_code=404, detail={"code": "pack_not_found", "message": "context pack not found"})
    artifact_rows = (
        list(
            session.execute(
                select(ContextPackArtifact, ContextArtifact)
                .join(ContextArtifact, ContextPackArtifact.context_artifact_id == ContextArtifact.id)
                .where(ContextPackArtifact.context_pack_version_id == version.id)
                .order_by(ContextPackArtifact.ordinal.asc())
                .offset(offset)
                .limit(limit)
            ).all()
        )
        if args.get("include_artifacts", True)
        else []
    )
    artifacts = []
    for pack_artifact, artifact in artifact_rows:
        citations = list(
            session.scalars(
                select(ContextArtifactCitation)
                .where(ContextArtifactCitation.context_artifact_id == artifact.id)
                .order_by(ContextArtifactCitation.ordinal.asc())
                .limit(5)
            )
        )
        artifacts.append(
            {
                "id": str(artifact.id),
                "pack_artifact_id": str(pack_artifact.id),
                "artifact_type": artifact.artifact_type,
                "resource_id": str(artifact.resource_id),
                "source_snapshot_id": str(artifact.source_snapshot_id),
                "status": artifact.status,
                "artifact_hash": artifact.artifact_hash,
                "title": artifact.title,
                "citation_locators": [deps.runtime_citation_locator(citation) for citation in citations],
            }
        )
    sources = [
        {
            "resource_id": str(resource.id),
            "name": resource.name,
            "type": resource.type,
            "current_snapshot_id": str(resource.current_snapshot_id) if resource.current_snapshot_id else None,
        }
        for _coverage, resource in coverage_rows[:limit]
    ]
    coverage = (
        [
            {
                "resource_id": str(coverage.resource_id),
                "source_snapshot_id": str(coverage.source_snapshot_id),
                "resource_manifest_id": str(coverage.resource_manifest_id),
                "artifact_count": coverage.artifact_count,
                "citation_count": coverage.citation_count,
            }
            for coverage, _resource in coverage_rows[:limit]
        ]
        if args.get("include_coverage", True)
        else []
    )
    freshness_resources = [
        deps.runtime_resource_freshness(session, resource, coverage.source_snapshot_id)
        for coverage, resource in coverage_rows[:limit]
    ]
    return {
        "pack": {
            "id": str(version.id),
            "pack_key": version.pack_key,
            "version": version.version,
            "status": version.status,
            "title": version.title,
            "pack_hash": version.pack_hash,
        },
        "freshness": deps.runtime_freshness(
            version.status if version.status != PACK_STATUS_PUBLISHED else "current",
            resources=freshness_resources,
            pack={"pack_key": version.pack_key, "version": version.version, "status": version.status},
        ),
        "sources": sources,
        "artifacts": artifacts,
        "coverage": coverage,
        "graph_inventory": deps.runtime_get_graph_inventory(session, workspace_id, project_id, principal, {"limit": 50})
        if args.get("include_graph_inventory", True)
        else {"resource_graphs": [], "merge_graphs": []},
        "runtime_guidance": "Start with search, then read_section using the returned locator. Use graph tools for architecture/impact questions.",
        "next_cursor": str(offset + limit) if len(coverage_rows) > limit else None,
        "truncated": len(coverage_rows) > limit,
    }


def get_resource_map(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: dict[str, Any],
    deps: RuntimeContentDeps,
) -> dict[str, Any]:
    require_scope(principal, "project:query")
    require_scope(principal, "resource:read")
    resource = deps.runtime_resolve_resource_ref(session, workspace_id, project_id, principal, args)
    artifact_id = args.get("artifact_id")
    stmt = select(ContextArtifact).where(
        ContextArtifact.workspace_id == workspace_id,
        ContextArtifact.project_id == project_id,
        ContextArtifact.resource_id == resource.id,
        ContextArtifact.artifact_type == ARTIFACT_TYPE_RESOURCE_MAP,
        ContextArtifact.status == "approved",
    )
    if artifact_id:
        stmt = stmt.where(ContextArtifact.id == UUID(str(artifact_id)))
    elif args.get("source_snapshot_id"):
        stmt = stmt.where(ContextArtifact.source_snapshot_id == UUID(str(args["source_snapshot_id"])))
    elif resource.current_snapshot_id:
        stmt = stmt.where(ContextArtifact.source_snapshot_id == resource.current_snapshot_id)
    artifact = session.scalar(stmt.order_by(ContextArtifact.created_at.desc()))
    if artifact is None:
        raise HTTPException(status_code=404, detail={"code": "resource_map_not_found", "message": "approved resource map not found"})
    limit = deps.runtime_limit(args.get("limit"), default=200, max_value=200)
    offset = deps.runtime_cursor(args.get("cursor"))
    citations = list(
        session.scalars(
            select(ContextArtifactCitation)
            .where(ContextArtifactCitation.context_artifact_id == artifact.id)
            .order_by(ContextArtifactCitation.normalized_path.asc(), ContextArtifactCitation.ordinal.asc())
            .offset(offset)
            .limit(limit + 1)
        )
    )
    entries = [
        {"title": citation.title, "path": citation.normalized_path, "summary": None, "locator": deps.runtime_citation_locator(citation)}
        for citation in citations[:limit]
    ]
    sources = (
        list(
            session.scalars(
                select(ContextArtifactSource)
                .where(ContextArtifactSource.context_artifact_id == artifact.id)
                .order_by(ContextArtifactSource.normalized_path.asc())
                .limit(limit)
            )
        )
        if args.get("include_sources", True)
        else []
    )
    freshness_resource = deps.runtime_resource_freshness(session, resource, artifact.source_snapshot_id)
    raw_resource_map = artifact.content_json
    resource_map_text = json.dumps(jsonable_encoder(raw_resource_map), sort_keys=True)
    map_truncated = len(resource_map_text) > 20_000
    resource_map_payload = (
        raw_resource_map
        if not map_truncated
        else {
            "truncated": True,
            "top_level_keys": sorted(raw_resource_map.keys()) if isinstance(raw_resource_map, dict) else [],
            "entry_count": len(raw_resource_map) if isinstance(raw_resource_map, list) else None,
        }
    )
    return {
        "artifact": {
            "id": str(artifact.id),
            "artifact_type": artifact.artifact_type,
            "status": artifact.status,
            "artifact_hash": artifact.artifact_hash,
            "artifact_revision": artifact.artifact_revision,
            "resource_id": str(artifact.resource_id),
            "source_snapshot_id": str(artifact.source_snapshot_id),
            "title": artifact.title,
            "approved_at": artifact.approved_at,
        },
        "freshness": deps.runtime_freshness(
            "current",
            resources=[freshness_resource],
            artifact={"id": str(artifact.id), "status": artifact.status, "artifact_hash": artifact.artifact_hash},
        ),
        "resource_map": resource_map_payload,
        "entries": entries,
        "sources": [
            {"path": source.normalized_path, "status": source.status, "coverage_status": source.coverage_status}
            for source in sources
        ],
        "citations": [
            {"locator": deps.runtime_citation_locator(citation), "snippet": None}
            for citation in citations[:limit]
        ]
        if args.get("include_citations", True)
        else [],
        "next_cursor": str(offset + limit) if len(citations) > limit else None,
        "truncated": len(citations) > limit or map_truncated,
    }
