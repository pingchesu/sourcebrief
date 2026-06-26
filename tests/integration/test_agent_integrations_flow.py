from __future__ import annotations

import json
import re
import time
import tomllib
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
    ws = client.post(
        "/workspaces", json={"name": prefix, "slug": f"{prefix}-{stamp}"}, headers=headers
    )
    assert ws.status_code == 201, ws.text
    workspace_id = ws.json()["id"]
    project = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"name": f"Project {stamp}", "description": "m6"},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    return headers, workspace_id, project.json()["id"]


def add_doc(
    client: TestClient,
    workspace_id: str,
    project_id: str,
    headers: dict[str, str],
    *,
    name: str = "Agent Runtime Doc",
    uri: str = "doc://agent-runtime",
    content: str = "# falconagent agent runtime\n\ndef runtime_symbol():\n    return 'falconagent'\n",
) -> str:
    res = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources",
        json={
            "type": "markdown",
            "name": name,
            "uri": uri,
            "source_config": {
                "content": content,
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


def create_runtime_token(
    client: TestClient,
    workspace_id: str,
    project_id: str,
    resource_id: str,
    headers: dict[str, str],
    *,
    scopes: list[str],
    name: str,
) -> dict[str, str]:
    response = client.post(
        f"/workspaces/{workspace_id}/api-tokens",
        json={"name": name, "scopes": scopes, "allowed_project_ids": [project_id], "allowed_resource_ids": [resource_id]},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['token']}"}


def test_agent_context_api_and_mcp_tool_call() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "m6-agent")
    resource_id = add_doc(client, workspace_id, project_id, headers)
    ingest(resource_id, workspace_id, project_id)

    response = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
        json={
            "query": "runtime_symbol",
            "runtime": "hermes",
            "resource_ids": [resource_id],
            "top_k": 5,
        },
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

    profile = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-profile", headers=headers
    )
    assert profile.status_code == 200, profile.text
    profile_body = profile.json()
    assert profile_body["project_id"] == project_id
    assert profile_body["resource_count"] == 1
    assert profile_body["graph_node_count"] >= 1
    assert profile_body["mcp_endpoint"].endswith(f"/{workspace_id}/{project_id}")

    updated = client.patch(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-profile",
        json={
            "system_prompt": "Prefer concise repo-owner-safe answers.",
            "default_runtime": "codex",
        },
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
    tool_names = [tool["name"] for tool in tools.json()["result"]["tools"]]
    assert tool_names[:4] == [
        "sourcebrief.ask",
        "sourcebrief.discover",
        "sourcebrief.lookup",
        "sourcebrief.get_agent_context",
    ]

    call = client.post(
        f"/mcp/{workspace_id}/{project_id}",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "sourcebrief.get_agent_context",
                "arguments": {
                    "query": "falconagent",
                    "runtime": "codex",
                    "resource_ids": [resource_id],
                },
            },
        },
        headers=headers,
    )
    assert call.status_code == 200, call.text
    result = call.json()["result"]
    assert result["structuredContent"]["runtime"] == "codex"
    assert "falconagent" in result["structuredContent"]["context"]


def test_context_only_token_omits_code_symbols_but_read_code_token_gets_them() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "m81-symbol-scope")
    resource_id = add_doc(client, workspace_id, project_id, headers)
    ingest(resource_id, workspace_id, project_id)

    context_only_headers = create_runtime_token(
        client,
        workspace_id,
        project_id,
        resource_id,
        headers,
        scopes=["project:query", "resource:read"],
        name="context only runtime",
    )
    context_only = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
        json={"query": "runtime_symbol", "resource_ids": [resource_id], "include_code_symbols": True},
        headers=context_only_headers,
    )
    assert context_only.status_code == 200, context_only.text
    context_only_body = context_only.json()
    assert context_only_body["symbols"] == []
    assert "code symbols omitted: missing required scope code:read" in context_only_body["coverage_warnings"]
    assert context_only_body["retrieval_metadata"]["code_symbols_omitted_reason"] == "missing_scope:code:read"
    context_only_tool_names = [call["name"] for call in context_only_body["suggested_tool_calls"]]
    assert "sourcebrief.read_section" in context_only_tool_names
    assert "sourcebrief.read_file" not in context_only_tool_names

    mcp_call = client.post(
        f"/mcp/{workspace_id}/{project_id}",
        json={
            "jsonrpc": "2.0",
            "id": 81,
            "method": "tools/call",
            "params": {
                "name": "sourcebrief.ask",
                "arguments": {"query": "runtime_symbol", "resource_ids": [resource_id], "include_code_symbols": True},
            },
        },
        headers=context_only_headers,
    )
    assert mcp_call.status_code == 200, mcp_call.text
    mcp_body = mcp_call.json()["result"]["structuredContent"]
    assert mcp_body["symbols"] == []
    assert mcp_body["retrieval_metadata"]["code_symbols_omitted_reason"] == "missing_scope:code:read"
    mcp_tool_names = [call["name"] for call in mcp_body["suggested_tool_calls"]]
    assert "sourcebrief.read_section" in mcp_tool_names
    assert "sourcebrief.read_file" not in mcp_tool_names

    code_search_denied = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/code-search",
        json={"query": "runtime_symbol", "resource_ids": [resource_id]},
        headers=context_only_headers,
    )
    assert code_search_denied.status_code == 403
    assert "missing scope: code:read" in code_search_denied.text

    read_code_headers = create_runtime_token(
        client,
        workspace_id,
        project_id,
        resource_id,
        headers,
        scopes=["project:query", "resource:read", "code:read"],
        name="read code runtime",
    )
    read_code = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
        json={"query": "runtime_symbol", "resource_ids": [resource_id], "include_code_symbols": True},
        headers=read_code_headers,
    )
    assert read_code.status_code == 200, read_code.text
    read_code_body = read_code.json()
    assert any(symbol["name"] == "runtime_symbol" for symbol in read_code_body["symbols"])
    assert read_code_body["retrieval_metadata"]["code_symbols_omitted_reason"] is None

    remote_symbol = client.post(
        f"/mcp/{workspace_id}/{project_id}",
        json={
            "jsonrpc": "2.0",
            "id": 82,
            "method": "tools/call",
            "params": {"name": "sourcebrief.find_symbol", "arguments": {"name": "runtime_symbol", "resource_ids": [resource_id]}},
        },
        headers=context_only_headers,
    )
    assert remote_symbol.status_code == 200, remote_symbol.text
    assert remote_symbol.json()["result"]["isError"] is True
    assert remote_symbol.json()["result"]["structuredContent"]["status_code"] == 403


def test_runtime_install_plan_is_redacted_live_and_permission_scoped() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "m30-runtime")
    resource_id = add_doc(
        client,
        workspace_id,
        project_id,
        headers,
        name="Runtime Primary",
        uri="doc://runtime-primary",
        content="# runtime primary\n\nThe runtime install plan should cite this project resource.",
    )
    other_resource_id = add_doc(
        client,
        workspace_id,
        project_id,
        headers,
        name="Runtime Other",
        uri="doc://runtime-other",
        content="# runtime other\n\nThis resource is outside the scoped token.",
    )

    plan = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/runtime-install-plan",
        json={
            "target": "hermes",
            "public_api_url": "https://alice:SECRET@sourcebrief.example.com/api?token=SECRET#frag",
            "server_name": "SourceBrief Runtime Demo",
            "resource_ids": [resource_id],
        },
        headers=headers,
    )
    assert plan.status_code == 200, plan.text
    body = plan.json()
    assert body["mode"] == "dry_run_plan"
    assert body["server_name"] == "sourcebrief-runtime-demo"
    assert body["endpoints"]["api_base_url"] == "https://sourcebrief.example.com/api"
    assert "SECRET" not in str(body)
    assert "alice" not in str(body)
    assert body["required_scopes"] == [
        "project:read",
        "project:query",
        "resource:read",
        "review:read",
        "code:read",
    ]
    assert body["suggested_token_request"]["allowed_resource_ids"] == [resource_id]
    assert "${" in body["mcp_config"]["content"]
    assert not re.search(r"cs_[A-Za-z0-9_-]{20,}", body["mcp_config"]["content"])
    assert body["resource_scope"]["resources"][0]["name"] == "Runtime Primary"
    assert "--query" in body["validator_commands"][0]
    assert "--token-env SOURCEBRIEF_TOKEN" in body["validator_commands"][0]
    assert "--token $SOURCEBRIEF_TOKEN" not in body["validator_commands"][0]
    assert "--allow-empty" not in body["validator_commands"][0]

    empty_plan = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/runtime-install-plan",
        json={"target": "hermes", "resource_ids": []},
        headers=headers,
    )
    assert empty_plan.status_code == 200, empty_plan.text
    empty_body = empty_plan.json()
    assert empty_body["resource_scope"] == {"mode": "selected_resources", "resources": []}
    assert empty_body["suggested_token_request"]["allowed_resource_ids"] == []
    assert "--allow-empty" in empty_body["validator_commands"][0]
    assert "--token-env SOURCEBRIEF_TOKEN" in empty_body["validator_commands"][0]

    invalid_port = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/runtime-install-plan",
        json={"target": "hermes", "public_api_url": "https://sourcebrief.example.com:99999"},
        headers=headers,
    )
    assert invalid_port.status_code == 422

    claude_plan = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/runtime-install-plan",
        json={
            "target": "claude",
            "server_name": "sourcebrief.prod",
            "public_api_url": "https://sourcebrief.example.com",
        },
        headers=headers,
    )
    assert claude_plan.status_code == 200, claude_plan.text
    claude_body = claude_plan.json()
    claude_config = json.loads(claude_body["mcp_config"]["content"])
    claude_server = claude_config["mcpServers"]["sourcebrief.prod"]
    assert claude_server["type"] == "http"
    assert claude_server["url"] == claude_body["endpoints"]["mcp_url"]
    assert claude_server["headers"] == {"Authorization": "Bearer ${SOURCEBRIEF_TOKEN}"}

    codex_plan = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/runtime-install-plan",
        json={
            "target": "codex",
            "server_name": "sourcebrief.prod",
            "public_api_url": "https://sourcebrief.example.com",
        },
        headers=headers,
    )
    assert codex_plan.status_code == 200, codex_plan.text
    codex_body = codex_plan.json()
    codex_content = codex_body["mcp_config"]["content"]
    assert '[mcp_servers."sourcebrief.prod"]' in codex_content
    codex_server = tomllib.loads(codex_content)["mcp_servers"]["sourcebrief.prod"]
    assert codex_server["url"] == codex_body["endpoints"]["mcp_url"]
    assert codex_server["bearer_token_env_var"] == "SOURCEBRIEF_TOKEN"
    assert "headers" not in codex_server

    tools = client.post(
        f"/mcp/{workspace_id}/{project_id}",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers=headers,
    )
    assert tools.status_code == 200, tools.text
    tool_names = {tool["name"] for tool in tools.json()["result"]["tools"]}
    plan_tool_names = {capability["name"] for capability in body["capabilities"]}
    assert plan_tool_names == tool_names
    patch_capability = next(
        capability
        for capability in body["capabilities"]
        if capability["name"] == "sourcebrief.generate_patch"
    )
    assert patch_capability["enabled"] is False
    assert patch_capability["policy"] == "opt_in_disabled_by_default"

    project_read_only = client.post(
        f"/workspaces/{workspace_id}/api-tokens",
        json={
            "name": "runtime project reader",
            "scopes": ["project:read"],
            "allowed_project_ids": [project_id],
        },
        headers=headers,
    )
    assert project_read_only.status_code == 201, project_read_only.text
    project_read_only_plan = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/runtime-install-plan",
        json={"target": "hermes"},
        headers={"Authorization": f"Bearer {project_read_only.json()['token']}"},
    )
    assert project_read_only_plan.status_code == 403
    assert "resource:read" in project_read_only_plan.text

    token_response = client.post(
        f"/workspaces/{workspace_id}/api-tokens",
        json={
            "name": "runtime scoped",
            "scopes": body["required_scopes"],
            "allowed_project_ids": [project_id],
            "allowed_resource_ids": [resource_id],
        },
        headers=headers,
    )
    assert token_response.status_code == 201, token_response.text
    runtime_token = token_response.json()["token"]
    bearer = {"Authorization": f"Bearer {runtime_token}"}

    scoped_plan = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/runtime-install-plan",
        json={"target": "codex", "public_api_url": "https://sourcebrief.example.com"},
        headers=bearer,
    )
    assert scoped_plan.status_code == 200, scoped_plan.text
    scoped_body = scoped_plan.json()
    assert scoped_body["resource_scope"]["mode"] == "token_allowed_resources"
    assert [resource["resource_id"] for resource in scoped_body["resource_scope"]["resources"]] == [
        resource_id
    ]
    assert runtime_token not in str(scoped_body)

    denied = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/runtime-install-plan",
        json={"target": "hermes", "resource_ids": [other_resource_id]},
        headers=bearer,
    )
    assert denied.status_code == 404


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
    session.add(
        WorkspaceMembership(
            workspace_id=UUID(workspace_id), user_id=intruder_user.id, role="viewer"
        )
    )
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
            "params": {
                "name": "sourcebrief.get_agent_context",
                "arguments": {"query": "x", "runtime": "root"},
            },
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
