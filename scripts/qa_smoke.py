from __future__ import annotations

import sys
import time

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
    deadline = time.time() + 90
    status = run["status"]
    while time.time() < deadline:
        current = request("GET", f"/workspaces/{ws}/index-runs/{run['id']}", 200, headers=HEADERS)
        status = current["status"]
        if status in {"succeeded", "failed"}:
            break
        time.sleep(2)
    if status != "succeeded":
        fail(f"index run did not succeed: {status}")
    if current["documents_seen"] < 1 or current["chunks_created"] < 1:
        fail(f"index run produced no chunks: {current}")

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
        "QA smoke passed: ingestion → snapshot → chunks → lexical search with citations, "
        "index-run logs, audit events, RQ worker, auth denial (read+search), frontend health"
    )


if __name__ == "__main__":
    main()
