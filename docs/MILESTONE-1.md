# Milestone 1: Foundation, Runtime Skeleton, and Real-Service QA Gate

Status: Draft v0.1  
Parent spec: [`docs/SPEC.md`](./SPEC.md)

## 1. Intent

Milestone 1 establishes the executable architecture for ContextSmith before feature work expands.

The goal is not just to create models or unit tests. The goal is to prove that the platform can boot as a real multi-service system and execute a thin end-to-end workflow through the API, database, Redis/RQ worker, and frontend/runtime shell.

Milestone 1 should leave the repository with a developer experience where every meaningful change can be verified by:

1. lint
2. type/static checks where applicable
3. unit tests for local logic
4. full Docker Compose startup
5. real-service integration tests against Postgres/pgvector, Redis, API, worker, and frontend health
6. a QA-style smoke flow that exercises the system as a user would

## 2. Architectural Decisions for M1

### 2.1 Backend

- Python + FastAPI.
- SQLAlchemy or SQLModel acceptable, but migrations must be Alembic-based.
- API should be typed with Pydantic schemas.

### 2.2 Worker

- Use **RQ** for V0 background jobs.
- Redis is the RQ broker.
- PostgreSQL `index_runs` is the durable source of job truth.
- RQ job payloads should carry IDs only, e.g. `index_run_id`, `resource_id`.
- Redis must be treated as an internal trusted service. Do not allow user-controlled callables or arbitrary serialized payloads.

### 2.3 Database

- PostgreSQL with pgvector extension enabled.
- M1 migrations must include tenancy/auth/resource foundation tables, even if some fields are not yet fully used.
- All core rows must carry `workspace_id` when applicable.

### 2.4 Frontend

- Next.js/React shell.
- M1 frontend can be minimal, but it must be part of Docker Compose and expose a health page or landing page.

### 2.5 Docker Compose

M1 must include a working local runtime:

```text
postgres
redis
api
worker-default
worker-maintenance or scheduler placeholder
frontend
```

Optional in M1:

```text
embedding-service stub
rerank-service stub
```

Do not add external services beyond Postgres/pgvector, Redis, API, worker, frontend unless required by the M1 tests.

## 3. M1 Deliverables

### 3.1 Repository Structure

Recommended initial layout:

```text
contextsmith/
  apps/
    api/
      contextsmith_api/
      tests/
    web/
      app/
      tests/
  packages/
    worker/
      contextsmith_worker/
      tests/
    shared/
      contextsmith_shared/
      tests/
  migrations/
  docker/
  scripts/
  docs/
  docker-compose.yml
  pyproject.toml
  package.json
  README.md
```

Alternative layouts are acceptable if they preserve clear boundaries:

- API
- worker
- shared domain/db code
- web frontend
- migrations
- scripts/tests

### 3.2 Database Tables

M1 migrations should include at minimum:

- `workspaces`
- `users`
- `workspace_memberships`
- `api_tokens`
- `audit_events`
- `projects`
- `project_memberships`
- `resources`
- `source_snapshots`
- `index_runs`

Embedding/chunk/code/graph tables can be created in later milestones unless needed by early smoke tests.

### 3.3 API Endpoints

M1 API must support:

```http
GET  /healthz
GET  /readyz
POST /workspaces
GET  /workspaces/{workspace_id}
POST /workspaces/{workspace_id}/projects
GET  /workspaces/{workspace_id}/projects/{project_id}
POST /workspaces/{workspace_id}/projects/{project_id}/resources
GET  /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}
POST /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/refresh
GET  /workspaces/{workspace_id}/index-runs/{index_run_id}
```

The refresh endpoint may enqueue a no-op or placeholder RQ job in M1. The important point is to prove API → Postgres `index_runs` → RQ → worker → Postgres status transition works.

### 3.4 Worker Jobs

M1 worker jobs:

```text
noop_index_run(index_run_id)
refresh_resource_placeholder(index_run_id, resource_id)
```

Expected status transition:

```text
queued -> running -> succeeded
```

Failure path should also be testable:

```text
queued -> running -> failed
```

### 3.5 Auth and Permissions

M1 can use development auth, but permission enforcement cannot be skipped.

Minimum acceptable approach:

- dev user identity header or local dev token
- workspace membership checked on read/write endpoints
- service token table exists and can be used by integration tests if practical
- unauthorized workspace/project read returns non-leaking error semantics consistent with `docs/SPEC.md`

## 4. Testing and QA Discipline

### 4.1 Required Test Tiers

Every development slice should pass:

```text
lint
unit tests
integration tests
compose smoke tests
QA flow tests
```

Unit tests are useful but insufficient. A change is not done if it only passes unit tests.

### 4.2 No-Mock Default

Default stance:

> Prefer real services over mocks for platform behavior.

Use real Postgres/pgvector and Redis/RQ for integration and QA tests.

Allowed exceptions:

- pure utility function unit tests
- third-party SaaS/network services not in local compose
- destructive external operations
- slow model endpoints before embedding/rerank milestones

Even when mocks are used for a boundary, at least one real-service integration test should cover the local platform path.

### 4.3 Integration Tests

Integration tests should run against the Docker Compose services or an equivalent test compose file.

Minimum M1 integration scenarios:

1. API can connect to Postgres and Redis.
2. Database migrations apply cleanly from empty database.
3. Create workspace.
4. Create user/dev identity and membership.
5. Create project.
6. Create resource.
7. Call refresh endpoint.
8. Verify `index_runs.status = queued` immediately after enqueue.
9. Worker processes job.
10. Verify `index_runs.status = succeeded`.
11. Unauthorized user cannot read workspace/project/resource.
12. Audit event is written for at least one mutating action.

### 4.4 QA Flow Tests

QA flow tests are black-box or near-black-box tests that exercise the system like a senior QA would.

M1 QA flow:

```text
start all services
wait for health checks
apply migrations
create workspace
create project
create resource
trigger refresh
wait for worker completion
read index run status
verify audit event
verify unauthorized read fails
verify frontend health page loads
stop services cleanly
```

The test should fail if any service cannot start, migrations fail, worker cannot consume jobs, or API permissions are bypassed.

### 4.5 Local Commands

M1 should provide stable commands, for example:

```bash
make lint
make test
make test-integration
make compose-up
make compose-down
make qa-smoke
make verify
```

`make verify` should eventually run the complete gate:

```text
lint -> unit tests -> integration tests -> compose up -> QA smoke -> compose down
```

### 4.6 CI Expectations

CI should run at least:

```text
lint
unit tests
integration tests with Postgres/Redis services
```

A full Docker Compose QA smoke can run in CI if runtime cost is acceptable. If not, it must still be mandatory locally before marking development complete.

## 5. Acceptance Criteria

Milestone 1 is complete only when all of the following are true:

1. `docker compose up` starts Postgres/pgvector, Redis, API, worker, and frontend.
2. API `/healthz` and `/readyz` return success after dependencies are ready.
3. Migrations apply from an empty database.
4. Workspace/project/resource can be created through API calls.
5. Workspace/project membership is enforced on reads.
6. Resource refresh creates an `index_runs` row.
7. RQ worker consumes the job and updates `index_runs` status.
8. At least one failure-path job test records `failed` status and error metadata.
9. Audit event is written for at least one mutating action.
10. Frontend health/landing page is reachable in the composed stack.
11. `make verify` or equivalent runs lint, tests, integration tests, and the QA smoke flow.
12. The final report includes actual command output, not just a statement that tests were run.

## 6. Explicit Non-Goals for M1

M1 should not attempt to implement:

- real Git repo parsing
- embeddings
- pgvector search
- context packet retrieval
- graph extraction
- MCP server
- production connectors
- external SaaS connectors
- full auth UX
- advanced RBAC UI

Those belong to later milestones after the runtime skeleton and QA gate are reliable.

## 7. Engineering Rule for Future Milestones

For every future milestone, the completion bar is:

```text
code implemented
lint passed
tests passed
all local services started
senior-QA-style integration flow passed
failures fixed or explicitly documented
```

If a feature cannot be proven through a real composed flow, it is not done.
