# E0 — Graph Version Storage Implementation Spec

Status: Draft v0.4 after adversarial review  
Branch: `feat/context-artifact-compiler-e0-graph-version-storage`  
Depends on: D Repo Agent V0 (`0019_d_repo_agents`) and existing `graph_nodes` / `graph_edges` tables.

## 1. Goal

Introduce first-class **resource graph** identity and graph version storage before cross-resource merge. Existing graph data is stored directly as resource/snapshot-scoped `graph_nodes` and `graph_edges`; E0 wraps that data in durable graph/version records so E1 can merge graph versions while preserving provenance and compatibility.

E0 is **not** graph merge. It is the storage and compatibility layer for future merge.

## 2. Non-goals

- No project graph compile.
- No merged graph stream.
- No entity-resolution / semantic merge.
- No cross-resource inferred equivalence edges.
- No deletion of existing `graph_nodes` / `graph_edges` rows.
- No user-facing internal UUID-first workflow.

## 3. Current state

Existing tables:

- `graph_nodes`: scoped by workspace/project/resource/source_snapshot and unique `(source_snapshot_id, node_key)`.
- `graph_edges`: scoped by workspace/project/resource/source_snapshot and unique `(source_snapshot_id, source_node_id, target_node_id, edge_type)`.
- Existing APIs read current snapshot graph rows for resource/project views.

Problem:

- A graph has no stable identity separate from a resource snapshot.
- A graph cannot be versioned/published/compared as an artifact.
- E1 merge needs explicit inputs like `graph_version_id[]`, not ad-hoc node/edge filters.

## 4. Proposed model

### 4.1 `graphs`

A stable resource graph stream.

Fields:

- `id uuid pk`
- `workspace_id uuid not null`
- `project_id uuid not null`
- `resource_id uuid null` — non-null for active/retained resource graph; null only for archived zero-version tombstone.
- `graph_key text not null` — human/product-facing slug derived from resource name, e.g. `hello-world-graph`; never `resource:<uuid>`.
- `title text not null`
- `description text null`
- `graph_type text not null default 'resource'` — E0 supports only `resource`; `project`/`merged` reserved for E1+ and not accepted by APIs/UI.
- `status text not null` — `active`, `archived`.
- `current_version_id uuid null`
- `created_by uuid null`
- `created_at timestamptz`
- `updated_at timestamptz`

Constraints:

- unique `(workspace_id, project_id, graph_key)`.
- unique `(workspace_id, project_id, resource_id) WHERE resource_id IS NOT NULL` — exactly one retained resource graph stream per resource in E0.
- unique `(id, workspace_id, project_id)` for scoped version FK.
- unique `(id, workspace_id, project_id, resource_id)` for scoped resource-version FK when resource is retained.
- if `resource_id is not null`, composite FK `(resource_id, workspace_id, project_id) -> resources(id, workspace_id, project_id)`.
- `graph_type = 'resource'` check for E0.
- `status in ('active','archived')`.
- `current_version_id` is validated in application transaction: when non-null, it must point to a `published` version for the same graph. DB-level cross-row status check is not feasible; tests must cover.

### 4.2 `graph_versions`

A retained version of a graph stream.

Fields:

- `id uuid pk`
- `workspace_id uuid not null`
- `project_id uuid not null`
- `graph_id uuid not null`
- `resource_id uuid not null` — retained E0 graph versions are always resource-scoped. Future scrub/tombstone behavior must use a later migration/spec with replacement integrity semantics.
- `source_snapshot_id uuid not null`
- `version int not null`
- `status text not null` — `draft`, `published`, `superseded`, `invalidated`.
- `version_hash text not null`
- `node_count int not null`
- `edge_count int not null`
- `membership_json jsonb not null`
- `provenance_json jsonb not null`
- `summary_json jsonb not null`
- `validation_json jsonb not null`
- `created_by uuid null`
- `published_by uuid null`
- `published_at timestamptz null`
- `invalidated_by uuid null`
- `invalidated_at timestamptz null`
- `status_reason text null`
- `created_at timestamptz`

Constraints:

- unique `(graph_id, version)`.
- scoped FK `(graph_id, workspace_id, project_id) -> graphs(id, workspace_id, project_id)`.
- scoped FK `(graph_id, workspace_id, project_id, resource_id) -> graphs(id, workspace_id, project_id, resource_id)` to guarantee a version cannot point at a different resource than its parent graph.
- scoped FK `(resource_id, workspace_id, project_id) -> resources(id, workspace_id, project_id)`.
- scoped FK `(source_snapshot_id, workspace_id, project_id, resource_id) -> source_snapshots(id, workspace_id, project_id, resource_id)`.
- `version_hash like 'sha256:%'`.
- `node_count >= 0`, `edge_count >= 0`.
- application validation: `published_at` required when status `published`/`superseded`; cannot publish invalidated versions.

### 4.3 Membership compatibility

Do **not** add `graph_version_id` to `graph_nodes`/`graph_edges` in E0. V0 membership references existing rows by deterministic filters and hashes:

```json
{
  "mode": "resource_snapshot",
  "resource_id": "...",
  "source_snapshot_id": "...",
  "node_count": 42,
  "edge_count": 17,
  "node_hash": "sha256:...",
  "edge_hash": "sha256:..."
}
```

This keeps current endpoints compatible and gives E1 stable version inputs.

## 5. Human graph key

Default graph key generation:

1. Normalize resource name or repo name into lowercase slug.
2. Append `-graph`.
3. If collision in `(workspace_id, project_id)`, append `-2`, `-3`, etc.
4. Reject user-provided keys that are reserved (`new`, `api`, `admin`, `merge`, `project`) or not slug-safe.

UI shows graph title/source name first and graph key second. Users never paste UUIDs.

## 6. Compile flow

`POST /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/graph/versions`

1. Require `resource:write` + project membership; resource-scoped write tokens allowed only for that resource.
2. Resolve resource current snapshot.
3. Acquire row lock on resource row first to serialize first graph creation for the resource. Then acquire row lock on existing graph stream if present; otherwise create graph stream inside transaction and flush. If a concurrent insert hits the `(workspace_id, project_id, resource_id)` unique constraint, retry by loading the existing graph with `FOR UPDATE`.
4. Count current snapshot `graph_nodes` and `graph_edges`.
5. Compute deterministic hashes from ordered rows:
   - node hash: `(node_key,node_type,label,path,metadata)`
   - edge hash: `(source_node_id,target_node_id,edge_type,weight,metadata)`
   - version hash: graph key + snapshot id + node/edge hash/counts.
6. If latest draft for this graph has same version hash, return unchanged.
7. Else compute next version while graph row is locked and create draft.
8. Audit `graph_version.compile`.

If a resource has zero graph rows, compile still creates a valid graph version with `node_count=0`, `edge_count=0`, and validation warning `empty_graph`; publish is allowed because absence of code graph is still useful provenance.

## 7. Publish / invalidate / archive

### Publish

`POST /workspaces/{workspace_id}/projects/{project_id}/graphs/{graph_key}/versions/{version}/publish`

- Body requires `{comment: string}` non-empty.
- Require `review:write` and non-resource-scoped token.
- Acquire graph row lock.
- Validate graph is active.
- Validate draft status and `validation_json.ok`.
- Validate resource current snapshot still equals draft `source_snapshot_id`; stale draft returns 422 and must be recompiled.
- Supersede previous current published version in same transaction.
- Set draft to `published`, set graph `current_version_id`, persist comment in `status_reason`, audit `graph_version.publish`.

### Invalidate

`POST /workspaces/{workspace_id}/projects/{project_id}/graphs/{graph_key}/versions/{version}/invalidate`

- Body requires `{comment: string}` non-empty.
- Require `review:write` and non-resource-scoped token.
- Cannot invalidate current published version unless graph is archived or another version is published first.
- Set status invalidated, clear `graphs.current_version_id` if archived current is invalidated.
- Audit `graph_version.invalidate`.

### Archive

`POST /workspaces/{workspace_id}/projects/{project_id}/graphs/{graph_key}/archive`

- Body requires `{comment: string}` non-empty.
- Require `review:write` and non-resource-scoped token.
- Blocks compile/publish new retained versions.
- If graph has zero versions, null `graphs.resource_id` to unblock resource purge.
- Audit `graph.archive`.

E0 does not implement graph version scrub. Retained graph versions intentionally keep source/snapshot provenance. Hard purge returns actionable 409 if retained graph versions remain.

## 8. API deliverables

- `GET /workspaces/{workspace_id}/projects/{project_id}/graphs`
- `GET /workspaces/{workspace_id}/projects/{project_id}/graphs/{graph_key}`
- `POST /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/graph/versions`
- `POST /workspaces/{workspace_id}/projects/{project_id}/graphs/{graph_key}/versions/{version}/publish`
- `POST /workspaces/{workspace_id}/projects/{project_id}/graphs/{graph_key}/versions/{version}/invalidate`
- `POST /workspaces/{workspace_id}/projects/{project_id}/graphs/{graph_key}/archive`

## 9. UI deliverable

Add `/graphs` page:

- list resource graph streams: title, resource name, current version, node/edge counts, draft count;
- resource selector to compile a graph version from current indexed graph rows;
- selected graph panel:
  - current published graph version;
  - newest draft summary and validation;
  - publish button requiring comment;
  - version history with invalidate/archive lifecycle;
  - compatibility note: existing graph APIs remain current-snapshot based until E1 merge.

No project/merged graph UI in E0.

## 10. Purge, retention, and authorization

- Hard purge of a resource must block while any `graphs.resource_id` or retained `graph_versions.resource_id` references the resource.
- Hard purge must also block deletion of source snapshots/graph rows implicitly because retained graph versions reference `source_snapshot_id` and row membership hashes. Resource purge only proceeds after graph references are cleared/absent.
- Archive zero-version graph stream nulls `graphs.resource_id` to unblock purge.
- Resource-scoped tokens can read graph streams only when `graphs.resource_id` is allowed. Tombstoned graph streams (`resource_id is null`) are hidden from resource-scoped tokens.
- Publish/invalidate/archive require non-resource-scoped `review:write`.
- Project/merged graphs are unsupported in E0 to avoid null-resource ACL ambiguity.

## 11. Compatibility

Existing graph endpoints that read `graph_nodes`/`graph_edges` from current snapshots must continue to return the same shape. E0 adds graph-version endpoints; it does not replace current graph reads.

## 12. Real integration tests

Use real Postgres/API/worker, no mocks:

1. Create/index a real local Git resource or folder bundle that produces graph rows.
2. Compile graph version from current snapshot.
3. Recompile unchanged -> `unchanged=true`.
4. Publish draft with comment -> current version pinned.
5. Modify source, re-index, compile second graph draft -> new version hash.
6. Publishing stale first draft after snapshot changes fails.
7. Resource-scoped token can read only allowed graph.
8. Resource-scoped token cannot publish/invalidate/archive.
9. Hard purge blocks while graph stream/version retained.
10. Zero-version graph stream blocks purge until archived tombstone.
11. Existing graph endpoint remains compatible.

## 13. Verification gates

- Alembic downgrade/upgrade `0019_d_repo_agents <-> 0020_e0_graph_versions`.
- `ruff`, `mypy`.
- `npm --prefix apps/web run lint` and `build`.
- `CONTEXTSMITH_RUN_REAL_INTEGRATION=1 pytest tests/integration/test_manifest_diff_flow.py -q` or split E0 integration file.
- Live compose rebuild + API smoke + browser QA on `/graphs`.
- Hermes adversarial backend/product review must PASS before PR.
