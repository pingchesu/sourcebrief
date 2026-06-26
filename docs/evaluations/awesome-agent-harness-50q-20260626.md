# Issue #86 real-corpus evaluation: awesome-agent-harness top 5

Generated: 2026-06-26T17:27:40Z

Source list: <https://github.com/Picrew/awesome-agent-harness#harness-architecture--orchestration>

Fetch evidence: `artifacts/e2e/20260626170543-issue86-awesome-agent-harness-retry/source-list-fetch.json`

SourceBrief commit under test: `498ffc391484eba30b7c8356c2cf2e3619b32b03`

Evidence bundle: `artifacts/e2e/20260626170543-issue86-awesome-agent-harness-retry`

Manifest digest: `sha256:437fff6b08a69a243476b7d6478870a4857ed709511dc2fe1d6a94385fe9665c`

Workspace: `1e5a774d-0f66-409c-af6c-923270d56a5e`
Project: `7a0932f4-17fd-4f8c-92ef-079f07126b5e`

## Scope

This run imported/evaluated the top 5 entries observed in the `Harness Architecture & Orchestration` table, sorted by rendered stars:

1. Superpowers — <https://github.com/obra/superpowers>
2. ECC — <https://github.com/affaan-m/ECC>
3. Matt Pocock Skills — <https://github.com/mattpocock/skills>
4. gstack — <https://github.com/garrytan/gstack>
5. DeerFlow — <https://github.com/bytedance/deer-flow>

The durable question bank is committed at `demo/awesome_agent_harness_50q/questions.json` with 50 questions total, 10 per primary repo. Five questions are cross-repo comparison questions and the bank includes five negative controls.

## Run environment evidence

The evidence bundle includes `run-environment.json` with command/exit-code captures for:

- `git rev-parse HEAD`
- `git branch --show-current`
- `git status --short --branch`
- `make -s print-api-url`
- `make -s print-web-url`
- `docker compose config --services`

It also records configured API/web URLs, compose project, API `/readyz`, API `/provider-health`, and frontend `/api/health`.

## Import results

All five repositories were successfully imported after the runner added bounded retry for large repos. Every resulting corpus is marked `limited` because explicit import budgets were used and/or SourceBrief reported partial coverage warnings.

| Repo | Final attempt | Resource ref | Upstream commit | Status | Import type | Files | Chunks | Symbols | Embeddings | Notes |
| --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Superpowers | wide-5000-files | `Superpowers` | `896224c4b1879920ab573417e68fd51d2ccc9072` | succeeded | limited | 170 | 884 | 150 | 884 | explicit limited import budget |
| ECC | bounded-500-files | `ECC (bounded 500 files)` | `2bc924faf2f8e893bfe0af86b1931283693c30ae` | succeeded | limited | 500 | 1513 | 124 | 1513 | wide import exceeded chunk budget; bounded retry succeeded |
| Matt Pocock Skills | wide-5000-files | `Matt Pocock Skills` | `5d78bd0903420f97c791f834201e550c765699f8` | succeeded | limited | 84 | 184 | 0 | 184 | explicit limited import budget |
| gstack | bounded-500-files | `gstack (bounded 500 files)` | `11de390be1be6849eb9a15f91ff4922dd16c589a` | succeeded | limited | 500 | 4688 | 1690 | 4688 | wide import exceeded chunk budget; bounded retry succeeded |
| DeerFlow | bounded-200-files | `DeerFlow (bounded 200 files)` | `7a6c4a994a86583d2a3c056ee9d0f157d4f030c2` | succeeded | limited | 200 | 1859 | 2237 | 1859 | wide and 500-file imports exceeded symbol budget; 200-file retry succeeded |

Human-name/resource-ref selection was verified for all five final resources. Raw evidence lives under `resource-ref/` and `resource-ref-summary.json`.

## Evaluation result

All 50 questions were run through SourceBrief after import. The runner uses `/retrieval-evals` for mechanical/retrieval checks and `agent-context` for answer-ready context packets. Single-repo `agent-context` calls use `resource_ref`; multi-repo comparison calls use explicit `resource_ids` because the API currently accepts only one `resource_ref` per request.

```json
{
  "human_answer_demo_pass_rate": 0.0,
  "mechanical_api_success_rate": 1.0,
  "retrieval_quality_pass_rate": 1.0,
  "unsupported_claim_failures": 0,
  "verdict": "RISK",
  "wrong_repo_failures": 0
}
```

Grade counts:

```json
{
  "FAIL": 0,
  "PARTIAL": 50,
  "PASS": 0
}
```

Why every question is `PARTIAL`:

- all corpora are partial/limited;
- SourceBrief produced cited context for the 50 questions, but this runner proves answer-ready context, not a synthesized end-user answer;
- negative-control questions returned scoped context/citations that need human interpretation rather than clean abstention.

## Product findings

### 1. Real-world import can exceed budgets and fail with no queryable partial snapshot

Opened child issue: #112.

First wide attempts failed for ECC, gstack, and DeerFlow with `max_chunks=5000` or `max_symbols=5000` budget errors and no current snapshot. The bounded retry path made the evaluation usable, but the product should not require the operator to infer safe retry budgets manually.

### 2. SourceBrief is credible for partial-corpus retrieval, but launch verdict remains RISK

For this corpus, SourceBrief produced cited context for all 50 questions once the imports were bounded. However, all imported corpora are partial, negative-control questions still require human follow-up, and the evaluated runtime path is context generation rather than a synthesized human answer. This supports a launch-readiness verdict of `RISK`, not `PASS`.

## Reproduce

With the local SourceBrief stack ready:

```bash
API_URL="$(make -s print-api-url)"
WEB_URL="$(make -s print-web-url)"
STAMP="$(date -u +%Y%m%d%H%M%S)"
SOURCEBRIEF_API_URL="$API_URL" SOURCEBRIEF_WEB_URL="$WEB_URL" \
  .venv/bin/python scripts/run_awesome_agent_harness_eval.py \
  --api-url "$API_URL" \
  --web-url "$WEB_URL" \
  --output-dir "artifacts/e2e/${STAMP}-issue86-awesome-agent-harness" \
  --slug "issue86-${STAMP}" \
  --index-timeout 900
```

The runner stores redacted raw payloads under the output directory:

- `run-environment.json` — command/exit-code, URLs, compose project, API/frontend/provider health
- `imports/` — per-repo import attempts, snapshots, index-run outcomes
- `resource-ref/` — human-name/resource_ref lookup proof
- `eval-batches/` — `/retrieval-evals` payloads and responses
- `agent-context/` — per-question raw redacted context packets
- `eval-manifest.json` — resolved manifest with resource/snapshot IDs and upstream commits
- `eval-report.json` — schema-validated grading report
