# Guide

This guide walks through the main ContextSmith workflow with the local API.

## 1. Start the stack

```bash
make compose-up
make migrate
```

Set shell helpers:

```bash
export API=http://localhost:18000
export AUTH='X-User-Email: demo@example.com'
```

## 2. Create a workspace

```bash
curl -s -X POST "$API/workspaces" \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"Demo Workspace","slug":"demo"}'
```

Save the returned `id`:

```bash
export WORKSPACE_ID=<workspace-id>
```

## 3. Create a project

```bash
curl -s -X POST "$API/workspaces/$WORKSPACE_ID/projects" \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"name":"Payments Knowledge","description":"Repos and runbooks for payments debugging"}'
```

Save the project id:

```bash
export PROJECT_ID=<project-id>
```

## 4. Add a markdown resource

```bash
curl -s -X POST "$API/workspaces/$WORKSPACE_ID/projects/$PROJECT_ID/resources" \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{
    "type":"markdown",
    "name":"Payment retry runbook",
    "uri":"doc://payment-retry-runbook",
    "source_config":{
      "content":"# Payment retry runbook\n\nIf a payment retry job stalls, inspect queue depth, worker status, and recent deploys. The marker payment-retry-contextsmith-demo proves retrieval."
    }
  }'
```

Save the resource id:

```bash
export RESOURCE_ID=<resource-id>
```

## 5. Refresh the resource

```bash
curl -s -X POST "$API/workspaces/$WORKSPACE_ID/projects/$PROJECT_ID/resources/$RESOURCE_ID/refresh" \
  -H "$AUTH"
```

Save the returned index run id:

```bash
export INDEX_RUN_ID=<index-run-id>
```

Check status:

```bash
curl -s "$API/workspaces/$WORKSPACE_ID/index-runs/$INDEX_RUN_ID" -H "$AUTH"
```

Wait until `status` is `succeeded`.

## 6. Search the project

```bash
curl -s -X POST "$API/workspaces/$WORKSPACE_ID/projects/$PROJECT_ID/search" \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"query":"payment-retry-contextsmith-demo"}'
```

Search results include citation fields such as resource id, snapshot id, version, ordinal, path, and content hash.

## 7. Build a context packet

```bash
curl -s -X POST "$API/workspaces/$WORKSPACE_ID/projects/$PROJECT_ID/context-packets" \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"query":"How do I debug payment retry stalls?","top_k":5}'
```

Context packets are the retrieval output used by agent-facing APIs. They include ranked items, citations, scores, and analytics ids.

## 8. Request agent-ready context

```bash
curl -s -X POST "$API/workspaces/$WORKSPACE_ID/projects/$PROJECT_ID/agent-context" \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{
    "query":"How do I debug payment retry stalls?",
    "runtime":"hermes",
    "top_k":5,
    "include_code_symbols":true,
    "max_chars":12000
  }'
```

The response includes:

- `instruction`: runtime-specific guidance for the calling agent
- `context`: cited text snippets
- `citations`: machine-readable citation metadata
- `symbols`: code symbols when available and requested
- `token_budget_hint`: approximate context budget guidance

Supported runtime profiles:

- `api`
- `hermes`
- `claude`
- `codex`
- `cursor`

## 9. Call the central MCP endpoint

List tools:

```bash
curl -s -X POST "$API/mcp/$WORKSPACE_ID/$PROJECT_ID" \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

Call the context tool:

```bash
curl -s -X POST "$API/mcp/$WORKSPACE_ID/$PROJECT_ID" \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{
    "jsonrpc":"2.0",
    "id":2,
    "method":"tools/call",
    "params":{
      "name":"contextsmith.get_agent_context",
      "arguments":{
        "query":"How do I debug payment retry stalls?",
        "runtime":"claude"
      }
    }
  }'
```

ContextSmith exposes context through MCP. It does not expose production mutations through repo agents.

## 10. Review resource usage and freshness

Resource review queue:

```bash
curl -s "$API/workspaces/$WORKSPACE_ID/projects/$PROJECT_ID/resource-review" -H "$AUTH"
```

Resource usage analytics:

```bash
curl -s "$API/workspaces/$WORKSPACE_ID/projects/$PROJECT_ID/resource-usage" -H "$AUTH"
```

Mark a resource reviewed:

```bash
curl -s -X POST "$API/workspaces/$WORKSPACE_ID/projects/$PROJECT_ID/resources/$RESOURCE_ID/review" \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"review_status":"approved","review_note":"Useful runbook","stale_after_days":30}'
```

Archive a resource:

```bash
curl -s -X POST "$API/workspaces/$WORKSPACE_ID/projects/$PROJECT_ID/resources/$RESOURCE_ID/archive" \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{"reason":"superseded by new runbook"}'
```

Delete a resource:

```bash
curl -s -X DELETE "$API/workspaces/$WORKSPACE_ID/projects/$PROJECT_ID/resources/$RESOURCE_ID" \
  -H "$AUTH"
```

## Git repository resources

Git resources use `type: "git"`. The current local smoke flow uses a mounted git bundle fixture so the worker can index it inside Docker. Public clone support should be hardened before broad production use.

Minimal shape:

```json
{
  "type": "git",
  "name": "Example repo",
  "uri": "https://github.com/example/repo.git",
  "source_config": {}
}
```

The indexer stores commit/version metadata and extracts deterministic code symbols with file and line citations.
