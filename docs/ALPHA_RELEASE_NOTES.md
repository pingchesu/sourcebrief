# ContextSmith Alpha Release Notes

## Shipped capabilities

ContextSmith alpha is an open-source, multi-tenant, project-based context platform for agent runtimes.

### Core platform

- Workspace/project/resource data model with day-one tenant boundaries.
- Resource lifecycle: active, review, archive, restore, soft delete, purge.
- Freshness metadata and scheduled refresh support.
- Usage analytics for query/resource hits.

### Resource ingestion

- Markdown/runbook resources.
- Git repository resources with commit/snapshot citations and code symbol extraction.
- URL connector with host/scheme/size guardrails.
- Upload/text connector with secret redaction.

### Retrieval and context

- Lexical, vector, graph-aware, and rerank retrieval paths.
- Providerized embeddings/rerank with deterministic local defaults.
- Provider health endpoint and embedding namespace drift diagnostics.
- Context packets and runtime-specific `agent-context` API with usage accounting.
- Central MCP endpoint exposing context retrieval only.

### SaaS/ops surface

- Next.js alpha web console for workspace/project/resource/token/review/agent flows.
- Scoped API tokens with allowlists for workspace/project/resource boundaries.
- Docker Compose local alpha stack using Postgres/pgvector and Redis.
- Operator runbook for health, logs, queues, stuck index runs, migrations, rollback, and reset.
- Hermes integration validator that creates or validates read-only project context tokens.

### Quality/release gate

- Unit and integration tests.
- Real-service Docker QA smoke covering ingestion, indexing, retrieval, MCP, auth denial, provider diagnostics, web health, and lifecycle flows.
- Alpha eval demo dataset with natural-language repo/runbook/cross-resource golden queries, relevance-budgeted citation checks, retrieval hit quality records, usage/freshness assertions, and cross-tenant leak checks.
- Release gate records `artifacts/alpha-eval-report.json`.

## Non-goals / not alpha-ready

- Public internet hardening.
- Enterprise SSO/SCIM.
- Fine-grained ABAC beyond current workspace/project/resource token allowlists.
- Production mutation execution from ContextSmith.
- Per-repo MCP servers.
- Unbounded connector/plugin marketplace.
- Large-scale semantic quality benchmark corpus.
- Kubernetes/Helm packaging.

## Recommended alpha command

```bash
cp .env.example .env
make release-gate
```

Then open:

```text
http://localhost:13000
```
