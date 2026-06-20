# C — Generated Skill Export and Runtime Guidance Implementation Spec

Status: Draft v0.2 after adversarial review  
Branch: `feat/context-artifact-compiler-c-skill-export`  
Depends on: B0 Resource Map artifacts, B1 Context Pack versions

## 1. Goal

Export published Context Packs into thin, auditable runtime adapters. A generated skill is **not** a copy of the source corpus and not the canonical system of record. It is an instruction package that teaches an agent how to call SourceBrief with a pinned pack selector and how to cite returned evidence.

## 2. Non-goals

- Do not embed full source files, chunks, snippets, retrieved context, embeddings, graph indexes, or raw corpus text.
- Do not auto-install generated skills into any Hermes profile.
- Do not mutate Hermes/Codex/Claude config from the web UI.
- Do not expose backend-local paths, worker temp dirs, secrets, session tokens, or bearer tokens.
- Do not advertise unavailable MCP tools.
- Do not claim runtime is configured; export only files and explicit install/use instructions.

## 3. Stable runtime contract

C must use the **existing stable runtime shape**:

REST:

```http
POST /workspaces/{workspace_id}/projects/{project_id}/agent-context
{
  "query": "...",
  "context_pack_key": "<pack_key>",
  "context_pack_version": <version>,
  "runtime": "hermes",
  "top_k": 8
}
```

The generated instructions must tell agents to verify:

- `context_pack_key` equals the exported pack key.
- `context_pack_version` equals the exported pack version.
- `context_pack_snapshot_pin_enforced === true`.
- citations are present before answering.

MCP:

- Only mention the actual stable tool name if this repo/runtime advertises it: `sourcebrief.get_agent_context`.
- Do **not** mention future tools such as `get_context_pack`, `search`, or `read_section` until live `tools/list` exposes them.
- README may say “future MCP tools may add resource-map drilldown,” but not instruct agents to call them.

## 4. Data model

### 4.1 `skill_exports`

Columns:

- `id uuid pk`
- `workspace_id uuid not null fk`
- `project_id uuid not null fk`
- `context_pack_version_id uuid not null`
- `pack_key text not null`
- `pack_version integer not null`
- `export_type text not null` — `hermes_skill` for C.
- `export_version integer not null`
- `status text not null` — `draft`, `approved`, `rejected`, `invalidated`, `failed`.
- `title text not null`
- `summary text null`
- `package_hash text not null`
- `manifest_json jsonb not null`
- `files_json jsonb not null` — generated text files only. Empty for `failed` exports.
- `validation_json jsonb not null`
- `leak_scan_json jsonb not null`
- `created_by uuid null fk users`
- `approved_by uuid null fk users`
- `approved_at timestamptz null`
- `rejected_by uuid null fk users`
- `rejected_at timestamptz null`
- `invalidated_by uuid null fk users`
- `invalidated_at timestamptz null`
- `review_comment text null`
- `created_at timestamptz default now()`
- `updated_at timestamptz default now()`

Constraints:

- scoped FK `(context_pack_version_id, workspace_id, project_id)` -> `context_pack_versions(id, workspace_id, project_id)`.
- unique `(workspace_id, project_id, context_pack_version_id, export_type, package_hash)`.
- unique `(workspace_id, project_id, context_pack_version_id, export_type, export_version)`.
- CHECK status in allowed set.
- CHECK export_type in allowed set.
- CHECK `package_hash LIKE 'sha256:%' AND length(package_hash)=71`.
- CHECK `export_version >= 1`.

Retention / purge:

- Resource hard purge must block if any export with retained files references a Context Pack covering that resource.
- `draft`, `approved`, `rejected`, and `failed` exports all have an explicit purge-unblock path to `invalidated/scrubbed`.
- Invalidated exports and failed exports are scrubbed: set `files_json=[]`, keep minimal manifest `{scrubbed:true, pack_key, pack_version, package_hash}` for audit.
- Rejected exports are not automatically scrubbed, but may be invalidated/scrubbed by review/admin action before purge.
- Pack version deletion/downgrade must delete/scrub dependent exports first.

## 5. Deterministic package rules

Package hash is over a canonical payload:

```json
{
  "schema_version": "skill-export.v1",
  "export_type": "hermes_skill",
  "pack_key": "...",
  "pack_version": 1,
  "pack_hash": "sha256:...",
  "files": [
    {"path":"README.md","sha256":"sha256:...","bytes":123},
    {"path":"SKILL.md","sha256":"sha256:...","bytes":456},
    {"path":"manifest.hash.json","sha256":"sha256:...","bytes":789}
  ]
}
```

Rules:

- Sort files by path.
- UTF-8 text only.
- Normalize line endings to `\n`.
- JSON uses sorted keys and compact separators.
- `manifest.json` is not hashed in its downloadable mutable form. The hash input uses `manifest.hash.json`, an internal canonical manifest form with volatile/mutable fields replaced by fixed placeholders.
- Hash input files are: `SKILL.md`, `README.md`, and `manifest.hash.json`.
- Downloadable `manifest.json` may include `package_hash`, `generated_at`, export status, and approval metadata, but those fields are outside the immutable package hash.
- `SKILL.md` and `README.md` are immutable after generation. Approval changes DB metadata and downloadable `manifest.json` review fields only.
- Re-generating same pack/export_type returns existing export by `(pack, export_type, package_hash)`.

## 6. Generated files

Allowed files:

1. `SKILL.md`
   - frontmatter with name, description, sourcebrief metadata.
   - trigger conditions.
   - exact REST and MCP fallback contract using `context_pack_key` + integer `context_pack_version`.
   - required verification of `context_pack_snapshot_pin_enforced=true`.
   - citation policy: answer only from returned citations; cite paths/sections; say when evidence is insufficient.
   - freshness warning and invalidated-pack behavior.
   - mutation boundary.
   - explicit warning if export status is not approved.
2. `manifest.json`
   - package hash, export status, approval metadata, pack key/version/hash/status, source coverage counts, file hashes, generated_at, generator version.
3. `README.md`
   - install/use instructions.
   - explicit statement: no source corpus is embedded; SourceBrief access is required.
   - copy/install only if export status is `approved`.

Positive content whitelist:

- pack key/version/hash/status
- resource names and counts
- artifact hashes/counts
- SourceBrief API route shape without token
- citation policy/instructions
- package metadata

Forbidden in all files and `files_json.content`:

- source chunks/snippets/context bodies
- raw citation content
- full source files
- local filesystem paths
- bearer/session/admin secrets
- backend database/Redis URLs

## 7. Leak scan and validation

Validation must pass before approval.

Leak scan fails on:

- `/home/`, `/tmp/`, `/var/lib/`, `/qa-fixtures/`, `file://`
- `SOURCEBRIEF_ADMIN_PASSWORD`, `session_token`, `cs_`, `Bearer `
- private-key markers
- source text markers from citations/chunks/snapshot file content
- any generated file above conservative size cap (`SKILL.md` 24KB, README 12KB, manifest 24KB)

If leak scan fails:

- persist a `failed` export row with `files_json=[]` and `leak_scan_json` findings;
- do not expose file downloads;
- do not allow approval;
- UI shows findings and remediation.

## 8. API

### Generate

`POST /workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions/{version_number}/skill-exports`

Auth:

- require `review:write` and project membership.
- require read access to every resource covered by the Context Pack.

Semantics:

- pack must be `published`.
- compile deterministic package.
- if validation/leak scan fails, create/return `failed` export with empty files.
- if same package hash exists, return existing export.
- otherwise create `draft` with next export_version.

### List/get

- `GET /workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions/{version_number}/skill-exports`
- `GET /workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_id}`

Auth: `resource:read` and pack resource visibility.

### Approve/reject/invalidate

Allowed transitions:

- `draft -> approved` only if validation ok and leak scan ok.
- `draft -> rejected`.
- `draft -> invalidated` for purge/unblock or abandoned export cleanup.
- `approved -> invalidated`.
- `failed -> invalidated` or `failed -> rejected`; never approved.
- `rejected -> invalidated` for purge/unblock cleanup; never approved.
- `invalidated` is terminal except idempotent same-state calls return 422 with explicit message.

All mutations:

- require `review:write`, project membership, and pack resource visibility.
- re-read row `FOR UPDATE`.
- require non-empty comment/reason.
- write audit events with previous/new status, pack key/version, package hash, actor.

### File download

`GET /workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_id}/files/{path}`

Rules:

- auth requires `resource:read`, project membership/access, and authorization for every resource covered by the referenced Context Pack.
- path must exactly match one generated file path; no traversal or arbitrary filesystem lookup.
- external download/copy allowed only for `approved` exports with validation/leak ok.
- draft exports are previewable in the authenticated review UI only; they are not downloadable/copyable as installable artifacts.
- response includes text/plain or application/json content type.

## 9. UI

Add a Skill Export panel near Context Packs:

- select a published Context Pack version;
- generate Hermes skill export;
- show status, package hash, approval metadata, validation and leak scan findings;
- show files list and `SKILL.md` preview;
- approve/reject/invalidate with required comments;
- disable external download/copy/install for every status except `approved`;
- for `draft`, show authenticated preview only with “approval required before installing”; no copy/download button;
- warn if export is draft inside package preview and downloadable package metadata;
- no raw bearer token/API base field;
- no internal UUID as primary action.

## 10. Tests / verification

Real integration tests:

1. Folder bundle -> worker index -> Resource Map -> approve -> Context Pack publish -> generate skill export.
2. Export package contains `SKILL.md`, `manifest.json`, `README.md`.
3. Package excludes source corpus, local paths, secrets, session token, bearer token.
4. Generated skill includes exact REST contract, stable MCP tool name only, citation policy, freshness warning, mutation boundary, pack key/version/hash, and pin verification.
5. Unauthorized resource-scoped token cannot list/get/generate/approve/export file for hidden pack resources.
6. Draft/non-published pack cannot be exported.
7. Leak scan failure creates failed export with empty files and no download.
8. Approve/reject/invalidate lifecycle and audit events.
9. File path traversal rejected.
10. Draft export preview is visible in authenticated UI, but file download/copy endpoint rejects until approval.
11. Hard purge blocked by export with retained files; allowed after invalidation/scrub for draft/rejected/approved/failed exports.
12. Migration downgrade/upgrade on real Postgres.
13. Web lint/build and browser QA with real generated export.

## 11. Rollout / reversibility

- Migration is additive; downgrade drops export table after explicit scrub/delete.
- Runtime path does not depend on exports.
- Disable UI panel if export generation defects appear; Context Packs remain usable.

## 12. Failure modes

- Pack invalidated after export: export remains historical but UI and package warn it may no longer be current.
- Backend unreachable: generated skill instructs agent to report degraded context and avoid unsupported claims.
- MCP not configured: use REST/API fallback if available or ask user to configure MCP.
- Leak scan fail: no generated content is downloadable.
