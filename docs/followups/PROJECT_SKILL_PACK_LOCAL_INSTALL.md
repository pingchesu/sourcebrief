# Project skill-pack local install flow

Status: Implemented first Hermes local-install slice for issue #137
Related docs: `REMOTE_REPO_AGENT_SKILL_PACK_SPEC.md`, `context-artifact-compiler/C2-skill-pack-compiler-spec.md`, `RUNTIME_INSTALL_PLAN.md`
Decision: SourceBrief may generate project-specific skill packs through API/MCP, but local installation must be performed by a local CLI/apply step with receipt and rollback.

## Problem

A SourceBrief user wants this product experience:

```text
Connect my repo/docs
  -> SourceBrief indexes and reviews the evidence
  -> generate a project-specific skill
  -> install it into Hermes/Codex/Claude locally
  -> my agent now knows when and how to query SourceBrief for this project
```

The risky shortcut is remote server-side MCP directly writing into a local runtime profile such as `~/.hermes/skills`. That creates unclear authority, profile targeting, rollback, and privacy boundaries.

## Product goal

Make project-specific skills a first-class onboarding artifact while preserving local-control boundaries.

A generated skill pack should be:

- project-specific;
- context-pack/version pinned;
- citation disciplined;
- explicit about remote-only code access;
- installable locally with a receipt;
- reversible;
- safe to inspect before apply;
- free of plaintext bearer tokens and raw private corpus dumps.

## Non-goals

- Do not embed the full source corpus, vector indexes, symbol graphs, or raw chunks in the skill.
- Do not let a remote MCP server silently mutate local runtime files.
- Do not store plaintext passwords/tokens in skill files, receipts, docs, or generated configs.
- Do not claim production mutation, PR opening, or deployment capabilities unless separately implemented and explicitly approved.
- Do not make Hermes the only target; Hermes is first-class for apply, but the package model should be portable.

## Architecture

```text
SourceBrief server
  context pack + resource maps + runtime capabilities
       |
       v
  generate skill-pack package (API/MCP)
       |
       v
Local CLI/apply command
  validates package hash + target + profile
  writes runtime files locally
  writes install receipt
       |
       v
Agent runtime
  reads local skill/instructions
  calls SourceBrief MCP/API for evidence
```

## Package layout

A portable package should include runtime-specific adapters and common references:

```text
sourcebrief-agent.yaml
README.md
references/
  context-pack.json
  resource-map-summary.md
  citation-policy.md
  runtime-help.md
  freshness-and-coverage.md
examples/
  smoke-queries.md
hermes/
  SKILL.md
  install-notes.md
codex/
  AGENTS.md
claude/
  CLAUDE.md
scripts/
  verify-sourcebrief-runtime.sh
```

The Hermes `SKILL.md` must be self-contained enough to be installed alone, because Hermes skill install flows may not copy the full package directory. It should still reference SourceBrief tools and tell the agent when to ask for more evidence.

## MCP tools

MCP should expose generation and help, not silent local mutation.

### `sourcebrief.generate_skill_pack`

Returns a package preview and download path. It may generate/approve server-side artifacts, but it never writes local runtime files.

Input sketch:

```json
{
  "pack_key": "default",
  "version": 3,
  "title": "SourceBrief runtime skill",
  "summary": "Project-specific SourceBrief skill",
  "approve_comment": "Approved for local install."
}
```

Output sketch:

```json
{
  "status": "draft|approved",
  "skill_export": {"id": "...", "package_hash": "sha256:...", "files": []},
  "download_path": "/workspaces/.../skill-exports/.../download.zip",
  "download_available": true,
  "local_install": {
    "dry_run": "sourcebrief skill install --package <package-dir-or-zip> --target hermes --dry-run",
    "apply": "sourcebrief skill install --package <package-dir-or-zip> --target hermes --apply",
    "uninstall": "sourcebrief skill uninstall --receipt <receipt.json>"
  }
}
```

### `sourcebrief.get_runtime_help`

Returns MCP/CLI usage guidance for the current project/runtime:

```json
{
  "runtime": "hermes",
  "mcp_tools": ["sourcebrief.ask", "sourcebrief.lookup", "sourcebrief.read_section", "sourcebrief.grep_code"],
  "cli_fallback": [
    "sourcebrief doctor --workspace \"SourceBrief CLI Demo\" --project \"First useful moment\"",
    "sourcebrief runtime validate --plan plan.json --run",
    "sourcebrief skill install --package ./sourcebrief-skill --target hermes --dry-run"
  ],
  "required_env": ["SOURCEBRIEF_API_URL", "SOURCEBRIEF_TOKEN"],
  "safety_notes": ["No plaintext token is stored in the skill pack."]
}
```

## CLI commands

### Generate/export

```bash
sourcebrief skill export \
  --workspace "SourceBrief CLI Demo" \
  --project "First useful moment" \
  --pack-key default \
  --pack-version 3 \
  --approve-comment "Approved for local install." \
  --out ./sourcebrief-skill
```


### Install locally

```bash
sourcebrief skill install \
  --package ./sourcebrief-skill \
  --target hermes \
  --profile default \
  --dry-run

sourcebrief skill install \
  --package ./sourcebrief-skill \
  --target hermes \
  --profile default \
  --receipt ./sourcebrief-skill-receipt.json \
  --apply
```

### Uninstall / rollback

```bash
sourcebrief skill uninstall --receipt ./sourcebrief-skill-receipt.json
```

## Install receipt

Receipt fields:

```json
{
  "schema_version": "sourcebrief.skill-install-receipt.v1",
  "target": "hermes",
  "profile": "default",
  "skill_name": "sourcebrief-default",
  "skill_dir": "~/.hermes/skills/sourcebrief-default",
  "package_hash": "sha256:...",
  "context_pack": {"pack_key": "default", "version": 3, "pack_hash": "sha256:..."},
  "files": [
    {
      "package_path": "SKILL.md",
      "target_path": "~/.hermes/skills/sourcebrief-default/SKILL.md",
      "existed_before": false,
      "sha256_before": null,
      "sha256_after": "sha256:..."
    }
  ],
  "installed_at": "2026-01-01T00:00:00Z"
}
```

The receipt must not include the token value.

## Hermes-specific install contract

Hermes first slice:

- install generated `SKILL.md` plus package references/examples/scripts into the target Hermes skill directory;
- accept package directories or `.zip` packages;
- do not modify another Hermes profile unless the user passes `--profile` explicitly;
- do not edit MCP config unless the user separately runs runtime apply or passes a future explicit `--include-runtime-config --apply` flag;
- run read-only validation after install:
  - skill file exists;
  - no plaintext token-like string;
  - package hash matches;
  - SourceBrief MCP server is configured or runtime help says it is missing;
  - `sourcebrief.ask` smoke succeeds when the runtime/MCP is available.

## Generated skill content requirements

The installed skill must tell the agent:

- what project/resources are covered;
- the pinned context pack key/version;
- when to use SourceBrief before answering/editing;
- preferred MCP tools and order: `ask` -> `lookup` -> `read_section` / `read_file` / `grep_code`;
- CLI fallback commands: `doctor`, `runtime validate`, `skill install`, `skill uninstall`;
- citation policy: do not claim facts without cited SourceBrief evidence;
- remote-only path policy: citation paths are repo-relative, not local files;
- stale/partial coverage behavior;
- mutation boundary: read-only by default, patch/PR only if separately enabled.

## Security and ownership

- Server-generated files are untrusted data until validated locally.
- Local apply reconstructs target file paths; it must not trust package paths containing `..`, absolute paths, symlinks, or profile escapes.
- Package preview and install plan are safe to display, but may reveal project names, repo names, path names, endpoint URLs, and context pack metadata.
- Installing a skill is a local mutation and must require `--apply` or equivalent user approval.
- Rollback must refuse if the installed files were modified after install unless `--force` is passed.

## Acceptance criteria

- [x] API/MCP can generate a skill-pack preview/download handle for an approved context pack.
- [x] CLI can dry-run and apply a Hermes skill install from that package.
- [x] Install writes a receipt and uninstall/rollback works.
- [x] Skill and receipt contain env var names but no plaintext tokens.
- [x] Path traversal and profile escape tests fail closed.
- [x] Generated `SKILL.md` includes SourceBrief MCP and CLI usage guidance.
- [x] Product-led example demonstrates local install and agent usage without requiring the target source repo to be locally checked out.

## PR slicing recommendation

1. Spec/docs + product-led example skeleton.
2. Server package preview model and tests.
3. CLI `skill export/install/uninstall` guarded local apply for Hermes.
4. MCP `generate_skill_pack` and `get_runtime_help` wrappers.
5. Real local-agent example with captured sanitized output.
