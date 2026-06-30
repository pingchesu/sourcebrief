# SourceBrief claim ledger

This ledger keeps launch-facing wording tied to current proof. It is intentionally stricter than marketing copy: a claim is safe only when the evidence is current for the named candidate or explicitly labeled historical.

## Status labels

| Status | Meaning |
| --- | --- |
| Current | Verified on the declared launch candidate SHA or a newer named SHA. |
| Historical | Real evidence exists, but it was captured on an older commit/run and cannot prove the current candidate by itself. |
| RISK | Mechanically demonstrated, but quality, corpus, provider, UX, or proof gaps remain. |
| Unsupported | Do not use in customer-facing wording. |

## Launch-facing claims

| Claim | Allowed wording | Status | Evidence | Caveat / blocker |
| --- | --- | --- | --- | --- |
| Local alpha scope | SourceBrief is a local alpha for development and product exploration. | Current | `docs/STATUS.md`, `docs/QUICKSTART.md`, `docker compose config -q`, quickstart doctor. | Not public-internet or enterprise-SaaS ready. |
| Cited agent context | SourceBrief serves cited, permission-scoped context through HTTP/API, Workbench, CLI, and MCP-compatible runtime paths. | Current | `make qa-smoke`, `scripts/qa_smoke.py`, `docs/PROOF_ARTIFACTS.md` automated proof rows. | Current launch signoff still requires a fresh #209 evidence bundle. |
| README-driven startup | A user can start the local Compose stack and reach API/web health from documented commands. | Current | `README.md`, `docs/QUICKSTART.md`, `make quickstart-doctor`, `make quickstart-ready` path. | Remote-browser setups must configure browser-visible API URL/CORS before build. |
| Screenshot-backed 50Q walkthrough | Current 50Q walkthrough screenshots show the local-alpha proof path with session login, isolated stack, 50/50 mechanical pass, and clean browser console/network transcript. | Current | `docs/evaluations/sourcebrief-launch-50q-20260630.md`, `docs/assets/screenshots/launch-50q-20260630/`. | Broader launch readiness still depends on remaining #211/#212/#213/#214 evidence and parent #208 signoff. |
| Real-corpus retrieval quality | SourceBrief has current real-corpus regression evidence with explicit RISK/PARTIAL accounting. | RISK | `docs/evaluations/real-corpus-regression-20260630/`, `examples/awesome-agent-harness-50q/README.md`. | #214 rerun is current but not PASS: providers are dev-quality, corpora are partial, and temporal-memory gate is tracked by #229. |
| Self-improvement surface | SourceBrief has an artifact-first self-improvement loop with no-silent-mutation boundaries. | RISK | `docs/SELF_IMPROVEMENT.md`, `docs/SELF_IMPROVEMENT_MVP_SMOKE.md`, `make qa-smoke` self-improvement path. | #213 browser proof is required before including it in launch screenshots. |
| Runtime install/apply | Runtime setup produces dry-run plans; local apply is explicit, guarded, receipt-backed, and rollbackable. | Current | `docs/RUNTIME_INSTALL_PLAN.md`, `docs/AGENT_RUNTIME_USAGE.md`, CLI tests. | Real runtime config mutation remains an explicit local operator action. |
| Security boundaries | Workspace/project/resource/token boundaries are covered by a live launch-security probe plus targeted tests, including test-token revocation. | Current | `scripts/launch_security_probe.py`, `make launch-security-probe`, `tests/unit/test_launch_security_probe.py`, auth/security integration tests, `qa_smoke.py` denial checks. | Current launch PASS still requires the probe output bundled for the declared SHA and browser console/network proof from #210/#213. |
| Enterprise/public SaaS readiness | SourceBrief is enterprise-ready or safe for public internet deployment. | Unsupported | `docs/STATUS.md` non-goals. | Do not claim until separate hardening, SSO/SCIM, deployment, and ops tracks ship. |
| Production mutation | SourceBrief autonomously edits, tests, deploys, or opens PRs. | Unsupported | Trust-boundary docs and runtime docs. | SourceBrief is evidence infrastructure; mutation requires separate explicit tools/approval. |

## Rule for launch reports

A launch report may use **PASS** only when every claim it repeats is `Current` for the declared SHA and the security/failure-mode gate has passed. If any claim relies on `Historical` or `RISK` evidence, the launch report must use `RISK` with the linked caveat. Unsupported claims must be removed, not caveated.
