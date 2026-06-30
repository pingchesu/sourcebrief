from __future__ import annotations

from uuid import uuid4

from sourcebrief_api.retrieval import (
    RetrievalCandidate,
    bound_merged_candidate_pool,
    candidate_limit_for_profile,
    diversify_ranked_candidates,
    normalize_retrieval_profile,
    path_prior_score,
    promote_sequence_siblings_for_second_stage,
    retrieval_profile_manifest,
    retrieve_context_candidates,
)
from sourcebrief_api.schemas import (
    AgentContextRequest,
    ContextPacketRequest,
    RetrievalEvalQuestion,
    RetrievalEvalRequest,
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


def test_retrieval_v2_profile_is_default_off_with_bounded_larger_candidate_pool() -> None:
    default_profile = normalize_retrieval_profile(None)
    retrieval_v2 = normalize_retrieval_profile("retrieval-v2-rerank")
    manifest = retrieval_profile_manifest()

    assert default_profile.name == "hybrid"
    assert retrieval_v2.name == "retrieval_v2_rerank"
    assert retrieval_v2.second_stage_rerank is True
    assert candidate_limit_for_profile(default_profile, top_k=8) == 64
    assert candidate_limit_for_profile(retrieval_v2, top_k=8) == 96
    assert candidate_limit_for_profile(retrieval_v2, top_k=50) == 100
    assert manifest["retrieval_v2_rerank"]["candidate_pool"] == {"multiplier": 12, "min": 80, "max": 100}


def test_retrieval_v2_merged_candidate_pool_is_capped_before_rerank() -> None:
    profile = normalize_retrieval_profile("retrieval-v2-rerank")
    candidate_limit = candidate_limit_for_profile(profile, top_k=50)
    candidates = [_candidate(path=f"docs/improve-{index:03}.md", content_hash=f"hash-{index}") for index in range(120)]
    for rank, candidate in enumerate(candidates):
        candidate.lexical_score = float(120 - rank)

    bounded, metadata = bound_merged_candidate_pool(
        candidates,
        query="Which temporal improvements matter?",
        retrieval_profile=profile,
        candidate_limit=candidate_limit,
    )

    assert candidate_limit == 100
    assert len(bounded) == 100
    assert metadata == {
        "candidate_pool_limit": 100,
        "merged_first_stage_candidate_count": 120,
        "candidate_pool_truncated": True,
        "reranked_candidate_count": 100,
    }
    assert bounded[0].path == "docs/improve-000.md"
    assert bounded[-1].path == "docs/improve-099.md"
    assert bounded[0].ranking_diagnostics["merged_first_stage_candidate_count"] == 120


def test_retrieval_v2_reranks_at_most_the_bounded_merged_pool(monkeypatch) -> None:
    class _Rows:
        def __init__(self, rows):
            self._rows = rows

        def mappings(self):
            return self

        def all(self):
            return self._rows

    class _Session:
        def __init__(self, lexical_rows, vector_rows):
            self.lexical_rows = lexical_rows
            self.vector_rows = vector_rows

        def execute(self, statement, params):
            sql = str(statement)
            if "ts_rank" in sql:
                return _Rows(self.lexical_rows)
            if "JOIN chunk_embeddings" in sql:
                return _Rows(self.vector_rows)
            if "JOIN graph_nodes" in sql:
                return _Rows([])
            raise AssertionError(f"unexpected query: {sql[:120]}")

    def row(index: int, *, score: float):
        return {
            "chunk_id": uuid4(),
            "resource_id": uuid4(),
            "source_snapshot_id": uuid4(),
            "path": f"docs/improve-{index:03}.md",
            "title": None,
            "ordinal": index,
            "content_hash": f"hash-{index}",
            "content": f"temporal improvement evidence {index}",
            "version": "v1",
            "version_kind": "commit",
            "snap_meta": {},
            "score": score,
        }

    lexical_rows = [row(index, score=200.0 - index) for index in range(100)]
    vector_rows = [row(100 + index, score=100.0 - index) for index in range(100)]
    rerank_batch_sizes: list[int] = []
    monkeypatch.setattr("sourcebrief_api.retrieval.embed_text", lambda query, *, config: [0.0] * config.dimensions)

    def fake_rerank_scores(query: str, contents: list[str]) -> list[float]:
        rerank_batch_sizes.append(len(contents))
        return [1.0 - (index / 1000.0) for index, _ in enumerate(contents)]

    monkeypatch.setattr("sourcebrief_api.retrieval.rerank_scores", fake_rerank_scores)

    selected = retrieve_context_candidates(
        _Session(lexical_rows, vector_rows),
        workspace_id=uuid4(),
        project_id=uuid4(),
        query="Which temporal improvements matter?",
        top_k=50,
        profile="retrieval_v2_rerank",
    )

    assert rerank_batch_sizes == [100]
    assert selected
    diversity = selected[0].ranking_diagnostics["retrieval_diversity"]
    assert diversity["merged_first_stage_candidate_count"] == 200
    assert diversity["reranked_candidate_count"] == 100
    assert diversity["candidate_pool_truncated"] is True


def test_retrieval_v2_profile_is_accepted_by_public_request_schemas() -> None:
    assert AgentContextRequest(query="temporal evidence", profile="retrieval-v2-rerank").profile == "retrieval-v2-rerank"
    assert ContextPacketRequest(query="temporal evidence", profile="retrieval_v2_rerank").profile == "retrieval_v2_rerank"
    request = RetrievalEvalRequest(
        profile="retrieval-v2-rerank",
        questions=[RetrievalEvalQuestion(id="q1", query="temporal evidence")],
    )
    assert request.profile == "retrieval-v2-rerank"


def test_second_stage_sibling_promotion_preserves_same_sequence_multi_evidence() -> None:
    candidates = [
        _candidate(path="demo/evo_temporal_sections/improve-003.md", content_hash="improve-003", score=1.0),
        _candidate(path="demo/evo_temporal_sections/decision-001.md", content_hash="decision-001", score=0.99),
        _candidate(path="demo/evo_temporal_sections/review-001.md", content_hash="review-001", score=0.98),
        _candidate(path="demo/evo_temporal_sections/improve-004.md", content_hash="improve-004", score=0.70),
    ]

    promoted, metadata = promote_sequence_siblings_for_second_stage(candidates, top_k=3, lookahead=4)
    selected, _ = diversify_ranked_candidates(promoted, top_k=3)

    selected_paths = [candidate.path for candidate in selected]
    assert selected_paths[:2] == [
        "demo/evo_temporal_sections/improve-003.md",
        "demo/evo_temporal_sections/improve-004.md",
    ]
    assert metadata["promoted_count"] == 1
    assert selected[1].ranking_diagnostics["second_stage_sibling_promoted"] is True
