from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_API_URL = "http://localhost:18000"
DEFAULT_EMAIL = "demo@example.com"


class ContextSmithCliError(RuntimeError):
    """User-facing CLI error."""


class ContextSmithClient:
    def __init__(self, api_url: str, email: str, token: str | None = None, timeout: float = 30.0) -> None:
        self.api_url = api_url.rstrip("/")
        self.email = email
        self.token = token
        self.timeout = timeout

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        expected: set[int] | None = None,
    ) -> Any:
        expected = expected or {200}
        data = None
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        else:
            headers["X-User-Email"] = self.email
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.api_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - user-provided API base is intentional CLI behavior
                payload = response.read()
                status = response.status
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ContextSmithCliError(
                f"{method} {path} failed with HTTP {exc.code}: {detail}"
            ) from exc
        except URLError as exc:
            raise ContextSmithCliError(f"failed to reach {self.api_url}: {exc.reason}") from exc
        if status not in expected:
            raise ContextSmithCliError(f"{method} {path} expected {sorted(expected)}, got {status}")
        if not payload:
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise ContextSmithCliError(f"{method} {path} returned non-JSON response") from exc


def _print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def _print_kv(title: str, data: dict[str, Any], keys: list[str]) -> None:
    print(title)
    for key in keys:
        if key in data:
            print(f"  {key}: {data[key]}")


def _resource_ids(values: list[str] | None) -> list[str] | None:
    return values or None


def _split_csv_or_repeated(values: list[str] | None) -> list[str] | None:
    if not values:
        return None
    result: list[str] = []
    for value in values:
        result.extend(part.strip() for part in value.split(",") if part.strip())
    return result or None


def _wait_for_run(client: ContextSmithClient, workspace_id: str, index_run_id: str, timeout: int) -> dict[str, Any]:
    deadline = time.time() + timeout
    current: dict[str, Any] = {"status": "queued", "id": index_run_id}
    while time.time() < deadline:
        current = client.request("GET", f"/workspaces/{workspace_id}/index-runs/{index_run_id}")
        if current.get("status") in {"succeeded", "failed"}:
            break
        time.sleep(2)
    if current.get("status") != "succeeded":
        raise ContextSmithCliError(f"index run did not succeed before timeout: {current}")
    return current


def cmd_health(client: ContextSmithClient, _args: argparse.Namespace) -> Any:
    return client.request("GET", "/readyz")


def cmd_workspace_create(client: ContextSmithClient, args: argparse.Namespace) -> Any:
    return client.request(
        "POST",
        "/workspaces",
        body={"name": args.name, "slug": args.slug},
        expected={201},
    )


def cmd_project_create(client: ContextSmithClient, args: argparse.Namespace) -> Any:
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects",
        body={"name": args.name, "description": args.description},
        expected={201},
    )


def cmd_token_create(client: ContextSmithClient, args: argparse.Namespace) -> Any:
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


def cmd_token_list(client: ContextSmithClient, args: argparse.Namespace) -> Any:
    return client.request("GET", f"/workspaces/{args.workspace_id}/api-tokens")


def cmd_token_revoke(client: ContextSmithClient, args: argparse.Namespace) -> Any:
    return client.request("DELETE", f"/workspaces/{args.workspace_id}/api-tokens/{args.token_id}")


def _maybe_refresh(client: ContextSmithClient, args: argparse.Namespace, resource: dict[str, Any]) -> dict[str, Any]:
    if not args.refresh:
        return {"resource": resource}
    run = client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{resource['id']}/refresh",
        expected={202},
    )
    result: dict[str, Any] = {"resource": resource, "index_run": run}
    if args.wait:
        result["index_run"] = _wait_for_run(client, args.workspace_id, run["id"], args.timeout)
    return result


def cmd_resource_add_doc(client: ContextSmithClient, args: argparse.Namespace) -> Any:
    content = args.content
    if args.content_file:
        content = Path(args.content_file).read_text(encoding="utf-8")
    if not content:
        raise ContextSmithCliError("add-doc requires --content or --content-file")
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
    return _maybe_refresh(client, args, resource)


def cmd_resource_add_repo(client: ContextSmithClient, args: argparse.Namespace) -> Any:
    source_config: dict[str, Any] = {"url": args.repo_url}
    if args.branch:
        source_config["branch"] = args.branch
    if args.max_files is not None:
        source_config["max_repo_files"] = args.max_files
    if args.max_file_bytes is not None:
        source_config["max_file_bytes"] = args.max_file_bytes
    if args.max_repo_bytes is not None:
        source_config["max_repo_bytes"] = args.max_repo_bytes
    if args.clone_timeout is not None:
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
    return _maybe_refresh(client, args, resource)


def cmd_resource_refresh(client: ContextSmithClient, args: argparse.Namespace) -> Any:
    run = client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}/refresh",
        expected={202},
    )
    if args.wait:
        return _wait_for_run(client, args.workspace_id, run["id"], args.timeout)
    return run


def cmd_resource_list(client: ContextSmithClient, args: argparse.Namespace) -> Any:
    return client.request("GET", f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources")


def cmd_search(client: ContextSmithClient, args: argparse.Namespace) -> Any:
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/search",
        body={"query": args.query, "top_k": args.top_k, "resource_ids": _resource_ids(args.resource_id)},
    )


def cmd_agent_context(client: ContextSmithClient, args: argparse.Namespace) -> Any:
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/agent-context",
        body={
            "query": args.query,
            "runtime": args.runtime,
            "top_k": args.top_k,
            "resource_ids": _resource_ids(args.resource_id),
            "include_code_symbols": args.include_code_symbols,
            "max_chars": args.max_chars,
        },
    )


def cmd_mcp_context(client: ContextSmithClient, args: argparse.Namespace) -> Any:
    return client.request(
        "POST",
        f"/mcp/{args.workspace_id}/{args.project_id}",
        body={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "contextsmith.get_agent_context",
                "arguments": {
                    "query": args.query,
                    "runtime": args.runtime,
                    "top_k": args.top_k,
                    "resource_ids": _resource_ids(args.resource_id),
                },
            },
        },
    )


def cmd_agent_list(client: ContextSmithClient, args: argparse.Namespace) -> Any:
    return client.request("GET", f"/workspaces/{args.workspace_id}/agents")


def cmd_agent_profile(client: ContextSmithClient, args: argparse.Namespace) -> Any:
    return client.request(
        "GET",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/agent-profile",
    )


def cmd_resource_graph(client: ContextSmithClient, args: argparse.Namespace) -> Any:
    return client.request(
        "GET",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{args.resource_id}/graph?limit={args.limit}",
    )


def _add_common_resource_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--update-frequency", default="manual")
    parser.add_argument("--refresh", action="store_true", help="refresh after creating the resource")
    parser.add_argument("--wait", action="store_true", help="wait for refresh completion")
    parser.add_argument("--timeout", type=int, default=120, help="seconds to wait for refresh")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="contextsmith", description="ContextSmith CLI")
    parser.add_argument("--api-url", default=os.getenv("CONTEXTSMITH_API_URL", DEFAULT_API_URL))
    parser.add_argument("--email", default=os.getenv("CONTEXTSMITH_EMAIL", DEFAULT_EMAIL))
    parser.add_argument("--token", default=os.getenv("CONTEXTSMITH_TOKEN"), help="Bearer API token; overrides --email dev auth")
    parser.add_argument("--json", action="store_true", help="print full JSON response")
    parser.set_defaults(func=None)

    sub = parser.add_subparsers(dest="command")

    health = sub.add_parser("health", help="check API readiness")
    health.set_defaults(func=cmd_health)

    ws = sub.add_parser("workspace", help="workspace commands").add_subparsers(dest="workspace_command")
    ws_create = ws.add_parser("create", help="create a workspace")
    ws_create.add_argument("--name", required=True)
    ws_create.add_argument("--slug", required=True)
    ws_create.set_defaults(func=cmd_workspace_create)

    projects = sub.add_parser("project", help="project commands").add_subparsers(dest="project_command")
    project_create = projects.add_parser("create", help="create a project")
    project_create.add_argument("--workspace-id", required=True)
    project_create.add_argument("--name", required=True)
    project_create.add_argument("--description")
    project_create.set_defaults(func=cmd_project_create)

    tokens = sub.add_parser("token", help="workspace API token commands").add_subparsers(dest="token_command")
    token_create = tokens.add_parser("create", help="create a bearer API token for agents/Hermes")
    token_create.add_argument("--workspace-id", required=True)
    token_create.add_argument("--name", required=True)
    token_create.add_argument("--scope", action="append", required=True, help="scope, repeatable or comma-separated")
    token_create.add_argument("--project-id", action="append", help="allowed project ID, repeatable or comma-separated")
    token_create.add_argument("--resource-id", action="append", help="allowed resource ID, repeatable or comma-separated")
    token_create.add_argument("--expires-at", help="ISO-8601 timestamp")
    token_create.set_defaults(func=cmd_token_create)

    token_list = tokens.add_parser("list", help="list API tokens without plaintext secrets")
    token_list.add_argument("--workspace-id", required=True)
    token_list.set_defaults(func=cmd_token_list)

    token_revoke = tokens.add_parser("revoke", help="revoke an API token")
    token_revoke.add_argument("--workspace-id", required=True)
    token_revoke.add_argument("--token-id", required=True)
    token_revoke.set_defaults(func=cmd_token_revoke)

    resources = sub.add_parser("resource", help="resource commands").add_subparsers(dest="resource_command")
    add_doc = resources.add_parser("add-doc", help="add a markdown/document resource")
    _add_common_resource_args(add_doc)
    add_doc.add_argument("--uri", required=True)
    add_doc.add_argument("--content")
    add_doc.add_argument("--content-file")
    add_doc.add_argument("--path")
    add_doc.add_argument("--title")
    add_doc.set_defaults(func=cmd_resource_add_doc)

    add_repo = resources.add_parser("add-repo", help="add a git repository resource")
    _add_common_resource_args(add_repo)
    add_repo.add_argument("--repo-url", required=True, help="public https git URL, or local file URL when the worker allows local git")
    add_repo.add_argument("--branch")
    add_repo.add_argument("--max-files", type=int)
    add_repo.add_argument("--max-file-bytes", type=int)
    add_repo.add_argument("--max-repo-bytes", type=int)
    add_repo.add_argument("--clone-timeout", type=int)
    add_repo.set_defaults(func=cmd_resource_add_repo)

    refresh = resources.add_parser("refresh", help="refresh a resource")
    refresh.add_argument("--workspace-id", required=True)
    refresh.add_argument("--project-id", required=True)
    refresh.add_argument("--resource-id", required=True)
    refresh.add_argument("--wait", action="store_true")
    refresh.add_argument("--timeout", type=int, default=120)
    refresh.set_defaults(func=cmd_resource_refresh)

    list_resources = resources.add_parser("list", help="list resources")
    list_resources.add_argument("--workspace-id", required=True)
    list_resources.add_argument("--project-id", required=True)
    list_resources.set_defaults(func=cmd_resource_list)

    graph = resources.add_parser("graph", help="show a resource graph index")
    graph.add_argument("--workspace-id", required=True)
    graph.add_argument("--project-id", required=True)
    graph.add_argument("--resource-id", required=True)
    graph.add_argument("--limit", type=int, default=50)
    graph.set_defaults(func=cmd_resource_graph)

    agents = sub.add_parser("agent", help="agent registry commands").add_subparsers(dest="agent_command")
    agent_list = agents.add_parser("list", help="list project agents in a workspace")
    agent_list.add_argument("--workspace-id", required=True)
    agent_list.set_defaults(func=cmd_agent_list)

    agent_profile = agents.add_parser("profile", help="show one project agent profile")
    agent_profile.add_argument("--workspace-id", required=True)
    agent_profile.add_argument("--project-id", required=True)
    agent_profile.set_defaults(func=cmd_agent_profile)

    search = sub.add_parser("search", help="search project context")
    search.add_argument("--workspace-id", required=True)
    search.add_argument("--project-id", required=True)
    search.add_argument("--query", required=True)
    search.add_argument("--resource-id", action="append")
    search.add_argument("--top-k", type=int, default=10)
    search.set_defaults(func=cmd_search)

    agent = sub.add_parser("agent-context", help="request runtime-shaped context")
    agent.add_argument("--workspace-id", required=True)
    agent.add_argument("--project-id", required=True)
    agent.add_argument("--query", required=True)
    agent.add_argument("--runtime", default="api", choices=["api", "hermes", "claude", "codex", "cursor"])
    agent.add_argument("--resource-id", action="append")
    agent.add_argument("--top-k", type=int, default=8)
    agent.add_argument("--max-chars", type=int, default=12000)
    agent.add_argument("--no-code-symbols", dest="include_code_symbols", action="store_false")
    agent.set_defaults(func=cmd_agent_context, include_code_symbols=True)

    mcp = sub.add_parser("mcp-context", help="call the central MCP context tool")
    mcp.add_argument("--workspace-id", required=True)
    mcp.add_argument("--project-id", required=True)
    mcp.add_argument("--query", required=True)
    mcp.add_argument("--runtime", default="api", choices=["api", "hermes", "claude", "codex", "cursor"])
    mcp.add_argument("--resource-id", action="append")
    mcp.add_argument("--top-k", type=int, default=8)
    mcp.set_defaults(func=cmd_mcp_context)

    return parser


def _print_default(command: str | None, data: Any) -> None:
    if isinstance(data, dict):
        if "resource" in data and isinstance(data["resource"], dict):
            _print_kv("Resource", data["resource"], ["id", "name", "type", "uri", "status"])
            if "index_run" in data:
                _print_kv("Index run", data["index_run"], ["id", "status", "documents_seen", "chunks_created", "symbols_created", "embeddings_created"])
            return
        if command in {"workspace", "project", "health"}:
            _print_kv(command.title() if command else "Result", data, ["id", "name", "slug", "workspace_id", "status"])
            return
        if command == "search":
            print(f"Search: {data.get('query')} ({data.get('count', 0)} hits)")
            for hit in data.get("hits", []):
                print(f"- {hit.get('path') or hit.get('title') or hit.get('resource_id')}: {hit.get('snippet')}")
            return
        if command in {"agent-context", "mcp-context", "agent", "token"}:
            _print_json(data)
            return
    _print_json(data)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.func is None:
        parser.print_help(sys.stderr)
        return 2
    client = ContextSmithClient(args.api_url, args.email, token=args.token)
    try:
        data = args.func(client, args)
    except ContextSmithCliError as exc:
        print(f"contextsmith: error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        _print_json(data)
    else:
        _print_default(args.command, data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
