# SourceBrief API main.py residual refactor map

Issue: #292, follow-up to #254.

## Current inventory

After the API router extraction train and CLI refactor train, `apps/api/sourcebrief_api/main.py` is no longer a one-file API surface, but it still contains the highest-coupling API orchestration code.

Current measured shape:

- `apps/api/sourcebrief_api/main.py`: 3,185 lines / 160,939 bytes / 88 top-level functions
- `packages/cli/sourcebrief_cli/main.py`: 236 lines / 9,564 bytes / 4 top-level functions
- Route contract coverage: `tests/unit/test_api_route_contract.py` snapshots 131 recursive route signatures and untagged OpenAPI metadata for the already-extracted routers
- Entrypoint growth guardrail: `tests/unit/test_entrypoint_size_guardrails.py` now caps API and CLI entrypoint line/function counts

## Keep in `main.py` for now

These are still acceptable entrypoint responsibilities and should remain until a wider API service-boundary refactor is planned:

- App assembly and startup wiring: `on_startup`, `_bootstrap_default_admin`, `app = create_app(...)`, router includes, dependency objects
- Compatibility aliases for private helpers that prior tests/callers import from `sourcebrief_api.main`
- Thin wrappers that inject `main.py` dependency callbacks into extracted routers/services to avoid circular imports

## Already extracted from `main.py`

The following API route families already live under focused router modules and are covered by route/OpenAPI contract tests:

- system health/provider routes
- auth/workspace/project/token routes
- resource core/lifecycle/artifact routes
- context-pack and skill-export routes
- repo-agent routes
- graph and graph-merge routes
- remote-code routes
- agent-context card-summary routes
- retrieval-eval routes
- runtime-agent/agent-pack routes
- MCP/context-packet route registration shell

## Residual high-coupling clusters

These clusters remain in `main.py` because they share access-control helpers, SQLAlchemy model queries, runtime/MCP tool dispatch, and compatibility aliases:

1. Project/auth/resource access helpers
   - Status: core access helpers were extracted to `sourcebrief_api.services.access`; `main.py` keeps compatibility aliases for injected router dependencies and existing private imports.
   - Still in `main.py`: `_validate_source_config`, because it depends on ingestion limits, git-env validation, and upload/folder policy wiring.

2. Agent-context synthesis and coverage helpers
   - Status: answer synthesis, citation-use selection, retrieval metadata, caveat/budget helpers, and unsupported-claim detection were extracted to `sourcebrief_api.services.agent_context_runtime`; `main.py` keeps compatibility aliases.
   - Still in `main.py`: full response builders `_build_agent_context_response` and `_build_pack_agent_context_response`, because they still orchestrate SQLAlchemy retrieval, usage persistence, code-search, coverage, and Context Pack queries.

3. MCP/runtime tool implementation
   - Status: MCP contract helpers, tool schema list, JSON-RPC result/error helpers, scope/remote-arg helpers, and runtime help text were extracted to `sourcebrief_api.services.mcp_runtime_contract`; `main.py` keeps compatibility aliases.
   - Still in `main.py`: MCP endpoint dispatch and runtime tool implementations such as `_runtime_search`, `_runtime_read_section`, `_runtime_graph_overview`, and `_runtime_lookup`, because they still orchestrate SQLAlchemy graph/resource queries and remote-code/router calls.
   - Risk: this is the most coupled cluster. Continue with route/OpenAPI parity plus targeted MCP tool-list/tool-call tests.

4. Context-packet action
   - Example: `_create_context_packet_action`
   - Extraction target: `sourcebrief_api.services.context_packets`
   - Risk: shares retrieval/query-run persistence with agent-context; split after agent-context service boundaries are explicit.

## Recommended migration path

Continue only with cohesive API service-boundary PRs, not one-route-per-issue churn:

1. Extract access/resource helper service while preserving `sourcebrief_api.main` compatibility aliases. (Core access helpers complete; `_validate_source_config` remains with resource config policy.)
2. Extract agent-context synthesis helpers and move direct unit imports to the service module while keeping aliases. (Core pure helpers complete; response builders remain.)
3. Extract MCP/runtime tool implementation as a single runtime service with explicit dependency injection. (Contract/schema helpers complete; dispatch and DB-backed tool actions remain.)
4. Extract context-packet action after agent-context/runtime service boundaries are stable.
5. Tighten `tests/unit/test_entrypoint_size_guardrails.py` API limits after each service extraction.

## Non-goals for #292

- No route path/method/schema changes.
- No `schemas.py` split yet; schema boundaries should follow service/router boundaries.
- No one-route-per-issue fan-out. The remaining surface is service orchestration, not isolated routers.
- No endpoint behavior changes in this audit PR.

## Observability and failure modes

Future extraction PRs must include:

- route signature parity from `tests/unit/test_api_route_contract.py`
- OpenAPI metadata parity for moved route families
- import-smoke proof that `sourcebrief_api.main.app` still loads
- compatibility alias smoke for any private helper still imported by tests or downstream code
- focused integration coverage for MCP `tools/list` and representative `tools/call` paths before moving MCP dispatch

The primary failure modes are silent OpenAPI metadata drift, circular imports from services back into `main.py`, broken private helper aliases, and token/resource-scope regressions in MCP runtime tools.

## Closure decision

#292 closes with this residual map plus the already-landed route contracts and entrypoint guardrails. The remaining API work is intentionally treated as future service-boundary extraction, not as incomplete route-router extraction under #254.
