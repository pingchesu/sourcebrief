# Review bundle capture

This document describes the first opt-in capture path for SourceBrief self-improvement issue [#160](https://github.com/pingchesu/sourcebrief/issues/160).

Capture persists a `sourcebrief.review-bundle.v1` artifact from a cited SourceBrief answer or deterministic quickstart demo. It does **not** run a reviewer agent, mutate prompts, or send private evidence to any reviewer backend.

## CLI usage

Ask capture:

```bash
sourcebrief ask \
  --workspace <workspace-name-or-slug> \
  --project <project-name> \
  --resource <resource-name-or-ref> \
  --review-bundle-out ./review-bundles/ask.json \
  "What should an operator do when payment retries fail?"
```

Quickstart demo capture:

```bash
sourcebrief quickstart-demo \
  --review-bundle-out ./review-bundles/quickstart-demo.json
```

Both commands write the bundle and include a `review_bundle` summary in JSON output. Human output prints the bundle path.

## Capture contract

The captured bundle includes:

- original query and task brief;
- final answer text and generated claim IDs;
- workspace/project/resource scope;
- runtime/retrieval metadata (`runtime`, `top_k`, `max_chars`, profile);
- source refs and citation refs from the agent-context response;
- sanitized command metadata and API proof;
- security metadata from [Self-improvement artifact security](SELF_IMPROVEMENT_SECURITY.md).

If required answer or citation proof is missing, capture still writes a schema-valid bundle but marks `security.completeness` as `insufficient_evidence`.

If redaction fires on captured text or command metadata, capture marks the bundle `redacted_partial`.

## Non-goals

- No automatic transcript/day harvesting.
- No reviewer execution.
- No validation gate execution.
- No UI surface.
- No private evidence egress beyond the local bundle write.

## Verification

Focused tests:

```bash
uv run --extra dev python -m pytest \
  tests/unit/test_cli.py::test_cli_ask_can_write_valid_review_bundle \
  tests/unit/test_cli.py::test_quickstart_demo_can_write_review_bundle -q
```

Broader review-bundle checks:

```bash
uv run --extra dev python -m pytest \
  tests/unit/test_cli.py \
  tests/unit/test_review_bundle.py \
  tests/unit/test_citation_support.py -q
```
