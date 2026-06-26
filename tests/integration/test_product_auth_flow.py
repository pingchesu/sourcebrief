from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import text

from sourcebrief_api.main import _bootstrap_default_admin, app
from sourcebrief_shared.config import get_settings
from sourcebrief_shared.db import get_engine

pytestmark = pytest.mark.integration


def require_real_services() -> None:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("select 1"))
        Redis.from_url(get_settings().redis_url).ping()
    except Exception as exc:  # pragma: no cover - diagnostic path
        pytest.skip(f"real Postgres/Redis services are not available: {exc}")


def bootstrap_case(monkeypatch: pytest.MonkeyPatch, prefix: str) -> tuple[str, str, str]:
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
    return email, password, suffix


def login_admin(client: TestClient, monkeypatch: pytest.MonkeyPatch, prefix: str) -> tuple[str, str, str, str]:
    email, password, _ = bootstrap_case(monkeypatch, prefix)
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return email, login.json()["session_token"], login.json()["default_workspace_id"], login.json()["default_project_id"]


def test_bootstrap_admin_login_and_create_second_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    require_real_services()
    client = TestClient(app)
    email, token, workspace_id, _ = login_admin(client, monkeypatch, "auth-admin")

    second_email = email.replace("auth-admin", "auth-second-admin")
    created = client.post(
        f"/workspaces/{workspace_id}/members",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": second_email, "password": "second-admin-password", "role": "admin"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["role"] == "admin"

    second_login = client.post("/auth/login", json={"email": second_email, "password": "second-admin-password"})
    assert second_login.status_code == 200, second_login.text
    assert second_login.json()["memberships"][0]["role"] == "admin"


def test_reserved_web_session_prefix_cannot_create_api_token(monkeypatch: pytest.MonkeyPatch) -> None:
    require_real_services()
    client = TestClient(app)
    email, token, workspace_id, _ = login_admin(client, monkeypatch, "auth-token")

    response = client.post(
        f"/workspaces/{workspace_id}/api-tokens",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": f"Web session for {email}", "scopes": ["project:read"]},
    )
    assert response.status_code == 422

    listed = client.get(f"/workspaces/{workspace_id}/api-tokens", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200, listed.text
    assert all(not item["name"].startswith("Web session for ") for item in listed.json())


def test_session_can_create_project_in_new_workspace_without_widening_api_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    require_real_services()
    client = TestClient(app)
    _, session_token, default_workspace_id, _ = login_admin(client, monkeypatch, "auth-workspace-refresh")
    session_headers = {"Authorization": f"Bearer {session_token}"}
    suffix = int(time.time() * 1000)

    created_workspace = client.post(
        "/workspaces",
        headers=session_headers,
        json={"name": f"Clean E2E Workspace {suffix}", "slug": f"clean-e2e-{suffix}"},
    )
    assert created_workspace.status_code == 201, created_workspace.text
    workspace_id = created_workspace.json()["id"]

    created_project = client.post(
        f"/workspaces/{workspace_id}/projects",
        headers=session_headers,
        json={"name": f"Clean E2E Project {suffix}", "description": "same-session workspace smoke"},
    )
    assert created_project.status_code == 201, created_project.text
    project_id = created_project.json()["id"]

    workspaces = client.get("/workspaces", headers=session_headers)
    assert workspaces.status_code == 200, workspaces.text
    assert workspace_id in {workspace["id"] for workspace in workspaces.json()}

    projects = client.get(f"/workspaces/{workspace_id}/projects", headers=session_headers)
    assert projects.status_code == 200, projects.text
    assert project_id in {project["id"] for project in projects.json()}

    scoped_token = client.post(
        f"/workspaces/{default_workspace_id}/api-tokens",
        headers=session_headers,
        json={"name": f"default workspace reader {suffix}", "scopes": ["project:read"]},
    )
    assert scoped_token.status_code == 201, scoped_token.text
    token_headers = {"Authorization": f"Bearer {scoped_token.json()['token']}"}

    denied = client.get(f"/workspaces/{workspace_id}/projects", headers=token_headers)
    assert denied.status_code == 404


def test_member_upsert_cannot_remove_final_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    require_real_services()
    client = TestClient(app)
    email, token, workspace_id, _ = login_admin(client, monkeypatch, "auth-last-admin")

    response = client.post(
        f"/workspaces/{workspace_id}/members",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": email, "role": "viewer"},
    )
    assert response.status_code == 422


def test_admin_members_must_have_password(monkeypatch: pytest.MonkeyPatch) -> None:
    require_real_services()
    client = TestClient(app)
    email, token, workspace_id, _ = login_admin(client, monkeypatch, "auth-password-admin")

    response = client.post(
        f"/workspaces/{workspace_id}/members",
        headers={"Authorization": f"Bearer {token}"},
        json={"email": email.replace("auth-password-admin", "auth-passwordless"), "role": "admin"},
    )
    assert response.status_code == 422


def test_viewer_session_cannot_write_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    require_real_services()
    client = TestClient(app)
    email, admin_token, workspace_id, project_id = login_admin(client, monkeypatch, "auth-viewer")
    viewer_email = email.replace("auth-viewer", "auth-viewer-user")
    viewer_password = "viewer-password"
    created = client.post(
        f"/workspaces/{workspace_id}/members",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"email": viewer_email, "password": viewer_password, "role": "viewer"},
    )
    assert created.status_code == 201, created.text
    viewer_login = client.post("/auth/login", json={"email": viewer_email, "password": viewer_password})
    assert viewer_login.status_code == 200, viewer_login.text
    viewer_token = viewer_login.json()["session_token"]

    denied = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={"type": "markdown", "name": "Viewer write", "uri": "viewer-write", "source_config": {"content": "no"}},
    )
    assert denied.status_code == 403


def test_api_token_cannot_read_account_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    require_real_services()
    client = TestClient(app)
    _, session_token, workspace_id, _ = login_admin(client, monkeypatch, "auth-api-me")
    created = client.post(
        f"/workspaces/{workspace_id}/api-tokens",
        headers={"Authorization": f"Bearer {session_token}"},
        json={"name": "integration token", "scopes": ["project:read"]},
    )
    assert created.status_code == 201, created.text
    api_token = created.json()["token"]
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {api_token}"})
    assert response.status_code == 403
