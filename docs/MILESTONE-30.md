# Milestone 30 — Runtime Install Plan

## Goal

Make SourceBrief onboarding feel like a runtime product, not a pile of docs. A project owner should be able to open a SourceBrief project, choose a target agent runtime, and get a safe, copyable, validated install plan for connecting that runtime to the project-scoped SourceBrief MCP endpoint.

User story:

> As a project owner, I want SourceBrief to tell me exactly how to connect Hermes, Claude Code, or Codex to this project, what token scopes are required, how to validate the connection, and how to roll it back — without SourceBrief silently editing my local agent profile or persisting secrets.

This slice implements the governed version of one-command onboarding inspired by local code-memory MCP tools: **plan first, validate with real runtime calls, apply only in a future explicit step**.

## Non-goals

- No silent mutation of Hermes, Claude, Codex, Cursor, shell profiles, or local config files.
- No plaintext bearer tokens in persisted artifacts, downloaded packages, audit metadata, or frontend local storage beyond the existing logged-in session token.
- No new production mutation capability. SourceBrief remains a read-only agent context provider by default.
- No local accelerator/cache daemon in this milestone.
- No benchmark or speed claims.
- No DB migration unless a later PR adds durable validation history; the plan itself is computed from current project/runtime state.

## Architecture decision

### Decision

Implement the install plan as a **computed project endpoint** plus CLI and UI surfaces:

```text
POST /workspaces/{workspace_id}/projects/{project_id}/runtime-install-plan
sourcebrief runtime plan --workspace-id <id> --project-id <id> --target hermes
Agent Profile → Runtime install plan
```

The response is generated from current project access, current MCP tool discovery, agent profile policy, and authorized resource scope. It is not stored as a durable artifact.

### Why computed instead of persisted

- The plan contains environment-specific endpoints, target runtime config shapes, and current MCP capabilities; storing it would create stale instructions.
- Runtime install state is not owned by SourceBrief yet. Persisting a plan would imply SourceBrief knows whether the user applied it, which is false in this milestone.
- The only durable security-critical object is the API token, which already has its own creation/revocation flow and audit trail.

A future `runtime validate` history can store append-only validation summaries, but not tokens or copied config files.

## API contract

Endpoint:

```http
POST /workspaces/{workspace_id}/projects/{project_id}/runtime-install-plan
Authorization: Bearer <session-or-api-token>
Content-Type: application/json
```

Request:

```json
{
  "target": "hermes",
  "public_api_url": "https://sourcebrief.example.com",
  "server_name": "sourcebrief-my-project",
  "resource_ids": ["optional-resource-uuid"],
  "include_optional_tools": true
}
```

Fields:

- `target`: initially `hermes`, `claude`, or `codex`.
- `public_api_url`: optional externally reachable API base used in snippets; defaults to the server's configured public/base URL when available, otherwise the existing API URL placeholder semantics.
- `server_name`: optional runtime MCP server key; sanitized by SourceBrief.
- `resource_ids`: optional authorization/resource scope for validation commands. If omitted, token-scoped callers default to their allowed resources; session callers default to all active project resources.
- `include_optional_tools`: include optional tool capabilities in the plan with explicit enabled/disabled policy labels.

Response includes:

```json
{
  "target": "hermes",
  "workspace_id": "...",
  "project_id": "...",
  "project_name": "SourceBrief",
  "generated_at": "2026-06-22T00:00:00Z",
  "mode": "dry_run_plan",
  "server_name": "sourcebrief-sourcebrief",
  "endpoints": {
    "api_base_url": "https://sourcebrief.example.com",
    "mcp_url": "https://sourcebrief.example.com/mcp/<workspace>/<project>",
    "agent_context_url": "https://sourcebrief.example.com/workspaces/<workspace>/projects/<project>/agent-context",
    "agent_pack_url": "https://sourcebrief.example.com/workspaces/<workspace>/projects/<project>/agent-pack.zip"
  },
  "required_scopes": ["project:read", "project:query", "resource:read", "review:read", "code:read"],
  "suggested_token_request": {
    "name": "SourceBrief Hermes read-only runtime",
    "scopes": ["project:read", "project:query", "resource:read", "review:read", "code:read"],
    "allowed_project_ids": ["..."],
    "allowed_resource_ids": ["..."]
  },
  "mcp_config": {
    "format": "yaml",
    "content": "mcp_servers:\n  sourcebrief-sourcebrief:\n    url: ...\n    headers:\n      Authorization: Bearer ${SOURCEBRIEF_TOKEN}\n"
  },
  "validator_commands": [
    "python scripts/hermes_integration.py --api-url ... --workspace-id ... --project-id ... --token $SOURCEBRIEF_TOKEN --redact-token"
  ],
  "capabilities": [
    {"name": "sourcebrief.get_agent_context", "required": true, "enabled": true, "policy": "read_only"},
    {"name": "sourcebrief.generate_patch", "required": false, "enabled": false, "policy": "opt_in_disabled_by_default"}
  ],
  "resource_scope": {
    "mode": "selected_resources",
    "resources": [{"resource_id": "...", "name": "API repo", "type": "git", "status": "ready"}]
  },
  "warnings": ["Dry-run only: SourceBrief did not edit any runtime config."],
  "rollback_steps": ["Remove the MCP server entry named sourcebrief-sourcebrief from the target runtime config."]
}
```

Security contract:

- `mcp_config.content` must use a token placeholder or runtime-native environment-variable reference only, never a plaintext token.
- Capability discovery must be derived from the live server tool registry used by `tools/list`, not a hard-coded marketing list.
- Generated commands may include UUIDs because commands need stable identifiers, but the UI must display project/resource names first and avoid UUID-first primary flows.
- The endpoint requires project read access and respects token project/resource allowlists.

## CLI contract

Add a runtime command group:

```bash
sourcebrief runtime plan \
  --workspace-id <workspace_uuid> \
  --project-id <project_uuid> \
  --target hermes \
  --public-api-url https://sourcebrief.example.com
```

Resource-scoped plan:

```bash
sourcebrief runtime plan \
  --workspace-id <workspace_uuid> \
  --project-id <project_uuid> \
  --target hermes \
  --resource-id <resource_uuid> \
  --json
```

The CLI prints the computed JSON by default for this milestone so operators can pipe it into review tools. A future `sourcebrief runtime validate` may wrap `scripts/hermes_integration.py`; a future `sourcebrief runtime install --apply` must remain explicit and preview the exact files it will edit.

## Web UI placement

Add the first UI slice to **Agent Profile** because that page already owns runtime identity, MCP endpoint, guardrails, and generated agent content.

Enterprise UX requirements:

- Show project and resource names before internal IDs.
- Provide a target selector with Hermes first, and Claude/Codex visible as supported config shapes.
- Show copyable config snippets using `${SOURCEBRIEF_TOKEN}` placeholders or runtime-native environment-variable references only.
- Show token scopes and token request body separately from config snippets.
- Show validator commands and rollback steps.
- Show loading, empty, and API error states.
- Do not show fake validation pass; if validation has not run, say "plan generated, validation not run".

## Security and tenant boundaries

- Project membership/visibility and API token project allowlists are enforced before returning a plan.
- Resource allowlists are honored. Token-scoped calls with no explicit `resource_ids` default to the token's allowed resource set.
- Token creation is suggested only as a request body/CLI command. SourceBrief does not create a runtime token as part of `runtime-install-plan`.
- All config snippets use environment placeholders and secret-manager-friendly text.
- Source names, repo names, branches, and descriptions are treated as untrusted metadata. They may appear as labels, but not as executable instructions.
- Backend/local filesystem paths are not included.
- Optional mutation-adjacent MCP tools (`generate_patch`, `open_pr`) are listed with disabled/opt-in policy unless explicitly enabled in the project agent profile.

## Migration path and reversibility

- No schema migration in this milestone.
- Removing the feature is a route/CLI/UI removal; it does not require data repair.
- Rollback for users is manual and explicit: delete the MCP server entry, unset the runtime token environment variable/secret, restart or reload the runtime, and revoke the SourceBrief API token if it was created.
- If future validation history is persisted, store only append-only summaries: target, status, tool names, latency/error code, actor, and timestamp. Never store tokens or full config files.

## Observability and operational ownership

Operational owner: SourceBrief Runtime Platform.

Minimum observability in this slice:

- API endpoint success/failure is visible through existing application logs.
- The plan response includes `generated_at`, target, target server key, resource count, warnings, and policy labels.
- Future audit event candidate: `runtime_install.plan_generated`, with target, resource_count, and server_name only; no tokens, no config payload.

## Failure modes and mitigations

| Failure mode | Mitigation |
|---|---|
| Plan claims unavailable MCP tools | Capabilities are derived from the same registry as `tools/list`; tests compare the two. |
| Runtime config leaks a token | Snippets always use `${SOURCEBRIEF_TOKEN}`; tests assert no token-like `cs_` pattern and no supplied token appears. |
| User thinks SourceBrief already edited config | Response mode is `dry_run_plan`; UI warns that no runtime file was changed. |
| Token-scoped caller sees resources outside allowlist | Use the same effective-resource logic as runtime query paths and test denial. |
| Generated instructions become prompt injection | Repo/resource metadata is labels only; no source text is copied into executable instructions. |
| Public URL is wrong or internal-only | Plan accepts `public_api_url`, shows warnings, and validation commands make failures visible. |
| Optional patch/PR tools are mistaken for write access | Capabilities carry required/optional and enabled/policy fields; UI labels read-only default and opt-in boundaries. |

## Implementation slices

1. **Backend computed plan**
   - Add request/response schemas.
   - Add `POST /runtime-install-plan` endpoint.
   - Derive tools from `_mcp_tools()`.
   - Build target-specific MCP snippets for Hermes, Claude, Codex.
   - Respect project/resource token scopes.

2. **CLI**
   - Add `sourcebrief runtime plan`.
   - Print JSON response.

3. **Agent Profile UI**
   - Add target selector and plan generation card.
   - Render config, scopes, capabilities, validation commands, warnings, rollback.

4. **Tests**
   - Integration test for redacted snippets, live capability parity with MCP `tools/list`, resource allowlist behavior, and optional tool policy labels.
   - CLI parser smoke for `runtime plan` can be covered by existing CLI invocation patterns.

## Acceptance criteria

- [x] `POST /runtime-install-plan` returns a dry-run plan for Hermes, Claude, and Codex.
- [x] Plan capabilities match live MCP `tools/list` names.
- [x] Plan snippets never contain a plaintext token and always use `${SOURCEBRIEF_TOKEN}` or runtime-native `SOURCEBRIEF_TOKEN` environment-variable references.
- [x] Token-scoped callers see only allowed resources and are denied explicit out-of-scope resources.
- [x] CLI `sourcebrief runtime plan --json` returns the same response shape.
- [x] Agent Profile UI exposes the plan without UUID-first primary UX.
- [x] Python lint/type checks, integration tests, and frontend typecheck pass.
- [x] Real stack smoke proves API and web load after the change.
