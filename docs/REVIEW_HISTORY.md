# Review history and observability

This document describes the local review-history surface for SourceBrief self-improvement issue [#168](https://github.com/pingchesu/sourcebrief/issues/168).

The first slice is intentionally local and file-based. It scans a directory containing self-improvement artifacts and builds a redacted summary so humans and future agents can inspect provenance without manually opening raw JSON files.

## CLI usage

```bash
sourcebrief review history list --dir ./artifacts/self-improvement

sourcebrief review history show proposal-finding-learning-quickstart-gap \
  --dir ./artifacts/self-improvement
```

The scanner recognizes:

- `sourcebrief.review-bundle.v1`
- `sourcebrief.review-report.v1`
- `sourcebrief.regression-proposal.v1`
- `sourcebrief.validation-gate-result.v1`
- `sourcebrief.staged-adoption-receipt.v1`

## Output

`history list` returns:

- `records[]`: artifact ID, schema, kind, relative path, status/decision/verdict, source IDs, target surface, PR subject refs, and redaction counts;
- `metrics`: record counts, artifact-type counts, blocker/major counts, gate accept/reject counts, rejected proposal counts;
- `provenance[]`: edges such as bundle -> report, report -> proposal, proposal -> gate, and proposal/gate -> staged adoption.

`history show` returns one record plus the redacted artifact payload. Secret-looking values are passed through the same self-improvement redactor used by bundle security code.

## Safety boundary

This command is read-only. It does not upload artifacts, comment on GitHub, mutate staged proposals, or adopt changes. The output is intended to be safer to share than raw artifacts, but operators should still treat review bundles and receipts as workspace artifacts.

## Verification

```bash
uv run --extra dev python -m pytest \
  tests/unit/test_review_history.py \
  tests/unit/test_cli.py::test_cli_review_history_list_and_show_are_redacted -q
```
