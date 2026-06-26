from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, cast

import requests

BASE = os.getenv("SOURCEBRIEF_API_URL") or os.getenv("CONTEXTSMITH_API_URL") or os.getenv("API_URL") or "http://localhost:18000"
FRONTEND = os.getenv("SOURCEBRIEF_WEB_URL") or os.getenv("CONTEXTSMITH_WEB_URL") or os.getenv("WEB_URL") or "http://localhost:13000"
HEADERS: dict[str, str] = {}
AUTH_DEFAULT_WORKSPACE_ID: str | None = None
MARKER = "sourcebriefqamarker"
TOKEN_PATTERN = re.compile(r"cs_[A-Za-z0-9_-]{20,}")
GOLDEN_MCP_TOOL_ORDER = [
    "sourcebrief.ask",
    "sourcebrief.discover",
    "sourcebrief.lookup",
    "sourcebrief.get_agent_context",
]


def request(method: str, path: str, expected: int, **kwargs):
    response = requests.request(method, f"{BASE}{path}", timeout=15, **kwargs)
    if response.status_code != expected:
        print(
            f"{method} {path} expected {expected}, got {response.status_code}: {response.text}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return response.json() if response.content else None


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def assert_golden_mcp_tool_order(mcp_tools: dict[str, Any]) -> None:
    tools = mcp_tools.get("result", {}).get("tools", [])
    names = [tool.get("name") for tool in tools]
    expected = GOLDEN_MCP_TOOL_ORDER
    if names[: len(expected)] != expected:
        fail(
            f"MCP tools/list golden tools must be first in order {expected}, "
            f"got {names[: len(expected)]}: {mcp_tools}"
        )


def authenticate() -> None:
    global AUTH_DEFAULT_WORKSPACE_ID
    token = os.getenv("SOURCEBRIEF_QA_TOKEN") or os.getenv("CONTEXTSMITH_QA_TOKEN")
    if token:
        HEADERS.clear()
        HEADERS["Authorization"] = f"Bearer {token}"
        return
    email = os.getenv("SOURCEBRIEF_ADMIN_EMAIL") or os.getenv("CONTEXTSMITH_ADMIN_EMAIL")
    password = os.getenv("SOURCEBRIEF_ADMIN_PASSWORD") or os.getenv("CONTEXTSMITH_ADMIN_PASSWORD")
    if email and password:
        response = requests.post(
            f"{BASE}/auth/login",
            json={"email": email, "password": password},
            timeout=15,
        )
        if response.status_code != 200:
            fail(f"admin login failed with HTTP {response.status_code}: {response.text[:300]}")
        body = response.json()
        session_token = body.get("session_token")
        if not session_token:
            fail("admin login response did not include a session token")
        AUTH_DEFAULT_WORKSPACE_ID = body.get("default_workspace_id")
        HEADERS.clear()
        HEADERS["Authorization"] = f"Bearer {session_token}"
        return
    if (os.getenv("SOURCEBRIEF_DEV_AUTH") or os.getenv("CONTEXTSMITH_DEV_AUTH") or "").lower() in {"1", "true", "yes", "on"}:
        HEADERS.clear()
        HEADERS["X-User-Email"] = f"qa-{int(time.time())}@example.com"
        return
    fail("QA smoke requires SOURCEBRIEF_ADMIN_EMAIL/PASSWORD, SOURCEBRIEF_QA_TOKEN, or SOURCEBRIEF_DEV_AUTH=true")


def _current_bearer_token() -> str | None:
    authorization = HEADERS.get("Authorization")
    if authorization and authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ")
    return None


def cli_auth_args() -> list[str]:
    token = _current_bearer_token()
    if token:
        return ["--token", token]
    return ["--email", HEADERS["X-User-Email"]]


def hermes_creator_auth_args() -> list[str]:
    token = _current_bearer_token()
    if token:
        return ["--admin-token", token]
    return ["--email", HEADERS["X-User-Email"]]


def build_git_fixture(ts: int) -> tuple[str, str]:
    """Create a tiny git repo mounted into the worker container for QA smoke."""
    if shutil.which("git") is None:
        fail("git executable is required for QA smoke git ingestion")
    host_root = Path("tmp/qa-git-fixtures").resolve()
    host_root.mkdir(parents=True, exist_ok=True)
    repo_name = f"smoke-repo-{ts}"
    repo_path = host_root / repo_name
    bundle_path = host_root / f"{repo_name}.bundle"
    if repo_path.exists():
        shutil.rmtree(repo_path)
    if bundle_path.exists():
        bundle_path.unlink()
    repo_path.mkdir(parents=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "qa",
        "GIT_AUTHOR_EMAIL": "qa@example.com",
        "GIT_COMMITTER_NAME": "qa",
        "GIT_COMMITTER_EMAIL": "qa@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "init", "-q", str(repo_path)],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    (repo_path / "README.md").write_text(
        "# QA Git Repo\n\nThe quokkasmoke marker proves git ingestion through RQ.\n",
        encoding="utf-8",
    )
    (repo_path / "src").mkdir()
    (repo_path / "src" / "app.py").write_text(
        "class SmokeService:\n    pass\n\ndef smoke_symbol():\n    return 'ok'\n",
        encoding="utf-8",
    )
    (repo_path / "node_modules").mkdir()
    (repo_path / "node_modules" / "ignored.js").write_text("ignoredsmoke", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_path), "add", "-A"], env=env, check=True)
    subprocess.run(
        ["git", "-C", str(repo_path), "commit", "-q", "-m", "qa smoke"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    commit = subprocess.run(
        ["git", "-C", str(repo_path), "rev-parse", "HEAD"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "-C", str(repo_path), "bundle", "create", str(bundle_path), "--all"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return f"/qa-fixtures/{bundle_path.name}", commit


def wait_for_index_run(ws: str, run_id: str) -> dict:
    deadline = time.time() + 90
    current: dict[str, Any] = {"status": "queued"}
    while time.time() < deadline:
        response = request("GET", f"/workspaces/{ws}/index-runs/{run_id}", 200, headers=HEADERS)
        if response is None:
            fail("index run lookup returned empty response")
        current = cast(dict[str, Any], response)
        if current["status"] in {"succeeded", "failed"}:
            break
        time.sleep(2)
    if current["status"] != "succeeded":
        fail(f"index run did not succeed: {current}")
    if current["documents_seen"] < 1 or current["chunks_created"] < 1:
        fail(f"index run produced no chunks: {current}")
    if current.get("embeddings_created", 0) < 1:
        fail(f"index run produced no embeddings: {current}")
    if current.get("graph_nodes_created", 0) < 1 or current.get("graph_edges_created", 0) < 1:
        fail(f"index run produced no graph index: {current}")
    return current


def main() -> None:
    frontend = requests.get(f"{FRONTEND}/", timeout=15)
    if frontend.status_code != 200:
        fail(f"frontend console returned HTTP {frontend.status_code}: {frontend.text[:300]}")
    for marker in ("Command Center", "Agent readiness", "Source coverage"):
        if marker not in frontend.text:
            fail(f"frontend console missing marker {marker!r}")

    authenticate()

    provider_health = request("GET", "/provider-health", 200)
    if provider_health is None:
        fail("provider health returned empty response")
    expected_namespace = "hashing:sourcebrief-hashing-v1:d64:l2"
    if provider_health.get("status") != "ok" or provider_health["embedding"].get("namespace") != expected_namespace:
        fail(f"provider health missing expected namespace: {provider_health}")
    if provider_health["embedding"].get("dev_quality") is not True:
        fail(f"hashing provider must be marked dev-quality: {provider_health}")

    ts = int(time.time() * 1000)
    created_new_workspace = AUTH_DEFAULT_WORKSPACE_ID is None
    if created_new_workspace:
        workspace = request("POST", "/workspaces", 201, json={"name": "QA", "slug": f"qa-{ts}"}, headers=HEADERS)
        if workspace is None:
            fail("workspace create returned empty response")
        ws = workspace["id"]
    else:
        ws = str(AUTH_DEFAULT_WORKSPACE_ID)
    project = request(
        "POST",
        f"/workspaces/{ws}/projects",
        201,
        json={"name": f"SourceBrief QA {ts}", "description": "smoke"},
        headers=HEADERS,
    )
    if project is None:
        fail("project create returned empty response")
    proj = project["id"]
    token_created = request(
        "POST",
        f"/workspaces/{ws}/api-tokens",
        201,
        json={
            "name": "qa-web-console-token",
            "scopes": [
                "project:read",
                "project:query",
                "resource:read",
                "resource:write",
                "resource:refresh",
                "review:read",
                "review:write",
                "token:admin",
            ],
            "allowed_project_ids": [proj],
        },
        headers=HEADERS,
    )
    if token_created is None:
        fail("token create returned empty response")
    if not token_created.get("token") or "token" in token_created.get("api_token", {}):
        fail(f"token create must return one-time plaintext only: {token_created}")
    token_list = request("GET", f"/workspaces/{ws}/api-tokens", 200, headers=HEADERS)
    if token_list is None:
        fail("token list returned empty response")
    listed = next((item for item in token_list if item["name"] == "qa-web-console-token"), None)
    if not listed or "token" in listed:
        fail(f"token list missing token metadata or leaked plaintext: {token_list}")
    content = (
        "# QA Runbook\n\n"
        "SourceBrief QA verifies resource ingestion and lexical search. "
        f"The unique marker {MARKER} appears exactly once in this document.\n"
    )
    resource = request(
        "POST",
        f"/workspaces/{ws}/projects/{proj}/resources",
        201,
        json={
            "type": "markdown",
            "name": "QA Runbook",
            "uri": "doc://qa-runbook",
            "source_config": {"content": content},
        },
        headers=HEADERS,
    )
    res = resource["id"]

    run = request(
        "POST",
        f"/workspaces/{ws}/projects/{proj}/resources/{res}/refresh",
        202,
        headers=HEADERS,
    )
    wait_for_index_run(ws, run["id"])

    # Snapshot version/commit/hash is visible.
    snapshots = request(
        "GET",
        f"/workspaces/{ws}/projects/{proj}/resources/{res}/snapshots",
        200,
        headers=HEADERS,
    )
    if not snapshots or not snapshots[0]["version"] or not snapshots[0]["is_current"]:
        fail(f"snapshot version/current missing: {snapshots}")

    # Per-resource index run log/status is queryable.
    resource_runs = request(
        "GET",
        f"/workspaces/{ws}/projects/{proj}/resources/{res}/index-runs",
        200,
        headers=HEADERS,
    )
    if not any(r["status"] == "succeeded" for r in resource_runs):
        fail(f"no succeeded index run for resource: {resource_runs}")

    # Lexical search returns the chunk with citation metadata.
    search = request(
        "POST",
        f"/workspaces/{ws}/projects/{proj}/search",
        200,
        json={"query": MARKER},
        headers=HEADERS,
    )
    if search["count"] < 1:
        fail(f"search returned no hits for marker: {search}")
    hit = search["hits"][0]
    if hit["resource_id"] != res:
        fail(f"search hit resource mismatch: {hit}")
    for field in ("snapshot_id", "version", "ordinal", "content_hash"):
        if hit.get(field) in (None, ""):
            fail(f"search hit missing citation field {field!r}: {hit}")
    if MARKER not in hit["snippet"].lower():
        fail(f"snippet missing marker: {hit}")

    # M3 hybrid context packet returns cited chunks and query/hit analytics IDs.
    packet = request(
        "POST",
        f"/workspaces/{ws}/projects/{proj}/context-packets",
        201,
        json={"query": f"lexical vector rerank {MARKER}", "resource_ids": [res], "top_k": 5},
        headers=HEADERS,
    )
    if packet is None:
        fail("context packet returned empty response")
    if packet["count"] < 1 or not packet.get("id") or not packet.get("query_run_id"):
        fail(f"context packet missing items or analytics ids: {packet}")
    packet_item = packet["items"][0]
    if packet_item["resource_id"] != res or packet_item["citation"]["resource_id"] != res:
        fail(f"context packet citation mismatch: {packet_item}")
    if packet_item.get("vector_score", 0) == 0:
        fail(f"context packet missing vector score: {packet_item}")
    if packet.get("diagnostics", {}).get("embedding_namespace") != expected_namespace:
        fail(f"context packet missing embedding namespace diagnostics: {packet}")

    usage = request(
        "GET",
        f"/workspaces/{ws}/projects/{proj}/resource-usage",
        200,
        headers=HEADERS,
    )
    usage_row = next((item for item in usage["resources"] if item["resource_id"] == res), None)
    if not usage_row or usage_row["hit_count"] < 1:
        fail(f"usage analytics missing retrieval hit: {usage}")
    reviewed = request(
        "POST",
        f"/workspaces/{ws}/projects/{proj}/resources/{res}/review",
        200,
        json={"review_status": "approved", "review_note": "qa smoke", "stale_after_days": 30},
        headers=HEADERS,
    )
    if reviewed["review_status"] != "approved" or not reviewed.get("last_reviewed_at"):
        fail(f"resource review failed: {reviewed}")
    review = request(
        "GET",
        f"/workspaces/{ws}/projects/{proj}/resource-review",
        200,
        headers=HEADERS,
    )
    review_row = next((item for item in review["resources"] if item["resource"]["id"] == res), None)
    if not review_row or review_row["usage_count"] < 1:
        fail(f"resource review missing usage: {review}")

    archived = request("POST", f"/workspaces/{ws}/projects/{proj}/resources/{res}/archive", 200, headers=HEADERS)
    if archived["status"] != "archived" or archived["retrieval_enabled"]:
        fail(f"archive did not disable retrieval: {archived}")
    restored = request("POST", f"/workspaces/{ws}/projects/{proj}/resources/{res}/restore", 200, headers=HEADERS)
    if restored["status"] != "active" or not restored["retrieval_enabled"]:
        fail(f"restore did not reactivate resource: {restored}")
    scheduled = request("POST", f"/workspaces/{ws}/projects/{proj}/scheduled-refreshes?dry_run=true", 202, headers=HEADERS)
    if "enqueued" not in scheduled or "resource_ids" not in scheduled:
        fail(f"scheduled refresh dry-run missing shape: {scheduled}")
    purge_resource = request(
        "POST",
        f"/workspaces/{ws}/projects/{proj}/resources",
        201,
        json={
            "type": "markdown",
            "name": "QA Purge Doc",
            "uri": "doc://qa-purge",
            "source_config": {"content": "temporary purge smoke"},
        },
        headers=HEADERS,
    )
    purge_res = purge_resource["id"]
    request("DELETE", f"/workspaces/{ws}/projects/{proj}/resources/{purge_res}", 204, headers=HEADERS)
    purged = request("POST", f"/workspaces/{ws}/projects/{proj}/resources/{purge_res}/purge", 200, headers=HEADERS)
    if not purged["purged"] or purged["counts"].get("resources") != 1:
        fail(f"resource purge failed: {purged}")

    upload_secret = "ghp_ab...3456"
    upload_resource = request(
        "POST",
        f"/workspaces/{ws}/projects/{proj}/resources",
        201,
        json={
            "type": "upload",
            "name": "QA Upload",
            "uri": "upload://qa-upload.md",
            "source_config": {
                "filename": "qa-upload.md",
                "content_type": "text/markdown",
                "content": f"# Upload\n\nThe qauploadredacted marker appears with api_key={upload_secret}.\n",
            },
        },
        headers=HEADERS,
    )
    upload_res = upload_resource["id"]
    upload_run = request("POST", f"/workspaces/{ws}/projects/{proj}/resources/{upload_res}/refresh", 202, headers=HEADERS)
    wait_for_index_run(ws, upload_run["id"])
    upload_secret_search = request(
        "POST",
        f"/workspaces/{ws}/projects/{proj}/search",
        200,
        json={"query": upload_secret, "resource_ids": [upload_res]},
        headers=HEADERS,
    )
    if upload_secret_search["count"] != 0:
        fail(f"secret should not be searchable after upload redaction: {upload_secret_search}")
    upload_redacted_search = request(
        "POST",
        f"/workspaces/{ws}/projects/{proj}/search",
        200,
        json={"query": "qauploadredacted", "resource_ids": [upload_res]},
        headers=HEADERS,
    )
    if upload_redacted_search["count"] < 1 or "REDACTED:generic_api_key" not in upload_redacted_search["hits"][0]["snippet"]:
        fail(f"redacted upload should be searchable with redacted snippet: {upload_redacted_search}")
    upload_snapshots = request(
        "GET",
        f"/workspaces/{ws}/projects/{proj}/resources/{upload_res}/snapshots",
        200,
        headers=HEADERS,
    )
    if upload_snapshots[0]["metadata"].get("redacted_secret_counts", {}).get("generic_api_key") != 1:
        fail(f"upload redaction metadata missing: {upload_snapshots}")

    # Negative search returns nothing.
    empty = request(
        "POST",
        f"/workspaces/{ws}/projects/{proj}/search",
        200,
        json={"query": "zzzznomatchzzzz"},
        headers=HEADERS,
    )
    if empty["count"] != 0:
        fail(f"negative search should be empty: {empty}")

    # Git repo ingestion also goes through the real API -> Redis/RQ worker -> DB path.
    git_uri, git_commit = build_git_fixture(ts)
    git_resource = request(
        "POST",
        f"/workspaces/{ws}/projects/{proj}/resources",
        201,
        json={
            "type": "git",
            "name": "QA Git Repo",
            "uri": git_uri,
            "source_config": {},
        },
        headers=HEADERS,
    )
    git_res = git_resource["id"]
    git_run = request(
        "POST",
        f"/workspaces/{ws}/projects/{proj}/resources/{git_res}/refresh",
        202,
        headers=HEADERS,
    )
    wait_for_index_run(ws, git_run["id"])
    git_snapshots = request(
        "GET",
        f"/workspaces/{ws}/projects/{proj}/resources/{git_res}/snapshots",
        200,
        headers=HEADERS,
    )
    if not git_snapshots or git_snapshots[0]["version"] != git_commit:
        fail(f"git snapshot commit mismatch: expected {git_commit}, got {git_snapshots}")
    git_search = request(
        "POST",
        f"/workspaces/{ws}/projects/{proj}/search",
        200,
        json={"query": "quokkasmoke", "resource_ids": [git_res]},
        headers=HEADERS,
    )
    if git_search["count"] < 1 or git_search["hits"][0].get("commit") != git_commit:
        fail(f"git search/citation failed: {git_search}")
    cli_search = subprocess.run(
        [
            sys.executable,
            "-m",
            "sourcebrief_cli.main",
            "--api-url",
            BASE,
            *cli_auth_args(),
            "--json",
            "search",
            "--workspace-id",
            ws,
            "--project-id",
            proj,
            "--query",
            "quokkasmoke",
            "--resource-id",
            git_res,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if cli_search.returncode != 0:
        fail(f"CLI search failed: stdout={cli_search.stdout} stderr={cli_search.stderr}")
    cli_payload = cli_search.stdout.strip()
    try:
        cli_result = json.loads(cli_payload)
    except json.JSONDecodeError:
        fail(f"CLI search returned non-JSON output: {cli_payload}")
    if cli_result["count"] < 1 or cli_result["hits"][0].get("commit") != git_commit:
        fail(f"CLI search/citation failed: {cli_result}")
    code_search = request(
        "POST",
        f"/workspaces/{ws}/projects/{proj}/code-search",
        200,
        json={"query": "smoke_symbol", "resource_ids": [git_res]},
        headers=HEADERS,
    )
    if code_search["count"] < 1:
        fail(f"code search returned no symbols: {code_search}")
    code_hit = code_search["symbols"][0]
    if code_hit["name"] != "smoke_symbol" or code_hit.get("commit") != git_commit:
        fail(f"code symbol citation failed: {code_search}")

    git_graph = request(
        "GET",
        f"/workspaces/{ws}/projects/{proj}/resources/{git_res}/graph",
        200,
        headers=HEADERS,
    )
    if git_graph["node_count"] < 2 or git_graph["edge_count"] < 1:
        fail(f"resource graph missing nodes/edges: {git_graph}")

    agent_profile = request(
        "GET",
        f"/workspaces/{ws}/projects/{proj}/agent-profile",
        200,
        headers=HEADERS,
    )
    if agent_profile["resource_count"] < 2 or agent_profile["graph_node_count"] < 1:
        fail(f"agent profile missing resources/graph stats: {agent_profile}")
    patched_profile = request(
        "PATCH",
        f"/workspaces/{ws}/projects/{proj}/agent-profile",
        200,
        json={"system_prompt": "Prefer concise QA-smoke answers."},
        headers=HEADERS,
    )
    if "QA-smoke" not in (patched_profile.get("system_prompt") or ""):
        fail(f"agent profile patch failed: {patched_profile}")

    agent_context = request(
        "POST",
        f"/workspaces/{ws}/projects/{proj}/agent-context",
        200,
        json={"query": "smoke_symbol", "runtime": "hermes", "resource_ids": [git_res], "top_k": 5},
        headers=HEADERS,
    )
    if "Hermes specialist agent" not in agent_context["instruction"] or not agent_context["citations"]:
        fail(f"agent context missing runtime instruction/citations: {agent_context}")
    if not any(symbol["name"] == "smoke_symbol" for symbol in agent_context.get("symbols", [])):
        fail(f"agent context missing code symbol: {agent_context}")

    runtime_plan = request(
        "POST",
        f"/workspaces/{ws}/projects/{proj}/runtime-install-plan",
        200,
        json={
            "target": "hermes",
            "public_api_url": f"{BASE}?token=must-not-leak",
            "server_name": "QA Runtime Plan",
            "resource_ids": [git_res],
        },
        headers=HEADERS,
    )
    if runtime_plan is None:
        fail("runtime install plan returned empty response")
    assert runtime_plan is not None
    if runtime_plan["server_name"] != "qa-runtime-plan" or runtime_plan["resource_scope"]["resources"][0]["resource_id"] != git_res:
        fail(f"runtime install plan scope/server mismatch: {runtime_plan}")
    if "must-not-leak" in json.dumps(runtime_plan) or "${SOURCEBRIEF_TOKEN}" not in runtime_plan["mcp_config"]["content"]:
        fail(f"runtime install plan did not redact token placeholder correctly: {runtime_plan}")
    validator_commands = runtime_plan.get("validator_commands") or []
    if not validator_commands or "--query" not in validator_commands[0]:
        fail(f"runtime install plan validator command is not runnable: {runtime_plan}")
    capability_names = {capability["name"] for capability in runtime_plan["capabilities"]}
    if "sourcebrief.get_agent_context" not in capability_names or "sourcebrief.open_pr" not in capability_names:
        fail(f"runtime install plan missing MCP capability inventory: {runtime_plan}")

    mcp_tools = request(
        "POST",
        f"/mcp/{ws}/{proj}",
        200,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers=HEADERS,
    )
    assert_golden_mcp_tool_order(mcp_tools)
    mcp_call = request(
        "POST",
        f"/mcp/{ws}/{proj}",
        200,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "sourcebrief.get_agent_context", "arguments": {"query": "smoke_symbol", "runtime": "codex"}},
        },
        headers=HEADERS,
    )
    if mcp_call["result"]["structuredContent"]["runtime"] != "codex":
        fail(f"MCP tools/call failed: {mcp_call}")

    hermes_check = subprocess.run(
        [
            sys.executable,
            "scripts/hermes_integration.py",
            "--api-url",
            BASE,
            *hermes_creator_auth_args(),
            "--workspace-id",
            ws,
            "--project-id",
            proj,
            "--resource-id",
            git_res,
            "--query",
            "smoke_symbol",
            "--expect-text",
            "smoke_symbol",
            "--redact-token",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if hermes_check.returncode != 0:
        fail(f"Hermes integration script failed: stdout={hermes_check.stdout}\nstderr={hermes_check.stderr}")
    hermes_output = json.loads(hermes_check.stdout)
    if TOKEN_PATTERN.search(hermes_check.stdout):
        fail(f"Hermes integration script leaked plaintext token in redacted output: {hermes_check.stdout}")
    if hermes_output["status"] != "ok" or "sourcebrief.get_agent_context" not in hermes_output["mcp"]["tool_names"]:
        fail(f"Hermes integration script returned invalid output: {hermes_output}")
    if hermes_output.get("token") != "<redacted>":
        fail(f"Hermes integration script did not redact token field: {hermes_output}")
    header = hermes_output["hermes_config"]["mcp_servers"]["sourcebrief"]["headers"]["Authorization"]
    if header != "Bearer <redacted>":
        fail(f"Hermes integration script did not redact config header: {hermes_output}")
    expected_scopes = {"project:read", "project:query", "resource:read", "review:read", "code:read"}
    actual_scopes = set(hermes_output["api_token"]["scopes"])
    if actual_scopes != expected_scopes:
        fail(f"Hermes token scopes are not read-only default: {hermes_output}")
    if hermes_output["api_token"].get("allowed_project_ids") != [proj]:
        fail(f"Hermes token project allowlist mismatch: {hermes_output}")
    if hermes_output["api_token"].get("allowed_resource_ids") != [git_res]:
        fail(f"Hermes token resource allowlist mismatch: {hermes_output}")
    if hermes_output["agent_context"]["citation_count"] < 1 or hermes_output["agent_context"]["context_chars"] < 1:
        fail(f"Hermes integration script did not validate cited context: {hermes_output}")
    if hermes_output["mcp"]["citation_count"] < 1:
        fail(f"Hermes integration script did not validate MCP citations: {hermes_output}")

    # Audit trail covers the mutating actions.
    audit_events = request("GET", f"/workspaces/{ws}/audit-events", 200, headers=HEADERS)
    actions = {event["action"] for event in audit_events}
    required_actions = {"project.create", "resource.create", "resource.refresh"}
    if created_new_workspace:
        required_actions.add("workspace.create")
    missing_actions = required_actions - actions
    if missing_actions:
        fail(f"missing audit actions: {sorted(missing_actions)}")

    # Auth denial: intruder cannot read the project or run search.
    denied = requests.get(
        f"{BASE}/workspaces/{ws}/projects/{proj}",
        headers={"X-User-Email": "intruder@example.com"},
        timeout=15,
    )
    if denied.status_code not in {401, 404}:
        fail(f"unauthorized read should 401/404, got {denied.status_code}: {denied.text}")
    denied_search = requests.post(
        f"{BASE}/workspaces/{ws}/projects/{proj}/search",
        json={"query": MARKER},
        headers={"X-User-Email": "intruder@example.com"},
        timeout=15,
    )
    if denied_search.status_code not in {401, 404}:
        fail(f"unauthorized search should 401/404, got {denied_search.status_code}: {denied_search.text}")

    # Frontend health is reachable in the composed stack.
    web = requests.get(f"{FRONTEND}/api/health", timeout=15)
    if web.status_code != 200:
        fail(f"frontend health failed: {web.status_code} {web.text}")

    print(
        "QA smoke passed: document+git ingestion → snapshots → chunks → embeddings → code symbols → graph index → lexical/hybrid/GraphRAG context retrieval with citations, "
        "CLI search, agent profile, runtime install plan, web console homepage/token flow, provider health/namespace diagnostics, query/resource usage analytics, review lifecycle, scheduled refresh dry-run, restore/purge lifecycle, upload connector redaction, agent-context API, central MCP context tool, Hermes integration script, index-run logs, audit events, RQ worker, auth denial (read+search), frontend health"
    )


if __name__ == "__main__":
    main()
