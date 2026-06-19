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
