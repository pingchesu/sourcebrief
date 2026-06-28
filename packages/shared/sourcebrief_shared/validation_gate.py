from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sourcebrief_shared.regression_proposal import RegressionProposal

VALIDATION_GATE_SCHEMA_VERSION = "sourcebrief.validation-gate-result.v1"
GateDecision = Literal["accept_new_best", "accept", "reject"]
CheckStatus = Literal["pass", "fail", "not_applicable"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ValidationGateResult(StrictModel):
    schema_version: Literal["sourcebrief.validation-gate-result.v1"] = "sourcebrief.validation-gate-result.v1"
    gate_result_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    decision: GateDecision
    baseline_score: float = Field(ge=0.0, le=1.0)
    candidate_score: float = Field(ge=0.0, le=1.0)
    checks: dict[str, CheckStatus]
    evidence_refs: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    rejected_learning: dict[str, str] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def load_regression_proposal(path: str | Path) -> RegressionProposal:
    return RegressionProposal.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _proposal_text(proposal: RegressionProposal) -> str:
    return "\n".join(
        [
            proposal.failure_mode,
            proposal.proposed_check,
            proposal.rationale,
            "\n".join(proposal.acceptance),
        ]
    ).lower()


def validate_regression_proposal(proposal: RegressionProposal) -> ValidationGateResult:
    checks: dict[str, CheckStatus] = {
        "schema_valid": "pass",
        "has_evidence_refs": "pass" if proposal.evidence_refs else "fail",
        "not_previously_rejected": "pass" if proposal.status != "rejected" else "fail",
        "harmful_auto_learning_guard": "pass",
        "target_surface_known": "pass" if proposal.target_surface != "unknown" else "fail",
    }
    text = _proposal_text(proposal)
    harmful_terms = ["always tell", "nightly optimizer", "updates skills automatically", "without user involvement"]
    if any(term in text for term in harmful_terms):
        checks["harmful_auto_learning_guard"] = "fail"
    failed = [name for name, status in checks.items() if status == "fail"]
    if failed:
        reason = f"Rejected because deterministic gate checks failed: {', '.join(sorted(failed))}."
        return ValidationGateResult(
            gate_result_id=f"gate-{proposal.proposal_id}",
            proposal_id=proposal.proposal_id,
            decision="reject",
            baseline_score=1.0,
            candidate_score=0.0,
            checks=checks,
            evidence_refs=proposal.evidence_refs,
            reason=reason,
            rejected_learning={"proposal_id": proposal.proposal_id, "reason": reason},
        )
    return ValidationGateResult(
        gate_result_id=f"gate-{proposal.proposal_id}",
        proposal_id=proposal.proposal_id,
        decision="accept",
        baseline_score=1.0,
        candidate_score=1.0,
        checks=checks,
        evidence_refs=proposal.evidence_refs,
        reason="Accepted by deterministic MVP gate: schema, evidence refs, status, target surface, and harmful-learning guard passed.",
    )


def write_validation_gate_result(path: str | Path, result: ValidationGateResult) -> Path:
    output_path = Path(path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return output_path
