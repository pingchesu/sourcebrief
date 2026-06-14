from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

EMBEDDING_DIMENSIONS = 64
DEFAULT_EMBEDDING_PROVIDER = os.getenv("CONTEXTSMITH_EMBEDDING_PROVIDER", "hashing")
DEFAULT_EMBEDDING_MODEL = os.getenv("CONTEXTSMITH_EMBEDDING_MODEL", "contextsmith-hashing-v1")
DEFAULT_RERANK_PROVIDER = os.getenv("CONTEXTSMITH_RERANK_PROVIDER", "term-overlap")
DEFAULT_RERANK_MODEL = os.getenv("CONTEXTSMITH_RERANK_MODEL", "contextsmith-term-overlap-v1")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str = DEFAULT_EMBEDDING_PROVIDER
    model: str = DEFAULT_EMBEDDING_MODEL
    dimensions: int = EMBEDDING_DIMENSIONS
    endpoint: str | None = os.getenv("CONTEXTSMITH_EMBEDDING_ENDPOINT")
    api_key: str | None = os.getenv("CONTEXTSMITH_EMBEDDING_API_KEY")
    timeout: float = float(os.getenv("CONTEXTSMITH_EMBEDDING_TIMEOUT", "30"))


@dataclass(frozen=True)
class RerankConfig:
    provider: str = DEFAULT_RERANK_PROVIDER
    model: str = DEFAULT_RERANK_MODEL
    endpoint: str | None = os.getenv("CONTEXTSMITH_RERANK_ENDPOINT")
    api_key: str | None = os.getenv("CONTEXTSMITH_RERANK_API_KEY")
    timeout: float = float(os.getenv("CONTEXTSMITH_RERANK_TIMEOUT", "30"))


def current_embedding_config() -> EmbeddingConfig:
    return EmbeddingConfig(
        provider=os.getenv("CONTEXTSMITH_EMBEDDING_PROVIDER", DEFAULT_EMBEDDING_PROVIDER),
        model=os.getenv("CONTEXTSMITH_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL),
        dimensions=EMBEDDING_DIMENSIONS,
        endpoint=os.getenv("CONTEXTSMITH_EMBEDDING_ENDPOINT"),
        api_key=os.getenv("CONTEXTSMITH_EMBEDDING_API_KEY"),
        timeout=float(os.getenv("CONTEXTSMITH_EMBEDDING_TIMEOUT", "30")),
    )


def current_rerank_config() -> RerankConfig:
    return RerankConfig(
        provider=os.getenv("CONTEXTSMITH_RERANK_PROVIDER", DEFAULT_RERANK_PROVIDER),
        model=os.getenv("CONTEXTSMITH_RERANK_MODEL", DEFAULT_RERANK_MODEL),
        endpoint=os.getenv("CONTEXTSMITH_RERANK_ENDPOINT"),
        api_key=os.getenv("CONTEXTSMITH_RERANK_API_KEY"),
        timeout=float(os.getenv("CONTEXTSMITH_RERANK_TIMEOUT", "30")),
    )


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text)]


def _hashing_embedding(text: str, *, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    tokens = tokenize(text)
    if not tokens and text:
        tokens = [text.lower()[:128]]
    for token in tokens:
        digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:4], "big") % dimensions
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[bucket] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _post_json(endpoint: str, payload: dict, *, api_key: str | None, timeout: float) -> dict:
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(endpoint, data=data, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - endpoint is operator-configured
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"embedding/rerank provider request failed: {exc}") from exc


def _remote_embedding(text: str, config: EmbeddingConfig) -> list[float]:
    if not config.endpoint:
        raise RuntimeError(f"embedding provider {config.provider!r} requires CONTEXTSMITH_EMBEDDING_ENDPOINT")
    payload = {"model": config.model, "input": text}
    result = _post_json(config.endpoint, payload, api_key=config.api_key, timeout=config.timeout)
    if isinstance(result.get("data"), list) and result["data"]:
        embedding = result["data"][0].get("embedding")
    else:
        embedding = result.get("embedding")
    if not isinstance(embedding, list) or not all(isinstance(value, int | float) for value in embedding):
        raise RuntimeError("embedding provider returned no numeric embedding")
    if len(embedding) != config.dimensions:
        raise RuntimeError(
            f"embedding provider returned {len(embedding)} dimensions; ContextSmith MVP storage expects {config.dimensions}"
        )
    return [float(value) for value in embedding]


def embed_text(text: str, *, dimensions: int | None = None, config: EmbeddingConfig | None = None) -> list[float]:
    """Return an embedding for ``text``.

    The default provider is deterministic hashing for offline dev/test. Operators
    can set `CONTEXTSMITH_EMBEDDING_PROVIDER=http` plus an OpenAI-compatible
    `CONTEXTSMITH_EMBEDDING_ENDPOINT` for HuggingFace/vLLM/SGLang-style services.
    """
    config = config or current_embedding_config()
    dims = dimensions or config.dimensions
    if dims <= 0:
        raise ValueError("dimensions must be positive")
    if config.provider in {"hashing", "deterministic", "dev"}:
        return _hashing_embedding(text, dimensions=dims)
    if config.provider in {"http", "openai", "openai-compatible", "huggingface", "vllm", "sglang"}:
        return _remote_embedding(text, config)
    raise RuntimeError(f"unsupported embedding provider: {config.provider}")


def vector_literal(vector: list[float]) -> str:
    """Serialize a vector for pgvector CAST(:value AS vector)."""
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


def term_overlap_score(query: str, content: str) -> float:
    """Simple deterministic dev reranker score in [0, 1]."""
    query_terms = set(tokenize(query))
    if not query_terms:
        return 0.0
    content_terms = set(tokenize(content))
    if not content_terms:
        return 0.0
    return len(query_terms & content_terms) / len(query_terms)


def _clamp_score(value: float) -> float:
    return max(0.0, min(1.0, value))


def rerank_score(query: str, content: str, *, config: RerankConfig | None = None) -> float:
    config = config or current_rerank_config()
    if config.provider in {"term-overlap", "overlap", "dev", "deterministic"}:
        return term_overlap_score(query, content)
    if config.provider in {"http", "huggingface", "vllm", "sglang"}:
        if not config.endpoint:
            raise RuntimeError(f"rerank provider {config.provider!r} requires CONTEXTSMITH_RERANK_ENDPOINT")
        result = _post_json(
            config.endpoint,
            {"model": config.model, "query": query, "documents": [content]},
            api_key=config.api_key,
            timeout=config.timeout,
        )
        if isinstance(result.get("scores"), list) and result["scores"]:
            return _clamp_score(float(result["scores"][0]))
        if isinstance(result.get("results"), list) and result["results"]:
            first = result["results"][0]
            if isinstance(first, dict) and "score" in first:
                return _clamp_score(float(first["score"]))
        if "score" in result:
            return _clamp_score(float(result["score"]))
        raise RuntimeError("rerank provider returned no score")
    raise RuntimeError(f"unsupported rerank provider: {config.provider}")
