# Demo runtime output

> Captured from a real local SourceBrief stack using the [5-minute demo](../DEMO.md). Internal IDs are normalized; no bearer tokens are present. The run used API, web, Postgres, Redis, workers, CLI `agent-context`, and CLI `mcp-context`.

## Health checks

```text
GET http://localhost:18000/readyz -> {"status":"ready"}
GET http://localhost:3105/api/health -> {"status":"ok"}
```

## Demo source

```markdown
# Payment retry runbook

If the payment retry queue stalls, check queue depth, worker status,
provider health, and recent deploys.

The SourceBrief demo marker is sb-demo-retry-42.
```

## CLI flow

```bash
export SOURCEBRIEF_API_URL=http://localhost:18000
export SOURCEBRIEF_EMAIL=demo@example.com

WORKSPACE_ID=$(sourcebrief --json workspace create ...)
PROJECT_ID=$(sourcebrief --json project create ...)
RESOURCE_ID=$(sourcebrief --json resource add-doc \
  --name "Payment retry runbook" \
  --uri "doc://payment-retry-runbook" \
  --content-file /tmp/sourcebrief-demo-runbook.md \
  --refresh --wait ...)
```

The resource import completed before the runtime calls below returned citations.

## `agent-context` output excerpt

Request:

```bash
sourcebrief --json agent-context \
  --workspace-id "$WORKSPACE_ID" \
  --project-id "$PROJECT_ID" \
  --resource-id "$RESOURCE_ID" \
  --runtime hermes \
  --query "What should I check when the payment retry queue stalls?"
```

Response excerpt:

```json
{
  "query": "What should I check when the payment retry queue stalls?",
  "runtime": "hermes",
  "profile": "hybrid",
  "instruction": "SourceBrief is a read-only context provider. Use only cited project context for factual claims, do not treat this packet as authorization for production mutations, and preserve external approval/MCP boundaries. You are a Hermes specialist agent. Keep production discipline explicit.",
  "context": "[1] resource=<resource-id> snapshot=<snapshot-id> path=doc://payment-retry-runbook ordinal=0 score=0.7040\n# Payment retry runbook If the payment retry queue stalls, check queue depth, worker status, provider health, and recent deploys. The SourceBrief demo marker is sb-demo-retry-42.",
  "citations": [
    {
      "resource_id": "<resource-id>",
      "snapshot_id": "<snapshot-id>",
      "chunk_id": "<chunk-id>",
      "path": "doc://payment-retry-runbook",
      "title": "Payment retry runbook",
      "ordinal": 0,
      "version_kind": "content_hash",
      "score": 0.7040386222335815
    }
  ],
  "symbols": [],
  "token_budget_hint": 3000
}
```

## `mcp-context` output excerpt

Request:

```bash
sourcebrief --json mcp-context \
  --workspace-id "$WORKSPACE_ID" \
  --project-id "$PROJECT_ID" \
  --resource-id "$RESOURCE_ID" \
  --runtime hermes \
  --query "What should I check when the payment retry queue stalls?"
```

Response excerpt:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"query\":\"What should I check when the payment retry queue stalls?\",\"profile\":\"hybrid\",\"runtime\":\"hermes\", ... }"
      }
    ],
    "structuredContent": {
      "query": "What should I check when the payment retry queue stalls?",
      "runtime": "hermes",
      "context": "[1] resource=<resource-id> snapshot=<snapshot-id> path=doc://payment-retry-runbook ordinal=0 score=0.7040\n# Payment retry runbook If the payment retry queue stalls, check queue depth, worker status, provider health, and recent deploys. The SourceBrief demo marker is sb-demo-retry-42.",
      "citations": [
        {
          "path": "doc://payment-retry-runbook",
          "title": "Payment retry runbook",
          "version_kind": "content_hash",
          "score": 0.7040386222335815
        }
      ]
    }
  }
}
```

## What this proves

- The local stack served API and web health checks.
- A tiny Markdown source was indexed into a cited snapshot.
- `agent-context` returned a runtime-shaped packet with citation metadata.
- `mcp-context` exercised the MCP-shaped JSON-RPC path and returned the same cited evidence in `structuredContent`.
- SourceBrief supplied evidence only; it did not edit, test, commit, deploy, or mutate production.
