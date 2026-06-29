#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel, Field

_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
MAX_RERANK_DOCUMENTS = 512


class RerankRequest(BaseModel):
    query: str = Field(min_length=1)
    documents: list[str] = Field(min_length=1, max_length=MAX_RERANK_DOCUMENTS)
    top_k: int | None = Field(default=None, ge=1, le=MAX_RERANK_DOCUMENTS)
    model: str | None = None
    return_documents: bool = False


class RerankResult(BaseModel):
    index: int
    score: float
    text: str | None = None


class RerankResponse(BaseModel):
    model: str
    backend: str
    tokenizer_name: str | None = None
    scores: list[float]
    results: list[RerankResult]
    dev_quality: bool = False


@dataclass
class SidecarConfig:
    backend: str
    model: str
    repo_path: str | None = None
    device: str | None = None
    tokenizer_name: str | None = None


class BaseBackend:
    dev_quality = False

    def rerank(self, query: str, documents: list[str], *, top_k: int | None = None, return_documents: bool = False) -> tuple[list[float], list[RerankResult]]:
        raise NotImplementedError


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in _TOKEN_RE.findall(text)}


def _normalize_score(value: float) -> float:
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(1.0, value))


class DeterministicBackend(BaseBackend):
    """Contract-test backend. It is intentionally dev-quality, not adoption evidence."""

    dev_quality = True

    def rerank(self, query: str, documents: list[str], *, top_k: int | None = None, return_documents: bool = False) -> tuple[list[float], list[RerankResult]]:
        q_terms = _tokens(query)
        scores: list[float] = []
        for doc in documents:
            d_terms = _tokens(doc)
            overlap = len(q_terms & d_terms) / len(q_terms) if q_terms else 0.0
            digest = hashlib.blake2b((query + "\0" + doc).encode(), digest_size=2).digest()
            tie_breaker = int.from_bytes(digest, "big") / 65535 * 0.001
            scores.append(_normalize_score(overlap + tie_breaker))
        ranked = sorted(range(len(documents)), key=lambda idx: (-scores[idx], idx))
        if top_k is not None:
            ranked = ranked[:top_k]
        results = [RerankResult(index=idx, score=scores[idx], text=documents[idx] if return_documents else None) for idx in ranked]
        return scores, results


class EvoEmbeddingBackend(BaseBackend):
    """Thin adapter around MiG-NJU/EvoEmbedding's `model.client.EvoEmbeddingClient`."""

    def __init__(self, config: SidecarConfig) -> None:
        if config.repo_path:
            repo = Path(config.repo_path).expanduser().resolve()
            if not repo.exists():
                raise RuntimeError(f"EVOEMBEDDING_REPO_PATH does not exist: {repo}")
            sys.path.insert(0, str(repo))
        try:
            module = importlib.import_module("model.client")
            client_cls = module.EvoEmbeddingClient
        except Exception as exc:  # noqa: BLE001 - dependency errors must surface in health/startup
            raise RuntimeError("failed to import EvoEmbeddingClient; set EVOEMBEDDING_REPO_PATH and install EvoEmbedding requirements") from exc
        kwargs: dict[str, Any] = {
            "model_path": config.model,
        }
        if config.tokenizer_name:
            kwargs["tokenizer_name"] = config.tokenizer_name
        if config.device:
            kwargs["device"] = config.device
        self.client = client_cls(**kwargs)

    def rerank(self, query: str, documents: list[str], *, top_k: int | None = None, return_documents: bool = False) -> tuple[list[float], list[RerankResult]]:
        call_top_k = top_k or len(documents)
        ranked, ranked_indices = self.client.rerank(query, documents, top_k=call_top_k, return_indices=True)
        index_list = [int(idx) for idx in ranked_indices]
        # Upstream returns ranked documents/indices, not always raw scores. Produce rank-normalized
        # scores for SourceBrief's current [0,1] rerank contract until a score-returning upstream
        # API is available.
        ranked_score_by_index = {
            idx: _normalize_score(1.0 - (rank / max(len(index_list), 1)))
            for rank, idx in enumerate(index_list)
        }
        scores = [ranked_score_by_index.get(idx, 0.0) for idx in range(len(documents))]
        results = [
            RerankResult(index=idx, score=scores[idx], text=(ranked[rank] if return_documents else None))
            for rank, idx in enumerate(index_list)
        ]
        return scores, results


def build_backend(config: SidecarConfig) -> BaseBackend:
    if config.backend in {"deterministic", "mock", "dev"}:
        return DeterministicBackend()
    if config.backend == "evoembedding":
        return EvoEmbeddingBackend(config)
    raise RuntimeError(f"unsupported backend {config.backend!r}")


def create_app(config: SidecarConfig | None = None) -> FastAPI:
    config = config or SidecarConfig(
        backend=os.getenv("EVOEMBEDDING_BACKEND", "deterministic"),
        model=os.getenv("EVOEMBEDDING_MODEL", "MiG-NJU/EvoEmbedding-0.8B"),
        repo_path=os.getenv("EVOEMBEDDING_REPO_PATH"),
        device=os.getenv("EVOEMBEDDING_DEVICE"),
        tokenizer_name=os.getenv("EVOEMBEDDING_TOKENIZER_NAME"),
    )
    app = FastAPI(title="SourceBrief EvoEmbedding Rerank Sidecar", version="0.1.0")
    backend: BaseBackend | None = None
    startup_error: str | None = None
    try:
        backend = build_backend(config)
    except Exception as exc:  # noqa: BLE001 - expose startup failure through healthz
        startup_error = str(exc)

    @app.get("/healthz")
    def healthz(response: Response) -> dict[str, Any]:
        if backend is None:
            response.status_code = 503
        return {
            "status": "ok" if backend is not None else "failed",
            "backend": config.backend,
            "model": config.model,
            "tokenizer_name": config.tokenizer_name,
            "dev_quality": bool(getattr(backend, "dev_quality", False)) if backend is not None else None,
            "error": startup_error,
        }

    @app.post("/rerank", response_model=RerankResponse)
    def rerank(request: RerankRequest) -> RerankResponse:
        if backend is None:
            raise HTTPException(status_code=503, detail=startup_error or "backend unavailable")
        if request.model and request.model != config.model:
            raise HTTPException(
                status_code=400,
                detail=f"request model {request.model!r} does not match loaded sidecar model {config.model!r}",
            )
        top_k = request.top_k or len(request.documents)
        scores, results = backend.rerank(request.query, request.documents, top_k=top_k, return_documents=request.return_documents)
        return RerankResponse(
            model=config.model,
            backend=config.backend,
            tokenizer_name=config.tokenizer_name,
            scores=scores,
            results=results,
            dev_quality=backend.dev_quality,
        )

    return app


app = create_app()


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve a SourceBrief-compatible EvoEmbedding rerank sidecar.")
    parser.add_argument("--host", default=os.getenv("EVOEMBEDDING_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("EVOEMBEDDING_PORT", "18180")))
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
