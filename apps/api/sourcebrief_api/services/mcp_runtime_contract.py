from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from sourcebrief_api.auth import Principal
from sourcebrief_api.retrieval import RETRIEVAL_PROFILES


def json_rpc_error(rpc_id: object | None, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id, "error": {"code": code, "message": message}}


def mcp_tool_result(rpc_id: object | None, result: Any) -> dict:
    payload = result.model_dump(mode="json") if hasattr(result, "model_dump") else jsonable_encoder(result)
    text_payload = result.model_dump_json() if hasattr(result, "model_dump_json") else json.dumps(payload)
    return {
        "jsonrpc": "2.0",
        "id": rpc_id,
        "result": {"content": [{"type": "text", "text": text_payload}], "structuredContent": payload},
    }


def runtime_remote_args(args: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    return {key: value for key, value in args.items() if key in allowed and value is not None}


def runtime_has_scope(principal: Principal, scope: str) -> bool:
    scopes = principal.scopes
    return "*" in scopes or scope in scopes


def mcp_tools() -> list[dict[str, Any]]:
    return [
        {
            "name": "sourcebrief.ask",
            "description": "Golden-path answer: ask a project question and receive a synthesized cited answer, cited context, and suggested next tool calls. Code symbols are returned only when the caller has code:read; context-only tokens receive cited context plus an omission warning. Set include_answer=false to get the raw context packet without synthesis.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "runtime": {"type": "string", "enum": ["api", "hermes", "claude", "codex", "cursor"]},
                    "profile": {"type": "string", "enum": sorted(RETRIEVAL_PROFILES)},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
                    "resource_ids": {"type": "array", "items": {"type": "string"}},
                    "resource_ref": {"type": "string"}, "resource_refs": {"type": "array", "items": {"type": "string"}},
                    "context_pack_key": {"type": "string"},
                    "context_pack_version": {"type": "integer", "minimum": 1},
                    "max_chars": {"type": "integer", "minimum": 1000, "maximum": 50000},
                    "include_code_symbols": {"type": "boolean"},
                    "include_answer": {"type": "boolean"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "sourcebrief.discover",
            "description": "Golden-path discovery: list authorized sources and return a compact architecture/graph overview before choosing lower-level tools.",
            "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "resource_type": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}, "cursor": {"type": "string"}, "max_resources": {"type": "integer", "minimum": 1, "maximum": 50}, "max_items": {"type": "integer", "minimum": 1, "maximum": 50}}},
        },
        {
            "name": "sourcebrief.lookup",
            "description": "Golden-path lookup router for docs, code, grep, and symbols; accepts optional human resource_ref for unambiguous source selection.",
            "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "search_in": {"type": "string", "enum": ["all", "docs", "code", "grep", "symbols"]}, "resource_ref": {"type": "string"}, "resource_refs": {"type": "array", "items": {"type": "string"}}, "resource_ids": {"type": "array", "items": {"type": "string"}}, "top_k": {"type": "integer", "minimum": 1, "maximum": 50}, "path_glob": {"type": "string"}, "regex": {"type": "boolean"}}, "required": ["query"]},
        },
        {
            "name": "sourcebrief.get_context_pack",
            "description": "Fetch a published SourceBrief context pack with bounded source/artifact/graph inventory and freshness metadata.",
            "inputSchema": {"type": "object", "properties": {"pack_key": {"type": "string"}, "version": {"type": "integer", "minimum": 1}, "include_artifacts": {"type": "boolean"}, "include_coverage": {"type": "boolean"}, "include_graph_inventory": {"type": "boolean"}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}, "cursor": {"type": "string"}}},
        },
        {
            "name": "sourcebrief.list_sources",
            "description": "List authorized human source names/resources so agents do not need UUID-first workflows.",
            "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "resource_type": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}, "cursor": {"type": "string"}}},
        },
        {
            "name": "sourcebrief.get_resource_map",
            "description": "Fetch an approved resource-map artifact by resource id, human resource reference, or artifact id with canonical read_section locators.",
            "inputSchema": {"type": "object", "properties": {"resource_id": {"type": "string"}, "resource_ref": {"type": "string"}, "resource_refs": {"type": "array", "items": {"type": "string"}}, "artifact_id": {"type": "string"}, "source_snapshot_id": {"type": "string"}, "include_sources": {"type": "boolean"}, "include_citations": {"type": "boolean"}, "limit": {"type": "integer", "minimum": 1, "maximum": 200}, "cursor": {"type": "string"}}},
        },
        {
            "name": "sourcebrief.search",
            "description": "Search indexed sections/artifacts with cited canonical locators for read_section.",
            "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "resource_ids": {"type": "array", "items": {"type": "string"}}, "resource_ref": {"type": "string"}, "resource_refs": {"type": "array", "items": {"type": "string"}}, "context_pack_key": {"type": "string"}, "context_pack_version": {"type": "integer", "minimum": 1}, "profile": {"type": "string", "enum": sorted(RETRIEVAL_PROFILES)}, "top_k": {"type": "integer", "minimum": 1, "maximum": 50}, "include_code_symbols": {"type": "boolean"}}, "required": ["query"]},
        },
        {
            "name": "sourcebrief.read_section",
            "description": "Read exact retained section evidence from a canonical locator returned by search/resource-map/context-pack tools.",
            "inputSchema": {"type": "object", "properties": {"resource_id": {"type": "string"}, "resource_ref": {"type": "string"}, "resource_refs": {"type": "array", "items": {"type": "string"}}, "source_snapshot_id": {"type": "string"}, "snapshot_section_id": {"type": "string"}, "context_artifact_id": {"type": "string"}, "context_artifact_citation_id": {"type": "string"}, "context_pack_key": {"type": "string"}, "context_pack_version": {"type": "integer"}, "path": {"type": "string"}, "heading": {"type": "string"}, "content_hash": {"type": "string"}, "start_line": {"type": "integer", "minimum": 1}, "end_line": {"type": "integer", "minimum": 1}, "allow_current_fallback": {"type": "boolean"}}, "allOf": [{"anyOf": [{"required": ["resource_id"]}, {"required": ["resource_ref"]}]}, {"anyOf": [{"required": ["context_artifact_citation_id"]}, {"required": ["snapshot_section_id", "source_snapshot_id"]}, {"required": ["source_snapshot_id", "path", "content_hash"]}]}]},
        },
        {
            "name": "sourcebrief.get_architecture",
            "description": "Return a compact permission-scoped architecture and graph overview before ad hoc search.",
            "inputSchema": {"type": "object", "properties": {"max_resources": {"type": "integer", "minimum": 1, "maximum": 50}, "max_items": {"type": "integer", "minimum": 1, "maximum": 50}}},
        },
        {
            "name": "sourcebrief.get_graph_inventory",
            "description": "Discover authorized published resource graphs and merge graphs by human key/title.",
            "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "kind": {"type": "string", "enum": ["resource", "merge", "all"]}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}, "cursor": {"type": "string"}}},
        },
        {
            "name": "sourcebrief.graph_query",
            "description": "Inspect a published resource or merge graph by human graph key with provenance/freshness.",
            "inputSchema": {"type": "object", "properties": {"graph_key": {"type": "string"}, "graph_kind": {"type": "string", "enum": ["resource", "merge", "auto"]}, "version": {"type": "integer", "minimum": 1}, "query": {"type": "string"}, "node_type": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 100}, "cursor": {"type": "string"}}, "required": ["graph_key"]},
        },
        {
            "name": "sourcebrief.graph_path",
            "description": "Find a bounded path through a published merge graph by node keys or human labels.",
            "inputSchema": {"type": "object", "properties": {"graph_key": {"type": "string"}, "graph_kind": {"type": "string", "enum": ["merge", "auto"]}, "version": {"type": "integer", "minimum": 1}, "from_node_key": {"type": "string"}, "to_node_key": {"type": "string"}, "from_label": {"type": "string"}, "to_label": {"type": "string"}, "max_depth": {"type": "integer", "minimum": 1, "maximum": 8}}, "required": ["graph_key"]},
        },
        {
            "name": "sourcebrief.get_agent_context",
            "description": "Return permission-scoped cited context for a SourceBrief project. By default the packet includes an extractive cited answer; set include_answer=false for raw context-only behavior. Code symbols require code:read and are omitted with a structured warning for context-only tokens.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "runtime": {"type": "string", "enum": ["api", "hermes", "claude", "codex", "cursor"]},
                    "profile": {"type": "string", "enum": sorted(RETRIEVAL_PROFILES)},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 50},
                    "resource_ids": {"type": "array", "items": {"type": "string"}},
                    "resource_ref": {"type": "string"}, "resource_refs": {"type": "array", "items": {"type": "string"}},
                    "context_pack_key": {"type": "string"},
                    "context_pack_version": {"type": "integer", "minimum": 1},
                    "max_chars": {"type": "integer", "minimum": 1000, "maximum": 50000},
                    "include_code_symbols": {"type": "boolean"},
                    "include_answer": {"type": "boolean"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "sourcebrief.search_code",
            "description": "Search indexed snapshot files without local repository access.",
            "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "resource_ids": {"type": "array", "items": {"type": "string"}}, "resource_ref": {"type": "string"}, "resource_refs": {"type": "array", "items": {"type": "string"}}, "top_k": {"type": "integer", "minimum": 1, "maximum": 50}}, "required": ["query"]},
        },
        {
            "name": "sourcebrief.grep_code",
            "description": "Run bounded grep over indexed snapshot files without local repository access.",
            "inputSchema": {"type": "object", "properties": {"pattern": {"type": "string"}, "resource_ids": {"type": "array", "items": {"type": "string"}}, "resource_ref": {"type": "string"}, "resource_refs": {"type": "array", "items": {"type": "string"}}, "path_glob": {"type": "string"}, "max_matches": {"type": "integer", "minimum": 1, "maximum": 100}, "regex": {"type": "boolean"}}, "required": ["pattern"]},
        },
        {
            "name": "sourcebrief.read_file",
            "description": "Read a line range from an indexed repo-relative file snapshot.",
            "inputSchema": {"type": "object", "properties": {"resource_id": {"type": "string"}, "resource_ref": {"type": "string"}, "resource_refs": {"type": "array", "items": {"type": "string"}}, "path": {"type": "string"}, "start_line": {"type": "integer", "minimum": 1}, "end_line": {"type": "integer", "minimum": 1}}, "required": ["path"], "anyOf": [{"required": ["resource_id"]}, {"required": ["resource_ref"]}]},
        },
        {
            "name": "sourcebrief.find_symbol",
            "description": "Find indexed code symbols by name and optional kind.",
            "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "kind": {"type": "string"}, "resource_ids": {"type": "array", "items": {"type": "string"}}, "resource_ref": {"type": "string"}, "resource_refs": {"type": "array", "items": {"type": "string"}}, "top_k": {"type": "integer", "minimum": 1, "maximum": 100}}, "required": ["name"]},
        },
        {
            "name": "sourcebrief.generate_skill_pack",
            "description": "Generate a project-specific Hermes skill pack from a published context pack. This creates server-side preview/download artifacts only; it never writes local runtime files.",
            "inputSchema": {"type": "object", "properties": {"pack_key": {"type": "string"}, "version": {"type": "integer", "minimum": 1}, "title": {"type": "string"}, "summary": {"type": "string"}, "approve_comment": {"type": "string"}}},
        },
        {
            "name": "sourcebrief.get_rpc_spec",
            "description": "Return the exact HTTP/JSON-RPC batch code-access schema, auth requirements, budgets, and failure-mode contract. MCP remains the default agent orchestration layer; this is for SDK/high-throughput clients.",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "sourcebrief.get_runtime_help",
            "description": "Return CLI-first instructions for installing generated SourceBrief skill packs and MCP runtime config locally.",
            "inputSchema": {"type": "object", "properties": {"target": {"type": "string", "enum": ["hermes"]}}},
        },
        {
            "name": "sourcebrief.generate_patch",
            "description": "Generate a patch proposal from authorized indexed snapshot files. Opt-in only; does not mutate a source repo.",
            "inputSchema": {"type": "object", "properties": {"resource_id": {"type": "string"}, "scope": {"type": "string"}, "files": {"type": "array", "items": {"type": "object"}}, "source_branch": {"type": "string"}, "target_branch": {"type": "string"}, "base_commit": {"type": "string"}}, "required": ["resource_id", "scope", "files"]},
        },
        {
            "name": "sourcebrief.open_pr",
            "description": "Record explicit approval for opening a PR from a generated patch. Opt-in approval record only; source-control mutation is handled by a separate approved integration.",
            "inputSchema": {"type": "object", "properties": {"patch_proposal_id": {"type": "string"}, "source_branch": {"type": "string"}, "target_branch": {"type": "string"}, "approval_note": {"type": "string"}, "github_pr_url": {"type": "string"}}, "required": ["patch_proposal_id", "source_branch", "target_branch", "approval_note"]},
        },
    ]


def runtime_help(args: Mapping[str, Any]) -> dict[str, Any]:
    target = str(args.get("target") or "hermes")
    if target != "hermes":
        raise HTTPException(status_code=422, detail="runtime help currently supports target=hermes")
    return {
        "target": "hermes",
        "flow": [
            "Generate and approve a project skill pack from a published context pack.",
            "Download or export the package locally; inspect SKILL.md, manifest.json, and references/.",
            "Run sourcebrief skill install --package <package> --target hermes --dry-run.",
            "Apply only with --apply; the installer writes a receipt without plaintext tokens.",
            "Rollback with sourcebrief skill uninstall --receipt <receipt.json>.",
        ],
        "commands": {
            "export": "sourcebrief skill export --workspace \"<name>\" --project \"<name>\" --pack-key default --approve-comment \"Approved\" --out ./sourcebrief-skill",
            "dry_run": "sourcebrief skill install --package ./sourcebrief-skill --target hermes --dry-run",
            "apply": "sourcebrief skill install --package ./sourcebrief-skill --target hermes --apply",
            "uninstall": "sourcebrief skill uninstall --receipt <receipt.json>",
        },
        "boundaries": [
            "The remote MCP server never mutates local files.",
            "Tokens stay in environment variables/runtime secret managers and are not embedded in the skill package or receipt.",
            "Non-default Hermes profiles require explicit --profile or --skills-dir.",
        ],
    }
