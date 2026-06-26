from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from sourcebrief_shared.eval_manifest import (
    EvalManifestError,
    api_eval_payloads,
    load_json_file,
    sha256_digest,
    validate_grade_report,
    validate_manifest,
)

ROOT = Path(__file__).resolve().parents[2]
SAMPLE_MANIFEST = ROOT / "demo" / "alpha" / "eval_manifest.json"
SAMPLE_REPORT = ROOT / "demo" / "alpha" / "eval_report_template.json"
SCRIPT = ROOT / "scripts" / "eval_manifest.py"


def _complete_report_for(manifest: dict) -> dict:
    template = load_json_file(SAMPLE_REPORT)
    first_result = template["results"][0]
    return {
        **template,
        "manifest_sha256": sha256_digest(manifest),
        "results": [
            {
                **deepcopy(first_result),
                "id": question["id"],
                "rationale": f"Synthetic complete grading row for {question['id']}",
            }
            for question in manifest["questions"]
        ],
    }


def test_sample_eval_manifest_is_valid_and_hashable() -> None:
    manifest = load_json_file(SAMPLE_MANIFEST)

    summary = validate_manifest(manifest)

    assert summary["schema_version"] == "sourcebrief.eval-manifest.v1"
    assert summary["question_count"] == 11
    assert summary["batch_count"] == 2
    assert summary["manifest_sha256"].startswith("sha256:")
    assert summary["manifest_sha256"] == sha256_digest(manifest)


def test_eval_manifest_splits_to_api_max_ten_question_batches() -> None:
    manifest = load_json_file(SAMPLE_MANIFEST)

    payloads = api_eval_payloads(manifest)

    assert [len(payload["questions"]) for payload in payloads] == [10, 1]
    first_question = payloads[0]["questions"][0]
    assert first_question["id"] == "repo-symbol-001"
    assert first_question["expected_resource_ids"] == ["NORMALIZED_REPO_RESOURCE_ID"]
    assert first_question["expected_paths"] == ["src/context_agent.py"]
    assert payloads[0]["runtime"] == "hermes"

    by_id = {question["id"]: question for payload in payloads for question in payload["questions"]}
    negative = by_id["negative-compliance-001"]
    assert negative["resource_ids"] == ["NORMALIZED_REPO_RESOURCE_ID", "NORMALIZED_RUNBOOK_RESOURCE_ID"]
    assert negative["expected_resource_ids"] == []
    assert negative["min_citations"] == 0


def test_eval_manifest_refuses_batches_over_api_limit() -> None:
    manifest = load_json_file(SAMPLE_MANIFEST)

    with pytest.raises(EvalManifestError, match="max_questions must be <= 10"):
        api_eval_payloads(manifest, max_questions=11)


def test_eval_manifest_requires_negative_control_question() -> None:
    manifest = load_json_file(SAMPLE_MANIFEST)
    manifest["questions"] = [q for q in manifest["questions"] if q["expected_result"] != "expected_unanswerable"]

    with pytest.raises(EvalManifestError, match="expected_unanswerable"):
        validate_manifest(manifest)


def test_eval_manifest_negative_controls_cannot_require_expected_resources() -> None:
    manifest = load_json_file(SAMPLE_MANIFEST)
    negative = next(question for question in manifest["questions"] if question["expected_result"] == "expected_unanswerable")
    negative["expected_resource_ids"] = ["NORMALIZED_REPO_RESOURCE_ID"]

    with pytest.raises(EvalManifestError, match="expected_resource_ids"):
        validate_manifest(manifest)


def test_eval_report_template_schema_is_valid_without_manifest_binding() -> None:
    report = load_json_file(SAMPLE_REPORT)

    summary = validate_grade_report(report)

    assert summary["result_count"] == 2
    assert summary["grade_counts"]["PASS"] == 2


def test_eval_report_requires_aggregate_and_strict_check_statuses() -> None:
    report = load_json_file(SAMPLE_REPORT)
    no_aggregate = deepcopy(report)
    no_aggregate.pop("aggregate")
    with pytest.raises(EvalManifestError, match="report.aggregate"):
        validate_grade_report(no_aggregate)

    bad_check = deepcopy(report)
    bad_check["results"][0]["checks"]["human_answer_demo"] = "maybe"
    with pytest.raises(EvalManifestError, match="human_answer_demo"):
        validate_grade_report(bad_check)


def test_eval_report_manifest_bound_validation_requires_complete_results() -> None:
    manifest = load_json_file(SAMPLE_MANIFEST)
    complete_report = _complete_report_for(manifest)

    summary = validate_grade_report(complete_report, manifest=manifest)

    assert summary["result_count"] == 11

    incomplete_report = deepcopy(complete_report)
    incomplete_report["results"] = incomplete_report["results"][:1]
    with pytest.raises(EvalManifestError, match="must exactly match manifest questions"):
        validate_grade_report(incomplete_report, manifest=manifest)


def test_eval_report_aggregate_must_match_per_result_grades_and_checks() -> None:
    manifest = load_json_file(SAMPLE_MANIFEST)
    report = _complete_report_for(manifest)
    for result in report["results"]:
        result["grade"] = "FAIL"
        for key in result["checks"]:
            result["checks"][key] = "fail"
    report["aggregate"] = {
        "mechanical_api_success_rate": 1.0,
        "retrieval_quality_pass_rate": 1.0,
        "human_answer_demo_pass_rate": 1.0,
        "abstention_pass_rate": 1.0,
        "wrong_repo_failures": 0,
        "unsupported_claim_failures": 0,
        "verdict": "PASS",
    }

    with pytest.raises(EvalManifestError, match="report.aggregate"):
        validate_grade_report(report, manifest=manifest)


def test_eval_report_failed_abstention_blocks_pass_verdict() -> None:
    report = load_json_file(SAMPLE_REPORT)
    report["aggregate"]["abstention_pass_rate"] = 0.0
    for result in report["results"]:
        result["checks"]["abstained_correctly"] = False if result["id"] == "negative-compliance-001" else "not_applicable"

    with pytest.raises(EvalManifestError, match="verdict"):
        validate_grade_report(report)


def test_eval_report_manifest_digest_mismatch_fails() -> None:
    manifest = load_json_file(SAMPLE_MANIFEST)
    report = load_json_file(SAMPLE_REPORT)

    with pytest.raises(EvalManifestError, match="manifest_sha256"):
        validate_grade_report(report, manifest_sha256=sha256_digest(manifest))


def test_eval_manifest_script_validate_and_split(tmp_path) -> None:
    validate = subprocess.run(
        [sys.executable, str(SCRIPT), "validate", str(SAMPLE_MANIFEST)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    summary = json.loads(validate.stdout)
    assert summary["question_count"] == 11

    output_dir = tmp_path / "batches"
    split = subprocess.run(
        [sys.executable, str(SCRIPT), "split", str(SAMPLE_MANIFEST), "--output-dir", str(output_dir)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    split_summary = json.loads(split.stdout)
    assert split_summary["batch_count"] == 2
    assert len(json.loads((output_dir / "batch-001.json").read_text())["questions"]) == 10
    assert len(json.loads((output_dir / "batch-002.json").read_text())["questions"]) == 1

    too_large = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "split",
            str(SAMPLE_MANIFEST),
            "--output-dir",
            str(tmp_path / "too-large"),
            "--max-questions",
            "11",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert too_large.returncode == 2
    assert "max_questions must be <= 10" in too_large.stderr
