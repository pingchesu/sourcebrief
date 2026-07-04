from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request, Response
from pydantic import ValidationError
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal
from sourcebrief_api.schemas import (
    AgentContextRequest,
    GeneratePatchRequest,
    OpenPrRequest,
    RemoteFindSymbolRequest,
    RemoteGrepCodeRequest,
    RemoteReadFileRequest,
    RemoteSearchCodeRequest,
)

ToolAction = Callable[..., Any]


@dataclass(frozen=True)
class McpEndpointDeps:
    require_project_access: ToolAction
    json_rpc_error: Callable[[object | None, int, str], dict]
    mcp_tool_result: Callable[[object | None, Any], dict]
    mcp_tool_error: Callable[[object | None, int, object], dict]
    mcp_tools: Callable[[], list[dict[str, Any]]]
    runtime_args_with_resource_ref: ToolAction
    runtime_remote_args: Callable[[dict[str, Any], set[str]], dict[str, Any]]
    agent_context: ToolAction
    runtime_discover: ToolAction
    runtime_lookup: ToolAction
    runtime_get_context_pack: ToolAction
    runtime_list_sources: ToolAction
    runtime_get_resource_map: ToolAction
    runtime_search: ToolAction
    runtime_read_section: ToolAction
    runtime_graph_overview: ToolAction
    runtime_get_graph_inventory: ToolAction
    runtime_graph_query: ToolAction
    runtime_graph_path: ToolAction
    runtime_generate_skill_pack: ToolAction
    remote_search_code: ToolAction
    remote_grep_code: ToolAction
    remote_read_file: ToolAction
    remote_find_symbol: ToolAction
    remote_code_rpc_spec: ToolAction
    runtime_help: Callable[[dict[str, Any]], dict[str, Any]]
    remote_generate_patch: ToolAction
    remote_open_pr: ToolAction


TOOL_PRIORITY = {
    "sourcebrief.ask": 0,
    "sourcebrief.discover": 1,
    "sourcebrief.lookup": 2,
    "sourcebrief.get_agent_context": 3,
    "sourcebrief.list_sources": 4,
    "sourcebrief.get_architecture": 5,
    "sourcebrief.get_context_pack": 6,
    "sourcebrief.search": 7,
    "sourcebrief.read_section": 8,
    "sourcebrief.read_file": 9,
    "sourcebrief.search_code": 10,
    "sourcebrief.grep_code": 11,
    "sourcebrief.find_symbol": 12,
    "sourcebrief.get_resource_map": 13,
    "sourcebrief.get_graph_inventory": 14,
    "sourcebrief.graph_query": 15,
    "sourcebrief.graph_path": 16,
    "sourcebrief.generate_skill_pack": 20,
    "sourcebrief.get_rpc_spec": 21,
    "sourcebrief.get_runtime_help": 22,
    "sourcebrief.generate_patch": 30,
    "sourcebrief.open_pr": 31,
}


def build_mcp_endpoint_action(deps: McpEndpointDeps):
    async def mcp_endpoint_action(
        workspace_id: UUID,
        project_id: UUID,
        request: Request,
        principal: Principal,
        session: Session,
    ) -> dict | Response:
        """Minimal central MCP-compatible JSON-RPC endpoint for project context."""
        deps.require_project_access(session, workspace_id, project_id, principal)
        try:
            body = await request.json()
        except Exception:
            return deps.json_rpc_error(None, -32700, "parse error")
        if not isinstance(body, dict):
            return deps.json_rpc_error(None, -32600, "invalid request")
        rpc_id = body.get("id")
        has_id = "id" in body
        if body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
            return deps.json_rpc_error(rpc_id if has_id else None, -32600, "invalid request")
        method = body["method"]
        if not has_id:
            return Response(status_code=204)
        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "sourcebrief", "version": "0.1.0"},
                    "capabilities": {"tools": {}},
                },
            }
        if method == "tools/list":
            tools = sorted(
                deps.mcp_tools(),
                key=lambda tool: (TOOL_PRIORITY.get(str(tool.get("name")), 50), str(tool.get("name"))),
            )
            return {"jsonrpc": "2.0", "id": rpc_id, "result": {"tools": tools}}
        if method == "tools/call":
            params = body.get("params", {})
            if not isinstance(params, dict):
                return deps.json_rpc_error(rpc_id, -32602, "invalid params")
            tool_name = params.get("name")
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                return deps.json_rpc_error(rpc_id, -32602, "invalid params")
            if isinstance(tool_name, str) and tool_name.startswith("contextsmith."):
                tool_name = "sourcebrief." + tool_name[len("contextsmith."):]
            result: Any
            try:
                if tool_name == "sourcebrief.ask":
                    payload = AgentContextRequest(**deps.runtime_args_with_resource_ref(session, workspace_id, project_id, principal, arguments, single=False))
                    result = deps.agent_context(workspace_id, project_id, payload, principal, session)
                elif tool_name == "sourcebrief.discover":
                    result = deps.runtime_discover(session, workspace_id, project_id, principal, arguments)
                elif tool_name == "sourcebrief.lookup":
                    result = deps.runtime_lookup(session, workspace_id, project_id, principal, arguments)
                elif tool_name == "sourcebrief.get_context_pack":
                    result = deps.runtime_get_context_pack(session, workspace_id, project_id, principal, arguments)
                elif tool_name == "sourcebrief.list_sources":
                    result = deps.runtime_list_sources(session, workspace_id, project_id, principal, arguments)
                elif tool_name == "sourcebrief.get_resource_map":
                    result = deps.runtime_get_resource_map(session, workspace_id, project_id, principal, arguments)
                elif tool_name == "sourcebrief.search":
                    result = deps.runtime_search(session, workspace_id, project_id, principal, deps.runtime_args_with_resource_ref(session, workspace_id, project_id, principal, arguments, single=False))
                elif tool_name == "sourcebrief.read_section":
                    result = deps.runtime_read_section(session, workspace_id, project_id, principal, deps.runtime_args_with_resource_ref(session, workspace_id, project_id, principal, arguments, single=True))
                elif tool_name == "sourcebrief.get_architecture":
                    result = deps.runtime_graph_overview(session, workspace_id, project_id, principal, arguments)
                elif tool_name == "sourcebrief.get_graph_inventory":
                    result = deps.runtime_get_graph_inventory(session, workspace_id, project_id, principal, arguments)
                elif tool_name == "sourcebrief.graph_query":
                    result = deps.runtime_graph_query(session, workspace_id, project_id, principal, arguments)
                elif tool_name == "sourcebrief.graph_path":
                    result = deps.runtime_graph_path(session, workspace_id, project_id, principal, arguments)
                elif tool_name == "sourcebrief.get_agent_context":
                    payload = AgentContextRequest(**deps.runtime_args_with_resource_ref(session, workspace_id, project_id, principal, arguments, single=False))
                    result = deps.agent_context(workspace_id, project_id, payload, principal, session)
                elif tool_name == "sourcebrief.search_code":
                    code_args = deps.runtime_args_with_resource_ref(session, workspace_id, project_id, principal, arguments, single=False)
                    result = deps.remote_search_code(workspace_id, project_id, RemoteSearchCodeRequest(**deps.runtime_remote_args(code_args, {"query", "resource_ids", "top_k", "cursor"})), principal, session)
                elif tool_name == "sourcebrief.grep_code":
                    grep_args = deps.runtime_args_with_resource_ref(session, workspace_id, project_id, principal, arguments, single=False)
                    result = deps.remote_grep_code(workspace_id, project_id, RemoteGrepCodeRequest(**deps.runtime_remote_args(grep_args, {"pattern", "resource_ids", "path_glob", "max_matches", "cursor", "regex", "context_lines"})), principal, session)
                elif tool_name == "sourcebrief.read_file":
                    read_args = deps.runtime_args_with_resource_ref(session, workspace_id, project_id, principal, arguments, single=True)
                    result = deps.remote_read_file(workspace_id, project_id, RemoteReadFileRequest(**deps.runtime_remote_args(read_args, {"resource_id", "path", "start_line", "end_line"})), principal, session)
                elif tool_name == "sourcebrief.find_symbol":
                    symbol_args = deps.runtime_args_with_resource_ref(session, workspace_id, project_id, principal, arguments, single=False)
                    result = deps.remote_find_symbol(workspace_id, project_id, RemoteFindSymbolRequest(**deps.runtime_remote_args(symbol_args, {"name", "kind", "resource_ids", "top_k"})), principal, session)
                elif tool_name == "sourcebrief.generate_skill_pack":
                    result = deps.runtime_generate_skill_pack(session, workspace_id, project_id, principal, arguments)
                elif tool_name == "sourcebrief.get_rpc_spec":
                    result = deps.remote_code_rpc_spec(workspace_id, project_id, principal, session)
                elif tool_name == "sourcebrief.get_runtime_help":
                    result = deps.runtime_help(arguments)
                elif tool_name == "sourcebrief.generate_patch":
                    result = deps.remote_generate_patch(workspace_id, project_id, GeneratePatchRequest(**arguments), principal, session)
                elif tool_name == "sourcebrief.open_pr":
                    result = deps.remote_open_pr(workspace_id, project_id, OpenPrRequest(**arguments), principal, session)
                else:
                    return deps.json_rpc_error(rpc_id, -32601, "unknown tool")
            except ValidationError as exc:
                return deps.json_rpc_error(rpc_id, -32602, f"invalid params: {exc.errors()[0]['msg']}")
            except HTTPException as exc:
                return deps.mcp_tool_error(rpc_id, exc.status_code, exc.detail)
            except (TypeError, ValueError) as exc:
                return deps.mcp_tool_error(rpc_id, 422, {"code": "invalid_params", "message": str(exc)})
            return deps.mcp_tool_result(rpc_id, result)
        return deps.json_rpc_error(rpc_id, -32601, "method not found")

    return mcp_endpoint_action
