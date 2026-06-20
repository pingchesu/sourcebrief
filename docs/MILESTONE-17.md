# M17 — Open-source Alpha Packaging / Deployment

## Goal

Make a new contributor/operator able to run SourceBrief reproducibly with only common open-source services: Docker Compose, Postgres/pgvector, Redis, API, worker, and web UI.

## Shipped changes

- `.env.example` documents:
  - default local ports
  - Postgres/Redis service URLs
  - local dev auth and CORS origins
  - local-git alpha fixture support
  - deterministic offline embedding/rerank providers
  - optional HuggingFace/vLLM/SGLang/OpenAI-compatible embedding and rerank provider settings
- `docker-compose.yml` now consumes env defaults while preserving the six-service alpha stack:
  - `postgres`
  - `redis`
  - `api`
  - `worker-default`
  - `worker-maintenance`
  - `frontend`
- `Makefile` adds:
  - `compose-ps`
  - `compose-logs`
  - `migrate-compose`
  - `API_URL` / `WEB_URL` variables for smoke waits
  - `verify` now exercises both host-side and container-side migrations
- `docs/QUICKSTART.md` now reaches a first indexed project and Hermes-style query.
- `docs/OPERATIONS.md` covers logs, queue checks, stuck index runs, migrations, rollback, and data reset.

## Operator flow

```bash
cp .env.example .env
make verify
open http://localhost:13000
```

For a shorter running-stack check:

> If you change `NEXT_PUBLIC_API_BASE_URL` or web/API ports, rebuild the frontend with `docker compose up -d --build`. For custom web ports, set `SOURCEBRIEF_CORS_ORIGINS` to the browser origins that should call the API.

```bash
make compose-up
make migrate
make migrate-compose
make qa-smoke
```

## Migration paths

Host-side:

```bash
make migrate
```

Container-side:

```bash
make migrate-compose
```

Both paths use the same Alembic migration tree. `make verify` runs both so drift between host and containerized packaging is caught early.

## Provider-backed embeddings/rerank

Default alpha deployments use deterministic local providers:

```env
SOURCEBRIEF_EMBEDDING_PROVIDER=hashing
SOURCEBRIEF_RERANK_PROVIDER=term-overlap
```

Provider-backed deployments should set endpoint/model/deployment-id together and then reindex resources:

```env
SOURCEBRIEF_EMBEDDING_PROVIDER=openai-compatible
SOURCEBRIEF_EMBEDDING_MODEL=bge-small-64
SOURCEBRIEF_EMBEDDING_ENDPOINT=http://embedding-service:8000/v1/embeddings
SOURCEBRIEF_EMBEDDING_DEPLOYMENT_ID=local-vllm-bge-small-64
```

SourceBrief MVP vector storage expects 64-dimensional embeddings. The `/provider-health` endpoint should return HTTP 200 before indexing with a provider-backed config.

## Verification

```bash
docker compose config >/tmp/sourcebrief-compose.yaml
python -m py_compile scripts/hermes_integration.py scripts/qa_smoke.py
make lint
.venv/bin/pytest tests/unit tests/integration -q
SOURCEBRIEF_API_PORT=18123 SOURCEBRIEF_WEB_PORT=13123 make -n qa-smoke
make migrate-compose
make qa-smoke
```

## Non-goals

- Kubernetes/Helm packaging.
- Public internet hardening.
- SSO/SCIM/enterprise auth.
- Production mutation execution from SourceBrief.
