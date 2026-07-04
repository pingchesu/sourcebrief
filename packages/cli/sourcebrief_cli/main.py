from __future__ import annotations

import argparse
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
from sourcebrief_cli.commands import admin as admin_commands
from sourcebrief_cli.commands import context as context_commands
from sourcebrief_cli.commands import core as core_commands
from sourcebrief_cli.commands import review as review_commands
from sourcebrief_cli.commands import runtime as runtime_commands
from sourcebrief_cli.commands import skill as skill_commands
from sourcebrief_cli.config import (
    config_path as _config_path,
)
from sourcebrief_cli.config import (
    load_cli_config as _load_cli_config,
)
from sourcebrief_cli.config import (
    save_cli_config as _save_cli_config,
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
_first_env = cli_auth.first_env
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
_add_common_resource_args = cli_support.add_common_resource_args
_print_default = cli_support.print_default
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
                mcp = context_commands.cmd_mcp_context(client, args)
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

    core_commands.register_core_commands(
        sub,
        config_path=str(_config_path()),
        health_command=core_commands.cmd_health,
        use_command=core_commands.cmd_use,
        status_command=core_commands.cmd_status,
        login_command=core_commands.cmd_login,
        logout_command=core_commands.cmd_logout,
        quickstart_demo_command=cmd_quickstart_demo,
        doctor_command=cmd_doctor,
    )

    admin_commands.register_workspace_project_token_agent_commands(
        sub,
        workspace_create_command=cmd_workspace_create,
        project_create_command=cmd_project_create,
        token_create_command=cmd_token_create,
        token_create_runtime_command=cmd_token_create_runtime,
        token_list_command=cmd_token_list,
        token_revoke_command=cmd_token_revoke,
        agent_list_command=cmd_agent_list,
        agent_profile_command=cmd_agent_profile,
    )

    cli_resources.register_resource_commands(sub)

    agent_pack_doctor.register_agent_pack_commands(sub, doctor_command=cmd_agent_pack_doctor)

    context_commands.register_context_commands(
        sub,
        search_command=context_commands.cmd_search,
        ask_command=context_commands.cmd_ask,
        agent_context_command=context_commands.cmd_agent_context,
        mcp_context_command=context_commands.cmd_mcp_context,
    )

    review_commands.register_review_commands(
        sub,
        pr_bundle_command=cmd_review_pr_bundle,
        run_command=cmd_review_run,
        propose_command=cmd_review_propose,
        gate_command=cmd_review_gate,
        stage_command=cmd_review_stage,
        history_list_command=cmd_review_history_list,
        history_show_command=cmd_review_history_show,
        mvp_smoke_command=cmd_review_mvp_smoke,
        sleep_command=cmd_review_sleep,
    )

    runtime_commands.register_runtime_commands(
        sub,
        plan_command=runtime_commands.cmd_runtime_plan,
        setup_command=runtime_commands.cmd_runtime_setup,
        detect_command=runtime_commands.cmd_runtime_detect,
        apply_command=runtime_commands.cmd_runtime_apply,
        rollback_command=runtime_commands.cmd_runtime_rollback,
        validate_command=runtime_commands.cmd_runtime_validate,
    )

    skill_commands.register_skill_commands(
        sub,
        export_command=skill_commands.cmd_skill_export,
        install_command=skill_commands.cmd_skill_install,
        uninstall_command=skill_commands.cmd_skill_uninstall,
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
