from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from sourcebrief_shared.regression_proposal import RegressionProposal, write_regression_proposal
from sourcebrief_shared.validation_gate import (
    ValidationGateResult,
    validate_regression_proposal,
    write_validation_gate_result,
)

SLEEP_REPLAY_SCHEMA_VERSION = "sourcebrief.sleep-replay-summary.v1"


class SleepReplayError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SleepReplayCandidate(StrictModel):
    candidate_id: str = Field(min_length=1)
    recurrence_key: str = Field(min_length=1)
    occurrence_count: int = Field(ge=1)
    source_proposal_ids: list[str] = Field(default_factory=list)
    target_surface: str = Field(min_length=1)
    gate_decision: str = Field(min_length=1)
    proposal_path: str | None = None
    gate_result_path: str | None = None


class SleepReplaySummary(StrictModel):
    schema_version: Literal["sourcebrief.sleep-replay-summary.v1"] = "sourcebrief.sleep-replay-summary.v1"
    dry_run: bool = True
    source_dir: str = Field(min_length=1)
    scanned_artifacts: int = Field(ge=0)
    proposal_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    min_occurrences: int = Field(ge=2)
    max_artifacts: int = Field(ge=1)
    candidates: list[SleepReplayCandidate] = Field(default_factory=list)
    skipped: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return raw if isinstance(raw, dict) else None


def _proposal_files(root: Path, max_artifacts: int) -> tuple[list[tuple[Path, RegressionProposal]], int, list[str]]:
    proposals: list[tuple[Path, RegressionProposal]] = []
    skipped: list[str] = []
    scanned = 0
    for path in sorted(root.rglob("*.json")):
        if scanned >= max_artifacts:
            skipped.append(f"budget_exhausted:{path.relative_to(root)}")
            continue
        scanned += 1
        payload = _load_json(path)
        if not payload or payload.get("schema_version") != "sourcebrief.regression-proposal.v1":
            continue
        try:
            proposals.append((path, RegressionProposal.model_validate(payload)))
        except ValueError as exc:
            skipped.append(f"invalid_proposal:{path.relative_to(root)}:{type(exc).__name__}")
    return proposals, scanned, skipped


def _normalize_failure_mode(text: str) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    useful = [word for word in words if word not in {"the", "and", "for", "with", "that", "this", "from", "into"}]
    return "-".join(useful[:12]) or "unknown"


def _recurrence_key(proposal: RegressionProposal) -> str:
    return f"{proposal.target_surface}:{proposal.finding_type or 'unknown'}:{_normalize_failure_mode(proposal.failure_mode)}"


def _candidate_id(key: str) -> str:
    safe = re.sub(r"[^a-z0-9-]+", "-", key.lower()).strip("-")[:80] or "recurring-learning"
    return f"sleep-{safe}"


def _candidate_from_group(key: str, group: list[RegressionProposal]) -> RegressionProposal:
    first = group[0]
    source_ids = [proposal.proposal_id for proposal in group]
    evidence_refs = [f"proposal:{proposal.proposal_id}" for proposal in group]
    return RegressionProposal(
        proposal_id=_candidate_id(key),
        source_report_id="sleep-replay",
        source_bundle_id="sleep-replay",
        source_finding_id=key,
        failure_mode=f"Recurring failure across {len(group)} proposal artifacts: {first.failure_mode}",
        finding_type=first.finding_type or "regression_candidate",
        finding_severity="learning",
        claim=first.claim,
        claim_ids=first.claim_ids,
        suggested_fix=first.suggested_fix,
        confidence="medium",
        reviewer_lens="quality",
        proposal_eligibility="candidate",
        target_surface=first.target_surface,
        proposed_check=(
            "Dry-run sleep/replay candidate: replay the source proposals "
            f"{', '.join(source_ids)} and require the recurring failure to be covered by a deterministic regression before adoption. "
            f"Original check: {first.proposed_check}"
        ),
        acceptance=[
            f"At least {len(group)} independent proposal artifacts reproduce the same recurrence key `{key}`.",
            "A held-out/replay regression fails before the candidate fix and passes after it.",
            "The validation gate accepts the candidate before any staged adoption or runtime/docs/code change.",
        ],
        fixture_refs=[f"sleep-key:{key}"],
        bundle_refs=sorted({bundle for proposal in group for bundle in proposal.bundle_refs}),
        evidence_refs=evidence_refs,
        owner="sleep-replay",
        status="proposed",
        rationale="Recurring bounded review artifacts crossed the dry-run recurrence threshold; this is a proposal only, not an applied learning.",
    )


def run_sleep_replay(
    source_dir: str | Path,
    *,
    out_dir: str | Path | None = None,
    min_occurrences: int = 2,
    max_artifacts: int = 100,
    dry_run: bool = True,
) -> SleepReplaySummary:
    if not dry_run:
        raise SleepReplayError("sleep replay is dry-run only in the MVP")
    if min_occurrences < 2:
        raise SleepReplayError("min_occurrences must be at least 2")
    if max_artifacts < 1:
        raise SleepReplayError("max_artifacts must be at least 1")
    root = Path(source_dir).expanduser()
    if not root.exists():
        raise SleepReplayError(f"source directory does not exist: {root}")
    proposals, scanned, skipped = _proposal_files(root, max_artifacts)
    groups: dict[str, list[RegressionProposal]] = defaultdict(list)
    for _path, proposal in proposals:
        if proposal.status == "rejected":
            skipped.append(f"rejected:{proposal.proposal_id}")
            continue
        groups[_recurrence_key(proposal)].append(proposal)

    output_root = Path(out_dir).expanduser() if out_dir else None
    if output_root:
        output_root.mkdir(parents=True, exist_ok=True)

    candidates: list[SleepReplayCandidate] = []
    for key, group in sorted(groups.items()):
        if len(group) < min_occurrences:
            skipped.append(f"insufficient_signal:{key}:{len(group)}")
            continue
        proposal = _candidate_from_group(key, group)
        gate_result: ValidationGateResult = validate_regression_proposal(proposal)
        proposal_path: Path | None = None
        gate_path: Path | None = None
        if output_root:
            safe = _candidate_id(key)
            proposal_path = write_regression_proposal(output_root / f"{safe}.proposal.json", proposal)
            gate_path = write_validation_gate_result(output_root / f"{safe}.gate.json", gate_result)
        candidates.append(
            SleepReplayCandidate(
                candidate_id=proposal.proposal_id,
                recurrence_key=key,
                occurrence_count=len(group),
                source_proposal_ids=[item.proposal_id for item in group],
                target_surface=proposal.target_surface,
                gate_decision=gate_result.decision,
                proposal_path=str(proposal_path) if proposal_path else None,
                gate_result_path=str(gate_path) if gate_path else None,
            )
        )
    return SleepReplaySummary(
        dry_run=dry_run,
        source_dir=str(root),
        scanned_artifacts=scanned,
        proposal_count=len(proposals),
        skipped_count=len(skipped),
        min_occurrences=min_occurrences,
        max_artifacts=max_artifacts,
        candidates=candidates,
        skipped=skipped,
    )


def write_sleep_replay_summary(path: str | Path, summary: SleepReplaySummary) -> Path:
    output_path = Path(path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(summary.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return output_path
