# SourceBrief docs

Use this page as a map. If you are new, follow the first section in order; the design specs and milestone archive are not required for normal use.

## Start here: understand the product

1. [Product walkthrough](WALKTHROUGH.md) - see real UI screenshots and a captured `agent-context` response before installing anything.
2. [5-minute demo](DEMO.md) - use a tiny deterministic source to prove the indexed-evidence and MCP-shaped path quickly.
3. [Concepts](CONCEPTS.md) - learn the minimum vocabulary: Source, Snapshot, Citation, Agent Context, Resource Map, Context Pack, Skill Pack, and MCP tools.
4. [Project status](STATUS.md) - understand what is shipped, experimental, and intentionally not production/SaaS-ready yet.

## Run SourceBrief locally

- [Quick start](QUICKSTART.md) - start the local stack, open the web console, connect a source, ask in Workbench, and reach the first useful SourceBrief product moment.
- [Guide](GUIDE.md) - hands-on API/CLI walkthrough for workspaces, projects, resources, search, context packets, MCP calls, review, and Git imports.

## Use SourceBrief with agents

- [Agent runtime usage](AGENT_RUNTIME_USAGE.md) - practical Hermes, Claude Code, Codex, Cursor, MCP, skill, and remote-code workflows.
- [Runtime install plan](RUNTIME_INSTALL_PLAN.md) - generate dry-run Hermes, Claude, or Codex connection plans, review scopes/config, validate MCP, and roll back without silent local profile mutation.
- [Captured agent-context output](examples/agent-context-output.md) - normalized example of a real runtime-shaped response.

## Understand the system

- [Architecture](ARCHITECTURE.md) - system design and runtime components: FastAPI, PostgreSQL/pgvector, Redis/RQ workers, Next.js, agent-context, MCP routes, graph/code-symbol retrieval, and tenant boundaries.
- [Operations](OPERATIONS.md) - health checks, logs, queues, migrations, stuck jobs, rollback, restore, purge lifecycle, and local reset.
- [Alpha release notes](ALPHA_RELEASE_NOTES.md) - shipped alpha capabilities and explicit non-goals.

## Trust, status, and product gaps

- [Project status](STATUS.md) - deployment readiness, alpha limits, experimental areas, and future work.
- [Git repo import product gaps](GIT_REPO_IMPORT_PRODUCT_GAPS.md) - enterprise product backlog for Git source onboarding.
- [Roadmap](ROADMAP.md) - finite alpha roadmap after the first milestone set.

## Deep reference and design specs

These documents are design/reference material. They are useful for contributors and reviewers, but they should not be the first read for new users.

- [Product spec](SPEC.md) - broad product and architecture specification.
- [Codebase Memory MCP reference spec](CODEBASE_MEMORY_MCP_REFERENCE_SPEC.md) - follow-up roadmap for runtime onboarding, cross-repo context, graph views, service-link candidates, and indexing/search POCs.
- [Remote repo agent skill pack spec](REMOTE_REPO_AGENT_SKILL_PACK_SPEC.md) - adapter and package design notes.
- [Context Artifact Compiler repo-agent spec](CONTEXT_ARTIFACT_COMPILER_REPO_AGENT_SPEC.md) - repo agent lifecycle and compiler direction.

Context Artifact Compiler specs live in [`context-artifact-compiler/`](context-artifact-compiler/):

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

## Implementation history

Milestone documents are retained as implementation history. They explain how the alpha was built, but they are archive material.

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
- [Later milestones](MILESTONE-23.md), [M27](MILESTONE-27.md), [M28](MILESTONE-28.md), [M29](MILESTONE-29.md), [M30 runtime install plan](MILESTONE-30.md)
