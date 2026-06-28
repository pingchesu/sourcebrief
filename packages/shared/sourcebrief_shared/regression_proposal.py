from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from sourcebrief_shared.review_findings import ReviewerFinding, ReviewerReport

REGRESSION_PROPOSAL_SCHEMA_VERSION = "sourcebrief.regression-proposal.v1"

ProposalStatus = Literal["proposed", "accepted", "rejected", "implemented", "superseded"]
TargetSurface = Literal["docs", "test", "eval_fixture", "skill", "runtime_pack", "code", "unknown"]


class RegressionProposalError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegressionProposal(StrictModel):
    schema_version: Literal["sourcebrief.regression-proposal.v1"] = "sourcebrief.regression-proposal.v1"
    proposal_id: str = Field(min_length=1)
    source_report_id: str = Field(min_length=1)
    source_bundle_id: str = Field(min_length=1)
    source_finding_id: str = Field(min_length=1)
    failure_mode: str = Field(min_length=1)
    target_surface: TargetSurface = "unknown"
    proposed_check: str = Field(min_length=1)
    acceptance: list[str] = Field(min_length=1)
    fixture_refs: list[str] = Field(default_factory=list)
    bundle_refs: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    owner: str = "unassigned"
    status: ProposalStatus = "proposed"
    rationale: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def load_reviewer_report(path: str | Path) -> ReviewerReport:
    return ReviewerReport.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _target_surface_for_finding(finding: ReviewerFinding) -> TargetSurface:
    if finding.type in {"citation_mismatch", "unsupported_claim", "missing_evidence", "stale_source", "no_proof"}:
        return "test"
    if finding.type in {"quickstart_dx_failure", "overclaim"}:
        return "docs"
    if finding.type == "unsafe_mutation":
        return "runtime_pack"
    if finding.type == "regression_candidate":
        return "eval_fixture"
    return "unknown"


def _status_for_finding(finding: ReviewerFinding) -> ProposalStatus:
    if finding.severity == "rejected_learning" or finding.proposal_eligibility == "not_eligible":
        return "rejected"
    return "proposed"


def proposal_from_finding(report: ReviewerReport, finding: ReviewerFinding, *, owner: str = "unassigned") -> RegressionProposal:
    status = _status_for_finding(finding)
    proposed_check = (
        f"Reproduce finding `{finding.finding_id}` for bundle `{report.bundle_id}` and assert that `{finding.type}` "
        "does not recur without an explicit rejected-proposal rationale."
    )
    rationale = finding.impact if status == "proposed" else f"Rejected as durable learning: {finding.impact}"
    return RegressionProposal(
        proposal_id=f"proposal-{finding.finding_id}",
        source_report_id=report.report_id,
        source_bundle_id=report.bundle_id,
        source_finding_id=finding.finding_id,
        failure_mode=finding.summary,
        target_surface=_target_surface_for_finding(finding),
        proposed_check=proposed_check,
        acceptance=[
            f"The regression check fails on the source finding `{finding.finding_id}` before the fix.",
            "The check passes after the smallest scoped fix or remains explicitly rejected with rationale.",
            "Evidence refs remain tied to the original review bundle/report.",
        ],
        fixture_refs=[f"finding:{finding.finding_id}"],
        bundle_refs=[report.bundle_id],
        evidence_refs=finding.evidence_refs,
        owner=owner,
        status=status,
        rationale=rationale,
    )


def proposals_from_report(report: ReviewerReport, *, owner: str = "unassigned") -> list[RegressionProposal]:
    proposals: list[RegressionProposal] = []
    for finding in report.findings:
        if finding.regression_candidate or finding.severity == "rejected_learning":
            proposals.append(proposal_from_finding(report, finding, owner=owner))
    return proposals


def select_finding(report: ReviewerReport, finding_id: str | None = None) -> ReviewerFinding:
    candidates = [finding for finding in report.findings if finding.regression_candidate or finding.severity == "rejected_learning"]
    if finding_id:
        for finding in candidates:
            if finding.finding_id == finding_id:
                return finding
        raise RegressionProposalError(f"finding not found or not proposal-eligible: {finding_id}")
    if not candidates:
        raise RegressionProposalError("review report has no regression candidate or rejected-learning findings")
    return candidates[0]


def write_regression_proposal(path: str | Path, proposal: RegressionProposal) -> Path:
    output_path = Path(path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(proposal.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return output_path
