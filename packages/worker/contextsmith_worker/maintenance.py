from __future__ import annotations

import os
import signal
import sys
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from redis import Redis
from rq import Queue
from sqlalchemy import select
from sqlalchemy.orm import Session

from contextsmith_shared.config import get_settings
from contextsmith_shared.db import get_sessionmaker
from contextsmith_shared.lifecycle import (
    compute_next_refresh_at,
    is_refresh_due,
    parse_update_frequency,
)
from contextsmith_shared.models import AuditEvent, IndexRun, Resource

ACTIVE_INDEX_STATUSES = {"enqueueing", "queued", "running"}


def _has_active_index_run(session: Session, resource: Resource) -> bool:
    return session.scalar(
        select(IndexRun.id)
        .where(
            IndexRun.workspace_id == resource.workspace_id,
            IndexRun.project_id == resource.project_id,
            IndexRun.resource_id == resource.id,
            IndexRun.status.in_(ACTIVE_INDEX_STATUSES),
        )
        .limit(1)
    ) is not None


def enqueue_due_refreshes(
    *,
    now: datetime | None = None,
    limit: int = 100,
    workspace_id: UUID | None = None,
    project_id: UUID | None = None,
    resource_ids: list[UUID] | None = None,
    queue: Queue | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Scan active scheduled resources and enqueue due index runs.

    This is intentionally idempotent: resources with active runs are skipped and
    each selected resource's `next_refresh_at` is advanced immediately after a
    queued run is persisted, preventing a tight scheduler loop from enqueuing the
    same resource repeatedly before workers pick it up.
    """
    now = now or datetime.now(UTC)
    session = get_sessionmaker()()
    enqueued: list[str] = []
    skipped_active: list[str] = []
    scanned = 0
    try:
        predicates = [
            Resource.deleted_at.is_(None),
            Resource.archived_at.is_(None),
            Resource.status != "deleted",
            Resource.status != "archived",
            Resource.retrieval_enabled.is_(True),
            Resource.update_frequency != "manual",
        ]
        if workspace_id is not None:
            predicates.append(Resource.workspace_id == workspace_id)
        if project_id is not None:
            predicates.append(Resource.project_id == project_id)
        if resource_ids is not None:
            if not resource_ids:
                return {"scanned": 0, "enqueued": 0, "resource_ids": [], "skipped_active": [], "dry_run": dry_run}
            predicates.append(Resource.id.in_(resource_ids))
        query = (
            select(Resource)
            .where(*predicates)
            .order_by(Resource.next_refresh_at.asc().nullsfirst(), Resource.created_at.asc())
            .limit(limit)
        )
        if not dry_run:
            query = query.with_for_update(skip_locked=True)
        resources = list(session.scalars(query))
        scanned = len(resources)
        if queue is None and not dry_run:
            queue = Queue("default", connection=Redis.from_url(get_settings().redis_url))
        for resource in resources:
            if not is_refresh_due(resource, now=now):
                if not dry_run and resource.next_refresh_at is None:
                    resource.next_refresh_at = compute_next_refresh_at(resource, now=now)
                continue
            if _has_active_index_run(session, resource):
                skipped_active.append(str(resource.id))
                continue
            if dry_run:
                enqueued.append(str(resource.id))
                continue
            run = IndexRun(
                workspace_id=resource.workspace_id,
                project_id=resource.project_id,
                resource_id=resource.id,
                trigger="scheduled",
                status="enqueueing",
                meta={"scheduler_at": now.isoformat()},
            )
            session.add(run)
            session.flush()
            try:
                assert queue is not None
                queue.enqueue("contextsmith_worker.jobs.run_index", str(run.id), job_timeout=600)
            except Exception as exc:
                run.status = "failed"
                run.error_message = f"failed to enqueue scheduled index job: {exc}"[:1000]
                run.finished_at = datetime.now(UTC)
                resource.status = "failed"
                resource.next_refresh_at = compute_next_refresh_at(resource, now=run.finished_at)
                session.add(run)
                continue
            run.status = "queued"
            interval = parse_update_frequency(resource.update_frequency)
            resource.next_refresh_at = now + interval if interval is not None else None
            session.add(
                AuditEvent(
                    workspace_id=resource.workspace_id,
                    actor_user_id=None,
                    actor_token_id=None,
                    action="resource.scheduled_refresh",
                    target_type="resource",
                    target_id=resource.id,
                    meta={"index_run_id": str(run.id), "scheduler_at": now.isoformat()},
                )
            )
            enqueued.append(str(resource.id))
        session.commit()
        return {
            "scanned": scanned,
            "enqueued": len(enqueued),
            "resource_ids": enqueued,
            "skipped_active": skipped_active,
            "dry_run": dry_run,
        }
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> None:
    running = True

    def stop(_signum: int, _frame: object) -> None:
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    interval_seconds = int(os.getenv("CONTEXTSMITH_MAINTENANCE_INTERVAL_SECONDS", "60"))
    limit = int(os.getenv("CONTEXTSMITH_MAINTENANCE_LIMIT", "100"))
    print("ContextSmith maintenance scheduler started", flush=True)
    while running:
        try:
            result = enqueue_due_refreshes(limit=limit)
            if result["enqueued"]:
                print(f"scheduled refreshes: {result}", flush=True)
        except Exception as exc:  # pragma: no cover - process supervisor observes logs
            print(f"maintenance scheduler error: {exc}", file=sys.stderr, flush=True)
        for _ in range(max(1, interval_seconds)):
            if not running:
                break
            time.sleep(1)
    print("ContextSmith maintenance scheduler stopped", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
