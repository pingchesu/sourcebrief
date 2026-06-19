from __future__ import annotations

import io
import os
import subprocess
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

    manifest = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{v2['resource']['id']}/manifest",
        headers=auth_headers(token),
    )
    assert manifest.status_code == 200, manifest.text
    manifest_body = manifest.json()
    assert manifest_body["section_count"] >= 3
    assert manifest_body["sections_reused_count"] >= 1
    assert manifest_body["sections_extracted_count"] >= 1
    assert manifest_body["sections_from_deleted_files_count"] >= 1
    assert manifest_body["sections_absent_count"] >= 1

    sections = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{v2['resource']['id']}/snapshot-sections",
        headers=auth_headers(token),
    )
    assert sections.status_code == 200, sections.text
    sections_body = sections.json()
    assert sections_body["section_count"] == manifest_body["section_count"]
    assert sections_body["rows"]
    assert {row["reuse_status"] for row in sections_body["rows"]} >= {"reused", "extracted"}

    impact = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{v2['resource']['id']}/section-impact",
        headers=auth_headers(token),
    )
    assert impact.status_code == 200, impact.text
    assert impact.json()["sections_from_deleted_files_count"] == manifest_body["sections_from_deleted_files_count"]
    assert impact.json()["impacted_artifacts_known"] is False

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
def test_section_absence_is_not_position_sensitive(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    require_real_services()
    monkeypatch.setenv("CONTEXTSMITH_WORK_DIR", str(tmp_path / "work"))
    client = TestClient(app)
    token, scope = login_admin(client, monkeypatch, "section-shift")
    workspace_id, project_id = scope.split(":")

    v1 = upload_bundle(
        client,
        workspace_id,
        project_id,
        token,
        "Shifted section bundle",
        {"README.md": b"# A\nalpha\n# B\nbravo\n# C\ncharlie"},
    )
    v2 = upload_bundle(
        client,
        workspace_id,
        project_id,
        token,
        None,
        {"README.md": b"# A\nalpha\n# C\ncharlie"},
        supersedes_resource_id=v1["resource"]["id"],
    )
    manifest = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{v2['resource']['id']}/manifest",
        headers=auth_headers(token),
    )
    assert manifest.status_code == 200, manifest.text
    body = manifest.json()
    assert body["section_count"] == 2
    assert body["sections_absent_count"] == 1


@pytest.mark.skipif(not os.getenv("CONTEXTSMITH_RUN_REAL_INTEGRATION"), reason="requires real Postgres/Redis services")
def test_section_absence_hash_fallback_is_path_scoped(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    require_real_services()
    monkeypatch.setenv("CONTEXTSMITH_WORK_DIR", str(tmp_path / "work"))
    client = TestClient(app)
    token, scope = login_admin(client, monkeypatch, "section-path-scope")
    workspace_id, project_id = scope.split(":")

    v1 = upload_bundle(
        client,
        workspace_id,
        project_id,
        token,
        "Path scoped section bundle",
        {
            "AAA.md": b"# C\ncharlie",
            "README.md": b"# A\nalpha\n# B\nbravo\n# C\ncharlie",
        },
    )
    v2 = upload_bundle(
        client,
        workspace_id,
        project_id,
        token,
        None,
        {"README.md": b"# A\nalpha\n# C\ncharlie"},
        supersedes_resource_id=v1["resource"]["id"],
    )
    manifest = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{v2['resource']['id']}/manifest",
        headers=auth_headers(token),
    )
    assert manifest.status_code == 200, manifest.text
    body = manifest.json()
    assert body["section_count"] == 2
    assert body["sections_from_deleted_files_count"] == 1
    assert body["sections_absent_count"] == 2


@pytest.mark.skipif(not os.getenv("CONTEXTSMITH_RUN_REAL_INTEGRATION"), reason="requires real Postgres/Redis services")
def test_resource_map_compile_review_and_scope(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    require_real_services()
    monkeypatch.setenv("CONTEXTSMITH_WORK_DIR", str(tmp_path / "work"))
    client = TestClient(app)
    token, scope = login_admin(client, monkeypatch, "resource-map")
    workspace_id, project_id = scope.split(":")

    upload = upload_bundle(
        client,
        workspace_id,
        project_id,
        token,
        "Resource Map bundle",
        {
            "README.md": b"# Overview\nThis repo ships the compiler.\n# Operations\nRun tests before release.",
            "docs/runbook.md": b"# Runbook\nRestart workers only after queue drain.",
        },
    )
    resource_id = upload["resource"]["id"]

    compiled = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/context-artifacts/resource-map",
        headers=auth_headers(token),
    )
    assert compiled.status_code == 200, compiled.text
    artifact = compiled.json()
    assert artifact["artifact_type"] == "resource_map"
    assert artifact["status"] == "draft"
    assert artifact["coverage_json"]["source_count"] == 2
    assert artifact["coverage_json"]["citation_count"] >= 3
    assert artifact["sources"]
    assert artifact["citations"]
    assert {source["normalized_path"] for source in artifact["sources"]} == {"README.md", "docs/runbook.md"}

    listed = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/context-artifacts",
        headers=auth_headers(token),
        params={"artifact_type": "resource_map"},
    )
    assert listed.status_code == 200, listed.text
    assert listed.json()[0]["id"] == artifact["id"]
    assert listed.json()[0]["sources"] == []

    fetched = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-artifacts/{artifact['id']}",
        headers=auth_headers(token),
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["artifact_hash"] == artifact["artifact_hash"]

    idempotent = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/context-artifacts/resource-map",
        headers=auth_headers(token),
    )
    assert idempotent.status_code == 200, idempotent.text
    assert idempotent.json()["id"] == artifact["id"]

    read_token = client.post(
        f"/workspaces/{workspace_id}/api-tokens",
        headers=auth_headers(token),
        json={
            "name": "Resource Map read token",
            "scopes": ["resource:read"],
            "allowed_project_ids": [project_id],
            "allowed_resource_ids": [resource_id],
        },
    )
    assert read_token.status_code == 201, read_token.text
    read_headers = auth_headers(read_token.json()["token"])
    scoped_list = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/context-artifacts",
        headers=read_headers,
    )
    assert scoped_list.status_code == 200, scoped_list.text
    denied_compile = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/context-artifacts/resource-map",
        headers=read_headers,
    )
    assert denied_compile.status_code == 403

    viewer_email = f"viewer-{int(time.time() * 1000)}@contextsmith.local"
    viewer_password = "viewer-password-123"
    viewer = client.post(
        f"/workspaces/{workspace_id}/members",
        headers=auth_headers(token),
        json={"email": viewer_email, "display_name": "Viewer", "password": viewer_password, "role": "viewer"},
    )
    assert viewer.status_code == 201, viewer.text
    viewer_login = client.post("/auth/login", json={"email": viewer_email, "password": viewer_password})
    assert viewer_login.status_code == 200, viewer_login.text
    viewer_headers = auth_headers(viewer_login.json()["session_token"])
    viewer_approve = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-artifacts/{artifact['id']}/approve",
        headers=viewer_headers,
        json={"acknowledge_warnings": True},
    )
    assert viewer_approve.status_code == 403
    viewer_reject = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-artifacts/{artifact['id']}/reject",
        headers=viewer_headers,
        json={"reason": "Viewer should not be allowed."},
    )
    assert viewer_reject.status_code == 403

    admin_reject = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-artifacts/{artifact['id']}/reject",
        headers=auth_headers(token),
        json={"reason": "Exercise force recompile after rejection."},
    )
    assert admin_reject.status_code == 200, admin_reject.text
    assert admin_reject.json()["status"] == "rejected"
    force_after_reject = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/context-artifacts/resource-map",
        headers=auth_headers(token),
        params={"force": "true"},
    )
    assert force_after_reject.status_code == 200, force_after_reject.text
    assert force_after_reject.json()["status"] == "draft"
    assert force_after_reject.json()["id"] != artifact["id"]
    artifact = force_after_reject.json()

    approved = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-artifacts/{artifact['id']}/approve",
        headers=auth_headers(token),
        json={"acknowledge_warnings": True, "comment": "Looks good."},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"

    approved_again = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/context-artifacts/resource-map",
        headers=auth_headers(token),
    )
    assert approved_again.status_code == 200, approved_again.text
    assert approved_again.json()["id"] == artifact["id"]
    assert approved_again.json()["status"] == "approved"


@pytest.mark.skipif(not os.getenv("CONTEXTSMITH_RUN_REAL_INTEGRATION"), reason="requires real Postgres/Redis services")
def test_resource_map_missing_snapshot_sections_fails_idempotently(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    require_real_services()
    monkeypatch.setenv("CONTEXTSMITH_WORK_DIR", str(tmp_path / "work"))
    client = TestClient(app)
    token, scope = login_admin(client, monkeypatch, "resource-map-corrupt")
    workspace_id, project_id = scope.split(":")
    upload = upload_bundle(
        client,
        workspace_id,
        project_id,
        token,
        "Corrupt Resource Map bundle",
        {"README.md": b"# Overview\nThis section will be removed from snapshot_sections."},
    )
    resource_id = upload["resource"]["id"]

    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM snapshot_sections WHERE version_resource_id = :resource_id"), {"resource_id": resource_id})

    first = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/context-artifacts/resource-map",
        headers=auth_headers(token),
    )
    assert first.status_code == 409, first.text
    second = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/context-artifacts/resource-map",
        headers=auth_headers(token),
    )
    assert second.status_code == 409, second.text
    assert "snapshot sections" in str(second.json()["detail"]).lower() or "sections" in str(second.json()["detail"]).lower()


@pytest.mark.skipif(not os.getenv("CONTEXTSMITH_RUN_REAL_INTEGRATION"), reason="requires real Postgres/Redis services")
def test_context_pack_publish_runtime_rollback_and_purge(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    require_real_services()
    monkeypatch.setenv("CONTEXTSMITH_WORK_DIR", str(tmp_path / "work"))
    client = TestClient(app)
    token, scope = login_admin(client, monkeypatch, "context-pack")
    workspace_id, project_id = scope.split(":")
    upload = upload_bundle(
        client,
        workspace_id,
        project_id,
        token,
        "B1 Context Pack bundle",
        {
            "README.md": b"# Overview\nPinned context pack content.\n# Operations\nPublished pack runtime should cite this snapshot.",
            "docs/runbook.md": b"# Runbook\nRollback and invalidation are explicit release operations.",
        },
    )
    resource_id = upload["resource"]["id"]
    artifact = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/context-artifacts/resource-map",
        headers=auth_headers(token),
    )
    assert artifact.status_code == 200, artifact.text
    artifact_id = artifact.json()["id"]
    approved = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-artifacts/{artifact_id}/approve",
        headers=auth_headers(token),
        json={"acknowledge_warnings": True, "comment": "Approve for B1 pack."},
    )
    assert approved.status_code == 200, approved.text

    draft = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions",
        headers=auth_headers(token),
        json={"title": "Default pack", "description": "B1 test", "artifact_ids": [artifact_id]},
    )
    assert draft.status_code == 201, draft.text
    assert draft.json()["status"] == "draft"
    assert draft.json()["coverage"][0]["resource_id"] == resource_id
    published = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions/{draft.json()['version']}/publish",
        headers=auth_headers(token),
        json={"comment": "Publish v1."},
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"

    current = client.get(f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/current", headers=auth_headers(token))
    assert current.status_code == 200, current.text
    assert current.json()["version"] == 1

    runtime = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
        headers=auth_headers(token),
        json={"query": "operations", "context_pack_key": "default", "top_k": 3},
    )
    assert runtime.status_code == 200, runtime.text
    runtime_body = runtime.json()
    assert runtime_body["context_pack_key"] == "default"
    assert runtime_body["context_pack_version"] == 1
    assert runtime_body["context_pack_snapshot_pin_enforced"] is True
    assert runtime_body["citations"]
    assert {citation["resource_id"] for citation in runtime_body["citations"]} == {resource_id}

    denied_token = client.post(
        f"/workspaces/{workspace_id}/api-tokens",
        headers=auth_headers(token),
        json={"name": "pack denied", "scopes": ["resource:read", "project:query"], "allowed_project_ids": [project_id], "allowed_resource_ids": []},
    )
    assert denied_token.status_code == 201, denied_token.text
    denied_current = client.get(f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/current", headers=auth_headers(denied_token.json()["token"]))
    assert denied_current.status_code == 404

    denied_review_token = client.post(
        f"/workspaces/{workspace_id}/api-tokens",
        headers=auth_headers(token),
        json={"name": "pack review denied", "scopes": ["resource:read", "project:query", "review:write"], "allowed_project_ids": [project_id], "allowed_resource_ids": []},
    )
    assert denied_review_token.status_code == 201, denied_review_token.text
    denied_invalidate = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions/{draft.json()['version']}/invalidate",
        headers=auth_headers(denied_review_token.json()["token"]),
        json={"reason": "should not invalidate denied resource coverage"},
    )
    assert denied_invalidate.status_code == 404

    viewer_email = f"pack-viewer-{int(time.time() * 1000)}@contextsmith.local"
    viewer_password = "viewer-password-123"
    viewer = client.post(
        f"/workspaces/{workspace_id}/members",
        headers=auth_headers(token),
        json={"email": viewer_email, "display_name": "Viewer", "password": viewer_password, "role": "viewer"},
    )
    assert viewer.status_code == 201, viewer.text
    viewer_login = client.post("/auth/login", json={"email": viewer_email, "password": viewer_password})
    assert viewer_login.status_code == 200, viewer_login.text
    denied_publish = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions/{draft.json()['version']}/publish",
        headers=auth_headers(viewer_login.json()["session_token"]),
        json={"comment": "viewer cannot publish"},
    )
    assert denied_publish.status_code == 403

    draft2 = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions",
        headers=auth_headers(token),
        json={"title": "Default pack", "description": "B1 test v2", "artifact_ids": [artifact_id]},
    )
    assert draft2.status_code == 201, draft2.text
    published2 = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions/{draft2.json()['version']}/publish",
        headers=auth_headers(token),
        json={"comment": "Publish v2."},
    )
    assert published2.status_code == 200, published2.text
    assert published2.json()["version"] == 2

    rollback = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions/1/rollback",
        headers=auth_headers(token),
        json={"reason": "Rollback test."},
    )
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["status"] == "published"
    assert rollback.json()["version"] == 1

    soft_delete = client.delete(f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}", headers=auth_headers(token))
    assert soft_delete.status_code == 204, soft_delete.text
    blocked_purge = client.post(f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/purge", headers=auth_headers(token))
    assert blocked_purge.status_code == 409
    assert "Context Pack" in str(blocked_purge.json()["detail"])

    invalidate_v1 = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions/1/invalidate",
        headers=auth_headers(token),
        json={"reason": "Allow purge."},
    )
    assert invalidate_v1.status_code == 200, invalidate_v1.text
    invalidate_v2 = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions/2/invalidate",
        headers=auth_headers(token),
        json={"reason": "Allow purge."},
    )
    assert invalidate_v2.status_code == 200, invalidate_v2.text
    purged = client.post(f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/purge", headers=auth_headers(token))
    assert purged.status_code == 200, purged.text


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


@pytest.mark.skipif(not os.getenv("CONTEXTSMITH_RUN_REAL_INTEGRATION"), reason="requires real Postgres/Redis services")
def test_skill_export_generation_approval_download_scope_and_purge(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    require_real_services()
    monkeypatch.setenv("CONTEXTSMITH_WORK_DIR", str(tmp_path / "work"))
    client = TestClient(app)
    token, scope = login_admin(client, monkeypatch, "skill-export")
    workspace_id, project_id = scope.split(":")
    upload = upload_bundle(
        client,
        workspace_id,
        project_id,
        token,
        "C Skill Export bundle",
        {
            "README.md": b"# Skill Export Source\nRuntime adapters must not copy this corpus sentence verbatim into package files.",
            "docs/runtime.md": b"# Runtime\nUse pinned ContextSmith context with citations.",
        },
    )
    resource_id = upload["resource"]["id"]
    artifact = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/context-artifacts/resource-map",
        headers=auth_headers(token),
    )
    assert artifact.status_code == 200, artifact.text
    artifact_id = artifact.json()["id"]
    approved_artifact = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-artifacts/{artifact_id}/approve",
        headers=auth_headers(token),
        json={"acknowledge_warnings": True, "comment": "Approve for C skill export."},
    )
    assert approved_artifact.status_code == 200, approved_artifact.text

    draft_pack = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions",
        headers=auth_headers(token),
        json={"title": "Default pack", "description": "C test", "artifact_ids": [artifact_id]},
    )
    assert draft_pack.status_code == 201, draft_pack.text
    draft_export = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions/{draft_pack.json()['version']}/skill-exports",
        headers=auth_headers(token),
        json={"title": "Should fail for draft pack"},
    )
    assert draft_export.status_code == 422

    published_pack = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions/{draft_pack.json()['version']}/publish",
        headers=auth_headers(token),
        json={"comment": "Publish for C export."},
    )
    assert published_pack.status_code == 200, published_pack.text

    leak_export = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions/{published_pack.json()['version']}/skill-exports",
        headers=auth_headers(token),
        json={"export_type": "hermes_skill", "title": "Leaky skill", "summary": "Runtime adapters must not copy this corpus sentence verbatim into package files."},
    )
    assert leak_export.status_code == 200, leak_export.text
    assert leak_export.json()["status"] == "failed"
    assert leak_export.json()["files"] == []
    assert leak_export.json()["leak_scan_json"]["ok"] is False
    leak_download = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{leak_export.json()['id']}/files/SKILL.md",
        headers=auth_headers(token),
    )
    assert leak_download.status_code == 403

    export = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions/{published_pack.json()['version']}/skill-exports",
        headers=auth_headers(token),
        json={"export_type": "hermes_skill", "title": "Default runtime skill", "summary": "Use pinned ContextSmith runtime context."},
    )
    assert export.status_code == 200, export.text
    export_body = export.json()
    assert export_body["status"] == "draft"
    assert export_body["package_hash"].startswith("sha256:")
    file_names = {file["path"] for file in export_body["files"]}
    assert {"SKILL.md", "README.md", "manifest.json"}.issubset(file_names)
    joined = "\n".join(file.get("content") or "" for file in export_body["files"])
    assert "contextsmith.get_agent_context" in joined
    assert "context_pack_key" in joined
    assert "context_pack_version" in joined
    assert "context_pack_snapshot_pin_enforced" in joined
    assert "Bearer " not in joined
    assert "cs_" not in joined
    assert "/home/" not in joined
    assert "Runtime adapters must not copy this corpus sentence" not in joined
    assert export_body["validation_json"]["ok"] is True
    assert export_body["leak_scan_json"]["ok"] is True

    repeated = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions/{published_pack.json()['version']}/skill-exports",
        headers=auth_headers(token),
        json={"export_type": "hermes_skill", "title": "Default runtime skill", "summary": "Use pinned ContextSmith runtime context."},
    )
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["id"] == export_body["id"]

    draft_download = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_body['id']}/files/SKILL.md",
        headers=auth_headers(token),
    )
    assert draft_download.status_code == 403

    denied_token = client.post(
        f"/workspaces/{workspace_id}/api-tokens",
        headers=auth_headers(token),
        json={"name": "skill export denied", "scopes": ["resource:read", "review:write"], "allowed_project_ids": [project_id], "allowed_resource_ids": []},
    )
    assert denied_token.status_code == 201, denied_token.text
    denied_get = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_body['id']}",
        headers=auth_headers(denied_token.json()["token"]),
    )
    assert denied_get.status_code == 404
    denied_generate = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions/{published_pack.json()['version']}/skill-exports",
        headers=auth_headers(denied_token.json()["token"]),
        json={"title": "Denied"},
    )
    assert denied_generate.status_code == 404

    approved_export = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_body['id']}/approve",
        headers=auth_headers(token),
        json={"comment": "Approved for runtime use."},
    )
    assert approved_export.status_code == 200, approved_export.text
    assert approved_export.json()["status"] == "approved"
    downloaded = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_body['id']}/files/SKILL.md",
        headers=auth_headers(token),
    )
    assert downloaded.status_code == 200, downloaded.text
    assert "Default runtime skill" in downloaded.text
    manifest_download = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_body['id']}/files/manifest.json",
        headers=auth_headers(token),
    )
    assert manifest_download.status_code == 200, manifest_download.text
    assert '"export_status":"approved"' in manifest_download.text
    assert '"approval"' in manifest_download.text
    traversal = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_body['id']}/files/../SKILL.md",
        headers=auth_headers(token),
    )
    assert traversal.status_code in {400, 404}

    soft_delete = client.delete(f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}", headers=auth_headers(token))
    assert soft_delete.status_code == 204, soft_delete.text
    blocked_by_pack = client.post(f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/purge", headers=auth_headers(token))
    assert blocked_by_pack.status_code == 409
    invalidate_pack = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions/{published_pack.json()['version']}/invalidate",
        headers=auth_headers(token),
        json={"reason": "Allow skill export purge test."},
    )
    assert invalidate_pack.status_code == 200, invalidate_pack.text
    blocked_by_export = client.post(f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/purge", headers=auth_headers(token))
    assert blocked_by_export.status_code == 409
    assert "skill export" in str(blocked_by_export.json()["detail"]).lower()
    invalidated_export = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/skill-exports/{export_body['id']}/invalidate",
        headers=auth_headers(token),
        json={"reason": "Scrub export for purge."},
    )
    assert invalidated_export.status_code == 200, invalidated_export.text
    assert invalidated_export.json()["status"] == "invalidated"
    assert invalidated_export.json()["files"] == []
    purged = client.post(f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/purge", headers=auth_headers(token))
    assert purged.status_code == 200, purged.text


@pytest.mark.skipif(not os.getenv("CONTEXTSMITH_RUN_REAL_INTEGRATION"), reason="requires real Postgres/Redis services")
def test_repo_agent_v0_draft_publish_archive_scrub_lifecycle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    require_real_services()
    monkeypatch.setenv("CONTEXTSMITH_WORK_DIR", str(tmp_path / "work"))
    client = TestClient(app)
    token, scope = login_admin(client, monkeypatch, "repo-agent")
    workspace_id, project_id = scope.split(":")
    monkeypatch.setenv("CONTEXTSMITH_ALLOW_LOCAL_GIT", "true")
    repo_dir = tmp_path / "repo-agent-fixture"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("# Repo Agent\nThis repo has runtime instructions.\n", encoding="utf-8")
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "app.py").write_text("print('hello repo agent')\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "agent@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Agent Test"], cwd=repo_dir, check=True)
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, check=True, capture_output=True)
    created_resource = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources",
        headers=auth_headers(token),
        json={"type": "git", "name": "D Repo Agent bundle", "uri": str(repo_dir), "source_config": {"url": str(repo_dir), "branch": "main"}},
    )
    assert created_resource.status_code == 201, created_resource.text
    resource_id = created_resource.json()["id"]
    zero_resource = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources",
        headers=auth_headers(token),
        json={"type": "git", "name": "D zero-version repo agent", "uri": str(repo_dir), "source_config": {"url": str(repo_dir), "branch": "main"}},
    )
    assert zero_resource.status_code == 201, zero_resource.text
    zero_resource_id = zero_resource.json()["id"]
    zero_agent = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{zero_resource_id}/repo-agent",
        headers=auth_headers(token),
        json={"agent_key": "zero-version-fixture", "pack_key": "default", "title": "Zero Version Agent"},
    )
    assert zero_agent.status_code == 200, zero_agent.text
    zero_delete = client.delete(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{zero_resource_id}",
        headers=auth_headers(token),
    )
    assert zero_delete.status_code == 204, zero_delete.text
    zero_purge_blocked = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{zero_resource_id}/purge",
        headers=auth_headers(token),
    )
    assert zero_purge_blocked.status_code == 409
    zero_archive = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/repo-agents/zero-version-fixture/archive",
        headers=auth_headers(token),
        json={"comment": "Archive zero-version agent before purge."},
    )
    assert zero_archive.status_code == 200, zero_archive.text
    assert zero_archive.json()["resource_id"] is None
    zero_purge = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{zero_resource_id}/purge",
        headers=auth_headers(token),
    )
    assert zero_purge.status_code == 200, zero_purge.text
    index_run = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/refresh",
        headers=auth_headers(token),
    )
    assert index_run.status_code == 202, index_run.text
    run_index(index_run.json()["id"])
    artifact = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/context-artifacts/resource-map",
        headers=auth_headers(token),
    )
    assert artifact.status_code == 200, artifact.text
    artifact_id = artifact.json()["id"]
    approved_artifact = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-artifacts/{artifact_id}/approve",
        headers=auth_headers(token),
        json={"acknowledge_warnings": True, "comment": "Approve for D repo agent."},
    )
    assert approved_artifact.status_code == 200, approved_artifact.text
    draft_pack = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions",
        headers=auth_headers(token),
        json={"title": "Default repo-agent pack", "description": "D test", "artifact_ids": [artifact_id]},
    )
    assert draft_pack.status_code == 201, draft_pack.text
    published_pack = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions/{draft_pack.json()['version']}/publish",
        headers=auth_headers(token),
        json={"comment": "Publish for D repo agent."},
    )
    assert published_pack.status_code == 200, published_pack.text

    created = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/repo-agent",
        headers=auth_headers(token),
        json={"agent_key": "repo-agent-fixture", "pack_key": "default", "title": "Repo Agent Fixture"},
    )
    assert created.status_code == 200, created.text
    assert created.json()["agent_key"] == "repo-agent-fixture"
    reserved_key = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/repo-agent",
        headers=auth_headers(token),
        json={"agent_key": "new", "pack_key": "default", "title": "Reserved"},
    )
    assert reserved_key.status_code == 422
    duplicate = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/repo-agent",
        headers=auth_headers(token),
        json={"agent_key": "repo-agent-fixture", "pack_key": "default", "title": "Duplicate"},
    )
    assert duplicate.status_code == 409
    refresh = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/repo-agents/repo-agent-fixture/refresh",
        headers=auth_headers(token),
    )
    assert refresh.status_code == 200, refresh.text
    assert refresh.json()["version"]["status"] == "draft"
    assert refresh.json()["version"]["validation_json"]["ok"] is True
    assert refresh.json()["version"]["skill_export_id"] is None
    repeated_refresh = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/repo-agents/repo-agent-fixture/refresh",
        headers=auth_headers(token),
    )
    assert repeated_refresh.status_code == 200, repeated_refresh.text
    assert repeated_refresh.json()["unchanged"] is True

    allowed_token = client.post(
        f"/workspaces/{workspace_id}/api-tokens",
        headers=auth_headers(token),
        json={"name": "repo agent reader", "scopes": ["resource:read", "review:write"], "allowed_project_ids": [project_id], "allowed_resource_ids": [resource_id]},
    )
    assert allowed_token.status_code == 201, allowed_token.text
    allowed_get = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/repo-agents/repo-agent-fixture",
        headers=auth_headers(allowed_token.json()["token"]),
    )
    assert allowed_get.status_code == 200, allowed_get.text
    denied_publish = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/repo-agents/repo-agent-fixture/versions/{refresh.json()['version']['version']}/publish",
        headers=auth_headers(allowed_token.json()["token"]),
        json={"comment": "resource scoped tokens must not publish"},
    )
    assert denied_publish.status_code == 403

    invalidate_pack = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions/{published_pack.json()['version']}/invalidate",
        headers=auth_headers(token),
        json={"reason": "Invalidate dependency before stale draft publish."},
    )
    assert invalidate_pack.status_code == 200, invalidate_pack.text
    stale_publish = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/repo-agents/repo-agent-fixture/versions/{refresh.json()['version']['version']}/publish",
        headers=auth_headers(token),
        json={"comment": "This stale draft must not publish."},
    )
    assert stale_publish.status_code == 422
    replacement_pack = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions",
        headers=auth_headers(token),
        json={"title": "Replacement repo-agent pack", "description": "D test", "artifact_ids": [artifact_id]},
    )
    assert replacement_pack.status_code == 201, replacement_pack.text
    replacement_published = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packs/default/versions/{replacement_pack.json()['version']}/publish",
        headers=auth_headers(token),
        json={"comment": "Replacement publish for D repo agent."},
    )
    assert replacement_published.status_code == 200, replacement_published.text
    refresh = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/repo-agents/repo-agent-fixture/refresh",
        headers=auth_headers(token),
    )
    assert refresh.status_code == 200, refresh.text
    assert refresh.json()["version"]["validation_json"]["ok"] is True

    published = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/repo-agents/repo-agent-fixture/versions/{refresh.json()['version']['version']}/publish",
        headers=auth_headers(token),
        json={"comment": "Publish D repo agent."},
    )
    assert published.status_code == 200, published.text
    current = published.json()["current"]
    assert current["status"] == "published"
    assert current["install_json"]["mode"] == "pack_only"

    rollback = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/repo-agents/repo-agent-fixture/versions/{current['version']}/rollback-draft",
        headers=auth_headers(token),
        json={"comment": "Create rollback draft."},
    )
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["version"]["rollback_from_version_id"] == current["id"]

    archive = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/repo-agents/repo-agent-fixture/archive",
        headers=auth_headers(token),
        json={"comment": "Archive for purge."},
    )
    assert archive.status_code == 200, archive.text
    assert archive.json()["status"] == "archived"
    refresh_archived = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/repo-agents/repo-agent-fixture/refresh",
        headers=auth_headers(token),
    )
    assert refresh_archived.status_code == 422
    invalidate_current = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/repo-agents/repo-agent-fixture/versions/{current['version']}/invalidate",
        headers=auth_headers(token),
        json={"comment": "Invalidate archived current."},
    )
    assert invalidate_current.status_code == 200, invalidate_current.text
    assert invalidate_current.json()["current_version_id"] is None
    scrub = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/repo-agents/repo-agent-fixture/versions/{current['version']}/scrub",
        headers=auth_headers(token),
        json={"comment": "Scrub archived current."},
    )
    assert scrub.status_code == 200, scrub.text
    scrubbed_version = next(version for version in scrub.json()["versions"] if version["version"] == current["version"])
    assert scrubbed_version["resource_id"] is None
    assert scrubbed_version["summary_json"]["scrubbed"] is True
    latest_agent = scrub.json()
    for retained in list(latest_agent["versions"]):
        if retained["resource_id"] is None:
            continue
        if retained["status"] != "invalidated":
            invalidate_retained = client.post(
                f"/workspaces/{workspace_id}/projects/{project_id}/repo-agents/repo-agent-fixture/versions/{retained['version']}/invalidate",
                headers=auth_headers(token),
                json={"comment": f"Invalidate retained v{retained['version']} before tombstone."},
            )
            assert invalidate_retained.status_code == 200, invalidate_retained.text
        scrub_retained = client.post(
            f"/workspaces/{workspace_id}/projects/{project_id}/repo-agents/repo-agent-fixture/versions/{retained['version']}/scrub",
            headers=auth_headers(token),
            json={"comment": f"Scrub retained v{retained['version']}."},
        )
        assert scrub_retained.status_code == 200, scrub_retained.text
        latest_agent = scrub_retained.json()
    assert latest_agent["resource_id"] is None
    tombstone_get = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/repo-agents/repo-agent-fixture",
        headers=auth_headers(allowed_token.json()["token"]),
    )
    assert tombstone_get.status_code == 404


@pytest.mark.skipif(not os.getenv("CONTEXTSMITH_RUN_REAL_INTEGRATION"), reason="requires real Postgres/Redis services")
def test_graph_version_storage_e0_lifecycle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    require_real_services()
    monkeypatch.setenv("CONTEXTSMITH_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("CONTEXTSMITH_ALLOW_LOCAL_GIT", "true")
    client = TestClient(app)
    token, scope = login_admin(client, monkeypatch, "graph-version")
    workspace_id, project_id = scope.split(":")

    repo_dir = tmp_path / "graph-fixture"
    repo_dir.mkdir()
    (repo_dir / "README.md").write_text("# Graph Fixture\nInitial graph fixture.\n", encoding="utf-8")
    (repo_dir / "src").mkdir()
    (repo_dir / "src" / "app.py").write_text("def main():\n    return 'graph-v1'\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "graph@example.com"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.name", "Graph Test"], cwd=repo_dir, check=True)
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, check=True, capture_output=True)

    created_resource = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources",
        headers=auth_headers(token),
        json={"type": "git", "name": "Graph Fixture", "uri": str(repo_dir), "source_config": {"url": str(repo_dir), "branch": "main"}},
    )
    assert created_resource.status_code == 201, created_resource.text
    resource_id = created_resource.json()["id"]
    index_run = client.post(f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/refresh", headers=auth_headers(token))
    assert index_run.status_code == 202, index_run.text
    run_index(index_run.json()["id"])

    compatible_graph = client.get(f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/graph", headers=auth_headers(token))
    assert compatible_graph.status_code == 200, compatible_graph.text
    compile_v1 = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/graph/versions",
        headers=auth_headers(token),
        json={"graph_key": "graph-fixture-graph", "title": "Graph Fixture Graph"},
    )
    assert compile_v1.status_code == 200, compile_v1.text
    assert compile_v1.json()["version"]["status"] == "draft"
    assert compile_v1.json()["version"]["validation_json"]["ok"] is True
    assert compile_v1.json()["graph"]["graph_key"] == "graph-fixture-graph"
    compile_same = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/graph/versions",
        headers=auth_headers(token),
        json={"graph_key": "graph-fixture-graph", "title": "Graph Fixture Graph"},
    )
    assert compile_same.status_code == 200, compile_same.text
    assert compile_same.json()["unchanged"] is True

    allowed_token = client.post(
        f"/workspaces/{workspace_id}/api-tokens",
        headers=auth_headers(token),
        json={"name": "graph scoped reader", "scopes": ["resource:read", "review:write"], "allowed_project_ids": [project_id], "allowed_resource_ids": [resource_id]},
    )
    assert allowed_token.status_code == 201, allowed_token.text
    allowed_graph = client.get(f"/workspaces/{workspace_id}/projects/{project_id}/graphs/graph-fixture-graph", headers=auth_headers(allowed_token.json()["token"]))
    assert allowed_graph.status_code == 200, allowed_graph.text
    denied_publish = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/graphs/graph-fixture-graph/versions/{compile_v1.json()['version']['version']}/publish",
        headers=auth_headers(allowed_token.json()["token"]),
        json={"comment": "resource-scoped token must not publish"},
    )
    assert denied_publish.status_code == 403

    published_v1 = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/graphs/graph-fixture-graph/versions/{compile_v1.json()['version']['version']}/publish",
        headers=auth_headers(token),
        json={"comment": "Publish graph v1."},
    )
    assert published_v1.status_code == 200, published_v1.text
    assert published_v1.json()["current"]["status"] == "published"

    (repo_dir / "src" / "app.py").write_text("def main():\n    return 'graph-v2'\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "second"], cwd=repo_dir, check=True, capture_output=True)
    second_run = client.post(f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/refresh", headers=auth_headers(token))
    assert second_run.status_code == 202, second_run.text
    run_index(second_run.json()["id"])
    compile_v2 = client.post(f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/graph/versions", headers=auth_headers(token), json={})
    assert compile_v2.status_code == 200, compile_v2.text
    assert compile_v2.json()["version"]["version_hash"] != compile_v1.json()["version"]["version_hash"]

    (repo_dir / "README.md").write_text("# Graph Fixture\nThird graph fixture.\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "third"], cwd=repo_dir, check=True, capture_output=True)
    third_run = client.post(f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/refresh", headers=auth_headers(token))
    assert third_run.status_code == 202, third_run.text
    run_index(third_run.json()["id"])
    stale_publish = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/graphs/graph-fixture-graph/versions/{compile_v2.json()['version']['version']}/publish",
        headers=auth_headers(token),
        json={"comment": "This stale draft must fail."},
    )
    assert stale_publish.status_code == 422
    compile_v3 = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/graph/versions",
        headers=auth_headers(token),
        json={},
    )
    assert compile_v3.status_code == 200, compile_v3.text

    delete_resource_response = client.delete(f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}", headers=auth_headers(token))
    assert delete_resource_response.status_code == 204, delete_resource_response.text
    deleted_publish = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/graphs/graph-fixture-graph/versions/{compile_v3.json()['version']['version']}/publish",
        headers=auth_headers(token),
        json={"comment": "This deleted-resource draft must fail."},
    )
    assert deleted_publish.status_code == 422
    assert "deleted or archived" in deleted_publish.text
    purge_blocked = client.post(f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/purge", headers=auth_headers(token))
    assert purge_blocked.status_code == 409
    assert "graphs" in purge_blocked.json()["detail"]


@pytest.mark.skipif(not os.getenv("CONTEXTSMITH_RUN_REAL_INTEGRATION"), reason="requires real Postgres/Redis services")
def test_graph_merge_e1_lifecycle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    require_real_services()
    monkeypatch.setenv("CONTEXTSMITH_WORK_DIR", str(tmp_path / "work"))
    monkeypatch.setenv("CONTEXTSMITH_ALLOW_LOCAL_GIT", "true")
    client = TestClient(app)
    token, scope = login_admin(client, monkeypatch, "graph-merge")
    workspace_id, project_id = scope.split(":")

    def make_repo(name: str, ret: str) -> Path:
        repo_dir = tmp_path / name
        repo_dir.mkdir()
        (repo_dir / "README.md").write_text(f"# Shared Guide\n{name}\n", encoding="utf-8")
        (repo_dir / "src").mkdir()
        (repo_dir / "src" / "common.py").write_text(f"def main():\n    return {ret!r}\n", encoding="utf-8")
        subprocess.run(["git", "init", "-b", "main"], cwd=repo_dir, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", f"{name}@example.com"], cwd=repo_dir, check=True)
        subprocess.run(["git", "config", "user.name", name], cwd=repo_dir, check=True)
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
        subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, check=True, capture_output=True)
        return repo_dir

    def create_git_resource(name: str, repo_dir: Path) -> str:
        created = client.post(
            f"/workspaces/{workspace_id}/projects/{project_id}/resources",
            headers=auth_headers(token),
            json={"type": "git", "name": name, "uri": str(repo_dir), "source_config": {"url": str(repo_dir), "branch": "main"}},
        )
        assert created.status_code == 201, created.text
        resource_id = created.json()["id"]
        refresh = client.post(f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/refresh", headers=auth_headers(token))
        assert refresh.status_code == 202, refresh.text
        run_index(refresh.json()["id"])
        return resource_id

    def publish_resource_graph(resource_id: str, graph_key: str, title: str) -> dict:
        compiled = client.post(
            f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/graph/versions",
            headers=auth_headers(token),
            json={"graph_key": graph_key, "title": title},
        )
        assert compiled.status_code == 200, compiled.text
        published = client.post(
            f"/workspaces/{workspace_id}/projects/{project_id}/graphs/{graph_key}/versions/{compiled.json()['version']['version']}/publish",
            headers=auth_headers(token),
            json={"comment": f"Publish {graph_key}"},
        )
        assert published.status_code == 200, published.text
        return published.json()["current"]

    repo_a = make_repo("merge-a", "a")
    repo_b = make_repo("merge-b", "b")
    resource_a = create_git_resource("Merge A", repo_a)
    resource_b = create_git_resource("Merge B", repo_b)
    graph_a_v1 = publish_resource_graph(resource_a, "merge-a-graph", "Merge A Graph")
    graph_b_v1 = publish_resource_graph(resource_b, "merge-b-graph", "Merge B Graph")

    monkeypatch.setenv("CONTEXTSMITH_GRAPH_MERGE_MAX_INPUTS", "1")
    too_many = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/graph-merges",
        headers=auth_headers(token),
        json={"title": "Too many", "strategy": "union", "inputs": [{"graph_key": "merge-a-graph", "version": graph_a_v1["version"]}, {"graph_key": "merge-b-graph", "version": graph_b_v1["version"]}]},
    )
    assert too_many.status_code == 422
    assert "too_many_inputs" in too_many.text
    monkeypatch.setenv("CONTEXTSMITH_GRAPH_MERGE_MAX_INPUTS", "8")
    monkeypatch.setenv("CONTEXTSMITH_GRAPH_MERGE_MAX_NODES", "1")
    too_large = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/graph-merges",
        headers=auth_headers(token),
        json={"title": "Too large", "strategy": "union", "inputs": [{"graph_key": "merge-a-graph", "version": graph_a_v1["version"]}, {"graph_key": "merge-b-graph", "version": graph_b_v1["version"]}]},
    )
    assert too_large.status_code == 413
    assert "merge_node_limit_exceeded" in too_large.text
    monkeypatch.setenv("CONTEXTSMITH_GRAPH_MERGE_MAX_NODES", "10000")

    compiled_merge = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/graph-merges",
        headers=auth_headers(token),
        json={"merge_key": "merge-fixture", "title": "Merge Fixture", "strategy": "overlay", "inputs": [{"graph_key": "merge-a-graph", "version": graph_a_v1["version"]}, {"graph_key": "merge-b-graph", "version": graph_b_v1["version"]}]},
    )
    assert compiled_merge.status_code == 200, compiled_merge.text
    merge = compiled_merge.json()
    latest = merge["versions"][0]
    merge_key = merge["merge_key"]
    assert latest["status"] == "draft"
    assert latest["node_count"] >= graph_a_v1["node_count"] + graph_b_v1["node_count"]
    assert latest["candidate_count"] >= 1

    scoped = client.post(
        f"/workspaces/{workspace_id}/api-tokens",
        headers=auth_headers(token),
        json={"name": "merge scoped reader", "scopes": ["resource:read"], "allowed_project_ids": [project_id], "allowed_resource_ids": [resource_a]},
    )
    assert scoped.status_code == 201, scoped.text
    hidden_merge = client.get(f"/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}", headers=auth_headers(scoped.json()["token"]))
    assert hidden_merge.status_code == 404

    blocked_publish = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/versions/{latest['version']}/publish",
        headers=auth_headers(token),
        json={"comment": "Publish should block unresolved candidates."},
    )
    assert blocked_publish.status_code == 422
    assert "unresolved" in blocked_publish.text

    candidates = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/versions/{latest['version']}/data",
        headers=auth_headers(token),
        params={"kind": "candidates", "limit": 1},
    )
    assert candidates.status_code == 200, candidates.text
    assert candidates.json()["next_cursor"] is not None
    candidate_page_2 = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/versions/{latest['version']}/data",
        headers=auth_headers(token),
        params={"kind": "candidates", "limit": 1, "cursor": candidates.json()["next_cursor"]},
    )
    assert candidate_page_2.status_code == 200, candidate_page_2.text
    inputs_data = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/versions/{latest['version']}/data",
        headers=auth_headers(token),
        params={"kind": "inputs"},
    )
    assert inputs_data.status_code == 200, inputs_data.text
    assert {row["resource_name"] for row in inputs_data.json()["items"]} == {"Merge A", "Merge B"}
    candidate_key = candidates.json()["items"][0]["candidate_key"]
    reviewed = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/versions/{latest['version']}/candidates/{candidate_key}/review",
        headers=auth_headers(token),
        json={"status": "rejected", "reason": "Same path is not enough for semantic equivalence."},
    )
    assert reviewed.status_code == 200, reviewed.text

    published_merge = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/versions/{latest['version']}/publish",
        headers=auth_headers(token),
        json={"comment": "Publish merge fixture with reviewed candidate; acknowledge unresolved candidate risk.", "allow_unresolved_candidates": True},
    )
    assert published_merge.status_code == 200, published_merge.text
    assert published_merge.json()["current"]["status"] == "published"

    nodes = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/versions/{latest['version']}/data",
        headers=auth_headers(token),
        params={"kind": "nodes", "limit": 10},
    )
    assert nodes.status_code == 200, nodes.text
    first_node = nodes.json()["items"][0]["key"]
    path = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/versions/{latest['version']}/path",
        headers=auth_headers(token),
        params={"from_node_key": first_node, "to_node_key": first_node, "max_depth": 4},
    )
    assert path.status_code == 200, path.text
    assert path.json()["found"] is True
    too_deep = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{merge_key}/versions/{latest['version']}/path",
        headers=auth_headers(token),
        params={"from_node_key": first_node, "to_node_key": first_node, "max_depth": 99},
    )
    assert too_deep.status_code == 422

    (repo_a / "src" / "common.py").write_text("def main():\n    return 'a2'\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo_a, check=True)
    subprocess.run(["git", "commit", "-m", "second"], cwd=repo_a, check=True, capture_output=True)
    refresh_a2 = client.post(f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_a}/refresh", headers=auth_headers(token))
    assert refresh_a2.status_code == 202, refresh_a2.text
    run_index(refresh_a2.json()["id"])
    graph_a_v2_draft = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_a}/graph/versions",
        headers=auth_headers(token),
        json={"graph_key": "merge-a-graph", "title": "Merge A Graph"},
    )
    assert graph_a_v2_draft.status_code == 200, graph_a_v2_draft.text

    stale_draft = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/graph-merges",
        headers=auth_headers(token),
        json={"merge_key": "merge-stale-fixture", "title": "Merge Stale Fixture", "strategy": "union", "inputs": [{"graph_key": "merge-a-graph", "version": graph_a_v1["version"]}, {"graph_key": "merge-b-graph", "version": graph_b_v1["version"]}]},
    )
    assert stale_draft.status_code == 200, stale_draft.text
    stale_merge_key = stale_draft.json()["merge_key"]
    stale_version = stale_draft.json()["versions"][0]["version"]
    graph_a_v2 = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/graphs/merge-a-graph/versions/{graph_a_v2_draft.json()['version']['version']}/publish",
        headers=auth_headers(token),
        json={"comment": "Publish merge-a v2."},
    )
    assert graph_a_v2.status_code == 200, graph_a_v2.text
    assert graph_a_v2.json()["current"]["version"] > graph_a_v1["version"]
    stale_publish = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/graph-merges/{stale_merge_key}/versions/{stale_version}/publish",
        headers=auth_headers(token),
        json={"comment": "This stale merge draft should fail; acknowledge unresolved candidate risk.", "allow_unresolved_candidates": True},
    )
    assert stale_publish.status_code == 422
    assert "stale" in stale_publish.text

    deleted = client.delete(f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_a}", headers=auth_headers(token))
    assert deleted.status_code == 204, deleted.text
    purge_blocked = client.post(f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_a}/purge", headers=auth_headers(token))
    assert purge_blocked.status_code == 409
    assert "graph_merges" in purge_blocked.json()["detail"]
