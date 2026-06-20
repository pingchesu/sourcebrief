# SourceBrief Product and Architecture Specification

Status: Draft v0.2
Repository: `pingchesu/sourcebrief`
Primary goal: build an open-source, multi-tenant service platform that turns repositories, documents, runbooks, URLs, and arbitrary resources into versioned, reviewable, queryable knowledge agents usable by multiple agent runtimes.

## 1. Executive Summary

SourceBrief is an open-source agent context platform.

It lets users create a Project, attach resources such as Git repositories, documents, runbooks, URLs, incident exports, and knowledge files, configure refresh schedules, and automatically produce indexed artifacts that can be used by agents through HTTP APIs, a web UI, a central MCP server, and runtime adapters such as Hermes, Claude Code, Codex, Cursor, or future SDKs.

The product is not just a RAG application, vector database, code search tool, or memory plugin. Its differentiator is the full lifecycle of **trusted context**:

- resource ingestion and versioned snapshots
- repository-derived code intelligence
- document and runbook retrieval
- graph and relationship extraction
- query-time hybrid retrieval and reranking
- context packet generation
- review and curation workflows
- freshness, drift, usage, and citation analytics
- multi-tenant access control from day one
- agent-ready APIs and integration surfaces

Tagline:

> Forge trusted context for every agent.

MVP scoping note: V0 is retrieval-first. It must reliably create versioned, permission-scoped context packets with citations before built-in answer generation or autonomous workflows.

## 2. Product Definition

SourceBrief is a multi-tenant Project-based platform where every Project can become a knowledge agent.

A Project may include:

- Git repositories
- Markdown files
- PDFs and uploaded documents
- URLs and web pages
- runbooks
- API docs
- incident/postmortem exports
- product/business docs
- future connectors such as Notion, Linear, GitHub Issues, Slack exports, Grafana dashboards, or service catalogs

Once resources are added and indexed, the Project exposes:

- web chat
- HTTP query API
- central MCP tools
- context packet export
- review UI
- usage and drift dashboard
- optional runtime adapters for Hermes, Claude Code, Codex, Cursor, or other agents

## 3. Goals

### 3.1 Functional Goals

1. Users can create workspaces, projects, and resources.
2. Users can add Git repositories and arbitrary documents/resources to a project.
3. Users can configure update frequency per resource.
4. Users can refresh/reindex resources on demand.
5. The platform can update, archive, soft-delete, hard-delete, and restore resources.
6. The platform stores versioned snapshots for every indexed resource.
7. Git repository answers are traceable to repo, branch, commit SHA, file path, and line range.
8. Document answers are traceable to source URI, document hash/version, chunk, and snapshot.
9. Projects become agent endpoints usable by API, MCP, web UI, and external agent runtimes.
10. Users can query within a resource, a project, or across projects/resources when authorized.
11. Users can inspect which resources were retrieved, included in context, and cited.
12. Reviewers can review generated summaries, inferred graph edges, stale resources, failed indexing, and low-confidence knowledge.
13. Usage analytics can show which resources, documents, chunks, and context items were hit, selected, cited, or marked useful/wrong/stale.
14. The platform can support repo-as-agent and arbitrary-resource-as-agent without modifying the source repository owner files such as `AGENTS.md`.
15. The platform can support production discipline by separating static repo/runbook knowledge from live external operations.

### 3.2 Non-Functional Goals

1. Open-source SaaS-scale architecture.
2. Minimal common external dependencies for MVP:
   - PostgreSQL
   - pgvector
   - Redis
   - local filesystem or S3-compatible object storage later
   - Hugging Face / vLLM / SGLang / OpenAI-compatible embedding and rerank endpoints
3. Multi-tenant by data model from day one.
4. Permission pre-filtering before lexical search, vector search, graph expansion, reranking, context packing, and answer generation.
5. No per-repo MCP server explosion. Use one central platform MCP server.
6. Support local-first/self-hosted deployments.
7. Maintain clear provenance and freshness on all derived artifacts.
8. Preserve future extensibility for optional storage backends such as Qdrant, Milvus, Neo4j, FalkorDB, or Hindsight without requiring them in MVP.

## 4. Non-Goals

MVP does not need to provide:

1. Enterprise SAML/SCIM/advanced compliance.
2. Per-field or per-chunk custom policy language.
3. Fully automated production mutation workflows.
4. Per-repository MCP servers.
5. A universal ontology for all code, business, and operations domains.
6. Neo4j-first graph architecture.
7. Mandatory Kubernetes deployment.
8. Billing and marketplace features.
9. Perfect security hardening before the functional platform exists.
10. Autonomous merging, deployment, or production mutation without external approval workflows.

However, the schema and API must not block later enterprise security, audit, tenant isolation, storage adapters, or advanced permissions.

## 5. Primary User Personas

### 5.1 Platform Admin

Creates workspaces, configures model providers, manages users, roles, API tokens, and deployment settings.

### 5.2 Project Maintainer

Creates projects, adds repos/docs/runbooks, sets refresh schedules, reviews generated knowledge, handles stale resources, and tunes retrieval policies.

### 5.3 Developer / Agent User

Queries a project agent for code understanding, bug localization, PR review, architecture questions, and cross-repo context.

### 5.4 SRE / Operator

Queries runbooks, incident history, service docs, and repository context. Uses SourceBrief for static knowledge, while live production reads/mutations go through separate approved typed tools.

### 5.5 Business / Product User

Queries product flows, business process docs, ownership, operational impact, and cross-resource knowledge summaries.

### 5.6 External Agent Runtime

Hermes, Claude Code, Codex, Cursor, or a custom application calls SourceBrief through HTTP API, MCP tools, or context packet export.

## 6. Core Concepts

### 6.1 Workspace

Top-level tenant boundary. Contains users, projects, service tokens, settings, and audit records.

### 6.2 Project

A curated knowledge/agent scope. A project contains resources and becomes a queryable agent.

### 6.3 Resource

A source of truth or source material attached to a project. Resource types include Git repo, uploaded file, URL, markdown collection, runbook, API docs, incident export, or future connectors.

### 6.4 Source Snapshot

A versioned view of a resource at a point in time. For Git repos this is branch + commit SHA. For documents/URLs this is content hash + fetched timestamp.

### 6.5 Artifact

Derived output from a snapshot, such as chunks, embeddings, code symbols, graph nodes/edges, summaries, context packets, and reports.

### 6.6 Agent Profile

Project-level configuration that defines how the project should be queried, what retrieval policies apply, how answers cite sources, and which integrations are exposed.

### 6.7 Context Packet

A reproducible bundle of selected evidence for an agent request. It includes exact source snippets, graph paths, citations, token counts, included/omitted reasons, freshness, and policy metadata.

### 6.8 Review Item

A user-reviewable item such as an inferred edge, generated summary, stale resource warning, failed index run, suspicious low-value resource, or high-impact unreviewed knowledge item.

### 6.9 Agent Memory

Learned usage information, preferences, routing hints, accepted insights, and feedback-derived knowledge. This is not source truth and must not replace repo/document citations.

## 7. High-Level Architecture

```text
Frontend / Review UI
        |
        v
API Server / Auth / Project Service
        |
        +-- Source Connectors
        |     +-- Git repository connector
        |     +-- file upload connector
        |     +-- URL/web connector
        |     +-- markdown/runbook connector
        |     +-- future external connectors
        |
        +-- Scheduler / Job Queue
        |     +-- Redis-backed jobs
        |     +-- periodic refresh
        |     +-- webhook/on-demand refresh
        |
        +-- Ingestion Workers
        |     +-- fetch resources
        |     +-- create snapshots
        |     +-- chunk documents
        |     +-- parse code symbols
        |     +-- generate embeddings
        |     +-- extract graph relationships
        |     +-- build context artifacts
        |
        +-- Retrieval Service
        |     +-- permission pre-filter
        |     +-- lexical search
        |     +-- vector search via pgvector
        |     +-- code symbol search
        |     +-- graph traversal over PostgreSQL adjacency tables
        |     +-- reranking
        |     +-- context packet builder
        |
        +-- Agent Gateway
        |     +-- HTTP query API
        |     +-- central MCP server
        |     +-- web chat
        |     +-- runtime adapters
        |
        +-- Review / Curation Service
        |     +-- generated summary review
        |     +-- inferred edge review
        |     +-- stale/unused resource review
        |     +-- failed ingestion review
        |
        +-- Usage / Evaluation Service
              +-- query traces
              +-- retrieval hits
              +-- context inclusion
              +-- answer citations
              +-- feedback
              +-- eval/golden questions
```

## 8. Recommended Initial Technology Stack

### 8.1 Required Services

| Component | Recommendation |
|---|---|
| Metadata database | PostgreSQL |
| Vector store | pgvector inside PostgreSQL, partitioned by workspace for tenant-scoped filtered search |
| Graph store | PostgreSQL adjacency tables for MVP |
| Queue / scheduler / locks | Redis |
| Object/artifact storage | Local filesystem first, S3-compatible optional later |
| API backend | FastAPI recommended; Django/NestJS acceptable if team preference differs |
| Worker runtime | RQ with Redis as broker; PostgreSQL `index_runs` remains durable job truth |
| Frontend | Next.js/React |
| Embedding provider | OpenAI-compatible endpoint, Hugging Face TEI, vLLM, SGLang, or local sentence-transformers |
| Rerank provider | bge-reranker/Jina/cross-encoder via HTTP or local worker |

### 8.2 Optional Later Services

| Component | Use only if proven needed |
|---|---|
| Neo4j / FalkorDB | Durable graph traversal workloads outperform PostgreSQL |
| Qdrant / Milvus | pgvector becomes a bottleneck or advanced vector features needed |
| LangGraph | Query/investigation workflows become complex enough for durable orchestration |
| Hindsight | Optional agent memory backend, not source-of-truth index |
| LlamaIndex | Optional ingestion/prototyping framework; do not let it own canonical schema |

## 9. Multi-Tenant and Permission Model

### 9.1 Principle

Tenancy is not a late security add-on. It is part of the core data model.

All core data must be scoped by `workspace_id`, and most data must also include `project_id` and `resource_id` where applicable.

Permission filtering must happen before:

1. lexical retrieval
2. vector retrieval
3. graph expansion
4. reranking
5. context packet generation
6. answer generation
7. memory recall

### 9.2 Roles

MVP roles:

| Role | Capabilities |
|---|---|
| owner | workspace settings, members, deletion, tokens, project/resource admin |
| admin | project/resource/update/review management |
| editor | create/update resources, review knowledge, run reindex |
| viewer | query/read project resources |
| service_account | scoped API/MCP access |

### 9.3 Membership Scope

MVP should support:

- workspace membership
- project membership override
- service tokens scoped to workspace/project/resources

V0 may avoid fine-grained per-resource ACL if project-level permission is implemented correctly. Schema should allow per-resource visibility later.

### 9.4 Visibility

Project visibility options:

- `private`: only project members
- `workspace`: workspace members with viewer or above can query
- `restricted`: explicit members only
- `public`: later feature, not needed for MVP

Resource visibility options:

- `inherit`
- `project`
- `restricted`
- `disabled`

### 9.5 API Token Scope

API tokens should be stored by hash only.

Token scopes:

- `project:read`
- `project:query`
- `resource:read`
- `resource:write`
- `resource:refresh`
- `review:read`
- `review:write`
- `admin:workspace`

Every MCP/API call must resolve token/user identity before accessing data.

## 10. Resource Lifecycle

Resources must support lifecycle operations from the beginning.

### 10.1 States

```text
active
paused
archived
soft_deleted
hard_delete_pending
failed
stale
```

### 10.2 Operations

| Operation | Behavior |
|---|---|
| Add | Create resource and initial snapshot/index run |
| Update config | Change branch, URL, include/exclude rules, refresh frequency, model policy |
| Refresh now | Fetch latest source and run incremental indexing |
| Reindex | Rebuild derived artifacts from the current snapshot/source |
| Pause | Stop scheduled updates but keep query availability unless disabled |
| Archive | Remove from default query scopes but preserve history and restore path |
| Soft delete | Disable retrieval and context inclusion while preserving audit/history |
| Hard delete | Purge source snapshots and derived artifacts asynchronously |
| Restore | Restore archived/soft-deleted resource |

### 10.3 State Transitions

Allowed MVP transitions:

```text
active -> paused -> active
active -> archived -> active
active -> soft_deleted -> active
archived -> soft_deleted
soft_deleted -> hard_delete_pending -> purged
failed -> active after successful refresh/reindex
stale -> active after successful refresh/reindex
```

Concurrent indexing rules:

- only one running `index_run` per resource is allowed by default
- repeated refresh requests while a run is active should coalesce or return the active run id
- cancellation is optional for V0 but the schema should not prevent it later

### 10.4 Deletion Semantics

Soft delete is the default safe operation.

Hard delete must purge:

- source snapshots
- documents
- chunks
- embeddings
- code symbols
- graph nodes and edges
- generated summaries
- context packets
- review items

Historical usage analytics may be anonymized/aggregated if retention policy allows. Raw query text and citations referencing deleted resources must be removed or redacted according to policy.

## 11. Source Snapshot Model

Each resource update creates a new snapshot.

### 11.1 Git Repository Snapshot

Fields:

- remote URL
- branch/ref
- commit SHA
- tree hash if available
- fetched_at
- indexed_at
- dirty flag should always be false for managed clones
- include/exclude rules version

### 11.2 Document/URL Snapshot

Fields:

- source URI
- content hash
- fetched_at/uploaded_at
- indexed_at
- content type
- extraction parser version
- source metadata

### 11.3 Why Snapshots Matter

Snapshots allow the system to answer:

- Which commit/document hash was used for this answer?
- Why did yesterday and today's answer differ?
- Which resources are stale?
- Which context packets are reproducible?
- Which resource update changed retrieval behavior?

## 12. Data Model Draft

This section defines the initial relational shape. Names are illustrative; final schema may use migrations and ORM naming conventions.

### 12.1 Tenancy and Identity

```sql
workspaces (
  id uuid primary key,
  name text not null,
  slug text unique not null,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  deleted_at timestamptz
)

users (
  id uuid primary key,
  email text unique,
  display_name text,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  deleted_at timestamptz
)

workspace_memberships (
  id uuid primary key,
  workspace_id uuid not null,
  user_id uuid not null,
  role text not null,
  created_at timestamptz not null,
  unique(workspace_id, user_id)
)

api_tokens (
  id uuid primary key,
  workspace_id uuid not null,
  project_id uuid,
  name text not null,
  token_hash text not null unique,
  scopes text[] not null,
  allowed_project_ids uuid[],
  allowed_resource_ids uuid[],
  created_by uuid,
  expires_at timestamptz,
  last_used_at timestamptz,
  revoked_at timestamptz,
  created_at timestamptz not null
)

audit_events (
  id uuid primary key,
  workspace_id uuid not null,
  actor_user_id uuid,
  actor_token_id uuid,
  action text not null,
  target_type text not null,
  target_id uuid,
  target_ref jsonb not null default '{}',
  metadata jsonb not null default '{}',
  created_at timestamptz not null
)
```

### 12.2 Projects and Resources

```sql
projects (
  id uuid primary key,
  workspace_id uuid not null,
  name text not null,
  slug text not null,
  description text,
  visibility text not null default 'workspace',
  default_agent_profile_id uuid,
  created_by uuid,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  deleted_at timestamptz,
  unique(workspace_id, slug)
)

project_memberships (
  id uuid primary key,
  workspace_id uuid not null,
  project_id uuid not null,
  user_id uuid not null,
  role text not null,
  created_at timestamptz not null,
  unique(project_id, user_id)
)

resources (
  id uuid primary key,
  workspace_id uuid not null,
  project_id uuid not null,
  type text not null,
  name text not null,
  uri text,
  source_config jsonb not null default '{}',
  update_frequency text not null default 'manual',
  visibility text not null default 'inherit',
  status text not null default 'active',
  retrieval_enabled boolean not null default true,
  current_snapshot_id uuid,
  next_refresh_at timestamptz,
  last_refresh_started_at timestamptz,
  last_refresh_finished_at timestamptz,
  created_by uuid,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  deleted_at timestamptz
)
```

### 12.3 Snapshots and Documents

```sql
source_snapshots (
  id uuid primary key,
  workspace_id uuid not null,
  project_id uuid not null,
  resource_id uuid not null,
  version text not null,
  version_kind text not null, -- commit_sha | content_hash | external_version
  metadata jsonb not null default '{}',
  fetched_at timestamptz,
  indexed_at timestamptz,
  status text not null,
  diff_summary jsonb,
  created_at timestamptz not null
)

documents (
  id uuid primary key,
  workspace_id uuid not null,
  project_id uuid not null,
  resource_id uuid not null,
  snapshot_id uuid not null,
  path text,
  title text,
  content_type text,
  hash text,
  metadata jsonb not null default '{}',
  created_at timestamptz not null,
  deleted_at timestamptz
)

chunks (
  id uuid primary key,
  workspace_id uuid not null,
  project_id uuid not null,
  resource_id uuid not null,
  snapshot_id uuid not null,
  document_id uuid not null,
  content text not null,
  token_count int,
  start_offset int,
  end_offset int,
  line_start int,
  line_end int,
  metadata jsonb not null default '{}',
  created_at timestamptz not null,
  deleted_at timestamptz
)
```

### 12.4 Embeddings

Embedding storage is namespaced by model, dimension, distance metric, and chunking version. Do not use one hard-coded vector dimension for all deployments. Each namespace has its own compatible pgvector table/index or partition strategy. A model or dimension change creates a new namespace and requires re-embedding before activation. Never mix vector spaces.

```sql
embedding_namespaces (
  id uuid primary key,
  workspace_id uuid not null,
  project_id uuid,
  name text not null,
  provider text not null,
  model text not null,
  dimension int not null,
  distance_metric text not null default 'cosine',
  chunking_version text not null,
  is_active boolean not null default false,
  created_at timestamptz not null,
  unique(workspace_id, project_id, name)
)

chunk_embeddings (
  id uuid primary key,
  workspace_id uuid not null,
  project_id uuid not null,
  resource_id uuid not null,
  snapshot_id uuid not null,
  chunk_id uuid not null,
  embedding_namespace_id uuid not null,
  embedding_model text not null,
  embedding_dimension int not null,
  chunking_version text not null,
  vector vector,
  created_at timestamptz not null,
  deleted_at timestamptz
) partition by list (workspace_id)
```

Implementation note: pgvector requires a known dimension for efficient HNSW/IVFFlat indexes. The logical schema is namespace-based, but the physical implementation should create a typed vector storage per active namespace, for example `chunk_embeddings_<namespace>` with `vector(<dimension>)`, or a generated migration/partition whose dimension matches `embedding_namespaces.dimension`. Workspace partitioning still applies inside that namespace table. MVP may support only one active namespace per project, but the API and metadata must still treat embeddings as namespaced so migrations do not mix vector spaces.

### 12.5 Code Symbols

```sql
code_symbols (
  id uuid primary key,
  workspace_id uuid not null,
  project_id uuid not null,
  resource_id uuid not null,
  snapshot_id uuid not null,
  document_id uuid,
  file_path text not null,
  language text,
  symbol_name text not null,
  symbol_kind text not null,
  signature text,
  docstring text,
  line_start int,
  line_end int,
  hash text,
  parser text,
  parser_version text,
  created_at timestamptz not null,
  deleted_at timestamptz
)
```

### 12.6 Graph

Graph tables are part of the target architecture, but full graph extraction/traversal is V1 unless explicitly enabled in V0 as an experimental feature. V0 may create minimal graph nodes for reviewed summaries, but code/doc retrieval must not depend on graph correctness.

```sql
graph_nodes (
  id uuid primary key,
  workspace_id uuid not null,
  project_id uuid not null,
  resource_id uuid,
  snapshot_id uuid,
  node_type text not null,
  source_ref jsonb,
  label text not null,
  summary text,
  confidence text not null default 'extracted',
  reviewed_status text not null default 'unreviewed',
  created_at timestamptz not null,
  deleted_at timestamptz
)

graph_edges (
  id uuid primary key,
  workspace_id uuid not null,
  project_id uuid not null,
  source_node_id uuid not null,
  target_node_id uuid not null,
  relation text not null,
  provenance text not null,
  confidence text not null,
  source_refs jsonb not null default '[]',
  cross_project boolean not null default false,
  reviewed_status text not null default 'unreviewed',
  created_at timestamptz not null,
  deleted_at timestamptz
)
```

Edge creation must ensure source and target nodes belong to the same workspace. Cross-project edges are allowed inside one workspace but must be explicit.

### 12.7 Agent Profiles

```sql
agent_profiles (
  id uuid primary key,
  workspace_id uuid not null,
  project_id uuid not null,
  name text not null,
  description text,
  system_prompt text,
  retrieval_policy jsonb not null default '{}',
  answer_policy jsonb not null default '{}',
  freshness_policy jsonb not null default '{}',
  allowed_resource_types text[],
  created_at timestamptz not null,
  updated_at timestamptz not null,
  deleted_at timestamptz
)
```

### 12.8 Index Runs and Scheduler State

Index jobs must be persisted, not only stored in Redis, because the UI, retry logic, failure review, and drift analysis depend on historical job state.

```sql
index_runs (
  id uuid primary key,
  workspace_id uuid not null,
  project_id uuid not null,
  resource_id uuid not null,
  snapshot_id uuid,
  trigger text not null, -- manual | schedule | webhook | api | retry
  status text not null, -- queued | running | succeeded | failed | cancelled
  started_at timestamptz,
  finished_at timestamptz,
  documents_seen int default 0,
  chunks_created int default 0,
  chunks_reused int default 0,
  symbols_created int default 0,
  embeddings_created int default 0,
  graph_nodes_created int default 0,
  graph_edges_created int default 0,
  error_message text,
  log_ref text,
  metadata jsonb not null default '{}',
  created_at timestamptz not null
)
```

Schedulers should select due resources by `next_refresh_at`, enqueue an `index_run`, and update resource refresh timestamps after completion.

### 12.9 Query, Usage, and Analytics

```sql
query_runs (
  id uuid primary key,
  workspace_id uuid not null,
  user_id uuid,
  agent_profile_id uuid,
  query_text text not null,
  query_mode text not null,
  scope_json jsonb not null default '{}',
  status text not null,
  latency_ms int,
  answer_id uuid,
  created_at timestamptz not null
)

retrieval_hits (
  id uuid primary key,
  workspace_id uuid not null,
  query_run_id uuid not null,
  project_id uuid,
  resource_id uuid,
  document_id uuid,
  chunk_id uuid,
  graph_node_id uuid,
  graph_edge_id uuid,
  retrieval_stage text not null, -- lexical | vector | graph | rerank | final
  raw_score double precision,
  rerank_score double precision,
  rank int,
  selected_for_context boolean not null default false,
  cited_in_answer boolean not null default false,
  created_at timestamptz not null
)

context_packets (
  id uuid primary key,
  workspace_id uuid not null,
  query_run_id uuid,
  project_id uuid,
  token_count int,
  format text not null,
  metadata jsonb not null default '{}',
  created_at timestamptz not null,
  deleted_at timestamptz
)

context_packet_items (
  id uuid primary key,
  workspace_id uuid not null,
  context_packet_id uuid not null,
  query_run_id uuid,
  project_id uuid,
  resource_id uuid,
  document_id uuid,
  chunk_id uuid,
  graph_node_id uuid,
  included_reason text,
  token_count int,
  order_index int,
  created_at timestamptz not null
)

answers (
  id uuid primary key,
  workspace_id uuid not null,
  query_run_id uuid not null,
  content text,
  model text,
  metadata jsonb not null default '{}',
  created_at timestamptz not null
)

answer_citations (
  id uuid primary key,
  workspace_id uuid not null,
  answer_id uuid not null,
  resource_id uuid,
  document_id uuid,
  chunk_id uuid,
  code_symbol_id uuid,
  source_uri text,
  line_start int,
  line_end int,
  citation_text text,
  created_at timestamptz not null
)

feedback (
  id uuid primary key,
  workspace_id uuid not null,
  query_run_id uuid not null,
  user_id uuid,
  rating text not null, -- helpful | wrong | stale | missing_source | irrelevant
  comment text,
  created_at timestamptz not null
)
```

### 12.10 Review Items

```sql
review_items (
  id uuid primary key,
  workspace_id uuid not null,
  project_id uuid,
  resource_id uuid,
  item_type text not null, -- inferred_edge | generated_summary | stale_resource | failed_index | cleanup_suggestion
  subject_ref jsonb not null,
  status text not null default 'pending', -- pending | accepted | rejected | edited | ignored
  priority text not null default 'normal',
  reason text,
  proposed_action jsonb,
  created_at timestamptz not null,
  reviewed_by uuid,
  reviewed_at timestamptz
)
```

### 12.11 Agent Memory

```sql
agent_memories (
  id uuid primary key,
  workspace_id uuid not null,
  project_id uuid,
  user_id uuid,
  agent_profile_id uuid,
  memory_type text not null, -- usage_learning | user_preference | routing_hint | accepted_insight | agent_experience
  content text not null,
  source_ref jsonb,
  confidence text,
  created_at timestamptz not null,
  deleted_at timestamptz
)
```

Agent memory is not source truth. Answers requiring factual claims should cite source resources, not memory alone.

## 13. Ingestion and Indexing Pipeline

### 13.1 Standard Flow

```text
resource refresh requested
  -> permission check
  -> enqueue index_run
  -> fetch source
  -> create source_snapshot
  -> parse source into documents/files
  -> chunk documents
  -> parse code symbols for repos
  -> generate lexical index rows
  -> generate embeddings
  -> extract graph nodes/edges
  -> create generated summaries/review items
  -> update `resources.current_snapshot_id`, freshness, next_refresh_at, and status
  -> emit metrics
```

### 13.2 Snapshot, Incremental Reuse, and Garbage Collection

Default retrieval uses only `resources.current_snapshot_id`. Historical snapshots are retained for audit and reproducibility only when explicitly requested.

MVP indexing may choose one of two implementation strategies, but must declare which one is active:

1. **Full rebuild per snapshot**: create new chunk/code-symbol rows for the new snapshot, set `current_snapshot_id`, and asynchronously garbage-collect superseded snapshot artifacts according to retention settings. This is simpler and preferred for V0.
2. **Content-hash reuse**: detect unchanged documents/chunks by hash, create new snapshot mapping rows while reusing embeddings from identical content. If this strategy is used, add a `snapshot_chunks` mapping table rather than pretending one `chunks.snapshot_id` row belongs to multiple snapshots.

`index_runs.chunks_reused` is only meaningful for the second strategy; for full rebuild it should remain 0.

### 13.3 Git Repository Connector

MVP requirements:

- clone/fetch by HTTPS or SSH
- select branch/ref
- compute latest commit SHA
- support include/exclude patterns
- ignore `.git`, generated directories, binary files, secrets, and size-capped files
- produce file documents and code symbol rows
- preserve file path and line ranges
- run lightweight secret detection before storing chunks/packets
- avoid modifying repo contents
- do not require `AGENTS.md`, `CLAUDE.md`, or repo-local agent files

### 13.4 Document and URL Connector

MVP resource types:

- markdown
- plaintext
- PDF if parser is available
- URL/web page
- uploaded file

URL fetching must include MVP SSRF protection: reject localhost/private-network targets by default, block cloud metadata endpoints, apply response size/time limits, and record final redirected URL.

Future:

- Notion
- Linear
- GitHub Issues
- Slack export
- Google Docs
- Confluence
- Grafana dashboard metadata

### 13.5 Code Intelligence

MVP code intelligence should prioritize deterministic extraction:

- file inventory
- language detection
- functions/classes/modules/interfaces/routes where practical
- imports/references where parser supports them
- source spans
- symbol summaries derived from docstrings/comments only when available

LLM-inferred code relationships must be marked as `inferred` and cannot be used as authoritative refactor or bug impact evidence unless verified.

### 13.6 Graph Extraction

Graph edges should distinguish:

- `parser` / deterministic
- `heuristic`
- `llm`
- `human`
- `runtime`

Confidence values:

- `extracted`
- `inferred`
- `ambiguous`
- `verified`
- `rejected`

LLM-generated edges default to `inferred` or `ambiguous` and create review items when high-impact or high-usage.

### 13.7 Embeddings

Each embedding row must record namespace, embedding model, embedding dimension, chunking version, snapshot ID, and resource ID. Changing embedding model or dimension creates a new namespace; activation requires re-embedding enough current snapshots for the namespace. Do not mix vector spaces.

### 13.8 Reranking

Reranking is query-time only. Rerank scores do not become graph truth.

Recommended MVP rerank configuration:

- disabled by default for lowest friction
- project-level opt-in
- top N candidates only, e.g. 50-100
- support HTTP endpoint compatible with Hugging Face/vLLM/SGLang or local worker

## 14. Query Modes

Supported modes are staged. MVP modes are intentionally small:

```text
auto
code
doc
cross_resource
```

Future modes after the retrieval foundation is proven:

```text
bug_triage
pr_review
business_insight
ops_runbook
algorithm_research
```

### 14.1 Auto Mode

Classifies user intent, identifies scope, picks retrieval strategy, and asks for disambiguation only when ambiguity materially affects results.

### 14.2 Code Mode

Uses lexical search, code symbols, repository snapshots, and optional semantic code search. Answers must cite commit, file, and line range where possible.

### 14.3 Bug Triage Mode

Future mode, not V0. It should only be enabled after code symbols, current-snapshot filtering, usage tracing, and optional graph expansion are working.

Flow:

```text
extract error/stack/symbols
  -> exact lexical search
  -> code symbol search
  -> graph expansion around candidates
  -> recent changes if available
  -> runbook/doc retrieval
  -> rerank candidates
  -> context packet
  -> answer with hypotheses, evidence, and verification steps
```

Answers must separate:

- confirmed evidence
- likely hypothesis
- missing evidence
- verification next step

### 14.4 PR Review Mode

Future mode for GitHub/GitLab PRs:

- diff to changed files/functions
- impact graph
- affected tests/docs/runbooks
- context packet for external reviewer
- no automatic merge decisions

### 14.5 Business Insight Mode

Uses business docs, domain/process graph, code-service mapping, and reviewed summaries. Unreviewed LLM-inferred business flows must be clearly labeled.

### 14.6 Ops Runbook Mode

Uses runbooks, service docs, incident history, and static repo context. Live production operations must go through external typed tools and approval flows outside SourceBrief.

### 14.7 Cross-Resource Mode

V0 supports cross-resource retrieval inside one project. Cross-project or workspace-wide retrieval is V1 unless explicitly enabled behind an admin-controlled feature flag. Evidence must be grouped by source and freshness.

## 15. Retrieval Pipeline

### 15.1 Mandatory Flow

```text
resolve user/token identity
  -> resolve allowed workspace/project/resource scope
  -> apply permission pre-filter
  -> restrict resources to current_snapshot_id unless historical query is explicitly requested
  -> candidate generation:
       lexical search
       vector search over workspace/project partitions and active embedding namespace
       code symbol search
       graph seed search if graph feature is enabled
  -> graph expansion within allowed scope if graph feature is enabled
  -> deduplicate candidates
  -> rerank if enabled
  -> build context packet
  -> generate answer or return packet
  -> record query_run/retrieval_hits/context_items/citations/feedback hooks
```

### 15.2 pgvector Filtering Strategy

MVP must not search a global vector index and filter after the fact. At minimum, embeddings should be partitioned by `workspace_id`, and queries should combine tenant/project/resource predicates with active embedding namespace and current snapshot filters before nearest-neighbor ranking. If pgvector filtered ANN recall is insufficient, the implementation should over-fetch within the tenant partition and record recall/latency metrics; specialized vector stores remain optional future adapters.

### 15.3 Candidate Sources

- PostgreSQL full-text search
- pgvector similarity search
- code symbol search
- graph traversal
- accepted agent memory/routing hints
- prior successful query outcomes, never as sole factual evidence

### 15.4 Context Packet Output

Formats:

- JSON for APIs
- Markdown for humans
- XML-like format for LLM context if needed

Packet fields:

```json
{
  "goal": "bug triage RuntimeBundle reboot issue",
  "scope": {},
  "freshness": [],
  "selected_sources": [],
  "source_excerpts": [],
  "code_symbols": [],
  "graph_paths": [],
  "omitted_sources": [],
  "citations": [],
  "audit": {
    "generated_at": "...",
    "retrieval_methods": [],
    "reranker": null,
    "token_count": 0,
    "permission_scope": "..."
  }
}
```

## 16. Review and Curation UI

Review UI is a core product feature.

### 16.1 Project Overview

Shows:

- resources count
- last indexed time
- freshness state
- failed index jobs
- stale resources
- chunks/symbols/graph edges count
- latest query feedback

### 16.2 Resource Management

Shows:

- resource type
- version/commit/hash
- last successful index
- update frequency
- freshness
- status
- usage counts
- actions: refresh, reindex, pause, archive, soft delete, hard delete, restore

### 16.3 Index Runs

Shows:

- duration
- source version
- changed files/docs/chunks/symbols
- embeddings generated
- graph edges generated
- parser failures
- logs

### 16.4 Knowledge Review

Review items:

- generated summaries
- inferred graph edges
- ambiguous relationships
- high-usage unreviewed claims
- stale high-usage resources
- failed indexing jobs
- cleanup suggestions

Actions:

- accept
- reject
- edit
- mark verified
- require source
- hide from agent answers

### 16.5 Agent Preview

Allows project maintainers to test:

- query
- retrieval candidates
- graph expansion
- rerank results
- context packet
- final answer
- citations and freshness warnings

### 16.6 Usage and Drift

Shows:

- query hit count
- context inclusion count
- citation count
- positive/negative feedback
- stale hit count
- last hit/cited time
- zero-hit days
- token cost contribution
- cleanup recommendations

## 17. Usage Analytics

The platform must answer:

- Which resources are queried most?
- Which resources are retrieved but never cited?
- Which context items consume tokens but get poor feedback?
- Which stale resources are still used?
- Which resources are unused and candidates for archive/delete?
- Which query clusters lack high-quality resources?
- Which generated summaries or inferred edges are high-impact and need review?

### 17.1 Resource Value Score

MVP may compute a simple score:

```text
value_score = citations * 3
            + context_inclusions * 1
            + helpful_feedback * 5
            - wrong_feedback * 5
            - stale_hits * 2
            - zero_hit_days_penalty
```

This is advisory only and should not auto-delete resources.

### 17.2 Query Clustering

Future feature:

- cluster queries by embedding/text similarity
- show top resources per cluster
- identify missing docs/runbooks
- generate review suggestions

## 18. Agent Memory and Hindsight

### 18.1 Positioning

Hindsight-like memory is useful for agent learning, but not as the source-of-truth repository/document index.

Source truth belongs to:

- resources
- snapshots
- chunks
- code symbols
- graph nodes/edges
- citations

Agent memory belongs to:

- user/team preferences
- routing hints
- accepted learnings
- repeated query patterns
- feedback summaries
- past investigation outcomes

### 18.2 MVP Recommendation

Implement internal lightweight memory using PostgreSQL and pgvector first.

Optional later:

```text
memory_backend = internal | hindsight
```

If Hindsight is integrated, it must be scoped by workspace/project/user/agent bank and cannot be used as factual evidence without citations to source resources.

### 18.3 Hindsight-Inspired Operations

- `retain`: store useful feedback, accepted insight, routing hint
- `recall`: retrieve prior accepted learning or routing hints
- `reflect`: generate cleanup suggestions, route improvements, or project learning summaries

## 19. External Integrations

### 19.1 HTTP API

Core endpoints:

```http
POST /workspaces
POST /workspaces/{workspace_id}/projects
POST /workspaces/{workspace_id}/projects/{project_id}/resources
PATCH /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}
POST  /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/refresh
POST  /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/reindex
POST  /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/pause
POST  /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/archive
POST  /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/restore
DELETE /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}          # soft delete by default
DELETE /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/purge    # hard delete
POST /workspaces/{workspace_id}/projects/{project_id}/query
POST /workspaces/{workspace_id}/query
GET  /workspaces/{workspace_id}/projects/{project_id}/review-items
POST /workspaces/{workspace_id}/review-items/{review_item_id}/decision
GET  /workspaces/{workspace_id}/projects/{project_id}/usage
```

### 19.2 Query API Contract

MVP query API is retrieval-first. It returns a context packet and citations. Built-in natural-language answer generation is V1 unless explicitly enabled.

Request:

```json
{
  "query": "How does resource deletion work?",
  "mode": "auto",
  "scope": {
    "project_ids": ["..."],
    "resource_ids": [],
    "resource_types": ["git_repo", "runbook"],
    "freshness": "fresh_or_warn"
  },
  "top_k": 20,
  "rerank": false,
  "return": ["context_packet", "citations", "trace"]
}
```

Response:

```json
{
  "query_run_id": "...",
  "context_packet_id": "...",
  "items": [],
  "citations": [],
  "freshness": [],
  "warnings": [],
  "trace": {
    "retrieval_stages": []
  }
}
```

Permission errors should avoid leaking existence of unauthorized resources. Use 404 for inaccessible project/resource identifiers and 403 for authenticated users lacking workspace access when the workspace itself is already known.

### 19.3 Central MCP Server

One platform MCP server, not one per repo.

Tools:

```text
list_workspaces
list_projects
list_resources
query_project
query_workspace
build_context_packet
refresh_resource
get_resource_usage
list_review_items
submit_review_decision
```

Every tool call must enforce token/user permissions.

### 19.4 Hermes Adapter

Hermes can call SourceBrief as external knowledge/context provider. SourceBrief does not replace Hermes approval, production tools, or typed MCP operations.

### 19.5 Claude Code / Codex / Cursor

Provide:

- MCP config snippets
- API usage examples
- context packet export
- optional CLI wrapper

## 20. Production Discipline

SourceBrief can know runbooks and repository code. It should not become a production mutation engine.

For production workflows:

1. SourceBrief retrieves static knowledge and runbooks.
2. External typed tools query live state, e.g. Grafana, Prometheus, Teleport, OpenSearch, GitHub.
3. Production action approval is handled by the calling runtime or external workflow.
4. Answers must separate static knowledge, historical evidence, live evidence, hypotheses, and required verification.

## 21. Security and Access Control Roadmap

### 21.1 MVP Required

- workspace/project ownership
- workspace/project roles
- service tokens with scopes
- permission pre-filter retrieval
- workspace-partitioned vector search strategy
- tenant-scoped embeddings/graph/context/query logs
- soft delete/archive
- resource visibility fields
- audit events for sensitive operations
- URL SSRF protection for web resources
- lightweight secret detection before indexing

### 21.2 Later

- OIDC/SAML
- SCIM
- row-level security
- enterprise audit export
- retention policy
- legal hold
- tenant-specific encryption keys
- advanced DLP/secret scanning
- per-resource/per-document ACL

## 22. Observability

Metrics:

- ingestion lag by resource
- failed index runs
- parse failures by file type/language
- embedding queue depth
- vector/rerank latency
- query latency by mode
- retrieval candidate counts
- context token counts
- citation coverage
- stale answer warnings
- resource hit/citation counts
- review backlog
- feedback rates

Traces:

```text
query -> route -> permission scope -> retrieval calls -> rerank -> context packet -> answer -> citations
```

Logs must avoid raw secrets where possible. Query text is sensitive and should follow workspace retention settings.

## 23. Evaluation and Acceptance Gates

### 23.1 Golden Questions

Each project can define golden questions with expected sources/citations.

Metrics:

- required evidence in top-k
- citation correctness
- answer groundedness
- stale answer detection
- permission block correctness

### 23.2 Bug Localization Evaluation

Use historical bugs with known fixing commits.

Metrics:

- top-k file recall
- implicated symbol recall
- verification step quality
- false confidence rate

### 23.3 PR Blast Radius Evaluation

Use historical PRs.

Metrics:

- affected file/test/service recall
- false positive rate
- reviewer usefulness
- token reduction with correctness preserved

### 23.4 Resource Cleanup Evaluation

Metrics:

- stale resources identified
- unused resources suggested
- wrong/stale feedback decreasing
- review backlog aging

## 24. MVP Scope

### 24.1 V0 Single-Node Open Source MVP

Required:

1. workspace/project/user/role data model
2. project creation
3. Git repo resource ingestion
4. Markdown/plaintext/uploaded doc ingestion
5. URL ingestion if easy
6. configurable update frequency
7. manual refresh/reindex
8. versioned snapshots
9. chunks + pgvector embeddings
10. basic code symbol index
11. optional minimal graph metadata only if it does not block retrieval MVP
12. query project agent in retrieval-only mode
13. context packet generation
14. central MCP server
15. review page for stale/failed/generated items and optional inferred items
16. usage analytics tables and dashboard
17. resource archive/soft delete/hard delete job

### 24.2 V1 Multi-Resource and Cross-Repo

Add:

- multiple repos per project
- cross-project query within workspace
- PR branch indexing
- GitHub webhook refresh
- graph extraction/traversal and graph review workflows
- runbook resource type
- eval/golden question page
- query clustering
- cleanup recommendations
- API token management UI

### 24.3 V2 Team SaaS

Add:

- SSO/OIDC
- advanced RBAC
- audit export
- resource-level ACL
- external connectors
- storage adapters
- model provider UI
- deployment templates
- workspace-level billing if desired

## 25. Implementation Milestones

### Milestone 1: Foundation

- Repo scaffold
- API backend
- PostgreSQL migrations
- workspace/project/resource models
- user auth placeholder
- roles, service tokens, and audit event table
- Docker Compose for Postgres/pgvector/Redis/API/RQ worker/frontend
- real-service QA smoke gate

Acceptance:

- create workspace/project/resource via API
- enforce workspace/project membership on reads
- run local stack with one command
- enqueue a no-op `index_run` through RQ and observe `queued -> running -> succeeded`
- run lint, unit tests, integration tests, and Docker Compose QA smoke before marking the milestone complete

### Milestone 2: Resource Ingestion

- Git repo connector
- file/doc connector
- source snapshots
- chunks
- basic lexical search
- manual refresh
- index run UI/logs

Acceptance:

- add a repo and markdown file
- see snapshot version/commit/hash
- query text search within allowed scope

### Milestone 3: Embeddings and Retrieval

- embedding provider config
- pgvector embedding storage
- hybrid lexical/vector retrieval
- context packet builder
- query_runs/retrieval_hits/context_packet_items

Acceptance:

- query returns a context packet with cited chunks, not necessarily a generated answer
- usage analytics captures hit/context/citation events
- permission pre-filter and current-snapshot filtering are tested

### Milestone 4: Code Intelligence

- code symbol extraction
- file/symbol search
- repo commit citations
- basic code query mode

Acceptance:

- answer code questions with file/line/commit citations
- no LLM-inferred code edge treated as authoritative

### Milestone 5: Review and Lifecycle

- review items
- resource usage dashboard
- archive/soft delete/hard delete
- stale/failure review
- generated summary/inferred edge review

Acceptance:

- archived/soft-deleted resource disappears from retrieval
- hard delete purges derived artifacts
- usage dashboard shows counts

### Milestone 6: Agent Integrations

- central MCP server
- API docs
- optional web chat/context preview
- Hermes adapter docs
- Claude/Codex/Cursor usage examples

Acceptance:

- external client queries project agent via API/MCP
- context packet export works

## 26. Architectural Decisions

### 26.1 Project-first over repo-first

Repos are resources inside projects. This supports arbitrary documents, runbooks, cross-repo projects, and future business/ops resources.

### 26.2 Postgres/pgvector first

PostgreSQL plus pgvector minimizes operational dependencies for open-source SaaS. Introduce specialized vector/graph stores only after proven need.

### 26.3 RQ as the V0 background job engine

SourceBrief V0 uses RQ because the workload is mostly long-running, retryable, resource-scoped indexing/cleanup jobs rather than complex distributed workflows. RQ keeps the open-source deployment small by reusing Redis, matches the Python/FastAPI stack, and has precedent in production open-source systems such as CVAT. PostgreSQL remains the durable source of truth through `index_runs`; RQ/Redis is only the execution queue.

### 26.4 Central MCP over per-repo MCP

A central platform MCP server avoids server lifecycle and tool schema explosion. Repos are selected by project/resource IDs, not by separate MCP servers.

### 26.5 Source truth separate from agent memory

Repo/document/resource snapshots are source truth. Agent memory stores learned usage, preferences, and routing hints only.

### 26.6 Reviewable generated knowledge

LLM-generated summaries and inferred edges must be reviewable and marked by confidence/provenance. They are not equivalent to parser-extracted or human-verified facts.

### 26.7 Multi-tenant from day one

Workspace/project/resource scoping is mandatory in schema and retrieval. Full enterprise security can come later, but tenant boundaries cannot.

### 26.8 Real-service QA gate

A feature is not complete merely because unit tests pass. Each milestone must include lint, unit tests where useful, real-service integration tests, Docker Compose startup, and a senior-QA-style smoke flow that exercises the platform through API, database, Redis/RQ worker, and frontend/runtime services. Mocks are allowed for pure unit boundaries and unavailable third-party systems, but the core local platform path must be tested with real services.

## 27. Key Risks

### 27.1 Permission leaks through derived artifacts

Mitigation: every artifact has workspace/project/resource scope; retrieval pre-filters by permission; generated summaries inherit source visibility.

### 27.2 Stale context causing wrong answers

Mitigation: versioned snapshots, freshness display, stale warnings, query-time freshness policy.

### 27.3 Graph overclaiming

Mitigation: provenance/confidence fields; review workflow; source citations; no inferred edge as hard truth by default.

### 27.4 Cross-resource noise

Mitigation: query mode classification, scope controls, rerank, evidence grouping, resource usage feedback.

### 27.5 Review UX overload

Mitigation: start with three review item types: stale/failed resources, inferred edges, generated summaries.

### 27.6 Embedding model migration pain

Mitigation: record embedding model/dimension/version; namespace embeddings; rebuild on model changes.

### 27.7 Too many external dependencies

Mitigation: MVP uses PostgreSQL, pgvector, Redis, and local/OpenAI-compatible model endpoints only.

## 28. MVP Scope Decisions After Review

The following choices are fixed for MVP to avoid ambiguity:

1. V0 is retrieval-first. It returns context packets and citations. Built-in answer generation and groundedness scoring are V1 unless explicitly enabled behind a feature flag.
2. FastAPI is the recommended backend for the first implementation because the indexing, parser, embedding, and ML tooling ecosystem is Python-heavy.
3. MVP auth may use local dev accounts plus scoped service tokens, but workspace/project membership enforcement is not optional.
4. Full graph extraction/traversal is V1 unless an experimental minimal graph can be implemented without delaying retrieval, resource lifecycle, and multi-tenant foundations.
5. Reranking is optional and query-time only. It is disabled by default until baseline retrieval metrics exist.

## 29. Open Questions

1. Which code parser should be MVP default: tree-sitter directly, pygments-like fallback, or language-specific adapters?
2. Should Graphify/LightRAG/CodeGraph concepts be implemented natively first or wrapped as optional workers?
3. How much of PDF parsing should be in V0?
4. Should Hindsight be optional integration in V1 or only design inspiration until later?
5. What should be the first demo dataset: SourceBrief repo itself, Hermes Agent, or a small public multi-repo project?

## 30. Initial Demo Scenario

Recommended first demo:

1. Create workspace `demo`.
2. Create project `SourceBrief`.
3. Add the `pingchesu/sourcebrief` repository.
4. Add a markdown runbook resource.
5. Configure daily update.
6. Run initial indexing.
7. Ask:
   - "What is SourceBrief's core architecture?"
   - "Which resources explain multi-tenant permission filtering?"
   - "Build a context packet for implementing resource deletion."
8. Show:
   - cited answer
   - source snapshot freshness
   - retrieval hits
   - context packet contents
   - review item for an inferred edge
   - resource usage dashboard

## 31. Definition of Done for MVP

MVP is done when:

1. A user can create a workspace/project.
2. A user can add at least one Git repo and one document resource.
3. Resources produce versioned snapshots and freshness metadata.
4. The system indexes chunks and embeddings into PostgreSQL/pgvector.
5. The system extracts at least basic code symbols from repositories.
6. Project query returns a context packet with citations and freshness metadata.
7. Retrieval honors workspace/project permissions before search.
8. Retrieval restricts default queries to each resource's current snapshot.
9. Query usage is recorded at query, hit, context inclusion, and citation levels.
10. Resources can be refreshed, archived, soft-deleted, and hard-deleted.
11. Review UI shows stale/failed/generated items and optional inferred items.
12. A central MCP server or equivalent HTTP API can query a project agent.
13. The local deployment uses only PostgreSQL/pgvector, Redis, API, worker, frontend, and optional model endpoints.
