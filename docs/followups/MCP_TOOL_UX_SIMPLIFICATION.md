# MCP tool UX simplification

## Problem

The MCP model is sound, but agents see many low-level tools and often need UUID-first multi-step workflows. The first-call path should be obvious, and follow-up calls should be guided by returned evidence handles.

## Scope

- Add high-level aliases while preserving precise tools:
  - `sourcebrief.ask` -> context answer
  - `sourcebrief.discover` -> sources + architecture overview
  - `sourcebrief.lookup` -> semantic/code/exact search routing where safe.
- Add `resource_ref` support to code/evidence drilldown tools where the server can resolve it safely:
  - read file
  - grep code
  - search code
  - find symbol.
- Improve MCP tool ordering/descriptions so agents start with context, sources, architecture, search/read, then advanced graph/proposal tools.
- Add suggested next tool calls to context responses when available.
- Ensure proposal/mutation-adjacent tools remain clearly opt-in/policy-bounded.

## Non-goals

- No source-control mutation from MCP aliases.
- No hiding security boundaries for convenience.
- No breaking existing tool names/schemas.

## Acceptance criteria

- Existing MCP clients keep working with old tools.
- New aliases appear with clear descriptions and tests.
- `resource_ref` paths resolve by human source name/ref without raw UUID when unambiguous.
- Ambiguous resource refs fail closed with useful errors.
- Integration tests cover tools/list and tools/call for aliases and at least one `resource_ref` drilldown.

## Verification

- `uv run python -m pytest tests/integration/test_manifest_diff_flow.py -q` or relevant MCP integration subset.
- Unit tests for resource-ref resolution and ambiguity handling.
- Real local MCP-shaped call proves alias response includes citations.
