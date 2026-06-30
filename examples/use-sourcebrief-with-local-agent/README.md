# Use SourceBrief with a local agent

This example is the product-led counterpart to the 50-question evaluation example. It is about using SourceBrief as a project context layer for a local coding agent, not merely asking SourceBrief questions about public repos.

The intended user story is deliberately stronger than "run a CLI command":

```text
I have a project.
I connect it to SourceBrief.
SourceBrief indexes, reviews, and packages project context.
My local agent installs a small project skill/instruction pack.
The agent uses SourceBrief MCP/API for citations and code drilldown while it works.
The CLI stays available as a setup/doctor/resource fallback, not the main reasoning surface.
```

## What this example proves

- SourceBrief is a runtime context product, not just a search demo.
- The agent should not need a local checkout of every indexed source to answer with evidence.
- MCP is the default live evidence path.
- Generated skills teach the agent when to call MCP and how to preserve citation discipline.
- CLI is the setup/admin/fallback path and must be documented for the agent/operator.
- Project skill packs are local instruction/config artifacts; SourceBrief remains the remote source of truth.

## Strong runtime acceptance bar

This example is not complete if it only demonstrates CLI output. A local agent integration must prove:

1. the generated skill/agent pack is installed or loaded;
2. SourceBrief MCP `tools/list` and a smoke `tools/call` work;
3. CLI fallback works for `doctor`, `runtime validate`, and `skill install --dry-run`;
4. the agent answer cites SourceBrief evidence and does not pretend remote indexed code is a local checkout.

## Current runnable path

Run the local stack, create an indexed demo project, generate an approved skill package, and install it locally with a receipt.

### 1. Start SourceBrief

```bash
cp .env.example .env
# Edit SOURCEBRIEF_ADMIN_PASSWORD before startup.
make compose-up
make quickstart-ready
make venv
export PATH="$PWD/.venv/bin:$PATH"
export SOURCEBRIEF_API_URL="$(make -s print-api-url)"
sourcebrief login --password-env SOURCEBRIEF_ADMIN_PASSWORD
```

`sourcebrief login` reads the admin email/password from environment variables or the local `.env` file, so the demo does not require dev-header auth.

### 2. Create a small demo project and indexed source

```bash
sourcebrief quickstart-demo --validate-mcp
```

This creates an isolated workspace/project, adds a tiny runbook, indexes it, saves local CLI defaults, and calls the MCP-shaped path.

Expected shape:

```text
Quickstart demo: indexed and ready for retrieval
  workspace: SourceBrief CLI Demo
  project: First useful moment
  resource: Payment retry runbook
...
MCP validation: passed
```

### 3. Ask through SourceBrief before the agent answers

```bash
sourcebrief ask --resource "Payment retry runbook" \
  "What should an operator do when payment retries fail?"
```

A good answer must include citations back to the indexed source. If citations are missing, the agent should not treat the answer as grounded.

### 4. Generate and validate runtime MCP config

Use the UI Agent Profile page or CLI runtime setup after selecting the workspace/project by name:

```bash
sourcebrief use --workspace "SourceBrief CLI Demo" --project "First useful moment"
sourcebrief --json runtime setup hermes \
  --public-api-url "http://localhost:18000" \
  --resource-id "$RESOURCE_ID" \
  --plan-out plan.json

export SOURCEBRIEF_TOKEN="<scoped-runtime-token>"
sourcebrief --json runtime validate --plan plan.json --run
```

Then apply only when you intentionally want to edit the local Hermes config:

```bash
sourcebrief --json runtime apply --plan plan.json --target hermes --dry-run
sourcebrief --json runtime apply --plan plan.json --target hermes --apply
```

The runtime plan wires the local agent to the project-scoped SourceBrief MCP endpoint. The skill-pack flow below installs the project-specific local instructions.

## Project skill pack install

This is the implemented Hermes first slice from [`PROJECT_SKILL_PACK_LOCAL_INSTALL.md`](../../docs/followups/PROJECT_SKILL_PACK_LOCAL_INSTALL.md).

The desired flow is:

```bash
# 1. Export a project-specific skill pack from an approved/published context pack.
sourcebrief skill export \
  --workspace "SourceBrief CLI Demo" \
  --project "First useful moment" \
  --pack-key default \
  --pack-version 1 \
  --approve-comment "Approved for local install." \
  --out ./sourcebrief-skill-pack

# 2. Inspect, dry-run, and install locally.
sourcebrief skill install \
  --package ./sourcebrief-skill-pack \
  --target hermes \
  --profile default \
  --dry-run

sourcebrief skill install \
  --package ./sourcebrief-skill-pack \
  --target hermes \
  --profile default \
  --receipt ./sourcebrief-skill-receipt.json \
  --apply

# 3. Roll back if needed.
sourcebrief skill uninstall --receipt ./sourcebrief-skill-receipt.json
```

After install, the local runtime should have a small SourceBrief-generated skill such as:

```text
~/.hermes/skills/sourcebrief-default/
  SKILL.md
  manifest.json
  references/data-structure.md
  references/resource-map.md
  references/citation-policy.md
  examples/smoke-queries.md
```

The skill does **not** embed full project source. It teaches the agent when and how to call SourceBrief.

## Agent behavior contract

A local agent with the installed skill should follow this order:

1. Start with `sourcebrief.ask` or `sourcebrief.lookup` for the task.
2. Use citations and suggested next tool calls.
3. Drill down with `sourcebrief.read_section`, `sourcebrief.read_file`, `sourcebrief.grep_code`, or `sourcebrief.find_symbol` only when needed.
4. Use CLI fallback for setup/admin:
   - `sourcebrief doctor`
   - `sourcebrief runtime validate`
   - `sourcebrief skill install --dry-run`
   - `sourcebrief skill uninstall --receipt ...`
5. Say when context is partial, stale, unauthenticated, or not queryable.
6. Never treat SourceBrief citation paths as local filesystem paths unless the runtime also has that checkout.
7. Never mutate source control, production, or local runtime config without explicit apply/approval.

## Example skill excerpt

A generated Hermes `SKILL.md` should look like this in spirit:

```markdown
# SourceBrief: First useful moment

Use this skill when answering questions or planning changes for the SourceBrief demo project.

Before making claims, call SourceBrief MCP:
1. `sourcebrief.ask(query="...")`
2. If needed, `sourcebrief.lookup(search_in="all", query="...")`
3. Drill down with `sourcebrief.read_section` or `sourcebrief.read_file` using cited paths.

Context pack: `default@1`
Coverage: partial/full status is reported by SourceBrief.
Token: read from `SOURCEBRIEF_TOKEN`; never paste the token into messages or files.
Mutation policy: read-only unless the user separately approves a patch/PR flow.
```

## Expected final artifact

A finished version of this example should commit sanitized output showing:

- local stack health;
- source creation and indexing completion;
- MCP validation;
- generated skill pack file inventory;
- dry-run install diff;
- install receipt with no plaintext token;
- one agent answer with citations;
- rollback/uninstall command.

This example remains intentionally sanitized: no tokens, local source paths, raw private corpus dumps, or generated runtime receipts are committed.
