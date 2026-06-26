# Issue #86 real-corpus evaluation: awesome-agent-harness top 5

Generated: 2026-06-26T17:08:36Z

Source list: <https://github.com/Picrew/awesome-agent-harness#harness-architecture--orchestration>

Fetch evidence: `artifacts/e2e/20260626170543-issue86-awesome-agent-harness-retry/source-list-fetch.json`

SourceBrief commit under test: `498ffc391484eba30b7c8356c2cf2e3619b32b03`

Evidence bundle: `artifacts/e2e/20260626170543-issue86-awesome-agent-harness-retry`

Manifest digest: `sha256:8b535a23cb0d4b8557b8a4505f5f58ffa65877c9fe7255a643486a51ee7559de`

Workspace: `1e5a774d-0f66-409c-af6c-923270d56a5e`
Project: `7a0932f4-17fd-4f8c-92ef-079f07126b5e`

## Scope

This run imported/evaluated the top 5 entries observed in the `Harness Architecture & Orchestration` table, sorted by rendered stars:

1. Superpowers — <https://github.com/obra/superpowers>
2. ECC — <https://github.com/affaan-m/ECC>
3. Matt Pocock Skills — <https://github.com/mattpocock/skills>
4. gstack — <https://github.com/garrytan/gstack>
5. DeerFlow — <https://github.com/bytedance/deer-flow>

The durable question bank is committed at `demo/awesome_agent_harness_50q/questions.json` with 50 questions total, 10 per repo.

## Import results

All five repositories were successfully imported after the runner added bounded retry for large repos. Every resulting corpus is marked `limited` because explicit import budgets were used and/or SourceBrief reported partial coverage warnings.

| Repo | Final attempt | Status | Import type | Files | Chunks | Symbols | Embeddings | Notes |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| Superpowers | wide-5000-files | succeeded | limited | 170 | 884 | 150 | 884 | explicit limited import budget |
| ECC | bounded-500-files | succeeded | limited | 500 | 1513 | 124 | 1513 | wide import exceeded chunk budget; bounded retry succeeded |
| Matt Pocock Skills | wide-5000-files | succeeded | limited | 84 | 184 | 0 | 184 | explicit limited import budget |
| gstack | bounded-500-files | succeeded | limited | 500 | 4688 | 1690 | 4688 | wide import exceeded chunk budget; bounded retry succeeded |
| DeerFlow | bounded-200-files | succeeded | limited | 200 | 1859 | 2237 | 1859 | wide and 500-file imports exceeded symbol budget; 200-file retry succeeded |

## Evaluation result

All 50 questions were run through SourceBrief after import.

```json
{
  "human_answer_demo_pass_rate": 0.9,
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

Why every question is `PARTIAL`: the run used explicit/automatic bounded imports, so evidence is intentionally partial. Positive questions had citations and passed the mechanical retrieval checks; negative controls retrieved evidence and therefore require human follow-up rather than being treated as clean abstentions.

## Product findings

### 1. Real-world import can exceed budgets and fail with no queryable partial snapshot

Opened child issue: #112.

First wide attempts failed for ECC, gstack, and DeerFlow with `max_chunks=5000` or `max_symbols=5000` budget errors and no current snapshot. The bounded retry path made the evaluation usable, but the product should not require the operator to infer safe retry budgets manually.

### 2. SourceBrief is credible for partial-corpus retrieval, but launch verdict remains RISK

For this corpus, SourceBrief produced cited context for all 50 questions once the imports were bounded. However, all imported corpora are partial, and negative-control questions still returned citations that need human interpretation rather than a clean abstention. This supports a launch-readiness verdict of `RISK`, not `PASS`.

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

- `imports/` — per-repo import attempts and index-run outcomes
- `eval-batches/` — `/retrieval-evals` payloads and responses
- `agent-context/` — per-question raw redacted context packets
- `eval-manifest.json` — resolved manifest with resource/snapshot IDs
- `eval-report.json` — schema-validated grading report
