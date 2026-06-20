from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import func, select, text

from sourcebrief_api import main as api_main
from sourcebrief_api.main import _bootstrap_default_admin, app
from sourcebrief_shared.config import get_settings
from sourcebrief_shared.db import get_engine, get_sessionmaker
from sourcebrief_shared.models import (
    AuditEvent,
    IndexRun,
    Resource,
    ResourceManifest,
    ResourceManifestFile,
    SnapshotFile,
    SourceSnapshot,
)
from sourcebrief_worker.jobs import run_index

pytestmark = pytest.mark.integration


def require_real_services() -> None:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("select 1"))
        Redis.from_url(get_settings().redis_url).ping()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"real Postgres/Redis services are not available: {exc}")


def make_zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, payload)
    return buf.getvalue()


def login_admin(client: TestClient, monkeypatch: pytest.MonkeyPatch, prefix: str) -> tuple[str, str]:
    suffix = f"{prefix}-{int(time.time() * 1000)}"
    email = f"{suffix}@sourcebrief.local"
    password = f"{suffix}-password"
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_EMAIL", email)
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_PASSWORD", password)
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_DISPLAY_NAME", f"Admin {suffix}")
    monkeypatch.setenv("SOURCEBRIEF_BOOTSTRAP_WORKSPACE_NAME", f"Workspace {suffix}")
    monkeypatch.setenv("SOURCEBRIEF_BOOTSTRAP_WORKSPACE_SLUG", suffix)
    monkeypatch.setenv("SOURCEBRIEF_BOOTSTRAP_PROJECT_NAME", f"Project {suffix}")
    _bootstrap_default_admin()
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    return body["session_token"], body["default_workspace_id"] + ":" + body["default_project_id"]


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_upload_folder_bundle_and_run_index_creates_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    require_real_services()
    monkeypatch.setenv("SOURCEBRIEF_WORK_DIR", str(tmp_path / "work"))
    client = TestClient(app)
    token, scope = login_admin(client, monkeypatch, "folder-flow")
    workspace_id, project_id = scope.split(":")

    payload = make_zip({"README.md": b"# Hello\nThis is real content.", "src/app.py": b"print('ok')\n", "image.png": b"\x89PNG\r\n\x1a\n"})
    upload = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/upload-folder-bundle",
        headers=auth_headers(token),
        data={"name": "Real folder bundle", "update_frequency": "manual"},
        files={"zip_file": ("bundle.zip", payload, "application/zip")},
    )
    assert upload.status_code == 202, upload.text
    body = upload.json()
    resource_id = body["resource"]["id"]
    run_id = body["index_run"]["id"]

    run_index(run_id)

    session = get_sessionmaker()()
    try:
        resource = session.get(Resource, resource_id)
        assert resource is not None
        assert resource.status == "active"
        run = session.get(IndexRun, run_id)
        assert run is not None
        assert run.status == "succeeded"
        manifest = session.scalar(select(ResourceManifest).where(ResourceManifest.resource_id == resource.id))
        assert manifest is not None
        assert manifest.file_count == 3
        assert manifest.unsupported_file_count == 1
        files = session.scalars(select(ResourceManifestFile).where(ResourceManifestFile.resource_id == resource.id)).all()
        assert {file.normalized_path for file in files} == {"README.md", "src/app.py", "image.png"}
        snapshot_files = session.scalars(select(SnapshotFile).where(SnapshotFile.resource_id == resource.id)).all()
        assert {file.path for file in snapshot_files} == {"README.md", "src/app.py"}
        snapshot = session.scalar(select(SourceSnapshot).where(SourceSnapshot.resource_id == resource.id))
        assert snapshot is not None
        assert "manifest_file_rows" not in snapshot.meta
        assert "text" not in str(snapshot.meta)
        upload_actions = set(session.scalars(select(AuditEvent.action).where(AuditEvent.target_id == resource.id)).all())
        assert "resource.upload" in upload_actions
        manifest_event = session.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "manifest.created",
                AuditEvent.target_ref["resource_id"].astext == str(resource.id),
            )
        )
        assert manifest_event is not None
    finally:
        session.close()

    manifest_response = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/manifest",
        headers=auth_headers(token),
    )
    assert manifest_response.status_code == 200, manifest_response.text
    assert manifest_response.json()["file_count"] == 3

    refresh = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/refresh",
        headers=auth_headers(token),
    )
    assert refresh.status_code == 422
    assert "uploading a new zip" in refresh.json()["detail"]

    patch_frequency = client.patch(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}",
        headers=auth_headers(token),
        json={"update_frequency": "daily"},
    )
    assert patch_frequency.status_code == 422
    assert "manual-only" in patch_frequency.json()["detail"]


def test_upload_traversal_zip_rejected_before_resource_create(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    require_real_services()
    monkeypatch.setenv("SOURCEBRIEF_WORK_DIR", str(tmp_path / "work"))
    client = TestClient(app)
    token, scope = login_admin(client, monkeypatch, "folder-bad")
    workspace_id, project_id = scope.split(":")
    session = get_sessionmaker()()
    try:
        before = session.scalar(select(func.count()).select_from(Resource).where(Resource.project_id == project_id))
    finally:
        session.close()
    bad_zip = make_zip({"../secret.txt": b"no"})
    response = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/upload-folder-bundle",
        headers=auth_headers(token),
        data={"name": "Bad bundle"},
        files={"zip_file": ("bad.zip", bad_zip, "application/zip")},
    )
    assert response.status_code == 422
    assert "secret.txt" in response.json()["detail"]
    session = get_sessionmaker()()
    try:
        after = session.scalar(select(func.count()).select_from(Resource).where(Resource.project_id == project_id))
        assert after == before
    finally:
        session.close()
    uploads = tmp_path / "work" / "uploads"
    assert not any(uploads.glob("*.zip"))


def test_upload_folder_bundle_is_manual_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    require_real_services()
    monkeypatch.setenv("SOURCEBRIEF_WORK_DIR", str(tmp_path / "work"))
    client = TestClient(app)
    token, scope = login_admin(client, monkeypatch, "folder-manual")
    workspace_id, project_id = scope.split(":")
    response = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/upload-folder-bundle",
        headers=auth_headers(token),
        data={"name": "Daily bundle", "update_frequency": "daily"},
        files={"zip_file": ("bundle.zip", make_zip({"README.md": b"ok"}), "application/zip")},
    )
    assert response.status_code == 422
    assert "manual-only" in response.json()["detail"]


def test_enqueue_failure_marks_failed_and_deletes_staged_zip(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    require_real_services()
    monkeypatch.setenv("SOURCEBRIEF_WORK_DIR", str(tmp_path / "work"))
    client = TestClient(app)
    token, scope = login_admin(client, monkeypatch, "folder-enqueue")
    workspace_id, project_id = scope.split(":")

    class FailingQueue:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def enqueue(self, *args, **kwargs) -> None:
            raise RuntimeError("redis unavailable")

    monkeypatch.setattr(api_main, "Queue", FailingQueue)
    response = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/upload-folder-bundle",
        headers=auth_headers(token),
        data={"name": "Queue fail bundle"},
        files={"zip_file": ("bundle.zip", make_zip({"README.md": b"ok"}), "application/zip")},
    )
    assert response.status_code == 503
    uploads = tmp_path / "work" / "uploads"
    assert not any(uploads.glob("*.zip"))
    session = get_sessionmaker()()
    try:
        resources = session.scalars(select(Resource).where(Resource.project_id == project_id, Resource.type == "folder_bundle")).all()
        assert len(resources) == 1
        assert resources[0].deleted_at is not None
        run = session.scalar(select(IndexRun).where(IndexRun.resource_id == resources[0].id))
        assert run is not None
        assert run.status == "failed"
    finally:
        session.close()
