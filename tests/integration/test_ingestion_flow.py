from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from rq import Queue, SimpleWorker
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
    except Exception as exc:  # pragma: no cover - diagnostic path
        pytest.skip(f"real Postgres/Redis services are not available: {exc}")


def drain_default_queue() -> None:
    redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6380/0"))
    queue = Queue("default", connection=redis)
    SimpleWorker([queue], connection=redis).work(burst=True)


def wait_for_run(client: TestClient, workspace_id: str, run_id: str, headers: dict[str, str]) -> dict:
    deadline = time.time() + 30
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


def make_project(client: TestClient, prefix: str) -> tuple[dict[str, str], str, str]:
    stamp = int(time.time() * 1_000_000)
    headers = {"X-User-Email": f"{prefix}-{stamp}@example.com"}
    ws = client.post("/workspaces", json={"name": prefix, "slug": f"{prefix}-{stamp}"}, headers=headers)
    assert ws.status_code == 201, ws.text
    workspace_id = ws.json()["id"]
    project = client.post(
        f"/workspaces/{workspace_id}/projects",
        json={"name": f"Project {stamp}", "description": "m2"},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    return headers, workspace_id, project.json()["id"]


def add_resource(client, workspace_id, project_id, headers, payload) -> str:
    res = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources",
        json=payload,
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def refresh(client, workspace_id, project_id, resource_id, headers) -> dict:
    run = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/refresh",
        headers=headers,
    )
    assert run.status_code == 202, run.text
    return wait_for_run(client, workspace_id, run.json()["id"], headers)


def ingest_inproc(client, workspace_id, project_id, resource_id, headers) -> dict:
    """Run ingestion synchronously in-process (bypassing the shared queue).

    Used where a competing compose worker (or a host-only fixture path it cannot
    reach) would make the queued path nondeterministic. It still exercises the
    real ingestion code against the real database.
    """
    session = get_sessionmaker()()
    run = IndexRun(
        workspace_id=uuid.UUID(workspace_id),
        project_id=uuid.UUID(project_id),
        resource_id=uuid.UUID(resource_id),
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


def test_document_ingestion_snapshot_chunks_and_search() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "doc")
    content = (
        "# Resource Lifecycle\n\n"
        "Resource deletion works by soft delete first, then an async purge job. "
        "The unique marker for this fixture is zebrafox42.\n"
    )
    resource_id = add_resource(
        client,
        workspace_id,
        project_id,
        headers,
        {
            "type": "markdown",
            "name": "Lifecycle Runbook",
            "uri": "doc://lifecycle",
            "source_config": {"content": content},
        },
    )

    completed = refresh(client, workspace_id, project_id, resource_id, headers)
    assert completed["status"] == "succeeded", completed
    assert completed["documents_seen"] == 1
    assert completed["chunks_created"] >= 1
    assert completed["snapshot_id"]

    snapshots = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/snapshots",
        headers=headers,
    )
    assert snapshots.status_code == 200, snapshots.text
    snaps = snapshots.json()
    assert len(snaps) == 1
    assert snaps[0]["version"]
    assert snaps[0]["version_kind"] == "content_hash"
    assert snaps[0]["status"] == "succeeded"
    assert snaps[0]["is_current"] is True

    runs = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/index-runs",
        headers=headers,
    )
    assert runs.status_code == 200
    assert any(r["status"] == "succeeded" for r in runs.json())

    found = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/search",
        json={"query": "zebrafox42"},
        headers=headers,
    )
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["count"] >= 1
    hit = body["hits"][0]
    assert hit["resource_id"] == resource_id
    assert hit["snapshot_id"] == snaps[0]["id"]
    assert hit["title"] == "Lifecycle Runbook"
    assert hit["path"] == "doc://lifecycle"
    assert isinstance(hit["ordinal"], int)
    assert hit["version"] == snaps[0]["version"]
    assert "zebrafox42" in hit["snippet"].lower()

    empty = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/search",
        json={"query": "nonexistentlexeme9999"},
        headers=headers,
    )
    assert empty.status_code == 200
    assert empty.json()["count"] == 0


def test_search_enforces_workspace_membership() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "scope")
    resource_id = add_resource(
        client,
        workspace_id,
        project_id,
        headers,
        {
            "type": "markdown",
            "name": "Secret Notes",
            "uri": "doc://secret",
            "source_config": {"content": "classified marker hippogriff in the vault"},
        },
    )
    refresh(client, workspace_id, project_id, resource_id, headers)

    denied = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/search",
        json={"query": "hippogriff"},
        headers={"X-User-Email": "intruder@example.com"},
    )
    assert denied.status_code == 404


def test_reindex_uses_current_snapshot_only() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "reindex")
    resource_id = add_resource(
        client,
        workspace_id,
        project_id,
        headers,
        {
            "type": "markdown",
            "name": "Versioned Doc",
            "uri": "doc://versioned",
            "source_config": {"content": "the first revision mentions alphatoken only"},
        },
    )
    refresh(client, workspace_id, project_id, resource_id, headers)

    patched = client.patch(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}",
        json={"source_config": {"content": "the second revision mentions betatoken only"}},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    refresh(client, workspace_id, project_id, resource_id, headers)

    snapshots = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/snapshots",
        headers=headers,
    ).json()
    assert len(snapshots) == 2

    new_hit = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/search",
        json={"query": "betatoken"},
        headers=headers,
    ).json()
    assert new_hit["count"] >= 1

    old_hit = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/search",
        json={"query": "alphatoken"},
        headers=headers,
    ).json()
    assert old_hit["count"] == 0


def _build_fixture_repo(path: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "qa",
        "GIT_AUTHOR_EMAIL": "qa@example.com",
        "GIT_COMMITTER_NAME": "qa",
        "GIT_COMMITTER_EMAIL": "qa@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }

    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", path, *args],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "init", "-q", path],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    os.makedirs(os.path.join(path, "src"), exist_ok=True)
    os.makedirs(os.path.join(path, "node_modules"), exist_ok=True)
    with open(os.path.join(path, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("# Fixture\nThe quokka subsystem handles retries.\n")
    with open(os.path.join(path, "src", "app.py"), "w", encoding="utf-8") as fh:
        fh.write("def quokka():\n    return 'retry'\n")
    with open(os.path.join(path, "node_modules", "lib.js"), "w", encoding="utf-8") as fh:
        fh.write("// junkmarker should never be indexed\n")
    with open(os.path.join(path, "logo.bin"), "wb") as fh:
        fh.write(b"\x00\x01\x02binarymarker")
    git("add", "-A")
    git("commit", "-q", "-m", "fixture commit")
    return git("rev-parse", "HEAD").stdout.strip()


def test_git_ingestion_indexes_text_files_with_commit_citation(tmp_path) -> None:
    require_real_services()
    if shutil.which("git") is None:
        pytest.skip("git executable not available")
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "git")

    repo_path = str(tmp_path / "fixture-repo")
    os.makedirs(repo_path, exist_ok=True)
    commit = _build_fixture_repo(repo_path)

    resource_id = add_resource(
        client,
        workspace_id,
        project_id,
        headers,
        {
            "type": "git",
            "name": "Fixture Repo",
            "uri": f"file://{repo_path}",
            "source_config": {"branch": "main"},
        },
    )
    completed = ingest_inproc(client, workspace_id, project_id, resource_id, headers)
    assert completed["status"] == "succeeded", completed
    # README.md + src/app.py only; node_modules and the binary are excluded.
    assert completed["documents_seen"] == 2
    assert completed["chunks_created"] >= 2

    snaps = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/snapshots",
        headers=headers,
    ).json()
    assert snaps[0]["version"] == commit
    assert snaps[0]["version_kind"] == "commit_sha"
    assert snaps[0]["metadata"]["commit"] == commit

    hits = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/search",
        json={"query": "quokka"},
        headers=headers,
    ).json()
    assert hits["count"] >= 1
    paths = {hit["path"] for hit in hits["hits"]}
    assert paths & {"README.md", "src/app.py"}
    for hit in hits["hits"]:
        assert hit["commit"] == commit
        assert "node_modules" not in (hit["path"] or "")

    # content that only lived in skipped files must not be searchable
    junk = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/search",
        json={"query": "junkmarker"},
        headers=headers,
    ).json()
    assert junk["count"] == 0
