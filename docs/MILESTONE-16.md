# M16 — Hermes and MCP Integration Pack

## Goal

Make a SourceBrief project directly consumable by Hermes as a read-only project knowledge backend, without creating one MCP server per repo and without allowing production mutations through repo agents.

## Shipped artifacts

- `scripts/hermes_integration.py`
  - creates a Hermes-scoped SourceBrief bearer token, unless `--token` is supplied
  - restricts created-token scopes to read-only/project-query scopes
  - validates the created token's scopes and project/resource allowlists
  - proves the token cannot create child tokens, create resources, refresh resources, or mutate resource review state
  - validates REST `agent-context` with `runtime=hermes`, citations, context text, requested-resource citations, and optional `--expect-text`
  - validates central MCP JSON-RPC `initialize`, `tools/list`, and `tools/call`
  - compares REST/MCP citation resource sets
  - prints a ready-to-paste Hermes `mcp_servers` config block
  - supports `--redact-token` for CI/smoke logs
- Existing central MCP endpoint: `POST /mcp/{workspace_id}/{project_id}`
  - `initialize`
  - `tools/list`
  - `tools/call` for `sourcebrief.get_agent_context`
- Existing REST endpoint: `POST /workspaces/{workspace_id}/projects/{project_id}/agent-context`
- QA smoke executes the Hermes integration script against the real Docker Compose stack.

## Create and validate a Hermes token

```bash
python scripts/hermes_integration.py \
  --api-url http://localhost:18000 \
  --workspace-id <workspace_uuid> \
  --project-id <project_uuid> \
  --resource-id <optional_resource_uuid> \
  --query "how does this project handle refresh?"
```

The script fails closed unless it receives cited context. Use `--allow-empty` only for intentionally empty projects.

Default token scopes:

- `project:read`
- `project:query`
- `resource:read`
- `review:read`

Created-token scopes are intentionally restricted to that read-only allowlist. Passing write/admin scopes fails before token creation. The generated token is allowlisted to the selected project and optional resources. It is not allowed to create resources, refresh jobs, mutate reviews, or create child tokens; the script verifies those denials.

## Hermes native MCP config

Paste the emitted `hermes_config.mcp_servers` block into the target Hermes profile config, for example `~/.hermes/config.yaml`:

```yaml
mcp_servers:
  sourcebrief:
    url: "http://localhost:18000/mcp/<workspace_uuid>/<project_uuid>"
    headers:
      Authorization: "Bearer <sourcebrief_token>"
    timeout: 120
    connect_timeout: 30
```

Then either restart Hermes, or for a running gateway that supports reload, ask the human operator to send `/reload-mcp` and approve the reload. Do not assume a bot-originated slash command will execute.

After discovery, Hermes registers the tool with the usual prefixing convention:

```text
mcp_sourcebrief_sourcebrief_get_agent_context
```

Ask Hermes a question like:

```text
Use SourceBrief to answer: how does this project handle refresh scheduling? Include citations.
```

## REST fallback for Hermes or other agents

If MCP discovery is not available, agents can call REST directly:

```bash
export CS_AUTH_HEADER='Authorization: Bearer <sourcebrief_token>'
curl -sS \
  -H "$CS_AUTH_HEADER" \
  -H "Content-Type: application/json" \
  -d '{"query":"how does refresh scheduling work?","runtime":"hermes","top_k":8}' \
  http://localhost:18000/workspaces/<workspace_uuid>/projects/<project_uuid>/agent-context
```

## Production boundary

SourceBrief is a **read-only context provider** for agents.

- It can return cited project/resource context.
- It can expose review/usage metadata to help humans clean drift.
- It does **not** execute production mutations.
- Prod actions must continue through Hermes approval, typed external MCP tools, and evidence workflows.
- SourceBrief does not hold AWS/Teleport/customer production credentials.

## Verification

```bash
python -m py_compile scripts/hermes_integration.py scripts/qa_smoke.py
make lint
.venv/bin/pytest tests/unit tests/integration -q
make qa-smoke
```

Real-service smoke verifies:

- Hermes integration script creates/validates a scoped token.
- Created token has exactly the expected read-only scopes.
- Created token is project/resource allowlisted.
- The script proves child-token creation, resource creation, refresh, and review mutation are denied.
- REST `agent-context` returns `runtime=hermes` with citations and context text.
- MCP `initialize`, `tools/list`, and `tools/call` work with bearer token auth.
- The tool list includes `sourcebrief.get_agent_context`.
- The script emits Hermes config without leaking plaintext `cs_...` tokens when `--redact-token` is used.
