from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from sourcebrief_api.graph_versions import (
    compile_graph_version,
    publish_graph_version_record,
)
from sourcebrief_shared.db import get_sessionmaker
from sourcebrief_shared.lifecycle import compute_next_refresh_at
from sourcebrief_shared.models import (
    AuditEvent,
    Graph,
    GraphMerge,
    GraphMergeInput,
    GraphMergeVersion,
    GraphVersion,
    IndexRun,
    Resource,
)
from sourcebrief_worker.bundle_ingest import cleanup_stale_uploads
from sourcebrief_worker.ingestion import GIT_TYPES, _work_base, ingest_resource


def run_index(index_run_id: str) -> None:
    """Execute a real ingestion run for the given index_run id.

    Status transitions are persisted to Postgres (the durable source of truth):
    ``queued -> running -> succeeded`` on success, or ``-> failed`` with an
    error message on any exception. The ingestion itself (snapshot + chunks) is
    committed atomically; a failure rolls those inserts back before the run is
    marked failed so no partial snapshot is left behind.
    """
    session = get_sessionmaker()()
    try:
        run = session.scalar(select(IndexRun).where(IndexRun.id == UUID(index_run_id)))
        cleanup_stale_uploads(_work_base())
        if run is None:
            raise RuntimeError(f"index_run not found: {index_run_id}")
        run.status = "running"
        run.started_at = datetime.now(UTC)
        resource = session.scalar(select(Resource).where(Resource.id == run.resource_id))
        if resource is not None:
            resource.last_refresh_started_at = run.started_at
        session.commit()

        # Failure hook retained for QA/failure-path testing.
        if run.meta.get("fail"):
            raise RuntimeError("intentional placeholder failure")

        resource = session.scalar(
            select(Resource)
            .where(Resource.id == run.resource_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if resource is None:
            raise RuntimeError(f"resource not found: {run.resource_id}")
        if (
            resource.deleted_at is not None
            or resource.archived_at is not None
            or resource.status in {"deleted", "archived"}
        ):
            raise RuntimeError(f"resource is not active: {run.resource_id}")

        previous_snapshot_id = resource.current_snapshot_id
        snapshot = ingest_resource(session, resource, run)
        snapshot_unchanged = (
            previous_snapshot_id is not None and snapshot.id == previous_snapshot_id
        )

        if resource.type.lower() in GIT_TYPES:
            if snapshot_unchanged:
                session.add(
                    AuditEvent(
                        workspace_id=resource.workspace_id,
                        action="resource.refresh_unchanged",
                        target_type="resource",
                        target_id=resource.id,
                        target_ref={
                            "project_id": str(resource.project_id),
                            "resource_id": str(resource.id),
                            "snapshot_id": str(snapshot.id),
                        },
                        meta={
                            "index_run_id": str(run.id),
                            "trigger": run.trigger,
                            "source_commit": (snapshot.meta or {}).get("commit"),
                        },
                    )
                )
            current_graph = session.scalar(
                select(Graph).where(
                    Graph.workspace_id == resource.workspace_id,
                    Graph.project_id == resource.project_id,
                    Graph.resource_id == resource.id,
                    Graph.status == "active",
                )
            )
            current_graph_version = (
                session.get(GraphVersion, current_graph.current_version_id)
                if current_graph is not None and current_graph.current_version_id
                else None
            )
            graph_is_current = (
                current_graph_version is not None
                and current_graph_version.status == "published"
                and current_graph_version.source_snapshot_id == resource.current_snapshot_id
            )
            if not graph_is_current:
                compile_result = compile_graph_version(session, resource, actor_id=None)
                publish_result = publish_graph_version_record(
                    session,
                    compile_result.graph,
                    compile_result.version,
                    actor_id=None,
                    comment=f"Auto-published by {run.trigger} Git refresh {run.id}",
                    allow_validation_warnings=False,
                )
                dependent_merges = session.execute(
                    select(GraphMerge, GraphMergeVersion)
                    .join(
                        GraphMergeVersion,
                        GraphMerge.current_version_id == GraphMergeVersion.id,
                    )
                    .join(
                        GraphMergeInput,
                        GraphMergeInput.graph_merge_version_id == GraphMergeVersion.id,
                    )
                    .where(
                        GraphMerge.workspace_id == resource.workspace_id,
                        GraphMerge.project_id == resource.project_id,
                        GraphMerge.status == "active",
                        GraphMergeVersion.status == "published",
                        GraphMergeInput.input_resource_id == resource.id,
                        GraphMergeInput.input_graph_version_id != publish_result.version.id,
                    )
                    .distinct()
                ).all()
                stale_merge_keys = [merge.merge_key for merge, _version in dependent_merges]
                run.meta = {
                    **dict(run.meta or {}),
                    "graph_sync": {
                        "graph_id": str(publish_result.graph.id),
                        "graph_key": publish_result.graph.graph_key,
                        "graph_version_id": str(publish_result.version.id),
                        "graph_version": publish_result.version.version,
                        "source_snapshot_id": str(publish_result.version.source_snapshot_id),
                        "source_commit": (snapshot.meta or {}).get("commit"),
                        "version_hash": publish_result.version.version_hash,
                        "stale_merge_keys": stale_merge_keys,
                    },
                }
                for merge, merge_version in dependent_merges:
                    merge_version.status = "invalidated"
                    merge_version.invalidated_at = datetime.now(UTC)
                    merge_version.status_reason = (
                        f"Automatically invalidated because resource graph {publish_result.graph.graph_key} "
                        f"advanced to version {publish_result.version.version}"
                    )
                    session.add(
                        AuditEvent(
                            workspace_id=resource.workspace_id,
                            action="graph_merge.stale",
                            target_type="graph_merge_version",
                            target_id=merge_version.id,
                            target_ref={
                                "project_id": str(resource.project_id),
                                "merge_id": str(merge.id),
                                "merge_key": merge.merge_key,
                                "merge_version_id": str(merge_version.id),
                                "resource_id": str(resource.id),
                                "index_run_id": str(run.id),
                            },
                            meta={
                                "reason": "resource_graph_advanced",
                                "new_graph_version_id": str(publish_result.version.id),
                                "new_source_snapshot_id": str(snapshot.id),
                            },
                        )
                    )
                session.add(
                    AuditEvent(
                        workspace_id=resource.workspace_id,
                        action="graph_version.compile",
                        target_type="graph_version",
                        target_id=compile_result.version.id,
                        target_ref={
                            "project_id": str(resource.project_id),
                            "resource_id": str(resource.id),
                            "snapshot_id": str(snapshot.id),
                            "index_run_id": str(run.id),
                        },
                        meta={
                            "graph_key": compile_result.graph.graph_key,
                            "version": compile_result.version.version,
                            "unchanged": compile_result.unchanged,
                            "automatic": True,
                            "trigger": run.trigger,
                        },
                    )
                )
                session.add(
                    AuditEvent(
                        workspace_id=resource.workspace_id,
                        action="graph_version.publish",
                        target_type="graph_version",
                        target_id=publish_result.version.id,
                        target_ref={
                            "project_id": str(resource.project_id),
                            "resource_id": str(resource.id),
                            "snapshot_id": str(snapshot.id),
                            "index_run_id": str(run.id),
                        },
                        meta={
                            "graph_key": publish_result.graph.graph_key,
                            "version": publish_result.version.version,
                            "automatic": True,
                            "trigger": run.trigger,
                        },
                    )
                )

        finished = datetime.now(UTC)
        resource.last_refresh_finished_at = finished
        resource.status = "active"
        resource.next_refresh_at = compute_next_refresh_at(resource, now=finished)
        run.status = "succeeded"
        run.finished_at = finished
        session.commit()
    except Exception as exc:
        session.rollback()
        failed = session.scalar(select(IndexRun).where(IndexRun.id == UUID(index_run_id)))
        if failed is not None:
            failed.status = "failed"
            failed.error_message = str(exc)
            failed.finished_at = datetime.now(UTC)
            resource = session.scalar(select(Resource).where(Resource.id == failed.resource_id))
            if resource is not None:
                resource.status = "failed"
                resource.last_refresh_finished_at = failed.finished_at
                if failed.trigger == "scheduled":
                    resource.next_refresh_at = failed.finished_at + timedelta(minutes=15)
            session.commit()
        raise
    finally:
        session.close()


# Backwards-compatible alias for any jobs enqueued under the M1 name.
run_placeholder_index = run_index
