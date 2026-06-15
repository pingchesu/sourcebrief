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


def test_provider_health_returns_503_on_failed_provider(monkeypatch) -> None:
    monkeypatch.setenv("CONTEXTSMITH_EMBEDDING_PROVIDER", "vllm")
    monkeypatch.delenv("CONTEXTSMITH_EMBEDDING_ENDPOINT", raising=False)
    response = TestClient(app).get("/provider-health")
    assert response.status_code == 503
    assert response.json()["status"] == "failed"
    assert response.json()["embedding"]["status"] == "failed"


def test_workspace_project_resource_refresh_flow() -> None:
    require_real_services()
    health = TestClient(app).get("/provider-health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["embedding"]["namespace"] == "hashing:contextsmith-hashing-v1:d64:l2"
    assert health.json()["embedding"]["dev_quality"] is True
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


def test_safe_connectors_upload_redaction_and_validation() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id, _ = create_flow(client, "m13")
    secret = "plainsecretvalue1234567890"
    upload = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources",
        json={
            "type": "upload",
            "name": "Uploaded Runbook",
            "uri": "upload://runbook.md",
            "source_config": {
                "filename": "runbook.md",
                "content_type": "text/markdown",
                "content": f"Upload marker safeupload and api_key={secret}",
            },
        },
        headers=headers,
    )
    assert upload.status_code == 201, upload.text
    resource_id = upload.json()["id"]
    run = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/refresh",
        headers=headers,
    )
    assert run.status_code == 202, run.text
    completed = wait_for_run(client, workspace_id, run.json()["id"], headers)
    assert completed["status"] == "succeeded"

    redacted_search = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/search",
        json={"query": "safeupload", "resource_ids": [resource_id]},
        headers=headers,
    )
    assert redacted_search.status_code == 200, redacted_search.text
    assert redacted_search.json()["count"] >= 1
    snippet = redacted_search.json()["hits"][0]["snippet"]
    assert "REDACTED:generic_api_key" in snippet
    assert secret not in snippet

    secret_search = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/search",
        json={"query": secret, "resource_ids": [resource_id]},
        headers=headers,
    )
    assert secret_search.status_code == 200, secret_search.text
    assert secret_search.json()["count"] == 0

    snapshots = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/snapshots",
        headers=headers,
    )
    assert snapshots.status_code == 200, snapshots.text
    assert snapshots.json()[0]["metadata"]["redacted_secret_counts"]["generic_api_key"] == 1

    unsafe_url = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources",
        json={"type": "url", "name": "Local", "uri": "http://127.0.0.1/admin", "source_config": {}},
        headers=headers,
    )
    assert unsafe_url.status_code == 422
    invalid_bound = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources",
        json={"type": "url", "name": "Bad Size", "uri": "https://example.com/doc", "source_config": {"max_url_bytes": -1}},
        headers=headers,
    )
    assert invalid_bound.status_code == 422
    sanitized_url = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources",
        json={
            "type": "url",
            "name": "Signed",
            "uri": "https://bad.example/internal?token=SECRET",
            "source_config": {"url": "https://example.com/doc?token=SECRET"},
        },
        headers=headers,
    )
    assert sanitized_url.status_code == 201, sanitized_url.text
    assert sanitized_url.json()["uri"] == "https://example.com/doc"
    assert "SECRET" not in sanitized_url.json()["uri"]
    unsafe_upload = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources",
        json={
            "type": "upload",
            "name": "Path Leak",
            "uri": "upload://bad",
            "source_config": {"path": "/etc/passwd", "content": "x"},
        },
        headers=headers,
    )
    assert unsafe_upload.status_code == 422


def test_api_tokens_enforce_scopes_and_resource_allowlists() -> None:
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

    scoped_eval = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/retrieval-evals",
        json={
            "questions": [
                {
                    "id": "scoped-token-defaults-to-allowed-resource",
                    "query": "marker token",
                    "expected_resource_ids": [resource_id],
                    "required_texts": ["Runbook body"],
                    "top_k": 8,
                }
            ]
        },
        headers=bearer,
    )
    assert scoped_eval.status_code == 200, scoped_eval.text
    scoped_eval_body = scoped_eval.json()
    assert scoped_eval_body["summary"]["status"] == "passed"
    assert scoped_eval_body["diagnostics"]["matching_embedding_count"] > 0
    assert {citation["resource_id"] for citation in scoped_eval_body["results"][0]["hit_quality"]} == {resource_id}

    eval_denied = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/retrieval-evals",
        json={"questions": [{"id": "denied", "query": "marker token", "resource_ids": [other_resource_id]}]},
        headers=bearer,
    )
    assert eval_denied.status_code == 404

    revoked = client.delete(f"/workspaces/{workspace_id}/api-tokens/{token_id}", headers=headers)
    assert revoked.status_code == 200, revoked.text
    after_revoke = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
        json={"query": "marker token"},
        headers=bearer,
    )
    assert after_revoke.status_code == 401
