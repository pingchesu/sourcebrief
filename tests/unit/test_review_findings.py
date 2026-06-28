from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from sourcebrief_shared.review_findings import (
    FINDING_TYPES,
    REVIEW_FINDING_SCHEMA_VERSION,
    REVIEW_REPORT_SCHEMA_VERSION,
    ReviewerFinding,
    ReviewerReport,
    aggregate_findings,
    build_reviewer_report,
    finding_to_proposal_rule,
    severity_blocks_adoption,
)
from sourcebrief_shared.self_improvement_golden import validate_golden_manifest

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE_REPORT = ROOT / "docs" / "examples" / "self-improvement" / "reviewer-report-example.json"
GOLDEN_MANIFEST = ROOT / "docs" / "examples" / "self-improvement" / "golden" / "manifest.json"


def _finding(**overrides) -> ReviewerFinding:
    payload = {
        "finding_id": "finding-1",
        "bundle_id": "bundle-1",
        "severity": "major",
        "type": "unsupported_claim",
        "summary": "Unsupported claim.",
        "claim": "A future feature is shipped.",
        "claim_ids": ["claim-1"],
        "evidence_refs": ["cite-1"],
        "impact": "Would mislead users.",
        "suggested_fix": "Use future-work wording.",
        "regression_candidate": True,
        "confidence": "high",
        "reviewer_lens": "scope",
        "proposal_eligibility": "candidate",
    }
    payload.update(overrides)
    return ReviewerFinding.model_validate(payload)


def test_reviewer_report_example_validates_and_aggregates() -> None:
    report = ReviewerReport.model_validate_json(EXAMPLE_REPORT.read_text(encoding="utf-8"))

    assert report.schema_version == REVIEW_REPORT_SCHEMA_VERSION
    assert {finding.schema_version for finding in report.findings} == {REVIEW_FINDING_SCHEMA_VERSION}
    assert report.aggregate.total == 4
    assert report.aggregate.blocks_adoption is True
    assert report.aggregate.by_severity["blocker"] == 1
    assert report.aggregate.by_severity["rejected_learning"] == 1
    assert report.aggregate.proposal_candidate_count == 3
    assert aggregate_findings(report.findings) == report.aggregate


def test_blocker_and_major_findings_require_evidence_refs() -> None:
    with pytest.raises(ValidationError, match="blocker/major findings require evidence_refs"):
        _finding(evidence_refs=[])

    minor = _finding(
        severity="minor",
        evidence_refs=[],
        regression_candidate=False,
        proposal_eligibility="not_eligible",
    )
    assert minor.evidence_refs == []


def test_proposal_eligibility_requires_regression_candidate() -> None:
    with pytest.raises(ValidationError, match="proposal candidates must set regression_candidate=true"):
        _finding(regression_candidate=False, proposal_eligibility="candidate")

    with pytest.raises(ValidationError, match="proposal_eligibility must be candidate"):
        _finding(proposal_eligibility="not_eligible")

    with pytest.raises(ValidationError, match="proposal_eligibility must be not_eligible"):
        _finding(severity="rejected_learning", type="rejected_proposal", regression_candidate=True, proposal_eligibility="candidate")


def test_reviewer_report_rejects_inconsistent_aggregate() -> None:
    finding = _finding()
    aggregate = aggregate_findings([finding]).model_copy(update={"total": 999})

    with pytest.raises(ValidationError, match="aggregate must equal"):
        ReviewerReport(
            report_id="report-1",
            bundle_id="bundle-1",
            reviewer_backend="mock",
            reviewer_lenses=["scope"],
            generated_at=datetime.now(UTC),
            verdict="BLOCK",
            findings=[finding],
            aggregate=aggregate,
        )


def test_finding_to_proposal_rule_and_severity_blocks() -> None:
    assert severity_blocks_adoption("blocker") is True
    assert severity_blocks_adoption("major") is True
    assert severity_blocks_adoption("learning") is False
    assert finding_to_proposal_rule(_finding(confidence="high")) == "candidate"
    assert finding_to_proposal_rule(_finding(confidence="low", proposal_eligibility="requires_human_review")) == "requires_human_review"
    assert (
        finding_to_proposal_rule(
            _finding(severity="rejected_learning", type="rejected_proposal", regression_candidate=False, proposal_eligibility="not_eligible")
        )
        == "not_eligible"
    )


def test_reviewer_report_requires_findings_to_match_bundle_id() -> None:
    with pytest.raises(ValidationError, match="all findings must match report bundle_id"):
        build_reviewer_report(
            report_id="report-1",
            bundle_id="bundle-1",
            reviewer_backend="mock",
            reviewer_lenses=["scope"],
            generated_at=datetime.now(UTC),
            findings=[_finding(bundle_id="other-bundle")],
        )


def test_golden_manifest_expected_finding_types_are_in_taxonomy() -> None:
    summary = validate_golden_manifest(GOLDEN_MANIFEST)
    assert set(summary["finding_types"]).issubset(set(FINDING_TYPES))
