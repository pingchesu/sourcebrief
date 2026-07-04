from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

CommandHandler = Callable[[Any, argparse.Namespace], Any]


def register_skill_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    *,
    export_command: CommandHandler,
    install_command: CommandHandler,
    uninstall_command: CommandHandler,
) -> None:
    skills = subparsers.add_parser(
        "skill", help="project skill-pack export and local install commands"
    ).add_subparsers(dest="skill_command")

    skill_export = skills.add_parser(
        "export", help="generate a project-specific Hermes skill package"
    )
    skill_export.add_argument(
        "--workspace", help="workspace name or slug; defaults to sourcebrief use selection"
    )
    skill_export.add_argument(
        "--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection"
    )
    skill_export.add_argument(
        "--project", help="project name; defaults to sourcebrief use selection"
    )
    skill_export.add_argument(
        "--project-id", help="advanced: project ID; defaults to sourcebrief use selection"
    )
    skill_export.add_argument("--pack-key", default="default")
    skill_export.add_argument("--pack-version", help="published context pack version; defaults to current")
    skill_export.add_argument("--title", default="SourceBrief runtime skill")
    skill_export.add_argument("--summary")
    skill_export.add_argument(
        "--approve-comment", help="approve the generated export with this review comment"
    )
    skill_export.add_argument("--out", help="write package files to this local directory")
    skill_export.add_argument(
        "--force", action="store_true", help="overwrite existing files when writing --out"
    )
    skill_export.set_defaults(func=export_command)

    skill_install_parser = skills.add_parser(
        "install", help="dry-run or apply a local Hermes skill package"
    )
    skill_install_parser.add_argument(
        "--package", required=True, help="package directory or .zip from sourcebrief skill export"
    )
    skill_install_parser.add_argument("--target", default="hermes", choices=["hermes"])
    skill_install_parser.add_argument(
        "--profile", default="default", help="Hermes profile name; non-default profiles must be explicit"
    )
    skill_install_parser.add_argument(
        "--skills-dir", help="override Hermes skills directory; defaults to profile skills dir"
    )
    skill_install_parser.add_argument(
        "--name", help="installed skill name; defaults to sourcebrief-<pack-key>"
    )
    skill_install_parser.add_argument("--receipt", help="receipt output path")
    skill_install_parser.add_argument("--dry-run", action="store_true")
    skill_install_parser.add_argument("--apply", action="store_true")
    skill_install_parser.add_argument(
        "--force", action="store_true", help="overwrite differing existing files"
    )
    skill_install_parser.set_defaults(func=install_command)

    skill_uninstall = skills.add_parser(
        "uninstall", help="remove an installed SourceBrief skill using its receipt"
    )
    skill_uninstall.add_argument("--receipt", required=True)
    skill_uninstall.add_argument(
        "--force", action="store_true", help="remove even when installed files changed"
    )
    skill_uninstall.set_defaults(func=uninstall_command)
