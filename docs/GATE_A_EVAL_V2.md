# Gate A Eval v2 tooling

- Tracking issue: [#346](https://github.com/pingchesu/sourcebrief/issues/346)
- Product decision: [#337](https://github.com/pingchesu/sourcebrief/issues/337), ADR-0002
- Reviewed product hypothesis: [#349](https://github.com/pingchesu/sourcebrief/issues/349)

Gate A is the first approved SourceBrief intelligence experiment. It tests one pinned Git repository, one repository-maintenance task class, four promotion arms, and six safety controls before any broader semantic graph, generalized retrieval, generated-answer, incident, or self-improvement work is authorized.

The tooling in `sourcebrief_shared.gate_a_eval` is deliberately fail-closed. It validates the experiment contract; it does not invent a corpus, owners, approval, or PASS report.

## Commands

Validate a manifest without authorizing candidate tuning:

```bash
.venv/bin/python scripts/eval_manifest.py validate-gate-a path/to/manifest.json
```

Validate the detached D0 approval and require that candidate tuning is authorized:

```bash
.venv/bin/python scripts/eval_manifest.py validate-gate-a \
  path/to/manifest.json \
  --approval path/to/approval.json \
  --approval-key-file /secure/path/gate-a-approval.key \
  --require-d0
```

Generate the only compiler-visible view:

```bash
.venv/bin/python scripts/eval_manifest.py prepare-gate-a-compiler-input \
  path/to/manifest.json \
  --approval path/to/approval.json \
  --approval-key-file /secure/path/gate-a-approval.key \
  --output /tmp/gate-a-compiler-input.json
```

The output contains the pinned source, runtime/compiler provenance, and four development tasks. It excludes held-out tasks, controls, hidden assertions, and expected outcomes.

Validate a completed report:

```bash
.venv/bin/python scripts/eval_manifest.py validate-gate-a-report \
  path/to/report.json \
  --manifest path/to/manifest.json \
  --approval path/to/approval.json \
  --approval-key-file /secure/path/gate-a-approval.key
```

## Contract enforced

- exact 4/12/6 development/held-out/control split, all fixed to the `repository-maintenance` task class;
- exact four promotion arms from ADR-0002, including fixed pack source, retrieval backend, and `source-and-development-only` compiler inputs;
- one declared direct-tools/no-SourceBrief diagnostic baseline;
- immutable pack-before-held-out rule for every arm;
- strict normative thresholds, budgets, cycle count, and stop clock;
- pinned source commit/tree digest and runtime/provider/model/prompt/compiler provenance;
- task-level expected resources, facets, evidence classes, and objective assertions;
- contamination-check declaration and unique task IDs/content fingerprints;
- detached content-addressed approval bound to manifest digest/revision and D0, with a server-held HMAC attestation key, immutable approval-event ID, actor, signers, comment, time, and payload hash;
- named owner roles, with provider/compiler ownership separated from Eval/QA authority;
- recursive allowlist construction for pairwise evaluator context;
- strict JSON/object schemas, duplicate-key rejection, scalar type checks, and identity-value scanning, so unknown manifest/task fields or nested/scalar candidate metadata cannot cross the compiler/evaluator boundary;
- exact report rows for every held-out task/control in every arm;
- separate resource recall, facet coverage, claim support, citation correctness, and abstention metrics; every successful AI task requires complete support across all four evidence lanes;
- no PASS for a partial corpus, missing provenance, unsupported successful task, selective abstention below the task-success floor, missing controls, or exceeded review/cost/latency/retry budget.
- baseline regression is derived by task ID from the better automated arm instead of trusting a candidate-supplied flag; non-finite JSON/numbers and out-of-window cycle reports fail closed.
- the receipt manifest binds candidate/source/pack/provider/model/prompt/compiler/evaluator identities plus randomized-arm, task-result, latency/cost, failure-reason, and raw-bundle indexes; latency/cost evidence must cover all three clean compile repetitions.

## What remains a human/product gate

Before candidate tuning begins, the real manifest still needs:

- the selected public or purpose-built non-sensitive repository and pinned commit;
- 4 development tasks, 12 held-out tasks, 6 controls, hidden tests, and contamination receipts;
- named Product, Eval/QA, provider/compiler, runtime-pack, Security, and incident-escalation owners;
- a detached human approval at D0;
- a protected approval-service HMAC key (never committed or embedded in the manifest/report);
- the actual Hermes/runtime/provider/model/compiler identities;
- retained redacted receipts and an independent release verdict.

A green validator means the declared experiment is internally consistent. It does not mean SourceBrief has passed Gate A or that any conditional intelligence architecture is approved.
