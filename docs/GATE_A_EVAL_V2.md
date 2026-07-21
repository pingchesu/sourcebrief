# Gate A Eval v2 tooling

- Tracking issue: [#346](https://github.com/pingchesu/sourcebrief/issues/346)
- Product decision: [#337](https://github.com/pingchesu/sourcebrief/issues/337), ADR-0002
- Single-founder integrity decision: [#353](https://github.com/pingchesu/sourcebrief/issues/353), ADR-0003
- Reviewed product hypothesis: [#349](https://github.com/pingchesu/sourcebrief/issues/349)

Gate A is the first approved SourceBrief intelligence experiment. It tests one pinned Git repository, one repository-maintenance task class, four promotion arms, and six safety controls before any broader semantic graph, generalized retrieval, generated-answer, incident, or self-improvement work is authorized.

The tooling in `sourcebrief_shared.gate_a_eval` is deliberately fail-closed. It validates the experiment contract; it does not invent a corpus, owners, approval, or PASS report.

## Commands

Validate a manifest without authorizing candidate tuning:

```bash
.venv/bin/python scripts/eval_manifest.py validate-gate-a path/to/manifest.json
```

Validate a founder-controlled agent council without granting D0 or promotion authority:

```bash
.venv/bin/python scripts/eval_manifest.py validate-gate-a-internal-governance \
  path/to/internal-governance.json
```

A valid result is always `authorization=internal_signal_only`, `d0_ready=false`, and `promotion_authorized=false`. Workload agents cannot be substituted into human-owner or human-approver fields.

Validate a detached approval object's schema, commitments, projection digest, event window, and MAC integrity:

```bash
.venv/bin/python scripts/eval_manifest.py validate-gate-a \
  path/to/manifest.json \
  --approval path/to/approval.json \
  --approval-key-file /secure/path/gate-a-approval.key
```

This local result is `integrity_checked_external_authority_required`, with `d0_ready=false` and `promotion_authorized=false`. `--require-d0` intentionally fails until a protected external review service verifies human identities, per-principal acceptance, key custody, and replay/revocation state.

`unsigned_gate_a_compiler_projection()` remains available only for deterministic pre-registration and compile-receipt binding. There is deliberately no local compiler-input emission command: a future external-authority path or the separately versioned founder-controlled envelope in #354 must define one successful authorization boundary before compiler execution.

Validate a completed report by reading the authenticated receipt bundle and recomputing every referenced verifier-owned CAS artifact:

```bash
.venv/bin/python scripts/eval_manifest.py validate-gate-a-report \
  path/to/report.json \
  --manifest path/to/manifest.json \
  --approval path/to/approval.json \
  --approval-key-file /secure/path/gate-a-approval.key \
  --receipt-bundle /secure/path/receipt-bundle.json \
  --verifier-key-file /secure/path/gate-a-verifier.key \
  --artifact-root /secure/path/verifier-cas
```

## Contract enforced

- exact 4/12/6 development/held-out/control split, all fixed to the `repository-maintenance` task class;
- exact four promotion arms from ADR-0002, including fixed pack source, retrieval backend, and `source-and-development-only` compiler inputs;
- one direct-tools/no-SourceBrief diagnostic lane executed across the same 12 held-out tasks and 6 controls; it is included in the hard automated comparator set even though it is not a promotion arm;
- immutable pack-before-held-out rule for every arm, enforced by one self-digested freeze receipt per arm that predates the authenticated protected-material release clock;
- strict normative thresholds, budgets, cycle count, and stop clock;
- pinned candidate SourceBrief commit, scorer implementation digest, source commit/tree digest, and runtime/provider/model/prompt/compiler provenance;
- task-level expected resources, facets, evidence classes, and objective assertions;
- contamination-check declaration and unique task IDs/content fingerprints;
- versioned `independent_human` governance with typed stable human IDs; Eval/QA, provider/compiler, and Security identities must remain distinct, while agent/workload/service/team aliases are forbidden from human fields;
- detached approval bound to manifest/revision, owner-acceptance index, protected/public corpus commitments, hidden tests, GREEN/RED/contamination/preflight/runtime/challenge receipts, exact unsigned compiler projection, D0, issuer, key ID, nonce, sequence, validity window, actor, required human role signers, comment, and payload digest;
- an approval HMAC is an integrity MAC under one service key, not proof of multisigner consent or non-repudiation; the committed owner-acceptance index and protected review-service identity checks remain mandatory;
- recursive allowlist construction for pairwise evaluator context;
- strict JSON/object schemas, duplicate-key rejection, scalar type checks, and identity-value scanning, so unknown manifest/task fields or nested/scalar candidate metadata cannot cross the compiler/evaluator boundary;
- exact report rows for every held-out task/control in every arm;
- separate resource recall, facet coverage, claim support, citation correctness, and abstention metrics; every successful AI task requires complete support across all four evidence lanes;
- no PASS for a partial corpus, missing provenance, unsupported successful task, selective abstention below the task-success floor, missing controls, or exceeded review/cost/latency/retry budget.
- baseline regression is derived by task ID from the union of every co-best automated comparator, never from a candidate-supplied flag or hash-order tie break; non-finite JSON/numbers and out-of-window cycle reports fail closed.
- every held/control cell retains a complete typed tool trace, authenticated `changed_paths`, and command/diff bytes; all lanes permit pinned repository file/search/patch/write tools only through strict JSON relative-path operations, read/search cannot touch task `forbidden_paths`, patch/write and every changed path must stay inside task `allowed_paths`, authenticated `changed_paths` must exactly equal patch/write trace events, VCS/cache/output/control metadata paths and wildcard path scopes are rejected, command bytes for every lane use the same grammar, runner targets are limited to the task ID, `tests/`, or task allowed-path roots, and test/lint output/cache flags are prohibited; terminal execution is single-line shell-free explicit pytest/ruff/mypy through the exact pinned `python` token; the source sandbox is an archive without `.git`, and arbitrary modules, `python -c`, shell control syntax, absolute/parent/flag-value path escapes, and direct-lane SourceBrief/ContextSmith CLI/MCP operations fail before scoring;
- five per-lane self-digested sandbox receipts are bound into every held/control cell; every lane must attest to the exact pinned source tree, disabled egress, no external mounts, the frozen tool/terminal policy, and only its expected capability/reference-pack digest; the direct lane has neither capability nor reference pack, so file tools cannot stage product code from outside the repo-only execution boundary;
- the signed receipt bundle authenticates cycle/start/end/protected-release timestamps, one start/finish/economics record per clean compile repetition, one human-review worklog receipt, the exact semantic 90-cell randomized mapping with each held/control receipt bound to its blinded slot, per-arm freeze receipts, the frozen per-task hidden-test index, and exact result/control/compile rows; report clocks and rows must be byte-equivalent projections;
- every approval-bound evidence commitment, every one of the 103 canonical self-digested receipt payloads, and every referenced verifier/scorer implementation/policy, randomized mapping, pack, hidden test, command, complete tool trace, diff, stdout/stderr/output, compiler projection/response, human-review worklog, and failure-detail digest must resolve to a regular non-symlink CAS file whose raw bytes recompute to that digest; for self-digested JSON receipts the retained bytes are UTF-8 `canonical_json()` of the documented self-digest payload with the self-digest field omitted, not the complete pretty-printed receipt file;
- typed authenticated failure reasons must exactly equal the verifier-computed `(code, subject_type, subject_id)` set; task/control/compile failures bind every affected item, while global budget failures bind the run rather than an arbitrary task;
- held-out task success is derived as zero exit plus non-abstention, exact support, and complete resource/facet/claim/citation metrics; an exit-zero unsupported or abstaining answer is therefore retained and scored as task failure rather than forcing a false nonzero exit; contradictory signed metadata fails closed;
- the receipt manifest binds candidate/source/pack/provider/model/prompt/compiler/evaluator identities plus hidden-test, randomized-arm, task-result, latency/cost, failure-reason, and raw-bundle indexes; AI first-use/review use the maximum across all three clean attempts, total cost sums all three, and every aggregate must exactly recompute from per-attempt receipts.

## Single-founder internal mode and remaining product gate

Joe is the sole accountable human. Separate Product, Eval/QA, provider/compiler, runtime/provenance, Security, and audit agents may produce procedural challenge and error diversity, but they are founder-controlled workload identities. Shared UID, host administration, gateway, logs, backups, provider accounts, or model lineage are disclosed as correlated evidence—not independent custody or independent votes.

Before candidate tuning begins under **independent Gate A**, the real manifest still needs:

- the selected public or purpose-built non-sensitive repository and pinned commit;
- 4 development tasks, 12 held-out tasks, 6 controls, hidden tests, and contamination receipts;
- named and verified Product, Eval/QA, provider/compiler, runtime-pack, Security, and incident-escalation humans with content-addressed acceptance evidence; provider/compiler, Eval/QA, and Security remain separately accountable;
- newly authored protected material under separately controlled QA custody after candidate inputs freeze; the current LLM-reviewed draft is internal-only;
- a detached D0 approval from a protected review/signing service with non-exportable key custody and replay/revocation state;
- OS/account/key isolation for QA, broker, executor, verifier, and compiler workloads; same-UID modes are not custody;
- the actual Hermes/runtime/provider/model/compiler/prompt/policy identities and a hash-chained contamination ledger;
- all four immutable packs frozen before protected release, three retained compile repetitions with precommitted repetition 1, and one-task-at-a-time fresh executor cells;
- verifier-owned content-addressed raw receipts, retained output/test/pack bytes, release-side recomputation/replay, and an independent release verdict.

The report-v2 validator now authenticates the verifier bundle and recomputes every approval-bound evidence commitment plus all referenced retained CAS bytes before scoring. This proves integrity relative to the supplied verifier key and artifact store, but it still does **not** prove independent identity, non-exportable key custody, replay/revocation state, or external human authority. The local result is evidence integrity only and cannot claim independent Gate A PASS or authorize promotion.

A green validator means the declared experiment is internally consistent. It does not mean SourceBrief has passed Gate A or that any conditional intelligence architecture is approved. A valid single-founder internal-governance artifact remains `internal_signal_only`, even when every agent challenge passes.
