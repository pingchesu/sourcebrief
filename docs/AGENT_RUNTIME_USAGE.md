# Agent runtime usage

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
safety, generated skills, Context Pack Skill Exports, and the workflow agents
should follow before editing or reviewing code.

## The mental model

```text
Developer / agent asks a question
        -> SourceBrief searches authorized retrieval-enabled indexed snapshots
        -> SourceBrief returns cited context, file paths, symbols, freshness, and drilldown handles
        -> Agent uses the evidence to reason, then edits/tests through its normal local repo tools
```

SourceBrief is not the agent, not the editor, and not a production executor. It
is the evidence service behind the agent.

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

When Hermes, Claude Code, Codex, or Cursor is working on an issue, use this loop:

1. Ask SourceBrief for a project-level map.

   ```text
   sourcebrief.get_agent_context(query="Where is token auth enforced for runtime agents?", runtime="hermes", profile="hybrid")
   ```

2. Follow exact terms with stricter tools.

   ```text
   sourcebrief.grep_code(pattern="require_scope", path_glob="*.py")
   sourcebrief.find_symbol(name="create_api_token")
   sourcebrief.read_file(resource_id=<resource>, path="apps/api/sourcebrief_api/main.py", start_line=2020, end_line=2095)
   ```

3. Ask an impact question before editing.

   ```text
   sourcebrief.get_agent_context(query="If token scopes change, what tests and docs need updates?", runtime="codex", profile="graph")
   ```

4. Edit in the real repo checkout, not in SourceBrief.

5. Run tests locally or in CI.

6. Use SourceBrief again when the diff touches unfamiliar areas.

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
| Start with a cited answer | `sourcebrief.get_agent_context` |
| Search indexed docs/artifacts | `sourcebrief.search` |
| Read exact cited sections | `sourcebrief.read_section` |
| Search indexed source files semantically | `sourcebrief.search_code` |
| Grep indexed source files | `sourcebrief.grep_code` |
| Read an indexed file range | `sourcebrief.read_file` |
| Find indexed symbols | `sourcebrief.find_symbol` |
| Inspect published graph context | `sourcebrief.graph_query` / `sourcebrief.graph_path` |
| Propose a patch without mutating Git | `sourcebrief.generate_patch` |
| Record explicit PR approval metadata | `sourcebrief.open_pr` |

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
| CLI `agent-context` | Scripts, demos, smoke tests, or one-off local experiments. | One JSON/text runtime packet with citations and runtime instructions. |
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

Do not use the narrowest token for generated agent packs or remote-code drilldown. Agent pack download needs `project:read`; `search_code`, `grep_code`, `read_file`, and `find_symbol` need `code:read`.

Token creation requires user/session authentication with `token:admin`; API tokens cannot mint child tokens. In local dev, the CLI can mint a token when `SOURCEBRIEF_DEV_AUTH=true` is enabled. In shared deployments, use a user-authenticated admin/session flow to mint scoped runtime tokens.

```bash
sourcebrief --json token create \
  --workspace-id "$WORKSPACE_ID" \
  --name "Hermes SourceBrief token" \
  --scope project:read,project:query,resource:read,review:read,code:read \
  --project-id "$PROJECT_ID" \
  --resource-id "$RESOURCE_ID"
```

The plaintext token is returned once. Store it in the runtime's secret manager or environment, not in Git:

```bash
export SB_TOKEN="<sourcebrief-api-token>"
```

List and revoke tokens:

```bash
sourcebrief --json token list --workspace-id "$WORKSPACE_ID"
sourcebrief --json token revoke --workspace-id "$WORKSPACE_ID" --token-id "$TOKEN_ID"
```

If you do not already have IDs, get them from the UI route you are using, from the API responses when you create a workspace/project/resource, or from CLI commands such as:

```bash
sourcebrief --json resource list --workspace-id "$WORKSPACE_ID" --project-id "$PROJECT_ID"
sourcebrief --json agent profile --workspace-id "$WORKSPACE_ID" --project-id "$PROJECT_ID"
```

## Install and use MCP

MCP is the main live integration. It lets an agent ask SourceBrief follow-up
questions during a task instead of making one giant context request at the start.

The useful pattern is:

```text
get_agent_context for the map
    -> search / read_section for cited docs
    -> search_code / grep_code / read_file / find_symbol for exact code evidence
    -> graph_query / graph_path for impact and relationships
    -> local edit and local tests outside SourceBrief
```

Core tools an agent should expect:

| Need | Tool family |
| --- | --- |
| Start with a cited project answer | `sourcebrief.get_agent_context` |
| Search or read approved docs and artifacts | `sourcebrief.search`, `sourcebrief.read_section` |
| Drill into indexed source code | `sourcebrief.search_code`, `sourcebrief.grep_code`, `sourcebrief.read_file`, `sourcebrief.find_symbol` |
| Follow resource/file/symbol relationships | `sourcebrief.graph_query`, `sourcebrief.graph_path` |
| Propose changes without direct mutation | `sourcebrief.generate_patch`, `sourcebrief.open_pr` when explicitly enabled |

The MCP endpoint is project scoped:

```text
http://localhost:18000/mcp/<workspace-id>/<project-id>
```

Use a scoped bearer token in the `Authorization` header. In the examples below, `<auth-header>` means the full authorization header for your runtime token, and `<bearer-header-value>` means the header value built from the bearer scheme plus that token.

### Validate the MCP integration first

SourceBrief ships an operational validator that checks REST `agent-context`, MCP `initialize`, MCP `tools/list`, MCP `tools/call`, read-only denial behavior, and citation consistency.

```bash
python scripts/hermes_integration.py \
  --api-url http://localhost:18000 \
  --workspace-id "$WORKSPACE_ID" \
  --project-id "$PROJECT_ID" \
  --resource-id "$RESOURCE_ID" \
  --query "How does this project expose context to agents?" \
  --redact-token
```

The output includes a `hermes_config.mcp_servers` block and redacts the token when `--redact-token` is set.

The validator's default minted token is enough for `sourcebrief.get_agent_context`. If you also want remote code drilldown tools (`search_code`, `grep_code`, `read_file`, `find_symbol`), create a token with `code:read` and pass it with `--token "$SB_TOKEN"`.

### Hermes config

Add this shape to the target Hermes profile config:

```yaml
mcp_servers:
  sourcebrief:
    url: http://localhost:18000/mcp/<workspace-id>/<project-id>
    headers:
      Authorization: <bearer-header-value>
    timeout: 120
    connect_timeout: 30
```

Then restart Hermes, or use MCP reload if your running gateway supports it. After discovery, the runtime should expose tools such as:

```text
sourcebrief.get_agent_context
sourcebrief.search
sourcebrief.read_section
sourcebrief.search_code
sourcebrief.grep_code
sourcebrief.read_file
sourcebrief.find_symbol
```

### Claude / Codex / Cursor config shape

Different runtimes store MCP config in different files, but the SourceBrief server shape is the same. The generated agent pack's `mcp.json` currently includes ready-to-copy sections for Hermes, Claude, and Codex. For Cursor or another MCP-capable client, use the same URL and header shape if that client supports HTTP MCP servers with custom headers.

Claude-style JSON:

```json
{
  "mcpServers": {
    "sourcebrief": {
      "url": "http://localhost:18000/mcp/<workspace-id>/<project-id>",
      "headers": {
        "Authorization": "<bearer-header-value>"
      }
    }
  }
}
```

Codex-style JSON:

```json
{
  "mcp_servers": {
    "sourcebrief": {
      "url": "http://localhost:18000/mcp/<workspace-id>/<project-id>",
      "headers": {
        "Authorization": "<bearer-header-value>"
      }
    }
  }
}
```

Use the runtime's own secret mechanism if it does not expand environment variables in headers. Do not paste plaintext tokens into committed config.

## Install and use skills

Skills are how SourceBrief becomes reusable agent behavior instead of a one-off
MCP config. They do not copy the indexed corpus into a prompt. They teach the
runtime how to call SourceBrief, how to treat citations, and how to avoid
mistaking remote indexed evidence for a local checkout.

SourceBrief has two skill-related outputs. They are related but not the same.

### Option A: project agent pack

Use this when you want a quick adapter package for one SourceBrief project. It is
the fastest way to hand a runtime a project-specific context contract.

Download the generated pack:

```bash
curl -fsS \
  -H "<auth-header>" \
  "http://localhost:18000/workspaces/$WORKSPACE_ID/projects/$PROJECT_ID/agent-pack.zip" \
  -o sourcebrief-agent-pack.zip
```

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

Important boundary: the pack is an adapter. It does not contain the target repo,
embeddings, indexes, eval history, or secrets. It tells the runtime to call
SourceBrief.

### Option B: reviewed Context Pack Skill Export

Use this when you have published a Context Pack and want a reusable
citation-backed skill package. This is the heavier path for team workflows where
the evidence bundle has been reviewed and should carry freshness rules,
references, validation metadata, and leak-scan results.

Generate a skill export from a published pack:

```bash
curl -fsS -X POST \
  -H "<auth-header>" \
  -H "Content-Type: application/json" \
  "http://localhost:18000/workspaces/$WORKSPACE_ID/projects/$PROJECT_ID/context-packs/$PACK_KEY/versions/$PACK_VERSION/skill-exports" \
  -d '{"export_type":"hermes_skill","title":"My project SourceBrief skill"}'
```

Review the returned files, validation report, leak scan, and manifest. Approve only if the package is safe:

```bash
curl -fsS -X POST \
  -H "<auth-header>" \
  -H "Content-Type: application/json" \
  "http://localhost:18000/workspaces/$WORKSPACE_ID/projects/$PROJECT_ID/skill-exports/$EXPORT_ID/approve" \
  -d '{"comment":"Reviewed citations, coverage, and leak scan."}'
```

Download an approved file:

```bash
curl -fsS \
  -H "<auth-header>" \
  "http://localhost:18000/workspaces/$WORKSPACE_ID/projects/$PROJECT_ID/skill-exports/$EXPORT_ID/files/SKILL.md" \
  -o SKILL.md
```

Generated skill exports are better for repeatable team workflows because they can include package metadata, references, playbooks, citation policy, freshness rules, and leak-scan validation.

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
