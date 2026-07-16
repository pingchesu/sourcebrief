# ruff: noqa: F405
from tests.unit.cli.support import *  # noqa: F401,F403


def test_add_repo_builds_git_resource_and_waits(monkeypatch, capsys):
    patch_client(monkeypatch)

    exit_code = cli_main(
        [
            "--api-url",
            "http://api.example",
            "--email",
            "dev@example.com",
            "resource",
            "add-repo",
            "--workspace-id",
            "ws-1",
            "--project-id",
            "proj-1",
            "--name",
            "SourceBrief repo",
            "--repo-url",
            "https://github.com/pingchesu/sourcebrief.git",
            "--branch",
            "main",
            "--max-files",
            "25",
            "--refresh",
            "--wait",
        ]
    )

    assert exit_code == 0
    client = FakeClient.instances[0]
    assert client.api_url == "http://api.example"
    assert client.email == "dev@example.com"
    method, path, body, expected = client.calls[0]
    assert method == "POST"
    assert path == "/workspaces/ws-1/projects/proj-1/resources"
    assert expected == {201}
    assert body == {
        "type": "git",
        "name": "SourceBrief repo",
        "uri": "https://github.com/pingchesu/sourcebrief.git",
        "update_frequency": "daily",
        "source_config": {
            "url": "https://github.com/pingchesu/sourcebrief.git",
            "branch": "main",
            "max_repo_files": 25,
        },
    }
    assert client.calls[1][0:2] == (
        "POST",
        "/workspaces/ws-1/projects/proj-1/resources/res-1/refresh",
    )
    assert client.calls[2][0:2] == ("GET", "/workspaces/ws-1/index-runs/run-1")
    output = capsys.readouterr().out
    assert "Resource" in output
    assert "Index run" in output
    assert "succeeded" in output


def test_add_repo_preserves_explicit_manual_frequency(monkeypatch, capsys):
    patch_client(monkeypatch)

    exit_code = cli_main(
        [
            "resource",
            "add-repo",
            "--workspace-id",
            "ws-1",
            "--project-id",
            "proj-1",
            "--name",
            "Manual repo",
            "--repo-url",
            "https://github.com/example/manual.git",
            "--update-frequency",
            "manual",
        ]
    )

    assert exit_code == 0
    body = FakeClient.instances[0].calls[0][2]
    assert isinstance(body, dict)
    assert body["update_frequency"] == "manual"


def test_add_doc_requires_content(monkeypatch, capsys):
    patch_client(monkeypatch)

    exit_code = cli_main(
        [
            "resource",
            "add-doc",
            "--workspace-id",
            "ws-1",
            "--project-id",
            "proj-1",
            "--name",
            "Runbook",
            "--uri",
            "doc://runbook",
        ]
    )

    assert exit_code == 1
    err = capsys.readouterr().err
    assert "add-doc requires --content or --content-file" in err


def test_resource_crud_commands_call_existing_api(monkeypatch, capsys):
    patch_client(monkeypatch)

    assert cli_main(["--json", "resource", "list", "--workspace-id", "ws-1", "--project-id", "proj-1"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed[0]["name"] == "SourceBrief repo"

    assert cli_main(["--json", "resource", "get", "--workspace-id", "ws-1", "--project-id", "proj-1", "--resource-id", "res-1"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "res-1"

    assert (
        cli_main(
            [
                "--json",
                "resource",
                "update",
                "--workspace-id",
                "ws-1",
                "--project-id",
                "proj-1",
                "--resource-id",
                "res-1",
                "--name",
                "Renamed repo",
                "--no-retrieval-enabled",
                "--stale-after-days",
                "45",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["retrieval_enabled"] is False

    assert (
        cli_main(
            [
                "--json",
                "resource",
                "update-git",
                "--workspace-id",
                "ws-1",
                "--project-id",
                "proj-1",
                "--resource-id",
                "res-1",
                "--branch",
                "main",
                "--max-files",
                "250",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["max_repo_files"] == 250

    assert cli_main(["--json", "resource", "archive", "--workspace-id", "ws-1", "--project-id", "proj-1", "--resource-id", "res-1"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "archived"

    assert cli_main(["--json", "resource", "delete", "--workspace-id", "ws-1", "--project-id", "proj-1", "--resource-id", "res-1"]) == 0
    assert json.loads(capsys.readouterr().out) == {"resource_id": "res-1", "status": "deleted"}

    calls = [call for instance in FakeClient.instances for call in instance.calls]
    assert ("GET", "/workspaces/ws-1/projects/proj-1/resources", None, None) in calls
    assert ("GET", "/workspaces/ws-1/projects/proj-1/resources/res-1", None, None) in calls
    assert (
        "PATCH",
        "/workspaces/ws-1/projects/proj-1/resources/res-1",
        {"name": "Renamed repo", "retrieval_enabled": False, "stale_after_days": 45},
        None,
    ) in calls
    assert (
        "PATCH",
        "/workspaces/ws-1/projects/proj-1/resources/res-1/git-env",
        {"branch": "main", "max_repo_files": 250},
        None,
    ) in calls
    assert ("POST", "/workspaces/ws-1/projects/proj-1/resources/res-1/archive", None, None) in calls
    assert ("DELETE", "/workspaces/ws-1/projects/proj-1/resources/res-1", None, {204}) in calls


def test_resource_update_requires_a_change(monkeypatch, capsys):
    patch_client(monkeypatch)

    assert cli_main(["resource", "update", "--workspace-id", "ws-1", "--project-id", "proj-1", "--resource-id", "res-1"]) == 1
    assert "requires at least one field" in capsys.readouterr().err

def test_agent_registry_and_resource_graph_commands(monkeypatch, capsys):
    patch_client(monkeypatch)

    assert cli_main(["--json", "agent", "list", "--workspace-id", "ws-1"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["project_id"] == "proj-1"

    assert (
        cli_main(["--json", "agent", "profile", "--workspace-id", "ws-1", "--project-id", "proj-1"])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["graph_node_count"] == 3

    assert (
        cli_main(
            [
                "--json",
                "resource",
                "graph",
                "--workspace-id",
                "ws-1",
                "--project-id",
                "proj-1",
                "--resource-id",
                "res-1",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["edge_count"] == 1

def test_safe_connector_cli_commands(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)

    assert (
        cli_main(
            [
                "--json",
                "resource",
                "add-url",
                "--workspace-id",
                "ws-1",
                "--project-id",
                "proj-1",
                "--name",
                "Docs",
                "--url",
                "https://example.com/docs",
                "--max-url-bytes",
                "1234",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["resource"]["type"] == "url"
    url_body = FakeClient.instances[-1].calls[0][2]
    assert url_body["source_config"] == {"url": "https://example.com/docs", "max_url_bytes": 1234}

    upload_path = tmp_path / "runbook.md"
    upload_path.write_text("uploaded marker", encoding="utf-8")
    assert (
        cli_main(
            [
                "--json",
                "resource",
                "add-upload",
                "--workspace-id",
                "ws-1",
                "--project-id",
                "proj-1",
                "--name",
                "Upload",
                "--path",
                str(upload_path),
                "--content-type",
                "text/markdown",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["resource"]["type"] == "upload"
    upload_body = FakeClient.instances[-1].calls[0][2]
    assert upload_body["uri"] == "upload://runbook.md"
    assert upload_body["source_config"]["content"] == "uploaded marker"
    assert upload_body["source_config"]["content_type"] == "text/markdown"
    assert upload_body["source_config"]["max_document_bytes"] == 5_000_000

    too_large = tmp_path / "too-large.md"
    too_large.write_text("0123456789", encoding="utf-8")
    assert (
        cli_main(
            [
                "resource",
                "add-upload",
                "--workspace-id",
                "ws-1",
                "--project-id",
                "proj-1",
                "--name",
                "Too Large",
                "--path",
                str(too_large),
                "--max-document-bytes",
                "5",
            ]
        )
        == 1
    )


def test_resource_lifecycle_cli_commands(monkeypatch, capsys):
    patch_client(monkeypatch)

    assert (
        cli_main(
            [
                "--json",
                "resource",
                "restore",
                "--workspace-id",
                "ws-1",
                "--project-id",
                "proj-1",
                "--resource-id",
                "res-1",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "active"

    assert (
        cli_main(
            [
                "--json",
                "resource",
                "purge",
                "--workspace-id",
                "ws-1",
                "--project-id",
                "proj-1",
                "--resource-id",
                "res-1",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["purged"] is True

    assert (
        cli_main(
            [
                "--json",
                "resource",
                "schedule-due",
                "--workspace-id",
                "ws-1",
                "--project-id",
                "proj-1",
                "--limit",
                "10",
                "--dry-run",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["resource_ids"] == ["res-1"]
    client = FakeClient.instances[-1]
    assert client.calls[-1][0:2] == (
        "POST",
        "/workspaces/ws-1/projects/proj-1/scheduled-refreshes?limit=10&dry_run=true",
    )
