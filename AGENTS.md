# SourceBrief Agent Development Guide

This repository is developed as an enterprise-grade product, not as a demo. Agents working here must follow this guide unless the user explicitly overrides it in the current conversation.

## Product bar

SourceBrief is a source-aware agent context compiler. Treat every change as product work with user experience, API behavior, operational support, data correctness, and long-term maintainability implications.

Default expectations:

- Build the smallest correct increment, but complete the full product path for that increment.
- Prefer pragmatic, reversible changes over clever rewrites.
- Do not expose internal IDs, raw endpoints, bearer-token workflows, or UUID-first flows to users unless the feature is explicitly an admin/debug surface.
- Avoid mock-driven confidence. Use real services and real data fixtures whenever the change claims runtime behavior.
- When a task changes behavior, update docs and any agent runbooks needed for future maintainers.

## Required development workflow

For non-trivial product/code changes, use this sequence:

1. Create a fresh branch from current `main`.
2. Ask Claude Code to draft or implement the scoped change when repository code needs substantive edits.
3. Review the Claude Code output yourself. Do not trust agent self-reports.
4. Run Hermes adversarial review using one or more independent reviewer subagents.
5. Fix every blocker/major issue. Repeat review until blockers/majors are gone.
6. Run local verification with real services where relevant.
7. Perform a final enterprise/product review as the user's agent: UI, UX, API, operational behavior, and failure modes.
8. Open a PR with evidence in the body.
9. If the user has already authorized autonomous merge and all gates pass, merge the PR and sync local `main`.

Docs-only changes may use a lighter gate, but still require a clean branch, `git diff --check`, review of rendered content/claims, PR, and post-merge verification.

## Claude Code usage

Preferred non-interactive invocation from Hermes:

```bash
claude -p --permission-mode acceptEdits --effort max "$(cat /tmp/prompt.txt)"
```

If a local runner needs a custom `HOME`, `PATH`, or auth wrapper for Claude Code, configure that in the runner/session environment. Do not hard-code machine-specific paths in repository docs.

Prompt requirements:

- Include the exact goal, branch, repo path, constraints, and non-goals.
- Tell Claude Code to inspect existing code before editing.
- Tell Claude Code not to perform GitHub mutations or merge PRs.
- Require concrete verification commands in its final summary.
- For implementation tasks, require tests or explain why no test is meaningful.

If Claude Code is unavailable, unauthenticated, or returns no useful output:

- Record the actual failure.
- Continue with Hermes-native implementation/review only if the task remains safe and bounded.
- Do not claim Claude Code reviewed or implemented the change.

## Hermes adversarial review

Use Hermes subagents for independent critique before PR merge. At minimum, ask reviewers to look for:

- product/UX gaps,
- API contract problems,
- permission/security regressions,
- migration and compatibility risks,
- missing tests,
- operational failure modes,
- stale docs or misleading runbooks.

Review prompts must be self-contained: repo path, branch, diff scope, expected behavior, and known constraints. Treat review results as evidence, not truth. Verify claimed blockers yourself before changing code, and verify fixes after changing code.

Do not merge while any credible blocker or major issue remains.

## Verification gates

Choose the narrowest gate that proves the change, but do not under-test runtime behavior.

Common gates:

```bash
.venv/bin/ruff check apps packages tests scripts
.venv/bin/mypy apps packages scripts --ignore-missing-imports --follow-imports=silent
.venv/bin/pytest tests/unit -q
npm --prefix apps/web run lint
npm --prefix apps/web run build
git diff --check
```

Real integration gate when backend/runtime behavior changes:

```bash
SOURCEBRIEF_DEV_AUTH=true \
SOURCEBRIEF_RUN_REAL_INTEGRATION=1 \
SOURCEBRIEF_ALLOW_LOCAL_GIT=true \
make test-integration
```

If running `pytest` directly against the default Compose ports, use canonical SourceBrief DB identity unless `.env` intentionally overrides it for an existing local volume:

```bash
SOURCEBRIEF_DEV_AUTH=true \
SOURCEBRIEF_RUN_REAL_INTEGRATION=1 \
SOURCEBRIEF_ALLOW_LOCAL_GIT=true \
DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://sourcebrief:sourcebrief@localhost:${SOURCEBRIEF_POSTGRES_PORT:-55432}/sourcebrief}" \
REDIS_URL="${REDIS_URL:-redis://localhost:${SOURCEBRIEF_REDIS_PORT:-6380}/0}" \
.venv/bin/pytest tests/integration -q
```

Compose and smoke gate when deployment/runtime wiring changes:

```bash
docker compose up -d --build
docker compose ps
API_URL="${API_URL:-http://127.0.0.1:${SOURCEBRIEF_API_PORT:-18000}}"
WEB_URL="${WEB_URL:-http://127.0.0.1:${SOURCEBRIEF_WEB_PORT:-13000}}"
curl -fsS "$API_URL/readyz"
curl -fsS "$WEB_URL/api/health"
```

Browser gate when frontend/auth/navigation changes:

- Open `$WEB_URL` from the compose smoke gate, or another user-provided reachable URL for the same frontend instance.
- Exercise the user-facing path, not just static rendering.
- Check browser console for JavaScript errors.
- Verify copy, navigation, loading/error states, and API behavior.

For docs-only changes:

```bash
git diff --check
```

Also read the changed docs and ensure they do not promise unverified behavior.

## No-mock policy

Do not use mock-only tests as proof for behavior that depends on:

- Postgres schema or migrations,
- Redis/RQ worker behavior,
- API authentication/authorization,
- file ingestion or source snapshots,
- MCP tool behavior,
- frontend-to-backend flows.

Mocks are acceptable only for unit-level edge cases that cannot reasonably hit real services. They never replace integration evidence.

## GitHub and PR operations

Use the GitHub identity configured for the current checkout. Before mutating GitHub, verify the authenticated account and target repository:

```bash
env -u GH_TOKEN gh auth status
env -u GH_TOKEN gh repo view --json nameWithOwner,url,viewerPermission
```

If a non-default GitHub account is required, set `GH_CONFIG_DIR` in the shell/session environment rather than hard-coding a personal config path in this file.

For Git push over HTTPS, bypass ambient credential helpers:

```bash
git -c credential.helper= \
  -c credential.https://github.com.helper='!gh auth git-credential' \
  push origin <branch>
```

PR body must include:

- summary,
- scope and non-goals,
- compatibility/migration notes if relevant,
- verification commands and results,
- review status,
- docs impact.

Before merging:

- confirm branch/base,
- confirm local verification,
- check PR state and CI/checks,
- verify there are no unexpected open blockers.

After merging:

- sync local `main`,
- verify `git status --short --branch`,
- report PR URL and merge commit.

## SourceBrief repo conventions

Canonical repository:

- `origin`: the canonical GitHub repository for this checkout, with repository slug `sourcebrief`
- default branch: `main`

Product/runtime names are canonical SourceBrief names:

- API package: `sourcebrief_api`
- shared package: `sourcebrief_shared`
- worker package: `sourcebrief_worker`
- CLI package: `sourcebrief_cli`
- canonical env prefix: `SOURCEBRIEF_`
- canonical MCP tool prefix: `sourcebrief.`

Legacy compatibility may remain where intentionally supported:

- `CONTEXTSMITH_*` env fallbacks,
- legacy browser storage fallback,
- legacy CLI alias,
- hidden MCP call alias from `contextsmith.*` to `sourcebrief.*`.

Do not advertise legacy names in new user-facing docs unless documenting migration/compatibility.

## Frontend product standards

Design direction:

- mature enterprise console,
- clear information architecture,
- no UUID-first workflows,
- no user-facing bearer-token collection for ordinary login,
- no raw internal endpoint setup in normal product flows,
- no decorative gradients/emoji/testimonial filler.

Visual constraints:

- headings: `Space Grotesk` / `IBM Plex Sans`,
- body: `IBM Plex Sans`,
- mono: `IBM Plex Mono`,
- warm paper + graphite + ink/slate palette,
- small radius, border-first surfaces, minimal shadow.

Every frontend PR should be reviewed as if the user is paying for a mature enterprise product.

## Operational boundaries

Local source/config analysis is allowed. Production, cloud, secret, deployment, or remote-system mutations require explicit scope approval.

Never commit:

- `.env` with live secrets,
- OAuth material,
- raw production config,
- generated evidence artifacts unless explicitly source-owned,
- local runtime state.

When an action has side effects beyond the repo, state the scope and get approval first.

## Communication style

Report status with evidence:

- exact PR URL,
- commit SHA,
- commands run,
- pass/fail counts,
- known limitations.

Do not say something is complete unless it was actually exercised. If blocked, say what failed and what evidence is missing.
