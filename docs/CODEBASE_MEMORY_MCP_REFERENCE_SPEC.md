# Codebase Memory MCP Reference Spec

## Goal

Use the analysis of [`DeusData/codebase-memory-mcp`](https://github.com/DeusData/codebase-memory-mcp) to define SourceBrief's next product and engineering slices. The intent is not to copy the local single-binary MCP architecture; it is to adapt the strongest ideas into SourceBrief's governed context platform:

- easy runtime onboarding;
- cross-repo and docs-aware context as a first-class product story;
- architecture and graph overview tools;
- reviewable cross-resource service-link candidates;
- faster, more precise code indexing and search.

This spec is the source of truth for the follow-up implementation sequence. Each slice should be completed through the SourceBrief agent workflow: fresh branch from `main`, implementation/spec review, Hermes adversarial review, relevant gates, PR evidence, merge when authorized, and local `main` sync.

## Source evidence

Reviewed external repo:

- `DeusData/codebase-memory-mcp` at commit `53ebeb4cf1fca0f4b2384e7ab085e529a2d2750b`.

Important observed patterns:

- README leads with a compact promise, quick install, cross-repo intelligence, agent support, performance claims, and security/trust claims.
- Runtime onboarding includes install, update, uninstall, config, dry-run/plan, agent autodetection, instruction files, and hooks.
- MCP tools include indexing, graph search, graph schema, architecture overview, trace path, change detection, source snippets, ADRs, and trace ingestion.
- Cross-repo intelligence creates `CROSS_*` edges for HTTP, async channels, gRPC, GraphQL, and tRPC across indexed projects.
- The indexer is local and performance-oriented: tree-sitter, hybrid language-resolution passes, RAM-first graph staging, SQLite/FTS, local semantic vectors, and watcher/incremental refresh.
- Trust claims are prominent, but some reviewer findings showed claim/enforcement drift; SourceBrief must avoid overclaiming.

SourceBrief baseline after Milestone 30:

- `POST /workspaces/{workspace_id}/projects/{project_id}/runtime-install-plan` returns a dry-run runtime install plan.
- `sourcebrief runtime plan` exposes that API from the CLI.
- Agent Profile UI can generate copyable runtime plans.
- SourceBrief uses project-scoped MCP, scoped tokens, resource allowlists, citations, graph versions, graph merge versions, context packs, and generated agent packs.

## Product principles

1. **Plan first, apply explicitly.** SourceBrief can feel easy to install without silently mutating Hermes, Claude, Codex, Cursor, shell profiles, or local runtime state.
2. **Cross-repo means cross-resource within a governed project.** SourceBrief should expose one project-scoped MCP endpoint across repos, docs, runbooks, URLs, and uploads while preserving resource boundaries and permissions.
3. **Evidence beats raw speed claims.** SourceBrief should not claim millisecond graph queries, full LSP parity, SLSA, reproducibility, VirusTotal coverage, or local-only behavior unless the implementation and gates prove it.
4. **Derived graph facts need provenance and review.** Inferred cross-resource links should start as reviewable candidates, not silently published graph facts.
5. **Runtime artifacts are executable products.** Generated configs, validator commands, agent packs, receipts, and rollback plans must be parsed, tested, and kept token-safe.
6. **Human-first entry points.** Avoid UUID-first workflows in README, UI, CLI output, and runtime instructions. IDs may appear as drilldown handles, not as the main product path.

## Non-goals

- Do not replace SourceBrief's PostgreSQL/pgvector/server architecture with a repo-local SQLite MCP server.
- Do not create one MCP server per repository as the SourceBrief product model.
- Do not auto-index or auto-publish runtime state from an agent session without SourceBrief review/publish gates.
- Do not expose raw SQL/Cypher over multi-tenant graph tables.
- Do not commit repo-local binary graph databases as canonical SourceBrief state.
- Do not install global hooks or agent instructions by default.
- Do not persist plaintext bearer tokens in generated config, receipts, skill packs, docs, or local runtime files.

## Workstream A - README and Runtime Productization

### Objective

Make SourceBrief's public product surface communicate the fast path: connect sources, ask across repos/docs/runbooks, generate a safe runtime install plan, validate the agent connection, and get cited evidence.

### Scope

- Update `README.md`.
- Update `docs/README.md`.
- Add or update a user-facing runtime install guide, separate from implementation milestone history.
- Keep `docs/MILESTONE-30.md` as implementation history.

### Requirements

- Add an above-the-fold value/trust strip that only claims what SourceBrief proves today, such as:
  - cited evidence for coding agents;
  - project-scoped MCP;
  - read-only by default;
  - scoped tokens;
  - no silent runtime profile mutation;
  - early alpha / local product exploration status.
- Add a `Connect an agent safely` section near the demo/walkthrough.
- Add a `Cross-repo and docs-aware context` section that explains:
  - one SourceBrief project can include multiple repos, docs, runbooks, URLs, uploads, and zip bundles;
  - one project-scoped MCP endpoint serves authorized cited evidence across those resources;
  - resource boundaries, freshness, and citations are preserved.
- Add a `What SourceBrief is / is not` table that frames limitations as product trust boundaries.
- Add a practical runtime install plan guide covering:
  - UI path from Agent Profile;
  - CLI path with `sourcebrief runtime plan`;
  - recommended token scopes;
  - config copy/apply boundary;
  - validator command;
  - rollback steps;
  - token safety.
- Add M30 / runtime install plan to `docs/README.md` so new users do not need to find it through milestone history.

### Acceptance criteria

- A new user can identify within 10 seconds:
  - what SourceBrief does;
  - why it helps agents;
  - how it supports cross-repo/docs context;
  - how to connect Hermes/Claude/Codex safely;
  - why SourceBrief does not silently mutate local runtimes.
- No README/docs claim depends on unimplemented release signing, SLSA, VirusTotal, performance benchmarks, or full installer behavior.
- Runtime guide references existing implemented commands and UI surfaces only, or labels future commands as future work.
- `git diff --check` passes.

### Verification

- `git diff --check`
- Manual claim audit against existing code/docs.
- Hermes adversarial docs review focused on overclaims, UUID-first UX, token safety, and stale/misleading runtime instructions.

## Workstream B - Runtime Apply MVP

### Objective

Turn Milestone 30's dry-run runtime install plan into a safe local install workflow, starting with Hermes only.

### Scope

- CLI runtime subcommands.
- Local config writer for Hermes MCP config only.
- Plan file schema/version validation, target matching, staleness detection, dry-run diff, explicit apply, receipt, rollback, and validation wrapper.
- Unit tests with temporary HOME/config roots.
- Docs updates.

### Commands

Initial commands:

```bash
sourcebrief runtime detect
sourcebrief runtime apply --plan plan.json --target hermes --dry-run
sourcebrief runtime apply --plan plan.json --target hermes --yes
sourcebrief runtime rollback --receipt receipt.json
sourcebrief runtime validate --plan plan.json
```

Later targets:

```bash
sourcebrief runtime apply --target claude ...
sourcebrief runtime apply --target codex ...
sourcebrief runtime uninstall --receipt ...
```

### Requirements

- `detect` reports local runtime candidates and config paths without writing files.
- `apply` validates the plan schema/version, target, plan digest, and expected SourceBrief project before computing any file write.
- `apply` rejects malformed, unsupported, stale, hand-edited, or target-mismatched plans before touching runtime config.
- `apply --dry-run` prints exact planned file operations and writes nothing.
- `apply --yes` is required for any write; no default mutation.
- Apply writes only a SourceBrief-managed MCP server entry or managed block.
- Apply uses atomic temp-file writes and creates backups or preimage hashes before mutation.
- Apply writes a receipt containing:
  - schema version;
  - plan digest;
  - target runtime;
  - server name;
  - files touched;
  - pre-change and post-change hashes;
  - whether each file was created;
  - token env var names, never token values;
  - validation status;
  - rollback command.
- Rollback restores or removes only SourceBrief-owned changes.
- Rollback refuses if the current file hash differs from the expected post-change hash unless `--force` is provided.
- No plaintext token appears in config, receipt, logs, or tests.
- Validation uses existing runtime validator behavior where possible and must report real pass/fail/not-run.

### Acceptance criteria

- Temp HOME tests prove dry-run writes nothing.
- Malformed, unsupported-version, stale, hand-edited, and target-mismatched plan fixtures fail closed before any file write.
- Temp HOME tests prove apply writes only expected managed files.
- Rollback restores previous content and removes created managed-only files.
- Modified-file rollback protection fails closed.
- Tests assert no `cs_`, `Bearer <token>`, private key marker, or local repo path leaks into config/receipt.
- Hermes config output is parseable by the expected config parser/format.

### Verification

- `.venv/bin/python -m pytest tests/unit/test_cli.py -q`
- `.venv/bin/ruff check apps packages tests scripts`
- `.venv/bin/mypy apps packages scripts --ignore-missing-imports --follow-imports=silent`
- Hermes adversarial security review for local file mutation, rollback, and token handling.

## Workstream C - Architecture and Graph Overview

### Objective

Give agents a compact, cited project architecture view before they start ad hoc searching.

### Scope

- New MCP/API read model, likely `sourcebrief.get_architecture` or `sourcebrief.graph_overview`.
- Backed by published resource graph versions and graph merge versions, not unreviewed raw rows.
- Optional CLI wrapper.

### Requirements

- Return project/resource/pack freshness.
- Return graph keys/versions/hashes.
- Return node and edge type counts.
- Return top resources, packages/directories, entry-like files, hotspots, and unresolved reconcile candidates.
- Include citation/drilldown handles for sections/files where possible.
- Respect workspace/project/resource authorization and token allowlists.
- Bound result size and traversal depth.

### Acceptance criteria

- A token scoped to one resource cannot see hidden resource names, counts, paths, graph nodes, or architecture hints from another resource.
- Output includes enough graph schema hints for an agent to choose next tools without UUID-first exploration.
- Stale/missing graph versions are clearly reported, not silently treated as empty architecture.

### Verification

- Unit tests for response shaping.
- Integration tests with two resources and scoped token denial.
- MCP `tools/list` parity tests if a new MCP tool is added.

## Workstream D - Reviewable Cross-Resource Service-Link Candidates

### Objective

Adapt codebase-memory-mcp's `CROSS_*` idea into SourceBrief's reviewable graph merge model.

### Scope

- Candidate generation for selected published graph versions within the same workspace/project.
- Candidate types:
  - HTTP route/client match;
  - async topic/channel match;
  - gRPC service/method match;
  - GraphQL operation match;
  - tRPC route match.
- Review status and later materialization into merge graph versions.

### Requirements

- Candidates are not published graph facts until accepted through a review flow.
- Every candidate stores:
  - left/right resource id;
  - left/right source snapshot id;
  - graph key/version;
  - source node/edge ids or stable handles;
  - evidence locators;
  - matcher type and version;
  - confidence and rationale;
  - review status.
- Candidate generation is explicitly project-scoped and cannot cross workspace/project boundaries.
- Candidate counts are capped and paginated.

### Acceptance criteria

- Candidate generation over two demo resources produces deterministic candidate payloads.
- Out-of-scope resource candidates are not visible to scoped tokens.
- Accepted candidates can be represented in a new merge graph version with provenance.
- Rejected candidates remain auditable and do not reappear as published facts without a newer matcher version or changed inputs.

### Status

Implemented in Workstream D:

- Resource graph indexing derives reviewable `service_endpoint` nodes for HTTP route/client, async topic/channel, gRPC method, GraphQL operation, and tRPC route patterns.
- Graph merge candidate generation emits `service_*` reconcile candidates with matcher version, rationale, source metadata, stable handles, and evidence locators while keeping them unpublished until review.
- Accepted candidates materialize as reviewed merge edges only when a merge graph version is published; rejected candidate reviews carry forward for unchanged inputs.

### Verification

- Unit fixtures for route/topic matching.
- Integration tests over published graph versions.
- Adversarial auth/resource-scope review.

## Workstream E - Index/Search Performance POC

### Objective

Improve code search and graph extraction precision without weakening SourceBrief's governance model.

### Scope

- Identifier-aware lexical search for code and symbols.
- Tree-sitter pilot for Python and TypeScript/JavaScript.
- Parse-once extraction cache keyed by content hash and parser policy version.
- Staged/bulk graph insertion POC.
- Metrics collection.

### Requirements

- Do not claim full LSP parity or broad language coverage.
- Extract symbol ranges, imports, function/class definitions, route-like declarations where deterministic.
- Split camelCase, snake_case, kebab-case, dotted paths, and file paths into searchable code tokens.
- Add score-component diagnostics for code search results.
- Preserve citations: path, line range, content hash, source snapshot id.
- Keep remote code search bounded and permission-scoped.

### Acceptance criteria

- SourceBrief repo full-index benchmark is recorded before and after the POC.
- One-file refresh demonstrates high reuse of unchanged files/chunks/symbols/embeddings.
- `search_code` p95 improves on SourceBrief repo fixture without widening resource leakage.
- Symbol lookup accuracy improves on representative Python/TS fixtures.

### Status

Implemented as a bounded POC in Workstream E:

- Remote `sourcebrief.search_code` now uses identifier-aware scoring over bounded current-snapshot files, splitting camelCase, snake_case, kebab-case, dotted paths, and file paths.
- `sourcebrief.search_code` returns per-hit `score_components` (`lexical`, `exact`, `identifier`, `path`) and preserves resource id, snapshot id, indexed commit, path, line range, and snippet citations.
- Symbol extraction now includes deterministic Python and TypeScript/JavaScript imports in addition to class/function definitions.
- REST code symbol search uses the same identifier token fallback while keeping project/resource scoping and current-snapshot joins.
- No tree-sitter dependency or parse cache landed in this POC; those remain follow-up work after measuring value from the lexical/import changes.

### Verification

- Unit fixtures cover identifier tokenization/scoring and Python/TypeScript import extraction.
- Integration tests cover REST code symbol search for imports, MCP `search_code` score components, and empty-resource allowlist denial.
- Measured local validation for this POC: `tests/unit/test_code_intel.py tests/unit/test_remote_code.py` -> 30 passed in 0.02s; targeted real Postgres/Redis integration for `test_remote_code_http_and_mcp_flow`, `test_empty_resource_allowlist_cannot_expand_to_project_scope`, and `test_git_ingestion_extracts_and_searches_code_symbols` -> 3 passed in 0.94s.
- Full SourceBrief repo benchmark, one-file refresh reuse metrics, tree-sitter pilot, and staged graph insertion remain out of scope for this incremental PR.

## Workstream F - Trust and Supply-Chain Packaging

### Objective

Prepare SourceBrief for easy installers and packages without overclaiming security.

### Requirements

- Any installer must support `--plan`, `--dry-run`, and explicit `--apply`.
- Official downloads must fail closed on checksum/signature/provenance verification if the docs claim verification.
- Package-manager wrappers must not silently mutate agent configs during install.
- Release workflows must not run mutable `latest` downloads without pinned version and verification.
- Security scripts must fail on missing coverage, zero files checked, or stale checksum manifests.
- Local cache/context artifacts must be documented as sensitive.

### Acceptance criteria

- Install docs distinguish stack install from runtime integration install.
- Docs state what is local, what contacts network endpoints, and how to disable optional update/download behavior.
- No SLSA/reproducible/static/VirusTotal claims are present unless backed by CI and installer enforcement.

## Execution order

1. Workstream A - README and Runtime Productization.
2. Workstream B - Runtime Apply MVP for Hermes.
3. Workstream C - Architecture and Graph Overview.
4. Workstream D - Reviewable Cross-Resource Service-Link Candidates.
5. Workstream E - Index/Search Performance POC.
6. Workstream F - Trust and Supply-Chain Packaging, in parallel with any installer/package release work.

## Branch / PR slicing

Recommended PR sequence:

1. `docs: add codebase-memory reference roadmap and runtime positioning`
2. `feat: add Hermes runtime apply and rollback`
3. `feat: add project architecture graph overview`
4. `feat: add reviewable cross-resource service-link candidates`
5. `perf: prototype identifier-aware code search and staged graph indexing`
6. `chore: harden installer and supply-chain verification docs/gates`

Each PR should update this spec's status notes or the relevant user-facing docs before merge.

## Open questions

- Which local Hermes config path should the first runtime apply writer target by default: active profile only, explicit `--profile`, or a passed config path?
- Should runtime apply support Claude/Codex in the same PR as Hermes, or wait for a separate target-specific review?
- Should architecture overview be a new MCP tool or a profile of `graph_query` / `get_context_pack`?
- Should cross-resource candidates reuse `graph_merge_reconcile_candidates` or introduce a separate table with service-link-specific fields?
- Which parser dependency is acceptable for the tree-sitter pilot in Python packaging and Docker images?

## Status

- Spec created from 10 reviewer viewpoints after codebase-memory-mcp analysis.
- Claude Code reviewers were attempted but blocked by `401 Invalid authentication credentials`; five Hermes fallback reviewers supplied the corresponding lenses.
- Workstream A completed in PR #58.
- Workstream B completed in PR #59.
- Workstream C in progress on `feat/architecture-overview`: adds `sourcebrief.get_architecture` / compact graph overview with scoped resource filtering.
- No remaining implementation workstream is complete until its acceptance criteria and verification gates pass.
