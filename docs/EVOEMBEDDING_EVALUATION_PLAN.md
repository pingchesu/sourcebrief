# EvoEmbedding Retrieval V2 evaluation plan

SourceBrief currently uses development-quality retrieval providers in the local stack:

- embedding: `hashing` / `sourcebrief-hashing-v1` / 64 dimensions
- rerank: `term-overlap` / `sourcebrief-term-overlap-v1`

This plan evaluates whether EvoEmbedding should influence SourceBrief Retrieval V2. It does **not** assume SourceBrief already has production-grade embedding/rerank, and it does **not** require the EvoEmbedding repository's Qwen/30B evaluator setup. The evaluator for SourceBrief adoption is the current Hermes runtime, because the product question is whether Hermes receives better cited context from SourceBrief.

Tracking issue: [#195](https://github.com/pingchesu/sourcebrief/issues/195).

## Decision question

> Should SourceBrief Retrieval V2 include EvoEmbedding-style temporal/memory retrieval, and does EvoEmbedding beat static embedding/rerank baselines on SourceBrief-owned evals while preserving citation safety?

The answer must come from replayable SourceBrief evidence, not from paper/project-page claims.

## Current decision after #195/#200 evidence

EvoEmbedding-4B is **not** adopted as a plug-and-play replacement for the current provider path. The completed evidence showed a strong 4B rank-only signal in a 50-candidate reranker-sensitive benchmark, but the section-level integrated POC did not improve final answer/context pass rate (`current=39/50`, `evo4b=38/50`).

The next implementation path is therefore a default-off Retrieval V2 experiment: retrieve a larger first-stage candidate pool, apply batch rerank as a second-stage selector, preserve pre/post/final-inclusion diagnostics, and tune final selection for multi-evidence questions. See #204.

## Eval sets

### A. General retrieval gate: existing Awesome Agent Harness 50Q

Reuse the existing 50-question Awesome Agent Harness corpus as the first gate.

Purpose:

- prove ordinary repo/doc/code retrieval does not regress;
- catch wrong-repo contamination;
- catch unsupported claims and weak citation support;
- compare current hashing/term-overlap with real static embedding and Evo rerank candidates.

This gate is necessary but not sufficient. It is not designed around EvoEmbedding's core temporal-memory claim.

### B. Temporal-memory gate: Evo temporal 50Q

Add [`../demo/evo_temporal_50q/eval_manifest.json`](../demo/evo_temporal_50q/eval_manifest.json) and its ordered fixture [`../demo/evo_temporal_50q/temporal_fixture.md`](../demo/evo_temporal_50q/temporal_fixture.md) as the second gate.

Purpose:

- first/last/latest temporal retrieval;
- changed-decision and preference-drift reasoning;
- incident/rollout timeline retrieval;
- PR review provenance;
- self-improvement review-bundle provenance;
- false-premise controls that require cited “No” answers, plus true unanswerable controls for absent evidence.

This is the adoption gate for EvoEmbedding-style retrieval.

## Profile matrix

The exact profile config files are owned by the runner/sidecar follow-up issues. This plan records the comparison matrix and decision gates; #198/#199 must pin model endpoints, batch scoring behavior, latency budgets, and provider namespaces before running adoption evidence.

Minimum profiles:

| ID | Profile | Purpose |
| --- | --- | --- |
| P0 | current hashing + term-overlap hybrid | current-state dev baseline |
| P1 | current graph profile | graph/lexical current-state baseline |
| P2 | real static embedding hybrid | baseline that avoids over-crediting Evo for merely replacing hashing |
| P3 | static embedding + batch rerank | isolates normal rerank benefit |
| P4 | EvoEmbedding-0.8B batch rerank | smallest Evo candidate |
| P5 | EvoEmbedding-2B batch rerank | medium Evo candidate |
| P6 | EvoEmbedding-4B batch rerank | quality upper bound if runtime budget allows |

Qwen/30B is not part of the required model matrix. It appeared in the EvoEmbedding repo's evaluation scripts as a generator/evaluator path, not as the EvoEmbedding model family under SourceBrief consideration.

## Run flow

For each `{eval_set, profile}` pair:

1. Capture provider health and profile config.
2. Run `/retrieval-evals` in max-10 question batches.
3. Run `/agent-context` for answer-ready cited context.
4. Grade each output with Hermes using the rubric below.
5. Run blind pairwise grading against the static baseline where possible.
6. Persist redacted evidence and aggregate metrics.

Evidence bundle convention:

```text
artifacts/evals/<run-id>/
  manifest-general.json
  manifest-temporal.json
  manifest-summary.json
  provider-health.json
  profile-configs/*.json
  retrieval-evals/<profile>/*.json
  agent-context/<profile>/*.json
  hermes-grades/<profile>/*.json
  pairwise/<candidate-vs-baseline>/*.json
  aggregate-report.json
  run-environment.json
```

Do not persist tokens, session cookies, private URLs, or unredacted source/query payloads in documentation-facing artifacts.

## Hermes evaluator rubric

Hermes grades only from the provided SourceBrief context and citations. The evaluator must not use outside knowledge to rescue missing evidence.

Required per-question JSON:

```json
{
  "question_id": "...",
  "profile": "...",
  "answer_correct": "pass|partial|fail",
  "citation_supported": "pass|partial|fail",
  "missing_evidence": true,
  "wrong_resource": false,
  "unsupported_claim": false,
  "abstention_correct": true,
  "usefulness": 1,
  "better_than_baseline": "better|same|worse|not_compared",
  "supporting_citation_ids": [],
  "failure_reasons": [],
  "rationale": "..."
}
```

Pairwise comparison must blind-shuffle baseline/candidate output and choose one of:

- `A_better`
- `B_better`
- `tie`
- `both_fail`

The profile identity is decoded only after the judgment is recorded.

## Gates

### General 50Q hard gates

- `mechanical_api_success_rate == 1.0`
- `wrong_repo_failures == 0`
- `unsupported_claim_failures == 0`
- citation support does not regress against static baseline
- retrieval quality is not worse than static baseline beyond a small tolerance

Passing this gate means a candidate is safe to continue evaluating. It does not prove EvoEmbedding should be adopted.

### Temporal 50Q adoption gates

- Hermes pairwise win rate vs static baseline >= 60%, excluding ties
- temporal retrieval pass rate improves materially: target +15 percentage points absolute or +25% relative
- negative controls pass
- citation correctness does not regress
- latency/cost/failure behavior is documented

## Outcomes

- **Adopt experimental `evo_temporal_rerank` profile** when temporal gains are meaningful and safety gates pass.
- **Adopt only the eval format / temporal manifest** when model gains are weak but the benchmark itself is useful.
- **Proceed to vector/schema v2** only if rerank POC justifies deeper embedding integration.
- **Reject model integration** if Evo fails general safety gates or does not beat static baselines.

## Non-goals

- Do not reproduce the EvoEmbedding paper benchmark.
- Do not use Qwen/30B as required evaluator.
- Do not make EvoEmbedding default before SourceBrief-owned evals pass.
- Do not model answerable false-premise questions as unanswerable; answer them with cited negative evidence.
- Do not treat current hashing/term-overlap as a production baseline.
- Do not send private source/query data to unapproved external endpoints.
