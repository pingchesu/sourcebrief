from __future__ import annotations

import importlib
import json
from typing import Any

cli = importlib.import_module("contextsmith_cli.main")
cli_main = cli.main


class FakeClient:
    instances: list[FakeClient] = []

    def __init__(self, api_url: str, email: str) -> None:
        self.api_url = api_url
        self.email = email
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
        return {"status": "ok"}


def patch_client(monkeypatch):
    FakeClient.instances.clear()
    monkeypatch.setattr(cli, "ContextSmithClient", FakeClient)


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
            "ContextSmith repo",
            "--repo-url",
            "https://github.com/pingchesu/contextsmith.git",
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
        "name": "ContextSmith repo",
        "uri": "https://github.com/pingchesu/contextsmith.git",
        "update_frequency": "manual",
        "source_config": {
            "url": "https://github.com/pingchesu/contextsmith.git",
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
