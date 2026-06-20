from __future__ import annotations

import os
import subprocess
import time
import uuid
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy import text

from sourcebrief_api.main import app
from sourcebrief_shared.config import get_settings
from sourcebrief_shared.db import get_engine, get_sessionmaker
from sourcebrief_shared.models import IndexRun
from sourcebrief_worker.jobs import run_index

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
        json={"name": f"Project {stamp}", "description": "m4"},
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


def create_token(client: TestClient, workspace_id: str, headers: dict[str, str], scopes: list[str], allowed_resource_ids: list[str] | None = None) -> dict[str, str]:
    payload: dict = {"name": f"agent-card-token-{uuid.uuid4().hex[:8]}", "scopes": scopes}
    if allowed_resource_ids is not None:
        payload["allowed_resource_ids"] = allowed_resource_ids
    response = client.post(f"/workspaces/{workspace_id}/api-tokens", json=payload, headers=headers)
    assert response.status_code == 201, response.text
    result = response.json()
    token_headers = {"Authorization": f"Bearer {result['token']}"}
    if "review:write" in scopes:
        token_headers["X-User-Email"] = headers["X-User-Email"]
    return token_headers


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


def build_code_repo(path: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "qa",
        "GIT_AUTHOR_EMAIL": "qa@example.com",
        "GIT_COMMITTER_NAME": "qa",
        "GIT_COMMITTER_EMAIL": "qa@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", path], env=env, check=True)
    os.makedirs(os.path.join(path, "src"), exist_ok=True)
    with open(os.path.join(path, "src", "checkout.py"), "w", encoding="utf-8") as fh:
        fh.write(
            "class CheckoutService:\n"
            "    pass\n\n"
            "def reconcile_cart(total):\n"
            "    return total\n"
        )
    with open(os.path.join(path, "src", "ui.ts"), "w", encoding="utf-8") as fh:
        fh.write("export function renderCheckout() { return true; }\n")
    with open(os.path.join(path, "main.py"), "w", encoding="utf-8") as fh:
        fh.write("from src.checkout import reconcile_cart\n")
    with open(os.path.join(path, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("# Code Repo\n\nRunbook marker checkoutrepo42. The reconcile_cart function is the checkout entrypoint.\n")
    with open(os.path.join(path, "pyproject.toml"), "w", encoding="utf-8") as fh:
        fh.write("[project]\nname = 'code-repo'\n")
    subprocess.run(["git", "-C", path, "add", "-A"], env=env, check=True)
    subprocess.run(["git", "-C", path, "commit", "-q", "-m", "code symbols"], env=env, check=True)
    return subprocess.run(
        ["git", "-C", path, "rev-parse", "HEAD"], env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_git_ingestion_extracts_and_searches_code_symbols(tmp_path) -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "m4-code")
    repo_path = str(tmp_path / "code-repo")
    commit = build_code_repo(repo_path)
    os.environ["SOURCEBRIEF_ALLOW_LOCAL_GIT"] = "true"
    resource_id = add_resource(
        client,
        workspace_id,
        project_id,
        headers,
        {
            "type": "git",
            "name": "Code Repo",
            "uri": f"file://{repo_path}",
            "source_config": {"branch": "main"},
        },
    )
    completed = ingest_inproc(client, workspace_id, project_id, resource_id, headers)
    assert completed["status"] == "succeeded"
    assert completed["symbols_created"] >= 3

    response = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/code-search",
        json={"query": "reconcile_cart", "resource_ids": [resource_id]},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] >= 1
    hit = body["symbols"][0]
    assert hit["name"] == "reconcile_cart"
    assert hit["kind"] == "function"
    assert hit["language"] == "python"
    assert hit["path"] == "src/checkout.py"
    assert hit["line_start"] == 4
    assert hit["commit"] == commit


def test_code_search_denies_non_workspace_member() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "m4-auth")
    denied = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/code-search",
        json={"query": "anything"},
        headers={"X-User-Email": "intruder@example.com"},
    )
    assert denied.status_code == 404


def test_code_search_uses_current_snapshot_and_resource_filter(tmp_path) -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "m4-current")
    repo_a = str(tmp_path / "repo-a")
    build_code_repo(repo_a)
    os.environ["SOURCEBRIEF_ALLOW_LOCAL_GIT"] = "true"
    resource_a = add_resource(
        client,
        workspace_id,
        project_id,
        headers,
        {"type": "git", "name": "Repo A", "uri": f"file://{repo_a}", "source_config": {"branch": "main"}},
    )
    ingest_inproc(client, workspace_id, project_id, resource_a, headers)

    repo_b = str(tmp_path / "repo-b")
    os.makedirs(repo_b, exist_ok=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "qa",
        "GIT_AUTHOR_EMAIL": "qa@example.com",
        "GIT_COMMITTER_NAME": "qa",
        "GIT_COMMITTER_EMAIL": "qa@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", repo_b], env=env, check=True)
    os.makedirs(os.path.join(repo_b, "src"), exist_ok=True)
    with open(os.path.join(repo_b, "src", "other.py"), "w", encoding="utf-8") as fh:
        fh.write("def only_in_repo_b():\n    return True\n")
    subprocess.run(["git", "-C", repo_b, "add", "-A"], env=env, check=True)
    subprocess.run(["git", "-C", repo_b, "commit", "-q", "-m", "repo b"], env=env, check=True)
    resource_b = add_resource(
        client,
        workspace_id,
        project_id,
        headers,
        {"type": "git", "name": "Repo B", "uri": f"file://{repo_b}", "source_config": {"branch": "main"}},
    )
    ingest_inproc(client, workspace_id, project_id, resource_b, headers)

    filtered = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/code-search",
        json={"query": "only_in_repo_b", "resource_ids": [resource_a]},
        headers=headers,
    )
    assert filtered.status_code == 200
    assert filtered.json()["count"] == 0

    with open(os.path.join(repo_a, "src", "checkout.py"), "w", encoding="utf-8") as fh:
        fh.write("def new_current_symbol():\n    return True\n")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "qa",
        "GIT_AUTHOR_EMAIL": "qa@example.com",
        "GIT_COMMITTER_NAME": "qa",
        "GIT_COMMITTER_EMAIL": "qa@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    subprocess.run(["git", "-C", repo_a, "add", "-A"], env=env, check=True)
    subprocess.run(["git", "-C", repo_a, "commit", "-q", "-m", "replace symbol"], env=env, check=True)
    ingest_inproc(client, workspace_id, project_id, resource_a, headers)
    old = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/code-search",
        json={"query": "reconcile_cart", "resource_ids": [resource_a]},
        headers=headers,
    )
    assert old.status_code == 200
    assert old.json()["count"] == 0
    new = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/code-search",
        json={"query": "new_current_symbol", "resource_ids": [resource_a]},
        headers=headers,
    )
    assert new.status_code == 200
    assert new.json()["count"] == 1


def test_code_search_respects_retrieval_enabled() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "m4-disabled")
    resource_id = add_resource(
        client,
        workspace_id,
        project_id,
        headers,
        {
            "type": "markdown",
            "name": "Disabled Code",
            "uri": "doc://disabled-code",
            "source_config": {"content": "def disabled_symbol():\n    return True\n", "path": "src/disabled.py"},
        },
    )
    ingest_inproc(client, workspace_id, project_id, resource_id, headers)
    patched = client.patch(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}",
        json={"retrieval_enabled": False},
        headers=headers,
    )
    assert patched.status_code == 200, patched.text
    response = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/code-search",
        json={"query": "disabled_symbol"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_symbol_budget_failure_is_recorded() -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "m4-budget")
    content = "\n".join(f"def symbol_{idx}():\n    return {idx}" for idx in range(5))
    resource_id = add_resource(
        client,
        workspace_id,
        project_id,
        headers,
        {
            "type": "markdown",
            "name": "Too Many Symbols",
            "uri": "doc://too-many-symbols",
            "source_config": {"content": content, "path": "src/many.py", "max_symbols": 2},
        },
    )
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
    with pytest.raises(RuntimeError, match="symbol budget exceeded"):
        run_index(run_id)
    response = client.get(f"/workspaces/{workspace_id}/index-runs/{run_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "failed"


def test_repo_agent_brief_and_retrieval_eval_are_productized(tmp_path) -> None:
    require_real_services()
    client = TestClient(app)
    headers, workspace_id, project_id = make_project(client, "mature-alpha")
    repo_path = str(tmp_path / "brief-repo")
    build_code_repo(repo_path)
    os.environ["SOURCEBRIEF_ALLOW_LOCAL_GIT"] = "true"
    resource_id = add_resource(
        client,
        workspace_id,
        project_id,
        headers,
        {
            "type": "git",
            "name": "Brief Repo",
            "uri": f"file://{repo_path}",
            "source_config": {"branch": "main"},
        },
    )
    completed = ingest_inproc(client, workspace_id, project_id, resource_id, headers)
    assert completed["status"] == "succeeded"
    review = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource_id}/review",
        json={"review_status": "approved", "retrieval_enabled": True, "stale_after_days": 30},
        headers=headers,
    )
    assert review.status_code == 200, review.text

    brief = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/repo-agents/{resource_id}/brief",
        headers=headers,
    )
    assert brief.status_code == 200, brief.text
    brief_body = brief.json()
    assert brief_body["readiness"] == "ready"
    assert "git-backed repo sub-agent" in brief_body["operating_brief"]
    assert "main.py" in brief_body["entrypoint_paths"]
    assert "pyproject.toml" in brief_body["config_paths"]
    assert brief_body["symbol_samples"]
    assert any(symbol["name"] == "reconcile_cart" for symbol in brief_body["symbol_samples"])

    profiles = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/retrieval-profiles",
        headers=headers,
    )
    assert profiles.status_code == 200, profiles.text
    profiles_body = profiles.json()
    assert profiles_body["default"] == "hybrid"
    profile_names = {profile["name"] for profile in profiles_body["profiles"]}
    assert {"lexical", "vector", "hybrid", "hybrid_rerank", "graph"}.issubset(profile_names)

    lexical_context = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
        json={"query": "reconcile_cart", "profile": "lexical", "resource_ids": [resource_id], "top_k": 8},
        headers=headers,
    )
    assert lexical_context.status_code == 200, lexical_context.text
    lexical_body = lexical_context.json()
    assert lexical_body["profile"] == "lexical"
    assert lexical_body["citations"]

    invalid_profile = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
        json={"query": "reconcile_cart", "profile": "rerank everything"},
        headers=headers,
    )
    assert invalid_profile.status_code == 422, invalid_profile.text

    context_packet = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packets",
        json={"query": "reconcile_cart", "profile": "lexical", "resource_ids": [resource_id], "top_k": 8},
        headers=headers,
    )
    assert context_packet.status_code == 201, context_packet.text
    assert context_packet.json()["diagnostics"]["retrieval_profile"] == "lexical"
    assert context_packet.json()["diagnostics"]["retrieval_profile_weights"]["lexical"] == 1.0

    eval_response = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/retrieval-evals",
        json={
            "runtime": "hermes",
            "profile": "hybrid_rerank",
            "max_chars": 8000,
            "questions": [
                {
                    "id": "checkout-symbol",
                    "query": "reconcile_cart",
                    "expected_resource_ids": [resource_id],
                    "resource_ids": [resource_id],
                    "required_texts": ["reconcile_cart"],
                    "expected_paths": ["src/checkout.py"],
                    "expected_symbols": ["reconcile_cart"],
                    "min_citations": 1,
                    "top_k": 8,
                }
            ],
        },
        headers=headers,
    )
    assert eval_response.status_code == 200, eval_response.text
    eval_body = eval_response.json()
    assert eval_body["summary"]["status"] == "passed"
    assert eval_body["profile"] == "hybrid_rerank"
    assert eval_body["diagnostics"]["retrieval_profile"] == "hybrid_rerank"
    assert eval_body["diagnostics"]["retrieval_profile_weights"]["rerank"] > 0
    assert eval_body["run_id"]
    assert eval_body["summary"]["passed_count"] == 1
    assert eval_body["results"][0]["passed"] is True
    assert resource_id in eval_body["results"][0]["cited_resource_ids"]
    assert eval_body["results"][0]["hit_quality"]

    history = client.get(f"/workspaces/{workspace_id}/projects/{project_id}/retrieval-evals", headers=headers)
    assert history.status_code == 200, history.text
    assert history.json()["count"] >= 1
    assert history.json()["runs"][0]["id"] == eval_body["run_id"]
    assert history.json()["runs"][0]["profile"] == "hybrid_rerank"
    detail = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/retrieval-evals/{eval_body['run_id']}",
        headers=headers,
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["profile"] == "hybrid_rerank"
    assert detail.json()["summary"]["status"] == "passed"
    assert detail.json()["results"][0]["hit_quality"]

    read_only_persist = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries/run?dry_run=false",
        headers=create_token(client, workspace_id, headers, ["review:read"], allowed_resource_ids=[resource_id]),
    )
    assert read_only_persist.status_code == 403, read_only_persist.text

    audit = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries/run?dry_run=false",
        headers=headers,
    )
    assert audit.status_code == 200, audit.text
    audit_body = audit.json()
    assert audit_body["count"] == 1
    assert audit_body["summaries"][0]["resource_id"] == resource_id
    assert audit_body["summaries"][0]["status"] == "healthy"
    assert audit_body["summaries"][0]["metrics"]["latest_eval_profile"] == "hybrid_rerank"
    assert audit_body["summaries"][0]["findings"] == []

    summaries = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries",
        headers=headers,
    )
    assert summaries.status_code == 200, summaries.text
    assert summaries.json()["count"] == 1
    assert summaries.json()["summaries"][0]["status"] == "healthy"

    scoped_headers = create_token(client, workspace_id, headers, ["review:read", "review:write"], allowed_resource_ids=[resource_id])
    scoped_list = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries",
        headers=scoped_headers,
    )
    assert scoped_list.status_code == 200, scoped_list.text
    assert scoped_list.json()["count"] == 1
    hidden_headers = create_token(client, workspace_id, headers, ["review:read"], allowed_resource_ids=[])
    hidden_list = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries",
        headers=hidden_headers,
    )
    assert hidden_list.status_code == 200, hidden_list.text
    assert hidden_list.json()["count"] == 0
    default_dry_run = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries/run",
        headers=scoped_headers,
    )
    assert default_dry_run.status_code == 200, default_dry_run.text
    assert default_dry_run.json()["count"] == 1
    scoped_dry_run = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries/run?dry_run=true",
        headers=scoped_headers,
    )
    assert scoped_dry_run.status_code == 200, scoped_dry_run.text
    assert scoped_dry_run.json()["count"] == 1
    dry_run_after = client.get(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries?latest_only=false",
        headers=headers,
    )
    assert dry_run_after.status_code == 200, dry_run_after.text
    assert dry_run_after.json()["count"] == 1
    ack = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries/{audit_body['summaries'][0]['id']}/acknowledge",
        json={"suppress_for_hours": 24},
        headers=scoped_headers,
    )
    assert ack.status_code == 200, ack.text
    assert ack.json()["acknowledged_at"]
    assert ack.json()["suppressed_until"]
    hidden_ack = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-card-summaries/{audit_body['summaries'][0]['id']}/acknowledge",
        json={"suppress_for_hours": 24},
        headers=hidden_headers,
    )
    assert hidden_ack.status_code == 403, hidden_ack.text

    mcp_tools = client.post(
        f"/mcp/{workspace_id}/{project_id}",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers=headers,
    )
    assert mcp_tools.status_code == 200, mcp_tools.text
    tools = {tool["name"]: tool for tool in mcp_tools.json()["result"]["tools"]}
    assert "profile" in tools["sourcebrief.get_agent_context"]["inputSchema"]["properties"]
    assert "profile" not in tools["sourcebrief.search_code"]["inputSchema"]["properties"]

    forbidden = client.post(
        f"/workspaces/{workspace_id}/projects/{project_id}/retrieval-evals",
        json={
            "questions": [
                {
                    "id": "forbidden-resource-regression",
                    "query": "Where is reconcile_cart implemented?",
                    "forbidden_resource_ids": [resource_id],
                    "min_citations": 1,
                }
            ]
        },
        headers=headers,
    )
    assert forbidden.status_code == 200, forbidden.text
    assert forbidden.json()["summary"]["status"] == "failed"
    assert "forbidden_resources_cited" in forbidden.json()["summary"]["failure_reasons"][0]
