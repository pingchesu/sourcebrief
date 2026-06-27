# RPC code access layer beside MCP

Status: Proposed follow-up for issue #134
Owner: SourceBrief runtime/retrieval
Decision: keep MCP as the agent entry point; add a lower-level HTTP/JSON-RPC batch surface for high-throughput code access.

## Problem

MCP is the right interoperability surface for agent runtimes: tools are discoverable, permission-scoped, and easy for agents to call. It is not always the best transport for repeated broad code-navigation loops. Broad `grep_code`, repeated `read_file`, and multi-path inspection need batching, cursors, budget telemetry, and stable machine schemas that SDKs can call without model-mediated retries.

The failure mode to avoid:

```text
MCP tells the agent: "call this HTTP endpoint"
  -> model hand-writes payloads
  -> auth/schema/budget mistakes
  -> accidental broad scans or uncited answers
```

## Goal

Provide a two-layer contract:

1. **MCP orchestration layer** — the default agent UX: `sourcebrief.ask`, `sourcebrief.lookup`, `sourcebrief.grep_code`, `sourcebrief.read_file`, suggested next calls, citations, and runtime guidance.
2. **HTTP/JSON-RPC code-access layer** — a backend/SDK surface for high-throughput batch search/read/grep over authorized indexed snapshots.

MCP tools may call the RPC layer server-side. Advanced agents/SDKs may request the RPC spec from MCP and call it directly only when the runtime has explicit auth and budget handling.

## Non-goals

- Do not replace MCP or remove existing MCP tool names.
- Do not expose mutable worker checkouts or local filesystem paths.
- Do not bypass project/resource/token scopes; `code:read` remains required for code drilldown.
- Do not create source-control write, test execution, PR, or deploy capabilities in this layer.
- Do not ask the model to invent endpoint schemas from prose.

## Proposed routes

Use normal HTTP endpoints first, with an optional JSON-RPC envelope for clients that want batch RPC semantics.

### REST-style routes

```http
POST /workspaces/{workspace_id}/projects/{project_id}/code/search:batch
POST /workspaces/{workspace_id}/projects/{project_id}/code/grep:batch
POST /workspaces/{workspace_id}/projects/{project_id}/code/read:batch
POST /workspaces/{workspace_id}/projects/{project_id}/code/rpc
```

### JSON-RPC methods

```text
sourcebrief.code.search
sourcebrief.code.grep
sourcebrief.code.read_batch
sourcebrief.code.lookup_plan
```

`code/rpc` accepts either one JSON-RPC request or a JSON-RPC batch array. Batch calls are evaluated under one caller principal and one request-level budget envelope.

## Request schema sketch

```json
{
  "resource_ref": "sourcebrief",
  "resource_ids": null,
  "context_pack_key": null,
  "context_pack_version": null,
  "query": "class SkillExport",
  "pattern": "SkillExport",
  "path_glob": "apps/api/**/*.py",
  "regex": false,
  "max_matches": 50,
  "cursor": null,
  "budget": {
    "max_files_scanned": 2000,
    "max_bytes_scanned": 20000000,
    "deadline_ms": 3000
  },
  "include": {
    "snippets": true,
    "symbols": true,
    "telemetry": true
  }
}
```

Rules:

- `resource_ref` is allowed only when it resolves to exactly one authorized resource.
- `resource_ids` may list multiple authorized resources for cross-repo comparisons.
- `context_pack_key/version` narrows the search to the pack intersection; it must not widen access.
- `path_glob` is strongly recommended for grep. Broad grep without it may return fail-soft warnings and retry guidance.
- `budget` is explicit and echoed back in the response.

## Response schema sketch

```json
{
  "status": "ok|partial|budget_exceeded|stale_snapshot|not_queryable|forbidden",
  "results": [
    {
      "resource_id": "res_xxx",
      "resource_ref": "sourcebrief",
      "snapshot_id": "snap_xxx",
      "indexed_commit": "abc123",
      "path": "apps/api/sourcebrief_api/main.py",
      "start_line": 1261,
      "end_line": 1278,
      "snippet": "class SkillExport(...)",
      "symbol_keys": ["python:SkillExport"],
      "citation": {
        "locator": "read_file(resource_ref='sourcebrief', path='apps/api/sourcebrief_api/main.py', start_line=1261, end_line=1278)",
        "content_hash": "sha256:..."
      }
    }
  ],
  "warnings": [
    {
      "code": "budget_exceeded",
      "message": "remote code scan exceeded max_bytes_scanned",
      "retry_guidance": [
        "Call sourcebrief.ask or lookup(search_in='docs') first, then grep cited directories.",
        "Retry with path_glob such as 'apps/api/**' or an exact cited path."
      ]
    }
  ],
  "page": {
    "next_cursor": "opaque-cursor-or-null"
  },
  "telemetry": {
    "elapsed_ms": 184,
    "files_scanned": 132,
    "bytes_scanned": 1849233,
    "cache_hit": false,
    "budget": {
      "max_files_scanned": 2000,
      "max_bytes_scanned": 20000000,
      "deadline_ms": 3000
    }
  }
}
```

## MCP contract

MCP remains the primary agent-facing surface.

Add or extend MCP guidance with:

- `sourcebrief.get_runtime_help` — returns MCP vs CLI vs RPC usage guidance for a runtime.
- `sourcebrief.get_rpc_spec` — returns the exact machine-readable RPC schema, auth requirements, budget defaults, and examples.
- `sourcebrief.lookup` / `sourcebrief.grep_code` — may return `rpc_available: true` plus a stable `rpc_call_hint` for SDKs.

Important: MCP should not merely say "use HTTP" in prose. It must provide validated schemas and examples, or call the RPC backend itself.

## Observability

Every RPC response and backing MCP call should make these visible in logs/telemetry:

- caller principal type: session token, API token, dev header;
- workspace/project/resource scope;
- requested method;
- files scanned;
- bytes scanned;
- result count;
- elapsed time;
- cache hit/miss;
- budget code when partial/failed;
- snapshot freshness / current snapshot ID;
- whether `code:read` was required and present.

## Failure modes

| Failure | Contract |
| --- | --- |
| Missing `code:read` | Return docs/context-only guidance; do not leak code paths/snippets. |
| Broad grep exceeds budget | Return `partial` or `budget_exceeded` with scanned counts, no crash-only failure. |
| No current snapshot | Return `not_queryable` and latest index-run status/link. |
| Stale snapshot | Return results with freshness warning and refresh command/route. |
| Ambiguous `resource_ref` | Fail closed with candidate names; require exact ref or ID. |
| Pack/resource intersection empty | Return empty with warning; do not widen to full project. |
| Cursor expired | Return explicit `cursor_expired`; caller restarts from a narrower query. |

## Migration path

1. Keep current MCP tools and fail-soft behavior.
2. Add internal service functions shared by MCP and HTTP RPC.
3. Add read-only REST batch endpoints behind existing auth/scopes.
4. Add JSON-RPC envelope if SDK/client demand exists.
5. Add MCP `get_rpc_spec` and `get_runtime_help` only after the RPC schema is stable.
6. Add benchmark/QA smoke comparing MCP broad grep and RPC batch grep on the same indexed fixture.

## Acceptance criteria

- [ ] Architecture doc lands and links from docs index.
- [ ] Endpoint schemas have Pydantic/request-response tests.
- [ ] Scope tests prove token/resource/project narrowing is identical to MCP.
- [ ] Broad grep budget tests prove partial/fail-soft response and retry guidance.
- [ ] Batch read/search tests prove cursor/telemetry fields.
- [ ] MCP `get_rpc_spec` returns exact schema and does not require the model to invent payloads.
- [ ] QA smoke or integration gate exercises one real indexed repo snapshot through RPC and MCP.

## README timing decision

Do not refactor the public README around RPC until at least the API schema, auth behavior, and one real example are implemented. For now, README should mention MCP as the default runtime path and link to this follow-up/spec as planned high-throughput code access.
