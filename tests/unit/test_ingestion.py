from __future__ import annotations

import os

import pytest

from contextsmith_worker.ingestion import (
    chunk_text,
    content_hash,
    is_text_file,
    iter_repo_files,
    should_index_path,
    validate_git_url,
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


def test_validate_git_url_accepts_https_and_local() -> None:
    assert validate_git_url("https://github.com/org/repo.git") == (
        False,
        "https://github.com/org/repo.git",
    )
    assert validate_git_url("file:///tmp/repo") == (True, "/tmp/repo")
    assert validate_git_url("/abs/path/repo") == (True, "/abs/path/repo")
    is_local, target = validate_git_url("./rel/repo")
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
