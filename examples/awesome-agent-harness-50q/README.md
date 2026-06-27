# Awesome Agent Harness 50-question example

This example shows a real SourceBrief launch-readiness evaluation shape: five public agent-harness repositories, a fixed 50-question bank, bounded imports, and a redacted result summary.

It is intentionally honest about the result. SourceBrief produced cited, answer-ready context for every question, but the run was still graded **RISK** because all imported corpora were limited/partial and the runner did not yet synthesize polished end-user answers.

## Repos

The corpus was selected from the `Harness Architecture & Orchestration` table in [`Picrew/awesome-agent-harness`](https://github.com/Picrew/awesome-agent-harness#harness-architecture--orchestration), sorted by rendered stars at selection time:

| Repo | URL | Import result |
| --- | --- | --- |
| Superpowers | <https://github.com/obra/superpowers> | limited import succeeded |
| ECC | <https://github.com/affaan-m/ECC> | wide import exceeded budget; bounded retry succeeded |
| Matt Pocock Skills | <https://github.com/mattpocock/skills> | limited import succeeded |
| gstack | <https://github.com/garrytan/gstack> | wide import exceeded budget; bounded retry succeeded |
| DeerFlow | <https://github.com/bytedance/deer-flow> | wide/500-file import exceeded budget; 200-file retry succeeded |

## Included files

- [`questions.json`](questions.json) — the full 50-question bank, including expected evidence type and bad-answer criteria.
- [`../../docs/evaluations/awesome-agent-harness-50q-20260626.md`](../../docs/evaluations/awesome-agent-harness-50q-20260626.md) — the committed evaluation report and reproduction notes.

## Final result from the recorded run

```json
{
  "mechanical_api_success_rate": 1.0,
  "retrieval_quality_pass_rate": 1.0,
  "human_answer_demo_pass_rate": 0.0,
  "unsupported_claim_failures": 0,
  "wrong_repo_failures": 0,
  "verdict": "RISK"
}
```

Grade counts:

```json
{
  "PASS": 0,
  "PARTIAL": 50,
  "FAIL": 0
}
```

Why every question was `PARTIAL`:

- every imported repo was partial/limited;
- SourceBrief generated cited context, but this runner proved answer-ready context rather than final synthesized answers;
- negative controls still returned scoped context/citations that need a clean abstention layer.

## Reproduce locally

Start the local stack first:

```bash
cp .env.example .env
# Set SOURCEBRIEF_ADMIN_PASSWORD to a local password before startup.
make compose-up
make quickstart-ready
```

Run the eval with session-login auth or a token:

```bash
API_URL="$(make -s print-api-url)"
WEB_URL="$(make -s print-web-url)"
STAMP="$(date -u +%Y%m%d%H%M%S)"

SOURCEBRIEF_API_URL="$API_URL" SOURCEBRIEF_WEB_URL="$WEB_URL" \
  .venv/bin/python scripts/run_awesome_agent_harness_eval.py \
  --api-url "$API_URL" \
  --web-url "$WEB_URL" \
  --output-dir "artifacts/e2e/${STAMP}-awesome-agent-harness" \
  --slug "awesome-agent-harness-${STAMP}" \
  --index-timeout 900
```

Authentication options, in preferred order:

1. `SOURCEBRIEF_ADMIN_EMAIL` + `SOURCEBRIEF_ADMIN_PASSWORD` from `.env` for session login.
2. `SOURCEBRIEF_TOKEN` for a bearer/session token.
3. `SOURCEBRIEF_DEV_AUTH=true` only for disposable local development header-auth experiments.

The runner writes redacted raw evidence under the output directory: imports, index runs, resource-ref proof, eval batches, agent-context packets, resolved eval manifest, and grade report.

## What this example teaches

- Real repos hit budgets; examples must show bounded retries and partial-corpus caveats.
- Mechanical API success is not the same as launch-quality answer quality.
- Public demos should commit reproducible question banks and summaries, not raw private evidence bundles.
- A stronger next milestone is a synthesized answer layer that can turn cited context into concise end-user answers and clean abstentions.
