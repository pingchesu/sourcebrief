from sourcebrief_api.routers.resource_core import _effective_update_frequency


def test_git_resources_default_to_daily() -> None:
    for resource_type in ("git", "git_repo", "git-repo", "repo", "repository"):
        assert _effective_update_frequency(resource_type, None) == "daily"


def test_non_git_resources_default_to_manual() -> None:
    assert _effective_update_frequency("markdown", None) == "manual"


def test_explicit_frequency_is_preserved() -> None:
    assert _effective_update_frequency("git", "manual") == "manual"
    assert _effective_update_frequency("markdown", "weekly") == "weekly"