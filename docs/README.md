# SourceBrief docs

Use this page as a map. New readers should stay in the **primary path** first; specs and milestones are archive/reference material, not onboarding.

## Primary path

| Step | Doc | Why read it |
| --- | --- | --- |
| 1 | [README](../README.md) | Product promise, diagrams, trust boundaries, and local start. |
| 2 | [Install and use](INSTALL_AND_USE.md) | Short product-led path: install, add/update resources, ask questions, connect a runtime, and understand embedding/rerank limits. |
| 3 | [Recipes](RECIPES.md) | Choose a user workflow such as repo onboarding, PR review, incident runbooks, API services, frontend product work, or multi-repo platforms. |
| 4 | [Product walkthrough](WALKTHROUGH.md) | Real UI screenshots and captured `agent-context` output before installing. |
| 5 | [Concepts](CONCEPTS.md) | Source -> Snapshot -> Evidence -> Review -> Runtime mental model. |
| 6 | [Quick start](QUICKSTART.md) | Run the local stack and reach the first cited answer. |
| 7 | [Agent runtime usage](AGENT_RUNTIME_USAGE.md) | Long-form operator guide for Hermes, Claude Code, Codex, Cursor, MCP clients, scopes, skills, and failure modes. |
| Reference | [Default credential policy](DEFAULT_CREDENTIAL_POLICY.md) | Why SourceBrief has no universal `changeme` login and how local demos authenticate. |

## Proof and demos

| Doc | Status | What it proves |
| --- | --- | --- |
| [Proof artifacts](PROOF_ARTIFACTS.md) | Proof manifest | Which screenshots, outputs, and tests are real; which proof gaps remain. |
| [E2E evidence bundles](E2E_EVIDENCE.md) | Release evidence convention | How to capture redacted launch evidence with commit, ports, Compose project, health, command outputs, and artifacts. |
| [5-minute demo](DEMO.md) | Deterministic local demo | Tiny source -> indexed snapshot -> cited agent context -> MCP-shaped response. |
| [Demo runtime output](examples/demo-runtime-output.md) | Captured output | Normalized output from a real local demo run. |
| [Captured agent-context output](examples/agent-context-output.md) | Captured output | Normalized response from the product walkthrough run. |
| [Awesome Agent Harness 50-question example](../examples/awesome-agent-harness-50q/README.md) | Real corpus eval example | Five public repos, 50 questions, bounded import notes, and final RISK verdict. |
| [Screenshot-backed 50Q launch walkthrough](evaluations/sourcebrief-launch-50q-20260627.md) | Launch proof | Local startup/import/50Q/scenario run with committed screenshots and answer-quality follow-up issues. |
| [Use SourceBrief with a local agent](../examples/use-sourcebrief-with-local-agent/README.md) | Product-led runtime example | Current MCP/runtime setup path plus target project skill-pack install flow. |

## Runtime and operations

| Doc | Status | Use it for |
| --- | --- | --- |
| [Agent runtime usage](AGENT_RUNTIME_USAGE.md) | Active runtime guide | MCP tools, runtime-specific setup, token scopes, skills, remote-code safety, failure modes. |
| [Runtime install plan](RUNTIME_INSTALL_PLAN.md) | Active runtime guide | Dry-run setup plans, validation, apply boundary, rollback receipts. |
| [Operations](OPERATIONS.md) | Active runbook | Health checks, logs, queues, migrations, stuck jobs, rollback, restore/purge, reset. |
| [Project status](STATUS.md) | Active status | Shipped alpha capabilities, experimental areas, non-goals, safe wording. |

## Product and architecture reference

| Doc | Status | Use it for |
| --- | --- | --- |
| [Architecture](ARCHITECTURE.md) | Active reference | FastAPI, Postgres/pgvector, Redis/RQ, Next.js, agent-context, MCP, graph/code-symbol retrieval, tenant boundaries. |
| [Install and use](INSTALL_AND_USE.md) | User guide | Short install/use path, resource CRUD commands, product advantages, and embedding/rerank test boundaries. |
| [Guide](GUIDE.md) | API/CLI reference | Hands-on API/CLI walkthroughs beyond the quick start. |
| [Eval manifests](EVAL_MANIFESTS.md) | Eval/release reference | Structured real-corpus eval manifests, hashable question artifacts, max-10 batching, and grading schema. |
| [Alpha release notes](ALPHA_RELEASE_NOTES.md) | Release reference | Alpha capability summary and explicit boundaries. |
| [Roadmap](ROADMAP.md) | Planning reference | Finite alpha roadmap and future work. |
| [Git repo import product gaps](GIT_REPO_IMPORT_PRODUCT_GAPS.md) | Product backlog | Enterprise Git onboarding gaps. |
| [Out-of-box product plan](OUT_OF_BOX_PRODUCT_PLAN.md) | Productization backlog | More attractive first-use experience and recipe/agent-pack roadmap. |
| [Self-improvement](SELF_IMPROVEMENT.md) | Product architecture | Review bundles, autonomous reviewer agents, regression proposals, validation gates, and staged adoption. |

## Deep specs

These documents are for contributors and reviewers. They are useful when changing the product, but they are not the first read for users.

| Doc | Status |
| --- | --- |
| [Product spec](SPEC.md) | Deep reference |
| [Codebase Memory MCP reference spec](CODEBASE_MEMORY_MCP_REFERENCE_SPEC.md) | Deep reference / follow-up roadmap |
| [Remote repo agent skill pack spec](REMOTE_REPO_AGENT_SKILL_PACK_SPEC.md) | Deep reference |
| [Context Artifact Compiler repo-agent spec](CONTEXT_ARTIFACT_COMPILER_REPO_AGENT_SPEC.md) | Deep reference |

Context Artifact Compiler specs:

- [A1 Manifest model](context-artifact-compiler/A1-manifest-model-spec.md)
- [A2 Folder upload](context-artifact-compiler/A2-folder-upload-spec.md)
- [A3 Manifest diff](context-artifact-compiler/A3-manifest-diff-spec.md)
- [A4 Sections reuse](context-artifact-compiler/A4-sections-reuse-spec.md)
- [B0 Resource Map](context-artifact-compiler/B0-resource-map-spec.md)
- [B1 Context Pack versions](context-artifact-compiler/B1-context-pack-versions-spec.md)
- [C Skill Export](context-artifact-compiler/C-skill-export-spec.md)
- [C2 Skill Pack Compiler](context-artifact-compiler/C2-skill-pack-compiler-spec.md)
- [D Repo Agent v0](context-artifact-compiler/D-repo-agent-v0-spec.md)
- [E0 Graph version storage](context-artifact-compiler/E0-graph-version-storage-spec.md)
- [E1 Graph merge v0](context-artifact-compiler/E1-graph-merge-v0-spec.md)
- [F Expanded MCP tools](context-artifact-compiler/F-expanded-mcp-tools-spec.md)

## Follow-up trackers

These are active planning docs for productization work that is not fully closed yet.

- [CLI ergonomics golden path](followups/CLI_ERGONOMICS_GOLDEN_PATH.md)
- [Runtime setup / doctor](followups/RUNTIME_SETUP_DOCTOR.md)
- [MCP tool UX simplification](followups/MCP_TOOL_UX_SIMPLIFICATION.md)
- [RPC code access layer beside MCP](followups/RPC_CODE_ACCESS_LAYER.md)
- [Project skill-pack local install flow](followups/PROJECT_SKILL_PACK_LOCAL_INSTALL.md)
- [Docs deep proof cleanup](followups/DOCS_DEEP_PROOF_CLEANUP.md)

## Archive: implementation history

Milestone documents explain how the alpha was built. Keep them for traceability, but do not use them as onboarding docs.

- [M1 Foundation runtime](MILESTONE-1.md)
- [M2 Resource ingestion and lexical search](MILESTONE-2.md)
- [M3 Embeddings, hybrid retrieval, context packets](MILESTONE-3.md)
- [M4 Code intelligence](MILESTONE-4.md)
- [M5 Review, lifecycle, freshness, usage analytics](MILESTONE-5.md)
- [M6 Agent-context API and MCP integration](MILESTONE-6.md)
- [M7-M10 Agent registry, provider adapters, graph index, graph-aware retrieval](MILESTONE-7-10.md)
- [M11 Alpha auth, service tokens, scope enforcement](MILESTONE-11.md)
- [M12 Scheduled refresh, restore, purge lifecycle](MILESTONE-12.md)
- [M13 URL/upload connectors and secret redaction](MILESTONE-13.md)
- [M14 Provider health and embedding namespace hardening](MILESTONE-14.md)
- [M15 SaaS alpha web console](MILESTONE-15.md)
- [M16 Hermes/MCP integration pack](MILESTONE-16.md)
- [M17 Open-source alpha packaging](MILESTONE-17.md)
- [M18 Alpha evaluation and release gate](MILESTONE-18.md)
- [M23](MILESTONE-23.md), [M27](MILESTONE-27.md), [M28](MILESTONE-28.md), [M29](MILESTONE-29.md), [M30 runtime install plan](MILESTONE-30.md)
