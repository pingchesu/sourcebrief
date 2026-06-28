# SourceBrief recipes

Recipes are user-facing starting points. They let someone choose a workflow before learning SourceBrief internals.

A recipe defines:

- what sources to connect;
- the first useful questions to ask;
- what good cited evidence should include;
- what the generated agent pack should teach the runtime;
- what the recipe intentionally does not do.

## How to use recipes today

Recipes are documentation-level guidance in the current alpha. First verify the local stack with the demo path, then import the source that matches the recipe before asking recipe-specific questions.

```bash
# One-time local stack/auth smoke. See README for the full password/login setup.
make compose-up
make quickstart-ready
uv run sourcebrief quickstart-demo --validate-mcp

# Then connect the source for the recipe you picked. Example for repo onboarding:
uv run sourcebrief resource add-repo \
  --name "My Repo" \
  --repo-url https://github.com/example/my-repo.git \
  --refresh --wait

uv run sourcebrief ask --resource "My Repo" "Where should a new agent start?"
uv run sourcebrief runtime setup hermes --dry-run
```

Future CLI work should make recipes executable, for example:

```bash
sourcebrief recipe init repo-onboarding ./my-repo
sourcebrief recipe ask repo-onboarding "Where should a new agent start?"
```

## Recipe: repo onboarding

**Promise:** understand an unfamiliar repository with cited files, docs, symbols, and risk areas.

Sources:

- Git repository.
- README, architecture docs, contributor docs, test docs.
- Optional runbooks or release notes.

First questions:

- "What is this repository responsible for?"
- "Where are the main entrypoints?"
- "What commands prove a safe local change?"
- "What files should an agent read before changing authentication?"

### Copy/paste start

1. Connect: add the target Git repo with `uv run sourcebrief resource add-repo --name "My Repo" --repo-url <https-url> --refresh --wait`.
2. Ask: "Where should a new agent start in this repository?"
3. Good result should cite README/architecture docs, entrypoint files, and test or contribution docs.
4. Verify: ask "Which command should I run before opening a PR?" and expect cited test/docs evidence.

Good evidence includes:

- README or docs overview citation.
- Entry-point file paths and line ranges.
- Test/verification command citations.
- Known non-goals or status boundaries.

Agent pack behavior:

- Tell the agent to ask SourceBrief before summarizing architecture or editing unfamiliar areas.
- Prefer `sourcebrief.ask`, then `sourcebrief.lookup`, then exact reads such as `read_section`, `read_file`, or `grep_code`.
- Remind the agent that indexed paths are evidence, not the editable local checkout.

Non-goals:

- No autonomous production mutation.
- No claim that every generated answer is complete without citations.

## Recipe: PR review

**Promise:** give an agent the project contract before reviewing a diff.

Sources:

- Target repository.
- Architecture docs.
- Testing docs.
- Security/auth docs.
- Release or deployment docs if relevant.

First questions:

- "What project contracts affect these touched paths?"
- "What tests or smoke gates should cover this change?"
- "What auth, tenant, data, or runtime boundaries are nearby?"
- "What docs might go stale if this change merges?"

### Copy/paste start

1. Connect: add the repo and any review/runbook docs that define the contract.
2. Ask: "What should a reviewer inspect before changing <touched path or feature>?"
3. Good result should cite touched-path context, related tests, and boundary docs.
4. Verify: ask "Which test or smoke gate would catch a regression here?"

Good evidence includes:

- Exact touched-path context.
- Related tests and docs.
- Security and permission boundaries.
- Operational or migration implications.

Agent pack behavior:

- Instruct reviewers to cite SourceBrief evidence before making architectural claims.
- Separate confirmed blockers from questions and follow-ups.
- Keep mutation/PR posting outside SourceBrief unless separately authorized.

Non-goals:

- No replacement for running tests on the real checkout.
- No source-control mutation from the recipe itself.

## Recipe: incident runbook

**Promise:** turn runbooks and source into an on-call evidence assistant.

Sources:

- Runbooks.
- Service repository.
- Alert docs.
- Dashboards or metric docs.
- Postmortems if approved.

First questions:

- "What should I check first for this alert?"
- "Which metrics prove the system is healthy?"
- "What are the known failure modes and rollback steps?"
- "Which commands are read-only and which require approval?"

### Copy/paste start

1. Connect: add the runbook and the service repo or operations docs.
2. Ask: "What should I check first for <alert name>?"
3. Good result should cite runbook sections, health checks, and approval boundaries.
4. Verify: ask "Which steps are read-only and which need approval?"

Good evidence includes:

- Runbook section citations.
- Operational command citations.
- Safety/approval boundary citations.
- Known failure-mode examples.

Agent pack behavior:

- Force read-only diagnosis first.
- Call out approval boundaries before restart, deploy, secret, or production actions.
- Prefer current source/runbook citations over memory.

Non-goals:

- No direct production action execution.
- No bypass around incident ownership or approval policy.

## Recipe: API service

**Promise:** map routes, auth, models, migrations, and API contracts.

Sources:

- API service repo.
- OpenAPI/route docs if available.
- Database migration docs.
- Auth/permission docs.
- Client SDK docs.

First questions:

- "Which routes implement this capability?"
- "Where is authorization enforced?"
- "Which database tables and migrations are involved?"
- "What compatibility risks does this API change create?"

### Copy/paste start

1. Connect: add the API repo plus API/auth/migration docs.
2. Ask: "Where is <capability> implemented and authorized?"
3. Good result should cite route handlers, auth middleware, schema/model files, and tests.
4. Verify: ask "What compatibility risk should I check before changing this endpoint?"

Good evidence includes:

- Route handler citations.
- Auth middleware citations.
- Schema/model/migration citations.
- Tests for permission denial and success paths.

Agent pack behavior:

- Require auth and tenant-boundary evidence before editing API behavior.
- Prefer exact file/line reads for route and model details.
- Warn when indexed code is stale relative to the local checkout.

Non-goals:

- No generated API client publication.
- No migration execution.

## Recipe: frontend product

**Promise:** give product agents UI routes, components, API calls, and UX docs.

Sources:

- Frontend app repo.
- API docs.
- Product specs and screenshots.
- Design-system docs.

First questions:

- "What user journey owns this screen?"
- "Which component and API call render this state?"
- "What loading, empty, and error states already exist?"
- "What should not expose internal IDs to users?"

### Copy/paste start

1. Connect: add the frontend repo, API docs, and product/design docs.
2. Ask: "Which route, component, and API call own <screen or journey>?"
3. Good result should cite the route/component, API client, and UX/product spec.
4. Verify: ask "What loading, empty, and error states must this UI preserve?"

Good evidence includes:

- Route/component citations.
- API client citations.
- UX/product spec citations.
- Status/non-goal citations.

Agent pack behavior:

- Prioritize information architecture and user-facing language.
- Flag UUID-first or raw-token flows in ordinary UX.
- Require browser verification for user-facing changes.

Non-goals:

- No visual redesign without product scope.
- No decorative polish that hides incomplete flows.

## Recipe: multi-repo platform

**Promise:** ask across repo groups without manually pasting context.

Sources:

- Multiple service repos.
- Shared libraries.
- Architecture docs.
- Deployment/runbook docs.

First questions:

- "Which repo owns this capability?"
- "What cross-service contract connects these components?"
- "Which deployment or compatibility boundary matters?"
- "What should an agent inspect before changing this shared interface?"

### Copy/paste start

1. Connect: add the relevant service repos, shared libraries, architecture docs, and runbooks.
2. Ask: "Which repo owns <capability> and what contract connects the services?"
3. Good result should cite multiple resources with provenance and contract docs.
4. Verify: ask "What should an agent inspect before changing this shared interface?"

Good evidence includes:

- Resource-level provenance.
- Cross-resource citations.
- Contract and ownership docs.
- Graph/path evidence where available.

Agent pack behavior:

- Ask SourceBrief before assuming ownership from local filenames.
- Use resource-aware lookup and exact reads.
- Keep generated pack scoped to approved resources/context packs.

Non-goals:

- No automatic cross-repo PR creation.
- No silent broadening beyond authorized resources.
