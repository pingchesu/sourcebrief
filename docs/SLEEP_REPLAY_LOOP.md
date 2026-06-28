# Sleep/replay dry-run loop

This document describes the later-stage dry-run sleep/replay loop for SourceBrief self-improvement issue [#170](https://github.com/pingchesu/sourcebrief/issues/170).

## Shipped scope

The MVP sleep loop mines bounded review artifacts, not raw chat transcripts:

```text
recent regression proposal artifacts
    -> recurrence grouping
    -> dry-run sleep candidate proposal
    -> deterministic validation gate
    -> sleep replay summary
```

It is deliberately dry-run only. It does not adopt learning, update prompts, mutate generated skills, patch runtime packs, create PRs, or schedule itself.

## Command

```bash
uv run sourcebrief --json review sleep \
  --dir ./artifacts/self-improvement-history \
  --out-dir ./artifacts/self-improvement-sleep \
  --summary-out ./artifacts/self-improvement-sleep/summary.json
```

Useful options:

- `--min-occurrences` defaults to `2`; one-off failures are reported as insufficient signal.
- `--max-artifacts` defaults to `100`; the scanner records budget skips.
- `--out-dir` writes candidate proposal/gate artifacts for inspection.
- `--summary-out` writes `sourcebrief.sleep-replay-summary.v1`.

## Safety and failure modes

- Input is limited to `sourcebrief.regression-proposal.v1` artifacts.
- Rejected proposals are skipped as durable negative learning.
- Candidate proposals still run through `validate_regression_proposal(...)`.
- Harmful recurring proposals, such as unsupported external-LLM-default learning, are rejected by the deterministic gate.
- No recurring candidate is staged or applied automatically.

## Verification

```bash
uv run --extra dev python -m pytest tests/unit/test_self_improvement_sleep.py -q
uv run --extra dev python -m pytest tests/unit/test_cli.py::test_cli_review_sleep_dry_run_mines_recurring_candidates -q
```
