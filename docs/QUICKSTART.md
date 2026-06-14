# Quick start

This guide gets ContextSmith running locally with the real services used by the test suite.

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
git clone https://github.com/pingchesu/contextsmith.git
cd contextsmith
```

## Run the full acceptance gate

```bash
make verify
```

This command does the full local path:

1. creates `.venv` with Python 3.11
2. installs Python dev dependencies
3. installs frontend dependencies
4. runs Python lint
5. runs frontend typecheck
6. runs unit tests
7. builds and starts Docker services
8. runs Alembic migrations
9. runs integration tests against real Postgres/Redis/API behavior
10. runs the QA smoke flow

Expected final smoke output:

```text
QA smoke passed: document+git ingestion → snapshots → chunks → embeddings → code symbols → lexical/hybrid context retrieval with citations, query/resource usage analytics, review lifecycle, agent-context API, central MCP context tool, index-run logs, audit events, RQ worker, auth denial (read+search), frontend health
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

## Dev authentication

Local API requests use a development header:

```bash
X-User-Email: demo@example.com
```

The first request from an email creates or resolves the local user. Workspace and project membership still matter, so a different email cannot read your workspace/project unless it has membership.

## Troubleshooting

### Port already in use

ContextSmith uses ports `18000`, `13000`, `55432`, and `6380`. Stop the conflicting process or edit `docker-compose.yml`.

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

The local package installs the `contextsmith` CLI:

```bash
contextsmith --help
contextsmith health
```

The CLI reads these environment variables:

```bash
export CONTEXTSMITH_API_URL=http://localhost:18000
export CONTEXTSMITH_EMAIL=demo@example.com
```

## What next?

After the stack is running, continue with [`docs/GUIDE.md`](GUIDE.md) to create a workspace, ingest a markdown resource or git repo, query it, and request an agent context packet.
