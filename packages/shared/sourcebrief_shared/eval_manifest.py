from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "sourcebrief.eval-manifest.v1"
REPORT_SCHEMA_VERSION = "sourcebrief.eval-report.v1"
MAX_API_BATCH_QUESTIONS = 10

VALID_IMPORT_TYPES = {"full", "limited", "failed", "expected-skip"}
VALID_EXPECTED_RESULTS = {"pass", "partial", "expected_unanswerable"}
VALID_GRADES = {"PASS", "PARTIAL", "FAIL"}
VALID_REPORT_VERDICTS = {"PASS", "RISK", "BLOCK"}
VALID_CHECK_STATUSES = {"pass", "partial", "fail", "not_applicable"}


class EvalManifestError(ValueError):
    pass


def canonical_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_digest(data: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()


def load_json_file(path: str | Path) -> dict[str, Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise EvalManifestError("manifest must be a JSON object")
    return raw


def _require_string(obj: dict[str, Any], key: str, *, context: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EvalManifestError(f"{context}.{key} must be a non-empty string")
    return value


def _optional_string_list(obj: dict[str, Any], key: str, *, context: str) -> list[str]:
    value = obj.get(key, [])
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise EvalManifestError(f"{context}.{key} must be a list of non-empty strings")
    return value


def _optional_number(obj: dict[str, Any], key: str, *, context: str, minimum: float | None = None, maximum: float | None = None) -> float | int | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise EvalManifestError(f"{context}.{key} must be a number")
    if minimum is not None and value < minimum:
        raise EvalManifestError(f"{context}.{key} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise EvalManifestError(f"{context}.{key} must be <= {maximum}")
    return value


def validate_run_manifest(run: dict[str, Any]) -> None:
    context = "run"
    _require_string(run, "sourcebrief_commit", context=context)
    _require_string(run, "api_url", context=context)
    _require_string(run, "workspace_id", context=context)
    _require_string(run, "project_id", context=context)
    resources = run.get("resources")
    if not isinstance(resources, list) or not resources:
        raise EvalManifestError("run.resources must be a non-empty list")
    seen_keys: set[str] = set()
    for index, resource in enumerate(resources):
        if not isinstance(resource, dict):
            raise EvalManifestError(f"run.resources[{index}] must be an object")
        rctx = f"run.resources[{index}]"
        key = _require_string(resource, "key", context=rctx)
        if key in seen_keys:
            raise EvalManifestError(f"duplicate resource key: {key}")
        seen_keys.add(key)
        _require_string(resource, "target_repo", context=rctx)
        import_type = _require_string(resource, "import_type", context=rctx)
        if import_type not in VALID_IMPORT_TYPES:
            raise EvalManifestError(f"{rctx}.import_type must be one of {sorted(VALID_IMPORT_TYPES)}")
        _optional_string_list(resource, "resource_ids", context=rctx)
        _optional_string_list(resource, "snapshot_ids", context=rctx)
        _optional_string_list(resource, "corpus_caveats", context=rctx)


def validate_question(question: dict[str, Any], *, index: int, resource_keys: set[str]) -> None:
    context = f"questions[{index}]"
    _require_string(question, "id", context=context)
    _require_string(question, "query", context=context)
    _require_string(question, "category", context=context)
    _require_string(question, "customer_job", context=context)
    _require_string(question, "difficulty", context=context)
    _require_string(question, "demo_type", context=context)
    target_repo = _require_string(question, "target_repo", context=context)
    if target_repo not in resource_keys:
        raise EvalManifestError(f"{context}.target_repo {target_repo!r} does not match run.resources[].key")
    import_type = _require_string(question, "import_type", context=context)
    if import_type not in VALID_IMPORT_TYPES:
        raise EvalManifestError(f"{context}.import_type must be one of {sorted(VALID_IMPORT_TYPES)}")
    expected_result = _require_string(question, "expected_result", context=context)
    if expected_result not in VALID_EXPECTED_RESULTS:
        raise EvalManifestError(f"{context}.expected_result must be one of {sorted(VALID_EXPECTED_RESULTS)}")
    _optional_string_list(question, "resource_ids", context=context)
    expected_resource_ids = _optional_string_list(question, "expected_resource_ids", context=context)
    _optional_string_list(question, "snapshot_ids", context=context)
    _optional_string_list(question, "expected_paths", context=context)
    _optional_string_list(question, "expected_symbols", context=context)
    _optional_string_list(question, "required_texts", context=context)
    _optional_string_list(question, "forbidden_resource_ids", context=context)
    _optional_string_list(question, "bad_answer_criteria", context=context)
    _optional_number(question, "min_citations", context=context, minimum=0, maximum=20)
    _optional_number(question, "top_k", context=context, minimum=1, maximum=20)
    _optional_number(question, "max_chars", context=context, minimum=1000, maximum=12000)
    include_code_symbols = question.get("include_code_symbols", True)
    if not isinstance(include_code_symbols, bool):
        raise EvalManifestError(f"{context}.include_code_symbols must be a boolean")
    if expected_result == "expected_unanswerable" and not question.get("bad_answer_criteria"):
        raise EvalManifestError(f"{context} expected_unanswerable questions must declare bad_answer_criteria")
    if expected_result == "expected_unanswerable" and expected_resource_ids:
        raise EvalManifestError(f"{context}.expected_resource_ids must be empty for expected_unanswerable controls")


def validate_thresholds(thresholds: dict[str, Any]) -> None:
    if not isinstance(thresholds, dict):
        raise EvalManifestError("thresholds must be an object")
    _optional_number(thresholds, "pass_min_rate", context="thresholds", minimum=0, maximum=1)
    _optional_number(thresholds, "partial_min_rate", context="thresholds", minimum=0, maximum=1)
    _optional_number(thresholds, "block_below_rate", context="thresholds", minimum=0, maximum=1)
    for key in ("max_wrong_repo", "max_unsupported_claims"):
        _optional_number(thresholds, key, context="thresholds", minimum=0)


def validate_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise EvalManifestError(f"schema_version must be {SCHEMA_VERSION!r}")
    _require_string(manifest, "name", context="manifest")
    _require_string(manifest, "description", context="manifest")
    validate_thresholds(manifest.get("thresholds", {}))
    run = manifest.get("run")
    if not isinstance(run, dict):
        raise EvalManifestError("run must be an object")
    validate_run_manifest(run)
    resource_keys = {resource["key"] for resource in run["resources"]}
    questions = manifest.get("questions")
    if not isinstance(questions, list) or not questions:
        raise EvalManifestError("questions must be a non-empty list")
    seen_ids: set[str] = set()
    has_negative_control = False
    for index, question in enumerate(questions):
        if not isinstance(question, dict):
            raise EvalManifestError(f"questions[{index}] must be an object")
        qid = _require_string(question, "id", context=f"questions[{index}]")
        if qid in seen_ids:
            raise EvalManifestError(f"duplicate question id: {qid}")
        seen_ids.add(qid)
        validate_question(question, index=index, resource_keys=resource_keys)
        has_negative_control = has_negative_control or question.get("expected_result") == "expected_unanswerable"
    if not has_negative_control:
        raise EvalManifestError("manifest must include at least one expected_unanswerable negative/control question")
    return {
        "schema_version": SCHEMA_VERSION,
        "question_count": len(questions),
        "batch_count": len(question_batches(manifest)),
        "manifest_sha256": sha256_digest(manifest),
    }


def question_batches(manifest: dict[str, Any], *, max_questions: int = MAX_API_BATCH_QUESTIONS) -> list[list[dict[str, Any]]]:
    if max_questions < 1:
        raise EvalManifestError("max_questions must be >= 1")
    if max_questions > MAX_API_BATCH_QUESTIONS:
        raise EvalManifestError(f"max_questions must be <= {MAX_API_BATCH_QUESTIONS}")
    questions = manifest.get("questions")
    if not isinstance(questions, list):
        raise EvalManifestError("questions must be a list before batching")
    return [questions[index : index + max_questions] for index in range(0, len(questions), max_questions)]


def api_eval_payloads(manifest: dict[str, Any], *, max_questions: int = MAX_API_BATCH_QUESTIONS) -> list[dict[str, Any]]:
    validate_manifest(manifest)
    payloads: list[dict[str, Any]] = []
    for batch in question_batches(manifest, max_questions=max_questions):
        payloads.append(
            {
                "questions": [
                    {
                        "id": question["id"],
                        "query": question["query"],
                        "expected_resource_ids": question.get("expected_resource_ids", []),
                        "forbidden_resource_ids": question.get("forbidden_resource_ids", []),
                        "resource_ids": question.get("resource_ids") or None,
                        "expected_paths": question.get("expected_paths", []),
                        "expected_symbols": question.get("expected_symbols", []),
                        "required_texts": question.get("required_texts", []),
                        "min_citations": question.get("min_citations", 1),
                        "top_k": question.get("top_k", 8),
                        "include_code_symbols": question.get("include_code_symbols", True),
                    }
                    for question in batch
                ],
                "runtime": "hermes",
                "max_chars": max(question.get("max_chars", 8000) for question in batch),
            }
        )
    return payloads


def _validate_report_aggregate(aggregate: Any) -> dict[str, Any]:
    if not isinstance(aggregate, dict):
        raise EvalManifestError("report.aggregate must be an object")
    for key in ("mechanical_api_success_rate", "retrieval_quality_pass_rate", "human_answer_demo_pass_rate"):
        if key not in aggregate:
            raise EvalManifestError(f"report.aggregate.{key} is required")
        _optional_number(aggregate, key, context="report.aggregate", minimum=0, maximum=1)
    for key in ("wrong_repo_failures", "unsupported_claim_failures"):
        if key not in aggregate:
            raise EvalManifestError(f"report.aggregate.{key} is required")
        value = _optional_number(aggregate, key, context="report.aggregate", minimum=0)
        if not isinstance(value, int):
            raise EvalManifestError(f"report.aggregate.{key} must be an integer")
    verdict = _require_string(aggregate, "verdict", context="report.aggregate")
    if verdict not in VALID_REPORT_VERDICTS:
        raise EvalManifestError(f"report.aggregate.verdict must be one of {sorted(VALID_REPORT_VERDICTS)}")
    return aggregate


def _check_passed(value: Any) -> bool:
    return value is True or value == "pass"


def _check_failed(value: Any) -> bool:
    return value is False or value == "fail"


def _check_applicable(value: Any) -> bool:
    return value != "not_applicable"


def _derived_check_rate(results: list[dict[str, Any]], check_key: str) -> float:
    values = [result["checks"][check_key] for result in results if _check_applicable(result["checks"][check_key])]
    if not values:
        return 1.0
    return sum(1 for value in values if _check_passed(value)) / len(values)


def _assert_report_aggregate_matches_results(
    aggregate: dict[str, Any], results: list[dict[str, Any]], grade_counts: dict[str, int]
) -> None:
    rate_checks = {
        "mechanical_api_success_rate": "mechanical_api_success",
        "retrieval_quality_pass_rate": "retrieval_quality",
        "human_answer_demo_pass_rate": "human_answer_demo",
    }
    for aggregate_key, check_key in rate_checks.items():
        expected_rate = _derived_check_rate(results, check_key)
        if abs(float(aggregate[aggregate_key]) - expected_rate) > 0.000001:
            raise EvalManifestError(
                f"report.aggregate.{aggregate_key} does not match per-result {check_key} checks: "
                f"expected {expected_rate:.6f}, got {aggregate[aggregate_key]}"
            )
    wrong_repo_failures = sum(1 for result in results if _check_failed(result["checks"]["wrong_repo_check"]))
    unsupported_claim_failures = sum(1 for result in results if _check_failed(result["checks"]["citation_support"]))
    if aggregate["wrong_repo_failures"] != wrong_repo_failures:
        raise EvalManifestError(
            f"report.aggregate.wrong_repo_failures does not match per-result checks: "
            f"expected {wrong_repo_failures}, got {aggregate['wrong_repo_failures']}"
        )
    if aggregate["unsupported_claim_failures"] != unsupported_claim_failures:
        raise EvalManifestError(
            f"report.aggregate.unsupported_claim_failures does not match per-result checks: "
            f"expected {unsupported_claim_failures}, got {aggregate['unsupported_claim_failures']}"
        )
    expected_verdict = "PASS"
    if grade_counts["FAIL"] or wrong_repo_failures or unsupported_claim_failures:
        expected_verdict = "BLOCK"
    elif grade_counts["PARTIAL"]:
        expected_verdict = "RISK"
    if aggregate["verdict"] != expected_verdict:
        raise EvalManifestError(
            f"report.aggregate.verdict does not match grades/check failures: expected {expected_verdict}, got {aggregate['verdict']}"
        )


def _manifest_question_ids(manifest: dict[str, Any]) -> set[str]:
    validate_manifest(manifest)
    return {question["id"] for question in manifest["questions"]}


def validate_grade_report(
    report: dict[str, Any], *, manifest_sha256: str | None = None, manifest: dict[str, Any] | None = None
) -> dict[str, Any]:
    if report.get("schema_version") != REPORT_SCHEMA_VERSION:
        raise EvalManifestError(f"report.schema_version must be {REPORT_SCHEMA_VERSION!r}")
    if manifest is not None:
        manifest_sha256 = sha256_digest(manifest)
    if manifest_sha256 is not None and report.get("manifest_sha256") != manifest_sha256:
        raise EvalManifestError("report.manifest_sha256 does not match manifest")
    aggregate = _validate_report_aggregate(report.get("aggregate"))
    results = report.get("results")
    if not isinstance(results, list) or not results:
        raise EvalManifestError("report.results must be a non-empty list")
    grade_counts = {grade: 0 for grade in VALID_GRADES}
    seen_ids: set[str] = set()
    for index, result in enumerate(results):
        if not isinstance(result, dict):
            raise EvalManifestError(f"report.results[{index}] must be an object")
        context = f"report.results[{index}]"
        result_id = _require_string(result, "id", context=context)
        if result_id in seen_ids:
            raise EvalManifestError(f"duplicate report result id: {result_id}")
        seen_ids.add(result_id)
        grade = _require_string(result, "grade", context=context)
        if grade not in VALID_GRADES:
            raise EvalManifestError(f"{context}.grade must be one of {sorted(VALID_GRADES)}")
        grade_counts[grade] += 1
        _require_string(result, "rationale", context=context)
        checks = result.get("checks")
        if not isinstance(checks, dict):
            raise EvalManifestError(f"{context}.checks must be an object")
        for key in (
            "mechanical_api_success",
            "retrieval_quality",
            "citation_support",
            "wrong_repo_check",
            "partial_corpus_caveat",
            "human_answer_demo",
        ):
            if key not in checks:
                raise EvalManifestError(f"{context}.checks.{key} is required")
            value = checks[key]
            if isinstance(value, bool):
                continue
            if not isinstance(value, str) or value not in VALID_CHECK_STATUSES:
                raise EvalManifestError(
                    f"{context}.checks.{key} must be a boolean or one of {sorted(VALID_CHECK_STATUSES)}"
                )
    _assert_report_aggregate_matches_results(aggregate, results, grade_counts)
    if manifest is not None:
        expected_ids = _manifest_question_ids(manifest)
        if seen_ids != expected_ids:
            missing = sorted(expected_ids - seen_ids)
            extra = sorted(seen_ids - expected_ids)
            raise EvalManifestError(f"report.results must exactly match manifest questions; missing={missing}, extra={extra}")
    return {"result_count": len(results), "grade_counts": grade_counts}
