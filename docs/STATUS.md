# Project status

Updated: 2026-06-30

SourceBrief is an early alpha for local development and product exploration. The core context path works locally; public internet hardening and enterprise deployment are not ready yet.

## Shipped in the local alpha

### Core platform

- Workspace, project, user, membership, and scoped access model.
- Email/password login and web sessions.
- Workspace API tokens with scopes and project/resource allowlists.
- Audit events for sensitive operations.

### Source ingestion

- Markdown/runbook resources.
- Git repository resources with commit/snapshot citations and code symbol extraction.
- URL connector with host/scheme/size guardrails.
- Upload/text connector with secret redaction.
- Zip folder-bundle upload path for non-Git knowledge packages.

### Retrieval and context

- Lexical, vector, graph-aware, code-symbol, and rerank retrieval paths.
- Deterministic local embedding/rerank defaults.
- Providerized embedding/rerank adapters for common HTTP/open-source deployment shapes.
- Cited context packets.
- Runtime-specific `agent-context` responses for API, Hermes, Claude, Codex, and Cursor profiles.

### Runtime integration

- Central MCP endpoint with source-aware tools.
- CLI for workspace/project/resource/search/context/token operations.
- Hermes integration validator for scoped context access.
- Runtime install-plan, validation, guarded apply, rollback receipt, and doctor flows for Hermes and MCP-style agent setup.

### Review and operations

- Resource lifecycle: active, review, archive, restore, soft delete, purge.
- Freshness metadata and scheduled refresh support.
- Query/resource usage analytics.
- Evidence-backed self-improvement artifact loop: review bundles, local reviewer reports, regression proposals, validation gates, staged receipts, redacted history, and a web console surface with no-silent-mutation boundaries.
- Docker Compose local stack using Postgres/pgvector and Redis.
- Operations runbook for health, logs, queues, stuck index runs, migrations, rollback, and reset.

### Web console

- Login and admin/user management.
- Command Center and project readiness surfaces.
- Sources lifecycle UI.
- Workbench for scoped questions and cited context.
- Quality/review surfaces.
- Self-improvement page for artifact history, redacted artifact detail, MVP smoke, and sleep dry-run.
- Graph, graph merge, repo agent, agent profile, and Skill Export surfaces.
- Product walkthrough screenshots, GIF, and proof artifact manifest for local alpha demos.

### Quality/release gate

- Unit and integration tests.
- Real-service Docker QA smoke covering ingestion, indexing, retrieval, MCP, auth denial, provider diagnostics, web health, and lifecycle flows.
- QA smoke now also covers the self-improvement artifact loop: overview, MVP smoke, redacted artifact detail, and sleep dry-run.
- Alpha eval demo dataset with natural-language repo/runbook/cross-resource golden queries.

## Experimental or still being productized

- Private Git repository connection UX.
- Git Resource Map UI flow and review ergonomics.
- Folder-bundle partial update UX.
- Large-repo progress UI, skipped-file reports, cancel/retry controls, and indexing explainability.
- Graph merge hardening for enterprise cross-repo workflows.
- Skill Pack generation quality and real-world package evaluation.
- Self-improvement remains artifact-first and review-gated; recurring sleep/replay mining is dry-run only until explicit adoption workflows mature.

## Not alpha-ready / non-goals today

- Public internet hardening.
- Enterprise SSO/SCIM.
- Fine-grained ABAC beyond current workspace/project/resource token allowlists.
- Production mutation execution from SourceBrief.
- Per-repo MCP server generation as the primary model.
- Unbounded connector/plugin marketplace.
- Kubernetes/Helm production packaging.
- Hosted SaaS operational runbooks.
- Large-scale semantic quality benchmark corpus.

## Safe product wording

Safe:

> SourceBrief serves cited, permission-scoped context to agents through HTTP and MCP.

Safe:

> SourceBrief can import public/local Git repositories, docs, URLs, uploads, and zip folder bundles in the local alpha.

Avoid:

> SourceBrief automatically turns every repo into a fully autonomous agent.

Avoid:

> SourceBrief is enterprise-ready for public SaaS deployment.

Avoid:

> SourceBrief executes production actions or opens PRs on its own.
