from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sourcebrief_cli import runtime_apply

DEFAULT_API_URL = "http://localhost:18000"
DEFAULT_EMAIL = "demo@example.com"
CONTEXT_RUNTIME_SCOPES = ["project:read", "project:query", "resource:read", "review:read"]
READ_CODE_RUNTIME_SCOPES = [*CONTEXT_RUNTIME_SCOPES, "code:read"]


class SourceBriefCliError(RuntimeError):
    """User-facing CLI error."""


class SourceBriefClient:
    def __init__(self, api_url: str, email: str, token: str | None = None, timeout: float = 30.0) -> None:
        self.api_url = api_url.rstrip("/")
        self.email = email
        self.token = token
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        expected: set[int] | None = None,
    ) -> Any:
        expected = expected or {200}
        data = None
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        else:
            headers["X-User-Email"] = self.email
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.api_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - user-provided API base is intentional CLI behavior
                payload = response.read()
                status = response.status
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SourceBriefCliError(
                f"{method} {path} failed with HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise SourceBriefCliError(f"failed to reach {self.api_url}: {exc.reason}") from exc
        if status not in expected:
            raise SourceBriefCliError(f"{method} {path} expected {sorted(expected)}, got {status}")
        if not payload:
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise SourceBriefCliError(f"{method} {path} returned non-JSON response") from exc


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def _print_kv(title: str, data: dict[str, Any], keys: list[str]) -> None:
    print(title)
    for key in keys:
        if key in data:
            print(f"  {key}: {data[key]}")


def _resource_ids(values: list[str] | None) -> list[str] | None:
    return values or None


def _split_csv_or_repeated(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    result: list[str] = []
    for value in values:
        result.extend(part.strip() for part in value.split(",") if part.strip())
    return result or None


def _config_path() -> Path:
    override = os.getenv("SOURCEBRIEF_CONFIG_PATH")
    if override:
        return Path(override).expanduser()
    config_home = os.getenv("XDG_CONFIG_HOME")
    if config_home:
        return Path(config_home).expanduser() / "sourcebrief" / "config.json"
    return Path.home() / ".config" / "sourcebrief" / "config.json"


def _load_cli_config() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SourceBriefCliError(f"invalid CLI config at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SourceBriefCliError(f"invalid CLI config at {path}: expected object")
    return data


def _save_cli_config(config: dict[str, Any]) -> Path:
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _selected_value(config: dict[str, Any], key: str) -> str | None:
    value = config.get(key)
    return value if isinstance(value, str) and value else None


def _command_uses_selected_scope(args: argparse.Namespace) -> bool:
    if args.command in {"ask", "search", "agent-context", "mcp-context", "doctor"}:
        return True
    if args.command == "resource" and getattr(args, "resource_command", None) == "list":
        return True
    return args.command == "runtime" and getattr(args, "runtime_command", None) == "setup"


def _apply_selected_defaults(args: argparse.Namespace, config: dict[str, Any]) -> None:
    if not _command_uses_selected_scope(args):
        return
    if "workspace_id" in args.__dict__ and not args.__dict__.get("workspace_id"):
        args.workspace_id = _selected_value(config, "workspace_id")
    if "project_id" in args.__dict__ and not args.__dict__.get("project_id"):
        args.project_id = _selected_value(config, "project_id")


def _resolve_api_url(args: argparse.Namespace, config: dict[str, Any]) -> None:
    env_api_url = os.getenv("SOURCEBRIEF_API_URL", os.getenv("CONTEXTSMITH_API_URL"))
    explicit_api_url = args.api_url is not None
    args._api_url_explicit = explicit_api_url
    args.api_url = args.api_url or env_api_url or _selected_value(config, "api_url") or DEFAULT_API_URL


def _require_scope(args: argparse.Namespace, *, workspace: bool = True, project: bool = True) -> None:
    missing: list[str] = []
    if workspace and "workspace_id" in args.__dict__ and not args.__dict__.get("workspace_id"):
        missing.append("--workspace-id")
    if project and "project_id" in args.__dict__ and not args.__dict__.get("project_id"):
        missing.append("--project-id")
    if missing:
        joined = " and ".join(missing)
        raise SourceBriefCliError(f"{joined} required; pass it explicitly or run sourcebrief use first")


def _wait_for_run(client: SourceBriefClient, workspace_id: str, index_run_id: str, timeout: int) -> dict[str, Any]:
    deadline = time.time() + timeout
    current: dict[str, Any] = {"status": "queued", "id": index_run_id}
    while time.time() < deadline:
        current = client.request("GET", f"/workspaces/{workspace_id}/index-runs/{index_run_id}")
        if current.get("status") in {"succeeded", "failed"}:
            break
        time.sleep(2)
    if current.get("status") != "succeeded":
        raise SourceBriefCliError(f"index run did not succeed before timeout: {current}")
    return current


def cmd_health(client: SourceBriefClient, _args: argparse.Namespace) -> Any:
    return client.request("GET", "/readyz")


def cmd_use(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    config = dict(getattr(args, "_sourcebrief_config", {}) or {})
    if args.clear:
        config.pop("workspace_id", None)
        config.pop("project_id", None)
    if args.workspace_id:
        config["workspace_id"] = args.workspace_id
        if not args.project_id and not args.clear:
            config.pop("project_id", None)
    if args.project_id:
        config["project_id"] = args.project_id
    if getattr(args, "_api_url_explicit", False) or "api_url" not in config:
        config["api_url"] = args.api_url.rstrip("/")
    path = _save_cli_config(config)
    return {
        "status": "saved",
        "config_path": str(path),
        "api_url": config.get("api_url"),
        "workspace_id": config.get("workspace_id"),
        "project_id": config.get("project_id"),
    }


def cmd_status(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    config = getattr(args, "_sourcebrief_config", {}) or {}
    return {
        "config_path": str(_config_path()),
        "api_url": args.api_url.rstrip("/"),
        "workspace_id": _selected_value(config, "workspace_id"),
        "project_id": _selected_value(config, "project_id"),
        "auth_mode": "bearer_token" if args.token else "email_header",
        "email": None if args.token else args.email,
        "token_set": bool(args.token),
    }


def _check_result(name: str, status: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "status": status, **extra}


def _mcp_error_message(response: Any) -> str | None:
    if not isinstance(response, dict):
        return "MCP response was not a JSON object"
    error = response.get("error")
    if error:
        return json.dumps(error, sort_keys=True) if isinstance(error, dict) else str(error)
    result = response.get("result")
    if isinstance(result, dict) and result.get("isError") is True:
        content = result.get("content")
        return "MCP tool returned isError=true" + (f": {content!r}" if content else "")
    return None


def cmd_doctor(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    checks: list[dict[str, Any]] = []
    try:
        health = client.request("GET", "/readyz")
        checks.append(_check_result("api", "passed", api_url=args.api_url.rstrip("/"), response=health))
    except SourceBriefCliError as exc:
        checks.append(_check_result("api", "failed", api_url=args.api_url.rstrip("/"), error=str(exc)))

    auth_mode = "bearer_token" if args.token else "email_header"
    checks.append(
        _check_result(
            "auth_mode",
            "info",
            mode=auth_mode,
            email=None if args.token else args.email,
            token_set=bool(args.token),
            message="auth mode selected; authenticated project/MCP checks below prove access",
        )
    )

    if args.workspace_id and args.project_id:
        try:
            resources = client.request("GET", f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources")
            checks.append(_check_result("project", "passed", workspace_id=args.workspace_id, project_id=args.project_id, resource_count=len(resources) if isinstance(resources, list) else None))
        except SourceBriefCliError as exc:
            checks.append(_check_result("project", "failed", workspace_id=args.workspace_id, project_id=args.project_id, error=str(exc)))
        if args.query:
            try:
                mcp = cmd_mcp_context(client, args)
                error = _mcp_error_message(mcp)
                if error:
                    checks.append(_check_result("mcp_context", "failed", query=args.query, error=error))
                else:
                    checks.append(_check_result("mcp_context", "passed", query=args.query, has_result=bool(mcp)))
            except SourceBriefCliError as exc:
                checks.append(_check_result("mcp_context", "failed", query=args.query, error=str(exc)))
    else:
        checks.append(
            _check_result(
                "project",
                "warning",
                message="workspace/project not selected; run `sourcebrief use --workspace-id ... --project-id ...` or pass IDs",
            )
        )

    failed = [check for check in checks if check["status"] == "failed"]
    warnings = [check for check in checks if check["status"] == "warning"]
    return {"status": "failed" if failed else "warning" if warnings else "passed", "checks": checks}


def cmd_workspace_create(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    return client.request(
        "POST",
        "/workspaces",
        body={"name": args.name, "slug": args.slug},
        expected={201},
    )


def cmd_project_create(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects",
        body={"name": args.name, "description": args.description},
        expected={201},
    )


def cmd_token_create(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/api-tokens",
        body={
            "name": args.name,
            "scopes": _split_csv_or_repeated(args.scope) or [],
            "allowed_project_ids": _split_csv_or_repeated(args.project_id),
            "allowed_resource_ids": _split_csv_or_repeated(args.resource_id),
            "expires_at": args.expires_at,
        },
        expected={201},
    )


def cmd_token_create_runtime(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    allowed_project_ids = _split_csv_or_repeated(args.project_id)
    allowed_resource_ids = _split_csv_or_repeated(args.resource_id)
    if not args.workspace_wide and not (allowed_project_ids or allowed_resource_ids):
        raise SourceBriefCliError(
            "token create-runtime requires --project-id/--resource-id or explicit --workspace-wide"
        )
    scopes = READ_CODE_RUNTIME_SCOPES if args.read_code else CONTEXT_RUNTIME_SCOPES
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/api-tokens",
        body={
            "name": args.name,
            "scopes": scopes,
            "allowed_project_ids": None if args.workspace_wide else allowed_project_ids,
            "allowed_resource_ids": None if args.workspace_wide else allowed_resource_ids,
            "expires_at": args.expires_at,
        },
        expected={201},
    )


def cmd_token_list(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    return client.request("GET", f"/workspaces/{args.workspace_id}/api-tokens")


def cmd_token_revoke(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    return client.request("DELETE", f"/workspaces/{args.workspace_id}/api-tokens/{args.token_id}")


def _maybe_refresh(client: SourceBriefClient, args: argparse.Namespace, resource: dict[str, Any]) -> dict[str, Any]:
    if not args.refresh:
        return {"resource": resource}
    run = client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{resource['id']}/refresh",
        expected={202},
    )
    result: dict[str, Any] = {"resource": resource, "index_run": run}
    if args.wait:
        result["index_run"] = _wait_for_run(client, args.workspace_id, run["id"], args.timeout)
    return result


def cmd_resource_add_doc(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    content = args.content
    if args.content_file:
        content = Path(args.content_file).read_text(encoding="utf-8")
    if not content:
        raise SourceBriefCliError("add-doc requires --content or --content-file")
    resource = client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources",
        body={
            "type": "markdown",
            "name": args.name,
            "uri": args.uri,
            "update_frequency": args.update_frequency,
            "source_config": {"content": content, "path": args.path, "title": args.title or args.name},
        },
        expected={201},
    )
    return _maybe_refresh(client, args, resource)


def cmd_resource_add_repo(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    source_config: dict[str, Any] = {"url": args.repo_url}
    if args.branch:
        source_config["branch"] = args.branch
    if args.max_files:
        source_config["max_repo_files"] = args.max_files
    if args.max_file_bytes:
        source_config["max_file_bytes"] = args.max_file_bytes
    if args.max_repo_bytes:
        source_config["max_repo_bytes"] = args.max_repo_bytes
    if args.clone_timeout:
        source_config["clone_timeout"] = args.clone_timeout
    resource = client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources",
        body={
            "type": "git",
            "name": args.name,
            "uri": args.repo_url,
            "update_frequency": args.update_frequency,
            "source_config": source_config,
        },
        expected={201},
    )
    return _maybe_refresh(client, args, resource)


def cmd_resource_add_url(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    source_config: dict[str, Any] = {"url": args.url}
    if args.title:
        source_config["title"] = args.title
    if args.max_url_bytes:
        source_config["max_url_bytes"] = args.max_url_bytes
    if args.fetch_timeout:
        source_config["fetch_timeout"] = args.fetch_timeout
    resource = client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources",
        body={
            "type": "url",
            "name": args.name,
            "uri": args.url,
            "update_frequency": args.update_frequency,
            "source_config": source_config,
        },
        expected={201},
    )
    return _maybe_refresh(client, args, resource)


def cmd_resource_add_upload(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    upload_path = Path(args.path)
    max_document_bytes = args.max_document_bytes or 5_000_000
    if upload_path.stat().st_size > max_document_bytes:
        raise SourceBriefCliError(f"upload file exceeds max_document_bytes={max_document_bytes}")
    content = upload_path.read_text(encoding=args.encoding)
    source_config: dict[str, Any] = {
        "filename": args.filename or Path(args.path).name,
        "content_type": args.content_type,
        "content": content,
        "max_document_bytes": max_document_bytes,
    }
    if args.title:
        source_config["title"] = args.title
    resource = client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources",
        body={
            "type": "upload",
            "name": args.name,
            "uri": f"upload://{source_config['filename']}",
            "update_frequency": args.update_frequency,
            "source_config": source_config,
        },
        expected={201},
    )
    return _maybe_refresh(client, args, resource)


def cmd_resource_refresh(client: SourceBriefClient, args: argparse.Namespace) -> Any:

    run = client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}/refresh",
        expected={202},
    )
    if args.wait:
        return _wait_for_run(client, args.workspace_id, run["id"], args.timeout)
    return run


def cmd_resource_list(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args)
    return client.request("GET", f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources")


def cmd_resource_restore(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}/restore",
    )


def cmd_resource_purge(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}/purge",
    )


def cmd_resource_schedule_due(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    query = f"limit={args.limit}"
    if args.dry_run:
        query += "&dry_run=true"
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/scheduled-refreshes?{query}",
        expected={202},
    )


def cmd_search(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args)
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/search",
        body={"query": args.query, "top_k": args.top_k, "resource_ids": _resource_ids(args.resource_id)},
    )


def cmd_agent_context(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args)
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/agent-context",
        body={
            "query": args.query,
            "runtime": args.runtime,
            "top_k": args.top_k,
            "resource_ids": _resource_ids(args.resource_id),
            "include_code_symbols": args.include_code_symbols,
            "max_chars": args.max_chars,
        },
    )


def cmd_mcp_context(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args)
    return client.request(
        "POST",
        f"/mcp/{args.workspace_id}/{args.project_id}",
        body={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "sourcebrief.get_agent_context",
                "arguments": {
                    "query": args.query,
                    "runtime": args.runtime,
                    "top_k": args.top_k,
                    "resource_ids": _resource_ids(args.resource_id),
                },
            },
        },
    )


def _runtime_plan_request(client: SourceBriefClient, args: argparse.Namespace) -> dict[str, Any]:
    _require_scope(args)
    plan = client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/runtime-install-plan",
        body={
            "target": args.target,
            "public_api_url": args.public_api_url,
            "server_name": args.server_name,
            "resource_ids": _resource_ids(args.resource_id),
            "include_optional_tools": args.include_optional_tools,
        },
    )
    return runtime_apply.attach_plan_metadata(plan)


def cmd_runtime_plan(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    return _runtime_plan_request(client, args)


def _validation_preview(plan: dict[str, Any], target: str, max_age_seconds: int) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(plan, handle)
        path = Path(handle.name)
    try:
        validation = runtime_apply.read_plan(path, target=target, max_age_seconds=max_age_seconds)
        return runtime_apply.validate_plan(validation, run=False)
    finally:
        path.unlink(missing_ok=True)


def _runtime_token_command(plan: dict[str, Any]) -> str:
    parts = [
        "sourcebrief",
        "token",
        "create-runtime",
        "--workspace-id",
        sh_quote(str(plan.get("workspace_id") or "<workspace-id>")),
    ]
    if "code:read" in (plan.get("required_scopes") or []):
        parts.append("--read-code")
    else:
        parts.append("--context-only")
    project_id = plan.get("project_id")
    if project_id:
        parts.extend(["--project-id", sh_quote(str(project_id))])
    resources = (plan.get("resource_scope") or {}).get("resources") or []
    for resource_id in resources:
        parts.extend(["--resource-id", sh_quote(str(resource_id))])
    return " ".join(parts)


def sh_quote(value: str) -> str:
    return shlex.quote(value)


def cmd_runtime_setup(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    plan = _runtime_plan_request(client, args)
    validation = _validation_preview(plan, args.target, args.max_age_seconds)
    if args.plan_out:
        out = Path(args.plan_out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        plan_path: str | None = str(out)
    else:
        plan_path = None
    plan_ref = plan_path or "<save first with: sourcebrief runtime setup hermes --plan-out plan.json>"
    return {
        "status": "dry_run_ready",
        "target": args.target,
        "workspace_id": plan.get("workspace_id"),
        "project_id": plan.get("project_id"),
        "server_name": plan.get("server_name"),
        "plan_path": plan_path,
        "plan": plan,
        "validation": validation,
        "token_command": _runtime_token_command(plan),
        "next_steps": [
            "Review the plan and generated MCP config.",
            f"Create/export a runtime token: {_runtime_token_command(plan)}",
            f"Run `sourcebrief runtime validate --plan {plan_ref} --run` after exporting SOURCEBRIEF_TOKEN.",
            f"Apply only with `sourcebrief runtime apply --plan {plan_ref} --target hermes --apply` when ready.",
        ],
    }


def _read_validated_runtime_plan(args: argparse.Namespace) -> runtime_apply.PlanValidation:
    return runtime_apply.read_plan(
        Path(args.plan),
        target=args.target,
        max_age_seconds=args.max_age_seconds,
    )


def cmd_runtime_detect(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    return runtime_apply.detect(runtime_apply.hermes_config_path(args.config))


def cmd_runtime_apply(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    validation = _read_validated_runtime_plan(args)
    config_path = runtime_apply.hermes_config_path(args.config)
    if args.dry_run:
        if args.apply or args.yes:
            raise SourceBriefCliError("runtime apply accepts only one of --dry-run or --apply/--yes")
        return runtime_apply.dry_run_apply(validation, config_path)
    if not (args.apply or args.yes):
        raise SourceBriefCliError("runtime apply requires --dry-run or explicit --apply")
    return runtime_apply.apply_plan(validation, config_path, runtime_apply.receipt_path(args.receipt))


def cmd_runtime_rollback(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    return runtime_apply.rollback(Path(args.receipt), force=args.force)


def cmd_runtime_validate(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    validation = _read_validated_runtime_plan(args)
    return runtime_apply.validate_plan(validation, run=args.run)


def cmd_agent_list(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    return client.request("GET", f"/workspaces/{args.workspace_id}/agents")


def cmd_agent_profile(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    return client.request(
        "GET",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/agent-profile",
    )


def cmd_resource_graph(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    return client.request(
        "GET",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}/graph?limit={args.limit}",
    )


def _add_common_resource_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--update-frequency", default="manual")
    parser.add_argument("--refresh", action="store_true", help="refresh after creating the resource")
    parser.add_argument("--wait", action="store_true", help="wait for refresh completion")
    parser.add_argument("--timeout", type=int, default=120, help="seconds to wait for refresh")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sourcebrief", description="SourceBrief CLI")
    parser.add_argument(
        "--api-url",
        default=None,
        help="SourceBrief API URL; overrides SOURCEBRIEF_API_URL and saved sourcebrief use config",
    )
    parser.add_argument(
        "--email",
        default=os.getenv("SOURCEBRIEF_EMAIL", os.getenv("CONTEXTSMITH_EMAIL", DEFAULT_EMAIL)),
    )
    parser.add_argument(
        "--token",
        default=os.getenv("SOURCEBRIEF_TOKEN", os.getenv("CONTEXTSMITH_TOKEN")),
        help="Bearer API token; overrides --email dev auth",
    )
    parser.add_argument("--json", action="store_true", help="print full JSON response")
    parser.set_defaults(func=None)

    sub = parser.add_subparsers(dest="command")

    health = sub.add_parser("health", help="check API readiness")
    health.set_defaults(func=cmd_health)

    use = sub.add_parser(
        "use",
        help="save default workspace/project for later read/query commands",
        description=f"Save CLI defaults in {_config_path()}. Explicit flags still override saved values.",
    )
    use.add_argument("--workspace-id", help="workspace ID to save; changing it without --project-id clears the saved project")
    use.add_argument("--project-id", help="project ID to save")
    use.add_argument("--clear", action="store_true", help="clear saved workspace/project before applying new values")
    use.set_defaults(func=cmd_use)

    status = sub.add_parser("status", help="show selected CLI defaults and auth mode without secrets")
    status.set_defaults(func=cmd_status)

    doctor = sub.add_parser("doctor", help="check API/auth/project/MCP readiness")
    doctor.add_argument("--workspace-id", help="workspace ID; defaults to sourcebrief use selection")
    doctor.add_argument("--project-id", help="project ID; defaults to sourcebrief use selection")
    doctor.add_argument("--query", help="optional MCP context smoke-test query")
    doctor.add_argument("--runtime", default="api", choices=["api", "hermes", "claude", "codex", "cursor"])
    doctor.add_argument("--resource-id", action="append")
    doctor.add_argument("--top-k", type=int, default=3)
    doctor.set_defaults(func=cmd_doctor)

    ws = sub.add_parser("workspace", help="workspace commands").add_subparsers(dest="workspace_command")
    ws_create = ws.add_parser("create", help="create a workspace")
    ws_create.add_argument("--name", required=True)
    ws_create.add_argument("--slug", required=True)
    ws_create.set_defaults(func=cmd_workspace_create)

    projects = sub.add_parser("project", help="project commands").add_subparsers(dest="project_command")
    project_create = projects.add_parser("create", help="create a project")
    project_create.add_argument("--workspace-id", required=True)
    project_create.add_argument("--name", required=True)
    project_create.add_argument("--description")
    project_create.set_defaults(func=cmd_project_create)

    tokens = sub.add_parser("token", help="workspace API token commands").add_subparsers(dest="token_command")
    token_create = tokens.add_parser("create", help="create a bearer API token for agents/Hermes")
    token_create.add_argument("--workspace-id", required=True)
    token_create.add_argument("--name", required=True)
    token_create.add_argument("--scope", action="append", required=True, help="scope, repeatable or comma-separated")
    token_create.add_argument("--project-id", action="append", help="allowed project ID, repeatable or comma-separated")
    token_create.add_argument("--resource-id", action="append", help="allowed resource ID, repeatable or comma-separated")
    token_create.add_argument("--expires-at", help="ISO-8601 timestamp")
    token_create.set_defaults(func=cmd_token_create)

    token_runtime = tokens.add_parser("create-runtime", help="create a preset runtime token")
    token_runtime.add_argument("--workspace-id", required=True)
    token_runtime.add_argument("--name", default="SourceBrief runtime")
    preset = token_runtime.add_mutually_exclusive_group()
    preset.add_argument("--context-only", dest="read_code", action="store_false", help="project/query/resource/review read scopes only")
    preset.add_argument("--read-code", dest="read_code", action="store_true", help="include code:read for source drill-down tools")
    token_runtime.add_argument("--project-id", action="append", help="allowed project ID, repeatable or comma-separated")
    token_runtime.add_argument("--resource-id", action="append", help="allowed resource ID, repeatable or comma-separated")
    token_runtime.add_argument("--workspace-wide", action="store_true", help="explicitly allow this runtime token across the whole workspace")
    token_runtime.add_argument("--expires-at", help="ISO-8601 timestamp")
    token_runtime.set_defaults(func=cmd_token_create_runtime, read_code=False)

    token_list = tokens.add_parser("list", help="list API tokens without plaintext secrets")
    token_list.add_argument("--workspace-id", required=True)
    token_list.set_defaults(func=cmd_token_list)

    token_revoke = tokens.add_parser("revoke", help="revoke an API token")
    token_revoke.add_argument("--workspace-id", required=True)
    token_revoke.add_argument("--token-id", required=True)
    token_revoke.set_defaults(func=cmd_token_revoke)

    resources = sub.add_parser("resource", help="resource commands").add_subparsers(dest="resource_command")
    add_doc = resources.add_parser("add-doc", help="add a markdown/document resource")
    _add_common_resource_args(add_doc)
    add_doc.add_argument("--uri", required=True)
    add_doc.add_argument("--content")
    add_doc.add_argument("--content-file")
    add_doc.add_argument("--path")
    add_doc.add_argument("--title")
    add_doc.set_defaults(func=cmd_resource_add_doc)

    add_repo = resources.add_parser("add-repo", help="add a git repository resource")
    _add_common_resource_args(add_repo)
    add_repo.add_argument("--repo-url", required=True, help="public https git URL, or local file URL when the worker allows local git")
    add_repo.add_argument("--branch")
    add_repo.add_argument("--max-files", type=int)
    add_repo.add_argument("--max-file-bytes", type=int)
    add_repo.add_argument("--max-repo-bytes", type=int)
    add_repo.add_argument("--clone-timeout", type=int)
    add_repo.set_defaults(func=cmd_resource_add_repo)

    add_url = resources.add_parser("add-url", help="add a public HTTP(S) URL resource")
    _add_common_resource_args(add_url)
    add_url.add_argument("--url", required=True)
    add_url.add_argument("--title")
    add_url.add_argument("--max-url-bytes", type=int)
    add_url.add_argument("--fetch-timeout", type=int)
    add_url.set_defaults(func=cmd_resource_add_url)

    add_upload = resources.add_parser("add-upload", help="add an uploaded text/markdown resource from a local file")
    _add_common_resource_args(add_upload)
    add_upload.add_argument("--path", required=True)
    add_upload.add_argument("--filename")
    add_upload.add_argument("--title")
    add_upload.add_argument("--content-type", default="text/plain")
    add_upload.add_argument("--encoding", default="utf-8")
    add_upload.add_argument("--max-document-bytes", type=int)
    add_upload.set_defaults(func=cmd_resource_add_upload)

    refresh = resources.add_parser("refresh", help="refresh a resource")
    refresh.add_argument("--workspace-id", required=True)
    refresh.add_argument("--project-id", required=True)
    refresh.add_argument("--resource-id", required=True)
    refresh.add_argument("--wait", action="store_true")
    refresh.add_argument("--timeout", type=int, default=120)
    refresh.set_defaults(func=cmd_resource_refresh)

    list_resources = resources.add_parser("list", help="list resources")
    list_resources.add_argument("--workspace-id")
    list_resources.add_argument("--project-id")
    list_resources.set_defaults(func=cmd_resource_list)

    restore = resources.add_parser("restore", help="restore an archived or soft-deleted resource")
    restore.add_argument("--workspace-id", required=True)
    restore.add_argument("--project-id", required=True)
    restore.add_argument("--resource-id", required=True)
    restore.set_defaults(func=cmd_resource_restore)

    purge = resources.add_parser("purge", help="hard purge a soft-deleted resource and artifacts")
    purge.add_argument("--workspace-id", required=True)
    purge.add_argument("--project-id", required=True)
    purge.add_argument("--resource-id", required=True)
    purge.set_defaults(func=cmd_resource_purge)

    schedule = resources.add_parser("schedule-due", help="enqueue due scheduled refreshes for a project")
    schedule.add_argument("--workspace-id", required=True)
    schedule.add_argument("--project-id", required=True)
    schedule.add_argument("--limit", type=int, default=100)
    schedule.add_argument("--dry-run", action="store_true")
    schedule.set_defaults(func=cmd_resource_schedule_due)

    graph = resources.add_parser("graph", help="show a resource graph index")
    graph.add_argument("--workspace-id", required=True)
    graph.add_argument("--project-id", required=True)
    graph.add_argument("--resource-id", required=True)
    graph.add_argument("--limit", type=int, default=50)
    graph.set_defaults(func=cmd_resource_graph)

    agents = sub.add_parser("agent", help="agent registry commands").add_subparsers(dest="agent_command")
    agent_list = agents.add_parser("list", help="list project agents in a workspace")
    agent_list.add_argument("--workspace-id", required=True)
    agent_list.set_defaults(func=cmd_agent_list)

    agent_profile = agents.add_parser("profile", help="show one project agent profile")
    agent_profile.add_argument("--workspace-id", required=True)
    agent_profile.add_argument("--project-id", required=True)
    agent_profile.set_defaults(func=cmd_agent_profile)

    search = sub.add_parser("search", help="search project context")
    search.add_argument("--workspace-id")
    search.add_argument("--project-id")
    search.add_argument("--query", required=True)
    search.add_argument("--resource-id", action="append")
    search.add_argument("--top-k", type=int, default=10)
    search.set_defaults(func=cmd_search)

    ask = sub.add_parser(
        "ask",
        help="ask SourceBrief for cited project context",
        description="Ask SourceBrief for cited context. Workspace/project can come from explicit flags or `sourcebrief use`.",
    )
    ask.add_argument("query", help="question to answer from cited project evidence")
    ask.add_argument("--workspace-id", help="workspace ID; overrides saved sourcebrief use value")
    ask.add_argument("--project-id", help="project ID; overrides saved sourcebrief use value")
    ask.add_argument("--runtime", default="api", choices=["api", "hermes", "claude", "codex", "cursor"])
    ask.add_argument("--resource-id", action="append")
    ask.add_argument("--top-k", type=int, default=8)
    ask.add_argument("--max-chars", type=int, default=12000)
    ask.add_argument("--no-code-symbols", dest="include_code_symbols", action="store_false")
    ask.set_defaults(func=cmd_agent_context, include_code_symbols=True)

    agent = sub.add_parser("agent-context", help="request runtime-shaped context")
    agent.add_argument("--workspace-id")
    agent.add_argument("--project-id")
    agent.add_argument("--query", required=True)
    agent.add_argument("--runtime", default="api", choices=["api", "hermes", "claude", "codex", "cursor"])
    agent.add_argument("--resource-id", action="append")
    agent.add_argument("--top-k", type=int, default=8)
    agent.add_argument("--max-chars", type=int, default=12000)
    agent.add_argument("--no-code-symbols", dest="include_code_symbols", action="store_false")
    agent.set_defaults(func=cmd_agent_context, include_code_symbols=True)

    mcp = sub.add_parser("mcp-context", help="call the central MCP context tool")
    mcp.add_argument("--workspace-id")
    mcp.add_argument("--project-id")
    mcp.add_argument("--query", required=True)
    mcp.add_argument("--runtime", default="api", choices=["api", "hermes", "claude", "codex", "cursor"])
    mcp.add_argument("--resource-id", action="append")
    mcp.add_argument("--top-k", type=int, default=8)
    mcp.set_defaults(func=cmd_mcp_context)

    runtime = sub.add_parser("runtime", help="agent runtime install and validation commands").add_subparsers(dest="runtime_command")
    runtime_plan = runtime.add_parser("plan", help="generate a dry-run runtime install plan")
    runtime_plan.add_argument("--workspace-id", required=True)
    runtime_plan.add_argument("--project-id", required=True)
    runtime_plan.add_argument("--target", required=True, choices=["hermes", "claude", "codex"])
    runtime_plan.add_argument("--public-api-url")
    runtime_plan.add_argument("--server-name")
    runtime_plan.add_argument("--resource-id", action="append")
    runtime_plan.add_argument("--no-optional-tools", dest="include_optional_tools", action="store_false")
    runtime_plan.set_defaults(func=cmd_runtime_plan, include_optional_tools=True)

    runtime_setup = runtime.add_parser("setup", help="guided dry-run runtime setup; never writes local config")
    runtime_setup.add_argument("target", choices=["hermes"])
    runtime_setup.add_argument("--workspace-id", help="workspace ID; defaults to sourcebrief use selection")
    runtime_setup.add_argument("--project-id", help="project ID; defaults to sourcebrief use selection")
    runtime_setup.add_argument("--public-api-url")
    runtime_setup.add_argument("--server-name")
    runtime_setup.add_argument("--resource-id", action="append")
    runtime_setup.add_argument("--no-optional-tools", dest="include_optional_tools", action="store_false")
    runtime_setup.add_argument("--dry-run", action="store_true", help="accepted for clarity; setup is always dry-run and never applies config")
    runtime_setup.add_argument("--plan-out", help="write the generated plan JSON to this path")
    runtime_setup.add_argument("--max-age-seconds", type=int, default=86400)
    runtime_setup.set_defaults(func=cmd_runtime_setup, include_optional_tools=True)

    runtime_detect = runtime.add_parser("detect", help="detect local runtime config paths without writing files")
    runtime_detect.add_argument("--config", help="Hermes config path; defaults to ~/.hermes/config.yaml")
    runtime_detect.set_defaults(func=cmd_runtime_detect)

    runtime_apply_parser = runtime.add_parser("apply", help="apply a validated runtime plan to Hermes config")
    runtime_apply_parser.add_argument("--plan", required=True, help="runtime plan JSON produced by sourcebrief runtime plan")
    runtime_apply_parser.add_argument("--target", required=True, choices=["hermes"])
    runtime_apply_parser.add_argument("--config", help="Hermes config path; defaults to ~/.hermes/config.yaml")
    runtime_apply_parser.add_argument("--receipt", help="receipt output path")
    runtime_apply_parser.add_argument("--dry-run", action="store_true", help="show planned writes without changing files")
    runtime_apply_parser.add_argument("--apply", action="store_true", help="perform the local config write after plan validation")
    runtime_apply_parser.add_argument("--yes", action="store_true", help="deprecated alias for --apply")
    runtime_apply_parser.add_argument("--max-age-seconds", type=int, default=86400, help="reject plans older than this; use -1 to disable")
    runtime_apply_parser.set_defaults(func=cmd_runtime_apply)

    runtime_rollback = runtime.add_parser("rollback", help="rollback a SourceBrief runtime apply receipt")
    runtime_rollback.add_argument("--receipt", required=True)
    runtime_rollback.add_argument("--force", action="store_true", help="restore even when current hash differs from receipt")
    runtime_rollback.set_defaults(func=cmd_runtime_rollback)

    runtime_validate = runtime.add_parser("validate", help="show or run the validator command from a runtime plan")
    runtime_validate.add_argument("--plan", required=True)
    runtime_validate.add_argument("--target", default="hermes", choices=["hermes"])
    runtime_validate.add_argument("--run", action="store_true", help="execute the generated validator command")
    runtime_validate.add_argument("--max-age-seconds", type=int, default=86400)
    runtime_validate.set_defaults(func=cmd_runtime_validate)

    return parser


def _print_default(command: str | None, data: Any) -> None:
    if isinstance(data, dict):
        if "resource" in data and isinstance(data["resource"], dict):
            _print_kv("Resource", data["resource"], ["id", "name", "type", "uri", "status"])
            if "index_run" in data:
                _print_kv("Index run", data["index_run"], ["id", "status", "documents_seen", "chunks_created", "symbols_created", "embeddings_created"])
            return
        if command in {"workspace", "project", "health"}:
            _print_kv(command.title() if command else "Result", data, ["id", "name", "slug", "workspace_id", "status"])
            return
        if command == "search":
            print(f"Search: {data.get('query')} ({data.get('count', 0)} hits)")
            for hit in data.get("hits", []):
                print(f"- {hit.get('path') or hit.get('title') or hit.get('resource_id')}: {hit.get('snippet')}")
            return
        if command == "runtime" and data.get("status") == "dry_run_ready":
            print("Runtime setup: dry-run ready")
            print(f"  target: {data.get('target')}")
            print(f"  workspace_id: {data.get('workspace_id')}")
            print(f"  project_id: {data.get('project_id')}")
            print(f"  server_name: {data.get('server_name')}")
            print(f"  plan_path: {data.get('plan_path') or '(not saved; rerun with --plan-out plan.json)'}")
            print(f"  validation: {(data.get('validation') or {}).get('status')}")
            print(f"  token_command: {data.get('token_command')}")
            print("Next steps:")
            for step in data.get("next_steps", []):
                print(f"- {step}")
            return
        if command in {"agent-context", "mcp-context", "ask", "agent", "token", "runtime", "use", "status", "doctor"}:
            _print_json(data)
            return
    _print_json(data)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.func is None:
        parser.print_help(sys.stderr)
        return 2
    try:
        try:
            config = _load_cli_config()
        except SourceBriefCliError:
            if args.command == "use" and getattr(args, "clear", False):
                config = {}
            else:
                raise
        args._sourcebrief_config = config
        _resolve_api_url(args, config)
        _apply_selected_defaults(args, config)
    except SourceBriefCliError as exc:
        print(f"sourcebrief: error: {exc}", file=sys.stderr)
        return 1
    client = SourceBriefClient(args.api_url, args.email, token=args.token)
    try:
        data = args.func(client, args)
    except (SourceBriefCliError, runtime_apply.RuntimeApplyError) as exc:
        print(f"sourcebrief: error: {exc}", file=sys.stderr)
        return 1
    exit_code = 1 if args.command == "doctor" and isinstance(data, dict) and data.get("status") == "failed" else 0
    if args.json:
        _print_json(data)
    else:
        _print_default(args.command, data)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
