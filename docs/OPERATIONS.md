# SourceBrief Alpha Operations Runbook

This runbook is for the open-source alpha Docker Compose deployment. It assumes the default local ports from `.env.example` unless overridden. `make` includes `.env` automatically when the file exists, so port/database overrides apply to the Makefile targets as well as Docker Compose.

## Start, stop, and status

```bash
cp .env.example .env  # optional but recommended
make compose-up
make migrate          # host-side Alembic migration
make migrate-compose  # container-side Alembic migration check
make compose-ps
```

Stop without deleting Postgres data:

```bash
make compose-down
```

Delete local persistent data only when intentionally resetting the alpha stack:

```bash
docker compose down --remove-orphans --volumes
```

## Configuration notes

- `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `POSTGRES_DB` drive both the Postgres container and the default API/worker database URL.
- Set `SOURCEBRIEF_DATABASE_URL` only when intentionally pointing API/workers at a non-compose database.
- `NEXT_PUBLIC_API_BASE_URL` is baked into the Next.js client at build time. After changing it, run `docker compose up -d --build`.
- If `SOURCEBRIEF_WEB_PORT` changes, update `SOURCEBRIEF_CORS_ORIGINS` to include the browser origin, for example `http://localhost:13100,http://127.0.0.1:13100`.

## Health checks

```bash
curl -fsS http://localhost:${SOURCEBRIEF_API_PORT:-18000}/healthz
curl -fsS http://localhost:${SOURCEBRIEF_API_PORT:-18000}/readyz
curl -fsS http://localhost:${SOURCEBRIEF_WEB_PORT:-13000}/api/health
```

Provider health:

```bash
curl -fsS http://localhost:${SOURCEBRIEF_API_PORT:-18000}/provider-health | python -m json.tool
```

`/provider-health` returns HTTP 503 when a provider-backed embedding/rerank endpoint is configured but unavailable.

## Logs

Tail all application logs:

```bash
make compose-logs
```

Individual services:

```bash
docker compose logs --tail=200 api
docker compose logs --tail=200 worker-default
docker compose logs --tail=200 worker-maintenance
docker compose logs --tail=200 frontend
docker compose logs --tail=200 postgres
docker compose logs --tail=200 redis
```

Follow logs while running a refresh:

```bash
docker compose logs -f api worker-default worker-maintenance
```

## Migrations

Host-side migration path:

```bash
make migrate
```

Container-side migration path:

```bash
make migrate-compose
```

Inspect current revision:

```bash
DATABASE_URL=${DATABASE_URL:-postgresql+psycopg://sourcebrief:sourcebrief@localhost:${SOURCEBRIEF_POSTGRES_PORT:-55432}/sourcebrief} \
  .venv/bin/alembic current

docker compose exec -T api alembic current
```

Rollback one revision in a local alpha environment only:

```bash
DATABASE_URL=${DATABASE_URL:-postgresql+psycopg://sourcebrief:sourcebrief@localhost:${SOURCEBRIEF_POSTGRES_PORT:-55432}/sourcebrief} \
  .venv/bin/alembic downgrade -1
```

For shared deployments, prefer database backup + forward fix over ad-hoc downgrade.

## Queue and worker checks

Redis queue depth:

```bash
docker compose exec -T redis redis-cli LLEN rq:queue:default
# There is no separate maintenance RQ queue in alpha; worker-maintenance schedules due refreshes onto the default queue.
```

Worker liveness:

```bash
docker compose ps worker-default worker-maintenance
docker compose logs --tail=100 worker-default worker-maintenance
```

Recent index runs:

```bash
docker compose exec -T postgres psql -U sourcebrief -d sourcebrief -c \
  "select id, resource_id, trigger, status, error_message, started_at, finished_at from index_runs order by created_at desc limit 20;"
```

Stuck queued/running runs:

```bash
docker compose exec -T postgres psql -U sourcebrief -d sourcebrief -c \
  "select id, resource_id, trigger, status, created_at, started_at, error_message from index_runs where status in ('queued','running') order by created_at asc;"
```

## Handling stuck index runs

1. Confirm worker containers are healthy/running:

   ```bash
   docker compose ps worker-default worker-maintenance
   ```

2. Read worker logs for the affected run/resource:

   ```bash
   docker compose logs --tail=300 worker-default worker-maintenance | grep -i '<run-or-resource-id>'
   ```

3. Check provider health if embeddings/rerank are provider-backed:

   ```bash
   curl -fsS http://localhost:${SOURCEBRIEF_API_PORT:-18000}/provider-health | python -m json.tool
   ```

4. If the run failed due a transient dependency, refresh the resource again from UI or CLI:

   ```bash
   sourcebrief resource refresh --workspace-id <workspace> --project-id <project> --resource-id <resource> --wait
   ```

5. If a run remains `queued` with no worker activity, restart workers only:

   ```bash
   docker compose restart worker-default worker-maintenance
   ```

Do not manually mutate `index_runs` rows unless this is a disposable local alpha database.

## Rollback and recovery

Application rollback to the last merged commit:

```bash
git fetch origin main
git checkout main
git reset --hard origin/main
docker compose up -d --build
make migrate-compose
make qa-smoke
```

Config rollback:

```bash
git checkout -- docker-compose.yml .env.example
# or restore your previous .env from backup
docker compose up -d --build
```

Data reset for local alpha demos:

```bash
docker compose down --remove-orphans --volumes
make compose-up
make migrate-compose
make qa-smoke
```

## Production boundary reminder

SourceBrief returns static/cited context. It does not execute production mutations. Live operations must remain behind separate typed MCP tools, approval, and evidence workflows.
