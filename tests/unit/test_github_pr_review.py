from pathlib import Path

import pytest

from sourcebrief_shared.github_pr_review import (
    MAX_CHANGED_PATHS,
    MAX_DIFF_SUMMARY_CHARS,
    MAX_PR_BODY_CHARS,
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


def test_pr_review_fixture_metadata_does_not_forge_gh_tool_proof() -> None:
    metadata = load_pr_metadata_fixture(FIXTURE)
    metadata["fixture_path"] = str(FIXTURE)

    bundle = build_review_bundle_from_github_pr_metadata(
        metadata,
        workspace_id="ws",
        project_id="proj",
        metadata_source="fixture",
    )

    proof = bundle.tool_proof[0]
    assert proof.kind == "other"
    assert proof.status == "not_run"
    assert proof.command[0] == "metadata-fixture"
    assert proof.command[1] == "[REDACTED:local_path]"
    assert "gh" not in proof.command


def test_pr_review_bundle_requires_repo_and_head_sha() -> None:
    metadata = load_pr_metadata_fixture(FIXTURE)
    metadata.pop("repo", None)
    metadata.pop("repository", None)

    with pytest.raises(GitHubPRBundleError, match="repo"):
        build_review_bundle_from_github_pr_metadata(metadata, workspace_id="ws", project_id="proj")

    metadata = load_pr_metadata_fixture(FIXTURE)
    metadata.pop("headRefOid", None)
    metadata.pop("head_sha", None)

    with pytest.raises(GitHubPRBundleError, match="head SHA"):
        build_review_bundle_from_github_pr_metadata(metadata, workspace_id="ws", project_id="proj")


def test_pr_review_bundle_bounds_large_evidence() -> None:
    metadata = load_pr_metadata_fixture(FIXTURE)
    metadata["body"] = "x" * (MAX_PR_BODY_CHARS + 1)
    with pytest.raises(GitHubPRBundleError, match="body exceeds"):
        build_review_bundle_from_github_pr_metadata(metadata, workspace_id="ws", project_id="proj")

    metadata = load_pr_metadata_fixture(FIXTURE)
    metadata["diff_summary"] = "x" * (MAX_DIFF_SUMMARY_CHARS + 1)
    with pytest.raises(GitHubPRBundleError, match="diff_summary exceeds"):
        build_review_bundle_from_github_pr_metadata(metadata, workspace_id="ws", project_id="proj")

    metadata = load_pr_metadata_fixture(FIXTURE)
    metadata["changed_paths"] = [f"path-{idx}.py" for idx in range(MAX_CHANGED_PATHS + 1)]
    with pytest.raises(GitHubPRBundleError, match="changed_paths exceeds"):
        build_review_bundle_from_github_pr_metadata(metadata, workspace_id="ws", project_id="proj")


def test_pr_review_report_subject_refs_preserve_space_and_comma_paths() -> None:
    metadata = load_pr_metadata_fixture(FIXTURE)
    metadata["changed_paths"] = ["docs/path with space.md", "src/foo,bar.py"]

    bundle = build_review_bundle_from_github_pr_metadata(metadata, workspace_id="ws", project_id="proj")
    report = run_review_bundle(bundle)

    assert report.subject_refs[0].changed_paths == ["docs/path with space.md", "src/foo,bar.py"]
