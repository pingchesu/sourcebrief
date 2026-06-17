# Milestone 28 — Agent Card Drift Auditor

Phase 5 adds a read-only drift auditor for repo-agent cards and skill packs.

## Scope

- Persist `agent_card_summaries` with status, severity, findings, metrics, acknowledgement, and suppression fields.
- Evaluate git repo-agent health from existing ContextSmith evidence:
  - resource status and retrieval enablement;
  - current snapshot and index-run status;
  - chunk, embedding, symbol, and graph coverage;
  - latest retrieval eval status/pass rate;
  - review status and freshness age.
- Expose summaries through API endpoints:
  - `GET /workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries`
  - `POST /workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries/run`
  - `POST /workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries/{summary_id}/acknowledge`
- Add the auditor to the maintenance scheduler with an at-most-daily default cadence.
- Surface latest drift status and findings on the Repo Agents page.

## Safety Contract

The default manual API run is dry-run and requires only `review:read`. Persisting summaries requires `review:write` plus project membership.

The scheduler is the only default persistent path and writes only ContextSmith summary/audit records. It does not rotate tokens, enable write tools, mutate source repos, send Slack/webhook messages, publish skill packs, or open PRs.

Slack/webhook delivery and GitHub PR draft generation remain out of scope for this milestone and must stay behind explicit future configuration and approval.

## Scheduling

`CONTEXTSMITH_AGENT_CARD_AUDITOR=true` enables maintenance-time audits. `CONTEXTSMITH_AGENT_CARD_AUDIT_INTERVAL_HOURS` defaults to `24`.

The scheduler orders projects by each project's least-recently-audited git resource, treating never-audited resources as oldest. This prevents a fixed project/resource window from starving later repo agents.

## Verification

- `ruff` passed for touched Python files.
- `mypy` passed for API/shared/worker packages.
- `npm run lint` passed for the web app.
- `DATABASE_URL=postgresql+psycopg://contextsmith:contextsmith@localhost:55432/contextsmith .venv/bin/alembic upgrade head` passed.
- Full test suite: `119 passed`.
- Web production build passed.
- Docker build/start smoke passed for API, frontend, default worker, and maintenance worker.
- Browser QA confirmed `/repo-agents` loads drift status, findings count, and the read-only audit action.
- Hermes adversarial review final verdict: PASS.
