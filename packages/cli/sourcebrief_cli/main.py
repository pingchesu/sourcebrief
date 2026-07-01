from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Literal

from sourcebrief_cli import agent_pack_doctor, runtime_apply, skill_install
from sourcebrief_cli import auth as cli_auth
from sourcebrief_cli import resources as cli_resources
from sourcebrief_cli import scope as cli_scope
from sourcebrief_cli import support as cli_support
from sourcebrief_cli.client import SourceBriefClient, SourceBriefCliError
from sourcebrief_cli.config import (
    SESSION_EMAIL_CONFIG_KEY,
    SESSION_TOKEN_CONFIG_KEY,
)
from sourcebrief_cli.config import (
    config_path as _config_path,
)
from sourcebrief_cli.config import (
    load_cli_config as _load_cli_config,
)
from sourcebrief_cli.config import (
    save_cli_config as _save_cli_config,
)
from sourcebrief_cli.config import (
    selected_value as _selected_value,
)
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

DEFAULT_API_URL = cli_scope.DEFAULT_API_URL
DEFAULT_EMAIL = cli_scope.DEFAULT_EMAIL
CONTEXT_RUNTIME_SCOPES = ["project:read", "project:query", "resource:read", "review:read"]
READ_CODE_RUNTIME_SCOPES = [*CONTEXT_RUNTIME_SCOPES, "code:read"]

_dotenv_path = cli_auth.dotenv_path
_dotenv_value = cli_auth.dotenv_value
_env_login_email = cli_auth.env_login_email
_env_login_password = cli_auth.env_login_password
_first_env = cli_auth.first_env
_login_with_password = cli_auth.login_with_password
_login_password_from_args = cli_auth.login_password_from_args
_resolve_auth = cli_auth.resolve_auth
_casefold = cli_scope.casefold
_matches_workspace_selector = cli_scope.matches_workspace_selector
_matches_project_selector = cli_scope.matches_project_selector
_workspace_candidate = cli_scope.workspace_candidate
_project_candidate = cli_scope.project_candidate
_resolve_workspace_selector = cli_scope.resolve_workspace_selector
_resolve_project_selector = cli_scope.resolve_project_selector
_resolve_named_scope = cli_scope.resolve_named_scope
_command_uses_selected_scope = cli_scope.command_uses_selected_scope
_apply_selected_defaults = cli_scope.apply_selected_defaults
_resolve_api_url = cli_scope.resolve_api_url
_resolve_email = cli_scope.resolve_email
_require_scope = cli_scope.require_scope
_print_json = cli_support.print_json
_print_kv = cli_support.print_kv
_resource_ids = cli_support.resource_ids
_resource_refs = cli_support.resource_refs
_apply_resource_refs = cli_support.apply_resource_refs
_split_csv_or_repeated = cli_support.split_csv_or_repeated
_wait_for_run = cli_support.wait_for_run
_check_result = cli_support.check_result
_mcp_error_message = cli_support.mcp_error_message
_mcp_structured_payload = cli_support.mcp_structured_payload
_mcp_citation_count = cli_support.mcp_citation_count
_maybe_refresh = cli_support.maybe_refresh
_pick_answer_lines = cli_support.pick_answer_lines
_human_answer_brief = cli_support.human_answer_brief
_capture_review_bundle = cli_support.capture_review_bundle
_runtime_plan_request = cli_support.runtime_plan_request
_validation_preview = cli_support.validation_preview
_runtime_token_command = cli_support.runtime_token_command
_read_validated_runtime_plan = cli_support.read_validated_runtime_plan
_skill_export_generate_path = cli_support.skill_export_generate_path
_skill_export_download_url = cli_support.skill_export_download_url
_skill_profile = cli_support.skill_profile
_skill_skills_dir = cli_support.skill_skills_dir
_add_common_resource_args = cli_support.add_common_resource_args
_print_default = cli_support.print_default
sh_quote = cli_support.sh_quote
cmd_resource_add_doc = cli_resources.cmd_resource_add_doc
cmd_resource_add_repo = cli_resources.cmd_resource_add_repo
cmd_resource_add_url = cli_resources.cmd_resource_add_url
cmd_resource_add_upload = cli_resources.cmd_resource_add_upload
cmd_resource_refresh = cli_resources.cmd_resource_refresh
cmd_resource_list = cli_resources.cmd_resource_list
cmd_resource_get = cli_resources.cmd_resource_get
cmd_resource_update = cli_resources.cmd_resource_update
cmd_resource_update_git = cli_resources.cmd_resource_update_git
cmd_resource_archive = cli_resources.cmd_resource_archive
cmd_resource_delete = cli_resources.cmd_resource_delete
cmd_resource_restore = cli_resources.cmd_resource_restore
cmd_resource_purge = cli_resources.cmd_resource_purge
cmd_resource_schedule_due = cli_resources.cmd_resource_schedule_due
cmd_resource_graph = cli_resources.cmd_resource_graph








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
    cli_auth.maybe_session_login(client, args, command_uses_authenticated_api=_command_uses_authenticated_api)



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



def cmd_runtime_plan(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    return _runtime_plan_request(client, args)





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


def cmd_agent_pack_doctor(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    return agent_pack_doctor.cmd_agent_pack_doctor(client, args, remote_doctor=cmd_doctor)


def cmd_agent_list(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args, project=False)
    return client.request("GET", f"/workspaces/{args.workspace_id}/agents")


def cmd_agent_profile(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    _require_scope(args)
    return client.request(
        "GET",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/agent-profile",
    )



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

    cli_resources.register_resource_commands(sub)

    agent_pack_doctor.register_agent_pack_commands(sub, doctor_command=cmd_agent_pack_doctor)

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

    runtime_apply.register_runtime_commands(
        sub,
        plan_command=cmd_runtime_plan,
        setup_command=cmd_runtime_setup,
        detect_command=cmd_runtime_detect,
        apply_command=cmd_runtime_apply,
        rollback_command=cmd_runtime_rollback,
        validate_command=cmd_runtime_validate,
    )

    skill_install.register_skill_commands(
        sub,
        export_command=cmd_skill_export,
        install_command=cmd_skill_install,
        uninstall_command=cmd_skill_uninstall,
    )

    return parser



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
