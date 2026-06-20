from __future__ import annotations

import importlib
import json
from typing import Any

cli = importlib.import_module("sourcebrief_cli.main")
cli_main = cli.main


class FakeClient:
    instances: list[FakeClient] = []

    def __init__(self, api_url: str, email: str, token: str | None = None) -> None:
        self.api_url = api_url
        self.email = email
        self.token = token
        self.calls: list[tuple[str, str, dict[str, Any] | None, set[int] | None]] = []
        FakeClient.instances.append(self)

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        expected: set[int] | None = None,
    ) -> Any:
        self.calls.append((method, path, body, expected))
        if method == "POST" and path.endswith("/resources"):
            return {"id": "res-1", "name": body["name"], "type": body["type"], "uri": body["uri"], "status": "created"}
        if method == "POST" and path.endswith("/refresh"):
            return {"id": "run-1", "status": "queued"}
        if method == "GET" and path == "/workspaces/ws-1/index-runs/run-1":
            return {
                "id": "run-1",
                "status": "succeeded",
                "documents_seen": 2,
                "chunks_created": 4,
                "symbols_created": 1,
                "embeddings_created": 4,
            }
        if method == "POST" and path.endswith("/search"):
            return {"query": body["query"], "count": 1, "hits": [{"path": "README.md", "snippet": "demo"}]}
        if method == "GET" and path == "/workspaces/ws-1/agents":
            return [{"project_id": "proj-1", "name": "SourceBrief repo", "resource_count": 1}]
        if method == "GET" and path == "/workspaces/ws-1/projects/proj-1/agent-profile":
            return {"project_id": "proj-1", "name": "SourceBrief repo", "graph_node_count": 3}
        if method == "GET" and path.endswith("/graph?limit=50"):
            return {"node_count": 2, "edge_count": 1, "nodes": [], "edges": []}
        if method == "POST" and path == "/workspaces/ws-1/api-tokens":
            assert body is not None
            return {"token": "cs_secret", "api_token": {"id": "tok-1", "name": body["name"], "scopes": body["scopes"]}}
        if method == "GET" and path == "/workspaces/ws-1/api-tokens":
            return [{"id": "tok-1", "name": "Hermes", "scopes": ["project:query"]}]
        if method == "DELETE" and path == "/workspaces/ws-1/api-tokens/tok-1":
            return {"id": "tok-1", "revoked_at": "2026-01-01T00:00:00Z"}
        if method == "POST" and path.endswith("/restore"):
            return {"id": "res-1", "status": "active", "retrieval_enabled": True}
        if method == "POST" and path.endswith("/purge"):
            return {"resource_id": "res-1", "purged": True, "counts": {"resources": 1}}
        if method == "POST" and path.endswith("/scheduled-refreshes?limit=10&dry_run=true"):
            return {"scanned": 1, "enqueued": 1, "resource_ids": ["res-1"], "skipped_active": [], "dry_run": True}
        return {"status": "ok"}


def patch_client(monkeypatch):
    FakeClient.instances.clear()
    monkeypatch.setattr(cli, "SourceBriefClient", FakeClient)


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
        "update_frequency": "manual",
        "source_config": {
            "url": "https://github.com/pingchesu/sourcebrief.git",
            "branch": "main",
            "max_repo_files": 25,
        },
    }
    assert client.calls[1][0:2] == ("POST", "/workspaces/ws-1/projects/proj-1/resources/res-1/refresh")
    assert client.calls[2][0:2] == ("GET", "/workspaces/ws-1/index-runs/run-1")
    output = capsys.readouterr().out
    assert "Resource" in output
    assert "Index run" in output
    assert "succeeded" in output


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


def test_search_json_output(monkeypatch, capsys):
    patch_client(monkeypatch)

    exit_code = cli_main(
        [
            "--json",
            "search",
            "--workspace-id",
            "ws-1",
            "--project-id",
            "proj-1",
            "--query",
            "demo",
            "--resource-id",
            "res-1",
        ]
    )

    assert exit_code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["query"] == "demo"
    client = FakeClient.instances[0]
    assert client.calls[0][2] == {"query": "demo", "top_k": 10, "resource_ids": ["res-1"]}


def test_agent_registry_and_resource_graph_commands(monkeypatch, capsys):
    patch_client(monkeypatch)

    assert cli_main(["--json", "agent", "list", "--workspace-id", "ws-1"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["project_id"] == "proj-1"

    assert cli_main(["--json", "agent", "profile", "--workspace-id", "ws-1", "--project-id", "proj-1"]) == 0
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


def test_token_commands_and_bearer_client(monkeypatch, capsys):
    patch_client(monkeypatch)

    exit_code = cli_main(
        [
            "--token",
            "cs_existing",
            "--json",
            "token",
            "create",
            "--workspace-id",
            "ws-1",
            "--name",
            "Hermes",
            "--scope",
            "project:query,resource:read",
            "--project-id",
            "proj-1",
            "--resource-id",
            "res-1",
        ]
    )
    assert exit_code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["token"] == "cs_secret"
    client = FakeClient.instances[0]
    assert client.token == "cs_existing"
    assert client.calls[0] == (
        "POST",
        "/workspaces/ws-1/api-tokens",
        {
            "name": "Hermes",
            "scopes": ["project:query", "resource:read"],
            "allowed_project_ids": ["proj-1"],
            "allowed_resource_ids": ["res-1"],
            "expires_at": None,
        },
        {201},
    )

    assert cli_main(["--json", "token", "list", "--workspace-id", "ws-1"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == "tok-1"

    assert cli_main(["--json", "token", "revoke", "--workspace-id", "ws-1", "--token-id", "tok-1"]) == 0
    assert json.loads(capsys.readouterr().out)["id"] == "tok-1"


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
