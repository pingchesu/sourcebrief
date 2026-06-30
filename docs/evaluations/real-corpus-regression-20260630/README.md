# SourceBrief real-corpus regression (#214)

Issue: [#214](https://github.com/pingchesu/sourcebrief/issues/214)
Parent: [#208](https://github.com/pingchesu/sourcebrief/issues/208)
Run date: 2026-06-30
Candidate commit under test: `5e6ae69526d3db8b1f19103171062bd2b8480e81`

This directory contains the committed, redacted summary for the current-main real-corpus regression refresh. Raw local evidence remains under ignored `artifacts/e2e/` and includes request/response payloads, resource-ref proof, eval batches, agent-context packets, and run-environment captures.

## Predeclared plan

See [`RUN_PLAN.md`](RUN_PLAN.md). The plan was committed before canonical raw generation so the runner could record a clean source state.

## General 50Q gate: Awesome Agent Harness

Raw evidence bundle: `artifacts/e2e/214-20260630165524-awesome-agent-harness`
Committed summary: [`awesome-agent-harness-summary.redacted.json`](awesome-agent-harness-summary.redacted.json)

| Lane | Result |
| --- | --- |
| Question bank | `examples/awesome-agent-harness-50q/questions.json` |
| Questions accounted | 50/50 |
| Mechanical/API success | 1.0 |
| Retrieval/context quality | 1.0 |
| Wrong-resource citations | 0 |
| Unsupported final-answer claims | 0 |
| Grade counts | PASS 0 / PARTIAL 50 / FAIL 0 |
| Final verdict | **RISK** |

Why RISK instead of PASS:

- provider health is development-quality (`hashing` embedding + `term-overlap` rerank);
- all five imported repos are explicitly limited/partial;
- this proves answer-ready cited context, not a production synthesized answer layer.

Import scope:

| Repo | Status | Import type | Files | Chunks | Symbols | Notes |
| --- | --- | --- | ---: | ---: | ---: | --- |
| Superpowers | succeeded | limited | 170 | 884 | 150 | explicit limited import budget |
| ECC | succeeded | limited | 1526 | 5000 | 124 | chunk budget reached |
| Matt Pocock Skills | succeeded | limited | 89 | 199 | 0 | explicit limited import budget |
| gstack | succeeded | limited | 545 | 5000 | 1844 | chunk budget reached |
| DeerFlow | succeeded | limited | 673 | 5000 | 5000 | chunk and symbol budgets reached |

## Temporal-memory gate

Raw evidence bundle: `artifacts/e2e/214-20260630170300-temporal-memory`
Committed summary: [`temporal-memory-summary.redacted.json`](temporal-memory-summary.redacted.json)
Child issue: [#229](https://github.com/pingchesu/sourcebrief/issues/229)

The temporal fixture was bound to real local resources and executed through `scripts/run_profile_matrix_eval.py` using `current:hybrid`.

| Lane | Result |
| --- | --- |
| Manifest | `demo/evo_temporal_50q/eval_manifest.json` |
| Bound manifest digest | `sha256:ffa3cf481f480c68cc329fd77309743c198abcf7074d80a0aee8eecff7426b1c` |
| Profile | `current:hybrid` |
| Questions accounted | 50/50 |
| Preflight errors | 0 |
| Runtime errors | 0 |
| Passed / failed | 32 / 18 |
| Pass rate | 0.64 |
| Final verdict | **RISK** |

The run is useful evidence, but not temporal-memory adoption proof. Current `hybrid` missed required ordered/provenance evidence texts in 18 questions; #229 tracks that blocker.

## Launch impact

#214 is now a current evidence refresh, not a launch PASS. It improves confidence in mechanical execution and wrong-resource safety, but the launch train should keep real-corpus retrieval quality at **RISK** until production-quality provider evidence and/or temporal-memory improvements are available.
