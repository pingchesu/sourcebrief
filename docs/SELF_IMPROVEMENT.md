# SourceBrief self-improvement

SourceBrief self-improvement is an evidence-backed product loop, not an agent that silently rewrites itself.

The goal is to turn important agent outputs into reviewable artifacts, run autonomous reviewers over those artifacts, convert validated failures into regressions or staged proposals, and adopt improvements only after gates pass.

```text
agent answer / PR / demo / recipe run
    -> review bundle
    -> autonomous reviewer agent
    -> structured findings
    -> regression or learning proposal
    -> validation gate
    -> staged patch / issue / PR
    -> explicit adoption
```

## Product promise

A normal RAG system stops at:

```text
query -> answer
```

SourceBrief should close the loop:

```text
query -> cited answer -> autonomous review -> regression/proposal -> better future answer
```

The product value is that agent mistakes do not disappear in chat history. They become inspectable, replayable, and reviewable evidence.

## Non-goals

SourceBrief self-improvement does **not** mean:

- reviewing an entire day of raw chat as one huge context window;
- treating user corrections as permanent rules without validation;
- letting a reviewer agent silently mutate prompts, skills, runtime config, source code, or production behavior;
- accepting LLM-judge scores as proof without replay or held-out gates;
- building a nightly optimizer before review bundles, findings, regression proposals, and staging exist;
- storing raw secrets, tokens, private local paths, or unbounded transcripts inside improvement artifacts.

## Reference projects and what to borrow

| Reference | Borrow | Do not copy blindly |
| --- | --- | --- |
| `NousResearch/hermes-agent-self-evolution` | Target taxonomy: skills, tool descriptions, prompt sections, code; SessionDB/trajectory mining; PR-based deployment. | Direct source integration before licensing/engineering maturity is checked; synthetic eval as the only proof; Hermes-only assumptions as SourceBrief product behavior. |
| `microsoft/SkillOpt` | Validation gates, bounded edits, rejected-edit buffer, sleep/replay cycle, staged adoption. | Full optimizer as the first feature; raw transcript harvesting; ungated skill/prompt mutation. |

## Core entities

### Review bundle

A review bundle is the unit of review. It replaces raw chat review.

A bundle should contain enough information for a reviewer agent to reproduce or validate the reasoning context without reading the whole conversation:

- original user query, task prompt, or PR/demo brief;
- task brief, acceptance criteria, and explicit non-goals;
- final output, answer, PR body, docs diff, or demo result;
- runtime, model/backend, prompt version, generated skill/agent-pack version, and reviewer policy version where applicable;
- retrieval profile, top-k, rerank flags, context-pack key, and other answer-generation settings;
- immutable source snapshot IDs, commit SHAs, paths, line/section ranges, and content hashes where available;
- citations, source/resource refs, and machine-readable citation metadata;
- sanitized command args, environment metadata, and tool proof such as CLI output, test output, API response, MCP call result, or browser evidence;
- workspace/project/resource/context-pack scope;
- user correction or reviewer feedback, if present;
- redaction metadata, retention class, allowed reviewer backend policy, and bundle completeness status: `complete`, `redacted_partial`, or `insufficient_evidence`.

### Reviewer agent

A reviewer agent reads a review bundle and returns structured findings. It should use distinct lenses:

- citation support: do cited evidence actually support the claim?
- scope and non-goals: did the answer overreach or claim future work as shipped?
- missing evidence: did the agent ignore likely relevant sources?
- product/DX: can a user follow the output successfully?
- safety: did the output imply unsafe mutation, secret exposure, or widened access?
- regression candidate: can this failure become a repeatable check?

Reviewer agents are evidence generators, not authorities. Findings still need validation.

### Finding

A finding is a structured reviewer result.

Suggested fields are type-backed by [Reviewer finding taxonomy](REVIEW_FINDING_TAXONOMY.md):

```json
{
  "severity": "blocker | major | minor | learning | rejected_learning",
  "type": "unsupported_claim | citation_mismatch | missing_evidence | stale_source | scope_creep | unsafe_mutation | quickstart_dx_failure | overclaim | no_proof",
  "summary": "short human-readable statement",
  "evidence_refs": ["bundle citation/tool/log refs"],
  "impact": "why this matters",
  "suggested_fix": "smallest safe fix",
  "regression_candidate": true,
  "confidence": "high | medium | low",
  "reviewer_lens": "citation_support | scope | missing_evidence | product_dx | safety | regression"
}
```

### Regression proposal

A regression proposal converts a validated finding into a future check.

Examples:

- README quickstart must include login when dev auth is off.
- Runtime docs must not claim native install support for targets that only have MCP guidance.
- Citation labels and machine-readable citation metadata must refer to the same source.
- A docs/resource smoke cannot prove repo-only code-read tools.

A proposal is not automatically accepted. It must pass a validation gate.

### Validation gate

The validation gate prevents harmful self-improvement.

A gate compares a candidate improvement against baseline behavior using deterministic checks, held-out bundles, replay tasks, or existing test suites. It returns one of:

- `accept_new_best`: candidate improves the baseline and becomes the best known variant;
- `accept`: candidate is safe and useful but not a new best;
- `reject`: candidate is unsupported, harmful, too broad, or unproven.

Rejected proposals are retained as negative feedback so the same bad lesson is not repeatedly proposed.

### Staged adoption

Accepted proposals are staged for human or PR review.

A staged improvement should include:

- source bundle and finding;
- candidate patch or issue body;
- validation gate result;
- expected effect;
- rollback path;
- owner and target surface.

No SourceBrief runtime, generated skill, prompt, docs, or code path should change silently.

## Trigger policy

Run review only where the signal is worth the cost.

Recommended triggers:

| Trigger | Why |
| --- | --- |
| PR opened or updated | Review concrete diff, tests, docs, and claims. |
| Important cited answer | Validate claim/citation support. |
| Quickstart, demo, or recipe run | Check product path and failure repair guidance. |
| User correction | Mine high-signal failures without reading all chat. |
| Failed verification followed by a fix | Turn the failure into a future regression. |
| Runtime/agent-pack generation | Check safety boundaries and generated instruction quality. |

Avoid default review of every message.

## Safety and permission model

Self-improvement artifacts must preserve SourceBrief's existing trust boundaries. The detailed implementation baseline is [Self-improvement artifact security](SELF_IMPROVEMENT_SECURITY.md).

- A reviewer can only inspect evidence allowed by the originating workspace/project/resource scope.
- A bundle should store references and redacted snippets, not full unbounded private corpora by default.
- Runtime tokens, credentials, bearer tokens, API keys, local private paths, and raw secrets must be redacted.
- Each bundle must carry sensitivity, retention, purge scope, allowed reviewer backend, and egress decision metadata.
- Private bundle evidence must not be sent to an unapproved external LLM or reviewer backend. External reviewers are opt-in by workspace/project policy.
- Every reviewer run must record backend/model identity, redaction status, egress decision, reviewer policy version, and artifact retention class.
- Purge/delete must cover derived artifacts too: bundle, finding, proposal, gate result, staged patch/receipt, and observability summaries.
- Improvements that change docs, recipes, generated skills, prompts, runtime config, or code must go through staging and PR review.
- Production mutation, deployment, restart, or external publication remains out of scope unless separately approved.

## Observability

Every review run should expose:

- bundle ID and schema version;
- originating command, PR, answer, recipe, or runtime artifact;
- reviewer lens and model/backend if applicable;
- finding counts by severity/type;
- proposal/gate/adoption status;
- redaction status;
- links to issue/PR/staged artifacts;
- cost and token budget when an LLM reviewer is used.

## Failure modes

| Failure mode | Mitigation |
| --- | --- |
| Reviewer hallucinates a blocker | Require evidence refs into the bundle; validate before patching. |
| Improvement overfits to one correction | Require regression proposal and held-out/replay gate. |
| Raw transcripts leak secrets | Use review bundles with redaction and retention classes. |
| Nightly optimizer learns a bad rule | Keep validation gate on; stage proposals; retain rejected edits. |
| Bundle lacks enough evidence | Mark incomplete and ask for source/proof instead of guessing. |
| Reviewer cost grows unbounded | Trigger on high-value events and cap tasks/tokens. |
| Product docs overclaim future work | Claim sweep and docs reviewer must compare docs to shipped commands/code. |

## MVP milestones

### M1 — Spec and issue stack

- Create this spec.
- Open the full GitHub issue stack.
- Link the tracker to `docs/OUT_OF_BOX_PRODUCT_PLAN.md`.

Tracking issue: [#157](https://github.com/pingchesu/sourcebrief/issues/157)

### M2 — Security baseline and bundle schema

- Define the artifact sensitivity, redaction, retention, permission-scope, purge, and reviewer-egress baseline before any durable capture path writes bundles.
- Define schema and examples against that safety baseline.
- Validate sample bundles and public-safe examples.

Issues: [#169](https://github.com/pingchesu/sourcebrief/issues/169), [#159](https://github.com/pingchesu/sourcebrief/issues/159)

### M3 — Minimum fixtures, taxonomy, and citation checks

- Define the finding taxonomy and output schema before the reviewer runner emits reports.
- Add minimum golden fixtures: unsupported claim, citation mismatch, safe passing answer, and rejected proposal.
- Add the deterministic citation-support fixture/check needed by the reviewer runner and validation gate.

Issues: [#162](https://github.com/pingchesu/sourcebrief/issues/162), [#172](https://github.com/pingchesu/sourcebrief/issues/172), [#167](https://github.com/pingchesu/sourcebrief/issues/167)

### M4 — Bundle capture and reviewer runner

- Persist bundles from `sourcebrief ask` and demo paths only after the M2 safety/schema baseline exists.
- Include citations, replay-critical metadata, completeness status, and tool proof.
- Run the reviewer agent over bundles and emit findings using the M3 taxonomy.

Issues: [#160](https://github.com/pingchesu/sourcebrief/issues/160), [#161](https://github.com/pingchesu/sourcebrief/issues/161)

### M5 — Proposals, gate, and staged adoption

- Convert findings to regression proposals.
- Validate candidate improvements before staging.
- Do not rely only on an LLM judge: the gate must include deterministic or mock-reviewer golden-suite checks from #172.
- Stage accepted proposals with receipts and explicit apply/adopt boundaries.

Issues: [#163](https://github.com/pingchesu/sourcebrief/issues/163), [#164](https://github.com/pingchesu/sourcebrief/issues/164), [#165](https://github.com/pingchesu/sourcebrief/issues/165), [#172](https://github.com/pingchesu/sourcebrief/issues/172)

### M6 — End-to-end MVP proof and observability

- Stitch the component issues into one vertical smoke path.
- Show bundle -> finding -> proposal -> gate -> staged artifact without silent mutation.
- Make review/regression history inspectable.

Issues: [#168](https://github.com/pingchesu/sourcebrief/issues/168), [#175](https://github.com/pingchesu/sourcebrief/issues/175)

### M7 — Product integrations after MVP proof

- Add PR review bundle integration.
- Add runtime-pack learning proposal support as a gated/staged target surface.
- Productize the story in README/recipes only after the MVP, security baseline, and golden fixtures have evidence.

Issues: [#166](https://github.com/pingchesu/sourcebrief/issues/166), [#173](https://github.com/pingchesu/sourcebrief/issues/173), [#171](https://github.com/pingchesu/sourcebrief/issues/171)

### M8 — Later sleep/replay loop

- Mine recurring validated failures from review artifacts.
- Replay against held-out bundles.
- Stage gated proposals.

Issue: [#170](https://github.com/pingchesu/sourcebrief/issues/170)

## Decision

Build SourceBrief self-improvement as event-triggered review bundles first, not as a raw-transcript nightly optimizer.

Rationale:

- Review bundles preserve evidence and reduce noise.
- Reviewer agents can run independently and asynchronously.
- Regression proposals make learning repeatable.
- Validation gates prevent harmful self-mutation.
- Staging/PR review keeps adoption reversible and auditable.

## Revisit triggers

Revisit this design if:

- reviewer findings cannot be tied to bundle evidence;
- the bundle schema cannot support PR, answer, recipe, and runtime cases;
- validation gates reject too many useful proposals due to weak evaluation data;
- review cost exceeds the value of caught failures;
- users need an always-on nightly sleep loop before event-triggered bundles are proven.

## Open implementation issues

- [#157](https://github.com/pingchesu/sourcebrief/issues/157) roadmap tracker
- [#158](https://github.com/pingchesu/sourcebrief/issues/158) this spec
- [#159](https://github.com/pingchesu/sourcebrief/issues/159) bundle schema; implementation baseline: [Review bundle schema](REVIEW_BUNDLE_SCHEMA.md)
- [#160](https://github.com/pingchesu/sourcebrief/issues/160) bundle capture; implementation baseline: [Review bundle capture](REVIEW_BUNDLE_CAPTURE.md)
- [#161](https://github.com/pingchesu/sourcebrief/issues/161) reviewer runner; implementation baseline: [Review bundle runner](REVIEW_BUNDLE_RUNNER.md)
- [#162](https://github.com/pingchesu/sourcebrief/issues/162) finding taxonomy; implementation baseline: [Reviewer finding taxonomy](REVIEW_FINDING_TAXONOMY.md)
- [#163](https://github.com/pingchesu/sourcebrief/issues/163) regression proposals; implementation baseline: [Regression proposal artifacts](REGRESSION_PROPOSALS.md)
- [#164](https://github.com/pingchesu/sourcebrief/issues/164) validation gate; implementation baseline: [Validation gate](VALIDATION_GATE.md)
- [#165](https://github.com/pingchesu/sourcebrief/issues/165) staged adoption; implementation baseline: [Staged adoption](STAGED_ADOPTION.md)
- [#166](https://github.com/pingchesu/sourcebrief/issues/166) GitHub PR integration; implementation baseline: [GitHub PR review bundles](GITHUB_PR_REVIEW.md)
- [#167](https://github.com/pingchesu/sourcebrief/issues/167) citation support checks; MVP deterministic check: [Citation-support check](CITATION_SUPPORT_CHECK.md)
- [#168](https://github.com/pingchesu/sourcebrief/issues/168) history and observability; implementation baseline: [Review history](REVIEW_HISTORY.md)
- [#169](https://github.com/pingchesu/sourcebrief/issues/169) security, privacy, retention; implementation baseline: [Self-improvement artifact security](SELF_IMPROVEMENT_SECURITY.md)
- [#170](https://github.com/pingchesu/sourcebrief/issues/170) nightly sleep/replay
- [#171](https://github.com/pingchesu/sourcebrief/issues/171) product docs
- [#172](https://github.com/pingchesu/sourcebrief/issues/172) golden regression suite; minimum fixtures: [Self-improvement golden fixtures](SELF_IMPROVEMENT_GOLDEN_FIXTURES.md)
- [#173](https://github.com/pingchesu/sourcebrief/issues/173) runtime-pack integration
- [#175](https://github.com/pingchesu/sourcebrief/issues/175) end-to-end MVP smoke path; proof command: [Self-improvement MVP smoke](SELF_IMPROVEMENT_MVP_SMOKE.md)
