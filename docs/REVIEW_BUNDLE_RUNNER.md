# Review bundle runner

This document describes the first autonomous reviewer runner for SourceBrief self-improvement issue [#161](https://github.com/pingchesu/sourcebrief/issues/161).

The runner reads a `sourcebrief.review-bundle.v1` artifact, applies local deterministic reviewer lenses, and writes a `sourcebrief.review-report.v1` artifact. It does **not** adopt findings, mutate prompts/skills/code, or call an external reviewer backend.

## CLI usage

```bash
sourcebrief review run \
  --bundle ./review-bundles/ask.json \
  --report-out ./review-reports/ask-review.json
```

Optional diagnostic mode for incomplete bundles:

```bash
sourcebrief review run \
  --bundle ./review-bundles/incomplete.json \
  --allow-incomplete \
  --report-out ./review-reports/incomplete-review.json
```

## Backend modes

| Backend | Behavior |
| --- | --- |
| `deterministic` | Local citation-support and missing-evidence lenses. Default. |
| `mock` | Same local deterministic behavior, reserved for CI/tests and future prompt-harness comparison. |

Unsupported backends fail closed.

## Output contract

The report uses [Reviewer finding taxonomy](REVIEW_FINDING_TAXONOMY.md):

- `schema_version`: `sourcebrief.review-report.v1`
- `verdict`: `PASS`, `BLOCK`, or `RISK`
- `findings[]`: `sourcebrief.review-finding.v1`
- `aggregate`: severity/type counts and proposal candidate count

Verdict policy:

- `BLOCK`: one or more blocker/major findings.
- `RISK`: findings exist, but none block adoption.
- `PASS`: no findings.

## Fail-closed behavior

By default, `security.completeness != complete` raises an actionable error. Use `--allow-incomplete` only for diagnostic review; the runner then emits a `major` `missing_evidence` finding.

## Current lenses

- Citation support: deterministic #167 unsupported-claim / citation-mismatch checks.
- Missing evidence: fail-closed incomplete bundle handling.

Future work can add LLM or retrieval-backed lenses, but those should preserve the same report schema and local deterministic controls.

## Verification

```bash
uv run --extra dev python -m pytest \
  tests/unit/test_review_runner.py \
  tests/unit/test_cli.py::test_cli_review_run_writes_report -q
```
