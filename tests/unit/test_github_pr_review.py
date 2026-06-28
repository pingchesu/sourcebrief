from pathlib import Path

import pytest

from sourcebrief_shared.github_pr_review import (
    GitHubPRBundleError,
    build_review_bundle_from_github_pr_metadata,
    load_pr_metadata_fixture,
)
from sourcebrief_shared.review_runner import run_review_bundle

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "docs" / "examples" / "self-improvement" / "pr-review-metadata-fixture.json"


def test_build_pr_review_bundle_from_fixture_links_pr_sha_and_changed_paths() -> None:
    metadata = load_pr_metadata_fixture(FIXTURE)
    bundle = build_review_bundle_from_github_pr_metadata(metadata, workspace_id="ws", project_id="proj")

    assert bundle.schema_version == "sourcebrief.review-bundle.v1"
    assert bundle.kind == "pr_review"
    assert bundle.security.completeness == "complete"
    assert bundle.scope.resource_ids == ["github-pr:pingchesu/sourcebrief#187"]
    assert "pingchesu/sourcebrief#187" in bundle.input.original_query
    assert "e174ea09b9edee97e1965c92b709d60f4f8d5160" in bundle.output.body
    assert {ref.path for ref in bundle.source_refs} == {
        "docs/STAGED_ADOPTION.md",
        "packages/shared/sourcebrief_shared/staged_adoption.py",
        "tests/unit/test_staged_adoption.py",
    }
    assert all(ref.commit_sha == "e174ea09b9edee97e1965c92b709d60f4f8d5160" for ref in bundle.source_refs)
    assert all(citation.supports_claim_ids == bundle.output.claim_ids for citation in bundle.citations)
    assert bundle.verification_logs[0].command == "make test"


def test_pr_review_bundle_report_subject_refs_include_pr_identity() -> None:
    bundle = build_review_bundle_from_github_pr_metadata(load_pr_metadata_fixture(FIXTURE), workspace_id="ws", project_id="proj")
    report = run_review_bundle(bundle)

    assert report.verdict == "PASS"
    assert report.subject_refs
    subject = report.subject_refs[0]
    assert subject.kind == "github_pr"
    assert subject.ref_id == "pingchesu/sourcebrief#187"
    assert subject.head_sha == "e174ea09b9edee97e1965c92b709d60f4f8d5160"
    assert "docs/STAGED_ADOPTION.md" in subject.changed_paths


def test_pr_review_bundle_requires_changed_paths() -> None:
    metadata = load_pr_metadata_fixture(FIXTURE)
    metadata["changed_paths"] = []

    with pytest.raises(GitHubPRBundleError, match="changed path"):
        build_review_bundle_from_github_pr_metadata(metadata, workspace_id="ws", project_id="proj")
