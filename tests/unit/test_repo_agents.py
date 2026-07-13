from __future__ import annotations

import pytest
from pydantic import ValidationError

from sourcebrief_api.repo_agents import _redact_bundle_text
from sourcebrief_api.schemas import GitResourceEnvUpdate


def test_repo_agent_bundle_text_redacts_credentials_paths_and_long_verbatim_content() -> None:
    source = (
        "Read /home/alice/private/repo and https://alice:secret@example.com/org/repo.git?access_token=SECRET#frag "
        "then use token: ghp_verysecrettokenvalue and "
        + "x" * 600
    )

    redacted = _redact_bundle_text(source, max_len=180)

    assert "/home/alice" not in redacted
    assert "alice:secret" not in redacted
    assert "access_token" not in redacted
    assert "SECRET" not in redacted
    assert "ghp_verysecrettokenvalue" not in redacted
    assert "https://example.com/org/repo.git" in redacted
    assert len(redacted) <= 180


def test_git_resource_env_update_rejects_unbounded_import_budgets() -> None:
    with pytest.raises(ValidationError):
        GitResourceEnvUpdate(max_repo_files=5_001)
    with pytest.raises(ValidationError):
        GitResourceEnvUpdate(max_repo_bytes=200_000_001)
    with pytest.raises(ValidationError):
        GitResourceEnvUpdate(max_chunks=20_001)
    with pytest.raises(ValidationError):
        GitResourceEnvUpdate(max_symbols=20_001)

    accepted = GitResourceEnvUpdate(
        max_file_bytes=10_000_000,
        max_repo_files=5_000,
        max_repo_bytes=200_000_000,
        max_chunks=20_000,
        max_symbols=20_000,
    )
    assert accepted.max_repo_files == 5_000
