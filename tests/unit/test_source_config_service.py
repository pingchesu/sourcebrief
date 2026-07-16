from __future__ import annotations

import pytest
from fastapi import HTTPException

from sourcebrief_api.services.source_config import validate_source_config
from sourcebrief_worker.ingestion import (
    HARD_MAX_CHUNKS,
    HARD_MAX_FILE_BYTES,
    HARD_MAX_REPO_BYTES,
    HARD_MAX_REPO_FILES,
    HARD_MAX_SYMBOLS,
)


@pytest.mark.parametrize(
    ("field", "maximum"),
    [
        ("clone_timeout", 600),
        ("max_file_bytes", HARD_MAX_FILE_BYTES),
        ("max_repo_files", HARD_MAX_REPO_FILES),
        ("max_repo_bytes", HARD_MAX_REPO_BYTES),
        ("max_chunks", HARD_MAX_CHUNKS),
        ("max_symbols", HARD_MAX_SYMBOLS),
    ],
)
def test_generic_git_source_config_rejects_import_bounds_above_hard_limit(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    maximum: int,
) -> None:
    monkeypatch.setenv("SOURCEBRIEF_ALLOW_LOCAL_GIT", "true")

    with pytest.raises(HTTPException) as exc_info:
        validate_source_config("git", "/tmp/example-repo", {field: maximum + 1})

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == f"{field} must be <= {maximum}"


@pytest.mark.parametrize("resource_type", ["git", "git_repo", "git-repo", "repo", "repository"])
def test_generic_git_source_config_accepts_exact_limits_for_all_git_aliases(
    monkeypatch: pytest.MonkeyPatch,
    resource_type: str,
) -> None:
    monkeypatch.setenv("SOURCEBRIEF_ALLOW_LOCAL_GIT", "true")
    limits = {
        "clone_timeout": 600,
        "max_file_bytes": HARD_MAX_FILE_BYTES,
        "max_repo_files": HARD_MAX_REPO_FILES,
        "max_repo_bytes": HARD_MAX_REPO_BYTES,
        "max_chunks": HARD_MAX_CHUNKS,
        "max_symbols": HARD_MAX_SYMBOLS,
    }

    validated = validate_source_config(resource_type, "/tmp/example-repo", limits)

    assert validated["url"] == "/tmp/example-repo"
    assert {key: validated[key] for key in limits} == limits


def test_generic_git_source_config_preserves_omitted_worker_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOURCEBRIEF_ALLOW_LOCAL_GIT", "true")

    validated = validate_source_config("git", "/tmp/example-repo", {"branch": "main"})

    assert validated == {"url": "/tmp/example-repo", "branch": "main"}
