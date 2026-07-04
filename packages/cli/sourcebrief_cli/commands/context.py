from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from sourcebrief_cli import support as cli_support
from sourcebrief_cli.client import SourceBriefClient

CommandHandler = Callable[[Any, argparse.Namespace], Any]


def cmd_search(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    cli_support.require_scope(args)
    body = {
        "query": args.query,
        "top_k": args.top_k,
        "resource_ids": cli_support.resource_ids(args.resource_id),
    }
    cli_support.apply_resource_refs(body, args)
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/search",
        body=body,
    )


def cmd_agent_context(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    cli_support.require_scope(args)
    body = {
        "query": args.query,
        "runtime": args.runtime,
        "top_k": args.top_k,
        "resource_ids": cli_support.resource_ids(args.resource_id),
        "include_code_symbols": args.include_code_symbols,
        "include_answer": getattr(args, "include_answer", True),
        "max_chars": args.max_chars,
    }
    cli_support.apply_resource_refs(body, args)
    return client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/agent-context",
        body=body,
    )


def cmd_mcp_context(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    cli_support.require_scope(args)
    arguments = {
        "query": args.query,
        "runtime": args.runtime,
        "top_k": args.top_k,
        "resource_ids": cli_support.resource_ids(args.resource_id),
    }
    cli_support.apply_resource_refs(arguments, args)
    return client.request(
        "POST",
        f"/mcp/{args.workspace_id}/{args.project_id}",
        body={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "sourcebrief.get_agent_context",
                "arguments": arguments,
            },
        },
    )


def cmd_ask(client: SourceBriefClient, args: argparse.Namespace) -> Any:
    data = cmd_agent_context(client, args)
    review_bundle = cli_support.capture_review_bundle(agent_context=data, args=args, query=args.query)
    if args.json:
        if review_bundle:
            data = {**data, "review_bundle": review_bundle}
        return data
    answer = cli_support.human_answer_brief(data)
    if review_bundle:
        answer["review_bundle"] = review_bundle
    return answer


def register_context_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    *,
    search_command: CommandHandler,
    ask_command: CommandHandler,
    agent_context_command: CommandHandler,
    mcp_context_command: CommandHandler,
) -> None:
    search = subparsers.add_parser("search", help="search project context")
    search.add_argument("--workspace", help="workspace name or slug; defaults to sourcebrief use selection")
    search.add_argument("--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection")
    search.add_argument("--project", help="project name; defaults to sourcebrief use selection")
    search.add_argument("--project-id", help="advanced: project ID; defaults to sourcebrief use selection")
    search.add_argument("--query", required=True)
    search.add_argument("--resource-id", action="append")
    search.add_argument("--resource", action="append", help="resource ID or unambiguous resource ref/name")
    search.add_argument("--top-k", type=int, default=10)
    search.set_defaults(func=search_command)

    ask = subparsers.add_parser(
        "ask",
        help="ask SourceBrief for cited project context",
        description="Ask SourceBrief for cited context. Workspace/project can come from explicit flags or `sourcebrief use`.",
    )
    ask.add_argument("query", help="question to answer from cited project evidence")
    ask.add_argument("--json", action="store_true", help="print the full agent-context packet for this ask")
    ask.add_argument("--workspace", help="workspace name or slug; overrides saved sourcebrief use value")
    ask.add_argument("--workspace-id", help="advanced: workspace ID; overrides saved sourcebrief use value")
    ask.add_argument("--project", help="project name; overrides saved sourcebrief use value")
    ask.add_argument("--project-id", help="advanced: project ID; overrides saved sourcebrief use value")
    ask.add_argument("--runtime", default="api", choices=["api", "hermes", "claude", "codex", "cursor"])
    ask.add_argument("--resource-id", action="append")
    ask.add_argument("--resource", action="append", help="resource ID or unambiguous resource ref/name")
    ask.add_argument("--top-k", type=int, default=8)
    ask.add_argument("--max-chars", type=int, default=12000)
    ask.add_argument("--review-bundle-out", help="write an opt-in self-improvement review bundle JSON for this answer")
    ask.add_argument("--no-code-symbols", dest="include_code_symbols", action="store_false")
    ask.set_defaults(func=ask_command, include_code_symbols=True)

    agent = subparsers.add_parser("agent-context", help="request runtime-shaped context")
    agent.add_argument("--workspace", help="workspace name or slug; defaults to sourcebrief use selection")
    agent.add_argument("--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection")
    agent.add_argument("--project", help="project name; defaults to sourcebrief use selection")
    agent.add_argument("--project-id", help="advanced: project ID; defaults to sourcebrief use selection")
    agent.add_argument("--query", required=True)
    agent.add_argument("--runtime", default="api", choices=["api", "hermes", "claude", "codex", "cursor"])
    agent.add_argument("--resource-id", action="append")
    agent.add_argument("--resource", action="append", help="resource ID or unambiguous resource ref/name")
    agent.add_argument("--top-k", type=int, default=8)
    agent.add_argument("--max-chars", type=int, default=12000)
    agent.add_argument("--no-code-symbols", dest="include_code_symbols", action="store_false")
    agent.add_argument("--no-answer", dest="include_answer", action="store_false", help="return raw context without synthesized answer metadata")
    agent.set_defaults(func=agent_context_command, include_code_symbols=True, include_answer=True)

    mcp = subparsers.add_parser("mcp-context", help="call the central MCP context tool")
    mcp.add_argument("--workspace", help="workspace name or slug; defaults to sourcebrief use selection")
    mcp.add_argument("--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection")
    mcp.add_argument("--project", help="project name; defaults to sourcebrief use selection")
    mcp.add_argument("--project-id", help="advanced: project ID; defaults to sourcebrief use selection")
    mcp.add_argument("--query", required=True)
    mcp.add_argument("--runtime", default="api", choices=["api", "hermes", "claude", "codex", "cursor"])
    mcp.add_argument("--resource-id", action="append")
    mcp.add_argument("--resource", action="append", help="resource ID or unambiguous resource ref/name")
    mcp.add_argument("--top-k", type=int, default=8)
    mcp.set_defaults(func=mcp_context_command)
