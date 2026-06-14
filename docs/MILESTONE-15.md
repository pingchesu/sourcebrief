# M15 — SaaS Alpha Web Console

## Goal

Make the alpha usable without the CLI for the core SaaS flows: workspace/project setup, resource ingestion, refresh/status, review/cleanup, usage visibility, token management, and asking a project agent with cited context.

## Shipped UI

The Next.js web app at `apps/web/app/page.tsx` is now a single-page alpha console with these sections:

1. **Connection**
   - API base URL
   - dev-mode `X-User-Email`
   - optional bearer token field
   - dashboard reload action

2. **Workspace / Project bootstrap**
   - create a workspace with a unique slug
   - create a project under that workspace
   - display and allow manually pasting existing workspace/project IDs

3. **Resource ingestion**
   - markdown inline document
   - upload text resource
   - public URL resource
   - git repository resource with branch/ref
   - update frequency field
   - create resource and select it for follow-up operations

4. **Refresh and status**
   - list resources
   - selected-resource refresh button
   - poll latest index run
   - show status, current snapshot, retrieval flag, review status, and usage counts

5. **Review / cleanup**
   - save review status/note
   - show freshness status, usage count, last index status, and stale reasons

6. **Token management**
   - create API tokens with explicit scopes
   - project allowlist by default
   - optional resource allowlist
   - show plaintext token only immediately after creation
   - list token metadata without plaintext
   - revoke tokens

7. **Ask project agent**
   - submit an `agent-context` query with `runtime=hermes`
   - inspect context, citations, scores, version metadata, and token budget hints

8. **Provider health**
   - dashboard load calls `/provider-health`
   - displays active embedding provider/model/namespace and dev-quality flag

## UX choices

- Single-page console is intentional for alpha: it reduces routing/auth complexity while exercising the real backend flows.
- Empty states tell the operator what to do next instead of showing blank tables.
- Destructive token revocation is visually separated with a red button.
- Token plaintext is isolated in a yellow one-time copy box and not rendered in token lists.
- Existing IDs can be pasted so operators can attach the UI to an already-created project.

## Verification

- `npm --prefix apps/web run lint`
- `make lint`
- `.venv/bin/pytest tests/unit tests/integration -q`
- `make qa-smoke`

The real-service smoke now verifies:

- frontend homepage renders and contains console markers
- token create returns one-time plaintext
- token list does not leak plaintext
- existing resource/index/review/usage/agent-context flows continue to work

## Non-goals

- Full enterprise navigation/sidebar IA.
- Persistent browser auth sessions.
- Rich graph visualization.
- File picker uploads; alpha upload uses text content in the form.
