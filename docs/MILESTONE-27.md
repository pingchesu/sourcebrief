# Milestone 27 - Retrieval Profiles and Eval Guidance

Phase 4 makes retrieval strategy explicit and measurable instead of hiding it behind one hybrid score.

## API

- `GET /workspaces/{workspace_id}/projects/{project_id}/retrieval-profiles` lists supported profiles and scoring weights.
- `POST /agent-context`, `POST /context-packets`, and `POST /retrieval-evals` accept `profile`.
- `retrieval-evals` persist the selected profile in run history and detail responses.

Supported profiles:

- `hybrid` - default balanced lexical/vector/rerank retrieval.
- `lexical` - exact identifiers, error strings, config keys, and literal text.
- `vector` - semantic discovery when exact words may differ.
- `hybrid_rerank` - higher rerank influence for eval-backed precision checks.
- `graph` - boosts graph/code-structure evidence for architecture and impact questions.

## UI

The Quality Evals page loads the profile catalog, lets reviewers choose a profile before running golden questions, and shows profile in summary/history so embedding/rerank/graph changes are comparable over time.

## Skill Pack Guidance

Generated Hermes/Codex/Claude adapters now include profile-selection guidance. The pack still remains read-only and remote-first; MCP configuration and scoped bearer tokens stay separate from raw skill installation.

## Operating Rule

Use `hybrid` unless the question shape has stronger evidence needs. Treat profile changes as experiments: run the same golden question set across candidate profiles, compare pass rate, latency, citation quality, and failure reasons, then keep the profile choice in eval history.
