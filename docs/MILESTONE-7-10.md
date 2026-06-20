# Milestones 7-10 — Agent Registry, Providerized Retrieval, Graph Index, GraphRAG

This milestone group turns the M1-M6 resource/context substrate into a project-as-agent platform.

## M7 — Agent Registry & Agent Profile

Every project now has a central `agent_profile` owned by SourceBrief, not by the source repository.

- `GET /workspaces/{workspace_id}/agents` lists all project agents in a workspace.
- `GET /workspaces/{workspace_id}/projects/{project_id}/agent-profile` returns one project agent profile plus live index stats.
- `PATCH /workspaces/{workspace_id}/projects/{project_id}/agent-profile` updates runtime defaults, system prompt, and tool policy.
- Agent profiles are auto-created when a project is created or first read.
- `agent-context` appends the profile system prompt to the runtime instruction packet.

Design boundary: repo owners do not need to commit `AGENTS.md`; SourceBrief keeps agent identity, prompt, policy, and runtime endpoints in the platform registry.

## M8 — Providerized Embedding/Rerank

The default development path remains deterministic/offline, but embedding and rerank are now providerized.

Environment knobs:

```bash
SOURCEBRIEF_EMBEDDING_PROVIDER=hashing          # default deterministic dev provider
SOURCEBRIEF_EMBEDDING_PROVIDER=http             # OpenAI-compatible HTTP service
SOURCEBRIEF_EMBEDDING_MODEL=text-embedding-model
SOURCEBRIEF_EMBEDDING_ENDPOINT=http://localhost:8000/v1/embeddings
SOURCEBRIEF_EMBEDDING_API_KEY=...

SOURCEBRIEF_RERANK_PROVIDER=term-overlap        # default deterministic dev reranker
SOURCEBRIEF_RERANK_PROVIDER=http
SOURCEBRIEF_RERANK_MODEL=bge-reranker
SOURCEBRIEF_RERANK_ENDPOINT=http://localhost:8001/rerank
SOURCEBRIEF_RERANK_API_KEY=...
```

The HTTP adapters accept common HuggingFace/vLLM/SGLang/OpenAI-compatible shapes. In this MVP the pgvector column is fixed at 64 dimensions, so external embedding services must return 64-dimensional embeddings or sit behind a projection/proxy layer.

- Embedding: `{ "data": [{ "embedding": [...] }] }` or `{ "embedding": [...] }`.
- Rerank: `{ "scores": [...] }`, `{ "results": [{ "score": ... }] }`, or `{ "score": ... }`.

## M9 — Graph Index Worker

Each successful resource refresh now also builds a deterministic graph index:

- `resource` node
- `directory` nodes
- `file` nodes
- `symbol` nodes from code intelligence
- `contains`, `defines`, and `sibling` edges

New endpoint:

```http
GET /workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/graph?limit=200
```

The index run records `graph_nodes_created` and `graph_edges_created`, so QA and operators can detect regressions when graph indexing silently disappears.

## M10 — Graph-aware Retrieval Signal

Retrieval now combines four signals:

```text
score = 0.40 lexical + 0.35 vector + 0.15 graph + 0.10 rerank
```

The graph signal boosts chunks whose current snapshot path/symbol/file graph matches the query. It is intentionally a bounded signal, not the main truth source; lexical/vector still dominate until graph quality is measured against real usage.

Returned citations include `graph_score`, and context packet items store `graph_score` in `retrieval_hits` for analytics.

## CLI

```bash
sourcebrief agent list --workspace-id $WS
sourcebrief agent profile --workspace-id $WS --project-id $PROJECT
sourcebrief --json resource graph --workspace-id $WS --project-id $PROJECT --resource-id $RESOURCE
```

## Operational notes

- Multi-tenant boundary is preserved with workspace/project IDs on agent, graph node, graph edge, query, and retrieval rows.
- Production mutations remain outside SourceBrief context retrieval. The default tool policy marks production mutations as `external_approval_required`.
- Graph index is rebuilt per versioned snapshot; old snapshots remain queryable in DB history but active retrieval uses current, non-archived resources.
- This is deliberately not a full Graphify/LightRAG clone. Graphify-like clustering can be added later as an optional worker once we have usage/eval evidence that it improves answer quality.
