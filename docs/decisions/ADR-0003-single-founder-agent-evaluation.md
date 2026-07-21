# ADR-0003: Treat the single-founder agent council as internal evidence, not independent Gate A authority

- Status: Proposed
- Date: 2026-07-20
- Tracking: [#353](https://github.com/pingchesu/sourcebrief/issues/353)
- Parent experiment: [#346](https://github.com/pingchesu/sourcebrief/issues/346)
- Corpus commitment: [#351](https://github.com/pingchesu/sourcebrief/issues/351)

## Context

SourceBrief is operated by one accountable human, Joe Su. Hermes can create isolated Product, Eval/QA, provider/compiler, runtime/provenance, Security, and adversarial-audit sessions, but those sessions inherit founder-controlled infrastructure and often the same model family. They are useful workload roles; they are not people, independent owners, legal signers, or independent custody authorities.

The previous Gate A owner schema used names and contacts as a proxy for independence. One human could therefore use several aliases and satisfy the validator. Approval also needed to bind the corpus, hidden-test, baseline, contamination, runtime, challenge, and owner-acceptance commitments rather than only the manifest digest. A single HMAC can prove local integrity under one key, but it cannot prove that several humans approved or provide non-repudiation.

A runtime review also found that the old GREEN receipt named a wheel digest after its `dist/` bytes had been overwritten, normal preflight rewrote commitment files, and same-UID `0600` files did not isolate role agents. These are decision-integrity failures, not reasons to build more product surface.

## Decision

### 1. Keep independent Gate A strict

The normative Gate A manifest declares:

```json
{"mode": "independent_human", "human_independence": true}
```

Every owner is a typed human identity with a stable `human_id`. Eval/QA, provider/compiler, and Security require distinct human IDs, contacts, and names. Workload, service, bot, agent, and team identities are rejected from human-owner fields.

The D0 approval MAC binds:

- exact manifest and revision;
- owner-acceptance index;
- protected bundle and public commitment index;
- hidden-test index;
- GREEN, RED, contamination, and preflight receipts;
- runtime policy;
- QA and Security challenge receipts;
- the exact unsigned compiler projection;
- event issuer, key ID, nonce, sequence, validity window, actor, and required human role signers.

The MAC is explicitly an integrity control. The local validator therefore never emits independent D0 or promotion authority: it returns `integrity_checked_external_authority_required`, `d0_ready=false`, `promotion_authorized=false`, and `identity_claims_verified=false`. Production D0 requires a protected review/signing service, verified identities, per-principal acceptance evidence, replay/revocation state, and non-exportable key custody.

### 2. Add a non-interchangeable single-founder internal contract

`single_founder_internal` requires exactly one accountable human and six distinct typed workload identities. It always returns:

```json
{
  "authorization": "internal_signal_only",
  "d0_ready": false,
  "promotion_authorized": false
}
```

This governance object cannot itself be used as a Gate A manifest, approval, compiler authorization, or report. Agents may write and challenge internal evidence, but they cannot sign as humans or manufacture promotion authority. A separately versioned internal execution envelope is required before any run: it must bind this governance digest, a governance-neutral frozen experiment contract, immutable packs, authenticated/retrievable receipts, the direct-tools comparator, and the scorer version. Its only outcome is `internal_signal` (`positive`, `negative`, or `inconclusive`), while `d0_ready` and `promotion_authorized` remain false.

### 3. Preserve visibility boundaries

| Role | May read | May produce | Must not receive |
|---|---|---|---|
| Founder | Metadata commitments, lineage, redacted final report | One internal-run decision | Protected plaintext unless break-glass contamination is recorded |
| Eval/QA workload | Frozen source/task class and protected authoring workspace | Protected corpus, tests, commitments, grading receipts | Candidate packs or outputs before freeze |
| Provider/compiler workload | Pinned source, four development tasks, runtime contract | Immutable pack and compile receipts | Held-out tasks, controls, tests, expected outcomes |
| Runtime workload | Frozen schedule and one blinded cell at a time | Execution receipts and sealed outputs | Other cells, grader material, prior scores |
| Verifier workload | One sealed output plus matching private oracle | Authenticated task/control receipt | Candidate mutation authority |
| Security/audit workload | Commitments, ledgers, preserved artifact bytes | Challenge and recomputation receipts | Promotion authority |

All four arm packs freeze before any protected task is released. Execution uses fresh workspaces and sessions, one task at a time. A verifier—not the compiler, executor, or report writer—owns task verdicts and retained artifact references.

### 4. Distinguish process isolation from custody

Separate sessions, profiles, workdirs, and `0600` modes reduce accidental cross-role leakage but do not create independent custody when they share Joe's UID, host administration, gateway, logs, backups, or provider account. Independent Gate A requires separately accountable QA and Security humans plus separate host/account/key boundaries.

### 5. Optimize for one user outcome

This work does not authorize a provider marketplace, semantic graph rebuild, generic retrieval platform, generated-answer service, dashboard, CRUD console, schema expansion, or independent candidate tuning. Issue #354 separately governs one founder-controlled, non-promotional experiment. The next product decision remains whether one immutable reviewed source-specific pack materially improves held-out repository-maintenance outcomes over the strongest automated comparator, including ordinary Hermes with pinned repository tools and no SourceBrief, within the frozen safety, time, review, and cost budgets.

## Operational path

1. Pre-register candidate SourceBrief commit, scorer implementation, source, development tasks, arms, thresholds, runtime/model/prompt/policy identities, budgets, and pricing.
2. Produce or replace protected material inside the QA boundary and record all model/provider exposure.
3. Complete and seal all three compile repetitions before protected release; each receipt binds start/finish, first-use, active review, cost, retries, response, and pack, and repetition 1 is precommitted as the AI promotion pack. Freeze all four arm packs before the same release clock.
4. Release one randomized task/arm cell at a time to a fresh executor.
5. Grade in verifier custody and retain content-addressed outputs, tests, command records, packs, timings, and usage records.
6. Recompute the report from retrieved bytes and authenticated receipts; reject unattached digests, claimant booleans, hash-order tie breaks, and failure reasons whose typed subjects do not exactly match every computed affected item.
7. Show Joe a redacted internal verdict. Any break-glass access contaminates and rotates protected material.
8. Do not claim independent D0/PASS until separately accountable humans and custody controls replace the internal-only boundaries.

## Observability and evidence

Every invocation records workload role, provider/model/deployment, prompt/tool/policy digests, source/pack/input/output/transcript digests, host/account/session identity, start/end time, retries, cost, and parent invocation. A hash-chained contamination ledger records every protected-item exposure and rotation. Shared model/provider lineage is reported as correlated evidence, not multiplied into independent votes.

## Failure modes and controls

- **Role aliases fake independence:** stable typed human IDs and exact role constraints reject shared identities.
- **Agent substituted for human:** actor kinds and namespace validation fail closed.
- **One MAC presented as multisignature:** documentation and schema separate MAC integrity from human acceptance evidence.
- **Post-approval candidate/scorer substitution:** candidate commit and exact current scorer/validator module bytes are manifest commitments covered by detached approval and CAS replay; receipt or runtime scorer mismatches fail before scoring.
- **Opaque or partial randomization:** the authenticated mapping must parse as exactly 90 frozen held/control cells, with one unique slot for every item/lane pair, and every receipt must carry the matching blinded slot.
- **Direct-tools contamination:** retained command/diff bytes, authenticated `changed_paths`, and complete typed tool traces are inspected; every lane uses strict repo-relative file operations, task forbidden/allowed path enforcement with exact patch/write-to-`changed_paths` reconciliation, no test/lint output or cache flags, and single-line shell-free pytest/ruff/mypy through the exact pinned `python` token in a source archive without `.git` or VCS/control metadata. Per-lane sandbox receipts bind each cell to the pinned source tree, disabled egress, no external mounts, the frozen tool policy, and only its expected capability/reference pack; the direct lane has neither capability nor pack. Arbitrary modules, `python -c`, shell syntax, path escapes, or SourceBrief/ContextSmith calls invalidate the run.
- **Unattached review economics:** one human-review receipt binds approved reviewer, clocks, active minutes, worklog bytes, and the report scalar; compile economics derive from all three attempts.
- **Pack changes after freeze:** every per-arm freeze receipt must predate the authenticated protected-release clock and match the arm pack digest; any substitution or late freeze invalidates the run.
- **Same session carries task knowledge:** fresh principal/workspace/cache per cell; no scores return to later executors.
- **Report self-grades:** verifier-owned raw receipt bundle, co-best baseline union, typed failure-category/affected-subject equality, and byte replay are required before report validation can accept an evidence score; local validation never creates D0 or promotion authority.
- **Retained artifact missing:** every approval-bound evidence commitment, all 103 self-digested receipt payloads, and every referenced runtime artifact is opened as a non-symlink regular file from verifier-owned CAS and recomputed from raw bytes; missing, tampered, placeholder-only, or wrong-type artifacts fail closed.
- **Same model agrees with itself:** correlation is disclosed; agent consensus is advisory only.
- **Founder inspects protected bytes:** append break-glass exposure, invalidate affected material, rotate before reuse.
- **No target-user evidence:** do not generalize a bounded engineering signal into product-value claims.

## Reversibility and migration

The schema versions are additive. Existing v2 manifest/v1 approval artifacts are not silently reinterpreted as v3/v2. The QueueKeeper commitment remains PRE-D0. Internal-governance artifacts remain non-promotional and can be deleted without changing product data. If trustworthy isolation or verifier replay proves impractical, stop AI expansion and retain SourceBrief as a deterministic cited-evidence service under ADR-0002.

## Consequences

- A one-person company can use several professional agents productively without fabricating organizational independence.
- Integrity work precedes compiler work, reducing the risk of tuning against a self-graded benchmark.
- Real independent Gate A remains blocked on external human/custody controls; this is an explicit limitation, not a papered-over owner field.
- The design adds only the minimum contracts needed to make a future outcome decision trustworthy; it does not expand the product surface.
