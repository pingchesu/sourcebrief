import json
import shutil
from pathlib import Path

import pytest

from sourcebrief_shared.review_history import (
    ReviewHistoryError,
    scan_review_history,
    show_review_history_record,
)
from sourcebrief_shared.staged_adoption import stage_regression_proposal

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs" / "examples" / "self-improvement"


def _history_dir(tmp_path: Path) -> Path:
    root = tmp_path / "history"
    root.mkdir()
    shutil.copyfile(EXAMPLES / "review-bundle-docs-answer.json", root / "bundle.json")
    shutil.copyfile(EXAMPLES / "reviewer-report-example.json", root / "report.json")
    proposal = json.loads((EXAMPLES / "regression-proposal-example.json").read_text(encoding="utf-8"))
    proposal["rationale"] = "safe rationale with token=abcdefghijklmnopqrstuvwxyz12345"
    (root / "proposal.json").write_text(json.dumps(proposal), encoding="utf-8")
    shutil.copyfile(EXAMPLES / "validation-gate-result-example.json", root / "gate.json")
    stage_regression_proposal(
        proposal_path=root / "proposal.json",
        gate_result_path=root / "gate.json",
        out_dir=root / "staged",
    )
    return root


def test_scan_review_history_links_provenance_and_metrics(tmp_path: Path) -> None:
    root = _history_dir(tmp_path)
    summary = scan_review_history(root)

    assert summary.metrics["record_count"] == 5
    assert summary.metrics["bundle_count"] == 1
    assert summary.metrics["report_count"] == 1
    assert summary.metrics["proposal_count"] == 1
    assert summary.metrics["gate_result_count"] == 1
    assert summary.metrics["staged_adoption_count"] == 1
    assert summary.metrics["gate_accept_count"] == 1
    assert any(edge["relation"] == "reviewed_as" for edge in summary.provenance)
    assert any(edge["relation"] == "gated_by" for edge in summary.provenance)
    assert any(edge["relation"] == "staged_as" for edge in summary.provenance)


def test_show_review_history_record_returns_redacted_payload(tmp_path: Path) -> None:
    root = _history_dir(tmp_path)
    shown = show_review_history_record(root, "proposal-finding-learning-quickstart-gap")

    assert shown["record"]["kind"] == "proposal"
    assert "abcdefghijklmnopqrstuvwxyz12345" not in json.dumps(shown, sort_keys=True)
    assert shown["redaction_counts"]


def test_scan_review_history_requires_existing_directory(tmp_path: Path) -> None:
    with pytest.raises(ReviewHistoryError, match="does not exist"):
        scan_review_history(tmp_path / "missing")
