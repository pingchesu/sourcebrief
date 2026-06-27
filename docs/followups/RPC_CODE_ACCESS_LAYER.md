# RPC code access layer beside MCP

Status: Implemented first read-only batch/RPC surface for issue #134
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

## Implemented routes

SourceBrief now exposes the JSON/RPC-style batch route beside the existing single-operation `remote-code/*` HTTP endpoints.

### HTTP routes

```http
POST /workspaces/{workspace_id}/projects/{project_id}/code/rpc
GET  /workspaces/{workspace_id}/projects/{project_id}/code/rpc/spec

POST /workspaces/{workspace_id}/projects/{project_id}/remote-code/search_code  # legacy/single call
POST /workspaces/{workspace_id}/projects/{project_id}/remote-code/grep_code    # legacy/single call
POST /workspaces/{workspace_id}/projects/{project_id}/remote-code/read_file    # legacy/single call
POST /workspaces/{workspace_id}/projects/{project_id}/remote-code/find_symbol  # legacy/single call
```

### JSON-RPC methods

```text
sourcebrief.code.search
sourcebrief.code.grep
sourcebrief.code.read_batch
sourcebrief.code.lookup_plan
```

`code/rpc` accepts a `calls` array. Batch calls are evaluated under one caller principal and each call returns its own `ok`/`error` result. The batch-level status is `ok`, `partial`, or `error`.

MCP also exposes `sourcebrief.get_rpc_spec`, which returns the exact route/method/auth/budget/failure-mode contract so agents do not invent payloads from prose.

## Request schema sketch

```json
{
  "calls": [
    {
      "id": "plan",
      "method": "sourcebrief.code.lookup_plan",
      "params": {"query": "SkillExport", "resource_ref": "sourcebrief"}
    },
    {
      "id": "grep",
      "method": "sourcebrief.code.grep",
      "params": {"pattern": "SkillExport", "resource_ref": "sourcebrief", "path_glob": "apps/api/**", "max_matches": 20}
    },
    {
      "id": "read",
      "method": "sourcebrief.code.read_batch",
      "params": {"files": [{"resource_ref": "sourcebrief", "path": "apps/api/sourcebrief_api/main.py", "start_line": 1, "end_line": 80}]}
    }
  ],
  "fail_fast": false
}
```

Rules:

- `resource_ref` is the preferred user-facing locator and is allowed only when it resolves to exactly one authorized resource.
- `resource_ids` may list multiple authorized resources for cross-repo comparisons and remain an advanced/debug escape hatch.
- `path_glob` is strongly recommended for grep. Broad grep without it may return fail-soft warnings and retry guidance.
- Budgets are fixed server-side for now and returned by `GET /code/rpc/spec` / MCP `sourcebrief.get_rpc_spec`.

## Response schema sketch

```json
{
  "workspace_id": "...",
  "project_id": "...",
  "status": "ok|partial|error",
  "results": [
    {
      "id": "grep",
      "method": "sourcebrief.code.grep",
      "status": "ok",
      "result": {"matches": []},
      "error": null,
      "telemetry": {"elapsed_ms": 184.0}
    }
  ],
  "telemetry": {"elapsed_ms": 210.0, "call_count": 1, "error_count": 0}
}
```

## MCP contract

MCP remains the primary agent-facing surface.

MCP guidance now includes:

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

1. Keep current MCP tools and fail-soft behavior. ✅
2. Add internal service functions shared by MCP and HTTP RPC. ✅
3. Add read-only JSON/RPC batch endpoint behind existing auth/scopes. ✅
4. Add MCP `get_rpc_spec` so models do not invent payloads. ✅
5. Keep REST `search:batch`/`grep:batch`/`read:batch` wrappers as optional future SDK ergonomics if clients dislike the RPC envelope.
6. Add benchmark/QA smoke comparing MCP broad grep and RPC batch grep on the same indexed fixture.

## Acceptance criteria

- [x] Architecture doc lands and links from docs index.
- [x] Endpoint schemas have Pydantic/request-response tests.
- [x] Scope tests prove token/resource/project narrowing is identical to MCP.
- [x] Broad grep budget tests prove partial/fail-soft response and retry guidance.
- [x] Batch read/search tests prove telemetry fields. Cursor remains reserved because existing single-operation remote-code responses do not page yet.
- [x] MCP `get_rpc_spec` returns exact schema and does not require the model to invent payloads.
- [x] Integration gate exercises one real indexed repo snapshot through RPC and MCP.

## README timing decision

Keep the public README centered on MCP as the default runtime path. RPC is now implemented enough to document under runtime/code-access docs, but it should not become the primary README story until an SDK/client asks for it or benchmark evidence shows it materially improves a launch workflow.
