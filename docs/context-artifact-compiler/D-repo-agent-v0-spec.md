# D — Repo Agent V0 Draft / Update / Publish Workflow Implementation Spec

Status: Draft v0.2 after adversarial review  
Branch: `feat/context-artifact-compiler-d-repo-agent-v0`  
Depends on: B0 deterministic Resource Map artifacts, B1 Context Pack versions, C generated Skill Export

## 1. Goal

Turn an indexed Git resource into a managed **Repo Agent V0** view without introducing an unconstrained autonomous coding agent.

Repo Agent V0 is a product/runtime view over one canonical Git `resource_id` plus:

- an explicit `pack_key` stream and pinned Context Pack version from that stream;
- optional approved generated Skill Export for local runtime install;
- refresh/update policy;
- draft version generated from source updates;
- manual publish gate;
- rollback history;
- install/runtime instructions.

This milestone must make repo-agent lifecycle visible and operable from UI/API while preserving the architecture decision that **Repo Agent is not a skill**. A Repo Agent can be useful with only a Context Pack and API/MCP runtime instructions. A generated skill is an optional adapter/export.

## 2. Non-goals

- No production mutation or write-capable repo operations.
- No auto-publish of behavior changes.
- No new generic agent table for all agent types yet; this is V0 repo-agent view scoped to Git resources.
- No unauthenticated or “signed-ish” webhook endpoint in this PR. UI/API refresh requires normal authenticated API access. External webhook support is deferred until it can include HMAC signature, timestamp/nonce replay protection, secret rotation, rate limiting, audit identity, and rotation UI.
- No LLM-authored summaries. V0 is deterministic from Resource Map, Context Pack, and optional Skill Export metadata.

## 3. User-facing behavior

A user can:

1. Select a Git source.
2. Create a Repo Agent V0 profile from it.
3. See current published agent version: source, pack version, optional skill export version/hash, freshness, install/runtime instructions.
4. Trigger refresh/reconcile.
5. See refresh status and draft generation result.
6. When the Git resource updates and a new Resource Map / Context Pack is available, see Repo Agent drafts with:
   - newest draft highlighted;
   - stale draft warning for older drafts;
   - changed files / manifest diff summary;
   - impacted context artifacts;
   - generated agent diff from current published version;
   - validation findings;
   - publish readiness.
7. Publish the newest valid draft manually. Older drafts are publish-disabled unless explicitly regenerated/current.
8. Roll back by creating a new published rollback version that copies the selected old version’s references and records rollback provenance.

## 4. Data model

### 4.1 `repo_agents`

Fields:

- `id uuid pk`
- `workspace_id uuid not null`
- `project_id uuid not null`
- `resource_id uuid null` — non-null for active/retained agent; null only after archive+scrub tombstone.
- `agent_key text not null`
- `pack_key text not null default 'default'` — explicit Context Pack stream used by this Repo Agent.
- `title text not null`
- `description text null`
- `status text not null` — `active`, `archived`.
- `update_policy_json jsonb not null default {"mode":"manual"}`
- `current_version_id uuid null`
- `created_by uuid null`
- `created_at timestamptz not null`
- `updated_at timestamptz not null`

Constraints:

- unique `(workspace_id, project_id, agent_key)`.
- unique `(workspace_id, project_id, resource_id, pack_key) WHERE resource_id IS NOT NULL` for V0, one active repo-agent per Git resource per pack stream.
- `agent_key` must match `^[a-z0-9][a-z0-9-]{2,62}$`; lowercase only; no path separators; reserved names: `new`, `settings`, `api`, `admin`, `current`, `versions`.
- `agent_key` is immutable in V0. Rename is a later explicit operation with redirect/deep-link policy.
- `current_version_id` has composite scoped FK to `(id, workspace_id, project_id, repo_agent_id)` via `repo_agent_versions` where supported by schema shape; API must also validate current version belongs to same repo-agent/workspace/project/resource.

### 4.2 `repo_agent_versions`

Fields:

- `id uuid pk`
- `workspace_id uuid not null`
- `project_id uuid not null`
- `repo_agent_id uuid not null`
- `resource_id uuid null` — non-null for active/retained version; null only after scrub tombstone.
- `version int not null`
- `status text not null` — `draft`, `published`, `superseded`, `invalidated`, `failed`.
- `source_snapshot_id uuid null` — null only after scrub or for failed compile before a snapshot exists.
- `resource_manifest_id uuid null` — null only after scrub or for failed compile before a manifest exists.
- `context_pack_version_id uuid null` — null for `failed` rows with `missing_context_pack` and after scrub.
- `skill_export_id uuid null`
- `version_hash text not null`
- `summary_json jsonb not null`
- `diff_json jsonb not null`
- `validation_json jsonb not null`
- `install_json jsonb not null`
- `rollback_from_version_id uuid null`
- `status_reason text null`
- `created_by uuid null`
- `created_at timestamptz not null`
- `published_by uuid null`
- `published_at timestamptz null`
- `scrubbed_at timestamptz null`

Constraints:

- unique `(repo_agent_id, version)`.
- active draft dedupe is application-level under repo-agent row lock; optional partial unique index may enforce `(repo_agent_id, version_hash) WHERE status='draft'` on Postgres.
- scoped FKs to resource, source snapshot, manifest, context pack version, optional skill export.
- DB cannot easily express “current version must be published” with a normal FK; API publish/rollback/invalidate must enforce under row lock, and tests must cover it.

## 5. Version hash

Canonical hash input:

```json
{
  "schema_version": "repo-agent.v0",
  "resource_id": "...",
  "source_snapshot_id": "...",
  "resource_manifest_id": "...",
  "context_pack_version_id": "...",
  "context_pack_hash": "sha256:...",
  "skill_export_id": "... or null",
  "skill_export_package_hash": "sha256:... or null",
  "update_policy": {"mode":"manual"},
  "rollback_from_version_hash": "... or null"
}
```

Volatile fields like created time, reviewer, status, and title are excluded.

## 6. Compile algorithm

`compile_repo_agent_version(session, repo_agent, actor, mode="refresh", rollback_from=None)`:

1. Validate resource type is `git` and visible in same workspace/project.
2. Resolve latest succeeded source snapshot and resource manifest.
3. Resolve current published Context Pack for `repo_agent.pack_key` whose coverage includes the resource. If absent, create `failed` draft with validation error `missing_context_pack`; `context_pack_version_id` and pack hash are null placeholders in hash input.
4. Resolve latest approved Skill Export for that Context Pack version if one exists. If absent, continue as pack-only with `skill_export_id=null`; validation warning `missing_skill_export` but `ok=true`.
5. Build deterministic summary:
   - resource name / URI / branch / commit if available;
   - manifest file counts / changed files from latest diff if available;
   - context pack version/hash;
   - optional skill export version/hash;
   - runtime tool contract: use ContextSmith APIs/MCP; read-only by default;
   - freshness timestamp.
6. Build diff against current published repo-agent version:
   - source snapshot changed;
   - manifest hash changed;
   - pack hash changed;
   - skill export package hash changed or missing/added;
   - file change summary if latest manifest diff exists.
7. Build install instructions:
   - pack-only runtime instructions always available;
   - generated skill install available only when approved Skill Export exists;
   - no bearer token in UI;
   - no production mutation permission;
   - skill download via authenticated UI action.
8. Persist `draft` or `failed` version unless an identical non-invalidated draft already exists.
9. For rollback, create a **new draft** copying target version references with `rollback_from_version_id`; publish flow then creates a new published version. V0 does not repoint current to a superseded row.

## 7. Refresh/reconcile semantics

V0 `refresh` endpoint is synchronous for repo-agent version compile, not a full Git webhook worker.

- It does **not** clone or index Git by itself.
- It checks latest completed index state already present in ContextSmith.
- It compiles a new repo-agent draft from the latest published Context Pack and optional approved Skill Export.
- It returns `{status: "draft"|"failed"|"unchanged", version, job_like_summary}`.
- If latest resource snapshot is stale relative to source update policy, UI shows “Source needs reindex first” and links to the Source update action.
- Idempotency: concurrent refresh uses `SELECT ... FOR UPDATE` on `repo_agents` and dedupes by `version_hash`.
- Version allocation: under repo-agent row lock, next version is `max(version)+1`.
- Future async refresh jobs can reuse the same compiler but are out of scope.

## 8. Lifecycle rules

All lifecycle mutations require comments and audit events.

### 8.1 Required scopes / actor types

- List/detail read: `resource:read` plus resource visibility.
- Create/refresh draft: `resource:write` or admin/session actor. Runtime read tokens cannot refresh.
- Publish/rollback/invalidate: `review:write` or admin/session actor with project access. Resource-scoped runtime/API tokens cannot publish, rollback, or invalidate even if they can read the resource.
- Download/copy generated skill remains governed by Skill Export approval rules from milestone C.

### 8.2 Publish

Under transaction:

1. Lock `repo_agents` row `FOR UPDATE`.
2. Resolve target version `FOR UPDATE`; verify same repo-agent/workspace/project/resource and `status=draft`.
3. Verify validation ok, Context Pack is `published`, optional Skill Export is `approved` if present.
4. Verify target is the newest non-invalidated draft for the agent. Older drafts require refresh/regenerate; UI disables publish.
5. Resolve current version `FOR UPDATE`; if present and `published`, set to `superseded` with reason.
6. Set target to `published`, `published_by`, `published_at`, comment.
7. Set `repo_agents.current_version_id=target.id`.
8. Commit and audit.

### 8.3 Rollback

Rollback creates a new draft from the selected historical published/superseded version:

1. Lock repo-agent row.
2. Validate target historical version belongs to same repo-agent and is `published` or `superseded`, not invalidated/scrubbed.
3. Create new draft with copied source/manifest/pack/export references, `rollback_from_version_id=target.id`, and diff showing current → rollback target.
4. Publish validation for rollback drafts allows the copied historical Context Pack if it is `published` or `superseded` and not `invalidated`/scrubbed. Copied Skill Export, when present, must be `approved` and not invalidated/scrubbed. Alternatively, if the operator wants the pack stream current pointer restored too, they must perform B1 Context Pack rollback first; UI explains both states.
5. User publishes that rollback draft using normal publish flow.

This keeps the current repo-agent version row status always `published`. It does not silently mutate the Context Pack current pointer.

### 8.4 Invalidate / scrub

- archived repo-agents reject refresh, publish, rollback-draft, and any mutation that creates retained resource references. Only invalidate, scrub, and read operations remain allowed.
- Draft/failed versions can be invalidated and scrubbed to unblock purge.
- Published current version cannot be invalidated unless another version is published first or the repo-agent is archived.
- If repo-agent is archived and the current published version is invalidated, `repo_agents.current_version_id` must be cleared in the same transaction; archived agents render with “no current runtime version.”
- Superseded versions can be invalidated with reason.
- Scrub operation clears `summary_json`, `diff_json`, `install_json`, `validation_json` to minimal tombstone, nulls `repo_agent_versions.resource_id`, `source_snapshot_id`, `resource_manifest_id`, `context_pack_version_id`, and `skill_export_id`, sets `scrubbed_at`; audit retains version id/status only. If all versions are scrubbed and the agent is archived, scrub may also null `repo_agents.resource_id` so resource hard purge can proceed while leaving an agent-key tombstone.

## 9. API

All endpoints require normal authenticated API access; no unsigned webhook endpoint.

- `GET /workspaces/{workspace_id}/projects/{project_id}/repo-agents`
- `POST /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/repo-agent` with body `{agent_key?, title?, pack_key}`; default `pack_key='default'` but UI must show the selected pack stream.
- `GET /workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}`
- `POST /workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}/refresh`
- `POST /workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}/versions/{version}/publish`
- `POST /workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}/versions/{version}/rollback-draft`
- `POST /workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}/versions/{version}/invalidate` with required reason; invalidates draft/failed/superseded versions, and current published only if the repo-agent is archived.
- `POST /workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}/archive` with required comment; sets `repo_agents.status='archived'`; if current version is invalidated during archive flow, clears `current_version_id`.
- `POST /workspaces/{workspace_id}/projects/{project_id}/repo-agents/{agent_key}/versions/{version}/scrub` with required reason; allowed only when repo-agent is archived and version is `invalidated` or `failed`; clears retained JSON/source refs. If all versions for the archived agent are scrubbed, also nulls `repo_agents.resource_id` to unblock resource hard purge while preserving agent-key tombstone.

API response includes human labels and hides internal IDs from primary UI affordances. Raw IDs may exist in JSON for clients but UI must not ask users to paste them.

## 10. UI

Add `/repo-agents` as a real page rather than placeholder.

### List view

- agents by title/key/source;
- current status;
- current version;
- freshness;
- pending draft count with newest draft highlighted;
- action: open, refresh.

### Detail view

- current published version panel;
- selected pack stream (`pack_key`) and coverage status;
- draft/update panel ordered newest first;
- stale draft warning and publish disabled for older drafts;
- version history;
- install/runtime instructions: pack-only and optional skill install;
- referenced Context Pack + optional Skill Export with links/actions;
- validation findings;
- publish/rollback-draft/invalidate with required comments.

### Source integration

On `/sources`, Git resources show:

- “Create / open Repo Agent” action;
- repo agent status in Source detail;
- if update created draft: visible callout.

## 11. Authorization and purge

- Resource-scoped tokens can read repo agents only if the underlying resource is allowed.
- Resource-scoped tokens cannot publish/rollback/invalidate.
- Publishing/rollback must verify both current and target versions reference resources visible to actor, and actor has `review:write`/admin session.
- Hard purge of a resource is blocked by retained repo-agent versions referencing it.
- Purge unblock path:
  1. archive repo agent;
  2. invalidate all retained versions, including current published; invalidating current while archived clears `current_version_id`;
  3. scrub every invalidated/failed version, nulling version resource/source/manifest/pack/export refs;
  4. once all versions are scrubbed, null `repo_agents.resource_id` tombstone;
  5. retry hard purge.
- Tests must assert invalidated-but-unscrubbed versions still block purge; scrubbed tombstones do not retain source metadata.

## 12. Observability

Audit events:

- `repo_agent.create`
- `repo_agent.refresh`
- `repo_agent_version.create`
- `repo_agent_version.publish`
- `repo_agent_version.rollback_draft`
- `repo_agent.archive`
- `repo_agent_version.invalidate`
- `repo_agent_version.scrub`

Structured logs include `repo_agent_id`, `agent_key`, `version`, `resource_id`, `context_pack_version_id`, and optional `skill_export_id`.

## 13. Real integration test plan

Use real Postgres/Redis/TestClient and existing resource/indexing paths.

1. Create controlled Git resource row with real snapshot/manifest/index state or use local bare Git fixture through existing indexing path.
2. Compile Resource Map, publish Context Pack, optionally approve Skill Export.
3. Create Repo Agent.
4. Refresh creates newest draft with correct source snapshot/manifest/selected pack/export references.
5. Pack-only mode works when no approved Skill Export exists.
6. Missing selected Context Pack creates failed version with null pack refs and `missing_context_pack` validation.
7. Publish draft sets current version and supersedes previous current under transaction.
8. Re-refresh with same inputs dedupes identical active draft.
9. Older draft cannot be published after a newer draft exists.
10. Resource-scoped denied token cannot read agent covering disallowed resource.
11. Resource-scoped allowed token can read but cannot publish/rollback/invalidate.
12. Rollback creates new rollback draft; publish makes it the only current published version even when referenced pack is superseded but not invalidated.
13. Archive rejects refresh/publish/rollback and allows current invalidation, which clears `current_version_id`.
14. Invalidate/scrub lifecycle requires comments and nulls source/manifest/pack/export/resource refs.
15. Resource purge blocked while repo-agent version retained; unblock after archive + invalidation + scrub nulls `repo_agent_versions.resource_id` and `repo_agents.resource_id` tombstone.
16. Migration downgrade/upgrade on real Postgres.
17. Web lint/build and browser QA for list/detail/source action.

## 14. Risks

- V0 one-agent-per-resource may not fit multi-pack agents. Acceptable; future v1 first-class agent object can generalize.
- Synchronous refresh only compiles from existing latest indexed state; users may expect it to clone. UI must say “Source needs reindex first” when applicable.
- Repo Agent page could become another technical table. Must show product-level source title, version, freshness, and next action.

## 15. Done definition

- Spec reviewed by Hermes adversarial backend + product reviewers and blockers fixed.
- Migration passes downgrade/upgrade.
- API + compiler implemented with auth tests.
- `/repo-agents` UI implemented and browser-tested.
- `/sources` links to repo-agent status/action.
- Full local gate and real integration tests pass.
- Hermes adversarial implementation review PASS.
- PR opened, merged, main synced.
