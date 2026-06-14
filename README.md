# ContextSmith

> Forge trusted context for every agent.

ContextSmith is an open-source context platform for teams that want their agents to answer from the right repos, docs, runbooks, and project knowledge without copying everything into prompts by hand.

Create a project, attach resources, let ContextSmith index them, then call the project like an agent context provider through HTTP or MCP.

```text
repos + docs + runbooks
            ↓
versioned snapshots + chunks + embeddings + code symbols
            ↓
hybrid retrieval + citations + review + usage analytics
            ↓
agent-ready context for Hermes, Claude, Codex, Cursor, or your own app
```

## Why this exists

Most agent stacks fail in the same boring way: the model is fine, but the context is stale, incomplete, or impossible to audit.

ContextSmith focuses on the missing layer between "a pile of knowledge" and "an agent I can trust":

- Turn a repo or document set into a queryable project agent.
- Query across repos, docs, and runbooks in one place.
- Keep context versioned by commit SHA, content hash, and snapshot.
- Track which resources actually get used in answers.
- Review stale or low-value resources instead of letting drift pile up.
- Serve context through a normal API or one central MCP server.

## Current status

ContextSmith is an early MVP. The core path is working:

- multi-tenant workspaces and projects
- resource ingestion for markdown documents and git repositories
- Redis/RQ background indexing
- PostgreSQL + pgvector storage
- lexical + vector hybrid retrieval
- context packets with citations
- deterministic code symbol extraction
- resource review, archive, delete, freshness, and usage analytics
- agent-context API
- central MCP context tool
- basic Next.js web shell

It is ready for local development and product exploration. It is not hardened for public internet deployment yet.

## Features

- Project agents built from repos, docs, and runbooks.
- Versioned snapshots with commit/hash citations.
- Hybrid retrieval over lexical search, vectors, and code symbols.
- Review and usage analytics for stale or low-value context.
- Runtime-shaped context packets for Hermes, Claude, Codex, Cursor, and API clients.
- One central MCP context tool instead of one MCP server per repo.

## Installation

Prerequisites:

- Docker with Compose
- Python 3.11
- [uv](https://docs.astral.sh/uv/)
- Node.js 20+
- npm
- git

Clone the repo:

```bash
git clone https://github.com/pingchesu/contextsmith.git
cd contextsmith
```

## Quick start

Run the full stack and smoke test:

```bash
make verify
```

`make verify` installs local dependencies, builds the Docker services, runs migrations, runs tests, starts API/worker/frontend/Postgres/Redis, and executes a real smoke flow.

When it passes, open:

- API health: <http://localhost:18000/healthz>
- API readiness: <http://localhost:18000/readyz>
- Web UI: <http://localhost:13000>

Need a shorter local loop after dependencies are installed?

```bash
make compose-up
make migrate
make qa-smoke
```

Stop services:

```bash
make compose-down
```

See the full setup guide: [`docs/QUICKSTART.md`](docs/QUICKSTART.md).

## Five-minute CLI demo

ContextSmith ships a CLI after local install. `make verify` installs it into `.venv/bin/contextsmith`.

```bash
export CONTEXTSMITH_API_URL=http://localhost:18000
export CONTEXTSMITH_EMAIL=demo@example.com

contextsmith workspace create --name Demo --slug demo
contextsmith project create \
  --workspace-id <workspace-id> \
  --name "Demo Project" \
  --description "Repo and runbook context"
```

Add a repository resource and wait for indexing:

```bash
contextsmith resource add-repo \
  --workspace-id <workspace-id> \
  --project-id <project-id> \
  --name "ContextSmith repo" \
  --repo-url https://github.com/pingchesu/contextsmith.git \
  --branch main \
  --refresh \
  --wait
```

Search it:

```bash
contextsmith search \
  --workspace-id <workspace-id> \
  --project-id <project-id> \
  --query "agent-context API"
```

The API/curl walkthrough and a longer repo example live in [`docs/GUIDE.md`](docs/GUIDE.md).

## What you can build with it

### Repo-as-agent

Attach one or more repositories to a project. ContextSmith indexes source files, extracts code symbols, preserves commit citations, and returns scoped context for coding agents.

### Team knowledge base

Attach docs, runbooks, decision records, and operating notes. Users query one project instead of hunting across multiple systems.

### Cross-resource debugging

Ask a question that spans code, docs, and runbooks. ContextSmith returns cited chunks and code symbols so the caller can inspect where the answer came from.

### Agent runtime integration

Call ContextSmith from Hermes, Claude Code, Codex, Cursor, your own API service, or any MCP-compatible client. ContextSmith provides context; production actions stay behind separate typed tools and approval flows.

## How it works

The short version:

1. A user creates a workspace and project.
2. The project gets resources: git repos, markdown docs, and runbooks.
3. Workers create versioned snapshots and chunks.
4. Chunks get lexical indexes, embeddings, and optional code symbols.
5. Queries run through hybrid retrieval and return cited context packets.
6. Review and usage pages show what is stale, noisy, or actually useful.
7. Agent clients request runtime-shaped context through HTTP or MCP.

Architecture details live in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The full product spec is in [`docs/SPEC.md`](docs/SPEC.md).

## Documentation

- [`docs/QUICKSTART.md`](docs/QUICKSTART.md) - install, run, verify, troubleshoot
- [`docs/GUIDE.md`](docs/GUIDE.md) - create a project, ingest resources, query, review, use agent context
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - system design and runtime components
- [`docs/SPEC.md`](docs/SPEC.md) - full product and architecture specification
- [`docs/MILESTONE-1.md`](docs/MILESTONE-1.md) - foundation runtime
- [`docs/MILESTONE-2.md`](docs/MILESTONE-2.md) - resource ingestion and lexical search
- [`docs/MILESTONE-3.md`](docs/MILESTONE-3.md) - embeddings, hybrid retrieval, context packets
- [`docs/MILESTONE-4.md`](docs/MILESTONE-4.md) - code intelligence
- [`docs/MILESTONE-5.md`](docs/MILESTONE-5.md) - review, lifecycle, freshness, usage analytics
- [`docs/MILESTONE-6.md`](docs/MILESTONE-6.md) - agent-context API and MCP integration

## Tech stack

ContextSmith intentionally stays on common infrastructure:

- FastAPI
- PostgreSQL + pgvector
- Redis + RQ
- SQLAlchemy + Alembic
- Next.js
- Docker Compose

Embedding and rerank backends are designed to be pluggable. The intended production adapters are common open-source paths such as Hugging Face, vLLM, and SGLang.

## Development

Useful commands:

```bash
make lint              # Python lint + frontend typecheck
make test              # unit tests
make test-integration  # integration tests against real services
make verify            # full local acceptance gate
make compose-down      # stop local services
```

The smoke test covers document and git ingestion, snapshots, chunks, embeddings, code symbols, hybrid retrieval, usage analytics, review lifecycle, agent-context API, central MCP tool, audit events, authorization denial, worker execution, and frontend health.

## Project direction

Near-term hardening areas:

- real auth and scoped API tokens
- scheduled refresh workers
- richer review UI
- production embedding and rerank adapters
- public deployment docs
- example clients for MCP and agent runtimes
- hosted SaaS packaging

## License

MIT
