# Self-improvement golden fixtures

This is the minimum regression suite for SourceBrief self-improvement issue [#172](https://github.com/pingchesu/sourcebrief/issues/172).

The suite exists before the reviewer runner and validation gate are fully implemented so those later issues cannot become empty LLM-judge wrappers.

## Fixture location

```text
docs/examples/self-improvement/golden/manifest.json
```

The manifest uses schema version:

```text
sourcebrief.self-improvement-golden.v1
```

Python validator:

```text
sourcebrief_shared.self_improvement_golden.validate_golden_manifest
```

## Minimum controls

The current minimum suite includes:

| Case | Purpose |
| --- | --- |
| `safe-passing-docs-answer` | Positive control: a cited docs answer should not produce findings. |
| `unsupported-shipped-nightly-optimizer` | Negative control: answer claims a future/non-goal nightly optimizer is shipped. |
| `citation-label-does-not-support-egress-claim` | Negative control: citation label exists but the snippet does not support the claim. |
| `reject-llm-judge-only-learning` | Gate must reject an unsupported learning rule even if it sounds plausible. |
| `accept-security-egress-wording` | Gate can accept a supported docs/security wording improvement. |

## Contract for later issues

- #161 reviewer runner should be able to run in deterministic/mock mode against these bundles.
- #162 finding taxonomy should preserve or intentionally migrate the expected finding types in this manifest.
- #164 validation gate should include the gate cases so it cannot accept LLM-judge-only or citation-unsupported learning proposals.
- #171 product docs should not claim self-improvement is proven until these fixtures and the end-to-end smoke path pass.

## Verification

```bash
uv run --extra dev python -m pytest tests/unit/test_self_improvement_golden.py -q
```

The validator loads every referenced review bundle, confirms examples are public-safe, requires both positive and negative controls, and requires at least one rejected gate case.
