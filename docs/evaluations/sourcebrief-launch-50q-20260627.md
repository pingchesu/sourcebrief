# SourceBrief screenshot-backed 50Q launch walkthrough

Issue: [#141](https://github.com/pingchesu/sourcebrief/issues/141)
Run date: 2026-06-27
Commit under test: `abc4c717c4f1affa917b1a3f476acdea7684f5f4`

## Verdict

`PASS` for mechanical launch walkthrough evidence, with 3 answer-quality follow-ups opened.

| Check | Result |
| --- | --- |
| Local services | API `/readyz` and web `/api/health` reachable |
| Auth path | Session login; no raw token-first UI path |
| Workspace/project UX | Human-readable names: `50Q Launch Walkthrough …` / `SourceBrief 50Q Product Walkthrough` |
| Import | Bounded real SourceBrief repository git bundle import succeeded |
| Indexed evidence | 240 documents, 1,710 chunks, 1,916 symbols, 1,710 embeddings, 2,350 graph nodes |
| 50Q mechanical run | 50/50 passed with citations |
| Scenario coverage | MCP context, bounded grep drilldown, and CLI fallback search passed |
| Screenshots | 7 sanitized screenshots committed below |

## Screenshots

1. Login screen

   ![Login screen](../assets/screenshots/launch-50q/01-login.png)

2. Command Center / dashboard

   ![Dashboard](../assets/screenshots/launch-50q/02-dashboard.png)

3. Workspace/project selection by name

   ![Workspace and project settings](../assets/screenshots/launch-50q/03-selection-settings.png)

4. Source import lifecycle and partial corpus warning

   ![Sources import lifecycle](../assets/screenshots/launch-50q/04-import-sources.png)

5. Workbench / citation surface

   ![Workbench citations](../assets/screenshots/launch-50q/05-workbench-citations.png)

6. Agent profile / runtime configuration surface

   ![Agent profile](../assets/screenshots/launch-50q/06-agent-profile.png)

7. 50Q report summary

   ![50Q report](../assets/screenshots/launch-50q/07-eval-report.png)

## Runnable command

From a local SourceBrief checkout with compose services available:

```bash
source .venv/bin/activate
python scripts/launch_50q_walkthrough.py \
  --skip-compose \
  --question-limit 50 \
  --artifact-dir artifacts/sourcebrief-launch-50q-run
```

To include service startup in the same command, omit `--skip-compose`:

```bash
python scripts/launch_50q_walkthrough.py \
  --question-limit 50 \
  --artifact-dir artifacts/sourcebrief-launch-50q-run
```

Generated artifacts stay under ignored `artifacts/` by default. Only sanitized screenshots and this report are committed.

## Actual operation walkthrough

The recorded run followed this concrete path:

1. **Prepare the local runtime.**

   ```bash
   cp .env.example .env
   # Set SOURCEBRIEF_ADMIN_PASSWORD in .env.
   make compose-up
   make quickstart-ready
   make venv
   npm --prefix apps/web install
   ```

   Proof captured by screenshots: login screen and Command Center.

2. **Run the launch-proof runner against the real stack.**

   ```bash
   source .venv/bin/activate
   python scripts/launch_50q_walkthrough.py \
     --skip-compose \
     --question-limit 50 \
     --artifact-dir artifacts/sourcebrief-launch-50q-run
   ```

   The runner can also start Compose itself if `--skip-compose` is omitted.

3. **Authenticate through the normal local auth path.**

   The runner uses, in order:

   - `SOURCEBRIEF_QA_TOKEN` or `SOURCEBRIEF_TOKEN`, if provided;
   - otherwise `SOURCEBRIEF_ADMIN_EMAIL` + `SOURCEBRIEF_ADMIN_PASSWORD` from `.env` via `/auth/login`;
   - otherwise `SOURCEBRIEF_DEV_AUTH=true` only for disposable local dev runs.

   The recorded proof used session login. Screenshots do not expose the session token.

4. **Create human-named workspace/project.**

   The script creates:

   - workspace: `50Q Launch Walkthrough <timestamp>`;
   - project: `SourceBrief 50Q Product Walkthrough`.

   The primary user flow is name/slug-first. Raw IDs are redacted from committed reports and not shown as the user-facing path.

5. **Import a bounded real SourceBrief repo bundle.**

   The script builds a local git bundle from the current `main` and adds it as a git resource named `SourceBrief repository launch import` with bounded launch-proof budgets:

   - `max_repo_files=320`
   - `max_file_bytes=120000`
   - `max_repo_bytes=18000000`

   The run waits for the index run to finish. The captured run intentionally surfaces partial/bounded coverage instead of hiding it.

6. **Run the fixed 50-question manifest.**

   Question bank: [`examples/sourcebrief-launch-50q/questions.json`](../../examples/sourcebrief-launch-50q/questions.json)

   Each question calls the project `agent-context` endpoint with the imported resource scoped in. The report separates:

   - mechanical API/citation pass/fail;
   - answer-quality warnings;
   - coverage warnings;
   - citation previews.

7. **Exercise runtime scenarios beyond the 50 questions.**

   The runner also calls:

   - MCP `tools/list`;
   - MCP `sourcebrief.get_agent_context`;
   - MCP `sourcebrief.grep_code` with a bounded path glob;
   - CLI `sourcebrief --json search` as fallback/control-plane proof.

8. **Capture screenshots with Playwright.**

   The runner writes a temporary screenshot script under the artifact directory and captures:

   - `/login` in a clean browser context;
   - `/` Command Center;
   - `/config` workspace/project selection settings;
   - `/sources` import/index status;
   - `/workbench` agent/citation surface;
   - `/agent-profile` runtime configuration surface;
   - generated `report.html` with the 50Q summary.

9. **Inspect/sanitize before committing.**

   The committed report and screenshots were checked for tokens, raw UUIDs, private local paths, and secret-looking values. Raw `report.json`, generated screenshot scripts, and local evidence bundles stay under ignored `artifacts/`.

## Generated files from the runner

For a fresh run with `--artifact-dir artifacts/sourcebrief-launch-50q-run`, expect:

```text
artifacts/sourcebrief-launch-50q-run/
  README.md
  report.json
  report.html
  capture_screenshots.cjs
  screenshots/
    01-login.png
    02-dashboard.png
    03-selection-settings.png
    04-import-sources.png
    05-workbench-citations.png
    06-agent-profile.png
    07-eval-report.png
```

Only the sanitized public screenshots and this Markdown report are committed. The raw JSON report remains local evidence unless intentionally redacted for a PR.

## What each screenshot proves

| Screenshot | Product moment | Regression it would catch |
| --- | --- | --- |
| `01-login.png` | Browser-visible login entry point. | Broken web routing, missing auth page, or token-first-only UX. |
| `02-dashboard.png` | Command Center after session setup. | Runtime cannot load selected workspace/project or dashboard state. |
| `03-selection-settings.png` | Workspace/project selection by human-readable name. | UUID-first golden path or missing project selection UI. |
| `04-import-sources.png` | Source import lifecycle and bounded/partial corpus disclosure. | Import/index failures hidden from users or stale status display. |
| `05-workbench-citations.png` | Agent Workbench/citation surface. | Agent flow lacks scoped cited context entry point. |
| `06-agent-profile.png` | Runtime/MCP configuration surface. | Agent runtime setup path disappears from UI. |
| `07-eval-report.png` | 50-question summary report. | Eval runner stops before producing human-readable launch evidence. |

## 50Q result

The runner separates **mechanical pass/fail** from **answer-quality warnings**.

- Mechanical failures: `0`
- Mechanical passes: `50`
- Answer-quality warnings: `3`

Follow-up issues opened:

- [#145](https://github.com/pingchesu/sourcebrief/issues/145) — `sourcebrief-launch-027`, CLI bounded import terms.
- [#146](https://github.com/pingchesu/sourcebrief/issues/146) — `sourcebrief-launch-031`, skill-pack excluded corpus terminology.
- [#147](https://github.com/pingchesu/sourcebrief/issues/147) — `sourcebrief-launch-041`, token redaction terminology.

## Notes and limitations

- The imported repository is a bounded git bundle of the real SourceBrief repository so the proof is reproducible and does not depend on public network GitHub availability.
- The import is intentionally marked partial because the runner uses bounded launch-proof budgets (`max_repo_files`, `max_file_bytes`, `max_repo_bytes`). Partial coverage is surfaced in the UI screenshot and report instead of hidden.
- Answer-quality warnings are not treated as mechanical retrieval failures. They remain follow-up issues because launch-facing language still matters.
- The generated report redacts tokens, UUIDs, and password-like fields. Public screenshots were inspected for tokens, raw UUIDs, private local paths, and secrets before commit.
