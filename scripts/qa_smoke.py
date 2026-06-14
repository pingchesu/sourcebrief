from __future__ import annotations

import sys
import time

import requests

BASE = "http://localhost:18000"
HEADERS = {"X-User-Email": f"qa-{int(time.time())}@example.com"}


def request(method: str, path: str, expected: int, **kwargs):
    response = requests.request(method, f"{BASE}{path}", timeout=10, **kwargs)
    if response.status_code != expected:
        print(f"{method} {path} expected {expected}, got {response.status_code}: {response.text}", file=sys.stderr)
        raise SystemExit(1)
    return response.json() if response.content else None


def main() -> None:
    ts = int(time.time() * 1000)
    workspace = request("POST", "/workspaces", 201, json={"name": "QA", "slug": f"qa-{ts}"}, headers=HEADERS)
    project = request(
        "POST",
        f"/workspaces/{workspace['id']}/projects",
        201,
        json={"name": "ContextSmith QA", "description": "smoke"},
        headers=HEADERS,
    )
    resource = request(
        "POST",
        f"/workspaces/{workspace['id']}/projects/{project['id']}/resources",
        201,
        json={"type": "markdown", "name": "QA Runbook", "uri": "file://qa.md"},
        headers=HEADERS,
    )
    run = request(
        "POST",
        f"/workspaces/{workspace['id']}/projects/{project['id']}/resources/{resource['id']}/refresh",
        202,
        headers=HEADERS,
    )
    deadline = time.time() + 60
    status = run["status"]
    while time.time() < deadline:
        current = request("GET", f"/workspaces/{workspace['id']}/index-runs/{run['id']}", 200, headers=HEADERS)
        status = current["status"]
        if status in {"succeeded", "failed"}:
            break
        time.sleep(2)
    if status != "succeeded":
        print(f"index run did not succeed: {status}", file=sys.stderr)
        raise SystemExit(1)
    audit_events = request("GET", f"/workspaces/{workspace['id']}/audit-events", 200, headers=HEADERS)
    actions = {event["action"] for event in audit_events}
    required_actions = {"workspace.create", "project.create", "resource.create", "resource.refresh"}
    missing_actions = required_actions - actions
    if missing_actions:
        print(f"missing audit actions: {sorted(missing_actions)}", file=sys.stderr)
        raise SystemExit(1)
    denied = requests.get(
        f"{BASE}/workspaces/{workspace['id']}/projects/{project['id']}",
        headers={"X-User-Email": "intruder@example.com"},
        timeout=10,
    )
    if denied.status_code != 404:
        print(f"unauthorized read should 404, got {denied.status_code}: {denied.text}", file=sys.stderr)
        raise SystemExit(1)
    web = requests.get("http://localhost:13000/api/health", timeout=10)
    if web.status_code != 200:
        print(f"frontend health failed: {web.status_code} {web.text}", file=sys.stderr)
        raise SystemExit(1)
    print(
        "QA smoke passed: workspace/project/resource refresh flow, audit events, RQ worker, auth denial, frontend health"
    )


if __name__ == "__main__":
    main()
