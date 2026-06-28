from pathlib import Path

import pytest

from sourcebrief_shared.self_improvement_golden import GoldenFixtureError, validate_golden_manifest

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "docs" / "examples" / "self-improvement" / "golden" / "manifest.json"


def test_golden_manifest_validates_minimum_controls() -> None:
    summary = validate_golden_manifest(MANIFEST)

    assert summary["schema_version"] == "sourcebrief.self-improvement-golden.v1"
    assert summary["bundle_case_count"] >= 3
    assert summary["gate_case_count"] >= 2
    assert "unsupported_claim" in summary["finding_types"]
    assert "citation_mismatch" in summary["finding_types"]
    assert "reject" in summary["gate_decisions"]
    assert "accept" in summary["gate_decisions"]
    assert len(summary["loaded_bundles"]) == summary["bundle_case_count"]


def test_golden_manifest_rejects_missing_required_controls(tmp_path: Path) -> None:
    examples_root = tmp_path / "self-improvement"
    golden_dir = examples_root / "golden"
    golden_dir.mkdir(parents=True)
    (examples_root / "review-bundle-docs-answer.json").write_text(
        (ROOT / "docs" / "examples" / "self-improvement" / "review-bundle-docs-answer.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    fixture = golden_dir / "manifest.json"
    fixture.write_text(
        """
        {
          "schema_version": "sourcebrief.self-improvement-golden.v1",
          "name": "bad fixture",
          "description": "missing negative controls",
          "bundle_cases": [
            {
              "case_id": "safe-only",
              "bundle_path": "../review-bundle-docs-answer.json",
              "expected_verdict": "pass",
              "expected_findings": []
            }
          ],
          "gate_cases": [
            {
              "case_id": "accept-only",
              "proposal_id": "proposal-ok",
              "proposal_type": "docs_update",
              "proposed_change": "A supported change.",
              "expected_gate_decision": "accept",
              "deterministic_checks": {"citation_support": "pass"},
              "rationale": "supported"
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    with pytest.raises(GoldenFixtureError, match="missing required finding type"):
        validate_golden_manifest(fixture)


def test_golden_manifest_rejects_public_unsafe_bundle(tmp_path: Path) -> None:
    examples_root = tmp_path / "self-improvement"
    golden_dir = examples_root / "golden"
    golden_dir.mkdir(parents=True)
    unsafe_bundle = golden_dir / "unsafe.json"
    unsafe_bundle.write_text(
        (ROOT / "docs" / "examples" / "self-improvement" / "review-bundle-docs-answer.json")
        .read_text(encoding="utf-8")
        .replace("no whitespace errors", "Authorization: Bearer cs_abcdefghijklmnopqrstuvwxyz123456"),
        encoding="utf-8",
    )
    manifest = golden_dir / "manifest.json"
    manifest.write_text(
        """
        {
          "schema_version": "sourcebrief.self-improvement-golden.v1",
          "name": "unsafe fixture",
          "description": "contains a token-like value",
          "bundle_cases": [
            {
              "case_id": "unsafe",
              "bundle_path": "unsafe.json",
              "expected_verdict": "findings",
              "expected_findings": [
                {
                  "finding_id": "finding-unsafe",
                  "severity": "major",
                  "type": "unsupported_claim",
                  "summary": "unsafe fixture",
                  "claim_ids": ["claim-staged-adoption"],
                  "evidence_refs": []
                }
              ]
            }
          ],
          "gate_cases": [
            {
              "case_id": "reject",
              "proposal_id": "proposal-reject",
              "proposal_type": "skill_rule",
              "proposed_change": "unsafe",
              "expected_gate_decision": "reject",
              "deterministic_checks": {"citation_support": "fail"},
              "rationale": "unsafe"
            }
          ]
        }
        """,
        encoding="utf-8",
    )

    with pytest.raises(GoldenFixtureError, match="redactable content"):
        validate_golden_manifest(manifest)
