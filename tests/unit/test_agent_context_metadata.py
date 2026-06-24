from __future__ import annotations

from uuid import uuid4

from sourcebrief_api.main import _agent_context_retrieval_metadata
from sourcebrief_api.retrieval import RetrievalCandidate


def _candidate(path: str, diagnostics: dict, resource_id=None) -> RetrievalCandidate:
    return RetrievalCandidate(
        chunk_id=uuid4(),
        resource_id=resource_id or uuid4(),
        snapshot_id=uuid4(),
        path=path,
        title=None,
        ordinal=1,
        content_hash=path,
        content="content",
        version="v1",
        version_kind="commit",
        snapshot_metadata={},
        ranking_diagnostics=diagnostics,
    )


def test_agent_context_retrieval_metadata_describes_used_citations_not_full_retriever_pool() -> None:
    candidate = _candidate(
        "README.md",
        {
            "path_prior_reasons": ["primary_readme"],
            "retrieval_diversity": {
                "candidate_pool_count": 10,
                "selected_count": 8,
                "unique_citation_paths": 8,
                "duplicate_citation_count": 0,
                "deduped_from_count": 2,
            },
        },
    )

    metadata = _agent_context_retrieval_metadata([candidate])

    assert metadata["selected_count"] == 1
    assert metadata["unique_citation_paths"] == 1
    assert metadata["duplicate_citation_count"] == 0
    assert metadata["candidate_pool_count"] == 10
    assert metadata["deduped_from_count"] == 2
    assert metadata["retriever_selected_count"] == 8
    assert metadata["retriever_unique_citation_paths"] == 8
    assert metadata["path_prior_hits"] == {"primary_readme": 1}


def test_agent_context_retrieval_metadata_discloses_requested_resource_gaps() -> None:
    resource_a = uuid4()
    resource_b = uuid4()
    candidate = _candidate("README.md", {"path_prior_reasons": ["primary_readme"]}, resource_id=resource_a)

    metadata = _agent_context_retrieval_metadata([candidate], [resource_a, resource_b])

    assert metadata["requested_resource_ids"] == [str(resource_a), str(resource_b)]
    assert metadata["cited_resource_counts"] == {str(resource_a): 1}
    assert metadata["missing_requested_resource_ids"] == [str(resource_b)]
