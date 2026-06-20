from __future__ import annotations

import hashlib
import json
import os
import re
from collections import deque
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

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

GRAPH_MERGE_STATUS_ACTIVE = "active"
GRAPH_MERGE_STATUS_ARCHIVED = "archived"
GRAPH_MERGE_VERSION_DRAFT = "draft"
GRAPH_MERGE_VERSION_PUBLISHED = "published"
GRAPH_MERGE_VERSION_SUPERSEDED = "superseded"
GRAPH_MERGE_VERSION_INVALIDATED = "invalidated"
STRATEGIES = {"union", "overlay"}
RESERVED_MERGE_KEYS = {"new", "api", "admin", "merge", "project", "graphs", "graph"}


def _limit(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def max_merge_inputs() -> int:
    return _limit("SOURCEBRIEF_GRAPH_MERGE_MAX_INPUTS", 8)


def max_merge_nodes() -> int:
    return _limit("SOURCEBRIEF_GRAPH_MERGE_MAX_NODES", 10_000)


def max_merge_edges() -> int:
    return _limit("SOURCEBRIEF_GRAPH_MERGE_MAX_EDGES", 25_000)


def max_merge_candidates() -> int:
    return _limit("SOURCEBRIEF_GRAPH_MERGE_MAX_CANDIDATES", 5_000)


def max_path_depth() -> int:
    return _limit("SOURCEBRIEF_GRAPH_MERGE_MAX_PATH_DEPTH", 6)


def max_path_visited_edges() -> int:
    return _limit("SOURCEBRIEF_GRAPH_MERGE_MAX_PATH_VISITED_EDGES", 5_000)


@dataclass(frozen=True)
class MergeInputRef:
    graph_key: str | None = None
    version: int | None = None
    graph_version_id: UUID | None = None


@dataclass(frozen=True)
class GraphMergeCompileResult:
    merge: GraphMerge
    version: GraphMergeVersion
    unchanged: bool


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def slugify_merge_key(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    if not slug:
        slug = "graph-merge"
    if not slug.endswith("-merge"):
        slug = f"{slug}-merge"
    slug = slug[:63].strip("-")
    if slug in RESERVED_MERGE_KEYS:
        raise ValueError(f"reserved merge key: {slug}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,62}", slug):
        raise ValueError("merge key must be a slug of 3-63 lowercase letters, numbers, or hyphens")
    return slug


def _unique_merge_key(session: Session, workspace_id: UUID, project_id: UUID, requested: str | None, title: str) -> str:
    base = slugify_merge_key(requested or title)
    existing = set(
        session.scalars(
            select(GraphMerge.merge_key).where(
                GraphMerge.workspace_id == workspace_id,
                GraphMerge.project_id == project_id,
                GraphMerge.merge_key.like(f"{base}%"),
            )
        )
    )
    if base not in existing:
        return base
    for suffix in range(2, 100):
        candidate = f"{base[:60]}-{suffix}"[:63].strip("-")
        if candidate not in existing:
            return candidate
    raise ValueError("could not allocate a unique merge key")


def _resolve_input_versions(session: Session, workspace_id: UUID, project_id: UUID, refs: list[MergeInputRef]) -> list[tuple[Graph, GraphVersion, Resource]]:
    if len(refs) < 2:
        raise ValueError("graph merge requires at least two input graph versions")
    if len(refs) > max_merge_inputs():
        raise OverflowError("too_many_inputs")
    resolved: list[tuple[Graph, GraphVersion, Resource]] = []
    seen_resources: set[UUID] = set()
    seen_graphs: set[UUID] = set()
    for ref in refs:
        if ref.graph_version_id:
            version = session.get(GraphVersion, ref.graph_version_id)
            if version is None or version.workspace_id != workspace_id or version.project_id != project_id:
                raise ValueError("input graph version not found")
            graph = session.get(Graph, version.graph_id)
        else:
            if not ref.graph_key or not ref.version:
                raise ValueError("each input needs graph_version_id or graph_key+version")
            graph = session.scalar(select(Graph).where(Graph.workspace_id == workspace_id, Graph.project_id == project_id, Graph.graph_key == ref.graph_key))
            if graph is None:
                raise ValueError("input graph not found")
            version = session.scalar(select(GraphVersion).where(GraphVersion.graph_id == graph.id, GraphVersion.version == ref.version))
        if graph is None or version is None:
            raise ValueError("input graph version not found")
        if graph.status != "active" or graph.graph_type != "resource":
            raise ValueError("input graph must be an active resource graph")
        if version.status != GRAPH_MERGE_VERSION_PUBLISHED:
            raise ValueError("input graph version must be published")
        if version.resource_id in seen_resources or graph.id in seen_graphs:
            raise ValueError("merge inputs cannot include multiple versions from the same resource or graph")
        resource = session.get(Resource, version.resource_id)
        if resource is None or resource.deleted_at is not None or resource.status in {"deleted", "archived"}:
            raise ValueError("input resource is deleted or archived")
        seen_resources.add(version.resource_id)
        seen_graphs.add(graph.id)
        resolved.append((graph, version, resource))
    return resolved


def _origin_for_node(ordinal: int, graph: Graph, version: GraphVersion, resource: Resource, node: GraphNode) -> dict[str, Any]:
    return {
        "input_ordinal": ordinal,
        "graph_key": graph.graph_key,
        "graph_version": version.version,
        "graph_version_id": str(version.id),
        "resource_id": str(resource.id),
        "resource_name": resource.name,
        "source_snapshot_id": str(version.source_snapshot_id),
        "node_id": str(node.id),
        "node_key": node.node_key,
        "label": node.label,
        "path": node.path,
        "node_type": node.node_type,
    }


def _merged_node_key(ordinal: int, node: GraphNode) -> str:
    return f"src:{ordinal}:{hashlib.sha256(node.node_key.encode('utf-8')).hexdigest()[:20]}"


def _normalize(value: str | None) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _candidate_key(candidate_type: str, left_key: str, right_key: str) -> str:
    pair = ":".join(sorted([left_key, right_key]))
    return f"{candidate_type}:{hashlib.sha256(pair.encode('utf-8')).hexdigest()[:32]}"


def compile_graph_merge(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    actor_id: UUID | None,
    inputs: list[MergeInputRef],
    strategy: str,
    merge_key: str | None,
    title: str,
    description: str | None = None,
) -> GraphMergeCompileResult:
    if strategy not in STRATEGIES:
        raise ValueError("merge strategy must be union or overlay")
    resolved = _resolve_input_versions(session, workspace_id, project_id, inputs)
    input_payload = [
        {
            "ordinal": idx,
            "graph_id": str(graph.id),
            "graph_key": graph.graph_key,
            "version_id": str(version.id),
            "version": version.version,
            "version_hash": version.version_hash,
            "resource_id": str(version.resource_id),
            "source_snapshot_id": str(version.source_snapshot_id),
        }
        for idx, (graph, version, _resource) in enumerate(resolved)
    ]
    input_hash = sha256_json({"strategy": strategy, "inputs": input_payload})

    key = slugify_merge_key(merge_key or title)
    merge = session.scalar(select(GraphMerge).where(GraphMerge.workspace_id == workspace_id, GraphMerge.project_id == project_id, GraphMerge.merge_key == key).with_for_update())
    if merge is None:
        merge = GraphMerge(workspace_id=workspace_id, project_id=project_id, merge_key=_unique_merge_key(session, workspace_id, project_id, key, title), title=title, description=description, status=GRAPH_MERGE_STATUS_ACTIVE, created_by=actor_id)
        session.add(merge)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            merge = session.scalar(select(GraphMerge).where(GraphMerge.workspace_id == workspace_id, GraphMerge.project_id == project_id, GraphMerge.merge_key == key).with_for_update())
            if merge is None:
                raise
    elif merge.status == GRAPH_MERGE_STATUS_ARCHIVED:
        raise ValueError("archived graph merges cannot compile new versions")

    node_rows: list[GraphMergeNode] = []
    edge_rows: list[GraphMergeEdge] = []
    candidate_rows: list[GraphMergeReconcileCandidate] = []
    original_to_merged: dict[UUID, str] = {}
    candidate_truncated = False
    all_node_payloads: list[dict[str, Any]] = []
    all_edge_payloads: list[dict[str, Any]] = []
    per_input_nodes: list[tuple[int, Graph, GraphVersion, Resource, list[tuple[GraphNode, str, dict[str, Any]]]]] = []

    for ordinal, (graph, version, resource) in enumerate(resolved):
        nodes = list(
            session.scalars(
                select(GraphNode)
                .where(
                    GraphNode.workspace_id == workspace_id,
                    GraphNode.project_id == project_id,
                    GraphNode.resource_id == version.resource_id,
                    GraphNode.source_snapshot_id == version.source_snapshot_id,
                )
                .order_by(GraphNode.node_key.asc(), GraphNode.id.asc())
            )
        )
        if len(all_node_payloads) + len(nodes) > max_merge_nodes():
            raise MemoryError("merge_node_limit_exceeded")
        node_triplets: list[tuple[GraphNode, str, dict[str, Any]]] = []
        for node in nodes:
            merged_key = _merged_node_key(ordinal, node)
            original_to_merged[node.id] = merged_key
            origin = _origin_for_node(ordinal, graph, version, resource, node)
            metadata = dict(node.meta or {})
            if strategy == "overlay" and node.path:
                metadata["overlay_group"] = f"path:{_normalize(node.path)}"
            node_triplets.append((node, merged_key, origin))
            all_node_payloads.append({"key": merged_key, "type": node.node_type, "label": node.label, "path": node.path, "origin": origin})
        per_input_nodes.append((ordinal, graph, version, resource, node_triplets))

    for ordinal, graph, version, resource, node_triplets in per_input_nodes:
        for node, merged_key, origin in node_triplets:
            node_rows.append(
                GraphMergeNode(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    graph_merge_version_id=None,  # type: ignore[arg-type]
                    merged_node_key=merged_key,
                    node_type=node.node_type,
                    label=node.label,
                    path=node.path,
                    display_label=f"{node.label} · {resource.name}",
                    origin_json=[origin],
                    meta={**(node.meta or {}), **({"overlay_group": f"path:{_normalize(node.path)}"} if strategy == "overlay" and node.path else {})},
                )
            )
        edges = list(
            session.scalars(
                select(GraphEdge)
                .where(
                    GraphEdge.workspace_id == workspace_id,
                    GraphEdge.project_id == project_id,
                    GraphEdge.resource_id == version.resource_id,
                    GraphEdge.source_snapshot_id == version.source_snapshot_id,
                )
                .order_by(GraphEdge.edge_type.asc(), GraphEdge.source_node_id.asc(), GraphEdge.target_node_id.asc())
            )
        )
        if len(all_edge_payloads) + len(edges) > max_merge_edges():
            raise MemoryError("merge_edge_limit_exceeded")
        for edge in edges:
            source_key = original_to_merged.get(edge.source_node_id)
            target_key = original_to_merged.get(edge.target_node_id)
            if not source_key or not target_key:
                continue
            origin = {
                "input_ordinal": ordinal,
                "graph_key": graph.graph_key,
                "graph_version": version.version,
                "graph_version_id": str(version.id),
                "resource_id": str(resource.id),
                "resource_name": resource.name,
                "source_snapshot_id": str(version.source_snapshot_id),
                "edge_id": str(edge.id),
                "edge_type": edge.edge_type,
            }
            all_edge_payloads.append({"source": source_key, "target": target_key, "edge_type": edge.edge_type, "origin": origin})
            edge_rows.append(
                GraphMergeEdge(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    graph_merge_version_id=None,  # type: ignore[arg-type]
                    source_merged_node_key=source_key,
                    target_merged_node_key=target_key,
                    edge_type=edge.edge_type,
                    weight=edge.weight,
                    origin_json=[origin],
                    meta=edge.meta or {},
                )
            )

    candidate_seen: set[str] = set()
    flat_nodes = [(node, merged_key, origin) for *_prefix, triplets in per_input_nodes for node, merged_key, origin in triplets]
    for idx, (left_node, left_key, left_origin) in enumerate(flat_nodes):
        for right_node, right_key, right_origin in flat_nodes[idx + 1 :]:
            if left_origin["resource_id"] == right_origin["resource_id"]:
                continue
            candidate_type = None
            confidence = 0.0
            if left_node.path and right_node.path and _normalize(left_node.path) == _normalize(right_node.path):
                candidate_type = "same_path"
                confidence = 0.9
            elif _normalize(left_node.label) and _normalize(left_node.label) == _normalize(right_node.label) and left_node.node_type == right_node.node_type:
                candidate_type = "same_label"
                confidence = 0.6
            if candidate_type is None:
                continue
            key_candidate = _candidate_key(candidate_type, left_key, right_key)
            if key_candidate in candidate_seen:
                continue
            candidate_seen.add(key_candidate)
            if len(candidate_rows) >= max_merge_candidates():
                candidate_truncated = True
                break
            candidate_rows.append(
                GraphMergeReconcileCandidate(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    graph_merge_version_id=None,  # type: ignore[arg-type]
                    candidate_key=key_candidate,
                    candidate_type=candidate_type,
                    left_origin_json=left_origin,
                    right_origin_json=right_origin,
                    confidence=confidence,
                    status="open",
                )
            )
        if candidate_truncated:
            break

    version_hash = sha256_json({"merge_key": merge.merge_key, "strategy": strategy, "inputs": input_payload, "nodes": all_node_payloads, "edges": all_edge_payloads, "candidate_keys": sorted(candidate_seen)})
    latest_draft = session.scalar(select(GraphMergeVersion).where(GraphMergeVersion.graph_merge_id == merge.id, GraphMergeVersion.status == GRAPH_MERGE_VERSION_DRAFT).order_by(GraphMergeVersion.version.desc()).limit(1))
    if latest_draft and latest_draft.version_hash == version_hash and latest_draft.input_hash == input_hash:
        return GraphMergeCompileResult(merge=merge, version=latest_draft, unchanged=True)

    next_version = int(session.scalar(select(func.coalesce(func.max(GraphMergeVersion.version), 0)).where(GraphMergeVersion.graph_merge_id == merge.id)) or 0) + 1
    validation = {"ok": True, "candidate_truncated": candidate_truncated, "limits": {"max_inputs": max_merge_inputs(), "max_nodes": max_merge_nodes(), "max_edges": max_merge_edges(), "max_candidates": max_merge_candidates()}}
    merge_version = GraphMergeVersion(
        workspace_id=workspace_id,
        project_id=project_id,
        graph_merge_id=merge.id,
        version=next_version,
        status=GRAPH_MERGE_VERSION_DRAFT,
        merge_strategy=strategy,
        version_hash=version_hash,
        input_hash=input_hash,
        node_count=len(node_rows),
        edge_count=len(edge_rows),
        candidate_count=len(candidate_rows),
        unresolved_candidate_count=len(candidate_rows),
        summary_json={"title": merge.title, "merge_key": merge.merge_key, "strategy": strategy, "input_count": len(resolved), "node_count": len(node_rows), "edge_count": len(edge_rows), "candidate_count": len(candidate_rows), "candidate_truncated": candidate_truncated},
        validation_json=validation,
        created_by=actor_id,
    )
    session.add(merge_version)
    session.flush()
    for ordinal, (graph, input_version, _resource) in enumerate(resolved):
        session.add(
            GraphMergeInput(
                workspace_id=workspace_id,
                project_id=project_id,
                graph_merge_version_id=merge_version.id,
                input_graph_id=graph.id,
                input_graph_version_id=input_version.id,
                input_resource_id=input_version.resource_id,
                input_source_snapshot_id=input_version.source_snapshot_id,
                ordinal=ordinal,
                input_version_hash=input_version.version_hash,
            )
        )
    for node_row in node_rows:
        node_row.graph_merge_version_id = merge_version.id
        session.add(node_row)
    session.flush()
    for edge_row in edge_rows:
        edge_row.graph_merge_version_id = merge_version.id
        session.add(edge_row)
    for candidate_row in candidate_rows:
        candidate_row.graph_merge_version_id = merge_version.id
        session.add(candidate_row)
    return GraphMergeCompileResult(merge=merge, version=merge_version, unchanged=False)


def find_path(session: Session, version: GraphMergeVersion, from_node_key: str, to_node_key: str, max_depth: int) -> dict[str, Any]:
    if max_depth > max_path_depth():
        raise ValueError("path_depth_limit_exceeded")
    edges = list(session.scalars(select(GraphMergeEdge).where(GraphMergeEdge.graph_merge_version_id == version.id)))
    adjacency: dict[str, list[GraphMergeEdge]] = {}
    for edge in edges:
        adjacency.setdefault(edge.source_merged_node_key, []).append(edge)
    queue: deque[tuple[str, list[GraphMergeEdge], int]] = deque([(from_node_key, [], 0)])
    seen = {from_node_key}
    visited_edges = 0
    while queue:
        node_key, path_edges, depth = queue.popleft()
        if node_key == to_node_key:
            node_keys = [from_node_key]
            for edge in path_edges:
                node_keys.append(edge.target_merged_node_key)
            nodes = list(session.scalars(select(GraphMergeNode).where(GraphMergeNode.graph_merge_version_id == version.id, GraphMergeNode.merged_node_key.in_(node_keys))))
            node_map = {node.merged_node_key: node for node in nodes}
            return {"found": True, "nodes": [{"key": key, "label": node_map[key].display_label, "origin": node_map[key].origin_json} for key in node_keys if key in node_map], "edges": [{"source": edge.source_merged_node_key, "target": edge.target_merged_node_key, "edge_type": edge.edge_type, "origin": edge.origin_json} for edge in path_edges]}
        if depth >= max_depth:
            continue
        for edge in adjacency.get(node_key, []):
            visited_edges += 1
            if visited_edges > max_path_visited_edges():
                raise OverflowError("path_search_limit_exceeded")
            if edge.target_merged_node_key in seen:
                continue
            seen.add(edge.target_merged_node_key)
            queue.append((edge.target_merged_node_key, [*path_edges, edge], depth + 1))
    return {"found": False, "nodes": [], "edges": []}
