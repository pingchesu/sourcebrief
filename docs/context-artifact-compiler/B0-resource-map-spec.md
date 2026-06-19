# B0 — Deterministic Resource Map and Context Artifact Foundation Spec

Status: Draft v0.3 after adversarial review  
Branch: `feat/context-artifact-compiler-b0-resource-map`  
Depends on: A1 manifests, A2 folder bundle upload, A3 manifest diff, A4 section extraction/reuse

## 1. Goal

B0 introduces the first compile-time artifact layer: a deterministic Resource Map artifact built from folder-bundle manifests and snapshot sections. It is not an LLM summary. It is a machine-verifiable map of source paths and sections with provenance, coverage, validation, and review state.

## 2. Non-goals

- No generated skill export.
- No Context Pack publish/rollback.
- No graph merge.
- No LLM summarization.
- No runtime packet changes.
- No auto-publish. Compiled artifacts remain local drafts/approved artifacts until B1.

## 3. Product behavior

For a folder-bundle source with a completed snapshot:

- User can compile a Resource Map from the current snapshot.
- UI shows compile status, validation state, file/section coverage, source entries, and provenance.
- User can approve or reject a draft with an explicit reason/comment.
- Validation errors block draft creation and approval; warnings require explicit acknowledgement before approval.
- No raw UUIDs as primary UX. Short hashes and timestamps may be shown for audit.

## 4. Compile preflight vs artifact lifecycle

B0 separates **preflight failures** from **artifact validation failures**.

Preflight failures return HTTP errors and do **not** create `context_artifacts` rows:

- resource missing / unauthorized -> 404
- no current snapshot -> 409
- no current manifest -> 409
- manifest is not for the selected resource/snapshot -> 409
- no snapshot sections table available due migration/config error -> 503

Artifact lifecycle statuses:

- `draft`: compile completed and validation has no errors. May have warnings.
- `approved`: reviewer approved a draft.
- `rejected`: reviewer rejected a draft with reason.
- `failed`: reserved for failures after prerequisites exist and a deterministic error artifact can be hashed, e.g. canonicalization failure or citation integrity check failure after the manifest/section inputs were loaded. `failed` artifacts have valid non-null snapshot/manifest FKs, a deterministic `artifact_hash` over an error payload, `content_json={}`, no source/citation rows, and `error_message`.

Allowed transitions:

- `draft -> approved`
- `draft -> rejected`
- `failed -> draft` only by recompiling successfully; no in-place mutation from failed to draft.
- `approved` and `rejected` are terminal in B0.

Idempotency:

- `artifact_revision int not null default 1`.
- Unique `(workspace_id, project_id, resource_id, source_snapshot_id, artifact_type, artifact_hash, artifact_revision)`.
- Recompile same hash returns existing latest `draft` or `approved` artifact.
- If latest same hash is `rejected`, recompile returns rejected artifact with message unless `force=true`.
- `force=true` may create a new `draft` with next revision only when latest same hash is `rejected` or `failed`.

## 5. Data model

### `context_artifacts`

Columns:

- `id uuid pk`
- `workspace_id uuid not null fk`
- `project_id uuid not null fk`
- `resource_id uuid not null fk resources.id`
- `source_snapshot_id uuid not null fk source_snapshots.id`
- `resource_manifest_id uuid not null fk resource_manifests.id`
- `artifact_type text not null` — B0 supports `resource_map`
- `artifact_revision int not null default 1`
- `status text not null` — `draft|approved|rejected|failed`
- `artifact_hash text not null`
- `title text not null`
- `summary text null`
- `content_json jsonb not null default '{}'`
- `coverage_json jsonb not null default '{}'`
- `validation_json jsonb not null default '{}'`
- `error_message text null`
- `created_by uuid null fk users.id`
- `approved_by uuid null fk users.id`
- `approved_at timestamptz null`
- `rejected_by uuid null fk users.id`
- `rejected_at timestamptz null`
- `review_comment text null`
- `created_at timestamptz not null default now()`

Constraints:

- FK `(source_snapshot_id, workspace_id, project_id, resource_id)` -> `source_snapshots(id, workspace_id, project_id, resource_id)`.
- FK `(resource_manifest_id, workspace_id, project_id, resource_id, source_snapshot_id)` -> `resource_manifests(id, workspace_id, project_id, resource_id, source_snapshot_id)`.
- Unique `(id, workspace_id, project_id, resource_id, source_snapshot_id, resource_manifest_id)` for scoped child FKs.
- Unique `(workspace_id, project_id, resource_id, source_snapshot_id, artifact_type, artifact_hash, artifact_revision)`.
- status check, hash format check, revision >= 1.

### `context_artifact_sources`

Columns:

- `id uuid pk`
- `workspace_id uuid not null`
- `project_id uuid not null`
- `context_artifact_id uuid not null`
- `resource_id uuid not null`
- `source_snapshot_id uuid not null`
- `resource_manifest_id uuid not null`
- `resource_manifest_file_id uuid not null`
- `normalized_path text not null`
- `status text not null`
- `section_count int not null`
- `coverage_status text not null` — `covered|warning|empty|unsupported|failed|skipped`
- `metadata_json jsonb not null default '{}'`
- `created_at timestamptz not null default now()`

Constraints:

- FK `(context_artifact_id, workspace_id, project_id, resource_id, source_snapshot_id, resource_manifest_id)` -> `context_artifacts` scoped unique.
- FK `(resource_manifest_file_id, workspace_id, project_id, resource_id, resource_manifest_id)` -> `resource_manifest_files` scoped unique.
- Unique `(id, workspace_id, project_id, context_artifact_id, resource_manifest_file_id, resource_id, source_snapshot_id, resource_manifest_id, normalized_path)` for citation FKs.
- Unique `(context_artifact_id, normalized_path)`.
- Coverage status check.

### `context_artifact_citations`

Columns:

- `id uuid pk`
- `workspace_id uuid not null`
- `project_id uuid not null`
- `context_artifact_id uuid not null`
- `context_artifact_source_id uuid not null`
- `resource_id uuid not null` — same as A4 `SnapshotSection.version_resource_id`
- `section_family_resource_id uuid not null`
- `source_snapshot_id uuid not null`
- `resource_manifest_id uuid not null`
- `resource_manifest_file_id uuid not null`
- `section_id uuid not null`
- `snapshot_section_id uuid not null`
- `normalized_path text not null`
- `ordinal int not null`
- `title text null`
- `content_hash text not null`
- `line_start int null`
- `line_end int null`
- `created_at timestamptz not null default now()`

B0 must first add this scoped unique to A4 `snapshot_sections`:

- Unique `(id, workspace_id, project_id, version_resource_id, section_family_resource_id, source_snapshot_id, resource_manifest_id, resource_manifest_file_id, normalized_path)`.

Citation constraints:

- FK `(snapshot_section_id, workspace_id, project_id, resource_id, section_family_resource_id, source_snapshot_id, resource_manifest_id, resource_manifest_file_id, normalized_path)` -> `snapshot_sections` scoped unique.
- FK `(section_id, workspace_id, project_id, section_family_resource_id)` -> `sections` scoped unique.
- FK `(context_artifact_source_id, workspace_id, project_id, context_artifact_id, resource_manifest_file_id, resource_id, source_snapshot_id, resource_manifest_id, normalized_path)` -> `context_artifact_sources` scoped unique.
- Unique `(context_artifact_id, snapshot_section_id)`.

### Purge/delete behavior

Hard purge distinguishes version resources from family-root resources.

Version-resource purge order for a resource that has B0/A4 artifacts:

1. `context_artifact_citations` where `resource_id = purged resource id` or artifact belongs to purged resource.
2. `context_artifact_sources` for those artifacts.
3. `context_artifacts` for the purged resource.
4. A4 `snapshot_sections` where `version_resource_id = purged resource id` before deleting manifest files/manifests/snapshots.
5. A1 `resource_manifest_files` and `resource_manifests`.
6. `source_snapshots`.
7. `resources`.

Family-root purge policy:

- If the purged resource is referenced as `section_family_resource_id` by surviving `sections`, `snapshot_sections`, or `context_artifact_citations` belonging to any other version resource, B0 must reject hard purge with HTTP 409 and a product-facing message: “This source family still has compiled versions. Delete dependent versions first.”
- B0 does not cascade-purge an entire source family implicitly. Family-wide cascade can be a later explicit admin operation with its own confirmation and tests.
- Only when no surviving version/artifact references the root may the root resource be deleted.

`sections` cleanup policy:

- Do not delete shared family `sections` while any `snapshot_sections` or `context_artifact_citations` reference them.
- After deleting all `snapshot_sections` for a version resource, opportunistically delete orphan `sections` for the same `(workspace_id, project_id, section_family_resource_id)` with `NOT EXISTS` references from `snapshot_sections` and `context_artifact_citations`.
- For version resources in a family, deleting the version must not delete section rows still referenced by another version or artifact.

Integration must cover both cases: hard-purge a soft-deleted version resource with compiled Resource Map, and reject hard-purge of a family root while sibling versions/artifacts still reference it.

## 6. Compiler semantics

Input:

- folder-bundle `Resource`
- current `SourceSnapshot`
- current `ResourceManifest`
- `ResourceManifestFile[]`
- `SnapshotSection[]` joined to `Section[]`

Canonical JSON:

- sorted keys, compact separators, UTF-8.
- source entries sorted by normalized path, sections by ordinal.
- no raw full source body and no `Section.content_text`.
- section entries include title, ordinal, line range, content hash, and optional redacted preview max 160 chars.
- artifact hash = sha256(canonical JSON).

Coverage mapping for A4 manifest file statuses:

- `parsed` or `pending` with `section_count > 0` and no warnings -> `covered`.
- `parsed` or `pending` with warnings and `section_count > 0` -> `warning`.
- `parsed` or `pending` with `section_count == 0` -> `empty` warning.
- `unsupported` -> `unsupported` warning.
- `skipped` -> `skipped` warning.
- `failed` -> validation error and coverage `failed`.
- Unknown status -> validation error.

Validation:

- Errors: provenance mismatch, missing scoped row after preflight, citation row cannot link to same snapshot/resource/manifest/path, invalid content hash, any file coverage `failed`, unknown file status.
- Warnings: unsupported/skipped/empty file, parser warnings, zero-section artifact.
- If validation has errors after prerequisites exist: create `failed` artifact with deterministic error hash, return 409, no source/citation rows.
- If only warnings: create `draft` with warnings.

## 7. API and authorization

All endpoints enforce project access and resource/token scope. Unauthorized/disallowed resource access returns 404.

### Compile Resource Map

`POST /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/context-artifacts/resource-map?force=false`

- Requires project member/admin and `resource:refresh` scope for API tokens.
- Requires resource-scope permission for `resource_id`.

### List artifacts

`GET /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/context-artifacts?artifact_type=resource_map`

- Requires `resource:read` and resource scope.

### Get artifact detail

`GET /workspaces/{workspace_id}/projects/{project_id}/context-artifacts/{artifact_id}`

- Requires `resource:read` and resource scope after loading artifact.
- Returns 404 if artifact resource is outside token scope.

### Approve draft

`POST /workspaces/{workspace_id}/projects/{project_id}/context-artifacts/{artifact_id}/approve`

Body: `{ "comment": "reviewed coverage", "acknowledge_warnings": true }`

- Requires human project member/admin session OR API token with `review:write`; `resource:refresh` is not sufficient.
- Only `draft` can be approved.
- If warnings exist and `acknowledge_warnings` is false, return 422 with warning summary.
- Validation errors can never be approved.
- Records review fields and audit event.

### Reject draft

`POST /workspaces/{workspace_id}/projects/{project_id}/context-artifacts/{artifact_id}/reject`

Body: `{ "reason": "missing critical docs" }`

- Requires human project member/admin session OR API token with `review:write`; `resource:refresh` is not sufficient.
- Only `draft` can be rejected.
- Reason required and stored in `review_comment`.
- Records audit event.

## 8. UI

Sources detail panel for folder bundles:

- `Context artifact` card below Section reuse and impact.
- Shows latest Resource Map status, short hash, compile time, coverage metrics, validation state.
- Button: `Compile resource map`.
- Draft actions: `Approve` and `Reject`.
- Approval dialog requires warning acknowledgement when warnings exist.
- Reject dialog requires reason.
- Failed state shows product-facing error and `Retry compile`.
- Coverage labels:
  - covered: “Sections were extracted and cited.”
  - warning: “Usable, but parser warnings need review.”
  - empty: “No sections found in a supported file.”
  - unsupported: “File type is tracked but not parsed into sections.”
  - skipped: “File was intentionally skipped by ingestion limits/policy.”
  - failed: “File failed parsing and blocks approval.”

## 9. Tests

Unit:

- canonical hash deterministic independent of DB ordering.
- no full section content in artifact JSON.
- validation error vs warning classification for every A4 file status.
- idempotency/revision rules.

Real integration:

- upload folder bundle, compile Resource Map, verify artifact/source/citation rows.
- compile same snapshot twice returns same artifact unless force allowed after rejection.
- warning draft cannot approve without acknowledgement.
- parser failed file creates failed artifact and no source/citation rows.
- preflight missing manifest returns 409 with no artifact row.
- resource-scoped token cannot list/get/approve disallowed artifact.
- hard purge succeeds for resource with context artifacts.

Browser QA:

- compile real Resource Map from Sources UI.
- coverage/validation visible.
- warning acknowledgement flow works.
- reject reason required.
- no internal UUID-first UX, no console errors.

## 10. Rollout and reversibility

- Additive tables and UI card only.
- Existing indexing and runtime retrieval unchanged.
- Rollback: hide compile endpoints/UI and leave existing tables inert; migration downgrade drops B0 tables after citations/sources/artifacts in dependency order.
