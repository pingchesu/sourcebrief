import shlex
from pathlib import Path

import pytest

from sourcebrief_shared.staged_adoption import (
    StagedAdoptionError,
    StagedAdoptionReceipt,
    load_regression_proposal,
    load_validation_gate_result,
    stage_regression_proposal,
    validate_stage_inputs,
)

ROOT = Path(__file__).resolve().parents[2]
PROPOSAL = ROOT / "docs" / "examples" / "self-improvement" / "regression-proposal-example.json"
GATE = ROOT / "docs" / "examples" / "self-improvement" / "validation-gate-result-example.json"


def test_stage_regression_proposal_writes_patch_receipt_and_copies_sources(tmp_path: Path) -> None:
    receipt = stage_regression_proposal(proposal_path=PROPOSAL, gate_result_path=GATE, out_dir=tmp_path)

    assert receipt.schema_version == "sourcebrief.staged-adoption-receipt.v1"
    assert receipt.proposal_id == "proposal-finding-learning-quickstart-gap"
    assert receipt.gate_decision == "accept"
    assert receipt.human_review_required is True
    assert shlex.split(receipt.apply_command) == receipt.apply_args
    assert shlex.split(receipt.rollback_command) == receipt.rollback_args
    assert shlex.split(receipt.discard_stage_command) == receipt.discard_stage_args
    assert receipt.apply_args == ["git", "apply", receipt.patch_path]

    stage_dir = Path(receipt.stage_dir)
    assert (stage_dir / "proposal.json").exists()
    assert (stage_dir / "gate-result.json").exists()
    assert (stage_dir / "proposal.patch").exists()
    assert (stage_dir / "README.md").exists()
    receipt_path = stage_dir / "receipt.json"
    assert receipt_path.exists()

    loaded = StagedAdoptionReceipt.model_validate_json(receipt_path.read_text(encoding="utf-8"))
    assert loaded.files
    assert {file.kind for file in loaded.files} == {"proposal", "gate_result", "patch", "summary"}
    assert all(file.sha256.startswith("sha256:") for file in loaded.files)

    patch_text = (stage_dir / "proposal.patch").read_text(encoding="utf-8")
    assert "diff --git" in patch_text
    assert "docs/self-improvement/staged-proposals/proposal-finding-learning-quickstart-gap.md" in patch_text
    assert "Applying it does not change runtime behavior" in patch_text
    assert "proposal-finding-learning-quickstart-gap" in patch_text


def test_stage_quotes_shell_commands_with_spaces(tmp_path: Path) -> None:
    out_dir = tmp_path / "stage dir with spaces"

    receipt = stage_regression_proposal(proposal_path=PROPOSAL, gate_result_path=GATE, out_dir=out_dir)

    assert "'" in receipt.apply_command
    assert shlex.split(receipt.apply_command) == ["git", "apply", receipt.patch_path]
    assert shlex.split(receipt.rollback_command) == ["git", "apply", "-R", receipt.patch_path]
    assert shlex.split(receipt.discard_stage_command) == ["rm", "-rf", receipt.stage_dir]


def test_stage_refuses_to_overwrite_existing_stage_dir(tmp_path: Path) -> None:
    receipt = stage_regression_proposal(proposal_path=PROPOSAL, gate_result_path=GATE, out_dir=tmp_path)
    readme = Path(receipt.stage_dir) / "README.md"
    readme.write_text("human review notes\n", encoding="utf-8")

    with pytest.raises(StagedAdoptionError, match="already exists and is not empty"):
        stage_regression_proposal(proposal_path=PROPOSAL, gate_result_path=GATE, out_dir=tmp_path)
    assert readme.read_text(encoding="utf-8") == "human review notes\n"


def test_stage_rejects_inconsistent_accepted_gate_result() -> None:
    proposal = load_regression_proposal(PROPOSAL)
    gate = load_validation_gate_result(GATE).model_copy(update={"checks": {"schema_valid": "fail"}})

    with pytest.raises(StagedAdoptionError, match="failed checks"):
        validate_stage_inputs(proposal, gate)


def test_stage_rejects_accepted_gate_with_rejected_learning() -> None:
    proposal = load_regression_proposal(PROPOSAL)
    gate = load_validation_gate_result(GATE).model_copy(update={"rejected_learning": {"proposal_id": proposal.proposal_id}})

    with pytest.raises(StagedAdoptionError, match="must not contain rejected_learning"):
        validate_stage_inputs(proposal, gate)


def test_stage_requires_accepted_gate_result() -> None:
    proposal = load_regression_proposal(PROPOSAL)
    gate = load_validation_gate_result(GATE).model_copy(update={"decision": "reject"})

    with pytest.raises(StagedAdoptionError, match="only accepted gate results"):
        validate_stage_inputs(proposal, gate)


def test_stage_requires_matching_proposal_id() -> None:
    proposal = load_regression_proposal(PROPOSAL)
    gate = load_validation_gate_result(GATE).model_copy(update={"proposal_id": "proposal-other"})

    with pytest.raises(StagedAdoptionError, match="does not match"):
        validate_stage_inputs(proposal, gate)
