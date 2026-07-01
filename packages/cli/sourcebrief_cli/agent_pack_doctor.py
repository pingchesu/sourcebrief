from __future__ import annotations

import argparse
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sourcebrief_cli import skill_install

RemoteDoctor = Callable[[Any, argparse.Namespace], dict[str, Any]]
CommandHandler = Callable[[Any, argparse.Namespace], Any]


SECRET_LIKE_RE = re.compile(
    r"(?i)(?:"
    r"\bcs_[a-z0-9_\-]{8,}\b|"
    r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{8,}\b|"
    r"\bgithub_pat_[A-Za-z0-9_]{8,}\b|"
    r"\bglpat-[A-Za-z0-9_\-]{8,}\b|"
    r"\bxox[baprs]-[A-Za-z0-9_\-]{8,}\b|"
    r"\b(?:sourcebrief|contextsmith)[-_]?(?:token|key|secret)[-_]?[a-z0-9_\-]{4,}\b|"
    r"\bsk-[a-z0-9_\-]{8,}\b"
    r")"
)


def _redact_manifest_key(key: Any) -> str:
    text = str(key)
    return "[redacted-secret-like-key]" if SECRET_LIKE_RE.search(text) else text


def _redact_manifest_value(value: Any) -> Any:
    if isinstance(value, str) and SECRET_LIKE_RE.search(value):
        return "[redacted-secret-like-value]"
    if isinstance(value, list):
        return [_redact_manifest_value(item) for item in value]
    if isinstance(value, dict):
        return {
            _redact_manifest_key(key): _redact_manifest_value(item) for key, item in value.items()
        }
    return value


def _agent_pack_check(name: str, status: str, **fields: Any) -> dict[str, Any]:
    return {"name": name, "status": status, **_redact_manifest_value(fields)}


def _strict_positive_int_at_most(value: Any, max_value: int) -> bool:
    return type(value) is int and 0 < value <= max_value


def _agent_pack_manifest_checks(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    mode = manifest.get("mode")
    schema_ok = manifest.get("agent_pack_schema_version") == "sourcebrief.agent-pack.v1"
    checks.append(
        _agent_pack_check(
            "manifest_schema",
            "passed"
            if schema_ok
            else "failed"
            if mode in {"pinned-snapshot", "local-mirror"}
            else "warning",
            agent_pack_schema_version=manifest.get("agent_pack_schema_version"),
            message=None
            if schema_ok
            else "manifest predates Agent Pack policy metadata"
            if mode not in {"pinned-snapshot", "local-mirror"}
            else f"{mode} manifests require sourcebrief.agent-pack.v1",
        )
    )
    raw_runtime_access = manifest.get("runtime_access")
    runtime_access = raw_runtime_access if isinstance(raw_runtime_access, dict) else {}
    if mode == "local-mirror":
        runtime_access_ok = (
            manifest.get("requires_sourcebrief_remote") is False
            and runtime_access.get("mode") == "local-mirror"
            and runtime_access.get("requires_sourcebrief_remote") is False
            and runtime_access.get("local_repo_required") is False
            and runtime_access.get("local_grep_allowed") is True
            and runtime_access.get("local_edits_allowed") is False
            and runtime_access.get("current_claims_require_remote") is True
        )
    else:
        runtime_access_ok = (
            mode in {"remote-live", "pinned-snapshot"}
            and manifest.get("requires_sourcebrief_remote") is True
            and runtime_access.get("mode") == mode
            and runtime_access.get("requires_sourcebrief_remote") is True
            and runtime_access.get("local_repo_required") is False
            and runtime_access.get("local_grep_allowed") is False
            and runtime_access.get("local_edits_allowed") is False
            and runtime_access.get("current_claims_require_remote") is True
        )
    checks.append(
        _agent_pack_check(
            "runtime_access",
            "passed" if runtime_access_ok else "failed",
            mode=mode,
            requires_sourcebrief_remote=manifest.get("requires_sourcebrief_remote"),
            runtime_access_mode=runtime_access.get("mode"),
            runtime_access_requires_sourcebrief_remote=runtime_access.get(
                "requires_sourcebrief_remote"
            ),
            runtime_access_local_repo_required=runtime_access.get("local_repo_required"),
            runtime_access_local_grep_allowed=runtime_access.get("local_grep_allowed"),
            runtime_access_local_edits_allowed=runtime_access.get("local_edits_allowed"),
            runtime_access_current_claims_require_remote=runtime_access.get(
                "current_claims_require_remote"
            ),
        )
    )
    raw_local_payload = manifest.get("local_payload")
    local_payload = raw_local_payload if isinstance(raw_local_payload, dict) else {}
    local_payload_ok = (
        local_payload.get("contains_full_resource") is False
        and local_payload.get("contains_raw_source") is False
        and local_payload.get("contains_embeddings") is False
        and local_payload.get("contains_graph_index") is False
    )
    if mode == "pinned-snapshot":
        local_payload_ok = (
            local_payload_ok
            and local_payload.get("contains_resource_map_summary") is True
            and local_payload.get("contains_cited_excerpts") == "bounded"
        )
    elif mode == "local-mirror":
        local_payload_ok = (
            local_payload.get("contains_full_resource") is True
            and local_payload.get("contains_raw_source") is True
            and local_payload.get("contains_embeddings") is True
            and local_payload.get("contains_graph_index") is True
            and local_payload.get("contains_resource_map_summary") is True
            and local_payload.get("contains_cited_excerpts") == "bounded"
            and bool(local_payload.get("sensitivity_label"))
        )
    checks.append(
        _agent_pack_check(
            "local_payload",
            "passed" if local_payload_ok else "failed",
            contains_full_resource=local_payload.get("contains_full_resource"),
            contains_raw_source=local_payload.get("contains_raw_source"),
            contains_embeddings=local_payload.get("contains_embeddings"),
            contains_graph_index=local_payload.get("contains_graph_index"),
            contains_resource_map_summary=local_payload.get("contains_resource_map_summary"),
            contains_cited_excerpts=local_payload.get("contains_cited_excerpts"),
            sensitivity_label=local_payload.get("sensitivity_label"),
        )
    )
    raw_security_policy = manifest.get("security_policy")
    security_policy = raw_security_policy if isinstance(raw_security_policy, dict) else {}
    security_ok = (
        security_policy.get("requires_runtime_auth") is True
        and security_policy.get("supports_revocation") is True
        and security_policy.get("plaintext_tokens_allowed") is False
        and security_policy.get("server_side_local_apply_allowed") is False
    )
    checks.append(
        _agent_pack_check(
            "security_policy",
            "passed" if security_ok else "failed",
            requires_runtime_auth=security_policy.get("requires_runtime_auth"),
            plaintext_tokens_allowed=security_policy.get("plaintext_tokens_allowed"),
            server_side_local_apply_allowed=security_policy.get("server_side_local_apply_allowed"),
            supports_revocation=security_policy.get("supports_revocation"),
        )
    )
    raw_freshness_policy = manifest.get("freshness_policy")
    freshness_policy = raw_freshness_policy if isinstance(raw_freshness_policy, dict) else {}
    snapshot_age_days = freshness_policy.get("max_snapshot_age_days")
    mirror_age_hours = freshness_policy.get("max_mirror_age_hours")
    freshness_ok = freshness_policy.get("require_remote_for_current_claims") is True
    if mode == "pinned-snapshot":
        freshness_ok = (
            freshness_ok
            and freshness_policy.get("pinned_snapshot") is True
            and freshness_policy.get("offline_current_claims_allowed") is False
            and _strict_positive_int_at_most(snapshot_age_days, 7)
        )
    elif mode == "local-mirror":
        freshness_ok = (
            freshness_ok
            and freshness_policy.get("offline_current_claims_allowed") is False
            and _strict_positive_int_at_most(mirror_age_hours, 24)
            and freshness_policy.get("drift_check_required") is True
            and freshness_policy.get("fail_closed_on_expired_mirror") is True
        )
    checks.append(
        _agent_pack_check(
            "freshness_policy",
            "passed" if freshness_ok else "failed",
            require_remote_for_current_claims=freshness_policy.get(
                "require_remote_for_current_claims"
            ),
            pinned_snapshot=freshness_policy.get("pinned_snapshot"),
            offline_current_claims_allowed=freshness_policy.get("offline_current_claims_allowed"),
            max_snapshot_age_days=freshness_policy.get("max_snapshot_age_days"),
            max_mirror_age_hours=freshness_policy.get("max_mirror_age_hours"),
            drift_check_required=freshness_policy.get("drift_check_required"),
            fail_closed_on_expired_mirror=freshness_policy.get("fail_closed_on_expired_mirror"),
        )
    )
    raw_cache_policy = manifest.get("cache_policy")
    cache_policy = raw_cache_policy if isinstance(raw_cache_policy, dict) else {}
    if mode == "pinned-snapshot":
        cache_snapshot_age_days = cache_policy.get("max_snapshot_age_days")
        cache_ok = (
            cache_policy.get("mode") == "pinned-snapshot"
            and cache_policy.get("pinned_snapshot") is True
            and cache_policy.get("full_resource_sync_default") is False
            and cache_policy.get("local_mirror") is False
            and _strict_positive_int_at_most(cache_snapshot_age_days, 7)
        )
    elif mode == "local-mirror":
        cache_ok = (
            cache_policy.get("mode") == "local-mirror"
            and cache_policy.get("pinned_snapshot") is False
            and cache_policy.get("local_mirror") is True
            and cache_policy.get("full_resource_sync_default") is False
            and cache_policy.get("purge_required") is True
            and cache_policy.get("update_required") is True
            and cache_policy.get("audit_receipts_required") is True
        )
    else:
        cache_ok = (
            cache_policy.get("mode") == "none"
            and cache_policy.get("pinned_snapshot") is False
            and cache_policy.get("full_resource_sync_default") is False
            and cache_policy.get("local_mirror") is False
        )
    checks.append(
        _agent_pack_check(
            "cache_policy",
            "passed" if cache_ok else "failed",
            mode=cache_policy.get("mode"),
            pinned_snapshot=cache_policy.get("pinned_snapshot"),
            local_mirror=cache_policy.get("local_mirror"),
            full_resource_sync_default=cache_policy.get("full_resource_sync_default"),
            max_snapshot_age_days=cache_policy.get("max_snapshot_age_days"),
            purge_required=cache_policy.get("purge_required"),
            update_required=cache_policy.get("update_required"),
            audit_receipts_required=cache_policy.get("audit_receipts_required"),
        )
    )
    if mode == "local-mirror":
        raw_local_mirror_policy = manifest.get("local_mirror_policy")
        local_mirror_policy = (
            raw_local_mirror_policy if isinstance(raw_local_mirror_policy, dict) else {}
        )
        local_mirror_policy_ok = (
            local_mirror_policy.get("explicit_opt_in") is True
            and local_mirror_policy.get("purge_command_required") is True
            and local_mirror_policy.get("update_command_required") is True
            and local_mirror_policy.get("drift_detection_required") is True
            and local_mirror_policy.get("audit_receipts_required") is True
            and local_mirror_policy.get("sensitivity_labels_required") is True
            and local_mirror_policy.get("local_access_control_required") is True
            and local_mirror_policy.get("encryption_at_rest_required") is True
            and local_mirror_policy.get("server_side_apply_allowed") is False
        )
        checks.append(
            _agent_pack_check(
                "local_mirror_policy",
                "passed" if local_mirror_policy_ok else "failed",
                explicit_opt_in=local_mirror_policy.get("explicit_opt_in"),
                purge_command_required=local_mirror_policy.get("purge_command_required"),
                update_command_required=local_mirror_policy.get("update_command_required"),
                drift_detection_required=local_mirror_policy.get("drift_detection_required"),
                audit_receipts_required=local_mirror_policy.get("audit_receipts_required"),
                sensitivity_labels_required=local_mirror_policy.get("sensitivity_labels_required"),
                local_access_control_required=local_mirror_policy.get(
                    "local_access_control_required"
                ),
                encryption_at_rest_required=local_mirror_policy.get("encryption_at_rest_required"),
                server_side_apply_allowed=local_mirror_policy.get("server_side_apply_allowed"),
            )
        )
    raw_runtime_tools = manifest.get("runtime_tools")
    runtime_tools = raw_runtime_tools if isinstance(raw_runtime_tools, dict) else {}
    raw_required = runtime_tools.get("mcp_required")
    required = raw_required if isinstance(raw_required, list) else []
    raw_optional = runtime_tools.get("mcp_optional")
    optional = raw_optional if isinstance(raw_optional, list) else []
    checks.append(
        _agent_pack_check(
            "runtime_tools",
            "passed" if "sourcebrief.get_agent_context" in required else "failed",
            mcp_required=_redact_manifest_value(required),
            mcp_optional=_redact_manifest_value(optional),
            message=None
            if "sourcebrief.get_agent_context" in required
            else "manifest does not declare sourcebrief.get_agent_context as required",
        )
    )
    return checks


def cmd_agent_pack_doctor(
    client: Any,
    args: argparse.Namespace,
    *,
    remote_doctor: RemoteDoctor | None = None,
) -> Any:
    package = skill_install.load_package(Path(args.package))
    manifest = package.manifest
    checks: list[dict[str, Any]] = [
        _agent_pack_check(
            "package_integrity",
            "passed",
            package_hash=package.package_hash,
            file_count=len(package.files),
            package_kind=_redact_manifest_value(manifest.get("package_kind")),
            export_status=_redact_manifest_value(manifest.get("export_status")),
        ),
        *_agent_pack_manifest_checks(manifest),
    ]
    remote_result = None
    if args.query:
        if not args.workspace_id and manifest.get("workspace_id"):
            args.workspace_id = str(manifest.get("workspace_id"))
        if not args.project_id and manifest.get("project_id"):
            args.project_id = str(manifest.get("project_id"))
        args.require_citations = True
        if remote_doctor is None:
            raise RuntimeError("remote_doctor callback is required when --query is used")
        remote_result = remote_doctor(client, args)
        for check in remote_result.get("checks", []):
            if isinstance(check, dict):
                checks.append({**check, "name": f"remote_{check.get('name')}"})
    failed = [check for check in checks if check["status"] == "failed"]
    incomplete = [check for check in checks if check["status"] == "incomplete"]
    warnings = [check for check in checks if check["status"] == "warning"]
    return {
        "status": "failed"
        if failed
        else "incomplete"
        if incomplete
        else "warning"
        if warnings
        else "passed",
        "package": {
            "path": str(Path(args.package).expanduser()),
            "package_hash": package.package_hash,
            "pack_key": _redact_manifest_value(manifest.get("pack_key")),
            "pack_version": _redact_manifest_value(manifest.get("pack_version")),
            "mode": _redact_manifest_value(manifest.get("mode")),
        },
        "checks": checks,
        "remote_smoke": remote_result,
    }


def register_agent_pack_commands(
    subparsers: Any,
    *,
    doctor_command: CommandHandler,
) -> None:
    agent_packs = subparsers.add_parser(
        "agent-pack", help="Agent Pack package validation commands"
    ).add_subparsers(dest="agent_pack_command")
    agent_pack_doctor = agent_packs.add_parser(
        "doctor", help="validate a local Agent Pack package and optional remote smoke query"
    )
    agent_pack_doctor.add_argument(
        "--package", required=True, help="package directory or .zip from sourcebrief skill export"
    )
    agent_pack_doctor.add_argument(
        "--workspace", help="workspace name or slug; defaults to sourcebrief use selection"
    )
    agent_pack_doctor.add_argument(
        "--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection"
    )
    agent_pack_doctor.add_argument(
        "--project", help="project name; defaults to sourcebrief use selection"
    )
    agent_pack_doctor.add_argument(
        "--project-id", help="advanced: project ID; defaults to sourcebrief use selection"
    )
    agent_pack_doctor.add_argument("--query", help="optional MCP context smoke-test query")
    agent_pack_doctor.add_argument(
        "--runtime", default="hermes", choices=["api", "hermes", "claude", "codex", "cursor"]
    )
    agent_pack_doctor.add_argument("--resource-id", action="append")
    agent_pack_doctor.add_argument("--top-k", type=int, default=3)
    agent_pack_doctor.set_defaults(func=doctor_command)
