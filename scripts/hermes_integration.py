#!/usr/bin/env python3
"""Create and validate a Hermes-scoped SourceBrief integration token.

This script is intentionally operational rather than magical: it creates (or uses)
a workspace-scoped bearer token, validates the REST agent-context path, validates
the central MCP JSON-RPC path, and prints the exact Hermes `mcp_servers` config
shape an operator can paste into Hermes config.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from typing import Any

import requests

DEFAULT_SCOPES = ["project:read", "project:query", "resource:read", "review:read", "code:read"]
READ_ONLY_SCOPE_ALLOWLIST = set(DEFAULT_SCOPES)
TOKEN_PATTERN = re.compile(r"cs_[A-Za-z0-9_-]{20,}")


def fail(message: str) -> None:
    print(f"hermes-integration: error: {message}", file=sys.stderr)
    raise SystemExit(1)


def request_json(
    method: str,
    url: str,
    *,
    expected: set[int] | None = None,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> Any:
    expected = expected or {200}
    try:
        response = requests.request(method, url, headers=headers, timeout=30, **kwargs)
    except requests.RequestException as exc:
        fail(f"{method} {url} failed: {exc}")
        raise AssertionError("unreachable") from exc
    if response.status_code not in expected:
        fail(f"{method} {url} returned HTTP {response.status_code}: {response.text[:1000]}")
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError as exc:
        fail(f"{method} {url} returned non-JSON response: {exc}")
        raise AssertionError("unreachable") from exc


def split_scopes(values: list[str] | None) -> list[str]:
    if not values:
        return list(DEFAULT_SCOPES)
    scopes: list[str] = []
    for value in values:
        scopes.extend(scope.strip() for scope in value.split(",") if scope.strip())
    if not scopes:
        return list(DEFAULT_SCOPES)
    unknown = sorted(set(scopes) - READ_ONLY_SCOPE_ALLOWLIST)
    if unknown:
        fail(f"Hermes integration tokens are read-only; unsupported scope(s): {', '.join(unknown)}")
    return sorted(set(scopes))


def bearer_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def citation_resource_ids(body: dict[str, Any]) -> set[str]:
    return {str(citation.get("resource_id")) for citation in body.get("citations", []) if citation.get("resource_id")}


def validate_context_body(args: argparse.Namespace, body: dict[str, Any], *, label: str) -> None:
    if body.get("runtime") != "hermes":
        fail(f"{label} returned unexpected runtime: {body.get('runtime')}")
    citations = body.get("citations") or []
    context = body.get("context") or ""
    if not args.allow_empty and (not citations or not context.strip()):
        fail(f"{label} validation returned no citations/context; pass --allow-empty only for empty projects")
    if args.expect_text and args.expect_text not in context:
        fail(f"{label} context did not contain expected text {args.expect_text!r}")
    if args.resource_id and citations:
        requested = set(args.resource_id)
        actual = citation_resource_ids(body)
        if not actual or not actual.issubset(requested):
            fail(f"{label} citations are outside requested resources: requested={sorted(requested)} actual={sorted(actual)}")


def validate_created_token(args: argparse.Namespace, api_token: dict[str, Any]) -> None:
    scopes = set(api_token.get("scopes") or [])
    if scopes != set(args.scope):
        fail(f"created token scopes mismatch: expected={sorted(args.scope)} actual={sorted(scopes)}")
    projects = [str(project_id) for project_id in (api_token.get("allowed_project_ids") or [])]
    if projects != [args.project_id]:
        fail(f"created token project allowlist mismatch: {projects}")
    resources = [str(resource_id) for resource_id in (api_token.get("allowed_resource_ids") or [])]
    expected_resources = args.resource_id or []
    if sorted(resources) != sorted(expected_resources):
        fail(f"created token resource allowlist mismatch: expected={expected_resources} actual={resources}")


def validate_read_only_denials(args: argparse.Namespace, token: str) -> None:
    headers = bearer_headers(token)
    request_json(
        "POST",
        f"{args.api_url}/workspaces/{args.workspace_id}/api-tokens",
        expected={403},
        headers=headers,
        json={"name": "denied child token", "scopes": ["project:query"], "allowed_project_ids": [args.project_id]},
    )
    request_json(
        "POST",
        f"{args.api_url}/workspaces/{args.workspace_id}/projects/{args.project_id}/resources",
        expected={403},
        headers=headers,
        json={"type": "markdown", "name": "denied", "uri": "doc://denied", "source_config": {"content": "denied"}},
    )
    if args.resource_id:
        resource_id = args.resource_id[0]
        request_json(
            "POST",
            f"{args.api_url}/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{resource_id}/refresh",
            expected={403},
            headers=headers,
        )
        request_json(
            "POST",
            f"{args.api_url}/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{resource_id}/review",
            expected={403},
            headers=headers,
            json={"review_status": "approved", "review_note": "should be denied"},
        )



def rpc(api_url: str, workspace_id: str, project_id: str, token: str, body: dict[str, Any]) -> Any:
    return request_json(
        "POST",
        f"{api_url}/mcp/{workspace_id}/{project_id}",
        headers=bearer_headers(token),
        json=body,
    )


def create_token(args: argparse.Namespace) -> tuple[str, dict[str, Any] | None]:
    if args.token:
        return args.token, None
    headers = bearer_headers(args.admin_token) if args.admin_token else {"X-User-Email": args.email, "Content-Type": "application/json"}
    payload: dict[str, Any] = {
        "name": args.token_name,
        "scopes": args.scope,
        "allowed_project_ids": [args.project_id],
        "allowed_resource_ids": args.resource_id or None,
    }
    created = request_json(
        "POST",
        f"{args.api_url}/workspaces/{args.workspace_id}/api-tokens",
        expected={201},
        headers=headers,
        json=payload,
    )
    token = created.get("token")
    if not token:
        fail("token creation response did not include one-time plaintext token")
    api_token = created.get("api_token")
    if not isinstance(api_token, dict):
        fail("token creation response did not include api_token metadata")
    validate_created_token(args, api_token)
    return token, api_token


def validate_agent_context(args: argparse.Namespace, token: str) -> dict[str, Any]:
    body = request_json(
        "POST",
        f"{args.api_url}/workspaces/{args.workspace_id}/projects/{args.project_id}/agent-context",
        headers=bearer_headers(token),
        json={
            "query": args.query,
            "runtime": "hermes",
            "top_k": args.top_k,
            "max_chars": args.max_chars,
            "resource_ids": args.resource_id or None,
            "include_code_symbols": not args.no_code_symbols,
        },
    )
    validate_context_body(args, body, label="agent-context")
    return body


def validate_mcp(args: argparse.Namespace, token: str) -> dict[str, Any]:
    init = rpc(
        args.api_url,
        args.workspace_id,
        args.project_id,
        token,
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
    )
    if init.get("result", {}).get("serverInfo", {}).get("name") != "sourcebrief":
        fail(f"MCP initialize returned unexpected serverInfo: {init}")
    tools = rpc(args.api_url, args.workspace_id, args.project_id, token, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tool_names = [tool.get("name") for tool in tools.get("result", {}).get("tools", [])]
    if "sourcebrief.get_agent_context" not in tool_names:
        fail(f"MCP tools/list missing sourcebrief.get_agent_context: {tools}")
    call = rpc(
        args.api_url,
        args.workspace_id,
        args.project_id,
        token,
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "sourcebrief.get_agent_context",
                "arguments": {
                    "query": args.query,
                    "runtime": "hermes",
                    "top_k": args.top_k,
                    "resource_ids": args.resource_id or None,
                    "include_code_symbols": not args.no_code_symbols,
                },
            },
        },
    )
    structured = call.get("result", {}).get("structuredContent") or {}
    validate_context_body(args, structured, label="MCP tools/call")
    return {"initialize": init, "tools": tools, "call": call}


def validate_rest_mcp_consistency(agent_context: dict[str, Any], mcp: dict[str, Any]) -> None:
    structured = mcp["call"]["result"]["structuredContent"]
    rest_resources = citation_resource_ids(agent_context)
    mcp_resources = citation_resource_ids(structured)
    if rest_resources != mcp_resources:
        fail(f"REST/MCP citation resource mismatch: rest={sorted(rest_resources)} mcp={sorted(mcp_resources)}")
    if bool(agent_context.get("context")) != bool(structured.get("context")):
        fail("REST/MCP context presence mismatch")


def hermes_config(args: argparse.Namespace, token: str) -> dict[str, Any]:
    return {
        "mcp_servers": {
            args.server_name: {
                "url": f"{args.public_api_url or args.api_url}/mcp/{args.workspace_id}/{args.project_id}",
                "headers": {"Authorization": f"Bearer {token}"},
                "timeout": args.timeout,
                "connect_timeout": args.connect_timeout,
            }
        }
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create and verify a SourceBrief Hermes/MCP integration")
    parser.add_argument("--api-url", default="http://localhost:18000")
    parser.add_argument("--public-api-url", help="URL Hermes should use if different from --api-url")
    parser.add_argument("--email", default=f"hermes-integration-{int(time.time())}@example.com")
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--query", required=True)
    parser.add_argument("--resource-id", action="append")
    parser.add_argument("--admin-token", help="existing bearer token used only to create the read-only integration token")
    parser.add_argument("--token", help="existing bearer token; skip token creation")
    parser.add_argument("--token-name", default="Hermes SourceBrief token")
    parser.add_argument("--scope", action="append", help="read-only token scope; repeatable or comma-separated; defaults to project/resource/review read + project query")
    parser.add_argument("--server-name", default="sourcebrief")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--max-chars", type=int, default=12000)
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--connect-timeout", type=int, default=30)
    parser.add_argument("--no-code-symbols", action="store_true")
    parser.add_argument("--expect-text", help="optional text that must appear in REST and MCP context")
    parser.add_argument("--allow-empty", action="store_true")
    parser.add_argument("--redact-token", action="store_true", help="redact token in printed Hermes config")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.api_url = args.api_url.rstrip("/")
    if args.public_api_url:
        args.public_api_url = args.public_api_url.rstrip("/")
    args.scope = split_scopes(args.scope)
    token, api_token = create_token(args)
    validate_read_only_denials(args, token)
    agent_context = validate_agent_context(args, token)
    mcp = validate_mcp(args, token)
    validate_rest_mcp_consistency(agent_context, mcp)
    printed_token = "<redacted>" if args.redact_token else token
    config = hermes_config(args, printed_token)
    output = {
        "status": "ok",
        "workspace_id": args.workspace_id,
        "project_id": args.project_id,
        "api_token": api_token,
        "token": printed_token if api_token is not None else None,
        "agent_context": {
            "runtime": agent_context.get("runtime"),
            "citation_count": len(agent_context.get("citations") or []),
            "context_chars": len(agent_context.get("context") or ""),
        },
        "mcp": {
            "server": mcp["initialize"]["result"]["serverInfo"],
            "tool_names": [tool.get("name") for tool in mcp["tools"]["result"]["tools"]],
            "citation_count": len(mcp["call"]["result"]["structuredContent"].get("citations") or []),
        },
        "hermes_config": config,
        "next_steps": [
            "Add hermes_config.mcp_servers to ~/.hermes/config.yaml or your target profile config.",
            "Restart Hermes, or use /reload-mcp if your running gateway supports MCP reload.",
            "Ask Hermes a project question; it should call mcp_sourcebrief_sourcebrief_get_agent_context after discovery.",
        ],
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
