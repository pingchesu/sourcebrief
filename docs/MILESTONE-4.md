# Milestone 4: Code Intelligence

Milestone 4 adds deterministic code-aware indexing on top of the M2/M3 resource
pipeline. The goal is not to infer architecture with an LLM; it is to expose
source-derived symbols with precise file/line/commit citations.

## Scope

Implemented in this milestone:

- `code_symbols` storage for source-derived symbols.
- Deterministic symbol extraction for Python, JavaScript, TypeScript, TSX, JSX.
- Worker-side symbol extraction during git/document ingestion.
- `IndexRun.symbols_created` is populated from real extraction results.
- `POST /workspaces/{workspace_id}/projects/{project_id}/code-search`.
- Symbol search is scoped to current snapshots and honors `resource_ids`.

## Guarantees

- Symbols are extracted from files and line numbers only.
- No LLM-inferred call graph or ownership edge is treated as authoritative.
- Citations include resource, current snapshot, file path, line range, version,
  and commit when the resource is a git repo.
- Workspace/project permission checks are identical to retrieval endpoints.

## Non-goals

- No cross-language parser framework yet.
- No Tree-sitter dependency yet.
- No call/reference graph yet; this milestone builds the trusted symbol layer that
  later graph intelligence can depend on.

## Verification gate

```bash
make lint test
make compose-up migrate test-integration
make verify
```

Integration coverage must prove git ingestion extracts symbols and `code-search`
returns file/line/commit citations without leaking to unauthorized users.
