# SourceBrief Alpha Roadmap

This roadmap scopes the remaining work after the M1-M10 MVP into a finite open-source SaaS alpha. Each milestone must ship through the established build cycle: feature branch, implementation, lint/typecheck/unit tests, real-service integration smoke, adversarial review, blocker fixes, PR, and merge.

## M11 — Alpha Auth / Service Tokens / Scope Enforcement

Goal: make SourceBrief usable by Hermes and external agents without dev-only `X-User-Email`, while preserving tenant/project/resource boundaries.

Acceptance criteria:

- Bearer API tokens are hash-only at rest and returned only once at creation.
- Tokens support scopes, expiry, revocation, last-used tracking, allowed project IDs, and allowed resource IDs.
- Project/resource read/query/mutation endpoints enforce scopes consistently.
- Resource-scoped tokens cannot list, search, retrieve context from, or explicitly request resources outside their allowlist.
- Central MCP and `agent-context` use the same token boundary as REST.
- CLI can create/list/revoke tokens and call APIs with `SOURCEBRIEF_TOKEN` / `--token`.
- Real-service integration proves scoped Hermes-style context retrieval and revocation.

## M12 — Scheduled Refresh / Reindex / Restore / Purge Lifecycle

Goal: operationalize freshness and drift control for repo/doc/url resources.

Acceptance criteria:

- Scheduler finds due resources from `update_frequency` and enqueues refresh jobs idempotently.
- Manual force reindex bypasses freshness checks but keeps versioned snapshots.
- Archived/deleted resources are excluded from retrieval by default.
- Soft delete supports restore; hard purge removes stale snapshots/chunks/embeddings after retention.
- Review page exposes due/stale/failed refresh state with actionable reasons.
- Real-service smoke proves scheduled refresh, restore, and purge on Postgres/Redis.

## M13 — Safe Resource Connectors

Goal: expand sources beyond inline docs/git while keeping connector failures observable and bounded.

Acceptance criteria:

- URL connector fetches public HTTP(S) content with size/time limits and stable metadata.
- File/upload connector ingests markdown/text/PDF-like text inputs through API/CLI.
- Connector errors are stored on index runs with actionable messages.
- Secret redaction pass runs before chunking/indexing for common token/key patterns.
- Source config validation rejects unsafe local paths/oversized fetches by default.

## M14 — Provider Verification / Embedding Namespace Hardening

Goal: make embedding/rerank provider changes safe and measurable.

Acceptance criteria:

- Provider health endpoint verifies embedding dimension/model/rerank availability before indexing.
- Embedding namespace includes provider, model, dimension, and normalization metadata.
- Retrieval refuses to mix incompatible embedding namespaces silently.
- Rerank score normalization/clamping is covered by tests and surfaced in query diagnostics.
- Fallback hashing provider is clearly marked as dev-quality, not production semantic retrieval.

## M15 — SaaS Alpha Web Console

Goal: make workspace/project/resource/review/token flows usable without CLI.

Acceptance criteria:

- Web UI supports workspace/project/resource creation, refresh, status, resource review, and usage views.
- Token management UI shows scopes/allowlists but never plaintext token after creation.
- Agent context page lets users ask questions and inspect citations/resource hits.
- Empty/error/loading states are clear and actionable.
- UI smoke test covers the happy path against real API.

## M16 — Hermes and MCP Integration Pack

Goal: make SourceBrief directly consumable by Hermes as a project knowledge backend.

Acceptance criteria:

- Documented Hermes configuration for SourceBrief MCP/REST usage.
- CLI script creates a Hermes-scoped token and validates `agent-context` with runtime=`hermes`.
- MCP endpoint supports initialization, tool listing, and context tool calls with bearer token auth.
- Integration smoke asks a real question through the SourceBrief service and verifies cited answer context.
- Production action boundaries remain out of SourceBrief and delegated to typed MCP tools.

## M17 — Open-source Alpha Packaging / Deployment

Goal: make a new contributor/operator able to run the platform reproducibly.

Acceptance criteria:

- Docker Compose alpha stack runs API, worker, web, Postgres/pgvector, and Redis.
- `.env.example` documents minimal and provider-backed embedding/rerank settings.
- Migrations run predictably in local and containerized flows.
- README quickstart reaches first indexed project and first Hermes-style query.
- Operational runbook covers logs, queues, stuck index runs, and rollback.

## M18 — Alpha Evaluation / Demo Dataset / Release Gate

Goal: prevent regressions in answer quality and platform reliability before alpha release.

Acceptance criteria:

- Demo dataset contains at least one repo, one runbook/doc, and one cross-resource query set.
- Golden questions assert citation presence, resource freshness, and no cross-tenant leakage.
- Evaluation report records retrieval hit quality, context length, latency, and failure reasons.
- Release gate runs lint, typecheck, unit, integration, real-service QA smoke, and eval.
- Alpha release notes clearly separate shipped capabilities from non-goals.

## Non-goals before alpha

- Full enterprise SSO/SCIM.
- Fine-grained per-field ABAC beyond workspace/project/resource token allowlists.
- Production mutation execution from repo agents.
- Per-repo MCP servers.
- Unbounded connector/plugin marketplace.
