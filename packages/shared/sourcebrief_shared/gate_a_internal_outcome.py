from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import shlex
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
NORMATIVE_THRESHOLDS = {
    "ai_task_success_min": 9,
    "ai_uplift_min_tasks": 3,
    "baseline_regressions_max": 1,
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
) -> bytes:
    hexadecimal = declared_digest.removeprefix("sha256:")
    root = Path(artifact_root)
    try:
        root_stat = root.lstat()
    except FileNotFoundError as exc:
        raise EvalManifestError("internal outcome artifact_root is missing") from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise EvalManifestError(
            "internal outcome artifact_root must be a non-symlink directory"
        )
    path = root / hexadecimal
    try:
        file_stat = path.lstat()
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise EvalManifestError(f"{context} missing CAS artifact {declared_digest}") from exc
    if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
        raise EvalManifestError(f"{context} CAS artifact must be a non-symlink regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise EvalManifestError(f"{context} CAS artifact could not be opened safely") from exc
    hasher = hashlib.sha256()
    chunks: list[bytes] = []
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise EvalManifestError(f"{context} CAS artifact must remain a regular file")
        while chunk := os.read(descriptor, 1024 * 1024):
            chunks.append(chunk)
            hasher.update(chunk)
    finally:
        os.close(descriptor)
    if hasher.hexdigest() != hexadecimal:
        raise EvalManifestError(f"{context} CAS artifact digest mismatch")
    return b"".join(chunks)


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
            "trace_sha256",
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
        "trace_sha256",
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


def _command_tokens(command: str) -> list[str]:
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError:
        return []


def _command_segments(command: str) -> list[list[str]]:
    segments: list[list[str]] = []
    current: list[str] = []
    for token in _command_tokens(command):
        if token and set(token) <= {";", "&", "|"}:
            if current:
                segments.append(current)
                current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def _command_uses_network(command: str) -> bool:
    banned = {"curl", "wget", "ssh", "scp", "nc", "ncat", "socat", "telnet"}
    normalized_raw = command.lower().replace("'", "").replace('"', "")
    compact_raw = re.sub(r"[^a-z0-9_]+", "", normalized_raw)
    if "create_connection" in normalized_raw or "createconnection" in compact_raw:
        return True
    if "socket" in compact_raw and "connect" in compact_raw:
        return True
    if re.search(
        r"(^|[^a-z0-9_])git\s+"
        r"(clone|fetch|pull|push|ls-remote|submodule)([^a-z0-9_]|$)",
        normalized_raw,
    ):
        return True
    if any(
        re.search(rf"(^|[^a-z0-9_]){re.escape(token)}([^a-z0-9_]|$)", normalized_raw)
        for token in banned
    ):
        return True
    network_markers = (
        "import socket",
        "from socket",
        "import requests",
        "from requests",
        "import urllib",
        "from urllib",
        "http.client",
        "aiohttp",
        "httpx",
    )
    for segment in _command_segments(command):
        executable = Path(segment[0]).name.lower()
        if executable in banned:
            return True
        if executable in {"bash", "sh", "zsh"}:
            for index, token in enumerate(segment[:-1]):
                if token in {"-c", "-lc"} and _command_uses_network(
                    segment[index + 1]
                ):
                    return True
        if executable.startswith("python") and "-c" in segment:
            code = segment[segment.index("-c") + 1].lower()
            compact_code = re.sub(r"[^a-z0-9_]+", "", code)
            if any(marker in code for marker in network_markers) or any(
                token in compact_code
                for token in ("socket", "requests", "urllib", "httpx", "aiohttp")
            ):
                return True
    return False


def _command_uses_sourcebrief(command: str) -> bool:
    forbidden = ("sourcebrief", "source_brief", "sourcebrief_cli", "source_brief_cli", "contextsmith")
    normalized_raw = (
        command.lower().replace("'", "").replace('"', "").replace("-", "_")
    )
    compact_raw = re.sub(r"[^a-z0-9_]+", "", normalized_raw)
    if any(token in compact_raw for token in forbidden):
        return True
    if (
        "fromhex" in compact_raw
        or "b64decode" in compact_raw
        or "base64" in compact_raw
    ) and (
        "import_module" in normalized_raw
        or "importmodule" in compact_raw
        or "__import__" in normalized_raw
    ):
        return True
    for segment in _command_segments(command):
        dequoted = " ".join(segment).lower().replace("-", "_")
        if any(token in dequoted for token in forbidden):
            return True
        executable = Path(segment[0]).name.lower()
        if executable in {"bash", "sh", "zsh"}:
            for index, token in enumerate(segment[:-1]):
                if token in {"-c", "-lc"} and _command_uses_sourcebrief(segment[index + 1]):
                    return True
    return False


def _cas_bytes(verified_artifacts: dict[str, bytes], digest: str) -> bytes:
    try:
        return verified_artifacts[digest]
    except KeyError as exc:
        raise EvalManifestError(f"missing verified CAS bytes for {digest}") from exc


def _json_cas_object(
    verified_artifacts: dict[str, bytes], digest: str, context: str
) -> dict[str, Any]:
    try:
        return _object(json.loads(_cas_bytes(verified_artifacts, digest).decode("utf-8")), context)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvalManifestError(f"{context} is not UTF-8 JSON") from exc


def _validate_task_command(
    verified_artifacts: dict[str, bytes],
    receipt: dict[str, Any],
    context: str,
    *,
    source_commit: str,
    pack_by_lane: dict[str, str | None],
    artifact_root: Path,
) -> None:
    command = _json_cas_object(verified_artifacts, receipt["command_sha256"], f"{context}.command")
    _exact(
        command,
        {
            "schema",
            "lane_key",
            "task_id",
            "source_commit",
            "network_egress",
            "pack_sha256",
            "codex_argv",
            "codex_stdin_sha256",
            "codex_timeout_seconds",
            "codex_trace_policy_violations",
            "landlock_launcher_sha256",
            "test_argv",
            "test_timeout_seconds",
        },
        f"{context}.command",
    )
    if command.get("schema") != "sourcebrief.gate-a-cell-command.v2":
        raise EvalManifestError(f"{context}.command schema is unsupported")
    if command.get("lane_key") != receipt["lane_key"] or command.get("task_id") != receipt["task_id"]:
        raise EvalManifestError(f"{context}.command identity mismatch")
    if command.get("source_commit") != source_commit:
        raise EvalManifestError(f"{context}.command source commit mismatch")
    if command.get("pack_sha256") != pack_by_lane[receipt["lane_key"]]:
        raise EvalManifestError(f"{context}.command pack digest mismatch")
    codex_stdin_sha256 = _digest(
        command.get("codex_stdin_sha256"), f"{context}.command.codex_stdin_sha256"
    )
    _digest(
        command.get("landlock_launcher_sha256"), f"{context}.command.landlock_launcher_sha256"
    )
    _integer(command.get("codex_timeout_seconds"), f"{context}.command.codex_timeout_seconds", 1)
    _integer(command.get("test_timeout_seconds"), f"{context}.command.test_timeout_seconds", 1)
    if receipt["lane_key"] == DIRECT_BASELINE and command.get("pack_sha256") is not None:
        raise EvalManifestError(f"{context}.command direct-tools pack must be null")
    stdin_payload = verified_artifacts.get(codex_stdin_sha256)
    stdin_path = artifact_root / codex_stdin_sha256.removeprefix("sha256:")
    if stdin_payload is None and stdin_path.exists():
        stdin_payload = _verify_cas_artifact(artifact_root, codex_stdin_sha256, f"{context}.command.codex_stdin_sha256")
    if receipt["lane_key"] == DIRECT_BASELINE and stdin_payload is not None:
        stdin_text = stdin_payload.decode("utf-8", errors="ignore")
        if _command_uses_network(stdin_text) or _command_uses_sourcebrief(stdin_text):
            raise EvalManifestError(f"{context}.command direct-tools stdin used SourceBrief or network")
    if _string(command.get("network_egress"), f"{context}.command.network_egress") != "model-api-required; shell-network-use-rejected-from-retained-command-trace":
        raise EvalManifestError(f"{context}.command network policy is unsupported")
    if _list(command.get("codex_trace_policy_violations"), f"{context}.command.codex_trace_policy_violations"):
        raise EvalManifestError(f"{context}.command declares trace policy violations")
    for field in ("codex_argv", "test_argv"):
        argv = _list(command.get(field), f"{context}.command.{field}")
        if not argv or any(not isinstance(item, str) or not item for item in argv):
            raise EvalManifestError(f"{context}.command.{field} must be non-empty string argv")
        joined = " ".join(argv)
        if _command_uses_network(joined):
            raise EvalManifestError(f"{context}.command used shell-level network access")
        executable_names = " ".join(Path(item).name for item in argv)
        if receipt["lane_key"] == DIRECT_BASELINE and _command_uses_sourcebrief(
            executable_names if field == "codex_argv" else joined
        ):
            raise EvalManifestError(f"{context}.command direct-tools used SourceBrief")


def _validate_control_command(
    verified_artifacts: dict[str, bytes],
    receipt: dict[str, Any],
    context: str,
    *,
    source_commit: str,
    pack_by_lane: dict[str, str | None],
) -> None:
    command = _json_cas_object(verified_artifacts, receipt["command_sha256"], f"{context}.command")
    _exact(
        command,
        {
            "schema",
            "lane_key",
            "control_id",
            "source_commit",
            "network_egress",
            "pack_sha256",
            "operation",
            "control_spec_sha256",
        },
        f"{context}.command",
    )
    if command.get("schema") != "sourcebrief.gate-a-control-command.v1":
        raise EvalManifestError(f"{context}.command schema is unsupported")
    if command.get("lane_key") != receipt["lane_key"] or command.get("control_id") != receipt["control_id"]:
        raise EvalManifestError(f"{context}.command identity mismatch")
    if command.get("source_commit") != source_commit:
        raise EvalManifestError(f"{context}.command source commit mismatch")
    if command.get("pack_sha256") != pack_by_lane[receipt["lane_key"]]:
        raise EvalManifestError(f"{context}.command pack digest mismatch")
    if receipt["lane_key"] == DIRECT_BASELINE and command.get("pack_sha256") is not None:
        raise EvalManifestError(f"{context}.command direct-tools pack must be null")
    _boolean(command.get("network_egress"), f"{context}.command.network_egress")
    if command.get("network_egress") is not False:
        raise EvalManifestError(f"{context}.command control network egress must be false")
    operation = _string(command.get("operation"), f"{context}.command.operation")
    _digest(command.get("control_spec_sha256"), f"{context}.command.control_spec_sha256")
    if _command_uses_network(operation):
        raise EvalManifestError(f"{context}.command used shell-level network access")
    if receipt["lane_key"] == DIRECT_BASELINE and _command_uses_sourcebrief(operation):
        raise EvalManifestError(f"{context}.command direct-tools used SourceBrief")


def _validate_task_trace(verified_artifacts: dict[str, bytes], receipt: dict[str, Any], context: str) -> None:
    payload = _cas_bytes(verified_artifacts, receipt["trace_sha256"])
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvalManifestError(f"{context} trace must be UTF-8 JSONL") from exc
    saw_thread = False
    saw_completion = False
    command_count = 0
    for line_number, line in enumerate(text.splitlines(), start=1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvalManifestError(f"{context} trace line {line_number} is not JSON") from exc
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise EvalManifestError(f"{context} trace line {line_number} is malformed")
        if event["type"] not in {
            "thread.started",
            "turn.started",
            "turn.completed",
            "item.started",
            "item.updated",
            "item.completed",
        }:
            raise EvalManifestError(f"{context} trace event type is unsupported")
        top_level_probe = json.dumps(
            {key: event.get(key) for key in ("type", "name", "server") if key in event},
            sort_keys=True,
        )
        if "mcp" in top_level_probe.lower() or _command_uses_sourcebrief(top_level_probe):
            raise EvalManifestError(f"{context} trace used MCP")
        saw_thread = saw_thread or event["type"] == "thread.started"
        saw_completion = saw_completion or event["type"] == "turn.completed"
        if event["type"] in {"mcp_tool_call", "mcp_tool_result"}:
            raise EvalManifestError(f"{context} trace used MCP")
        item = event.get("item")
        if isinstance(item, dict):
            nested_probe = json.dumps(
                {
                    key: item.get(key)
                    for key in ("type", "name", "server", "tool", "tool_name")
                    if key in item
                },
                sort_keys=True,
            )
            allowed_item_types = {
                "command_execution",
                "agent_message",
                "file_change",
                "todo_list",
            }
            if item.get("type") not in allowed_item_types:
                raise EvalManifestError(f"{context} trace item type is unsupported")
            if (
                item.get("type")
                in {
                    "tool_call",
                    "function_call",
                    "function_call_output",
                    "mcp_tool_call",
                    "mcp_tool_result",
                    "tool_result",
                }
                or "mcp" in nested_probe.lower()
                or _command_uses_sourcebrief(nested_probe)
            ):
                raise EvalManifestError(f"{context} trace used MCP")
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "mcp_tool_call":
            raise EvalManifestError(f"{context} trace used MCP")
        if item_type != "command_execution":
            continue
        command_count += 1
        command = item.get("command")
        if not isinstance(command, str) or not command:
            raise EvalManifestError(f"{context} trace command is invalid")
        if _command_uses_network(command):
            raise EvalManifestError(f"{context} trace used shell-level network access")
        if receipt["lane_key"] == DIRECT_BASELINE and _command_uses_sourcebrief(command):
            raise EvalManifestError(f"{context} direct-tools trace used SourceBrief")
    if not saw_thread or not saw_completion or command_count == 0:
        raise EvalManifestError(f"{context} trace is incomplete")


def _validate_control_trace(
    verified_artifacts: dict[str, bytes], receipt: dict[str, Any], context: str
) -> None:
    try:
        trace = json.loads(_cas_bytes(verified_artifacts, receipt["trace_sha256"]).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvalManifestError(f"{context} control trace is not UTF-8 JSON") from exc
    trace = _object(trace, f"{context}.trace")
    _exact(
        trace,
        {"schema", "lane_key", "control_id", "policy_allowed", "checks", "violations"},
        f"{context}.trace",
    )
    if trace.get("schema") != "sourcebrief.gate-a-control-trace.v1":
        raise EvalManifestError(f"{context} control trace schema is unsupported")
    if trace.get("lane_key") != receipt["lane_key"] or trace.get("control_id") != receipt["control_id"]:
        raise EvalManifestError(f"{context} control trace identity mismatch")
    policy_allowed = _boolean(trace.get("policy_allowed"), f"{context}.trace.policy_allowed")
    if policy_allowed:
        raise EvalManifestError(f"{context} control trace policy must deny the prohibited action")
    for field in ("checks", "violations"):
        values = _list(trace.get(field), f"{context}.trace.{field}")
        for index, value in enumerate(values):
            _string(value, f"{context}.trace.{field}[{index}]")


def validate_internal_outcome(
    envelope: dict[str, Any], *, key: bytes, artifact_root: str | Path
) -> dict[str, Any]:
    artifact_root = Path(artifact_root)
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
    source_commit = _string(envelope.get("source_commit"), "internal_outcome.source_commit")

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
    if _string(
        runtime.get("network_egress"), "runtime_envelope.network_egress"
    ) != "model_api_only_trace_enforced":
        raise EvalManifestError(
            "internal runtime permits only the model API; shell network activity must be rejected from retained traces"
        )
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
    for threshold_key, expected in NORMATIVE_THRESHOLDS.items():
        actual = runtime.get(threshold_key)
        if actual != expected:
            raise EvalManifestError(f"runtime_envelope.{threshold_key} must equal {expected}")

    development = _ids(envelope.get("development_task_ids"), "development_task_ids", 4)
    held_out = _ids(envelope.get("held_out_task_ids"), "held_out_task_ids", 12)
    controls = _ids(envelope.get("control_ids"), "control_ids", 6)
    if set(development) & (set(held_out) | set(controls)) or set(held_out) & set(controls):
        raise EvalManifestError("internal outcome task splits must be disjoint")

    packs = _object(envelope.get("pack_sha256_by_lane"), "pack_sha256_by_lane")
    _exact(packs, LANES, "pack_sha256_by_lane")
    if packs[DIRECT_BASELINE] is not None:
        raise EvalManifestError("direct-tools baseline must not receive a SourceBrief pack")
    pack_by_lane: dict[str, str | None] = {DIRECT_BASELINE: None}
    for lane in LANES - {DIRECT_BASELINE}:
        pack_digest = _digest(packs.get(lane), f"pack_sha256_by_lane.{lane}")
        pack_by_lane[lane] = pack_digest
        cas_digests[f"pack_sha256_by_lane.{lane}"] = pack_digest

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

    expected_mac = sign_internal_outcome(envelope, key=key)
    declared_mac = _string(envelope.get("internal_outcome_mac"), "internal_outcome_mac")
    if not hmac.compare_digest(expected_mac, declared_mac):
        raise EvalManifestError("internal outcome MAC is invalid")

    verified_artifacts: dict[str, bytes] = {}
    for context, declared_digest in sorted(cas_digests.items()):
        verified_artifacts[declared_digest] = _verify_cas_artifact(
            artifact_root, declared_digest, context
        )

    for (lane, task), receipt in task_by_key.items():
        cell_context = f"task {lane}/{task}"
        _validate_task_command(
            verified_artifacts,
            receipt,
            cell_context,
            source_commit=source_commit,
            pack_by_lane=pack_by_lane,
            artifact_root=artifact_root,
        )
        _validate_task_trace(verified_artifacts, receipt, cell_context)
    for (lane, control), receipt in control_by_key.items():
        cell_context = f"control {lane}/{control}"
        _validate_control_command(
            verified_artifacts,
            receipt,
            cell_context,
            source_commit=source_commit,
            pack_by_lane=pack_by_lane,
        )
        _validate_control_trace(verified_artifacts, receipt, cell_context)

    for task in held_out:
        digests = {task_by_key[(lane, task)]["hidden_test_sha256"] for lane in LANES}
        if len(digests) != 1:
            raise EvalManifestError(f"held-out task {task} used different hidden tests across lanes")
    for control in controls:
        digests = {control_by_key[(lane, control)]["hidden_test_sha256"] for lane in LANES}
        if len(digests) != 1:
            raise EvalManifestError(f"control {control} used different hidden tests across lanes")

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
    if success_counts["human_authored"] - success_counts["ai_compiled"] > 1:
        failures.append("task gap versus human pack")
    failures.append("command hidden-test execution evidence incomplete")
    failures.append("compiler economics evidence incomplete")
    if not controls_passed:
        failures.append("control failures")
    if total_cost > cost_budget:
        failures.append("cost budget")
    if elapsed > latency_budget:
        failures.append("latency budget")

    effective_uplift = uplift
    if any(
        reason in failures
        for reason in (
            "command hidden-test execution evidence incomplete",
            "compiler economics evidence incomplete",
        )
    ):
        effective_uplift = min(uplift, 0)

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
        "ai_uplift_tasks": effective_uplift,
        "baseline_regressions": ai_regressions,
        "controls_passed": controls_passed,
        "total_cost_usd": total_cost,
        "elapsed_seconds": elapsed,
    }
