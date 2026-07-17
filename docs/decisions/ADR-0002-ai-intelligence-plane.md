# ADR-0002: Preserve the evidence substrate and gate AI expansion behind a product proof

- Status: Proposed Phase 0 / Gate A decision; broad intelligence architecture not yet approved
- Date: 2026-07-17
- Decision horizon: two Gate A cycles, at most 20 working days after Eval v2 `D0`; later architecture requires a follow-on decision
- Umbrella: [#337](https://github.com/pingchesu/sourcebrief/issues/337)
- Product contract: [Core Product Reset](../CORE_PRODUCT_RESET.md)

## Context

SourceBrief has working source ingestion, snapshot, provenance, ACL, audit, review, API/MCP, Context Pack, packaging, and runtime-adapter capabilities. It does not yet deliver the intended intelligence outcome:

- default retrieval is development-quality hashing plus term overlap;
- the human answer path stitches first sentences from retrieved context;
- the graph is primarily structural;
- Resource Maps are deterministic evidence inventories;
- Skill Export is a deterministic template compiler with `llm_provider_used=false`;
- current real-corpus evaluation is RISK/PARTIAL rather than semantic-quality PASS.

The immediate decision is whether model-backed compilation improves one source-specific Hermes maintenance-task class enough to justify an AI product at all. Graph, generalized retrieval planning, generated answers, and broad source support are candidate follow-ons, not assumptions embedded in this decision.

## Goals

Necessary conditions:

1. Exact evidence provenance and tenant/resource scope.
2. Real model-backed knowledge compilation for AI-labeled features.
3. Visible failure with no silent fallback under a stronger label.
4. Versioned review, audit, reproducibility, and rollback.
5. Additive migration from current data and APIs.
6. A primary platform-engineer golden path with no raw IDs, at most one review action, and a measurable source-to-first-use budget.
7. A frozen Eval v2 contract before provider/compiler tuning, with deterministic, real-static, human-authored, and AI arms.

Weighted preferences:

| Preference | Weight |
| --- | ---: |
| Time to a falsifiable product proof | 5 |
| Reuse of verified substrate | 4 |
| Semantic quality ceiling | 5 |
| Reversibility | 4 |
| Operational simplicity | 3 |
| Clean reuse of OSS ideas/components | 2 |

## Options considered

Scores use 0 = poor, 1 = partial/uncertain, 2 = strong before weighting. These scores expose the assumptions behind the choice; they are not outcome evidence.

| Option | Time ×5 | Reuse ×4 | Quality ceiling ×5 | Reversibility ×4 | Ops ×3 | OSS ×2 | Total | Evidence / uncertainty |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Continue current incremental development | 2 | 2 | 0 | 2 | 2 | 0 | 32 | Fast, reversible, and simple, but current code is deterministic/template-driven and cannot test the AI claim. |
| Full rewrite around reference projects | 0 | 0 | 2 | 0 | 0 | 2 | 14 | High theoretical ceiling, but discards verified governance and requires a second control-plane build. |
| Preserve substrate; freeze Eval v2; run one bounded AI Skill experiment | 1 | 2 | 2 | 2 | 1 | 1 | 36 | Reuses verified substrate and is reversible. Quality=2 is a ceiling hypothesis; provider/eval/compiler work remains unproven. |
| Freeze as a deterministic cited-evidence service | 2 | 2 | 0 | 2 | 2 | 0 | 32 | Honest low-cost product and equal-status fallback; it does not test whether model compilation adds value. |

## Decision

Approve only:

1. Phase 0 truth adoption and chosen-Git-source evidence hardening;
2. Eval v2 freeze before candidate tuning;
3. the minimal typed provider/compiler/reference-pack work needed to execute Gate A;
4. the 20-working-day, two-cycle stop rule in the product contract.

Gate A uses the same Hermes runtime on 4 development tasks, 12 held-out repository-maintenance tasks, and 6 negative/security controls. It compares the current deterministic adapter, deterministic plus real static retrieval, a human-authored reviewed reference pack, and the AI-compiled reviewed reference pack. Exact task, quality, review-time, latency, cost, and stop thresholds are normative in [Core Product Reset §15](../CORE_PRODUCT_RESET.md#15-outcome-based-release-gates).

This ADR does **not** approve G1–G3 semantic graph publication, generalized evidence-closure retrieval, or generated-answer infrastructure. Those remain candidate designs. A Gate A PASS authorizes a new needs/evidence decision, not automatic construction of the whole candidate architecture.

If a follow-on decision is justified, candidate layers may include:

1. G0 Structural Evidence Graph.
2. G1 Semantic Candidate Graph.
3. G2 Reviewed Project Graph.
4. G3 Temporal Decision and Evaluation Graph.

Any AI-labeled capability still requires a healthy typed provider plane. Deterministic adapters remain available under an honest label. AI failure cannot corrupt or block G0 and cannot silently return deterministic output as AI-compiled.

## Consequences

### Positive

- Existing provenance, ACL, review, audit, and runtime delivery work remains useful.
- Intelligence can be benchmarked and failed independently of source ingestion.
- A provider/model change has explicit lineage, cost, and rollback.
- Product claims can be tied to actual capability states.
- Reference-project algorithms can be adopted cleanly without inheriting their control-plane limitations.

### Negative

- SourceBrief temporarily exposes an uncomfortable truth: several broad product labels describe deterministic or development-quality behavior.
- Eval v2, a minimal provider/compiler path, a deterministic control-plane pack, and review/economics receipts are required before value is known.
- Parallel semantic artifact versions are required only if a follow-on semantic capability is separately approved.
- Model cost, latency, provider availability, and prompt-injection risk become first-class operational concerns.
- Exact replay of a nondeterministic model response may be impossible; the system guarantees pinned execution lineage and retained hashes rather than byte-identical regeneration.

### Accepted trade-offs

- The first AI compiler is narrow and task-specific rather than universal.
- Deterministic artifacts remain first-class but no longer stand in for semantic output.
- PostgreSQL remains the graph store until measured traversal limits justify another database.
- Gate A permits at most one visible approval object, 10 minutes of active review, and 20 minutes source-to-first-use; governance that exceeds those limits fails the product gate.
- Semantic graph, generalized retrieval, and generated answers are explicitly deferred until task evidence demonstrates need.

## Rejected shortcuts

- Rename current template exports as AI-generated.
- Add a chat-completions call inside ingestion without typed claims/evidence lineage.
- Adopt one GraphRAG framework as the new system of record.
- Use an LLM judge as the sole promotion gate.
- Backfill old graphs/packs by changing labels in place.
- Treat provider health, graph size, citation count, file count, or HTTP success as intelligence proof.

## Reversibility

The AI plane is separately disableable. If it fails adoption gates:

- stop semantic compilation jobs;
- retain G0 structural evidence and cited MCP/API access;
- roll back G2 to the prior reviewed version;
- keep deterministic adapters installable;
- mark AI artifacts stale/unavailable;
- remove unsupported AI/semantic/GraphRAG/generated-skill product claims.

No destructive rewrite of existing snapshots, Context Packs, graphs, or Skill Exports is part of this decision.

## Operational ownership

- Platform/Data: evidence substrate, schemas, jobs, isolation, APIs, audit, rollback.
- AI/ML and Knowledge Engineering: provider policy, compiler, ontology, retrieval, answer/verifier quality.
- Product: user tasks, capability labels, first-use outcome.
- QA/Security: held-out gates, negative controls, promotion verdict, tenant/egress/injection/leakage tests.
- Operations: provider/runtime health, budget, canary, backfill, incident and rollback execution.

## Failure signals

1. Provider health is green but the AI arm misses any Gate A quality/economics threshold after two cycles or 20 working days after `D0`.
2. Graph/claim volume rises while reviewed precision, required-resource coverage, or answer support is flat or lower.
3. AI mode silently produces deterministic output or lacks provider/model/prompt/snapshot provenance.
4. Users still need raw internal IDs or multiple lifecycle objects before seeing source-specific value.
5. Semantic-worker failure blocks structural evidence access.
6. A launch report uses mechanical success to override RISK/PARTIAL semantic evidence.

## Revisit triggers

- AI arm succeeds on fewer than 9/12 tasks, gains fewer than 3 tasks over the better automated baseline, falls more than one task behind the human pack, or regresses more than one baseline-solved task after two cycles.
- Any of the six negative/security controls fails, exact evidence support fails, or nested identity metadata defeats blinding.
- Across any of three clean runs, compiler latency exceeds 15 minutes, source-to-first-use exceeds 20 minutes, active review exceeds 10 minutes or 50% of human-pack author-plus-review time, more than one approval object appears, or incremental compilation exceeds USD 5. Gate A reports all values/max; a later p95 claim requires at least 20 representative samples.
- Migration requires destructive reinterpretation of existing source truth.
- Tenant isolation, provider egress, or prompt-injection controls cannot be demonstrated.

If triggered, reconsider the product as a deterministic cited evidence backend rather than extending the AI program indefinitely.

## Bias check

- Sunk-cost bias: existing platform work is retained only where it passes the new outcome contract.
- Rewrite bias: declaring product failure does not make a full rewrite safer or more correct.
- New-model bias: provider novelty is not evidence of product quality.
- Familiarity bias: PostgreSQL and existing APIs remain only until measured evidence justifies replacement.
- Time-pressure bias: the reset prioritizes falsifiable narrow proof over a rushed universal compiler.
