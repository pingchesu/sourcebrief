# Milestone 23 — Persisted retrieval eval history

This milestone turns the mature-alpha Quality Evals page from a one-shot smoke tool into a persistent product gate.

## Shipped

- `retrieval_eval_runs` and `retrieval_eval_items` tables store every eval run and per-question result.
- `POST /workspaces/{workspace_id}/projects/{project_id}/retrieval-evals` still runs the real `agent-context` path, and now returns `run_id` after persisting the run.
- `GET /workspaces/{workspace_id}/projects/{project_id}/retrieval-evals` lists recent run summaries.
- `GET /workspaces/{workspace_id}/projects/{project_id}/retrieval-evals/{run_id}` returns persisted question-level evidence.
- The web `Quality Evals` page loads recent history and can reload an old run into the result viewer.

## Authorization invariant

Eval history follows the same resource-scoped token boundary as eval execution:

- workspace/project access is still required;
- unrestricted project-wide runs are hidden from resource-scoped tokens;
- resource-scoped tokens can only list/read runs whose persisted resource set is inside their allowed resources.

## Why this matters

Embedding/rerank/graph changes now have a durable comparison trail: pass rate, latency, provider/model, diagnostics, cited resources, paths, symbols, and hit-quality evidence are no longer lost after the browser refreshes.

## Not yet shipped

- Async eval jobs for large datasets.
- Dataset manager / named golden sets.
- Trend charts and provider A/B comparison UI.
