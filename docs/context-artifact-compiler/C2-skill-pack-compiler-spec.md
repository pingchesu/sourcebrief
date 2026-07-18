# C2 — Skill Pack Compiler Implementation Spec

Status: Deterministic baseline implemented; AI knowledge-compilation scope superseded by the [Core Product Reset](../CORE_PRODUCT_RESET.md)<br/>
Depends on: B0 Resource Map artifacts, B1 Context Pack versions, C Skill Export review/download lifecycle, F expanded MCP tools
References considered: `book-to-skill`, `rag-skill`, `garden-skills`, `Skill-Anything`

> [!WARNING]
> C2 produced a safer, richer **deterministic runtime adapter package**. It did not implement LLM-backed semantic compilation: current manifests record `llm_provider_used=false`. In this historical spec, “Compile Knowledge Pack” and “source-aware Skill Pack Compiler” mean deterministic organization of approved metadata, citations, references, and fixed playbooks—not AI understanding. The new `ai-compiled` contract is tracked by [#341](https://github.com/pingchesu/sourcebrief/issues/341) and [#345](https://github.com/pingchesu/sourcebrief/issues/345).


## 1. Problem

Current SourceBrief Skill Export is a safe but shallow runtime adapter. It produces only:

```text
SKILL.md
README.md
manifest.json
```

The generated `SKILL.md` mostly tells an agent to call SourceBrief with a pinned Context Pack. That is useful as an audit-safe pointer, but it is not a competitive product feature. A user can reasonably say that a generic LLM could generate a more useful skill because the export lacks source-specific structure, progressive disclosure, task playbooks, examples, and a visible package model.

C2 improves that baseline by making SourceBrief a **deterministic source-aware adapter compiler**, not merely a Context Pack pointer exporter. It does not satisfy the product-reset definition of an AI Knowledge Compiler.

## 2. Product goal

A user should be able to ingest a Git repo, folder bundle, or document collection; publish a Context Pack; compile an installable Skill Pack; download it; and have an agent use that pack to answer source-specific questions with better discipline than generic LLM/RAG.

The generated pack must help the agent know:

- what sources are covered,
- where to start reading,
- what task workflow to follow,
- how to drill down through SourceBrief MCP/API evidence,
- what cannot be answered safely,
- whether freshness/coverage blocks the answer,
- how to cite evidence.

## 3. Non-goals for this PR

- No direct code copy from the reference repos.
- No required paid LLM/provider call in C2 PR1.
- No embedding full source corpus, retrieved snippets, private repository contents, or raw chunks in the package.
- No auto-install into Hermes/Claude/Codex profiles.
- No production mutation, GitHub write operation, or external repo automation from generated skills.
- No replacement of SourceBrief as source of truth. Skill Pack is an export artifact; SourceBrief remains canonical for evidence, freshness, ACL, and review state.

## 4. Lifecycle decision

C2 separates value generation from export packaging.

```text
Import / Index
  -> deterministic maps, sections, manifests, citations
Compile Knowledge Pack
  -> structured, reviewable Skill Pack package files
Publish / Approve
  -> fixed reviewed package state
Export / Download
  -> runtime-specific installable package
Runtime use
  -> agent follows Skill Pack guidance and uses SourceBrief evidence tools
```

### 4.1 Import / Index

Triggered by adding or refreshing a Git repo, folder bundle, file, or document collection.

Existing SourceBrief entities provide the deterministic foundation:

- `resources`
- `source_snapshots`
- `resource_manifests`
- `resource_manifest_files`
- `sections`
- `snapshot_sections`
- `context_artifacts` (`resource_map`)
- `context_artifact_citations`
- graph nodes/edges when available

C2 PR1 does not need a new import pipeline.

### 4.2 Compile Knowledge Pack

Triggered by existing Skill Export generation endpoint for PR1:

```http
POST /workspaces/{workspace_id}/projects/{project_id}/context-packs/{pack_key}/versions/{version}/skill-exports
```

PR1 may reuse the `skill_exports` table and approved-only download gate, but the generated `files_json` must become a full Skill Pack file set. Future PRs may split first-class `knowledge_packs` from `skill_exports` if product needs require a reviewable pack before runtime export.

### 4.3 Publish / Approve

Existing lifecycle remains:

```text
draft -> approved | rejected | invalidated | failed
```

Approval stays blocked unless validation and leak scan pass.

### 4.4 Export / Download

Export is packaging only. Download should return individual files through the existing approved-only endpoint in PR1. A later PR can add `.zip` download.

### 4.5 Runtime use

At runtime, agents read `SKILL.md`, then specific `references/*` and `task-playbooks/*`. The package must instruct agents to use SourceBrief MCP/API for evidence, not rely on package text as the full corpus.

## 5. Reference repo mapping to concrete SourceBrief features

### 5.1 `book-to-skill`

Observed value:

- Converts books/folders/sources into a skill folder, not a single pointer.
- Uses progressive disclosure: compact `SKILL.md` + on-demand files.
- Generates glossary, patterns, cheatsheet, chapter/section files.
- Supports update/fold-in mindset.
- Includes cost/dependency/validation thinking.

C2 features:

- Main `SKILL.md` contains compact operating instructions and an index of available reference files.
- `references/data-structure.md` and `references/resource-map.md` act as SourceBrief's on-demand chapter/resource index.
- `references/glossary.md`, `references/patterns.md`, and `references/pitfalls.md` are generated deterministically from available metadata/citations in PR1 and may be LLM-augmented later.
- `manifest.json` records generator version, pack hash, file hashes, resource/snapshot coverage, validation status, and future fold-in compatibility metadata.

Acceptance:

- Package contains more than a thin `SKILL.md`; at least 12 meaningful files are generated.
- `SKILL.md` tells the agent when to open each reference file.
- Manifest file hashes cover every generated file.

### 5.2 `rag-skill`

Observed value:

- Hierarchical `data_structure.md` drives retrieval before file reading.
- Agent reads indexes first, then drills into narrower files.
- PDF/Excel/large-source handling uses dedicated references before processing.
- Retrieval is iterative and avoids loading whole corpora.

C2 features:

- `references/data-structure.md` lists resources, source families, snapshots, artifact counts, citation counts, and likely starting points.
- `references/resource-map.md` summarizes approved Resource Map artifacts and their citation locators.
- `references/citation-policy.md` mandates SourceBrief `search`/`read_section` or `get_agent_context` before claims.
- Task playbooks instruct agents to start with data-structure/resource-map before search/read_section.

Acceptance:

- Generated package includes an explicit resource-map-first workflow.
- At least one smoke query requires citations and fails if no citations are returned.
- `SKILL.md` says not to load/read the entire source corpus.

### 5.3 `garden-skills`

Observed value:

- Production-ready skill package, not a loose markdown file.
- Uses `SKILL.md`, `manifest.json`, `references/`, `assets/`, `scripts/`, release zip, compatibility/install docs.
- Each skill states best-for, workflow, references, scripts, and concrete usage modes.

C2 features:

- Package layout mirrors production skill package conventions:

```text
SKILL.md
README.md
manifest.json
references/...
examples/...
scripts/verify-sourcebrief-runtime.sh
```

- `README.md` includes install steps, compatibility, SourceBrief runtime requirements, approval status, and failure modes.
- `manifest.json` includes full file inventory/checksums and package schema.
- `scripts/verify-sourcebrief-runtime.sh` is safe/read-only and verifies that required MCP/API configuration exists without embedding secrets.

Acceptance:

- Generated package has installable shape and self-documenting file inventory.
- Download is approved-only and leak-scanned across all package files.
- UI previews the package as a file tree instead of a flat three-file adapter.

### 5.4 `Skill-Anything`

Observed value:

- Any source -> structured pack -> optional skill export.
- Section-aware parsing and map-reduce for long sources.
- Coverage quotas prevent later sections from being dropped.
- Cache by source/prompt/model/version.
- Repo parser and skill lint/export loop.

C2 PR1 features:

- Deterministic package assembly from current Context Pack and artifact metadata.
- Coverage report identifies resources, artifacts, citations, and missing/weak areas.
- `examples/smoke-queries.md` creates source-specific smoke tasks based on available resources/artifacts.
- Validation requires the generated pack to contain resource-map-first instructions, citation policy, freshness guidance, and all required files.

Future features:

- Optional LLM/provider stage for source-specific glossary/pattern/playbook synthesis.
- Section-aware map-reduce with per-section quota and cache key:

```text
sha256(pack_hash + compiler_version + prompt_version + model + section_hashes)
```

- Claim schema:

```json
{
  "claim_text": "...",
  "claim_type": "summary | pattern | pitfall | glossary | playbook_step",
  "citation_ids": ["..."],
  "uncited_reason": null
}
```

Acceptance:

- C2 PR1 has deterministic value without paid LLM.
- Future LLM output cannot publish uncited claims unless artifact type explicitly allows an `uncited_reason`.

## 6. C2 package file set

PR1 must generate at least these files:

```text
SKILL.md
README.md
manifest.json
references/data-structure.md
references/resource-map.md
references/source-coverage.md
references/glossary.md
references/patterns.md
references/pitfalls.md
references/freshness.md
references/citation-policy.md
references/task-routes.md
references/task-playbooks/onboarding.md
references/task-playbooks/architecture-question.md
references/task-playbooks/debugging.md
references/task-playbooks/change-impact.md
examples/smoke-queries.md
scripts/verify-sourcebrief-runtime.sh
```

### 6.1 `SKILL.md`

Purpose: compact operating front door.

Must include:

- skill name/description/frontmatter,
- best-for / trigger conditions,
- pack key/version/hash,
- resource-map-first workflow,
- reference file index,
- task playbook routing,
- SourceBrief MCP/API evidence workflow,
- citation requirement,
- freshness/staleness blocking rules,
- mutation boundary,
- failure modes.

Must not include:

- source corpus,
- raw chunks/snippets,
- secret-bearing URIs,
- local backend paths,
- user-specific bearer/session tokens.

### 6.2 `references/data-structure.md`

Purpose: hierarchical navigation index.

Must include:

- pack identity,
- resource list by source family/name/type,
- snapshot/manifest IDs shortened or hashed for audit, not as primary user workflow,
- artifact/citation counts,
- top covered paths/headings where available,
- recommended starting points by resource.

### 6.3 `references/resource-map.md`

Purpose: generated evidence map.

Must include:

- each Resource Map artifact title/summary,
- artifact status/hash/revision,
- citation locator inventory by path/title/line range where available,
- SourceBrief MCP drilldown examples using pack selector and canonical locators.

### 6.4 `references/source-coverage.md`

Purpose: reviewable coverage report.

Must include:

- resource count,
- artifact count,
- citation count,
- per-resource coverage,
- warnings for resources with zero citations or missing approved Resource Map artifacts,
- package limitations.

### 6.5 `references/glossary.md`

PR1 deterministic version:

- Extract candidate terms from resource names, path stems, artifact titles, section titles, graph symbol labels when available.
- Mark as `candidate`, not authoritative definition, unless citation metadata supports more.
- Future LLM version may synthesize definitions only with citations.

### 6.6 `references/patterns.md`

PR1 deterministic version:

- Group reusable patterns by artifact type, path cluster, symbols, and source family.
- Include how to verify each pattern through SourceBrief evidence.
- Avoid uncited implementation claims.

### 6.7 `references/pitfalls.md`

Must include generic SourceBrief/runtime pitfalls plus source-specific review warnings:

- stale pack,
- insufficient citations,
- missing MCP tools,
- resource coverage gaps,
- rejected/failed artifacts,
- source names/metadata are untrusted data,
- production mutations require explicit approval.

### 6.8 `references/freshness.md`

Must include:

- pack publish status,
- pack version/hash,
- resource freshness signals if available,
- instructions for handling stale/invalidated packs.

### 6.9 `references/citation-policy.md`

Must include:

- claims require citations,
- acceptable citation forms,
- when to refuse or ask for reindex/pack update,
- exact SourceBrief MCP/API verification checklist.

### 6.10 `references/task-routes.md`

Must include deterministic source-specific route hints generated from indexed paths:

- docs/onboarding paths,
- runtime/implementation paths,
- tests/verification paths,
- CI/release/package paths,
- config/policy paths.

These are starting points only; agents must still resolve exact evidence via Resource Map citations and SourceBrief `read_section`.

### 6.11 Task playbooks

Each playbook must be concrete and source-aware.

- `onboarding.md`: answer "what is this repo/folder/project?" with resource map, entrypoints, important paths, caveats.
- `architecture-question.md`: trace components/data flow through maps, graph paths, symbols, and citations.
- `debugging.md`: locate likely files, read sections, check failure modes, cite evidence; no mutation without approval.
- `change-impact.md`: use resource map + graph paths + symbols to assess impacted resources/sections; cite exact evidence.

### 6.12 `examples/smoke-queries.md`

Must include at least 3 generated queries:

- onboarding query,
- architecture/resource-map query,
- debugging/change-impact query.

Each query must include expected behavior:

- must use SourceBrief evidence,
- must return citations,
- must identify insufficient evidence rather than hallucinating.

### 6.13 `scripts/verify-sourcebrief-runtime.sh`

Must be read-only and safe.

Allowed behavior:

- check env variables are present by name but never print values,
- print required MCP/API tool names,
- optionally curl a user-provided health endpoint if `SOURCEBRIEF_API_URL` is set.

Forbidden behavior:

- no token output,
- no package install,
- no source upload,
- no mutation,
- no hard-coded local IP/path/account.

## 7. Backend implementation plan

Primary file:

```text
apps/api/sourcebrief_api/skill_exports.py
```

### 7.1 Generator version

Update:

```python
GENERATOR_VERSION = "skill-export.v2"
```

If backward compatibility requires distinguishing current v1 vs v2, use helper-level schema version while preserving existing `export_type = "hermes_skill"`.

### 7.2 New internal data structure

Add a compiler context object:

```python
@dataclass(frozen=True)
class SkillPackContext:
    version: ContextPackVersion
    title: str
    summary: str | None
    resources: list[ResourceSummary]
    artifacts: list[ArtifactSummary]
    coverage: dict[str, Any]
    smoke_queries: list[dict[str, Any]]
```

PR1 can use dictionaries instead of new dataclasses if smaller, but the boundary must be explicit.

### 7.3 Data queries

Add helpers to collect:

- resource coverage rows from `ContextPackResourceCoverage` + `Resource`,
- pack artifacts from `ContextPackArtifact` + `ContextArtifact`,
- context artifact citations from `ContextArtifactCitation`,
- resource manifests/files when available,
- section titles/path samples from `SnapshotSection`/`Section` when cheap and bounded.

All queries must be pack-scoped by `context_pack_version_id`, `workspace_id`, and `project_id`.

### 7.4 Rendering functions

Replace single `_render_skill`/`_render_readme` only approach with per-file renderers:

```python
_render_skill(...)
_render_readme(...)
_render_data_structure(...)
_render_resource_map(...)
_render_source_coverage(...)
_render_glossary(...)
_render_patterns(...)
_render_pitfalls(...)
_render_freshness(...)
_render_citation_policy(...)
_render_task_playbook(kind, ...)
_render_smoke_queries(...)
_render_verify_script(...)
```

### 7.5 Manifest and hashing

`manifest.json` must include:

- schema version,
- package kind: `sourcebrief_skill_pack`,
- export type,
- generator version,
- pack key/version/hash/status,
- source coverage counts,
- reference inspirations with concrete implemented features,
- file inventory with path/kind/sha256/bytes,
- validation summary,
- smoke query count,
- approval metadata.

Package hash input must include all immutable generated files except `manifest.json` mutable approval fields. Existing manifest placeholder model can be extended.

### 7.6 Validation

Update `_validate_files` to require:

- all required files,
- `SKILL.md` mentions resource-map-first workflow,
- `SKILL.md` references `references/data-structure.md`, `references/resource-map.md`, and task playbooks,
- citation policy exists and mentions `sourcebrief.read_section` or `sourcebrief.get_agent_context`,
- at least 3 smoke queries,
- manifest file inventory covers all files.

### 7.7 Leak scan

Extend `_scan_files`:

- cap all generated files by path pattern,
- scan all files, not only three files,
- reject URL userinfo/query/fragment-like secrets,
- reject token patterns including `access_token`, `api_key`, `client_secret`, `secret-token`, `gh[pousr]_`, private key markers,
- continue source text marker scan across generated package.

### 7.8 API compatibility

No endpoint path change in PR1.

The response shape remains `SkillExportRead` with `files: SkillExportFile[]`. Frontend can render more files without API migration.

## 8. Frontend requirements

Primary file:

```text
apps/web/app/sources/page.tsx
```

PR1 UI updates:

- Rename visible panel copy from "runtime adapter" to "Skill Pack" where accurate.
- Show file tree grouped by `SKILL.md`, `references/`, `examples/`, `scripts/`.
- Show package value indicators:
  - file count,
  - reference files count,
  - smoke query count,
  - coverage resources/artifacts/citations,
  - validation/leak scan status.
- Show "Reference inspirations" as implemented feature mapping, not marketing copy:
  - book-to-skill: progressive disclosure files,
  - rag-skill: data_structure/resource-map-first retrieval,
  - garden-skills: manifest/checksums/scripts package shape,
  - Skill-Anything: deterministic section-aware coverage + future map-reduce boundary.
- Keep no UUID-first UX. IDs may appear only in compact audit/code fields, not primary workflow.

Future UI:

- dedicated Skill Packs page,
- zip download,
- smoke-query runner,
- coverage gap review queue.

## 9. Real E2E value validation

After implementation, the controller must validate with real repositories/folders, not mocks.

Minimum target:

```text
N = 3 different repos/folders
M = 3 independent subagents
```

Suggested repos/folders:

- SourceBrief itself,
- one small Python library/repo,
- one frontend/Node repo or documentation-heavy folder.

For each source:

1. Ingest/index with real SourceBrief services.
2. Compile/publish a Context Pack.
3. Generate Skill Pack export.
4. Approve and download generated package files.
5. Provide downloaded package to subagents.
6. Ask subagents to perform:
   - onboarding task,
   - architecture task,
   - debugging/change-impact task.
7. Compare against a baseline prompt that does not include the Skill Pack but may know the repo name/files.

Pass/fail rubric:

- PASS if Skill Pack-guided answers cite SourceBrief evidence, choose better starting points, state limitations/freshness, and avoid hallucinated claims.
- FAIL if the Skill Pack answer is no better than generic LLM, lacks citations, or fails to guide drilldown.
- BLOCK if package leaks source text beyond allowed metadata, secrets, local paths, or unsafe instructions.

Subagent prompts must be self-contained and must not reveal source corpus outside the package/evidence APIs.

## 10. Security and failure modes

### 10.1 Prompt injection through source metadata

Resource names, paths, branches, titles, URIs, artifact summaries, and source metadata are untrusted data. Generated files must treat them as quoted data, not executable instructions.

Rules:

- never copy source metadata into imperative instruction sections without neutral framing,
- markdown-escape control-sensitive fields,
- avoid frontmatter injection through `:` / `#` / newline values,
- use YAML-safe quoting/escaping for frontmatter.

### 10.2 Secret leakage

Reject or redact:

- URL userinfo,
- query/fragment credentials,
- bearer tokens,
- GitHub tokens,
- API keys,
- client secrets,
- private key blocks,
- local filesystem paths.

### 10.3 Source corpus leakage

Package may include metadata, citations, paths, titles, short labels, and locators. It must not include full source files, chunks, or long snippets.

### 10.4 Stale or invalidated pack

Skill Pack must instruct the agent to block production-sensitive answers if:

- pack invalidated,
- freshness warning present,
- SourceBrief returned mismatched pack key/version/hash,
- citations missing.

### 10.5 MCP unavailable

Skill Pack must provide REST fallback shape but no raw bearer token collection workflow.

### 10.6 Package size

PR1 caps:

- `SKILL.md`: 32 KB,
- `README.md`: 24 KB,
- `manifest.json`: 64 KB,
- each reference/playbook/example file: 48 KB,
- total package: 512 KB.

Adjust only with validation and real package evidence.

## 11. Verification gates

Required local gates:

```bash
git diff --check
.venv/bin/ruff check apps packages tests scripts
.venv/bin/mypy apps packages scripts --ignore-missing-imports --follow-imports=silent
SOURCEBRIEF_DEV_AUTH=true SOURCEBRIEF_RUN_REAL_INTEGRATION=1 SOURCEBRIEF_ALLOW_LOCAL_GIT=true make test-integration
npm --prefix apps/web run lint
npm --prefix apps/web run build
```

If full integration is too slow during inner loop, focused integration tests may run first, but final PR must include real-service evidence.

Required review gates:

- Hermes adversarial review with at least:
  - product/value lens,
  - security/leakage lens,
  - API/data model lens,
  - E2E/no-mock lens.
- Fix blocker/major issues and re-review.

## 12. PR1 scope for this branch

PR1 should implement a meaningful deterministic Skill Pack package, not just docs.

Must include:

- this spec,
- backend multi-file package generation,
- validation/leak scan updates,
- tests for required package files and leak scan,
- frontend preview improvements if feasible within one PR,
- real package generation evidence from at least one existing integration flow.

May defer:

- LLM/map-reduce synthesis,
- first-class `knowledge_packs` table,
- zip download endpoint,
- automated baseline-vs-skill eval dashboard,
- multi-repo value study across N=3/M=3 until after deterministic package compiles locally.

But before calling C2 complete, the N/M subagent value assessment must run.

## 13. Definition of done

C2 is not done until all are true:

- A published Context Pack generates an approved Skill Pack with the required file set.
- Package preview shows a useful file tree and coverage/value indicators.
- Package validation and leak scan run across every file.
- Generated package is installable/readable as a real skill package.
- At least three smoke queries are generated.
- Real-service integration test exercises package generation from real stored resources/artifacts.
- Subagent value assessment over real repos/folders demonstrates whether the package improves agent behavior; results are documented honestly.
- No blocker/major remains from Hermes adversarial review.
