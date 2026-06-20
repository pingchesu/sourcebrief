# Quick start

This guide gets SourceBrief running locally with the real services used by the test suite.

## Prerequisites

Install these first:

- Docker with Compose
- Python 3.11
- [uv](https://docs.astral.sh/uv/)
- Node.js 20+
- npm
- git

Check the basics:

```bash
docker compose version
python3 --version
uv --version
node --version
npm --version
git --version
```

## Clone

```bash
git clone https://github.com/pingchesu/sourcebrief.git
cd sourcebrief
```

## Configure environment

Create a local `.env` before starting Docker Compose. The API bootstraps the first administrator from `SOURCEBRIEF_ADMIN_EMAIL` and `SOURCEBRIEF_ADMIN_PASSWORD`, so clean installs need those values present:

```bash
cp .env.example .env
# edit SOURCEBRIEF_ADMIN_PASSWORD before first startup
```

The template keeps the local deterministic hashing/term-overlap providers enabled. It also documents the admin bootstrap account, local ports, browser-visible API URL, and optional HuggingFace/vLLM/SGLang/OpenAI-compatible embedding and rerank endpoints.

`make` and Docker Compose both read `.env`. If you change frontend/API ports, also update `NEXT_PUBLIC_API_BASE_URL` and `SOURCEBRIEF_CORS_ORIGINS`, then rebuild with `docker compose up -d --build` because the browser API URL is compiled into the Next.js client.

## Run the full acceptance gate

```bash
make verify
```

This command does the full local path:

1. creates `.venv` with Python 3.11
2. installs Python dev dependencies
3. installs frontend dependencies
4. runs Python lint
5. runs backend mypy typecheck
6. runs frontend typecheck
7. runs unit tests
8. builds and starts Docker services
9. runs host and container Alembic migrations
10. runs integration tests against real Postgres/Redis/API behavior
11. runs the QA smoke flow
12. runs alpha evaluation and writes `artifacts/alpha-eval-report.json`

`make verify` is an alias for the full release gate:

```bash
make release-gate
```

It runs lint/typecheck, unit tests, integration tests, host/container migrations, real-service QA smoke, and alpha eval. Expected final smoke/eval output includes:

```text
QA smoke passed: document+git ingestion → snapshots → chunks → embeddings → code symbols → graph index → lexical/hybrid/GraphRAG context retrieval with citations, CLI search, agent profile, web console homepage/token flow, provider health/namespace diagnostics, query/resource usage analytics, review lifecycle, scheduled refresh dry-run, restore/purge lifecycle, upload connector redaction, agent-context API, central MCP context tool, Hermes integration script, index-run logs, audit events, RQ worker, auth denial (read+search), frontend health
Alpha eval passed: 3 golden questions, report=artifacts/alpha-eval-report.json
```

## Open the local services

After `make verify` or `make compose-up`, use:

- API health: <http://localhost:18000/healthz>
- API readiness: <http://localhost:18000/readyz>
- Web UI: <http://localhost:13000>

Local service ports:

| Service | URL / port |
| --- | --- |
| API | `http://localhost:18000` |
| Web | `http://localhost:13000` |
| PostgreSQL | `localhost:55432` |
| Redis | `localhost:6380` |

## Faster development loop

Once dependencies are installed:

```bash
make compose-up
make migrate
make test
make test-integration
make qa-smoke
```

Stop services:

```bash
make compose-down
```

Clean local Python/tool caches:

```bash
make clean
```

## First indexed project and Hermes-style query

After `make verify`, the stack has already exercised this path through `scripts/qa_smoke.py`. To run it yourself:

```bash
export SOURCEBRIEF_API_URL=http://localhost:18000
export SOURCEBRIEF_EMAIL=demo@example.com
export PATH="$PWD/.venv/bin:$PATH"

WORKSPACE_ID=$(sourcebrief --json workspace create --name Demo --slug "demo-$(date +%s)" | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')
PROJECT_ID=$(sourcebrief --json project create --workspace-id "$WORKSPACE_ID" --name "Demo Project" | python -c 'import json,sys; print(json.load(sys.stdin)["id"])')
RESOURCE_JSON=$(sourcebrief --json resource add-repo --workspace-id "$WORKSPACE_ID" --project-id "$PROJECT_ID" --name SourceBrief --repo-url https://github.com/pingchesu/sourcebrief.git --branch main --refresh --wait)
RESOURCE_ID=$(printf '%s' "$RESOURCE_JSON" | python -c 'import json,sys; print(json.load(sys.stdin)["resource"]["id"])')

sourcebrief agent-context \
  --workspace-id "$WORKSPACE_ID" \
  --project-id "$PROJECT_ID" \
  --resource-id "$RESOURCE_ID" \
  --runtime hermes \
  --query "how does SourceBrief expose agent context?"
```

For Hermes MCP config/token validation:

```bash
python scripts/hermes_integration.py \
  --api-url http://localhost:18000 \
  --workspace-id "$WORKSPACE_ID" \
  --project-id "$PROJECT_ID" \
  --resource-id "$RESOURCE_ID" \
  --query "agent-context API" \
  --expect-text "agent-context"
```

## Dev authentication

Local API requests use a development header:

```bash
X-User-Email: demo@example.com
```

The first request from an email creates or resolves the local user. Workspace and project membership still matter, so a different email cannot read your workspace/project unless it has membership.

## Troubleshooting

### Port already in use

SourceBrief uses ports `18000`, `13000`, `55432`, and `6380`. Stop the conflicting process or edit `docker-compose.yml`.

### Docker services are stale

```bash
make compose-down
docker compose up -d --build
make migrate
```

### Integration tests cannot connect to Postgres

Make sure Compose is up and migrations ran:

```bash
make compose-up
make migrate
make test-integration
```

### Frontend dependency warnings

`npm audit` may report moderate dependency warnings from the frontend stack. They do not block the current local MVP gate, but should be handled before public deployment.

## CLI check

The local package installs the `sourcebrief` CLI:

```bash
sourcebrief --help
sourcebrief health
```

The CLI reads these environment variables:

```bash
export SOURCEBRIEF_API_URL=http://localhost:18000
export SOURCEBRIEF_EMAIL=demo@example.com
```

## What next?

After the stack is running, continue with [`docs/GUIDE.md`](GUIDE.md) to create a workspace, ingest a markdown resource or git repo, query it, and request an agent context packet.
