# Milestone 3: Embeddings, Hybrid Retrieval, and Context Packets

Milestone 3 turns SourceBrief from a lexical search prototype into a retrieval
pipeline that can serve agent-ready context packets.

## Scope

Implemented in this milestone:

- Deterministic local `hashing` embedding provider for dev/test/offline CI.
- `chunk_embeddings` storage backed by pgvector `vector(64)`.
- Worker-side embedding creation during resource ingestion.
- Hybrid retrieval over current snapshots only:
  - PostgreSQL full-text lexical candidates.
  - pgvector nearest-neighbor candidates.
  - deterministic term-overlap rerank/guard for the local hashing provider.
- `POST /workspaces/{workspace_id}/projects/{project_id}/context-packets`.
- Durable usage analytics:
  - `query_runs`
  - `retrieval_hits`
  - `context_packets`
  - `context_packet_items`
- Frontend context packet query UI.

## Non-goals

- No model downloads in V0/M3.
- No HuggingFace/vLLM/SGLang runtime integration yet; the provider boundary is in
  place so those can replace the hashing provider later.
- No generated answer synthesis. The API returns cited context, not a final answer.

## Security and correctness constraints

- Retrieval remains workspace/project scoped.
- Retrieval only considers active, retrieval-enabled resources.
- Retrieval only considers each resource's `current_snapshot_id`.
- Optional `resource_ids` is applied before retrieval, not after ranking.
- Citations expose resource/snapshot/chunk/path/version metadata, not secret source
  URLs or raw source config.

## Verification gate

Milestone 3 is complete only when the standard real-service gate passes:

```bash
make lint test
make compose-up migrate test-integration
make verify
```

The integration tests must prove:

- embeddings are created during ingestion,
- context packets return cited chunks,
- query/retrieval/context analytics rows are written,
- old snapshots are not retrieved after re-index,
- `resource_ids` pre-filtering is enforced.
