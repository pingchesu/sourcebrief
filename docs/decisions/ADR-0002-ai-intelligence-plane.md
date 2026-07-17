# ADR-0002: Preserve the evidence substrate and rebuild the AI intelligence plane

- Status: Proposed
- Date: 2026-07-17
- Decision horizon: 12 months, with bounded candidate-cycle revisit triggers
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

The decision is not whether AI should replace deterministic evidence. The decision is how to add real semantic compilation, retrieval planning, grounded answers, and source-specific packs without losing provenance, permissions, review, migration safety, and failure isolation.

## Goals

Necessary conditions:

1. Exact evidence provenance and tenant/resource scope.
2. Real model-backed knowledge compilation for AI-labeled features.
3. Visible failure with no silent fallback under a stronger label.
4. Versioned review, audit, reproducibility, and rollback.
5. Additive migration from current data and APIs.

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

Scores use 0 = poor, 1 = partial, 2 = strong before weighting.

| Option | Necessary-condition result | Weighted score | Exit cost |
| --- | --- | ---: | --- |
| Continue current incremental development | Rejected: fails real AI compilation and semantic truth. | 32 | Low, but preserves the wrong product. |
| Full rewrite around reference projects | Rejected: migration, tenancy, governance, and operational conditions are not met without rebuilding them. | 14 | Very high. |
| Preserve verified substrate; rebuild the intelligence plane | Passes. | 36 | Medium; bounded by additive versions and separate workers. |
| Freeze as a deterministic evidence backend | Rejected for the stated AI product goal; retained as fallback. | 32 | Low. |

## Decision

Preserve the verified deterministic Evidence Foundation and rebuild an explicit AI Intelligence Plane beside it.

The architecture has four knowledge layers:

1. G0 Structural Evidence Graph.
2. G1 Semantic Candidate Graph.
3. G2 Reviewed Project Graph.
4. G3 Temporal Decision and Evaluation Graph.

AI-labeled compilation and answer capabilities require a healthy typed provider plane. Deterministic adapters remain available under an honest label. AI failure cannot corrupt or block G0 and cannot silently return deterministic output as AI-compiled.

The rollout is additive:

- versioned AI execution records;
- candidate semantic artifacts;
- separate reviewed semantic graph versions;
- a new WEAVE retrieval profile;
- typed grounded answer claims;
- separate deterministic and AI-compiled pack modes;
- current data remains readable throughout migration.

## Consequences

### Positive

- Existing provenance, ACL, review, audit, and runtime delivery work remains useful.
- Intelligence can be benchmarked and failed independently of source ingestion.
- A provider/model change has explicit lineage, cost, and rollback.
- Product claims can be tied to actual capability states.
- Reference-project algorithms can be adopted cleanly without inheriting their control-plane limitations.

### Negative

- SourceBrief temporarily exposes an uncomfortable truth: several broad product labels describe deterministic or development-quality behavior.
- New schemas, workers, provider policy, review UI, evaluation, and operational ownership are required.
- The product will support parallel structural and semantic artifact versions during migration.
- Model cost, latency, provider availability, and prompt-injection risk become first-class operational concerns.
- Exact replay of a nondeterministic model response may be impossible; the system guarantees pinned execution lineage and retained hashes rather than byte-identical regeneration.

### Accepted trade-offs

- The first AI compiler is narrow and review-heavy rather than universal.
- Deterministic artifacts remain first-class but no longer stand in for semantic output.
- PostgreSQL remains the graph store until measured traversal limits justify another database.
- Human review remains a publish boundary even if it slows first-use flow; UX must hide internal plumbing without removing the boundary.

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

1. Provider health is green but two bounded candidate cycles fail to beat a real static baseline on held-out source-specific tasks.
2. Graph/claim volume rises while reviewed precision, required-resource coverage, or answer support is flat or lower.
3. AI mode silently produces deterministic output or lacks provider/model/prompt/snapshot provenance.
4. Users still need raw internal IDs or multiple lifecycle objects before seeing source-specific value.
5. Semantic-worker failure blocks structural evidence access.
6. A launch report uses mechanical success to override RISK/PARTIAL semantic evidence.

## Revisit triggers

- Two bounded AI compiler/retrieval candidate cycles fail the predeclared adoption gates.
- p95 cost or latency exceeds the declared product budget for two consecutive candidate runs without a quality advantage.
- Evidence closure or semantic relation precision cannot meet the predeclared threshold on the narrow initial corpus.
- Migration requires destructive reinterpretation of existing source truth.
- Tenant isolation, provider egress, or prompt-injection controls cannot be demonstrated.

If triggered, reconsider the product as a deterministic cited evidence backend rather than extending the AI program indefinitely.

## Bias check

- Sunk-cost bias: existing platform work is retained only where it passes the new outcome contract.
- Rewrite bias: declaring product failure does not make a full rewrite safer or more correct.
- New-model bias: provider novelty is not evidence of product quality.
- Familiarity bias: PostgreSQL and existing APIs remain only until measured evidence justifies replacement.
- Time-pressure bias: the reset prioritizes falsifiable narrow proof over a rushed universal compiler.
