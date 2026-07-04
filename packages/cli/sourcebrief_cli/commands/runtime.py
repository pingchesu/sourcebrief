from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sourcebrief_cli import runtime_apply
from sourcebrief_cli import support as cli_support
from sourcebrief_cli.client import SourceBriefClient, SourceBriefCliError

CommandHandler = Callable[[Any, argparse.Namespace], Any]


def cmd_runtime_plan(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    return cli_support.runtime_plan_request(client, args)


def cmd_runtime_setup(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    plan = cli_support.runtime_plan_request(client, args)
    validation = cli_support.validation_preview(plan, args.target, args.max_age_seconds)
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
        "token_command": cli_support.runtime_token_command(plan),
        "next_steps": [
            "Review the plan and generated MCP config.",
            f"Create/export a runtime token: {cli_support.runtime_token_command(plan)}",
            f"Run `sourcebrief runtime validate --plan {plan_ref} --run` after exporting SOURCEBRIEF_TOKEN.",
            f"Apply only with `sourcebrief runtime apply --plan {plan_ref} --target hermes --apply` when ready.",
        ],
    }


def cmd_runtime_detect(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    return runtime_apply.detect(runtime_apply.hermes_config_path(args.config))


def cmd_runtime_apply(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    validation = cli_support.read_validated_runtime_plan(args)
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
    validation = cli_support.read_validated_runtime_plan(args)
    return runtime_apply.validate_plan(validation, run=args.run)


def register_runtime_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    *,
    plan_command: CommandHandler,
    setup_command: CommandHandler,
    detect_command: CommandHandler,
    apply_command: CommandHandler,
    rollback_command: CommandHandler,
    validate_command: CommandHandler,
) -> None:
    runtime = subparsers.add_parser(
        "runtime", help="agent runtime install and validation commands"
    ).add_subparsers(dest="runtime_command")

    runtime_plan = runtime.add_parser("plan", help="generate a dry-run runtime install plan")
    runtime_plan.add_argument(
        "--workspace", help="workspace name or slug; defaults to sourcebrief use selection"
    )
    runtime_plan.add_argument(
        "--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection"
    )
    runtime_plan.add_argument(
        "--project", help="project name; defaults to sourcebrief use selection"
    )
    runtime_plan.add_argument(
        "--project-id", help="advanced: project ID; defaults to sourcebrief use selection"
    )
    runtime_plan.add_argument("--target", required=True, choices=["hermes", "claude", "codex"])
    runtime_plan.add_argument("--public-api-url")
    runtime_plan.add_argument("--server-name")
    runtime_plan.add_argument("--resource-id", action="append")
    runtime_plan.add_argument(
        "--no-optional-tools", dest="include_optional_tools", action="store_false"
    )
    runtime_plan.set_defaults(func=plan_command, include_optional_tools=True)

    runtime_setup = runtime.add_parser(
        "setup", help="guided dry-run runtime setup; never writes local config"
    )
    runtime_setup.add_argument("target", choices=["hermes"])
    runtime_setup.add_argument(
        "--workspace", help="workspace name or slug; defaults to sourcebrief use selection"
    )
    runtime_setup.add_argument(
        "--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection"
    )
    runtime_setup.add_argument(
        "--project", help="project name; defaults to sourcebrief use selection"
    )
    runtime_setup.add_argument(
        "--project-id", help="advanced: project ID; defaults to sourcebrief use selection"
    )
    runtime_setup.add_argument("--public-api-url")
    runtime_setup.add_argument("--server-name")
    runtime_setup.add_argument("--resource-id", action="append")
    runtime_setup.add_argument(
        "--no-optional-tools", dest="include_optional_tools", action="store_false"
    )
    runtime_setup.add_argument(
        "--dry-run",
        action="store_true",
        help="accepted for clarity; setup is always dry-run and never applies config",
    )
    runtime_setup.add_argument("--plan-out", help="write the generated plan JSON to this path")
    runtime_setup.add_argument("--max-age-seconds", type=int, default=86400)
    runtime_setup.set_defaults(func=setup_command, include_optional_tools=True)

    runtime_detect = runtime.add_parser(
        "detect", help="detect local runtime config paths without writing files"
    )
    runtime_detect.add_argument(
        "--config", help="Hermes config path; defaults to ~/.hermes/config.yaml"
    )
    runtime_detect.set_defaults(func=detect_command)

    runtime_apply_parser = runtime.add_parser(
        "apply", help="apply a validated runtime plan to Hermes config"
    )
    runtime_apply_parser.add_argument(
        "--plan", required=True, help="runtime plan JSON produced by sourcebrief runtime plan"
    )
    runtime_apply_parser.add_argument("--target", required=True, choices=["hermes"])
    runtime_apply_parser.add_argument(
        "--config", help="Hermes config path; defaults to ~/.hermes/config.yaml"
    )
    runtime_apply_parser.add_argument("--receipt", help="receipt output path")
    runtime_apply_parser.add_argument(
        "--dry-run", action="store_true", help="show planned writes without changing files"
    )
    runtime_apply_parser.add_argument(
        "--apply", action="store_true", help="perform the local config write after plan validation"
    )
    runtime_apply_parser.add_argument("--yes", action="store_true", help="deprecated alias for --apply")
    runtime_apply_parser.add_argument(
        "--max-age-seconds",
        type=int,
        default=86400,
        help="reject plans older than this; use -1 to disable",
    )
    runtime_apply_parser.set_defaults(func=apply_command)

    runtime_rollback = runtime.add_parser(
        "rollback", help="rollback a SourceBrief runtime apply receipt"
    )
    runtime_rollback.add_argument("--receipt", required=True)
    runtime_rollback.add_argument(
        "--force", action="store_true", help="restore even when current hash differs from receipt"
    )
    runtime_rollback.set_defaults(func=rollback_command)

    runtime_validate = runtime.add_parser(
        "validate", help="show or run the validator command from a runtime plan"
    )
    runtime_validate.add_argument("--plan", required=True)
    runtime_validate.add_argument("--target", default="hermes", choices=["hermes"])
    runtime_validate.add_argument(
        "--run", action="store_true", help="execute the generated validator command"
    )
    runtime_validate.add_argument("--max-age-seconds", type=int, default=86400)
    runtime_validate.set_defaults(func=validate_command)
