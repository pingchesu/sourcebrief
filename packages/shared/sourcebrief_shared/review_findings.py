from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

REVIEW_FINDING_SCHEMA_VERSION = "sourcebrief.review-finding.v1"
REVIEW_REPORT_SCHEMA_VERSION = "sourcebrief.review-report.v1"

FINDING_SEVERITIES = ("blocker", "major", "minor", "learning", "rejected_learning")
FINDING_TYPES = (
    "unsupported_claim",
    "citation_mismatch",
    "missing_evidence",
    "stale_source",
    "scope_creep",
    "unsafe_mutation",
    "quickstart_dx_failure",
    "regression_candidate",
    "overclaim",
    "no_proof",
    "rejected_proposal",
)

FindingSeverity = Literal["blocker", "major", "minor", "learning", "rejected_learning"]
FindingType = Literal[
    "unsupported_claim",
    "citation_mismatch",
    "missing_evidence",
    "stale_source",
    "scope_creep",
    "unsafe_mutation",
    "quickstart_dx_failure",
    "regression_candidate",
    "overclaim",
    "no_proof",
    "rejected_proposal",
]
ReviewerLens = Literal[
    "citation_support",
    "scope",
    "missing_evidence",
    "product_dx",
    "safety",
    "regression",
]
FindingConfidence = Literal["high", "medium", "low"]
ProposalEligibility = Literal["not_eligible", "candidate", "requires_human_review"]
ReviewVerdict = Literal["PASS", "BLOCK", "RISK"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewerFinding(StrictModel):
    schema_version: Literal["sourcebrief.review-finding.v1"] = "sourcebrief.review-finding.v1"
    finding_id: str = Field(min_length=1)
    bundle_id: str = Field(min_length=1)
    severity: FindingSeverity
    type: FindingType
    summary: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    impact: str = Field(min_length=1)
    suggested_fix: str = Field(min_length=1)
    regression_candidate: bool = False
    confidence: FindingConfidence
    reviewer_lens: ReviewerLens
    proposal_eligibility: ProposalEligibility = "not_eligible"

    @field_validator("evidence_refs")
    @classmethod
    def blocking_findings_need_evidence(cls, value: list[str], info: Any) -> list[str]:
        severity = info.data.get("severity")
        if severity in {"blocker", "major"} and not value:
            raise ValueError("blocker/major findings require evidence_refs")
        return value

    @field_validator("proposal_eligibility")
    @classmethod
    def proposal_candidates_need_regression_flag(
        cls,
        value: ProposalEligibility,
        info: Any,
    ) -> ProposalEligibility:
        if value in {"candidate", "requires_human_review"} and not info.data.get("regression_candidate"):
            raise ValueError("proposal candidates must set regression_candidate=true")
        return value
    @model_validator(mode="after")
    def proposal_eligibility_matches_rule(self) -> ReviewerFinding:
        expected = finding_to_proposal_rule(self)
        if self.proposal_eligibility != expected:
            raise ValueError(f"proposal_eligibility must be {expected} for this finding")
        return self


class ReviewerReportAggregate(StrictModel):
    total: int = Field(ge=0)
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)
    blocks_adoption: bool = False
    proposal_candidate_count: int = Field(default=0, ge=0)


class ReviewerReport(StrictModel):
    schema_version: Literal["sourcebrief.review-report.v1"] = "sourcebrief.review-report.v1"
    report_id: str = Field(min_length=1)
    bundle_id: str = Field(min_length=1)
    reviewer_backend: str = Field(min_length=1)
    reviewer_lenses: list[ReviewerLens] = Field(default_factory=list)
    generated_at: datetime
    verdict: ReviewVerdict
    findings: list[ReviewerFinding] = Field(default_factory=list)
    aggregate: ReviewerReportAggregate

    @field_validator("findings")
    @classmethod
    def findings_must_match_bundle(cls, value: list[ReviewerFinding], info: Any) -> list[ReviewerFinding]:
        bundle_id = info.data.get("bundle_id")
        if bundle_id:
            for finding in value:
                if finding.bundle_id != bundle_id:
                    raise ValueError("all findings must match report bundle_id")
        return value

    @model_validator(mode="after")
    def aggregate_must_match_findings(self) -> ReviewerReport:
        expected = aggregate_findings(self.findings)
        if self.aggregate != expected:
            raise ValueError("aggregate must equal deterministic aggregate_findings(findings)")
        return self


def severity_blocks_adoption(severity: str) -> bool:
    return severity in {"blocker", "major"}


def finding_to_proposal_rule(finding: ReviewerFinding) -> ProposalEligibility:
    if finding.severity == "rejected_learning":
        return "not_eligible"
    if finding.regression_candidate and finding.confidence in {"high", "medium"}:
        return "candidate"
    if finding.regression_candidate:
        return "requires_human_review"
    return "not_eligible"


def verdict_for_findings(findings: list[ReviewerFinding]) -> ReviewVerdict:
    if any(finding.severity in {"blocker", "major"} for finding in findings):
        return "BLOCK"
    if findings:
        return "RISK"
    return "PASS"


def aggregate_findings(findings: list[ReviewerFinding]) -> ReviewerReportAggregate:
    by_severity = Counter(finding.severity for finding in findings)
    by_type = Counter(finding.type for finding in findings)
    return ReviewerReportAggregate(
        total=len(findings),
        by_severity=dict(sorted(by_severity.items())),
        by_type=dict(sorted(by_type.items())),
        blocks_adoption=any(severity_blocks_adoption(finding.severity) for finding in findings),
        proposal_candidate_count=sum(
            1 for finding in findings if finding_to_proposal_rule(finding) in {"candidate", "requires_human_review"}
        ),
    )


def build_reviewer_report(
    *,
    report_id: str,
    bundle_id: str,
    reviewer_backend: str,
    reviewer_lenses: list[ReviewerLens],
    generated_at: datetime,
    findings: list[ReviewerFinding],
) -> ReviewerReport:
    return ReviewerReport(
        report_id=report_id,
        bundle_id=bundle_id,
        reviewer_backend=reviewer_backend,
        reviewer_lenses=reviewer_lenses,
        generated_at=generated_at,
        verdict=verdict_for_findings(findings),
        findings=findings,
        aggregate=aggregate_findings(findings),
    )
