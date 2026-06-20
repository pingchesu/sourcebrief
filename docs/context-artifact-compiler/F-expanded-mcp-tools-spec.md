# F — Expanded MCP Tools Implementation Spec

Status: Draft v0.4 after adversarial review  
Branch: `feat/context-artifact-compiler-f-expanded-mcp-tools`  
Depends on: B0 context artifacts, B1 context packs, E0 graph versions, E1 graph merges, existing `/mcp/{workspace_id}/{project_id}` JSON-RPC endpoint.

## 1. Goal

Teach runtime agents to inspect SourceBrief sources without local repository access by expanding the MCP tool surface from repo-code search primitives into artifact/pack/graph-aware tools.

Milestone F ships read-only, permission-scoped tools:

- `sourcebrief.get_context_pack`
- `sourcebrief.list_sources`
- `sourcebrief.get_resource_map`
- `sourcebrief.search`
- `sourcebrief.read_section`
- `sourcebrief.get_graph_inventory`
- `sourcebrief.graph_query`
- `sourcebrief.graph_path`
- freshness metadata on all relevant responses

`list_sources` and `get_graph_inventory` are intentionally added as product/runtime discovery helpers so the rest of the milestone does not become UUID/key-first.

Existing tools remain supported:

- `sourcebrief.get_agent_context`
- `sourcebrief.search_code`
- `sourcebrief.grep_code`
- `sourcebrief.read_file`
- `sourcebrief.find_symbol`
- opt-in patch/PR tools

## 2. Non-goals

- No new mutation MCP tools.
- No direct filesystem/repository access from MCP tools.
- No LLM summarization inside MCP calls.
- No broad agent object redesign.
- No automatic context pack publishing.
- No source corpus download endpoint.
- No hidden fallback to project-wide data when token/resource scope is narrow.

## 3. Existing surfaces and constraints

Current MCP implementation is a minimal JSON-RPC endpoint in `apps/api/sourcebrief_api/main.py`:

- `initialize`
- `tools/list`
- `tools/call`
- `_mcp_tools()` returns static schemas.
- MCP tool errors return structured `isError` payloads rather than throwing transport errors.

Current source-of-truth tables already exist:

- resource/snapshot/manifest/section lineage
- `context_artifacts`, `context_artifact_sources`, `context_artifact_citations`
- `context_pack_versions`, `context_pack_artifacts`, `context_pack_resource_coverage`
- `graphs`, `graph_versions`
- `graph_merges`, `graph_merge_versions`, nodes/edges/candidates/inputs

## 4. Product runtime workflow

Generated skills/adapters should instruct agents:

1. Call `get_context_pack` with no version/key when a curated project pack is desired; use returned source/graph inventory.
2. If no pack is relevant, call `list_sources` to discover authorized human source names and resource ids.
3. Call `get_resource_map` by `resource_ref` (name/key/id) or a resource id discovered from pack/source listing.
4. Call `search` for cited section discovery.
5. Call `read_section` using the exact locator returned by `search`, pack citations, or resource map citations.
6. Call `get_graph_inventory`, `graph_query`, or `graph_path` for architecture/impact questions.
7. Use existing `read_file`/`grep_code`/`find_symbol` only when exact repo file/symbol evidence is needed.

No workflow should require users or agents to paste internal UUIDs as the first step.

## 5. Authorization model

All F tools must preserve current project/resource token semantics:

- Require authenticated principal through the existing MCP endpoint dependency.
- Require project access for the path project.
- Require `project:query` for all F tools.
- Require `resource:read` for any response that exposes resource-scoped rows, resource IDs, snapshot IDs, coverage rows, artifact citations, graph origins, node paths, section text, or freshness details.
- Intersect requested `resource_ids` with `_effective_resource_ids(principal, requested)`.
- For packs/merged graphs spanning multiple resources, return 404/empty if the effective resource set cannot read **every covered input resource** required for that artifact/version.
- Never leak hidden resource IDs, hidden counts, hidden pack coverage, hidden graph inputs, or hidden freshness warnings.

## 6. Shared response bounds

All tools must be bounded:

- `limit` max 500 rows unless specified lower.
- text fields are snippet-bounded unless tool is explicitly `read_section`.
- `read_section` max 20k chars / 500 lines per call, whichever comes first.
- list tools support `cursor` offset cursors and `next_cursor`.
- tool result includes `truncated` when rows/content are omitted.
- no tool returns full source corpus, generated ZIPs, package archives, or raw manifests without bounds.

## 7. Shared freshness model

Use a multi-resource freshness object, not a singular resource-only shape:

```json
{
  "status": "current|stale|draft|superseded|invalidated|archived|partial|unknown",
  "warnings": ["..."],
  "generated_at": "...",
  "pack": {"pack_key": "...", "version": 3, "status": "published"},
  "artifact": {"id": "uuid", "status": "approved", "artifact_hash": "sha256:..."},
  "graph": {"graph_key": "...", "kind": "resource|merge", "version": 1, "status": "published"},
  "resources": [
    {
      "resource_id": "uuid",
      "name": "human name",
      "artifact_snapshot_id": "uuid?",
      "current_snapshot_id": "uuid?",
      "status": "current|stale|deleted|archived|unknown",
      "warning": "..."
    }
  ],
  "coverage_complete": true
}
```

For unauthorized covered resources, do not return partial freshness. Return 404/empty for the whole pack/merge graph instead.

## 8. Shared canonical citation locator

Every tool that returns cited evidence (`get_resource_map`, `search`, `get_context_pack` artifact/citation details, graph provenance where line evidence exists) must return a canonical locator object consumable by `read_section`:

```json
{
  "resource_id": "uuid",
  "source_snapshot_id": "uuid",
  "snapshot_section_id": "uuid?",
  "context_artifact_id": "uuid?",
  "context_artifact_citation_id": "uuid?",
  "path": "docs/foo.md",
  "title": "Heading",
  "start_line": 10,
  "end_line": 32,
  "content_hash": "sha256:..."
}
```

Rules:

- `search` and resource-map citations must prefer `snapshot_section_id` when available.
- If evidence came from `context_artifact_citations`, include `context_artifact_citation_id`.
- Path/title fallback is display-only unless paired with `source_snapshot_id` and either `snapshot_section_id`, `context_artifact_citation_id`, or an exact `(path, start_line, end_line, content_hash)` match.
- `read_section` must reject ambiguous artifact/path-only requests instead of guessing.

## 9. Tool contracts

### 9.1 `sourcebrief.get_context_pack`

Purpose: fetch published context pack metadata, bounded artifact/source coverage, runtime guidance, and discovery inventory.

Input:

```json
{
  "pack_key": "optional human key; default current project pack",
  "version": 1,
  "include_artifacts": true,
  "include_coverage": true,
  "include_graph_inventory": true,
  "limit": 100,
  "cursor": "0"
}
```

Output:

```json
{
  "pack": {"id": "uuid", "pack_key": "...", "version": 1, "status": "published"},
  "freshness": {"status": "current", "resources": []},
  "sources": [{"resource_id": "uuid", "name": "Repo A", "type": "git", "current_snapshot_id": "uuid"}],
  "artifacts": [{"id": "uuid", "artifact_type": "resource_map", "resource_id": "uuid", "status": "approved", "citation_locators": [{"resource_id": "uuid", "source_snapshot_id": "uuid", "context_artifact_citation_id": "uuid", "path": "docs/foo.md", "start_line": 1, "end_line": 20, "content_hash": "sha256:..."}]}],
  "coverage": [{"resource_id": "uuid", "snapshot_id": "uuid", "artifact_count": 1}],
  "graph_inventory": {"resource_graphs": [], "merge_graphs": []},
  "runtime_guidance": "Use search/read_section...",
  "next_cursor": null,
  "truncated": false
}
```

Rules:

- Default to latest published version for `pack_key`, or project default if key omitted.
- If no published pack exists, return structured not-found with guidance to call `list_sources`/`search`.
- If any covered resource is unauthorized, return 404/empty.
- Respect `limit/cursor` for artifact and coverage arrays.

### 9.2 `sourcebrief.list_sources`

Purpose: product-safe discovery of authorized source resources and available artifact/graph summaries.

Input:

```json
{"query": "optional name/path filter", "resource_type": "git|bundle|document", "limit": 100, "cursor": "0"}
```

Output:

```json
{
  "sources": [
    {
      "resource_id": "uuid",
      "name": "Human name",
      "type": "git",
      "status": "active",
      "current_snapshot_id": "uuid",
      "resource_maps": [{"artifact_id": "uuid", "status": "approved"}],
      "graphs": [{"graph_key": "repo-graph", "current_version": 1}]
    }
  ],
  "next_cursor": null
}
```

Rules:

- Only returns resources allowed by the token.
- Requires `resource:read`.
- Does not include hidden project-wide counts.

### 9.3 `sourcebrief.get_resource_map`

Purpose: fetch the latest approved/published resource map artifact for one resource, using human or id discovery.

Input:

```json
{
  "resource_id": "uuid?",
  "resource_ref": "human name or exact resource id?",
  "artifact_id": "uuid?",
  "source_snapshot_id": "uuid?",
  "include_sources": true,
  "include_citations": true,
  "limit": 200,
  "cursor": "0"
}
```

Output:

```json
{
  "artifact": {"id": "uuid", "artifact_type": "resource_map", "status": "approved", "artifact_hash": "sha256:..."},
  "freshness": {"status": "current", "resources": []},
  "entries": [{"title": "Runbook", "path": "docs/runbook.md", "summary": "bounded text", "locator": {"resource_id": "uuid", "source_snapshot_id": "uuid", "context_artifact_citation_id": "uuid", "path": "docs/runbook.md", "start_line": 1, "end_line": 20, "content_hash": "sha256:..."}}],
  "sources": [{"path": "docs/runbook.md", "locator": {"resource_id": "uuid", "source_snapshot_id": "uuid", "snapshot_section_id": "uuid"}}],
  "citations": [{"locator": {"resource_id": "uuid", "source_snapshot_id": "uuid", "context_artifact_citation_id": "uuid", "content_hash": "sha256:..."}, "snippet": "..."}],
  "next_cursor": null,
  "truncated": false
}
```

Rules:

- `resource_id`, `resource_ref`, or `artifact_id` is required.
- `resource_ref` resolves only among authorized resources; ambiguous match returns bounded candidates without hidden resources.
- Default to latest approved `artifact_type=resource_map` for current resource snapshot.
- If `source_snapshot_id` is specified, return the approved map for that snapshot and mark stale/current in freshness.
- Bound artifact payload. If too large, return inventory/truncated guidance to `search`/`read_section`.

### 9.4 `sourcebrief.search`

Purpose: search indexed sections/artifacts with citations, not just code files.

Input:

```json
{
  "query": "string",
  "resource_ids": ["uuid"],
  "context_pack_key": "optional human key",
  "context_pack_version": 1,
  "profile": "lexical|hybrid|hybrid_rerank|vector|graph",
  "top_k": 8,
  "include_code_symbols": false
}
```

Output hit locators must include enough information for pinned `read_section`:

```json
{
  "hits": [
    {
      "resource_id": "uuid",
      "source_snapshot_id": "uuid",
      "snapshot_section_id": "uuid?",
      "context_artifact_id": "uuid?",
      "context_artifact_citation_id": "uuid?",
      "context_pack_key": "pack?",
      "context_pack_version": 1,
      "path": "docs/foo.md",
      "title": "...",
      "start_line": 10,
      "end_line": 32,
      "content_hash": "sha256:...",
      "snippet": "...",
      "score": 0.77,
      "freshness": { ... }
    }
  ],
  "freshness": {"warnings": []}
}
```

Rules:

- If `context_pack_key/version` is provided, restrict hits to covered resources/snapshots/artifacts in that pack.
- If token cannot read full requested pack coverage, return 404/empty.
- Do not return full source corpus.

### 9.5 `sourcebrief.read_section`

Purpose: read exact cited section evidence by pinned locator.

Input:

```json
{
  "resource_id": "uuid",
  "source_snapshot_id": "uuid?",
  "snapshot_section_id": "uuid?",
  "context_artifact_id": "uuid?",
  "context_artifact_citation_id": "uuid?",
  "context_pack_key": "optional",
  "context_pack_version": 1,
  "path": "optional repo/folder path",
  "heading": "optional heading/title",
  "content_hash": "sha256:...?",
  "start_line": 1,
  "end_line": 80,
  "allow_current_fallback": false
}
```

Output:

```json
{
  "locator": {"resource_id": "uuid", "source_snapshot_id": "uuid", "snapshot_section_id": "uuid", "path": "docs/foo.md", "start_line": 1, "end_line": 80, "content_hash": "sha256:..."},
  "resource": {"resource_id": "uuid", "name": "Repo A", "type": "git"},
  "section": {"title": "Heading", "path": "docs/foo.md", "start_line": 1, "end_line": 40, "total_lines": 120},
  "content": "bounded retained section text",
  "freshness": {"status": "current", "resources": []},
  "truncated": false
}
```

Tool-error shapes:

```json
{"code": "ambiguous_section", "candidates": [{"locator": {}, "title": "...", "path": "..."}]}
{"code": "section_not_found", "message": "section not found"}
{"code": "section_content_unavailable", "message": "retained section content is unavailable"}
```

Rules:

- Exact locator precedence:
  1. `snapshot_section_id` + `source_snapshot_id`
  2. `context_artifact_citation_id`
  3. context-pack scoped exact `(resource_id, source_snapshot_id, path, start_line, end_line, content_hash)`
  4. current snapshot `(resource_id, path, heading)` only when `allow_current_fallback=true`
- A bare `context_artifact_id` or `(path, heading)` is ambiguous and must be rejected unless it resolves to exactly one retained citation/section under the supplied pinned snapshot.
- Default is pinned/evidence-safe. It must not silently read current content after a pack/search citation pointed to an old snapshot.
- If reading a stale/deleted pinned section, return content if retained and include freshness warning; if scrubbed/unavailable, return structured not-found with no hidden leak.
- Reject binary/oversized content and path traversal.

### 9.6 `sourcebrief.get_graph_inventory`

Purpose: discover authorized published resource graphs and merge graphs by human labels/keys.

Input:

```json
{"query": "optional", "kind": "resource|merge|all", "limit": 100, "cursor": "0"}
```

Output:

```json
{
  "resource_graphs": [{"graph_key": "...", "title": "...", "resource_id": "uuid", "current_version": 1}],
  "merge_graphs": [{"merge_key": "...", "title": "...", "current_version": 1, "input_sources": ["Repo A", "Repo B"]}],
  "next_cursor": null
}
```

Rules:

- Merge graph rows are returned only if all input resources are authorized.
- Does not expose hidden merge count.

### 9.7 `sourcebrief.graph_query`

Purpose: inspect published resource graph or published graph merge by human key.

Input:

```json
{"graph_key": "resource-or-merge-key", "graph_kind": "resource|merge|auto", "version": 1, "query": "node label/path/type filter", "node_type": "optional", "limit": 50, "cursor": "0"}
```

Output:

```json
{
  "graph": {"key": "...", "kind": "merge", "version": 1, "status": "published", "title": "..."},
  "freshness": {"status": "current", "resources": []},
  "nodes": [{"key": "...", "label": "...", "node_type": "file", "path": "src/app.py", "origin": {"resource_id": "uuid", "source_snapshot_id": "uuid", "path": "src/app.py"}}],
  "edges": [{"source": "...", "target": "...", "edge_type": "imports", "origin": {"resource_id": "uuid", "source_snapshot_id": "uuid", "path": "src/app.py"}}],
  "next_cursor": null,
  "truncated": false
}
```

Rules:

- Default to current published graph/merge version only.
- Draft versions are not exposed via runtime MCP.
- Enforce all covered input resources for merge graphs.
- Return bounded nodes and adjacent edges with provenance/freshness.

### 9.8 `sourcebrief.graph_path`

Purpose: runtime path query over published graph/merge by node labels or keys.

Input:

```json
{"graph_key": "...", "graph_kind": "resource|merge|auto", "version": 1, "from_node_key": "optional", "to_node_key": "optional", "from_label": "optional", "to_label": "optional", "max_depth": 4}
```

Output:

```json
{
  "graph": {"key": "...", "kind": "merge", "version": 1, "status": "published"},
  "freshness": {"status": "current", "resources": []},
  "found": true,
  "nodes": [{"key": "...", "label": "...", "path": "src/app.py", "origin": {"resource_id": "uuid", "source_snapshot_id": "uuid", "path": "src/app.py"}}],
  "edges": [{"source": "...", "target": "...", "edge_type": "imports", "origin": {"resource_id": "uuid", "source_snapshot_id": "uuid"}}],
  "truncated": false
}
```

Rules:

- If label is ambiguous, return structured `ambiguous_node` with up to 10 authorized candidate labels/paths.
- `max_depth` hard cap 8.
- Reuse E1 path implementation for merge graphs.
- Resource graph path may be shallow adjacency/path if available; if not, return structured unsupported for resource graphs rather than guessing.

## 10. API implementation plan

1. Add Pydantic request/response models for F tools in `schemas.py`.
2. Add read-only helper functions in `runtime_tools.py`.
3. Register schemas in `_mcp_tools()`.
4. Wire `tools/call` branches to helpers.
5. Reuse existing retrieval/remote-code helpers only where auth and error semantics are safe.
6. Test through JSON-RPC `/mcp/{workspace_id}/{project_id}` only.

## 11. Generated skill/docs impact

Update generated Hermes/Codex/Claude guidance:

- Start with `get_context_pack` or `list_sources`.
- Use `get_resource_map`, `search`, and `read_section` for source evidence.
- Use graph tools for architecture/impact.
- Use code tools only for exact file/symbol evidence.
- Treat freshness warnings as first-class; do not hide stale context.

## 12. Acceptance tests

Real-service tests must cover:

1. `tools/list` includes all F tools and schemas.
2. Runtime-style flow: `get_context_pack` or `list_sources` -> `get_resource_map` -> `search` -> `read_section` -> graph inventory/path.
3. Resource-scoped token cannot read a pack or merge graph covering disallowed resources.
4. Pinned `read_section` reads the snapshot from the citation, not current content after source changes.
5. Multi-resource freshness includes per-resource entries and stale warnings.
6. Tool payloads are bounded with `next_cursor`/`truncated` where relevant.
7. Existing MCP tools still work.

## 13. Review checklist

- Backend/platform: auth scopes, hidden-resource leak prevention, bounded responses, freshness semantics, no mutation.
- Product/runtime: tool workflow is discoverable; generated instructions avoid local repo assumptions and UUID-first entry.
- QA: real Postgres integration through JSON-RPC MCP endpoint; frontend/build green.
