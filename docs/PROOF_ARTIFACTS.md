# Proof artifacts

SourceBrief documentation should show real evidence, not polished fiction. This page is the manifest for committed proof artifacts and the gaps that still need capture.

## What counts as proof

A proof artifact must be one of:

- a screenshot or GIF captured from a live local SourceBrief stack;
- a normalized API/CLI/MCP response captured from a live local run;
- an automated real-service integration test that exercises the behavior against Postgres/Redis/API code;
- an explicit follow-up entry saying the artifact is not captured yet.

Do not add mock screenshots, invented JSON, fake IDs, or hand-written "sample" output unless it is clearly labeled as illustrative and not proof.

## Committed visual proof

Visual artifacts below are real captured product proof, not mockups. When recapturing for a launch signoff, pair them with a redacted [E2E evidence bundle](E2E_EVIDENCE.md) that records the current commit, stack mode, `COMPOSE_PROJECT_NAME`, configured ports, capture date, redaction policy, and exact UI/command path.

| Artifact | What it proves | Source | Capture status |
| --- | --- | --- | --- |
| Product walkthrough GIF | Command Center -> Sources -> Workbench citation loop. | [`assets/sourcebrief-product-walkthrough.gif`](assets/sourcebrief-product-walkthrough.gif), [`WALKTHROUGH.md`](WALKTHROUGH.md) | Recaptured from the current live screenshot set after the first-source fix. |
| Command Center screenshot | Project readiness entry point. | [`assets/screenshots/sourcebrief-command-center.png`](assets/screenshots/sourcebrief-command-center.png) | Recaptured from a live local stack after the first-source fix; bundle with current commit for launch signoff. |
| Sources screenshot | Connected sources, indexing state, freshness/review surface. | [`assets/screenshots/sourcebrief-sources.png`](assets/screenshots/sourcebrief-sources.png) | Recaptured from a live local stack after the first-source fix; shows a successful Markdown source/index run. |
| Workbench citations screenshot | Human-visible cited context packet. | [`assets/screenshots/sourcebrief-workbench-citations.png`](assets/screenshots/sourcebrief-workbench-citations.png) | Recaptured from a live local stack as a citation-only crop so raw resource/snapshot IDs are not exposed. |
| Mental model diagram | Source -> snapshot -> evidence -> runtime flow. | [`assets/sourcebrief-mental-model.svg`](assets/sourcebrief-mental-model.svg) | Generated diagram; keep aligned with current Concepts wording. |
| Agent workflow diagram | Agent asks SourceBrief before local edit/test. | [`assets/sourcebrief-agent-workflow.svg`](assets/sourcebrief-agent-workflow.svg) | Generated diagram; keep aligned with runtime docs. |
| Trust boundary diagram | Read-only evidence service vs local runtime mutation boundaries. | [`assets/sourcebrief-trust-boundary.svg`](assets/sourcebrief-trust-boundary.svg) | Generated diagram; keep aligned with security boundaries. |

### Visual proof metadata

| Artifact set | Commit/PR | Stack/auth mode | Capture date | UI/command path | Redaction/currentness policy |
| --- | --- | --- | --- | --- | --- |
| Product walkthrough GIF + three screenshots | PR #104 / `6fd0df6` | Local Docker Compose stack, dev-auth demo session, configured local API/web URLs | 2026-06-26 | Command Center `/` -> Sources `/sources` -> Workbench citation card `/workbench` | Citation screenshot is cropped to the human evidence card and excludes raw resource/snapshot IDs; GIF is rebuilt only from the committed screenshots; launch signoff must pair recaptures with a fresh redacted bundle from `make collect-e2e-evidence`. |

## Committed runtime output proof

| Artifact | What it proves | Source |
| --- | --- | --- |
| Demo runtime output | Tiny deterministic source -> indexed snapshot -> `agent-context` and MCP-shaped response. | [`examples/demo-runtime-output.md`](examples/demo-runtime-output.md), [`DEMO.md`](DEMO.md) |
| Agent-context output | Real local walkthrough query returned cited context from indexed resources. | [`examples/agent-context-output.md`](examples/agent-context-output.md), [`WALKTHROUGH.md`](WALKTHROUGH.md) |

Internal UUIDs and token values are normalized or omitted in committed examples. That keeps the artifact readable and safe while preserving the response shape, citation policy, and runtime contract.

## Durable E2E evidence bundles

Use [`docs/E2E_EVIDENCE.md`](E2E_EVIDENCE.md) and `make collect-e2e-evidence` for launch or README-driven E2E signoff. The generated bundle lives under ignored `artifacts/e2e/<timestamp>/` and records:

- exact Git branch, SHA, and dirty state;
- sanitized `.env` summary;
- `COMPOSE_PROJECT_NAME` and configured ports/URLs;
- `docker compose ps` output;
- API/web health checks using configured URLs, not hard-coded defaults;
- command transcripts with exit codes when passed through `--command`;
- optional redacted files such as `artifacts/alpha-eval-report.json`.

This convention is the release evidence path; issue comments and terminal excerpts are supporting notes, not the durable bundle.

## Automated proof paths

These are not screenshots, but they are stronger than prose because they run against real services when `SOURCEBRIEF_RUN_REAL_INTEGRATION=1` is set.

| Behavior | Test evidence |
| --- | --- |
| Expanded MCP tools, aliases, `resource_ref`, pinned `read_section`, Context Pack scoping, graph overview. | `tests/integration/test_manifest_diff_flow.py::test_expanded_mcp_runtime_tools_f` |
| Agent-context API and MCP `tools/list` / `tools/call` contract. | `tests/integration/test_agent_integrations_flow.py::test_agent_context_api_and_mcp_tool_call` |
| Remote code search/grep/read/symbol MCP flow. | `tests/integration/test_remote_code_tools_flow.py::test_remote_code_http_and_mcp_flow` |
| Runtime setup/doctor/token preset behavior. | `tests/unit/test_cli.py` doctor/runtime/token tests plus real local smoke recorded in PR #68. |
| CLI selected defaults and `ask` golden path. | `tests/unit/test_cli.py` selected-default and ask tests plus real local smoke recorded in PR #67. |

Run the focused real-service proof:

```bash
SOURCEBRIEF_RUN_REAL_INTEGRATION=1 uv run python -m pytest \
  tests/integration/test_manifest_diff_flow.py::test_expanded_mcp_runtime_tools_f \
  tests/integration/test_agent_integrations_flow.py::test_agent_context_api_and_mcp_tool_call \
  tests/integration/test_remote_code_tools_flow.py::test_remote_code_http_and_mcp_flow -q
```

Run the full local release gate:

```bash
make verify
```

## Proof gaps / follow-ups

These are intentionally not faked in the current docs.

| Gap | Current status | Follow-up |
| --- | --- | --- |
| Resource Map rendered output | Real behavior is covered by API/integration paths, but no committed human-facing screenshot/output excerpt yet. | Capture Resource Map UI/API output from a real local run. |
| Context Pack rendered output | Context Pack behavior is covered by real integration tests, but no committed response excerpt yet. | Capture `get_context_pack` and pack-scoped `ask` output with normalized IDs. |
| Skill Export package example | Product behavior exists, but no committed approved export file tree/output excerpt yet. | Capture a real approved export manifest and validation report with IDs normalized. |
| Runtime doctor terminal transcript | CLI behavior is covered by tests and PR proof, but no stable committed transcript yet. | Capture `sourcebrief doctor --query` and `runtime setup hermes --dry-run` output from a clean local run. |

When adding one of these artifacts, include the command, stack assumptions, redaction policy, and what would fail if the feature regressed.
