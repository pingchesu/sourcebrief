# Validation gate

This document describes the MVP validation gate for SourceBrief self-improvement issue [#164](https://github.com/pingchesu/sourcebrief/issues/164).

The gate prevents plausible but wrong lessons from becoming permanent behavior. A proposal must produce a `sourcebrief.validation-gate-result.v1` artifact before later staged adoption work can consider it.

## CLI usage

```bash
sourcebrief review gate \
  --proposal ./regression-proposals/quickstart-auth.json \
  --result-out ./gate-results/quickstart-auth.json
```

## Output decisions

| Decision | Meaning |
| --- | --- |
| `accept_new_best` | Candidate beats the baseline and should become the best known variant. Reserved for future scored gates. |
| `accept` | Candidate is safe/useful and can move to staged adoption. |
| `reject` | Candidate is unsupported, harmful, too broad, or unproven. |

## MVP deterministic checks

The first gate is deliberately narrow and deterministic:

- schema-valid proposal;
- proposal has evidence refs;
- proposal is not already a rejected durable lesson;
- target surface is known;
- harmful auto-learning guard rejects broad rules such as “always claim nightly optimizer / automatic skill updates”.

A rejected result includes a `rejected_learning` payload so later workflows can preserve negative feedback.

## Non-goals

- No LLM-judge-only acceptance.
- No automatic staged adoption.
- No skill/prompt/code/runtime mutation.
- No nightly optimizer.

## Example

- [validation-gate-result-example.json](examples/self-improvement/validation-gate-result-example.json)

## Verification

```bash
uv run --extra dev python -m pytest \
  tests/unit/test_validation_gate.py \
  tests/unit/test_cli.py::test_cli_review_gate_writes_validation_result -q
```
