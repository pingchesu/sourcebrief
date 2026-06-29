# EvoEmbedding temporal-memory eval fixture

This fixture is intentionally ordered. Questions in `eval_manifest.json` should cite the specific turn or event that proves the answer, not just any document containing a keyword.

## Thread timeline: EvoEmbedding adoption discussion

### turn-001 — User asks for EvoEmbedding research
Joe asks whether SourceBrief should study `MiG-NJU/EvoEmbedding` and whether it has adoption space.

### turn-002 — Initial assistant framing was too conservative
The initial framing overemphasized production-risk language and treated SourceBrief as if mature production embedding/rerank already existed.

### turn-003 — Corrected current retrieval baseline
Joe corrects the premise: SourceBrief currently has no real production embedding or rerank. Live provider health shows `hashing` / `sourcebrief-hashing-v1` and `term-overlap` / `sourcebrief-term-overlap-v1`, both `dev_quality=true`.

### turn-004 — EvoEmbedding model-family correction
Joe corrects model sizing: the EvoEmbedding family under consideration is `EvoEmbedding-0.8B`, `EvoEmbedding-2B`, and `EvoEmbedding-4B`. Qwen/30B is not the EvoEmbedding model family.

### turn-005 — Evaluator correction
Joe says the evaluator should be the current Hermes runtime. The evaluation should not require the EvoEmbedding repository's Qwen/30B evaluator setup.

### turn-006 — Evaluation-first correction
Joe asks why the evaluation design was not specified first, especially whether the existing 50 questions should be used.

### turn-007 — Issue-first instruction
Joe asks to open issues for the planned experiment before implementation.

### turn-008 — Issue stack created
Issues #195 through #200 are opened for EvoEmbedding Retrieval V2 evaluation: parent tracking, Hermes rubric, temporal-memory 50Q, profile-matrix runner, sidecar POC, and adoption decision.

### turn-009 — Start instruction
Joe says to start. The first implementation slice should be the evaluation plan and temporal-memory 50Q manifest, not model serving or schema migration.

## Retrieval V2 experiment decisions

### decision-001 — Correct decision question
The decision question is whether SourceBrief Retrieval V2 should include EvoEmbedding-style temporal/memory retrieval, and whether EvoEmbedding beats static embedding/rerank baselines on SourceBrief-owned evals while preserving citation safety.

### decision-002 — Existing 50Q role
The existing Awesome Agent Harness 50 questions are a general retrieval regression gate. They can detect wrong-repo contamination, unsupported claims, citation support failures, and ordinary repo/doc/code retrieval regressions. They are not sufficient final adoption evidence for EvoEmbedding.

### decision-003 — Temporal 50Q role
The temporal-memory 50Q is the adoption gate for EvoEmbedding-style retrieval. It must test ordered evidence such as first/latest, changed decisions, before/after timeline, review provenance, and self-improvement provenance.

### decision-004 — Hermes evaluator rule
Hermes evaluates only from the provided SourceBrief context and citations. Hermes must not use outside knowledge to rescue missing evidence.

### decision-005 — Static baseline requirement
A real static embedding baseline is required. Comparing EvoEmbedding only against hashing would over-credit EvoEmbedding for merely replacing a dev stub.

### decision-006 — Model matrix
The minimum Evo candidates are `EvoEmbedding-0.8B` and `EvoEmbedding-2B`; `EvoEmbedding-4B` is a quality upper bound if runtime resources permit.

### decision-007 — First integration shape
The first Evo integration shape is external batch rerank sidecar. It should not put Torch, Transformers, or flash-attn into SourceBrief API/web/worker core.

### decision-008 — Vector/schema deferral
Variable-dimension vector storage and multi-namespace chunk embeddings are deferred until rerank evidence justifies deeper vector integration.

### decision-009 — Privacy non-goal
Private source/query payloads must not be sent to unapproved external endpoints.

### decision-010 — Adoption outcomes
Possible outcomes are: adopt experimental `evo_temporal_rerank`, adopt only the temporal eval format, proceed to vector/schema v2, or reject model integration.

## Awesome Agent Harness 50Q run timeline

### eval-001 — Source list and top five repos
The Awesome Agent Harness run selected five public repos: Superpowers, ECC, Matt Pocock Skills, gstack, and DeerFlow.

### eval-002 — Wide import failures
Initial wide imports for ECC, gstack, and DeerFlow exceeded chunk or symbol budgets and did not leave queryable full snapshots.

### eval-003 — Bounded retry made eval usable
Bounded retry imports made the run usable, but the resulting corpora were marked limited or partial.

### eval-004 — Provider health is launch-risk evidence
The 50Q evidence bundle records provider health separately from mechanical API success. Development-quality providers force a RISK verdict unless explicitly overridden.

### eval-005 — Final 50Q result
The run had mechanical API success and retrieval quality pass rates, but all 50 rows were PARTIAL and the final verdict was RISK because corpora were limited and answer quality was not fully proven.

## Self-improvement provenance timeline

### improve-001 — Review bundle capture
A review bundle captures scoped prompts, retrieved citations, output, proof metadata, and completeness information before reviewer agents evaluate a run.

### improve-002 — Reviewer report
Reviewer agents produce reports with findings, severity, citation-support concerns, and evidence-linked rationales.

### improve-003 — Regression proposal
Eligible reviewer findings can become regression proposal artifacts. A proposal is reviewable evidence, not an automatic runtime mutation.

### improve-004 — Validation gate
The validation gate accepts or rejects a proposal deterministically before any staged adoption. Rejected proposals must not stage runtime changes.

### improve-005 — Staged adoption receipt
Accepted proposals may be staged as human-reviewable patches/receipts. Staged adoption writes receipts and reviewable artifacts without silently mutating production behavior.

### improve-006 — Sleep replay dry-run
The sleep/replay loop mines recurring proposal artifacts in dry-run mode. It can propose eval fixtures or follow-up work, but it must not auto-adopt runtime behavior.

### improve-007 — Citation support check
Citation-support checks detect unsupported claims and citation mismatches by comparing claims against cited evidence.

### improve-008 — Artifact security
Self-improvement artifacts use sensitivity classes, redaction, reviewer egress controls, retention rules, and purge contracts.

## False-premise guardrails

### guard-001 — Qwen/30B premise rejection
If a question claims Qwen/30B is the required evaluator, the correct answer is a cited "No": Hermes is the evaluator for SourceBrief adoption, and Qwen/30B is not the required evaluator.

### guard-002 — Default adoption premise rejection
If a question claims EvoEmbedding is already proven as default, the correct answer is a cited "No": adoption requires SourceBrief-owned eval gates to pass.

### guard-003 — Hashing production premise rejection
If a question claims hashing/term-overlap is production-grade retrieval, the correct answer is a cited "No": current provider health marks both as `dev_quality=true`.

### guard-004 — Paper benchmark premise rejection
If a question claims paper benchmark results prove SourceBrief citation correctness, the correct answer is a cited "No": SourceBrief must grade citation support on SourceBrief-owned evals.

### guard-005 — Static baseline skip premise rejection
If a question claims Evo can be compared only against hashing, the correct answer is a cited "No": a real static embedding baseline is required.

### guard-006 — External endpoint privacy premise rejection
If a question claims SourceBrief can send private corpora to any external Evo endpoint without approval, the correct answer is a cited "No": unapproved egress is a non-goal.

## True unanswerable controls

### unknown-001 — SOC2 claim
This fixture contains no signed SOC 2 Type II audit report and names no auditor.

### unknown-002 — GPU benchmark result
This fixture contains no measured latency, GPU memory, or p95 cost result for EvoEmbedding-0.8B, 2B, or 4B.

### unknown-003 — Adoption result
This fixture contains no completed A/B evidence bundle proving final adoption or rejection.

### unknown-004 — Secret endpoint
This fixture contains no approved production EvoEmbedding endpoint URL or credential.
