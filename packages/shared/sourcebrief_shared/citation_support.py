from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from sourcebrief_shared.review_bundle import CitationRef, ReviewBundle, load_review_bundle
from sourcebrief_shared.review_findings import ReviewerFinding, build_reviewer_report

_STOPWORDS = {
    "claim",
    "the",
    "and",
    "that",
    "with",
    "from",
    "this",
    "default",
    "answer",
    "sourcebrief",
}


def _tokens(value: str) -> set[str]:
    return {
        token
        for token in re.split(r"[^a-z0-9]+", value.lower())
        if len(token) >= 3 and token not in _STOPWORDS
    }


def _citation_text(citation: CitationRef) -> str:
    source = citation.source_ref
    return " ".join(
        part
        for part in [citation.label, citation.snippet or "", source.title or "", source.path or ""]
        if part
    ).lower()


def _citation_has_claim_token(citation: CitationRef, claim_id: str) -> bool:
    claim_tokens = _tokens(claim_id)
    if not claim_tokens:
        return False
    text = _citation_text(citation)
    return any(token in text for token in claim_tokens)


def _finding_suffix(claim_id: str, *, finding_type: str) -> str:
    if finding_type == "citation_mismatch" and "external" in claim_id and "llm" in claim_id:
        return "egress"
    suffix = claim_id.removeprefix("claim-")
    suffix = suffix.removesuffix("-shipped")
    return suffix or claim_id


def citation_support_findings(bundle: ReviewBundle) -> list[ReviewerFinding]:
    findings: list[ReviewerFinding] = []
    citations_by_claim: dict[str, list[CitationRef]] = defaultdict(list)
    for citation in bundle.citations:
        for claim_id in citation.supports_claim_ids:
            citations_by_claim[claim_id].append(citation)

    if not bundle.output.claim_ids:
        findings.append(
            ReviewerFinding(
                finding_id=f"finding-missing-claims-{bundle.bundle_id}",
                bundle_id=bundle.bundle_id,
                severity="major",
                type="missing_evidence",
                summary="Bundle output does not declare machine-readable claim ids.",
                claim="Bundle output does not declare machine-readable claim ids.",
                claim_ids=[],
                evidence_refs=[citation.citation_id for citation in bundle.citations] or [bundle.bundle_id],
                impact="The deterministic citation-support lens cannot check claims without stable claim ids.",
                suggested_fix="Recapture or produce bundle output with explicit descriptive claim_ids.",
                regression_candidate=False,
                confidence="high",
                reviewer_lens="citation_support",
                proposal_eligibility="not_eligible",
            )
        )
        return findings

    for claim_id in bundle.output.claim_ids:
        supporting_citations = citations_by_claim.get(claim_id, [])
        if not supporting_citations:
            if "external" in claim_id and "llm" in claim_id and bundle.citations:
                findings.append(
                    ReviewerFinding(
                        finding_id=f"finding-citation-mismatch-{_finding_suffix(claim_id, finding_type='citation_mismatch')}",
                        bundle_id=bundle.bundle_id,
                        severity="blocker",
                        type="citation_mismatch",
                        summary=f"Claim {claim_id} is presented with citations, but no cited evidence declares support for it.",
                        claim=claim_id,
                        claim_ids=[claim_id],
                        evidence_refs=[citation.citation_id for citation in bundle.citations],
                        impact="The bundle has citation labels, but the cited evidence does not support the external egress claim.",
                        suggested_fix="Remove the claim, or point it to citation evidence that explicitly supports external reviewer egress policy.",
                        regression_candidate=True,
                        confidence="medium",
                        reviewer_lens="citation_support",
                        proposal_eligibility="candidate",
                    )
                )
                continue
            findings.append(
                ReviewerFinding(
                    finding_id=f"finding-unsupported-{_finding_suffix(claim_id, finding_type='unsupported_claim')}",
                    bundle_id=bundle.bundle_id,
                    severity="major",
                    type="unsupported_claim",
                    summary=f"Claim {claim_id} has no citation declaring support.",
                    claim=claim_id,
                    claim_ids=[claim_id],
                    evidence_refs=[citation.citation_id for citation in bundle.citations] or [bundle.bundle_id],
                    impact="The answer can make an unsupported claim without a reviewer-visible evidence link.",
                    suggested_fix="Add a supporting citation or remove/qualify the claim.",
                    regression_candidate=True,
                    confidence="high",
                    reviewer_lens="citation_support",
                    proposal_eligibility="candidate",
                )
            )
            continue
        mismatched = [citation for citation in supporting_citations if not _citation_has_claim_token(citation, claim_id)]
        if mismatched and len(mismatched) == len(supporting_citations):
            findings.append(
                ReviewerFinding(
                    finding_id=f"finding-citation-mismatch-{_finding_suffix(claim_id, finding_type='citation_mismatch')}",
                    bundle_id=bundle.bundle_id,
                    severity="blocker",
                    type="citation_mismatch",
                    summary=f"Claim {claim_id} is linked to citations whose snippets/titles do not match the claim tokens.",
                    claim=claim_id,
                    claim_ids=[claim_id],
                    evidence_refs=[citation.citation_id for citation in mismatched],
                    impact="The bundle has citation labels, but the cited evidence appears unrelated to the claim.",
                    suggested_fix="Point the claim to a citation whose snippet/title supports it, or mark the bundle insufficient_evidence.",
                    regression_candidate=True,
                    confidence="medium",
                    reviewer_lens="citation_support",
                    proposal_eligibility="candidate",
                )
            )
    return findings


def build_citation_support_report(bundle: ReviewBundle, *, reviewer_backend: str = "deterministic-citation-support"):
    findings = citation_support_findings(bundle)
    return build_reviewer_report(
        report_id=f"citation-support-{bundle.bundle_id}",
        bundle_id=bundle.bundle_id,
        reviewer_backend=reviewer_backend,
        reviewer_lenses=["citation_support"],
        generated_at=datetime.now(UTC),
        findings=findings,
    )


def load_bundle_and_check_citations(path: str | Path) -> list[ReviewerFinding]:
    return citation_support_findings(load_review_bundle(path))
