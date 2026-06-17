from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from contextsmith_shared.models import AgentCardSummary, AuditEvent, Resource

BLOCKED_STATUSES = {"deleted", "failed"}
ACTIVE_STATUSES = {"active"}


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _severity(status: str) -> str:
    return {
        "healthy": "info",
        "attention_needed": "warning",
        "stale": "warning",
        "degraded": "major",
        "blocked": "blocker",
    }[status]


def _finding(code: str, severity: str, message: str, evidence: dict[str, Any]) -> dict[str, Any]:
    return {"code": code, "severity": severity, "message": message, "evidence": evidence}


def evaluate_agent_card(session: Session, resource: Resource, *, now: datetime | None = None) -> dict[str, Any]:
    """Read-only drift evaluation for one git repo-agent card."""
    now = now or datetime.now(UTC)
    latest_index = session.execute(
        text(
            """
            SELECT status, finished_at, error_message, created_at
            FROM index_runs
            WHERE workspace_id = :ws AND project_id = :proj AND resource_id = :res
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"ws": resource.workspace_id, "proj": resource.project_id, "res": resource.id},
    ).mappings().first()
    usage = session.execute(
        text(
            """
            SELECT COUNT(*) AS hit_count, MAX(created_at) AS last_used_at
            FROM retrieval_hits
            WHERE workspace_id = :ws AND project_id = :proj AND resource_id = :res
            """
        ),
        {"ws": resource.workspace_id, "proj": resource.project_id, "res": resource.id},
    ).mappings().one()
    stats = session.execute(
        text(
            """
            SELECT
              (SELECT COUNT(*) FROM chunks c WHERE c.workspace_id = :ws AND c.project_id = :proj AND c.resource_id = :res AND c.source_snapshot_id = :snap AND c.deleted_at IS NULL) AS chunk_count,
              (SELECT COUNT(*) FROM chunk_embeddings ce WHERE ce.workspace_id = :ws AND ce.project_id = :proj AND ce.resource_id = :res AND ce.source_snapshot_id = :snap) AS embedding_count,
              (SELECT COUNT(*) FROM code_symbols cs WHERE cs.workspace_id = :ws AND cs.project_id = :proj AND cs.resource_id = :res AND cs.source_snapshot_id = :snap AND cs.deleted_at IS NULL) AS symbol_count,
              (SELECT COUNT(*) FROM graph_nodes gn WHERE gn.workspace_id = :ws AND gn.project_id = :proj AND gn.resource_id = :res AND gn.source_snapshot_id = :snap) AS graph_node_count
            """
        ),
        {"ws": resource.workspace_id, "proj": resource.project_id, "res": resource.id, "snap": resource.current_snapshot_id},
    ).mappings().one()
    latest_eval = session.execute(
        text(
            """
            SELECT status, pass_rate, profile, created_at, summary
            FROM retrieval_eval_runs
            WHERE workspace_id = :ws
              AND project_id = :proj
              AND (project_wide = true OR :res = ANY(resource_ids))
            ORDER BY created_at DESC
            LIMIT 1
            """
        ),
        {"ws": resource.workspace_id, "proj": resource.project_id, "res": resource.id},
    ).mappings().first()

    findings: list[dict[str, Any]] = []
    if resource.status not in ACTIVE_STATUSES or resource.archived_at is not None:
        findings.append(_finding("resource_inactive", "blocker", "Repo agent resource is not active.", {"status": resource.status, "archived_at": resource.archived_at.isoformat() if resource.archived_at else None}))
    if not resource.retrieval_enabled:
        findings.append(_finding("retrieval_disabled", "blocker", "Retrieval is disabled for this repo agent.", {"retrieval_enabled": False}))
    if resource.current_snapshot_id is None:
        findings.append(_finding("missing_snapshot", "blocker", "Repo agent has no current indexed snapshot.", {}))
    if latest_index and latest_index["status"] == "failed":
        findings.append(_finding("latest_index_failed", "major", "Latest index run failed.", {"finished_at": latest_index["finished_at"].isoformat() if latest_index["finished_at"] else None, "error": latest_index["error_message"]}))
    elif not latest_index:
        findings.append(_finding("no_index_run", "major", "Repo agent has no index run evidence.", {}))
    if resource.current_snapshot_id is not None and int(stats["chunk_count"] or 0) == 0:
        findings.append(_finding("empty_index", "major", "Current snapshot has no retrievable chunks.", {"snapshot_id": str(resource.current_snapshot_id)}))
    if resource.current_snapshot_id is not None and int(stats["embedding_count"] or 0) == 0:
        findings.append(_finding("missing_embeddings", "warning", "Current snapshot has no embeddings; semantic profiles may degrade.", {"snapshot_id": str(resource.current_snapshot_id)}))
    if resource.type == "git" and resource.current_snapshot_id is not None and int(stats["symbol_count"] or 0) == 0:
        findings.append(_finding("missing_symbols", "warning", "Git repo agent has no extracted code symbols.", {"snapshot_id": str(resource.current_snapshot_id)}))
    if resource.review_status in {"needs_update", "stale", "unreviewed"}:
        findings.append(_finding("review_status", "warning", "Repo agent review status needs maintainer attention.", {"review_status": resource.review_status}))

    base = _aware(resource.last_refresh_finished_at or resource.created_at)
    age_days = None
    if base is not None:
        age_days = max(0, (now - base).days)
        if age_days > resource.stale_after_days:
            findings.append(_finding("refresh_age_exceeded", "warning", "Repo agent index is older than its freshness policy.", {"age_days": age_days, "stale_after_days": resource.stale_after_days}))
    if latest_eval is None:
        findings.append(_finding("no_recent_eval", "warning", "No retrieval eval evidence exists for this repo agent.", {}))
    elif float(latest_eval["pass_rate"] or 0.0) < 0.8:
        findings.append(_finding("eval_regression", "major", "Latest retrieval eval pass rate is below threshold.", {"pass_rate": float(latest_eval["pass_rate"] or 0.0), "profile": latest_eval["profile"], "created_at": latest_eval["created_at"].isoformat() if latest_eval["created_at"] else None}))

    status = "healthy"
    if any(item["severity"] == "blocker" for item in findings):
        status = "blocked"
    elif any(item["severity"] == "major" for item in findings):
        status = "degraded"
    elif any(item["code"] == "refresh_age_exceeded" for item in findings):
        status = "stale"
    elif findings:
        status = "attention_needed"

    metrics = {
        "chunk_count": int(stats["chunk_count"] or 0),
        "embedding_count": int(stats["embedding_count"] or 0),
        "symbol_count": int(stats["symbol_count"] or 0),
        "graph_node_count": int(stats["graph_node_count"] or 0),
        "usage_count": int(usage["hit_count"] or 0),
        "last_used_at": usage["last_used_at"].isoformat() if usage["last_used_at"] else None,
        "last_index_status": latest_index["status"] if latest_index else None,
        "last_index_finished_at": latest_index["finished_at"].isoformat() if latest_index and latest_index["finished_at"] else None,
        "freshness_age_days": age_days,
        "latest_eval_status": latest_eval["status"] if latest_eval else None,
        "latest_eval_pass_rate": float(latest_eval["pass_rate"] or 0.0) if latest_eval else None,
        "latest_eval_profile": latest_eval["profile"] if latest_eval else None,
    }
    if status == "healthy":
        summary = "Repo agent card is healthy: indexed, retrievable, reviewed, and backed by passing eval evidence."
    else:
        summary = f"Repo agent card is {status}: " + "; ".join(item["message"] for item in findings[:3])
    return {"status": status, "severity": _severity(status), "summary": summary, "findings": findings, "metrics": metrics}


def run_agent_card_auditor(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    resource_ids: list[UUID] | None = None,
    now: datetime | None = None,
    actor_user_id: UUID | None = None,
    actor_token_id: UUID | None = None,
    persist: bool = True,
    limit: int = 100,
) -> list[AgentCardSummary]:
    now = now or datetime.now(UTC)
    predicates = [
        Resource.workspace_id == workspace_id,
        Resource.project_id == project_id,
        Resource.type == "git",
        Resource.deleted_at.is_(None),
    ]
    if resource_ids is not None:
        if not resource_ids:
            return []
        predicates.append(Resource.id.in_(resource_ids))
    resources = list(session.scalars(select(Resource).where(*predicates).order_by(Resource.created_at.asc()).limit(limit)))
    summaries: list[AgentCardSummary] = []
    for resource in resources:
        result = evaluate_agent_card(session, resource, now=now)
        summary = AgentCardSummary(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            project_id=project_id,
            resource_id=resource.id,
            status=result["status"],
            severity=result["severity"],
            summary=result["summary"],
            findings=result["findings"],
            metrics=result["metrics"],
            source="auditor",
            created_at=now,
        )
        summaries.append(summary)
        if persist:
            session.add(summary)
            session.add(
                AuditEvent(
                    workspace_id=workspace_id,
                    actor_user_id=actor_user_id,
                    actor_token_id=actor_token_id,
                    action="agent_card.audited",
                    target_type="resource",
                    target_id=resource.id,
                    meta={"status": summary.status, "severity": summary.severity, "finding_count": len(summary.findings)},
                )
            )
    if persist:
        session.commit()
    return summaries
