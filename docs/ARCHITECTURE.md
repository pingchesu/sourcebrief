# Architecture

SourceBrief is a multi-tenant context platform. It turns project resources into versioned, cited, agent-ready context.

## Design goals

- Keep the infrastructure boring: PostgreSQL, pgvector, Redis, RQ, FastAPI, Next.js.
- Make tenant and project boundaries part of the data model from day one.
- Treat indexed context as versioned artifacts, not mutable prompt text.
- Return citations for every retrieved answer path.
- Keep production actions outside repo agents. SourceBrief provides context; typed external tools handle mutations.
- Support multiple agent runtimes through HTTP and one central MCP endpoint.

## Runtime components

```text
                  ┌────────────────────┐
                  │      Web UI        │
                  │  review + search   │
                  └─────────┬──────────┘
                            │
┌──────────────┐    ┌────────▼─────────┐      ┌────────────────┐
│ Agent client │───▶│ FastAPI service  │─────▶│ PostgreSQL      │
│ HTTP/MCP/CLI │    │ API + MCP routes │      │ + pgvector      │
└──────────────┘    └────────┬─────────┘      └────────────────┘
                             │
                             ▼
                       ┌──────────┐
                       │ Redis/RQ │
                       └────┬─────┘
                            ▼
                    ┌───────────────┐
                    │ Index workers │
                    │ docs + git    │
                    └───────────────┘
```

## Data model overview

Core entities:

- `users`
- `workspaces`
- `workspace_memberships`
- `projects`
- `project_memberships`
- `resources`
- `source_snapshots`
- `chunks`
- `chunk_embeddings`
- `code_symbols`
- `agent_profiles`
- `graph_nodes`
- `graph_edges`
- `index_runs`
- `query_runs`
- `retrieval_hits`
- `audit_events`

The important boundary is:

```text
workspace → project → agent_profile
workspace → project → resource → snapshot → chunk / symbol / embedding / graph
```

Queries always resolve through workspace and project scope. Resources from another workspace/project should not appear in search, context packets, MCP calls, or usage reports.

## Resource lifecycle

A resource can be:

- created
- refreshed
- reviewed
- archived
- soft-deleted
- hard-deleted

Each refresh creates index-run state and source snapshots. Current retrieval uses current snapshots only, so old snapshots remain auditable without polluting active answers. For Git resources, the current snapshot and current published resource-graph version are one atomic consistency boundary: they advance together, and graph compile/validation/publish failure leaves the previous complete pair current.

Scheduled Git refreshes reuse an existing snapshot only when both the fetched commit and effective extraction-policy fingerprint are unchanged. Manual refreshes continue to reindex the selected commit so source-config changes can take effect.

## Indexing path

```text
resource refresh request
        ↓
index_runs row created
        ↓
Redis/RQ job queued
        ↓
worker fetches source
        ↓
source snapshot, chunks, embeddings, symbols, and graph rows staged
        ↓
for Git: resource graph version compiled + validated + published
        ↓
for Git: dependent current merge versions invalidated when their input graph advanced
        ↓
for Git: resource.current_snapshot_id and graph.current_version_id advance atomically
        ↓
index_run marked succeeded; any failure rolls back the staged snapshot/graph pair
```

Document resources currently support inline markdown content. Git resources support commit-aware indexing and code symbol extraction.

## Retrieval path

SourceBrief combines multiple retrieval signals:

- lexical search over chunks
- vector search through pgvector
- bounded graph signal over current resource/file/symbol graph nodes
- deterministic rerank signal by default, with HTTP provider adapters for external rerankers
- deterministic code symbol search
- resource filters
- citation and usage logging

The API can return raw search results, context packets, or runtime-shaped agent context.

## Agent context path

Agent clients call:

```text
POST /workspaces/{workspace_id}/projects/{project_id}/agent-context
```

The response includes:

- runtime-specific instruction plus optional project agent profile system prompt
- cited context text
- structured citations
- optional code symbols
- token budget hint

Supported runtime profiles:

- `api`
- `hermes`
- `claude`
- `codex`
- `cursor`

## MCP path

SourceBrief exposes one central MCP-style endpoint:

```text
POST /mcp/{workspace_id}/{project_id}
```

Implemented methods:

- `initialize`
- `tools/list`
- `tools/call`

Core tool groups:

- agent context retrieval: `sourcebrief.get_agent_context`
- Context Pack and Resource Map inspection
- cited section reads and source search
- graph inventory/query/path traversal
- indexed code search, grep, read-file, and symbol lookup
- patch proposal / PR approval records where explicitly enabled

This is intentionally not one MCP server per repo. A project is the boundary; a project can contain many repos and resources. SourceBrief exposes context/source intelligence plus guarded patch proposal and PR approval-record workflows through MCP; production mutations remain outside SourceBrief.

## Agent registry

Each project has one platform-owned `agent_profile`. The profile stores the project agent's name, description, default runtime, optional system prompt, and tool policy. The source repo is not required to accept `AGENTS.md` or other agent files.

Useful endpoints:

- `GET /workspaces/{workspace_id}/agents`
- `GET /workspaces/{workspace_id}/projects/{project_id}/agent-profile`
- `PATCH /workspaces/{workspace_id}/projects/{project_id}/agent-profile`

The profile is intentionally metadata and policy only. Production actions still require external typed tools and approvals.

## Review and drift control

SourceBrief tracks:

- resource usage count
- retrieval hit count
- last used time
- review status
- last reviewed time
- stale-after days
- archived/deleted state
- latest index run status

This lets users clean up unused or stale context instead of blindly growing the knowledge base.

## Local development stack

| Component | Role |
| --- | --- |
| FastAPI | API and MCP routes |
| PostgreSQL | relational state, audit, snapshots, chunks |
| pgvector | embedding storage and vector search |
| Redis | queue broker |
| RQ | background indexing workers |
| Next.js | web shell and review/search UI surface |
| Docker Compose | local real-service runtime |

## Security posture in the MVP

Current local CLI/test flows may use `X-User-Email` only when `SOURCEBRIEF_DEV_AUTH=true`. The alpha also includes email/password web login, session tokens, workspace memberships, and scoped workspace API tokens. It is still not public-internet hardened: production deployment needs SSO/SCIM or another real identity provider, CSRF/CORS review, deployment-specific secret handling, and operational hardening.

Non-negotiable design rule:

> SourceBrief can provide context to agents. It should not let repo agents own production mutation boundaries.

Production actions should stay behind dedicated typed MCP tools, explicit approval, and evidence/rollback workflows.

## Known hardening work

- production identity-provider integration beyond alpha email/password sessions and API tokens
- scheduled refresh orchestration
- production embedding/rerank provider adapters
- richer review UI
- resource connector hardening
- public deployment docs
- observability dashboards and metrics
- hosted SaaS tenancy hardening
