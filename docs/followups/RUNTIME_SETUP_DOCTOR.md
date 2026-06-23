# Runtime setup and doctor workflow

## Problem

Runtime setup is safe but too procedural: users create tokens, generate plans, validate MCP, copy config, restart runtimes, and then separately confirm tool discovery. The safety model is right, but the workflow needs a guided CLI path and one diagnostic command.

## Scope

- Add `sourcebrief doctor` for local/API/runtime readiness checks.
- Add `sourcebrief runtime setup <target>` as a guided dry-run wrapper around existing token/plan/validate behavior.
- Add `sourcebrief token create-runtime` presets:
  - context-only scopes
  - remote-code read scopes.
- Improve validation output for MCP tools and citations.
- Keep Hermes apply guarded and explicit.

## Non-goals

- No silent local runtime mutation.
- No plaintext token persistence in generated artifacts.
- No non-Hermes apply unless separately implemented with equivalent guardrails.
- No production deployment/install scripts.

## Acceptance criteria

- `sourcebrief doctor` checks API reachability, selected/default IDs if available, auth mode, project/resource reachability, and MCP context path.
- `sourcebrief runtime setup hermes --dry-run` produces a readable plan and validator guidance.
- `sourcebrief token create-runtime --context-only` and `--read-code` generate correct scope sets.
- Existing `runtime plan/apply/rollback/validate` behavior remains compatible.
- Docs show when to use doctor/setup vs manual plan commands.

## Verification

- Unit tests for command construction and scope presets.
- Real local stack: doctor passes against a demo project.
- Runtime plan validator still works with redacted token output.
