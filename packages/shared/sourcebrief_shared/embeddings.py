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
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def _env(name: str, legacy: str | None = None, default: str | None = None) -> str | None:
    if name in os.environ:
        return os.environ[name]
    if legacy and legacy in os.environ:
        return os.environ[legacy]
    return default


def _env_float(name: str, legacy: str | None = None, default: float = 30.0) -> float:
    raw = _env(name, legacy, str(default))
    return float(raw if raw is not None else default)


DEFAULT_EMBEDDING_PROVIDER = _env("SOURCEBRIEF_EMBEDDING_PROVIDER", "CONTEXTSMITH_EMBEDDING_PROVIDER", "hashing") or "hashing"
DEFAULT_EMBEDDING_MODEL = _env("SOURCEBRIEF_EMBEDDING_MODEL", "CONTEXTSMITH_EMBEDDING_MODEL", "sourcebrief-hashing-v1") or "sourcebrief-hashing-v1"
DEFAULT_RERANK_PROVIDER = _env("SOURCEBRIEF_RERANK_PROVIDER", "CONTEXTSMITH_RERANK_PROVIDER", "term-overlap") or "term-overlap"
DEFAULT_RERANK_MODEL = _env("SOURCEBRIEF_RERANK_MODEL", "CONTEXTSMITH_RERANK_MODEL", "sourcebrief-term-overlap-v1") or "sourcebrief-term-overlap-v1"


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str = DEFAULT_EMBEDDING_PROVIDER
    model: str = DEFAULT_EMBEDDING_MODEL
    dimensions: int = EMBEDDING_DIMENSIONS
    normalized: bool = True
    deployment_id: str | None = None
    endpoint: str | None = _env("SOURCEBRIEF_EMBEDDING_ENDPOINT", "CONTEXTSMITH_EMBEDDING_ENDPOINT")
    api_key: str | None = _env("SOURCEBRIEF_EMBEDDING_API_KEY", "CONTEXTSMITH_EMBEDDING_API_KEY")
    timeout: float = _env_float("SOURCEBRIEF_EMBEDDING_TIMEOUT", "CONTEXTSMITH_EMBEDDING_TIMEOUT", 30)


@dataclass(frozen=True)
class RerankConfig:
    provider: str = DEFAULT_RERANK_PROVIDER
    model: str = DEFAULT_RERANK_MODEL
    endpoint: str | None = _env("SOURCEBRIEF_RERANK_ENDPOINT", "CONTEXTSMITH_RERANK_ENDPOINT")
    api_key: str | None = _env("SOURCEBRIEF_RERANK_API_KEY", "CONTEXTSMITH_RERANK_API_KEY")
    timeout: float = _env_float("SOURCEBRIEF_RERANK_TIMEOUT", "CONTEXTSMITH_RERANK_TIMEOUT", 30)


def _safe_deployment_id(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-._")
    return cleaned[:64] or "unnamed"


def _derived_deployment_id(provider: str, endpoint: str | None) -> str | None:
    explicit = _env("SOURCEBRIEF_EMBEDDING_DEPLOYMENT_ID", "CONTEXTSMITH_EMBEDDING_DEPLOYMENT_ID")
    if explicit:
        return _safe_deployment_id(explicit)
    if provider not in {"http", "openai", "openai-compatible", "huggingface", "vllm", "sglang"} or not endpoint:
        return None
    return "endpoint-" + hashlib.sha256(endpoint.encode("utf-8")).hexdigest()[:12]


def current_embedding_config() -> EmbeddingConfig:
    provider = _env("SOURCEBRIEF_EMBEDDING_PROVIDER", "CONTEXTSMITH_EMBEDDING_PROVIDER", DEFAULT_EMBEDDING_PROVIDER) or DEFAULT_EMBEDDING_PROVIDER
    endpoint = _env("SOURCEBRIEF_EMBEDDING_ENDPOINT", "CONTEXTSMITH_EMBEDDING_ENDPOINT")
    return EmbeddingConfig(
        provider=provider,
        model=_env("SOURCEBRIEF_EMBEDDING_MODEL", "CONTEXTSMITH_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL) or DEFAULT_EMBEDDING_MODEL,
        dimensions=EMBEDDING_DIMENSIONS,
        normalized=(_env("SOURCEBRIEF_EMBEDDING_NORMALIZED", "CONTEXTSMITH_EMBEDDING_NORMALIZED", "true") or "true").lower() not in {"0", "false", "no"},
        deployment_id=_derived_deployment_id(provider, endpoint),
        endpoint=endpoint,
        api_key=_env("SOURCEBRIEF_EMBEDDING_API_KEY", "CONTEXTSMITH_EMBEDDING_API_KEY"),
        timeout=_env_float("SOURCEBRIEF_EMBEDDING_TIMEOUT", "CONTEXTSMITH_EMBEDDING_TIMEOUT", 30),
    )


def current_rerank_config() -> RerankConfig:
    return RerankConfig(
        provider=_env("SOURCEBRIEF_RERANK_PROVIDER", "CONTEXTSMITH_RERANK_PROVIDER", DEFAULT_RERANK_PROVIDER) or DEFAULT_RERANK_PROVIDER,
        model=_env("SOURCEBRIEF_RERANK_MODEL", "CONTEXTSMITH_RERANK_MODEL", DEFAULT_RERANK_MODEL) or DEFAULT_RERANK_MODEL,
        endpoint=_env("SOURCEBRIEF_RERANK_ENDPOINT", "CONTEXTSMITH_RERANK_ENDPOINT"),
        api_key=_env("SOURCEBRIEF_RERANK_API_KEY", "CONTEXTSMITH_RERANK_API_KEY"),
        timeout=_env_float("SOURCEBRIEF_RERANK_TIMEOUT", "CONTEXTSMITH_RERANK_TIMEOUT", 30),
    )


def embedding_namespace(config: EmbeddingConfig | None = None) -> str:
    config = config or current_embedding_config()
    normalized = "l2" if config.normalized else "raw"
    base = f"{config.provider}:{config.model}:d{config.dimensions}:{normalized}"
    if config.deployment_id:
        return f"{base}:dep-{_safe_deployment_id(config.deployment_id)}"
    return base


def is_dev_embedding_provider(config: EmbeddingConfig | None = None) -> bool:
    config = config or current_embedding_config()
    return config.provider in {"hashing", "deterministic", "dev"}


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in _TOKEN_RE.findall(text)]


def _normalize_vector(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return vector
    return [value / norm for value in vector]


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
    return _normalize_vector(vector)


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
        raise RuntimeError(f"embedding provider {config.provider!r} requires SOURCEBRIEF_EMBEDDING_ENDPOINT")
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
            f"embedding provider returned {len(embedding)} dimensions; SourceBrief MVP storage expects {config.dimensions}"
        )
    return [float(value) for value in embedding]


def embed_text(text: str, *, dimensions: int | None = None, config: EmbeddingConfig | None = None) -> list[float]:
    """Return an embedding for ``text``.

    The default provider is deterministic hashing for offline dev/test. Operators
    can set `SOURCEBRIEF_EMBEDDING_PROVIDER=http` plus an OpenAI-compatible
    `SOURCEBRIEF_EMBEDDING_ENDPOINT` for HuggingFace/vLLM/SGLang-style services.
    """
    config = config or current_embedding_config()
    dims = dimensions or config.dimensions
    if dims <= 0:
        raise ValueError("dimensions must be positive")
    if config.provider in {"hashing", "deterministic", "dev"}:
        return _hashing_embedding(text, dimensions=dims)
    if config.provider in {"http", "openai", "openai-compatible", "huggingface", "vllm", "sglang"}:
        vector = _remote_embedding(text, config)
        return _normalize_vector(vector) if config.normalized else vector
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


def normalize_rerank_score(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


def rerank_score(query: str, content: str, *, config: RerankConfig | None = None) -> float:
    config = config or current_rerank_config()
    if config.provider in {"term-overlap", "overlap", "dev", "deterministic"}:
        return term_overlap_score(query, content)
    if config.provider in {"http", "huggingface", "vllm", "sglang"}:
        if not config.endpoint:
            raise RuntimeError(f"rerank provider {config.provider!r} requires SOURCEBRIEF_RERANK_ENDPOINT")
        result = _post_json(
            config.endpoint,
            {"model": config.model, "query": query, "documents": [content]},
            api_key=config.api_key,
            timeout=config.timeout,
        )
        if isinstance(result.get("scores"), list) and result["scores"]:
            return normalize_rerank_score(float(result["scores"][0]))
        if isinstance(result.get("results"), list) and result["results"]:
            first = result["results"][0]
            if isinstance(first, dict) and "score" in first:
                return normalize_rerank_score(float(first["score"]))
        if "score" in result:
            return normalize_rerank_score(float(result["score"]))
        raise RuntimeError("rerank provider returned no score")
    raise RuntimeError(f"unsupported rerank provider: {config.provider}")


def verify_provider_health() -> dict:
    embedding_config = current_embedding_config()
    rerank_config = current_rerank_config()
    embedding_status = "ok"
    rerank_status = "ok"
    embedding_error: str | None = None
    rerank_error: str | None = None
    try:
        vector = embed_text("sourcebrief provider health probe", config=embedding_config)
        if len(vector) != embedding_config.dimensions:
            raise RuntimeError(f"expected {embedding_config.dimensions} dimensions, got {len(vector)}")
        if embedding_config.normalized:
            norm = math.sqrt(sum(value * value for value in vector))
            if vector and norm > 0 and not 0.99 <= norm <= 1.01:
                raise RuntimeError(f"embedding norm {norm:.4f} is not normalized")
    except Exception as exc:  # pragma: no cover - exercised through API/integration paths
        embedding_status = "failed"
        embedding_error = str(exc)
    try:
        score = rerank_score("provider health", "provider health probe", config=rerank_config)
        if not 0.0 <= score <= 1.0:
            raise RuntimeError(f"rerank score out of range: {score}")
    except Exception as exc:  # pragma: no cover
        rerank_status = "failed"
        rerank_error = str(exc)
    return {
        "status": "ok" if embedding_status == "ok" and rerank_status == "ok" else "failed",
        "embedding": {
            "status": embedding_status,
            "provider": embedding_config.provider,
            "model": embedding_config.model,
            "dimensions": embedding_config.dimensions,
            "normalized": embedding_config.normalized,
            "namespace": embedding_namespace(embedding_config),
            "deployment_id": embedding_config.deployment_id,
            "dev_quality": is_dev_embedding_provider(embedding_config),
            "error": embedding_error,
        },
        "rerank": {
            "status": rerank_status,
            "provider": rerank_config.provider,
            "model": rerank_config.model,
            "score_range": [0.0, 1.0],
            "dev_quality": rerank_config.provider in {"term-overlap", "overlap", "dev", "deterministic"},
            "error": rerank_error,
        },
    }
