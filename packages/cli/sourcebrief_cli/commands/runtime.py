from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

CommandHandler = Callable[[Any, argparse.Namespace], Any]


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
