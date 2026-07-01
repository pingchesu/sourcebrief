from __future__ import annotations

import argparse
import os
from typing import Any

from sourcebrief_cli.auth import first_env
from sourcebrief_cli.client import SourceBriefClient, SourceBriefCliError
from sourcebrief_cli.config import selected_value

DEFAULT_API_URL = "http://localhost:18000"
DEFAULT_EMAIL = "demo@example.com"


def casefold(value: str) -> str:
    return value.strip().casefold()


def matches_workspace_selector(workspace: dict[str, Any], selector: str) -> bool:
    wanted = casefold(selector)
    return wanted in {
        casefold(str(workspace.get("id") or "")),
        casefold(str(workspace.get("name") or "")),
        casefold(str(workspace.get("slug") or "")),
    }


def matches_project_selector(project: dict[str, Any], selector: str) -> bool:
    wanted = casefold(selector)
    return wanted in {
        casefold(str(project.get("id") or "")),
        casefold(str(project.get("name") or "")),
    }


def workspace_candidate(workspace: dict[str, Any]) -> str:
    return f"{workspace.get('name')} (slug={workspace.get('slug')}, id={workspace.get('id')})"


def project_candidate(project: dict[str, Any]) -> str:
    return f"{project.get('name')} (id={project.get('id')})"


def resolve_workspace_selector(client: SourceBriefClient, selector: str) -> dict[str, Any]:
    workspaces = client.request("GET", "/workspaces")
    if not isinstance(workspaces, list):
        raise SourceBriefCliError("workspace resolver expected /workspaces to return a list")
    matches = [workspace for workspace in workspaces if isinstance(workspace, dict) and matches_workspace_selector(workspace, selector)]
    if not matches:
        raise SourceBriefCliError(f"workspace {selector!r} was not found or is not accessible")
    if len(matches) > 1:
        choices = "; ".join(workspace_candidate(workspace) for workspace in matches)
        raise SourceBriefCliError(f"workspace {selector!r} is ambiguous; choose one of: {choices}")
    return matches[0]


def resolve_project_selector(client: SourceBriefClient, workspace_id: str, selector: str) -> dict[str, Any]:
    projects = client.request("GET", f"/workspaces/{workspace_id}/projects")
    if not isinstance(projects, list):
        raise SourceBriefCliError("project resolver expected /projects to return a list")
    matches = [project for project in projects if isinstance(project, dict) and matches_project_selector(project, selector)]
    if not matches:
        raise SourceBriefCliError(f"project {selector!r} was not found or is not accessible in the selected workspace")
    if len(matches) > 1:
        choices = "; ".join(project_candidate(project) for project in matches)
        raise SourceBriefCliError(f"project {selector!r} is ambiguous in the selected workspace; choose one of: {choices}")
    return matches[0]


def resolve_named_scope(client: SourceBriefClient, args: argparse.Namespace, config: dict[str, Any]) -> None:
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
        workspace = resolve_workspace_selector(client, workspace_selector)
        args.workspace_id = str(workspace["id"])
        args._resolved_workspace_name = workspace.get("name")
        args._resolved_workspace_slug = workspace.get("slug")
    elif not getattr(args, "workspace_id", None):
        saved_workspace_id = selected_value(config, "workspace_id")
        if saved_workspace_id:
            args.workspace_id = saved_workspace_id
    if project_selector:
        if not getattr(args, "workspace_id", None):
            raise SourceBriefCliError("--project requires --workspace or a saved workspace selection")
        project = resolve_project_selector(client, str(args.workspace_id), project_selector)
        args.project_id = str(project["id"])
        args._resolved_project_name = project.get("name")
    if project_refs:
        if not getattr(args, "workspace_id", None):
            raise SourceBriefCliError("--project requires --workspace or a saved workspace selection")
        resolved_project_ids = list(getattr(args, "project_id", None) or [])
        for selector in project_refs:
            project = resolve_project_selector(client, str(args.workspace_id), selector)
            resolved_project_ids.append(str(project["id"]))
        args.project_id = resolved_project_ids


def command_uses_selected_scope(args: argparse.Namespace) -> bool:
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


def apply_selected_defaults(args: argparse.Namespace, config: dict[str, Any]) -> None:
    if not command_uses_selected_scope(args):
        return
    workspace_id_explicit = bool(args.__dict__.get("workspace_id"))
    if "workspace_id" in args.__dict__ and not args.__dict__.get("workspace_id") and not getattr(args, "workspace", None):
        args.workspace_id = selected_value(config, "workspace_id")
    if (
        "project_id" in args.__dict__
        and not args.__dict__.get("project_id")
        and args.command != "token"
        and not workspace_id_explicit
        and not getattr(args, "workspace", None)
        and not getattr(args, "project", None)
        and not getattr(args, "project_ref", None)
    ):
        args.project_id = selected_value(config, "project_id")


def resolve_api_url(args: argparse.Namespace, config: dict[str, Any]) -> None:
    env_api_url = os.getenv("SOURCEBRIEF_API_URL", os.getenv("CONTEXTSMITH_API_URL"))
    explicit_api_url = args.api_url is not None
    args._api_url_explicit = explicit_api_url
    args.api_url = args.api_url or env_api_url or selected_value(config, "api_url") or DEFAULT_API_URL


def resolve_email(args: argparse.Namespace) -> None:
    args._email_explicit = args.email is not None
    args.email = args.email or first_env("SOURCEBRIEF_EMAIL", "CONTEXTSMITH_EMAIL") or DEFAULT_EMAIL


def require_scope(args: argparse.Namespace, *, workspace: bool = True, project: bool = True) -> None:
    missing: list[str] = []
    if workspace and "workspace_id" in args.__dict__ and not args.__dict__.get("workspace_id"):
        missing.append("--workspace / --workspace-id")
    if project and "project_id" in args.__dict__ and not args.__dict__.get("project_id"):
        missing.append("--project / --project-id")
    if missing:
        joined = " and ".join(missing)
        raise SourceBriefCliError(f"{joined} required; pass a name explicitly or run sourcebrief use first")
