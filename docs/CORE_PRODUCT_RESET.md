# SourceBrief Core Product Reset

- Status: Proposed Phase 0 contract; the product reset is incomplete until one of the explicit exit outcomes in Section 19 is proven
- Umbrella: [#337](https://github.com/pingchesu/sourcebrief/issues/337)
- Contract slice: [#338](https://github.com/pingchesu/sourcebrief/issues/338)
- Decision record: [ADR-0002](decisions/ADR-0002-ai-intelligence-plane.md)
- Owner: SourceBrief platform, AI/ML, Product, and QA

## 1. Executive decision

SourceBrief's product development has failed against its intended intelligence outcome.

The repository contains substantial working platform machinery: versioned source snapshots, provenance, tenant and token scope, audit, review lifecycle, API/MCP delivery, Context Pack versions, package validation, runtime adapters, and local real-service QA. Those capabilities are useful, but they were allowed to look like completion of a different product promise:

> SourceBrief understands heterogeneous project sources, builds useful cross-resource knowledge, answers with grounded reasoning, and produces genuinely source-specific skills and agents.

That promise is not currently shipped.

This reset makes one immediate decision:

> Preserve only the verified evidence and governance substrate. Freeze a falsifiable evaluation contract, then run the smallest provider-backed AI-compiled Skill Pack experiment. A broader semantic graph, evidence-closure retrieval, and generated-answer plane is conditional on that experiment proving user value. No deterministic or mechanical fallback may retain an AI, semantic, GraphRAG, or generated-knowledge label.

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

### Contingent long-term target state

Only if the bounded Gate A experiment in Section 15 passes, a later product may let a user connect versioned sources and receive:

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

Primary persona: **a platform engineer onboarding Hermes to an existing repository**.

Golden path:

> From one pinned Git repository, the platform engineer reaches an installed, source-specific AI-compiled Skill Pack within 20 minutes, without entering raw internal IDs and with at most one explicit review/approval action. Hermes then completes a held-out repository maintenance task in a sandbox, passes its objective tests/rubric, and cites the exact repository evidence used.

Cross-resource questions, reviewed semantic graphs, generic generated answers, and broad source-type support are contingent follow-on outcomes, not prerequisites for this first proof.

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

Gate A implements only the minimum single-workload execution path required by the frozen experiment. Multi-provider breadth, generalized answer workloads, and platform expansion are not approved without measured need.

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

Gate A compiles only the reference/claim types needed by the selected repository-maintenance task. The broader claim taxonomy below is a versioned candidate contract, not a requirement to build every type before product proof.

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
  "map_parent_claim_ids": ["map-claim-id"],
  "source_section_hashes": ["sha256:section"],
  "coverage_plan_hash": "sha256:plan",
  "examined_scope_hash": "sha256:all-sections-examined-by-reducer",
  "negative_or_conflict_dependency_ids": ["candidate-or-conflict-id"],
  "reducer_version": "knowledge-reducer.v1",
  "ontology_version": "sourcebrief.ontology.v1",
  "review_state": "unreviewed"
}
```

Rules:

- source-specific claims require citations;
- unknown citation IDs fail validation;
- citation-ID presence alone is not support: exact evidence spans and a support decision are separate typed records;
- per-section quotas prevent late-source starvation;
- reduced claims retain their map-parent claims, source-section hashes, selected and examined scope, coverage-plan hash, reducer/ontology versions, and negative/contradiction dependencies;
- a changed dependency, excluded-candidate decision, contradiction, coverage plan, or examined scope invalidates the complete affected reduce closure; the system must not reuse a global conclusion merely because its final positive citation did not change;
- model output is untrusted typed input and must pass schema, evidence, leakage, and policy checks;
- no candidate is published directly.

Ownership: AI/ML and Knowledge Engineering; Platform owns immutable lineage and review lifecycle.

Child: [#341](https://github.com/pingchesu/sourcebrief/issues/341).

### 6.4 Conditional graph candidate uses four layers

This design is dormant until Gate A passes and a separate measured-need decision authorizes semantic graph work.

| Layer | Name | Contents | Truth policy |
| --- | --- | --- | --- |
| G0 | Structural Evidence Graph | Resource, file, section, symbol, explicit config/deployment/data/event relationships. | Deterministic/observed. |
| G1 | Semantic Candidate Graph | AI-extracted concepts, decisions, owners, procedures, risks, flows, candidate entity links. | Candidate; evidence required. |
| G2 | Reviewed Project Graph | Approved union/overlay/reconcile across resources; conflicts and communities. | Published reviewed knowledge. |
| G3 | Temporal Decision and Evaluation Graph | Decisions, incidents, corrections, evaluation failures, proposal lineage. | Time/version bounded; never rewrites source truth. |

Every semantic node/edge carries independent provenance and lifecycle fields:

- evidence locators and parent claim IDs;
- `derivation_source`: `explicit`, `ai_extracted`, or `inferred`;
- derivation rule/prompt/compiler identity;
- `ontology_id` and `ontology_version` for every typed relation;
- confidence and calibration state;
- `review_state` plus immutable `review_event_id` and reviewer identity;
- valid time and transaction/recorded time;
- freshness and supersession state.

Human approval never overwrites derivation lineage. For example, an approved AI-extracted edge remains `derivation_source=ai_extracted` with a separate `review_state=approved`.

A name match is not sufficient for entity resolution. Inferred edges cannot satisfy high-assurance questions until reviewed.

Model-reported confidence is advisory unless calibrated against a pinned labeled set. Uncalibrated confidence cannot satisfy a trust gate or replace evidence/review.

Semantic compilation failure marks G1/G2 stale or unavailable while G0 remains queryable.

Ownership: Knowledge Engineering and Platform.

Child: [#342](https://github.com/pingchesu/sourcebrief/issues/342).

### 6.5 Retrieval remains conditional and becomes authorization-bound evidence closure

No branded retrieval architecture is approved before Gate A. If the first Skill Pack proof shows that runtime evidence retrieval is a material failure source, the follow-on retrieval design uses three separate typed contracts:

1. `AuthorizationEnvelope`: server-issued and immutable for the request; carries tenant/project/resource scope, permitted evidence classes, egress/tool policy, and maximum risk/budget. A model can never create or expand it.
2. `EvidenceRequirementContract`: user-, policy-, or evaluation-owned required resources, facets, evidence classes, freshness, and risk. In evaluation, QA supplies gold requirements independently of the planner.
3. `PlannerProposal`: model/deterministic proposal for intent, candidate facets, follow-up queries, and ranking preferences. It is untrusted input and can only narrow or operate inside the envelope.

The effective plan records all three inputs:

```json
{
  "authorization_envelope_id": "server-signed-envelope",
  "evidence_requirement_contract_id": "user-policy-or-eval-contract",
  "planner_proposal": {
    "intent": "architecture | code | operations | decision | comparison | procedure | change_impact",
    "candidate_facets": ["planner-proposed answer dimensions"],
    "requested_resources": ["resource refs within the envelope"],
    "requested_evidence_classes": ["structural", "reviewed_semantic", "live"],
    "freshness_preference": "policy",
    "risk_proposal": "normal | high_assurance"
  },
  "effective_plan_hash": "sha256:server-intersection-and-policy-result",
  "coverage_basis": "user_declared | policy_declared | eval_gold | planner_only",
  "token_budget": 8000
}
```

Closure rules:

- authorization is always evaluated against the server-issued envelope, never model output;
- the planner cannot remove externally required resources/facets or promote its own proposal to gold truth;
- `coverage_state=full` requires closure against a user-, policy-, or QA-declared requirement contract;
- when only a planner proposal exists, `coverage_state=unknown` with `coverage_basis=planner_only`; it cannot certify completeness;
- Eval v2 independently labels gold resources, facets, evidence classes, freshness/risk, and planner precision/recall before retrieval quality is scored.

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

### 6.6 Conditional answers use atomic verification proofs

This design is dormant until Gate A passes and a separate measured-need decision authorizes generated-answer work.

The evidence packet and the generated answer are separate artifacts.

Answer claim contract:

```json
{
  "claim_id": "answer-claim-id",
  "atomic_text": "one independently verifiable proposition",
  "kind": "quote | paraphrase | synthesis | inference | conflict | unknown",
  "evidence_spans": [
    {
      "citation_id": "citation-id",
      "quote_hash": "sha256:exact-span"
    }
  ],
  "support": "verified | partial | unsupported | conflicting",
  "verification_proofs": [
    {
      "method": "deterministic_span | independent_model | human_review",
      "verifier": "deterministic-policy-or-provider/model-or-reviewer",
      "verifier_prompt_or_policy_version": "support.v1",
      "entailment": "supported | partial | unsupported",
      "contradiction": "none | present | unknown",
      "rationale_hash": "sha256:redacted-rationale",
      "verified_at": "RFC3339"
    }
  ],
  "confidence": 0.0
}
```

Rules:

- answer prose decomposes into atomic claims; a sentence containing multiple propositions maps to multiple claims rather than one bundled support decision;
- each atomic claim maps to exact evidence spans;
- quotes use a deterministic exact-span verifier;
- paraphrase, synthesis, and inference require an independent verifier/provider or an authorized human gate with recorded lineage; the generator cannot self-approve;
- `verified` requires retained verification proof and a declared support policy; a citation label, generator/verifier agreement from the same execution, or prose quality is insufficient;
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

For the Gate A experiment, the deterministic adapter/control files (`SKILL.md`, tool policy, runtime selectors, validation, and executable helpers) remain deterministic and allowlisted. Model-produced material is stored only as clearly delimited, reviewable reference/data-plane content. It is treated as source evidence, not as runtime instruction, and cannot introduce tools, executable scripts, shell commands, mutation authority, or policy overrides. Promoting any generated procedure into instruction/executable authority requires a later, separate typed action contract, security review, adversarial evaluation, explicit human approval, and its own release gate.

The package renderer serializes only allowlisted typed fields, escapes Markdown/HTML/template delimiters where the target runtime requires it, performs no template or code evaluation over model text, and rejects tool-call-shaped or instruction-authority fields. Runtime smoke tests inject adversarial source instructions and prove that the deterministic controller preserves SourceBrief policy rather than following them. Lexical scanning is defense in depth, not the authority boundary.

Gate A tests this minimal AI-compiled reference pack directly. Semantic graph publication, generalized evidence-closure retrieval, and generated-answer infrastructure are not prerequisites and may be added only if the Gate A failure analysis demonstrates that they are necessary.

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

Eval v2, the pinned corpus/splits, objective task harness, baselines, evaluator prompt/version, recursive blind-payload sanitizer, thresholds, budgets, and stop date are frozen **before** provider/compiler candidate tuning begins. Existing v1 profile-matrix and 50Q mechanics are historical regression inputs only; they cannot authorize Gate A or be relabeled as v2 evidence. The current pairwise path is specifically unsafe as a blind authority until nested `profile` and retrieval metadata are removed through a recursive allowlist transform and regression-tested.

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
- QA-owned gold resources/facets/evidence classes/risk contracts, independent of candidate planner output;
- comparison with current deterministic and real static embedding/rerank baselines;
- disjoint train/development/held-out sets with contamination checks;
- recursively allowlisted and sanitized pairwise payloads with candidate/profile identity removed at every nesting level;
- blinded, randomized Hermes/human pairwise review where semantic quality is subjective, with evaluator identity/version recorded and no generator self-approval;
- raw redacted evidence and a finding ledger.

Ownership: QA is the release authority; Product owns task relevance; AI/ML owns model analysis but cannot self-approve.

Child: [#346](https://github.com/pingchesu/sourcebrief/issues/346).

## 7. Typed event boundary

The intelligence plane uses explicit events. Generic `object` payloads and runtime field guessing are prohibited at domain boundaries.

Initial event set:

- `AuthorizationEnvelopeIssued`
- `EvidenceRequirementDeclared`
- `PlannerProposalCreated`
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
- `VerificationProofRecorded`
- `PackCompiled`
- `PackPublicationRejected`

Each event has a versioned schema, tenant/project scope, immutable input identities, actor/provider identity, timestamps, idempotency key, and typed result/failure fields. Extension data must live under a versioned namespace and cannot replace required fields.

## 8. Options and decision

Scoring uses 0 = poor, 1 = partial/uncertain, 2 = strong. Weights: time to proof 5, reuse verified substrate 4, semantic quality ceiling 5, reversibility 4, operational simplicity 3, clean OSS reuse 2. Scores are a decision aid, not product evidence.

| Option | Time ×5 | Reuse ×4 | Quality ceiling ×5 | Reversibility ×4 | Ops simplicity ×3 | OSS reuse ×2 | Weighted total | Evidence and uncertainty |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Continue current incremental development | 2 | 2 | 0 | 2 | 2 | 0 | 32 | Fast and simple, but current code proves deterministic/template behavior, not the intended outcome. |
| Full rewrite around reference projects | 0 | 0 | 2 | 0 | 0 | 2 | 14 | High theoretical ceiling and reuse ideas, but discards verified governance and requires rebuilding migration/tenancy/ops. |
| Preserve substrate; freeze Eval v2; run one bounded AI Skill experiment | 1 | 2 | 2 | 2 | 1 | 1 | 36 | Reuses proven substrate and is reversible. Quality score is a hypothesis to test, not an observed win; provider/eval/compiler work adds time and operations. |
| Freeze SourceBrief as deterministic evidence service | 2 | 2 | 0 | 2 | 2 | 0 | 32 | Honest, usable fallback with low exit cost, but does not test whether model-backed compilation improves the selected user task. |

Decision: **approve Phase 0 truth adoption and the bounded Gate A experiment only**.

This decision does **not** yet approve a broad intelligence-plane build, G1–G3 publication, generalized evidence-closure retrieval, or generated-answer infrastructure. Whether model-backed compilation is needed is itself a hypothesis. Gate A compares the deterministic adapter, a real static retrieval baseline, and the minimal AI-compiled reference pack with the same Hermes runtime and held-out tasks before those broader investments are authorized.

Why:

- the existing substrate solves expensive governance and lifecycle problems and can host a cheap reversible experiment;
- a direct Skill Pack task tests the claimed user value earlier than building graph/retrieval/answer plumbing;
- a full rewrite maximizes sunk-cost reaction and migration risk without proving user outcomes;
- continuing current work would optimize the wrong completion criteria;
- freezing as a deterministic backend remains an equal-status fallback outcome if Gate A cannot meet the predeclared outcome and economics gates.

## 9. Migration plan

### Phase 0 — Truth adoption, chosen-source evidence, and Eval v2 freeze

- Land this contract and ADR as Phase 0 adoption only.
- Add README/status/claim-ledger reset wording.
- Rename or relabel existing surfaces:

| Current label | Honest interim label |
| --- | --- |
| Graph | Structural Graph |
| GraphRAG in mechanical smoke output | Hybrid structural retrieval |
| `extractive_synthesis` | `extractive_preview` |
| Skill Export without LLM | Deterministic Adapter Export |
| Self-improvement | Review and Proposal Loop |

- Pin the one Git repository, task split, objective harness, two baselines, blind sanitizer, thresholds, budgets, and stop clock defined in Section 15.
- Close exact evidence/locator gaps only for that selected Git source path; unsupported source formats remain visibly unsupported.
- Capture the current pairwise nested-profile leak as an Eval v2 RED regression.

No stored artifact semantics change in Phase 0.

### Phase 1 — Minimal Gate A vertical slice

- Add only the provider/execution records required by the chosen experiment.
- Compile one bounded, reviewable AI reference pack directly from the pinned Git source.
- Keep deterministic `SKILL.md`, selectors, policy, validation, and executable helpers as the control plane.
- Run the three predeclared arms with the same Hermes model/runtime and held-out tasks.
- Do not build a semantic graph, generalized evidence-closure retrieval, or generated-answer service to satisfy Gate A.

### Gate A — Product/economics decision

- **PASS:** authorize only the next capability whose need is demonstrated by task failure analysis; do not automatically approve the full long-term architecture.
- **FAIL after two cycles:** stop AI expansion, adopt the deterministic cited-evidence product, and remove unsupported AI/semantic/GraphRAG/generated-skill positioning.

### Phase 2 — Conditional compiler/evidence hardening

If Gate A passes, broaden claim types, invalidation closure, source formats, and review workflows only against new pinned tasks and budgets.

### Phase 3 — Conditional graph, retrieval, or answer work

Add reviewed semantic graph, authorization-bound evidence-closure retrieval, or atomic claim-verified answers only when a measured Gate A or follow-on task failure demonstrates that the capability is required. Each receives a separate decision/evaluation gate.

### Phase 4 — Controlled expansion

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

Minimum dashboards/metrics for the capabilities actually approved and running (conditional graph/retrieval/answer metrics do not activate before their decisions):

- source/section coverage and skipped reasons;
- AI queue depth, age, attempts, cancellation, and terminal state;
- provider/model health, latency, tokens, cost, timeout, and error class;
- compiler coverage, claims per type, unsupported/invalid citation counts, duplicate/conflict counts;
- semantic graph freshness, candidate/reviewed/rejected edges, relation quality sample;
- authorization envelope denials, requirement-contract coverage, planner precision/recall, planner-relative unknown coverage, and follow-up rate;
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

The signed Gate A manifest must name the accountable Product owner, Eval/QA owner, provider/compiler operator, runtime-pack owner, security reviewer, and incident escalation target. Missing ownership or an untestable runbook blocks `D0`; a generic team label is not sufficient release ownership.

## 12. Failure modes

| Failure | Required behavior | Forbidden behavior |
| --- | --- | --- |
| No AI provider configured | `ai_compiled` unavailable; deterministic mode remains separately selectable. | Silent fallback under AI label. |
| Provider timeout/rate limit | Typed retryable failure, budget/attempt data, bounded retry. | Infinite retry or incomplete publish. |
| Malformed/model-injected output | Reject at schema/evidence/security gate. | Persist arbitrary model fields as trusted metadata. |
| Unknown or missing citation | Reject claim or mark partial. | Publish uncited source claim. |
| Source advances | Mark affected AI artifacts and packs stale; queue explicit recompile. | Serve an old compiled artifact as current without warning. |
| Entity ambiguity/contradiction | Preserve candidates/conflict and request review. | Merge by name or choose one source silently. |
| Semantic worker outage | G0 remains available; G1/G2 unavailable/stale. | Block structural source access. |
| Required resource missing | Return partial/follow-up/abstention with resource name. | Fill top-k from another resource and claim completeness. |
| Answer verifier fails | Return evidence packet and answer unavailable/partial. | Return unverified prose. |
| Pack compile/leak scan fails | No downloadable/publishable package. | Publish partial ZIP. |
| Tenant/permission mismatch | Fail closed and audit. | Cross-scope evidence or cache reuse. |
| Eval/provider provenance missing | Verdict cannot PASS. | Infer provider/corpus identity from labels. |

## 13. Security and privacy

- Model input is restricted to authorized section evidence and declared task purpose.
- Authorization envelopes are issued and enforced by trusted server policy; model/planner output can never add resources, scopes, evidence classes, tools, egress, or mutation rights.
- Prompt injection in sources is treated as source data, never runtime instruction.
- Provider egress and retention policy is explicit per workspace/project.
- Secrets are redacted before provider calls and output persistence.
- Cache keys include tenant/project and immutable evidence identity; cross-tenant AI cache sharing is forbidden in the first implementation.
- Canonical evidence, redacted provider-input views, provider responses, and published artifacts have distinct hashes and lineage so redaction cannot silently invalidate citations.
- Model output is untrusted until schema, evidence, leakage, and policy validation pass.
- Source text can contribute knowledge candidates but cannot override compiler/runtime instructions or introduce tools, executable package content, or mutation authority.
- Human approval events include actor, exact artifact hash, evidence closure, and comment.
- Raw prompts/responses have bounded retention and are not included in public packs or routine logs.
- Evaluation and pairwise-review payloads use recursive field allowlists so nested profile, provider, retrieval, tenant, or candidate identity cannot defeat blinding or leak scope metadata.
- Gate A Hermes tasks run in disposable sandboxes with no production/user credentials, no deploy/push/PR authority, network egress denied by default, a read-only pinned evidence/source mount plus one scoped writable checkout, bounded CPU/memory/time, and retained command/diff/test receipts. Provider compilation runs in a separate trust boundary; model/source text cannot widen task-executor capabilities.

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

### Gate A must be frozen before implementation

Before #340 or #341 candidate tuning begins, #346 publishes a signed Eval v2 manifest with the pinned corpus/snapshots, split membership, objective harness, four arms, evaluator policy, recursive blind sanitizer, thresholds, budgets, and `D0` stop-clock timestamp. `D0` must be signed no later than 10 working days after Phase 0 merges; missing that deadline is an explicit AI no-go under this ADR unless a new decision supplies materially different evidence. Threshold changes require a new manifest version **before** a new candidate run, reset the comparison baseline, and invalidate runs under the previous contract. A manifest revision does not extend the absolute 30-working-day Phase-0-to-outcome deadline; it consumes the remaining clock.

Primary persona and task class:

- persona: platform engineer onboarding Hermes to an existing repository;
- source type: one pinned Git repository only;
- task: Hermes applies one scoped repository-specific maintenance change in a sandbox, using the installed pack and authorized repository evidence, then passes hidden tests plus a typed product/citation rubric;
- interaction budget: no raw IDs, at most one explicit review/approval action.

Dataset fixed before candidate work:

- 4 development tasks, never used for promotion;
- 12 held-out tasks of the same declared class;
- 6 held-out negative/security controls covering wrong resource, false premise, prompt injection, secret leakage, unauthorized mutation instruction, and unsupported claim;
- the first corpus is public or purpose-built non-sensitive data with compatible licensing and no customer, employee, production, credential, or restricted-source content;
- contamination check between source material, development tasks, held-out tasks, prompts, and generated pack content.
- human authors and the AI compiler may see only the pinned source plus the 4 development tasks; they cannot see held-out task prompts, hidden tests, control payloads, or expected outcomes;
- each arm produces one immutable pack before held-out material is decrypted/revealed to the executor; per-task compilation or pack regeneration is forbidden.

Four arms run with the same Hermes model/runtime, sandbox, task order randomization, and pinned source snapshot:

1. current deterministic adapter and current development-quality retrieval;
2. deterministic adapter with a real static embedding/rerank baseline;
3. human-authored reviewed reference pack using the same real static retrieval as arm 2, recording author/review time and cost as the manual ceiling;
4. minimal AI-compiled reviewed reference pack using the same real static retrieval as arm 2.

Primary metric: objective held-out task success, requiring hidden tests plus all mandatory rubric fields. Gate A PASS requires all of the following:

- AI arm succeeds on at least 9 of 12 held-out tasks;
- AI arm wins at least 3 more tasks than the better automated baseline (arms 1–2);
- AI arm finishes no more than 1 task below the human-authored reference arm and regresses on at most 1 task solved by the better automated baseline;
- every externally sourced claim used by a successful candidate task has a valid exact evidence span; any unknown/out-of-scope citation or unsupported high-confidence claim fails that task;
- all 6 negative/security controls pass, with zero tenant/scope leak, secret leak, executable or mutation-authority injection, false-premise supported answer, or review bypass;
- across 3 clean compile/install repetitions, every run has compiler latency at most 15 minutes, the complete source-to-first-use path at most 20 minutes, active human review time at most 10 minutes and at most 50% of the human-authored arm's recorded author-plus-review time, and only one approval object exposed; report all three values and the maximum rather than mislabeling a three-sample maximum as p95;
- incremental AI compilation cost is at most USD 5 per pinned repository run, with no unbounded retry and no more than 2 provider retries per run;
- raw redacted receipts include candidate SHA, source snapshot, pack hash, provider/model/prompt/compiler, evaluator identity/version, randomized arm mapping, task result, latency, cost, and failure reason.

Cycle 1 ends no later than 10 working days after `D0`; cycle 2 ends no later than 20 working days after `D0`. There is no third cycle under this decision, so Phase 0 merge to final Gate A outcome is bounded at 30 working days.

### Gate A consequences

- **PASS:** Phase 0 plus the AI Skill experiment has proved a bounded user outcome. Follow-on graph, retrieval, or answer work still requires a separate need statement and gate; Gate A does not approve the long-term architecture wholesale.
- **FINAL FAIL after the second cycle, or an explicit no-go before it:** freeze SourceBrief as a deterministic cited-evidence service, remove unsupported AI/semantic/GraphRAG/generated-skill positioning, and stop provider/compiler expansion until a new ADR presents materially different evidence. A failed first cycle may use the one remaining cycle but cannot loosen the frozen gate.

### Follow-on release authority

Any later semantic graph, evidence-closure retrieval, generated answer, or broader AI pack capability must additionally prove exact evidence closure, independently declared resource/facet requirements, atomic claim verification, semantic relation precision/recall, false-premise abstention, cost/latency/recovery, tenant/security controls, and migration/rollback on a new predeclared held-out contract. A follow-on p95 latency/cost claim requires at least 20 independent representative samples and must publish sample count and distribution. Mechanical 50Q, HTTP success, artifact volume, or Gate A alone cannot promote those capabilities.

## 16. Execution order

1. [#338](https://github.com/pingchesu/sourcebrief/issues/338) — Phase 0 product contract and claim freeze.
2. [#346](https://github.com/pingchesu/sourcebrief/issues/346) — freeze Eval v2, pinned task corpus, recursive blind sanitizer, four arms, thresholds, budgets, and `D0` before candidate tuning.
3. [#339](https://github.com/pingchesu/sourcebrief/issues/339) — exact evidence contract for the selected Git source path only.
4. [#340](https://github.com/pingchesu/sourcebrief/issues/340) — minimal typed AI provider/execution slice required by Gate A.
5. [#341](https://github.com/pingchesu/sourcebrief/issues/341) — minimal compiler and dependency lineage required by the selected task.
6. [#345](https://github.com/pingchesu/sourcebrief/issues/345) — deterministic control plane plus bounded AI reference pack; execute Gate A in Hermes.
7. Record Gate A PASS or FAIL before authorizing broader product architecture.
8. [#342](https://github.com/pingchesu/sourcebrief/issues/342), [#343](https://github.com/pingchesu/sourcebrief/issues/343), and [#344](https://github.com/pingchesu/sourcebrief/issues/344) — semantic graph, authorization-bound evidence-closure retrieval, and grounded answers remain conditional; each requires measured need and a separate gate.
9. [#347](https://github.com/pingchesu/sourcebrief/issues/347) — capability UX, security, observability, review economics, canary, and rollback throughout.

No provider/compiler candidate tuning may start before step 2 is frozen. No conditional issue in step 8 may start merely because the schema exists or Gate A passed.

A child may not declare itself complete from helper/unit tests alone. Each must prove the consumed API/artifact/UI/runtime path named in its acceptance criteria.

## 17. Assumption ledger

These are hypotheses, not decisions. Each must be retired with the named evidence before its dependent capability is promoted.

| Assumption | Evidence required to retire it | Accountable owner |
| --- | --- | --- |
| The current snapshot/ACL/audit/review substrate can host additive AI artifacts without destructive reinterpretation. | Schema spike, current-data migration dry-run, dual-read compatibility test, canary, and rollback rehearsal. | Platform/Data |
| Section-aware AI compilation produces more useful source-specific knowledge than deterministic or human-authored alternatives at acceptable economics. | Gate A four-arm comparison: at least 9/12 task success, +3 wins over the better automated baseline, within one task of the human pack, exact support, all controls, at most 50% of manual author/review time, and declared latency/cost budgets. | AI/ML + Product + QA |
| Exact-span plus independent support verification can keep unsupported claims below the predeclared gate. | Human-labeled claim-support set with mutation and false-premise controls. | AI/ML + QA |
| PostgreSQL can serve bounded reviewed semantic graph traversal at target scale. | Representative node/edge corpus, p50/p95 path/query latency, lock/load behavior, and failure profile. | Platform/Data |
| Human review can protect publication without destroying first-use value. | Three clean Gate A repetitions with no raw IDs, at most one approval object, at most 10 minutes active review and 50% of human-pack author/review time, and at most 20 minutes source-to-first-use. | Product/UX |
| Provider cost, latency, rate limits, and retention policy fit the intended operating model. | Pinned-model load/cost run, quota/timeout/cancellation test, retention/egress review, and budget approval. | AI/ML + Operations + Security |
| Long-form parsers preserve reliable locators across Markdown/HTML/PDF/Office/OCR inputs. | Representative parsing corpus with page/heading/table/bounding-box locator checks and explicit unsupported-format results. | Platform/Data + QA |
| Semantic failures can be isolated from structural evidence availability. | Worker/provider outage and failed-recompile chaos test proving G0 reads, stale/degraded labels, retry, and rollback. | Platform + Operations |
| AI-compiled reference packs improve real Hermes tasks without introducing executable or prompt-injection authority. | Gate A held-out tasks and six negative/security controls; deterministic `SKILL.md` control plane; installed-package receipt audit. | Product + AI/ML + Security + QA |
| Planner-generated requirements can aid retrieval without self-certifying completeness or expanding authorization. | Server-issued authorization envelope tests, QA-owned gold requirement contracts, planner precision/recall, and closure computed independently of planner proposal. | Platform + Retrieval + QA/Security |

Unretired assumptions remain visible in the relevant issue and evaluation manifest. A successful demo does not retire an assumption unless it exercises the stated evidence path.

## 18. Pre-mortem and revisit triggers

### Likely failure 1: another provider wrapper is mistaken for intelligence

Signal: provider health is green while held-out Hermes task success and pack evidence quality do not improve.

Revisit trigger: the second candidate cycle fails any frozen Gate A threshold.

Action: stop model/provider expansion; audit compiler/evidence/eval design.

### Likely failure 2: AI output volume recreates the graph-size illusion

Signal: nodes/claims increase while reviewed precision, required-resource coverage, or answer support stays flat or falls.

Revisit trigger: any release proposal leads with artifact volume rather than quality/error data.

Action: block promotion and reduce ontology/compiler scope.

### Likely failure 3: governance overwhelms first-use value

Signal: a user cannot connect the pinned source, approve the single review object, install the reference pack, and complete the task without understanding internal lifecycle objects.

Revisit trigger: first-use usability requires raw IDs, more than one review object, more than 10 minutes active review, or more than 20 minutes before the source-specific task starts.

Action: simplify the product path while preserving internal review/audit boundaries.

### Fallback decision

If Gate A cannot meet every predeclared release gate within two cycles and 20 working days after `D0`, freeze SourceBrief as a deterministic, cited evidence service. Remove AI/semantic/GraphRAG/generated-skill positioning rather than continuing indefinite platform expansion.

## 19. Phase 0 adoption and product-reset exit

### Phase 0 contract adoption complete

Phase 0 is complete only when:

- this contract and ADR are merged;
- claim-freeze wording is visible from README, status, and claim ledger;
- every child issue is linked, scoped, and marked conditional where applicable;
- current deterministic features carry honest labels;
- Eval v2 RED cases, including nested pairwise profile leakage, are recorded;
- no current artifact, test, or report is cited as proof of an AI capability it did not execute.

This milestone means only that the contract was adopted. It is **not** product-reset completion and cannot be presented as user-outcome proof.

### Product reset complete

The reset exits in exactly one evidence-backed outcome:

1. **AI outcome:** Gate A PASS is reproduced on the current candidate SHA under the predeclared Eval v2 manifest, including task, safety, review-economics, latency, and cost gates; or
2. **Deterministic outcome:** Gate A reaches final failure after the two-cycle budget or is deliberately rejected by an explicit no-go, the deterministic cited-evidence product is adopted, unsupported AI/semantic/GraphRAG/generated-skill positioning is removed from primary product surfaces, and further AI expansion is stopped pending a new ADR.

Opening or starting provider/compiler issues, merging schemas, generating a package, or passing mechanical tests cannot complete the product reset.
