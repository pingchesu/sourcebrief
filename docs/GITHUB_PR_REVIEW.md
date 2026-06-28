# GitHub PR review bundles

This document describes the GitHub PR review-bundle integration for SourceBrief self-improvement issue [#166](https://github.com/pingchesu/sourcebrief/issues/166).

The goal is to review pull-request outcomes from bounded PR evidence instead of raw Slack/chat history. The first slice creates a `sourcebrief.review-bundle.v1` artifact with PR metadata, head SHA, changed paths, diff summary, and verification logs. The existing local reviewer runner can then produce a structured report.

## Offline fixture / dry run

```bash
sourcebrief review pr-bundle \
  --metadata-fixture docs/examples/self-improvement/pr-review-metadata-fixture.json \
  --workspace-id github \
  --project-id sourcebrief \
  --bundle-out ./review-bundles/pr-187.json

sourcebrief review run \
  --bundle ./review-bundles/pr-187.json \
  --report-out ./review-reports/pr-187.json
```

## Live GitHub metadata

When `--metadata-fixture` is omitted, the command shells out to the GitHub CLI:

```bash
sourcebrief review pr-bundle \
  --repo pingchesu/sourcebrief \
  --pr 187 \
  --workspace-id github \
  --project-id sourcebrief \
  --bundle-out ./review-bundles/pr-187.json
```

This uses:

- `gh pr view --json number,title,body,url,headRefOid,headRefName,baseRefName,author,changedFiles`
- `gh pr diff --name-only`

## Artifact contents

The PR bundle records:

- `kind="pr_review"`;
- `output.body` with PR number, URL, head SHA, refs, changed paths, PR body, and diff summary;
- `source_refs[]` for each changed path with the PR head SHA;
- `citations[]` for changed-path evidence;
- `tool_proof[]` for PR metadata and verification logs;
- `reviewer_notes[]` containing a machine-readable `github_pr ...` subject line.

When the local reviewer runs over a PR bundle, the report includes `subject_refs[]` with:

- `kind="github_pr"`;
- `ref_id` such as `pingchesu/sourcebrief#187`;
- PR URL;
- head SHA;
- changed paths.

## Safety boundary

`sourcebrief review pr-bundle` does not merge, push, comment, or mutate production. GitHub posting is intentionally not part of this first slice. If a future `--post-comment` path is added, it must be an explicit flag and must read back the posted comment URL/status.

## Verification

```bash
uv run --extra dev python -m pytest \
  tests/unit/test_github_pr_review.py \
  tests/unit/test_cli.py::test_cli_review_pr_bundle_from_fixture_and_run_report -q
```
