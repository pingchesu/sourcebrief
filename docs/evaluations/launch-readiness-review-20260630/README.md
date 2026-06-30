# Launch readiness synthesis (#208 / #211)

Issue: [#211](https://github.com/pingchesu/sourcebrief/issues/211)
Parent: [#208](https://github.com/pingchesu/sourcebrief/issues/208)
Synthesis prepared after all #208 child risks were closed on current `main` at `54aea13` (`docs: exclude temporal adoption from launch scope`). This is a readiness synthesis, not a new full E2E rerun.

## Final verdict

**Close #208 as a completed local-alpha evidence/readiness train with explicit RISK lanes. Do not call it a blanket launch PASS.**

What is safe to say:

- SourceBrief has current committed evidence for README-driven local startup, cited agent context surfaces, screenshot-backed 50Q walkthrough, proof-gap closures, Skill Export approval/download, self-improvement review UI, runtime dry-run/apply boundaries, and real-corpus regression accounting.
- The previously validated child risks (#229, #231, #233, #234, #235) are closed or explicitly scoped out of launch claims.
- Customer-facing wording must continue to follow [`docs/CLAIM_LEDGER.md`](../../CLAIM_LEDGER.md): local-alpha evidence review is supported; public-SaaS/enterprise readiness, autonomous mutation, temporal-memory adoption, and blanket security/retrieval PASS claims remain unsupported or RISK.

What is not safe to say:

- “Production/public launch ready.”
- “Enterprise-ready.”
- “Temporal-memory retrieval is adopted/passing.”
- “Security boundary launch PASS” without a fresh declared-SHA, browser-transcript-backed probe bundle.
- “50Q/browser proof PASS for a final launch candidate” without a fresh declared-SHA rerun.

## Evidence inputs reviewed

| Evidence | Current status |
| --- | --- |
| Claim ledger | [`docs/CLAIM_LEDGER.md`](../../CLAIM_LEDGER.md) keeps launch-facing claims separated into Current / RISK / Unsupported. |
| Proof manifest | [`docs/PROOF_ARTIFACTS.md`](../../PROOF_ARTIFACTS.md) links committed screenshots, runtime proof, proof-gap closures, Skill Export, real-corpus, and self-improvement browser proof. |
| Screenshot-backed 50Q | [`sourcebrief-launch-50q-20260630.md`](../sourcebrief-launch-50q-20260630.md) records the current screenshot-backed 50Q walkthrough and now documents random-port/CORS reproducibility rules. |
| Proof gaps | [`proof-gaps-20260630/README.md`](../proof-gaps-20260630/README.md) closes Resource Map, Context Pack, and runtime doctor proof gaps. |
| Skill Export | [`skill-export-20260630/README.md`](../skill-export-20260630/README.md) closes approved/downloadable package proof with status wording clarified. |
| Real-corpus regression | [`real-corpus-regression-20260630/README.md`](../real-corpus-regression-20260630/README.md) records current real-corpus evidence as **RISK**, not PASS, and excludes temporal-memory adoption claims. |
| Self-improvement browser proof | [`self-improvement-browser-20260630/README.md`](../self-improvement-browser-20260630/README.md) verifies the artifact-first no-silent-mutation UI surface and documents the resolved CORS setup finding. |

## Child-risk disposition

| Issue | Resolution | Launch impact after closure |
| --- | --- | --- |
| [#229](https://github.com/pingchesu/sourcebrief/issues/229) | Closed by excluding temporal-memory adoption/PASS claims from launch scope until a future provider/profile passes the temporal-memory 50Q gate. | Keeps real-corpus/temporal claims at **RISK**; no longer blocks closing #208 as a scoped local-alpha train. |
| [#231](https://github.com/pingchesu/sourcebrief/issues/231) | Closed by adding a browser-origin CORS preflight to the proof runner and documenting matching `NEXT_PUBLIC_API_BASE_URL` / `SOURCEBRIEF_CORS_ORIGINS` in the isolated-stack convention. | Removes the random-port browser setup blocker; future proof capture fails fast instead of producing CORS-noise screenshots. |
| [#233](https://github.com/pingchesu/sourcebrief/issues/233) | Closed by hardening the launch-security probe: fail-closed semantics, false-premise checks, browser transcript requirement, token cleanup, and JSON secret redaction. | Probe path is trustworthy enough to use as a gate, but a fresh declared-SHA probe bundle is still required before claiming security-boundary PASS. |
| [#234](https://github.com/pingchesu/sourcebrief/issues/234) | Closed by hardening 50Q runner fail-fast behavior, public screenshot redaction, public hashes, and reproducibility docs. | Screenshot-backed 50Q evidence is useful and public-safe; final launch PASS still requires a fresh declared-SHA rerun. |
| [#235](https://github.com/pingchesu/sourcebrief/issues/235) | Closed by distinguishing package-generation status from authoritative SourceBrief export approval state and refreshing public proof artifacts. | Skill Export proof can be described as approved/downloadable without contradictory draft-only README wording. |

## Local verification for this final synthesis

```text
launch synthesis docs audit ok
33 passed in focused launch-train unit suites
```

Focused suites:

```text
tests/unit/test_launch_50q_walkthrough.py
tests/unit/test_skill_export_contract.py
tests/unit/test_launch_security_probe.py
```

Docs audit:

```text
docs/evaluations/launch-readiness-review-20260630/README.md
docs/CLAIM_LEDGER.md
docs/evaluations/sourcebrief-launch-50q-20260630.md
```

## Five-role final review

| Role | Final verdict | Rationale |
| --- | --- | --- |
| CEO / customer trust | **RISK, acceptable for local-alpha evidence review only** | The narrative is now bounded: no enterprise/public-SaaS, no autonomous mutation, no temporal-memory adoption claim. |
| CTO / architecture, ops, security | **RISK, not production launch PASS** | Architecture/proof runners are more trustworthy, but final security/50Q PASS requires fresh declared-SHA run bundles. |
| PO / onboarding and customer value | **Current for local-alpha story with caveats** | The product story has screenshots, Skill Export, proof gaps, self-improvement UI, and runtime docs, with claim ledger guardrails. |
| Tech Lead / reproducibility | **RISK but tracked/operable** | Random-port browser CORS, screenshot hygiene, token cleanup, and package-status mismatches were fixed; remaining upgrade path is explicit rerun evidence. |
| QA Lead / acceptance/flakiness | **RISK for launch PASS** | Focused regressions pass and child blockers are closed, but QA should not sign a blanket PASS without fresh end-to-end declared-SHA bundles. |

## Final synthesis boundary

#208 is complete as a launch-train closure because every validated child gap is closed, converted into claim-scope exclusion, or carried as an explicit non-goal in the claim ledger. The final output is **not** “SourceBrief is launch PASS”; it is:

> SourceBrief has a current local-alpha evidence package with explicit RISK lanes. It is suitable for bounded evidence review and continued alpha iteration. Upgrade to a blanket launch PASS requires fresh declared-SHA README/E2E, 50Q/browser, and launch-security bundles with the claim ledger showing no repeated RISK/Unsupported claims.
