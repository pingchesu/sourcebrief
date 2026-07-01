from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sourcebrief_cli.client import SourceBriefClient, SourceBriefCliError
from sourcebrief_cli.scope import require_scope
from sourcebrief_cli.support import add_common_resource_args, maybe_refresh, wait_for_run


def cmd_resource_add_doc(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    require_scope(args)
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
    return maybe_refresh(client, args, resource)


def cmd_resource_add_repo(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    require_scope(args)
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
    return maybe_refresh(client, args, resource)


def cmd_resource_add_url(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    require_scope(args)
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
    return maybe_refresh(client, args, resource)


def cmd_resource_add_upload(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    require_scope(args)
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
    return maybe_refresh(client, args, resource)


def cmd_resource_refresh(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    require_scope(args)

    run = client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}/refresh",
        expected={202},
    )
    if args.wait:
        return wait_for_run(client, args.workspace_id, run["id"], args.timeout)
    return run


def cmd_resource_list(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    require_scope(args)
    return client.request("GET", f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources")


def cmd_resource_get(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    require_scope(args)
    return client.request("GET", f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}")


def cmd_resource_update(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    require_scope(args)
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
    require_scope(args)
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
    require_scope(args)
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}/archive",
    )


def cmd_resource_delete(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    require_scope(args)
    client.request(
        "DELETE",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}",
        expected={204},
    )
    return {"status": "deleted", "resource_id": args.resource_id}


def cmd_resource_restore(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    require_scope(args)
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}/restore",
    )


def cmd_resource_purge(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    require_scope(args)
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}/purge",
    )


def cmd_resource_schedule_due(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    require_scope(args)
    query = f"limit={args.limit}"
    if args.dry_run:
        query += "&dry_run=true"
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/scheduled-refreshes?{query}",
        expected={202},
    )


def cmd_resource_graph(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    require_scope(args)
    return client.request(
        "GET",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}/graph?limit={args.limit}",
    )


def register_resource_commands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    resources = subparsers.add_parser("resource", help="resource commands").add_subparsers(dest="resource_command")
    add_doc = resources.add_parser("add-doc", help="add a markdown/document resource")
    add_common_resource_args(add_doc)
    add_doc.add_argument("--uri", required=True)
    add_doc.add_argument("--content")
    add_doc.add_argument("--content-file")
    add_doc.add_argument("--path")
    add_doc.add_argument("--title")
    add_doc.set_defaults(func=cmd_resource_add_doc)

    add_repo = resources.add_parser("add-repo", help="add a git repository resource")
    add_common_resource_args(add_repo)
    add_repo.add_argument("--repo-url", required=True, help="public https git URL, or local file URL when the worker allows local git")
    add_repo.add_argument("--branch")
    add_repo.add_argument("--max-files", type=int)
    add_repo.add_argument("--max-file-bytes", type=int)
    add_repo.add_argument("--max-repo-bytes", type=int)
    add_repo.add_argument("--clone-timeout", type=int)
    add_repo.set_defaults(func=cmd_resource_add_repo)

    add_url = resources.add_parser("add-url", help="add a public HTTP(S) URL resource")
    add_common_resource_args(add_url)
    add_url.add_argument("--url", required=True)
    add_url.add_argument("--title")
    add_url.add_argument("--max-url-bytes", type=int)
    add_url.add_argument("--fetch-timeout", type=int)
    add_url.set_defaults(func=cmd_resource_add_url)

    add_upload = resources.add_parser("add-upload", help="add an uploaded text/markdown resource from a local file")
    add_common_resource_args(add_upload)
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
