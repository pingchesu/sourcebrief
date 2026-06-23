# CLI ergonomics golden path

## Implementation status

Implemented in this PR:

- `sourcebrief use` persists workspace/project defaults in a local JSON config.
- `sourcebrief status` reports selected defaults and auth mode without exposing tokens.
- `sourcebrief ask "question"` calls the same runtime-shaped context path as `agent-context`.
- `search`, `agent-context`, `mcp-context`, and `resource list` can use selected workspace/project defaults when IDs are omitted.
- Explicit `--workspace-id` / `--project-id` still override saved defaults.

## Problem

The README/front-door rewrite made SourceBrief easier to understand, but the CLI still feels lower-level than the product story. First-time users must pass workspace/project/resource IDs through many commands, and the most common runtime query is named `agent-context` instead of the simpler action users expect: ask SourceBrief.

## Scope

- Add a human command for asking cited project context:
  - `sourcebrief ask "question"`
  - keep `agent-context` as the explicit/API-shaped command.
- Add persistent local selection for workspace/project defaults:
  - `sourcebrief use --workspace-id ... --project-id ...`
  - `sourcebrief status`
  - default config path under the user config directory.
- Teach existing read/query commands to use selected defaults when IDs are omitted where safe:
  - `ask`
  - `search`
  - `agent-context`
  - `mcp-context`
  - resource list where applicable.
- Update quick docs and CLI help.

## Non-goals

- No production auth model change.
- No server-side schema changes unless needed for name lookup.
- No silent resource scope widening.
- No removal of explicit `--workspace-id` / `--project-id` flags.

## Acceptance criteria

- `sourcebrief use --workspace-id <id> --project-id <id>` persists defaults locally.
- `sourcebrief status` prints selected API URL, workspace ID, project ID, and auth mode without secrets.
- `sourcebrief ask "..."` calls the same runtime-shaped context path as `agent-context` and returns citations.
- Existing explicit flags override persisted defaults.
- Unit tests cover config load/save and command fallback behavior.
- Docs explain the new golden path without replacing advanced UUID/API flows.

## Verification

- `uv run python -m pytest tests/unit -q`
- `uv run python -m ruff check apps packages tests scripts`
- `uv run python -m mypy apps packages scripts --ignore-missing-imports --follow-imports=silent`
- Real local demo: select a demo workspace/project and run `sourcebrief ask`.
