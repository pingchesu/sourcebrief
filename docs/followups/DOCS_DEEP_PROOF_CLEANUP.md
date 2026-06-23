# Deep docs proof and IA cleanup

## Problem

The front door now explains SourceBrief better, but deep docs still mix product concepts, runtime guidance, specs, milestones, and internal history. The next docs pass should make runtime usage and proof artifacts complete without turning the README back into a wall of text.

## Scope

- Rewrite `CONCEPTS.md` around the product mental model from README.
- Split or restructure runtime guidance into clear paths:
  - Hermes
  - Claude Code
  - Codex
  - Cursor/custom MCP.
- Add proof artifacts for Resource Map, Context Pack, Skill Pack export, graph/query output, and runtime validation where available.
- Clean the docs index so specs/milestones/archive are discoverable but not primary onboarding paths.
- Add status labels for alpha/experimental/archive docs.

## Non-goals

- No new product capabilities unless required to produce proof artifacts.
- No deletion of historical specs without separate review.
- No fake screenshots or mock-only output.

## Acceptance criteria

- A new reader can move from README -> concepts -> runtime guide without hitting milestone/spec walls.
- Runtime-specific docs include exact config shape, auth boundary, reload/validation step, and failure modes.
- Proof artifacts are either captured from real local runs or explicitly marked as unavailable/follow-up.
- Archive/spec docs are demoted with clear labels.
- Docs links and examples pass sanity checks.

## Verification

- Markdown link/fence checks.
- Secret/raw ID scan for new proof artifacts.
- At least two docs review passes: reader/product and technical/security.
- Real local stack evidence for any new proof claim.
