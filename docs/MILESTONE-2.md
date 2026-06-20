# Milestone 2: Resource Ingestion, Snapshots, and Lexical Search

Status: Implemented v0.1
Parent spec: [`docs/SPEC.md`](./SPEC.md) · Builds on [`docs/MILESTONE-1.md`](./MILESTONE-1.md)

## 1. Intent

Milestone 1 proved the runtime skeleton (API → Postgres `index_runs` → RQ worker →
status transition) with a placeholder job. Milestone 2 makes the worker do **real
ingestion**: a refresh now fetches/reads a resource, writes a versioned
`source_snapshot`, and produces lexical `chunks` that can be searched within an
authorized workspace/project scope, with citations back to the snapshot.

The bar is unchanged from M1: a feature is done only when it passes lint, unit
tests, real-service integration tests, full Docker Compose startup, and a
senior-QA-style smoke flow.

## 2. Scope

In scope for M2:

- **Git repo connector** — clone a public `https` or local `file://` repository
  into a controlled work directory, capture the commit SHA as the snapshot
  version, and index only text-ish, size-bounded files. Generated/dependency
  directories (`.git`, `node_modules`, `.venv`, `dist`, `build`, caches, …),
  binaries, lockfiles, and oversized files are skipped. Repo code is never
  executed.
- **File/document connector** — document resources accept inline content via
  `source_config` (`content`, or a `documents: [{path,title,content}]` list).
  The platform does **not** read arbitrary host files through the API.
- **Source snapshots** — each refresh creates a new `source_snapshots` row with a
  `version` (commit SHA for git, content hash for documents), `version_kind`,
  status, fetched/indexed timestamps, and connector metadata.
- **Chunks** — a new `chunks` table holds `workspace_id`, `project_id`,
  `resource_id`, `source_snapshot_id`, `path`, `title`, `content`, `ordinal`,
  `content_hash`, and `metadata`.
- **Basic lexical search** — Postgres full-text search (`to_tsvector` /
  `plainto_tsquery` / `ts_rank`) over chunks, backed by a GIN index, restricted
  to each resource's **current** snapshot.
- **Manual refresh** — the existing refresh endpoint now drives real ingestion.
- **Index run UI/logs** — per-resource snapshot and index-run listings, plus a
  frontend surface for ingestion docs and live search.

## 3. Data Model Changes

Migration `0002_m2_ingestion`:

- `source_snapshots.version_kind` (`commit_sha` | `content_hash`) added.
- `chunks` table created with tenancy columns, citation columns
  (`path`, `title`, `ordinal`, `content_hash`), `metadata`, and soft-delete.
- Indexes: `workspace_id`, `(workspace_id, project_id)`, `source_snapshot_id`,
  `resource_id`, and a GIN `to_tsvector('english', content)` index for search.

The **full-rebuild** strategy (SPEC §13.2 option 1) is used: each refresh writes a
new snapshot and new chunk rows; search filters to `resources.current_snapshot_id`,
so superseded snapshots are simply not searched. `chunks_reused` stays `0`.

## 4. API Surface

Existing endpoints are preserved. New/changed in M2:

```http
PATCH /workspaces/{ws}/projects/{proj}/resources/{res}          # update config/source_config
GET   /workspaces/{ws}/projects/{proj}/resources                # list resources
GET   /workspaces/{ws}/projects/{proj}/resources/{res}/snapshots
GET   /workspaces/{ws}/projects/{proj}/resources/{res}/index-runs
POST  /workspaces/{ws}/projects/{proj}/search                   # lexical search
POST  /workspaces/{ws}/projects/{proj}/resources/{res}/refresh  # now real ingestion
```

Search request / response:

```json
// POST .../search
{ "query": "resource deletion", "resource_ids": [], "top_k": 10 }

// 200
{
  "query": "resource deletion",
  "count": 1,
  "hits": [
    {
      "resource_id": "…", "snapshot_id": "…",
      "path": "README.md", "title": "README.md", "ordinal": 0,
      "content_hash": "…", "version": "<commit-or-hash>",
      "version_kind": "commit_sha", "commit": "<commit>",
      "snippet": "…", "score": 0.0607
    }
  ]
}
```

Every read/search resolves the dev identity (`X-User-Email`), enforces workspace
membership, and confirms the project/resource belongs to the workspace.
Unauthorized access returns `404` (non-leaking), consistent with M1 and SPEC §19.2.

## 5. Security / Operational Notes

- **No shell injection** — git runs via `subprocess` list args (never a shell),
  with `--` before the URL to prevent option injection.
- **Bounded & sandboxed git** — `--depth 1 --single-branch --no-tags
  --no-recurse-submodules`, hooks disabled (`core.hooksPath=/dev/null`), system &
  global config ignored, credential prompts disabled (`GIT_TERMINAL_PROMPT=0`),
  and `GIT_ALLOW_PROTOCOL=https:file` plus `protocol.ext.allow=never`. `https`
  remotes are accepted only when their host resolves to public IPs (local,
  private, link-local, multicast, reserved, and `.local` names are rejected
  before git runs). Workers should still run with deployment-level egress policy;
  this is a preflight guard, not a complete network sandbox.
- **Local sources gated** — local `file://`/path sources are disabled unless the
  worker has `SOURCEBRIEF_ALLOW_LOCAL_GIT=true` (used only by local
  development/QA Compose), so an untrusted SaaS user cannot point ingestion at
  arbitrary worker filesystem paths.
- **Secret-safe snapshot metadata** — git snapshot metadata stores a sanitized
  remote URL with userinfo/query/fragment stripped, plus commit SHA; inline
  document metadata stores counts/budgets, not raw content.
- **Resource budgets** — per-inline-document bytes, per-file bytes,
  total-file-count, total-repo-byte, and total-chunk caps prevent large resources
  from exhausting worker memory/DB/disk. Git also skips LFS smudge and requests a
  blob-size filter where the remote supports partial clone.
- **No path traversal** — every repo file is resolved and confirmed to live
  inside the clone root; escaping symlinks are skipped.
- **No arbitrary host reads via API** — document content is inline only.
- **Tenant boundary** — all chunk/snapshot queries filter by
  `workspace_id`/`project_id`; search additionally restricts to current,
  retrieval-enabled, non-deleted resources.
- **Size/binary guards** — files over the byte cap (default 1 MB) or detected as
  binary are skipped before storage.

## 6. Acceptance Criteria

From the spec (M2):

1. Add a repo and a markdown file. ✅ (git + document connectors)
2. See snapshot version/commit/hash. ✅ (`GET …/snapshots`, `version` +
   `version_kind` + `metadata.commit`)
3. Query text search within allowed scope. ✅ (`POST …/search`, membership
   enforced, current-snapshot filtered, citations returned)

## 7. QA Commands

```bash
make lint              # ruff + tsc --noEmit
make test              # unit tests (chunking, filtering, safe git url, repo walk)
make compose-up        # start postgres/pgvector, redis, api, workers, frontend
make migrate           # apply 0001 + 0002 migrations
make test-integration  # real Postgres/Redis: document + git ingestion + search
make qa-smoke          # end-to-end smoke through the composed stack
make verify            # the canonical gate: all of the above in order
```

`make verify` remains the single canonical gate.

## 8. Non-Goals (deferred)

- Embeddings / pgvector similarity / hybrid retrieval (Milestone 3).
- Context packet builder, `query_runs` / `retrieval_hits` analytics (Milestone 3).
- Code symbol extraction and code query mode (Milestone 4).
- URL/web connector and its SSRF hardening (uses the same snapshot/chunk path
  later; not in M2).
- Graph extraction, review items, MCP server.
- Incremental/content-hash chunk reuse and snapshot garbage collection.
- Concurrency coalescing of overlapping refreshes (one run per resource).

## 9. Follow-ups

- Garbage-collect or soft-delete superseded-snapshot chunks after a successful
  rebuild (currently retained; search already ignores them).
- Add the URL/web connector with SSRF protection (private-network/metadata
  blocking, redirect capture, response caps).
- Coalesce concurrent refreshes per resource (return the active run id).
- `ts_headline`-based highlighted snippets and language-config selection.
