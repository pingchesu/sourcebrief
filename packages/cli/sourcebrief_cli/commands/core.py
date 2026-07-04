from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

CommandHandler = Callable[[Any, argparse.Namespace], Any]


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
