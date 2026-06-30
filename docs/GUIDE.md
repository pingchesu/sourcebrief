# Guide

This guide walks through the main SourceBrief workflow after the local stack is running. If you are new to the project, start with [Quick start](QUICKSTART.md) first.

If you already understand the UI and want to connect Hermes, Claude Code, Codex, Cursor, MCP, or generated skills, read [Agent runtime usage](AGENT_RUNTIME_USAGE.md).

## 1. Start the stack

```bash
make compose-up
make quickstart-ready
```

Log in through the CLI. `sourcebrief login` reads the admin email/password from environment variables or the local `.env` file:

```bash
make venv
export PATH="$PWD/.venv/bin:$PATH"
export SOURCEBRIEF_API_URL=http://localhost:18000
sourcebrief login --password-env SOURCEBRIEF_ADMIN_PASSWORD
```

Bearer API tokens are useful after a workspace exists, for project/resource/query/MCP flows. They cannot create workspaces.

## 2. Create and select a workspace/project

Use names and slugs in the normal path. SourceBrief resolves them internally.

```bash
WORKSPACE_SLUG=demo
PROJECT_NAME="Payments Knowledge"

sourcebrief workspace create \
  --name "Demo Workspace" \
  --slug "$WORKSPACE_SLUG"

sourcebrief project create \
  --workspace "$WORKSPACE_SLUG" \
  --name "$PROJECT_NAME" \
  --description "Repos and runbooks for payments debugging"

sourcebrief use --workspace "$WORKSPACE_SLUG" --project "$PROJECT_NAME"
sourcebrief status
```

## 3. Add a markdown resource

```bash
cat > /tmp/payment-retry-runbook.md <<'EOF'
# Payment retry runbook

If a payment retry job stalls, inspect queue depth, worker status, and recent deploys. The marker payment-retry-sourcebrief-demo proves retrieval.
EOF

sourcebrief resource add-doc \
  --name "Payment retry runbook" \
  --uri "doc://payment-retry-runbook" \
  --content-file /tmp/payment-retry-runbook.md \
  --refresh \
  --wait
```

The command creates the resource, triggers indexing, and waits for the background run to finish.

## 4. Search and ask with citations

Search the selected project:

```bash
sourcebrief search --query "payment-retry-sourcebrief-demo"
```

Ask for a cited answer:

```bash
sourcebrief ask \
  --resource "Payment retry runbook" \
  "How do I debug payment retry stalls?"
```

Request runtime-shaped context for an agent:

```bash
sourcebrief agent-context \
  --runtime hermes \
  --resource "Payment retry runbook" \
  --query "How do I debug payment retry stalls?"
```

The response includes runtime guidance, cited context, machine-readable citation metadata, and token budget hints.

Supported runtime profiles:

- `api`
- `hermes`
- `claude`
- `codex`
- `cursor`

## 5. Call the MCP-shaped context path

For the same selected workspace/project, the CLI can call the central MCP context tool without requiring you to copy internal identifiers:

```bash
sourcebrief mcp-context \
  --runtime claude \
  --resource "Payment retry runbook" \
  --query "How do I debug payment retry stalls?"
```

SourceBrief exposes context through MCP. It does not expose production mutations through repo agents.

## 6. Review resource usage and freshness

List resources and review/freshness state:

```bash
sourcebrief resource list
```

Use the web **Sources** / **Quality** pages to update review decisions and inspect freshness, index status, usage, and coverage. The UI keeps resources name-first; internal handles are secondary debug metadata.

If you need exact REST endpoint shapes for automation, use [Architecture](ARCHITECTURE.md) or fetch machine-readable schemas from the API/runtime tooling. The guide keeps the product path name-first.

## 7. Git repository resources

Git resources use `type: "git"`. This is the repo-as-agent path: SourceBrief clones the repository in the worker, captures the commit SHA, indexes text/source files, extracts code symbols, and returns citations with path/line/commit metadata.

### Add a public repo with the CLI

Use `sourcebrief resource add-repo` for a name-first CLI import. Keep the initial import bounded with `--max-files` and related budget flags when a repository may be large; SourceBrief surfaces partial coverage instead of hiding a capped corpus.

```bash
sourcebrief resource add-repo \
  --name "SourceBrief repo" \
  --repo-url https://github.com/pingchesu/sourcebrief.git \
  --branch main \
  --max-files 500 \
  --refresh \
  --wait
```

Search the repo:

```bash
sourcebrief search --query "agent-context API"
```

Ask for runtime-shaped context:

```bash
sourcebrief agent-context \
  --runtime codex \
  --resource "SourceBrief repo" \
  --query "How does SourceBrief expose MCP context?"
```

In the local Compose stack, filesystem Git repos are enabled by `.env.example` through `SOURCEBRIEF_ALLOW_LOCAL_GIT=true` so smoke tests and local demos can index `file://` fixtures. The worker's safer standalone default is disabled when that environment variable is absent. Public or shared deployments should prefer public HTTPS remotes or a hardened private-repo connector.

## CLI workflow summary

Useful commands:

```bash
sourcebrief health
sourcebrief workspace create --name Demo --slug demo
sourcebrief project create --workspace Demo --name "Demo Project"
sourcebrief use --workspace Demo --project "Demo Project"
sourcebrief resource add-doc --name Runbook --uri doc://runbook --content-file runbook.md --refresh --wait
sourcebrief resource add-repo --name Repo --repo-url https://github.com/example/repo.git --refresh --wait
sourcebrief resource list
sourcebrief search --query "payment retry"
sourcebrief agent-context --runtime hermes --query "payment retry runbook"
sourcebrief mcp-context --runtime claude --query "payment retry runbook"
```

The primary CLI path is name-first. Advanced/debug flags for exact internal identifiers still exist, but they are not the normal product workflow.

Global options:

```bash
sourcebrief --api-url http://localhost:18000 --email demo@example.com --json search ...
```

Environment variables:

```bash
export SOURCEBRIEF_API_URL=http://localhost:18000
export SOURCEBRIEF_EMAIL=demo@example.com
```
