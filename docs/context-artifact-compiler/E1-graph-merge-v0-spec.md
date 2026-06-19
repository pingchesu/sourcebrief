# E1 — Graph Merge V0 Implementation Spec

Status: Draft v0.2 after adversarial review  
Branch: `feat/context-artifact-compiler-e1-graph-merge-v0`  
Depends on: E0 graph version storage (`0020_e0_graph_versions`).

## 1. Goal

Add first-class **project-scoped graph merge** over published resource graph versions. E1 lets a user merge two or more resource graphs into a durable merged graph version, inspect node/edge provenance, review ambiguous reconcile candidates, view graph diffs, and query deterministic paths between human-selected nodes.

This is the Graphify-style merge primitive the product needs, implemented inside ContextSmith with tenant scoping, review gates, provenance, authorization, and UI—not as an offline JSON utility.

## 2. Non-goals

- No LLM/embedding automatic entity resolution.
- No auto-publish of merged behavior.
- No cross-workspace or cross-project merge.
- No destructive mutation of input resource graph versions.
- No accepted equivalence edges before explicit review.
- No UUID-first or technical-key-first user workflow.
- No hard-purge release for retained merge references in E1; retained merge versions intentionally block hard purge until a later scrub/delete lifecycle exists.

## 3. Concepts

### Source graph version

A published E0 `graph_versions` row with parent `graphs.graph_type='resource'`.

### Merged graph stream

E1 uses **separate `graph_merges` tables only**. It does not insert `graphs.graph_type='merged'` rows and does not relax the E0 `graphs.graph_type='resource'` constraint. This avoids weakening E0 resource-graph referential integrity.

Tables:

- `graph_merges`: stable merged graph stream metadata and current version pointer.
- `graph_merge_versions`: retained merged version payloads.
- `graph_merge_inputs`: ordered source graph version inputs.
- `graph_merge_nodes`: materialized merged node table.
- `graph_merge_edges`: materialized merged edge table.
- `graph_merge_reconcile_candidates`: review-required suggested overlap/equivalence candidates.

## 4. Data model

### 4.1 Compatibility constraint added to E0 graph_versions

E1 adds a unique constraint on existing `graph_versions` to support provenance-safe composite FKs:

- unique `(id, workspace_id, project_id, graph_id, resource_id, source_snapshot_id)`.

This guarantees `graph_merge_inputs` copied graph/resource/snapshot columns cannot drift from the referenced input version.

### 4.2 `graph_merges`

Fields:

- `id uuid pk`
- `workspace_id uuid not null`
- `project_id uuid not null`
- `merge_key text not null`
- `title text not null`
- `description text null`
- `status text not null` — `active`, `archived`
- `current_version_id uuid null`
- `created_by uuid null`
- `created_at timestamptz`
- `updated_at timestamptz`

Constraints:

- unique `(workspace_id, project_id, merge_key)`.
- unique `(id, workspace_id, project_id)` for scoped FKs.
- unique `(current_version_id, id, workspace_id, project_id)` nullable support if DB permits; otherwise application transaction validates current pointer.
- `status in ('active','archived')`.
- slug-safe merge key with reserved names rejected.

Current pointer invariant:

- Application transaction must only set `current_version_id` to a `graph_merge_versions` row for the same merge with status `published`.
- Tests must reject cross-merge current assignment and current pointer to draft/invalidated.

### 4.3 `graph_merge_versions`

Fields:

- `id uuid pk`
- `workspace_id uuid not null`
- `project_id uuid not null`
- `graph_merge_id uuid not null`
- `version int not null`
- `status text not null` — `draft`, `published`, `superseded`, `invalidated`
- `merge_strategy text not null` — `union`, `overlay`
- `version_hash text not null`
- `input_hash text not null`
- `node_count int not null`
- `edge_count int not null`
- `candidate_count int not null`
- `unresolved_candidate_count int not null`
- `summary_json jsonb not null`
- `validation_json jsonb not null`
- `created_by uuid null`
- `created_at timestamptz`
- `published_by uuid null`
- `published_at timestamptz null`
- `invalidated_by uuid null`
- `invalidated_at timestamptz null`
- `status_reason text null`

Constraints:

- unique `(graph_merge_id, version)`.
- unique `(id, workspace_id, project_id)` for scoped child FKs.
- unique `(id, graph_merge_id, workspace_id, project_id)` for current pointer validation.
- scoped FK `(graph_merge_id, workspace_id, project_id) -> graph_merges(id, workspace_id, project_id)`.
- `version_hash like 'sha256:%'`, `input_hash like 'sha256:%'`.
- nonnegative counts.

### 4.4 `graph_merge_inputs`

One row per input graph version.

Fields:

- `id uuid pk`
- `workspace_id`, `project_id`
- `graph_merge_version_id uuid not null`
- `input_graph_id uuid not null`
- `input_graph_version_id uuid not null`
- `input_resource_id uuid not null`
- `input_source_snapshot_id uuid not null`
- `ordinal int not null`
- `input_version_hash text not null`

Constraints:

- unique `(graph_merge_version_id, input_graph_version_id)`.
- unique `(graph_merge_version_id, input_resource_id)` — E1 forbids multiple versions from the same resource in one merge.
- unique `(graph_merge_version_id, input_graph_id)` — E1 forbids multiple versions from the same source graph in one merge.
- unique `(graph_merge_version_id, ordinal)`.
- scoped FK `(graph_merge_version_id, workspace_id, project_id) -> graph_merge_versions(id, workspace_id, project_id)` via unique helper if needed.
- composite FK `(input_graph_version_id, workspace_id, project_id, input_graph_id, input_resource_id, input_source_snapshot_id) -> graph_versions(id, workspace_id, project_id, graph_id, resource_id, source_snapshot_id)`.
- scoped FK to `resources` and `source_snapshots` for purge/reference checks.

### 4.5 `graph_merge_nodes`

Materialized merged nodes.

Fields:

- `id uuid pk`
- `workspace_id`, `project_id`
- `graph_merge_version_id uuid not null`
- `merged_node_key text not null`
- `node_type text not null`
- `label text not null`
- `path text null`
- `display_label text not null` — human-first label shown in UI.
- `origin_json jsonb not null` — ordered source node provenance: graph version, resource, snapshot, original node id/key, path.
- `metadata jsonb not null`

Constraints:

- unique `(graph_merge_version_id, merged_node_key)`.
- scoped FK to merge version.

### 4.6 `graph_merge_edges`

Materialized merged edges.

Fields:

- `id uuid pk`
- `workspace_id`, `project_id`
- `graph_merge_version_id uuid not null`
- `source_merged_node_key text not null`
- `target_merged_node_key text not null`
- `edge_type text not null`
- `weight float not null default 1.0`
- `origin_json jsonb not null` — ordered source edge provenance where available.
- `metadata jsonb not null`

Constraints:

- unique `(graph_merge_version_id, source_merged_node_key, target_merged_node_key, edge_type)`.
- scoped FK `(graph_merge_version_id, source_merged_node_key) -> graph_merge_nodes(graph_merge_version_id, merged_node_key)`.
- scoped FK `(graph_merge_version_id, target_merged_node_key) -> graph_merge_nodes(graph_merge_version_id, merged_node_key)`.
- scoped FK to merge version.

### 4.7 `graph_merge_reconcile_candidates`

Review-required suggestions only; they are not accepted merged edges and do not rewrite the materialized graph in E1.

Fields:

- `id uuid pk`
- `workspace_id`, `project_id`
- `graph_merge_version_id uuid not null`
- `candidate_key text not null`
- `candidate_type text not null` — `same_path`, `same_label`, `same_symbol`
- `left_origin_json jsonb not null`
- `right_origin_json jsonb not null`
- `confidence float not null`
- `status text not null` — `open`, `accepted`, `rejected`
- `review_reason text null`
- `reviewed_by uuid null`
- `reviewed_at timestamptz null`

Constraints:

- unique `(graph_merge_version_id, candidate_key)`.
- confidence range `0..1`.
- status check.
- scoped FK to merge version.

## 5. Merge semantics

### 5.1 Inputs

- API accepts graph keys + version numbers or graph version ids; UI uses graph titles/keys and published current versions by default.
- Minimum 2 inputs.
- Every input must be `published`, same workspace/project, parent graph status active, and resource visible to caller.
- E1 rejects multiple input versions from the same resource or same source graph in one merge.
- Resource-scoped tokens can read a merged graph only if all input resources are allowed; they cannot compile/publish/review merged graphs.

### 5.2 Union merge

- Preserve every input node as distinct using identity that includes `input_graph_version_id` and original node key.
- Merged node key format is deterministic but secondary: `src:<input_ordinal>:<node_key_hash>`.
- UI label is human-first: label/path/resource/source, with technical key hidden in details.
- Preserve every input edge translated to merged node keys.
- Candidate generation suggests possible overlaps but does not merge them.

### 5.3 Overlay merge V0

Overlay in E1 is **a layered overlay view**, not semantic equivalence collapse.

- Materialized nodes remain distinct exactly like union.
- Overlay adds grouping metadata for deterministic same-path overlaps so UI can show stacked/layered nodes.
- Same-path/same-label/same-symbol candidates remain review-required suggestions.
- No candidate is auto-marked accepted and no materialized node is collapsed because of overlay.

Applying accepted candidates to rewrite a merged graph is a future milestone: user reviews candidates in E1; a later compile can use accepted decisions explicitly.

### 5.4 Candidate generation

Generate candidates for:

- `same_path`: same normalized path across different resources.
- `same_label`: same normalized label and node_type across different resources.
- `same_symbol`: available only if metadata has symbol-ish fields; otherwise skip.

Candidate confidence is deterministic:

- same path: 0.9
- same symbol: 0.8
- same label: 0.6

All candidates default `open`.

## 6. API

### 6.0 Hard limits

E1 must fail safely before expensive materialization or traversal:

- `MAX_MERGE_INPUTS = 8`; compile with more inputs returns 422 `too_many_inputs`.
- `MAX_MERGE_NODES = 10000`; compile exceeding cap returns 413 `merge_node_limit_exceeded` before inserting materialized rows.
- `MAX_MERGE_EDGES = 25000`; compile exceeding cap returns 413 `merge_edge_limit_exceeded` before inserting materialized rows.
- `MAX_MERGE_CANDIDATES = 5000`; candidate generation truncates at the cap, sets `validation_json.candidate_truncated=true`, and publish requires explicit unresolved/truncated acknowledgement.
- `MAX_PATH_DEPTH = 6`; API rejects larger requested depth with 422.
- `MAX_PATH_VISITED_EDGES = 5000`; path query stops with 413 `path_search_limit_exceeded` if traversal exceeds cap.

Integration tests must cover input-count rejection, compile-size rejection via artificially small test-config caps, and path traversal cap rejection.

### Compile draft

`POST /workspaces/{workspace_id}/projects/{project_id}/graph-merges`

Body:

```json
{
  "merge_key": "checkout-systems-graph",
  "title": "Checkout systems graph",
  "strategy": "union",
  "inputs": [
    {"graph_key": "service-a-graph", "version": 3},
    {"graph_key": "service-b-graph", "version": 2}
  ]
}
```

Behavior:

- Creates or reuses merge stream by key.
- Locks merge stream before computing next version.
- If latest draft has same input hash + strategy + content hash, return unchanged.
- Creates draft merge version and materialized nodes/edges/candidates.

### List/get/data

- `GET /workspaces/{workspace_id}/projects/{project_id}/graph-merges`
- `GET /workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}`
- `GET /workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/versions/{version}/data?kind=nodes|edges|candidates&limit=100&cursor=...`

Data endpoint is paginated to avoid huge responses.

### Publish/invalidate/archive

- `POST /.../graph-merges/{merge_key}/versions/{version}/publish`
- `POST /.../graph-merges/{merge_key}/versions/{version}/invalidate`
- `POST /.../graph-merges/{merge_key}/archive`

All require `review:write`, non-resource-scoped token, and non-empty comment.

Publish revalidates inputs:

- input graph versions still exist and remain `published` or `superseded`;
- input parent resources are not deleted/archived;
- caller can still access all input resources;
- if an input graph has a newer published current, publish returns 422 stale unless body explicitly sets `allow_stale_inputs=true` and comment contains a stale acknowledgement phrase;
- if unresolved candidates exist, publish returns 422 unless body explicitly sets `allow_unresolved_candidates=true` and comment contains an unresolved-candidate acknowledgement phrase.

Default product behavior is reject stale or unresolved merges.

### Path query

`GET /.../graph-merges/{merge_key}/versions/{version}/path?from_node_key=<key>&to_node_key=<key>&max_depth=4`

- Deterministic BFS over materialized merged edges.
- Returns node/edge path and provenance.
- No semantic inference.
- API accepts node keys; UI must provide human-first search/selection and not require manual key entry.

### Review candidates

`POST /.../graph-merges/{merge_key}/versions/{version}/candidates/{candidate_key}/review`

Body `{status: "accepted"|"rejected", reason: "..."}`.

E1 candidate review updates candidate status and publish gating only. It does not rewrite the materialized merge graph. Accepted candidates become explicit review evidence for a later graph-rewrite milestone.

## 7. UI

Add `/graph-merge` product surface.

Required UI:

- Nav entry **Graph merge**.
- Select 2+ published resource graph currents using human titles/source names.
- Strategy picker:
  - `Union`: keep each source graph distinct.
  - `Overlay`: layered view for deterministic same-path overlaps; does not auto-merge entities.
- Compile draft button.
- Merge stream list: key, strategy, current version, input count, unresolved candidate count.
- Selected merge detail:
  - current published summary;
  - newest draft summary;
  - input graph provenance table;
  - node/edge/candidate counts;
  - candidate review table with provenance and reason;
  - graph diff against current when draft exists;
  - path query with human-first node search by label/path/resource/node type and provenance preview; technical key secondary.
- Publish requires review comment and clearly shows stale/unresolved candidate blockers.
- Archive is two-step with impact copy.

## 8. Authorization and safety

- Compile requires `resource:write` + project membership, non-resource-scoped token.
- Publish/invalidate/archive/candidate review require `review:write`, non-resource-scoped token.
- Read requires `resource:read` and access to **all input resources**. If any input resource is hidden, return 404 for the merge, not partial hidden provenance.
- API responses must not leak hidden resource ids in error messages.
- Hard purge of any input resource is blocked while retained graph merge versions reference it. E1 does not implement scrub/delete of retained merge references; invalidated/archived merge versions still block hard purge. A later lifecycle milestone may add explicit scrub/delete.

## 9. Observability

Audit events:

- `graph_merge.compile`
- `graph_merge.publish`
- `graph_merge.invalidate`
- `graph_merge.archive`
- `graph_merge_candidate.review`
- `graph_merge.path_query`

Include merge key/version, strategy, input count, candidate counts, unchanged/stale flags, unresolved override flags, and actor.

## 10. Tests

Real integration test using two local Git repos:

1. Create/index two real Git resources.
2. Compile/publish resource graph versions for both.
3. Compile union merge draft.
4. Verify node/edge counts equal deterministic union and nodes are namespaced by input version.
5. Verify candidate generation for same path or same label.
6. Verify resource-scoped token with only one input resource gets 404 on merged graph.
7. Verify publish is blocked while unresolved candidates exist unless explicit override is supplied.
8. Publish merge and verify current pointer.
9. Change one input resource, publish new resource graph current, then verify stale merge draft publish is rejected.
10. Path query by node key returns deterministic path and provenance; browser path UI uses label/path search.
11. Soft delete one input resource and verify hard purge is blocked by retained merge references.
12. Verify hard limit behavior: too many inputs returns 422, small configured materialization caps return 413 before rows are retained, and path traversal cap returns 413.
13. UI/browser QA loads Graph merge page, shows inputs/provenance/candidates/path query, and no console errors.

## 11. Risks and reversibility

Risks:

- Merge tables can grow fast; V0 must page data endpoint and cap compile input size.
- Overlay semantics can be mistaken for correctness; UI must label overlay as layered view only.
- Authorization must be all-or-nothing for multi-resource merges.

Reversibility:

- E1 adds separate merge tables and endpoints only; existing E0 resource graph storage remains intact.
- Downgrade can drop merge tables if no dependent future artifacts exist.
- If UI is not good enough, API/storage can remain while hiding nav entry.
