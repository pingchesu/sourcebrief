from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from contextsmith_shared.db import get_sessionmaker
from contextsmith_shared.models import IndexRun, Resource


def run_placeholder_index(index_run_id: str) -> None:
    session = get_sessionmaker()()
    try:
        run = session.scalar(select(IndexRun).where(IndexRun.id == UUID(index_run_id)))
        if run is None:
            raise RuntimeError(f"index_run not found: {index_run_id}")
        run.status = "running"
        run.started_at = datetime.now(UTC)
        session.commit()

        if run.meta.get("fail"):
            raise RuntimeError("intentional placeholder failure")

        resource = session.scalar(select(Resource).where(Resource.id == run.resource_id))
        if resource is not None:
            resource.last_refresh_started_at = run.started_at
            resource.last_refresh_finished_at = datetime.now(UTC)
        run.status = "succeeded"
        run.finished_at = datetime.now(UTC)
        run.documents_seen = 1
        session.commit()
    except Exception as exc:
        session.rollback()
        failed = session.scalar(select(IndexRun).where(IndexRun.id == UUID(index_run_id)))
        if failed is not None:
            failed.status = "failed"
            failed.error_message = str(exc)
            failed.finished_at = datetime.now(UTC)
            session.commit()
        raise
    finally:
        session.close()
