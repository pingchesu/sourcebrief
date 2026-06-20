# SourceBrief

> The evidence layer for coding agents.

SourceBrief turns repos, docs, runbooks, and uploaded knowledge into cited context that agents can actually trust.

It is not a chatbot, a vector database wrapper, or an autonomous production agent. It is the context control plane between your source material and Claude Code, Codex, Cursor, Hermes, or any MCP-compatible runtime.

Agents should not guess from whatever files happened to fit in the prompt. They should ask for evidence: commit SHAs, file paths, line ranges, document hashes, freshness, and citations.

<img src="docs/assets/sourcebrief-context-flow.svg" alt="SourceBrief turns sources into reviewed context packs and serves them to agents through API and MCP" width="100%" />

## See it running

<img src="docs/assets/sourcebrief-product-walkthrough.gif" alt="Animated SourceBrief walkthrough showing Command Center, Sources, and Workbench citations" width="100%" />

This walkthrough was captured from a real local SourceBrief stack with live API, workers, Postgres, Redis, two indexed resources, and a real `agent-context` response. See the full [product walkthrough](docs/WALKTHROUGH.md) and the captured [agent-context output](docs/examples/agent-context-output.md).

## Why SourceBrief exists

AI coding agents are becoming daily engineering tools, but the context layer is still handled like a hack:

- developers paste random files into prompts
- repo-local instruction files drift from reality
- runbooks, architecture notes, and source code live in different places
- generated answers often cannot prove which commit, file, line, or document version they came from
- every repo wants its own MCP server, prompt bundle, or ad hoc retrieval script
- teams have no review loop for stale, noisy, or low-value context

SourceBrief gives teams a governed context supply chain:

```text
connect sources
    -> index versioned snapshots
    -> review maps, freshness, and coverage
    -> publish pinned context packs
    -> serve cited evidence through API or MCP
```

Use it when you need agents to answer with evidence, not vibes.

## What SourceBrief does

| Capability | What it means for an agent |
| --- | --- |
| Resource ingestion | Add Git repos, Markdown/runbooks, URLs, uploads, and zip folder bundles. |
| Versioned snapshots | Keep context tied to commit SHA, content hash, path, and indexed version. |
| Resource Maps | Generate reviewable maps of what SourceBrief found in a repo or folder. |
| Context Packs | Publish pinned, permission-scoped evidence bundles for agent tasks. |
| Graph and symbols | Follow relationships across resources, directories, files, and code symbols. |
| MCP and HTTP runtime | Let agents retrieve context on demand through one central API/MCP surface. |
| Skill Packs | Export citation-backed runtime packages from published Context Packs. |
| Review and quality | Track freshness, failed imports, usage, and low-value context before drift piles up. |

SourceBrief provides context. Production mutations should stay behind separate typed tools, explicit approvals, and rollback workflows.

## A good SourceBrief answer

Ask:

```text
How does this project expose context to agents?
```

SourceBrief should return the files, docs, and symbols that matter, with citations the caller can inspect:

```text
SourceBrief exposes agent context through the project-scoped agent-context API
and the central MCP endpoint.

Evidence:
- apps/api/sourcebrief_api/main.py:6906-6949
  agent-context response shape and route
- apps/api/sourcebrief_api/main.py:8007-8196
  MCP tools/list and tools/call dispatch
- docs/ARCHITECTURE.md:124-166
  agent context and MCP runtime paths

The response includes runtime instructions, cited snippets, structured citations,
optional code symbols, and a token budget hint.
```

That is the product bar: source-backed answers a coding agent can use without pretending it read the whole repo.

## Use it with agents

The UI is where humans connect and review context. The runtime value shows up when Hermes, Claude Code, Codex, Cursor, or another agent can ask SourceBrief for cited project evidence while working on an issue.

Start with [Agent runtime usage](docs/AGENT_RUNTIME_USAGE.md) for the practical flows:

- using SourceBrief while developing a project
- using MCP from Hermes, Claude, Codex, or Cursor
- handling remote indexed code safely
- installing generated skills and agent packs
- knowing where SourceBrief stops and the coding agent begins

## Quick start

This is the shortest honest local path. It starts the real stack and opens the web console.

### Prerequisites

- Docker with Compose
- Python 3.11
- [uv](https://docs.astral.sh/uv/)
- Node.js 20+
- npm
- git

### Run SourceBrief locally

```bash
git clone https://github.com/pingchesu/sourcebrief.git
cd sourcebrief

cp .env.example .env
# Edit SOURCEBRIEF_ADMIN_PASSWORD before the first startup.
# Keep SOURCEBRIEF_DEV_AUTH=false unless you explicitly want local header auth for CLI experiments.

make compose-up
until curl -fsS http://localhost:18000/readyz; do sleep 2; done
until curl -fsS http://localhost:13000/api/health; do sleep 2; done
```

Open the web console:

```text
http://localhost:13000/login
```

Sign in with the admin email and password from `.env`:

```text
SOURCEBRIEF_ADMIN_EMAIL
SOURCEBRIEF_ADMIN_PASSWORD
```

From the UI, connect a source, inspect its indexing lifecycle, ask in Workbench, and review citations before using the context from an agent runtime.

### CLI experiments

The CLI supports either a bearer token or local development header auth.

For local-only CLI demos, set `SOURCEBRIEF_DEV_AUTH=true` in `.env` before startup, then use `SOURCEBRIEF_EMAIL`:

```bash
make venv
export PATH="$PWD/.venv/bin:$PATH"
export SOURCEBRIEF_API_URL=http://localhost:18000
export SOURCEBRIEF_EMAIL=demo@example.com

sourcebrief health
sourcebrief --help
```

For automation, pass a bearer API token as `SOURCEBRIEF_TOKEN` or `--token`. Do not use dev auth for shared or production-like deployments.

### Full verification gate

Use this when contributing or cutting a local release gate:

```bash
make verify
```

`make verify` runs lint, typecheck, unit tests, real-service integration tests, Docker Compose startup, migrations, QA smoke, and alpha eval. It is intentionally heavier than the quick start.

## Core workflow

```text
1. Connect sources
   Git repos, docs, runbooks, URLs, uploads, or zip folder bundles.

2. Index snapshots
   Workers create chunks, embeddings, code symbols, graph edges, and citations.

3. Inspect and review
   See freshness, indexing status, skipped files, usage, and low-value resources.

4. Ask with evidence
   Workbench and API requests return cited context packets and runtime instructions.

5. Serve agents
   Claude, Codex, Cursor, Hermes, and custom runtimes call HTTP or MCP tools.

6. Package reusable context
   Published Context Packs can export citation-backed Skill Packs.
```

## What SourceBrief is not

SourceBrief is deliberately not:

- a general chat UI
- a replacement for code search
- a plain vector database wrapper
- a tool that executes production mutations
- one MCP server per repository
- a public-internet-hardened SaaS distribution yet

It is an early alpha for local development and product exploration. See [project status](docs/STATUS.md) for what is shipped, experimental, or future work.

## Architecture

SourceBrief uses boring infrastructure on purpose:

- FastAPI
- PostgreSQL + pgvector
- Redis + RQ
- SQLAlchemy + Alembic
- Next.js
- Docker Compose

Runtime shape:

```text
Web UI / CLI / Agent client
        -> FastAPI API + MCP routes
        -> PostgreSQL + pgvector
        -> Redis/RQ workers
        -> source snapshots, chunks, symbols, graphs, context packs, skill exports
```

Read the full design in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Documentation

Start here:

- [Quick start](docs/QUICKSTART.md) - run the local stack and get to the first useful product moment
- [Agent runtime usage](docs/AGENT_RUNTIME_USAGE.md) - use SourceBrief from Hermes, Claude Code, Codex, Cursor, MCP, and generated skills
- [Concepts](docs/CONCEPTS.md) - Resource, Snapshot, Resource Map, Context Pack, Skill Pack, MCP, and related terms
- [Guide](docs/GUIDE.md) - end-to-end API, CLI, Git resource, MCP, and review workflows
- [Architecture](docs/ARCHITECTURE.md) - system design and runtime components
- [Operations](docs/OPERATIONS.md) - logs, queues, migrations, stuck jobs, rollback, and local reset
- [Project status](docs/STATUS.md) - shipped alpha capabilities, experimental areas, and non-goals
- [Docs home](docs/README.md) - full documentation map, including RFCs, compiler specs, milestones, and backlog

## Development

Useful commands:

```bash
make help              # list common commands
make compose-up        # start local services
make compose-down      # stop local services
make lint              # Python lint + frontend typecheck
make typecheck         # backend mypy + frontend typecheck
make test              # unit tests
make test-integration  # integration tests against real services
make qa-smoke          # real API/worker/frontend smoke flow
make verify            # full local acceptance gate
```

The smoke test covers document and Git ingestion, snapshots, chunks, embeddings, code symbols, hybrid retrieval, usage analytics, review lifecycle, agent-context API, MCP tools, audit events, authorization denial, worker execution, and frontend health.

## Security and privacy

SourceBrief analyzes only the sources you connect or upload. Use ignore rules and bounded import settings to exclude secrets, vendored code, generated files, or private material you do not want indexed.

Generated Skill Packs and runtime adapters should point agents back to SourceBrief citations. They should not embed an entire private source corpus.

## License

MIT
