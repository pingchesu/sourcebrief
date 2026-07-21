from __future__ import annotations

import hashlib
import hmac
import math
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sourcebrief_shared.eval_manifest import EvalManifestError, canonical_json, sha256_digest

SCHEMA_VERSION = "sourcebrief.gate-a-founder-internal-outcome.v1"
SIGNAL_LABEL = (
    "FOUNDER-CONTROLLED INTERNAL SIGNAL — NOT INDEPENDENT GATE A, "
    "NOT D0, AND NOT PROMOTION AUTHORITY"
)
AUTHORIZATION = "internal_signal_only"
DIRECT_BASELINE = "direct_tools_no_sourcebrief"
LANES = {
    DIRECT_BASELINE,
    "current_deterministic",
    "real_static",
    "human_authored",
    "ai_compiled",
}
AUTOMATED_COMPARATORS = {
    DIRECT_BASELINE,
    "current_deterministic",
    "real_static",
}
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvalManifestError(f"{context} must be an object")
    return value


def _list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise EvalManifestError(f"{context} must be a list")
    return value


def _exact(value: dict[str, Any], keys: set[str], context: str) -> None:
    missing = sorted(keys - set(value))
    unknown = sorted(set(value) - keys)
    if missing or unknown:
        raise EvalManifestError(f"{context} schema drift: missing={missing}, unknown={unknown}")


def _string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvalManifestError(f"{context} must be a non-empty string")
    return value


def _boolean(value: Any, context: str) -> bool:
    if not isinstance(value, bool):
        raise EvalManifestError(f"{context} must be a boolean")
    return value


def _integer(value: Any, context: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise EvalManifestError(f"{context} must be an integer")
    if value < minimum:
        raise EvalManifestError(f"{context} must be >= {minimum}")
    return value


def _number(value: Any, context: str, minimum: float = 0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvalManifestError(f"{context} must be a number")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise EvalManifestError(f"{context} must be finite and >= {minimum}")
    return result


def _digest(value: Any, context: str) -> str:
    result = _string(value, context)
    if not _SHA256_RE.fullmatch(result) or len(set(result.removeprefix("sha256:"))) == 1:
        raise EvalManifestError(f"{context} must be a non-placeholder sha256 digest")
    return result


def _timestamp(value: Any, context: str) -> datetime:
    text = _string(value, context)
    if not text.endswith("Z"):
        raise EvalManifestError(f"{context} must be UTC RFC3339 ending in Z")
    try:
        parsed = datetime.fromisoformat(text.removesuffix("Z") + "+00:00")
    except ValueError as exc:
        raise EvalManifestError(f"{context} must be RFC3339") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise EvalManifestError(f"{context} must be UTC")
    return parsed


def _verify_cas_artifact(
    artifact_root: str | Path, declared_digest: str, context: str
) -> None:
    hexadecimal = declared_digest.removeprefix("sha256:")
    root = Path(artifact_root)
    path = root / hexadecimal
    try:
        root_stat = root.stat()
        file_stat = path.lstat()
    except FileNotFoundError as exc:
        raise EvalManifestError(f"{context} missing CAS artifact {declared_digest}") from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise EvalManifestError("internal outcome artifact_root must be a directory")
    if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
        raise EvalManifestError(f"{context} CAS artifact must be a non-symlink regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise EvalManifestError(f"{context} CAS artifact could not be opened safely") from exc
    hasher = hashlib.sha256()
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise EvalManifestError(f"{context} CAS artifact must remain a regular file")
        while chunk := os.read(descriptor, 1024 * 1024):
            hasher.update(chunk)
    finally:
        os.close(descriptor)
    if hasher.hexdigest() != hexadecimal:
        raise EvalManifestError(f"{context} CAS artifact digest mismatch")


def _ids(value: Any, context: str, expected_count: int) -> list[str]:
    raw = _list(value, context)
    ids: list[str] = []
    for index, item in enumerate(raw):
        item_id = _string(item, f"{context}[{index}]")
        if not _ID_RE.fullmatch(item_id):
            raise EvalManifestError(f"{context}[{index}] must be an opaque identifier")
        ids.append(item_id)
    if len(ids) != expected_count or len(set(ids)) != expected_count:
        raise EvalManifestError(f"{context} must contain exactly {expected_count} unique IDs")
    return ids


def _unsigned(envelope: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in envelope.items() if key != "internal_outcome_mac"}


def sign_internal_outcome(envelope: dict[str, Any], *, key: bytes) -> str:
    if not key:
        raise EvalManifestError("internal outcome key must not be empty")
    return "hmac-sha256:" + hmac.new(
        key, canonical_json(_unsigned(envelope)).encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _receipt(
    value: Any,
    context: str,
    *,
    item_key: str,
    expected_ids: set[str],
    cas_digests: dict[str, str],
) -> dict[str, Any]:
    receipt = _object(value, context)
    _exact(
        receipt,
        {
            "lane_key",
            item_key,
            "success" if item_key == "task_id" else "passed",
            "exit_code",
            "duration_seconds",
            "cost_usd",
            "hidden_test_sha256",
            "command_sha256",
            "diff_sha256",
            "stdout_sha256",
            "stderr_sha256",
            "receipt_sha256",
        },
        context,
    )
    lane = _string(receipt.get("lane_key"), f"{context}.lane_key")
    if lane not in LANES:
        raise EvalManifestError(f"{context}.lane_key is unknown")
    item_id = _string(receipt.get(item_key), f"{context}.{item_key}")
    if item_id not in expected_ids:
        raise EvalManifestError(f"{context}.{item_key} is unknown")
    outcome_key = "success" if item_key == "task_id" else "passed"
    outcome = _boolean(receipt.get(outcome_key), f"{context}.{outcome_key}")
    exit_code = _integer(receipt.get("exit_code"), f"{context}.exit_code")
    if outcome != (exit_code == 0):
        raise EvalManifestError(f"{context}.{outcome_key} must equal zero exit status")
    _number(receipt.get("duration_seconds"), f"{context}.duration_seconds")
    _number(receipt.get("cost_usd"), f"{context}.cost_usd")
    for field in (
        "hidden_test_sha256",
        "command_sha256",
        "diff_sha256",
        "stdout_sha256",
        "stderr_sha256",
    ):
        cas_digests[f"{context}.{field}"] = _digest(
            receipt.get(field), f"{context}.{field}"
        )
    declared = _digest(receipt.get("receipt_sha256"), f"{context}.receipt_sha256")
    cas_digests[f"{context}.receipt_sha256"] = declared
    if declared != sha256_digest(
        {key: item for key, item in receipt.items() if key != "receipt_sha256"}
    ):
        raise EvalManifestError(f"{context}.receipt_sha256 is invalid")
    return receipt


def validate_internal_outcome(
    envelope: dict[str, Any], *, key: bytes, artifact_root: str | Path
) -> dict[str, Any]:
    cas_digests: dict[str, str] = {}
    _exact(
        envelope,
        {
            "schema_version",
            "signal_label",
            "authorization",
            "d0_ready",
            "promotion_authorized",
            "governance_sha256",
            "source_commit",
            "source_tree_sha256",
            "candidate_sourcebrief_commit",
            "scorer_sha256",
            "task_bundle_sha256",
            "frozen_at",
            "run_started_at",
            "run_finished_at",
            "runtime_envelope",
            "development_task_ids",
            "held_out_task_ids",
            "control_ids",
            "pack_sha256_by_lane",
            "compiler_receipts",
            "task_receipts",
            "control_receipts",
            "internal_outcome_mac",
        },
        "internal_outcome",
    )
    if envelope.get("schema_version") != SCHEMA_VERSION:
        raise EvalManifestError("internal_outcome.schema_version is unsupported")
    if envelope.get("signal_label") != SIGNAL_LABEL:
        raise EvalManifestError("internal_outcome.signal_label must use the mandatory warning")
    if envelope.get("authorization") != AUTHORIZATION:
        raise EvalManifestError("internal_outcome.authorization must be internal_signal_only")
    if _boolean(envelope.get("d0_ready"), "internal_outcome.d0_ready"):
        raise EvalManifestError("internal outcome can never be D0 ready")
    if _boolean(
        envelope.get("promotion_authorized"), "internal_outcome.promotion_authorized"
    ):
        raise EvalManifestError("internal outcome can never authorize promotion")

    for field in (
        "governance_sha256",
        "source_tree_sha256",
        "scorer_sha256",
        "task_bundle_sha256",
    ):
        cas_digests[f"internal_outcome.{field}"] = _digest(
            envelope.get(field), f"internal_outcome.{field}"
        )
    for field in ("source_commit", "candidate_sourcebrief_commit"):
        commit = _string(envelope.get(field), f"internal_outcome.{field}")
        if not _COMMIT_RE.fullmatch(commit):
            raise EvalManifestError(f"internal_outcome.{field} must be a 40-hex commit")

    frozen = _timestamp(envelope.get("frozen_at"), "internal_outcome.frozen_at")
    started = _timestamp(envelope.get("run_started_at"), "internal_outcome.run_started_at")
    finished = _timestamp(envelope.get("run_finished_at"), "internal_outcome.run_finished_at")
    if not frozen < started <= finished:
        raise EvalManifestError("internal outcome clocks must satisfy frozen < started <= finished")

    runtime = _object(envelope.get("runtime_envelope"), "internal_outcome.runtime_envelope")
    _exact(
        runtime,
        {
            "provider",
            "model",
            "prompt_sha256",
            "sandbox_policy_sha256",
            "network_egress",
            "cost_budget_usd",
            "latency_budget_seconds",
            "retry_budget",
            "stop_budget_failures",
            "ai_uplift_min_tasks",
            "ai_task_success_min",
            "baseline_regressions_max",
        },
        "internal_outcome.runtime_envelope",
    )
    _string(runtime.get("provider"), "internal_outcome.runtime_envelope.provider")
    _string(runtime.get("model"), "internal_outcome.runtime_envelope.model")
    cas_digests["runtime_envelope.prompt_sha256"] = _digest(
        runtime.get("prompt_sha256"), "internal_outcome.runtime_envelope.prompt_sha256"
    )
    cas_digests["runtime_envelope.sandbox_policy_sha256"] = _digest(
        runtime.get("sandbox_policy_sha256"),
        "internal_outcome.runtime_envelope.sandbox_policy_sha256",
    )
    if _boolean(runtime.get("network_egress"), "runtime_envelope.network_egress"):
        raise EvalManifestError("internal experiment network egress must be disabled")
    cost_budget = _number(runtime.get("cost_budget_usd"), "runtime_envelope.cost_budget_usd")
    latency_budget = _number(
        runtime.get("latency_budget_seconds"), "runtime_envelope.latency_budget_seconds"
    )
    _integer(runtime.get("retry_budget"), "runtime_envelope.retry_budget")
    _integer(runtime.get("stop_budget_failures"), "runtime_envelope.stop_budget_failures", 1)
    uplift_min = _integer(runtime.get("ai_uplift_min_tasks"), "runtime_envelope.ai_uplift_min_tasks", 1)
    ai_min = _integer(runtime.get("ai_task_success_min"), "runtime_envelope.ai_task_success_min", 1)
    regression_max = _integer(
        runtime.get("baseline_regressions_max"),
        "runtime_envelope.baseline_regressions_max",
    )

    development = _ids(envelope.get("development_task_ids"), "development_task_ids", 4)
    held_out = _ids(envelope.get("held_out_task_ids"), "held_out_task_ids", 12)
    controls = _ids(envelope.get("control_ids"), "control_ids", 6)
    if set(development) & (set(held_out) | set(controls)) or set(held_out) & set(controls):
        raise EvalManifestError("internal outcome task splits must be disjoint")

    packs = _object(envelope.get("pack_sha256_by_lane"), "pack_sha256_by_lane")
    _exact(packs, LANES, "pack_sha256_by_lane")
    if packs[DIRECT_BASELINE] is not None:
        raise EvalManifestError("direct-tools baseline must not receive a SourceBrief pack")
    for lane in LANES - {DIRECT_BASELINE}:
        cas_digests[f"pack_sha256_by_lane.{lane}"] = _digest(
            packs.get(lane), f"pack_sha256_by_lane.{lane}"
        )

    compiler_receipts = _list(envelope.get("compiler_receipts"), "compiler_receipts")
    if len(compiler_receipts) != 3:
        raise EvalManifestError("exactly three compiler receipts are required")
    attempts: set[int] = set()
    compiler_by_attempt: dict[int, dict[str, Any]] = {}
    compiler_prompt_digests: set[str] = set()
    for index, raw in enumerate(compiler_receipts):
        context = f"compiler_receipts[{index}]"
        receipt = _object(raw, context)
        _exact(
            receipt,
            {
                "attempt",
                "started_at",
                "finished_at",
                "succeeded",
                "prompt_sha256",
                "response_sha256",
                "pack_sha256",
                "duration_seconds",
                "cost_usd",
            },
            context,
        )
        attempt = _integer(receipt.get("attempt"), f"{context}.attempt", 1)
        if attempt in compiler_by_attempt:
            raise EvalManifestError(f"duplicate compiler attempt {attempt}")
        attempts.add(attempt)
        compiler_by_attempt[attempt] = receipt
        compile_started = _timestamp(receipt.get("started_at"), f"{context}.started_at")
        compile_finished = _timestamp(receipt.get("finished_at"), f"{context}.finished_at")
        if not frozen <= compile_started <= compile_finished < started:
            raise EvalManifestError(f"{context} must finish after freeze and before run")
        if not _boolean(receipt.get("succeeded"), f"{context}.succeeded"):
            raise EvalManifestError(f"{context} must succeed")
        prompt_digest = _digest(
            receipt.get("prompt_sha256"), f"{context}.prompt_sha256"
        )
        compiler_prompt_digests.add(prompt_digest)
        cas_digests[f"{context}.prompt_sha256"] = prompt_digest
        cas_digests[f"{context}.response_sha256"] = _digest(
            receipt.get("response_sha256"), f"{context}.response_sha256"
        )
        cas_digests[f"{context}.pack_sha256"] = _digest(
            receipt.get("pack_sha256"), f"{context}.pack_sha256"
        )
        _number(receipt.get("duration_seconds"), f"{context}.duration_seconds")
        _number(receipt.get("cost_usd"), f"{context}.cost_usd")
    if attempts != {1, 2, 3}:
        raise EvalManifestError("compiler attempts must be exactly 1, 2, and 3")
    if len(compiler_prompt_digests) != 1:
        raise EvalManifestError("all compiler attempts must use the same frozen prompt")
    if compiler_by_attempt[1]["pack_sha256"] != packs["ai_compiled"]:
        raise EvalManifestError("compiler attempt 1 must be the promoted AI pack")

    task_receipts = _list(envelope.get("task_receipts"), "task_receipts")
    task_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for index, raw in enumerate(task_receipts):
        receipt = _receipt(
            raw,
            f"task_receipts[{index}]",
            item_key="task_id",
            expected_ids=set(held_out),
            cas_digests=cas_digests,
        )
        identity = (receipt["lane_key"], receipt["task_id"])
        if identity in task_by_key:
            raise EvalManifestError(f"duplicate task receipt {identity}")
        task_by_key[identity] = receipt
    expected_task_keys = {(lane, task) for lane in LANES for task in held_out}
    if set(task_by_key) != expected_task_keys or len(task_receipts) != 60:
        raise EvalManifestError("task receipts must provide exact 5x12 coverage")

    control_receipts = _list(envelope.get("control_receipts"), "control_receipts")
    control_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for index, raw in enumerate(control_receipts):
        receipt = _receipt(
            raw,
            f"control_receipts[{index}]",
            item_key="control_id",
            expected_ids=set(controls),
            cas_digests=cas_digests,
        )
        identity = (receipt["lane_key"], receipt["control_id"])
        if identity in control_by_key:
            raise EvalManifestError(f"duplicate control receipt {identity}")
        control_by_key[identity] = receipt
    expected_control_keys = {(lane, control) for lane in LANES for control in controls}
    if set(control_by_key) != expected_control_keys or len(control_receipts) != 30:
        raise EvalManifestError("control receipts must provide exact 5x6 coverage")

    for context, declared_digest in sorted(cas_digests.items()):
        _verify_cas_artifact(artifact_root, declared_digest, context)

    expected_mac = sign_internal_outcome(envelope, key=key)
    declared_mac = _string(envelope.get("internal_outcome_mac"), "internal_outcome_mac")
    if not hmac.compare_digest(expected_mac, declared_mac):
        raise EvalManifestError("internal outcome MAC is invalid")

    success_counts = {
        lane: sum(bool(task_by_key[(lane, task)]["success"]) for task in held_out)
        for lane in sorted(LANES)
    }
    best_automated = max(success_counts[lane] for lane in AUTOMATED_COMPARATORS)
    co_best = sorted(
        lane for lane in AUTOMATED_COMPARATORS if success_counts[lane] == best_automated
    )
    co_best_success_ids = {
        task
        for lane in co_best
        for task in held_out
        if bool(task_by_key[(lane, task)]["success"])
    }
    ai_regressions = sorted(
        task
        for task in co_best_success_ids
        if not bool(task_by_key[("ai_compiled", task)]["success"])
    )
    controls_passed = all(
        bool(control_by_key[(lane, control)]["passed"])
        for lane in LANES
        for control in controls
    )
    total_cost = sum(float(receipt["cost_usd"]) for receipt in task_receipts)
    total_cost += sum(float(receipt["cost_usd"]) for receipt in control_receipts)
    total_cost += sum(float(receipt["cost_usd"]) for receipt in compiler_receipts)
    elapsed = (finished - started).total_seconds()
    uplift = success_counts["ai_compiled"] - best_automated

    failures: list[str] = []
    if DIRECT_BASELINE not in success_counts:
        failures.append("missing direct-tools baseline")
    if success_counts["ai_compiled"] < ai_min:
        failures.append("AI task-success floor")
    if uplift < uplift_min:
        failures.append("insufficient uplift over strongest automated comparator")
    if len(ai_regressions) > regression_max:
        failures.append("baseline regressions")
    if not controls_passed:
        failures.append("control failures")
    if total_cost > cost_budget:
        failures.append("cost budget")
    if elapsed > latency_budget:
        failures.append("latency budget")

    verdict = "PASS" if not failures else "FAIL"
    return {
        "schema_version": SCHEMA_VERSION,
        "signal_label": SIGNAL_LABEL,
        "authorization": AUTHORIZATION,
        "d0_ready": False,
        "promotion_authorized": False,
        "computed_verdict": verdict,
        "stop_investment": verdict == "FAIL",
        "failure_reasons": failures,
        "task_success_counts": success_counts,
        "best_automated_arms": co_best,
        "ai_uplift_tasks": uplift,
        "baseline_regressions": ai_regressions,
        "controls_passed": controls_passed,
        "total_cost_usd": total_cost,
        "elapsed_seconds": elapsed,
    }
