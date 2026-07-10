from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal, require_principal, require_scope
from sourcebrief_api.graph_merges import (
    GRAPH_MERGE_STATUS_ARCHIVED,
    GRAPH_MERGE_VERSION_DRAFT,
    GRAPH_MERGE_VERSION_INVALIDATED,
    GRAPH_MERGE_VERSION_PUBLISHED,
    GRAPH_MERGE_VERSION_SUPERSEDED,
    MergeInputRef,
    compile_graph_merge,
    find_path,
)
from sourcebrief_api.graph_versions import (
    GRAPH_STATUS_ARCHIVED,
    GRAPH_VERSION_INVALIDATED,
    compile_graph_version,
    publish_graph_version_record,
)
from sourcebrief_api.schemas import (
    GraphCompileRequest,
    GraphCompileResponse,
    GraphEdgeRead,
    GraphMergeCandidateReviewRequest,
    GraphMergeCompileRequest,
    GraphMergeDataRead,
    GraphMergePathRead,
    GraphMergeRead,
    GraphMergeReviewRequest,
    GraphMergeVersionRead,
    GraphNodeRead,
    GraphRead,
    GraphReviewRequest,
    GraphStreamRead,
    GraphVersionRead,
)
from sourcebrief_shared.db import get_session
from sourcebrief_shared.models import (
    AuditEvent,
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

ProjectAccessAuthorizer = Callable[[Session, UUID, UUID, Principal], object]
ProjectMemberAuthorizer = Callable[..., object]
ResourceResolver = Callable[..., Resource]
ReviewWriteAuthorizer = Callable[[Session, UUID, UUID, Principal], None]


@dataclass(frozen=True)
class GraphRouterDeps:
    require_project_access: ProjectAccessAuthorizer
    require_project_member: ProjectMemberAuthorizer
    resolve_resource: ResourceResolver
    require_review_write: ReviewWriteAuthorizer


def graph_version_read(version: GraphVersion) -> GraphVersionRead:
    return GraphVersionRead(
        id=version.id,
        graph_id=version.graph_id,
        resource_id=version.resource_id,
        source_snapshot_id=version.source_snapshot_id,
        version=version.version,
        status=version.status,
        version_hash=version.version_hash,
        node_count=version.node_count,
        edge_count=version.edge_count,
        membership_json=version.membership_json,
        provenance_json=version.provenance_json,
        summary_json=version.summary_json,
        validation_json=version.validation_json,
        status_reason=version.status_reason,
        published_at=version.published_at,
        invalidated_at=version.invalidated_at,
        created_at=version.created_at,
    )


def graph_stream_read(session: Session, graph: Graph) -> GraphStreamRead:
    versions = list(
        session.scalars(
            select(GraphVersion)
            .where(GraphVersion.graph_id == graph.id)
            .order_by(GraphVersion.version.desc())
        )
    )
    current = next(
        (version for version in versions if version.id == graph.current_version_id), None
    )
    return GraphStreamRead(
        id=graph.id,
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        resource_id=graph.resource_id,
        graph_key=graph.graph_key,
        title=graph.title,
        description=graph.description,
        graph_type=graph.graph_type,
        status=graph.status,
        current_version_id=graph.current_version_id,
        current=graph_version_read(current) if current else None,
        versions=[graph_version_read(version) for version in versions],
        created_at=graph.created_at,
        updated_at=graph.updated_at,
    )


def resolve_graph(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    graph_key: str,
    *,
    for_update: bool = False,
) -> Graph:
    stmt = select(Graph).where(
        Graph.workspace_id == workspace_id,
        Graph.project_id == project_id,
        Graph.graph_key == graph_key,
    )
    if for_update:
        stmt = stmt.with_for_update()
    graph = session.scalar(stmt)
    if graph is None:
        raise HTTPException(status_code=404, detail="graph not found")
    return graph


def require_graph_read(
    session: Session, graph: Graph, principal: Principal, deps: GraphRouterDeps
) -> Resource | None:
    require_scope(principal, "resource:read")
    deps.require_project_access(session, graph.workspace_id, graph.project_id, principal)
    if graph.resource_id is None:
        if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
            raise HTTPException(status_code=404, detail="graph not found")
        return None
    return deps.resolve_resource(
        session,
        graph.workspace_id,
        graph.project_id,
        graph.resource_id,
        principal,
        include_deleted=True,
    )


def require_graph_review_write(
    session: Session, graph: Graph, principal: Principal, deps: GraphRouterDeps
) -> Resource | None:
    deps.require_review_write(session, graph.workspace_id, graph.project_id, principal)
    if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
        raise HTTPException(
            status_code=403, detail="resource-scoped tokens cannot mutate graph lifecycle"
        )
    if graph.resource_id is None:
        return None
    return deps.resolve_resource(
        session,
        graph.workspace_id,
        graph.project_id,
        graph.resource_id,
        principal,
        include_deleted=True,
    )


def assert_graph_active(graph: Graph) -> None:
    if graph.status == GRAPH_STATUS_ARCHIVED:
        raise HTTPException(
            status_code=422, detail="archived graphs cannot compile or publish versions"
        )


def graph_merge_version_read(version: GraphMergeVersion) -> GraphMergeVersionRead:
    return GraphMergeVersionRead.model_validate(version)


def graph_merge_read(session: Session, merge: GraphMerge) -> GraphMergeRead:
    versions = list(
        session.scalars(
            select(GraphMergeVersion)
            .where(GraphMergeVersion.graph_merge_id == merge.id)
            .order_by(GraphMergeVersion.version.desc())
        )
    )
    current = next(
        (version for version in versions if version.id == merge.current_version_id), None
    )
    return GraphMergeRead(
        id=merge.id,
        workspace_id=merge.workspace_id,
        project_id=merge.project_id,
        merge_key=merge.merge_key,
        title=merge.title,
        description=merge.description,
        status=merge.status,
        current_version_id=merge.current_version_id,
        current=graph_merge_version_read(current) if current else None,
        versions=[graph_merge_version_read(version) for version in versions],
        created_at=merge.created_at,
        updated_at=merge.updated_at,
    )


def resolve_graph_merge(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    merge_key: str,
    *,
    for_update: bool = False,
) -> GraphMerge:
    stmt = select(GraphMerge).where(
        GraphMerge.workspace_id == workspace_id,
        GraphMerge.project_id == project_id,
        GraphMerge.merge_key == merge_key,
    )
    if for_update:
        stmt = stmt.with_for_update()
    merge = session.scalar(stmt)
    if merge is None:
        raise HTTPException(status_code=404, detail="graph merge not found")
    return merge


def graph_merge_input_resource_ids(session: Session, merge: GraphMerge) -> set[UUID]:
    return set(
        session.scalars(
            select(GraphMergeInput.input_resource_id)
            .join(GraphMergeVersion, GraphMergeVersion.id == GraphMergeInput.graph_merge_version_id)
            .where(GraphMergeVersion.graph_merge_id == merge.id)
        )
    )


def require_graph_merge_read(
    session: Session, merge: GraphMerge, principal: Principal, deps: GraphRouterDeps
) -> None:
    require_scope(principal, "resource:read")
    deps.require_project_access(session, merge.workspace_id, merge.project_id, principal)
    if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
        allowed = set(principal.api_token.allowed_resource_ids)
        if not graph_merge_input_resource_ids(session, merge).issubset(allowed):
            raise HTTPException(status_code=404, detail="graph merge not found")


def require_graph_merge_write(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    deps: GraphRouterDeps,
) -> None:
    require_scope(principal, "resource:write")
    deps.require_project_member(
        session, workspace_id, project_id, principal, required_scopes={"resource:write"}
    )
    if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
        raise HTTPException(
            status_code=403, detail="resource-scoped tokens cannot compile graph merges"
        )


def require_graph_merge_review(
    session: Session, merge: GraphMerge, principal: Principal, deps: GraphRouterDeps
) -> None:
    deps.require_review_write(session, merge.workspace_id, merge.project_id, principal)
    if principal.api_token is not None and principal.api_token.allowed_resource_ids is not None:
        raise HTTPException(
            status_code=403, detail="resource-scoped tokens cannot mutate graph merge lifecycle"
        )


def resolve_graph_merge_version(
    session: Session, merge: GraphMerge, version_number: int, *, for_update: bool = False
) -> GraphMergeVersion:
    stmt = select(GraphMergeVersion).where(
        GraphMergeVersion.graph_merge_id == merge.id, GraphMergeVersion.version == version_number
    )
    if for_update:
        stmt = stmt.with_for_update()
    version = session.scalar(stmt)
    if version is None:
        raise HTTPException(status_code=404, detail="graph merge version not found")
    return version


def assert_graph_merge_publishable(
    session: Session, version: GraphMergeVersion, payload: GraphMergeReviewRequest
) -> None:
    if version.status != GRAPH_MERGE_VERSION_DRAFT:
        raise HTTPException(
            status_code=422, detail="only draft graph merge versions can be published"
        )
    if not version.validation_json.get("ok"):
        raise HTTPException(
            status_code=422, detail="graph merge validation must pass before publish"
        )
    comment_lc = payload.comment.lower()
    unresolved_or_truncated = version.unresolved_candidate_count > 0 or bool(
        version.validation_json.get("candidate_truncated")
    )
    if unresolved_or_truncated:
        if not payload.allow_unresolved_candidates:
            raise HTTPException(
                status_code=422,
                detail="unresolved or truncated candidates require review or explicit acknowledgement",
            )
        if "acknowledge unresolved" not in comment_lc:
            raise HTTPException(
                status_code=422,
                detail="comment must include 'acknowledge unresolved' when overriding unresolved or truncated candidates",
            )
    inputs = list(
        session.scalars(
            select(GraphMergeInput).where(GraphMergeInput.graph_merge_version_id == version.id)
        )
    )
    stale = False
    for row in inputs:
        graph_version = session.get(GraphVersion, row.input_graph_version_id)
        graph = session.get(Graph, row.input_graph_id)
        resource = session.get(Resource, row.input_resource_id)
        if graph_version is None or graph is None or resource is None:
            raise HTTPException(status_code=422, detail="graph merge input is missing")
        if graph_version.status not in {
            GRAPH_MERGE_VERSION_PUBLISHED,
            GRAPH_MERGE_VERSION_SUPERSEDED,
        }:
            raise HTTPException(
                status_code=422, detail="graph merge input version is not published or superseded"
            )
        if resource.deleted_at is not None or resource.status in {"deleted", "archived"}:
            raise HTTPException(
                status_code=422, detail="graph merge input resource is deleted or archived"
            )
        if graph.current_version_id and graph.current_version_id != graph_version.id:
            stale = True
    if stale:
        if not payload.allow_stale_inputs:
            raise HTTPException(
                status_code=422,
                detail="graph merge draft is stale; recompile against current graph inputs",
            )
        if "acknowledge stale" not in comment_lc:
            raise HTTPException(
                status_code=422,
                detail="comment must include 'acknowledge stale' when overriding stale inputs",
            )


def create_router(deps: GraphRouterDeps) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/workspaces/{workspace_id}/projects/{project_id}/graph-merges",
        response_model=list[GraphMergeRead],
    )
    def list_graph_merges(
        workspace_id: UUID,
        project_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> list[GraphMergeRead]:
        require_scope(principal, "resource:read")
        deps.require_project_access(session, workspace_id, project_id, principal)
        merges = list(
            session.scalars(
                select(GraphMerge)
                .where(GraphMerge.workspace_id == workspace_id, GraphMerge.project_id == project_id)
                .order_by(GraphMerge.created_at.desc())
            )
        )
        visible: list[GraphMergeRead] = []
        for merge in merges:
            try:
                require_graph_merge_read(session, merge, principal, deps)
            except HTTPException as exc:
                if exc.status_code == 404:
                    continue
                raise
            visible.append(graph_merge_read(session, merge))
        return visible

    @router.get(
        "/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}",
        response_model=GraphMergeRead,
    )
    def get_graph_merge(
        workspace_id: UUID,
        project_id: UUID,
        merge_key: str,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> GraphMergeRead:
        merge = resolve_graph_merge(session, workspace_id, project_id, merge_key)
        require_graph_merge_read(session, merge, principal, deps)
        return graph_merge_read(session, merge)

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/graph-merges",
        response_model=GraphMergeRead,
    )
    def compile_graph_merge_endpoint(
        workspace_id: UUID,
        project_id: UUID,
        payload: GraphMergeCompileRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> GraphMergeRead:
        require_graph_merge_write(session, workspace_id, project_id, principal, deps)
        refs = [
            MergeInputRef(
                graph_key=item.graph_key,
                version=item.version,
                graph_version_id=item.graph_version_id,
            )
            for item in payload.inputs
        ]
        try:
            result = compile_graph_merge(
                session,
                workspace_id=workspace_id,
                project_id=project_id,
                actor_id=principal.user.id,
                inputs=refs,
                strategy=payload.strategy,
                merge_key=payload.merge_key,
                title=payload.title,
                description=payload.description,
            )
        except OverflowError as exc:
            status_code = 422 if str(exc) == "too_many_inputs" else 413
            raise HTTPException(status_code=status_code, detail=str(exc)) from exc
        except MemoryError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="graph_merge.compile",
                target_type="graph_merge_version",
                target_id=result.version.id,
                meta={
                    "merge_key": result.merge.merge_key,
                    "version": result.version.version,
                    "strategy": result.version.merge_strategy,
                    "unchanged": result.unchanged,
                },
            )
        )
        session.commit()
        return graph_merge_read(session, result.merge)

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/versions/{version_number}/publish",
        response_model=GraphMergeRead,
    )
    def publish_graph_merge(
        workspace_id: UUID,
        project_id: UUID,
        merge_key: str,
        version_number: int,
        payload: GraphMergeReviewRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> GraphMergeRead:
        merge = resolve_graph_merge(session, workspace_id, project_id, merge_key, for_update=True)
        require_graph_merge_review(session, merge, principal, deps)
        if merge.status == GRAPH_MERGE_STATUS_ARCHIVED:
            raise HTTPException(
                status_code=422, detail="archived graph merges cannot publish versions"
            )
        version = resolve_graph_merge_version(session, merge, version_number, for_update=True)
        assert_graph_merge_publishable(session, version, payload)
        current = (
            session.get(GraphMergeVersion, merge.current_version_id)
            if merge.current_version_id
            else None
        )
        if current and current.status == GRAPH_MERGE_VERSION_PUBLISHED:
            current.status = GRAPH_MERGE_VERSION_SUPERSEDED
        accepted_candidates = list(
            session.scalars(
                select(GraphMergeReconcileCandidate).where(
                    GraphMergeReconcileCandidate.graph_merge_version_id == version.id,
                    GraphMergeReconcileCandidate.status == "accepted",
                )
            )
        )
        existing_review_edges = {
            (row.source_merged_node_key, row.target_merged_node_key, row.edge_type)
            for row in session.execute(
                select(
                    GraphMergeEdge.source_merged_node_key,
                    GraphMergeEdge.target_merged_node_key,
                    GraphMergeEdge.edge_type,
                ).where(
                    GraphMergeEdge.graph_merge_version_id == version.id,
                    GraphMergeEdge.edge_type.like("reviewed_%"),
                )
            ).all()
        }
        for candidate in accepted_candidates:
            source_key = (candidate.left_origin_json or {}).get("merged_node_key")
            target_key = (candidate.right_origin_json or {}).get("merged_node_key")
            if not source_key or not target_key:
                continue
            edge_type = f"reviewed_{candidate.candidate_type}"
            edge_tuple = (source_key, target_key, edge_type)
            if edge_tuple in existing_review_edges:
                continue
            session.add(
                GraphMergeEdge(
                    workspace_id=workspace_id,
                    project_id=project_id,
                    graph_merge_version_id=version.id,
                    source_merged_node_key=source_key,
                    target_merged_node_key=target_key,
                    edge_type=edge_type,
                    weight=candidate.confidence,
                    origin_json=[
                        {
                            "candidate_key": candidate.candidate_key,
                            "left": candidate.left_origin_json,
                            "right": candidate.right_origin_json,
                            "review_reason": candidate.review_reason,
                        }
                    ],
                    meta={
                        "materialized_from": "accepted_reconcile_candidate",
                        "candidate_type": candidate.candidate_type,
                    },
                )
            )
            existing_review_edges.add(edge_tuple)
        version.edge_count = (
            session.scalar(
                select(func.count())
                .select_from(GraphMergeEdge)
                .where(GraphMergeEdge.graph_merge_version_id == version.id)
            )
            or version.edge_count
        )
        version.status = GRAPH_MERGE_VERSION_PUBLISHED
        version.published_by = principal.user.id
        version.published_at = datetime.now(UTC)
        version.status_reason = payload.comment
        merge.current_version_id = version.id
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="graph_merge.publish",
                target_type="graph_merge_version",
                target_id=version.id,
                meta={
                    "merge_key": merge.merge_key,
                    "version": version.version,
                    "comment": payload.comment,
                },
            )
        )
        session.commit()
        return graph_merge_read(session, merge)

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/versions/{version_number}/invalidate",
        response_model=GraphMergeRead,
    )
    def invalidate_graph_merge_version(
        workspace_id: UUID,
        project_id: UUID,
        merge_key: str,
        version_number: int,
        payload: GraphMergeReviewRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> GraphMergeRead:
        merge = resolve_graph_merge(session, workspace_id, project_id, merge_key, for_update=True)
        require_graph_merge_review(session, merge, principal, deps)
        version = resolve_graph_merge_version(session, merge, version_number, for_update=True)
        if version.status == GRAPH_MERGE_VERSION_INVALIDATED:
            raise HTTPException(
                status_code=422, detail="graph merge version is already invalidated"
            )
        if merge.current_version_id == version.id and merge.status != GRAPH_MERGE_STATUS_ARCHIVED:
            raise HTTPException(
                status_code=422,
                detail="archive merge or publish another version before invalidating current",
            )
        version.status = GRAPH_MERGE_VERSION_INVALIDATED
        version.invalidated_by = principal.user.id
        version.invalidated_at = datetime.now(UTC)
        version.status_reason = payload.comment
        if merge.current_version_id == version.id:
            merge.current_version_id = None
        session.commit()
        return graph_merge_read(session, merge)

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/archive",
        response_model=GraphMergeRead,
    )
    def archive_graph_merge(
        workspace_id: UUID,
        project_id: UUID,
        merge_key: str,
        payload: GraphMergeReviewRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> GraphMergeRead:
        merge = resolve_graph_merge(session, workspace_id, project_id, merge_key, for_update=True)
        require_graph_merge_review(session, merge, principal, deps)
        merge.status = GRAPH_MERGE_STATUS_ARCHIVED
        session.commit()
        return graph_merge_read(session, merge)

    @router.get(
        "/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/versions/{version_number}/data",
        response_model=GraphMergeDataRead,
    )
    def get_graph_merge_data(
        workspace_id: UUID,
        project_id: UUID,
        merge_key: str,
        version_number: int,
        kind: str = "nodes",
        limit: int = 100,
        cursor: str | None = None,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> GraphMergeDataRead:
        merge = resolve_graph_merge(session, workspace_id, project_id, merge_key)
        require_graph_merge_read(session, merge, principal, deps)
        version = resolve_graph_merge_version(session, merge, version_number)
        limit = max(1, min(limit, 500))
        try:
            offset = max(0, int(cursor or "0"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="cursor must be an integer offset") from exc
        items: list[dict[str, Any]]
        row_count = 0
        if kind == "nodes":
            node_rows = list(
                session.scalars(
                    select(GraphMergeNode)
                    .where(GraphMergeNode.graph_merge_version_id == version.id)
                    .order_by(GraphMergeNode.display_label.asc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            row_count = len(node_rows)
            items = [
                {
                    "key": row.merged_node_key,
                    "label": row.display_label,
                    "node_type": row.node_type,
                    "path": row.path,
                    "origin": row.origin_json,
                }
                for row in node_rows
            ]
        elif kind == "edges":
            edge_rows = list(
                session.scalars(
                    select(GraphMergeEdge)
                    .where(GraphMergeEdge.graph_merge_version_id == version.id)
                    .order_by(
                        GraphMergeEdge.edge_type.asc(), GraphMergeEdge.source_merged_node_key.asc()
                    )
                    .offset(offset)
                    .limit(limit)
                )
            )
            row_count = len(edge_rows)
            items = [
                {
                    "source": row.source_merged_node_key,
                    "target": row.target_merged_node_key,
                    "edge_type": row.edge_type,
                    "origin": row.origin_json,
                }
                for row in edge_rows
            ]
        elif kind == "candidates":
            candidate_rows = list(
                session.scalars(
                    select(GraphMergeReconcileCandidate)
                    .where(GraphMergeReconcileCandidate.graph_merge_version_id == version.id)
                    .order_by(
                        GraphMergeReconcileCandidate.confidence.desc(),
                        GraphMergeReconcileCandidate.candidate_key.asc(),
                    )
                    .offset(offset)
                    .limit(limit)
                )
            )
            row_count = len(candidate_rows)
            items = [
                {
                    "candidate_key": row.candidate_key,
                    "candidate_type": row.candidate_type,
                    "confidence": row.confidence,
                    "status": row.status,
                    "left": row.left_origin_json,
                    "right": row.right_origin_json,
                    "review_reason": row.review_reason,
                }
                for row in candidate_rows
            ]
        elif kind == "inputs":
            input_rows = list(
                session.execute(
                    select(GraphMergeInput, Graph, GraphVersion, Resource)
                    .join(GraphVersion, GraphVersion.id == GraphMergeInput.input_graph_version_id)
                    .join(Graph, Graph.id == GraphMergeInput.input_graph_id)
                    .join(Resource, Resource.id == GraphMergeInput.input_resource_id)
                    .where(GraphMergeInput.graph_merge_version_id == version.id)
                    .order_by(GraphMergeInput.ordinal.asc())
                    .offset(offset)
                    .limit(limit)
                ).all()
            )
            row_count = len(input_rows)
            items = [
                {
                    "ordinal": row.GraphMergeInput.ordinal,
                    "graph_key": row.Graph.graph_key,
                    "graph_title": row.Graph.title,
                    "graph_version": row.GraphVersion.version,
                    "graph_version_status": row.GraphVersion.status,
                    "resource_name": row.Resource.name,
                    "resource_id": str(row.Resource.id),
                    "source_snapshot_id": str(row.GraphMergeInput.input_source_snapshot_id),
                    "version_hash": row.GraphMergeInput.input_version_hash,
                }
                for row in input_rows
            ]
        else:
            raise HTTPException(
                status_code=422, detail="kind must be nodes, edges, candidates, or inputs"
            )
        next_cursor = str(offset + row_count) if row_count == limit else None
        return GraphMergeDataRead(kind=kind, items=items, limit=limit, next_cursor=next_cursor)

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/versions/{version_number}/candidates/{candidate_key}/review",
        response_model=GraphMergeRead,
    )
    def review_graph_merge_candidate(
        workspace_id: UUID,
        project_id: UUID,
        merge_key: str,
        version_number: int,
        candidate_key: str,
        payload: GraphMergeCandidateReviewRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> GraphMergeRead:
        merge = resolve_graph_merge(session, workspace_id, project_id, merge_key, for_update=True)
        require_graph_merge_review(session, merge, principal, deps)
        version = resolve_graph_merge_version(session, merge, version_number, for_update=True)
        if payload.status not in {"accepted", "rejected"}:
            raise HTTPException(
                status_code=422, detail="candidate review status must be accepted or rejected"
            )
        candidate = session.scalar(
            select(GraphMergeReconcileCandidate)
            .where(
                GraphMergeReconcileCandidate.graph_merge_version_id == version.id,
                GraphMergeReconcileCandidate.candidate_key == candidate_key,
            )
            .with_for_update()
        )
        if candidate is None:
            raise HTTPException(status_code=404, detail="candidate not found")
        candidate.status = payload.status
        candidate.review_reason = payload.reason
        candidate.reviewed_by = principal.user.id
        candidate.reviewed_at = datetime.now(UTC)
        version.unresolved_candidate_count = (
            session.scalar(
                select(func.count())
                .select_from(GraphMergeReconcileCandidate)
                .where(
                    GraphMergeReconcileCandidate.graph_merge_version_id == version.id,
                    GraphMergeReconcileCandidate.status == "open",
                )
            )
            or 0
        )
        session.commit()
        return graph_merge_read(session, merge)

    @router.get(
        "/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/versions/{version_number}/path",
        response_model=GraphMergePathRead,
    )
    def get_graph_merge_path(
        workspace_id: UUID,
        project_id: UUID,
        merge_key: str,
        version_number: int,
        from_node_key: str,
        to_node_key: str,
        max_depth: int = 4,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> GraphMergePathRead:
        merge = resolve_graph_merge(session, workspace_id, project_id, merge_key)
        require_graph_merge_read(session, merge, principal, deps)
        version = resolve_graph_merge_version(session, merge, version_number)
        try:
            result = find_path(session, version, from_node_key, to_node_key, max_depth)
        except OverflowError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="graph_merge.path_query",
                target_type="graph_merge_version",
                target_id=version.id,
                meta={
                    "merge_key": merge.merge_key,
                    "version": version.version,
                    "found": result.get("found"),
                },
            )
        )
        session.commit()
        return GraphMergePathRead(**result)

    @router.get(
        "/workspaces/{workspace_id}/projects/{project_id}/graphs",
        response_model=list[GraphStreamRead],
    )
    def list_graph_streams(
        workspace_id: UUID,
        project_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> list[GraphStreamRead]:
        require_scope(principal, "resource:read")
        deps.require_project_access(session, workspace_id, project_id, principal)
        graphs = list(
            session.scalars(
                select(Graph)
                .where(Graph.workspace_id == workspace_id, Graph.project_id == project_id)
                .order_by(Graph.created_at.desc())
            )
        )
        visible: list[GraphStreamRead] = []
        for graph in graphs:
            try:
                require_graph_read(session, graph, principal, deps)
            except HTTPException as exc:
                if exc.status_code == 404:
                    continue
                raise
            visible.append(graph_stream_read(session, graph))
        return visible

    @router.get(
        "/workspaces/{workspace_id}/projects/{project_id}/graphs/{graph_key}",
        response_model=GraphStreamRead,
    )
    def get_graph_stream(
        workspace_id: UUID,
        project_id: UUID,
        graph_key: str,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> GraphStreamRead:
        graph = resolve_graph(session, workspace_id, project_id, graph_key)
        require_graph_read(session, graph, principal, deps)
        return graph_stream_read(session, graph)

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/graph/versions",
        response_model=GraphCompileResponse,
    )
    def compile_resource_graph_version(
        workspace_id: UUID,
        project_id: UUID,
        resource_id: UUID,
        payload: GraphCompileRequest = GraphCompileRequest(),
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> GraphCompileResponse:
        require_scope(principal, "resource:write")
        deps.require_project_member(
            session, workspace_id, project_id, principal, required_scopes={"resource:write"}
        )
        resource = deps.resolve_resource(session, workspace_id, project_id, resource_id, principal)
        try:
            result = compile_graph_version(
                session,
                resource,
                actor_id=principal.user.id,
                requested_graph_key=payload.graph_key,
                title=payload.title,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="graph_version.compile",
                target_type="graph_version",
                target_id=result.version.id,
                meta={
                    "graph_key": result.graph.graph_key,
                    "version": result.version.version,
                    "unchanged": result.unchanged,
                },
            )
        )
        session.commit()
        return GraphCompileResponse(
            graph=graph_stream_read(session, result.graph),
            version=graph_version_read(result.version),
            unchanged=result.unchanged,
        )

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/graphs/{graph_key}/versions/{version_number}/publish",
        response_model=GraphStreamRead,
    )
    def publish_graph_version(
        workspace_id: UUID,
        project_id: UUID,
        graph_key: str,
        version_number: int,
        payload: GraphReviewRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> GraphStreamRead:
        graph = resolve_graph(session, workspace_id, project_id, graph_key, for_update=True)
        require_graph_review_write(session, graph, principal, deps)
        assert_graph_active(graph)
        version = session.scalar(
            select(GraphVersion)
            .where(GraphVersion.graph_id == graph.id, GraphVersion.version == version_number)
            .with_for_update()
        )
        if version is None:
            raise HTTPException(status_code=404, detail="graph version not found")
        try:
            result = publish_graph_version_record(
                session,
                graph,
                version,
                actor_id=principal.user.id,
                comment=payload.comment,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="graph_version.publish",
                target_type="graph_version",
                target_id=result.version.id,
                meta={
                    "graph_key": result.graph.graph_key,
                    "version": result.version.version,
                    "comment": payload.comment,
                },
            )
        )
        session.commit()
        return graph_stream_read(session, result.graph)

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/graphs/{graph_key}/versions/{version_number}/invalidate",
        response_model=GraphStreamRead,
    )
    def invalidate_graph_version(
        workspace_id: UUID,
        project_id: UUID,
        graph_key: str,
        version_number: int,
        payload: GraphReviewRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> GraphStreamRead:
        graph = resolve_graph(session, workspace_id, project_id, graph_key, for_update=True)
        require_graph_review_write(session, graph, principal, deps)
        version = session.scalar(
            select(GraphVersion)
            .where(GraphVersion.graph_id == graph.id, GraphVersion.version == version_number)
            .with_for_update()
        )
        if version is None:
            raise HTTPException(status_code=404, detail="graph version not found")
        if version.status == GRAPH_VERSION_INVALIDATED:
            raise HTTPException(status_code=422, detail="graph version is already invalidated")
        if graph.current_version_id == version.id and graph.status != GRAPH_STATUS_ARCHIVED:
            raise HTTPException(
                status_code=422,
                detail="publish another version or archive graph before invalidating current graph version",
            )
        version.status = GRAPH_VERSION_INVALIDATED
        version.invalidated_by = principal.user.id
        version.invalidated_at = datetime.now(UTC)
        version.status_reason = payload.comment
        if graph.current_version_id == version.id:
            graph.current_version_id = None
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="graph_version.invalidate",
                target_type="graph_version",
                target_id=version.id,
                meta={
                    "graph_key": graph.graph_key,
                    "version": version.version,
                    "comment": payload.comment,
                },
            )
        )
        session.commit()
        return graph_stream_read(session, graph)

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/graphs/{graph_key}/archive",
        response_model=GraphStreamRead,
    )
    def archive_graph_stream(
        workspace_id: UUID,
        project_id: UUID,
        graph_key: str,
        payload: GraphReviewRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> GraphStreamRead:
        graph = resolve_graph(session, workspace_id, project_id, graph_key, for_update=True)
        require_graph_review_write(session, graph, principal, deps)
        graph.status = GRAPH_STATUS_ARCHIVED
        retained_versions = session.scalar(
            select(func.count()).select_from(GraphVersion).where(GraphVersion.graph_id == graph.id)
        )
        if not retained_versions:
            graph.resource_id = None
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="graph.archive",
                target_type="graph",
                target_id=graph.id,
                meta={
                    "graph_key": graph.graph_key,
                    "comment": payload.comment,
                    "zero_version_tombstone": not bool(retained_versions),
                },
            )
        )
        session.commit()
        return graph_stream_read(session, graph)

    @router.get(
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
        deps.require_project_access(session, workspace_id, project_id, principal)
        resource = deps.resolve_resource(session, workspace_id, project_id, resource_id, principal)
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

    return router
