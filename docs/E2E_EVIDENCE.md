# E2E evidence bundles

SourceBrief launch checks should leave a durable, redacted evidence bundle. The bundle is not committed by default; `artifacts/` is ignored so large logs, screenshots, IDs, and local paths do not leak into source control.

Use this convention for README-driven E2E, release signoff, and issue #71 child evidence.

## Recommended isolated run shape

Use a unique Compose project name on shared or remote hosts so one launch test cannot collide with another checkout that is also named `sourcebrief`:

```bash
export RUN_ID="$(date -u +%Y%m%d%H%M%S)"
export PORT_SUFFIX="$(python -c 'import random; print(random.randint(10, 99))')"
export COMPOSE_PROJECT_NAME="sourcebrief_e2e_${RUN_ID}"
export SOURCEBRIEF_API_PORT="18${PORT_SUFFIX}"
export SOURCEBRIEF_WEB_PORT="13${PORT_SUFFIX}"
export NEXT_PUBLIC_API_BASE_URL="http://localhost:${SOURCEBRIEF_API_PORT}"
export SOURCEBRIEF_CORS_ORIGINS="http://localhost:${SOURCEBRIEF_WEB_PORT},http://127.0.0.1:${SOURCEBRIEF_WEB_PORT}"

make compose-up
make migrate
python scripts/collect_e2e_evidence.py \
  --command 'make qa-smoke' \
  --command 'make alpha-eval' \
  --include-file alpha-eval=artifacts/alpha-eval-report.json
```

If you are verifying an existing checkout, do not assume the default ports. Read the configured values from `.env` and the environment:

- `SOURCEBRIEF_API_PORT` / `SOURCEBRIEF_API_URL`
- `SOURCEBRIEF_WEB_PORT` / `SOURCEBRIEF_WEB_URL`
- `SOURCEBRIEF_POSTGRES_PORT`
- `SOURCEBRIEF_REDIS_PORT`
- `COMPOSE_PROJECT_NAME`

## Bundle command

```bash
make collect-e2e-evidence
```

This writes and fails closed if a health check, command, missing include, or stale included file fails. Use `--allow-failures` only when intentionally preserving a red exploratory run. This writes:

```text
artifacts/e2e/<timestamp>/
  manifest.json
  README.md
```

The collector records:

- capture time and run id;
- Git branch, HEAD SHA, and `git status --short --branch`;
- redacted `.env` summary;
- configured API/web URLs and ports;
- `COMPOSE_PROJECT_NAME`;
- `docker compose ps --format json` output;
- `/readyz` and `/api/health` responses;
- optional command transcripts with exit codes;
- optional included files such as `artifacts/alpha-eval-report.json`.

Example with additional proof files and command transcripts:

```bash
python scripts/collect_e2e_evidence.py \
  --command 'make qa-smoke' \
  --command 'make alpha-eval' \
  --include-file alpha-eval=artifacts/alpha-eval-report.json
```

## Redaction policy

The collector redacts secret-looking environment keys and token-like values (`cs_*`, `Bearer ...`). Do not add raw screenshots, terminal logs, `.env`, browser storage, or generated runtime config to a PR unless you have checked the artifact for:

- bearer tokens and session tokens;
- admin passwords;
- local-only absolute paths that should not be public;
- private repository URLs with embedded credentials;
- unrelated customer data.

## Screenshot and visual proof policy

Committed screenshots/GIFs are allowed only when they are captured from a real local SourceBrief stack and are safe to publish. Each visual artifact should have metadata in `docs/PROOF_ARTIFACTS.md`:

- commit SHA or PR number used for capture;
- stack mode and auth mode;
- capture date;
- exact UI path or command path;
- redaction policy;
- whether it is current launch proof or historical illustration.

If a current clean E2E finds a UI regression, keep the old visual artifact but label it historical until it is recaptured from a fixed run.
