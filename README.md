# SourceBrief

> Forge trusted context for every agent.

SourceBrief is an open-source context platform for teams that want their agents to answer from the right repos, docs, runbooks, and project knowledge without copying everything into prompts by hand.

Create a project, attach resources, let SourceBrief index them, then call the project like an agent context provider through HTTP or MCP.

```text
repos + docs + runbooks
            ↓
versioned snapshots + chunks + embeddings + code symbols + graph index
            ↓
hybrid/graph-aware retrieval + citations + review + usage analytics
            ↓
agent-ready context for Hermes, Claude, Codex, Cursor, or your own app
```

## Why this exists

Most agent stacks fail in the same boring way: the model is fine, but the context is stale, incomplete, or impossible to audit.

SourceBrief focuses on the missing layer between "a pile of knowledge" and "an agent I can trust":

- Turn a repo or document set into a queryable project agent.
- Query across repos, docs, and runbooks in one place.
- Keep context versioned by commit SHA, content hash, and snapshot.
- Track which resources actually get used in answers.
- Review stale or low-value resources instead of letting drift pile up.
- Serve context through a normal API or one central MCP server.

## Current status

SourceBrief is an early MVP. The core path is working:

- multi-tenant workspaces and projects
- resource ingestion for markdown documents and git repositories
- Redis/RQ background indexing
- PostgreSQL + pgvector storage
- lexical + vector hybrid retrieval
- bounded graph retrieval signal from resource/file/symbol graph edges
- providerized embedding and rerank adapters for HTTP/HuggingFace/vLLM/SGLang-style services
- context packets with citations
- deterministic code symbol extraction
- central agent registry and per-project agent profiles
- resource review, archive, delete, freshness, and usage analytics
- agent-context API
- central MCP context tool
- SaaS alpha web console for workspace/project/resource/token/review/agent flows

It is ready for local development and product exploration. It is not hardened for public internet deployment yet.

## Features

- Project agents built from repos, docs, and runbooks.
- Versioned snapshots with commit/hash citations.
- Hybrid retrieval over lexical search, vectors, graph index, rerank, and code symbols.
- Agent profiles owned by the platform, not forced into source repos.
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
git clone https://github.com/pingchesu/sourcebrief.git
cd sourcebrief
```

## Quick start

Create local configuration and set the bootstrap administrator password:

```bash
cp .env.example .env
# edit SOURCEBRIEF_ADMIN_PASSWORD before first startup
```

Run the full stack and smoke test:

```bash
make verify
# or explicitly:
make release-gate
```

`make verify` is an alias for `make release-gate`: it installs local dependencies, builds the Docker services, runs migrations, runs tests, starts API/worker/frontend/Postgres/Redis, executes a real smoke flow, and runs alpha evaluation against the demo dataset.

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

SourceBrief ships a CLI after local install. `make verify` installs it into `.venv/bin/sourcebrief`.

```bash
export SOURCEBRIEF_API_URL=http://localhost:18000
export SOURCEBRIEF_EMAIL=demo@example.com

sourcebrief workspace create --name Demo --slug demo
sourcebrief project create \
  --workspace-id <workspace-id> \
  --name "Demo Project" \
  --description "Repo and runbook context"
```

Add a repository resource and wait for indexing:

```bash
sourcebrief resource add-repo \
  --workspace-id <workspace-id> \
  --project-id <project-id> \
  --name "SourceBrief repo" \
  --repo-url https://github.com/pingchesu/sourcebrief.git \
  --branch main \
  --refresh \
  --wait
```

Search it and request Hermes-shaped context:

```bash
sourcebrief search \
  --workspace-id <workspace-id> \
  --project-id <project-id> \
  --query "agent-context API"

sourcebrief agent-context \
  --workspace-id <workspace-id> \
  --project-id <project-id> \
  --runtime hermes \
  --query "how does SourceBrief expose agent context?"

sourcebrief agent list --workspace-id <workspace-id>
sourcebrief agent profile --workspace-id <workspace-id> --project-id <project-id>
sourcebrief --json resource graph --workspace-id <workspace-id> --project-id <project-id> --resource-id <resource-id>
```

To validate a Hermes MCP integration token for that project:

```bash
python scripts/hermes_integration.py \
  --api-url http://localhost:18000 \
  --workspace-id <workspace-id> \
  --project-id <project-id> \
  --resource-id <resource-id> \
  --query "agent-context API" \
  --expect-text "agent-context"
```

The API/curl walkthrough and a longer repo example live in [`docs/GUIDE.md`](docs/GUIDE.md). Operator commands live in [`docs/OPERATIONS.md`](docs/OPERATIONS.md).

## What you can build with it

### Repo-as-agent

Attach one or more repositories to a project. SourceBrief indexes source files, extracts code symbols, preserves commit citations, and returns scoped context for coding agents.

### Team knowledge base

Attach docs, runbooks, decision records, and operating notes. Users query one project instead of hunting across multiple systems.

### Cross-resource debugging

Ask a question that spans code, docs, and runbooks. SourceBrief returns cited chunks and code symbols so the caller can inspect where the answer came from.

### Agent runtime integration

Call SourceBrief from Hermes, Claude Code, Codex, Cursor, your own API service, or any MCP-compatible client. SourceBrief provides context; production actions stay behind separate typed tools and approval flows.

## How it works

The short version:

1. A user creates a workspace and project.
2. The project gets resources: git repos, markdown docs, and runbooks.
3. Workers create versioned snapshots, chunks, and resource/file/symbol graph indexes.
4. Chunks get lexical indexes, embeddings, and optional code symbols.
5. Context packet and agent-context queries run through hybrid lexical/vector/graph/rerank retrieval and return cited context packets.
6. Review and usage pages show what is stale, noisy, or actually useful.
7. Agent clients request runtime-shaped context through HTTP or MCP.

Architecture details live in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). The full product spec is in [`docs/SPEC.md`](docs/SPEC.md).

## Documentation

- [`docs/QUICKSTART.md`](docs/QUICKSTART.md) - install, run, verify, troubleshoot
- [`docs/GUIDE.md`](docs/GUIDE.md) - create a project, ingest resources, query, review, use agent context
- [`docs/OPERATIONS.md`](docs/OPERATIONS.md) - local alpha operations, logs, queues, stuck jobs, rollback
- [`docs/ALPHA_RELEASE_NOTES.md`](docs/ALPHA_RELEASE_NOTES.md) - shipped alpha capabilities and explicit non-goals
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - system design and runtime components
- [`docs/SPEC.md`](docs/SPEC.md) - full product and architecture specification
- [`docs/ROADMAP.md`](docs/ROADMAP.md) - finite alpha milestone roadmap after M1-M10
- [`docs/MILESTONE-1.md`](docs/MILESTONE-1.md) - foundation runtime
- [`docs/MILESTONE-2.md`](docs/MILESTONE-2.md) - resource ingestion and lexical search
- [`docs/MILESTONE-3.md`](docs/MILESTONE-3.md) - embeddings, hybrid retrieval, context packets
- [`docs/MILESTONE-4.md`](docs/MILESTONE-4.md) - code intelligence
- [`docs/MILESTONE-5.md`](docs/MILESTONE-5.md) - review, lifecycle, freshness, usage analytics
- [`docs/MILESTONE-6.md`](docs/MILESTONE-6.md) - agent-context API and MCP integration
- [`docs/MILESTONE-7-10.md`](docs/MILESTONE-7-10.md) - agent registry, providerized embedding/rerank, graph index, graph-aware retrieval
- [`docs/MILESTONE-11.md`](docs/MILESTONE-11.md) - alpha auth, service tokens, and scope enforcement
- [`docs/MILESTONE-12.md`](docs/MILESTONE-12.md) - scheduled refresh, restore, and purge lifecycle
- [`docs/MILESTONE-13.md`](docs/MILESTONE-13.md) - safe URL/upload connectors and secret redaction
- [`docs/MILESTONE-14.md`](docs/MILESTONE-14.md) - provider health, embedding namespace hardening, and query diagnostics
- [`docs/MILESTONE-15.md`](docs/MILESTONE-15.md) - SaaS alpha web console for project/resource/token/review/agent flows
- [`docs/MILESTONE-16.md`](docs/MILESTONE-16.md) - Hermes/MCP integration pack and scoped token validation
- [`docs/MILESTONE-17.md`](docs/MILESTONE-17.md) - open-source alpha packaging and deployment runbook
- [`docs/MILESTONE-18.md`](docs/MILESTONE-18.md) - alpha evaluation, demo dataset, and release gate

## Tech stack

SourceBrief intentionally stays on common infrastructure:

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

- production auth integration beyond alpha dev headers and service tokens
- scheduled refresh workers
- richer review UI
- production embedding and rerank adapters
- public deployment docs
- example clients for MCP and agent runtimes
- hosted SaaS packaging

## License

MIT
