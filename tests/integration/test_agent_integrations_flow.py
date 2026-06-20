from __future__ import annotations

import time
import uuid
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import text

from sourcebrief_api.auth import get_or_create_user
from sourcebrief_api.main import app
from sourcebrief_shared.config import get_settings
from sourcebrief_shared.db import get_engine, get_sessionmaker
from sourcebrief_shared.models import IndexRun, Project, WorkspaceMembership
from sourcebrief_worker.jobs import run_index

pytestmark = pytest.mark.integration


def require_real_services() -> None:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("select 1"))
        Redis.from_url(get_settings().redis_url).ping()
    except Exception as exc:
        pytest.skip(f"real Postgres/Redis services are not available: {exc}")


def make_project(client: TestClient, prefix: str) -> tuple[dict[str, str], str, str]:
    stamp = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
    headers = {"X-User-Email": f"{prefix}-{stamp}@example.com"}
    ws = client.post("/workspaces", json={"name": prefix, "slug": f"{prefix}-{stamp}"}, headers=headers)
    assert ws.status_code == 201, ws.text
    workspace_id = ws.json()["id"]
    project = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"name": f"Project {stamp}", "description": "m6"},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    return headers, workspace_id, project.json()["id"]


def add_doc(client: TestClient, workspace_id: str, project_id: str, headers: dict[str, str]) -> str:
    res = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources",
        json={
            "type": "markdown",
            "name": "Agent Runtime Doc",
            "uri": "doc://agent-runtime",
            "source_config": {
                "content": "# falconagent agent runtime\n\ndef runtime_symbol():\n    return 'falconagent'\n",
                "path": "runtime.py",
            },
        },
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def ingest(resource_id: str, workspace_id: str, project_id: str) -> None:
    session = get_sessionmaker()()
    run = IndexRun(
        workspace_id=UUID(workspace_id),
        project_id=UUID(project_id),
        resource_id=UUID(resource_id),
        trigger="manual",
        status="queued",
        meta={},
    )
    session.add(run)
    session.commit()
    run_id = str(run.id)
    session.close()
    run_index(run_id)


def test_agent_context_api_and_mcp_tool_call() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "m6-agent")
    resource_id = add_doc(client, workspace_id, project_id, headers)
    ingest(resource_id, workspace_id, project_id)

    response = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
        json={"query": "runtime_symbol", "runtime": "hermes", "resource_ids": [resource_id], "top_k": 5},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["runtime"] == "hermes"
    assert "Hermes specialist agent" in body["instruction"]
    assert "falconagent" in body["context"]
    assert body["citations"][0]["resource_id"] == resource_id
    assert "graph_score" in body["citations"][0]
    assert any(symbol["name"] == "runtime_symbol" for symbol in body["symbols"])

    profile = client.get(f"/workspaces/{workspace_id}/projects/{project_id}/agent-profile", headers=headers)
    assert profile.status_code == 200, profile.text
    profile_body = profile.json()
    assert profile_body["project_id"] == project_id
    assert profile_body["resource_count"] == 1
    assert profile_body["graph_node_count"] >= 1
    assert profile_body["mcp_endpoint"].endswith(f"/{workspace_id}/{project_id}")

    updated = client.patch(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-profile",
        json={"system_prompt": "Prefer concise repo-owner-safe answers.", "default_runtime": "codex"},
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    assert "repo-owner-safe" in updated.json()["system_prompt"]

    default_runtime = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
        json={"query": "runtime_symbol", "resource_ids": [resource_id], "top_k": 5},
        headers=headers,
    )
    assert default_runtime.status_code == 200, default_runtime.text
    assert default_runtime.json()["runtime"] == "codex"
    assert "repo-owner-safe" in default_runtime.json()["instruction"]

    null_patch = client.patch(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-profile",
        json={"name": None},
        headers=headers,
    )
    assert null_patch.status_code == 422

    graph = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/graph",
        headers=headers,
    )
    assert graph.status_code == 200, graph.text
    assert graph.json()["node_count"] >= 2
    assert graph.json()["edge_count"] >= 1

    tools = client.post(
        f"/mcp/{workspace_id}/{project_id}",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers=headers,
    )
    assert tools.status_code == 200, tools.text
    assert tools.json()["result"]["tools"][0]["name"] == "sourcebrief.get_agent_context"

    call = client.post(
        f"/mcp/{workspace_id}/{project_id}",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "sourcebrief.get_agent_context",
                "arguments": {"query": "falconagent", "runtime": "codex", "resource_ids": [resource_id]},
            },
        },
        headers=headers,
    )
    assert call.status_code == 200, call.text
    result = call.json()["result"]
    assert result["structuredContent"]["runtime"] == "codex"
    assert "falconagent" in result["structuredContent"]["context"]


def test_agent_registry_respects_private_project_membership() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "m7-private")

    session = get_sessionmaker()()
    project = session.get(Project, UUID(project_id))
    assert project is not None
    project.visibility = "private"
    session.commit()
    session.close()

    owner_agents = client.get(f"/workspaces/{workspace_id}/agents", headers=headers)
    assert owner_agents.status_code == 200, owner_agents.text
    assert any(agent["project_id"] == project_id for agent in owner_agents.json())

    intruder_email = "m7-private-intruder@example.com"
    session = get_sessionmaker()()
    intruder_user = get_or_create_user(session, intruder_email)
    session.add(WorkspaceMembership(workspace_id=UUID(workspace_id), user_id=intruder_user.id, role="viewer"))
    session.commit()
    session.close()

    intruder = {"X-User-Email": intruder_email}
    workspace_read = client.get(f"/workspaces/{workspace_id}", headers=intruder)
    assert workspace_read.status_code == 200
    intruder_agents = client.get(f"/workspaces/{workspace_id}/agents", headers=intruder)
    assert intruder_agents.status_code == 200, intruder_agents.text
    assert all(agent["project_id"] != project_id for agent in intruder_agents.json())
    intruder_projects = client.get(f"/workspaces/{workspace_id}/projects", headers=intruder)
    assert intruder_projects.status_code == 200, intruder_projects.text
    assert all(project["id"] != project_id for project in intruder_projects.json())


def test_workspace_member_listing_requires_admin_token_scope() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, _project_id = make_project(client, "m7-members")

    token = client.post(
        f"/workspaces/{workspace_id}/api-tokens",
        json={"name": "read-only", "scopes": ["project:read"]},
        headers=headers,
    )
    assert token.status_code == 201, token.text
    bearer_headers = {"Authorization": f"Bearer {token.json()['token']}"}
    members = client.get(f"/workspaces/{workspace_id}/members", headers=bearer_headers)
    assert members.status_code == 403, members.text


def test_agent_context_and_mcp_are_permission_scoped() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "m6-auth")
    resource_id = add_doc(client, workspace_id, project_id, headers)
    ingest(resource_id, workspace_id, project_id)
    intruder = {"X-User-Email": "m6-intruder@example.com"}
    response = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
        json={"query": "falconagent", "resource_ids": [resource_id]},
        headers=intruder,
    )
    assert response.status_code == 404
    mcp = client.post(
        f"/mcp/{workspace_id}/{project_id}",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers=intruder,
    )
    assert mcp.status_code == 404


def test_agent_context_adversarial_boundaries() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "m6-boundary")
    resource_id = add_doc(client, workspace_id, project_id, headers)
    ingest(resource_id, workspace_id, project_id)

    small = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
        json={"query": "runtime_symbol", "resource_ids": [resource_id], "max_chars": 1000},
        headers=headers,
    )
    assert small.status_code == 200, small.text
    assert small.json()["citations"], small.text
    assert small.json()["context"]
    assert len(small.json()["context"]) <= 1000
    assert "read-only context provider" in small.json()["instruction"]
    assert "production mutations" in small.json()["instruction"]

    archived = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/archive",
        headers=headers,
    )
    assert archived.status_code == 200, archived.text
    filtered = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
        json={"query": "runtime_symbol", "resource_ids": [resource_id]},
        headers=headers,
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["citations"] == []
    assert filtered.json()["context"] == ""


def test_mcp_json_rpc_error_semantics() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "m6-rpc")

    malformed = client.post(
        f"/mcp/{workspace_id}/{project_id}",
        data="{not-json",
        headers={**headers, "Content-Type": "application/json"},
    )
    assert malformed.status_code == 200
    assert malformed.json()["error"]["code"] == -32700

    batch = client.post(
        f"/mcp/{workspace_id}/{project_id}",
        json=[],
        headers=headers,
    )
    assert batch.status_code == 200
    assert batch.json()["error"]["code"] == -32600

    bad_envelope = client.post(
        f"/mcp/{workspace_id}/{project_id}",
        json={"jsonrpc": "1.0", "id": 10, "method": "tools/list"},
        headers=headers,
    )
    assert bad_envelope.status_code == 200
    assert bad_envelope.json()["error"]["code"] == -32600

    invalid_no_id = client.post(
        f"/mcp/{workspace_id}/{project_id}",
        json={"jsonrpc": "1.0", "method": "tools/list"},
        headers=headers,
    )
    assert invalid_no_id.status_code == 200
    assert invalid_no_id.json()["error"]["code"] == -32600
    explicit_null_id = client.post(
        f"/mcp/{workspace_id}/{project_id}",
        json={"jsonrpc": "2.0", "id": None, "method": "tools/list"},
        headers=headers,
    )
    assert explicit_null_id.status_code == 200
    assert explicit_null_id.json()["id"] is None
    assert "result" in explicit_null_id.json()

    notification = client.post(
        f"/mcp/{workspace_id}/{project_id}",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=headers,
    )
    assert notification.status_code == 204
    assert notification.content == b""

    missing_query = client.post(
        f"/mcp/{workspace_id}/{project_id}",
        json={
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {"name": "sourcebrief.get_agent_context", "arguments": {}},
        },
        headers=headers,
    )
    assert missing_query.status_code == 200
    assert missing_query.json()["error"]["code"] == -32602

    invalid_runtime = client.post(
        f"/mcp/{workspace_id}/{project_id}",
        json={
            "jsonrpc": "2.0",
            "id": 12,
            "method": "tools/call",
            "params": {"name": "sourcebrief.get_agent_context", "arguments": {"query": "x", "runtime": "root"}},
        },
        headers=headers,
    )
    assert invalid_runtime.status_code == 200
    assert invalid_runtime.json()["error"]["code"] == -32602

    invalid_uuid = client.post(
        f"/mcp/{workspace_id}/{project_id}",
        json={
            "jsonrpc": "2.0",
            "id": 13,
            "method": "tools/call",
            "params": {
                "name": "sourcebrief.get_agent_context",
                "arguments": {"query": "x", "resource_ids": ["not-a-uuid"]},
            },
        },
        headers=headers,
    )
    assert invalid_uuid.status_code == 200
    assert invalid_uuid.json()["error"]["code"] == -32602

    invalid_params = client.post(
        f"/mcp/{workspace_id}/{project_id}",
        json={"jsonrpc": "2.0", "id": 14, "method": "tools/call", "params": []},
        headers=headers,
    )
    assert invalid_params.status_code == 200
    assert invalid_params.json()["error"]["code"] == -32602
