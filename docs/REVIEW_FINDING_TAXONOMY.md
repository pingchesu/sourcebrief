# Reviewer finding taxonomy

This document defines the machine-readable reviewer output contract for SourceBrief self-improvement issue [#162](https://github.com/pingchesu/sourcebrief/issues/162).

The reviewer runner in #161 must emit this shape. The proposal and gate work in #163/#164 should consume it instead of parsing free-form review text.

## Schema versions

```text
sourcebrief.review-finding.v1
sourcebrief.review-report.v1
```

Python models:

```text
sourcebrief_shared.review_findings.ReviewerFinding
sourcebrief_shared.review_findings.ReviewerReport
```

Example report:

- [reviewer-report-example.json](examples/self-improvement/reviewer-report-example.json)

## Severity policy

| Severity | Blocks adoption? | Meaning |
| --- | --- | --- |
| `blocker` | yes | Unsafe, false, privacy-breaking, or product-breaking result. Must be fixed before staging/adoption. |
| `major` | yes | Material correctness, evidence, sequencing, or product/DX issue. Should be fixed before merge/adoption. |
| `minor` | no | Local improvement that does not invalidate the artifact. |
| `learning` | no | Valid pattern worth converting into a regression/proposal if gated. |
| `rejected_learning` | no | A proposed lesson that should be retained as negative feedback. |

`blocker` and `major` findings must include `evidence_refs` into the originating review bundle, issue, gate result, or proof artifact.

## Finding types

| Type | Use when |
| --- | --- |
| `unsupported_claim` | The output states something not supported by the bundle evidence. |
| `citation_mismatch` | Citation label or metadata exists but the cited snippet/source does not support the claim. |
| `missing_evidence` | The bundle lacks enough proof to validate the answer. |
| `stale_source` | The answer relies on stale snapshot/commit/runtime evidence. |
| `scope_creep` | The output exceeds the task, workspace/project/resource scope, or approved non-goals. |
| `unsafe_mutation` | The output implies silent production/config/source mutation or unsafe side effects. |
| `quickstart_dx_failure` | A user-facing setup/recipe/demo path would fail or mislead. |
| `regression_candidate` | The finding is primarily a repeatable test/fixture opportunity. |
| `overclaim` | Product docs or answer claims future/planned behavior as shipped. |
| `no_proof` | The artifact claims verification without real tool output/proof. |
| `rejected_proposal` | A proposed learning should be retained as rejected negative feedback. |

## Required finding fields

- `finding_id`
- `bundle_id`
- `severity`
- `type`
- `summary`
- `claim`
- `claim_ids`
- `evidence_refs`
- `impact`
- `suggested_fix`
- `regression_candidate`
- `confidence`
- `reviewer_lens`
- `proposal_eligibility`

Proposal eligibility rules:

- `candidate`: finding is a medium/high-confidence regression candidate.
- `requires_human_review`: finding is a low-confidence regression candidate.
- `not_eligible`: finding should not become a proposal, including `rejected_learning` records.

## Report aggregation

Reviewer reports carry a deterministic verdict and aggregate:

- `verdict`: `PASS`, `BLOCK`, or `RISK`;
- total finding count;
- counts by severity;
- counts by type;
- `blocks_adoption`, true if any blocker/major exists;
- proposal candidate count.

Aggregation is implemented by `aggregate_findings(...)` so later reviewer runners and observability surfaces do not invent their own severity math.

PR review reports may also carry `subject_refs[]` entries such as `kind="github_pr"`, `ref_id="owner/repo#123"`, head SHA, URL, and changed paths. This keeps the report linked to the reviewed PR without embedding raw chat history.

## Verification

```bash
uv run --extra dev python -m pytest tests/unit/test_review_findings.py -q
```

The tests validate the example report, blocker/major evidence requirements, proposal eligibility rules, bundle/report consistency, aggregation, and compatibility with #172 golden expected findings.
