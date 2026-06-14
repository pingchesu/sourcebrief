from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

BASE = "http://localhost:18000"
HEADERS = {"X-User-Email": f"qa-{int(time.time())}@example.com"}
MARKER = "contextsmithqamarker"


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
    current = {"status": "queued"}
    while time.time() < deadline:
        current = request("GET", f"/workspaces/{ws}/index-runs/{run_id}", 200, headers=HEADERS)
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
    ts = int(time.time() * 1000)
    workspace = request("POST", "/workspaces", 201, json={"name": "QA", "slug": f"qa-{ts}"}, headers=HEADERS)
    ws = workspace["id"]
    project = request(
        "POST",
        f"/workspaces/{ws}/projects",
        201,
        json={"name": "ContextSmith QA", "description": "smoke"},
        headers=HEADERS,
    )
    proj = project["id"]
    content = (
        "# QA Runbook\n\n"
        "ContextSmith QA verifies resource ingestion and lexical search. "
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
    if packet["count"] < 1 or not packet.get("id") or not packet.get("query_run_id"):
        fail(f"context packet missing items or analytics ids: {packet}")
    packet_item = packet["items"][0]
    if packet_item["resource_id"] != res or packet_item["citation"]["resource_id"] != res:
        fail(f"context packet citation mismatch: {packet_item}")
    if packet_item.get("vector_score", 0) == 0:
        fail(f"context packet missing vector score: {packet_item}")

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
            "contextsmith_cli.main",
            "--api-url",
            BASE,
            "--email",
            HEADERS["X-User-Email"],
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
    mcp_tools = request(
        "POST",
        f"/mcp/{ws}/{proj}",
        200,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers=HEADERS,
    )
    if mcp_tools["result"]["tools"][0]["name"] != "contextsmith.get_agent_context":
        fail(f"MCP tools/list missing context tool: {mcp_tools}")
    mcp_call = request(
        "POST",
        f"/mcp/{ws}/{proj}",
        200,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "contextsmith.get_agent_context", "arguments": {"query": "smoke_symbol", "runtime": "codex"}},
        },
        headers=HEADERS,
    )
    if mcp_call["result"]["structuredContent"]["runtime"] != "codex":
        fail(f"MCP tools/call failed: {mcp_call}")

    # Audit trail covers the mutating actions.
    audit_events = request("GET", f"/workspaces/{ws}/audit-events", 200, headers=HEADERS)
    actions = {event["action"] for event in audit_events}
    required_actions = {"workspace.create", "project.create", "resource.create", "resource.refresh"}
    missing_actions = required_actions - actions
    if missing_actions:
        fail(f"missing audit actions: {sorted(missing_actions)}")

    # Auth denial: intruder cannot read the project or run search.
    denied = requests.get(
        f"{BASE}/workspaces/{ws}/projects/{proj}",
        headers={"X-User-Email": "intruder@example.com"},
        timeout=15,
    )
    if denied.status_code != 404:
        fail(f"unauthorized read should 404, got {denied.status_code}: {denied.text}")
    denied_search = requests.post(
        f"{BASE}/workspaces/{ws}/projects/{proj}/search",
        json={"query": MARKER},
        headers={"X-User-Email": "intruder@example.com"},
        timeout=15,
    )
    if denied_search.status_code != 404:
        fail(f"unauthorized search should 404, got {denied_search.status_code}: {denied_search.text}")

    # Frontend health is reachable in the composed stack.
    web = requests.get("http://localhost:13000/api/health", timeout=15)
    if web.status_code != 200:
        fail(f"frontend health failed: {web.status_code} {web.text}")

    print(
        "QA smoke passed: document+git ingestion → snapshots → chunks → embeddings → code symbols → graph index → lexical/hybrid/GraphRAG context retrieval with citations, "
        "CLI search, agent profile, query/resource usage analytics, review lifecycle, agent-context API, central MCP context tool, index-run logs, audit events, RQ worker, auth denial (read+search), frontend health"
    )


if __name__ == "__main__":
    main()
