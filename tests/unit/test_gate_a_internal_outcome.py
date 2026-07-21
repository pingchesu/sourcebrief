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
    return _digest_payload(payload, artifact_root)


def _digest_payload(payload: bytes, artifact_root: Path | None = None) -> str:
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

    def task_command_digest(lane: str, task_id: str) -> str:
        payload = json.dumps(
            {
                "schema": "sourcebrief.gate-a-cell-command.v2",
                "lane_key": lane,
                "task_id": task_id,
                "source_commit": "1" * 40,
                "network_egress": "model-api-required; shell-network-use-rejected-from-retained-command-trace",
                "pack_sha256": None if lane == DIRECT_BASELINE else digest(f"pack/{lane}"),
                "codex_argv": ["codex", "exec", "--sandbox", "danger-full-access"],
                "codex_stdin_sha256": (
                    _digest_payload(f"stdin/direct/{task_id}".encode(), artifact_root)
                    if lane == DIRECT_BASELINE
                    else digest(f"stdin/{lane}/{task_id}")
                ),
                "codex_timeout_seconds": 1800,
                "codex_trace_policy_violations": [],
                "landlock_launcher_sha256": digest("landlock"),
                "test_argv": ["python", "-m", "pytest", "tests"],
                "test_timeout_seconds": 600,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return _digest_payload(payload, artifact_root)

    def control_command_digest(lane: str, control_id: str) -> str:
        payload = json.dumps(
            {
                "schema": "sourcebrief.gate-a-control-command.v1",
                "lane_key": lane,
                "control_id": control_id,
                "source_commit": "1" * 40,
                "network_egress": False,
                "pack_sha256": None if lane == DIRECT_BASELINE else digest(f"pack/{lane}"),
                "operation": "deterministic-local-sandbox-policy-probe",
                "control_spec_sha256": digest(f"hidden/{control_id}"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return _digest_payload(payload, artifact_root)

    def task_trace_digest(lane: str, task_id: str) -> str:
        lines = [
            {"type": "thread.started", "thread_id": f"{lane}-{task_id}"},
            {"type": "turn.started"},
            {
                "type": "item.completed",
                "item": {
                    "id": "cmd-1",
                    "type": "command_execution",
                    "command": "bash -lc 'python -m pytest tests'",
                    "status": "completed",
                    "exit_code": 0,
                    "aggregated_output": "",
                },
            },
            {"type": "turn.completed", "usage": {}},
        ]
        payload = "\n".join(
            json.dumps(line, sort_keys=True, separators=(",", ":")) for line in lines
        ).encode()
        return _digest_payload(payload, artifact_root)

    def control_trace_digest(lane: str, control_id: str) -> str:
        payload = json.dumps(
            {
                "schema": "sourcebrief.gate-a-control-trace.v1",
                "lane_key": lane,
                "control_id": control_id,
                "policy_allowed": False,
                "checks": ["fixture-policy-check"],
                "violations": ["fixture-control-violation"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return _digest_payload(payload, artifact_root)

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
                        "command_sha256": task_command_digest(lane, task_id),
                        "trace_sha256": task_trace_digest(lane, task_id),
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
                        "command_sha256": control_command_digest(lane, control_id),
                        "trace_sha256": control_trace_digest(lane, control_id),
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


def test_internal_outcome_is_non_promotional_and_baseline_relative_fail_closed(
    tmp_path: Path,
) -> None:
    summary = validate_internal_outcome(
        valid_envelope(tmp_path), key=KEY, artifact_root=tmp_path
    )
    assert summary["computed_verdict"] == "FAIL"
    assert summary["ai_uplift_tasks"] == 0
    assert summary["best_automated_arms"] == [
        DIRECT_BASELINE,
        "real_static",
    ]
    assert summary["authorization"] == "internal_signal_only"
    assert summary["d0_ready"] is False
    assert summary["promotion_authorized"] is False
    assert summary["stop_investment"] is True
    assert summary["failure_reasons"] == [
        "command hidden-test execution evidence incomplete",
        "compiler economics evidence incomplete",
    ]

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
    assert summary["ai_uplift_tasks"] == 0
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


def test_internal_outcome_replays_trace_and_rejects_product_or_network_access(
    tmp_path: Path,
) -> None:
    envelope = valid_envelope(tmp_path)
    row = next(row for row in envelope["task_receipts"] if row["lane_key"] == DIRECT_BASELINE)
    payload = b'\n'.join(
        [
            json.dumps({"type": "thread.started", "thread_id": "bad"}).encode(),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "bash -lc 'python -m pytest tests; curl https://example.invalid'",
                    },
                },
                sort_keys=True,
            ).encode(),
            json.dumps({"type": "turn.completed", "usage": {}}).encode(),
        ]
    )
    row["trace_sha256"] = _digest_payload(payload, tmp_path)
    _seal_receipt(row, tmp_path)
    envelope["internal_outcome_mac"] = sign_internal_outcome(envelope, key=KEY)
    with pytest.raises(EvalManifestError, match="shell-level network"):
        validate_internal_outcome(envelope, key=KEY, artifact_root=tmp_path)

    product = valid_envelope(tmp_path)
    direct = next(row for row in product["task_receipts"] if row["lane_key"] == DIRECT_BASELINE)
    payload = b'\n'.join(
        [
            json.dumps({"type": "thread.started", "thread_id": "bad"}).encode(),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "bash -lc 'python -m sourcebrief_cli.main ask'",
                    },
                },
                sort_keys=True,
            ).encode(),
            json.dumps({"type": "turn.completed", "usage": {}}).encode(),
        ]
    )
    direct["trace_sha256"] = _digest_payload(payload, tmp_path)
    _seal_receipt(direct, tmp_path)
    product["internal_outcome_mac"] = sign_internal_outcome(product, key=KEY)
    with pytest.raises(EvalManifestError, match="direct-tools trace used SourceBrief"):
        validate_internal_outcome(product, key=KEY, artifact_root=tmp_path)


def test_internal_outcome_rejects_mcp_dynamic_product_and_socket_traces(
    tmp_path: Path,
) -> None:
    top_level_mcp = valid_envelope(tmp_path)
    row = next(row for row in top_level_mcp["task_receipts"] if row["lane_key"] == DIRECT_BASELINE)
    payload = b"\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "bad"}).encode(),
            json.dumps({"type": "mcp_tool_call", "name": "sourcebrief.get_agent_context"}).encode(),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "command_execution", "command": "python -m pytest tests"},
                },
                sort_keys=True,
            ).encode(),
            json.dumps({"type": "turn.completed", "usage": {}}).encode(),
        ]
    )
    row["trace_sha256"] = _digest_payload(payload, tmp_path)
    _seal_receipt(row, tmp_path)
    top_level_mcp["internal_outcome_mac"] = sign_internal_outcome(top_level_mcp, key=KEY)
    with pytest.raises(EvalManifestError, match="trace event type is unsupported|trace used MCP"):
        validate_internal_outcome(top_level_mcp, key=KEY, artifact_root=tmp_path)

    dynamic_product = valid_envelope(tmp_path)
    row = next(row for row in dynamic_product["task_receipts"] if row["lane_key"] == DIRECT_BASELINE)
    payload = b"\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "bad"}).encode(),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "python -c \"import importlib; importlib.import_module('source'+'brief_cli.main')\"",
                    },
                },
                sort_keys=True,
            ).encode(),
            json.dumps({"type": "turn.completed", "usage": {}}).encode(),
        ]
    )
    row["trace_sha256"] = _digest_payload(payload, tmp_path)
    _seal_receipt(row, tmp_path)
    dynamic_product["internal_outcome_mac"] = sign_internal_outcome(dynamic_product, key=KEY)
    with pytest.raises(EvalManifestError, match="direct-tools trace used SourceBrief"):
        validate_internal_outcome(dynamic_product, key=KEY, artifact_root=tmp_path)

    base64_product = valid_envelope(tmp_path)
    row = next(row for row in base64_product["task_receipts"] if row["lane_key"] == DIRECT_BASELINE)
    payload = b"\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "bad"}).encode(),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "python -c \"import importlib,base64; importlib.import_module(base64.b64decode('c291cmNlYnJpZWZfY2xpLm1haW4=').decode())\"",
                    },
                },
                sort_keys=True,
            ).encode(),
            json.dumps({"type": "turn.completed", "usage": {}}).encode(),
        ]
    )
    row["trace_sha256"] = _digest_payload(payload, tmp_path)
    _seal_receipt(row, tmp_path)
    base64_product["internal_outcome_mac"] = sign_internal_outcome(base64_product, key=KEY)
    with pytest.raises(EvalManifestError, match="direct-tools trace used SourceBrief"):
        validate_internal_outcome(base64_product, key=KEY, artifact_root=tmp_path)

    socket_trace = valid_envelope(tmp_path)
    row = next(row for row in socket_trace["task_receipts"] if row["lane_key"] == DIRECT_BASELINE)
    payload = b"\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "bad"}).encode(),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "command_execution",
                        "command": "python -c \"__import__('socket').create_connection(('1.1.1.1',443))\"",
                    },
                },
                sort_keys=True,
            ).encode(),
            json.dumps({"type": "turn.completed", "usage": {}}).encode(),
        ]
    )
    row["trace_sha256"] = _digest_payload(payload, tmp_path)
    _seal_receipt(row, tmp_path)
    socket_trace["internal_outcome_mac"] = sign_internal_outcome(socket_trace, key=KEY)
    with pytest.raises(EvalManifestError, match="shell-level network"):
        validate_internal_outcome(socket_trace, key=KEY, artifact_root=tmp_path)


    top_level_tool_call = valid_envelope(tmp_path)
    row = next(row for row in top_level_tool_call["task_receipts"] if row["lane_key"] == DIRECT_BASELINE)
    payload = b"\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "bad"}).encode(),
            json.dumps({"type": "tool_call", "server": "mcp", "name": "sourcebrief.get_agent_context"}).encode(),
            json.dumps({"type": "turn.completed", "usage": {}}).encode(),
        ]
    )
    row["trace_sha256"] = _digest_payload(payload, tmp_path)
    _seal_receipt(row, tmp_path)
    top_level_tool_call["internal_outcome_mac"] = sign_internal_outcome(top_level_tool_call, key=KEY)
    with pytest.raises(EvalManifestError, match="trace event type is unsupported|trace used MCP"):
        validate_internal_outcome(top_level_tool_call, key=KEY, artifact_root=tmp_path)

    nested_tool_call = valid_envelope(tmp_path)
    row = next(row for row in nested_tool_call["task_receipts"] if row["lane_key"] == DIRECT_BASELINE)
    payload = b"\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "bad"}).encode(),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "tool_call",
                        "server": "mcp",
                        "name": "sourcebrief.get_agent_context",
                    },
                },
                sort_keys=True,
            ).encode(),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "command_execution", "command": "python -m pytest tests"},
                },
                sort_keys=True,
            ).encode(),
            json.dumps({"type": "turn.completed", "usage": {}}).encode(),
        ]
    )
    row["trace_sha256"] = _digest_payload(payload, tmp_path)
    _seal_receipt(row, tmp_path)
    nested_tool_call["internal_outcome_mac"] = sign_internal_outcome(nested_tool_call, key=KEY)
    with pytest.raises(EvalManifestError, match="trace item type is unsupported|trace used MCP"):
        validate_internal_outcome(nested_tool_call, key=KEY, artifact_root=tmp_path)

    nested_tool_result = valid_envelope(tmp_path)
    row = next(row for row in nested_tool_result["task_receipts"] if row["lane_key"] == DIRECT_BASELINE)
    payload = b"\n".join(
        [
            json.dumps({"type": "thread.started", "thread_id": "bad"}).encode(),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {
                        "type": "function_call_output",
                        "call_id": "call-1",
                        "output": "tool result",
                    },
                },
                sort_keys=True,
            ).encode(),
            json.dumps(
                {
                    "type": "item.completed",
                    "item": {"type": "command_execution", "command": "python -m pytest tests"},
                },
                sort_keys=True,
            ).encode(),
            json.dumps({"type": "turn.completed", "usage": {}}).encode(),
        ]
    )
    row["trace_sha256"] = _digest_payload(payload, tmp_path)
    _seal_receipt(row, tmp_path)
    nested_tool_result["internal_outcome_mac"] = sign_internal_outcome(nested_tool_result, key=KEY)
    with pytest.raises(EvalManifestError, match="trace item type is unsupported"):
        validate_internal_outcome(nested_tool_result, key=KEY, artifact_root=tmp_path)


def test_internal_outcome_checks_mac_before_cas_and_replays_command_artifacts(
    tmp_path: Path,
) -> None:
    missing_cas = valid_envelope(tmp_path)
    row = missing_cas["task_receipts"][0]
    row["command_sha256"] = "sha256:" + hashlib.sha256(b"missing command").hexdigest()
    _seal_receipt(row, tmp_path)
    with pytest.raises(EvalManifestError, match="MAC"):
        validate_internal_outcome(missing_cas, key=KEY, artifact_root=tmp_path)

    product_command = valid_envelope(tmp_path)
    row = next(row for row in product_command["task_receipts"] if row["lane_key"] == DIRECT_BASELINE)
    command = {
        "schema": "sourcebrief.gate-a-cell-command.v2",
        "lane_key": DIRECT_BASELINE,
        "task_id": row["task_id"],
        "source_commit": "1" * 40,
        "network_egress": "model-api-required; shell-network-use-rejected-from-retained-command-trace",
        "pack_sha256": None,
        "codex_argv": ["codex", "exec"],
        "codex_stdin_sha256": _digest_fixture("bad-stdin", tmp_path),
        "codex_timeout_seconds": 1800,
        "codex_trace_policy_violations": [],
        "landlock_launcher_sha256": _digest_fixture("landlock", tmp_path),
        "test_argv": ["sourcebrief", "ask"],
        "test_timeout_seconds": 600,
    }
    row["command_sha256"] = _digest_payload(
        json.dumps(command, sort_keys=True, separators=(",", ":")).encode(), tmp_path
    )
    _seal_receipt(row, tmp_path)
    product_command["internal_outcome_mac"] = sign_internal_outcome(product_command, key=KEY)
    with pytest.raises(EvalManifestError, match="command direct-tools used SourceBrief"):
        validate_internal_outcome(product_command, key=KEY, artifact_root=tmp_path)

    git_network = valid_envelope(tmp_path)
    row = next(
        row for row in git_network["task_receipts"] if row["lane_key"] == DIRECT_BASELINE
    )
    command = json.loads((tmp_path / row["command_sha256"].removeprefix("sha256:")).read_text())
    command["test_argv"] = ["git", "clone", "https://example.invalid/repo.git"]
    row["command_sha256"] = _digest_payload(
        json.dumps(command, sort_keys=True, separators=(",", ":")).encode(), tmp_path
    )
    _seal_receipt(row, tmp_path)
    git_network["internal_outcome_mac"] = sign_internal_outcome(git_network, key=KEY)
    with pytest.raises(EvalManifestError, match="shell-level network"):
        validate_internal_outcome(git_network, key=KEY, artifact_root=tmp_path)

    bad_typed_command = valid_envelope(tmp_path)
    row = bad_typed_command["task_receipts"][0]
    command = json.loads((tmp_path / row["command_sha256"].removeprefix("sha256:")).read_text())
    command["codex_stdin_sha256"] = "not-a-digest"
    command["landlock_launcher_sha256"] = False
    command["codex_timeout_seconds"] = "forever"
    command["test_timeout_seconds"] = True
    row["command_sha256"] = _digest_payload(
        json.dumps(command, sort_keys=True, separators=(",", ":")).encode(), tmp_path
    )
    _seal_receipt(row, tmp_path)
    bad_typed_command["internal_outcome_mac"] = sign_internal_outcome(bad_typed_command, key=KEY)
    with pytest.raises(EvalManifestError, match="codex_stdin_sha256"):
        validate_internal_outcome(bad_typed_command, key=KEY, artifact_root=tmp_path)

    direct_stdin_product = valid_envelope(tmp_path)
    row = next(
        row for row in direct_stdin_product["task_receipts"] if row["lane_key"] == DIRECT_BASELINE
    )
    command = json.loads((tmp_path / row["command_sha256"].removeprefix("sha256:")).read_text())
    command["codex_stdin_sha256"] = _digest_payload(b"use sourcebrief.get_agent_context", tmp_path)
    row["command_sha256"] = _digest_payload(
        json.dumps(command, sort_keys=True, separators=(",", ":")).encode(), tmp_path
    )
    _seal_receipt(row, tmp_path)
    direct_stdin_product["internal_outcome_mac"] = sign_internal_outcome(direct_stdin_product, key=KEY)
    with pytest.raises(EvalManifestError, match="stdin used SourceBrief"):
        validate_internal_outcome(direct_stdin_product, key=KEY, artifact_root=tmp_path)

    wrong_pack = valid_envelope(tmp_path)
    row = next(row for row in wrong_pack["task_receipts"] if row["lane_key"] == "ai_compiled")
    command = json.loads((tmp_path / row["command_sha256"].removeprefix("sha256:")).read_text())
    command["pack_sha256"] = None
    row["command_sha256"] = _digest_payload(
        json.dumps(command, sort_keys=True, separators=(",", ":")).encode(), tmp_path
    )
    _seal_receipt(row, tmp_path)
    wrong_pack["internal_outcome_mac"] = sign_internal_outcome(wrong_pack, key=KEY)
    with pytest.raises(EvalManifestError, match="command pack digest mismatch"):
        validate_internal_outcome(wrong_pack, key=KEY, artifact_root=tmp_path)

    wrong_source = valid_envelope(tmp_path)
    row = wrong_source["control_receipts"][0]
    command = json.loads((tmp_path / row["command_sha256"].removeprefix("sha256:")).read_text())
    command["source_commit"] = "3" * 40
    row["command_sha256"] = _digest_payload(
        json.dumps(command, sort_keys=True, separators=(",", ":")).encode(), tmp_path
    )
    _seal_receipt(row, tmp_path)
    wrong_source["internal_outcome_mac"] = sign_internal_outcome(wrong_source, key=KEY)
    with pytest.raises(EvalManifestError, match="command source commit mismatch"):
        validate_internal_outcome(wrong_source, key=KEY, artifact_root=tmp_path)

    control_network = valid_envelope(tmp_path)
    row = control_network["control_receipts"][0]
    command = json.loads((tmp_path / row["command_sha256"].removeprefix("sha256:")).read_text())
    command["network_egress"] = True
    row["command_sha256"] = _digest_payload(
        json.dumps(command, sort_keys=True, separators=(",", ":")).encode(), tmp_path
    )
    _seal_receipt(row, tmp_path)
    control_network["internal_outcome_mac"] = sign_internal_outcome(control_network, key=KEY)
    with pytest.raises(EvalManifestError, match="control network egress must be false"):
        validate_internal_outcome(control_network, key=KEY, artifact_root=tmp_path)

    control_allowed = valid_envelope(tmp_path)
    row = control_allowed["control_receipts"][0]
    trace = json.loads((tmp_path / row["trace_sha256"].removeprefix("sha256:")).read_text())
    trace["policy_allowed"] = True
    row["trace_sha256"] = _digest_payload(
        json.dumps(trace, sort_keys=True, separators=(",", ":")).encode(), tmp_path
    )
    _seal_receipt(row, tmp_path)
    control_allowed["internal_outcome_mac"] = sign_internal_outcome(control_allowed, key=KEY)
    with pytest.raises(EvalManifestError, match="control trace policy must deny"):
        validate_internal_outcome(control_allowed, key=KEY, artifact_root=tmp_path)


def test_internal_outcome_rejects_hidden_test_drift_and_weakened_thresholds(
    tmp_path: Path,
) -> None:
    mismatch = valid_envelope(tmp_path)
    ai_row = next(row for row in mismatch["task_receipts"] if row["lane_key"] == "ai_compiled")
    ai_row["hidden_test_sha256"] = _digest_fixture("different-hidden", tmp_path)
    _seal_receipt(ai_row, tmp_path)
    mismatch["internal_outcome_mac"] = sign_internal_outcome(mismatch, key=KEY)
    with pytest.raises(EvalManifestError, match="different hidden tests across lanes"):
        validate_internal_outcome(mismatch, key=KEY, artifact_root=tmp_path)

    weak = valid_envelope(tmp_path)
    weak["runtime_envelope"]["ai_task_success_min"] = 1
    weak["internal_outcome_mac"] = sign_internal_outcome(weak, key=KEY)
    with pytest.raises(EvalManifestError, match="ai_task_success_min must equal 9"):
        validate_internal_outcome(weak, key=KEY, artifact_root=tmp_path)


def test_internal_outcome_enforces_human_gap_before_positive_signal(tmp_path: Path) -> None:
    envelope = valid_envelope(tmp_path, ai_successes=9)
    for row in envelope["task_receipts"]:
        if row["lane_key"] == "human_authored":
            row["success"] = True
            row["exit_code"] = 0
            _seal_receipt(row, tmp_path)
    envelope["internal_outcome_mac"] = sign_internal_outcome(envelope, key=KEY)
    summary = validate_internal_outcome(envelope, key=KEY, artifact_root=tmp_path)
    assert "task gap versus human pack" in summary["failure_reasons"]
    assert summary["computed_verdict"] == "FAIL"


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
    assert summary["computed_verdict"] == "FAIL"
    assert summary["authorization"] == "internal_signal_only"
    assert summary["d0_ready"] is False
    assert summary["promotion_authorized"] is False
    assert summary["stop_investment"] is True

    key_path.unlink()
    rejected = subprocess.run(
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
    assert rejected.returncode == 2
    assert "key file is unreadable" in rejected.stderr
    assert "Traceback" not in rejected.stderr
