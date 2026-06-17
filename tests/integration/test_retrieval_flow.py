from __future__ import annotations

import time
import uuid
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import text

import contextsmith_api.main as api_main
import contextsmith_api.retrieval as retrieval_module
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
    except Exception as exc:  # pragma: no cover - diagnostic path
        pytest.skip(f"real Postgres/Redis services are not available: {exc}")


def make_project(client: TestClient, prefix: str) -> tuple[dict[str, str], str, str]:
    stamp = f"{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
    headers = {"X-User-Email": f"{prefix}-{stamp}@example.com"}
    ws = client.post("/workspaces", json={"name": prefix, "slug": f"{prefix}-{stamp}"}, headers=headers)
    assert ws.status_code == 201, ws.text
    workspace_id = ws.json()["id"]
    project = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"name": f"Project {stamp}", "description": "m3"},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    return headers, workspace_id, project.json()["id"]


def add_resource(client: TestClient, workspace_id: str, project_id: str, headers: dict[str, str], payload: dict) -> str:
    res = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources",
        json=payload,
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def ingest_inproc(client: TestClient, workspace_id: str, project_id: str, resource_id: str, headers: dict[str, str]) -> dict:
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
    response = client.get(f"/workspaces/{workspace_id}/index-runs/{run_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_context_packet_hybrid_retrieval_records_analytics() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "m3-context")
    resource_id = add_resource(
        client,
        workspace_id,
        project_id,
        headers,
        {
            "type": "markdown",
            "name": "M3 Retrieval Runbook",
            "uri": "doc://m3-retrieval",
            "source_config": {
                "content": "Hybrid retrieval combines lexical search, vector embeddings, and rerank scoring. Marker narwhalvector42."
            },
        },
    )
    completed = ingest_inproc(client, workspace_id, project_id, resource_id, headers)
    assert completed["status"] == "succeeded", completed
    assert completed["embeddings_created"] >= 1

    packet = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packets",
        json={"query": "hybrid vector rerank narwhalvector42", "top_k": 5},
        headers=headers,
    )
    assert packet.status_code == 201, packet.text
    body = packet.json()
    assert body["query_run_id"]
    assert body["id"]
    assert body["provider"] == "hashing"
    assert body["model"] == "contextsmith-hashing-v1"
    assert body["diagnostics"]["embedding_namespace"] == "hashing:contextsmith-hashing-v1:d64:l2"
    assert body["diagnostics"]["embedding_normalized"] is True
    assert body["diagnostics"]["rerank_score_range"] == [0.0, 1.0]
    assert body["diagnostics"]["vector_status"] == "ok"
    assert body["diagnostics"]["matching_embedding_count"] >= 1
    assert body["diagnostics"]["available_embedding_namespaces"] == ["hashing:contextsmith-hashing-v1:d64:l2"]
    assert body["count"] >= 1
    item = body["items"][0]
    assert item["resource_id"] == resource_id
    assert item["citation"]["resource_id"] == resource_id
    assert item["citation"]["snapshot_id"] == item["snapshot_id"]
    assert "narwhalvector42" in item["snippet"].lower()
    assert item["vector_score"] != 0

    session = get_sessionmaker()()
    try:
        query_rows = [
            dict(row)
            for row in session.execute(
                text("SELECT hit_count, status, metadata FROM query_runs WHERE id = CAST(:id AS uuid)"),
                {"id": body["query_run_id"]},
            )
            .mappings()
            .all()
        ]
        assert query_rows[0]["hit_count"] == body["count"]
        assert query_rows[0]["status"] == "succeeded"
        assert query_rows[0]["metadata"]["embedding_namespace"] == "hashing:contextsmith-hashing-v1:d64:l2"
        embedding_rows = [
            dict(row)
            for row in session.execute(
                text(
                    "SELECT provider, model, dimensions, namespace, normalized FROM chunk_embeddings "
                    "WHERE resource_id = CAST(:rid AS uuid)"
                ),
                {"rid": resource_id},
            )
            .mappings()
            .all()
        ]
        assert embedding_rows
        assert {row["namespace"] for row in embedding_rows} == {"hashing:contextsmith-hashing-v1:d64:l2"}
        assert all(row["normalized"] is True for row in embedding_rows)
        hit_count = session.execute(
            text("SELECT count(*) FROM retrieval_hits WHERE query_run_id = CAST(:id AS uuid)"),
            {"id": body["query_run_id"]},
        ).scalar_one()
        item_count = session.execute(
            text("SELECT count(*) FROM context_packet_items WHERE context_packet_id = CAST(:id AS uuid)"),
            {"id": body["id"]},
        ).scalar_one()
        assert hit_count == body["count"]
        assert item_count == body["count"]

        session.execute(
            text("UPDATE chunk_embeddings SET namespace = 'other:model:d64:l2' WHERE resource_id = CAST(:rid AS uuid)"),
            {"rid": resource_id},
        )
        session.commit()
    finally:
        session.close()

    packet_after_drift = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packets",
        json={"query": "hybrid vector rerank narwhalvector42", "top_k": 5},
        headers=headers,
    )
    assert packet_after_drift.status_code == 201, packet_after_drift.text
    drift_item = packet_after_drift.json()["items"][0]
    assert drift_item["resource_id"] == resource_id
    assert drift_item["vector_score"] == 0.0
    assert packet_after_drift.json()["diagnostics"]["vector_status"] == "namespace_mismatch"
    assert packet_after_drift.json()["diagnostics"]["matching_embedding_count"] == 0
    assert packet_after_drift.json()["diagnostics"]["available_embedding_namespaces"] == ["other:model:d64:l2"]


def test_context_packet_uses_current_snapshot_and_resource_filter() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "m3-current")
    first_resource = add_resource(
        client,
        workspace_id,
        project_id,
        headers,
        {
            "type": "markdown",
            "name": "Versioned Doc",
            "uri": "doc://versioned-m3",
            "source_config": {"content": "old revision says redpandaold only"},
        },
    )
    ingest_inproc(client, workspace_id, project_id, first_resource, headers)
    patched = client.patch(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{first_resource}",
        json={"source_config": {"content": "new revision says ottercurrent only"}},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    ingest_inproc(client, workspace_id, project_id, first_resource, headers)

    second_resource = add_resource(
        client,
        workspace_id,
        project_id,
        headers,
        {
            "type": "markdown",
            "name": "Other Doc",
            "uri": "doc://other-m3",
            "source_config": {"content": "other resource says ottercurrent but should be filtered"},
        },
    )
    ingest_inproc(client, workspace_id, project_id, second_resource, headers)

    old_packet = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packets",
        json={"query": "redpandaold", "top_k": 5, "resource_ids": [first_resource]},
        headers=headers,
    )
    assert old_packet.status_code == 201, old_packet.text
    assert old_packet.json()["count"] == 0

    current_packet = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packets",
        json={"query": "ottercurrent", "top_k": 5, "resource_ids": [first_resource]},
        headers=headers,
    )
    assert current_packet.status_code == 201, current_packet.text
    body = current_packet.json()
    assert body["count"] >= 1
    assert {item["resource_id"] for item in body["items"]} == {first_resource}
    assert all(UUID(item["resource_id"]) == UUID(first_resource) for item in body["items"])


def test_context_packet_denies_non_workspace_member() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "m3-auth")
    resource_id = add_resource(
        client,
        workspace_id,
        project_id,
        headers,
        {
            "type": "markdown",
            "name": "Secret Doc",
            "uri": "doc://secret-m3",
            "source_config": {"content": "secret context marker gryphonpacket"},
        },
    )
    ingest_inproc(client, workspace_id, project_id, resource_id, headers)

    denied = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packets",
        json={"query": "gryphonpacket"},
        headers={"X-User-Email": "intruder@example.com"},
    )
    assert denied.status_code == 404


def test_failed_reindex_keeps_last_good_snapshot_retrievable() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "m3-failed-refresh")
    resource_id = add_resource(
        client,
        workspace_id,
        project_id,
        headers,
        {
            "type": "markdown",
            "name": "Stable Doc",
            "uri": "doc://stable-m3",
            "source_config": {"content": "last good snapshot marker phoenixstable"},
        },
    )
    ingest_inproc(client, workspace_id, project_id, resource_id, headers)

    failed_run = get_sessionmaker()()
    run = IndexRun(
        workspace_id=UUID(workspace_id),
        project_id=UUID(project_id),
        resource_id=UUID(resource_id),
        trigger="manual",
        status="queued",
        meta={"fail": True},
    )
    failed_run.add(run)
    failed_run.commit()
    run_id = str(run.id)
    failed_run.close()
    try:
        run_index(run_id)
    except RuntimeError:
        pass

    packet = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packets",
        json={"query": "phoenixstable", "top_k": 5, "resource_ids": [resource_id]},
        headers=headers,
    )
    assert packet.status_code == 201, packet.text
    body = packet.json()
    assert body["count"] >= 1
    assert body["items"][0]["resource_id"] == resource_id


def test_context_packet_failure_persists_failed_query_run(monkeypatch) -> None:
    require_real_services()
    client = TestClient(app, raise_server_exceptions=False)
    headers, workspace_id, project_id = make_project(client, "m3-failed-query")

    def boom(*args, **kwargs):
        raise RuntimeError("synthetic retrieval failure")

    monkeypatch.setattr(api_main, "retrieve_context_candidates", boom)
    response = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packets",
        json={"query": "will fail", "top_k": 3},
        headers=headers,
    )
    assert response.status_code == 500

    session = get_sessionmaker()()
    try:
        rows = [
            dict(row)
            for row in session.execute(
                text(
                    """
                    SELECT status, hit_count, metadata
                    FROM query_runs
                    WHERE workspace_id = CAST(:ws AS uuid)
                      AND project_id = CAST(:proj AS uuid)
                      AND query = 'will fail'
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ),
                {"ws": workspace_id, "proj": project_id},
            )
            .mappings()
            .all()
        ]
        assert rows
        assert rows[0]["status"] == "failed"
        assert rows[0]["hit_count"] == 0
        assert "synthetic retrieval failure" in rows[0]["metadata"]["error"]
    finally:
        session.close()


def test_lexical_profile_does_not_call_embedding_provider(monkeypatch) -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "m27-lexical")
    resource_id = add_resource(
        client,
        workspace_id,
        project_id,
        headers,
        {
            "type": "markdown",
            "name": "Lexical Doc",
            "uri": "doc://m27-lexical",
            "source_config": {"content": "lexical-only marker platypuslexical27"},
        },
    )
    ingest_inproc(client, workspace_id, project_id, resource_id, headers)

    def fail_embed(*args, **kwargs):
        raise RuntimeError("embedding provider should not be called for lexical profile")

    monkeypatch.setattr(retrieval_module, "embed_text", fail_embed)
    response = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
        json={"query": "platypuslexical27", "profile": "lexical", "resource_ids": [resource_id], "top_k": 5},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["profile"] == "lexical"
    assert response.json()["citations"]
