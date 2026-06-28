from pathlib import Path

from sourcebrief_shared.regression_proposal import RegressionProposal
from sourcebrief_shared.validation_gate import (
    ValidationGateResult,
    load_regression_proposal,
    validate_regression_proposal,
    write_validation_gate_result,
)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "docs" / "examples" / "self-improvement" / "regression-proposal-example.json"


def test_validation_gate_accepts_supported_proposal() -> None:
    proposal = load_regression_proposal(EXAMPLE)
    result = validate_regression_proposal(proposal)

    assert result.schema_version == "sourcebrief.validation-gate-result.v1"
    assert result.decision == "accept"
    assert result.checks["schema_valid"] == "pass"
    assert result.checks["has_evidence_refs"] == "pass"
    assert result.rejected_learning is None


def test_validation_gate_rejects_harmful_auto_learning() -> None:
    proposal = RegressionProposal(
        proposal_id="proposal-nightly-optimizer-claim-rule",
        source_report_id="report-1",
        source_bundle_id="bundle-1",
        source_finding_id="finding-1",
        failure_mode="LLM judge suggested a broad rule.",
        target_surface="skill",
        proposed_check="Always tell users SourceBrief has a nightly optimizer that updates skills automatically.",
        acceptance=["The gate should reject this harmful rule."],
        evidence_refs=["gate-reject-llm-judge-only-learning"],
        status="proposed",
        rationale="This would encode future work as shipped behavior.",
    )

    result = validate_regression_proposal(proposal)
    assert result.decision == "reject"
    assert result.checks["harmful_auto_learning_guard"] == "fail"
    assert result.rejected_learning is not None
    assert result.rejected_learning["proposal_id"] == proposal.proposal_id


def test_validation_gate_result_round_trips(tmp_path: Path) -> None:
    result = validate_regression_proposal(load_regression_proposal(EXAMPLE))
    output = write_validation_gate_result(tmp_path / "gate.json", result)

    loaded = ValidationGateResult.model_validate_json(output.read_text(encoding="utf-8"))
    assert loaded.decision == "accept"
    assert loaded.proposal_id == result.proposal_id
