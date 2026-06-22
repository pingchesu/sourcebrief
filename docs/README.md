# SourceBrief docs

This directory contains user docs, operator docs, architecture notes, and product/RFC material. Start with the path that matches what you are trying to do.

## New users

- [Quick start](QUICKSTART.md) - run the local stack and get to the first product moment.
- [Product walkthrough](WALKTHROUGH.md) - see real UI screenshots and a captured agent-context response.
- [Agent runtime usage](AGENT_RUNTIME_USAGE.md) - use SourceBrief from Hermes, Claude Code, Codex, Cursor, MCP, and generated skills.
- [Concepts](CONCEPTS.md) - learn the vocabulary: Source, Snapshot, Resource Map, Context Pack, Skill Pack, MCP tools.
- [Guide](GUIDE.md) - walk through API, CLI, Git resources, MCP, and review workflows.
- [Project status](STATUS.md) - what works today, what is experimental, and what is intentionally not ready.

## Agent/runtime integration

- [Agent runtime usage](AGENT_RUNTIME_USAGE.md) - practical Hermes, Claude Code, Codex, Cursor, MCP, skill, and remote-code workflows.
- [Guide](GUIDE.md) - `agent-context`, MCP calls, CLI workflow, and resource review.
- [Remote repo agent skill pack spec](REMOTE_REPO_AGENT_SKILL_PACK_SPEC.md) - adapter and package design notes.
- [Context Artifact Compiler repo-agent spec](CONTEXT_ARTIFACT_COMPILER_REPO_AGENT_SPEC.md) - repo agent lifecycle and compiler direction.
- [C2 Skill Pack Compiler spec](context-artifact-compiler/C2-skill-pack-compiler-spec.md) - citation-backed Skill Pack package model and real E2E value gate.

## Developers

- [Architecture](ARCHITECTURE.md) - system design and runtime components.
- [Product spec](SPEC.md) - full product and architecture specification.
- [Roadmap](ROADMAP.md) - finite alpha roadmap after the first milestone set.
- [Alpha release notes](ALPHA_RELEASE_NOTES.md) - shipped alpha capabilities and explicit non-goals.

## Operators

- [Operations](OPERATIONS.md) - health checks, logs, queues, migrations, stuck jobs, rollback, and local reset.
- [Git repo import product gaps](GIT_REPO_IMPORT_PRODUCT_GAPS.md) - enterprise product backlog for Git source onboarding.

## RFCs and implementation specs

- [Codebase Memory MCP reference spec](CODEBASE_MEMORY_MCP_REFERENCE_SPEC.md) - follow-up roadmap for easy runtime onboarding, cross-repo context, architecture graph views, service-link candidates, and indexing/search POCs inspired by `DeusData/codebase-memory-mcp`.

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

## Milestone archive

Milestone documents are retained as implementation history. They are useful when reviewing how the alpha was built, but they are not the best first read for new users.

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
- [Later milestones](MILESTONE-23.md), [M27](MILESTONE-27.md), [M28](MILESTONE-28.md), [M29](MILESTONE-29.md)
