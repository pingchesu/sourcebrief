# M11 — Alpha Auth / Service Tokens / Scope Enforcement

## Goal

Enable Hermes and external agents to query ContextSmith with bearer API tokens instead of dev-only `X-User-Email`, while enforcing workspace, project, resource, and scope boundaries consistently.

## Delivered behavior

- `Authorization: Bearer <token>` resolves to a service-token principal.
- Plaintext token is generated once at creation; only SHA-256 hash is stored.
- Tokens are workspace-scoped and support:
  - `scopes`
  - `allowed_project_ids`
  - `allowed_resource_ids`
  - `expires_at`
  - `revoked_at`
  - `last_used_at`
- Dev/user auth through `X-User-Email` is available only when `CONTEXTSMITH_DEV_AUTH=true` is explicitly set for local alpha flows.
- Service tokens cannot create tenant-root workspaces or mint child tokens.
- Service tokens cannot create projects; project creation remains user/admin driven in M11.
- Resource-scoped write tokens cannot create new resources outside their declared resource allowlist.
- Resource-scoped tokens are narrowed even when a request omits `resource_ids`; they do not silently query the full project.
- Central MCP and `agent-context` use the same effective resource scope as REST search/context-packet flows.

## Scopes

Current alpha scopes:

- `project:read` — workspace/project/agent profile read paths.
- `project:query` — search, code-search, agent-context, context-packets, MCP context tool.
- `resource:read` — resource list/detail/snapshots/graph/index-run resource views.
- `resource:write` — create/update/archive/delete resources.
- `resource:refresh` — enqueue manual resource refresh jobs.
- `review:read` — resource review and usage surfaces.
- `review:write` — resource review mutations.
- `token:admin` — create/list/revoke tokens and admin-like project/profile/audit operations.

`X-User-Email` local users are treated as alpha dev users with all scopes only when `CONTEXTSMITH_DEV_AUTH=true`. The default runtime rejects missing bearer auth; production auth remains a future milestone/non-goal for M11. The point here is service-token boundaries for agents/Hermes.

## REST examples

Create a Hermes-scoped token:

```bash
contextsmith token create \
  --workspace-id "$WORKSPACE_ID" \
  --name "Hermes project query" \
  --scope project:query,resource:read \
  --project-id "$PROJECT_ID" \
  --resource-id "$RESOURCE_ID" \
  --json
```

Use it:

```bash
CONTEXTSMITH_TOKEN="cs_..." contextsmith agent-context \
  --workspace-id "$WORKSPACE_ID" \
  --project-id "$PROJECT_ID" \
  --runtime hermes \
  --query "How does refresh work?" \
  --json
```

Revoke it:

```bash
contextsmith token revoke --workspace-id "$WORKSPACE_ID" --token-id "$TOKEN_ID" --json
```

## Security and operational notes

- Do not log plaintext tokens after creation.
- Prefer narrowly scoped Hermes tokens: `project:query,resource:read` plus explicit project/resource allowlists.
- Mutation tokens should be separate from query tokens.
- Revocation is immediate because token lookup checks `revoked_at` on every request.
- Token allowlists are defense-in-depth; workspace membership/project visibility checks still run.

## Verification

M11 must pass:

```bash
make lint
.venv/bin/pytest tests/unit/test_cli.py tests/unit/test_models.py -q
.venv/bin/pytest tests/integration/test_api_flow.py -q -s
```

The integration test proves:

- token creation returns plaintext once;
- bearer token can list only allowed resources;
- missing write scope returns 403;
- Hermes-style `agent-context` only cites allowed resources;
- explicit request for a denied resource returns 404;
- revoked token returns 401.
