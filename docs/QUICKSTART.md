# Quick start

This guide gets SourceBrief running locally and gets you to the first useful product moment: a source connected to the web console and ready for cited context queries.

For the full contributor/release gate, skip to [Full verification](#full-verification). It is intentionally heavier than the quick start.

Want to see the intended result before running the stack yourself? Open the [product walkthrough](WALKTHROUGH.md), [proof artifacts manifest](PROOF_ARTIFACTS.md), and captured [agent-context output](examples/agent-context-output.md). These were generated from real local SourceBrief runs.

If your goal is to use SourceBrief from Hermes, Claude Code, Codex, Cursor, MCP, or generated skills, read [Agent runtime usage](AGENT_RUNTIME_USAGE.md) after the stack is running.

## Prerequisites

Install:

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

## 1. Clone and configure

```bash
git clone https://github.com/pingchesu/sourcebrief.git
cd sourcebrief

cp .env.example .env
```

Before the first startup, edit `.env` and replace the example admin password:

```env
SOURCEBRIEF_ADMIN_EMAIL=admin@sourcebrief.local
SOURCEBRIEF_ADMIN_PASSWORD=<choose-a-local-password>
```

Keep this default unless you explicitly want local header auth for CLI experiments:

```env
SOURCEBRIEF_DEV_AUTH=false
```

If you change ports or `NEXT_PUBLIC_API_BASE_URL`, rebuild the frontend with `docker compose up -d --build`; the browser-visible API URL is compiled into the Next.js client.

## 2. Start the local stack

```bash
make compose-up
until curl -fsS http://localhost:18000/readyz; do sleep 2; done
until curl -fsS http://localhost:13000/api/health; do sleep 2; done
```

This starts:

| Service | URL / port |
| --- | --- |
| API | `http://localhost:18000` |
| Web | `http://localhost:13000` |
| PostgreSQL | `localhost:55432` |
| Redis | `localhost:6380` |

The API container runs migrations automatically in Compose through `SOURCEBRIEF_AUTO_MIGRATE=true`.

## 3. Open the web console

Open:

```text
http://localhost:13000/login
```

Sign in with the admin account from `.env`:

```text
SOURCEBRIEF_ADMIN_EMAIL
SOURCEBRIEF_ADMIN_PASSWORD
```

You should land in the SourceBrief console with a default workspace and project.

## 4. Add your first source

Use the UI first; it is the clearest product path.

1. Open **Sources**.
2. Add a small Git repo, Markdown document, URL, upload, or zip folder bundle.
3. Start indexing if the UI does not start it automatically.
4. Wait for the resource to reach an indexed/retrieval-ready state.
5. Open **Workbench** and ask a question about that source.
6. Expand the citations. A useful result should point back to source paths, line ranges, document hashes, snapshots, or commits.

The product is working when the answer is not just plausible. It should be inspectable.

### Large repo behavior

Real repos may exceed the default import budgets for chunks or code symbols. SourceBrief should not leave that ambiguous:

- Sources with no current snapshot are marked **not queryable** even if retrieval is enabled.
- Failed index runs show the budget that failed, the configured limit, and a suggested retry path.
- Limited/fallback imports are marked **partial**; generated context packets include coverage warnings so agents do not over-trust a subset corpus.
- If a repo is too broad, retry with a smaller `max_repo_files` / `max_repo_bytes`, a docs-only or source-subpath import, include/exclude filters, or an intentional higher budget.

## 5. CLI first useful moment

The fastest CLI path is a deterministic demo that creates an isolated workspace/project, adds a tiny runbook, indexes it, and ends with a cited human answer instead of raw JSON plumbing:

```bash
make venv
export PATH="$PWD/.venv/bin:$PATH"
export SOURCEBRIEF_API_URL=http://localhost:18000
export SOURCEBRIEF_EMAIL=demo@example.com

sourcebrief quickstart-demo
```

Expected shape:

```text
Quickstart demo: indexed and ready for retrieval
  workspace_id: ...
  project_id: ...
  resource_id: ...
  index_status: succeeded
Answer: Retry payment jobs with exponential backoff. Escalate after three failures.
Citations:
- [1] runbooks/payment-retry.md score=...
Next:
- sourcebrief ask --workspace-id ... --project-id ... --resource ... "What should an operator do when payment retries fail?"
```

After the demo, ask follow-up questions with the saved IDs from the transcript:

```bash
sourcebrief ask \
  --workspace-id "$WORKSPACE_ID" \
  --project-id "$PROJECT_ID" \
  --resource "$RESOURCE_ID" \
  "what should an operator do when payment retries fail?"
```

`sourcebrief ask` prints a concise cited answer by default. Add `--json` when you need the full agent-context packet for runtime debugging or automation.

For local automation, you can save workspace/project defaults so resource and query commands do not require repeating UUIDs:

```bash
sourcebrief use --workspace-id "$WORKSPACE_ID" --project-id "$PROJECT_ID"
sourcebrief resource add-doc --name "Payment retry runbook" --uri demo://payment-retry --content "Retry with exponential backoff." --refresh --wait
sourcebrief ask --resource "Payment retry runbook" "how should retryable payment failures be handled?"
```

The CLI supports two auth modes:

- bearer token: `SOURCEBRIEF_TOKEN` or `--token`
- local development header auth: `SOURCEBRIEF_DEV_AUTH=true` plus `SOURCEBRIEF_EMAIL`

The default `.env.example` has `SOURCEBRIEF_DEV_AUTH=false`, so local header-auth experiments require opting in before startup:

```env
SOURCEBRIEF_DEV_AUTH=true
```

For shared or production-like deployments, do not use dev auth. Use a scoped API token instead.

### Advanced raw packet proof

Use this when validating the agent runtime contract rather than the human first-use flow:

```bash
sourcebrief agent-context \
  --workspace-id "$WORKSPACE_ID" \
  --project-id "$PROJECT_ID" \
  --resource-id "$RESOURCE_ID" \
  --runtime hermes \
  --query "how does SourceBrief expose agent context?"
```

## Full verification

Use this when contributing or validating a release candidate:

```bash
make verify
```

`make verify` is an alias for the full release gate. It runs:

1. Python dev dependency install
2. frontend dependency install
3. Python lint
4. backend mypy typecheck
5. frontend typecheck
6. unit tests
7. Docker Compose build/start
8. host and container Alembic migrations
9. integration tests against real Postgres/Redis/API behavior
10. QA smoke flow
11. alpha evaluation, writing `artifacts/alpha-eval-report.json`

Expected final output includes:

```text
QA smoke passed: document+git ingestion -> snapshots -> chunks -> embeddings -> code symbols -> graph index -> lexical/hybrid/GraphRAG context retrieval with citations, CLI search, agent profile, web console homepage/token flow, provider health/namespace diagnostics, query/resource usage analytics, review lifecycle, scheduled refresh dry-run, restore/purge lifecycle, upload connector redaction, agent-context API, central MCP context tool, index-run logs, audit events, RQ worker, auth denial, frontend health
Alpha eval passed: 3 golden questions, report=artifacts/alpha-eval-report.json
```

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

## Troubleshooting

### Port already in use

SourceBrief uses ports `18000`, `13000`, `55432`, and `6380` by default. Stop the conflicting process or override ports in `.env`.

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

### CLI returns `authentication required`

You are probably using `SOURCEBRIEF_EMAIL` while `SOURCEBRIEF_DEV_AUTH=false`. Either:

- use `SOURCEBRIEF_TOKEN`, or
- set `SOURCEBRIEF_DEV_AUTH=true` in `.env`, restart the stack, and use `SOURCEBRIEF_EMAIL` only for local demos.

### Frontend dependency warnings

`npm audit` may report moderate dependency warnings from the frontend stack. They do not block the current local alpha gate, but should be handled before public deployment.

## Next steps

- Read [Concepts](CONCEPTS.md) for SourceBrief terminology.
- Read [Guide](GUIDE.md) for API, CLI, Git resource, MCP, and review workflows.
- Read [Operations](OPERATIONS.md) for logs, queues, migrations, and reset procedures.
