# Self-improvement MVP smoke path

This document is the end-to-end proof for SourceBrief self-improvement issue [#175](https://github.com/pingchesu/sourcebrief/issues/175), linked from the roadmap tracker [#157](https://github.com/pingchesu/sourcebrief/issues/157).

The smoke path connects the component artifacts without reviewing raw chat transcripts and without mutating prompts, skills, runtime config, code, or production state.

## Web console path

Open **Self-improvement** from the web console. The page provides a **Run MVP smoke** action that writes the same artifact chain into the current workspace/project self-improvement root and immediately refreshes redacted review history. This is the preferred product path for humans because it makes provenance, gate status, staged receipts, and non-mutation boundaries visible without opening raw JSON by hand.

## CLI path

```bash
sourcebrief review mvp-smoke --out-dir ./artifacts/self-improvement-mvp-smoke
```

By default this uses the public-safe unsupported-claim golden review bundle. You can pass another public-safe bundle with `--bundle`.

The command writes:

```text
review-bundle.json
review-report.json
regression-proposal.json
validation-gate-result.json
staged/<proposal-id>/receipt.json
history-summary.json
mvp-smoke-summary.json
```

## What it proves

The command performs the full local MVP path:

1. Load a `sourcebrief.review-bundle.v1` bundle.
2. Run the local deterministic reviewer.
3. Select a proposal-eligible finding.
4. Convert it to a `sourcebrief.regression-proposal.v1` artifact.
5. Run the deterministic validation gate.
6. If accepted, stage a patch/receipt with no automatic apply.
7. Scan the output directory with review history/observability.
8. Emit a summary linked to #157 and #175.

The summary includes `no_silent_mutation=true`; this is backed by the implementation boundary that only writes artifacts under `--out-dir`.

## Verification

```bash
uv run --extra dev python -m pytest \
  tests/unit/test_cli.py::test_cli_review_mvp_smoke_runs_full_local_path -q
```
