from __future__ import annotations

import io
import os
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from rq import Queue
from sqlalchemy import text

from contextsmith_api.main import _bootstrap_default_admin, app
from contextsmith_shared.config import get_settings
from contextsmith_shared.db import get_engine
from contextsmith_worker.jobs import run_index

pytestmark = pytest.mark.integration


def require_real_services() -> None:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("select 1"))
        Redis.from_url(get_settings().redis_url).ping()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"real Postgres/Redis services are not available: {exc}")


def login_admin(client: TestClient, monkeypatch: pytest.MonkeyPatch, prefix: str) -> tuple[str, str]:
    suffix = f"{prefix}-{int(time.time() * 1000)}"
    email = f"{suffix}@contextsmith.local"
    password = f"{suffix}-password"
    monkeypatch.setenv("CONTEXTSMITH_ADMIN_EMAIL", email)
    monkeypatch.setenv("CONTEXTSMITH_ADMIN_PASSWORD", password)
    monkeypatch.setenv("CONTEXTSMITH_ADMIN_DISPLAY_NAME", f"Admin {suffix}")
    monkeypatch.setenv("CONTEXTSMITH_BOOTSTRAP_WORKSPACE_NAME", f"Workspace {suffix}")
    monkeypatch.setenv("CONTEXTSMITH_BOOTSTRAP_WORKSPACE_SLUG", suffix)
    monkeypatch.setenv("CONTEXTSMITH_BOOTSTRAP_PROJECT_NAME", f"Project {suffix}")
    _bootstrap_default_admin()
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    return body["session_token"], body["default_workspace_id"] + ":" + body["default_project_id"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def make_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries.items():
            zf.writestr(name, payload)
    return buf.getvalue()


def upload_bundle(client: TestClient, workspace_id: str, project_id: str, token: str, name: str | None, entries: dict[str, bytes], supersedes_resource_id: str | None = None) -> dict:
    data: dict[str, str] = {"update_frequency": "manual"}
    if name is not None:
        data["name"] = name
    if supersedes_resource_id:
        data["supersedes_resource_id"] = supersedes_resource_id
    response = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/upload-folder-bundle",
        headers=auth_headers(token),
        data=data,
        files={"zip_file": ("bundle.zip", make_zip(entries), "application/zip")},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    run_index(body["index_run"]["id"])
    return body


@pytest.mark.skipif(not os.getenv("CONTEXTSMITH_RUN_REAL_INTEGRATION"), reason="requires real Postgres/Redis services")
def test_folder_bundle_manifest_diff_v1_v2(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    require_real_services()
    monkeypatch.setenv("CONTEXTSMITH_WORK_DIR", str(tmp_path / "work"))
    client = TestClient(app)
    token, scope = login_admin(client, monkeypatch, "manifest-diff")
    workspace_id, project_id = scope.split(":")

    v1 = upload_bundle(
        client,
        workspace_id,
        project_id,
        token,
        "Diff bundle",
        {"README.md": b"old", "keep.txt": b"same", "delete.txt": b"gone"},
    )
    v2 = upload_bundle(
        client,
        workspace_id,
        project_id,
        token,
        None,
        {"README.md": b"new", "keep.txt": b"same", "added.txt": b"add"},
        supersedes_resource_id=v1["resource"]["id"],
    )

    assert v2["resource"]["source_family_label"] == "Diff bundle"
    assert v2["resource"]["version_label"] == "v2"
    assert v2["resource"]["name"] != "Diff bundle"

    diff = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{v2['resource']['id']}/manifest-diff",
        headers=auth_headers(token),
    )
    assert diff.status_code == 200, diff.text
    body = diff.json()
    assert body["added_count"] == 1
    assert body["changed_count"] == 1
    assert body["deleted_count"] == 1
    assert body["unchanged_count"] == 1
    assert body["deleted_file_impact"]["impacted_sections_known"] is False
    by_path = {row["normalized_path"]: row["change_type"] for row in body["rows"]}
    assert by_path["README.md"] == "changed"
    assert by_path["added.txt"] == "added"
    assert by_path["delete.txt"] == "deleted"
    assert by_path["keep.txt"] == "unchanged"

    added = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{v2['resource']['id']}/manifest-diff",
        headers=auth_headers(token),
        params={"change_type": "added", "limit": 1},
    )
    assert added.status_code == 200
    assert added.json()["total_row_count"] == 1
    assert added.json()["rows"][0]["normalized_path"] == "added.txt"

    forged = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/upload-folder-bundle",
        headers=auth_headers(token),
        data={"name": "Diff bundle", "source_family_id": v1["resource"]["id"]},
        files={"zip_file": ("bundle.zip", make_zip({"README.md": b"bad"}), "application/zip")},
    )
    assert forged.status_code == 422

    scoped = client.post(
        f"/workspaces/{workspace_id}/api-tokens",
        headers=auth_headers(token),
        json={
            "name": "Diff scoped token",
            "scopes": ["resource:read"],
            "allowed_project_ids": [project_id],
            "allowed_resource_ids": [v2["resource"]["id"]],
        },
    )
    assert scoped.status_code == 201, scoped.text
    scoped_headers = auth_headers(scoped.json()["token"])
    listed = client.get(f"/workspaces/{workspace_id}/projects/{project_id}/resources", headers=scoped_headers)
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == v2["resource"]["id"]
    assert listed.json()[0]["has_manifest_diff"] is False
    denied_diff = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{v2['resource']['id']}/manifest-diff",
        headers=scoped_headers,
    )
    assert denied_diff.status_code == 404


@pytest.mark.skipif(not os.getenv("CONTEXTSMITH_RUN_REAL_INTEGRATION"), reason="requires real Postgres/Redis services")
def test_manifest_diff_with_one_version_returns_conflict(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    require_real_services()
    monkeypatch.setenv("CONTEXTSMITH_WORK_DIR", str(tmp_path / "work"))
    client = TestClient(app)
    token, scope = login_admin(client, monkeypatch, "manifest-diff-single")
    workspace_id, project_id = scope.split(":")
    v1 = upload_bundle(client, workspace_id, project_id, token, "Single diff bundle", {"README.md": b"only"})
    response = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{v1['resource']['id']}/manifest-diff",
        headers=auth_headers(token),
    )
    assert response.status_code == 409


def test_real_services_reachable_for_manifest_diff() -> None:
    require_real_services()
    Redis.from_url(get_settings().redis_url).ping()
    Queue("default", connection=Redis.from_url(get_settings().redis_url))
