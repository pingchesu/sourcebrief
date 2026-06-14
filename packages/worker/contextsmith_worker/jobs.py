from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from contextsmith_shared.db import get_sessionmaker
from contextsmith_shared.lifecycle import compute_next_refresh_at
from contextsmith_shared.models import IndexRun, Resource
from contextsmith_worker.ingestion import ingest_resource


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

        if resource is None:
            raise RuntimeError(f"resource not found: {run.resource_id}")
        if resource.deleted_at is not None or resource.archived_at is not None or resource.status in {"deleted", "archived"}:
            raise RuntimeError(f"resource is not active: {run.resource_id}")

        ingest_resource(session, resource, run)

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
            session.commit()
        raise
    finally:
        session.close()


# Backwards-compatible alias for any jobs enqueued under the M1 name.
run_placeholder_index = run_index
