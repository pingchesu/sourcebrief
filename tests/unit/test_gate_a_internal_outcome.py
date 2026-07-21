from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from sourcebrief_shared.eval_manifest import EvalManifestError
from sourcebrief_shared.gate_a_internal_outcome import (
    AUTHORIZATION,
    DIRECT_BASELINE,
    LANES,
    SCHEMA_VERSION,
    SIGNAL_LABEL,
    sign_internal_outcome,
    validate_internal_outcome,
)

KEY = b"founder-internal-outcome-test-key"
ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "eval_manifest.py"


def _digest_fixture(label: str, artifact_root: Path | None = None) -> str:
    payload = json.dumps({"fixture": label}, sort_keys=True, separators=(",", ":")).encode()
    result = "sha256:" + hashlib.sha256(payload).hexdigest()
    if artifact_root is not None:
        artifact_root.mkdir(parents=True, exist_ok=True)
        (artifact_root / result.removeprefix("sha256:")).write_bytes(payload)
    return result


def _seal_receipt(receipt: dict, artifact_root: Path | None = None) -> dict:
    payload = json.dumps(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    receipt["receipt_sha256"] = "sha256:" + hashlib.sha256(payload).hexdigest()
    if artifact_root is not None:
        (artifact_root / receipt["receipt_sha256"].removeprefix("sha256:")).write_bytes(payload)
    return receipt


def valid_envelope(
    artifact_root: Path, *, direct_successes: int = 6, ai_successes: int = 9
) -> dict:
    def digest(label: str) -> str:
        return _digest_fixture(label, artifact_root)

    def seal_receipt(receipt: dict) -> dict:
        return _seal_receipt(receipt, artifact_root)

    development = [f"dev-{index:02d}" for index in range(1, 5)]
    held = [f"held-{index:02d}" for index in range(1, 13)]
    controls = [f"control-{index:02d}" for index in range(1, 7)]
    success_counts = {
        DIRECT_BASELINE: direct_successes,
        "current_deterministic": 5,
        "real_static": 6,
        "human_authored": 10,
        "ai_compiled": ai_successes,
    }
    task_receipts = []
    for lane in sorted(LANES):
        for index, task_id in enumerate(held):
            success = index < success_counts[lane]
            task_receipts.append(
                seal_receipt(
                    {
                        "lane_key": lane,
                        "task_id": task_id,
                        "success": success,
                        "exit_code": 0 if success else 1,
                        "duration_seconds": 10,
                        "cost_usd": 0.01,
                        "hidden_test_sha256": digest(f"hidden/{task_id}"),
                        "command_sha256": digest(f"command/{lane}/{task_id}"),
                        "diff_sha256": digest(f"diff/{lane}/{task_id}"),
                        "stdout_sha256": digest(f"stdout/{lane}/{task_id}"),
                        "stderr_sha256": digest(f"stderr/{lane}/{task_id}"),
                        "receipt_sha256": "pending",
                    }
                )
            )
    control_receipts = []
    for lane in sorted(LANES):
        for control_id in controls:
            control_receipts.append(
                seal_receipt(
                    {
                        "lane_key": lane,
                        "control_id": control_id,
                        "passed": True,
                        "exit_code": 0,
                        "duration_seconds": 5,
                        "cost_usd": 0.005,
                        "hidden_test_sha256": digest(f"hidden/{control_id}"),
                        "command_sha256": digest(f"command/{lane}/{control_id}"),
                        "diff_sha256": digest(f"diff/{lane}/{control_id}"),
                        "stdout_sha256": digest(f"stdout/{lane}/{control_id}"),
                        "stderr_sha256": digest(f"stderr/{lane}/{control_id}"),
                        "receipt_sha256": "pending",
                    }
                )
            )
    packs: dict[str, str | None] = {
        lane: digest(f"pack/{lane}") for lane in LANES
    }
    packs[DIRECT_BASELINE] = None
    compiler_receipts = [
        {
            "attempt": attempt,
            "started_at": f"2026-07-21T09:{attempt:02d}:00Z",
            "finished_at": f"2026-07-21T09:{attempt + 3:02d}:00Z",
            "succeeded": True,
            "prompt_sha256": digest("compiler-prompt"),
            "response_sha256": digest(f"compiler-response/{attempt}"),
            "pack_sha256": packs["ai_compiled"] if attempt == 1 else digest(f"pack/attempt-{attempt}"),
            "duration_seconds": 180,
            "cost_usd": 0.1,
        }
        for attempt in (1, 2, 3)
    ]
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "signal_label": SIGNAL_LABEL,
        "authorization": AUTHORIZATION,
        "d0_ready": False,
        "promotion_authorized": False,
        "governance_sha256": digest("internal-governance"),
        "source_commit": "1" * 40,
        "source_tree_sha256": digest("source-tree"),
        "candidate_sourcebrief_commit": "2" * 40,
        "scorer_sha256": digest("scorer"),
        "task_bundle_sha256": digest("task-bundle"),
        "frozen_at": "2026-07-21T09:00:00Z",
        "run_started_at": "2026-07-21T10:00:00Z",
        "run_finished_at": "2026-07-21T10:10:00Z",
        "runtime_envelope": {
            "provider": "openai-codex",
            "model": "gpt-5.6-sol",
            "prompt_sha256": digest("runtime-prompt"),
            "sandbox_policy_sha256": digest("sandbox-policy"),
            "network_egress": "model_api_only_trace_enforced",
            "cost_budget_usd": 10,
            "latency_budget_seconds": 3600,
            "retry_budget": 1,
            "stop_budget_failures": 3,
            "ai_uplift_min_tasks": 3,
            "ai_task_success_min": 9,
            "baseline_regressions_max": 1,
        },
        "development_task_ids": development,
        "held_out_task_ids": held,
        "control_ids": controls,
        "pack_sha256_by_lane": packs,
        "compiler_receipts": compiler_receipts,
        "task_receipts": task_receipts,
        "control_receipts": control_receipts,
        "internal_outcome_mac": "pending",
    }
    envelope["internal_outcome_mac"] = sign_internal_outcome(envelope, key=KEY)
    return envelope


def test_internal_outcome_pass_is_non_promotional_and_baseline_relative(
    tmp_path: Path,
) -> None:
    summary = validate_internal_outcome(
        valid_envelope(tmp_path), key=KEY, artifact_root=tmp_path
    )
    assert summary["computed_verdict"] == "PASS"
    assert summary["ai_uplift_tasks"] == 3
    assert summary["best_automated_arms"] == [
        DIRECT_BASELINE,
        "real_static",
    ]
    assert summary["authorization"] == "internal_signal_only"
    assert summary["d0_ready"] is False
    assert summary["promotion_authorized"] is False
    assert summary["stop_investment"] is False

    bad_root = tmp_path / "not-a-directory"
    bad_root.write_text("not a CAS", encoding="utf-8")
    with pytest.raises(EvalManifestError, match="non-symlink directory"):
        validate_internal_outcome(
            valid_envelope(tmp_path), key=KEY, artifact_root=bad_root
        )


def test_internal_outcome_strong_direct_baseline_forces_fail_and_stop(
    tmp_path: Path,
) -> None:
    summary = validate_internal_outcome(
        valid_envelope(tmp_path, direct_successes=8),
        key=KEY,
        artifact_root=tmp_path,
    )
    assert summary["computed_verdict"] == "FAIL"
    assert summary["best_automated_arms"] == [DIRECT_BASELINE]
    assert summary["ai_uplift_tasks"] == 1
    assert summary["stop_investment"] is True
    assert "insufficient uplift over strongest automated comparator" in summary["failure_reasons"]


def test_internal_outcome_rejects_missing_direct_coverage_authority_lies_and_tamper(
    tmp_path: Path,
) -> None:
    missing = valid_envelope(tmp_path)
    missing["task_receipts"] = [
        row for row in missing["task_receipts"] if row["lane_key"] != DIRECT_BASELINE
    ]
    missing["internal_outcome_mac"] = sign_internal_outcome(missing, key=KEY)
    with pytest.raises(EvalManifestError, match="5x12 coverage"):
        validate_internal_outcome(missing, key=KEY, artifact_root=tmp_path)

    authority = valid_envelope(tmp_path)
    authority["d0_ready"] = True
    authority["internal_outcome_mac"] = sign_internal_outcome(authority, key=KEY)
    with pytest.raises(EvalManifestError, match="never be D0"):
        validate_internal_outcome(authority, key=KEY, artifact_root=tmp_path)

    tampered = valid_envelope(tmp_path)
    tampered["run_finished_at"] = "2026-07-21T10:11:00Z"
    with pytest.raises(EvalManifestError, match="MAC"):
        validate_internal_outcome(tampered, key=KEY, artifact_root=tmp_path)


def test_internal_outcome_rejects_split_runtime_and_receipt_scalar_bypasses(
    tmp_path: Path,
) -> None:
    bad_id = valid_envelope(tmp_path)
    bad_id["held_out_task_ids"][0] = "src/secret.py"
    bad_id["internal_outcome_mac"] = sign_internal_outcome(bad_id, key=KEY)
    with pytest.raises(EvalManifestError, match="opaque"):
        validate_internal_outcome(bad_id, key=KEY, artifact_root=tmp_path)

    bool_budget = valid_envelope(tmp_path)
    bool_budget["runtime_envelope"]["retry_budget"] = True
    bool_budget["internal_outcome_mac"] = sign_internal_outcome(bool_budget, key=KEY)
    with pytest.raises(EvalManifestError, match="integer"):
        validate_internal_outcome(bool_budget, key=KEY, artifact_root=tmp_path)

    lie = valid_envelope(tmp_path)
    lie["task_receipts"][0]["success"] = True
    lie["task_receipts"][0]["exit_code"] = 1
    lie["task_receipts"][0] = _seal_receipt(lie["task_receipts"][0], tmp_path)
    lie["internal_outcome_mac"] = sign_internal_outcome(lie, key=KEY)
    with pytest.raises(EvalManifestError, match="zero exit"):
        validate_internal_outcome(lie, key=KEY, artifact_root=tmp_path)


def test_internal_outcome_cli_is_non_promotional(tmp_path: Path) -> None:
    outcome_path = tmp_path / "outcome.json"
    key_path = tmp_path / "key"
    outcome_path.write_text(json.dumps(valid_envelope(tmp_path)), encoding="utf-8")
    key_path.write_bytes(KEY)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate-gate-a-internal-outcome",
            str(outcome_path),
            "--key-file",
            str(key_path),
            "--artifact-root",
            str(tmp_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout)
    assert summary["computed_verdict"] == "PASS"
    assert summary["authorization"] == "internal_signal_only"
    assert summary["d0_ready"] is False
    assert summary["promotion_authorized"] is False
