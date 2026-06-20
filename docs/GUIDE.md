# Guide

This guide walks through the main SourceBrief workflow with the CLI and the local API.

## 1. Start the stack

```bash
make compose-up
make migrate
```

Set shell helpers:

```bash
export API=http://localhost:18000
export AUTH='X-User-Email: demo@example.com'
export SOURCEBRIEF_API_URL=$API
export SOURCEBRIEF_EMAIL=demo@example.com
```

The examples below show curl first because it exposes the API shape. The same flow can be run through the CLI; see [CLI workflow](#cli-workflow) and [Git repository resources](#git-repository-resources).

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
      "content":"# Payment retry runbook\n\nIf a payment retry job stalls, inspect queue depth, worker status, and recent deploys. The marker payment-retry-sourcebrief-demo proves retrieval."
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
  -d '{"query":"payment-retry-sourcebrief-demo"}'
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
      "name":"sourcebrief.get_agent_context",
      "arguments":{
        "query":"How do I debug payment retry stalls?",
        "runtime":"claude"
      }
    }
  }'
```

SourceBrief exposes context through MCP. It does not expose production mutations through repo agents.

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

Git resources use `type: "git"`. This is the repo-as-agent path: SourceBrief clones the repository in the worker, captures the commit SHA, indexes text/source files, extracts code symbols, and returns citations with path/line/commit metadata.

### Add a public repo with the CLI

```bash
sourcebrief resource add-repo \
  --workspace-id $WORKSPACE_ID \
  --project-id $PROJECT_ID \
  --name "SourceBrief repo" \
  --repo-url https://github.com/pingchesu/sourcebrief.git \
  --branch main \
  --max-files 500 \
  --refresh \
  --wait
```

Search the repo:

```bash
sourcebrief search \
  --workspace-id $WORKSPACE_ID \
  --project-id $PROJECT_ID \
  --query "agent-context API"
```

Ask for runtime-shaped context:

```bash
sourcebrief agent-context \
  --workspace-id $WORKSPACE_ID \
  --project-id $PROJECT_ID \
  --runtime codex \
  --query "How does SourceBrief expose MCP context?"
```

### Add a public repo with curl

Minimal shape:

```bash
curl -s -X POST "$API/workspaces/$WORKSPACE_ID/projects/$PROJECT_ID/resources" \
  -H "$AUTH" -H 'Content-Type: application/json' \
  -d '{
    "type":"git",
    "name":"SourceBrief repo",
    "uri":"https://github.com/pingchesu/sourcebrief.git",
    "source_config":{
      "url":"https://github.com/pingchesu/sourcebrief.git",
      "branch":"main",
      "max_repo_files":500
    }
  }'
```

Refresh it the same way as a markdown resource, then use search, context packets, code search, or agent-context requests.

Local filesystem repos are disabled by default in workers. They can be enabled for controlled local smoke tests with `SOURCEBRIEF_ALLOW_LOCAL_GIT=true`, but public deployments should prefer public HTTPS remotes or a hardened connector.

## CLI workflow

The Python package installs a `sourcebrief` command:

```bash
sourcebrief --help
```

Useful commands:

```bash
sourcebrief health
sourcebrief workspace create --name Demo --slug demo
sourcebrief project create --workspace-id <workspace-id> --name "Demo Project"
sourcebrief resource add-doc --workspace-id <workspace-id> --project-id <project-id> --name Runbook --uri doc://runbook --content-file runbook.md --refresh --wait
sourcebrief resource add-repo --workspace-id <workspace-id> --project-id <project-id> --name Repo --repo-url https://github.com/example/repo.git --refresh --wait
sourcebrief resource list --workspace-id <workspace-id> --project-id <project-id>
sourcebrief search --workspace-id <workspace-id> --project-id <project-id> --query "payment retry"
sourcebrief agent-context --workspace-id <workspace-id> --project-id <project-id> --runtime hermes --query "payment retry runbook"
sourcebrief mcp-context --workspace-id <workspace-id> --project-id <project-id> --runtime claude --query "payment retry runbook"
```

Global options:

```bash
sourcebrief --api-url http://localhost:18000 --email demo@example.com --json search ...
```

Environment variables:

```bash
export SOURCEBRIEF_API_URL=http://localhost:18000
export SOURCEBRIEF_EMAIL=demo@example.com
```
