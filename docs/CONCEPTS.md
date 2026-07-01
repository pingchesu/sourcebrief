# Concepts

SourceBrief is easier to understand as a pipeline than as a feature list:

```text
Source -> Snapshot -> Evidence -> Review -> Runtime
```

<img src="assets/sourcebrief-context-flow.svg" alt="SourceBrief context flow from sources through snapshots and reviewed evidence to runtime agents" width="100%" />

The core idea: agents should ask for cited project evidence before they edit. SourceBrief stores exact indexed versions of project material, attaches provenance to retrieved context, and serves that evidence through UI, CLI, HTTP, and MCP.

## The product mental model

| Stage | Plain meaning | Why it exists |
| --- | --- | --- |
| Source | A repo, doc, URL, runbook, upload, or folder bundle you connect. | Gives SourceBrief material to index. |
| Snapshot | The exact version SourceBrief indexed. Git snapshots include commit provenance; docs/uploads include content hashes. | Lets answers point to the version they came from. |
| Evidence | Search chunks, retained sections, citations, code symbols, graph nodes/edges, and file paths. | Gives agents inspectable handles, not just prose. |
| Review | Resource Maps, freshness, coverage, Context Packs, Repo/Project Agent views, and Skill Exports. | Lets humans decide which context is useful, stale, reusable, or ready for runtime packaging. |
| Runtime | Workbench, CLI, HTTP API, MCP tools, and installable Agent Packs that route agents back to SourceBrief. | Lets agents use the reviewed evidence during real work without copying the full corpus locally. |

If you remember one sentence, use this:

> SourceBrief is the read-only evidence service behind coding agents.

## The common objects

| Object | What it is | Use it when... |
| --- | --- | --- |
| Workspace | Tenant boundary for users, projects, tokens, and audit events. | You are administering access. |
| Project | Context boundary for a product, service, or repo group. | You choose what an agent is allowed to ask about. |
| Source / Resource | User-facing source material; backend APIs often call it a resource. | You connect or scope knowledge. |
| Snapshot | Indexed version of a resource. | You need provenance, freshness, or reproducibility. |
| Citation | A pointer back to path/title, ordinal or lines, snapshot, hash, and score. | You need to verify a claim. |
| Agent Context | Runtime-shaped answer with instruction, context, citations, symbols, and follow-up tool hints. | An agent needs a cited project answer. |
| Resource Map | Reviewable map of what SourceBrief found in one source. | You are onboarding or auditing a source. |
| Resource Graph / Evidence Graph | Permissioned graph of snapshots, sections, symbols, citations, and relationships. | You need the canonical evidence layer that agents query. |
| Context Pack | Versioned, published bundle of approved artifacts. | A team wants stable evidence for repeatable work. |
| Repo Agent / Project Agent | User-facing published runtime view over resources, context packs, freshness, capabilities, and known limits. | You want to present an installable agent capability without exposing graph internals. |
| Agent Pack / Skill Pack | Runtime adapter files that tell an agent how to call SourceBrief and respect citations. | You want repeatable agent behavior, not one-off prompts. |
| Skill Export | One packaging format for an Agent Pack. | You need downloadable/installable runtime adapter files. |
| MCP tools | JSON-RPC tool surface for live agent sessions. | Hermes, Claude Code, Codex, Cursor, or another MCP client needs on-demand evidence. |

## Resource Map vs Context Pack

A **Resource Map** answers:

> What did SourceBrief find inside this one source, and where should an agent start?

A **Context Pack** answers:

> Which approved evidence bundle should an agent use for this workflow or project?

Resource Maps are source-specific. Context Packs can combine approved artifacts from multiple sources and pin the snapshot versions used by a workflow.

## Repo/Project Agent vs Agent Pack

A **Repo Agent** or **Project Agent** answers:

> Which reviewed resources, context packs, capabilities, freshness limits, and operating boundaries should an agent use for this repo or project?

An **Agent Pack** answers:

> What should a local runtime install or copy so the agent knows when and how to call SourceBrief?

Agent Packs are thin runtime adapters. They should not contain the full source corpus, embeddings, vector indexes, raw chunks, or graph indexes by default. The default install mode is `remote-live`: the installed pack routes the runtime back to SourceBrief MCP/API/RPC for current cited evidence.

A **Skill Export** is one packaging format for an Agent Pack. It is generated from reviewed SourceBrief evidence, but it is not the evidence itself.

## Agent Context vs Context Packet

Both are cited retrieval results, but they serve different callers.

| Shape | Caller | Difference |
| --- | --- | --- |
| Context Packet | API clients that want raw ranked evidence. | Retrieval-oriented response. |
| Agent Context | Agent runtimes such as Hermes, Claude, Codex, Cursor, or MCP clients. | Adds runtime instruction, token budget hint, symbols, pack pinning metadata, and suggested next tool calls. |

Start with `sourcebrief.ask` / `sourcebrief.get_agent_context`. Drill down with `sourcebrief.search`, `sourcebrief.read_section`, `sourcebrief.search_code`, `sourcebrief.grep_code`, `sourcebrief.read_file`, and graph tools when a task needs exact evidence.

## What SourceBrief returns

A useful answer should expose:

- source name;
- path or title;
- line range, section ordinal, or citation locator;
- snapshot/version identifier;
- commit or content hash where available;
- retrieval score and graph/code-symbol hints;
- runtime instruction and follow-up tool calls.

That is what makes the answer inspectable.

## What SourceBrief is not

SourceBrief is not:

- a replacement for the local checkout;
- a production executor;
- a magic repo-to-autonomous-engineer converter;
- a place to paste secrets into generated configs;
- proof that an agent has permission to deploy, restart, commit, or open PRs.

Use SourceBrief to know where to look and what to trust. Use the coding agent's normal tools to edit, test, commit, and request approval.
