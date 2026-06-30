# SourceBrief launch proof skill export approved #226 v2

This is a generated SourceBrief Skill Pack for Context Pack `launch-proof-212` v`1`.

Status: `draft`. External install/copy is allowed only after the export is `approved` in SourceBrief.

## What this package contains

- A compact `SKILL.md` front door.
- Resource-map-first references under `references/`.
- Task playbooks for onboarding, architecture, debugging, and change-impact work.
- Smoke queries for value validation.
- A safe read-only runtime verification script.

## Coverage

- Resources: 1
- Context artifacts: 1
- Citations: 2203

## Install

Copy the package directory into the target runtime skill directory only after SourceBrief approval. Keep `manifest.json` beside the skill for audit.

## Runtime requirement

Agents must have SourceBrief MCP/API access. This package contains no source corpus and no credentials.

## Compatibility

- Hermes: `SKILL.md` compatible.
- Claude Code / Codex / Cursor: usable as a generic agent skill package if the runtime can read `SKILL.md` and references.

## Verification

Run the read-only check:

```bash
bash scripts/verify-sourcebrief-runtime.sh
```

Then ask at least one question from `examples/smoke-queries.md` and verify cited SourceBrief evidence is returned.
