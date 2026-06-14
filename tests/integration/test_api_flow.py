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
