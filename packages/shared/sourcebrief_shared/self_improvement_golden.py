from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from sourcebrief_shared.review_bundle import ReviewBundle, load_review_bundle
from sourcebrief_shared.review_findings import (
    FindingSeverity,
    FindingType,
    severity_blocks_adoption,
)
from sourcebrief_shared.self_improvement_security import redact_review_artifact

GOLDEN_FIXTURE_SCHEMA_VERSION = "sourcebrief.self-improvement-golden.v1"


class GoldenFixtureError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpectedFinding(StrictModel):
    finding_id: str = Field(min_length=1)
    severity: FindingSeverity
    type: FindingType
    summary: str = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)


class GoldenBundleCase(StrictModel):
    case_id: str = Field(min_length=1)
    bundle_path: str = Field(min_length=1)
    expected_verdict: Literal["pass", "findings"]
    expected_findings: list[ExpectedFinding] = Field(default_factory=list)


class GoldenGateCase(StrictModel):
    case_id: str = Field(min_length=1)
    proposal_id: str = Field(min_length=1)
    proposal_type: Literal["docs_update", "regression", "skill_rule", "runtime_pack"]
    proposed_change: str = Field(min_length=1)
    expected_gate_decision: Literal["accept", "accept_new_best", "reject"]
    deterministic_checks: dict[str, Literal["pass", "fail", "not_applicable"]]
    rationale: str = Field(min_length=1)


class GoldenManifest(StrictModel):
    schema_version: Literal["sourcebrief.self-improvement-golden.v1"]
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    bundle_cases: list[GoldenBundleCase] = Field(min_length=1)
    gate_cases: list[GoldenGateCase] = Field(min_length=1)


def _read_manifest(path: str | Path) -> GoldenManifest:
    return GoldenManifest.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _ensure_public_safe(value: Any, *, context: str) -> None:
    _, report = redact_review_artifact(value.model_dump(mode="json") if isinstance(value, BaseModel) else value)
    if report.counts:
        raise GoldenFixtureError(f"{context} contains redactable content: {report.counts}")


def _bundle_evidence_refs(bundle: ReviewBundle) -> set[str]:
    refs = {bundle.bundle_id}
    refs.update(citation.citation_id for citation in bundle.citations)
    refs.update(proof.proof_id for proof in bundle.tool_proof)
    refs.update(log.artifact_uri for log in bundle.verification_logs if log.artifact_uri)
    refs.update(ref.resource_id for ref in bundle.source_refs)
    return refs


def validate_golden_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    manifest = _read_manifest(manifest_path)
    base_dir = manifest_path.parent
    case_ids: set[str] = set()
    finding_types: set[str] = set()
    has_safe_passing = False
    loaded_bundles: list[str] = []

    for case in manifest.bundle_cases:
        if case.case_id in case_ids:
            raise GoldenFixtureError(f"duplicate bundle case id: {case.case_id}")
        case_ids.add(case.case_id)
        if case.expected_verdict == "pass" and case.expected_findings:
            raise GoldenFixtureError(f"{case.case_id} pass cases must not declare findings")
        if case.expected_verdict == "findings" and not case.expected_findings:
            raise GoldenFixtureError(f"{case.case_id} finding cases must declare expected findings")
        bundle_path = (base_dir / case.bundle_path).resolve()
        try:
            bundle_path.relative_to(base_dir.parent.resolve())
        except ValueError as exc:
            raise GoldenFixtureError(f"{case.case_id} bundle_path must stay under self-improvement examples") from exc
        bundle = load_review_bundle(bundle_path)
        _ensure_public_safe(bundle, context=case.case_id)
        loaded_bundles.append(str(bundle_path))
        has_safe_passing = has_safe_passing or case.expected_verdict == "pass"
        for finding in case.expected_findings:
            finding_types.add(finding.type)
            if not finding.claim_ids:
                raise GoldenFixtureError(f"{case.case_id} finding must declare claim_ids")
            if severity_blocks_adoption(finding.severity) and not finding.evidence_refs:
                raise GoldenFixtureError(f"{case.case_id} blocker/major expected findings require evidence_refs")
            missing_claims = set(finding.claim_ids) - set(bundle.output.claim_ids)
            if missing_claims:
                raise GoldenFixtureError(f"{case.case_id} finding references unknown claim ids: {sorted(missing_claims)}")
            missing_evidence = set(finding.evidence_refs) - _bundle_evidence_refs(bundle)
            if missing_evidence:
                raise GoldenFixtureError(f"{case.case_id} finding references unknown evidence refs: {sorted(missing_evidence)}")
            if finding.type == "citation_mismatch":
                for evidence_ref in finding.evidence_refs:
                    for citation in bundle.citations:
                        if citation.citation_id == evidence_ref and set(finding.claim_ids) & set(citation.supports_claim_ids):
                            raise GoldenFixtureError(
                                f"{case.case_id} citation_mismatch evidence must not declare support for the mismatched claim"
                            )

    for gate_case in manifest.gate_cases:
        _ensure_public_safe(gate_case, context=gate_case.case_id)
    gate_decisions = {case.expected_gate_decision for case in manifest.gate_cases}
    if not has_safe_passing:
        raise GoldenFixtureError("golden suite must include a safe passing answer control")
    for required in ("unsupported_claim", "citation_mismatch"):
        if required not in finding_types:
            raise GoldenFixtureError(f"golden suite missing required finding type: {required}")
    if "reject" not in gate_decisions:
        raise GoldenFixtureError("golden suite must include a rejected proposal gate case")
    if not gate_decisions.intersection({"accept", "accept_new_best"}):
        raise GoldenFixtureError("golden suite must include an accepted proposal gate case")
    return {
        "schema_version": manifest.schema_version,
        "bundle_case_count": len(manifest.bundle_cases),
        "gate_case_count": len(manifest.gate_cases),
        "finding_types": sorted(finding_types),
        "gate_decisions": sorted(gate_decisions),
        "loaded_bundles": loaded_bundles,
    }
