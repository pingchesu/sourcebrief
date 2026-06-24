from __future__ import annotations

from uuid import uuid4

from sourcebrief_api.retrieval import (
    RetrievalCandidate,
    diversify_ranked_candidates,
    path_prior_score,
)


def _candidate(*, path: str, content_hash: str | None = None, score: float = 1.0, resource_id=None) -> RetrievalCandidate:
    rid = resource_id or uuid4()
    return RetrievalCandidate(
        chunk_id=uuid4(),
        resource_id=rid,
        snapshot_id=uuid4(),
        path=path,
        title=None,
        ordinal=1,
        content_hash=content_hash or path,
        content=f"content for {path}",
        version="v1",
        version_kind="commit",
        snapshot_metadata={},
        score=score,
        ranking_diagnostics={"base_score": score},
    )


def test_path_prior_prefers_primary_docs_for_install_and_architecture_queries() -> None:
    readme_prior, readme_reasons = path_prior_score("How do I install and activate this project?", "README.md")
    issue_prior, issue_reasons = path_prior_score(
        "How do I install and activate this project?", ".github/ISSUE_TEMPLATE/platform_support.md"
    )
    arch_prior, arch_reasons = path_prior_score(
        "What is the long horizon architecture?", "backend/docs/ARCHITECTURE.md"
    )
    localized_prior, localized_reasons = path_prior_score(
        "What is the long horizon architecture?", "README_ja.md"
    )

    setup_prior, setup_reasons = path_prior_score("How do I set up team mode?", "docs/quickstart.md")

    assert readme_prior > issue_prior
    assert setup_prior > 0.10
    assert "install_doc" in setup_reasons
    assert "primary_readme" in readme_reasons
    assert "low_signal_path" in issue_reasons
    assert arch_prior > localized_prior
    assert "architecture_doc" in arch_reasons
    assert "localized_readme_downrank" in localized_reasons


def test_diversify_ranked_candidates_prefers_unique_content_and_paths_before_backfill() -> None:
    resource_a = uuid4()
    resource_b = uuid4()
    candidates = [
        _candidate(path="docs/repeated.md", content_hash="same", resource_id=resource_a, score=1.0),
        _candidate(path="docs/repeated.md", content_hash="same", resource_id=resource_a, score=0.99),
        _candidate(path="README.md", content_hash="readme", resource_id=resource_a, score=0.95),
        _candidate(path="backend/docs/ARCHITECTURE.md", content_hash="arch", resource_id=resource_b, score=0.90),
        _candidate(path="docs/other.md", content_hash="other", resource_id=resource_b, score=0.80),
    ]

    selected, metadata = diversify_ranked_candidates(candidates, top_k=4)

    paths = [candidate.path for candidate in selected]
    assert paths[:3] == ["docs/repeated.md", "README.md", "backend/docs/ARCHITECTURE.md"]
    assert paths.count("docs/repeated.md") == 1
    assert metadata["selected_count"] == 4
    assert metadata["unique_citation_paths"] >= 4
    assert metadata["deduped_from_count"] == 1
    diagnostics = selected[0].ranking_diagnostics or {}
    assert diagnostics["diversity"] == "selected"


def test_diversify_ranked_candidates_uses_resource_soft_cap_when_pool_has_multiple_resources() -> None:
    resource_a = uuid4()
    resource_b = uuid4()
    candidates = [
        _candidate(path="a/one.md", content_hash="a1", resource_id=resource_a, score=1.0),
        _candidate(path="a/two.md", content_hash="a2", resource_id=resource_a, score=0.99),
        _candidate(path="a/three.md", content_hash="a3", resource_id=resource_a, score=0.98),
        _candidate(path="b/one.md", content_hash="b1", resource_id=resource_b, score=0.50),
    ]

    selected, _ = diversify_ranked_candidates(candidates, top_k=3)
    small_selected, _ = diversify_ranked_candidates(candidates, top_k=2)

    assert [candidate.resource_id for candidate in selected] == [resource_a, resource_a, resource_b]
    assert selected[-1].path == "b/one.md"
    assert [candidate.resource_id for candidate in small_selected] == [resource_a, resource_b]
    assert [candidate.path for candidate in small_selected] == ["a/one.md", "b/one.md"]


def test_diversify_ranked_candidates_exposes_resource_count_diagnostics() -> None:
    resource_a = uuid4()
    resource_b = uuid4()
    candidates = [
        _candidate(path="a/one.md", content_hash="a1", resource_id=resource_a, score=1.0),
        _candidate(path="a/two.md", content_hash="a2", resource_id=resource_a, score=0.90),
        _candidate(path="b/one.md", content_hash="b1", resource_id=resource_b, score=0.80),
    ]

    selected, metadata = diversify_ranked_candidates(candidates, top_k=2)

    assert {candidate.resource_id for candidate in selected} == {resource_a, resource_b}
    assert metadata["candidate_resource_counts"] == {str(resource_a): 2, str(resource_b): 1}
    assert metadata["selected_resource_counts"] == {str(resource_a): 1, str(resource_b): 1}
