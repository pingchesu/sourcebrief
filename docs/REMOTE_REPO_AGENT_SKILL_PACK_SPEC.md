# Remote Repo Agent Skill Pack Specification

Status: Draft v0.2 after adversarial review
Owner: SourceBrief platform
Related milestones: M16, M23, proposed M24-M26
Primary decision: package repo agents as remote SourceBrief capabilities plus thin runtime-specific local adapters.

Adversarial review result: first pass BLOCK. This version incorporates the required contract clarifications: Hermes raw skill installs are single-file installs, MCP configuration is a separate mandatory step, public skill packs must not advertise unavailable tools, remote code tools require exact schemas/security gates, and the drift auditor is read-only by default.

## 1. Problem

SourceBrief currently turns repositories into indexed project resources and can generate preliminary agent files. That is enough for a local demo, but not enough for real agent runtime use.

In the real deployment shape:

- Hermes, Codex, or Claude may run on a different machine from SourceBrief.
- The source repository may live in GitHub, a worker checkout, a bundle, or object storage, not on the agent runtime filesystem.
- A path shown by SourceBrief may be provenance, not a path the runtime can `grep`, `cat`, or edit.
- Local skills/instructions can teach an agent how to behave, but they cannot carry a large repo index, symbol graph, embeddings, eval history, or authorization policy.

The product gap is that a user wants to install a repo agent into Hermes/Codex/Claude as a first-class capability, while the data and code intelligence remain remotely hosted by SourceBrief.

## 2. Goal

SourceBrief should package each repo/project agent as an installable **Remote Repo Agent Skill Pack**.

The skill pack gives a local runtime a small operating manual and connection contract. The actual code intelligence remains in SourceBrief and is accessed through remote MCP/HTTP tools.

One sentence:

> SourceBrief packages a repository or project into an installable remote repo agent: the local runtime installs a small Skill Pack from GitHub, and uses SourceBrief MCP tools for indexed context, code search, grep, file reads, symbol lookup, eval-backed operating guidance, and optional patch generation.

## 3. Non-goals

- Do not copy full repository source code into Hermes/Codex/Claude skills.
- Do not copy vector indexes, embeddings, symbol graphs, or eval histories into the skill package.
- Do not expose backend worker checkout paths as runtime-accessible paths.
- Do not require Milvus, Qdrant, Neo4j, or a new mandatory storage service.
- Do not make per-repo MCP servers mandatory; keep the central SourceBrief MCP server as the default.
- Do not enable production mutation, remote writes, test execution, PR creation, or deployment by default.
- Do not silently mutate the user's active Hermes profile or Claude/Codex config from the web UI.

## 4. Core model

A repo agent consists of three separately versioned surfaces.

### 4.1 Agent Card

The Agent Card is the human and platform-facing description of the repo agent.

It answers:

- What repositories/resources does this agent cover?
- What commit/snapshot is indexed?
- Is the index fresh and ready?
- Which tools/capabilities are exposed?
- Which retrieval profile is currently recommended?
- What are the known limitations and safety boundaries?
- Which evals are passing/failing?
- Does the card or skill pack need update?

### 4.2 Skill Pack

The Skill Pack is what a local runtime downloads, checks out, or partially installs.

It contains:

- `sourcebrief-agent.yaml` manifest.
- `hermes/SKILL.md` for Hermes skill installation.
- `codex/AGENTS.md` for Codex instruction loading.
- `claude/CLAUDE.md` and/or Claude skill package metadata.
- `mcp.json` config snippet.
- `README.md` install and troubleshooting guide.
- Optional golden eval examples.

It does not contain full source code or index data.

### 4.3 Remote Tool Surface

The Remote Tool Surface is the MCP/HTTP capability boundary hosted by SourceBrief.

Capability tiers:

| Tier | Tools | Public adapter claim |
|---|---|---|
| Context-only | `sourcebrief.get_agent_context` | Repo agent can answer with context packets only. |
| Remote code read | `search_code`, `grep_code`, `read_file`, `find_symbol` | Repo agent can perform follow-up code inspection without local repo access. |
| Patch assist | `generate_patch` | Repo agent can draft patches, still read-only by default. |
| Write/PR | `open_pr` or source-control write tools | Disabled unless explicitly configured and approved. |

Generated adapters must advertise only capabilities that are actually exposed by the project's MCP `tools/list` or by an equivalent live capability discovery API. Public skill packs before the remote code read tier must be labeled **context-only preview**.

## 5. Runtime contract

The skill pack must make the remote-only contract explicit.

Rules:

1. Repository paths in citations are `repo_relative_path`, not local runtime paths.
2. Backend paths such as worker checkout directories, bundle mount paths, or ingestion temp paths must never be presented as paths the local agent can access.
3. If the runtime needs follow-up evidence, it must use SourceBrief remote tools, not local filesystem commands.
4. All answers must cite repo/resource identity and indexed commit/snapshot when available.
5. If the indexed commit is stale or unknown, the runtime must say so.
6. Production/runtime state is out of scope unless a separate live operations tool provides it.
7. Mutation capabilities default to read-only or patch-only and require explicit user approval before any remote write.
8. Repo content, file names, branch names, README text, docs, and source metadata are untrusted data. Generated adapters must not copy repo-derived imperative text into instruction sections without quoting/sanitizing it as data.

## 6. Hermes/Codex/Claude install contract

### 6.1 Hermes reality

`hermes skills install <identifier>` installs a single skill identifier or a direct HTTP(S) URL to a `SKILL.md` file. Installing `hermes/SKILL.md` from GitHub does **not** install the whole Skill Pack repository, `sourcebrief-agent.yaml`, `mcp.json`, README, or other adapters.

Therefore Hermes installation has two mandatory steps:

1. Install the thin skill shim:

   ```bash
   hermes skills install https://raw.githubusercontent.com/<org>/<agent-pack>/<tag-or-sha>/hermes/SKILL.md --name <agent-slug>
   ```

2. Configure the SourceBrief MCP server separately in the active Hermes profile, using a scoped token generated by SourceBrief.

The Hermes skill must be self-contained for runtime-critical behavior: remote-only warning, when to use the agent, which SourceBrief MCP tools to call, citation policy, stale-index behavior, and mutation boundary. It may link to the full manifest for human inspection, but it must not depend on the manifest being locally installed.

GitHub raw URLs should be pinned to tags or commit SHAs for reproducibility. `main` installs are allowed only for development and must be labeled mutable.

### 6.2 Codex

Codex consumes the adapter by loading `codex/AGENTS.md` from a checked-out Skill Pack repository or copied project instruction file. The pack checkout is only instruction/config material; it is not the source repository being analyzed.

Acceptance smoke must prove:

- Codex is run in a directory with only the Skill Pack, not the target source repo.
- The instructions tell Codex to use SourceBrief remote tools.
- A follow-up code inspection succeeds through SourceBrief once remote code tools exist.

### 6.3 Claude

For alpha, Claude support means `claude/CLAUDE.md` documentation/instruction mode unless the project explicitly implements Claude's skill bundle format later. The spec must not claim native Claude skill package support until the exact layout and install command are implemented.

Acceptance smoke must prove:

- Claude Code can be pointed at the `CLAUDE.md` instruction file or a checked-out Skill Pack.
- The MCP/tool configuration is separate and documented.
- The adapter preserves the same remote-only and mutation boundaries as Hermes/Codex.

### 6.4 Runtime compatibility table

| Runtime | Install mechanism | Config mechanism | Adapter file | Acceptance command |
|---|---|---|---|---|
| Hermes | `hermes skills install <raw SKILL.md URL>` | Separate Hermes MCP config/reload | `hermes/SKILL.md` | `hermes skills inspect`, temp-profile install, MCP tool call |
| Codex | Checkout/copy Skill Pack instructions | Codex MCP/tool config as supported by environment | `codex/AGENTS.md` | Run Codex in pack-only dir, verify remote tool workflow |
| Claude | `CLAUDE.md` instruction mode for alpha | Claude MCP/tool config as supported by environment | `claude/CLAUDE.md` | Run Claude Code with pack instructions, verify remote tool workflow |

## 7. Manifest schema v1

`sourcebrief-agent.yaml` is the canonical portable manifest for generated adapters.

The implementation must provide a machine-validated JSON Schema or equivalent Pydantic model. The schema must define required fields, defaults, enum values, version negotiation, and backward compatibility behavior.

Required top-level fields:

| Field | Type | Required | Notes |
|---|---|---|---|
| `kind` | string | yes | Must be `sourcebrief.repo-agent`. |
| `version` | integer | yes | Starts at `1`. Unknown major versions are rejected. |
| `identity` | object | yes | Name, slug, workspace/project IDs, optional card URL. |
| `sourcebrief` | object | yes | API/MCP endpoints and auth placeholder metadata. |
| `runtime_access` | object | yes | Must include mode and local access booleans. |
| `capabilities` | object | yes | Required/optional capability names actually available. |
| `sources` | array | yes | Authorized resources only. |
| `retrieval_profiles` | object | no | Defaults to `default` profile when omitted. |
| `mutation_policy` | object | yes | Defaults to read-only. |
| `citation_policy` | object | yes | Path/commit/resource citation requirements. |
| `freshness` | object | yes | Generated time and stale/expiry semantics. |

Example:

```yaml
kind: sourcebrief.repo-agent
version: 1
identity:
  name: AngiKnowledge Repo Agent
  slug: angiknowledge-repo-agent
  workspace_id: ws_xxx
  project_id: prj_xxx
  agent_card_url: https://sourcebrief.example.com/workspaces/ws_xxx/projects/prj_xxx/agents/card
sourcebrief:
  api_base_url: https://sourcebrief.example.com
  mcp_endpoint: https://sourcebrief.example.com/mcp/ws_xxx/prj_xxx
  agent_context_endpoint: https://sourcebrief.example.com/workspaces/ws_xxx/projects/prj_xxx/agent-context
  auth:
    type: bearer
    token_env: SOURCEBRIEF_TOKEN
runtime_access:
  mode: remote_only
  local_repo_required: false
  local_grep_allowed: false
capabilities:
  required:
    - get_agent_context
  optional:
    - search_code
    - grep_code
    - read_file
    - find_symbol
sources:
  - resource_id: res_xxx
    name: AngiZero
    type: git
    source_uri: https://github.com/angible/AngiZero
    default_branch: main
    indexed_commit: abc123
    current_snapshot_id: snap_xxx
    status: ready
retrieval_profiles:
  default: hybrid_rerank
mutation_policy:
  default: read_only
  patch_generation: disabled
  remote_write: disabled
citation_policy:
  path_format: repo_relative
  require_indexed_commit: true
  include_resource_id: true
freshness:
  generated_at: "2026-06-16T00:00:00Z"
  expires_after: P7D
  stale_after: P14D
```

## 8. Skill adapter requirements

### 8.1 Hermes adapter

`hermes/SKILL.md` is a thin skill shim. It must include:

- YAML frontmatter with `name` and `description`.
- Trigger conditions for the repo/project/domain.
- Remote-only warning.
- Mandatory separate MCP configuration note.
- Live capability list at generation time.
- Step-by-step workflow.
- Citation requirements.
- Staleness handling.
- Mutation boundary.
- Failure modes when the MCP endpoint is unavailable.

It must not include:

- Backend local paths.
- Full source code.
- Secrets or bearer tokens.
- Instructions to `rg`, `grep`, `cat`, or edit local files unless the user explicitly provides a separate local checkout path for the current task.

### 8.2 Codex adapter

`codex/AGENTS.md` must express the same contract in Codex-friendly form:

- Use SourceBrief remote tools for repo context.
- Do not assume repo files are in the current working directory.
- Prefer remote `grep_code`/`read_file` follow-ups when those tools are available.
- Cite repo-relative paths and indexed commits.
- Generate patches before proposing writes.

### 8.3 Claude adapter

`claude/CLAUDE.md` must express the same contract:

- The repo agent is remote.
- Use MCP tools before making repo claims.
- Treat indexed code as static evidence, not live production truth.
- Ask for approval before mutation.

### 8.4 Shared generator invariant

All runtime adapters must be generated from the same manifest and must preserve the same safety boundaries. Adapter parity tests must compare key clauses across Hermes, Codex, and Claude outputs.

## 9. GitHub distribution model

SourceBrief should support exporting or publishing a Skill Pack to GitHub.

Recommended repository layout:

```text
<agent-pack>/
  README.md
  sourcebrief-agent.yaml
  mcp.json
  hermes/
    SKILL.md
  codex/
    AGENTS.md
  claude/
    CLAUDE.md
  evals/
    golden-questions.yaml
  CHANGELOG.md
```

Publishing modes:

1. Download zip from SourceBrief UI.
2. Copy generated files manually.
3. Open a PR to a configured GitHub repository.
4. Later: publish to a registry compatible with `hermes skills install` discovery.

Security rules:

- Never commit plaintext bearer tokens.
- Use env var placeholders in `mcp.json` and docs.
- Generated install docs must instruct the user to create a scoped token.
- GitHub PR publishing must require explicit user action and show the diff.
- Generated files must pass leak scans for backend local paths, plaintext tokens, private source URIs outside the caller's authorization, and obvious secrets captured from repo metadata.

## 10. Remote tool contracts

Remote tools make repo agents usable when Hermes and SourceBrief run on different machines.

All tools must share these rules:

- Authorization is checked before existence disclosure.
- Token scopes are least-privilege and resource-scoped when requested.
- Inputs are validated by schema.
- Outputs have caps for result count, snippet chars, total bytes, and latency.
- Errors use deterministic codes such as `unauthorized`, `not_found`, `invalid_path`, `invalid_regex`, `too_many_results`, `timeout`, `binary_unsupported`, and `capability_unavailable`.
- Tool failures use this envelope and must not leak unauthorized resource existence:

  ```json
  {
    "error": {
      "code": "invalid_path",
      "message": "Path must be repo-relative and inside the indexed snapshot.",
      "retryable": false,
      "details": {
        "field": "path"
      }
    }
  }
  ```

- `unauthorized` and hidden-resource `not_found` responses must be indistinguishable to callers without access.
- Audit events record privacy-safe metadata: workspace, project, resource IDs, tool name, status, result count, latency, denied reason; not full query text by default when sensitive mode is enabled.

Required token scopes:

| Tool | Minimum scope |
|---|---|
| `get_agent_context` | `project:query`; optional symbols require `code:read` |
| `search_code` | `project:query` + `code:read` |
| `grep_code` | `project:query` + `code:read` |
| `read_file` | `resource:read` + `code:read` |
| `find_symbol` | `project:query` + `code:read` |
| `generate_patch` | `project:query` + `code:read` + `patch:generate` |
| `open_pr` | `pr:write` plus explicit approval |

### 10.1 `get_agent_context`

Existing tool. Returns selected context packet with citations, included/omitted evidence, diagnostics, and scope metadata. It returns code symbols only when the caller has `code:read`; context-only tokens that request symbols receive an empty `symbols` list plus `coverage_warnings` / `retrieval_metadata.code_symbols_omitted_reason`.

### 10.2 `search_code`

Request:

```json
{
  "query": "natural language or symbol-like query",
  "resource_ids": ["..."],
  "profile": "code_debug",
  "top_k": 10,
  "cursor": null
}
```

Response:

```json
{
  "results": [
    {
      "resource_id": "...",
      "snapshot_id": "...",
      "indexed_commit": "abc123",
      "path": "apps/api/main.py",
      "line_start": 10,
      "line_end": 40,
      "snippet": "...",
      "score": 0.82,
      "score_components": {"lexical": 0.3, "vector": 0.4, "rerank": 0.8}
    }
  ],
  "next_cursor": null
}
```

### 10.3 `grep_code`

Request:

```json
{
  "pattern": "exact string or safe regex",
  "resource_ids": ["..."],
  "path_glob": "*.py",
  "max_matches": 50,
  "cursor": null
}
```

Rules:

- Must run against indexed snapshots or controlled sanitized artifact storage, not arbitrary server filesystem paths.
- Must bound regex complexity, result count, timeout, and snippet length.
- Must return no backend local path.

Response:

```json
{
  "matches": [
    {
      "resource_id": "...",
      "snapshot_id": "...",
      "indexed_commit": "abc123",
      "path": "apps/api/main.py",
      "line_start": 42,
      "line_end": 44,
      "line_text": "def target_symbol(...):",
      "before": ["..."],
      "after": ["..."]
    }
  ],
  "next_cursor": null,
  "truncated": false
}
```

Validation/error mapping:

| Condition | Error code |
|---|---|
| Pattern exceeds length/complexity budget | `invalid_regex` |
| Search exceeds timeout | `timeout` |
| Match cap exceeded before stable page boundary | `too_many_results` |
| Resource hidden or outside allowlist | `not_found` |

### 10.4 `read_file`

Request:

```json
{
  "resource_id": "...",
  "path": "apps/api/main.py",
  "start_line": 120,
  "end_line": 180
}
```

Rules:

- Path is repo-relative and resolved within the indexed snapshot.
- Must reject absolute paths, `..`, NUL bytes, symlinks outside snapshot, and backend temp paths.
- Must include indexed commit/snapshot metadata in the response.
- Phase 3 requires a controlled full-file snapshot artifact or equivalent sanitized source blob store. Chunk-only read is insufficient for `read_file` because line ranges may cross chunk boundaries.
- Binary files return `binary_unsupported` unless a later explicit binary-safe mode is implemented.

Response:

```json
{
  "resource_id": "...",
  "snapshot_id": "...",
  "indexed_commit": "abc123",
  "path": "apps/api/main.py",
  "start_line": 120,
  "end_line": 180,
  "total_lines": 420,
  "content": "120|...\n121|...",
  "truncated": false
}
```

Validation/error mapping:

| Condition | Error code |
|---|---|
| Absolute path, traversal, NUL byte, symlink escape | `invalid_path` |
| Path not present in authorized snapshot | `not_found` |
| Requested line range exceeds cap | `too_many_results` |
| Binary file without binary-safe mode | `binary_unsupported` |

### 10.5 `find_symbol`

Request:

```json
{
  "name": "SomeClass",
  "kind": "class",
  "resource_ids": ["..."],
  "top_k": 20
}
```

Returns symbol definitions and references when available.

Response:

```json
{
  "symbols": [
    {
      "resource_id": "...",
      "snapshot_id": "...",
      "indexed_commit": "abc123",
      "path": "apps/api/main.py",
      "name": "SomeClass",
      "kind": "class",
      "language": "python",
      "line_start": 12,
      "line_end": 88,
      "signature": "class SomeClass(...)",
      "content_hash": "sha256:...",
      "score": 0.91
    }
  ],
  "next_cursor": null
}
```

Validation/error mapping:

| Condition | Error code |
|---|---|
| Symbol index unavailable for resource | `capability_unavailable` |
| Invalid kind/language filter | `invalid_request` |
| Resource hidden or outside allowlist | `not_found` |

### 10.6 Future mutation tools

`generate_patch` and `open_pr` must not be exposed by MCP `tools/list`, advertised in public adapters, or marked as available in `sourcebrief-agent.yaml` until a separate contract defines their request/response schemas, approval model, branch freshness checks, audit events, and rollback behavior. Phase 6 may add that contract; before Phase 6, these names are roadmap placeholders only.

## 11. Agent Card Drift Auditor

The platform should run a scheduled read-only auditor for each agent card and skill pack.

Goal:

> Periodically summarize whether each agent card, skill pack, retrieval profile, and eval set needs adjustment.

Inputs:

- resource freshness and index run status;
- git branch/commit drift when source credentials allow read-only checks;
- eval history trends;
- failed/no-citation query traces;
- usage analytics by tool and query class;
- retrieval diagnostics;
- adapter generation diff against current manifest;
- stale or missing capabilities;
- user feedback when available.

Status thresholds must be explicit and configurable. Initial defaults:

| Status | Default trigger examples |
|---|---|
| `healthy` | Latest successful index age <= 7 days, latest eval pass rate >= 90%, remote tool error rate < 2% over 24h, no unacknowledged high findings. |
| `attention` | Generated skill pack digest differs from current manifest; eval pass rate drops 5-15 percentage points from 7-day baseline; >= 3 similar failed/no-citation queries in 7 days; new optional capability available but adapter not updated. |
| `stale` | Manifest older than 14 days; indexed branch is behind source by >= 25 commits or >= 7 days when read-only git checks are available; resource review status is `needs_update`/`stale`. |
| `degraded` | Eval pass rate < 80% or drops >= 15 percentage points from 7-day baseline; required remote tool error rate >= 5% over 24h; p95 `get_agent_context` latency doubles from 7-day baseline. |
| `blocked` | Latest index failed; required tool unavailable; token revoked/expired; manifest schema invalid; no authorized sources remain. |

Default cadence and retry policy:

- Run auditor daily at most for each active agent card; default Slack/webhook summary is weekly.
- Use one idempotency key per `(agent_id, period_start, period_end, manifest_digest)`.
- Retry transient failures up to 3 times with exponential backoff; mark `blocked` only after retries or deterministic failure.
- Suppress identical acknowledged findings for 14 days unless severity increases.

Scheduler requirements:

- Idempotent by `(agent_id, period_start, period_end, manifest_digest)`.
- Backoff and retry on transient API/GitHub/provider failures.
- Suppression/ack controls for repeated noisy findings.
- Cost caps for LLM summaries, eval reruns, GitHub calls, embeddings, and remote tool probes.
- Usage traces and failed queries are untrusted input and must not directly rewrite generated instructions.

Outputs:

- UI badge: `healthy`, `attention`, `stale`, `degraded`, `blocked`.
- Agent Card Summary.
- Recommended changes.
- Optional GitHub PR draft for the Skill Pack repository.
- Optional golden eval additions.

External side effects require explicit approval/configuration:

- Slack/webhook delivery.
- GitHub PR draft creation.
- Golden eval additions.
- Skill pack publishing.

Non-goals:

- Do not auto-merge skill pack updates.
- Do not rotate tokens automatically.
- Do not enable write tools automatically.
- Do not mutate external repos without explicit approval.

## 12. By-phase implementation plan

### Phase 0 — Rename the concept and lock the contract

Goal: make the product language explicit before adding more UI.

Deliverables:

- Add this spec to docs.
- Define canonical terms: Agent Card, Skill Pack, Remote Tool Surface.
- Update roadmap/docs to say repo agents are remote-first and path-safe.
- Document that current generated skills are preliminary shims, not full install packages.

Acceptance criteria:

- Docs clearly distinguish provenance paths from runtime-accessible paths.
- Docs clearly state that local skills do not contain repo indexes.
- No code behavior change required.

### Phase 1 — Manifest and context-only adapter generation

Goal: make SourceBrief generate a portable Skill Pack without pretending remote code tools already exist.

Deliverables:

- `GET /workspaces/{workspace_id}/projects/{project_id}/agent-pack/manifest`
- `GET /workspaces/{workspace_id}/projects/{project_id}/agent-pack/hermes/SKILL.md`
- `GET /workspaces/{workspace_id}/projects/{project_id}/agent-pack/codex/AGENTS.md`
- `GET /workspaces/{workspace_id}/projects/{project_id}/agent-pack/claude/CLAUDE.md`
- `GET /workspaces/{workspace_id}/projects/{project_id}/agent-pack/mcp.json`
- UI `Install Agent` panel with copy/download actions.

Acceptance criteria:

- Generated artifacts are all derived from `sourcebrief-agent.yaml`.
- Generated Hermes skill includes `remote_only`, no local grep, separate MCP config requirement, and context-only workflow unless remote tools are live.
- Generated Codex/Claude adapters preserve the same safety boundaries.
- Generated artifacts contain no backend local paths or plaintext tokens.
- Resource-scoped token users only see allowed resources in generated manifests.
- Adapter generation fails if it references a required MCP tool that `tools/list` does not expose.
- Real-service smoke runs `hermes skills inspect` or temp-profile `hermes skills install` against generated raw `SKILL.md`, then separately validates MCP config/tool-call.

### Phase 2 — GitHub Skill Pack publishing

Goal: let users host skill packs in GitHub and install them with runtime-native mechanisms.

Deliverables:

- Export zip containing the recommended repository layout.
- Optional GitHub PR publisher using a user-configured repo and branch.
- Install docs for Hermes, Codex, and Claude.
- Skill Pack changelog generated from manifest changes.
- Manifest digest and tag/commit pinning guidance.

Acceptance criteria:

- Hermes install path works with a raw pinned `SKILL.md` URL:
  `hermes skills install https://raw.githubusercontent.com/<org>/<pack>/<tag-or-sha>/hermes/SKILL.md --name <agent>`.
- Codex can consume `codex/AGENTS.md` from the checked-out pack.
- Claude can consume `claude/CLAUDE.md` for alpha instruction mode.
- Publishing requires explicit user approval and displays the diff.
- Tokens are represented only as env var placeholders.

### Phase 3 — Remote code tools

Goal: remove the need for Hermes/Codex/Claude to access the repository filesystem.

Deliverables:

- Controlled sanitized full-file snapshot artifact or equivalent source blob store.
- MCP/HTTP `search_code`.
- MCP/HTTP `grep_code`.
- MCP/HTTP `read_file`.
- MCP/HTTP `find_symbol`.
- UI examples showing follow-up inspection through remote tools.

Acceptance criteria:

- Tools operate on indexed snapshots or controlled artifact storage, not arbitrary server paths.
- Absolute paths, `..`, NUL bytes, symlink escapes, binary files, unauthorized resources, and traversal attempts are rejected with deterministic errors.
- Regex/search operations are bounded and observable.
- All tools enforce the same token/project/resource boundary as `agent-context` plus `code:read` where required.
- Browser/API smoke proves a follow-up exact grep and file read without local repo access.
- Hermes MCP smoke proves a question -> context -> grep -> read_file flow from a runtime directory that does not contain the target source repo.

### Phase 4 — Retrieval profiles and eval-backed operating guidance

Goal: let the repo agent choose how it retrieves based on task type and prove whether embedding/rerank helps.

Deliverables:

- Named retrieval profiles in the manifest.
- Profile selection in `get_agent_context` and remote code tools where applicable.
- Eval history grouped by retrieval profile.
- UI comparison for lexical/vector/hybrid/hybrid+rerank/graph profiles.
- Generated skill instructions for when to use each profile.

Acceptance criteria:

- Eval runs record profile name, provider, model, latency, pass rate, and cited resources.
- Quality Evals can compare profiles across the same golden set.
- Generated skill pack updates when profile guidance changes.
- No provider switch silently mixes incompatible embedding namespaces.

### Phase 5 — Agent Card Drift Auditor cron

Goal: periodically summarize whether each repo agent card or skill pack needs adjustment.

Deliverables:

- Scheduled read-only auditor job.
- Agent Card Summary model/table.
- UI card status badge and finding list.
- Slack/webhook delivery option behind explicit configuration.
- Optional GitHub PR draft generator for skill pack updates behind explicit approval.

Acceptance criteria:

- Cron output says whether each agent card is healthy, stale, degraded, attention-needed, or blocked using documented thresholds.
- Findings cite evidence: eval trend, stale index, failed queries, missing capability, generation diff, or user feedback.
- The default auditor is read-only and tests prove it cannot rotate tokens, enable write tools, mutate source repos, send Slack/webhooks, or publish pack changes.
- Draft PRs require user approval before merge/publish.
- Suppression/ack controls prevent repeated noisy findings.

### Phase 6 — Patch and PR workflow, still opt-in

Goal: make repo agents useful for code change workflows without violating production or source-control boundaries.

Deliverables:

- `generate_patch` remote tool using indexed evidence and optional user-provided branch context.
- Optional GitHub PR creation through a separate approved integration.
- Mutation policy UI and audit records.

Acceptance criteria:

- Read-only remains the default.
- Remote write/PR creation requires explicit project config and per-action approval.
- Generated patches include indexed commit and warn if source branch moved.
- PR creation records scope, approver, source branch, target branch, and diff summary.

## 13. Observability and operations

Required metrics:

- skill pack generation count and failure count;
- adapter diff count;
- manifest stale count;
- remote tool call count, latency, error rate, result count;
- denied access count by tool;
- grep/read timeout count;
- eval pass rate by retrieval profile;
- drift auditor findings by severity.

Required audit events:

- manifest generated;
- skill pack downloaded;
- GitHub publish PR opened;
- MCP config copied/downloaded;
- remote code tool invoked;
- denied remote code tool access;
- auditor finding created;
- draft skill pack update proposed.

Ownership/RACI:

| Area | Responsible | Accountable | Notes |
|---|---|---|---|
| SourceBrief MCP uptime | Platform operator | Workspace/platform admin | Include health, logs, rate limits. |
| Index freshness | Project maintainer | Workspace admin | Auditor reports drift; maintainer approves refresh policy. |
| Generated adapter correctness | SourceBrief platform | Platform maintainer | Covered by parity and leak tests. |
| GitHub publishing | User/project maintainer | Repo owner | SourceBrief may draft PRs only with approval. |
| Token lifecycle | Workspace admin | Workspace admin | Expiry/revocation/scopes required. |
| Local runtime config | User/operator | User/operator | SourceBrief provides snippets, not silent mutation. |
| Incident response | Platform operator | Workspace/platform admin | Define support path per deployment. |

Initial SLO targets for alpha should be modest and configurable:

- MCP health endpoint available during platform uptime.
- p95 `get_agent_context` latency tracked, not yet hard-gated.
- Remote code read tools bounded by timeout and output caps.
- Auditor cadence at most daily by default; weekly summaries recommended for Slack.

## 14. Executable verification matrix

Each phase must include tests or smoke scripts for the critical contract.

Required checks:

- Manifest schema validation.
- Adapter parity test across Hermes/Codex/Claude.
- Generated-file secret and backend-path leak scan.
- Generated adapter does not reference unavailable MCP tools.
- Resource-scoped token manifest only includes allowed resources.
- Hermes raw `SKILL.md` inspect/install in a temp profile.
- Separate MCP config validation and tool call.
- No-local-checkout smoke from a directory/machine without target repo files.
- Malicious path tests for absolute path, `..`, NUL byte, and symlink escape.
- Unauthorized resource tests and no existence disclosure.
- Pathological regex timeout/complexity tests.
- Binary/large file behavior tests.
- Drift auditor read-only default tests.

## 15. Open decisions

1. Should SourceBrief create one skill pack repo per project, or one monorepo containing many generated agent packs?
2. Should `hermes skills install` point directly to `hermes/SKILL.md`, or should SourceBrief publish to a Hermes-compatible registry later?
3. What is the exact Claude skill package layout we want to support after alpha: `CLAUDE.md` only or Claude's skill bundle format?
4. Should Skill Pack publishing be built into SourceBrief or left as generated files plus user-managed GitHub workflow for alpha?
5. Should drift findings become SourceBrief Review Items, GitHub PRs, Slack summaries, or all three by default?

## 16. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Agent sees repo path and tries local grep | Broken UX and hallucinated evidence | Remote-only skill instructions, no backend paths, remote grep/read tools |
| Hermes skill install is mistaken for full package install | Missing manifest/MCP config and broken runtime | Explicit single-file install contract and separate MCP step |
| Adapter advertises unavailable tools | Runtime failures and user distrust | Capability matrix, `tools/list` validation, context-only preview label |
| Skill pack becomes huge/stale | Context overflow and wrong answers | Thin skill shim; data stays remote; auditor checks drift |
| Token leak through generated files | Security incident | Env var placeholders only; tests for no plaintext tokens |
| Remote grep becomes arbitrary filesystem read | Critical security bug | Snapshot-only path resolver, no absolute paths, no traversal, auth prefilter |
| Prompt injection from repo content rewrites instructions | Agent follows malicious source text | Treat repo-derived text as untrusted data; sanitize/quote generated content |
| Multiple runtime adapters drift | Inconsistent behavior | Generate all adapters from one manifest; adapter parity tests |
| Auditor creates noisy recommendations | Users ignore it | Evidence-backed findings, severity, thresholds, suppression controls |
| Auditor causes side effects | Surprise Slack/PR spam or unsafe changes | Read-only default; explicit approval for external side effects |
| Users confuse indexed code with live prod state | Bad operational decisions | Skill and context packets repeat static-context boundary |

## 17. Definition of done for the overall program

A user can:

1. Create a SourceBrief project with one or more Git resources.
2. Index the repos and see Agent Card readiness.
3. Generate a Skill Pack.
4. Publish or download the Skill Pack.
5. Install the Hermes skill from a pinned GitHub raw URL.
6. Configure MCP with a scoped token as a separate step.
7. Ask Hermes a repo question from a different machine or directory with no local repo checkout.
8. Hermes retrieves context, then performs follow-up remote grep/read via SourceBrief.
9. Hermes cites repo-relative paths and indexed commits.
10. SourceBrief cron later summarizes whether the Agent Card or Skill Pack needs adjustment.
