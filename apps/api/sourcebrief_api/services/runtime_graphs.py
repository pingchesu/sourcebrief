from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal, require_scope, token_allows_resource
from sourcebrief_api.graph_merges import (
    GRAPH_MERGE_VERSION_PUBLISHED,
    find_path,
    stale_merge_inputs,
)
from sourcebrief_api.graph_versions import GRAPH_VERSION_PUBLISHED
from sourcebrief_shared.models import (
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
    Resource,
)

RuntimeLimit = Callable[..., int]
RuntimeCursor = Callable[..., int]
RequireProjectAccess = Callable[[Session, UUID, UUID, Principal], object]
ResourceFreshness = Callable[[Session, Resource, UUID | None], dict[str, Any]]
RuntimeFreshness = Callable[..., dict[str, Any]]
ResourceRowsAllowed = Callable[[Principal, list[UUID]], bool]
ResourceAllowedOr404 = Callable[[Principal, UUID], None]


@dataclass(frozen=True)
class RuntimeGraphDeps:
    runtime_limit: RuntimeLimit
    runtime_cursor: RuntimeCursor
    require_project_access: RequireProjectAccess
    runtime_resource_freshness: ResourceFreshness
    runtime_freshness: RuntimeFreshness
    runtime_resource_rows_allowed: ResourceRowsAllowed
    runtime_resource_allowed_or_404: ResourceAllowedOr404


def sample_counter(counter: Counter[str], limit: int = 20) -> dict[str, int]:
    return dict(counter.most_common(limit))

def graph_overview(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any], deps: RuntimeGraphDeps) -> dict[str, Any]:
    require_scope(principal, "project:query")
    require_scope(principal, "resource:read")
    deps.require_project_access(session, workspace_id, project_id, principal)
    max_resources = deps.runtime_limit(args.get("max_resources"), default=20, max_value=50)
    max_items = deps.runtime_limit(args.get("max_items"), default=20, max_value=50)

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
                "freshness": deps.runtime_freshness("current"),
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
            freshness = deps.runtime_resource_freshness(session, resource, version.source_snapshot_id)
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
            freshness_resources.append(deps.runtime_resource_freshness(session, resource, resource.current_snapshot_id))
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
        )
        .order_by(GraphMerge.merge_key.asc())
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
        stale_inputs = stale_merge_inputs(session, version)
        merge_is_stale = version.status != GRAPH_MERGE_VERSION_PUBLISHED or bool(stale_inputs)
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
            "freshness": "stale" if merge_is_stale else "current",
            "status": version.status,
            "status_reason": version.status_reason,
            "stale_inputs": stale_inputs,
        }
        if merge_is_stale:
            stale_or_missing.append(
                {
                    "merge_key": merge.merge_key,
                    "status": "stale_merge_graph",
                    "version_status": version.status,
                    "status_reason": version.status_reason,
                    "stale_inputs": stale_inputs,
                }
            )
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
        if len(merge_graphs) >= max_resources:
            break

    status_value = "missing_graphs" if visible and not graphs else "partial" if stale_or_missing else "current"
    truncated = truncated or len(entries) > max_items or len(unresolved) > max_items
    return {
        "project": {"scope": "authorized_project", "locator": {"workspace_id": str(workspace_id), "project_id": str(project_id)}},
        "freshness": deps.runtime_freshness(status_value, resources=freshness_resources),
        "resources": resource_cards,
        "graphs": graphs[:max_resources],
        "schema_hints": {
            "node_types": sample_counter(node_types, max_items),
            "edge_types": sample_counter(edge_types, max_items),
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


def get_graph_inventory(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    args: dict[str, Any],
    deps: RuntimeGraphDeps,
) -> dict[str, Any]:
    require_scope(principal, "project:query")
    require_scope(principal, "resource:read")
    kind = str(args.get("kind") or "all")
    query = str(args.get("query") or "").strip().lower()
    limit = deps.runtime_limit(args.get("limit"), default=100, max_value=100)
    offset = deps.runtime_cursor(args.get("cursor"))
    authorized_resource_graphs: list[dict[str, Any]] = []
    authorized_merge_graphs: list[dict[str, Any]] = []

    if kind in {"all", "resource"}:
        resource_rows = session.execute(
            select(Graph, GraphVersion, Resource)
            .join(GraphVersion, Graph.current_version_id == GraphVersion.id)
            .join(Resource, Graph.resource_id == Resource.id)
            .where(
                Graph.workspace_id == workspace_id,
                Graph.project_id == project_id,
                Graph.status == "active",
                GraphVersion.status == GRAPH_VERSION_PUBLISHED,
                Resource.deleted_at.is_(None),
                Resource.archived_at.is_(None),
            )
            .order_by(Graph.graph_key.asc())
        ).all()
        for graph, version, resource in resource_rows:
            if not token_allows_resource(principal, resource.id):
                continue
            if (
                query
                and query not in graph.graph_key.lower()
                and query not in graph.title.lower()
                and query not in resource.name.lower()
            ):
                continue
            authorized_resource_graphs.append(
                {
                    "graph_key": graph.graph_key,
                    "title": graph.title,
                    "resource_id": str(resource.id),
                    "resource_name": resource.name,
                    "current_version": version.version,
                    "node_count": version.node_count,
                    "edge_count": version.edge_count,
                    "freshness": (
                        "current"
                        if version.source_snapshot_id == resource.current_snapshot_id
                        else "stale"
                    ),
                    "graph_snapshot_id": str(version.source_snapshot_id),
                    "current_snapshot_id": (
                        str(resource.current_snapshot_id)
                        if resource.current_snapshot_id
                        else None
                    ),
                }
            )

    if kind in {"all", "merge"}:
        merge_rows = session.execute(
            select(GraphMerge, GraphMergeVersion)
            .join(GraphMergeVersion, GraphMerge.current_version_id == GraphMergeVersion.id)
            .where(
                GraphMerge.workspace_id == workspace_id,
                GraphMerge.project_id == project_id,
                GraphMerge.status == "active",
            )
            .order_by(GraphMerge.merge_key.asc())
        ).all()
        for merge, version in merge_rows:
            inputs = session.execute(
                select(GraphMergeInput, Resource)
                .join(Resource, GraphMergeInput.input_resource_id == Resource.id)
                .where(GraphMergeInput.graph_merge_version_id == version.id)
                .order_by(GraphMergeInput.ordinal.asc())
            ).all()
            resources = [resource for _input, resource in inputs]
            if not deps.runtime_resource_rows_allowed(
                principal, [resource.id for resource in resources]
            ):
                continue
            if query and query not in merge.merge_key.lower() and query not in merge.title.lower():
                continue
            stale_inputs = stale_merge_inputs(session, version)
            merge_is_stale = (
                version.status != GRAPH_MERGE_VERSION_PUBLISHED or bool(stale_inputs)
            )
            authorized_merge_graphs.append(
                {
                    "merge_key": merge.merge_key,
                    "title": merge.title,
                    "current_version": version.version,
                    "status": version.status,
                    "status_reason": version.status_reason,
                    "node_count": version.node_count,
                    "edge_count": version.edge_count,
                    "input_sources": [resource.name for resource in resources],
                    "freshness": "stale" if merge_is_stale else "current",
                    "stale_inputs": stale_inputs,
                }
            )

    resource_graphs = authorized_resource_graphs[offset : offset + limit]
    merge_graphs = authorized_merge_graphs[offset : offset + limit]
    has_more = (
        len(authorized_resource_graphs) > offset + limit
        or len(authorized_merge_graphs) > offset + limit
    )
    return {
        "resource_graphs": resource_graphs,
        "merge_graphs": merge_graphs,
        "next_cursor": str(offset + limit) if has_more else None,
    }


def resolve_graph_target(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any], deps: RuntimeGraphDeps) -> tuple[str, Graph | GraphMerge, GraphVersion | GraphMergeVersion]:
    key = str(args.get("graph_key") or "").strip()
    if not key:
        raise HTTPException(status_code=422, detail={"code": "missing_graph_key", "message": "graph_key is required"})
    kind = str(args.get("graph_kind") or "auto")
    version_number = args.get("version")
    if kind in {"auto", "resource"}:
        graph = session.scalar(select(Graph).where(Graph.workspace_id == workspace_id, Graph.project_id == project_id, Graph.graph_key == key, Graph.status == "active"))
        if graph is not None:
            deps.runtime_resource_allowed_or_404(principal, graph.resource_id)  # type: ignore[arg-type]
            if version_number is None:
                graph_version = session.scalar(select(GraphVersion).where(GraphVersion.id == graph.current_version_id, GraphVersion.status == GRAPH_VERSION_PUBLISHED))
            else:
                graph_version = session.scalar(select(GraphVersion).where(GraphVersion.graph_id == graph.id, GraphVersion.version == int(version_number), GraphVersion.status == GRAPH_VERSION_PUBLISHED))
            if graph_version is None:
                raise HTTPException(status_code=404, detail={"code": "graph_not_found", "message": "published graph version not found"})
            if version_number is None:
                resource = session.get(Resource, graph_version.resource_id)
                if resource is None or resource.current_snapshot_id != graph_version.source_snapshot_id:
                    raise HTTPException(status_code=409, detail={"code": "stale_resource_graph", "message": "published graph does not match the current resource snapshot", "graph_snapshot_id": str(graph_version.source_snapshot_id), "current_snapshot_id": str(resource.current_snapshot_id) if resource and resource.current_snapshot_id else None})
            return "resource", graph, graph_version
    if kind in {"auto", "merge"}:
        merge = session.scalar(select(GraphMerge).where(GraphMerge.workspace_id == workspace_id, GraphMerge.project_id == project_id, GraphMerge.merge_key == key, GraphMerge.status == "active"))
        if merge is not None:
            if version_number is None:
                merge_version = session.scalar(
                    select(GraphMergeVersion).where(
                        GraphMergeVersion.id == merge.current_version_id
                    )
                )
            else:
                merge_version = session.scalar(
                    select(GraphMergeVersion).where(
                        GraphMergeVersion.graph_merge_id == merge.id,
                        GraphMergeVersion.version == int(version_number),
                        GraphMergeVersion.status == GRAPH_MERGE_VERSION_PUBLISHED,
                    )
                )
            if merge_version is None:
                raise HTTPException(status_code=404, detail={"code": "graph_not_found", "message": "published merge graph version not found"})
            inputs = list(session.scalars(select(GraphMergeInput.input_resource_id).where(GraphMergeInput.graph_merge_version_id == merge_version.id)))
            if not deps.runtime_resource_rows_allowed(principal, inputs):
                raise HTTPException(status_code=404, detail={"code": "graph_not_found", "message": "published graph not found"})
            if version_number is None:
                stale_inputs = stale_merge_inputs(session, merge_version)
                if merge_version.status != GRAPH_MERGE_VERSION_PUBLISHED or stale_inputs:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "stale_merge_graph",
                            "message": "merge graph is invalidated or no longer matches current resource graphs",
                            "version_status": merge_version.status,
                            "status_reason": merge_version.status_reason,
                            "stale_inputs": stale_inputs,
                        },
                    )
            return "merge", merge, merge_version
    raise HTTPException(status_code=404, detail={"code": "graph_not_found", "message": "published graph not found"})


def graph_query(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any], deps: RuntimeGraphDeps) -> dict[str, Any]:
    require_scope(principal, "project:query")
    require_scope(principal, "resource:read")
    kind, graph, version = resolve_graph_target(session, workspace_id, project_id, principal, args, deps)
    limit = deps.runtime_limit(args.get("limit"), default=50, max_value=100)
    offset = deps.runtime_cursor(args.get("cursor"))
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
            freshness_resources.append(deps.runtime_resource_freshness(session, resource, resource_version.source_snapshot_id))
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
        freshness_resources = [deps.runtime_resource_freshness(session, resource, input_row.input_source_snapshot_id) for input_row, resource in inputs]
        next_cursor = str(offset + limit) if len(merge_node_rows) > limit else None
        graph_key = merge_graph.merge_key
        graph_title = merge_graph.title
    return {"graph": {"key": graph_key, "kind": kind, "version": version.version, "status": version.status, "title": graph_title}, "freshness": deps.runtime_freshness("current", resources=freshness_resources, graph={"graph_key": graph_key, "kind": kind, "version": version.version, "status": version.status}), "nodes": nodes, "edges": edges, "next_cursor": next_cursor, "truncated": next_cursor is not None}


def graph_path(session: Session, workspace_id: UUID, project_id: UUID, principal: Principal, args: dict[str, Any], deps: RuntimeGraphDeps) -> dict[str, Any]:
    require_scope(principal, "project:query")
    require_scope(principal, "resource:read")
    kind, graph, version = resolve_graph_target(session, workspace_id, project_id, principal, args, deps)
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
    return {"graph": {"key": merge_graph.merge_key, "kind": "merge", "version": merge_version.version, "status": merge_version.status}, "freshness": deps.runtime_freshness("current", graph={"graph_key": merge_graph.merge_key, "kind": "merge", "version": merge_version.version, "status": merge_version.status}), **path_result, "truncated": False}
