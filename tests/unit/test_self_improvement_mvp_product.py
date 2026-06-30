from __future__ import annotations

from pathlib import Path

from sourcebrief_shared.review_history import scan_review_history
from sourcebrief_shared.self_improvement_mvp import (
    load_default_mvp_smoke_bundle,
    run_mvp_smoke_path,
)
from sourcebrief_shared.self_improvement_sleep import run_sleep_replay


def test_mvp_smoke_runs_from_embedded_fixture_without_docs_tree(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    bundle = load_default_mvp_smoke_bundle()
    assert bundle.bundle_id == "rb-golden-unsupported-claim-001"

    summary = run_mvp_smoke_path(out_dir=tmp_path / "smoke")

    assert summary["schema_version"] == "sourcebrief.self-improvement-mvp-smoke.v1"
    assert summary["status"] == "completed"
    assert summary["gate_decision"] == "accept"
    assert summary["no_silent_mutation"] is True
    assert (tmp_path / "smoke" / "review-bundle.json").exists()
    assert (tmp_path / "smoke" / "review-report.json").exists()
    assert (tmp_path / "smoke" / "regression-proposal.json").exists()
    assert (tmp_path / "smoke" / "validation-gate-result.json").exists()
    assert (tmp_path / "smoke" / "staged" / summary["proposal_id"] / "receipt.json").exists()

    history = scan_review_history(tmp_path / "smoke")
    assert history.metrics["record_count"] >= 5
    assert history.metrics["gate_accept_count"] == 1


def test_sleep_replay_dry_run_mines_bounded_smoke_proposals(tmp_path: Path) -> None:
    first = run_mvp_smoke_path(out_dir=tmp_path / "one")
    second = run_mvp_smoke_path(out_dir=tmp_path / "two")

    summary = run_sleep_replay(tmp_path, out_dir=tmp_path / "sleep", min_occurrences=2, max_artifacts=100)

    assert summary.dry_run is True
    assert summary.candidates
    candidate = summary.candidates[0]
    assert set(candidate.source_proposal_ids) == {first["proposal_id"], second["proposal_id"]}
    assert candidate.gate_decision in {"accept", "accept_new_best"}
    assert candidate.proposal_path is not None
    assert candidate.gate_result_path is not None
