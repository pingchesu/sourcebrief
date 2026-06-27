# Contributing to SourceBrief

SourceBrief is an open-source project and contributions are welcome.

Before opening a pull request, please open or comment on a GitHub issue first. This keeps design discussion, scope, acceptance criteria, and implementation tradeoffs visible to maintainers and future contributors.

## Contribution flow

1. **Search existing issues** to avoid duplicates.
2. **Open an issue** using one of the templates:
   - Bug report: reproducible failures, logs, expected vs actual behavior.
   - Feature request / proposal: problem, non-goals, options, tradeoffs, and acceptance criteria.
   - Evaluation / example request: repo set, questions, expected evidence, and desired demo output.
3. **Wait for scope alignment** when the change affects product behavior, auth, data model, runtime/MCP contracts, or public docs.
4. **Create a focused PR** that links the issue and includes verification evidence.
5. **Keep secrets out of the repo.** Do not commit tokens, passwords, private repo URLs containing credentials, local `.env`, generated evidence with raw IDs/tokens, or production state.

Small typo/docs fixes can be opened directly, but please still explain the user-facing improvement in the PR body.

## Local verification

For most code changes, run:

```bash
make lint
make typecheck
.venv/bin/python -m pytest -q
docker compose config -q
git diff --check
```

For runtime, ingestion, MCP, retrieval, or UI changes, also run:

```bash
make qa-smoke
```

For README or launch-facing docs, prefer proof from a real local stack and include sanitized outputs or screenshots when relevant.

## PR expectations

A good PR includes:

- the linked issue (`Closes #...` or `Refs #...`);
- a concise summary of the behavior change;
- the commands run and their results;
- screenshots or captured output for UI/docs/demo changes;
- explicit notes for non-goals, compatibility risks, migrations, or rollback if applicable.

## Security and privacy

SourceBrief is designed around cited, permission-scoped evidence. Contributions should preserve these boundaries:

- do not widen project/resource/token scope silently;
- do not store plaintext tokens where an environment variable reference or scoped bearer token is expected;
- do not expose raw private corpus content in public examples;
- mark partial/limited imports honestly instead of presenting them as full-corpus proof.
