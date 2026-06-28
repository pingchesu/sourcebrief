from pathlib import Path

from sourcebrief_shared.citation_support import (
    build_citation_support_report,
    load_bundle_and_check_citations,
)
from sourcebrief_shared.review_bundle import load_review_bundle

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs" / "examples" / "self-improvement"
GOLDEN = EXAMPLES / "golden"


def test_supported_cited_answer_has_no_citation_support_findings() -> None:
    findings = load_bundle_and_check_citations(EXAMPLES / "review-bundle-docs-answer.json")
    assert findings == []


def test_unsupported_claim_bundle_yields_major_finding_with_evidence_refs() -> None:
    findings = load_bundle_and_check_citations(GOLDEN / "review-bundle-unsupported-claim.json")

    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "major"
    assert finding.type == "unsupported_claim"
    assert finding.claim_ids == ["claim-nightly-optimizer-shipped"]
    assert finding.evidence_refs == ["cite-non-goals"]
    assert finding.reviewer_lens == "citation_support"


def test_citation_mismatch_bundle_yields_blocker_with_citation_id() -> None:
    findings = load_bundle_and_check_citations(GOLDEN / "review-bundle-citation-mismatch.json")

    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "blocker"
    assert finding.type == "citation_mismatch"
    assert finding.claim_ids == ["claim-external-llm-default"]
    assert finding.evidence_refs == ["cite-security-intro"]
    assert finding.reviewer_lens == "citation_support"


def test_citation_support_report_aggregates_findings() -> None:
    bundle = load_review_bundle(GOLDEN / "review-bundle-citation-mismatch.json")
    report = build_citation_support_report(bundle)

    assert report.bundle_id == bundle.bundle_id
    assert report.reviewer_backend == "deterministic-citation-support"
    assert report.reviewer_lenses == ["citation_support"]
    assert report.aggregate.total == 1
    assert report.aggregate.blocks_adoption is True
    assert report.aggregate.by_type == {"citation_mismatch": 1}
    assert report.aggregate.proposal_candidate_count == 1


def test_opaque_or_missing_claim_ids_fail_closed() -> None:
    bundle = load_review_bundle(EXAMPLES / "review-bundle-docs-answer.json")
    data = bundle.model_dump(mode="json")
    data["output"]["claim_ids"] = ["claim-1"]
    data["citations"][0]["supports_claim_ids"] = ["claim-1"]
    opaque = type(bundle).model_validate(data)

    findings = build_citation_support_report(opaque).findings
    assert findings[0].type == "citation_mismatch"

    data["output"]["claim_ids"] = []
    data["citations"][0]["supports_claim_ids"] = []
    missing = type(bundle).model_validate(data)
    findings = build_citation_support_report(missing).findings
    assert findings[0].type == "missing_evidence"
