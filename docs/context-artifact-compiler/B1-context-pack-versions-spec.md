# B1 — Context Pack Versions Implementation Spec

Status: Draft v0.2 after adversarial review  
Branch: `feat/context-artifact-compiler-b1-context-packs`  
Depends on: B0 Context Artifacts / Resource Map (`context_artifacts`, `context_artifact_sources`, `context_artifact_citations`)

## 1. Goal

B1 introduces durable, reviewable **Context Pack versions**: curated sets of approved Context Artifacts that can be pinned, published, rolled back, invalidated for retention/compliance, and used by runtime context construction.

A Context Pack is a product-facing release object between low-level artifacts and future generated skills/repo agents. It answers: "for this project and pack key, the runtime may use exactly these artifact revisions and their pinned source snapshot coverage."

## 2. Non-goals

- No generated Skill export yet.
- No repo-agent publish workflow yet.
- No graph merge yet.
- No LLM-generated summaries inside packs.
- No auto-publish from source refresh; pack publish is explicit.
- No UUID-first UX. UUID APIs may exist internally, but product/runtime flows must support `pack_key` + `current`/version aliases.

## 3. Product behavior

### 3.1 Pack identity

A Context Pack has a stable logical key inside a project:

- `default`
- `repo-agent`
- future user-created pack keys

Users operate on pack key and version number, not raw UUID. The UI can show a short hash for verification, but must not require users to paste UUIDs.

### 3.2 Pack lifecycle

A pack version can be:

- `draft`: created from approved artifacts; not runtime-selectable.
- `published`: the single current runtime-selectable version for `(workspace_id, project_id, pack_key)`.
- `superseded`: an older published version after another version was published.
- `rolled_back`: a version explicitly replaced by rollback.
- `invalidated`: no longer usable because covered source/artifact must be purged or compliance-retired.
- `failed`: validation failed; cannot publish.

Only `published` versions are runtime-selectable.

SourceBrief must show latest/current pack by key with status, version, hash, created/published times, artifact count, resource coverage, validation state, and rollback/invalidated state.

### 3.3 Publish

Publishing a draft pack:

1. Requires explicit `review:write`.
2. Requires a publish comment.
3. Validates all artifacts are approved and all covered resources are authorized.
4. Locks the pack key row set transactionally.
5. Marks existing `published` version for the same pack key as `superseded`.
6. Marks selected draft as `published`.

A partial unique index enforces at most one `published` version per `(workspace_id, project_id, pack_key)`.

### 3.4 Rollback

Rollback is a release action, not a silent state flip.

- Target must be `superseded`.
- Target must not already be the current `published` version.
- Request must include a rollback reason/comment.
- UI must show diff/impact summary: current version -> target version, added/removed artifacts/resources/snapshots.
- Transaction locks pack key row set.
- Current `published` becomes `rolled_back`.
- Target becomes `published`.

### 3.5 Invalidation / compliance escape hatch

B1 must not create an operational dead-end where a resource can never be hard-purged after being packed.

Add explicit invalidation:

`POST /workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions/{version}/invalidate`

- Requires `review:write`.
- Requires reason/comment.
- If invalidating current `published`, no current version remains until a new publish or rollback occurs.
- Invalidated packs are not runtime-selectable.
- Audit event records reason and actor.

Hard purge policy:

- If a resource is covered by any non-invalidated pack version, hard purge returns 409 with the list of pack keys/versions to invalidate first.
- After all covering pack versions are `invalidated`, hard purge may delete pack coverage rows and proceed.

This preserves compliance while keeping published packs immutable until explicitly invalidated.

## 4. Data model

### 4.0 `context_packs`

A parent row exists so every state transition can lock a stable pack identity, including first-version creation.

Columns:

- `id uuid pk`
- `workspace_id uuid not null fk`
- `project_id uuid not null fk`
- `pack_key text not null`
- `title text not null`
- `description text null`
- `created_by uuid null fk users`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Constraints/indexes:

- unique `(id, workspace_id, project_id)` for scoped child FKs.
- unique `(workspace_id, project_id, pack_key)`.
- CHECK `pack_key` matches `^[a-z0-9][a-z0-9._-]{0,62}$`.

Concurrency rule:

- Create/get parent pack row under a transaction.
- For every create/publish/rollback/invalidate operation, lock the parent row with `SELECT ... FOR UPDATE` before reading or mutating versions.
- If a concurrent create races on first pack creation and hits unique `(workspace_id, project_id, pack_key)`, retry by selecting and locking the existing parent row.

### 4.1 `context_pack_versions`

Columns:

- `id uuid pk`
- `workspace_id uuid not null fk`
- `project_id uuid not null fk`
- `context_pack_id uuid not null`
- `pack_key text not null`
- `version integer not null`
- `status text not null` — draft/published/superseded/rolled_back/invalidated/failed
- `title text not null`
- `description text null`
- `pack_hash text not null`
- `coverage_json jsonb not null default {}`
- `validation_json jsonb not null default {}`
- `created_by uuid null fk users`
- `published_by uuid null fk users`
- `published_at timestamptz null`
- `rolled_back_by uuid null fk users`
- `rolled_back_at timestamptz null`
- `invalidated_by uuid null fk users`
- `invalidated_at timestamptz null`
- `status_reason text null`
- `created_at timestamptz not null default now()`
- `updated_at timestamptz not null default now()`

Constraints/indexes:

- unique `(id, workspace_id, project_id)` for scoped child FKs.
- scoped FK `(context_pack_id, workspace_id, project_id)` -> `context_packs(id, workspace_id, project_id)`.
- unique `(workspace_id, project_id, pack_key, version)`.
- partial unique index on `(workspace_id, project_id, pack_key)` where `status = 'published'`.
- CHECK `status in ('draft','published','superseded','rolled_back','invalidated','failed')`.
- CHECK `version >= 1`.
- CHECK `pack_hash ~ '^sha256:[0-9a-f]{64}$'`.
- CHECK `jsonb_typeof(coverage_json) = 'object'` and `jsonb_typeof(validation_json) = 'object'`.
- index `(workspace_id, project_id, pack_key, status)`.
- index `(workspace_id, project_id, status, created_at)`.

### 4.2 `context_pack_artifacts`

Columns:

- `id uuid pk`
- `workspace_id uuid not null`
- `project_id uuid not null`
- `context_pack_version_id uuid not null`
- `context_artifact_id uuid not null`
- `resource_id uuid not null`
- `source_snapshot_id uuid not null`
- `resource_manifest_id uuid not null` — required to match B0 scoped artifact FK.
- `artifact_type text not null`
- `artifact_hash text not null`
- `ordinal integer not null`
- `created_at timestamptz not null default now()`

Scoped FKs:

- `(context_pack_version_id, workspace_id, project_id)` -> `context_pack_versions(id, workspace_id, project_id)`.
- `(context_artifact_id, workspace_id, project_id, resource_id, source_snapshot_id, resource_manifest_id)` -> `context_artifacts(id, workspace_id, project_id, resource_id, source_snapshot_id, resource_manifest_id)`.
- `(resource_id, workspace_id, project_id)` -> `resources(id, workspace_id, project_id)`.
- `(source_snapshot_id, workspace_id, project_id, resource_id)` -> `source_snapshots(id, workspace_id, project_id, resource_id)`.
- `(resource_manifest_id, workspace_id, project_id, resource_id, source_snapshot_id)` -> `resource_manifests(id, workspace_id, project_id, resource_id, source_snapshot_id)` if this scoped key exists; otherwise B1 migration must add it.

Constraints:

- unique `(context_pack_version_id, context_artifact_id)`.
- unique `(context_pack_version_id, ordinal)`.
- CHECK `ordinal >= 0`.
- CHECK `artifact_hash ~ '^sha256:[0-9a-f]{64}$'`.

### 4.3 `context_pack_resource_coverage`

Columns:

- `id uuid pk`
- `workspace_id uuid not null`
- `project_id uuid not null`
- `context_pack_version_id uuid not null`
- `resource_id uuid not null`
- `source_snapshot_id uuid not null`
- `resource_manifest_id uuid not null`
- `artifact_count integer not null`
- `citation_count integer not null`
- `created_at timestamptz not null default now()`

Scoped FKs mirror pack version/resource/snapshot/manifest.

Constraints:

- unique `(context_pack_version_id, resource_id, source_snapshot_id, resource_manifest_id)`.
- CHECK `artifact_count >= 0` and `citation_count >= 0`.

## 5. API

### 5.1 Create draft by pack key

`POST /workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions`

Payload:

```json
{
  "title": "Default context pack",
  "description": "Optional human description",
  "artifact_ids": ["..."]
}
```

Auth:

- `review:write` for all principals.
- explicit project membership.
- all artifacts must be readable by principal resource scopes.

Validation:

- all artifacts exist in same workspace/project.
- all artifacts are `approved`.
- no duplicate artifact IDs.
- no artifact with `failed`, `rejected`, or `draft` status.
- no duplicate `(resource_id, source_snapshot_id, artifact_type)` unless a future spec supports layers.
- compute deterministic `pack_hash` over ordered artifact IDs, artifact hashes, and coverage rows.

Version number: create or load the `context_packs` parent row, lock it with `SELECT ... FOR UPDATE`, then compute `max(version)+1`. If first-time concurrent creation hits the parent unique key, retry by selecting/locking the created parent row. Artifact validation and version insert happen under the same parent lock.

Response: full pack version with artifacts and coverage rows.

### 5.2 Product-safe list/get aliases

- `GET /workspaces/{workspace_id}/projects/{project_id}/context-packs`
  - returns pack keys with latest draft/current published/prior versions summary.
- `GET /workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions`
- `GET /workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions/{version}`
- `GET /workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/current`

Internal UUID route may also exist:

- `GET /workspaces/{workspace_id}/projects/{project_id}/context-pack-versions/{version_id}`

Auth:

- `resource:read`.
- requester must be authorized for every resource covered by the pack. Otherwise hide/404 the pack.

### 5.3 Publish by key/version

`POST /workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions/{version}/publish`

Payload:

```json
{"comment": "Reviewed and ready for runtime."}
```

Auth: `review:write` and project membership.

Validation:

- version exists and is `draft`.
- validation has no errors.
- requester can read all covered resources.

Transaction:

- lock the `context_packs` parent row for `(workspace_id, project_id, pack_key)` with `SELECT ... FOR UPDATE`.
- re-read selected version and current published version under that lock.
- re-run status validation, validation-json checks, and resource visibility checks under that lock.
- mark current `published` version `superseded`.
- mark selected draft `published`, set `published_at`, `published_by`, `status_reason`.
- rely on partial unique index for final protection.

### 5.4 Rollback by key/version

`POST /workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions/{version}/rollback`

Payload:

```json
{"reason": "Rollback because v4 removed required runbook coverage."}
```

Auth: `review:write` and project membership.

Validation:

- target status is `superseded`.
- target is not the current published version.
- requester can read all covered resources.

Transaction:

- lock the `context_packs` parent row for `(workspace_id, project_id, pack_key)`.
- re-read target and current published versions under that lock.
- re-run status validation and resource visibility under that lock.
- current `published` -> `rolled_back` with reason.
- target -> `published` with rollback reason and actor.

### 5.5 Invalidate by key/version

`POST /workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions/{version}/invalidate`

Payload:

```json
{"reason": "Resource requested for hard purge."}
```

Auth: `review:write` and project membership.

Validation:

- target not already `invalidated`.
- reason required.

Effect:

- lock the `context_packs` parent row for `(workspace_id, project_id, pack_key)`.
- re-read target under that lock.
- reject if already `invalidated`.
- target -> `invalidated`, set invalidation metadata.
- if target was current `published`, no current published version remains.

## 6. Runtime integration

Extend `AgentContextRequest` with product-safe selectors:

```py
context_pack_key: str | None = None
context_pack_version: int | Literal["current"] | None = "current"
context_pack_version_id: UUID | None = None  # internal/backcompat only
```

Rules:

1. If `context_pack_key` is supplied, resolve key + version. `current` means the single `published` version.
2. If `context_pack_version_id` is supplied, resolve it but still require `status == 'published'`.
3. Reject `draft`, `failed`, `superseded`, `rolled_back`, or `invalidated` for runtime with 409/422.
4. Enforce all covered resources allowed by token/session.
5. Enforce snapshot pinning. B1 runtime must not silently fall back to unpinned current retrieval.

Snapshot pin enforcement implementation:

- Minimum acceptable B1 behavior: when a context pack is supplied, construct the context packet from the pack's approved artifact citations and only those pinned `(resource_id, source_snapshot_id, resource_manifest_id)` rows. Retrieval/search may rank within those citations/sections, but it must not read newer snapshots.
- If a requested query cannot be served from pinned pack citations, return a clear empty result with `context_pack_snapshot_pin_enforced=true`, not unpinned current data.

Response diagnostics:

- `context_pack_key`
- `context_pack_version`
- `context_pack_version_id`
- `context_pack_status='published'`
- `context_pack_snapshot_pin_enforced=true`

## 7. UI

B1 should add a discoverable **Context Packs** surface. Minimum acceptable product scope:

- a top-level route or clearly visible Project Agent/Quality panel labeled `Context Packs`.
- no UUID paste flow.
- list pack keys, current published version, latest draft, status, hash, created/published times.
- create draft from selected approved artifacts.
- publish draft with required comment.
- rollback to superseded version with required reason and diff/impact summary.
- invalidate version with required reason and explicit warning if it removes current published pack.
- show artifact list and resource/snapshot coverage.
- show validation errors and why publish/runtime is blocked.

## 8. Purge/delete behavior

Resource hard purge behavior:

1. Query `context_pack_resource_coverage` for the resource.
2. If any covering pack version status is not `invalidated`, return 409 with pack key/version/status list and user action: invalidate pack version first.
3. If all covering pack versions are `invalidated`, delete pack coverage/artifact rows referencing the purged resource as part of hard purge, then proceed with B0/A4 purge order.

This creates an explicit compliance path while preserving pack immutability unless invalidated.

## 9. Tests

Real integration tests must cover:

1. Create approved Resource Map artifact, create draft pack, publish it by key/version.
2. Pack response includes immutable artifact and resource/snapshot/manifest coverage rows.
3. Creating pack from draft/rejected/failed artifact returns 422.
4. Viewer/session without `review:write` cannot publish/rollback/invalidate.
5. Resource-scoped token missing one covered resource cannot read pack (404/403).
6. Runtime `/agent-context` with `context_pack_key='default'` uses current published pack and returns pack diagnostics with `snapshot_pin_enforced=true`.
7. Runtime rejects non-published pack versions.
8. Rollback rejects current published/no-op, requires reason, and changes single current published version.
9. Partial unique published invariant prevents two current published versions.
10. Hard purge covered resource returns 409 until pack version invalidated; succeeds after invalidation.
12. Concurrent draft creation for same new pack key cannot create duplicate versions.
13. DB CHECK constraints reject invalid status/hash/negative counters.
14. Migration downgrade/upgrade on real Postgres.

## 10. Rollout / reversibility

- Additive migration; no mutation of existing B0 artifacts.
- If UI has issues, hide Context Packs route/panel without affecting Resource Maps.
- Rollback migration drops pack tables only. Before production launch, pack data is derived and can be regenerated from approved artifacts.

## 11. Observability / audit

Audit events:

- `context_pack.create_draft`
- `context_pack.publish`
- `context_pack.rollback`
- `context_pack.invalidate`

Logs/metrics should include pack key, version, status, artifact count, resource count, and actor.

## 12. Implementation order

1. Migration/model with `context_packs` parent row, scoped FKs, DB CHECK constraints, and partial unique published index.
2. Pack compiler/persistence helper with parent-row locking and retry on first-create race.
3. Create/list/get/publish/rollback/invalidate APIs with under-lock revalidation.
4. Runtime `agent-context` pack selector with pinned citation/section context.
5. Purge guard/update.
6. UI Context Pack surface.
7. Real integration and browser tests.
