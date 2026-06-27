# SourceBrief 5-minute demo

This demo proves the shortest SourceBrief loop without waiting on a large Git import:

```text
small source -> indexed snapshot -> cited agent context -> MCP-shaped response
```

It is intentionally deterministic. Use it when you want to show the product idea before moving to a real repository.

## Assumptions

- The local stack is already running. See [Quick start](QUICKSTART.md).
- The CLI is on your path.
- You can log in with the admin email/password from `.env`.

Configure the CLI demo environment and save a local session token:

```bash
export SOURCEBRIEF_API_URL=http://localhost:18000
sourcebrief login --password-env SOURCEBRIEF_ADMIN_PASSWORD
```

For agents/CI or shared deployments, use a scoped bearer token instead of a saved human session.

## 1. Create a tiny source

```bash
cat > /tmp/sourcebrief-demo-runbook.md <<'EOF'
# Payment retry runbook

If the payment retry queue stalls, check queue depth, worker status,
provider health, and recent deploys.

The SourceBrief demo marker is sb-demo-retry-42.
EOF
```

## 2. Create a workspace and project

```bash
WORKSPACE_ID=$(sourcebrief --json workspace create \
  --name "Demo" \
  --slug "demo-$(date +%s)" \
  | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')

PROJECT_ID=$(sourcebrief --json project create \
  --workspace-id "$WORKSPACE_ID" \
  --name "Demo Project" \
  | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')
```

The CLI is automation-oriented and supports name-first workspace/project selection for normal use, while IDs remain advanced/debug escape hatches. For agent runtimes, MCP plus generated skills are the primary path; CLI commands are useful for bootstrap, validation, resource lifecycle automation, and fallback debugging.

## 3. Add and index the source

Save the workspace/project IDs once so later commands can use the human-facing golden path:

```bash
sourcebrief use \
  --workspace-id "$WORKSPACE_ID" \
  --project-id "$PROJECT_ID"

sourcebrief status
```

Then add and index the source. Resource creation remains explicit so scripts do not accidentally add sources to the wrong project:

```bash
RESOURCE_JSON=$(sourcebrief --json resource add-doc \
  --workspace-id "$WORKSPACE_ID" \
  --project-id "$PROJECT_ID" \
  --name "Payment retry runbook" \
  --uri "doc://payment-retry-runbook" \
  --content-file /tmp/sourcebrief-demo-runbook.md \
  --refresh \
  --wait)

RESOURCE_ID=$(printf '%s' "$RESOURCE_JSON" \
  | python -c 'import json,sys; print(json.load(sys.stdin)["resource"]["id"])')
```

## 4. Ask for cited context

Golden path: ask by the human resource name and get a concise cited answer.

```bash
sourcebrief ask \
  --runtime hermes \
  --resource "Payment retry runbook" \
  "What should I check when the payment retry queue stalls?"
```

Use raw JSON only when validating the runtime packet contract:

```bash
sourcebrief ask --json \
  --runtime hermes \
  --resource "Payment retry runbook" \
  "What should I check when the payment retry queue stalls?"
```

Equivalent explicit/API-shaped form:

```bash
sourcebrief --json agent-context \
  --workspace-id "$WORKSPACE_ID" \
  --project-id "$PROJECT_ID" \
  --resource-id "$RESOURCE_ID" \
  --runtime hermes \
  --query "What should I check when the payment retry queue stalls?"
```

A useful response should mention the queue depth, worker status, provider health, and recent deploys, with citations back to the demo runbook.

## 5. Exercise the MCP-shaped path

```bash
sourcebrief --json mcp-context \
  --workspace-id "$WORKSPACE_ID" \
  --project-id "$PROJECT_ID" \
  --resource-id "$RESOURCE_ID" \
  --runtime hermes \
  --query "What should I check when the payment retry queue stalls?"
```

This calls the same project-scoped MCP surface an agent runtime would use. The important proof is not that the answer sounds right; it should be inspectable and cite the exact indexed source.

## What this demo proves

- SourceBrief can index source material into a snapshot.
- Agent-shaped context is generated from that indexed evidence.
- The response carries citations and follow-up handles instead of unsupported prose.
- MCP is the runtime path for agents; SourceBrief still does not edit, test, commit, or deploy anything.

See [demo runtime output](examples/demo-runtime-output.md) for a captured real run with normalized IDs. See [proof artifacts](PROOF_ARTIFACTS.md) for the full manifest of committed screenshots, runtime outputs, automated proof paths, and known proof gaps.

## What to try next

- Use the web Workbench to ask the same question and inspect citations visually.
- Add a real Git resource from [Quick start](QUICKSTART.md).
- Generate a runtime install plan from [Runtime install plan](RUNTIME_INSTALL_PLAN.md).
- Connect an actual agent using [Agent runtime usage](AGENT_RUNTIME_USAGE.md).
