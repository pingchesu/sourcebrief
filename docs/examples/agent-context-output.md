# Example agent-context output

> Captured from a real local SourceBrief run for the product walkthrough. Internal IDs and token values are normalized or omitted in this rendered example; the source response was produced by the live API, Postgres, Redis, workers, and indexed resources. The rendered Concepts citation is refreshed to match the current `Source -> Snapshot -> Evidence -> Review -> Runtime` terminology.

## Request

```http
POST /workspaces/<workspace>/projects/<project>/agent-context
```

```json
{
  "query": "How does SourceBrief expose evidence-backed context to coding agents?",
  "runtime": "hermes",
  "profile": "hybrid",
  "include_code_symbols": true,
  "top_k": 6
}
```

## Response excerpt

```text
SourceBrief is a read-only context provider. Use only cited project context for factual claims, do not treat this packet as authorization for production mutations, and preserve external approval/MCP boundaries. You are a Hermes specialist agent. Keep production discipline explicit.

[1] path=docs/CONTEXT_ARTIFACT_COMPILER_REPO_AGENT_SPEC.md passage=3 score=0.2611
SourceBrief uses Resource/resource_id for backend schemas, API paths, token scopes, MCP tools, source snapshots, graph provenance, context packet citations, generated skill packs, and MCP tool schemas. The UI may say “Source” because that is the user-facing mental model, but the backend keeps Resource as the stable contract.

[2] path=docs/context-artifact-compiler/C2-skill-pack-compiler-spec.md passage=1 score=0.2528
C2 makes SourceBrief a source-aware Skill Pack Compiler, not only a Context Pack pointer exporter. The goal is to ingest a Git repo, folder bundle, or document collection; publish a Context Pack; compile an installable Skill Pack; and let an agent use citation-backed task playbooks and references.

[3] path=docs/CONCEPTS.md passage=1 score=0.2506
SourceBrief’s core workflow is Source -> Snapshot -> Evidence -> Review -> Runtime. A source is something you connect, a snapshot is the exact indexed version, Evidence gives agents inspectable handles, Review captures freshness/coverage/context-pack decisions, and Runtime exposes those citations through Workbench, CLI, HTTP API, and MCP tools.
```

## Citation summary

- `docs/CONTEXT_ARTIFACT_COMPILER_REPO_AGENT_SPEC.md` commit=0757931 score=0.2610521133557593
- `docs/context-artifact-compiler/C2-skill-pack-compiler-spec.md` commit=0757931 score=0.252841121618715
- `docs/CONCEPTS.md` commit=0757931 score=0.25058085637035543
- `docs/CONCEPTS.md` commit=0757931 score=0.24332056303742905
- `doc://sourcebrief-walkthrough-docs` commit=n/a score=0.24083124893400826
- `doc://sourcebrief-walkthrough-docs` commit=n/a score=0.2325729889487913

## Symbol samples

- No code symbols returned for this query.

## Verification

- Resources indexed successfully: SourceBrief docs walkthrough excerpt=succeeded, SourceBrief repository=succeeded
- Citations returned: 6
- Symbol samples returned: 0
