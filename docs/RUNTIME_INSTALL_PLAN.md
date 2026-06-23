# Runtime install plan

SourceBrief can generate a copyable install plan for connecting an agent runtime to one SourceBrief project. The plan is intentionally a dry run: it shows the MCP URL, target runtime config, required token scopes, validation command, and rollback steps without editing Hermes, Claude Code, Codex, Cursor, shell profiles, or local config files. The separate guarded Hermes apply command supports a no-write preview, requires an explicit mutation flag for writes, and writes a local receipt when applied.

Use this guide when you already have a running SourceBrief stack and want a coding agent to call SourceBrief for cited evidence while it works.

## What the plan does

A runtime install plan answers five questions:

1. Which SourceBrief project-scoped MCP endpoint should this runtime call?
2. Which read-oriented token scopes are required?
3. What config shape does this runtime expect?
4. How can I validate the connection with real MCP calls?
5. How do I roll back the local runtime wiring?

It does not create or store plaintext tokens, and it does not apply local config changes by itself.

## Supported targets

The current plan generator supports:

- `hermes`
- `claude`
- `codex`

Cursor and other MCP clients can usually use the same HTTP MCP endpoint if they support custom authorization headers, but they are not first-class runtime plan targets yet.

## Recommended token scopes

For a runtime that can answer questions and drill into indexed source code:

```text
project:read,project:query,resource:read,review:read,code:read
```

For context-only use without remote file, grep, symbol, or code-search tools:

```text
project:read,project:query,resource:read,review:read
```

Store the token in the runtime's secret manager or environment. Do not paste it into committed config files, generated agent packs, or docs.

## Generate a plan from the UI

1. Open SourceBrief.
2. Choose the workspace and project.
3. Open **Agent Profile**.
4. In **Runtime install plan**, choose `Hermes`, `Claude`, or `Codex`.
5. Optionally narrow the resource scope.
6. Generate the plan.
7. Review the config, scopes, warnings, validator command, capabilities, and rollback steps.

The UI plan is copyable, but generation is not validation. Run the validator command before relying on the SourceBrief endpoint/token, then separately confirm your runtime loaded the copied config.

## Get IDs and a token

For first-time setup, prefer the UI: it shows the workspace, project, and resource names before any internal IDs. If you are scripting, get IDs from creation responses, the current UI route, or an existing agent profile response:

```bash
sourcebrief --json agent profile \
  --workspace-id "$WORKSPACE_ID" \
  --project-id "$PROJECT_ID"
```

Create a runtime token from a user/session-authenticated flow. In local dev, the CLI can create one when `SOURCEBRIEF_DEV_AUTH` is set to `true`:

```bash
sourcebrief --json token create-runtime \
  --workspace-id "$WORKSPACE_ID" \
  --name "SourceBrief runtime token" \
  --read-code \
  --project-id "$PROJECT_ID" \
  --resource-id "$RESOURCE_ID"
```

Use `--context-only` if the runtime only needs cited context and not remote code drilldown tools.

The plaintext token is returned once. Store it in the runtime secret store or an environment variable such as `SOURCEBRIEF_TOKEN`; do not commit it. API tokens cannot mint child tokens in shared deployments. See [Agent runtime usage](AGENT_RUNTIME_USAGE.md#auth-for-agents) for the longer auth guidance.

## Generate a plan from the CLI

The UI is the primary human-facing path because it lets you choose the workspace, project, and resource scope by name. Use the CLI when you are scripting or when you already have the IDs from the UI route, creation responses, or `sourcebrief --json agent profile` output.

Guided dry-run setup:

```bash
sourcebrief use --workspace-id "$WORKSPACE_ID" --project-id "$PROJECT_ID"
sourcebrief --json runtime setup hermes \
  --public-api-url "http://localhost:18000" \
  --resource-id "$RESOURCE_ID" \
  --plan-out plan.json
```

`runtime setup` generates the same plan, writes it only when `--plan-out` is provided, previews the validator command, and prints next steps. It does not edit Hermes or any other runtime config.

Lower-level explicit plan generation:

```bash
sourcebrief --json runtime plan \
  --workspace-id "$WORKSPACE_ID" \
  --project-id "$PROJECT_ID" \
  --target hermes \
  --public-api-url "http://localhost:18000" \
  --resource-id "$RESOURCE_ID"
```

Use `--target claude` or `--target codex` for those runtime config shapes.

If you omit `--resource-id`, SourceBrief computes the plan from the caller's authorized project/resource scope. Empty explicit resource scopes remain empty; they are not widened to all resources.

## Validate before relying on it

The generated plan includes a validator command. It validates the SourceBrief API/MCP endpoint, confirms the provided token works for the context path, checks citations, and exercises read-only denial behavior. It does not launch Hermes, Claude Code, Codex, or Cursor, and it does not prove that a local runtime has loaded your copied config.

It checks REST `agent-context`, MCP `initialize`, MCP `tools/list`, MCP `tools/call` for `sourcebrief.get_agent_context`, read-only denial behavior, and citation consistency. The example command prints redacted output when `--redact-token` is used.

If you intend to use remote code drilldown tools such as `sourcebrief.search_code`, `sourcebrief.grep_code`, `sourcebrief.read_file`, or `sourcebrief.find_symbol`, make sure your token includes `code:read` and confirm those tools appear after runtime discovery. The current validator command does not exercise every optional code-read tool.

Example direct validator command:

```bash
export SOURCEBRIEF_TOKEN="<sourcebrief-api-token>"
python scripts/hermes_integration.py \
  --api-url "http://localhost:18000" \
  --workspace-id "$WORKSPACE_ID" \
  --project-id "$PROJECT_ID" \
  --resource-id "$RESOURCE_ID" \
  --query "How does this project expose context to agents?" \
  --token-env SOURCEBRIEF_TOKEN \
  --redact-token
```

Prefer `--token-env SOURCEBRIEF_TOKEN` over passing a token on the command line. Command-line arguments can be visible to local process listings on shared systems.

After copying the generated config into your runtime, reload or restart that runtime and confirm it lists SourceBrief tools such as `sourcebrief.get_agent_context` and `sourcebrief.search`. That runtime-specific check is separate from the SourceBrief API/MCP validator.

## Apply from the CLI

Hermes has a guarded local apply flow. Claude, Codex, Cursor, and other runtimes still use the manual copy path above.

```bash
sourcebrief --json runtime plan \
  --workspace-id "$WORKSPACE_ID" \
  --project-id "$PROJECT_ID" \
  --target hermes \
  --public-api-url "http://localhost:18000" \
  --resource-id "$RESOURCE_ID" > plan.json

sourcebrief --json runtime detect
sourcebrief --json runtime apply --plan plan.json --target hermes --dry-run
sourcebrief --json runtime apply --plan plan.json --target hermes --apply
```

`apply` validates the plan schema, target, digest, and age before writing. The digest is an accidental-edit guard for a generated local plan, not a signature or trust boundary. `--dry-run` prints the exact file operation and writes nothing. `--apply` is required for mutation, but the CLI does not persist or require proof of a prior dry run; legacy `--yes` remains only as a compatibility alias. SourceBrief does not run installer scripts from remote URLs, does not use mutable `latest` download commands, and does not verify release signatures because no signed release channel exists yet.

For Hermes, apply rewrites the YAML file through the YAML parser while preserving existing top-level settings and MCP server entries semantically. It only adds or replaces the planned SourceBrief MCP server entry, but comments, anchors, and formatting may be normalized. The receipt records file hashes, token env var names, and rollback command. The receipt never stores the token value.

Rollback restores the pre-change file or removes a created managed-only config file:

```bash
sourcebrief --json runtime rollback --receipt receipt.json
```

Rollback refuses to touch a file whose current hash differs from the receipt's expected post-change hash unless you pass `--force`.

## Apply boundary

Today, SourceBrief generates a plan and leaves non-Hermes local runtime changes to you. That is deliberate: local runtime config is outside SourceBrief's server-side authority.

Future CLI apply work may extend the same guarded flow to Claude/Codex and add uninstall helpers.

## Rollback

For a manual install, rollback means:

1. Remove the SourceBrief MCP server entry from the target runtime config.
2. Unset `SOURCEBRIEF_TOKEN` or remove the matching runtime secret.
3. Reload or restart the runtime.
4. Revoke the dedicated SourceBrief token if you created one only for this runtime.

Use these commands when token revocation is needed:

```bash
sourcebrief --json token list --workspace-id "$WORKSPACE_ID"
sourcebrief --json token revoke --workspace-id "$WORKSPACE_ID" --token-id "$TOKEN_ID"
```

## Trust boundaries

SourceBrief provides cited context. It is not the coding agent, editor, deployment tool, or production executor. Local runtime config files, receipts, cached context, downloaded/generated agent packs, and validator output can reveal project names, endpoint URLs, resource IDs, paths, snippets, and token environment variable names; treat them as sensitive workspace artifacts even though they should not contain plaintext bearer tokens.

Runtime install plans preserve these boundaries:

- read-oriented scopes by default;
- project-scoped MCP endpoint;
- no silent local profile mutation;
- no plaintext token in generated artifacts;
- optional patch/PR tools remain opt-in proposal flows;
- validation uses real SourceBrief API/MCP calls and reports real failures;
- runtime-specific config-load checks remain a manual runtime step until target-specific validators exist.

## Related docs

- [Agent runtime usage](AGENT_RUNTIME_USAGE.md)
- [Quick start](QUICKSTART.md)
- [Project status](STATUS.md)
