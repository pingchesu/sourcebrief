# MCP tool UX simplification

## Implementation status

Implemented in this PR:

- Golden-path MCP aliases: `sourcebrief.ask`, `sourcebrief.discover`, and `sourcebrief.lookup`.
- `sourcebrief.get_agent_context` / `sourcebrief.ask` now return pinned `suggested_tool_calls` so agents know the next exact evidence tools to use.
- MCP `tools/list` now orders golden-path and evidence tools before advanced graph/proposal tools while keeping all existing tool names available.
- `resource_ref` works for ask/search/read-section and remote code drilldown paths where it can resolve to exactly one authorized resource. Context-pack search intersects `resource_ref` with pack coverage instead of widening back to the whole pack.
- `sourcebrief.lookup` returns docs results with a warning instead of failing the whole call when a context-only token lacks `code:read`.

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
