from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from sourcebrief_shared.models import (
    Graph,
    GraphEdge,
    GraphNode,
    GraphVersion,
    Resource,
    SourceSnapshot,
)

GRAPH_STATUS_ACTIVE = "active"
GRAPH_STATUS_ARCHIVED = "archived"
GRAPH_VERSION_DRAFT = "draft"
GRAPH_VERSION_PUBLISHED = "published"
GRAPH_VERSION_SUPERSEDED = "superseded"
GRAPH_VERSION_INVALIDATED = "invalidated"
RESERVED_GRAPH_KEYS = {"new", "api", "admin", "merge", "project", "graphs"}


@dataclass(frozen=True)
class GraphCompileResult:
    graph: Graph
    version: GraphVersion
    unchanged: bool


def _sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def slugify_graph_key(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    slug = re.sub(r"-+", "-", slug)
    if not slug:
        slug = "resource"
    if not slug.endswith("-graph"):
        slug = f"{slug}-graph"
    slug = slug[:63].strip("-")
    if len(slug) < 3:
        slug = f"{slug}-graph"
    if slug in RESERVED_GRAPH_KEYS:
        raise ValueError(f"reserved graph key: {slug}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,62}", slug):
        raise ValueError("graph key must be a slug of 3-63 lowercase letters, numbers, or hyphens")
    return slug


def _unique_graph_key(session: Session, resource: Resource, requested: str | None = None) -> str:
    base = slugify_graph_key(requested or resource.name)
    existing = set(
        session.scalars(
            select(Graph.graph_key).where(
                Graph.workspace_id == resource.workspace_id,
                Graph.project_id == resource.project_id,
                Graph.graph_key.like(f"{base}%"),
            )
        )
    )
    if base not in existing:
        return base
    for suffix in range(2, 100):
        candidate = f"{base[:60]}-{suffix}"[:63].strip("-")
        if candidate not in existing:
            return candidate
    raise ValueError("could not allocate a unique graph key")


def _ordered_node_payloads(session: Session, resource: Resource, snapshot_id: UUID) -> list[dict[str, Any]]:
    nodes = list(
        session.scalars(
            select(GraphNode)
            .where(
                GraphNode.workspace_id == resource.workspace_id,
                GraphNode.project_id == resource.project_id,
                GraphNode.resource_id == resource.id,
                GraphNode.source_snapshot_id == snapshot_id,
            )
            .order_by(GraphNode.node_key.asc(), GraphNode.id.asc())
        )
    )
    return [
        {
            "id": str(node.id),
            "node_key": node.node_key,
            "node_type": node.node_type,
            "label": node.label,
            "path": node.path,
            "metadata": node.meta,
        }
        for node in nodes
    ]


def _ordered_edge_payloads(session: Session, resource: Resource, snapshot_id: UUID) -> list[dict[str, Any]]:
    edges = list(
        session.scalars(
            select(GraphEdge)
            .where(
                GraphEdge.workspace_id == resource.workspace_id,
                GraphEdge.project_id == resource.project_id,
                GraphEdge.resource_id == resource.id,
                GraphEdge.source_snapshot_id == snapshot_id,
            )
            .order_by(GraphEdge.edge_type.asc(), GraphEdge.source_node_id.asc(), GraphEdge.target_node_id.asc(), GraphEdge.id.asc())
        )
    )
    return [
        {
            "id": str(edge.id),
            "source_node_id": str(edge.source_node_id),
            "target_node_id": str(edge.target_node_id),
            "edge_type": edge.edge_type,
            "weight": edge.weight,
            "metadata": edge.meta,
        }
        for edge in edges
    ]


def compile_graph_version(session: Session, resource: Resource, *, actor_id: UUID | None, requested_graph_key: str | None = None, title: str | None = None) -> GraphCompileResult:
    if resource.current_snapshot_id is None:
        raise ValueError("resource has no current snapshot")
    # Serialize first graph creation for this resource.
    session.scalar(select(Resource).where(Resource.id == resource.id).with_for_update())
    graph = session.scalar(
        select(Graph)
        .where(Graph.workspace_id == resource.workspace_id, Graph.project_id == resource.project_id, Graph.resource_id == resource.id)
        .with_for_update()
    )
    if graph is None:
        graph = Graph(
            workspace_id=resource.workspace_id,
            project_id=resource.project_id,
            resource_id=resource.id,
            graph_key=_unique_graph_key(session, resource, requested_graph_key),
            title=title or f"{resource.name} Graph",
            graph_type="resource",
            status=GRAPH_STATUS_ACTIVE,
            created_by=actor_id,
        )
        session.add(graph)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            graph = session.scalar(
                select(Graph)
                .where(Graph.workspace_id == resource.workspace_id, Graph.project_id == resource.project_id, Graph.resource_id == resource.id)
                .with_for_update()
            )
            if graph is None:
                raise
    elif graph.status == GRAPH_STATUS_ARCHIVED:
        raise ValueError("archived graphs cannot compile new versions")

    snapshot = session.get(SourceSnapshot, resource.current_snapshot_id)
    if snapshot is None:
        raise ValueError("resource current snapshot is missing")
    node_payloads = _ordered_node_payloads(session, resource, resource.current_snapshot_id)
    edge_payloads = _ordered_edge_payloads(session, resource, resource.current_snapshot_id)
    node_hash = _sha256_json(node_payloads)
    edge_hash = _sha256_json(edge_payloads)
    membership = {
        "mode": "resource_snapshot",
        "resource_id": str(resource.id),
        "source_snapshot_id": str(resource.current_snapshot_id),
        "node_count": len(node_payloads),
        "edge_count": len(edge_payloads),
        "node_hash": node_hash,
        "edge_hash": edge_hash,
    }
    provenance = {
        "resource": {"id": str(resource.id), "name": resource.name, "type": resource.type, "uri": resource.uri},
        "source_snapshot": {
            "id": str(snapshot.id),
            "version": snapshot.version,
            "version_kind": snapshot.version_kind,
            "indexed_at": snapshot.indexed_at.isoformat() if snapshot.indexed_at else None,
        },
    }
    validation_warnings = []
    if not node_payloads and not edge_payloads:
        validation_warnings.append({"code": "empty_graph", "message": "Current snapshot has no graph rows; version is still publishable as explicit empty graph provenance."})
    summary = {
        "title": graph.title,
        "graph_key": graph.graph_key,
        "resource": provenance["resource"],
        "source_snapshot": provenance["source_snapshot"],
        "node_count": len(node_payloads),
        "edge_count": len(edge_payloads),
        "node_types": sorted({node["node_type"] for node in node_payloads}),
        "edge_types": sorted({edge["edge_type"] for edge in edge_payloads}),
    }
    version_hash = _sha256_json({"graph_key": graph.graph_key, "membership": membership, "provenance": provenance})
    latest_draft = session.scalar(
        select(GraphVersion)
        .where(GraphVersion.graph_id == graph.id, GraphVersion.status == GRAPH_VERSION_DRAFT)
        .order_by(GraphVersion.version.desc())
        .limit(1)
    )
    if latest_draft and latest_draft.version_hash == version_hash:
        return GraphCompileResult(graph=graph, version=latest_draft, unchanged=True)
    next_version = int(session.scalar(select(func.coalesce(func.max(GraphVersion.version), 0)).where(GraphVersion.graph_id == graph.id)) or 0) + 1
    version = GraphVersion(
        workspace_id=resource.workspace_id,
        project_id=resource.project_id,
        graph_id=graph.id,
        resource_id=resource.id,
        source_snapshot_id=resource.current_snapshot_id,
        version=next_version,
        status=GRAPH_VERSION_DRAFT,
        version_hash=version_hash,
        node_count=len(node_payloads),
        edge_count=len(edge_payloads),
        membership_json=membership,
        provenance_json=provenance,
        summary_json=summary,
        validation_json={"ok": True, "warnings": validation_warnings},
        created_by=actor_id,
    )
    session.add(version)
    session.flush()
    return GraphCompileResult(graph=graph, version=version, unchanged=False)
