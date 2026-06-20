# A3 — Manifest Diff Implementation Spec

Status: Draft for implementation  
Branch: `feat/context-artifact-compiler-a3-manifest-diff`  
Parent milestones: A1 manifest model/path normalization, A2 manual folder-bundle zip upload

## 1. Goal

A3 adds a deterministic manifest diff layer so SourceBrief can answer: "what changed between the current folder/source snapshot and the prior one?" without forcing users to paste internal IDs.

The diff is file-level only in A3. It compares two resource manifests by normalized path, content hash, status, and warning state, then exposes changed/added/deleted/unchanged files through API and Sources UI.

## 2. Non-goals

- No new section model or citation impact computation; that starts in A4.
- No graph diff.
- No LLM summarization.
- No auto-publish or generated repo-agent behavior changes.
- No new DB tables unless implementation proves existing manifests cannot support required queries.

## 3. Product behavior

### 3.1 User-visible flow

1. User uploads a folder bundle zip and indexing succeeds.
2. User uploads a second version of the same logical folder bundle.
3. Source detail shows a **Manifest diff** panel comparing latest vs previous successful manifest.
4. The panel shows counts:
   - Added
   - Changed
   - Deleted
   - Unchanged
   - Warning changes
5. The table shows human paths, status, size, and a reason.
6. Deleted files show a deterministic impact stub: "Section/citation impact will be computed in A4" plus the deleted path count.

### 3.2 No UUID-first workflow

The UI must not ask users for manifest IDs. The default UX is:

- select source/resource in Sources page
- if it has >=2 successful manifests in its server-derived family, show latest-vs-previous diff automatically
- optional advanced API can accept explicit manifest IDs for tests/debug, but UI should not expose those as required inputs

## 4. Current A2 constraint

A2 folder bundles are manual-only and do not refresh the same resource because the staged zip is deleted after worker ingestion. A3 therefore needs one of these minimal mechanisms before diff can be useful:

**Chosen A3 mechanism:** introduce server-derived source family metadata on folder-bundle resources without a DB migration by storing it in `Resource.source_config`:

- First upload creates `source_config.source_family_id = resource.id`.
- Re-upload/update flow passes only `supersedes_resource_id` for the selected resource. The server derives the family from that resource. The UI never needs to know or submit `source_family_id`.
- New upload creates a new Resource + IndexRun but is grouped into the same logical source family.
- Diff default resolves latest two successful manifests for that family.

This avoids mutating old staged zips and keeps A2's manual-only invariant intact.

## 5. Data model

No new tables.

### 5.1 Resource.source_config additions

For `folder_bundle` resources:

```json
{
  "staged_zip_path": "/var/lib/sourcebrief/work/uploads/<resource-id>.zip",
  "original_filename": "docs.zip",
  "source_family_id": "<uuid>",
  "source_family_label": "Product docs",
  "supersedes_resource_id": "<uuid-or-null>"
}
```

Rules:

- `source_family_id` must be a UUID string.
- On first upload, set it to the new resource ID after flush.
- On re-upload, caller must provide only `supersedes_resource_id`; API derives the family from that selected resource and rejects any client-provided `source_family_id`.
- `supersedes_resource_id` is optional and used for UI traceability only.
- Resource-scoped API tokens cannot create new resources or re-upload into a family.

### 5.2 Resource name uniqueness

Current resources have `UniqueConstraint(project_id, name)`. A3 must preserve a stable user-visible family label while generating unique internal resource names.

Rules:

- `source_family_label` is the stable user-visible label shown in the Sources UI.
- First upload: `source_family_label = submitted name`, `Resource.name = submitted name` if available.
- Re-upload: `source_family_label = superseded.source_config.source_family_label or superseded.name`.
- Re-upload `Resource.name` is server-generated and unique, e.g. `{source_family_label} · v{n}` or `{source_family_label} · {short_resource_id}` if the version suffix collides.
- UI groups or labels versions by `source_family_label`, not by the generated unique `Resource.name` alone.
- API response must expose `source_family_label` and `version_label` as safe product metadata in resource list/detail/upload responses for folder bundles. The UI must use these fields for family/version display and must not expose generated internal `Resource.name` as the primary product label.

## 6. Diff semantics

### 6.1 Inputs

A diff compares `base_manifest` and `head_manifest` from the same workspace/project. Normally:

- base = previous successful manifest in same source family
- head = latest successful manifest in same source family

### 6.2 File matching

Key: `normalized_path`.

For each path in union(base.paths, head.paths):

| Case | Classification |
|---|---|
| only in head | `added` |
| only in base | `deleted` |
| in both and `content_hash`, `status`, `mime_type`, `warnings_json` all equal | `unchanged` |
| in both and any compared field differs | `changed` |

Size-only changes should count as changed if content hash is unavailable, but A2 should always have content hash for pending text and unsupported binaries.

### 6.3 Warning changes

A row has `warning_changed=true` if normalized warning arrays differ.

Counts include:

- `added_count`
- `changed_count`
- `deleted_count`
- `unchanged_count`
- `warning_changed_count`
- `base_file_count`
- `head_file_count`

### 6.4 Deleted-file impact stub

A3 returns deterministic stub:

```json
{
  "deleted_file_count": 1,
  "impacted_sections_known": false,
  "message": "Section/citation impact will be computed after A4 section extraction."
}
```

Do not overclaim section/citation impact.

## 7. Backend implementation

### 7.1 New shared/worker helper

Create `packages/worker/sourcebrief_worker/manifest_diff.py` or shared module if API imports it directly.

Functions:

```python
@dataclass(frozen=True)
class ManifestDiffRow:
    normalized_path: str
    change_type: Literal["added", "changed", "deleted", "unchanged"]
    base_file_id: UUID | None
    head_file_id: UUID | None
    base_status: str | None
    head_status: str | None
    base_size_bytes: int | None
    head_size_bytes: int | None
    base_content_hash: str | None
    head_content_hash: str | None
    warning_changed: bool
    reason: str


def build_manifest_diff(base_files: Sequence[ResourceManifestFile], head_files: Sequence[ResourceManifestFile]) -> ManifestDiffResult:
    ...
```

Keep this pure and unit-testable.

### 7.2 API schemas

Add to `apps/api/sourcebrief_api/schemas.py`:

```python
class ManifestDiffRowRead(BaseModel): ...
class DeletedFileImpactStub(BaseModel): ...
class ManifestDiffRead(BaseModel): ...
```

Include manifest IDs in API response for traceability, but UI should display labels/timestamps/versions, not raw IDs as primary workflow.

`ManifestDiffRead` must include pagination metadata:

```python
limit: int
next_cursor: str | None
row_count_returned: int
total_row_count: int
```

Cursor format is opaque to clients and encodes `(change_sort_rank, normalized_path)`. UI may pass it back but must not construct it manually.

### 7.3 Upload endpoint extension

`POST /workspaces/{workspace_id}/projects/{project_id}/resources/upload-folder-bundle`

Add optional multipart field:

- `supersedes_resource_id`: UUID string for the selected resource being versioned

Name behavior:

- First upload keeps existing A2 contract: `name` is required and becomes the family label.
- Re-upload (`supersedes_resource_id` present): UI hides/disables the name field and sends either no `name` or the current family label for compatibility.
- Backend ignores submitted `name` for re-upload except for basic validation/logging; it derives `source_family_label` from superseded resource and generates unique `Resource.name` server-side.
- If a caller tries to change family label during re-upload, API must reject with 422 or ignore deterministically; recommended A3 behavior is reject with `family label changes are not supported in A3`.

Validation:

- Superseded resource must belong to same workspace/project.
- Superseded resource must be `folder_bundle` and not deleted.
- Caller must have project member access and token resource authorization must not be resource-scoped.
- Server derives `source_family_id`; client-provided `source_family_id` is ignored/rejected.

On resource creation:

- If no `supersedes_resource_id`: after flush set `source_family_id` to new resource.id.
- If `supersedes_resource_id` is provided: validate it belongs to a readable same-workspace/project `folder_bundle`, then derive `source_family_id = superseded.source_config.source_family_id or superseded.id`.

API responses may expose a safe public `source_family_label` and `has_manifest_diff`/`version_label`, but should not require UI callers to submit internal family UUIDs.

### 7.4 Diff endpoints

#### Default family diff

```
GET /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/manifest-diff
```

Query params:

- `change_type`: optional repeated filter over `added|changed|deleted|unchanged`
- `limit`: default 100, max 500
- `cursor`: opaque pagination cursor returned by previous page

Behavior:

- Resolve selected resource.
- If `source_config.source_family_id` exists, find latest two successful manifests across folder-bundle resources in that family.
- Else fall back to latest two successful manifests for that resource.
- If fewer than two manifests: return 404/409 with `detail="not enough manifests to diff"`.
- Enforce `resource:read` scope and project membership.
- Enforce `token_allows_resource` for all resources involved. If token cannot access any compared resource, return 404.

#### Explicit diff (for API/tests)

Optional if cheap:

```
GET /workspaces/{workspace_id}/projects/{project_id}/manifest-diff?base_manifest_id=...&head_manifest_id=...
```

Same auth/resource checks.

## 8. Frontend implementation

`apps/web/app/sources/page.tsx`

- When selected source is `folder_bundle`, fetch `/resources/{id}/manifest-diff` after manifest fetch.
- If 404/409 not enough manifests: show neutral empty state: "Upload another zip version to see file-level diff."
- If available, render `Manifest diff` card:
  - metrics: Added / Changed / Deleted / Unchanged / Warnings
  - table sorted by severity: deleted, changed, added, warning-changed, unchanged
  - columns: Path, Change, Base status, Head status, Size delta, Reason
  - deleted impact stub under deleted rows
- Add a simple "Upload new version" affordance in source detail that opens connect panel with folder-bundle selected and hidden `supersedes_resource_id` populated from the selected resource. The server derives family membership.

No UUID inputs in UI.

## 9. Observability and audit

- Existing `resource.upload` and `manifest.created` audit events remain.
- Add no audit event for read-only diff by default.
- Add structured API logs for diff resolution:
  - workspace_id
  - project_id
  - source_family_id
  - base_manifest_id
  - head_manifest_id
  - counts
- Do not log file contents.

## 10. Failure modes

| Failure | Response / behavior |
|---|---|
| fewer than 2 manifests | 409 `not enough manifests to diff` |
| source_family_id not found/inaccessible | 404 |
| cross-project family ID | 404/422 without leaking hidden resource IDs |
| compared manifest missing files | 404 |
| resource-scoped token cannot access related family resource | 404 |
| diff result very large | paginate rows; default `limit=100`, max `limit=500`, include full counts and `next_cursor` |

## 11. Rollback

- Disable UI diff panel by hiding fetch/render path.
- API endpoint is read-only and can be left unused.
- `source_config.source_family_id` is additive metadata; old resources without it still work as single-resource fallback.
- No migration rollback required.

## 12. Test plan

### 12.1 Unit tests

`tests/unit/test_manifest_diff.py`

- added/changed/deleted/unchanged classification
- warning_changed count
- status-only change counts as changed
- deterministic sorting
- pagination/filtering preserves full counts and can retrieve all rows

### 12.2 Integration tests with real DB/API

`tests/integration/test_manifest_diff_flow.py`

1. Login admin against real Postgres-backed API test client.
2. Upload v1 zip:
   - `README.md = old`
   - `keep.txt = same`
   - `delete.txt = gone`
3. Run worker job synchronously or through RQ helper used by A2 tests.
4. Upload v2 zip by passing only `supersedes_resource_id` for v1; server derives the family:
   - `README.md = new` (changed)
   - `keep.txt = same` (unchanged)
   - `added.txt = new` (added)
   - no `delete.txt` (deleted)
5. Fetch default manifest diff for v2 resource.
6. Assert counts: added=1, changed=1, deleted=1, unchanged=1.
7. Assert paths appear under correct change types.
8. Assert deleted impact stub is present and explicitly says impact is not known until A4.
9. Assert upload-v2 accepts only `supersedes_resource_id` and derives family server-side.
10. Assert client-provided `source_family_id` is rejected.
11. Assert pagination/filtering can retrieve all changed/added/deleted rows across multiple pages.
12. Assert resource-scoped token cannot diff inaccessible family resources.

### 12.3 Frontend checks

- `npm --prefix apps/web run lint`
- `npm --prefix apps/web run build`
- Browser smoke on `/sources`:
  - selected folder bundle with one manifest shows empty diff state
  - selected folder bundle with two manifests shows metrics/table
  - no console errors

### 12.4 Full gate

- `ruff`
- `mypy`
- unit tests
- real integration tests
- docker compose build/up for api + workers
- real API smoke uploading v1/v2 zip and fetching diff
- Hermes adversarial review backend + product/UI

## 13. Acceptance checklist

- [ ] User can upload v1/v2 folder zip versions into same source family without handling UUIDs manually.
- [ ] Diff API returns correct counts and paths for 1 changed, 1 added, 1 deleted, 1 unchanged.
- [ ] UI shows manifest diff panel from selected source.
- [ ] Deleted-file impact stub is honest and non-overclaiming.
- [ ] Auth checks prevent cross-project/resource-scope leakage.
- [ ] No mock-only tests.
