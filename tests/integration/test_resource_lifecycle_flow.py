from __future__ import annotations

import time
import uuid
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import text

from contextsmith_api.main import app
from contextsmith_shared.config import get_settings
from contextsmith_shared.db import get_engine, get_sessionmaker
from contextsmith_shared.models import IndexRun
from contextsmith_worker.jobs import run_index

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
        json={"name": f"Project {stamp}", "description": "m5"},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    return headers, workspace_id, project.json()["id"]


def add_doc(client: TestClient, workspace_id: str, project_id: str, headers: dict[str, str], name: str, marker: str) -> str:
    res = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources",
        json={
            "type": "markdown",
            "name": name,
            "uri": f"doc://{marker}",
            "source_config": {"content": f"# {name}\n{marker} context for lifecycle review", "path": f"{marker}.md"},
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


def test_resource_review_usage_archive_and_delete_flow() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "m5-flow")
    resource_id = add_doc(client, workspace_id, project_id, headers, "Lifecycle Doc", "marmotreview")
    ingest(resource_id, workspace_id, project_id)

    packet = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packets",
        json={"query": "marmotreview", "top_k": 3, "resource_ids": [resource_id]},
        headers=headers,
    )
    assert packet.status_code == 201, packet.text
    assert packet.json()["count"] >= 1

    usage = client.get(f"/workspaces/{workspace_id}/projects/{project_id}/resource-usage", headers=headers)
    assert usage.status_code == 200, usage.text
    usage_row = next(item for item in usage.json()["resources"] if item["resource_id"] == resource_id)
    assert usage_row["query_count"] == 1
    assert usage_row["hit_count"] == packet.json()["count"]
    assert usage_row["context_packet_count"] == 1

    reviewed = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/review",
        json={"review_status": "needs_update", "review_note": "source drift", "retrieval_enabled": False, "stale_after_days": 1},
        headers=headers,
    )
    assert reviewed.status_code == 200, reviewed.text
    body = reviewed.json()
    assert body["review_status"] == "needs_update"
    assert body["retrieval_enabled"] is False
    assert body["stale_after_days"] == 1

    review = client.get(f"/workspaces/{workspace_id}/projects/{project_id}/resource-review", headers=headers)
    assert review.status_code == 200, review.text
    item = next(item for item in review.json()["resources"] if item["resource"]["id"] == resource_id)
    assert item["freshness_status"] == "stale"
    assert "review_status:needs_update" in item["stale_reasons"]
    assert item["usage_count"] >= 1

    search = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packets",
        json={"query": "marmotreview", "top_k": 3, "resource_ids": [resource_id]},
        headers=headers,
    )
    assert search.status_code == 201, search.text
    assert search.json()["count"] == 0

    archived = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/archive",
        headers=headers,
    )
    assert archived.status_code == 200, archived.text
    assert archived.json()["status"] == "archived"
    reenable_patch = client.patch(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}",
        json={"retrieval_enabled": True},
        headers=headers,
    )
    assert reenable_patch.status_code == 409
    reenable_review = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/review",
        json={"review_status": "approved", "retrieval_enabled": True},
        headers=headers,
    )
    assert reenable_review.status_code == 409
    archived_search = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packets",
        json={"query": "marmotreview", "top_k": 3, "resource_ids": [resource_id]},
        headers=headers,
    )
    assert archived_search.status_code == 201
    assert archived_search.json()["count"] == 0
    archived_lexical = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/search",
        json={"query": "marmotreview", "top_k": 3, "resource_ids": [resource_id]},
        headers=headers,
    )
    assert archived_lexical.status_code == 200
    assert archived_lexical.json()["count"] == 0
    hidden_review = client.get(f"/workspaces/{workspace_id}/projects/{project_id}/resource-review", headers=headers)
    assert all(item["resource"]["id"] != resource_id for item in hidden_review.json()["resources"])
    shown_review = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/resource-review?include_archived=true",
        headers=headers,
    )
    assert any(item["resource"]["id"] == resource_id for item in shown_review.json()["resources"])

    deleted = client.delete(f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}", headers=headers)
    assert deleted.status_code == 204
    deleted_search = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packets",
        json={"query": "marmotreview", "top_k": 3, "resource_ids": [resource_id]},
        headers=headers,
    )
    assert deleted_search.status_code == 201
    assert deleted_search.json()["count"] == 0
    resources = client.get(f"/workspaces/{workspace_id}/projects/{project_id}/resources", headers=headers)
    assert all(resource["id"] != resource_id for resource in resources.json())

    audit = client.get(f"/workspaces/{workspace_id}/audit-events", headers=headers)
    assert audit.status_code == 200
    lifecycle_events = [event for event in audit.json() if event["target_id"] == resource_id]
    review_event = next(event for event in lifecycle_events if event["action"] == "resource.review")
    archive_event = next(event for event in lifecycle_events if event["action"] == "resource.archive")
    delete_event = next(event for event in lifecycle_events if event["action"] == "resource.delete")
    assert review_event["actor_user_id"] is not None
    assert review_event["metadata"]["review_note"] == "source drift"
    assert review_event["metadata"]["new"]["review_status"] == "needs_update"
    assert review_event["metadata"]["new"]["retrieval_enabled"] is False
    assert archive_event["metadata"]["previous"]["status"] in {"active", "failed"}
    assert archive_event["metadata"]["new"]["status"] == "archived"
    assert archive_event["metadata"]["new"]["retrieval_enabled"] is False
    assert delete_event["metadata"]["previous"]["status"] == "archived"
    assert delete_event["metadata"]["new"]["status"] == "deleted"


def test_resource_lifecycle_requires_project_membership() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "m5-auth")
    resource_id = add_doc(client, workspace_id, project_id, headers, "Auth Doc", "authreview")
    intruder = {"X-User-Email": "m5-intruder@example.com"}
    for method, url in [
        ("get", f"/workspaces/{workspace_id}/projects/{project_id}/resource-review"),
        ("get", f"/workspaces/{workspace_id}/projects/{project_id}/resource-usage"),
        ("post", f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/review"),
        ("post", f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/archive"),
        ("delete", f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}"),
    ]:
        kwargs = {"headers": intruder}
        if method == "post" and url.endswith("/review"):
            kwargs["json"] = {"review_status": "approved"}
        response = getattr(client, method)(url, **kwargs)
        assert response.status_code == 404
