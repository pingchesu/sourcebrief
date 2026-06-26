from pathlib import Path

from scripts import check_quickstart_prereqs as prereqs


def test_remote_browser_check_fails_for_localhost_api_and_missing_cors(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SOURCEBRIEF_API_PORT=18123\n"
        "SOURCEBRIEF_WEB_PORT=13123\n"
        "NEXT_PUBLIC_API_BASE_URL=http://localhost:18123\n"
        "SOURCEBRIEF_CORS_ORIGINS=http://localhost:13123,http://127.0.0.1:13123\n",
        encoding="utf-8",
    )

    results = prereqs.remote_browser_check(prereqs.parse_env_file(env_file), "http://10.10.70.17:13123")

    assert [result.ok for result in results] == [False, False]
    assert "NEXT_PUBLIC_API_BASE_URL=http://10.10.70.17:18123" in (results[0].remediation or "")
    assert "10.10.70.17:13123" in (results[1].remediation or "")


def test_remote_browser_check_passes_for_browser_visible_api_and_cors(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SOURCEBRIEF_API_PORT=18123\n"
        "SOURCEBRIEF_WEB_PORT=13123\n"
        "NEXT_PUBLIC_API_BASE_URL=http://10.10.70.17:18123\n"
        "SOURCEBRIEF_CORS_ORIGINS=http://10.10.70.17:13123,http://localhost:13123,http://127.0.0.1:13123\n",
        encoding="utf-8",
    )

    results = prereqs.remote_browser_check(prereqs.parse_env_file(env_file), "http://10.10.70.17:13123")

    assert results
    assert all(result.ok for result in results)


def test_remote_browser_check_uses_env_file_before_shell_environment(tmp_path: Path, monkeypatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SOURCEBRIEF_API_PORT=18123\n"
        "SOURCEBRIEF_WEB_PORT=13123\n"
        "NEXT_PUBLIC_API_BASE_URL=http://localhost:18123\n"
        "SOURCEBRIEF_CORS_ORIGINS=http://localhost:13123,http://127.0.0.1:13123\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEXT_PUBLIC_API_BASE_URL", "http://10.10.70.17:18123")
    monkeypatch.setenv("SOURCEBRIEF_CORS_ORIGINS", "http://10.10.70.17:13123")

    results = prereqs.remote_browser_check(prereqs.parse_env_file(env_file), "http://10.10.70.17:13123")

    assert [result.ok for result in results] == [False, False]
    assert "local-only NEXT_PUBLIC_API_BASE_URL=http://localhost:18123" in results[0].message


def test_uv_check_is_actionable_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(prereqs.shutil, "which", lambda command: None if command == "uv" else f"/usr/bin/{command}")

    result = prereqs.uv_check()

    assert not result.ok
    assert "curl -LsSf https://astral.sh/uv/install.sh | sh" in (result.remediation or "")
    assert "uv python install 3.11" in (result.remediation or "")
