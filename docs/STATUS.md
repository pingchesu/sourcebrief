# Project status

Updated: 2026-07-17

SourceBrief is an early local alpha undergoing a [core product reset](CORE_PRODUCT_RESET.md). The repository has a working deterministic evidence, governance, API/MCP, and runtime-adapter substrate. The intended intelligence layer is not shipped: current defaults and package generation must not be described as an AI knowledge compiler, reviewed semantic graph, production-quality GraphRAG, claim-verified answer engine, AI-generated Skill Pack, or autonomous self-improvement system.

## Product-reset status

- Umbrella: [#337](https://github.com/pingchesu/sourcebrief/issues/337)
- Product contract: [#338](https://github.com/pingchesu/sourcebrief/issues/338)
- Decision: [ADR-0002](decisions/ADR-0002-ai-intelligence-plane.md)
- Current safe operating mode: deterministic evidence service and runtime adapters
- AI intelligence mode: not shipped

The reset preserves verified snapshot, provenance, ACL, audit, review, API/MCP, package-integrity, and rollback work. It rebuilds semantic compilation, semantic graph, retrieval planning, grounded answers, and AI-compiled Agent/Skill Packs behind explicit typed provider and evaluation gates.

## Shipped and honestly supportable in the local alpha

### Core platform

- Workspace, project, user, membership, and scoped access model.
- Email/password login and web sessions.
- Workspace API tokens with scopes and project/resource allowlists.
- Audit events for sensitive operations.
- Versioned artifacts, review states, receipts, and guarded rollback paths where documented.

### Deterministic Evidence Foundation

- Markdown/runbook resources.
- Git repository resources with commit/snapshot citations and deterministic code symbol extraction.
- URL connector with host/scheme/size guardrails.
- Upload/text connector with secret redaction.
- Zip folder-bundle upload path for non-Git knowledge packages.
- Versioned snapshots, chunks, retained sections, paths, line ranges, hashes, and citation locators.
- Deterministic resource/file/symbol structural graph.
- Resource Maps as deterministic file/section navigation and coverage artifacts.

### Retrieval and context mechanics

- Lexical, vector-capable, structural-graph-aware, code-symbol, and rerank retrieval paths.
- Development-quality deterministic defaults: hashing embeddings and term-overlap reranking.
- Provider adapters for external embedding/rerank services; provider availability is not semantic-quality proof.
- Cited context/evidence packets.
- Deterministic extractive answer preview; this is not claim-verified generated synthesis.
- Runtime-specific `agent-context` responses for API, Hermes, Claude, Codex, and Cursor profiles.

### Runtime integration

- Central MCP endpoint with source-aware tools.
- CLI for workspace/project/resource/search/context/token operations.
- Hermes integration validator for scoped context access.
- Runtime install-plan, validation, guarded apply, rollback receipt, and doctor flows for Hermes and MCP-style agent setup.
- Repo/Project Agent runtime views.
- Deterministic Agent Pack / Skill Export adapters that route agents back to SourceBrief.
- Package manifest, integrity, leak-scan, approval, download, doctor, install, and rollback mechanics where documented.
- `remote-live` default mode plus explicit bounded policy declarations for non-default modes.

### Review and operations

- Resource lifecycle: active, review, archive, restore, soft delete, purge.
- Freshness metadata and scheduled refresh support.
- Query/resource usage analytics.
- Review and Proposal Loop: review bundles, local reviewer reports, regression proposals, validation gates, staged receipts, redacted history, and no-silent-mutation boundaries.
- Docker Compose local stack using Postgres/pgvector and Redis.
- Operations runbook for health, logs, queues, stuck index runs, migrations, rollback, and reset.

### Web console

- Login and admin/user management.
- Command Center and project readiness surfaces.
- Sources lifecycle UI.
- Workbench for scoped questions and cited context.
- Quality/review surfaces.
- Current **Self-improvement** page for review/proposal artifacts and dry-run recurrence mining; the label is slated for migration because autonomous optimization is not shipped.
- Structural Graph, graph merge, repo agent, agent profile, deterministic Skill Export, and Agent Pack publish/install/validate surfaces.
- Product walkthrough assets for local-alpha mechanics.

### Quality and mechanical gates

- Unit and integration tests.
- Real-service Docker QA smoke covering ingestion, indexing, retrieval mechanics, MCP, auth denial, provider diagnostics, web health, and lifecycle flows.
- Real-corpus and 50Q evidence with explicit RISK/PARTIAL accounting.
- Provider-quality downgrade gates that prevent development-quality providers from silently producing launch PASS.

Mechanical QA proves wiring and failure handling. It does not prove semantic relation quality, grounded answer quality, or source-specific AI Skill quality.

## Not shipped

The following claims are unsupported until the linked reset children pass current-candidate outcome gates:

- AI knowledge compiler or section-aware LLM map-reduce.
- Reviewed cross-resource semantic knowledge graph.
- Production-quality GraphRAG or WEAVE retrieval.
- Claim-level generated answers with evidence verification.
- AI-compiled source-specific Agent/Skill Packs.
- Autonomous self-improvement, prompt optimization, or silent learning.
- Large-scale semantic quality benchmark PASS.

A disabled, missing, failed, or unhealthy AI provider must never silently return deterministic output under an AI label.

## Experimental or being rebuilt

- Private Git repository connection UX.
- Git Resource Map UI flow and review ergonomics.
- Folder-bundle partial update UX.
- Large-repo progress UI, skipped-file reports, cancel/retry controls, and indexing explainability.
- Graph merge hardening for enterprise cross-repo workflows.
- Typed AI provider/execution plane.
- Citation-bound AI knowledge compiler.
- Provenance-gated semantic graph.
- WEAVE query planning and evidence closure.
- Grounded answer composer and verifier.
- AI-compiled Agent/Skill Pack quality and runtime task evaluation.
- Product capability truth labels, observability, migration, and rollback.

## Not alpha-ready / non-goals today

- Public internet hardening.
- Enterprise SSO/SCIM.
- Fine-grained ABAC beyond current workspace/project/resource token allowlists.
- Production mutation execution from SourceBrief.
- Per-repo MCP server generation as the primary model.
- Unbounded connector/plugin marketplace.
- Kubernetes/Helm production packaging.
- Hosted SaaS operational runbooks.

## Safe product wording

Safe:

> SourceBrief serves cited, permission-scoped evidence and deterministic context packets to agents through HTTP and MCP.

Safe:

> SourceBrief can import public/local Git repositories, docs, URLs, uploads, and zip folder bundles in the local alpha.

Safe:

> SourceBrief can generate reviewed deterministic runtime adapters that point agents back to current cited evidence.

Avoid:

> SourceBrief understands every connected project or builds a semantic knowledge graph automatically.

Avoid:

> SourceBrief generates AI-derived skills from books, documents, or repositories.

Avoid:

> SourceBrief's current GraphRAG and answers are production-quality.

Avoid:

> SourceBrief autonomously improves itself, executes production actions, or opens PRs on its own.

Avoid:

> SourceBrief is enterprise-ready for public SaaS deployment.
