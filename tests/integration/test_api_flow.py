from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from rq import Queue, SimpleWorker
from sqlalchemy import text

from contextsmith_api.main import app
from contextsmith_shared.config import get_settings
from contextsmith_shared.db import get_engine

pytestmark = pytest.mark.integration


def require_real_services() -> None:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("select 1"))
        Redis.from_url(get_settings().redis_url).ping()
    except Exception as exc:  # pragma: no cover - diagnostic path
        pytest.skip(f"real Postgres/Redis services are not available: {exc}")


def drain_default_queue() -> None:
    redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6380/0"))
    queue = Queue("default", connection=redis)
    SimpleWorker([queue], connection=redis).work(burst=True)


def wait_for_run(client: TestClient, workspace_id: str, run_id: str, headers: dict[str, str]) -> dict:
    deadline = time.time() + 15
    last = None
    while time.time() < deadline:
        response = client.get(f"/workspaces/{workspace_id}/index-runs/{run_id}", headers=headers)
        assert response.status_code == 200, response.text
        last = response.json()
        if last["status"] in {"succeeded", "failed"}:
            return last
        drain_default_queue()
        time.sleep(0.2)
    raise AssertionError(f"index run did not finish; last={last}")


def create_flow(client: TestClient, email_prefix: str) -> tuple[dict[str, str], str, str, str]:
    headers = {"X-User-Email": f"{email_prefix}-{int(time.time() * 1000)}@example.com"}
    slug = f"{email_prefix}-{int(time.time() * 1000)}"
    ws = client.post("/workspaces", json={"name": email_prefix, "slug": slug}, headers=headers)
    assert ws.status_code == 201, ws.text
    workspace_id = ws.json()["id"]
    project = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"name": f"Project {slug}", "description": "demo"},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    project_id = project.json()["id"]
    resource = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources",
        json={
            "type": "markdown",
            "name": f"Runbook {slug}",
            "uri": "doc://runbook",
            "source_config": {"content": "Runbook body with an indexable marker token."},
        },
        headers=headers,
    )
    assert resource.status_code == 201, resource.text
    return headers, workspace_id, project_id, resource.json()["id"]


def test_workspace_project_resource_refresh_flow() -> None:
    require_real_services()
    old_dev_auth = os.environ.get("CONTEXTSMITH_DEV_AUTH")
    os.environ["CONTEXTSMITH_DEV_AUTH"] = "false"
    try:
        unauthenticated = TestClient(app).post("/workspaces", json={"name": "No Auth", "slug": f"no-auth-{int(time.time() * 1000)}"})
        assert unauthenticated.status_code == 401
    finally:
        if old_dev_auth is None:
            os.environ["CONTEXTSMITH_DEV_AUTH"] = "true"
        else:
            os.environ["CONTEXTSMITH_DEV_AUTH"] = old_dev_auth

    client = TestClient(app)
    headers, workspace_id, project_id, resource_id = create_flow(client, "owner")

    run = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/refresh",
        headers=headers,
    )
    assert run.status_code == 202, run.text
    assert run.json()["status"] == "queued"

    completed = wait_for_run(client, workspace_id, run.json()["id"], headers)
    assert completed["status"] == "succeeded"
    assert completed["documents_seen"] == 1
    assert completed["chunks_created"] >= 1
    assert completed["snapshot_id"]

    audit = client.get(f"/workspaces/{workspace_id}/audit-events", headers=headers)
    assert audit.status_code == 200
    actions = {event["action"] for event in audit.json()}
    assert {"workspace.create", "project.create", "resource.create", "resource.refresh"} <= actions

    denied = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}",
        headers={"X-User-Email": "intruder@example.com"},
    )
    assert denied.status_code == 404


def test_refresh_failure_path_records_failed_status() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id, resource_id = create_flow(client, "fail")
    run = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/refresh?fail=true",
        headers=headers,
    )
    assert run.status_code == 202

    failed = wait_for_run(client, workspace_id, run.json()["id"], headers)
    assert failed["status"] == "failed"
    assert "intentional placeholder failure" in failed["error_message"]


def test_api_token_scopes_and_resource_allowlist() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id, resource_id = create_flow(client, "token")

    other = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources",
        json={
            "type": "markdown",
            "name": f"Secret {int(time.time() * 1000)}",
            "uri": "doc://secret",
            "source_config": {"content": "Secret resource with marker token that should stay out of scoped context."},
        },
        headers=headers,
    )
    assert other.status_code == 201, other.text
    other_resource_id = other.json()["id"]

    run_ids: dict[str, str] = {}
    for rid in (resource_id, other_resource_id):
        run = client.post(
            f"/workspaces/{workspace_id}/projects/{project_id}/resources/{rid}/refresh",
            headers=headers,
        )
        assert run.status_code == 202, run.text
        run_ids[rid] = run.json()["id"]
        assert wait_for_run(client, workspace_id, run.json()["id"], headers)["status"] == "succeeded"

    created = client.post(
        f"/workspaces/{workspace_id}/api-tokens",
        json={
            "name": "Hermes scoped token",
            "scopes": ["project:query", "resource:read"],
            "allowed_project_ids": [project_id],
            "allowed_resource_ids": [resource_id],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    token = created.json()["token"]
    token_id = created.json()["api_token"]["id"]
    bearer = {"Authorization": f"Bearer {token}"}

    child_attempt = client.post(
        f"/workspaces/{workspace_id}/api-tokens",
        json={"name": "bad child", "scopes": ["project:query"], "allowed_project_ids": [project_id]},
        headers=bearer,
    )
    assert child_attempt.status_code == 403

    project_attempt = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"name": "Denied project"},
        headers=bearer,
    )
    assert project_attempt.status_code == 403

    listed = client.get(f"/workspaces/{workspace_id}/projects/{project_id}/resources", headers=bearer)
    assert listed.status_code == 200, listed.text
    assert [item["id"] for item in listed.json()] == [resource_id]

    visible_run = client.get(f"/workspaces/{workspace_id}/index-runs/{run_ids[resource_id]}", headers=bearer)
    assert visible_run.status_code == 200, visible_run.text
    hidden_run = client.get(f"/workspaces/{workspace_id}/index-runs/{run_ids[other_resource_id]}", headers=bearer)
    assert hidden_run.status_code == 404

    listed_tokens = client.get(f"/workspaces/{workspace_id}/api-tokens", headers=headers)
    assert listed_tokens.status_code == 200
    persisted = next(item for item in listed_tokens.json() if item["id"] == token_id)
    assert persisted["last_used_at"] is not None

    denied_write = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources",
        json={"type": "markdown", "name": "Denied", "uri": "doc://denied", "source_config": {"content": "nope"}},
        headers=bearer,
    )
    assert denied_write.status_code == 403

    write_scoped = client.post(
        f"/workspaces/{workspace_id}/api-tokens",
        json={
            "name": "resource scoped writer",
            "scopes": ["resource:write"],
            "allowed_project_ids": [project_id],
            "allowed_resource_ids": [resource_id],
        },
        headers=headers,
    )
    assert write_scoped.status_code == 201, write_scoped.text
    write_bearer = {"Authorization": f"Bearer {write_scoped.json()['token']}"}
    scoped_create = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources",
        json={"type": "markdown", "name": "Denied scoped", "uri": "doc://denied-scoped", "source_config": {"content": "nope"}},
        headers=write_bearer,
    )
    assert scoped_create.status_code == 403

    context = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
        json={"query": "marker token", "runtime": "hermes", "top_k": 8, "include_code_symbols": False},
        headers=bearer,
    )
    assert context.status_code == 200, context.text
    citations = context.json()["citations"]
    assert citations
    assert {citation["resource_id"] for citation in citations} == {resource_id}
    assert other_resource_id not in context.json()["context"]

    empty_resource_filter = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
        json={"query": "marker token", "runtime": "hermes", "resource_ids": [], "include_code_symbols": False},
        headers=bearer,
    )
    assert empty_resource_filter.status_code == 200, empty_resource_filter.text
    assert {citation["resource_id"] for citation in empty_resource_filter.json()["citations"]} == {resource_id}

    explicit_denied = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
        json={"query": "marker token", "resource_ids": [other_resource_id]},
        headers=bearer,
    )
    assert explicit_denied.status_code == 404

    revoked = client.delete(f"/workspaces/{workspace_id}/api-tokens/{token_id}", headers=headers)
    assert revoked.status_code == 200, revoked.text
    after_revoke = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
        json={"query": "marker token"},
        headers=bearer,
    )
    assert after_revoke.status_code == 401
