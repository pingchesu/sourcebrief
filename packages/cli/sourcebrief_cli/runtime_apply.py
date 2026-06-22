from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

PLAN_SCHEMA_VERSION = "sourcebrief.runtime-install-plan.v1"
RECEIPT_SCHEMA_VERSION = "sourcebrief.runtime-apply-receipt.v1"
DEFAULT_HERMES_CONFIG = Path("~/.hermes/config.yaml")
DEFAULT_RECEIPT_DIR = Path("~/.sourcebrief/runtime-receipts")
SOURCEBRIEF_TOKEN_ENV = "SOURCEBRIEF_TOKEN"
_ALLOWED_HERMES_SERVER_KEYS = {"url", "headers", "timeout", "connect_timeout"}
_ALLOWED_HERMES_HEADER_KEYS = {"Authorization"}
_AUTH_PLACEHOLDER = "Bearer ${SOURCEBRIEF_" "TOKEN}"
_MAX_FUTURE_SKEW_SECONDS = 300


class RuntimeApplyError(RuntimeError):
    """User-facing runtime apply error."""


@dataclass(frozen=True)
class PlanValidation:
    plan: dict[str, Any]
    digest: str
    generated_at_epoch: float


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def plan_digest(plan: dict[str, Any]) -> str:
    body = dict(plan)
    body.pop("plan_digest", None)
    return "sha256:" + hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def attach_plan_metadata(plan: dict[str, Any]) -> dict[str, Any]:
    enriched = dict(plan)
    enriched.setdefault("schema_version", PLAN_SCHEMA_VERSION)
    enriched["plan_digest"] = plan_digest(enriched)
    return enriched


def sha256_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return sha256_bytes(path.read_bytes())


def _parse_generated_at(value: Any) -> float:
    if not isinstance(value, str):
        raise RuntimeApplyError("plan generated_at must be an ISO-8601 string")
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise RuntimeApplyError("plan generated_at is not valid ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.timestamp()


def read_plan(path: Path, *, target: str, max_age_seconds: int) -> PlanValidation:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeApplyError(f"plan is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise RuntimeApplyError("plan must be a JSON object")
    if raw.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise RuntimeApplyError(f"unsupported or missing plan schema_version: {raw.get('schema_version')!r}")
    expected_digest = raw.get("plan_digest")
    if not isinstance(expected_digest, str) or not expected_digest.startswith("sha256:"):
        raise RuntimeApplyError("plan is missing plan_digest")
    actual_digest = plan_digest(raw)
    if expected_digest != actual_digest:
        raise RuntimeApplyError("plan digest mismatch; regenerate the plan before applying")
    if raw.get("target") != target:
        raise RuntimeApplyError(f"plan target {raw.get('target')!r} does not match --target {target!r}")
    if target != "hermes":
        raise RuntimeApplyError("runtime apply currently supports only --target hermes")
    for field in ["workspace_id", "project_id", "server_name", "mcp_config", "endpoints"]:
        if field not in raw:
            raise RuntimeApplyError(f"plan missing required field: {field}")
    generated_epoch = _parse_generated_at(raw.get("generated_at"))
    now = time.time()
    if generated_epoch - now > _MAX_FUTURE_SKEW_SECONDS:
        raise RuntimeApplyError("plan generated_at is too far in the future")
    if max_age_seconds >= 0 and now - generated_epoch > max_age_seconds:
        raise RuntimeApplyError("plan is stale; regenerate it before applying")
    return PlanValidation(plan=raw, digest=actual_digest, generated_at_epoch=generated_epoch)


def hermes_config_path(config_path: str | None = None) -> Path:
    if config_path:
        return Path(config_path).expanduser()
    return DEFAULT_HERMES_CONFIG.expanduser()


def receipt_path(path: str | None = None) -> Path:
    if path:
        return Path(path).expanduser()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    suffix = uuid.uuid4().hex[:8]
    return (DEFAULT_RECEIPT_DIR / f"sourcebrief-hermes-{stamp}-{suffix}.json").expanduser()


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise RuntimeApplyError(f"Hermes config {path} must be a YAML mapping")
    return data


def _validate_server_shape(plan: dict[str, Any], server: dict[str, Any]) -> None:
    extra_keys = set(server) - _ALLOWED_HERMES_SERVER_KEYS
    if extra_keys:
        raise RuntimeApplyError(f"Hermes mcp_config has unsupported server keys: {sorted(extra_keys)}")
    endpoints = plan.get("endpoints")
    if not isinstance(endpoints, dict) or not isinstance(endpoints.get("mcp_url"), str):
        raise RuntimeApplyError("plan endpoints.mcp_url must be a string")
    if server.get("url") != endpoints["mcp_url"]:
        raise RuntimeApplyError("Hermes mcp_config URL does not match plan endpoints.mcp_url")
    headers = server.get("headers")
    if not isinstance(headers, dict):
        raise RuntimeApplyError("Hermes mcp_config headers must be a mapping")
    extra_headers = set(headers) - _ALLOWED_HERMES_HEADER_KEYS
    if extra_headers:
        raise RuntimeApplyError(f"Hermes mcp_config has unsupported header keys: {sorted(extra_headers)}")
    if headers.get("Authorization") != _AUTH_PLACEHOLDER:
        raise RuntimeApplyError("Hermes mcp_config must use the SOURCEBRIEF_TOKEN authorization placeholder")
    for timeout_key in ["timeout", "connect_timeout"]:
        if timeout_key in server and not isinstance(server[timeout_key], int):
            raise RuntimeApplyError(f"Hermes mcp_config {timeout_key} must be an integer")


def _parse_hermes_snippet(plan: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    mcp_config = plan.get("mcp_config")
    if not isinstance(mcp_config, dict) or mcp_config.get("format") != "yaml":
        raise RuntimeApplyError("Hermes plan must include YAML mcp_config")
    content = mcp_config.get("content")
    if not isinstance(content, str):
        raise RuntimeApplyError("Hermes plan mcp_config.content must be a string")
    try:
        parsed = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise RuntimeApplyError("Hermes plan mcp_config.content is not valid YAML") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("mcp_servers"), dict):
        raise RuntimeApplyError("Hermes mcp_config must contain mcp_servers")
    server_name = plan.get("server_name")
    if not isinstance(server_name, str) or not server_name:
        raise RuntimeApplyError("plan server_name must be a non-empty string")
    if set(parsed["mcp_servers"]) != {server_name}:
        raise RuntimeApplyError("Hermes mcp_config must contain exactly the planned server entry")
    server = parsed["mcp_servers"].get(server_name)
    if not isinstance(server, dict):
        raise RuntimeApplyError("Hermes mcp_config is missing the planned server entry")
    _validate_server_shape(plan, server)
    return server_name, server


def _planned_config(config_path: Path, plan: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    server_name, server = _parse_hermes_snippet(plan)
    config = _load_yaml_mapping(config_path)
    mcp_servers = config.get("mcp_servers")
    if mcp_servers is None:
        mcp_servers = {}
        config["mcp_servers"] = mcp_servers
    if not isinstance(mcp_servers, dict):
        raise RuntimeApplyError("Hermes config mcp_servers must be a mapping")
    updated = dict(config)
    updated_servers = dict(mcp_servers)
    updated_servers[server_name] = server
    updated["mcp_servers"] = updated_servers
    return server_name, config, updated


def _atomic_write(path: Path, content: str, *, mode_from: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        if mode_from is not None and mode_from.exists():
            tmp_path.chmod(mode_from.stat().st_mode & 0o777)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _dump_yaml(data: dict[str, Any]) -> str:
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=False)


def _is_owned_created_config(path: Path, server_name: str) -> bool:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return False
    return isinstance(data, dict) and set(data) == {"mcp_servers"} and isinstance(data["mcp_servers"], dict) and set(data["mcp_servers"]) == {server_name}


def _validate_distinct_paths(config_path: Path, receipt_file: Path) -> None:
    if config_path.resolve() == receipt_file.resolve():
        raise RuntimeApplyError("receipt path must be different from Hermes config path")
    if config_path.suffix.lower() not in {".yaml", ".yml"}:
        raise RuntimeApplyError("Hermes config path must end in .yaml or .yml")
    if receipt_file.suffix.lower() != ".json":
        raise RuntimeApplyError("receipt path must end in .json")


def detect(config_path: Path) -> dict[str, Any]:
    parent = config_path.parent if config_path.parent.exists() else config_path.parent.parent
    return {
        "runtimes": [
            {
                "target": "hermes",
                "config_path": str(config_path),
                "exists": config_path.exists(),
                "writable_parent": os.access(parent, os.W_OK) if parent.exists() else False,
            }
        ]
    }


def dry_run_apply(validation: PlanValidation, config_path: Path) -> dict[str, Any]:
    server_name, before, after = _planned_config(config_path, validation.plan)
    rendered = _dump_yaml(after)
    return {
        "status": "dry_run",
        "target": "hermes",
        "server_name": server_name,
        "plan_digest": validation.digest,
        "operations": [
            {
                "action": "upsert_mcp_server",
                "path": str(config_path),
                "created": not config_path.exists(),
                "pre_hash": sha256_file(config_path),
                "post_hash": sha256_bytes(rendered.encode("utf-8")),
                "changed": before != after,
            }
        ],
    }


def _receipt_payload(
    *,
    validation: PlanValidation,
    server_name: str,
    config_path: Path,
    before_exists: bool,
    pre_hash: str | None,
    post_hash: str,
    backup_path: Path | None,
    receipt_file: Path,
    status: str,
) -> dict[str, Any]:
    return {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "managed_by": "sourcebrief_runtime_apply",
        "status": status,
        "plan_digest": validation.digest,
        "target": "hermes",
        "server_name": server_name,
        "files": [
            {
                "path": str(config_path),
                "created": not before_exists,
                "pre_hash": pre_hash,
                "post_hash": post_hash,
                "backup_path": str(backup_path) if backup_path else None,
            }
        ],
        "token_env_vars": [SOURCEBRIEF_TOKEN_ENV],
        "validation_status": "not_run",
        "rollback_command": f"sourcebrief runtime rollback --receipt {receipt_file}",
        "created_at": datetime.now(UTC).isoformat(),
    }


def apply_plan(validation: PlanValidation, config_path: Path, receipt_file: Path) -> dict[str, Any]:
    _validate_distinct_paths(config_path, receipt_file)
    server_name, _before, after = _planned_config(config_path, validation.plan)
    before_exists = config_path.exists()
    pre_hash = sha256_file(config_path)
    rendered = _dump_yaml(after)
    post_hash = sha256_bytes(rendered.encode("utf-8"))
    receipt_file.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if before_exists:
        backup_dir = receipt_file.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{receipt_file.stem}-{config_path.name}.bak"
        shutil.copy2(config_path, backup_path)
    pending = _receipt_payload(
        validation=validation,
        server_name=server_name,
        config_path=config_path,
        before_exists=before_exists,
        pre_hash=pre_hash,
        post_hash=post_hash,
        backup_path=backup_path,
        receipt_file=receipt_file,
        status="pending_config_write",
    )
    _atomic_write(receipt_file, json.dumps(pending, indent=2, sort_keys=True) + "\n")
    _atomic_write(config_path, rendered, mode_from=config_path if before_exists else None)
    receipt = dict(pending)
    receipt["status"] = "applied"
    _atomic_write(receipt_file, json.dumps(receipt, indent=2, sort_keys=True) + "\n", mode_from=receipt_file)
    return {"status": "applied", "receipt_path": str(receipt_file), "receipt": receipt}


def _validate_receipt(receipt: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    if receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise RuntimeApplyError("unsupported receipt schema_version")
    if receipt.get("managed_by") != "sourcebrief_runtime_apply":
        raise RuntimeApplyError("receipt was not created by sourcebrief runtime apply")
    if receipt.get("target") != "hermes":
        raise RuntimeApplyError("receipt target must be hermes")
    server_name = receipt.get("server_name")
    if not isinstance(server_name, str) or not server_name:
        raise RuntimeApplyError("receipt missing server_name")
    files = receipt.get("files")
    if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
        raise RuntimeApplyError("receipt must contain exactly one managed file")
    return server_name, files


def rollback(receipt_file: Path, *, force: bool = False) -> dict[str, Any]:
    try:
        receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeApplyError("receipt is not valid JSON") from exc
    if not isinstance(receipt, dict):
        raise RuntimeApplyError("receipt must be a JSON object")
    server_name, files = _validate_receipt(receipt)
    restored: list[dict[str, Any]] = []
    for file_info in files:
        path = Path(file_info["path"]).expanduser()
        _validate_distinct_paths(path, receipt_file)
        expected_post = file_info.get("post_hash")
        current_hash = sha256_file(path)
        if current_hash != expected_post and not force:
            raise RuntimeApplyError("current file hash differs from receipt post_hash; use --force to override")
        if file_info.get("created"):
            if path.exists():
                if not _is_owned_created_config(path, server_name):
                    raise RuntimeApplyError("created-file rollback refuses to remove a non-SourceBrief-only config")
                path.unlink()
            restored.append({"path": str(path), "action": "removed_created_file"})
            continue
        backup = file_info.get("backup_path")
        if not backup:
            raise RuntimeApplyError("receipt is missing backup_path for existing file rollback")
        backup_path = Path(backup).expanduser()
        expected_backup_parent = (receipt_file.parent / "backups").resolve()
        if backup_path.resolve().parent != expected_backup_parent:
            raise RuntimeApplyError("receipt backup_path is outside the managed backup directory")
        if not backup_path.name.startswith(f"{receipt_file.stem}-"):
            raise RuntimeApplyError("receipt backup_path does not match the receipt name")
        if not backup_path.exists():
            raise RuntimeApplyError("receipt backup_path does not exist")
        if sha256_file(backup_path) != file_info.get("pre_hash"):
            raise RuntimeApplyError("receipt backup hash does not match pre_hash")
        shutil.copy2(backup_path, path)
        restored.append({"path": str(path), "action": "restored_backup", "post_hash": sha256_file(path)})
    return {"status": "rolled_back", "receipt_path": str(receipt_file), "files": restored}


def _validator_argv(plan: dict[str, Any]) -> list[str]:
    endpoints = plan.get("endpoints")
    if not isinstance(endpoints, dict) or not isinstance(endpoints.get("api_base_url"), str):
        raise RuntimeApplyError("plan endpoints.api_base_url must be a string")
    argv = [
        sys.executable,
        "scripts/hermes_integration.py",
        "--api-url",
        endpoints["api_base_url"],
        "--workspace-id",
        str(plan["workspace_id"]),
        "--project-id",
        str(plan["project_id"]),
        "--query",
        "SourceBrief runtime install plan validation",
        "--token-env",
        SOURCEBRIEF_TOKEN_ENV,
        "--redact-token",
    ]
    resources = plan.get("resource_scope", {}).get("resources") if isinstance(plan.get("resource_scope"), dict) else None
    if isinstance(resources, list) and resources:
        for resource in resources:
            resource_id = resource.get("resource_id") if isinstance(resource, dict) else resource
            if resource_id:
                argv.extend(["--resource-id", str(resource_id)])
    else:
        argv.append("--allow-empty")
    return argv


def validate_plan(validation: PlanValidation, *, run: bool = False) -> dict[str, Any]:
    argv = _validator_argv(validation.plan)
    command = " ".join(shlex.quote(part) for part in argv)
    if not run:
        return {
            "status": "not_run",
            "reason": "pass --run to execute the generated validator command",
            "commands": [command],
        }
    completed = subprocess.run(argv, text=True, capture_output=True, check=False)  # noqa: S603 - fixed argv assembled from a validated plan
    return {
        "status": "passed" if completed.returncode == 0 else "failed",
        "returncode": completed.returncode,
        "stdout": completed.stdout.replace(os.getenv(SOURCEBRIEF_TOKEN_ENV, ""), "<redacted>")
        if os.getenv(SOURCEBRIEF_TOKEN_ENV)
        else completed.stdout,
        "stderr": completed.stderr.replace(os.getenv(SOURCEBRIEF_TOKEN_ENV, ""), "<redacted>")
        if os.getenv(SOURCEBRIEF_TOKEN_ENV)
        else completed.stderr,
    }
