from __future__ import annotations

import importlib.util
from pathlib import Path


def load_qa_smoke():
    script = Path(__file__).resolve().parents[2] / "scripts" / "qa_smoke.py"
    spec = importlib.util.spec_from_file_location("qa_smoke_under_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_qa_smoke_urls_follow_env(monkeypatch):
    monkeypatch.setenv("CONTEXTSMITH_API_URL", "http://localhost:18123")
    monkeypatch.setenv("CONTEXTSMITH_WEB_URL", "http://localhost:13123")

    module = load_qa_smoke()

    assert module.BASE == "http://localhost:18123"
    assert module.FRONTEND == "http://localhost:13123"


def test_qa_smoke_urls_fall_back_to_make_vars(monkeypatch):
    monkeypatch.delenv("CONTEXTSMITH_API_URL", raising=False)
    monkeypatch.delenv("CONTEXTSMITH_WEB_URL", raising=False)
    monkeypatch.setenv("API_URL", "http://localhost:18234")
    monkeypatch.setenv("WEB_URL", "http://localhost:13234")

    module = load_qa_smoke()

    assert module.BASE == "http://localhost:18234"
    assert module.FRONTEND == "http://localhost:13234"


def test_qa_smoke_uses_configured_urls_for_requests():
    script = Path(__file__).resolve().parents[2] / "scripts" / "qa_smoke.py"
    text = script.read_text()

    assert 'requests.get("http://localhost:13000' not in text
    assert 'requests.request(method, f"http://localhost:18000' not in text
    assert 'requests.post("http://localhost:18000' not in text
