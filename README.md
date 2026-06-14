# ContextSmith

**Forge trusted context for every agent.**

ContextSmith is an open-source, multi-tenant agent context platform that turns repositories, documents, runbooks, URLs, and arbitrary resources into versioned, reviewable, queryable knowledge agents.

## Why ContextSmith

Agents are only as useful as the context they can trust. ContextSmith is designed to manage the full lifecycle of that context:

- create projects from repositories and arbitrary resources
- index code, documents, runbooks, and operational knowledge
- support cross-repo and cross-resource retrieval
- track resource freshness, usage, citations, and drift
- review generated summaries, inferred relationships, and stale resources
- expose project agents through APIs, MCP, web UI, and agent runtimes such as Hermes, Claude Code, Codex, and Cursor

## Core principles

- **Project-first**: users create projects, then attach repos, docs, runbooks, URLs, and other resources.
- **Resource lifecycle**: resources can be added, updated, paused, archived, soft-deleted, hard-deleted, and reindexed.
- **Versioned context**: every indexed resource is tied to a commit SHA, content hash, snapshot, and freshness timestamp.
- **Reviewable knowledge**: generated summaries and inferred edges are not treated as truth until reviewed.
- **Usage-aware cleanup**: query hits, context inclusion, citations, feedback, and stale usage guide drift control.
- **Multi-tenant by design**: workspace, project, resource, API token, and role boundaries are part of the data model from day one.
- **Agent-ready**: project knowledge can be consumed by HTTP APIs, MCP tools, web chat, and external agent runtimes.
- **Minimal common infrastructure**: designed to run on PostgreSQL, pgvector, Redis, and common embedding/rerank services such as Hugging Face, vLLM, or SGLang.

## Specification

See [`docs/SPEC.md`](docs/SPEC.md) for the detailed product and architecture specification.

See [`docs/MILESTONE-1.md`](docs/MILESTONE-1.md) for the foundation implementation plan, Docker runtime skeleton, and real-service QA gate.

## Initial scope

ContextSmith is planned as an open-source SaaS-scale platform with the following first-class capabilities:

1. Multi-tenant workspaces, projects, users, roles, and scoped service tokens.
2. Git repository, document, URL, runbook, and arbitrary resource ingestion.
3. Configurable refresh schedules and on-demand reindexing.
4. Versioned snapshots for commit/hash-based freshness tracking.
5. Code/document/vector/graph/context artifacts.
6. Cross-repo and cross-resource query routing.
7. Review UI for stale resources, inferred knowledge, summaries, and failed indexing jobs.
8. Usage analytics for resources, chunks, context packets, citations, feedback, and query clusters.
9. Agent APIs and a central MCP server for external runtimes.

## Status

This repository is newly created. Architecture, product specification, and implementation plan are forthcoming.

## License

MIT
