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
| Cited agent context | SourceBrief serves cited, permission-scoped context through HTTP/API, Workbench, CLI, and MCP-compatible runtime paths. | Current | `make qa-smoke`, `scripts/qa_smoke.py`, `docs/PROOF_ARTIFACTS.md` automated proof rows. | Blanket launch PASS still requires a declared-SHA README/E2E evidence bundle. |
| README-driven startup | A user can start the local Compose stack and reach API/web health from documented commands. | Current | `README.md`, `docs/QUICKSTART.md`, `make quickstart-doctor`, `make quickstart-ready` path. | Remote-browser setups must configure browser-visible API URL/CORS before build. |
| Screenshot-backed 50Q walkthrough | Current 50Q walkthrough shows the local-alpha proof path with session login, 50/50 mechanical pass, clean browser console/network transcript, UUID-safe public screenshots, and fail-fast browser-session validation. | RISK | `docs/evaluations/sourcebrief-launch-50q-20260630.md`, `docs/assets/screenshots/launch-50q-20260630/`, `scripts/launch_50q_walkthrough.py`, `tests/unit/test_launch_50q_walkthrough.py`. | Runner/artifact hygiene has been hardened; a fresh declared-SHA rerun is required before this lane is upgraded to launch PASS. |
| Real-corpus retrieval quality | SourceBrief has current real-corpus regression evidence with explicit RISK/PARTIAL accounting. | RISK | `docs/evaluations/real-corpus-regression-20260630/`, `examples/awesome-agent-harness-50q/README.md`. | #214 rerun is current but not PASS: providers are dev-quality, corpora are partial, and temporal-memory adoption/PASS claims are explicitly excluded from launch scope until a future provider/profile passes the temporal-memory 50Q gate. |
| Self-improvement surface | SourceBrief has an artifact-first self-improvement loop with browser proof for MVP smoke, redacted review history/detail, sleep dry-run, and no-silent-mutation boundaries. | Current | `docs/evaluations/self-improvement-browser-20260630/README.md`, `docs/SELF_IMPROVEMENT.md`, `docs/SELF_IMPROVEMENT_MVP_SMOKE.md`, `make qa-smoke` self-improvement path, `scripts/launch_50q_walkthrough.py` browser-origin CORS preflight. | Do not claim recurring autonomous learning or silent product mutation; random-port browser proof runners now fail before capture if the active web origin is missing from CORS config. |
| Runtime install/apply | Runtime setup produces dry-run plans; local apply is explicit, guarded, receipt-backed, and rollbackable. | Current | `docs/RUNTIME_INSTALL_PLAN.md`, `docs/AGENT_RUNTIME_USAGE.md`, CLI tests. | Real runtime config mutation remains an explicit local operator action. `sourcebrief doctor` is a lightweight smoke test; use generated runtime validators for full REST/MCP/citation validation. |
| Security boundaries | Workspace/project/resource/token boundaries have targeted tests and a hardened live probe path, but a fresh browser-transcript-backed probe output is still required for launch PASS. | RISK | `scripts/launch_security_probe.py`, `make launch-security-probe`, `tests/unit/test_launch_security_probe.py`, auth/security integration tests, `qa_smoke.py` denial checks. | The probe now fails closed for RISK and checks semantic false-premise/browser transcript/token cleanup behavior; a fresh declared-SHA probe bundle is required before upgrading this lane to Current/PASS. |
| Enterprise/public SaaS readiness | SourceBrief is enterprise-ready or safe for public internet deployment. | Unsupported | `docs/STATUS.md` non-goals. | Do not claim until separate hardening, SSO/SCIM, deployment, and ops tracks ship. |
| Production mutation | SourceBrief autonomously edits, tests, deploys, or opens PRs. | Unsupported | Trust-boundary docs and runtime docs. | SourceBrief is evidence infrastructure; mutation requires separate explicit tools/approval. |

## Rule for launch reports

A launch report may use **PASS** only when every claim it repeats is `Current` for the declared SHA and the security/failure-mode gate has passed. If any claim relies on `Historical` or `RISK` evidence, the launch report must use `RISK` with the linked caveat. Unsupported claims must be removed, not caveated.
