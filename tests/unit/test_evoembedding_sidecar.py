from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "evoembedding_sidecar.py"
spec = importlib.util.spec_from_file_location("evoembedding_sidecar", SCRIPT)
assert spec is not None and spec.loader is not None
evoembedding_sidecar = importlib.util.module_from_spec(spec)
sys.modules["evoembedding_sidecar"] = evoembedding_sidecar
spec.loader.exec_module(evoembedding_sidecar)

SidecarConfig = evoembedding_sidecar.SidecarConfig
create_app = evoembedding_sidecar.create_app


def test_deterministic_sidecar_rerank_contract() -> None:
    app = create_app(SidecarConfig(backend="deterministic", model="contract-test"))
    client = TestClient(app)

    health = client.get("/healthz")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["dev_quality"] is True

    response = client.post(
        "/rerank",
        json={
            "query": "where did I travel in spring",
            "documents": ["I bought a new laptop yesterday.", "I visited Paris in April."],
            "top_k": 1,
            "return_documents": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["backend"] == "deterministic"
    assert body["model"] == "contract-test"
    assert len(body["scores"]) == 2
    assert body["results"][0]["index"] == 1
    assert "Paris" in body["results"][0]["text"]
    assert 0.0 <= body["results"][0]["score"] <= 1.0


def test_sidecar_accepts_sourcebrief_max_candidate_batch() -> None:
    app = create_app(SidecarConfig(backend="deterministic", model="contract-test"))
    client = TestClient(app)
    documents = [f"candidate {index}" for index in range(400)]

    response = client.post(
        "/rerank",
        json={"query": "candidate 399", "documents": documents, "top_k": 50},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["scores"]) == 400
    assert len(body["results"]) == 50


def test_evo_backend_missing_dependency_reports_failed_health() -> None:
    app = create_app(SidecarConfig(backend="evoembedding", model="MiG-NJU/EvoEmbedding-0.8B", repo_path="/definitely/missing"))
    client = TestClient(app)

    health = client.get("/healthz")
    assert health.status_code == 503
    assert health.json()["status"] == "failed"

    response = client.post("/rerank", json={"query": "q", "documents": ["d"]})
    assert response.status_code == 503


def test_evo_backend_uses_upstream_constructor_and_rerank_contract(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured["kwargs"] = kwargs

        def rerank(self, query, candidates, top_k=None, return_indices=False):
            captured["rerank"] = {
                "query": query,
                "candidates": candidates,
                "top_k": top_k,
                "return_indices": return_indices,
            }
            assert return_indices is True
            return [candidates[1], candidates[0]], [1, 0]

    class FakeModule:
        EvoEmbeddingClient = FakeClient

    monkeypatch.setattr(evoembedding_sidecar.importlib, "import_module", lambda name: FakeModule)
    app = create_app(
        SidecarConfig(
            backend="evoembedding",
            model="MiG-NJU/EvoEmbedding-0.8B",
            device="cpu",
            tokenizer_name="Qwen/Qwen3-0.6B-Instruct-2507",
        )
    )
    client = TestClient(app)

    assert client.get("/healthz").json()["status"] == "ok"
    assert captured["kwargs"] == {
        "model_path": "MiG-NJU/EvoEmbedding-0.8B",
        "tokenizer_name": "Qwen/Qwen3-0.6B-Instruct-2507",
        "device": "cpu",
    }
    response = client.post(
        "/rerank",
        json={"query": "q", "documents": ["old", "new"], "top_k": 2, "return_documents": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dev_quality"] is False
    assert body["scores"] == [0.5, 1.0]
    assert [item["index"] for item in body["results"]] == [1, 0]
    assert [item["text"] for item in body["results"]] == ["new", "old"]
    assert captured["rerank"] == {
        "query": "q",
        "candidates": ["old", "new"],
        "top_k": 2,
        "return_indices": True,
    }


def test_sidecar_rejects_request_model_mismatch() -> None:
    app = create_app(SidecarConfig(backend="deterministic", model="loaded-model"))
    client = TestClient(app)

    response = client.post(
        "/rerank",
        json={"model": "other-model", "query": "q", "documents": ["d"]},
    )
    assert response.status_code == 400
    assert "does not match loaded sidecar model" in response.json()["detail"]
