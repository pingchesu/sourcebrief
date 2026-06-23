# Structured real-corpus eval manifests

SourceBrief retrieval evals should be reproducible, hashable, and gradeable. A Markdown question list is useful for brainstorming, but launch evidence needs a structured manifest that can explain what corpus was indexed, what each question is expected to prove, and why a weak result is a product failure versus a partial-corpus caveat.

This format addresses issue #92 and complements the durable evidence bundle tracked by #79.

## Files

- Example manifest: [`../demo/alpha/eval_manifest.json`](../demo/alpha/eval_manifest.json)
- Example grading report template: [`../demo/alpha/eval_report_template.json`](../demo/alpha/eval_report_template.json)
- Validator/splitter: [`../scripts/eval_manifest.py`](../scripts/eval_manifest.py)

## Manifest contract

A manifest uses:

```json
{
  "schema_version": "sourcebrief.eval-manifest.v1",
  "name": "SourceBrief alpha real-corpus launch eval",
  "description": "...",
  "thresholds": {
    "pass_min_rate": 0.8,
    "partial_min_rate": 0.6,
    "block_below_rate": 0.6,
    "max_wrong_repo": 0,
    "max_unsupported_claims": 0
  },
  "run": {
    "sourcebrief_commit": "...",
    "api_url": "http://localhost:18000",
    "web_url": "http://localhost:13000",
    "workspace_id": "...",
    "project_id": "...",
    "resources": [
      {
        "key": "awesome_agent_harness",
        "target_repo": "org/repo",
        "resource_ids": ["..."],
        "snapshot_ids": ["..."],
        "upstream_commit": "...",
        "import_type": "full",
        "corpus_caveats": []
      }
    ]
  },
  "questions": []
}
```

Each question declares the customer job and grading expectations:

- `id`, `query`
- `target_repo`
- `resource_ids`, `snapshot_ids` — retrieval scope for the question
- `import_type`: `full`, `limited`, `failed`, or `expected-skip`
- `category`, `customer_job`, `difficulty`, `demo_type`
- `expected_resource_ids` — resources that must be cited for answerable questions; leave empty for `expected_unanswerable` controls
- `expected_paths`, `expected_symbols`, `required_texts`
- `forbidden_resource_ids`
- `min_citations`, `top_k`, `max_chars`, `include_code_symbols`
- `expected_result`: `pass`, `partial`, or `expected_unanswerable`
- `bad_answer_criteria`

A valid manifest must include at least one `expected_unanswerable` negative/control question. Use these to catch unsupported compliance/security claims, wrong-repo contamination, and ambiguous source names.

## Validate and freeze

```bash
python scripts/eval_manifest.py validate demo/alpha/eval_manifest.json
```

The validator prints a stable `manifest_sha256`. Store that digest in the run evidence so later grading can prove which question artifact was used.

## Split for `/retrieval-evals`

The API accepts at most 10 questions per request. Split large manifests into reproducible API payloads:

```bash
python scripts/eval_manifest.py split demo/alpha/eval_manifest.json --output-dir artifacts/eval-batches
```

This writes:

```text
artifacts/eval-batches/batch-001.json
artifacts/eval-batches/batch-002.json
...
```

Each batch is shape-compatible with `/retrieval-evals`. Before posting a documentation-facing sample, replace `NORMALIZED_*` placeholders with real workspace/project/resource/snapshot IDs and concrete commits:

```bash
curl -X POST "$SOURCEBRIEF_API_URL/workspaces/$WS/projects/$PROJECT/retrieval-evals" \
  -H 'Authorization: Bearer <sourcebrief-token>' \
  -H 'Content-Type: application/json' \
  --data-binary @artifacts/eval-batches/batch-001.json
```

## Grading report contract

The grading report distinguishes three layers:

1. **Mechanical API success** — request returned the expected shape/status.
2. **Retrieval quality** — citations hit expected resources/paths/symbols/texts and avoid forbidden resources.
3. **Human answer/demo quality** — synthesized answer is supported, caveated, and useful to a customer.

The report uses `schema_version: sourcebrief.eval-report.v1` and per-question grades:

- `PASS`
- `PARTIAL`
- `FAIL`

Each result must include:

- `id`
- `grade`
- `rationale`
- checks for `mechanical_api_success`, `retrieval_quality`, `citation_support`, `wrong_repo_check`, `partial_corpus_caveat`, and `human_answer_demo`
- optional `linked_child_issue_ids`
- optional `raw_output_ref` pointing to redacted raw evidence

The report also has a required `aggregate` object with mechanical, retrieval, and human-answer pass rates, wrong-repo/unsupported-claim failure counts, and a `PASS`/`RISK`/`BLOCK` verdict. The validator cross-checks those aggregate values against per-result grades/checks; an aggregate cannot claim `PASS` if rows fail. When validated with `--manifest`, the report must use the manifest digest and its result IDs must exactly match every manifest question ID; this prevents omitting failed questions from a customer-trust evidence bundle.

Validate a report by itself:

```bash
python scripts/eval_manifest.py validate-report demo/alpha/eval_report_template.json
```

Validate against a specific manifest digest:

```bash
python scripts/eval_manifest.py validate-report artifacts/eval-report.json --manifest demo/alpha/eval_manifest.json
```

## Evidence bundle recommendation

For a real customer-style run, keep a redacted bundle:

```text
artifacts/evals/<timestamp>/
  manifest.json
  manifest-summary.json
  batches/
  question-runs/*.redacted.json
  grading-report.json
  run-manifest.json
  git.txt
  env.redacted.txt
  resource-coverage.json
```

Do not store raw tokens, session cookies, or unredacted private URLs. Normalize IDs only when the bundle is documentation-facing; keep the private raw bundle on the operator host if needed for debugging.
