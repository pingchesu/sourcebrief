# Out-of-box product plan

SourceBrief should feel less like infrastructure you configure and more like a product that makes an agent useful on a project in minutes.

This plan turns the inspiration from Cortex RAG and Hyper-Extract into SourceBrief-specific work. The goal is not to copy their architecture. The goal is to copy the feeling: clear promise, short install path, visible first result, reusable templates, and a next step that makes the agent better.

## Product goal

A new user should be able to say:

> I connected a repo or docs folder, asked one project question, saw cited evidence, and installed a project-aware agent pack without learning SourceBrief internals first.

## First useful moment

The product must optimize for this sequence:

```text
start local SourceBrief
  -> add one source
  -> wait for indexed snapshot
  -> ask one question
  -> inspect citations
  -> generate/install an agent pack
```

The user-facing language is:

```text
Connect source. Ask with citations. Wire into your agent.
```

Internal concepts such as Resource Maps, Context Packs, graph indexes, snapshots, and token scopes still exist, but they should not block first use.

## Non-goals

- Do not reposition SourceBrief as a generic chatbot, vector database wrapper, or single-page RAG demo.
- Do not hide citation, freshness, permission, and mutation boundaries to make onboarding look simpler.
- Do not claim public SaaS or enterprise SSO readiness until those gates exist.
- Do not silently mutate Hermes, Claude, Codex, Cursor, shell profiles, or local runtime config.
- Do not embed private corpora inside generated skills or examples.

## Competitive lessons to adopt

### From Cortex RAG

What to reuse:

- Strong top-of-page promise.
- Visual flow before deep architecture.
- Tiny quickstart with obvious prerequisites.
- Demo-first language: upload/connect, ask, answer, citations.

What not to reuse:

- Demo-only engineering bar.
- Unverified hype around advanced RAG labels.
- Install scripts that mutate user machines too aggressively.
- Product claims that outpace tests and security boundaries.

### From Hyper-Extract

What to reuse:

- Short CLI verbs.
- Recipe/template gallery.
- Clear installed artifact: a Knowledge Abstract, graph, Obsidian export, or MCP server.
- Packaged docs and examples that demonstrate real workflows.

What not to reuse blindly:

- Raw API-key setup as the ordinary product path for agents.
- Template-count claims unless generated from source and tested.
- Treating local extraction artifacts as enough for governed team context.

## Product shape

SourceBrief should present four surfaces:

1. **Web console** — human onboarding, source import, Workbench citations, review, and runtime install guidance.
2. **CLI** — bootstrap, automation, doctor, runtime setup, skill export/install, and CI fallback. Recipe commands are a future wrapper over existing source import and ask flows.
3. **MCP/API** — cited runtime evidence for agents.
4. **Agent pack** — generated project instructions plus local install receipt and rollback.

## Golden-path UX

### Current path to advertise today

```bash
git clone https://github.com/pingchesu/sourcebrief.git
cd sourcebrief
cp .env.example .env
python3 - <<'PY'
from pathlib import Path
import secrets
p = Path(".env")
text = p.read_text()
text = text.replace(
    "SOURCEBRIEF_ADMIN_PASSWORD=change-me-before-compose-up",
    "SOURCEBRIEF_ADMIN_PASSWORD=sourcebrief-local-" + secrets.token_urlsafe(12),
)
p.write_text(text)
PY
python3 scripts/check_quickstart_prereqs.py
make compose-up
make quickstart-ready
export SOURCEBRIEF_API_URL="$(make -s print-api-url)"
export SOURCEBRIEF_ADMIN_EMAIL="$(grep '^SOURCEBRIEF_ADMIN_EMAIL=' .env | cut -d= -f2-)"
export SOURCEBRIEF_ADMIN_PASSWORD="$(grep '^SOURCEBRIEF_ADMIN_PASSWORD=' .env | cut -d= -f2-)"
uv run sourcebrief login --email "$SOURCEBRIEF_ADMIN_EMAIL" --password-env SOURCEBRIEF_ADMIN_PASSWORD
uv run sourcebrief quickstart-demo --validate-mcp
uv run sourcebrief ask "What does this source say about the retry policy?"
uv run sourcebrief runtime setup hermes --dry-run
```

This is accurate for the current repo and should be kept green. The runtime setup command intentionally stays dry-run until a user explicitly applies or installs the generated Hermes artifacts.

### Target path to build next

```bash
sourcebrief init --local
sourcebrief quickstart ./my-repo --runtime hermes
sourcebrief ask "Where is authentication implemented?"
sourcebrief agent-pack install hermes --dry-run
```

This target is intentionally fewer commands. It may wrap existing lower-level commands, but it must keep guarded apply semantics.

## Recipes

Create first-class recipes that map user intent to source import, suggested questions, context-pack policy, and runtime pack language.

Initial recipe backlog:

| Recipe | User promise | First questions |
| --- | --- | --- |
| `repo-onboarding` | Understand an unfamiliar codebase with cited files and docs. | architecture, entrypoints, test commands, risk areas |
| `pr-review` | Give an agent the project contract before reviewing a diff. | touched paths, auth/data boundaries, tests, docs drift |
| `incident-runbook` | Turn runbooks and source into an on-call evidence assistant. | escalation path, health checks, known failure modes |
| `api-service` | Map routes, auth, models, migrations, and API contracts. | auth flow, endpoint ownership, migration risk |
| `frontend-product` | Give product agents UI routes, components, API calls, and UX docs. | user journey, API dependency, route/component mapping |
| `multi-repo-platform` | Ask across repo groups without manually pasting context. | cross-service contract, ownership, deployment boundary |

## Milestones

### M1 — Product-front-door rewrite

Scope:

- README top section becomes product-led.
- Quickstart advertises the current accurate path and one clear first useful moment.
- Docs map links to this plan and recipe gallery.
- Claims are checked against `docs/STATUS.md`.

Acceptance:

- A new reader can understand SourceBrief in 10 seconds.
- The first command path is visible without reading deep architecture docs.
- No claim says SourceBrief is public-SaaS/enterprise hardened today.

Verification:

```bash
git diff --check
python3 scripts/check_quickstart_prereqs.py
make help
```

### M2 — Recipe gallery

Scope:

- Add `docs/RECIPES.md` with the six initial recipes.
- Each recipe includes inputs, first questions, expected citations, runtime pack behavior, and non-goals.
- Add links from README and docs map.

Acceptance:

- A user can choose a workflow without first learning Resource Map vs Context Pack.
- Each recipe has a concrete copy-paste prompt and a verification question.

### M3 — One-command local quickstart wrapper

Scope:

- Add a CLI wrapper such as `sourcebrief quickstart <path>` or `sourcebrief init --local` if product naming is finalized.
- Wrap existing compose, project/resource creation, index wait, ask, and optional MCP smoke.
- Keep advanced commands available.

Acceptance:

- Fresh local stack reaches first cited answer with one primary command after prerequisites.
- Failure output is actionable and points to `sourcebrief doctor`.
- No plaintext tokens are printed.

### M4 — Guided agent connection

Scope:

- Add a higher-level wrapper over runtime setup + skill export/install.
- Keep `--dry-run` as default and require explicit `--apply` for local mutation.
- Print receipt, rollback, validation, and MCP smoke instructions.

Acceptance:

- Hermes path proves skill installed and MCP ask returns citations.
- Missing MCP config or token scope failures produce repair guidance.
- Generated skill contains no raw corpus or plaintext tokens.

### M5 — Web onboarding wizard

Scope:

- First-run flow: create project, add source, index, ask, install agent.
- Hide UUID-first controls from normal path.
- Keep admin/debug escape hatches separate.

Acceptance:

- Browser walkthrough reaches a cited answer and runtime install CTA.
- Console errors are clean.
- Screenshots/GIF are refreshed after the flow ships.

### M6 — Autonomous review agent and improvement loop

Scope:

- Treat review as a separate agent run over durable artifacts, not as another chat transcript pass.
- Capture task brief, source/resource IDs, generated answers, citations, tool outputs, verification logs, and user corrections as a review bundle.
- Run a reviewer agent asynchronously after important answers, PRs, demos, or recipe runs.
- Classify findings as blocker, major, minor, or learning candidate.
- Convert repeated validated issues into regression questions, recipe updates, docs fixes, or skill/rule updates.

Acceptance:

- The reviewer can reproduce the answer from the bundle without reading a full day of chat.
- Every improvement has evidence: original failure, reviewer finding, fix, and rerun result.
- The loop opens an issue or creates a proposed patch for human approval; it does not silently change production behavior.
- Review cost is bounded by triggers and sampling, not every message.

## Observability and operations

Out-of-box does not mean opaque. Every guided flow should report:

- API and web health.
- Current selected workspace/project.
- Source import/index stage.
- Snapshot freshness and skipped-file summary.
- Citation count and resource coverage.
- Runtime/MCP validation status.
- Next repair command on failure.

## Reversibility

- Docs changes are reversible by normal git revert.
- CLI wrappers should call existing lower-level commands so users can drop down when needed.
- Runtime install remains receipt-backed and rollbackable.
- Web onboarding should create ordinary workspace/project/resource records, not special demo-only state.

## Ownership

- Product owner: SourceBrief product/runtime owner.
- Runtime integration owner: agent-runtime/skill-pack maintainer.
- Operational owner: local-stack/CLI maintainer.
- Review owner: final PR reviewer must check product attractiveness, DX correctness, technical accuracy, and documentation IA.

## Evidence needed before closing the full initiative

- Fresh local demo evidence from a clean checkout.
- One repo import path with a real cited answer.
- One docs/runbook import path with a real cited answer.
- One Hermes runtime pack install or dry-run validation path.
- Reviewer notes showing no major product/DX/accuracy/IA blockers.
