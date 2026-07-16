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
- The default Compose file publishes Postgres and Redis to `127.0.0.1` only. On remote or shared hosts, keep those internal data services loopback-bound unless you intentionally add a local Compose override and matching firewall policy for development access.

Run the quickstart doctor after editing `.env` to catch missing host tools and remote-browser configuration mistakes before rebuilding containers:

```bash
python3 scripts/check_quickstart_prereqs.py
SOURCEBRIEF_HOST=<sourcebrief-host-or-ip>
python3 scripts/check_quickstart_prereqs.py \
  --remote-browser-origin "http://${SOURCEBRIEF_HOST}:${SOURCEBRIEF_WEB_PORT:-13000}"
```

## Remote/self-host port exposure

The alpha stack intentionally separates browser/API exposure from data-service exposure:

- API and web ports may be reachable from other machines when the host firewall and Docker networking allow it.
- Postgres and Redis are internal services for the API/workers and bind to loopback by default.
- For remote/self-host evaluation, expose only the API/web ports you need and keep DB/Redis off the LAN/public interface.
- If users open the web UI from another machine, `NEXT_PUBLIC_API_BASE_URL` must be the browser-visible API origin, such as `http://10.10.70.17:${SOURCEBRIEF_API_PORT:-18000}`, and `SOURCEBRIEF_CORS_ORIGINS` must include the browser-visible web origin.
- API `/readyz` and web `/api/health` can both pass while browser login still fails from another machine if the frontend was built with `NEXT_PUBLIC_API_BASE_URL=http://localhost:...`; run the remote-browser quickstart doctor or a browser login smoke before declaring remote/self-host setup healthy.
- If you need host-side database inspection, connect from the Docker host via `localhost:${SOURCEBRIEF_POSTGRES_PORT:-55432}` or run `docker compose exec -T postgres ...`.
- If you intentionally need remote DB/Redis access in a disposable development environment, add an explicit untracked override such as `docker-compose.override.yml`; do not rely on the shared default compose file to expose those services.

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

## Atomic Git snapshot/graph rollout and recovery

The Git refresh consistency contract is enforced by application code and does not require a schema migration. It becomes active only after the new workers and API/runtime are deployed. Keep production Git resources on `manual` during the rollout; changing refresh frequency is a separate, explicit operation.

### Preflight and drift inventory

Before replacing workers, stop the maintenance scheduler so it cannot enqueue new scheduled work, then let active default-queue work drain:

```bash
docker compose stop worker-maintenance
docker compose exec -T redis redis-cli LLEN rq:queue:default
docker compose exec -T postgres psql -U sourcebrief -d sourcebrief -c \
  "select id, resource_id, trigger, status, created_at, started_at from index_runs where status in ('enqueueing','queued','running') order by created_at asc;"
```

Do not stop default workers until the queue is empty and no run is `enqueueing`, `queued`, or `running`. Record legacy Git snapshot/graph drift before deployment:

```bash
docker compose exec -T postgres psql -U sourcebrief -d sourcebrief -c \
  "select r.id as resource_id, r.name, r.current_snapshot_id, g.id as graph_id, g.current_version_id, gv.status as graph_status, gv.source_snapshot_id as graph_snapshot_id from resources r left join graphs g on g.resource_id = r.id and g.status = 'active' left join graph_versions gv on gv.id = g.current_version_id where lower(r.type) in ('git','git_repo','git-repo','repo','repository') and r.status = 'active' and r.deleted_at is null and r.archived_at is null and (r.current_snapshot_id is null or g.id is null or gv.id is null or gv.status <> 'published' or gv.source_snapshot_id is distinct from r.current_snapshot_id) order by r.created_at asc;"
```

Save the result as rollout evidence. A non-empty result is not safe to hide: repair/backfill those resources with the new worker path before enabling fail-closed runtime access broadly.

### Git import-bound audit

Generic Git resource create/update rejects configured integer bounds outside the supported envelope with HTTP `422`; the worker repeats the same validation as a final defense. Omitted fields keep worker defaults. Deployments must not silently clamp or rewrite legacy rows at startup because changing a bound changes the extraction fingerprint and therefore the indexed corpus.

Before enabling scheduled refresh for legacy resources, run this read-only audit:

```bash
docker compose exec -T postgres psql -U sourcebrief -d sourcebrief -c \
  "with limits(field, maximum) as (values ('clone_timeout',600::numeric),('max_file_bytes',10000000),('max_repo_files',5000),('max_repo_bytes',200000000),('max_chunks',20000),('max_symbols',20000)) select r.id,r.name,l.field,r.source_config->>l.field as configured,l.maximum from resources r cross join limits l where lower(r.type) in ('git','git_repo','git-repo','repo','repository') and r.status = 'active' and r.deleted_at is null and r.archived_at is null and r.source_config ? l.field and case when r.source_config->>l.field ~ '^[0-9]+$' then (r.source_config->>l.field)::numeric not between 1 and l.maximum else true end order by r.name,l.field;"
```

An empty result is the required precondition. For a non-empty result, review each resource and update it through the supported Git settings/resource API; then refresh in bounded waves so the new extraction fingerprint produces an explicit snapshot/graph pair. Retain failed runs as audit evidence rather than deleting them.

### Worker-first deployment order

A mixed old-worker/new-runtime deployment is unsupported because an old worker can advance a snapshot without publishing its matching graph. Use this order:

```bash
# Maintenance is already stopped from preflight. Stop every default-worker replica.
docker compose stop worker-default

# Build the shared API/worker image from the intended commit.
docker compose build api worker-default worker-maintenance

# Start new workers first and verify their logs/liveness.
docker compose up -d worker-default worker-maintenance
docker compose ps worker-default worker-maintenance
docker compose logs --tail=100 worker-default worker-maintenance

# Only after old workers are absent, recreate the API/runtime.
docker compose up -d api
curl -fsS http://localhost:${SOURCEBRIEF_API_PORT:-18000}/readyz
```

For deployments with scaled workers, verify every old replica is gone rather than checking only one container name. Do not change any resource from `manual` to `daily` yet.

### Canary and post-deploy proof

Refresh one non-empty Git canary through the normal UI or CLI:

```bash
sourcebrief resource refresh \
  --workspace <workspace-name-or-slug> \
  --project <project-name> \
  --resource-id <resource-id> \
  --wait
```

Then verify:

1. The run succeeded and did not return to `queued` after a fast worker completed.
2. `graph_versions.source_snapshot_id` equals `resources.current_snapshot_id`.
3. Repeating a scheduled refresh at the same commit and policy produces no snapshot/version churn.
4. A source-config policy change at the same commit creates a new matching snapshot/graph pair.
5. Any dependent current merge version becomes `invalidated`, inventory reports it stale, and default graph query/path calls return `409 stale_merge_graph`.
6. Audit evidence contains `graph_version.compile`, `graph_version.publish`, and, when applicable, `graph_merge.stale`.

Inspect invalidated current merges:

```bash
docker compose exec -T postgres psql -U sourcebrief -d sourcebrief -c \
  "select gm.merge_key, gmv.version, gmv.status, gmv.invalidated_at, gmv.status_reason from graph_merges gm join graph_merge_versions gmv on gmv.id = gm.current_version_id where gm.status = 'active' and gmv.status = 'invalidated' order by gmv.invalidated_at desc;"
```

Re-run the drift inventory after the canary/backfill. Proceed to a small `daily` cohort only when the result is empty and the canary evidence is complete.

### Legacy fingerprint and failure behavior

Snapshots created before the atomic-refresh release do not contain an extraction-policy fingerprint. Their first scheduled refresh on the new worker intentionally rebuilds once even when the Git commit is unchanged. Roll out `daily` in bounded cohorts so this one-time indexing load does not create a queue spike.

If graph compile, validation, or publish fails, the new snapshot/graph transaction rolls back and the previous complete pair remains current. Scheduled failures set `next_refresh_at` to approximately 15 minutes later. Diagnose the failed run and provider/source health; do not manually promote a staged snapshot or graph version.

When a merge is invalidated, rebuild it through the Graph UI/API using current published resource graph inputs, review reconciliation candidates, and publish the replacement. Do not manually change merge-version status or current pointers. An application rollback does not automatically republish an invalidated merge; prefer a forward fix/rebuild with retained audit history.

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
   sourcebrief resource refresh --workspace <workspace-name-or-slug> --project <project-name> --resource-id <resource> --wait
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
