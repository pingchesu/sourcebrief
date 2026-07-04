from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

CommandHandler = Callable[[Any, argparse.Namespace], Any]


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
