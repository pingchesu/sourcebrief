from __future__ import annotations

from contextsmith_shared.embeddings import (
    EmbeddingConfig,
    embed_text,
    embedding_namespace,
    normalize_rerank_score,
    rerank_score,
    term_overlap_score,
    vector_literal,
    verify_provider_health,
)


def test_hashing_embedding_is_deterministic_and_normalized() -> None:
    first = embed_text("Resource lifecycle cleanup")
    second = embed_text("Resource lifecycle cleanup")
    assert first == second
    assert len(first) == 64
    assert any(value != 0 for value in first)
    norm = sum(value * value for value in first) ** 0.5
    assert 0.999 <= norm <= 1.001


def test_vector_literal_matches_pgvector_format() -> None:
    literal = vector_literal([0.5, -0.25])
    assert literal == "[0.50000000,-0.25000000]"


def test_term_overlap_score() -> None:
    assert term_overlap_score("resource cleanup", "cleanup old resource versions") == 1.0
    assert term_overlap_score("resource cleanup", "unrelated text") == 0.0


def test_configurable_hashing_dimensions_and_rerank() -> None:
    config = EmbeddingConfig(provider="hashing", dimensions=16)
    vector = embed_text("graph retrieval", config=config)
    assert len(vector) == 16
    assert embedding_namespace(config) == "hashing:contextsmith-hashing-v1:d16:l2"
    assert rerank_score("graph retrieval", "retrieval uses graph nodes") == 1.0


def test_rerank_normalization_and_provider_health(monkeypatch) -> None:
    assert normalize_rerank_score(1.8) == 1.0
    assert normalize_rerank_score(-0.5) == 0.0
    assert normalize_rerank_score(float("nan")) == 0.0
    health = verify_provider_health()
    assert health["status"] == "ok"
    assert health["embedding"]["namespace"].endswith(":d64:l2")
    assert health["embedding"]["dev_quality"] is True
    assert health["rerank"]["score_range"] == [0.0, 1.0]

    remote_config = EmbeddingConfig(
        provider="vllm",
        model="bge-m3",
        dimensions=64,
        endpoint="http://embed-a.local/v1/embeddings",
        deployment_id="prod-a",
    )
    assert embedding_namespace(remote_config) == "vllm:bge-m3:d64:l2:dep-prod-a"

    monkeypatch.delenv("CONTEXTSMITH_EMBEDDING_DEPLOYMENT_ID", raising=False)
    monkeypatch.setenv("CONTEXTSMITH_EMBEDDING_PROVIDER", "vllm")
    monkeypatch.setenv("CONTEXTSMITH_EMBEDDING_MODEL", "bge-m3")
    monkeypatch.setenv("CONTEXTSMITH_EMBEDDING_ENDPOINT", "http://embed-a.local/v1/embeddings")
    first = embedding_namespace()
    monkeypatch.setenv("CONTEXTSMITH_EMBEDDING_ENDPOINT", "http://embed-b.local/v1/embeddings")
    second = embedding_namespace()
    assert first != second
    assert first.startswith("vllm:bge-m3:d64:l2:dep-endpoint-")
