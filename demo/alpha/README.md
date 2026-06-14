# ContextSmith alpha demo dataset

This directory documents the executable demo dataset used by `scripts/alpha_eval.py`.

The script creates the dataset dynamically so the release gate can run against the same Docker Compose stack used by operators.

## Resources created

- **Alpha Eval Repo** — a local git bundle mounted into the worker container. It contains:
  - `README.md` explaining that repository agent context is exposed through REST and central MCP tools;
  - `src/context_agent.py` defining `alpha_repo_symbol`.
- **Alpha Eval Runbook** — markdown runbook content with provider-health/index-run/reindex escalation guidance.
- **Foreign Tenant Secret** — markdown resource in a separate workspace and separate principal. The primary project must not retrieve its `forbiddenleak42` marker or resource ID.

## Golden questions

`golden_questions.json` contains natural-language questions that do **not** include the answer marker tokens. Each row declares:

- expected text facts that must appear in cited context;
- expected resource classes (`repo`, `runbook`);
- unexpected resource classes that must not appear for single-resource questions;
- per-question `top_k` context budget;
- minimum citation count.

The eval runs each question through both:

1. `agent-context` — validates runtime context/citations and proves usage-hit deltas are recorded before packet validation runs.
2. `context-packets` — records packet artifacts and retrieval-hit quality fields.

## Report

The report is written to `artifacts/alpha-eval-report.json` and includes:

- pass/fail and failure reasons per golden question;
- cited resource IDs and packet resource IDs;
- hit quality rows with rank, score, lexical/vector/graph/rerank scores, snippet, content hash, and expected/unexpected resource flags;
- latency and context length;
- freshness review rows;
- resource usage rows;
- tenant isolation result.
