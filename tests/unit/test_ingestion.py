from __future__ import annotations

import os
from email.message import Message
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from sourcebrief_worker.ingestion import (
    _coerce_documents,
    chunk_text,
    content_hash,
    fetch_url_document,
    html_to_text,
    is_text_file,
    iter_repo_files,
    redact_secrets,
    sanitize_remote_url,
    should_index_path,
    validate_git_url,
    validate_http_url,
)


def test_content_hash_is_stable_and_sensitive() -> None:
    assert content_hash("hello") == content_hash("hello")
    assert content_hash("hello") != content_hash("hello!")
    assert len(content_hash("hello")) == 64


def test_chunk_text_empty_and_whitespace() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\t  ") == []


def test_chunk_text_short_returns_single_chunk() -> None:
    chunks = chunk_text("a short paragraph", max_chars=2000)
    assert chunks == ["a short paragraph"]


def test_chunk_text_splits_large_input_within_bounds() -> None:
    body = "\n\n".join(f"paragraph number {i} with some words" for i in range(50))
    chunks = chunk_text(body, max_chars=80, overlap=10)
    assert len(chunks) > 1
    assert all(len(chunk) <= 80 for chunk in chunks)
    # the final marker survives somewhere in the chunk set (coverage of the tail)
    assert any("number 49" in chunk for chunk in chunks)


def test_chunk_text_respects_overlap_progress() -> None:
    body = "x" * 500
    chunks = chunk_text(body, max_chars=100, overlap=20)
    # no infinite loop, and every chunk is bounded
    assert len(chunks) >= 5
    assert all(len(chunk) <= 100 for chunk in chunks)


def test_is_text_file() -> None:
    assert is_text_file(b"") is True
    assert is_text_file(b"plain text content") is True
    assert is_text_file("unicode snowman ☃".encode()) is True
    assert is_text_file(b"binary\x00data") is False
    assert is_text_file(b"\xff\xfe\xfa\xfb") is False


def test_should_index_path_allows_source_files() -> None:
    assert should_index_path("README.md") is True
    assert should_index_path("src/app.py") is True
    assert should_index_path("docs/guide.txt") is True


def test_should_index_path_skips_generated_and_binary() -> None:
    assert should_index_path("node_modules/lib/index.js") is False
    assert should_index_path(".git/config") is False
    assert should_index_path("pkg/__pycache__/m.pyc") is False
    assert should_index_path("dist/bundle.js") is False
    assert should_index_path(".venv/lib/site.py") is False
    assert should_index_path("assets/logo.png") is False
    assert should_index_path("native/lib.so") is False
    assert should_index_path("package-lock.json") is False


def test_validate_git_url_accepts_https_and_local_only_when_enabled() -> None:
    assert validate_git_url("https://github.com/org/repo.git") == (
        False,
        "https://github.com/org/repo.git",
    )
    with pytest.raises(ValueError):
        validate_git_url("file:///tmp/repo")
    assert validate_git_url("file:///tmp/repo", allow_local=True) == (True, "/tmp/repo")
    assert validate_git_url("/abs/path/repo", allow_local=True) == (True, "/abs/path/repo")
    is_local, target = validate_git_url("./rel/repo", allow_local=True)
    assert is_local is True
    assert target.endswith("rel/repo")


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "ssh://git@github.com/org/repo.git",
        "git://github.com/org/repo.git",
        "git@github.com:org/repo.git",
        "ext::sh -c whoami",
        "http://example.com/repo.git",
        "https://github.com/org/repo .git",
        "-oProxyCommand=evil",
    ],
)
def test_validate_git_url_rejects_unsafe(bad: str) -> None:
    with pytest.raises(ValueError):
        validate_git_url(bad)


def test_validate_git_url_rejects_internal_https_hosts() -> None:
    with pytest.raises(ValueError):
        validate_git_url("https://localhost/repo.git")
    with pytest.raises(ValueError):
        validate_git_url("https://127.0.0.1/repo.git")


def test_sanitize_remote_url_strips_credentials_and_query() -> None:
    assert (
        sanitize_remote_url("https://token:secret@example.com/org/repo.git?access_token=x#frag")
        == "https://example.com/org/repo.git"
    )
    assert sanitize_remote_url("/qa-fixtures/repo.bundle") == "local"


def test_coerce_documents_rejects_oversized_inline_content() -> None:
    with pytest.raises(RuntimeError, match="max_document_bytes"):
        _coerce_documents({"content": "x" * 11}, max_document_bytes=10)

def test_iter_repo_files_filters_and_is_deterministic(tmp_path) -> None:
    (tmp_path / "README.md").write_text("hello quokka", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "lib.js").write_text("junk", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]", encoding="utf-8")
    (tmp_path / "big.txt").write_text("a" * 100, encoding="utf-8")
    (tmp_path / "logo.bin").write_bytes(b"\x00\x01\x02\x03binary")
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")

    results = list(iter_repo_files(tmp_path, max_file_bytes=50))
    paths = [rel for rel, _ in results]
    assert paths == ["README.md", "src/app.py"]
    contents = dict(results)
    assert contents["README.md"] == "hello quokka"


def test_iter_repo_files_skips_escaping_symlinks(tmp_path) -> None:
    (tmp_path / "keep.md").write_text("real file", encoding="utf-8")
    target = tmp_path.parent / "outside_secret.txt"
    target.write_text("secret", encoding="utf-8")
    link = tmp_path / "leak.txt"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    paths = [rel for rel, _ in iter_repo_files(tmp_path)]
    assert paths == ["keep.md"]


def test_validate_http_url_rejects_unsafe_targets() -> None:
    assert validate_http_url("https://example.com/docs?q=1#frag") == "https://example.com/docs?q=1"
    for bad in [
        "file:///etc/passwd",
        "http://localhost/admin",
        "http://127.0.0.1/admin",
        "https://user:pass@example.com/secret",
        "https://example.com/a b",
    ]:
        with pytest.raises(ValueError):
            validate_http_url(bad)


def test_html_to_text_and_redaction() -> None:
    text = html_to_text("<html><body><h1>Title</h1><script>secret</script><p>Hello</p></body></html>")
    assert "Title" in text
    assert "Hello" in text
    assert "secret" not in text

    redacted, counts = redact_secrets("token=ghp_abcdefghijklmnopqrstuvwxyz123456 and password=supersecretvalue")
    assert "ghp_" not in redacted
    assert "supersecretvalue" not in redacted
    assert counts["github_token"] == 1
    assert counts["generic_api_key"] == 1


def test_fetch_url_document_bounds_and_html(monkeypatch) -> None:
    class FakeResponse:
        headers = {"Content-Type": "text/html; charset=utf-8", "Content-Length": "80"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def geturl(self):
            return "https://example.com/page"

        def read(self, size: int):
            assert size == 101
            return b"<html><body><h1>Connector</h1><p>public content</p></body></html>"

    monkeypatch.setattr("sourcebrief_worker.ingestion._open_url", lambda request, timeout: FakeResponse())
    resource = SimpleNamespace(
        type="url",
        name="Example",
        uri="https://example.com/page",
        source_config={"max_url_bytes": 100},
    )
    docs, version, version_kind, meta = fetch_url_document(resource)
    assert version_kind == "content_hash"
    assert len(version) == 64
    assert docs[0]["title"] == "page"
    assert "Connector" in docs[0]["content"]
    assert "<html" not in docs[0]["content"]
    assert meta["source"] == "url"


def test_fetch_url_document_blocks_redirect_to_private_host_before_second_request(monkeypatch) -> None:
    calls: list[str] = []

    def fake_open(request, timeout):
        calls.append(request.full_url)
        headers = Message()
        headers["Location"] = "http://127.0.0.1/admin"
        raise HTTPError(
            request.full_url,
            302,
            "Found",
            headers,
            None,
        )

    monkeypatch.setattr("sourcebrief_worker.ingestion._open_url", fake_open)
    resource = SimpleNamespace(
        type="url",
        name="Redirect",
        uri="https://example.com/redirect",
        source_config={},
    )
    with pytest.raises(ValueError, match="public"):
        fetch_url_document(resource)
    assert calls == ["https://example.com/redirect"]


def test_fetch_url_document_strips_query_from_persisted_paths(monkeypatch) -> None:
    class FakeResponse:
        headers = {"Content-Type": "text/plain", "Content-Length": "12"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def geturl(self):
            return "https://example.com/doc?access_token=SECRET"

        def read(self, size: int):
            return b"hello world"

    monkeypatch.setattr("sourcebrief_worker.ingestion._open_url", lambda request, timeout: FakeResponse())
    resource = SimpleNamespace(
        type="url",
        name="Signed",
        uri="https://example.com/doc?access_token=SECRET",
        source_config={"max_url_bytes": 100},
    )
    docs, _, _, meta = fetch_url_document(resource)
    assert docs[0]["path"] == "https://example.com/doc"
    assert meta["url"] == "https://example.com/doc"
    assert "SECRET" not in str(docs) + str(meta)


def test_fetch_url_document_rejects_invalid_bounds() -> None:
    resource = SimpleNamespace(
        type="url",
        name="Bad",
        uri="https://example.com/doc",
        source_config={"max_url_bytes": -1},
    )
    with pytest.raises(ValueError, match="max_url_bytes"):
        fetch_url_document(resource)
