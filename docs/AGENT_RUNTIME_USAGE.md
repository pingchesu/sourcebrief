# Agent runtime usage

> This is the long-form runtime/operator reference. If you are new to the
> product, start with [Install and use](INSTALL_AND_USE.md) first; it gives the
> short install path, daily resource commands, product advantages, and
> embedding/rerank test boundaries.

The UI gets project context into shape: connect sources, index snapshots, review
what was found, and keep stale material out. The runtime layer is where that work
pays off. A coding agent can ask SourceBrief for the exact evidence it needs
while fixing an issue instead of relying on prompt stuffing or whatever files are
open locally.

If SourceBrief only stopped at Workbench, it would be a useful search UI. Runtime
integration makes it agent infrastructure:

| Without SourceBrief | With SourceBrief runtime |
| --- | --- |
| Agent guesses from prompt context. | Agent calls MCP for cited project evidence. |
| Agent edits the first file it can see. | Agent asks for related docs, tests, symbols, and impact areas first. |
| Remote indexed repos are confused with local checkouts. | Remote code is treated as static evidence; edits happen only in the real checkout. |
| Project instructions drift or get copied by hand. | Generated skills and agent packs point runtimes back to SourceBrief citations. |

This page is the practical runtime guide: MCP setup, scoped tokens, remote-code
safety, Agent Packs, generated skills, Context Pack Skill Exports, and the workflow agents
should follow before editing or reviewing code. For agents, **MCP plus Agent Packs/skills are
the primary path**. The CLI is the control plane and fallback path for setup,
resource lifecycle automation, validation, and CI.

Do not present SourceBrief as "a CLI the agent can run." The stronger runtime
contract is:

```text
generated skill/agent pack tells the agent WHEN and WHY to use SourceBrief
        -> MCP gives the agent live cited evidence and drilldown tools
        -> CLI remains available for doctor/setup/resource lifecycle fallback
        -> local checkout tools perform edits/tests/commits outside SourceBrief
```

An agent runtime is not ready until all three SourceBrief pieces have been
verified: skill loaded, MCP smoke call returns citations, and CLI doctor or
runtime validation passes without exposing tokens.

## The mental model

```text
Developer / agent asks a question
        -> SourceBrief searches authorized retrieval-enabled indexed snapshots
        -> SourceBrief returns cited context, file paths, symbols, freshness, and drilldown handles
        -> Agent uses the evidence to reason, then edits/tests through its normal local repo tools
```

SourceBrief is not the agent, not the editor, and not a production executor. It
is the evidence service behind the agent. See [Agent Packs](AGENT_PACKS.md) for
the install model: packs install thin runtime adapters and route agents back to
SourceBrief remote evidence; they do not sync the full corpus by default.

For code work, that distinction matters:

- SourceBrief can index a remote Git repository and answer from that indexed
  snapshot.
- SourceBrief can search, grep, read files, find symbols, and inspect graphs from
  indexed snapshots through MCP.
- SourceBrief should not be treated as proof that the repo exists in the agent's
  current filesystem.
- SourceBrief does not run tests, deploy code, restart services, or mutate
  production.
- Patch generation and PR workflows are opt-in proposal flows. They still
  require explicit policy, scopes, and approval before any external
  source-control mutation.

The short version:

```text
Use SourceBrief to know where to look and what to trust.
Use the coding agent's normal tools to edit, test, commit, and open PRs.
```

## When to use it during development

Use SourceBrief when the question spans more context than the files currently open in your editor.

Good prompts:

```text
Where is checkout retry behavior implemented, and what docs explain the intended policy?
```

```text
What config files and runbooks mention this queue name?
```

```text
I need to change the auth token model. Which API routes, tests, docs, and runtime clients probably need updates?
```

```text
Find the owner-facing docs and code paths behind the repo agent skill export flow.
```

Bad prompts:

```text
Fix this bug.
```

SourceBrief should not be asked to "fix" by itself. Ask it for evidence first, then let your coding agent edit and test in the actual checkout.

## A practical issue flow

See [demo runtime output](examples/demo-runtime-output.md) for a captured local run that indexes a tiny runbook and then exercises both `agent-context` and the MCP-shaped `mcp-context` path with normalized IDs.

When Hermes, Claude Code, Codex, or Cursor is working on an issue, use this loop:

1. Ask SourceBrief for a project-level map.

   ```text
   sourcebrief.ask(query="Where is token auth enforced for runtime agents?", runtime="hermes", profile="hybrid")
   ```

2. Discover sources and architecture when the agent needs the project shape.

   ```text
   sourcebrief.discover(query="runtime auth and MCP", max_resources=10, max_items=10)
   ```

3. Follow exact terms with stricter tools.

   ```text
   sourcebrief.lookup(query="require_scope service tokens", search_in="all")
   sourcebrief.grep_code(pattern="require_scope", path_glob="apps/api/**")
   sourcebrief.find_symbol(name="create_api_token")
   sourcebrief.read_file(resource_ref="SourceBrief API", path="apps/api/sourcebrief_api/main.py", start_line=2020, end_line=2095)
   ```

   On large partial repos, `lookup(search_in="all")` returns docs/symbols plus a structured warning if the code-search facet exceeds the remote scan budget. Use cited paths from `ask`/`lookup` as `path_glob` before broad `grep_code`.

4. Ask an impact question before editing.

   ```text
   sourcebrief.ask(query="If token scopes change, what tests and docs need updates?", runtime="codex", profile="graph")
   ```

5. Edit in the real repo checkout, not in SourceBrief.

6. Run tests locally or in CI.

7. Use SourceBrief again when the diff touches unfamiliar areas.

This prevents the common failure mode where an agent edits the one file it can see and misses sibling docs, runtime adapters, CLI commands, or MCP clients.

## Remote code handling

A Git source in SourceBrief is remote indexed evidence. It is not a mounted working tree.

If an agent has a SourceBrief skill or MCP server but no local checkout, it must not run local filesystem commands as if the target repo is present:

```text
Do not use local rg/cat/edit on the target repo unless the user provides a checkout.
Use SourceBrief MCP tools for remote evidence instead.
```

Use these MCP tools for remote code:

| Task | Tool |
| --- | --- |
| Start with a cited answer | `sourcebrief.ask` / `sourcebrief.get_agent_context` |
| Discover available sources and architecture | `sourcebrief.discover` / `sourcebrief.list_sources` / `sourcebrief.get_architecture` |
| Search docs/code/symbols by question | `sourcebrief.lookup` (`search_in=docs` works with context-only tokens; default `all` returns docs plus a warning when `code:read` is absent or code scan exceeds budget) |
| Search indexed docs/artifacts | `sourcebrief.search` |
| Read exact cited sections | `sourcebrief.read_section` |
| Search indexed source files semantically | `sourcebrief.search_code` |
| Grep indexed source files | `sourcebrief.grep_code` |
| Read an indexed file range | `sourcebrief.read_file` |
| Find indexed symbols | `sourcebrief.find_symbol` |
| Inspect published graph context | `sourcebrief.graph_query` / `sourcebrief.graph_path` |
| Propose a patch without mutating Git | `sourcebrief.generate_patch` |
| Record explicit PR approval metadata | `sourcebrief.open_pr` |

For high-throughput SDK/backend clients, use MCP `sourcebrief.get_rpc_spec` to fetch the exact HTTP/JSON-RPC code-access schema, then call the project-scoped RPC endpoint returned by the spec/runtime plan. The RPC surface batches `sourcebrief.code.search`, `sourcebrief.code.grep`, `sourcebrief.code.read_batch`, and `sourcebrief.code.lookup_plan`; it uses the same auth/resource boundaries as MCP, prefers `resource_ref` names in user-facing clients, and returns per-call `ok`/`error` telemetry instead of asking a model to invent HTTP payloads from prose.

The right behavior for a coding agent is:

```text
Use SourceBrief to find and cite evidence.
Use the actual local checkout to edit and test.
Use explicit approval before any PR or remote mutation.
```

## Runtime choices

SourceBrief exposes the same project through several surfaces. They are meant to
compose, not compete with each other.

| Surface | Best for | What the agent gets |
| --- | --- | --- |
| Workbench UI | A human wants to inspect an answer before handing it to an agent. | Rendered packet, citations, evidence rows, and freshness signals. |
| CLI `ask` / `agent-context` | Scripts, demos, smoke tests, or one-off local experiments. | One JSON/text runtime packet with citations and runtime instructions. |
| MCP | Live agent sessions in Hermes, Claude Code, Codex, Cursor, or custom runtimes. | Discoverable tools for context, search, remote code drilldown, graph traversal, and guarded proposal flows. |
| Generated agent pack | You want to configure a runtime for one SourceBrief project quickly. | `SKILL.md`, `CLAUDE.md`, `AGENTS.md`, `mcp.json`, golden questions, manifest, and usage notes. |
| Context Pack Skill Export | You have a reviewed Context Pack and want a reusable team workflow. | Approved skill files, references, playbooks, citation policy, validation report, and leak-scan metadata. |

Start with MCP for live agent use. Add skills when you want a repeatable
instruction package that tells the agent when to call SourceBrief, what evidence
standard to follow, and where to stop before mutation.

## Auth for agents

Humans sign in to the web UI with email/password. Agents should use scoped API tokens.

Recommended read-only scopes for a runtime agent that can answer and drill into remote code:

```text
project:read,project:query,resource:read,review:read,code:read
```

Context-only token, if you only need `sourcebrief.get_agent_context` and do not want remote file/symbol/grep tools:

```text
project:read,project:query,resource:read,review:read
```

Narrowest context-only token for a known project/resource:

```text
project:query,resource:read
```

Do not use the narrowest token for generated agent packs or remote-code drilldown. Agent pack download needs `project:read`; `sourcebrief.ask` / `sourcebrief.get_agent_context` omit code symbols unless the token has `code:read`; `search_code`, `grep_code`, `read_file`, and `find_symbol` require `code:read`.

Token creation requires user/session authentication with `token:admin`; API tokens cannot mint child tokens. For local development, run `sourcebrief login --password-env SOURCEBRIEF_ADMIN_PASSWORD` first or use an already authenticated web/session flow. `SOURCEBRIEF_DEV_AUTH=true` remains a disposable-local fallback, not the normal quickstart path.

```bash
sourcebrief --json token create-runtime \
  --workspace "SourceBrief CLI Demo" \
  --name "Hermes SourceBrief token" \
  --read-code \
  --project "First useful moment" \
  --resource-id "$RESOURCE_ID"
```

Use `--context-only` instead of `--read-code` when the runtime only needs cited context and not remote file/symbol/grep drilldown. `create-runtime` requires an explicit project/resource allowlist by default; pass `--workspace-wide` only when you intentionally want a workspace-wide runtime token.

The plaintext token is returned once. Store it in the runtime's secret manager or environment, not in Git. Treat local runtime config, generated plans, receipts, downloaded/generated agent packs, and cached context as sensitive workspace artifacts because they can expose endpoint URLs, project/resource IDs, source paths, and citations even when token values are not present:

```bash
export SB_TOKEN="<sourcebrief-api-token>"
```

List and revoke tokens:

```bash
sourcebrief --json token list --workspace "SourceBrief CLI Demo"
sourcebrief --json token revoke --workspace "SourceBrief CLI Demo" --token-id "$TOKEN_ID"
```

For normal CLI usage, choose workspace/project by name and save that selection once:

```bash
sourcebrief use --workspace "SourceBrief CLI Demo" --project "First useful moment"
sourcebrief --json resource list
sourcebrief --json agent profile
```

IDs remain available as advanced/debug escape hatches when you need to script against exact API identifiers.

## Install and use MCP

MCP is the main live integration. It lets an agent ask SourceBrief follow-up
questions during a task instead of making one giant context request at the start.

For a safer copyable setup path, start with [Runtime install plan](RUNTIME_INSTALL_PLAN.md). It shows the MCP URL, runtime-specific config shape, required scopes, validation command, and rollback steps without silently editing local runtime profiles.

The useful pattern is:

```text
get_agent_context or ask for the map
    -> discover / lookup for source and architecture orientation
    -> search / read_section for cited docs
    -> search_code / grep_code / read_file / find_symbol for exact code evidence
    -> graph_query / graph_path for impact and relationships
    -> local edit and local tests outside SourceBrief
```

Core tools an agent should expect:

| Need | Tool family |
| --- | --- |
| Start with a cited project answer | `sourcebrief.ask` / `sourcebrief.get_agent_context` |
| Discover available sources and architecture | `sourcebrief.discover`, `sourcebrief.list_sources`, `sourcebrief.get_architecture` |
| Search docs/code/symbols by question | `sourcebrief.lookup` |
| Search or read approved docs and artifacts | `sourcebrief.search`, `sourcebrief.read_section` |
| Drill into indexed source code | `sourcebrief.search_code`, `sourcebrief.grep_code`, `sourcebrief.read_file`, `sourcebrief.find_symbol` |
| Follow resource/file/symbol relationships | `sourcebrief.graph_query`, `sourcebrief.graph_path` |
| Propose changes without direct mutation | `sourcebrief.generate_patch`, `sourcebrief.open_pr` when explicitly enabled |

The MCP endpoint is project scoped. Users should choose the workspace and project by name through the UI, `sourcebrief use --workspace ... --project ...`, or a generated runtime plan. The generated config may contain a resolved internal URL path because MCP clients need a stable transport endpoint, but users should not copy internal identifiers manually:

```text
http://localhost:18000/mcp/<resolved-project-scope>
```

Use a scoped bearer token in the `Authorization` header. In the examples below, `<auth-header>` means the full authorization header for your runtime token, and `<bearer-header-value>` means the header value built from the bearer scheme plus that token.

### Choose a runtime path

| Runtime | Config shape | Reload / validation | Common failure mode |
| --- | --- | --- | --- |
| Hermes | YAML `mcp_servers.sourcebrief.url` plus `headers.Authorization`. | Restart Hermes/gateway or use runtime MCP reload; then run `sourcebrief doctor --query ...` or `scripts/hermes_integration.py`. | Gateway has discovered tools but invocation returns stale session/tool errors; restart the runtime side. |
| Claude Code | JSON `mcpServers.sourcebrief` with `type = http`, or project instruction file from the agent pack. | Restart Claude Code session after changing MCP config/instructions. | Instruction file is loaded but MCP server is not configured, so Claude can mention SourceBrief but cannot call it. |
| Codex | TOML `[mcp_servers.sourcebrief]` with `url` and `bearer_token_env_var`, plus optional `AGENTS.md` from the agent pack. | Start a fresh Codex session in the target checkout after config changes. | Codex treats indexed remote code as local files; remind it to use SourceBrief for evidence and local tools only for the real checkout. |
| Cursor/custom MCP | HTTP MCP URL + bearer header if the client supports custom headers. | Use the client MCP inspector/logs plus `sourcebrief doctor --query ...`. | Client supports stdio MCP only or cannot set headers; use an adapter/proxy or another runtime. |

Runtime setup should be boring and reversible: generate a plan, inspect config and scopes, validate, apply only when intended, and keep rollback instructions.

### Validate the MCP integration first

Use `sourcebrief doctor` as a lightweight API/project/MCP-context smoke test. It checks API readiness, resolves the selected workspace/project, verifies project resources are visible, and can make one `sourcebrief.get_agent_context`-style MCP context call when `--query` is provided.

```bash
sourcebrief doctor \
  --workspace "SourceBrief CLI Demo" \
  --project "First useful moment" \
  --query "How does this project expose context to agents?" \
  --runtime hermes
```

For full runtime validation, generate a plan and inspect/run its validator command instead of treating `doctor` as the complete gate. The generated validator path covers REST `agent-context`, MCP `initialize`, MCP `tools/list`, MCP `tools/call`, read-only denial behavior, and citation consistency; it also emits `hermes_config.mcp_servers` and redacts the token when configured with redaction flags.

```bash
sourcebrief runtime plan \
  --workspace "SourceBrief CLI Demo" \
  --project "First useful moment" \
  --runtime hermes
```

The validator's default minted token is enough for `sourcebrief.get_agent_context`. If you also want remote code drilldown tools (`search_code`, `grep_code`, `read_file`, `find_symbol`), create a token with `code:read` and pass it with `--token "$SB_TOKEN"`.

### Hermes config

Add this shape to the target Hermes profile config:

```yaml
mcp_servers:
  sourcebrief:
    url: http://localhost:18000/mcp/<resolved-project-scope>
    headers:
      Authorization: <bearer-header-value>
    timeout: 120
    connect_timeout: 30
```

Then restart Hermes, or use MCP reload if your running gateway supports it. After discovery, the runtime should expose tools such as:

```text
sourcebrief.ask
sourcebrief.discover
sourcebrief.lookup
sourcebrief.get_agent_context
sourcebrief.search
sourcebrief.read_section
sourcebrief.search_code
sourcebrief.grep_code
sourcebrief.read_file
sourcebrief.find_symbol
```

### Claude / Codex / Cursor config shape

Different runtimes store MCP config in different formats. The shapes below mirror SourceBrief's runtime install-plan generator. For Cursor or another MCP-capable client, use the same HTTP MCP URL and bearer auth pattern if that client supports HTTP MCP servers with custom headers.

Claude-style JSON:

```json
{
  "mcpServers": {
    "sourcebrief": {
      "type": "http",
      "url": "http://localhost:18000/mcp/<resolved-project-scope>",
      "headers": {
        "Authorization": "<bearer-header-value>"
      }
    }
  }
}
```

Codex-style TOML:

```toml
[mcp_servers.sourcebrief]
url = "http://localhost:18000/mcp/<resolved-project-scope>"
bearer_token_env_var = "SOURCEBRIEF_TOKEN"
```

Use the runtime's own secret mechanism if it does not expand environment variables in headers. For the Codex shape above, put only the environment variable name in the config and export the token separately. Do not paste plaintext tokens into committed config.

## Install and use skills

Skills are how SourceBrief becomes reusable agent behavior instead of a one-off
MCP config. They do not copy the indexed corpus into a prompt. They teach the
runtime how to call SourceBrief, how to treat citations, and how to avoid
mistaking remote indexed evidence for a local checkout.

SourceBrief has two skill-related outputs. They are related but not the same.

### Option A: project agent pack

Use this when you want a quick adapter package for one SourceBrief project. It is
the fastest way to hand a runtime a project-specific context contract.

Download the generated pack from the web **Install Agent** panel or from the project agent-pack URL returned by a generated runtime plan. The URL is resolved internally for the selected workspace/project; do not ask users to paste internal identifiers into it.

The zip contains:

```text
README.md
sourcebrief-agent.yaml
mcp.json
hermes/SKILL.md
claude/CLAUDE.md
codex/AGENTS.md
evals/golden-questions.yaml
CHANGELOG.md
```

Unpack it:

```bash
rm -rf sourcebrief-agent-pack
mkdir -p sourcebrief-agent-pack
unzip -q sourcebrief-agent-pack.zip -d sourcebrief-agent-pack
```

Install the Hermes skill shim into a local Hermes user skill directory, then configure MCP from the pack's `mcp.json`:

```bash
mkdir -p ~/.hermes/skills/sourcebrief-project
cp sourcebrief-agent-pack/hermes/SKILL.md ~/.hermes/skills/sourcebrief-project/SKILL.md
```

For Claude Code or Codex, put the adapter file where that runtime will load project instructions. A safe pattern is to keep the pack outside the target repo and copy/symlink the instruction file into the agent workdir only when needed:

```bash
# Claude Code workdir
cp sourcebrief-agent-pack/claude/CLAUDE.md ./CLAUDE.md

# Codex workdir
cp sourcebrief-agent-pack/codex/AGENTS.md ./AGENTS.md
```

Do not commit those copied instruction files to the target repo unless that is an intentional project policy.

How to use it:

- Hermes: install or copy `hermes/SKILL.md` into your Hermes skills workflow, then configure MCP separately from `mcp.json`.
- Claude Code: use `claude/CLAUDE.md` as project instruction context.
- Codex: use `codex/AGENTS.md` as the agent instruction file.
- Any MCP-capable runtime: use `mcp.json` as the config template.

Important boundary: the pack is an adapter. It contains runtime instructions
such as `SKILL.md`, MCP config templates, and project metadata; it intentionally
excludes the target repo, full source corpus, embeddings, indexes, eval history,
plaintext bearer tokens, and other secrets. It tells the runtime to call
SourceBrief rather than answer from a copied local corpus.

### Option B: reviewed Context Pack Skill Export

Use this when you have published a Context Pack and want a reusable
citation-backed skill package. This is the heavier path for team workflows where
the evidence bundle has been reviewed and should carry freshness rules,
references, validation metadata, and leak-scan results.

Generate, approve, and write a local package directory with the CLI:

```bash
sourcebrief skill export \
  --workspace "SourceBrief CLI Demo" \
  --project "First useful moment" \
  --pack-key "$PACK_KEY" \
  --pack-version "$PACK_VERSION" \
  --title "My project SourceBrief skill" \
  --approve-comment "Reviewed citations, coverage, and leak scan." \
  --out ./sourcebrief-skill
```

Inspect `SKILL.md`, `manifest.json`, and `references/`, then dry-run and apply the local Hermes install:

```bash
sourcebrief skill install --package ./sourcebrief-skill --target hermes --dry-run
sourcebrief skill install --package ./sourcebrief-skill --target hermes --receipt ./sourcebrief-skill-receipt.json --apply
sourcebrief skill uninstall --receipt ./sourcebrief-skill-receipt.json
```

The API also exposes an approved package download for internal clients; normal users should use the UI/CLI export flow above rather than constructing an internal ID-based URL. Draft exports cannot be downloaded or installed.

Generated skill exports are better for repeatable team workflows because they can include package metadata, references, playbooks, citation policy, freshness rules, local install receipts, and leak-scan validation. They still do not embed the full source corpus or plaintext bearer tokens; generated artifacts should reference token environment variable names and redact token values in examples, receipts, and validation output.

## Usage examples by agent

### Hermes debugging a backend issue

1. Load the project skill if installed.
2. Let Hermes discover MCP tools.
3. Ask a scoped question:

   ```text
   In SourceBrief, where is bearer token scope enforced for MCP and agent-context? Use SourceBrief evidence first, then inspect local files before editing.
   ```

4. Hermes should call `sourcebrief.get_agent_context`, then drill down with `sourcebrief.grep_code` or `sourcebrief.read_file`.
5. Hermes edits the local checkout and runs tests normally.

### Claude Code reviewing a cross-file change

Use `CLAUDE.md` from the agent pack or write equivalent instructions:

```text
Use SourceBrief MCP before making claims about this repo. Treat indexed code as static evidence. If you need exact code, call sourcebrief.read_file or sourcebrief.grep_code. Do not assume the target repo is local unless the user confirms the checkout path.
```

Then ask:

```text
Review this PR for auth/runtime impacts. Start by asking SourceBrief which docs, CLI commands, MCP tools, and tests mention service tokens.
```

### Codex implementing an issue

Use `AGENTS.md` from the agent pack in the working directory where Codex runs. The intended flow is:

```text
SourceBrief get_agent_context -> exact remote read/grep/symbol lookup -> local edit -> local tests -> PR.
```

Codex should not treat the SourceBrief pack directory as the target source repo. The pack is instruction/config only.

## What to say when evidence is missing

A good SourceBrief-powered agent should refuse to invent project facts. Use language like:

```text
I do not have cited SourceBrief evidence for that area. I need the source indexed, the Context Pack updated, or permission to inspect a local checkout before making that claim.
```

That is a feature, not a failure. It is how SourceBrief keeps agents from turning stale or missing context into confident nonsense.
