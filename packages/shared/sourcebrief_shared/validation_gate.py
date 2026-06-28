from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
            "\n".join(proposal.evidence_refs),
        ]
    ).lower()


def _reject_result(
    *,
    proposal_id: str,
    checks: dict[str, CheckStatus],
    evidence_refs: list[str] | None = None,
    reason: str,
) -> ValidationGateResult:
    return ValidationGateResult(
        gate_result_id=f"gate-{proposal_id}",
        proposal_id=proposal_id,
        decision="reject",
        baseline_score=1.0,
        candidate_score=0.0,
        checks=checks,
        evidence_refs=evidence_refs or [],
        reason=reason,
        rejected_learning={"proposal_id": proposal_id, "reason": reason},
    )


def validate_regression_proposal(proposal: RegressionProposal) -> ValidationGateResult:
    checks: dict[str, CheckStatus] = {
        "schema_valid": "pass",
        "has_evidence_refs": "pass" if proposal.evidence_refs else "fail",
        "not_previously_rejected": "pass" if proposal.status != "rejected" else "fail",
        "target_surface_known": "pass" if proposal.target_surface != "unknown" else "fail",
        "harmful_auto_learning_guard": "pass",
        "no_llm_judge_only_learning": "pass",
        "security_policy_alignment": "pass",
        "golden_negative_controls": "pass",
    }
    text = _proposal_text(proposal)
    harmful_terms = [
        "always tell",
        "nightly optimizer",
        "updates skills automatically",
        "without user involvement",
    ]
    security_conflicts = [
        "private review bundles may use external llm",
        "private bundles may use external llm",
        "external llm reviewer backends by default",
        "external reviewer backends by default",
        "sent to any external llm by default",
    ]
    if any(term in text for term in harmful_terms):
        checks["harmful_auto_learning_guard"] = "fail"
        checks["golden_negative_controls"] = "fail"
    if any(term in text for term in security_conflicts):
        checks["security_policy_alignment"] = "fail"
    if "llm judge" in text and not any(ref.startswith(("cite-", "proof-", "gate-")) for ref in proposal.evidence_refs):
        checks["no_llm_judge_only_learning"] = "fail"
    failed = [name for name, status in checks.items() if status == "fail"]
    if failed:
        reason = f"Rejected because deterministic gate checks failed: {', '.join(sorted(failed))}."
        return _reject_result(
            proposal_id=proposal.proposal_id,
            checks=checks,
            evidence_refs=proposal.evidence_refs,
            reason=reason,
        )
    return ValidationGateResult(
        gate_result_id=f"gate-{proposal.proposal_id}",
        proposal_id=proposal.proposal_id,
        decision="accept",
        baseline_score=1.0,
        candidate_score=1.0,
        checks=checks,
        evidence_refs=proposal.evidence_refs,
        reason="Accepted by deterministic MVP gate: schema, evidence refs, status, target surface, security alignment, and golden negative controls passed.",
    )


def validate_regression_proposal_file(path: str | Path) -> ValidationGateResult:
    proposal_path = Path(path)
    raw: dict[str, Any] = {}
    try:
        raw_obj = json.loads(proposal_path.read_text(encoding="utf-8"))
        if isinstance(raw_obj, dict):
            raw = raw_obj
        proposal = RegressionProposal.model_validate(raw_obj)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        proposal_id = str(raw.get("proposal_id") or proposal_path.stem or "invalid-proposal")
        checks: dict[str, CheckStatus] = {
            "schema_valid": "fail",
            "has_evidence_refs": "not_applicable",
            "not_previously_rejected": "not_applicable",
            "target_surface_known": "not_applicable",
            "no_llm_judge_only_learning": "not_applicable",
            "harmful_auto_learning_guard": "not_applicable",
            "security_policy_alignment": "not_applicable",
            "golden_negative_controls": "not_applicable",
        }
        reason = f"Rejected because proposal schema validation failed: {type(exc).__name__}: {str(exc).splitlines()[0]}"
        return _reject_result(proposal_id=proposal_id, checks=checks, reason=reason)
    return validate_regression_proposal(proposal)


def write_validation_gate_result(path: str | Path, result: ValidationGateResult) -> Path:
    output_path = Path(path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return output_path
