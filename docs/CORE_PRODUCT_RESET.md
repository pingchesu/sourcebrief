# SourceBrief Core Product Reset

- Status: Proposed product contract
- Umbrella: [#337](https://github.com/pingchesu/sourcebrief/issues/337)
- Contract slice: [#338](https://github.com/pingchesu/sourcebrief/issues/338)
- Decision record: [ADR-0002](decisions/ADR-0002-ai-intelligence-plane.md)
- Owner: SourceBrief platform, AI/ML, Product, and QA

## 1. Executive decision

SourceBrief's product development has failed against its intended intelligence outcome.

The repository contains substantial working platform machinery: versioned source snapshots, provenance, tenant and token scope, audit, review lifecycle, API/MCP delivery, Context Pack versions, package validation, runtime adapters, and local real-service QA. Those capabilities are useful, but they were allowed to look like completion of a different product promise:

> SourceBrief understands heterogeneous project sources, builds useful cross-resource knowledge, answers with grounded reasoning, and produces genuinely source-specific skills and agents.

That promise is not currently shipped.

This reset makes one decision:

> Preserve only the verified evidence and governance substrate. Rebuild the intelligence plane as an explicit, typed, provider-backed, evidence-verified system. No deterministic or mechanical fallback may retain an AI, semantic, GraphRAG, or generated-knowledge label.

The reset is not a cosmetic rename and not a full repository rewrite. It changes the product's completion criteria from **plumbing exists** to **the user receives correct, source-specific, evidence-verifiable knowledge**.

## 2. Problem brief

### One-sentence problem

When a user connects repositories, documents, books, and runbooks expecting SourceBrief to understand the project, the product can produce indexed records, citations, graphs, answer-shaped text, and installable packages without having performed the semantic work those surfaces imply, causing false confidence and a product that passes mechanical gates while missing its core user outcome.

### Verified current state

| Surface | Current implementation truth | Evidence |
| --- | --- | --- |
| Retrieval defaults | Hashing embeddings and term-overlap reranking; explicitly development-quality. | `.env.example`, `packages/shared/sourcebrief_shared/embeddings.py` |
| Human answer | `extractive_synthesis` selects the first usable sentence from up to three context entries. | `apps/api/sourcebrief_api/services/agent_context_runtime.py` |
| Resource Map | Deterministic file/section inventory, previews, counts, hashes, and citations. | `apps/api/sourcebrief_api/resource_map.py` |
| Resource graph | Resource/file/symbol structural graph; useful evidence, not a reviewed semantic concept graph. | `packages/shared/sourcebrief_shared/graph_index.py`, `docs/ARCHITECTURE.md` |
| Context Pack | A reviewed, versioned selection of context artifacts and source coverage. It is not semantic synthesis by itself. | `apps/api/sourcebrief_api/context_packs.py` |
| Skill Export | Template-driven package compiler. Manifest records `llm_provider_used=false` and future `section_aware_map_reduce`. | `apps/api/sourcebrief_api/skill_exports.py` |
| Self-improvement | Review bundles, proposals, gates, and receipts; no autonomous optimizer or model-backed learning contract. | `docs/SELF_IMPROVEMENT.md`, `docs/STATUS.md` |
| Evaluation | Real mechanical evidence exists, but the claim ledger marks real-corpus quality RISK/PARTIAL and providers development-quality. | `docs/CLAIM_LEDGER.md`, `docs/evaluations/` |

### Target state

A user connects versioned sources and receives:

1. a provenance-complete deterministic evidence foundation;
2. AI-compiled semantic claims, concepts, decisions, procedures, risks, and relationships;
3. a reviewed cross-resource project graph;
4. query plans that know which resources, facets, evidence classes, and freshness are required;
5. answers whose individual claims resolve to exact source evidence;
6. Agent/Skill Packs whose source-specific knowledge was actually compiled and reviewed;
7. capability, cost, latency, coverage, freshness, and failure state visible to users and operators;
8. evaluation results that measure task outcomes rather than artifact volume.

## 3. Why this is the root problem

1. Package generation was mistaken for knowledge compilation.
2. Citation presence was mistaken for claim support.
3. File/symbol graph volume was mistaken for semantic relationship quality.
4. HTTP success and 50/50 execution were mistaken for answer quality.
5. Provider abstraction was mistaken for a working AI plane.
6. Review workflow mechanics were mistaken for self-improvement.
7. UI breadth was mistaken for first-use value.

The root problem is therefore not a missing button or one weak model. It is the absence of a product-wide contract that distinguishes **evidence mechanics**, **AI intelligence**, **human review**, and **published truth**.

## 4. Product outcome and non-goals

### North-star outcome

> An authorized agent or human can ask a cross-resource project question and receive a useful answer whose claims, relationships, limitations, freshness, and source evidence can be inspected and reproduced; the same reviewed knowledge can be compiled into a genuinely source-specific runtime pack.

### Necessary conditions

A candidate architecture is rejected if it cannot provide all of the following:

1. exact source provenance and tenant scope;
2. real AI knowledge compilation for AI-labeled capabilities;
3. visible failure and no silent semantic fallback;
4. review, version, rollback, and reproducibility boundaries;
5. additive migration from existing SourceBrief data and APIs.

### Non-goals

- SourceBrief is not an autonomous coding or production-mutation agent.
- AI-generated content is never source truth merely because a model produced it.
- Structural indexing does not require an LLM and must remain useful when the AI plane is disabled.
- Full source corpora, embeddings, or graph indexes are not copied into runtime packs by default.
- No graph database migration is approved until PostgreSQL traversal limits are measured.
- No third-party reference repository is copied wholesale into SourceBrief.
- No self-improvement process may silently modify prompts, skills, graph truth, runtime config, or production code.

## 5. Canonical capability truth dimensions

Generation method, review, coverage, freshness, serving availability, and execution state are orthogonal. A reviewed AI artifact can still be partial and stale; a failed recompile can coexist with a degraded but available previous version. Every API response, artifact, UI surface, manifest, claim ledger row, and evaluation report that describes product intelligence must expose all applicable dimensions rather than forcing them into one status enum.

| Dimension | Initial values | Meaning |
| --- | --- | --- |
| `generation_method` | `structural`, `deterministic`, `ai_compiled` | How the content or relationship was produced. |
| `review_state` | `unreviewed`, `in_review`, `approved`, `rejected` | Whether an authorized reviewer accepted the exact artifact/version. |
| `coverage_state` | `full`, `partial`, `unknown` | Whether required resources, sections, facets, and evidence classes are represented. |
| `freshness_state` | `current`, `stale`, `invalidated` | Whether source/provider/policy/compiler changes supersede the artifact. |
| `availability_state` | `available`, `degraded`, `unavailable` | Whether the capability can serve this request now. |
| `execution_state` | `not_started`, `queued`, `running`, `succeeded`, `failed`, `cancelled` | State of a specific compile/query/publish attempt. |

Forbidden dimension collapse:

- `generation_method=deterministic` must never be emitted as `ai_compiled`.
- `generation_method=ai_compiled` must never imply `review_state=approved` without an approval event.
- `coverage_state=partial` must never become `full` because `top_k` was filled.
- `freshness_state=stale` must never be hidden by returning an older semantic artifact as current.
- `execution_state=failed` must never silently return a lower-quality artifact under the requested compilation label; serving an older version requires `availability_state=degraded` plus explicit stale/version metadata.

## 6. Core feature redefinition

### 6.1 Source ingestion becomes the Evidence Foundation

**Purpose:** preserve exact, authorized, versioned evidence for every later intelligence operation.

Required outputs:

- resource and immutable snapshot identity;
- files/documents and retained sections;
- a declared source-type capability matrix for Git/text/Markdown/HTML/PDF/Office/image inputs, with unsupported formats rejected visibly rather than sent as opaque binary to a model;
- headings, pages, tables, bounding boxes, OCR confidence, and parser warnings where the source format supports them;
- chunks and exact evidence locators;
- explicit structure: symbols, imports, calls, tests, config, deployment, data/event declarations, document links;
- extraction-policy fingerprint and extractor version;
- full/partial/skipped/failed coverage;
- freshness and invalidation state.

Done means:

- every evidence item resolves back to a pinned snapshot and exact source region;
- a budget-limited or parser-limited import is visible as partial;
- tenant/resource scope is preserved across every derived artifact;
- structural indexing remains usable with every AI provider disabled.

Failure control:

> A node or edge without evidence, scope, extractor identity, and freshness cannot enter the Evidence Foundation.

Ownership: Platform/Data.

Child: [#339](https://github.com/pingchesu/sourcebrief/issues/339).

### 6.2 AI Provider Plane becomes a real product subsystem

**Purpose:** provide typed, observable, bounded model execution for compiler and answer workloads.

Required contracts:

- strict provider request/response types;
- provider, model, deployment, prompt/extractor version;
- output-schema, tool, sampling, and decoding parameters;
- immutable input snapshot/section hashes;
- canonical source hashes plus the redacted model-input view hash and transform version;
- attempt, retry, cancellation, timeout, idempotency, and terminal status;
- token, cost, latency, and cache identity;
- egress, credential, retention, and redaction policy;
- provider health and model provenance.

Compilation-mode rule:

```text
deterministic-adapter requested -> no LLM required, honest deterministic output
ai-compiled requested           -> healthy configured AI provider required
```

If the second path cannot run, it returns `unavailable` or `failed`. It does not produce deterministic output under an AI label.

Model APIs may be nondeterministic. Reproducibility means pinned inputs and execution configuration, retained request/response hashes, auditable lineage, and cache identity—not a false promise of byte-identical regeneration.

AI compilation and answer jobs use dedicated queues, concurrency limits, quotas, and circuit breakers so provider saturation cannot starve source refresh, structural indexing, evidence reads, or rollback operations.

Ownership: AI/ML for model policy and quality; Platform for execution, persistence, isolation, and APIs.

Child: [#340](https://github.com/pingchesu/sourcebrief/issues/340).

### 6.3 AI Knowledge Compiler replaces template-as-intelligence

**Purpose:** convert source sections into source-specific, reviewable semantic knowledge.

Pipeline:

```text
pinned Context Pack / section set
    -> section selection and coverage plan
    -> bounded parallel map
    -> typed evidence claims
    -> cross-section reduce/reconcile
    -> contradiction and duplicate handling
    -> citation/evidence verification
    -> reviewable semantic artifact
```

Minimum typed claim:

```json
{
  "claim_id": "stable-id",
  "claim_type": "concept | decision | rationale | owner | procedure | pattern | pitfall | glossary | playbook_step | risk",
  "claim_text": "source-specific statement",
  "citation_ids": ["retained-citation-id"],
  "evidence_spans": [
    {
      "citation_id": "retained-citation-id",
      "quote_hash": "sha256:hash-of-exact-supporting-span"
    }
  ],
  "support_state": "candidate",
  "confidence": 0.0,
  "model": "provider/model",
  "prompt_version": "compiler.prompt.v1",
  "extractor_version": "knowledge-compiler.v1",
  "review_state": "candidate"
}
```

Rules:

- source-specific claims require citations;
- unknown citation IDs fail validation;
- citation-ID presence alone is not support: exact evidence spans and a support decision are separate typed records;
- per-section quotas prevent late-source starvation;
- changed sections invalidate only affected compiled claims;
- model output is untrusted typed input and must pass schema, evidence, leakage, and policy checks;
- no candidate is published directly.

Ownership: AI/ML and Knowledge Engineering; Platform owns immutable lineage and review lifecycle.

Child: [#341](https://github.com/pingchesu/sourcebrief/issues/341).

### 6.4 Graph is split into four named layers

| Layer | Name | Contents | Truth policy |
| --- | --- | --- | --- |
| G0 | Structural Evidence Graph | Resource, file, section, symbol, explicit config/deployment/data/event relationships. | Deterministic/observed. |
| G1 | Semantic Candidate Graph | AI-extracted concepts, decisions, owners, procedures, risks, flows, candidate entity links. | Candidate; evidence required. |
| G2 | Reviewed Project Graph | Approved union/overlay/reconcile across resources; conflicts and communities. | Published reviewed knowledge. |
| G3 | Temporal Decision and Evaluation Graph | Decisions, incidents, corrections, evaluation failures, proposal lineage. | Time/version bounded; never rewrites source truth. |

Every semantic node/edge carries:

- evidence locators;
- relation type from a versioned ontology;
- source class: explicit, AI-extracted, inferred, human-approved;
- confidence;
- model/extractor version;
- valid time and freshness;
- review state.

A name match is not sufficient for entity resolution. Inferred edges cannot satisfy high-assurance questions until reviewed.

Model-reported confidence is advisory unless calibrated against a pinned labeled set. Uncalibrated confidence cannot satisfy a trust gate or replace evidence/review.

Semantic compilation failure marks G1/G2 stale or unavailable while G0 remains queryable.

Ownership: Knowledge Engineering and Platform.

Child: [#342](https://github.com/pingchesu/sourcebrief/issues/342).

### 6.5 Retrieval becomes WEAVE

WEAVE means **Provenance-Gated Adaptive Graph Retrieval**.

A query first produces a typed plan:

```json
{
  "intent": "architecture | code | operations | decision | comparison | procedure | change_impact",
  "facets": ["required answer dimensions"],
  "allowed_resources": ["resource refs"],
  "required_resources": ["resource refs"],
  "required_evidence_classes": ["structural", "reviewed_semantic", "live"],
  "freshness": "policy",
  "risk": "normal | high_assurance",
  "token_budget": 8000
}
```

Retrieval channels may include:

- exact identifier/path;
- lexical;
- real dense embedding;
- symbol/code;
- structural graph;
- reviewed semantic graph;
- community/global summaries;
- temporal evidence;
- live external evidence where authorized.

Channels return ranks and typed diagnostics. Fusion uses normalized rank fusion such as intent-conditioned RRF, not silent addition of incomparable raw scores.

Selection order:

1. ACL and freshness gate;
2. multi-channel candidate collection;
3. normalized fusion;
4. trust-gated graph expansion;
5. facet/resource/claim reranking;
6. diversity and evidence set cover;
7. evidence closure;
8. targeted follow-up, partial result, or abstention.

Done means:

- required-resource and facet coverage are machine-readable;
- low-trust evidence cannot satisfy high-assurance facets;
- missing evidence produces a targeted next query;
- negative controls do not gain false support from weak overlap;
- diagnostics explain why each evidence item was selected.

Ownership: Retrieval/AI and Platform.

Child: [#343](https://github.com/pingchesu/sourcebrief/issues/343).

### 6.6 Answers become claim-verified products

The evidence packet and the generated answer are separate artifacts.

Answer claim contract:

```json
{
  "claim_id": "answer-claim-id",
  "text": "human-readable claim",
  "kind": "quote | paraphrase | synthesis | inference | conflict | unknown",
  "citation_ids": ["citation-id"],
  "support": "verified | partial | unsupported | conflicting",
  "support_methods": ["deterministic_span", "human_review"],
  "confidence": 0.0
}
```

Rules:

- every answer sentence maps to one or more answer claims;
- each claim maps to exact evidence;
- `verified` requires a declared support policy; a citation label or an unreviewed generator/verifier agreement is insufficient;
- contradictions remain visible;
- false-premise and insufficient-evidence questions abstain;
- provider failure may still return the evidence packet, but answer state is `unavailable`;
- deterministic first-sentence extraction remains only as `extractive_preview` for debugging, never as grounded synthesis.

Ownership: AI/ML for generator/verifier quality; Platform for typed contracts and policy.

Child: [#344](https://github.com/pingchesu/sourcebrief/issues/344).

### 6.7 Resource Map, Context Pack, Agent Pack, and Skill Export are separated

| Artifact | New definition |
| --- | --- |
| Resource Map | Deterministic evidence/navigation inventory. It does not claim semantic understanding. |
| Context Pack | Immutable reviewed selection and coverage boundary for evidence and semantic artifacts. |
| Deterministic Adapter | Thin runtime instructions, MCP selectors, citation policy, manifests, smoke queries, and validation. No AI claim. |
| AI-Compiled Skill Pack | Reviewed source-specific glossary, concepts, patterns, pitfalls, procedures, routes, and playbooks derived by the AI Knowledge Compiler. |
| Repo/Project Agent | User-facing runtime view over selected evidence, reviewed knowledge, capability state, and operating policy. |

Package manifests must expose:

- `compilation_mode`: `deterministic-adapter` or `ai-compiled`;
- `delivery_mode`: `remote-live`, bounded `pinned-snapshot`, or separately approved exceptional policy;
- source snapshots and Context Pack version;
- compiler, prompt, provider, model, and deployment identity;
- claim and citation inventory;
- evidence closure and coverage;
- review/publish state;
- freshness, stale behavior, rollback target;
- leak scan, integrity, and install policy.

A ZIP file, manifest, or file count proves packaging only. AI package quality requires source-specific held-out task wins.

In the first AI-compiled package version, model output cannot create executable scripts or runtime mutation instructions. Executable helpers remain deterministic and allowlisted; source-derived procedures stay reviewable reference content unless a separate typed action contract and approval explicitly promotes them.

Ownership: Platform and Product; AI/ML owns compiled content quality.

Child: [#345](https://github.com/pingchesu/sourcebrief/issues/345).

### 6.8 Self-improvement is renamed until optimization is real

Current shipped behavior is a **Review and Proposal Loop**:

```text
answer/evidence
    -> review bundle
    -> findings
    -> regression proposal
    -> validation
    -> staged patch/receipt
    -> explicit human action
```

It may be called self-improvement only when a candidate optimizer:

- trains/optimizes against a separated training set;
- passes held-out regression and negative controls;
- records candidate lineage;
- cannot mutate production automatically;
- is explicitly promoted and rollbackable.

Until then, UI/docs must not imply autonomous learning.

Ownership: QA/Product for review semantics; AI/ML for future optimizer; Platform for mutation boundary.

### 6.9 Evaluation becomes the release authority

Evaluation lanes are independent:

1. ingestion and provenance integrity;
2. retrieval required-resource/facet coverage;
3. semantic relation precision/recall;
4. answer claim support and abstention;
5. AI compiler source-specific quality;
6. Agent/Skill task success;
7. tenant/security/leakage;
8. latency, cost, timeout, and recovery;
9. migration and rollback.

A report cannot PASS because:

- all HTTP requests returned 200;
- all question rows executed;
- `top_k` was filled;
- citations are non-empty;
- a graph or pack has many nodes/files;
- an LLM judge liked the prose;
- development-quality providers were used without an explicit non-production override.

Promotion requires:

- pinned candidate SHA, corpus, snapshots, provider/model/prompt/compiler manifest;
- predeclared thresholds and stop criteria;
- objective assertions and negative controls;
- comparison with current deterministic and real static embedding/rerank baselines;
- disjoint train/development/held-out sets with contamination checks;
- blinded, randomized Hermes/human pairwise review where semantic quality is subjective, with evaluator identity/version recorded and no generator self-approval;
- raw redacted evidence and a finding ledger.

Ownership: QA is the release authority; Product owns task relevance; AI/ML owns model analysis but cannot self-approve.

Child: [#346](https://github.com/pingchesu/sourcebrief/issues/346).

## 7. Typed event boundary

The intelligence plane uses explicit events. Generic `object` payloads and runtime field guessing are prohibited at domain boundaries.

Initial event set:

- `AICompilationRequested`
- `AICompilationSectionCompleted`
- `AICompilationFailed`
- `SemanticCandidateProposed`
- `SemanticCandidateReviewed`
- `SemanticGraphPublished`
- `QueryPlanned`
- `EvidenceSelected`
- `EvidenceClosureFailed`
- `AnswerClaimGenerated`
- `AnswerClaimVerified`
- `PackCompiled`
- `PackPublicationRejected`

Each event has a versioned schema, tenant/project scope, immutable input identities, actor/provider identity, timestamps, idempotency key, and typed result/failure fields. Extension data must live under a versioned namespace and cannot replace required fields.

## 8. Options and decision

Scoring uses 0 = poor, 1 = partial, 2 = strong. Weights: time to proof 5, reuse verified substrate 4, semantic quality ceiling 5, reversibility 4, operational simplicity 3, clean OSS reuse 2.

| Option | Necessary conditions | Weighted score | Exit cost |
| --- | --- | ---: | --- |
| Continue current incremental development | Fails real AI compilation and semantic truth conditions. | 32 | Low, but preserves product failure. |
| Full rewrite around one or more reference projects | Fails migration/governance conditions without major reimplementation. | 14 | Very high. |
| Preserve verified substrate; rebuild intelligence plane | Passes all necessary conditions. | 36 | Medium and bounded by additive versions. |
| Freeze SourceBrief as deterministic evidence backend | Fails intended AI knowledge outcome. | 32 | Low; valid fallback product, not the chosen goal. |

Decision: **preserve the verified substrate and rebuild the intelligence plane**.

Why:

- the existing substrate solves expensive governance and lifecycle problems the reference projects generally do not;
- the intelligence layer can be additive, separately failed, benchmarked, and rolled back;
- a full rewrite maximizes sunk-cost reaction and migration risk without proving better answers;
- continuing current work would optimize the wrong completion criteria;
- freezing as a deterministic backend remains the fallback if the AI plane cannot meet outcome gates.

## 9. Migration plan

### Phase 0 — Claim freeze and truth labels

- Land this contract and ADR.
- Add README/status/claim-ledger reset wording.
- Rename or relabel existing surfaces:

| Current label | Honest interim label |
| --- | --- |
| Graph | Structural Graph |
| GraphRAG in mechanical smoke output | Hybrid structural retrieval |
| `extractive_synthesis` | `extractive_preview` |
| Skill Export without LLM | Deterministic Adapter Export |
| Self-improvement | Review and Proposal Loop |

No stored artifact semantics change in Phase 0.

### Phase 1 — Versioned AI execution plane

- Add typed provider/execution records and health.
- Add explicit compile modes.
- Add budgets, retries, cancellation, cache, cost, and failure state.
- Keep disabled by default until provider contract tests pass.

### Phase 2 — AI compiler on a narrow corpus

- Start with ADRs, runbooks, architecture docs, and one book/document corpus.
- Produce candidate claims and citation-bound semantic artifacts.
- Review manually and establish relation/claim error taxonomy.
- Do not publish into current graphs or packs automatically.

### Phase 3 — Semantic graph, WEAVE retrieval, and answers

- Publish reviewed G2 project graphs beside existing G0 graphs.
- Introduce a new retrieval profile and typed QueryPlan.
- Add claim-level answer generation and verification.
- Compare against both deterministic and real static provider baselines.

### Phase 4 — AI-compiled Agent/Skill Packs

- Keep deterministic adapters available.
- Add AI packages as a separate manifest/API/UI mode.
- Install and test in Hermes against held-out source-specific tasks.
- Require review and evidence closure before publication.

### Phase 5 — Adoption, backfill, and claim promotion

- Canary selected projects/resources.
- Backfill semantic artifacts explicitly; never relabel old artifacts in place.
- Rehearse rollback to deterministic-only operation.
- Promote claims in `docs/CLAIM_LEDGER.md` only from current-candidate evidence.

## 10. Compatibility and reversibility

- Existing resources, snapshots, chunks, structural graphs, Context Packs, and deterministic Skill Exports remain readable.
- New semantic and AI artifacts use additive schema versions and separate lifecycle rows/fields.
- Existing `Graph` and `SkillExport` API consumers receive compatibility fields during deprecation; new consumers use explicit capability/mode fields.
- AI failure does not roll back or corrupt the current structural snapshot.
- Semantic publication can roll back independently to the previous reviewed version.
- The whole AI plane can be disabled, leaving SourceBrief as an honestly labeled deterministic evidence backend.

No destructive data migration is allowed until a dry-run inventory, canary, rollback rehearsal, and current-artifact read compatibility test pass.

## 11. Observability and operational ownership

Minimum dashboards/metrics:

- source/section coverage and skipped reasons;
- AI queue depth, age, attempts, cancellation, and terminal state;
- provider/model health, latency, tokens, cost, timeout, and error class;
- compiler coverage, claims per type, unsupported/invalid citation counts, duplicate/conflict counts;
- semantic graph freshness, candidate/reviewed/rejected edges, relation quality sample;
- QueryPlan required-resource/facet coverage and follow-up rate;
- answer verified/partial/unsupported/conflicting claims;
- pack mode, compilation status, stale/install mismatch, review and rollback;
- evaluation candidate/baseline provenance and current verdict.

Ownership:

| Domain | Accountable owner |
| --- | --- |
| Snapshots, schemas, jobs, APIs, ACL, audit, rollback | Platform/Data |
| Models, prompts, compiler, semantic extraction, answer/verifier quality | AI/ML + Knowledge Engineering |
| Task definitions, UX, capability labels, acceptable outcomes | Product |
| Golden sets, negative controls, promotion verdict, security regression | QA/Security |
| Provider/runtime incidents, budgets, canary/backfill, rollback | Operations with Platform/AI escalation |

## 12. Failure modes

| Failure | Required behavior | Forbidden behavior |
| --- | --- | --- |
| No AI provider configured | `ai_compiled` unavailable; deterministic mode remains separately selectable. | Silent fallback under AI label. |
| Provider timeout/rate limit | Typed retryable failure, budget/attempt data, bounded retry. | Infinite retry or incomplete publish. |
| Malformed/model-injected output | Reject at schema/evidence/security gate. | Persist arbitrary model fields as trusted metadata. |
| Unknown or missing citation | Reject claim or mark partial. | Publish uncited source claim. |
| Source advances | Mark affected semantic artifacts and packs stale; queue explicit recompile. | Serve old semantic artifact as current without warning. |
| Entity ambiguity/contradiction | Preserve candidates/conflict and request review. | Merge by name or choose one source silently. |
| Semantic worker outage | G0 remains available; G1/G2 unavailable/stale. | Block structural source access. |
| Required resource missing | Return partial/follow-up/abstention with resource name. | Fill top-k from another resource and claim completeness. |
| Answer verifier fails | Return evidence packet and answer unavailable/partial. | Return unverified prose. |
| Pack compile/leak scan fails | No downloadable/publishable package. | Publish partial ZIP. |
| Tenant/permission mismatch | Fail closed and audit. | Cross-scope evidence or cache reuse. |
| Eval/provider provenance missing | Verdict cannot PASS. | Infer provider/corpus identity from labels. |

## 13. Security and privacy

- Model input is restricted to authorized section evidence and declared task purpose.
- Prompt injection in sources is treated as source data, never runtime instruction.
- Provider egress and retention policy is explicit per workspace/project.
- Secrets are redacted before provider calls and output persistence.
- Cache keys include tenant/project and immutable evidence identity; cross-tenant AI cache sharing is forbidden in the first implementation.
- Canonical evidence, redacted provider-input views, provider responses, and published artifacts have distinct hashes and lineage so redaction cannot silently invalidate citations.
- Model output is untrusted until schema, evidence, leakage, and policy validation pass.
- Source text can contribute knowledge candidates but cannot override compiler/runtime instructions or introduce tools, executable package content, or mutation authority.
- Human approval events include actor, exact artifact hash, evidence closure, and comment.
- Raw prompts/responses have bounded retention and are not included in public packs or routine logs.

## 14. Product surface requirements

Primary UI surfaces must answer, without UUID-first inspection:

1. What mode ran?
2. Which provider/model/compiler and source versions were used?
3. What are its generation method, review state, coverage state, freshness state, availability state, and latest execution state?
4. Which evidence supports it?
5. What is missing or conflicting?
6. What did it cost and how long did it take?
7. Who approved it?
8. What will retry, recompile, publish, rollback, install, or uninstall do?

Copy must not use `AI`, `semantic`, `GraphRAG`, `generated knowledge`, or `self-improvement` as decorative labels. The capability state and current evidence decide the label.

Child: [#347](https://github.com/pingchesu/sourcebrief/issues/347).

## 15. Outcome-based release gates

Before any AI capability is called shipped:

- source claims have exact evidence closure;
- unknown citation acceptance is zero;
- false-premise controls do not receive supported answers;
- cross-resource questions report required-resource coverage;
- semantic relation quality is measured on human-reviewed samples;
- AI-compiled packs beat deterministic adapters on held-out source-specific tasks;
- candidate profiles beat the current dev baseline and a real static embedding/rerank baseline without general regressions;
- cost, latency, timeout, cancellation, and failure recovery are reported;
- tenant, egress, prompt-injection, secret, and review-bypass tests pass;
- migration/backfill/rollback proof exists on representative current data.

Thresholds must be declared in the evaluation manifest before a candidate run. They cannot be chosen after viewing results.

### First bounded product proof

The first implementation train is not a universal compiler. It uses one pinned project containing:

- one repository;
- one architecture/decision set;
- one operations runbook;
- one long-form document or book-like text source.

The proof must demonstrate one architecture path question, one decision/rationale question, one operating procedure question, and one source-specific Skill task end to end:

```text
ingest evidence
  -> AI compile typed claims
  -> review/publish semantic graph
  -> WEAVE evidence closure
  -> claim-verified answer
  -> AI-compiled Skill Pack
  -> Hermes held-out task
```

The same inputs are evaluated through the deterministic adapter and a real static embedding/rerank baseline. If the candidate cannot beat both baselines without citation, negative-control, leakage, latency, or cost regressions in two bounded candidate cycles, stop and revisit the architecture before broadening source types or ontologies.

## 16. Execution order

1. [#338](https://github.com/pingchesu/sourcebrief/issues/338) — product contract and claim freeze.
2. [#339](https://github.com/pingchesu/sourcebrief/issues/339) — structural evidence contract.
3. [#340](https://github.com/pingchesu/sourcebrief/issues/340) — AI provider plane.
4. [#341](https://github.com/pingchesu/sourcebrief/issues/341) — AI knowledge compiler.
5. [#346](https://github.com/pingchesu/sourcebrief/issues/346) — executable eval contract and initial baselines, in parallel with compiler work after schemas stabilize.
6. [#342](https://github.com/pingchesu/sourcebrief/issues/342) — semantic graph.
7. [#343](https://github.com/pingchesu/sourcebrief/issues/343) — WEAVE retrieval.
8. [#344](https://github.com/pingchesu/sourcebrief/issues/344) — grounded answers.
9. [#345](https://github.com/pingchesu/sourcebrief/issues/345) — AI-compiled packs.
10. [#347](https://github.com/pingchesu/sourcebrief/issues/347) — product/ops closure throughout the train, with final migration and rollback gate.

A child may not declare itself complete from helper/unit tests alone. Each must prove the consumed API/artifact/UI/runtime path named in its acceptance criteria.

## 17. Assumption ledger

These are hypotheses, not decisions. Each must be retired with the named evidence before its dependent capability is promoted.

| Assumption | Evidence required to retire it | Accountable owner |
| --- | --- | --- |
| The current snapshot/ACL/audit/review substrate can host additive AI artifacts without destructive reinterpretation. | Schema spike, current-data migration dry-run, dual-read compatibility test, canary, and rollback rehearsal. | Platform/Data |
| Section-aware AI compilation produces more useful source-specific knowledge than deterministic templates. | Blinded held-out comparison on the first bounded corpus, with citation support and negative controls. | AI/ML + Product + QA |
| Exact-span plus independent support verification can keep unsupported claims below the predeclared gate. | Human-labeled claim-support set with mutation and false-premise controls. | AI/ML + QA |
| PostgreSQL can serve bounded reviewed semantic graph traversal at target scale. | Representative node/edge corpus, p50/p95 path/query latency, lock/load behavior, and failure profile. | Platform/Data |
| Human review can protect publication without destroying first-use value. | Timed usability test showing source-specific value without raw IDs and no more than one visible review object before first useful result. | Product/UX |
| Provider cost, latency, rate limits, and retention policy fit the intended operating model. | Pinned-model load/cost run, quota/timeout/cancellation test, retention/egress review, and budget approval. | AI/ML + Operations + Security |
| Long-form parsers preserve reliable locators across Markdown/HTML/PDF/Office/OCR inputs. | Representative parsing corpus with page/heading/table/bounding-box locator checks and explicit unsupported-format results. | Platform/Data + QA |
| Semantic failures can be isolated from structural evidence availability. | Worker/provider outage and failed-recompile chaos test proving G0 reads, stale/degraded labels, retry, and rollback. | Platform + Operations |
| AI-compiled packs improve real Hermes tasks without introducing executable or prompt-injection authority. | Installed-package held-out task run, deterministic baseline, injection/leak/mutation controls, and runtime receipt audit. | Product + AI/ML + Security + QA |

Unretired assumptions remain visible in the relevant issue and evaluation manifest. A successful demo does not retire an assumption unless it exercises the stated evidence path.

## 18. Pre-mortem and revisit triggers

### Likely failure 1: another provider wrapper is mistaken for intelligence

Signal: provider health is green while held-out claim/relation/answer quality does not improve.

Revisit trigger: two candidate cycles fail to beat the real static baseline on source-specific held-out tasks.

Action: stop model/provider expansion; audit compiler/evidence/eval design.

### Likely failure 2: AI output volume recreates the graph-size illusion

Signal: nodes/claims increase while reviewed precision, required-resource coverage, or answer support stays flat or falls.

Revisit trigger: any release proposal leads with artifact volume rather than quality/error data.

Action: block promotion and reduce ontology/compiler scope.

### Likely failure 3: governance overwhelms first-use value

Signal: a user cannot connect a representative source and obtain a reviewed useful answer without understanding internal lifecycle objects.

Revisit trigger: first-use usability test requires raw IDs or more than one manual review object before seeing source-specific value.

Action: simplify the product path while preserving internal review/audit boundaries.

### Fallback decision

If the AI plane cannot meet the release gates within two bounded candidate cycles, freeze SourceBrief as a deterministic, cited evidence service. Remove AI/semantic/GraphRAG/generated-skill positioning rather than continuing indefinite platform expansion.

## 19. Completion definition for the reset

The reset itself is complete only when:

- this contract and ADR are merged;
- claim freeze wording is visible from README, status, and claim ledger;
- every child issue is linked and scoped;
- current deterministic features carry honest labels;
- the first AI-provider/knowledge-compiler implementation issue begins from this contract;
- no current artifact, test, or report is cited as proof of an AI capability it did not execute.
