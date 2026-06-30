# SourceBrief

> Connect source. Ask with citations. Wire into your agent.

SourceBrief gives coding agents a project evidence layer they can inspect before they edit. Connect a repo, docs folder, runbook, URL, upload, or folder bundle; ask a project question; get an answer with citations, snapshots, paths, line ranges, hashes, and follow-up read handles.

Use it when you need agents to answer with evidence, not vibes.

```text
source -> indexed snapshot -> cited answer -> agent pack -> safer coding agent
```

A useful SourceBrief setup has three pieces:

| Piece | What you get |
| --- | --- |
| **Cited evidence service** | MCP/API/CLI answers that point back to exact source sections. |
| **Human workbench** | Web UI for sources, indexing state, review, and cited questions. |
| **Agent pack** | Hermes skill packs and MCP/runtime guidance that teach agents when to ask SourceBrief first. Claude, Codex, Cursor, and other MCP clients use the same cited evidence service through their runtime setup paths. |

[Start here](docs/INSTALL_AND_USE.md) · [See the walkthrough](docs/WALKTHROUGH.md) · [Recipes](docs/RECIPES.md) · [Use it with agents](docs/AGENT_RUNTIME_USAGE.md) · [Contribute](CONTRIBUTING.md)

<img src="docs/assets/sourcebrief-mental-model.svg" alt="SourceBrief mental model from sources to snapshots to reviewed evidence to MCP/API agent access" width="100%" />

## Try the product path

Start the local stack, create a tiny demo source, ask for cited context, and validate the MCP-shaped path:

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
```

Then ask a project question and prepare a guarded agent runtime connection:

```bash
uv run sourcebrief ask "What does this source say about the retry policy?"
uv run sourcebrief runtime setup hermes --dry-run
```

Today, `runtime setup hermes` produces an inspectable dry-run plan. Local Hermes skill install/apply remains explicit, receipt-backed, and rollbackable; see [Agent runtime usage](docs/AGENT_RUNTIME_USAGE.md) when you are ready to apply.

Prefer the web console? Run `printf '%s/login\n' "$(make -s print-web-url)"`, sign in with the admin email/password in `.env`, connect a source, ask in Workbench, and inspect citations before generating or installing an agent pack.

## The problem

AI coding agents are becoming daily engineering tools, but the context layer is still handled like a hack:

- developers paste random files into prompts
- repo-local instruction files drift from reality
- runbooks, architecture notes, and source code live in different places
- generated answers often cannot prove which commit, file, line, or document version they came from
- every repo wants its own MCP server, prompt bundle, or ad hoc retrieval script
- teams have no review loop for stale, noisy, or low-value context

SourceBrief exists so agents can ask the project for cited, permission-scoped evidence before they act.

## See it work

<img src="docs/assets/sourcebrief-product-walkthrough.gif" alt="Animated SourceBrief walkthrough showing Command Center, Sources, and Workbench citations" width="100%" />

This walkthrough was captured from a real local SourceBrief stack with live API, workers, Postgres, Redis, two indexed resources, and a real `agent-context` response. See the full [product walkthrough](docs/WALKTHROUGH.md) and the captured [agent-context output](docs/examples/agent-context-output.md).

For 50Q launch proof with screenshots, use the screenshot-backed [50Q walkthrough](docs/evaluations/sourcebrief-launch-50q-20260627.md). It documents the exact command path, created workspace/project/resource, MCP/CLI scenarios, 50-question result, follow-up issues, and seven committed screenshots under [`docs/assets/screenshots/launch-50q/`](docs/assets/screenshots/launch-50q/).

A useful SourceBrief answer looks like this:

```text
Question: How does this project expose context to agents?

Answer:
SourceBrief exposes agent context through the project-scoped agent-context API
and the central MCP endpoint.

Evidence:
- apps/api/sourcebrief_api/main.py
  agent-context response shape and route
- apps/api/sourcebrief_api/main.py
  MCP tools/list and tools/call dispatch
- docs/ARCHITECTURE.md
  agent context and MCP runtime paths

The response includes runtime instructions, cited snippets, structured citations,
optional code symbols, and a token budget hint.
```

That is the product bar: an agent can act on the answer because every claim points back to source.

## Self-improvement without silent mutation

SourceBrief now ships a productized, artifact-based self-improvement loop for reviewing its own cited answers and PR-review evidence:

```text
cited answer or PR evidence
    -> review bundle
    -> local reviewer report with findings
    -> regression proposal
    -> deterministic validation gate
    -> staged patch/receipt
    -> review history
```

This is not an automatic optimizer and it does not rewrite prompts, skills, runtime packs, docs, or code by itself. The shipped path writes bounded JSON artifacts and human-reviewable staged patches; applying a change remains an explicit developer/PR action.

Use the web console for the product path:

1. Open **Self-improvement** from the left navigation.
2. Run **MVP smoke** to generate the complete bundle → report → proposal → gate → staged receipt chain.
3. Inspect **Review history** and artifact detail before applying any staged patch.
4. Run **sleep dry-run** only after multiple proposal artifacts exist; it mines recurrence candidates but still does not apply learning.

Use the CLI for automation or local evidence bundles:

```bash
uv run sourcebrief review mvp-smoke --out-dir ./artifacts/self-improvement-mvp-smoke
uv run sourcebrief review history list --dir ./artifacts/self-improvement-mvp-smoke
```

Start with the web console **Self-improvement** page, then use [Self-improvement MVP smoke](docs/SELF_IMPROVEMENT_MVP_SMOKE.md), [Review bundle runner](docs/REVIEW_BUNDLE_RUNNER.md), [Validation gate](docs/VALIDATION_GATE.md), and [Staged adoption](docs/STAGED_ADOPTION.md) for automation details.

## How SourceBrief works

```text
connect sources
    -> index versioned snapshots
    -> build chunks, embeddings, code symbols, and graphs
    -> review freshness, coverage, and low-value context
    -> publish pinned Context Packs when a workflow needs reviewed evidence
    -> serve cited evidence through MCP for agents, Workbench for humans, and CLI/HTTP for setup and automation
```

| Layer | What it means |
| --- | --- |
| Sources | Git repos, Markdown/runbooks, URLs, uploads, and zip folder bundles. |
| Snapshots | Exact indexed versions with commit, content hash, path, and timestamp provenance. |
| Evidence index | Chunks, retained sections, embeddings, code symbols, graph nodes/edges, and citation locators. |
| Review artifacts | Resource Maps, freshness, coverage, Context Packs, and Skill Exports for repeatable workflows. |
| Runtime access | Project-scoped MCP tools for agents, Workbench for humans, and CLI/HTTP for setup, CI, and fallback automation. |

A SourceBrief project is a context boundary for a product, service, or repo group. Put multiple repos, runbooks, architecture notes, URLs, uploads, and zip/folder bundles into one project, then let agents ask one authorized endpoint for evidence across the resources they are allowed to see.

## The agent workflow

<img src="docs/assets/sourcebrief-agent-workflow.svg" alt="Agent workflow showing SourceBrief evidence lookup before local checkout edits and tests" width="100%" />

SourceBrief changes the agent loop:

```text
coding agent gets an issue
    -> asks SourceBrief MCP for relevant docs, files, symbols, and risks
    -> reads exact cited sections from indexed snapshots
    -> edits and tests in the real checkout
    -> explains the change with citations instead of vibes
```

Start broad with MCP tools such as `sourcebrief.ask` or `sourcebrief.discover`. Use `sourcebrief.lookup` for docs/code/symbol discovery. Drill down with `sourcebrief.search`, `sourcebrief.read_section`, `sourcebrief.search_code`, `sourcebrief.grep_code`, `sourcebrief.read_file`, `sourcebrief.find_symbol`, and graph tools when the task needs exact evidence. Generated skills and agent packs teach this workflow to the runtime. The CLI is still important, but as the human/CI control plane and fallback path for setup, resource lifecycle, and validation—not as the main agent reasoning surface. Use SourceBrief to know where to look and what to trust; use the coding agent's normal tools to edit, test, commit, and open PRs.

### Agent runtime is not complete until all three pieces work

| Piece | Why it matters | Proof |
| --- | --- | --- |
| Generated skill / agent pack | Tells the agent when to use SourceBrief, what scope is pinned, citation policy, and mutation boundaries. | Runtime loads `SKILL.md`, `AGENTS.md`, or `CLAUDE.md`. |
| SourceBrief MCP | Gives the agent live cited evidence and drilldown tools. | `tools/list` shows SourceBrief tools and a smoke `tools/call` returns citations. |
| CLI fallback/control plane | Lets humans/CI/agents bootstrap, validate, doctor, install/uninstall skills, and manage resources when MCP is down or not yet configured. | `sourcebrief doctor` or `sourcebrief runtime validate --run` passes without printing tokens. |

For runtime setup, prompts, token scopes, remote-code safety, generated skills, and exact MCP tool guidance, read [Agent runtime usage](docs/AGENT_RUNTIME_USAGE.md).

## Before and after SourceBrief

| Task | Without SourceBrief | With SourceBrief |
| --- | --- | --- |
| Review a runtime-auth change | The agent searches whatever files are local, guesses which token path matters, and may miss docs or tests in sibling folders. | The agent asks SourceBrief for service-token evidence, gets cited API routes, CLI commands, MCP auth docs, and tests, then edits the real checkout with a source-backed plan. |
| Onboard to an unfamiliar repo group | The agent reads a README and a few files that fit in context, then invents a mental model. | The agent asks for architecture evidence across repos, docs, runbooks, symbols, and graph paths, then follows citations into exact sections before summarizing. |
| Triage a stale runbook | The agent repeats old instructions because they were pasted into the prompt. | SourceBrief reports the indexed snapshot, freshness/review state, and cited sections, so the agent can say what is current, stale, or missing. |

## Choose your path

| I want to... | Start here |
| --- | --- |
| Understand the product value and use it end-to-end | [Install and use](docs/INSTALL_AND_USE.md) |
| See the product before installing | [Product walkthrough](docs/WALKTHROUGH.md) |
| Try a deterministic 5-minute demo | [5-minute demo](docs/DEMO.md) |
| Run the full local stack | [Quick start](docs/QUICKSTART.md) |
| Connect Hermes, Claude Code, Codex, Cursor, or another MCP client | [Agent runtime usage](docs/AGENT_RUNTIME_USAGE.md) |
| Generate a guarded runtime config plan | [Runtime install plan](docs/RUNTIME_INSTALL_PLAN.md) |
| Learn the vocabulary | [Concepts](docs/CONCEPTS.md) |
| Understand the system design | [Architecture](docs/ARCHITECTURE.md) |
| Operate or debug the local stack | [Operations](docs/OPERATIONS.md) |
| Check alpha readiness and limits | [Project status](docs/STATUS.md) |
| Review real evaluation examples | [Awesome Agent Harness 50-question example](examples/awesome-agent-harness-50q/README.md) |
| Run the self-improvement proof path | [Self-improvement MVP smoke](docs/SELF_IMPROVEMENT_MVP_SMOKE.md) |
| Pick a product workflow | [Recipes](docs/RECIPES.md) |
| Use SourceBrief with a local agent | [Local-agent runtime example](examples/use-sourcebrief-with-local-agent/README.md) |

## Trust boundaries

<img src="docs/assets/sourcebrief-trust-boundary.svg" alt="SourceBrief runtime trust boundary showing evidence service, dry-run plan, local runtime config, MCP calls, and out-of-scope production mutations" width="100%" />

| Boundary | SourceBrief does | SourceBrief does not |
| --- | --- | --- |
| Project/resource access | Enforces workspace, project, resource, and token scopes. | Widen token-scoped access silently. |
| Runtime install | Generates inspectable plans, config snippets, validator commands, and rollback steps. | Silently edit Hermes, Claude, Codex, Cursor, shell profiles, or local runtime files. |
| Tokens | Uses placeholders or runtime-native environment references. | Put plaintext bearer tokens in generated plans, config snippets, or receipts. |
| Remote code | Serves indexed evidence with citations and exact-read handles. | Pretend indexed code is the editable local checkout. |
| Mutation | Can produce guarded proposals when explicitly enabled. | Deploy, restart services, mutate production, or open PRs without separate approval/tooling. |

SourceBrief is a local alpha for development and product exploration. It is not a public-internet-hardened SaaS distribution yet. See [project status](docs/STATUS.md) for shipped, experimental, and future work.

## Run it locally

This starts the real local stack and opens the web console.

### Prerequisites

- Docker with Compose
- Python 3.11
- [uv](https://docs.astral.sh/uv/)
- Node.js 20+
- npm
- git

On a clean Linux host, install `uv` with `curl -LsSf https://astral.sh/uv/install.sh | sh`, add `$HOME/.local/bin` to `PATH`, and run `uv python install 3.11` if Python 3.11 is not already available. The project venv uses `uv venv --python 3.11`; the host `python3` may be newer.

### Start the stack

```bash
git clone https://github.com/pingchesu/sourcebrief.git
cd sourcebrief

cp .env.example .env
# Edit SOURCEBRIEF_ADMIN_PASSWORD before the first startup.
# SourceBrief has no universal `changeme` login; see docs/DEFAULT_CREDENTIAL_POLICY.md.
# Keep SOURCEBRIEF_DEV_AUTH=false unless you explicitly want local header auth for CLI experiments.

python3 scripts/check_quickstart_prereqs.py

make compose-up
make quickstart-ready
```

If you will open the web console from another machine, set `NEXT_PUBLIC_API_BASE_URL` to the browser-visible API URL and add the web origin to `SOURCEBRIEF_CORS_ORIGINS` before `make compose-up`; changing the API base later requires `docker compose up -d --build`. The [Quick start](docs/QUICKSTART.md#remote-browser--self-host-setup) includes the exact remote/self-host snippet.

Open the web console:

```bash
printf '%s/login\n' "$(make -s print-web-url)"
```

Sign in with the admin email and password from `.env`:

```text
SOURCEBRIEF_ADMIN_EMAIL
SOURCEBRIEF_ADMIN_PASSWORD
```

From the UI, connect a source, inspect its indexing lifecycle, ask in Workbench, and review citations before using the context from an agent runtime. The full [Quick start](docs/QUICKSTART.md) includes CLI experiments, verification commands, and troubleshooting.

## Architecture, briefly

SourceBrief uses boring infrastructure on purpose:

```text
Web UI / CLI / Agent client
        -> FastAPI API + MCP routes
        -> PostgreSQL + pgvector
        -> Redis/RQ workers
        -> source snapshots, chunks, symbols, graphs, context packs, skill exports
```

Read the full design in [Architecture](docs/ARCHITECTURE.md).

## Contributing

Contributions are welcome. Please start with a GitHub issue for bugs, feature proposals, or evaluation/example requests so scope and acceptance criteria are visible before implementation. See [CONTRIBUTING.md](CONTRIBUTING.md) and the issue templates in `.github/ISSUE_TEMPLATE/`.

## Development

Useful commands:

```bash
make help       # list common commands
make compose-up # start local services
make verify     # full local acceptance gate
```

`make verify` runs lint, typecheck, unit tests, real-service integration tests, Docker Compose startup, migrations, QA smoke, and alpha eval. It is intentionally heavier than the quick start.

## Security and privacy

SourceBrief analyzes only the sources you connect or upload. Use built-in skip rules, bounded import settings, and redaction checks to reduce accidental indexing of secrets, vendored code, generated files, or private material.

Generated Skill Packs and runtime adapters should point agents back to SourceBrief citations. They should not embed an entire private source corpus.

## License

MIT
