# Milestone 29 — Opt-in Patch and PR Workflow

Phase 6 adds a guarded patch/PR workflow for repo agents without changing the platform's default read-only posture.

## Scope

- Add `patch_proposals` and `pr_requests` records for durable auditability.
- Add `contextsmith.generate_patch` as an HTTP/MCP tool that builds unified diffs from authorized indexed snapshot files.
- Add `contextsmith.open_pr` as an HTTP/MCP tool that records explicit PR approval metadata.
- Surface an opt-in patch/PR panel on the Repo Agents page.
- Advertise patch/PR as optional capabilities in generated Skill Packs while preserving the read-only default contract.

## Safety Contract

Patch generation is disabled unless the project agent profile has `tool_policy.patch_generation == "enabled"`. Calls also require `project:query`, `code:read`, `patch:generate`, project membership, and resource authorization.

PR workflow is disabled unless `tool_policy.open_pr == "enabled"`. Calls require `pr:write`, project membership, and an explicit approval note. The current implementation records approval and PR metadata only; it does not push branches, mutate the source repository, run tests, deploy, or open a GitHub PR directly.

Generated patches include the indexed commit. If the caller provides a stale `base_commit`, the proposal is marked `branch_moved=true`, includes `source_branch_moved_since_base_commit`, and PR approval is rejected until the patch is regenerated.

## Observability

- `patch.generate` audit events record resource, scope, diff summary, and branch-moved status.
- `pr.open_record` audit events record patch proposal, resource, source branch, target branch, and diff summary.
- Resource purge deletes PR requests and patch proposals before deleting resources to preserve lifecycle safety.

## Verification

Planned gates for this milestone:

- Python lint/type checks for API/shared/worker code.
- Alembic upgrade against real Postgres.
- Integration tests for disabled-by-default policy, scope enforcement, branch freshness warnings, MCP tool error semantics, and PR approval records.
- Web TypeScript lint/build.
- Docker Compose startup and API/frontend smoke.
- Browser QA on `/repo-agents`.
- Hermes adversarial review to PASS before PR/merge.
