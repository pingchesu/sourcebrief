# M18 — Alpha Evaluation / Demo Dataset / Release Gate

## Goal

Prevent regressions in answer quality and platform reliability before alpha release by making a real-service demo dataset and release gate executable from the repo.

## Shipped changes

- `demo/alpha/` documents the executable demo dataset and golden query set.
- `scripts/alpha_eval.py` creates a fresh evaluation workspace/project with:
  - one git repo resource;
  - one markdown runbook resource;
  - one foreign-tenant document used only for leakage checks.
- Golden questions assert:
  - cited context exists;
  - realistic natural-language questions retrieve expected facts without embedding the answer marker in the query;
  - expected repo/runbook text is present;
  - single-resource questions exclude unrelated resource citations at the configured context budget;
  - cross-resource query cites both repo and runbook resources;
  - resources are fresh and last index status succeeded;
  - resource usage analytics record retrieval hits from `agent-context` itself and from context-packet validation;
  - foreign-tenant marker does not leak into the primary project.
- Evaluation report is written to `artifacts/alpha-eval-report.json` by default and includes context-packet rank/score/snippet/content-hash retrieval-hit quality records.
- `make alpha-eval` runs the eval against the local composed stack.
- `make release-gate` runs lint/typecheck, unit tests, integration tests, host/container migrations, real-service QA smoke, and alpha eval.
- `make verify` is now an alias for `make release-gate`.

## Release gate

```bash
make release-gate
```

Equivalent expanded gate:

```bash
make lint
make typecheck
make test
make compose-up
make migrate
make migrate-compose
make test-integration
make qa-smoke
make alpha-eval
```

## Evaluation report fields

`artifacts/alpha-eval-report.json` records:

- workspace/project/resource IDs;
- git commit for the repo fixture;
- each golden query, pass/fail, failure reasons, citation count, cited resource IDs;
- context-packet hit quality: rank, score, lexical/vector/graph/rerank scores, snippet, content hash, expected/unexpected resource flags;
- `agent_context_usage_delta` per golden question proving `agent-context` records usage before context-packet validation runs;
- latency in milliseconds;
- context length in characters;
- freshness review rows;
- resource usage rows;
- tenant-isolation assertion result;
- aggregate max/avg latency and context size.

## Verification

```bash
python -m py_compile scripts/alpha_eval.py scripts/qa_smoke.py scripts/hermes_integration.py
make lint
make typecheck
.venv/bin/pytest tests/unit tests/integration -q
make qa-smoke
make alpha-eval
make release-gate
```

## Non-goals

- Human relevance grading beyond deterministic golden checks.
- Large benchmark corpus.
- Public internet security hardening.
- Production mutation execution from SourceBrief.
