# A1: Manifest Model and Path Normalization — Implementation Spec

Status: Draft
Date: 2026-06-19
Owner: SourceBrief platform
Parent spec: `docs/CONTEXT_ARTIFACT_COMPILER_REPO_AGENT_SPEC.md` §27 Milestone A1

---

## 1. Goal and scope

Add the `resource_manifests` and `resource_manifest_files` tables plus pure path/archive-safety helpers with full unit and integration test coverage. No upload endpoint, no archive extraction, no parser invocation, no worker job.

**In scope**

- SQLAlchemy ORM models for `ResourceManifest` and `ResourceManifestFile`
- Alembic migration `0014_a1_manifest_model`
- New helper module `packages/worker/sourcebrief_worker/manifest.py`:
  - `ManifestPathError` typed exception
  - `normalize_path(raw)` — POSIX-safe canonical form
  - `validate_archive_entry(name, entry_type, depth)` — reject symlinks, device files, deep nesting
  - `compute_manifest_hash(file_rows)` — deterministic SHA256 over sorted file rows
  - Quota constants (soft + hard limits)
- Unit tests for every rejection/normalization case
- Integration tests: Alembic upgrade, row creation, unique constraints, workspace scoping, audit event

**Out of scope for A1**

- ZIP/tar extraction or any actual archive parsing
- Upload API endpoint or multipart form handling
- Worker RQ job
- Manifest diff (A3)
- Section/chunk extraction reuse (A4)
- Any frontend UI
- Parser invocation or MIME sniffing from real bytes

---

## 2. Canonical entity rule

`Resource` remains the canonical backend entity. These tables hang off `resource_id` and `source_snapshot_id`. No `sources` table is introduced. See parent spec §2.

---

## 3. Data model

### 3.1 `resource_manifests`

One row per `(resource_id, source_snapshot_id)`. Captures the summary-level statistics for an ingested folder bundle or document collection snapshot.

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4()` | PK |
| `workspace_id` | UUID → workspaces.id | no | — | Tenant boundary |
| `project_id` | UUID → projects.id | no | — | Project boundary |
| `resource_id` | UUID → resources.id | no | — | Resource boundary |
| `source_snapshot_id` | UUID → source_snapshots.id | no | — | UNIQUE; one manifest per snapshot |
| `manifest_hash` | Text | no | — | SHA256 of deterministic serialization of file rows (see §5.3) |
| `file_count` | Integer | no | 0 | Total accepted file entries |
| `total_bytes` | BigInteger | no | 0 | Sum of `size_bytes` across accepted files |
| `parser_warning_count` | Integer | no | 0 | Files with non-empty `warnings_json` |
| `unsupported_file_count` | Integer | no | 0 | Files with `status = 'unsupported'` |
| `created_at` | DateTime(tz) | no | `now()` | — |

**Unique constraint**: `uq_resource_manifests_snapshot` on `(source_snapshot_id)`.

**Indexes**:
- `ix_resource_manifests_workspace` on `(workspace_id)`
- `ix_resource_manifests_workspace_project` on `(workspace_id, project_id)`
- `ix_resource_manifests_resource` on `(resource_id)`

**Rationale for `source_snapshot_id` UNIQUE**: a snapshot is immutable once created, so it can have at most one canonical manifest. If a re-manifest is needed (e.g. parser policy change), a new snapshot must be created. This keeps the A1 data model simple; A3 diff will create new snapshots naturally.

### 3.2 `resource_manifest_files`

One row per file within a manifest. This is the structured row from §10.3 of the parent spec, scoped to A1's accepted fields.

| Column | Type | Nullable | Default | Notes |
|---|---|---|---|---|
| `id` | UUID | no | `uuid4()` | PK |
| `workspace_id` | UUID → workspaces.id | no | — | Tenant boundary |
| `project_id` | UUID → projects.id | no | — | Project boundary |
| `resource_id` | UUID → resources.id | no | — | Resource boundary |
| `resource_manifest_id` | UUID → resource_manifests.id | no | — | Parent manifest |
| `normalized_path` | Text | no | — | Canonical POSIX path (see §5.1) |
| `display_path` | Text | yes | — | Raw client path if different; never used for lookups |
| `path_hash` | Text | no | — | SHA256 of `normalized_path` bytes |
| `content_hash` | Text | no | — | SHA256 of file content bytes |
| `size_bytes` | BigInteger | no | 0 | Byte count of raw file |
| `mime_type` | Text | yes | — | Client-declared or sniffed; untrusted display only |
| `mtime_client` | DateTime(tz) | yes | — | Client-reported mtime; untrusted, never used for security |
| `parser` | Text | yes | — | Parser name assigned at manifest time; `null` if none yet |
| `parser_version` | Text | yes | — | Parser version string |
| `extraction_policy_hash` | Text | yes | — | Hash of the extraction policy applied |
| `status` | Text | no | `'pending'` | `pending \| parsed \| failed \| unsupported \| skipped` |
| `section_count` | Integer | no | 0 | Populated by extraction (A4); 0 in A1 |
| `warnings_json` | JSONB | no | `[]` | List of parser warning strings |
| `created_at` | DateTime(tz) | no | `now()` | — |

**Unique constraint**: `uq_resource_manifest_files_manifest_path` on `(resource_manifest_id, normalized_path)`.

**Indexes**:
- `ix_resource_manifest_files_manifest` on `(resource_manifest_id)`
- `ix_resource_manifest_files_workspace` on `(workspace_id)`
- `ix_resource_manifest_files_resource` on `(resource_id)`
- `ix_resource_manifest_files_content_hash` on `(content_hash)` — supports reuse lookups in A4

**`mtime_client` security note**: this is stored as-is from the client. It must never be used for access control, cache freshness decisions, or security logic. It is display-only metadata.

---

## 4. Files to create or modify

| File | Action | Description |
|---|---|---|
| `packages/shared/sourcebrief_shared/models.py` | Modify | Append `ResourceManifest` and `ResourceManifestFile` ORM classes |
| `migrations/versions/0014_a1_manifest_model.py` | Create | Alembic migration creating both tables + all indexes |
| `packages/worker/sourcebrief_worker/manifest.py` | Create | Pure helper module (no DB, no network) |
| `packages/worker/sourcebrief_worker/manifest_store.py` | Create | Transactional DB helper for manifest + file rows + audit event |
| `tests/unit/test_manifest.py` | Create | Unit tests for helpers |
| `tests/integration/test_manifest_flow.py` | Create | Integration tests against real DB |

No other files require changes. No API router, no worker job, no frontend.

---

## 5. Helper module: `manifest.py`

Location: `packages/worker/sourcebrief_worker/manifest.py`

This module must have **no** database imports, no network imports, no subprocess calls, and no filesystem reads beyond what is passed in as function arguments. Every function must be fully testable without a running server.

### 5.1 `normalize_path(raw: str) -> str`

Converts an arbitrary client-supplied path string to a canonical POSIX-safe relative path.

Rules (applied in order):

1. Strip leading and trailing whitespace.
2. Reject if empty after stripping → `ManifestPathError(reason="empty_path")`.
3. Convert backslashes to forward slashes.
4. Reject if starts with `/` → `ManifestPathError(reason="absolute_path")`.
5. Split on `/`, process each component:
   - Drop empty components (consecutive slashes, trailing slash).
   - Reject if any component is `..` → `ManifestPathError(reason="path_traversal")`.
   - Drop `.` components (collapse in-place).
6. Reject if resulting path is empty after collapsing → `ManifestPathError(reason="empty_path")`.
7. Reject if `len(result) > MAX_PATH_LENGTH` → `ManifestPathError(reason="path_too_long")`.
8. Return joined result with `/` separator.

**`normalize_path` must never call `os.path` or `pathlib` functions that consult the real filesystem** (e.g. `resolve()`, `realpath()`). String-only processing only.

### 5.2 `validate_archive_entry(name: str, entry_type: str, depth: int) -> None`

Validates a single entry from a would-be archive before any content is extracted.

Parameters:
- `name`: raw path string from the archive member (before normalization)
- `entry_type`: one of `"file"`, `"dir"`, `"symlink"`, `"hardlink"`, `"device"`, `"socket"`, `"fifo"`, `"other"`
- `depth`: number of directory components in the path (0 = root-level file)

Rejection rules:

| Condition | Error reason |
|---|---|
| `entry_type` not in `{"file", "dir"}` | `"unsafe_entry_type"` |
| `depth > MAX_ARCHIVE_DEPTH` | `"archive_too_deep"` |
| `normalize_path(name)` raises `ManifestPathError` | re-raise as-is |

Symlinks, hardlinks, device files, sockets, and FIFOs are all rejected via the `entry_type` check. Callers must classify the entry before calling this function — the classification is connector-specific (zipfile vs tarfile).

### 5.3 `compute_manifest_hash(file_rows: list[dict]) -> str`

Produces a deterministic SHA256 fingerprint of a manifest's file contents.

Algorithm:
1. Sort `file_rows` ascending by `normalized_path` (lexicographic).
2. For each row, extract the tuple `(normalized_path, content_hash, size_bytes, parser, parser_version)`. Missing keys default to empty string / 0.
3. Serialize as a JSON array of sorted-key objects using `json.dumps(..., sort_keys=True, separators=(",", ":"))`.
4. SHA256 the UTF-8 bytes of the serialized string.
5. Return `"sha256:" + hex_digest`.

This hash changes if any file's path, content, parser, or parser version changes. It does not include `mtime_client`, `mime_type`, `display_path`, or `status` because those are not part of the canonical identity.

### 5.4 Quota constants

```python
# Soft limits: default for new resources unless overridden by project config
DEFAULT_MAX_MANIFEST_FILE_COUNT = 10_000
DEFAULT_MAX_MANIFEST_TOTAL_BYTES = 500_000_000   # 500 MB

# Hard limits: cannot be exceeded regardless of config
HARD_MAX_MANIFEST_FILE_COUNT = 50_000
HARD_MAX_MANIFEST_TOTAL_BYTES = 2_000_000_000    # 2 GB

# Per-file limits
MAX_SINGLE_FILE_BYTES = 50_000_000               # 50 MB
HARD_MAX_SINGLE_FILE_BYTES = 200_000_000         # 200 MB

# Path constraints
MAX_PATH_LENGTH = 512
MAX_ARCHIVE_DEPTH = 10
```

### 5.5 `ManifestPathError`

```python
class ManifestPathError(ValueError):
    def __init__(self, reason: str, path: str = "") -> None:
        self.reason = reason   # one of the reason strings above
        self.path = path
        super().__init__(f"manifest path error: {reason!r} path={path!r}")
```

Callers can catch `ManifestPathError` specifically and inspect `.reason` for structured logging or UI error messages.

---

## 6. ORM model additions

Add the following to the **bottom** of `packages/shared/sourcebrief_shared/models.py`, after `AuditEvent`, following the existing style (`uuid_pk()` helper, `Mapped[]` annotations, `JSONB` for structured columns, `BigInteger` import added where needed):

```python
from sqlalchemy import BigInteger  # add to existing import line

class ResourceManifest(Base):
    __tablename__ = "resource_manifests"
    __table_args__ = (
        UniqueConstraint("source_snapshot_id", name="uq_resource_manifests_snapshot"),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_snapshots.id"), nullable=False)
    manifest_hash: Mapped[str] = mapped_column(Text, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    parser_warning_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unsupported_file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResourceManifestFile(Base):
    __tablename__ = "resource_manifest_files"
    __table_args__ = (
        UniqueConstraint(
            "resource_manifest_id", "normalized_path",
            name="uq_resource_manifest_files_manifest_path",
        ),
    )
    id = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id"), nullable=False)
    resource_manifest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resource_manifests.id"), nullable=False)
    normalized_path: Mapped[str] = mapped_column(Text, nullable=False)
    display_path: Mapped[str | None] = mapped_column(Text)
    path_hash: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    mime_type: Mapped[str | None] = mapped_column(Text)
    mtime_client: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parser: Mapped[str | None] = mapped_column(Text)
    parser_version: Mapped[str | None] = mapped_column(Text)
    extraction_policy_hash: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    section_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

---

## 7. Migration

File: `migrations/versions/0014_a1_manifest_model.py`

```python
revision = "0014_a1_manifest_model"
down_revision = "0013_product_auth_admin"
```

The `upgrade()` function must:
1. Create `resource_manifests` with all columns, unique constraint, and four indexes.
2. Create `resource_manifest_files` with all columns, unique constraint, and four indexes.

The `downgrade()` function drops indexes in reverse creation order, then tables in reverse order (`resource_manifest_files` first, then `resource_manifests`).

`total_bytes` and `size_bytes` use `sa.BigInteger()` in the migration (not `sa.Integer()`).

Index naming convention (matching existing migrations):
- `ix_resource_manifests_workspace`
- `ix_resource_manifests_workspace_project`
- `ix_resource_manifests_resource`
- `ix_resource_manifest_files_manifest`
- `ix_resource_manifest_files_workspace`
- `ix_resource_manifest_files_resource`
- `ix_resource_manifest_files_content_hash`

---

## 8. No API in A1

A1 introduces no HTTP endpoints. Acceptance testing uses:

1. Unit tests calling helpers directly.
2. Integration tests constructing rows via SQLAlchemy ORM against a real Postgres database (same pattern as `tests/integration/test_ingestion_flow.py`).

A manifest endpoint (`GET /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/manifest`) is planned in A2 but must not be stubbed here.

---

## 9. Test plan

### 9.1 Unit tests — `tests/unit/test_manifest.py`

All tests are pure Python. Import only `sourcebrief_worker.manifest`. No database, no fixtures, no network.

| Test ID | Function under test | Scenario | Expected outcome |
|---|---|---|---|
| `test_normalize_simple` | `normalize_path` | `"docs/guide.md"` | `"docs/guide.md"` |
| `test_normalize_backslash` | `normalize_path` | `"docs\\guide.md"` | `"docs/guide.md"` |
| `test_normalize_trailing_slash` | `normalize_path` | `"docs/"` | `"docs"` |
| `test_normalize_dot_component` | `normalize_path` | `"a/./b"` | `"a/b"` |
| `test_normalize_consecutive_slashes` | `normalize_path` | `"a//b"` | `"a/b"` |
| `test_normalize_absolute_rejected` | `normalize_path` | `"/etc/passwd"` | `ManifestPathError(reason="absolute_path")` |
| `test_normalize_traversal_simple` | `normalize_path` | `"../etc/passwd"` | `ManifestPathError(reason="path_traversal")` |
| `test_normalize_traversal_embedded` | `normalize_path` | `"docs/../../../etc/passwd"` | `ManifestPathError(reason="path_traversal")` |
| `test_normalize_traversal_windows` | `normalize_path` | `"docs\\..\\..\\etc\\passwd"` | `ManifestPathError(reason="path_traversal")` |
| `test_normalize_empty_string` | `normalize_path` | `""` | `ManifestPathError(reason="empty_path")` |
| `test_normalize_whitespace_only` | `normalize_path` | `"   "` | `ManifestPathError(reason="empty_path")` |
| `test_normalize_only_dots_rejected` | `normalize_path` | `"."` | `ManifestPathError(reason="empty_path")` |
| `test_normalize_path_too_long` | `normalize_path` | string of 513 `a/` chars | `ManifestPathError(reason="path_too_long")` |
| `test_validate_entry_symlink` | `validate_archive_entry` | `entry_type="symlink"` | `ManifestPathError(reason="unsafe_entry_type")` |
| `test_validate_entry_hardlink` | `validate_archive_entry` | `entry_type="hardlink"` | `ManifestPathError(reason="unsafe_entry_type")` |
| `test_validate_entry_device` | `validate_archive_entry` | `entry_type="device"` | `ManifestPathError(reason="unsafe_entry_type")` |
| `test_validate_entry_socket` | `validate_archive_entry` | `entry_type="socket"` | `ManifestPathError(reason="unsafe_entry_type")` |
| `test_validate_entry_fifo` | `validate_archive_entry` | `entry_type="fifo"` | `ManifestPathError(reason="unsafe_entry_type")` |
| `test_validate_entry_file_ok` | `validate_archive_entry` | `entry_type="file"`, depth=2 | no exception |
| `test_validate_entry_dir_ok` | `validate_archive_entry` | `entry_type="dir"`, depth=0 | no exception |
| `test_validate_entry_max_depth` | `validate_archive_entry` | depth=11 | `ManifestPathError(reason="archive_too_deep")` |
| `test_validate_entry_traversal_in_name` | `validate_archive_entry` | `name="../evil"`, type=`"file"` | `ManifestPathError(reason="path_traversal")` |
| `test_manifest_hash_deterministic` | `compute_manifest_hash` | same list twice | same hash |
| `test_manifest_hash_order_independent` | `compute_manifest_hash` | same list, different order | same hash |
| `test_manifest_hash_differs_on_content` | `compute_manifest_hash` | one content_hash changed | different hash |
| `test_manifest_hash_differs_on_path` | `compute_manifest_hash` | one path changed | different hash |
| `test_manifest_hash_differs_on_parser_version` | `compute_manifest_hash` | parser_version changed | different hash |
| `test_manifest_hash_ignores_mtime` | `compute_manifest_hash` | only `mtime_client` differs between two lists | same hash |

### 9.2 Integration tests — `tests/integration/test_manifest_flow.py`

Use the same fixture pattern as existing integration tests (real Postgres, SQLAlchemy session, existing workspace/project/resource/snapshot rows created as prerequisites).

| Test ID | Scenario | Expected outcome |
|---|---|---|
| `test_alembic_upgrade_creates_tables` | Run `alembic upgrade 0014_a1_manifest_model` on clean DB | `resource_manifests` and `resource_manifest_files` tables exist |
| `test_create_manifest_row` | Insert `ResourceManifest` via ORM session | Row retrieved by PK; `manifest_hash`, `file_count` correct |
| `test_create_manifest_file_rows` | Insert 3 `ResourceManifestFile` rows under same manifest | All 3 retrieved by `resource_manifest_id` filter |
| `test_unique_constraint_snapshot` | Insert two `ResourceManifest` rows with same `source_snapshot_id` | Second insert raises `IntegrityError` |
| `test_unique_constraint_manifest_path` | Insert two `ResourceManifestFile` rows with same `(resource_manifest_id, normalized_path)` | Second insert raises `IntegrityError` |
| `test_workspace_scoping` | Insert manifests for two workspaces; query filtered by `workspace_id` | Each workspace only sees its own rows |
| `test_audit_event_on_manifest_create` | Create manifest + emit `AuditEvent` with `action="manifest.created"` | Event row exists with matching `target_id` |
| `test_content_hash_index_lookup` | Insert file row; query `resource_manifest_files` by `content_hash` | Row found without table scan |

**Audit event shape for A1**: callers that create a `ResourceManifest` must also create an `AuditEvent`:

```python
AuditEvent(
    workspace_id=manifest.workspace_id,
    action="manifest.created",
    target_type="resource_manifest",
    target_id=manifest.id,
    target_ref={"resource_id": str(manifest.resource_id), "snapshot_id": str(manifest.source_snapshot_id)},
)
```

This is tested in the integration suite. It is not enforced at the ORM layer (no trigger or hook). The caller — which will be the A2 worker job — is responsible for emitting it.

---

## 10. Real-service QA checklist (A1)

Per parent spec §32:

- [ ] `alembic upgrade head` runs cleanly on a fresh local DB.
- [ ] `alembic downgrade -1` drops both tables without error.
- [ ] `alembic upgrade head` again succeeds.
- [ ] Integration test suite passes against a running Postgres instance.
- [ ] No broken imports in the shared models module.
- [ ] No new test fixtures require a running worker or Redis.

---

## 11. Non-goals (reiterated for A1)

- No archive extraction.
- No ZIP/tar parsing.
- No HTTP upload endpoint.
- No RQ worker job.
- No manifest diff logic (that is A3).
- No partial update / section reuse (A4).
- No MIME sniffing from real file bytes.
- No frontend UI changes.
- No `Source` table.

---

## 12. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| `source_snapshot_id` UNIQUE proves too strict (re-manifest same snapshot for policy change) | Low | A2/A3 will create new snapshots for policy changes; revisit if needed. Don't relax the constraint preemptively. |
| `BigInteger` for `total_bytes`/`size_bytes` not imported in models.py | Low | Spec explicitly calls out the `BigInteger` import addition. Migration uses `sa.BigInteger()`. |
| `mtime_client` used for logic by a future developer | Low | Column comment in migration: `"untrusted client-reported mtime; display only"`. |
| Path normalization bypassed by malicious null bytes | Low | Add null-byte check in `normalize_path` step 1: reject if `"\x00"` in raw string → `reason="invalid_characters"`. |
| `compute_manifest_hash` non-determinism across Python versions | Low | Use `json.dumps(sort_keys=True, separators=(",", ":"))` and only stable primitive types. Cover with snapshot test. |
| `warnings_json` column stores unbounded list | Medium | Helpers should cap to 100 warnings per file before storage. Implement cap in the A2 worker; document the cap here. |
