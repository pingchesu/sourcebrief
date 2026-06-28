# Regression proposal artifacts

This document describes the first regression proposal artifact flow for SourceBrief self-improvement issue [#163](https://github.com/pingchesu/sourcebrief/issues/163).

A reviewer finding is not a permanent lesson by itself. It becomes durable only as a reviewable `sourcebrief.regression-proposal.v1` artifact that can later pass or fail the #164 validation gate.

## CLI usage

```bash
sourcebrief review propose \
  --report ./review-reports/ask-review.json \
  --finding-id finding-learning-quickstart-gap \
  --owner qa \
  --proposal-out ./regression-proposals/quickstart-auth.json
```

If `--finding-id` is omitted, the first regression candidate or rejected-learning finding is selected.

## Artifact fields

Python model:

```text
sourcebrief_shared.regression_proposal.RegressionProposal
```

Schema version:

```text
sourcebrief.regression-proposal.v1
```

Required context:

- source report ID;
- source bundle ID;
- source finding ID;
- failure mode;
- target surface;
- proposed check;
- acceptance criteria;
- fixture/bundle/evidence refs;
- owner;
- status;
- rationale.

## Status policy

| Status | Meaning |
| --- | --- |
| `proposed` | Candidate is ready for validation-gate evaluation. |
| `accepted` | Gate accepted it; later work may implement/stage it. |
| `rejected` | Durable negative feedback; do not keep proposing the same lesson. |
| `implemented` | Accepted proposal has been implemented. |
| `superseded` | Replaced by another proposal. |

This issue only creates artifacts. It does not accept, implement, or apply proposals.

## Example

- [regression-proposal-example.json](examples/self-improvement/regression-proposal-example.json)

## Verification

```bash
uv run --extra dev python -m pytest \
  tests/unit/test_regression_proposal.py \
  tests/unit/test_cli.py::test_cli_review_propose_writes_regression_proposal -q
```
