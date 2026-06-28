from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from sourcebrief_shared.self_improvement_security import redact_review_artifact

HistoryArtifactKind = Literal["bundle", "report", "proposal", "gate_result", "staged_adoption", "unknown"]

_SCHEMA_TO_KIND: dict[str, HistoryArtifactKind] = {
    "sourcebrief.review-bundle.v1": "bundle",
    "sourcebrief.review-report.v1": "report",
    "sourcebrief.regression-proposal.v1": "proposal",
    "sourcebrief.validation-gate-result.v1": "gate_result",
    "sourcebrief.staged-adoption-receipt.v1": "staged_adoption",
}


class ReviewHistoryError(ValueError):
    """User-facing review history error."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewHistoryRecord(StrictModel):
    artifact_id: str = Field(min_length=1)
    schema_version: str = Field(min_length=1)
    kind: HistoryArtifactKind
    path: str = Field(min_length=1)
    created_at: str | None = None
    bundle_id: str | None = None
    report_id: str | None = None
    proposal_id: str | None = None
    gate_result_id: str | None = None
    source_report_id: str | None = None
    source_bundle_id: str | None = None
    source_finding_id: str | None = None
    status: str | None = None
    decision: str | None = None
    verdict: str | None = None
    finding_count: int = 0
    blocker_major_count: int = 0
    target_surface: str | None = None
    subject_refs: list[dict[str, Any]] = Field(default_factory=list)
    redaction_counts: dict[str, int] = Field(default_factory=dict)


class ReviewHistorySummary(StrictModel):
    root: str
    records: list[ReviewHistoryRecord]
    metrics: dict[str, int]
    provenance: list[dict[str, str]]


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _artifact_id(kind: HistoryArtifactKind, payload: dict[str, Any], path: Path) -> str:
    preferred_keys: dict[HistoryArtifactKind, list[str]] = {
        "bundle": ["bundle_id"],
        "report": ["report_id"],
        "proposal": ["proposal_id"],
        "gate_result": ["gate_result_id"],
        "staged_adoption": ["stage_id"],
        "unknown": [],
    }
    for key in preferred_keys.get(kind, []):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    for key in ["bundle_id", "report_id", "proposal_id", "gate_result_id", "stage_id"]:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return f"{kind}:{path.name}"


def _count_blocker_major(findings: list[Any]) -> int:
    total = 0
    for finding in findings:
        if isinstance(finding, dict) and finding.get("severity") in {"blocker", "major"}:
            total += 1
    return total


def record_from_payload(path: Path, payload: dict[str, Any], *, root: Path) -> ReviewHistoryRecord | None:
    schema_version = payload.get("schema_version")
    if not isinstance(schema_version, str):
        return None
    kind = _SCHEMA_TO_KIND.get(schema_version)
    if kind is None:
        return None
    redacted, report = redact_review_artifact(payload)
    if not isinstance(redacted, dict):
        return None
    raw_findings = redacted.get("findings")
    findings: list[Any] = raw_findings if isinstance(raw_findings, list) else []
    raw_aggregate = redacted.get("aggregate")
    aggregate: dict[str, Any] = raw_aggregate if isinstance(raw_aggregate, dict) else {}
    raw_by_severity = aggregate.get("by_severity")
    by_severity: dict[str, Any] = raw_by_severity if isinstance(raw_by_severity, dict) else {}
    report_blocker_major = int(by_severity.get("blocker") or 0) + int(by_severity.get("major") or 0)
    raw_subject_refs = redacted.get("subject_refs")
    subject_refs: list[dict[str, Any]] = [item for item in raw_subject_refs if isinstance(item, dict)] if isinstance(raw_subject_refs, list) else []
    return ReviewHistoryRecord(
        artifact_id=_artifact_id(kind, redacted, path),
        schema_version=schema_version,
        kind=kind,
        path=str(path.relative_to(root)),
        created_at=redacted.get("created_at"),
        bundle_id=redacted.get("bundle_id"),
        report_id=redacted.get("report_id"),
        proposal_id=redacted.get("proposal_id"),
        gate_result_id=redacted.get("gate_result_id"),
        source_report_id=redacted.get("source_report_id"),
        source_bundle_id=redacted.get("source_bundle_id"),
        source_finding_id=redacted.get("source_finding_id"),
        status=redacted.get("status"),
        decision=redacted.get("decision") or redacted.get("gate_decision"),
        verdict=redacted.get("verdict"),
        finding_count=int(aggregate.get("total") or len(findings)),
        blocker_major_count=report_blocker_major if kind == "report" else _count_blocker_major(findings),
        target_surface=redacted.get("target_surface"),
        subject_refs=subject_refs,
        redaction_counts=report.counts,
    )


def _provenance(records: list[ReviewHistoryRecord]) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for record in records:
        if record.kind == "report" and record.bundle_id:
            edges.append({"from": record.bundle_id, "to": record.report_id or record.artifact_id, "relation": "reviewed_as"})
        if record.kind == "proposal":
            if record.source_report_id:
                edges.append({"from": record.source_report_id, "to": record.proposal_id or record.artifact_id, "relation": "proposed_from"})
            if record.source_bundle_id:
                edges.append({"from": record.source_bundle_id, "to": record.proposal_id or record.artifact_id, "relation": "bundle_source"})
        if record.kind == "gate_result" and record.proposal_id:
            edges.append({"from": record.proposal_id, "to": record.gate_result_id or record.artifact_id, "relation": "gated_by"})
        if record.kind == "staged_adoption":
            if record.proposal_id:
                edges.append({"from": record.proposal_id, "to": record.artifact_id, "relation": "staged_as"})
            if record.gate_result_id:
                edges.append({"from": record.gate_result_id, "to": record.artifact_id, "relation": "stage_authorized_by"})
    return edges


def scan_review_history(root: str | Path) -> ReviewHistorySummary:
    root_path = Path(root).expanduser()
    if not root_path.exists():
        raise ReviewHistoryError(f"history root does not exist: {root_path}")
    if not root_path.is_dir():
        raise ReviewHistoryError(f"history root must be a directory: {root_path}")
    records: list[ReviewHistoryRecord] = []
    seen: set[tuple[str, str]] = set()
    for path in sorted(root_path.rglob("*.json")):
        payload = _load_json(path)
        if payload is None:
            continue
        record = record_from_payload(path, payload, root=root_path)
        if record is not None:
            key = (record.kind, record.artifact_id)
            if key in seen:
                continue
            seen.add(key)
            records.append(record)
    counts = Counter(record.kind for record in records)
    metrics = {f"{kind}_count": count for kind, count in sorted(counts.items())}
    metrics["record_count"] = len(records)
    metrics["blocker_major_count"] = sum(record.blocker_major_count for record in records)
    metrics["gate_accept_count"] = sum(1 for record in records if record.kind == "gate_result" and record.decision in {"accept", "accept_new_best"})
    metrics["gate_reject_count"] = sum(1 for record in records if record.kind == "gate_result" and record.decision == "reject")
    metrics["proposal_rejected_count"] = sum(1 for record in records if record.kind == "proposal" and record.status == "rejected")
    return ReviewHistorySummary(root=str(root_path), records=records, metrics=metrics, provenance=_provenance(records))


def show_review_history_record(root: str | Path, artifact: str) -> dict[str, Any]:
    root_path = Path(root).expanduser()
    summary = scan_review_history(root_path)
    matches = [record for record in summary.records if record.artifact_id == artifact or record.path == artifact]
    if not matches:
        raise ReviewHistoryError(f"history artifact not found: {artifact}")
    record = matches[0]
    payload = _load_json(root_path / record.path)
    if payload is None:
        raise ReviewHistoryError(f"history artifact is no longer readable JSON: {record.path}")
    redacted, report = redact_review_artifact(payload)
    return {
        "record": record.model_dump(mode="json"),
        "payload": redacted,
        "redaction_counts": report.counts,
    }
