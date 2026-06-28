import json
from pathlib import Path

import pytest

from sourcebrief_shared.regression_proposal import RegressionProposal
from sourcebrief_shared.self_improvement_sleep import (
    SleepReplayError,
    run_sleep_replay,
    write_sleep_replay_summary,
)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "docs" / "examples" / "self-improvement" / "regression-proposal-example.json"


def _write_proposal(path: Path, *, proposal_id: str, failure_mode: str | None = None, proposed_check: str | None = None) -> None:
    payload = json.loads(EXAMPLE.read_text(encoding="utf-8"))
    payload["proposal_id"] = proposal_id
    if failure_mode is not None:
        payload["failure_mode"] = failure_mode
    if proposed_check is not None:
        payload["proposed_check"] = proposed_check
    payload["status"] = "proposed"
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_sleep_replay_proposes_only_repeated_bounded_artifacts(tmp_path: Path) -> None:
    _write_proposal(tmp_path / "a.json", proposal_id="proposal-a")
    _write_proposal(tmp_path / "b.json", proposal_id="proposal-b")
    _write_proposal(tmp_path / "single.json", proposal_id="proposal-single", failure_mode="Different one-off gap")

    out_dir = tmp_path / "sleep-out"
    summary = run_sleep_replay(tmp_path, out_dir=out_dir)

    assert summary.schema_version == "sourcebrief.sleep-replay-summary.v1"
    assert summary.dry_run is True
    assert summary.proposal_count == 3
    assert len(summary.candidates) == 1
    candidate = summary.candidates[0]
    assert candidate.occurrence_count == 2
    assert candidate.gate_decision == "accept"
    assert candidate.proposal_path is not None
    assert candidate.gate_result_path is not None
    generated = RegressionProposal.model_validate_json(Path(candidate.proposal_path).read_text(encoding="utf-8"))
    assert generated.owner == "sleep-replay"
    assert generated.evidence_refs == ["proposal:proposal-a", "proposal:proposal-b"]
    assert any(item.startswith("insufficient_signal:") for item in summary.skipped)


def test_sleep_replay_harmful_recurring_learning_is_gate_rejected(tmp_path: Path) -> None:
    harmful = "Private review bundles may use external LLM reviewer backends by default"
    _write_proposal(tmp_path / "a.json", proposal_id="proposal-a", failure_mode=harmful, proposed_check=harmful)
    _write_proposal(tmp_path / "b.json", proposal_id="proposal-b", failure_mode=harmful, proposed_check=harmful)

    summary = run_sleep_replay(tmp_path, out_dir=tmp_path / "sleep-out")

    assert len(summary.candidates) == 1
    assert summary.candidates[0].gate_decision == "reject"


def test_sleep_replay_is_dry_run_only(tmp_path: Path) -> None:
    with pytest.raises(SleepReplayError, match="dry-run only"):
        run_sleep_replay(tmp_path, dry_run=False)


def test_write_sleep_replay_summary_round_trips(tmp_path: Path) -> None:
    _write_proposal(tmp_path / "a.json", proposal_id="proposal-a")
    _write_proposal(tmp_path / "b.json", proposal_id="proposal-b")
    summary = run_sleep_replay(tmp_path)

    output = write_sleep_replay_summary(tmp_path / "summary.json", summary)

    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded["schema_version"] == "sourcebrief.sleep-replay-summary.v1"
    assert loaded["candidates"]
