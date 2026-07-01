from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import shlex
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import dotenv_values

from sourcebrief_cli import runtime_apply, skill_install
from sourcebrief_shared.github_pr_review import (
    GitHubPRBundleError,
    build_review_bundle_from_github_pr_metadata,
    fetch_github_pr_metadata,
    load_pr_metadata_fixture,
)
from sourcebrief_shared.regression_proposal import (
    RegressionProposalError,
    load_reviewer_report,
    proposal_from_finding,
    select_finding,
    write_regression_proposal,
)
from sourcebrief_shared.review_bundle import (
    build_review_bundle_from_agent_context,
    write_review_bundle,
)
from sourcebrief_shared.review_history import scan_review_history, show_review_history_record
from sourcebrief_shared.review_runner import (
    ReviewRunnerError,
    ReviewRunOptions,
    run_review_bundle_path,
    write_reviewer_report,
)
from sourcebrief_shared.self_improvement_mvp import run_mvp_smoke_path
from sourcebrief_shared.self_improvement_sleep import (
    SleepReplayError,
    run_sleep_replay,
    write_sleep_replay_summary,
)
from sourcebrief_shared.staged_adoption import stage_regression_proposal
from sourcebrief_shared.validation_gate import (
    validate_regression_proposal_file,
    write_validation_gate_result,
)

DEFAULT_API_URL = "http://localhost:18000"
DEFAULT_EMAIL = "demo@example.com"
SESSION_TOKEN_CONFIG_KEY = "session_token"
SESSION_EMAIL_CONFIG_KEY = "session_email"
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


def _resource_refs(args: argparse.Namespace) -> list[str] | None:
    values = getattr(args, "resource", None) or []
    return values or None


def _apply_resource_refs(body: dict[str, Any], args: argparse.Namespace) -> None:
    refs = _resource_refs(args)
    if not refs:
        return
    if len(refs) == 1:
        body["resource_ref"] = refs[0]
    else:
        body["resource_refs"] = refs


def _split_csv_or_repeated(values: str | list[str] | None) -> list[str] | None:
    if not values:
        return None
    raw_values = [values] if isinstance(values, str) else values
    result: list[str] = []
    for value in raw_values:
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
    payload = json.dumps(config, indent=2, sort_keys=True) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        temp_path.chmod(0o600)
        os.replace(temp_path, path)
        path.chmod(0o600)
    finally:
        temp_path.unlink(missing_ok=True)
    return path


def _selected_value(config: dict[str, Any], key: str) -> str | None:
    value = config.get(key)
    return value if isinstance(value, str) and value else None


def _casefold(value: str) -> str:
    return value.strip().casefold()


def _matches_workspace_selector(workspace: dict[str, Any], selector: str) -> bool:
    wanted = _casefold(selector)
    return wanted in {
        _casefold(str(workspace.get("id") or "")),
        _casefold(str(workspace.get("name") or "")),
        _casefold(str(workspace.get("slug") or "")),
    }


def _matches_project_selector(project: dict[str, Any], selector: str) -> bool:
    wanted = _casefold(selector)
    return wanted in {
        _casefold(str(project.get("id") or "")),
        _casefold(str(project.get("name") or "")),
    }


def _workspace_candidate(workspace: dict[str, Any]) -> str:
    return f"{workspace.get('name')} (slug={workspace.get('slug')}, id={workspace.get('id')})"


def _project_candidate(project: dict[str, Any]) -> str:
    return f"{project.get('name')} (id={project.get('id')})"


def _resolve_workspace_selector(client: SourceBriefClient, selector: str) -> dict[str, Any]:
    workspaces = client.request("GET", "/workspaces")
    if not isinstance(workspaces, list):
        raise SourceBriefCliError("workspace resolver expected /workspaces to return a list")
    matches = [workspace for workspace in workspaces if isinstance(workspace, dict) and _matches_workspace_selector(workspace, selector)]
    if not matches:
        raise SourceBriefCliError(f"workspace {selector!r} was not found or is not accessible")
    if len(matches) > 1:
        choices = "; ".join(_workspace_candidate(workspace) for workspace in matches)
        raise SourceBriefCliError(f"workspace {selector!r} is ambiguous; choose one of: {choices}")
    return matches[0]


def _resolve_project_selector(client: SourceBriefClient, workspace_id: str, selector: str) -> dict[str, Any]:
    projects = client.request("GET", f"/workspaces/{workspace_id}/projects")
    if not isinstance(projects, list):
        raise SourceBriefCliError("project resolver expected /projects to return a list")
    matches = [project for project in projects if isinstance(project, dict) and _matches_project_selector(project, selector)]
    if not matches:
        raise SourceBriefCliError(f"project {selector!r} was not found or is not accessible in the selected workspace")
    if len(matches) > 1:
        choices = "; ".join(_project_candidate(project) for project in matches)
        raise SourceBriefCliError(f"project {selector!r} is ambiguous in the selected workspace; choose one of: {choices}")
    return matches[0]


def _resolve_named_scope(client: SourceBriefClient, args: argparse.Namespace, config: dict[str, Any]) -> None:
    workspace_selector = getattr(args, "workspace", None)
    project_selector = getattr(args, "project", None)
    project_refs = getattr(args, "project_ref", None)
    if not (workspace_selector or project_selector or project_refs):
        return
    if workspace_selector and getattr(args, "workspace_id", None):
        raise SourceBriefCliError("use either --workspace or --workspace-id, not both")
    if project_selector and getattr(args, "project_id", None):
        raise SourceBriefCliError("use either --project or --project-id, not both")
    if workspace_selector:
        workspace = _resolve_workspace_selector(client, workspace_selector)
        args.workspace_id = str(workspace["id"])
        args._resolved_workspace_name = workspace.get("name")
        args._resolved_workspace_slug = workspace.get("slug")
    elif not getattr(args, "workspace_id", None):
        saved_workspace_id = _selected_value(config, "workspace_id")
        if saved_workspace_id:
            args.workspace_id = saved_workspace_id
    if project_selector:
        if not getattr(args, "workspace_id", None):
            raise SourceBriefCliError("--project requires --workspace or a saved workspace selection")
        project = _resolve_project_selector(client, str(args.workspace_id), project_selector)
        args.project_id = str(project["id"])
        args._resolved_project_name = project.get("name")
    if project_refs:
        if not getattr(args, "workspace_id", None):
            raise SourceBriefCliError("--project requires --workspace or a saved workspace selection")
        resolved_project_ids = list(getattr(args, "project_id", None) or [])
        for selector in project_refs:
            project = _resolve_project_selector(client, str(args.workspace_id), selector)
            resolved_project_ids.append(str(project["id"]))
        args.project_id = resolved_project_ids


def _dotenv_path() -> Path:
    override = os.getenv("SOURCEBRIEF_DOTENV_PATH")
    return Path(override).expanduser() if override else Path(".env")


def _dotenv_value(name: str) -> str | None:
    path = _dotenv_path()
    if not path.exists():
        return None
    value = dotenv_values(path).get(name)
    return value if isinstance(value, str) and value else None


def _first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    for name in names:
        value = _dotenv_value(name)
        if value:
            return value
    return None


def _env_login_email(args: argparse.Namespace) -> str | None:
    explicit_email = getattr(args, "email", None) if getattr(args, "_email_explicit", False) else None
    return explicit_email or _first_env(
        "SOURCEBRIEF_ADMIN_EMAIL",
        "SOURCEBRIEF_EMAIL",
        "CONTEXTSMITH_ADMIN_EMAIL",
        "CONTEXTSMITH_EMAIL",
    ) or getattr(args, "email", None)


def _env_login_password() -> str | None:
    return _first_env(
        "SOURCEBRIEF_ADMIN_PASSWORD",
        "SOURCEBRIEF_PASSWORD",
        "CONTEXTSMITH_ADMIN_PASSWORD",
        "CONTEXTSMITH_PASSWORD",
    )


def _resolve_auth(args: argparse.Namespace, config: dict[str, Any]) -> None:
    args._auth_mode = "email_header"
    args._session_email = None
    args._session_login_password = None
    if args.token:
        args._auth_mode = "bearer_token"
        return
    saved_session = _selected_value(config, SESSION_TOKEN_CONFIG_KEY)
    if saved_session:
        args.token = saved_session
        args._auth_mode = "saved_session"
        args._session_email = _selected_value(config, SESSION_EMAIL_CONFIG_KEY)
        return
    password = _env_login_password()
    if password:
        args._auth_mode = "session_login_env"
        args._session_email = _env_login_email(args)
        args._session_login_password = password


def _login_with_password(client: SourceBriefClient, email: str, password: str) -> str:
    login = client.request("POST", "/auth/login", body={"email": email, "password": password})
    session_token = login.get("session_token") if isinstance(login, dict) else None
    if not isinstance(session_token, str) or not session_token:
        raise SourceBriefCliError("/auth/login response did not include session_token")
    return session_token


def _agent_pack_doctor_package_only(args: argparse.Namespace) -> bool:
    return args.command == "agent-pack" and getattr(args, "agent_pack_command", None) == "doctor" and not getattr(args, "query", None)


def _command_uses_authenticated_api(args: argparse.Namespace) -> bool:
    if args.command == "use":
        return bool(getattr(args, "workspace", None) or getattr(args, "project", None))
    if args.command in {"health", "status", "login", "logout", "review"}:
        return False
    if args.command == "runtime" and getattr(args, "runtime_command", None) in {"detect", "apply", "rollback", "validate"}:
        return False
    if _agent_pack_doctor_package_only(args):
        return False
    return True


def _maybe_session_login(client: SourceBriefClient, args: argparse.Namespace) -> None:
    if getattr(args, "_auth_mode", None) != "session_login_env":
        return
    if not _command_uses_authenticated_api(args):
        return
    email = getattr(args, "_session_email", None) or args.email
    password = getattr(args, "_session_login_password", None)
    if not password:
        return
    client.token = _login_with_password(client, email, password)
    args.token = client.token


def _command_uses_selected_scope(args: argparse.Namespace) -> bool:
    if args.command in {"ask", "search", "agent-context", "mcp-context", "doctor"}:
        return True
    if args.command == "agent-pack" and getattr(args, "agent_pack_command", None) == "doctor":
        return True
    if args.command == "project" and getattr(args, "project_command", None) == "create":
        return True
    if args.command == "token" and getattr(args, "token_command", None) in {"create", "create-runtime", "list", "revoke"}:
        return True
    if args.command == "agent" and getattr(args, "agent_command", None) in {"list", "profile"}:
        return True
    if args.command == "skill" and getattr(args, "skill_command", None) == "export":
        return True
    if args.command == "resource" and getattr(args, "resource_command", None) in {
        "add-doc",
        "add-repo",
        "add-upload",
        "add-url",
        "archive",
        "delete",
        "get",
        "list",
        "refresh",
        "restore",
        "purge",
        "schedule-due",
        "graph",
        "update",
        "update-git",
    }:
        return True
    return args.command == "runtime" and getattr(args, "runtime_command", None) in {"plan", "setup"}


def _apply_selected_defaults(args: argparse.Namespace, config: dict[str, Any]) -> None:
    if not _command_uses_selected_scope(args):
        return
    workspace_id_explicit = bool(args.__dict__.get("workspace_id"))
    if "workspace_id" in args.__dict__ and not args.__dict__.get("workspace_id") and not getattr(args, "workspace", None):
        args.workspace_id = _selected_value(config, "workspace_id")
    if (
        "project_id" in args.__dict__
        and not args.__dict__.get("project_id")
        and args.command != "token"
        and not workspace_id_explicit
        and not getattr(args, "workspace", None)
        and not getattr(args, "project", None)
        and not getattr(args, "project_ref", None)
    ):
        args.project_id = _selected_value(config, "project_id")


def _resolve_api_url(args: argparse.Namespace, config: dict[str, Any]) -> None:
    env_api_url = os.getenv("SOURCEBRIEF_API_URL", os.getenv("CONTEXTSMITH_API_URL"))
    explicit_api_url = args.api_url is not None
    args._api_url_explicit = explicit_api_url
    args.api_url = args.api_url or env_api_url or _selected_value(config, "api_url") or DEFAULT_API_URL


def _resolve_email(args: argparse.Namespace) -> None:
    args._email_explicit = args.email is not None
    args.email = args.email or _first_env("SOURCEBRIEF_EMAIL", "CONTEXTSMITH_EMAIL") or DEFAULT_EMAIL


def _require_scope(args: argparse.Namespace, *, workspace: bool = True, project: bool = True) -> None:
    missing: list[str] = []
    if workspace and "workspace_id" in args.__dict__ and not args.__dict__.get("workspace_id"):
        missing.append("--workspace / --workspace-id")
    if project and "project_id" in args.__dict__ and not args.__dict__.get("project_id"):
        missing.append("--project / --project-id")
    if missing:
        joined = " and ".join(missing)
        raise SourceBriefCliError(f"{joined} required; pass a name explicitly or run sourcebrief use first")


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
        for key in ("workspace_id", "project_id", "workspace_name", "workspace_slug", "project_name"):
            config.pop(key, None)
    if args.workspace_id:
        config["workspace_id"] = args.workspace_id
        if getattr(args, "_resolved_workspace_name", None):
            config["workspace_name"] = args._resolved_workspace_name
        if getattr(args, "_resolved_workspace_slug", None):
            config["workspace_slug"] = args._resolved_workspace_slug
        if not args.project_id and not args.clear:
            config.pop("project_id", None)
            config.pop("project_name", None)
    if args.project_id:
        config["project_id"] = args.project_id
        if getattr(args, "_resolved_project_name", None):
            config["project_name"] = args._resolved_project_name
    if getattr(args, "_api_url_explicit", False) or "api_url" not in config:
        config["api_url"] = args.api_url.rstrip("/")
    path = _save_cli_config(config)
    return {
        "status": "saved",
        "config_path": str(path),
        "api_url": config.get("api_url"),
        "workspace": config.get("workspace_name") or config.get("workspace_slug"),
        "project": config.get("project_name"),
        "workspace_id": config.get("workspace_id"),
        "project_id": config.get("project_id"),
    }


def cmd_status(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    config = getattr(args, "_sourcebrief_config", {}) or {}
    return {
        "config_path": str(_config_path()),
        "api_url": args.api_url.rstrip("/"),
        "workspace": _selected_value(config, "workspace_name") or _selected_value(config, "workspace_slug"),
        "project": _selected_value(config, "project_name"),
        "workspace_id": _selected_value(config, "workspace_id"),
        "project_id": _selected_value(config, "project_id"),
        "auth_mode": getattr(args, "_auth_mode", "bearer_token" if args.token else "email_header"),
        "email": getattr(args, "_session_email", None) if getattr(args, "_auth_mode", None) in {"saved_session", "session_login_env"} else (None if args.token else args.email),
        "token_set": bool(args.token),
        "password_env_set": bool(getattr(args, "_session_login_password", None)),
    }


def _login_password_from_args(args: argparse.Namespace) -> str:
    env_name = getattr(args, "password_env", None)
    if env_name:
        value = os.getenv(env_name) or _dotenv_value(env_name)
        if not value:
            raise SourceBriefCliError(f"password environment variable or .env key {env_name} is not set")
        return value
    env_password = _env_login_password()
    if env_password:
        return env_password
    return getpass.getpass("SourceBrief password: ")


def cmd_login(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    email = getattr(args, "login_email", None) or _env_login_email(args)
    if not email:
        raise SourceBriefCliError("login requires --email or SOURCEBRIEF_ADMIN_EMAIL/SOURCEBRIEF_EMAIL")
    password = _login_password_from_args(args)
    client = SourceBriefClient(args.api_url, email, token=None)
    session_token = _login_with_password(client, email, password)
    config = dict(getattr(args, "_sourcebrief_config", {}) or {})
    config[SESSION_TOKEN_CONFIG_KEY] = session_token
    config[SESSION_EMAIL_CONFIG_KEY] = email
    if getattr(args, "_api_url_explicit", False) or "api_url" not in config:
        config["api_url"] = args.api_url.rstrip("/")
    path = _save_cli_config(config)
    return {
        "status": "logged_in",
        "config_path": str(path),
        "api_url": config.get("api_url"),
        "email": email,
        "auth_mode": "saved_session",
        "token_set": True,
    }


def cmd_logout(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    config = dict(getattr(args, "_sourcebrief_config", {}) or {})
    had_session = bool(config.pop(SESSION_TOKEN_CONFIG_KEY, None))
    config.pop(SESSION_EMAIL_CONFIG_KEY, None)
    path = _save_cli_config(config)
    return {"status": "logged_out", "config_path": str(path), "removed_session": had_session}


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


def _mcp_structured_payload(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return None
    result = response.get("result")
    if not isinstance(result, dict):
        return None
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text" or not isinstance(item.get("text"), str):
                continue
            try:
                parsed = json.loads(item["text"])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def _mcp_citation_count(response: Any) -> int:
    payload = _mcp_structured_payload(response)
    if not isinstance(payload, dict):
        return 0
    citations = payload.get("citations")
    if isinstance(citations, list) and citations:
        return len(citations)
    answer = payload.get("answer")
    if isinstance(answer, dict):
        citations_used = answer.get("citations_used")
        if isinstance(citations_used, list) and citations_used:
            return len(citations_used)
    return 0


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
        return {_redact_manifest_key(key): _redact_manifest_value(item) for key, item in value.items()}
    return value


def cmd_doctor(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    checks: list[dict[str, Any]] = []
    try:
        health = client.request("GET", "/readyz")
        checks.append(_check_result("api", "passed", api_url=args.api_url.rstrip("/"), response=health))
    except SourceBriefCliError as exc:
        checks.append(_check_result("api", "failed", api_url=args.api_url.rstrip("/"), error=str(exc)))

    auth_mode = getattr(args, "_auth_mode", "bearer_token" if args.token else "email_header")
    checks.append(
        _check_result(
            "auth_mode",
            "info",
            mode=auth_mode,
            email=getattr(args, "_session_email", None) if auth_mode in {"saved_session", "session_login_env"} else (None if args.token else args.email),
            token_set=bool(args.token),
            password_env_set=bool(getattr(args, "_session_login_password", None)),
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
                elif getattr(args, "require_citations", False):
                    citation_count = _mcp_citation_count(mcp)
                    if citation_count <= 0:
                        checks.append(_check_result("mcp_context", "failed", query=args.query, error="MCP smoke returned no citations", citation_count=citation_count))
                    else:
                        checks.append(_check_result("mcp_context", "passed", query=args.query, has_result=bool(mcp), citation_count=citation_count))
                else:
                    checks.append(_check_result("mcp_context", "passed", query=args.query, has_result=bool(mcp)))
            except SourceBriefCliError as exc:
                checks.append(_check_result("mcp_context", "failed", query=args.query, error=str(exc)))
    else:
        next_step = 'run `sourcebrief use --workspace "..." --project "..."` or rerun doctor with --workspace "..." --project "..."'
        checks.append(
            _check_result(
                "project",
                "warning",
                message=f"workspace/project not selected; {next_step}",
            )
        )
        if args.query:
            checks.append(
                _check_result(
                    "mcp_context",
                    "incomplete",
                    query=args.query,
                    message="MCP smoke was not run: workspace/project not selected.",
                    next_step=next_step,
                )
            )

    failed = [check for check in checks if check["status"] == "failed"]
    incomplete = [check for check in checks if check["status"] == "incomplete"]
    warnings = [check for check in checks if check["status"] == "warning"]
    return {"status": "failed" if failed else "incomplete" if incomplete else "warning" if warnings else "passed", "checks": checks}


def cmd_workspace_create(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    return client.request(
        "POST",
        "/workspaces",
        body={"name": args.name, "slug": args.slug},
        expected={201},
    )


def cmd_project_create(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args, project=False)
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects",
        body={"name": args.name, "description": args.description},
        expected={201},
    )


def cmd_token_create(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args, project=False)
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
    _require_scope(args, project=False)
    allowed_project_ids = _split_csv_or_repeated(args.project_id)
    allowed_resource_ids = _split_csv_or_repeated(args.resource_id)
    if not args.workspace_wide and not (allowed_project_ids or allowed_resource_ids):
        raise SourceBriefCliError(
            "token create-runtime requires --project/--project-id/--resource-id or explicit --workspace-wide"
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
    _require_scope(args, project=False)
    return client.request("GET", f"/workspaces/{args.workspace_id}/api-tokens")


def cmd_token_revoke(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args, project=False)
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
    _require_scope(args)
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
    _require_scope(args)
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
    _require_scope(args)
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
    _require_scope(args)
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
    _require_scope(args)

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


def cmd_resource_get(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args)
    return client.request("GET", f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}")


def cmd_resource_update(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args)
    body: dict[str, Any] = {}
    for field in ("name", "uri", "update_frequency", "retrieval_enabled", "stale_after_days"):
        value = getattr(args, field, None)
        if value is not None:
            body[field] = value
    if args.source_config_json:
        try:
            parsed = json.loads(args.source_config_json)
        except json.JSONDecodeError as exc:
            raise SourceBriefCliError("--source-config-json must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise SourceBriefCliError("--source-config-json must be a JSON object")
        body["source_config"] = parsed
    if not body:
        raise SourceBriefCliError("resource update requires at least one field to change")
    return client.request(
        "PATCH",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}",
        body=body,
    )


def cmd_resource_update_git(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args)
    body: dict[str, Any] = {}
    mapping = {
        "branch": "branch",
        "auth_token_env": "auth_token_env",
        "clone_timeout": "clone_timeout",
        "max_file_bytes": "max_file_bytes",
        "max_files": "max_repo_files",
        "max_repo_bytes": "max_repo_bytes",
        "update_frequency": "update_frequency",
    }
    for arg_name, field_name in mapping.items():
        value = getattr(args, arg_name, None)
        if value is not None:
            body[field_name] = value
    if not body:
        raise SourceBriefCliError("resource update-git requires at least one git setting to change")
    return client.request(
        "PATCH",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}/git-env",
        body=body,
    )


def cmd_resource_archive(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args)
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}/archive",
    )


def cmd_resource_delete(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args)
    client.request(
        "DELETE",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}",
        expected={204},
    )
    return {"status": "deleted", "resource_id": args.resource_id}


def cmd_resource_restore(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args)
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}/restore",
    )


def cmd_resource_purge(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args)
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}/purge",
    )


def cmd_resource_schedule_due(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args)
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
    body = {"query": args.query, "top_k": args.top_k, "resource_ids": _resource_ids(args.resource_id)}
    _apply_resource_refs(body, args)
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/search",
        body=body,
    )


def cmd_agent_context(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args)
    body = {
        "query": args.query,
        "runtime": args.runtime,
        "top_k": args.top_k,
        "resource_ids": _resource_ids(args.resource_id),
        "include_code_symbols": args.include_code_symbols,
        "include_answer": getattr(args, "include_answer", True),
        "max_chars": args.max_chars,
    }
    _apply_resource_refs(body, args)
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/agent-context",
        body=body,
    )


def cmd_mcp_context(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args)
    arguments = {
        "query": args.query,
        "runtime": args.runtime,
        "top_k": args.top_k,
        "resource_ids": _resource_ids(args.resource_id),
    }
    _apply_resource_refs(arguments, args)
    return client.request(
        "POST",
        f"/mcp/{args.workspace_id}/{args.project_id}",
        body={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "sourcebrief.get_agent_context",
                "arguments": arguments,
            },
        },
    )


def _pick_answer_lines(context: str, *, limit: int = 3) -> list[str]:
    lines: list[str] = []
    for raw_line in context.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("[") or line.startswith("#"):
            continue
        lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def _human_answer_brief(data: dict[str, Any]) -> dict[str, Any]:
    citations = data.get("citations") or []
    warnings = data.get("coverage_warnings") or []
    api_answer = data.get("answer") if isinstance(data.get("answer"), dict) else None
    if api_answer and api_answer.get("text"):
        return {
            "query": data.get("query"),
            "answer": api_answer.get("text"),
            "outcome": api_answer.get("outcome", "answered"),
            "abstention_reason": api_answer.get("abstention_reason"),
            "unsupported_claim_terms": api_answer.get("unsupported_claim_terms") or [],
            "citations_used": api_answer.get("citations_used") or [],
            "confidence": api_answer.get("confidence", "medium"),
            "missing_evidence": api_answer.get("caveats") or warnings,
            "suggested_follow_up_reads": [call.get("arguments", {}) for call in data.get("suggested_tool_calls", [])[:2]],
            "raw_packet_hint": "Run with --json for the full agent-context packet.",
        }
    answer_lines = _pick_answer_lines(str(data.get("context") or ""))
    if answer_lines:
        answer = " ".join(answer_lines)
    elif citations:
        answer = "SourceBrief found cited context, but no readable snippet fit the response budget. Use --json to inspect the full packet."
    else:
        answer = "No grounded answer is available from the selected SourceBrief evidence."
    cited = citations[:3]
    return {
        "query": data.get("query"),
        "answer": answer,
        "citations_used": [
            {
                "label": f"[{idx}]",
                "path": citation.get("path") or citation.get("title") or str(citation.get("resource_id")),
                "resource_id": citation.get("resource_id"),
                "snapshot_id": citation.get("snapshot_id"),
                "content_hash": citation.get("content_hash"),
                "score": citation.get("score"),
            }
            for idx, citation in enumerate(cited, start=1)
        ],
        "confidence": "low" if warnings or not citations else "medium",
        "missing_evidence": warnings,
        "suggested_follow_up_reads": [call.get("arguments", {}) for call in data.get("suggested_tool_calls", [])[:2]],
        "raw_packet_hint": "Run with --json for the full agent-context packet.",
    }


def _capture_review_bundle(
    *,
    agent_context: dict[str, Any],
    args: argparse.Namespace,
    query: str,
    kind: str = "answer",
    task_brief: str = "Capture a cited SourceBrief answer for autonomous review.",
) -> dict[str, Any] | None:
    output_path = getattr(args, "review_bundle_out", None)
    if not output_path:
        return None
    bundle = build_review_bundle_from_agent_context(
        agent_context=agent_context,
        workspace_id=args.workspace_id,
        project_id=args.project_id,
        query=query,
        runtime=getattr(args, "runtime", "api"),
        top_k=getattr(args, "top_k", 8),
        max_chars=getattr(args, "max_chars", 12000),
        kind=kind,  # type: ignore[arg-type]
        command=["sourcebrief", *list(getattr(args, "_sourcebrief_argv", []) or [])],
        resource_ids=_resource_ids(getattr(args, "resource_id", None)),
        task_brief=task_brief,
    )
    written = write_review_bundle(output_path, bundle)
    return {
        "path": str(written),
        "bundle_id": bundle.bundle_id,
        "schema_version": bundle.schema_version,
        "completeness": bundle.security.completeness,
        "citation_count": len(bundle.citations),
        "claim_count": len(bundle.output.claim_ids),
    }


def cmd_ask(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    data = cmd_agent_context(client, args)
    review_bundle = _capture_review_bundle(agent_context=data, args=args, query=args.query)
    if args.json:
        if review_bundle:
            data = {**data, "review_bundle": review_bundle}
        return data
    answer = _human_answer_brief(data)
    if review_bundle:
        answer["review_bundle"] = review_bundle
    return answer


def cmd_quickstart_demo(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    health = client.request("GET", "/readyz")
    workspace_slug = args.slug or f"sourcebrief-demo-{int(time.time())}"
    workspace = client.request("POST", "/workspaces", body={"name": args.workspace_name, "slug": workspace_slug}, expected={201})
    project = client.request(
        "POST",
        f"/workspaces/{workspace['id']}/projects",
        body={"name": args.project_name, "description": "Isolated SourceBrief CLI quickstart demo"},
        expected={201},
    )
    content = (
        "# Payment retry runbook\n\n"
        "If a payment job fails with retryable upstream errors, retry it with exponential backoff. "
        "Escalate after three failed attempts and include the order id, upstream status, and retry timestamps.\n"
    )
    resource_result = cmd_resource_add_doc(
        client,
        argparse.Namespace(
            workspace_id=workspace["id"],
            project_id=project["id"],
            name="Payment retry runbook",
            uri="demo://payment-retry-runbook",
            update_frequency="manual",
            content=content,
            content_file=None,
            path="runbooks/payment-retry.md",
            title="Payment retry runbook",
            refresh=True,
            wait=True,
            timeout=args.timeout,
        ),
    )
    resource = resource_result["resource"]
    answer_packet = cmd_agent_context(
        client,
        argparse.Namespace(
            workspace_id=workspace["id"],
            project_id=project["id"],
            query="What should an operator do when a payment job hits retryable upstream errors?",
            runtime="api",
            top_k=3,
            resource_id=None,
            resource=["Payment retry runbook"],
            include_code_symbols=False,
            max_chars=6000,
        ),
    )
    mcp_validation: dict[str, Any] | None = None
    if args.validate_mcp:
        mcp_response = cmd_mcp_context(
            client,
            argparse.Namespace(
                workspace_id=workspace["id"],
                project_id=project["id"],
                query="What should an operator do when a payment job hits retryable upstream errors?",
                runtime="api",
                top_k=3,
                resource_id=None,
                resource=["Payment retry runbook"],
            ),
        )
        error = _mcp_error_message(mcp_response)
        mcp_validation = {"status": "failed" if error else "passed", "error": error}
    saved_config = dict(getattr(args, "_sourcebrief_config", {}) or {})
    saved_config.update(
        {
            "api_url": args.api_url.rstrip("/"),
            "workspace_id": workspace["id"],
            "workspace_name": workspace.get("name"),
            "workspace_slug": workspace.get("slug"),
            "project_id": project["id"],
            "project_name": project.get("name"),
        }
    )
    config_path = _save_cli_config(saved_config)
    review_bundle = None
    if getattr(args, "review_bundle_out", None):
        review_args = argparse.Namespace(
            **{
                **vars(args),
                "workspace_id": workspace["id"],
                "project_id": project["id"],
                "runtime": "api",
                "top_k": 3,
                "max_chars": 6000,
                "resource_id": [resource["id"]],
            }
        )
        review_bundle = _capture_review_bundle(
            agent_context=answer_packet,
            args=review_args,
            query="What should an operator do when a payment job hits retryable upstream errors?",
            kind="cli_demo",
            task_brief="Capture the deterministic quickstart demo answer for autonomous review.",
        )
    result = {
        "status": "indexed_and_ready_for_retrieval",
        "health": health,
        "workspace_id": workspace["id"],
        "project_id": project["id"],
        "resource_id": resource["id"],
        "workspace_name": workspace.get("name"),
        "project_name": project.get("name"),
        "resource_name": resource.get("name"),
        "config_path": str(config_path),
        "mcp_validation": mcp_validation,
        "index_run": resource_result.get("index_run"),
        "answer": _human_answer_brief(answer_packet),
        "next_command": 'sourcebrief ask --resource "Payment retry runbook" "What should an operator do when payment retries fail?"',
        "cleanup": "Delete the demo workspace from the web console when finished, or keep it for CLI experiments.",
    }
    if review_bundle:
        result["review_bundle"] = review_bundle
    return result


def cmd_review_pr_bundle(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    try:
        metadata_source: Literal["live", "fixture"] = "live"
        if args.metadata_fixture:
            metadata_source = "fixture"
            metadata = load_pr_metadata_fixture(args.metadata_fixture)
            metadata.setdefault("repo", args.repo or metadata.get("repo") or metadata.get("repository"))
            metadata["fixture_path"] = str(Path(args.metadata_fixture).expanduser())
        else:
            if args.pr is None:
                raise GitHubPRBundleError("--pr is required when --metadata-fixture is not provided")
            metadata = fetch_github_pr_metadata(repo=args.repo or "", pr_number=args.pr)
        bundle = build_review_bundle_from_github_pr_metadata(
            metadata,
            workspace_id=args.workspace_id,
            project_id=args.project_id,
            reviewer_backend=args.reviewer_backend,
            metadata_source=metadata_source,
        )
        written = write_review_bundle(args.bundle_out, bundle)
    except (OSError, ValueError) as exc:
        raise SourceBriefCliError(str(exc)) from exc
    subject = bundle.reviewer_notes[0] if bundle.reviewer_notes else ""
    return {
        "status": "pr_review_bundle_written",
        "bundle_path": str(written),
        "bundle_id": bundle.bundle_id,
        "subject": subject,
        "changed_paths": [source_ref.path for source_ref in bundle.source_refs if source_ref.path],
        "bundle": bundle.model_dump(mode="json"),
    }


def cmd_review_run(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    options = ReviewRunOptions(backend=args.backend, allow_incomplete=args.allow_incomplete)
    try:
        report = run_review_bundle_path(args.bundle, options=options)
    except ReviewRunnerError as exc:
        raise SourceBriefCliError(str(exc)) from exc
    output_path = args.report_out
    if output_path:
        written = write_reviewer_report(output_path, report)
        return {
            "status": "reviewed",
            "verdict": report.verdict,
            "report_path": str(written),
            "report": report.model_dump(mode="json"),
        }
    return report.model_dump(mode="json")


def cmd_review_propose(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    report = load_reviewer_report(args.report)
    finding = select_finding(report, args.finding_id)
    proposal = proposal_from_finding(report, finding, owner=args.owner)
    if args.proposal_out:
        written = write_regression_proposal(args.proposal_out, proposal)
        return {
            "status": "proposal_written",
            "proposal_path": str(written),
            "proposal": proposal.model_dump(mode="json"),
        }
    return proposal.model_dump(mode="json")


def cmd_review_gate(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    result = validate_regression_proposal_file(args.proposal)
    if args.result_out:
        written = write_validation_gate_result(args.result_out, result)
        return {
            "status": "gate_evaluated",
            "decision": result.decision,
            "result_path": str(written),
            "result": result.model_dump(mode="json"),
        }
    return result.model_dump(mode="json")


def cmd_review_stage(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    try:
        receipt = stage_regression_proposal(
            proposal_path=args.proposal,
            gate_result_path=args.gate_result,
            out_dir=args.out_dir,
        )
    except (OSError, ValueError) as exc:
        raise SourceBriefCliError(str(exc)) from exc
    return {
        "status": "staged",
        "stage_dir": receipt.stage_dir,
        "receipt_path": str(Path(receipt.stage_dir) / "receipt.json"),
        "patch_path": receipt.patch_path,
        "apply_command": receipt.apply_command,
        "rollback_command": receipt.rollback_command,
        "receipt": receipt.model_dump(mode="json"),
    }


def cmd_review_history_list(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    try:
        summary = scan_review_history(args.dir)
    except (OSError, ValueError) as exc:
        raise SourceBriefCliError(str(exc)) from exc
    return summary.model_dump(mode="json")


def cmd_review_history_show(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    try:
        return show_review_history_record(args.dir, args.artifact)
    except (OSError, ValueError) as exc:
        raise SourceBriefCliError(str(exc)) from exc


def cmd_review_mvp_smoke(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    try:
        return run_mvp_smoke_path(
            out_dir=args.out_dir,
            bundle_path=Path(args.bundle).expanduser() if args.bundle else None,
            finding_id=args.finding_id,
            owner=args.owner,
        )
    except (OSError, ValueError) as exc:
        raise SourceBriefCliError(str(exc)) from exc


def cmd_review_sleep(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    try:
        summary = run_sleep_replay(
            args.dir,
            out_dir=args.out_dir,
            min_occurrences=args.min_occurrences,
            max_artifacts=args.max_artifacts,
            dry_run=True,
        )
        if args.summary_out:
            write_sleep_replay_summary(args.summary_out, summary)
    except (OSError, SleepReplayError) as exc:
        raise SourceBriefCliError(str(exc)) from exc
    return summary.model_dump(mode="json")


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


def _skill_export_generate_path(client: SourceBriefClient, args: argparse.Namespace) -> str:
    _require_scope(args)
    version = args.pack_version
    if not version:
        current = client.request("GET", f"/workspaces/{args.workspace_id}/projects/{args.project_id}/context-packs/{args.pack_key}/current")
        version = str(current.get("version"))
    return f"/workspaces/{args.workspace_id}/projects/{args.project_id}/context-packs/{args.pack_key}/versions/{version}/skill-exports"


def _skill_export_download_url(client: SourceBriefClient, args: argparse.Namespace, export: dict[str, Any]) -> str:
    export_id = export.get("id")
    return f"{client.api_url}/workspaces/{args.workspace_id}/projects/{args.project_id}/skill-exports/{export_id}/download.zip"


def cmd_skill_export(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    payload: dict[str, Any] = {"export_type": "hermes_skill", "title": args.title}
    if args.summary:
        payload["summary"] = args.summary
    export = client.request("POST", _skill_export_generate_path(client, args), body=payload)
    if args.approve_comment:
        export = client.request(
            "POST",
            f"/workspaces/{args.workspace_id}/projects/{args.project_id}/skill-exports/{export['id']}/approve",
            body={"comment": args.approve_comment},
        )
    out_result = None
    if args.out:
        out_result = skill_install.write_export_files(export, Path(args.out), force=args.force)
    return {
        "status": "exported",
        "export": export,
        "download_url": _skill_export_download_url(client, args, export),
        "local_package": out_result,
        "next_steps": [
            "Review generated package files before installing.",
            "Approve the export before local install if it is still draft.",
            f"Install with: sourcebrief skill install --package {sh_quote(args.out or '<package-dir>')} --target hermes --dry-run",
        ],
    }


def _skill_profile(args: argparse.Namespace) -> str:
    return args.profile or "default"


def _skill_skills_dir(args: argparse.Namespace) -> Path:
    return Path(args.skills_dir).expanduser() if args.skills_dir else skill_install.default_skills_dir(_skill_profile(args))


def cmd_skill_install(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    skills_dir = _skill_skills_dir(args)
    profile = _skill_profile(args)
    package = Path(args.package)
    if args.dry_run:
        if args.apply:
            raise SourceBriefCliError("skill install accepts only one of --dry-run or --apply")
        return skill_install.dry_run_install(package, skills_dir=skills_dir, profile=profile, skill_name=args.name)
    if not args.apply:
        raise SourceBriefCliError("skill install requires --dry-run or explicit --apply")
    return skill_install.install_package(
        package,
        skills_dir=skills_dir,
        receipt_file=skill_install.receipt_path(args.receipt),
        profile=profile,
        skill_name=args.name,
        force=args.force,
    )


def cmd_skill_uninstall(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    return skill_install.uninstall(Path(args.receipt), force=args.force)


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
            "passed" if schema_ok else "failed" if mode in {"pinned-snapshot", "local-mirror"} else "warning",
            agent_pack_schema_version=manifest.get("agent_pack_schema_version"),
            message=None if schema_ok else "manifest predates Agent Pack policy metadata" if mode not in {"pinned-snapshot", "local-mirror"} else f"{mode} manifests require sourcebrief.agent-pack.v1",
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
            runtime_access_requires_sourcebrief_remote=runtime_access.get("requires_sourcebrief_remote"),
            runtime_access_local_repo_required=runtime_access.get("local_repo_required"),
            runtime_access_local_grep_allowed=runtime_access.get("local_grep_allowed"),
            runtime_access_local_edits_allowed=runtime_access.get("local_edits_allowed"),
            runtime_access_current_claims_require_remote=runtime_access.get("current_claims_require_remote"),
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
            require_remote_for_current_claims=freshness_policy.get("require_remote_for_current_claims"),
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
        local_mirror_policy = raw_local_mirror_policy if isinstance(raw_local_mirror_policy, dict) else {}
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
                local_access_control_required=local_mirror_policy.get("local_access_control_required"),
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
            message=None if "sourcebrief.get_agent_context" in required else "manifest does not declare sourcebrief.get_agent_context as required",
        )
    )
    return checks


def cmd_agent_pack_doctor(client: SourceBriefClient, args: argparse.Namespace) -> Any:
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
        remote_result = cmd_doctor(client, args)
        for check in remote_result.get("checks", []):
            if isinstance(check, dict):
                checks.append({**check, "name": f"remote_{check.get('name')}"})
    failed = [check for check in checks if check["status"] == "failed"]
    incomplete = [check for check in checks if check["status"] == "incomplete"]
    warnings = [check for check in checks if check["status"] == "warning"]
    return {
        "status": "failed" if failed else "incomplete" if incomplete else "warning" if warnings else "passed",
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


def cmd_agent_list(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args, project=False)
    return client.request("GET", f"/workspaces/{args.workspace_id}/agents")


def cmd_agent_profile(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args)
    return client.request(
        "GET",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/agent-profile",
    )


def cmd_resource_graph(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args)
    return client.request(
        "GET",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}/graph?limit={args.limit}",
    )


def _add_common_resource_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", help="workspace name or slug; defaults to sourcebrief use selection")
    parser.add_argument("--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection")
    parser.add_argument("--project", help="project name; defaults to sourcebrief use selection")
    parser.add_argument("--project-id", help="advanced: project ID; defaults to sourcebrief use selection")
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
        default=None,
    )
    parser.add_argument(
        "--token",
        default=_first_env("SOURCEBRIEF_TOKEN", "CONTEXTSMITH_TOKEN"),
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
    use.add_argument("--workspace", help="workspace name or slug to save; changing it without --project clears the saved project")
    use.add_argument("--workspace-id", help="advanced: workspace ID to save; changing it without --project-id clears the saved project")
    use.add_argument("--project", help="project name to save")
    use.add_argument("--project-id", help="advanced: project ID to save")
    use.add_argument("--clear", action="store_true", help="clear saved workspace/project before applying new values")
    use.set_defaults(func=cmd_use)

    status = sub.add_parser("status", help="show selected CLI defaults and auth mode without secrets")
    status.set_defaults(func=cmd_status)

    login = sub.add_parser("login", help="log in with email/password and save a session token")
    login.add_argument("--email", dest="login_email", help="login email; defaults to SOURCEBRIEF_ADMIN_EMAIL/SOURCEBRIEF_EMAIL")
    login.add_argument("--password-env", help="name of an environment variable containing the password; otherwise prompts")
    login.set_defaults(func=cmd_login)

    logout = sub.add_parser("logout", help="remove the saved SourceBrief session token")
    logout.set_defaults(func=cmd_logout)

    quickstart = sub.add_parser(
        "quickstart-demo",
        help="run a one-command local demo that ends with a cited human answer",
    )
    quickstart.add_argument("--workspace-name", default="SourceBrief CLI Demo")
    quickstart.add_argument("--project-name", default="First useful moment")
    quickstart.add_argument("--slug", help="workspace slug; defaults to a timestamped sourcebrief-demo-* slug")
    quickstart.add_argument("--timeout", type=int, default=120, help="seconds to wait for indexing")
    quickstart.add_argument("--review-bundle-out", help="write an opt-in self-improvement review bundle JSON for the demo answer")
    quickstart.add_argument("--validate-mcp", action="store_true", help="also call the MCP context tool and report pass/fail")
    quickstart.set_defaults(func=cmd_quickstart_demo)

    doctor = sub.add_parser("doctor", help="check API/auth/project/MCP readiness")
    doctor.add_argument("--workspace", help="workspace name or slug; defaults to sourcebrief use selection")
    doctor.add_argument("--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection")
    doctor.add_argument("--project", help="project name; defaults to sourcebrief use selection")
    doctor.add_argument("--project-id", help="advanced: project ID; defaults to sourcebrief use selection")
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
    project_create.add_argument("--workspace", help="workspace name or slug")
    project_create.add_argument("--workspace-id", help="advanced: workspace ID")
    project_create.add_argument("--name", required=True)
    project_create.add_argument("--description")
    project_create.set_defaults(func=cmd_project_create)

    tokens = sub.add_parser("token", help="workspace API token commands").add_subparsers(dest="token_command")
    token_create = tokens.add_parser("create", help="create a bearer API token for agents/Hermes")
    token_create.add_argument("--workspace", help="workspace name or slug")
    token_create.add_argument("--workspace-id", help="advanced: workspace ID")
    token_create.add_argument("--name", required=True)
    token_create.add_argument("--scope", action="append", required=True, help="scope, repeatable or comma-separated")
    token_create.add_argument("--project", dest="project_ref", action="append", help="allowed project name, repeatable")
    token_create.add_argument("--project-id", action="append", help="advanced: allowed project ID, repeatable or comma-separated")
    token_create.add_argument("--resource-id", action="append", help="allowed resource ID, repeatable or comma-separated")
    token_create.add_argument("--expires-at", help="ISO-8601 timestamp")
    token_create.set_defaults(func=cmd_token_create)

    token_runtime = tokens.add_parser("create-runtime", help="create a preset runtime token")
    token_runtime.add_argument("--workspace", help="workspace name or slug")
    token_runtime.add_argument("--workspace-id", help="advanced: workspace ID")
    token_runtime.add_argument("--name", default="SourceBrief runtime")
    preset = token_runtime.add_mutually_exclusive_group()
    preset.add_argument("--context-only", dest="read_code", action="store_false", help="project/query/resource/review read scopes only")
    preset.add_argument("--read-code", dest="read_code", action="store_true", help="include code:read for source drill-down tools")
    token_runtime.add_argument("--project", dest="project_ref", action="append", help="allowed project name, repeatable")
    token_runtime.add_argument("--project-id", action="append", help="advanced: allowed project ID, repeatable or comma-separated")
    token_runtime.add_argument("--resource-id", action="append", help="allowed resource ID, repeatable or comma-separated")
    token_runtime.add_argument("--workspace-wide", action="store_true", help="explicitly allow this runtime token across the whole workspace")
    token_runtime.add_argument("--expires-at", help="ISO-8601 timestamp")
    token_runtime.set_defaults(func=cmd_token_create_runtime, read_code=False)

    token_list = tokens.add_parser("list", help="list API tokens without plaintext secrets")
    token_list.add_argument("--workspace", help="workspace name or slug")
    token_list.add_argument("--workspace-id", help="advanced: workspace ID")
    token_list.set_defaults(func=cmd_token_list)

    token_revoke = tokens.add_parser("revoke", help="revoke an API token")
    token_revoke.add_argument("--workspace", help="workspace name or slug")
    token_revoke.add_argument("--workspace-id", help="advanced: workspace ID")
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
    refresh.add_argument("--workspace", help="workspace name or slug")
    refresh.add_argument("--workspace-id", help="advanced: workspace ID")
    refresh.add_argument("--project", help="project name")
    refresh.add_argument("--project-id", help="advanced: project ID")
    refresh.add_argument("--resource-id", required=True)
    refresh.add_argument("--wait", action="store_true")
    refresh.add_argument("--timeout", type=int, default=120)
    refresh.set_defaults(func=cmd_resource_refresh)

    list_resources = resources.add_parser("list", help="list resources")
    list_resources.add_argument("--workspace", help="workspace name or slug; defaults to sourcebrief use selection")
    list_resources.add_argument("--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection")
    list_resources.add_argument("--project", help="project name; defaults to sourcebrief use selection")
    list_resources.add_argument("--project-id", help="advanced: project ID; defaults to sourcebrief use selection")
    list_resources.set_defaults(func=cmd_resource_list)

    get_resource = resources.add_parser("get", help="show one resource")
    get_resource.add_argument("--workspace", help="workspace name or slug; defaults to sourcebrief use selection")
    get_resource.add_argument("--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection")
    get_resource.add_argument("--project", help="project name; defaults to sourcebrief use selection")
    get_resource.add_argument("--project-id", help="advanced: project ID; defaults to sourcebrief use selection")
    get_resource.add_argument("--resource-id", required=True)
    get_resource.set_defaults(func=cmd_resource_get)

    update_resource = resources.add_parser("update", help="update resource metadata or retrieval settings")
    update_resource.add_argument("--workspace", help="workspace name or slug; defaults to sourcebrief use selection")
    update_resource.add_argument("--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection")
    update_resource.add_argument("--project", help="project name; defaults to sourcebrief use selection")
    update_resource.add_argument("--project-id", help="advanced: project ID; defaults to sourcebrief use selection")
    update_resource.add_argument("--resource-id", required=True)
    update_resource.add_argument("--name")
    update_resource.add_argument("--uri")
    update_resource.add_argument("--update-frequency")
    update_resource.add_argument("--retrieval-enabled", dest="retrieval_enabled", action="store_true", default=None)
    update_resource.add_argument("--no-retrieval-enabled", dest="retrieval_enabled", action="store_false")
    update_resource.add_argument("--stale-after-days", type=int)
    update_resource.add_argument("--source-config-json", help="advanced: replace source_config with this JSON object")
    update_resource.set_defaults(func=cmd_resource_update)

    update_git = resources.add_parser("update-git", help="update common git resource import settings")
    update_git.add_argument("--workspace", help="workspace name or slug; defaults to sourcebrief use selection")
    update_git.add_argument("--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection")
    update_git.add_argument("--project", help="project name; defaults to sourcebrief use selection")
    update_git.add_argument("--project-id", help="advanced: project ID; defaults to sourcebrief use selection")
    update_git.add_argument("--resource-id", required=True)
    update_git.add_argument("--branch")
    update_git.add_argument("--auth-token-env")
    update_git.add_argument("--clone-timeout", type=int)
    update_git.add_argument("--max-files", type=int)
    update_git.add_argument("--max-file-bytes", type=int)
    update_git.add_argument("--max-repo-bytes", type=int)
    update_git.add_argument("--update-frequency")
    update_git.set_defaults(func=cmd_resource_update_git)

    archive = resources.add_parser("archive", help="archive a resource and disable retrieval")
    archive.add_argument("--workspace", help="workspace name or slug")
    archive.add_argument("--workspace-id", help="advanced: workspace ID")
    archive.add_argument("--project", help="project name")
    archive.add_argument("--project-id", help="advanced: project ID")
    archive.add_argument("--resource-id", required=True)
    archive.set_defaults(func=cmd_resource_archive)

    delete_resource = resources.add_parser("delete", help="soft-delete a resource and disable retrieval")
    delete_resource.add_argument("--workspace", help="workspace name or slug")
    delete_resource.add_argument("--workspace-id", help="advanced: workspace ID")
    delete_resource.add_argument("--project", help="project name")
    delete_resource.add_argument("--project-id", help="advanced: project ID")
    delete_resource.add_argument("--resource-id", required=True)
    delete_resource.set_defaults(func=cmd_resource_delete)

    restore = resources.add_parser("restore", help="restore an archived or soft-deleted resource")
    restore.add_argument("--workspace", help="workspace name or slug")
    restore.add_argument("--workspace-id", help="advanced: workspace ID")
    restore.add_argument("--project", help="project name")
    restore.add_argument("--project-id", help="advanced: project ID")
    restore.add_argument("--resource-id", required=True)
    restore.set_defaults(func=cmd_resource_restore)

    purge = resources.add_parser("purge", help="hard purge a soft-deleted resource and artifacts")
    purge.add_argument("--workspace", help="workspace name or slug")
    purge.add_argument("--workspace-id", help="advanced: workspace ID")
    purge.add_argument("--project", help="project name")
    purge.add_argument("--project-id", help="advanced: project ID")
    purge.add_argument("--resource-id", required=True)
    purge.set_defaults(func=cmd_resource_purge)

    schedule = resources.add_parser("schedule-due", help="enqueue due scheduled refreshes for a project")
    schedule.add_argument("--workspace", help="workspace name or slug")
    schedule.add_argument("--workspace-id", help="advanced: workspace ID")
    schedule.add_argument("--project", help="project name")
    schedule.add_argument("--project-id", help="advanced: project ID")
    schedule.add_argument("--limit", type=int, default=100)
    schedule.add_argument("--dry-run", action="store_true")
    schedule.set_defaults(func=cmd_resource_schedule_due)

    graph = resources.add_parser("graph", help="show a resource graph index")
    graph.add_argument("--workspace", help="workspace name or slug")
    graph.add_argument("--workspace-id", help="advanced: workspace ID")
    graph.add_argument("--project", help="project name")
    graph.add_argument("--project-id", help="advanced: project ID")
    graph.add_argument("--resource-id", required=True)
    graph.add_argument("--limit", type=int, default=50)
    graph.set_defaults(func=cmd_resource_graph)

    agent_packs = sub.add_parser("agent-pack", help="Agent Pack package validation commands").add_subparsers(dest="agent_pack_command")
    agent_pack_doctor = agent_packs.add_parser("doctor", help="validate a local Agent Pack package and optional remote smoke query")
    agent_pack_doctor.add_argument("--package", required=True, help="package directory or .zip from sourcebrief skill export")
    agent_pack_doctor.add_argument("--workspace", help="workspace name or slug; defaults to sourcebrief use selection")
    agent_pack_doctor.add_argument("--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection")
    agent_pack_doctor.add_argument("--project", help="project name; defaults to sourcebrief use selection")
    agent_pack_doctor.add_argument("--project-id", help="advanced: project ID; defaults to sourcebrief use selection")
    agent_pack_doctor.add_argument("--query", help="optional MCP context smoke-test query")
    agent_pack_doctor.add_argument("--runtime", default="hermes", choices=["api", "hermes", "claude", "codex", "cursor"])
    agent_pack_doctor.add_argument("--resource-id", action="append")
    agent_pack_doctor.add_argument("--top-k", type=int, default=3)
    agent_pack_doctor.set_defaults(func=cmd_agent_pack_doctor)

    agents = sub.add_parser("agent", help="agent registry commands").add_subparsers(dest="agent_command")
    agent_list = agents.add_parser("list", help="list project agents in a workspace")
    agent_list.add_argument("--workspace", help="workspace name or slug")
    agent_list.add_argument("--workspace-id", help="advanced: workspace ID")
    agent_list.set_defaults(func=cmd_agent_list)

    agent_profile = agents.add_parser("profile", help="show one project agent profile")
    agent_profile.add_argument("--workspace", help="workspace name or slug")
    agent_profile.add_argument("--workspace-id", help="advanced: workspace ID")
    agent_profile.add_argument("--project", help="project name")
    agent_profile.add_argument("--project-id", help="advanced: project ID")
    agent_profile.set_defaults(func=cmd_agent_profile)

    search = sub.add_parser("search", help="search project context")
    search.add_argument("--workspace", help="workspace name or slug; defaults to sourcebrief use selection")
    search.add_argument("--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection")
    search.add_argument("--project", help="project name; defaults to sourcebrief use selection")
    search.add_argument("--project-id", help="advanced: project ID; defaults to sourcebrief use selection")
    search.add_argument("--query", required=True)
    search.add_argument("--resource-id", action="append")
    search.add_argument("--resource", action="append", help="resource ID or unambiguous resource ref/name")
    search.add_argument("--top-k", type=int, default=10)
    search.set_defaults(func=cmd_search)

    ask = sub.add_parser(
        "ask",
        help="ask SourceBrief for cited project context",
        description="Ask SourceBrief for cited context. Workspace/project can come from explicit flags or `sourcebrief use`.",
    )
    ask.add_argument("query", help="question to answer from cited project evidence")
    ask.add_argument("--json", action="store_true", help="print the full agent-context packet for this ask")
    ask.add_argument("--workspace", help="workspace name or slug; overrides saved sourcebrief use value")
    ask.add_argument("--workspace-id", help="advanced: workspace ID; overrides saved sourcebrief use value")
    ask.add_argument("--project", help="project name; overrides saved sourcebrief use value")
    ask.add_argument("--project-id", help="advanced: project ID; overrides saved sourcebrief use value")
    ask.add_argument("--runtime", default="api", choices=["api", "hermes", "claude", "codex", "cursor"])
    ask.add_argument("--resource-id", action="append")
    ask.add_argument("--resource", action="append", help="resource ID or unambiguous resource ref/name")
    ask.add_argument("--top-k", type=int, default=8)
    ask.add_argument("--max-chars", type=int, default=12000)
    ask.add_argument("--review-bundle-out", help="write an opt-in self-improvement review bundle JSON for this answer")
    ask.add_argument("--no-code-symbols", dest="include_code_symbols", action="store_false")
    ask.set_defaults(func=cmd_ask, include_code_symbols=True)

    agent = sub.add_parser("agent-context", help="request runtime-shaped context")
    agent.add_argument("--workspace", help="workspace name or slug; defaults to sourcebrief use selection")
    agent.add_argument("--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection")
    agent.add_argument("--project", help="project name; defaults to sourcebrief use selection")
    agent.add_argument("--project-id", help="advanced: project ID; defaults to sourcebrief use selection")
    agent.add_argument("--query", required=True)
    agent.add_argument("--runtime", default="api", choices=["api", "hermes", "claude", "codex", "cursor"])
    agent.add_argument("--resource-id", action="append")
    agent.add_argument("--resource", action="append", help="resource ID or unambiguous resource ref/name")
    agent.add_argument("--top-k", type=int, default=8)
    agent.add_argument("--max-chars", type=int, default=12000)
    agent.add_argument("--no-code-symbols", dest="include_code_symbols", action="store_false")
    agent.add_argument("--no-answer", dest="include_answer", action="store_false", help="return raw context without synthesized answer metadata")
    agent.set_defaults(func=cmd_agent_context, include_code_symbols=True, include_answer=True)

    mcp = sub.add_parser("mcp-context", help="call the central MCP context tool")
    mcp.add_argument("--workspace", help="workspace name or slug; defaults to sourcebrief use selection")
    mcp.add_argument("--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection")
    mcp.add_argument("--project", help="project name; defaults to sourcebrief use selection")
    mcp.add_argument("--project-id", help="advanced: project ID; defaults to sourcebrief use selection")
    mcp.add_argument("--query", required=True)
    mcp.add_argument("--runtime", default="api", choices=["api", "hermes", "claude", "codex", "cursor"])
    mcp.add_argument("--resource-id", action="append")
    mcp.add_argument("--resource", action="append", help="resource ID or unambiguous resource ref/name")
    mcp.add_argument("--top-k", type=int, default=8)
    mcp.set_defaults(func=cmd_mcp_context)

    review = sub.add_parser("review", help="self-improvement review bundle commands").add_subparsers(dest="review_command")
    review_pr_bundle = review.add_parser("pr-bundle", help="create a review bundle from GitHub PR metadata")
    review_pr_bundle.add_argument("--repo", help="GitHub repository in owner/name form; required unless fixture includes repo")
    review_pr_bundle.add_argument("--pr", type=int, help="GitHub pull request number; required unless --metadata-fixture is used")
    review_pr_bundle.add_argument("--metadata-fixture", help="local PR metadata JSON fixture for offline/dry-run bundle creation")
    review_pr_bundle.add_argument("--workspace", "--workspace-id", dest="workspace_id", metavar="WORKSPACE", default="github", help="workspace name/slug or advanced ID to record in the bundle scope")
    review_pr_bundle.add_argument("--project", "--project-id", dest="project_id", metavar="PROJECT", default="github-pr", help="project name or advanced ID to record in the bundle scope")
    review_pr_bundle.add_argument("--reviewer-backend", default="local", choices=["local", "mock"])
    review_pr_bundle.add_argument("--bundle-out", required=True, help="write the sourcebrief.review-bundle.v1 PR bundle to this path")
    review_pr_bundle.set_defaults(func=cmd_review_pr_bundle)
    review_run = review.add_parser("run", help="run a local reviewer over a review bundle")
    review_run.add_argument("--bundle", required=True, help="path to a sourcebrief.review-bundle.v1 JSON file")
    review_run.add_argument("--report-out", help="write the sourcebrief.review-report.v1 JSON report to this path")
    review_run.add_argument("--backend", default="local", choices=["local", "deterministic", "mock"])
    review_run.add_argument("--allow-incomplete", action="store_true", help="diagnose incomplete/redacted bundles instead of failing closed")
    review_run.set_defaults(func=cmd_review_run)
    review_propose = review.add_parser("propose", help="create a regression proposal from a reviewer report finding")
    review_propose.add_argument("--report", required=True, help="path to a sourcebrief.review-report.v1 JSON file")
    review_propose.add_argument("--finding-id", help="specific proposal-eligible finding id; defaults to the first candidate")
    review_propose.add_argument("--proposal-out", help="write the sourcebrief.regression-proposal.v1 artifact to this path")
    review_propose.add_argument("--owner", default="unassigned")
    review_propose.set_defaults(func=cmd_review_propose)
    review_gate = review.add_parser("gate", help="validate a regression proposal with the deterministic MVP gate")
    review_gate.add_argument("--proposal", required=True, help="path to a sourcebrief.regression-proposal.v1 JSON file")
    review_gate.add_argument("--result-out", help="write the sourcebrief.validation-gate-result.v1 artifact to this path")
    review_gate.set_defaults(func=cmd_review_gate)
    review_stage = review.add_parser("stage", help="stage an accepted proposal as a human-reviewable patch and receipt")
    review_stage.add_argument("--proposal", required=True, help="path to a sourcebrief.regression-proposal.v1 JSON file")
    review_stage.add_argument("--gate-result", required=True, help="path to an accepted sourcebrief.validation-gate-result.v1 JSON file")
    review_stage.add_argument("--out-dir", required=True, help="directory where staged artifacts should be written")
    review_stage.set_defaults(func=cmd_review_stage)
    review_history = review.add_parser("history", help="inspect local self-improvement artifact history").add_subparsers(dest="history_command")
    review_history_list = review_history.add_parser("list", help="list review bundles, reports, proposals, gates, and staged receipts")
    review_history_list.add_argument("--dir", required=True, help="artifact directory to scan recursively")
    review_history_list.set_defaults(func=cmd_review_history_list)
    review_history_show = review_history.add_parser("show", help="show one redacted history artifact by id or relative path")
    review_history_show.add_argument("artifact", help="artifact id or path relative to --dir")
    review_history_show.add_argument("--dir", required=True, help="artifact directory to scan recursively")
    review_history_show.set_defaults(func=cmd_review_history_show)
    review_mvp_smoke = review.add_parser("mvp-smoke", help="run the local end-to-end self-improvement MVP smoke path")
    review_mvp_smoke.add_argument("--bundle", help="review bundle fixture/path; defaults to the public unsupported-claim golden bundle")
    review_mvp_smoke.add_argument("--finding-id", help="specific proposal-eligible finding id; defaults to first candidate")
    review_mvp_smoke.add_argument("--owner", default="qa")
    review_mvp_smoke.add_argument("--out-dir", required=True, help="directory where smoke artifacts should be written")
    review_mvp_smoke.set_defaults(func=cmd_review_mvp_smoke)
    review_sleep = review.add_parser("sleep", help="dry-run recurring-learning mining over bounded review artifacts")
    review_sleep.add_argument("--dir", required=True, help="directory of review/proposal artifacts to scan recursively")
    review_sleep.add_argument("--out-dir", help="write dry-run candidate proposal/gate artifacts to this directory")
    review_sleep.add_argument("--summary-out", help="write the sourcebrief.sleep-replay-summary.v1 artifact")
    review_sleep.add_argument("--min-occurrences", type=int, default=2)
    review_sleep.add_argument("--max-artifacts", type=int, default=100)
    review_sleep.set_defaults(func=cmd_review_sleep)

    runtime = sub.add_parser("runtime", help="agent runtime install and validation commands").add_subparsers(dest="runtime_command")
    runtime_plan = runtime.add_parser("plan", help="generate a dry-run runtime install plan")
    runtime_plan.add_argument("--workspace", help="workspace name or slug; defaults to sourcebrief use selection")
    runtime_plan.add_argument("--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection")
    runtime_plan.add_argument("--project", help="project name; defaults to sourcebrief use selection")
    runtime_plan.add_argument("--project-id", help="advanced: project ID; defaults to sourcebrief use selection")
    runtime_plan.add_argument("--target", required=True, choices=["hermes", "claude", "codex"])
    runtime_plan.add_argument("--public-api-url")
    runtime_plan.add_argument("--server-name")
    runtime_plan.add_argument("--resource-id", action="append")
    runtime_plan.add_argument("--no-optional-tools", dest="include_optional_tools", action="store_false")
    runtime_plan.set_defaults(func=cmd_runtime_plan, include_optional_tools=True)

    runtime_setup = runtime.add_parser("setup", help="guided dry-run runtime setup; never writes local config")
    runtime_setup.add_argument("target", choices=["hermes"])
    runtime_setup.add_argument("--workspace", help="workspace name or slug; defaults to sourcebrief use selection")
    runtime_setup.add_argument("--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection")
    runtime_setup.add_argument("--project", help="project name; defaults to sourcebrief use selection")
    runtime_setup.add_argument("--project-id", help="advanced: project ID; defaults to sourcebrief use selection")
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

    skills = sub.add_parser("skill", help="project skill-pack export and local install commands").add_subparsers(dest="skill_command")
    skill_export = skills.add_parser("export", help="generate a project-specific Hermes skill package")
    skill_export.add_argument("--workspace", help="workspace name or slug; defaults to sourcebrief use selection")
    skill_export.add_argument("--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection")
    skill_export.add_argument("--project", help="project name; defaults to sourcebrief use selection")
    skill_export.add_argument("--project-id", help="advanced: project ID; defaults to sourcebrief use selection")
    skill_export.add_argument("--pack-key", default="default")
    skill_export.add_argument("--pack-version", help="published context pack version; defaults to current")
    skill_export.add_argument("--title", default="SourceBrief runtime skill")
    skill_export.add_argument("--summary")
    skill_export.add_argument("--approve-comment", help="approve the generated export with this review comment")
    skill_export.add_argument("--out", help="write package files to this local directory")
    skill_export.add_argument("--force", action="store_true", help="overwrite existing files when writing --out")
    skill_export.set_defaults(func=cmd_skill_export)

    skill_install_parser = skills.add_parser("install", help="dry-run or apply a local Hermes skill package")
    skill_install_parser.add_argument("--package", required=True, help="package directory or .zip from sourcebrief skill export")
    skill_install_parser.add_argument("--target", default="hermes", choices=["hermes"])
    skill_install_parser.add_argument("--profile", default="default", help="Hermes profile name; non-default profiles must be explicit")
    skill_install_parser.add_argument("--skills-dir", help="override Hermes skills directory; defaults to profile skills dir")
    skill_install_parser.add_argument("--name", help="installed skill name; defaults to sourcebrief-<pack-key>")
    skill_install_parser.add_argument("--receipt", help="receipt output path")
    skill_install_parser.add_argument("--dry-run", action="store_true")
    skill_install_parser.add_argument("--apply", action="store_true")
    skill_install_parser.add_argument("--force", action="store_true", help="overwrite differing existing files")
    skill_install_parser.set_defaults(func=cmd_skill_install)

    skill_uninstall = skills.add_parser("uninstall", help="remove an installed SourceBrief skill using its receipt")
    skill_uninstall.add_argument("--receipt", required=True)
    skill_uninstall.add_argument("--force", action="store_true", help="remove even when installed files changed")
    skill_uninstall.set_defaults(func=cmd_skill_uninstall)

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
        if command == "ask" and "answer" in data:
            print(f"Question: {data.get('query')}")
            print(f"Answer: {data.get('answer')}")
            if data.get("outcome"):
                print(f"Outcome: {data.get('outcome')}")
            if data.get("abstention_reason"):
                print(f"Abstention reason: {data.get('abstention_reason')}")
            if data.get("unsupported_claim_terms"):
                print("Unsupported claim terms: " + ", ".join(str(term) for term in data.get("unsupported_claim_terms", [])))
            print(f"Confidence: {data.get('confidence')}")
            citations = data.get("citations_used") or []
            if citations:
                print("Citations:")
                for citation in citations:
                    print(f"- {citation.get('label')} {citation.get('path')} score={citation.get('score')}")
            if data.get("missing_evidence"):
                print("Missing evidence / warnings:")
                for warning in data.get("missing_evidence", []):
                    print(f"- {warning}")
            if data.get("review_bundle"):
                print(f"Review bundle: {(data.get('review_bundle') or {}).get('path')}")
            print(data.get("raw_packet_hint"))
            return
        if command == "quickstart-demo" and data.get("status") == "indexed_and_ready_for_retrieval":
            print("Quickstart demo: indexed and ready for retrieval")
            print(f"  workspace: {data.get('workspace_name')}")
            print(f"  project: {data.get('project_name')}")
            print(f"  resource: {data.get('resource_name')}")
            print(f"  saved_defaults: {data.get('config_path')}")
            print(f"  index_status: {(data.get('index_run') or {}).get('status')}")
            if data.get("mcp_validation"):
                print(f"  mcp_validation: {(data.get('mcp_validation') or {}).get('status')}")
            answer = data.get("answer") or {}
            print(f"Answer: {answer.get('answer')}")
            if data.get("review_bundle"):
                print(f"  review_bundle: {(data.get('review_bundle') or {}).get('path')}")
            print("Citations:")
            for citation in answer.get("citations_used", []):
                print(f"- {citation.get('label')} {citation.get('path')} score={citation.get('score')}")
            print("Next:")
            print(f"- {data.get('next_command')}")
            print(f"- {data.get('cleanup')}")
            return
        if command in {"agent-context", "mcp-context", "ask", "agent", "agent-pack", "token", "runtime", "skill", "use", "status", "doctor", "login", "logout"}:
            _print_json(data)
            return
    _print_json(data)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args._sourcebrief_argv = list(argv) if argv is not None else sys.argv[1:]
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
        _resolve_email(args)
        _resolve_auth(args, config)
        _apply_selected_defaults(args, config)
    except SourceBriefCliError as exc:
        print(f"sourcebrief: error: {exc}", file=sys.stderr)
        return 1
    client = SourceBriefClient(args.api_url, args.email, token=args.token)
    try:
        _maybe_session_login(client, args)
        if not _agent_pack_doctor_package_only(args):
            _resolve_named_scope(client, args, getattr(args, "_sourcebrief_config", {}) or {})
        data = args.func(client, args)
    except (SourceBriefCliError, runtime_apply.RuntimeApplyError, skill_install.SkillInstallError, RegressionProposalError) as exc:
        print(f"sourcebrief: error: {exc}", file=sys.stderr)
        return 1
    exit_code = 1 if args.command in {"doctor", "agent-pack"} and isinstance(data, dict) and data.get("status") in {"failed", "incomplete"} else 0
    if args.json:
        _print_json(data)
    else:
        _print_default(args.command, data)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
