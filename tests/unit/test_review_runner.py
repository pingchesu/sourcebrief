from pathlib import Path

import pytest

from sourcebrief_shared.review_bundle import load_review_bundle
from sourcebrief_shared.review_findings import ReviewerReport
from sourcebrief_shared.review_runner import (
    ReviewRunnerError,
    ReviewRunOptions,
    build_reviewer_prompt,
    run_review_bundle,
    run_review_bundle_path,
    write_reviewer_report,
)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs" / "examples" / "self-improvement"
GOLDEN = EXAMPLES / "golden"


def test_runner_passes_safe_bundle() -> None:
    bundle = load_review_bundle(EXAMPLES / "review-bundle-docs-answer.json")
    report = run_review_bundle(bundle)

    assert report.schema_version == "sourcebrief.review-report.v1"
    assert report.verdict == "PASS"
    assert report.findings == []
    assert report.aggregate.total == 0
    assert build_reviewer_prompt(bundle).startswith("You are a SourceBrief self-improvement reviewer")


def test_runner_blocks_citation_mismatch_fixture() -> None:
    report = run_review_bundle_path(GOLDEN / "review-bundle-citation-mismatch.json")

    assert report.verdict == "BLOCK"
    assert report.aggregate.blocks_adoption is True
    assert report.findings[0].type == "citation_mismatch"
    assert report.findings[0].evidence_refs == ["cite-security-intro"]


def test_runner_writes_report_artifact(tmp_path: Path) -> None:
    report = run_review_bundle_path(GOLDEN / "review-bundle-unsupported-claim.json")
    output = write_reviewer_report(tmp_path / "reports" / "review.json", report)

    loaded = ReviewerReport.model_validate_json(output.read_text(encoding="utf-8"))
    assert loaded.verdict == "BLOCK"
    assert loaded.findings[0].type == "unsupported_claim"


def test_runner_fails_closed_on_incomplete_bundle_unless_allowed() -> None:
    bundle = load_review_bundle(EXAMPLES / "review-bundle-docs-answer.json")
    data = bundle.model_dump(mode="json")
    data["security"]["completeness"] = "insufficient_evidence"
    incomplete = type(bundle).model_validate(data)

    with pytest.raises(ReviewRunnerError, match="insufficient_evidence"):
        run_review_bundle(incomplete)

    report = run_review_bundle(incomplete, options=ReviewRunOptions(allow_incomplete=True))
    assert report.verdict == "BLOCK"
    assert report.findings[0].type == "missing_evidence"


def test_runner_enforces_bundle_backend_policy() -> None:
    bundle = load_review_bundle(EXAMPLES / "review-bundle-docs-answer.json")

    with pytest.raises(ReviewRunnerError, match="not allowed by bundle policy"):
        run_review_bundle(bundle, options=ReviewRunOptions(backend="deterministic"))
