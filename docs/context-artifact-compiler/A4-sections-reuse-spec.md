# A4 — Section Extraction and Reuse Implementation Spec

Status: Draft v0.2 after adversarial review  
Branch: `feat/context-artifact-compiler-a4-sections-reuse`  
Parent milestones: A1 manifest/path safety, A2 folder bundle upload, A3 manifest diff

## 1. Goal

A4 turns file-level manifest data into reusable section-level evidence. When a user uploads a new folder-bundle version, ContextSmith should reuse unchanged extraction results, re-extract only changed/added files, and make reuse/impact visible to operators.

A4 is the bridge from source snapshots to deterministic context artifacts. It does **not** introduce LLM summaries, generated skills, resource maps, embeddings, or auto-publish.

## 2. Alignment with A3 lineage

A3 creates a new `Resource` row per folder-bundle upload. Lineage lives in `source_config`:

- `source_family_id`: root/v1 resource ID string
- `source_family_label`: human family label
- `version_label`: `v1`, `v2`, ...
- `supersedes_resource_id`: explicit predecessor version resource ID for v2+

A4 section identity must use this family root, not the current version resource ID.

Terms:

- `section_family_resource_id`: UUID parsed from `source_config.source_family_id`; stable across versions.
- `version_resource_id`: current `Resource.id`; changes on every uploaded version.
- `predecessor_resource_id`: UUID parsed from current resource `source_config.supersedes_resource_id`; used for worker reuse.

The worker must never infer predecessor by `created_at` or “latest two manifests”; that is unsafe under concurrent uploads, retries, and out-of-order worker completion.

## 3. User-facing promise

For folder bundles:

1. Upload v1 zip.
2. Worker extracts sections for supported text-like files.
3. Upload v2 zip into the same family via “Upload new version”.
4. Worker reuses sections for unchanged files, extracts new sections for changed/added files, and detects sections absent from the new version.
5. Source detail shows:
   - section count,
   - reused section count,
   - newly extracted section count,
   - sections from deleted files,
   - sections absent from this version,
   - whether artifact impact is known.

## 4. Non-goals

- No LLM summarization.
- No context artifact/resource-map generation; B0 owns it.
- No embedding namespace or semantic chunking.
- No exact parser for every file type. A4 starts with deterministic Markdown/plain-text/code section extraction.
- No auto-publish or generated agent mutation.

## 5. Data model

### 5.1 `sections`

Logical section identity across versions in one source family.

Fields:

- `id UUID PK`
- `workspace_id UUID NOT NULL`
- `project_id UUID NOT NULL`
- `section_family_resource_id UUID NOT NULL`
- `normalized_path TEXT NOT NULL`
- `parser_version TEXT NOT NULL`
- `extraction_policy_hash TEXT NOT NULL`
- `section_hash TEXT NOT NULL`
- `occurrence_key TEXT NOT NULL`
- `logical_key TEXT NOT NULL`
- `title TEXT NULL`
- `content_hash TEXT NOT NULL`
- `content_text TEXT NOT NULL` — **redacted text only**
- `content_bytes INTEGER NOT NULL`
- `ordinal INTEGER NOT NULL`
- `start_line INTEGER NULL`
- `end_line INTEGER NULL`
- `metadata_json JSONB NOT NULL DEFAULT '{}'`
- timestamps

Indexes:

- unique `(project_id, logical_key)`
- `(section_family_resource_id, normalized_path)`
- `(workspace_id, project_id)`

Scoped integrity constraints:

- `section_family_resource_id` must reference a `resources.id` in the same `(workspace_id, project_id)`.
- Section rows must not be insertable for a different workspace/project than their family resource.
- These constraints should follow the existing scoped FK style used by A1 manifest tables, not loose UUID-only references.

Logical key:

```text
sha256(section_family_resource_id + normalized_path + parser_version + extraction_policy_hash + section_hash + occurrence_key)
```

`occurrence_key` is required because repeated identical sections can appear in one file/snapshot. For v0 it is `ordinal:start_line:end_line` when line bounds are available, else `ordinal`. This makes repeated identical windows representable while preserving reuse when unchanged files keep stable structure.

### 5.2 `snapshot_sections`

Immutable mapping from source snapshot to logical section.

Fields:

- `id UUID PK`
- `workspace_id UUID NOT NULL`
- `project_id UUID NOT NULL`
- `version_resource_id UUID NOT NULL`
- `section_family_resource_id UUID NOT NULL`
- `source_snapshot_id UUID NOT NULL`
- `resource_manifest_id UUID NOT NULL`
- `resource_manifest_file_id UUID NOT NULL`
- `section_id UUID NOT NULL`
- `normalized_path TEXT NOT NULL`
- `ordinal INTEGER NOT NULL`
- `reused_from_snapshot_id UUID NULL`
- `reuse_status TEXT NOT NULL` enum-ish: `reused|extracted`
- timestamps

Indexes:

- unique `(source_snapshot_id, resource_manifest_file_id, ordinal)`
- non-unique `(source_snapshot_id, section_id)`
- `(source_snapshot_id, normalized_path)`
- `(section_id)`
- `(version_resource_id, normalized_path)`

Scoped integrity constraints:

- `version_resource_id` references a `resources.id` in the same `(workspace_id, project_id)`.
- `section_family_resource_id` references the family/root `resources.id` in the same `(workspace_id, project_id)`.
- `source_snapshot_id` references `source_snapshots.id` in the same `(workspace_id, project_id, version_resource_id)`.
- `resource_manifest_id` references `resource_manifests.id` in the same `(workspace_id, project_id, version_resource_id, source_snapshot_id)`.
- `resource_manifest_file_id` references `resource_manifest_files.id` in the same `(workspace_id, project_id, version_resource_id, resource_manifest_id)`.
- `section_id` references `sections.id` in the same `(workspace_id, project_id, section_family_resource_id)`.

If SQLAlchemy/Alembic cannot express one composite FK cleanly for a field, the migration must still add equivalent indexed constraints and the worker/API must validate before insert. Cross-project provenance rows are not acceptable.

### 5.3 Manifest counters

Add persisted counters to `resource_manifests`:

- `section_count INTEGER NOT NULL DEFAULT 0`
- `sections_reused_count INTEGER NOT NULL DEFAULT 0`
- `sections_extracted_count INTEGER NOT NULL DEFAULT 0`
- `sections_from_deleted_files_count INTEGER NOT NULL DEFAULT 0`
- `sections_absent_count INTEGER NOT NULL DEFAULT 0`

These counters are cheap UI evidence and simplify operator triage.

## 6. Extraction policy

Supported in v0:

- `.md`, `.mdx`, `.txt`, `.rst`, `.yaml`, `.yml`, `.json`, `.toml`, `.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.go`, `.rs`, `.java`, `.kt`, `.sh`, `.sql`

Policy:

- Binary/unsupported files produce no sections and keep A2 manifest unsupported/warning behavior.
- Markdown-like files split by heading blocks.
- Plain/code files split into bounded line windows (default 120 lines, no overlap in v0).
- Empty files produce no sections.
- Newlines are normalized before hashing.
- `parser_version = section-extractor-v1`.
- `extraction_policy_hash = sha256(policy JSON)`.
- Extractor is pure/unit-testable; no DB/session inside extractor.

## 7. Redaction and content safety

Persisted `sections.content_text` and section previews must contain redacted text only. A4 must apply the same secret-redaction policy used by worker document ingestion before hashing/storing section content.

Rules:

- `section_hash`, `content_hash`, and `logical_key` are computed from redacted normalized text.
- Raw archive text may exist only in process memory/sandbox while parsing.
- Raw content must not be persisted in `sections`, `snapshot_sections`, audit payloads, parser warnings, or logs.
- Tests must upload an obvious token/password and assert the raw secret does not appear in section storage or API previews.

## 8. Worker algorithm

After A2 manifest generation and before graph/chunking:

1. Load current manifest files.
2. Resolve `section_family_resource_id` from current resource `source_config.source_family_id`.
3. Resolve predecessor only from current resource `source_config.supersedes_resource_id`.
4. If predecessor exists and has a current snapshot + manifest, load its `snapshot_sections`; otherwise set reuse baseline empty and emit a warning/audit event.
5. Build A3 diff against the explicit predecessor when available.
6. For each current manifest file:
   - Unsupported/non-text-like: skip section extraction.
   - Unchanged file with predecessor `snapshot_sections` for same `normalized_path`: copy mappings into current `snapshot_sections` with `reuse_status='reused'`, same `section_id`, `reused_from_snapshot_id=<predecessor snapshot>` **only if predecessor `sections.parser_version` and `sections.extraction_policy_hash` match the current extractor policy**.
   - If parser version or extraction policy differs, treat the unchanged file as extraction-required: re-extract redacted sections, upsert new logical keys under the current policy, and count rows as `extracted`, not `reused`.
   - Changed/added file: extract redacted sections, upsert `sections` by logical key, insert current `snapshot_sections` with `reuse_status='extracted'`.
7. Compute:
   - `sections_from_deleted_files_count`: predecessor sections whose path is deleted by A3 file diff.
   - `sections_absent_count`: predecessor snapshot sections that are not mapped into current snapshot, including sections removed inside changed files.
8. Persist manifest counters.
9. Emit audit event with counters.

If A3 diff is unavailable, A4 may extract all current supported files, set reused count to 0, and emit an explicit warning. It must not claim reuse.

## 9. API

### 9.1 Manifest extension

`GET /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/manifest`

Add counters:

- `section_count`
- `sections_reused_count`
- `sections_extracted_count`
- `sections_from_deleted_files_count`
- `sections_absent_count`

### 9.2 Snapshot sections

```text
GET /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/snapshot-sections
```

Query:

- `version_resource_id` optional human-workflow version selector; resolves to that version’s current snapshot after auth.
- `source_snapshot_id` optional for internal/API callers; UI must not require UUID input.
- `limit` default 100, max 500.
- `cursor` opaque.
- `reuse_status` optional filter.

Response:

- `rows`: path, title/label, ordinal, reuse status, content preview, line bounds.
- `total_row_count`, `row_count_returned`, `next_cursor`.

Authorization:

- Requires `resource:read`.
- Resource-scoped tokens can read sections only for allowed version resources.
- Hidden sibling versions/resources return 404 where existence would leak.

### 9.3 Section impact

```text
GET /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/section-impact
```

Response:

- `sections_from_deleted_files_count`
- `sections_absent_count`
- `impacted_artifacts_known=false` until B0 citations exist
- `message`: explicit limitation
- `deleted_paths`: bounded list of deleted paths with section counts
- `changed_paths_with_absent_sections`: bounded list of changed paths where prior sections disappeared

This is intentionally honest: A4 can identify absent sections, but cannot know artifact impact until citation tables exist.

## 10. UI

Source detail for folder bundles adds `Section extraction` panel:

- Total sections
- Reused sections
- Newly extracted sections
- Sections from deleted files
- Sections absent from this version
- Reuse ratio
- Impact limitation text

Section table:

- Path
- Title/section label
- Reuse status
- Ordinal / line range
- Preview

Version UX:

- Source list continues to show family label + version label from A3.
- Source detail shows a compact version selector using `version_label`, created time, and index status.
- Selecting a version calls APIs with `version_resource_id` or selects the version row internally.
- Users are never asked to paste `source_snapshot_id`, raw UUIDs, API endpoints, or bearer tokens.

## 11. Observability and operational ownership

Audit events:

- `section_extraction_started`
- `section_extraction_completed`
- `section_extraction_failed`

Payload fields:

- workspace/project/version resource ID
- source family label/version label
- manifest ID/snapshot ID
- section counts, reused/extracted/from-deleted-files/absent counts
- parser warning count
- duration_ms
- failure class/message when failed

Operator surface:

- Index run error message starts with `section extraction:` for extraction failures.
- Source detail Section extraction panel shows failed/partial state if counters are unavailable.
- Logs include resource/version labels and run ID, never raw content.

Owner: ContextSmith platform/worker owner.

Runbook path:

1. Inspect index run status/error.
2. Inspect worker logs by run ID/resource label.
3. Inspect manifest parser warnings and section extraction audit events.
4. Retry by reindexing/uploading a new version after fixing malformed content or quota settings.

## 12. Tests

### Unit

- Markdown heading split is deterministic.
- Plain/code window split is deterministic.
- Logical keys stable for same redacted content/policy/occurrence.
- Changed content yields new logical key.
- Repeated identical sections in one file produce distinct snapshot rows.
- Empty/unsupported content yields no sections.
- Pagination cursor for snapshot sections preserves total count.
- Redaction test proves raw secrets are not persisted in section content.

### Real integration

Use real Postgres/RQ/API and folder-bundle zip uploads:

1. Upload v1 zip with:
   - `README.md` with two headings,
   - `keep.txt`,
   - `delete.md`,
   - `secret.md` containing an obvious fake token.
2. Wait worker success.
3. Assert manifest section counters > 0 and sections endpoint returns extracted rows.
4. Assert raw secret not present in stored section content or API preview.
5. Upload v2:
   - unchanged `keep.txt`,
   - changed `README.md` with one prior section removed,
   - added `added.md`,
   - deleted `delete.md`.
6. Wait worker success.
7. Assert:
   - unchanged file sections are `reused`,
   - changed/added sections are `extracted`,
   - sections-from-deleted-files count reflects deleted file sections,
   - absent-section count includes sections removed from changed files,
   - section impact says artifact impact is not known yet,
   - resource-scoped token cannot read sections of sibling hidden versions/resources.

### Frontend/browser

- Real 3105 UI shows Section extraction counters.
- Inspect v2 source shows reused/extracted/from-deleted-files/absent counts.
- Snapshot section table shows human labels and no UUID-first workflow.
- Version selector uses labels, not pasted IDs.
- Console has no JS errors.

## 13. Failure modes and guardrails

- Extraction failure fails the index run with useful `section extraction:` error.
- Large files respect existing A2 quotas; section extraction caps max sections per file/project with explicit parser warning.
- Reuse is conservative. If predecessor sections are missing, extract again rather than invent reuse.
- If predecessor indexing failed, v2 can still index but reports zero reuse and an audit warning.
- Duplicate normalized paths should already be rejected by A2; A4 should not crash if old DB rows are malformed.

## 14. Migration and reversibility

Migrations are additive:

- create `sections`
- create `snapshot_sections`
- add manifest counters

Rollback drops these tables/counters. A1/A2/A3 manifest upload/diff remains functional.

## 15. Acceptance

A4 is complete when:

- Additive migration passes on fresh DB and existing DB.
- Worker extracts redacted sections for folder bundles.
- Unchanged files reuse logical sections across v1/v2.
- Changed/added files produce new snapshot sections.
- Sections-from-deleted-files and absent-section counts are visible.
- API and UI expose reuse counters and human version selection.
- Real integration tests use Postgres/RQ/API; no mocks.
- Hermes adversarial backend/product reviews PASS.
