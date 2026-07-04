from __future__ import annotations

import importlib
import json
import re
import stat
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import yaml  # type: ignore[import-untyped]

from sourcebrief_shared.review_bundle import load_review_bundle

__all__ = [
    "Any",
    "FakeClient",
    "Path",
    "UTC",
    "cli",
    "cli_main",
    "datetime",
    "importlib",
    "isolate_cli_config_env",
    "json",
    "load_review_bundle",
    "patch_client",
    "pytest",
    "REPO_ROOT",
    "re",
    "skill_install",
    "stat",
    "time",
    "yaml",
]

REPO_ROOT = Path(__file__).resolve().parents[3]

cli = importlib.import_module("sourcebrief_cli.main")
skill_install = importlib.import_module("sourcebrief_cli.skill_install")
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
        if method == "POST" and path == "/auth/login":
            assert body is not None
            return {"session_token": f"session-for-{body['email']}"}
        if method == "GET" and path == "/workspaces":
            return [
                {"id": "ws-1", "name": "Demo Workspace", "slug": "demo-workspace"},
                {"id": "ws-amb-1", "name": "Duplicate Workspace", "slug": "dupe-a"},
                {"id": "ws-amb-2", "name": "Duplicate Workspace", "slug": "dupe-b"},
            ]
        if method == "GET" and path == "/workspaces/ws-1/projects":
            return [
                {"id": "proj-1", "workspace_id": "ws-1", "name": "Demo Project", "visibility": "workspace"},
                {"id": "proj-amb-1", "workspace_id": "ws-1", "name": "Duplicate Project", "visibility": "workspace"},
                {"id": "proj-amb-2", "workspace_id": "ws-1", "name": "Duplicate Project", "visibility": "workspace"},
            ]
        if method == "POST" and path.endswith("/resources"):
            assert body is not None
            return {
                "id": "res-1",
                "name": body["name"],
                "type": body["type"],
                "uri": body["uri"],
                "status": "created",
            }
        if method == "GET" and path == "/workspaces/ws-1/projects/proj-1/resources":
            return [{"id": "res-1", "name": "SourceBrief repo", "type": "git", "uri": "https://example.test/repo.git", "status": "active"}]
        if method == "GET" and path == "/workspaces/ws-1/projects/proj-1/resources/res-1":
            return {"id": "res-1", "name": "SourceBrief repo", "type": "git", "uri": "https://example.test/repo.git", "status": "active"}
        if method == "PATCH" and path == "/workspaces/ws-1/projects/proj-1/resources/res-1":
            assert body is not None
            return {"id": "res-1", "name": body.get("name", "SourceBrief repo"), "type": "git", "uri": body.get("uri", "https://example.test/repo.git"), "status": "active", **body}
        if method == "PATCH" and path == "/workspaces/ws-1/projects/proj-1/resources/res-1/git-env":
            assert body is not None
            return {"resource_id": "res-1", "name": "SourceBrief repo", "uri": "https://example.test/repo.git", **body}
        if method == "POST" and path == "/workspaces/ws-1/projects/proj-1/resources/res-1/archive":
            return {"id": "res-1", "name": "SourceBrief repo", "status": "archived", "retrieval_enabled": False}
        if method == "DELETE" and path == "/workspaces/ws-1/projects/proj-1/resources/res-1":
            return None
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
            assert body is not None
            return {
                "query": body["query"],
                "count": 1,
                "hits": [{"path": "README.md", "snippet": "demo"}],
            }
        if method == "POST" and path == "/workspaces":
            assert body is not None
            return {"id": "ws-1", "name": body["name"], "slug": body["slug"], "status": "active"}
        if method == "POST" and path == "/workspaces/ws-1/projects":
            assert body is not None
            return {"id": "proj-1", "workspace_id": "ws-1", "name": body["name"], "status": "active"}
        if method == "POST" and path == "/workspaces/ws-1/projects/proj-1/agent-context":
            assert body is not None
            return {
                "query": body["query"],
                "profile": "hybrid",
                "runtime": body["runtime"],
                "instruction": "Use citations.",
                "context": "[1] resource=res-1 snapshot=snap-1 path=runbooks/payment-retry.md ordinal=1 score=0.9\nRetry payment jobs with exponential backoff. Escalate after three failures.",
                "answer": {
                    "mode": "extractive_synthesis",
                    "text": "Based on cited context: Retry payment jobs with exponential backoff. [1]",
                    "citations_used": [
                        {
                            "label": "[1]",
                            "resource_id": "res-1",
                            "snapshot_id": "snap-1",
                            "path": "runbooks/payment-retry.md",
                            "content_hash": "hash-1",
                            "score": 0.91,
                        }
                    ],
                    "caveats": [],
                    "confidence": "medium",
                },
                "citations": [
                    {
                        "resource_id": "res-1",
                        "snapshot_id": "snap-1",
                        "chunk_id": "chunk-1",
                        "path": "runbooks/payment-retry.md",
                        "title": "Payment retry runbook",
                        "ordinal": 1,
                        "content_hash": "hash-1",
                        "version": "v1",
                        "version_kind": "snapshot",
                        "commit": None,
                        "score": 0.91,
                        "graph_score": 0.0,
                        "score_components": {},
                    }
                ],
                "symbols": [],
                "suggested_tool_calls": [
                    {"name": "sourcebrief.read_section", "arguments": {"path": "runbooks/payment-retry.md"}}
                ],
                "token_budget_hint": 3000,
                "resource_coverage": [],
                "coverage_warnings": [],
                "retrieval_metadata": {},
            }
        if method == "GET" and path == "/workspaces/ws-1/agents":
            return [{"project_id": "proj-1", "name": "SourceBrief repo", "resource_count": 1}]
        if method == "GET" and path == "/workspaces/ws-1/projects/proj-1/agent-profile":
            return {"project_id": "proj-1", "name": "SourceBrief repo", "graph_node_count": 3}
        if method == "GET" and path == "/workspaces/ws-1/projects/proj-1/context-packs/default/current":
            return {"pack_key": "default", "version": 3, "status": "published"}
        if method == "POST" and path == "/workspaces/ws-1/projects/proj-1/context-packs/default/versions/3/skill-exports":
            assert body is not None
            return {
                "id": "skill-export-1",
                "context_pack_version_id": "pack-version-1",
                "pack_key": "default",
                "pack_version": 3,
                "export_type": "hermes_skill",
                "export_version": 1,
                "status": "draft",
                "title": body["title"],
                "summary": body.get("summary"),
                "package_hash": "sha256:" + "a" * 64,
                "manifest_json": {"package_hash": "sha256:" + "a" * 64},
                "files": [
                    {"path": "SKILL.md", "kind": "skill", "sha256": "sha256:" + "b" * 64, "bytes": 20, "content": "---\nname: demo\n---\n"},
                    {"path": "manifest.json", "kind": "json", "sha256": "sha256:" + "c" * 64, "bytes": 100, "content": json.dumps({"package_kind": "sourcebrief_skill_pack", "export_status": "draft", "package_hash": "sha256:" + "a" * 64, "pack_key": "default", "pack_version": 3}) + "\n"},
                ],
                "validation_json": {"ok": True},
                "leak_scan_json": {"ok": True},
                "created_at": "2026-01-01T00:00:00Z",
            }
        if method == "POST" and path == "/workspaces/ws-1/projects/proj-1/skill-exports/skill-export-1/approve":
            assert body is not None
            return {
                "id": "skill-export-1",
                "context_pack_version_id": "pack-version-1",
                "pack_key": "default",
                "pack_version": 3,
                "export_type": "hermes_skill",
                "export_version": 1,
                "status": "approved",
                "title": "Demo skill",
                "summary": None,
                "package_hash": "sha256:" + "a" * 64,
                "manifest_json": {"package_hash": "sha256:" + "a" * 64, "export_status": "approved"},
                "files": [
                    {"path": "SKILL.md", "kind": "skill", "sha256": "sha256:" + "b" * 64, "bytes": 20, "content": "---\nname: demo\n---\n"},
                    {"path": "manifest.json", "kind": "json", "sha256": "sha256:" + "d" * 64, "bytes": 100, "content": json.dumps({"package_kind": "sourcebrief_skill_pack", "export_status": "approved", "package_hash": "sha256:" + "a" * 64, "pack_key": "default", "pack_version": 3}) + "\n"},
                ],
                "validation_json": {"ok": True},
                "leak_scan_json": {"ok": True},
                "created_at": "2026-01-01T00:00:00Z",
                "approved_at": "2026-01-01T00:01:00Z",
                "review_comment": body["comment"],
            }
        if method == "POST" and path == "/workspaces/ws-1/projects/proj-1/runtime-install-plan":
            assert body is not None
            plan = {
                "target": body["target"],
                "workspace_id": "ws-1",
                "project_id": "proj-1",
                "project_name": "Demo Project",
                "generated_at": datetime.now(UTC).isoformat(),
                "mode": "dry_run_plan",
                "server_name": body["server_name"] or "sourcebrief-demo",
                "endpoints": {
                    "api_base_url": body["public_api_url"] or "http://localhost:18000",
                    "mcp_url": f"{body['public_api_url'] or 'http://localhost:18000'}/mcp/ws-1/proj-1",
                    "agent_context_url": f"{body['public_api_url'] or 'http://localhost:18000'}/workspaces/ws-1/projects/proj-1/agent-context",
                    "agent_pack_url": f"{body['public_api_url'] or 'http://localhost:18000'}/workspaces/ws-1/projects/proj-1/agent-pack.zip",
                },
                "required_scopes": ["project:read", "project:query", "resource:read", "review:read", "code:read"],
                "suggested_token_request": {},
                "mcp_config": {
                    "format": "yaml",
                    "content": (
                        "mcp_servers:\n"
                        f"  {body['server_name'] or 'sourcebrief-demo'}:\n"
                        f"    url: {json.dumps((body['public_api_url'] or 'http://localhost:18000') + '/mcp/ws-1/proj-1')}\n"
                        "    headers:\n"
                        "      Authorization: \"Bearer ${SOURCEBRIEF_" "TOKEN}\"\n"
                    ),
                },
                "validator_commands": ["python scripts/hermes_integration.py --token-env SOURCEBRIEF_TOKEN"],
                "capabilities": [],
                "resource_scope": {"mode": "selected_resources", "resources": body["resource_ids"] or []},
                "warnings": [],
                "rollback_steps": [],
            }
            return plan
        if method == "GET" and path.endswith("/graph?limit=50"):
            return {"node_count": 2, "edge_count": 1, "nodes": [], "edges": []}
        if method == "POST" and path == "/workspaces/ws-1/api-tokens":
            assert body is not None
            return {
                "token": "cs_secret",
                "api_token": {"id": "tok-1", "name": body["name"], "scopes": body["scopes"]},
            }
        if method == "GET" and path == "/workspaces/ws-1/api-tokens":
            return [{"id": "tok-1", "name": "Hermes", "scopes": ["project:query"]}]
        if method == "DELETE" and path == "/workspaces/ws-1/api-tokens/tok-1":
            return {"id": "tok-1", "revoked_at": "2026-01-01T00:00:00Z"}
        if method == "POST" and path == "/mcp/ws-1/proj-1":
            payload = {
                "query": (body or {}).get("params", {}).get("arguments", {}).get("query", "demo"),
                "citations": [{"resource_id": "res-1", "path": "runbooks/payment-retry.md", "content_hash": "hash-1"}],
                "answer": {"text": "Use the cited runbook. [1]", "citations_used": [{"label": "[1]", "path": "runbooks/payment-retry.md"}]},
            }
            return {
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(payload)}],
                    "structuredContent": payload,
                },
            }
        if method == "POST" and path.endswith("/restore"):
            return {"id": "res-1", "status": "active", "retrieval_enabled": True}
        if method == "POST" and path.endswith("/purge"):
            return {"resource_id": "res-1", "purged": True, "counts": {"resources": 1}}
        if method == "POST" and path.endswith("/scheduled-refreshes?limit=10&dry_run=true"):
            return {
                "scanned": 1,
                "enqueued": 1,
                "resource_ids": ["res-1"],
                "skipped_active": [],
                "dry_run": True,
            }
        return {"status": "ok"}


def patch_client(monkeypatch):
    FakeClient.instances.clear()
    monkeypatch.setattr(cli, "SourceBriefClient", FakeClient)


@pytest.fixture(autouse=True)
def isolate_cli_config_env(monkeypatch, tmp_path):
    monkeypatch.delenv("SOURCEBRIEF_CONFIG_PATH", raising=False)
    monkeypatch.setenv("SOURCEBRIEF_DOTENV_PATH", str(tmp_path / "missing.env"))
    monkeypatch.delenv("SOURCEBRIEF_API_URL", raising=False)
    monkeypatch.delenv("CONTEXTSMITH_API_URL", raising=False)
    monkeypatch.delenv("SOURCEBRIEF_TOKEN", raising=False)
    monkeypatch.delenv("CONTEXTSMITH_TOKEN", raising=False)
    monkeypatch.delenv("SOURCEBRIEF_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("SOURCEBRIEF_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("SOURCEBRIEF_EMAIL", raising=False)
    monkeypatch.delenv("SOURCEBRIEF_PASSWORD", raising=False)
    monkeypatch.delenv("CONTEXTSMITH_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("CONTEXTSMITH_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("CONTEXTSMITH_EMAIL", raising=False)
    monkeypatch.delenv("CONTEXTSMITH_PASSWORD", raising=False)
