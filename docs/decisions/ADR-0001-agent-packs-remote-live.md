# ADR-0001: Agent Packs use remote-live SourceBrief evidence by default

- Status: Accepted
- Date: 2026-07-01
- Issue: [#246](https://github.com/pingchesu/sourcebrief/issues/246)
- Time horizon: this decision should hold for the alpha-to-enterprise runtime packaging line; revisit when air-gapped/local-only customers become the primary deployment shape.

## Context

SourceBrief is evolving from source-aware search into runtime infrastructure for agents. The product needs a stable install model before expanding Repo Agent, Skill Export, and runtime install features.

The product question is:

> Is this a resource agent, a resource skill, or resource-as-graph? When a user installs a remote skill or agent, should the installed package query SourceBrief remotely, or should installation sync the resource/source/index/graph to local disk?

Existing SourceBrief docs and implementation already separate:

```text
Source -> Snapshot -> Evidence -> Review -> Runtime
```

A Git resource may be indexed remotely and cited with repo-relative paths, but it is not a local editable checkout. Runtime agents use SourceBrief to know what to trust, then use their normal local tools only when the user has provided a real checkout.

## Decision

Use a layered model:

```text
Resource Graph / Evidence Graph = canonical evidence truth
Repo Agent / Project Agent = user-facing published runtime view
Agent Pack / Skill Pack = installable thin runtime adapter
Skill Export = one packaging format for an Agent Pack
```

Generated Agent Packs / Skill Packs are **remote-live by default**. Installing a pack installs the runtime adapter, not the corpus.

The installed pack may include operating instructions, manifests, MCP config snippets, resource-map summaries, citation policy, smoke queries, and verification scripts. It must not sync full resources, source files, embeddings, vector indexes, raw chunks, or symbol/graph indexes to local disk as a normal install side effect.

Runtime evidence should come from SourceBrief MCP/API/RPC calls such as:

```text
ask -> lookup -> read_section/read_file/grep_code/find_symbol -> graph_query/graph_path
```

Local edits, tests, commits, and PR operations happen only in an explicitly provided local checkout outside SourceBrief.

## Options considered

| Option | Necessary criteria | Score / fit | Exit cost |
| --- | --- | --- | --- |
| Do nothing / keep terminology implicit | Fails: users and generated packs can confuse skill, agent, graph, and local sync. | Low. Blocks coherent packaging roadmap. | Medium; confusion hardens into public docs and APIs. |
| Full local resource sync at install | Fails auth revocation, audit, tenant isolation, and remote-indexed-code boundary by default. | Low for default; useful only for explicit local-only deployments. | High; synced private data is hard to revoke or purge. |
| Remote-only packs with no local fallback | Passes safety and clarity; weak offline/demo story. | Medium. Good base but too brittle for reproducibility. | Low. Can add bounded snapshots later. |
| Remote-live default with explicit `pinned-snapshot` and `local-mirror` modes | Passes safety, freshness, audit, and UX boundaries while keeping future offline options. | High. Best fit. | Low-to-medium. Modes are additive and policy-gated. |

## Rationale

Remote-live preserves SourceBrief's core value:

```text
permissioned + cited + fresh + auditable + versioned evidence graph
```

Default local sync would turn install into a data export path. That breaks or weakens:

- authorization and permission revocation;
- multi-tenant isolation;
- freshness and review-state enforcement;
- query/tool/citation auditability;
- path normalization and backend-path hiding;
- secret/code leak controls;
- the boundary between remote indexed evidence and editable local checkouts.

The core principle is:

> Install the skill, not the corpus. The skill teaches the agent how to query the SourceBrief graph.

## Modes

### `remote-live` — default

The pack contains metadata, instructions, resource-map summaries, runtime tool contracts, and validation scripts. Current evidence comes from SourceBrief MCP/API/RPC.

This is the default for normal Hermes, Claude Code, Codex, Cursor, and MCP-client usage.

### `pinned-snapshot` — explicit bounded evidence snapshot

The pack may include bounded excerpts, resource-map summaries, source-coverage summaries, graph-neighborhood summaries, and hashes.

This mode supports demos, reproducibility, and limited offline first-use. It must label itself as pinned evidence and must not make current claims without remote verification.

### `local-mirror` — exceptional opt-in

The pack or a related command may create a full local mirror only for air-gapped, local-only, CI-deterministic, or explicitly approved cache use cases.

This mode requires explicit flags, sensitivity labels, purge/update commands, TTL/freshness checks, drift detection, local access-control guidance, and audit receipts.

## Required boundaries

Generated packs must clearly state:

- installing an Agent Pack does not clone or sync the full repo;
- a SourceBrief indexed Git resource is not an editable working tree;
- SourceBrief does not run tests, deploy, restart services, or mutate production;
- generated packs do not include plaintext runtime tokens;
- local summaries/excerpts are not current evidence unless freshness policy says so;
- remote graph/code tools must not bypass workspace/project/resource auth;
- server-side generation must not silently write into `~/.hermes`, Claude, Codex, Cursor, or shell config; local apply must be explicit and receipt-backed.

## Consequences

### Positive

- The product model is easier to explain: graph is truth, agent is view, pack is adapter.
- Permission revocation and audit remain server-side and enforceable.
- Packs stay small, reviewable, regeneratable, and leak-scannable.
- Runtime agents can use current cited evidence without confusing SourceBrief snapshots with local checkouts.
- Future offline/local capabilities can be added as explicit modes rather than accidental install behavior.

### Negative / accepted costs

- Current answers require SourceBrief availability and runtime auth.
- Some users will expect local grep/cat after install; docs and generated skills must redirect them to remote tools.
- Offline and air-gapped stories require additional product work instead of being implicitly handled by install.
- Runtime doctor/smoke validation becomes mandatory for a good install experience.

## Failure modes and required behavior

| Failure mode | Required behavior |
| --- | --- |
| SourceBrief remote unavailable | Report remote evidence unavailable. Use only pinned summaries, with no current claims. |
| Token revoked | Stop. Do not fall back to a stale local full copy. |
| Context pack stale | Warn or block current claims based on pack policy. |
| Local checkout differs from indexed snapshot | Warn that the edit tree and cited evidence snapshot differ. |
| MCP/API tool missing | Doctor fails; generated skill must not claim unavailable tools. |
| Unauthorized resource | Fail closed without existence disclosure. |
| Local cache expired | Refuse or refresh; no silent stale answer. |
| Pack outdated | Suggest update; no silent self-mutation of installed runtimes. |

## Observability requirements

Runtime calls should record at least:

```text
query_run_id
workspace/project/resource scope
agent_pack_id/version/hash
runtime target
called tool
retrieval profile
freshness status
citation count
code:read allowed/denied
cache mode
latency
redaction counts
denial/block reason
```

Install and doctor flows should record at least:

```text
pack version/hash
runtime target
files written
MCP/API reachability
auth scope result
sample citation result
tool parity check
freshness result
rollback receipt
```

## Revisit triggers

Reopen this ADR if any of these become true:

- air-gapped or local-only deployments become the primary customer path;
- remote MCP/API latency makes normal agent workflows unusable;
- SourceBrief availability becomes a frequent blocker for runtime usage;
- security review approves an encrypted local cache with acceptable revocation/purge semantics;
- runtime vendors provide a standard signed package format with built-in secret and cache controls;
- customer policy requires local evidence mirrors for all agent runtime calls.

## Implementation follow-up

The first implementation issue is [#246](https://github.com/pingchesu/sourcebrief/issues/246). Planned slices:

1. Terminology/ADR docs and Agent Pack guide.
2. Manifest hardening for `mode`, local-payload, freshness, security, and runtime-tool fields.
3. Agent Pack doctor / smoke validation.
4. UI IA for Project/Repo Agent -> Install Agent Pack -> Validate Runtime.
5. Explicit `pinned-snapshot` export mode.
6. Explicit `local-mirror` mode only after the safer modes are stable.
