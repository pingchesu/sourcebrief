from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from sourcebrief_cli import support as cli_support
from sourcebrief_cli.client import SourceBriefClient, SourceBriefCliError
from sourcebrief_cli.scope import require_scope

CONTEXT_RUNTIME_SCOPES = ["project:read", "project:query", "resource:read", "review:read"]
READ_CODE_RUNTIME_SCOPES = [*CONTEXT_RUNTIME_SCOPES, "code:read"]

CommandHandler = Callable[[Any, argparse.Namespace], Any]


def cmd_workspace_create(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    return client.request(
        "POST",
        "/workspaces",
        body={"name": args.name, "slug": args.slug},
        expected={201},
    )


def cmd_project_create(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    require_scope(args, project=False)
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects",
        body={"name": args.name, "description": args.description},
        expected={201},
    )


def cmd_token_create(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    require_scope(args, project=False)
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/api-tokens",
        body={
            "name": args.name,
            "scopes": cli_support.split_csv_or_repeated(args.scope) or [],
            "allowed_project_ids": cli_support.split_csv_or_repeated(args.project_id),
            "allowed_resource_ids": cli_support.split_csv_or_repeated(args.resource_id),
            "expires_at": args.expires_at,
        },
        expected={201},
    )


def cmd_token_create_runtime(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    require_scope(args, project=False)
    allowed_project_ids = cli_support.split_csv_or_repeated(args.project_id)
    allowed_resource_ids = cli_support.split_csv_or_repeated(args.resource_id)
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
    require_scope(args, project=False)
    return client.request("GET", f"/workspaces/{args.workspace_id}/api-tokens")


def cmd_token_revoke(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    require_scope(args, project=False)
    return client.request("DELETE", f"/workspaces/{args.workspace_id}/api-tokens/{args.token_id}")




def cmd_agent_list(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    require_scope(args, project=False)
    return client.request("GET", f"/workspaces/{args.workspace_id}/agents")


def cmd_agent_profile(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    require_scope(args)
    return client.request(
        "GET",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/agent-profile",
    )




def register_workspace_project_token_agent_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    *,
    workspace_create_command: CommandHandler,
    project_create_command: CommandHandler,
    token_create_command: CommandHandler,
    token_create_runtime_command: CommandHandler,
    token_list_command: CommandHandler,
    token_revoke_command: CommandHandler,
    agent_list_command: CommandHandler,
    agent_profile_command: CommandHandler,
) -> None:
    ws = subparsers.add_parser("workspace", help="workspace commands").add_subparsers(dest="workspace_command")
    ws_create = ws.add_parser("create", help="create a workspace")
    ws_create.add_argument("--name", required=True)
    ws_create.add_argument("--slug", required=True)
    ws_create.set_defaults(func=workspace_create_command)

    projects = subparsers.add_parser("project", help="project commands").add_subparsers(dest="project_command")
    project_create = projects.add_parser("create", help="create a project")
    project_create.add_argument("--workspace", help="workspace name or slug")
    project_create.add_argument("--workspace-id", help="advanced: workspace ID")
    project_create.add_argument("--name", required=True)
    project_create.add_argument("--description")
    project_create.set_defaults(func=project_create_command)

    tokens = subparsers.add_parser("token", help="workspace API token commands").add_subparsers(dest="token_command")
    token_create = tokens.add_parser("create", help="create a bearer API token for agents/Hermes")
    token_create.add_argument("--workspace", help="workspace name or slug")
    token_create.add_argument("--workspace-id", help="advanced: workspace ID")
    token_create.add_argument("--name", required=True)
    token_create.add_argument("--scope", action="append", required=True, help="scope, repeatable or comma-separated")
    token_create.add_argument("--project", dest="project_ref", action="append", help="allowed project name, repeatable")
    token_create.add_argument("--project-id", action="append", help="advanced: allowed project ID, repeatable or comma-separated")
    token_create.add_argument("--resource-id", action="append", help="allowed resource ID, repeatable or comma-separated")
    token_create.add_argument("--expires-at", help="ISO-8601 timestamp")
    token_create.set_defaults(func=token_create_command)

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
    token_runtime.set_defaults(func=token_create_runtime_command, read_code=False)

    token_list = tokens.add_parser("list", help="list API tokens without plaintext secrets")
    token_list.add_argument("--workspace", help="workspace name or slug")
    token_list.add_argument("--workspace-id", help="advanced: workspace ID")
    token_list.set_defaults(func=token_list_command)

    token_revoke = tokens.add_parser("revoke", help="revoke an API token")
    token_revoke.add_argument("--workspace", help="workspace name or slug")
    token_revoke.add_argument("--workspace-id", help="advanced: workspace ID")
    token_revoke.add_argument("--token-id", required=True)
    token_revoke.set_defaults(func=token_revoke_command)

    agents = subparsers.add_parser("agent", help="agent registry commands").add_subparsers(dest="agent_command")
    agent_list = agents.add_parser("list", help="list project agents in a workspace")
    agent_list.add_argument("--workspace", help="workspace name or slug")
    agent_list.add_argument("--workspace-id", help="advanced: workspace ID")
    agent_list.set_defaults(func=agent_list_command)

    agent_profile = agents.add_parser("profile", help="show one project agent profile")
    agent_profile.add_argument("--workspace", help="workspace name or slug")
    agent_profile.add_argument("--workspace-id", help="advanced: workspace ID")
    agent_profile.add_argument("--project", help="project name")
    agent_profile.add_argument("--project-id", help="advanced: project ID")
    agent_profile.set_defaults(func=agent_profile_command)
