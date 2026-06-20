from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from sqlalchemy.orm import Session

from sourcebrief_shared.code_intel import extract_code_symbols
from sourcebrief_shared.models import GraphEdge, GraphNode, Resource, SourceSnapshot


@dataclass(frozen=True)
class GraphBuildStats:
    nodes_created: int
    edges_created: int


def _file_label(path: str | None, title: str | None) -> str:
    return path or title or "document"


def _dir_parts(path: str | None) -> list[str]:
    if not path or "/" not in path:
        return []
    pure = PurePosixPath(path)
    parts: list[str] = []
    current = ""
    for part in pure.parts[:-1]:
        current = part if not current else f"{current}/{part}"
        parts.append(current)
    return parts


def _node(
    session: Session,
    *,
    resource: Resource,
    snapshot: SourceSnapshot,
    node_key: str,
    node_type: str,
    label: str,
    path: str | None = None,
    meta: dict | None = None,
) -> GraphNode:
    node = GraphNode(
        workspace_id=resource.workspace_id,
        project_id=resource.project_id,
        resource_id=resource.id,
        source_snapshot_id=snapshot.id,
        node_key=node_key,
        node_type=node_type,
        label=label,
        path=path,
        meta=meta or {},
    )
    session.add(node)
    session.flush()
    return node


def _edge(
    session: Session,
    *,
    resource: Resource,
    snapshot: SourceSnapshot,
    source: GraphNode,
    target: GraphNode,
    edge_type: str,
    weight: float = 1.0,
    meta: dict | None = None,
) -> GraphEdge:
    edge = GraphEdge(
        workspace_id=resource.workspace_id,
        project_id=resource.project_id,
        resource_id=resource.id,
        source_snapshot_id=snapshot.id,
        source_node_id=source.id,
        target_node_id=target.id,
        edge_type=edge_type,
        weight=weight,
        meta=meta or {},
    )
    session.add(edge)
    session.flush()
    return edge


def build_graph_index(session: Session, resource: Resource, snapshot: SourceSnapshot, docs: list[dict]) -> GraphBuildStats:
    """Build a deterministic repo/document graph for one resource snapshot.

    This is intentionally not a full Graphify/LightRAG clone. It gives SourceBrief
    a production-shaped graph substrate: resource → directories → files → symbols,
    plus sibling file/symbol edges that can be used as a graph retrieval signal.
    """
    nodes_created = 0
    edges_created = 0
    resource_node = _node(
        session,
        resource=resource,
        snapshot=snapshot,
        node_key=f"resource:{resource.id}",
        node_type="resource",
        label=resource.name,
        path=None,
        meta={"uri": resource.uri, "resource_type": resource.type},
    )
    nodes_created += 1

    directory_nodes: dict[str, GraphNode] = {}
    file_nodes: dict[str, GraphNode] = {}
    for doc in docs:
        path = _file_label(doc.get("path"), doc.get("title"))
        parent = resource_node
        for directory in _dir_parts(path):
            node = directory_nodes.get(directory)
            if node is None:
                node = _node(
                    session,
                    resource=resource,
                    snapshot=snapshot,
                    node_key=f"dir:{directory}",
                    node_type="directory",
                    label=directory,
                    path=directory,
                    meta={"source": doc.get("meta", {}).get("source")},
                )
                directory_nodes[directory] = node
                nodes_created += 1
                _edge(session, resource=resource, snapshot=snapshot, source=parent, target=node, edge_type="contains")
                edges_created += 1
            parent = node

        file_node = _node(
            session,
            resource=resource,
            snapshot=snapshot,
            node_key=f"file:{path}",
            node_type="file",
            label=path,
            path=path,
            meta=doc.get("meta", {}),
        )
        file_nodes[path] = file_node
        nodes_created += 1
        _edge(session, resource=resource, snapshot=snapshot, source=parent, target=file_node, edge_type="contains")
        edges_created += 1

        for symbol in extract_code_symbols(doc.get("path"), doc["content"]):
            symbol_node = _node(
                session,
                resource=resource,
                snapshot=snapshot,
                node_key=f"symbol:{path}:{symbol.name}:{symbol.line_start}",
                node_type="symbol",
                label=symbol.name,
                path=path,
                meta={
                    "kind": symbol.kind,
                    "language": symbol.language,
                    "line_start": symbol.line_start,
                    "line_end": symbol.line_end,
                    "signature": symbol.signature,
                },
            )
            nodes_created += 1
            _edge(
                session,
                resource=resource,
                snapshot=snapshot,
                source=file_node,
                target=symbol_node,
                edge_type="defines",
                weight=2.0,
            )
            edges_created += 1
    by_directory: dict[str, list[GraphNode]] = {}
    for path, file_node in file_nodes.items():
        directory_parent = str(PurePosixPath(path).parent)
        if directory_parent == ".":
            directory_parent = ""
        by_directory.setdefault(directory_parent, []).append(file_node)
    for siblings in by_directory.values():
        for left, right in zip(siblings, siblings[1:], strict=False):
            _edge(
                session,
                resource=resource,
                snapshot=snapshot,
                source=left,
                target=right,
                edge_type="sibling",
                weight=0.25,
            )
            edges_created += 1

    return GraphBuildStats(nodes_created=nodes_created, edges_created=edges_created)
