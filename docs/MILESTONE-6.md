# Milestone 6: Agent Integrations

Milestone 6 makes each SourceBrief project usable as a permission-scoped agent
context provider for API clients, Hermes, Claude, Codex, Cursor, and a central
MCP integration.

## Scope

Implemented in this milestone:

- `POST /workspaces/{workspace_id}/projects/{project_id}/agent-context`
  - builds runtime-specific agent packets from hybrid retrieval
  - includes cited snippets, citation metadata, optional code symbols, and a
    token budget hint
  - supports runtime profiles: `api`, `hermes`, `claude`, `codex`, `cursor`
- `POST /mcp/{workspace_id}/{project_id}`
  - minimal central JSON-RPC/MCP-compatible endpoint
  - exposes one typed tool: `sourcebrief.get_agent_context`
  - intentionally does not expose production actions; external operations stay
    behind dedicated MCP tools and approval flows
- Permission-scoped behavior for both API and MCP paths.
- QA smoke coverage for API agent context and MCP `tools/list`/`tools/call`.

## API contract

Example request:

```json
POST /workspaces/{workspace_id}/projects/{project_id}/agent-context
{
  "query": "payment retry runbook",
  "runtime": "hermes",
  "top_k": 8,
  "include_code_symbols": true,
  "max_chars": 12000
}
```

Example response shape:

```json
{
  "query": "payment retry runbook",
  "runtime": "hermes",
  "instruction": "You are a Hermes specialist agent...",
  "context": "[1] resource=... snapshot=... path=... score=...\n...",
  "citations": [
    {"resource_id": "...", "snapshot_id": "...", "chunk_id": "...", "path": "...", "score": 0.9}
  ],
  "symbols": [],
  "token_budget_hint": 3000
}
```

## MCP contract

The central MCP endpoint exposes only context retrieval:

- `initialize`
- `tools/list`
- `tools/call` with `sourcebrief.get_agent_context`

This follows the product constraint that SourceBrief should not create one MCP
server per repo and should not allow repo agents to own production mutation
boundaries.

## Verification

Milestone 6 is covered by:

- `tests/integration/test_agent_integrations_flow.py`
- `scripts/qa_smoke.py`
- `make verify`

The smoke path now validates:

1. document + git ingestion
2. snapshots/chunks/embeddings/code symbols
3. lexical/hybrid retrieval
4. resource usage/review lifecycle
5. agent-context API
6. central MCP context tool
7. auth denial and frontend health
