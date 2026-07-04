from __future__ import annotations

import argparse
import time
from collections.abc import Callable
from typing import Any

from sourcebrief_cli import auth as cli_auth
from sourcebrief_cli import resources as cli_resources
from sourcebrief_cli import support as cli_support
from sourcebrief_cli.client import SourceBriefClient, SourceBriefCliError
from sourcebrief_cli.commands import context as context_commands
from sourcebrief_cli.config import (
    SESSION_EMAIL_CONFIG_KEY,
    SESSION_TOKEN_CONFIG_KEY,
)
from sourcebrief_cli.config import (
    config_path as _config_path,
)
from sourcebrief_cli.config import (
    save_cli_config as _save_cli_config,
)
from sourcebrief_cli.config import (
    selected_value as _selected_value,
)

CommandHandler = Callable[[Any, argparse.Namespace], Any]


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


def cmd_login(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    email = getattr(args, "login_email", None) or cli_auth.env_login_email(args)
    if not email:
        raise SourceBriefCliError("login requires --email or SOURCEBRIEF_ADMIN_EMAIL/SOURCEBRIEF_EMAIL")
    password = cli_auth.login_password_from_args(args)
    login_client = type(client)(args.api_url, email, token=None)
    session_token = cli_auth.login_with_password(login_client, email, password)
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


def cmd_doctor(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    checks: list[dict[str, Any]] = []
    try:
        health = client.request("GET", "/readyz")
        checks.append(cli_support.check_result("api", "passed", api_url=args.api_url.rstrip("/"), response=health))
    except SourceBriefCliError as exc:
        checks.append(cli_support.check_result("api", "failed", api_url=args.api_url.rstrip("/"), error=str(exc)))

    auth_mode = getattr(args, "_auth_mode", "bearer_token" if args.token else "email_header")
    checks.append(
        cli_support.check_result(
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
            checks.append(cli_support.check_result("project", "passed", workspace_id=args.workspace_id, project_id=args.project_id, resource_count=len(resources) if isinstance(resources, list) else None))
        except SourceBriefCliError as exc:
            checks.append(cli_support.check_result("project", "failed", workspace_id=args.workspace_id, project_id=args.project_id, error=str(exc)))
        if args.query:
            try:
                mcp = context_commands.cmd_mcp_context(client, args)
                error = cli_support.mcp_error_message(mcp)
                if error:
                    checks.append(cli_support.check_result("mcp_context", "failed", query=args.query, error=error))
                elif getattr(args, "require_citations", False):
                    citation_count = cli_support.mcp_citation_count(mcp)
                    if citation_count <= 0:
                        checks.append(cli_support.check_result("mcp_context", "failed", query=args.query, error="MCP smoke returned no citations", citation_count=citation_count))
                    else:
                        checks.append(cli_support.check_result("mcp_context", "passed", query=args.query, has_result=bool(mcp), citation_count=citation_count))
                else:
                    checks.append(cli_support.check_result("mcp_context", "passed", query=args.query, has_result=bool(mcp)))
            except SourceBriefCliError as exc:
                checks.append(cli_support.check_result("mcp_context", "failed", query=args.query, error=str(exc)))
    else:
        next_step = 'run `sourcebrief use --workspace "..." --project "..."` or rerun doctor with --workspace "..." --project "..."'
        checks.append(
            cli_support.check_result(
                "project",
                "warning",
                message=f"workspace/project not selected; {next_step}",
            )
        )
        if args.query:
            checks.append(
                cli_support.check_result(
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
    resource_result = cli_resources.cmd_resource_add_doc(
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
    answer_packet = context_commands.cmd_agent_context(
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
        mcp_response = context_commands.cmd_mcp_context(
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
        error = cli_support.mcp_error_message(mcp_response)
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
        review_bundle = cli_support.capture_review_bundle(
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
        "answer": cli_support.human_answer_brief(answer_packet),
        "next_command": 'sourcebrief ask --resource "Payment retry runbook" "What should an operator do when payment retries fail?"',
        "cleanup": "Delete the demo workspace from the web console when finished, or keep it for CLI experiments.",
    }
    if review_bundle:
        result["review_bundle"] = review_bundle
    return result





def register_core_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    *,
    config_path: str,
    health_command: CommandHandler,
    use_command: CommandHandler,
    status_command: CommandHandler,
    login_command: CommandHandler,
    logout_command: CommandHandler,
    quickstart_demo_command: CommandHandler,
    doctor_command: CommandHandler,
) -> None:
    health = subparsers.add_parser("health", help="check API readiness")
    health.set_defaults(func=health_command)

    use = subparsers.add_parser(
        "use",
        help="save default workspace/project for later read/query commands",
        description=f"Save CLI defaults in {config_path}. Explicit flags still override saved values.",
    )
    use.add_argument("--workspace", help="workspace name or slug to save; changing it without --project clears the saved project")
    use.add_argument("--workspace-id", help="advanced: workspace ID to save; changing it without --project-id clears the saved project")
    use.add_argument("--project", help="project name to save")
    use.add_argument("--project-id", help="advanced: project ID to save")
    use.add_argument("--clear", action="store_true", help="clear saved workspace/project before applying new values")
    use.set_defaults(func=use_command)

    status = subparsers.add_parser("status", help="show selected CLI defaults and auth mode without secrets")
    status.set_defaults(func=status_command)

    login = subparsers.add_parser("login", help="log in with email/password and save a session token")
    login.add_argument("--email", dest="login_email", help="login email; defaults to SOURCEBRIEF_ADMIN_EMAIL/SOURCEBRIEF_EMAIL")
    login.add_argument("--password-env", help="name of an environment variable containing the password; otherwise prompts")
    login.set_defaults(func=login_command)

    logout = subparsers.add_parser("logout", help="remove the saved SourceBrief session token")
    logout.set_defaults(func=logout_command)

    quickstart = subparsers.add_parser(
        "quickstart-demo",
        help="run a one-command local demo that ends with a cited human answer",
    )
    quickstart.add_argument("--workspace-name", default="SourceBrief CLI Demo")
    quickstart.add_argument("--project-name", default="First useful moment")
    quickstart.add_argument("--slug", help="workspace slug; defaults to a timestamped sourcebrief-demo-* slug")
    quickstart.add_argument("--timeout", type=int, default=120, help="seconds to wait for indexing")
    quickstart.add_argument("--review-bundle-out", help="write an opt-in self-improvement review bundle JSON for the demo answer")
    quickstart.add_argument("--validate-mcp", action="store_true", help="also call the MCP context tool and report pass/fail")
    quickstart.set_defaults(func=quickstart_demo_command)

    doctor = subparsers.add_parser("doctor", help="check API/auth/project/MCP readiness")
    doctor.add_argument("--workspace", help="workspace name or slug; defaults to sourcebrief use selection")
    doctor.add_argument("--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection")
    doctor.add_argument("--project", help="project name; defaults to sourcebrief use selection")
    doctor.add_argument("--project-id", help="advanced: project ID; defaults to sourcebrief use selection")
    doctor.add_argument("--query", help="optional MCP context smoke-test query")
    doctor.add_argument("--runtime", default="api", choices=["api", "hermes", "claude", "codex", "cursor"])
    doctor.add_argument("--resource-id", action="append")
    doctor.add_argument("--top-k", type=int, default=3)
    doctor.set_defaults(func=doctor_command)
