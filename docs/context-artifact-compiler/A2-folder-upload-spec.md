# A2: Multipart Zip Folder Upload — Implementation Spec

Status: Draft
Date: 2026-06-19
Owner: SourceBrief platform
Parent spec: `docs/CONTEXT_ARTIFACT_COMPILER_REPO_AGENT_SPEC.md` §27 Milestone A2
A1 spec: `docs/context-artifact-compiler/A1-manifest-model-spec.md`

---

## 1. Objective and non-goals

**Objective.** Users upload a zip file representing a folder bundle through a normal API/UI flow. The system creates a `folder_bundle` Resource, SourceSnapshot, ResourceManifest, ResourceManifestFile rows, SnapshotFile rows for text-indexable files, and an IndexRun whose final state is visible in the existing Sources UI. File count, unsupported file count, and any parser warnings are surfaced without requiring mock data.

**In scope**

- Dedicated multipart upload endpoint `POST .../resources/upload-folder-bundle`
- Read-only manifest endpoint `GET .../resources/{resource_id}/manifest`
- Zip extraction sandbox with zip-bomb, traversal, symlink, and quota guards
- New `_collect_folder_bundle` ingestion connector (reuses A1 helpers)
- New `bundle_ingest.py` module containing the extraction and manifest-building logic
- Manifest creation wired into the existing `ingest_resource` / `run_index` pipeline
- Frontend connect panel extended with a zip file picker
- Sources detail: manifest summary (file count, unsupported count, warnings count)
- Audit events: `resource.upload`, `manifest.created`
- Unit and integration tests including all malicious-archive cases
- Real Postgres + RQ + API + frontend verification (no mock data)

**Out of scope for A2**

- Browser File System Access API / directory picker
- S3 or external blob storage (staging is a shared filesystem path)
- Re-upload / version bump (that is A3 diff)
- Per-file parser invocation (parsers produce section content — A4)
- Manifest diff (A3)
- Section/chunk reuse (A4)
- Multi-file or mixed-connector uploads
- Any new Alembic migration (no new tables required)

---

## 2. User-visible flow

1. User opens the Sources page and clicks **Connect source**.
2. User selects the new **Folder bundle** tab in the connect panel.
3. User fills in a name and picks a `.zip` file from their local disk using a standard `<input type="file" accept=".zip">`. A2 folder bundles are manual-only; updates happen by uploading a new zip, not by refresh/scheduled polling. API update and scheduler paths must also preserve that invariant.
4. User clicks **Upload**. The browser sends a `multipart/form-data` POST to the upload endpoint.
5. The API performs synchronous structural zip validation before creating DB rows, writes the upload to controlled staging, creates the Resource and IndexRun, enqueues the worker job, and returns `{resource, index_run}` (HTTP 202).
6. The frontend transitions to the source detail view showing an in-progress IndexRun.
7. The worker extracts the zip, creates the manifest, chunks text files, and marks the IndexRun `succeeded`.
8. After the run finishes (poll or refresh), the source detail shows:
   - Resource status: `active`
   - Manifest summary card: **10 files · 2 unsupported · 0 warnings** (real counts, not placeholders)
9. Rejected uploads detected synchronously (zip bomb ratio/total bytes, traversal path, symlink/special file, absolute path, too many files, too large) show an inline error on the connect panel with the specific rejection reason. Defensive worker rejections after enqueue are shown on the source detail as a failed IndexRun with the same structured reason.

---

## 3. API design

### 3.1 Upload endpoint

```
POST /workspaces/{workspace_id}/projects/{project_id}/resources/upload-folder-bundle
```

**Content-Type**: `multipart/form-data`

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | string | yes | Resource display name; max 255 chars |
| `zip_file` | binary file | yes | Must be `application/zip` or `application/x-zip-compressed` (also validated by magic bytes) |
| `update_frequency` | string | no | Must be `"manual"` in A2; non-manual values return 422 |
| `max_file_count` | integer | no | Soft limit; defaults to `DEFAULT_MAX_MANIFEST_FILE_COUNT`; capped at `HARD_MAX_MANIFEST_FILE_COUNT` |
| `max_total_bytes` | integer | no | Soft limit; defaults to `DEFAULT_MAX_MANIFEST_TOTAL_BYTES`; capped at `HARD_MAX_MANIFEST_TOTAL_BYTES` |

**Auth / scope**

- Requires `resource:write` scope.
- Tokens with `allowed_resource_ids` set must be rejected with 403 (`"resource-scoped tokens cannot create new resources"`). This matches the existing guard in `create_resource`.
- Caller must be a project member (`_require_project_member`).

**Request-time validation (synchronous, before DB resource creation/enqueueing)**

1. Content-Length / streaming check: reject if the zip exceeds `HARD_MAX_ZIP_UPLOAD_BYTES` (100 MB for A2) before writing the full file to disk.
2. MIME type: accept `application/zip`, `application/x-zip-compressed`, `application/octet-stream` with a `.zip` filename extension.
3. Magic bytes: read first 4 bytes; reject if not a zip local file header (`PK\x03\x04`) or empty zip/end-of-central-directory signature (`PK\x05\x06`) as supported by Python `zipfile`.
4. Filename extraction: use `UploadFile.filename`; sanitize to alphanumeric + `.` + `-` + `_`; default to `upload.zip`.
5. Structural archive validation: after writing to a temporary upload file but before inserting Resource/IndexRun rows, call `validate_zip_before_extract(temp_zip_path, max_file_count=..., max_total_bytes=...)`. This catches traversal, absolute paths, duplicate normalized paths, file/descendant path-prefix conflicts, symlinks/special files, zip-bomb ratio/total bytes, and too-many-files errors while the browser is still on the connect panel.
6. If any synchronous validation fails, delete the temporary upload file and return the appropriate 4xx response. No Resource or IndexRun row should be created for rejected uploads.

**Successful response** — HTTP 202

```json
{
  "resource": { ...ResourceRead... },
  "index_run": { ...IndexRunRead... }
}
```

`ResourceRead` is the existing Pydantic schema. `IndexRunRead` is the existing schema. The response combines both so the frontend can begin polling the run status without a second request.

**New Pydantic schema** in `apps/api/sourcebrief_api/schemas.py`:

```python
class FolderBundleUploadResponse(BaseModel):
    resource: ResourceRead
    index_run: IndexRunRead
```

**Error responses**

| Condition | HTTP | `detail` |
|---|---|---|
| Zip exceeds size limit | 413 | `"zip upload exceeds max size of {N} bytes"` |
| Magic bytes not zip | 422 | `"uploaded file is not a zip archive"` |
| `name` missing or blank | 422 | `"name is required"` |
| Resource-scoped token | 403 | `"resource-scoped tokens cannot create new resources"` |
| Redis enqueue failure | 503 | `"failed to enqueue index job"` |

**Transaction and cleanup rule**

The upload endpoint must not leave an active orphan when enqueue fails. Use this sequence:

1. Stream upload to a temporary path under `{work_base}/uploads/.incoming-{uuid}.zip`.
2. Run magic and structural validation against the temp file.
3. In one DB transaction, create Resource, IndexRun (`status="enqueueing"`), and `resource.upload` AuditEvent; commit only after the staged path has been atomically renamed to `{work_base}/uploads/{resource_id}.zip` and `resource.source_config["staged_zip_path"]` points to that final path.
4. Attempt RQ enqueue.
5. If enqueue succeeds, set IndexRun `status="queued"` and commit.
6. If enqueue fails, set IndexRun `status="failed"`, set `error_message`, mark the Resource `status="deleted"`/`retrieval_enabled=False` or delete it through `_purge_resource_artifacts`, delete the staged zip, commit the failed state, and return 503. The implementation should prefer failed-state auditability over silent rollback, but it must not leave a runnable active resource or staged zip.

### 3.2 Manifest read endpoint

```
GET /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/manifest
```

**Auth / scope**: `resource:read` scope; token project/resource allowlists apply.

Returns the most recent `ResourceManifest` for the resource (by `created_at DESC LIMIT 1`). Returns 404 if no manifest exists yet (IndexRun still in progress).

**Response** — HTTP 200

```json
{
  "id": "uuid",
  "resource_id": "uuid",
  "source_snapshot_id": "uuid",
  "manifest_hash": "sha256:...",
  "file_count": 10,
  "total_bytes": 52428,
  "parser_warning_count": 0,
  "unsupported_file_count": 2,
  "created_at": "2026-01-01T00:00:00Z",
  "files": [
    {
      "id": "uuid",
      "normalized_path": "src/main.py",
      "display_path": "src/main.py",
      "size_bytes": 1234,
      "content_hash": "sha256:...",
      "mime_type": null,
      "status": "pending",
      "warnings_json": []
    }
  ]
}
```

`files` is the full list of `ResourceManifestFile` rows (up to `HARD_MAX_MANIFEST_FILE_COUNT`; in practice capped by quota at extraction time). No separate pagination for A2. If needed in the future, a `?page=` query parameter can be added without breaking the spec.

**New Pydantic schemas** in `apps/api/sourcebrief_api/schemas.py`:

```python
class ResourceManifestFileRead(BaseModel):
    id: UUID
    normalized_path: str
    display_path: str | None
    size_bytes: int
    content_hash: str
    mime_type: str | None
    status: str
    warnings_json: list

class ResourceManifestRead(BaseModel):
    id: UUID
    resource_id: UUID
    source_snapshot_id: UUID
    manifest_hash: str
    file_count: int
    total_bytes: int
    parser_warning_count: int
    unsupported_file_count: int
    created_at: datetime
    files: list[ResourceManifestFileRead]
```

---

## 4. Worker / storage design

### 4.1 Staging path

The API writes the zip to a controlled staging path before enqueuing the job. The worker reads from that path and cleans up afterward.

**Staging path convention:**

```
{_work_base()}/uploads/{resource_id}.zip
```

`_work_base()` is the existing helper in `ingestion.py` that returns `SOURCEBRIEF_WORK_DIR` or `/tmp/sourcebrief-ingest`.

The API creates `{_work_base()}/uploads/` on first use (with `os.makedirs(..., exist_ok=True)`).

**Stored in `source_config`:**

```python
source_config = {
    "staged_zip_path": str(staging_path),
    "original_filename": sanitized_filename,
    "zip_size_bytes": len(zip_bytes),
    "max_file_count": effective_max_file_count,
    "max_total_bytes": effective_max_total_bytes,
    "max_zip_bytes": HARD_MAX_ZIP_UPLOAD_BYTES,
}
```

**Worker path validation.** The worker must verify that `Path(source_config["staged_zip_path"]).resolve()` is relative to `Path(_work_base() + "/uploads").resolve()` before opening the file. If the resolved path escapes the uploads directory, raise `RuntimeError("staged zip path is outside work_base/uploads")`. This prevents a compromised `source_config` from pointing the worker at an arbitrary server file.

### 4.2 New module: `bundle_ingest.py`

Location: `packages/worker/sourcebrief_worker/bundle_ingest.py`

This module contains all zip-specific logic. It imports A1 helpers from `manifest.py` but has no knowledge of the ORM — it returns plain dicts that `ingestion.py` and `manifest_store.py` consume.

**Constants** (override via `source_config` up to HARD limits):

```python
HARD_MAX_ZIP_UPLOAD_BYTES = 100_000_000       # 100 MB compressed
DEFAULT_MAX_ZIP_UPLOAD_BYTES = 50_000_000     # 50 MB default soft limit
ZIP_BOMB_MAX_RATIO = 20                        # max uncompressed/compressed ratio
ZIP_BOMB_MIN_COMPRESSED = 1024                 # only check ratio if compressed > 1 KB
```

**`class ZipRejectionError(ValueError)`**

```python
class ZipRejectionError(ValueError):
    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason   # structured reason for logging/UI
        self.detail = detail
        super().__init__(f"zip rejected: {reason}: {detail}")
```

Reasons: `"zip_bomb_ratio"`, `"zip_bomb_total_bytes"`, `"too_many_files"`, `"unsafe_entry"`, `"extraction_failed"`, `"not_a_zip"`, `"nested_archive"`.

**`validate_zip_before_extract(zip_path: str, *, max_file_count: int, max_total_bytes: int) -> None`**

Opens the zip in read mode using `zipfile.ZipFile`. Iterates `zf.infolist()` without extracting:

1. Count total entries; if `len(infolist) > HARD_MAX_MANIFEST_FILE_COUNT`, raise `ZipRejectionError("too_many_files")`.
2. Sum `info.compress_size` and `info.file_size` across all entries. If `sum(file_size) > HARD_MAX_MANIFEST_TOTAL_BYTES`, raise `ZipRejectionError("zip_bomb_total_bytes")`.
3. If `sum(compress_size) >= ZIP_BOMB_MIN_COMPRESSED` and `sum(file_size) / sum(compress_size) > ZIP_BOMB_MAX_RATIO`, raise `ZipRejectionError("zip_bomb_ratio")`.
4. For each entry:
   - Determine `entry_type`: zipfile does not expose symlinks directly — check `info.external_attr >> 16` for Unix mode bits. If `stat.S_ISLNK(mode)`, classify as `"symlink"`. If `stat.S_ISBLK(mode) or stat.S_ISCHR(mode)`, classify as `"device"`. If `stat.S_ISFIFO(mode)`, classify as `"fifo"`. If name ends with `/` or `stat.S_ISDIR(mode)`, classify as `"dir"`. If `stat.S_ISREG(mode)`, classify as `"file"`. If no Unix file-type bits are present (`mode & 0o170000 == 0`) and the name is not a directory, classify as `"file"` because normal `zipfile.writestr()` entries commonly omit `S_IFREG`. Otherwise classify as `"other"`.
   - Determine `depth`: count `/`-separated components (strip trailing `/`), subtract 1.
   - Call `validate_archive_entry(info.filename, entry_type, depth)` from A1 `manifest.py`. Re-raise `ManifestPathError` as `ZipRejectionError("unsafe_entry", ...)`.
   - Detect nested archives: if `entry_type == "file"` and `normalize_path(info.filename)` has an extension in `{".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz", ".7z", ".rar"}`, do NOT raise but mark the entry for `status="unsupported"` — see extraction step.

This function raises before any bytes leave the zip. It is pure and has no filesystem side-effects beyond opening the file for reading.

**`extract_zip_to_sandbox(zip_path: str, sandbox_dir: str, *, max_file_count: int, max_total_bytes: int) -> list[dict]`**

Extracts accepted file entries to `sandbox_dir`. Returns a list of file row dicts (input for manifest creation).

Algorithm:

1. Call `validate_zip_before_extract(zip_path, ...)` first.
2. Open `zipfile.ZipFile(zip_path, "r")`.
3. Initialize `files_extracted = 0`, `total_bytes_written = 0`.
4. For each entry:
   a. Re-run the entry classification from step 4 above (no double-parsing; caller already validated, but extraction loop re-classifies to determine how to handle each entry).
   b. If `entry_type` in `{"symlink", "device", "fifo", "socket", "other", "hardlink"}`: skip — these were validated away already, but guard defensively.
   c. If `entry_type == "dir"`: skip (directories are implicit from file paths).
   d. Get `normalized_path` via `normalize_path(info.filename)` (already validated; re-run is fine since it's cheap string ops).
   e. If the entry is a known nested archive (extension check as above): add a `status="unsupported"` manifest file row with `content_hash="sha256:" + hashlib.sha256(b"").hexdigest()` and `size_bytes=info.file_size`; continue without extracting.
   f. If `info.file_size > HARD_MAX_SINGLE_FILE_BYTES` (from A1 constants): add `status="skipped"` row; continue.
   g. If `files_extracted >= max_file_count` or `total_bytes_written + info.file_size > max_total_bytes`: add `status="skipped"` row; continue.
   h. Compute `dest = os.path.join(sandbox_dir, normalized_path)`. Call `_safe_extract_dest(dest, sandbox_dir)` — see below.
   i. `os.makedirs(os.path.dirname(dest), exist_ok=True)` — safe because `normalized_path` has no traversal.
   j. Read bytes: `raw = zf.read(info.filename)`. Verify `len(raw) <= HARD_MAX_SINGLE_FILE_BYTES` (defense against incorrect `file_size` in the header).
   k. Write to `dest`.
   l. Compute `content_hash = "sha256:" + hashlib.sha256(raw).hexdigest()`.
   m. Determine file status:
      - If extension in `SKIP_EXTS` or not `is_text_file(raw[:8192])`: `status="unsupported"`.
      - Else: `status="pending"`.
   n. Build file row dict:
      ```python
      {
          "normalized_path": normalized_path,
          "display_path": info.filename,
          "path_hash": "sha256:" + hashlib.sha256(normalized_path.encode()).hexdigest(),
          "content_hash": content_hash,
          "size_bytes": info.file_size,
          "status": status,
          "warnings_json": [],
          "text": raw.decode("utf-8", errors="replace") if status == "pending" else None,
      }
      ```
   o. Increment counters.
5. Return file row list. `text` field is for chunking; never stored in `ResourceManifestFile`.

**`_safe_extract_dest(dest: str, sandbox_dir: str) -> None`**

Resolves `dest` and raises `ZipRejectionError("unsafe_entry", "extraction path escapes sandbox")` if the resolved path is not under `sandbox_dir`. This is a final defense against zip implementations that parse `.` and `..` in filenames differently from Python's `normalize_path`.

```python
resolved = os.path.realpath(dest)
sandbox_real = os.path.realpath(sandbox_dir)
if not resolved.startswith(sandbox_real + os.sep) and resolved != sandbox_real:
    raise ZipRejectionError("unsafe_entry", f"extraction path escapes sandbox: {dest!r}")
```

### 4.3 New connector in `ingestion.py`

Add `FOLDER_BUNDLE_TYPES = {"folder_bundle"}` to `ingestion.py`.

Add `_collect_folder_bundle(resource: Resource) -> tuple[list[dict], str, str, dict]`:

```python
def _collect_folder_bundle(resource: Resource) -> tuple[list[dict], str, str, dict]:
    from sourcebrief_worker.bundle_ingest import (
        extract_zip_to_sandbox, ZipRejectionError,
        HARD_MAX_ZIP_UPLOAD_BYTES,
    )
    config = resource.source_config or {}
    staged_zip_path = config.get("staged_zip_path")
    if not staged_zip_path:
        raise RuntimeError("folder_bundle source_config missing staged_zip_path")

    # Validate staging path is under work_base/uploads
    uploads_dir = os.path.join(_work_base(), "uploads")
    real_staged = os.path.realpath(staged_zip_path)
    real_uploads = os.path.realpath(uploads_dir)
    if not real_staged.startswith(real_uploads + os.sep):
        raise RuntimeError("staged zip path is outside work_base/uploads")

    max_file_count = min(
        int(config.get("max_file_count", DEFAULT_MAX_MANIFEST_FILE_COUNT)),
        HARD_MAX_MANIFEST_FILE_COUNT,
    )
    max_total_bytes = min(
        int(config.get("max_total_bytes", DEFAULT_MAX_MANIFEST_TOTAL_BYTES)),
        HARD_MAX_MANIFEST_TOTAL_BYTES,
    )

    sandbox_dir = tempfile.mkdtemp(prefix="bundle-", dir=_work_base())
    file_rows = []
    try:
        file_rows = extract_zip_to_sandbox(
            staged_zip_path,
            sandbox_dir,
            max_file_count=max_file_count,
            max_total_bytes=max_total_bytes,
        )
    finally:
        shutil.rmtree(sandbox_dir, ignore_errors=True)
        # Clean up staging zip regardless of success or failure
        try:
            os.unlink(staged_zip_path)
        except OSError:
            pass

    docs = [
        {
            "path": row["normalized_path"],
            "title": row["normalized_path"],
            "content": row["text"],
            "meta": {
                "source": "folder_bundle",
                "path": row["normalized_path"],
                "content_hash": row["content_hash"],
            },
        }
        for row in file_rows
        if row["status"] == "pending" and row.get("text")
    ]
    combined_hash = content_hash("\n".join(row["content_hash"] for row in sorted(file_rows, key=lambda r: r["normalized_path"])))
    meta = {
        "source": "folder_bundle",
        "original_filename": config.get("original_filename", "upload.zip"),
        "zip_size_bytes": config.get("zip_size_bytes", 0),
        "file_count": len(file_rows),
        "manifest_file_rows": file_rows,  # consumed by manifest creation step in ingest_resource
    }
    return docs, combined_hash, "content_hash", meta
```

Add `FOLDER_BUNDLE_TYPES` branch to `ingest_resource` dispatch block:

```python
elif rtype in FOLDER_BUNDLE_TYPES:
    docs, version, version_kind, meta = _collect_folder_bundle(resource)
```

Before `snapshot.meta = meta`, remove manifest rows from metadata:

```python
manifest_file_rows: list[dict] = []
if rtype in FOLDER_BUNDLE_TYPES:
    manifest_file_rows = list(meta.pop("manifest_file_rows", []))
```

This is mandatory because current `ingest_resource` assigns `snapshot.meta = meta` before chunking and graph building. `manifest_file_rows` may include transient `text`; it must never be persisted in `source_snapshots.meta`.

Change SnapshotFile creation to include folder bundles. Current code only creates `SnapshotFile` rows for `resource.type.lower() == "git"`; A2 must update that condition to `rtype in GIT_TYPES | FOLDER_BUNDLE_TYPES` or equivalent so folder text files get snapshot file evidence.

After the snapshot + chunks section of `ingest_resource` (after `build_graph_index`, before `resource.current_snapshot_id = snapshot.id`), create the manifest from the already-popped rows:

```python
if rtype in FOLDER_BUNDLE_TYPES:
    from sourcebrief_worker.manifest_store import ManifestFileInput, create_resource_manifest
    create_resource_manifest(
        session,
        workspace_id=resource.workspace_id,
        project_id=resource.project_id,
        resource_id=resource.id,
        source_snapshot_id=snapshot.id,
        files=[ManifestFileInput(**_manifest_input(row)) for row in manifest_file_rows],
    )
```

`meta` is cleaned of `manifest_file_rows` before being stored in `snapshot.meta` so large file row lists do not inflate the JSONB column.

### 4.4 `manifest_store.create_resource_manifest` (A1 already exists; use actual signature)

The A1 implementation defines this in `packages/worker/sourcebrief_worker/manifest_store.py`:

```python
def create_resource_manifest(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    source_snapshot_id: UUID,
    files: list[ManifestFileInput],
    actor_user_id: UUID | None = None,
    actor_token_id: UUID | None = None,
) -> ResourceManifest:
    ...
```

Implement a small adapter in `ingestion.py` or `bundle_ingest.py`, for example `_manifest_input(row)`, that maps worker row dicts into `ManifestFileInput` and deliberately drops transient keys such as `text` and `path_hash`. `path_hash` is recomputed by A1 `manifest_store.compute_path_hash`; do not pass it through from untrusted upload-derived data.

### 4.5 Cleanup guarantee

The staging zip is deleted in the `_collect_folder_bundle` `finally` block regardless of success or failure after the job starts. The API endpoint must also delete temporary/staged files on synchronous validation failure and enqueue failure.

Add A2-owned stale upload cleanup, not just an operator note:

- Create `cleanup_stale_uploads(work_base: str, max_age_seconds: int = 86400) -> dict` in `bundle_ingest.py`.
- Call it from worker startup/maintenance path or add it to existing maintenance worker code if available.
- It only deletes `*.zip` and `.incoming-*.zip` under `{work_base}/uploads` after validating the resolved path is still under that directory.
- It returns counts/bytes deleted and emits a structured log.
- Add a unit test using a temp uploads directory with old/new files.

Operators can still purge manually if needed:

```bash
find "$(printenv SOURCEBRIEF_WORK_DIR || echo /tmp/sourcebrief-ingest)/uploads" \
  \( -name "*.zip" -o -name ".incoming-*.zip" \) -mtime +1 -delete
```

### 4.6 Shared filesystem deployment precondition

A2's staging design requires API and worker containers to share the same `SOURCEBRIEF_WORK_DIR` volume. This is an explicit deployment contract:

- `docker-compose.yml` must mount the same named volume/path into `api`, `worker-default`, and `worker-maintenance` if it does not already.
- Add a lightweight startup/health helper `validate_upload_staging_dir()` that creates `{work_base}/uploads`, writes and removes a tiny probe file, and verifies free disk is above a conservative threshold (for local dev, at least `HARD_MAX_ZIP_UPLOAD_BYTES`).
- API upload endpoint calls this helper before accepting an upload; worker `_collect_folder_bundle` also validates path readability under the same directory.
- If the path is not writable/readable, API returns 503 before reading the upload.

### 4.7 Minimum observability contract

A2 must emit structured logs and low-cardinality metrics/counters where this repo's current observability hooks allow it. At minimum, structured logs must include `workspace_id`, `project_id`, `resource_id` when available, `index_run_id` when available, and `reason` for `ZipRejectionError`.

Required events/counters:

- upload accepted: bytes, original filename, resource_id, index_run_id
- upload rejected: reason, bytes read, no resource_id if rejected before DB create
- enqueue failed: resource_id, index_run_id, staged_zip_deleted boolean
- extraction failed: `ZipRejectionError.reason`
- staging cleanup: files_deleted, bytes_deleted, failures
- staging free-disk warning: free_bytes, required_bytes

---

## 5. Data model usage

No new Alembic migration is required for A2. All tables already exist after A1.

| Table | How it is used in A2 |
|---|---|
| `resources` | New row with `type="folder_bundle"` and `uri="upload://{name}"`. `source_config` stores `staged_zip_path`, `original_filename`, `zip_size_bytes`, `max_file_count`, `max_total_bytes`. |
| `source_snapshots` | Created by `ingest_resource` as normal. `meta` stores `source`, `original_filename`, `zip_size_bytes`, `file_count`. `manifest_file_rows` is popped before storage. |
| `resource_manifests` | One row per upload, created by `create_manifest`. `file_count` = total entries (including unsupported/skipped). `unsupported_file_count` and `parser_warning_count` computed from file rows. |
| `resource_manifest_files` | One row per zip entry (accepted + unsupported + skipped up to quota). `status` is `"pending"` (text files), `"unsupported"` (binary/nested archive), or `"skipped"` (quota exceeded). |
| `snapshot_files` | Created by `ingest_resource` for text (`status="pending"`) files only, same as git connector. |
| `chunks` | Created by the existing chunking loop in `ingest_resource` for docs returned by `_collect_folder_bundle`. |
| `index_runs` | Existing lifecycle; created by the upload endpoint alongside the resource, same pattern as `refresh_resource`. |
| `audit_events` | `resource.upload` (at upload time), `manifest.created` (in `create_manifest`). |

**`source_config` field contract for `type="folder_bundle"`:**

```python
{
    "staged_zip_path": str,       # absolute path under {work_base}/uploads/
    "original_filename": str,     # sanitized filename from UploadFile
    "zip_size_bytes": int,        # compressed size
    "max_file_count": int,        # effective limit applied during extraction
    "max_total_bytes": int,       # effective limit applied during extraction
    "max_zip_bytes": int,         # validated at upload time
}
```

**No new type enum or migration** — `type` is a `Text` column; adding `"folder_bundle"` as a string value requires no schema change.

**New constant** in `apps/api/sourcebrief_api/constants.py`:

```python
FOLDER_BUNDLE_RESOURCE_TYPES = {"folder_bundle"}
```

This is used in the upload endpoint to gate `_validate_source_config` (which does not apply to folder bundles — source_config is built programmatically by the endpoint, not derived from the JSON body).

`packages/worker/sourcebrief_worker/ingestion.py` should define its own matching connector set or import the API constant only if that does not introduce an API→worker dependency cycle. Prefer keeping the worker-side set local (`FOLDER_BUNDLE_TYPES = {"folder_bundle"}`) as existing ingestion connector sets are local.

---

## 6. Security and quota design

### 6.1 At upload time (API, synchronous)

| Check | Limit | Error |
|---|---|---|
| Zip compressed size | `HARD_MAX_ZIP_UPLOAD_BYTES` = 100 MB | 413 |
| Magic bytes / malformed zip | — | 422 |
| Structural validation | traversal, symlink/special file, absolute path, too many files, zip-bomb ratio/total bytes | 422/413 before Resource creation |
| `name` blank | — | 422 |
| Resource-scoped token | — | 403 |

The API reads only enough bytes to validate magic bytes (4 bytes) before streaming to disk. Streaming write: the API should use `UploadFile.read()` in chunks (e.g., 64 KB at a time) while counting bytes, rejecting if the running total exceeds `HARD_MAX_ZIP_UPLOAD_BYTES`. This prevents a slow-drip oversized upload from consuming memory.

### 6.2 At extraction time (worker, async)

| Check | Constant | Behavior |
|---|---|---|
| Zip bomb ratio | `ZIP_BOMB_MAX_RATIO = 20` | `ZipRejectionError("zip_bomb_ratio")` — IndexRun fails |
| Total uncompressed bytes | `HARD_MAX_MANIFEST_TOTAL_BYTES` = 2 GB | `ZipRejectionError("zip_bomb_total_bytes")` — IndexRun fails |
| Total entry count | `HARD_MAX_MANIFEST_FILE_COUNT` = 50,000 | `ZipRejectionError("too_many_files")` — IndexRun fails |
| Per-entry: symlink | mode bits or name pattern | `ZipRejectionError("unsafe_entry")` via `ManifestPathError("unsafe_entry_type")` |
| Per-entry: path traversal | `..` component | `ZipRejectionError("unsafe_entry")` via `ManifestPathError("path_traversal")` |
| Per-entry: absolute path | leading `/` | `ZipRejectionError("unsafe_entry")` via `ManifestPathError("absolute_path")` |
| Per-entry: depth > 10 | `MAX_ARCHIVE_DEPTH` = 10 | `ZipRejectionError("unsafe_entry")` |
| Per-file size | `HARD_MAX_SINGLE_FILE_BYTES` = 200 MB | `status="skipped"` in manifest file row |
| Nested archive | extension check | `status="unsupported"` in manifest file row; not extracted |
| Sandbox escape | `_safe_extract_dest` path check | `ZipRejectionError("unsafe_entry")` — IndexRun fails |
| Staging path escape | `realpath` vs `work_base/uploads` | `RuntimeError` — IndexRun fails |

When a `ZipRejectionError` or `RuntimeError` propagates out of `_collect_folder_bundle`, the existing `run_index` exception handler marks `IndexRun.status = "failed"` and stores `error_message`. The staging zip is still cleaned up by the `finally` block.

### 6.3 Token scope constraints

- `resource:write` required for upload.
- Resource-scoped tokens (`allowed_resource_ids`) cannot create new resources (existing guard, already enforced in `create_resource`; the upload endpoint mirrors this guard explicitly).
- `resource:read` required for the manifest read endpoint.
- Token `allowed_resource_ids` list applies to the manifest endpoint via the existing `token_allows_resource` guard.

### 6.4 Quota defaults (from A1 constants — no change)

```python
DEFAULT_MAX_MANIFEST_FILE_COUNT = 10_000
DEFAULT_MAX_MANIFEST_TOTAL_BYTES = 500_000_000   # 500 MB
HARD_MAX_MANIFEST_FILE_COUNT = 50_000
HARD_MAX_MANIFEST_TOTAL_BYTES = 2_000_000_000    # 2 GB
MAX_SINGLE_FILE_BYTES = 50_000_000               # 50 MB soft
HARD_MAX_SINGLE_FILE_BYTES = 200_000_000         # 200 MB hard
```

These constants are imported into `bundle_ingest.py` from `manifest.py`. Do not duplicate them.

---

## 7. Frontend changes

File: `apps/web/app/sources/page.tsx`

### 7.1 Type union extension

```typescript
type ResourceType = 'git' | 'url' | 'markdown' | 'upload' | 'folder_bundle';
```

### 7.2 New state variables for folder bundle connect

```typescript
const [zipFile, setZipFile] = useState<File | null>(null);
const [zipError, setZipError] = useState<string | null>(null);
```

### 7.3 Connect panel UI (new `folder_bundle` branch)

When `type === 'folder_bundle'`:

```tsx
<Field label="Folder bundle (.zip)">
  <input
    type="file"
    accept=".zip,application/zip"
    onChange={(e) => {
      const f = e.target.files?.[0] ?? null;
      setZipFile(f);
      setZipError(null);
    }}
  />
  {zipError && <p className="text-red-600 text-sm mt-1">{zipError}</p>}
</Field>
```

`defaultUri` for `folder_bundle` returns `'upload://folder.zip'`.
`defaultName` for `folder_bundle` returns `'New folder bundle'`.

### 7.4 Submit handler for folder bundle

When `type === 'folder_bundle'`, use `FormData` and direct `fetch` with no explicit `Content-Type` header (the browser sets the multipart boundary). Current `client`/`apiFetch` helpers always set `Content-Type: application/json`, so do **not** use them for this endpoint.

```typescript
const formData = new FormData();
formData.append('name', name);
formData.append('update_frequency', frequency);
if (!zipFile) { setZipError('Choose a .zip folder bundle first.'); return; }
formData.append('zip_file', zipFile);

const res = await fetch(
  `${settings.apiBaseUrl}/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources/upload-folder-bundle`,
  {
    method: 'POST',
    headers: { Authorization: `Bearer ${settings.sessionToken}` },
    body: formData,
  }
);
if (!res.ok) {
  const err = await res.json().catch(() => ({ detail: 'upload failed' }));
  setZipError(err.detail ?? 'upload failed');
  return;
}
const data: { resource: Resource; index_run: IndexRun } = await res.json();
setConnectResult(data.resource);
selectResource(data.resource.id);
await reload();
```

### 7.5 Manifest summary in source detail

When the selected resource has `type === 'folder_bundle'` and its IndexRun has `status === 'succeeded'`, fetch the manifest and display a summary card.

```typescript
// New state
const [manifest, setManifest] = useState<ResourceManifest | null>(null);

// Fetch on resource selection change
useEffect(() => {
  if (selectedResource?.type !== 'folder_bundle' || !selectedResource.current_snapshot_id) return;
  client<ResourceManifest>(`/workspaces/${settings.workspaceId}/projects/${settings.projectId}/resources/${selectedResource.id}/manifest`)
    .then((m) => setManifest(m))
    .catch(() => setManifest(null));
}, [client, selectedResource?.id, selectedResource?.current_snapshot_id, selectedResource?.type, settings.workspaceId, settings.projectId]);
```

Manifest summary card (rendered below the existing index-run status row):

```tsx
{manifest && (
  <SectionCard title="Folder manifest">
    <div className="flex gap-4 text-sm">
      <Metric label="Files" value={manifest.file_count} />
      <Metric label="Unsupported" value={manifest.unsupported_file_count} />
      <Metric label="Warnings" value={manifest.parser_warning_count} />
      <Metric label="Total size" value={short(manifest.total_bytes)} />
    </div>
  </SectionCard>
)}
```

**New type in `apps/web/lib/types.ts`** (or wherever `Resource`, `IndexRun` etc. are declared):

```typescript
export type ResourceManifest = {
  id: string;
  resource_id: string;
  source_snapshot_id: string;
  manifest_hash: string;
  file_count: number;
  total_bytes: number;
  parser_warning_count: number;
  unsupported_file_count: number;
  created_at: string;
  files: ResourceManifestFile[];
};

export type ResourceManifestFile = {
  id: string;
  normalized_path: string;
  display_path: string | null;
  size_bytes: number;
  content_hash: string;
  mime_type: string | null;
  status: string;
  warnings_json: string[];
};
```

---

## 8. Files to create or modify

| File | Action | Description |
|---|---|---|
| `packages/worker/sourcebrief_worker/bundle_ingest.py` | Create | Zip extraction sandbox, staging-dir validation, stale upload cleanup, `validate_zip_before_extract`, `extract_zip_to_sandbox`, `_safe_extract_dest`, `ZipRejectionError` |
| `packages/worker/sourcebrief_worker/ingestion.py` | Modify | Add `FOLDER_BUNDLE_TYPES`, `_collect_folder_bundle`, dispatch branch and post-snapshot manifest creation in `ingest_resource` |
| `packages/worker/sourcebrief_worker/manifest_store.py` | Use existing | Use `ManifestFileInput` + `create_resource_manifest`; do not change A1 signature unless implementation proves a narrow adapter belongs there |
| `apps/api/sourcebrief_api/main.py` | Modify | Add `upload_folder_bundle` endpoint; add `get_resource_manifest` endpoint; import `FolderBundleUploadResponse`, `ResourceManifestRead` |
| `apps/api/sourcebrief_api/schemas.py` | Modify | Add `FolderBundleUploadResponse`, `ResourceManifestRead`, `ResourceManifestFileRead` |
| `apps/api/sourcebrief_api/constants.py` | Modify | Add `FOLDER_BUNDLE_RESOURCE_TYPES = {"folder_bundle"}` |
| `apps/web/app/sources/page.tsx` | Modify | Add `folder_bundle` type, zip file picker, FormData upload, manifest summary card |
| `apps/web/lib/types.ts` | Modify | Add `ResourceManifest`, `ResourceManifestFile` types |
| `docker-compose.yml` | Verify/modify | Ensure API and workers share `SOURCEBRIEF_WORK_DIR` volume for staged uploads |
| `tests/unit/test_bundle_ingest.py` | Create | Unit tests for all zip-bomb, traversal, symlink, nested archive cases |
| `tests/integration/test_folder_bundle_flow.py` | Create | Integration tests: API upload → RQ job → DB state → manifest endpoint |

No migration file required.

---

## 9. Tests

### 9.1 Unit tests — `tests/unit/test_bundle_ingest.py`

All tests use synthetic in-memory zips created with `zipfile.ZipFile(io.BytesIO(), "w")`. No database, no network, no filesystem writes (except `tempfile.mkdtemp` for extraction sandbox tests).

**Import only**: `sourcebrief_worker.bundle_ingest`, `sourcebrief_worker.manifest` (A1).

| Test ID | Scenario | Expected |
|---|---|---|
| `test_valid_zip_passes_validation` | Zip with 3 plain text files, no traversal | `validate_zip_before_extract` returns without raising |
| `test_zip_bomb_ratio` | 1 KB compressed / 100 KB uncompressed (ratio 100) | `ZipRejectionError(reason="zip_bomb_ratio")` |
| `test_zip_bomb_total_bytes` | Entry `file_size` sum > `HARD_MAX_MANIFEST_TOTAL_BYTES` | `ZipRejectionError(reason="zip_bomb_total_bytes")` |
| `test_too_many_files` | `HARD_MAX_MANIFEST_FILE_COUNT + 1` entries | `ZipRejectionError(reason="too_many_files")` |
| `test_symlink_entry_rejected` | Entry with Unix mode bits `0o120000` (symlink) | `ZipRejectionError(reason="unsafe_entry")` |
| `test_path_traversal_rejected` | Entry named `../../etc/passwd` | `ZipRejectionError(reason="unsafe_entry")` |
| `test_absolute_path_rejected` | Entry named `/etc/passwd` | `ZipRejectionError(reason="unsafe_entry")` |
| `test_nested_zip_unsupported` | Entry named `archive.zip` | `extract_zip_to_sandbox` includes row with `status="unsupported"`, no recursive extraction |
| `test_nested_tar_unsupported` | Entry named `data.tar.gz` | Same as above for `.tar.gz` |
| `test_oversized_single_file_skipped` | Entry `file_size > HARD_MAX_SINGLE_FILE_BYTES` | Row has `status="skipped"` |
| `test_file_count_quota_skipped` | More files than `max_file_count` param | Files beyond quota have `status="skipped"` |
| `test_binary_file_unsupported` | Entry with null bytes in content | `status="unsupported"`, no text in row |
| `test_text_file_pending` | Entry with valid UTF-8 content | `status="pending"`, `text` field populated |
| `test_content_hash_correct` | Known file content | `content_hash` matches `"sha256:" + sha256(content).hexdigest()` |
| `test_staging_path_validation` | `staged_zip_path` pointing outside `work_base/uploads` | `RuntimeError` before extraction |
| `test_sandbox_escape_rejected` | Craft zip that passes `validate_zip_before_extract` but `_safe_extract_dest` would escape | `ZipRejectionError(reason="unsafe_entry")` |
| `test_unicode_paths_normalized` | Entry named `src/café/main.py` | `normalized_path` preserved as-is (Unicode is allowed; only structural checks) |
| `test_windows_backslash_path` | Entry named `src\\lib\\util.py` | `normalized_path = "src/lib/util.py"` |
| `test_empty_zip` | Zip with zero entries | `extract_zip_to_sandbox` returns empty list |
| `test_directory_entries_skipped` | Explicit directory entry ending in `/` | No file row for directory; not included in returned list |
| `test_zipfile_writestr_entries_classified_as_file` | Normal `zipfile.writestr()` entry with no file-type mode bits | Accepted as `file`, not rejected as `other` |
| `test_cleanup_stale_uploads_deletes_only_old_uploads` | Temp uploads dir has old/new files plus non-zip | Deletes only old `.zip`/`.incoming-*.zip` under uploads dir |
| `test_validate_upload_staging_dir_probe` | Temp work dir | Creates uploads dir, writes/removes probe file, reports capacity |

### 9.2 Integration tests — `tests/integration/test_folder_bundle_flow.py`

Use real Postgres via the existing integration test session fixture. Synthesize a valid in-memory zip; do not rely on test fixtures stored on disk.

| Test ID | Scenario | Expected |
|---|---|---|
| `test_upload_endpoint_creates_resource_and_index_run` | POST multipart to upload endpoint with valid zip | HTTP 201; `resource.type == "folder_bundle"`; `index_run.status in {"queued", "enqueueing"}` |
| `test_upload_resource_scoped_token_blocked` | POST with token that has `allowed_resource_ids` set | HTTP 403 |
| `test_upload_exceeds_size_limit` | POST zip > `HARD_MAX_ZIP_UPLOAD_BYTES` | HTTP 413 |
| `test_upload_not_a_zip_magic_bytes` | POST file without `PK\x03\x04` header | HTTP 422 |
| `test_upload_structural_validation_rejects_traversal_before_resource_create` | POST zip with `../` entry | HTTP 422; no Resource/IndexRun row created; temp file removed |
| `test_enqueue_failure_marks_run_failed_and_deletes_staged_zip` | Patch queue enqueue to fail after DB create | HTTP 503; no active Resource; staged zip removed; failed run/audit evidence retained or purge verified |
| `test_run_index_folder_bundle_succeeds` | Call `run_index(index_run_id)` directly with valid staged zip | `IndexRun.status == "succeeded"`; `ResourceManifest` row exists; `file_count > 0` |
| `test_run_index_creates_manifest_rows` | Same as above + query `resource_manifest_files` | Correct count of `ResourceManifestFile` rows with `normalized_path` values |
| `test_run_index_creates_snapshot_files` | Text files in zip → `snapshot_files` rows | `SnapshotFile` rows exist for text-only files |
| `test_run_index_creates_chunks` | Text files in zip → chunks rows | `Chunk` rows exist; `chunks.count > 0` |
| `test_run_index_zip_bomb_fails_run` | Staged zip has ratio > 20 | `IndexRun.status == "failed"`; `error_message` contains `"zip_bomb"` |
| `test_run_index_traversal_zip_fails_run` | Entry with `../` path | `IndexRun.status == "failed"`; `error_message` contains traversal |
| `test_run_index_staging_zip_cleaned_up` | After successful run | `staged_zip_path` file no longer exists on disk |
| `test_run_index_failed_zip_staging_cleaned_up` | After failed run (bad zip) | `staged_zip_path` file no longer exists on disk |
| `test_manifest_endpoint_returns_summary` | After successful run, GET manifest endpoint | HTTP 200; `file_count` matches; `files` list present |
| `test_manifest_endpoint_404_before_run` | GET manifest endpoint before IndexRun completes | HTTP 404 |
| `test_audit_events_emitted` | After successful upload + run | `AuditEvent` rows exist for `resource.upload` and `manifest.created` |
| `test_purge_resource_deletes_manifest_rows` | Purge the resource | `resource_manifests` and `resource_manifest_files` rows deleted (existing purge statement in `main.py` already covers this) |
| `test_snapshot_meta_does_not_store_manifest_rows_or_text` | After successful run | `source_snapshots.meta` has summary counts only; no `manifest_file_rows` or file `text` |

### 9.3 Malicious archive generation

Generate malicious zip payloads in-memory in unit/integration tests unless a tiny committed fixture is materially clearer. Do **not** commit large zip bombs or `HARD_MAX_MANIFEST_FILE_COUNT + 1` archives. For manual QA, a helper script may generate files under `/tmp/sourcebrief-malicious-zips/`.

| Filename | Description |
|---|---|
| `traversal.zip` | Entry `../../etc/passwd` |
| `absolute.zip` | Entry `/etc/passwd` |
| `symlink.zip` | Entry with Unix mode `0o120000` |
| `bomb_ratio.zip` | 1 byte compressed / 10 MB uncompressed (using `zipfile.ZIP_DEFLATED` with synthetic data) |
| `too_many_files.zip` | Generated on demand with a small test-specific `max_file_count` override, not committed |
| `nested.zip` | Outer zip containing an inner `inner.zip` entry |
| `deep_path.zip` | Entry with `MAX_ARCHIVE_DEPTH + 1` directory components |

Optional generation script: `tests/fixtures/generate_malicious_zips.py`. It must default to `/tmp/sourcebrief-malicious-zips/` and must not be required for automated tests.

### 9.4 Browser / API real-data QA checklist

Run against a live local stack (`docker compose up` or equivalent):

```bash
# Upload a real zip
curl -s -X POST \
  "http://localhost:18000/workspaces/${WS}/projects/${PROJ}/resources/upload-folder-bundle" \
  -H "Authorization: Bearer ***" \
  -F "name=My test bundle" \
  -F "zip_file=@/tmp/test_bundle.zip" | jq .

# Observe IndexRun status
psql "$DATABASE_URL" -c "SELECT id, status, error_message FROM index_runs ORDER BY created_at DESC LIMIT 3;"

# Verify manifest created
psql "$DATABASE_URL" -c "SELECT id, file_count, unsupported_file_count, total_bytes FROM resource_manifests ORDER BY created_at DESC LIMIT 1;"

# Verify manifest files
psql "$DATABASE_URL" -c "SELECT normalized_path, status FROM resource_manifest_files WHERE resource_manifest_id = '<manifest_id>' LIMIT 20;"

# Read manifest via API
curl -s \
  "http://localhost:18000/workspaces/${WS}/projects/${PROJ}/resources/${RESOURCE_ID}/manifest" \
  -H "Authorization: Bearer ***" | jq '{file_count, unsupported_file_count, parser_warning_count}'

# Verify staging zip was cleaned up
ls "$(printenv SOURCEBRIEF_WORK_DIR || echo /tmp/sourcebrief-ingest)/uploads/"

# Verify audit events
psql "$DATABASE_URL" -c "SELECT action, target_type FROM audit_events WHERE action IN ('resource.upload','manifest.created') ORDER BY created_at DESC LIMIT 5;"
```

---

## 10. Rollback and reversibility

**No migration** — A2 introduces no new tables. Rolling back the code removes all new behaviour.

**Data cleanup** (if needed after a bad deploy):

Prefer the application purge path (`_purge_resource_artifacts`) for each affected folder-bundle resource instead of hand-writing SQL. It already owns the correct dependency order and is covered by integration tests.

If emergency SQL is unavoidable, mirror `_purge_resource_artifacts` exactly and verify against a real DB before running anywhere persistent:

```sql
-- For one resource at a time; repeat from an audited list of folder_bundle resources.
-- Replace :resource_id with a bound parameter in the actual client.
UPDATE resources SET current_snapshot_id = NULL WHERE id = :resource_id;
DELETE FROM pr_requests WHERE resource_id = :resource_id;
DELETE FROM patch_proposals WHERE resource_id = :resource_id;
DELETE FROM agent_card_summaries WHERE resource_id = :resource_id;
DELETE FROM context_packet_items WHERE resource_id = :resource_id;
DELETE FROM retrieval_hits WHERE resource_id = :resource_id;
DELETE FROM chunk_embeddings WHERE resource_id = :resource_id;
DELETE FROM graph_edges WHERE resource_id = :resource_id;
DELETE FROM graph_nodes WHERE resource_id = :resource_id;
DELETE FROM code_symbols WHERE resource_id = :resource_id;
DELETE FROM resource_manifest_files WHERE resource_id = :resource_id;
DELETE FROM resource_manifests WHERE resource_id = :resource_id;
DELETE FROM snapshot_files WHERE resource_id = :resource_id;
DELETE FROM chunks WHERE resource_id = :resource_id;
DELETE FROM index_runs WHERE resource_id = :resource_id;
DELETE FROM source_snapshots WHERE resource_id = :resource_id;
DELETE FROM audit_events WHERE target_id = :resource_id;
DELETE FROM resources WHERE id = :resource_id;
```

**Staging file cleanup** (if worker crashed mid-job):

```bash
find "$(printenv SOURCEBRIEF_WORK_DIR || echo /tmp/sourcebrief-ingest)/uploads" \
  -name "*.zip" -mtime +1 -delete
```

**Frontend rollback** — removing the `folder_bundle` branch from `page.tsx` is safe; existing `folder_bundle` resources will still be listed (they appear as `type="folder_bundle"` which falls through to the default display path).

---

## 11. PR acceptance checklist

**Code completeness**

- [ ] `bundle_ingest.py` created with `validate_zip_before_extract`, `extract_zip_to_sandbox`, `_safe_extract_dest`, `ZipRejectionError`
- [ ] `ingestion.py` has `FOLDER_BUNDLE_TYPES`, `_collect_folder_bundle`, dispatch branch, and manifest creation call after `build_graph_index`
- [ ] A2 adapts worker `file_rows` into A1 `ManifestFileInput` and calls `create_resource_manifest` (no `text` key leaks into ORM; upload-derived `path_hash` is not trusted)
- [ ] `main.py` has `upload_folder_bundle` endpoint (HTTP 201) and `get_resource_manifest` endpoint (HTTP 200 / 404)
- [ ] `schemas.py` has `FolderBundleUploadResponse`, `ResourceManifestRead`, `ResourceManifestFileRead`
- [ ] `constants.py` has `FOLDER_BUNDLE_RESOURCE_TYPES`
- [ ] `sources/page.tsx` has `folder_bundle` type, zip file picker, FormData submit, manifest summary card
- [ ] `types.ts` has `ResourceManifest`, `ResourceManifestFile`

**Security**

- [ ] Upload endpoint rejects resource-scoped tokens (HTTP 403)
- [ ] Upload endpoint rejects files larger than `HARD_MAX_ZIP_UPLOAD_BYTES` (HTTP 413)
- [ ] Upload endpoint rejects non-zip magic bytes (HTTP 422)
- [ ] Worker rejects staging path outside `work_base/uploads`
- [ ] Worker rejects zip bombs (ratio and total-bytes checks both exercised by tests)
- [ ] Worker rejects traversal paths (`../`) in zip entries
- [ ] Worker rejects symlinks / device files in zip entries
- [ ] Worker rejects absolute paths in zip entries
- [ ] `_safe_extract_dest` validates final extraction path after all normalization
- [ ] Nested archives produce `status="unsupported"` rows, not recursive extraction
- [ ] Normal `zipfile.writestr()` entries with no file-type bits are accepted as regular files
- [ ] API structural validation rejects malicious archives before Resource/IndexRun creation
- [ ] Enqueue failure does not leave active Resource rows or staged zip files
- [ ] Stale upload cleanup deletes old staged files under uploads dir only
- [ ] API and worker validate `SOURCEBRIEF_WORK_DIR/uploads` readiness/free disk before use
- [ ] Structured logs include `ZipRejectionError.reason` and upload/extraction cleanup outcomes

**Functional**

- [ ] Upload a real 10-file zip via `curl`; IndexRun reaches `succeeded`
- [ ] `resource_manifests.file_count` matches actual file count in zip
- [ ] `resource_manifest_files` rows have correct `normalized_path` values
- [ ] Text files produce `SnapshotFile` and `Chunk` rows
- [ ] Binary files produce `ResourceManifestFile` rows with `status="unsupported"` and no chunks
- [ ] `source_snapshots.meta` contains summary fields only and never stores full manifest rows or file text
- [ ] Staging zip deleted after successful run
- [ ] Staging zip deleted after failed run
- [ ] Manifest read endpoint returns correct JSON (file_count, files list, hash)
- [ ] `AuditEvent` rows exist for `resource.upload` and `manifest.created`

**Tests**

- [ ] All unit tests in `test_bundle_ingest.py` pass without a DB or network
- [ ] All integration tests in `test_folder_bundle_flow.py` pass against real Postgres
- [ ] All malicious zip fixture tests pass (traversal, bomb, symlink, absolute, too-many-files, nested)
- [ ] `test_purge_resource_deletes_manifest_rows` passes (no orphaned manifest rows)

**Frontend**

- [ ] Folder bundle tab visible in connect panel
- [ ] File picker accepts `.zip` only
- [ ] Upload error (e.g. zip bomb) displayed inline on the connect panel without page navigation
- [ ] Manifest summary card visible on source detail after IndexRun succeeds
- [ ] File count, unsupported count, warnings count are real DB values (not placeholders)
- [ ] No `folder_bundle` UUIDs exposed as required input in the connect flow (UI-first, not UUID-first)

**Regression**

- [ ] Existing `git`, `url`, `markdown`, `upload` connect flows unaffected
- [ ] Existing `create_resource` JSON endpoint unaffected
- [ ] Existing `refresh_resource` endpoint unaffected
- [ ] `_purge_resource_artifacts` still covers manifest rows (already present; verify no regression)
