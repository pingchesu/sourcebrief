#!/usr/bin/env python3
"""Run the SourceBrief alpha evaluation/release dataset.

The eval intentionally uses the public API and worker-backed indexing path. It
creates a small repo, a runbook document, a foreign tenant document, and then
checks golden questions for citations, resource freshness, usage accounting,
latency/context metrics, and tenant isolation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests

BASE = os.getenv("SOURCEBRIEF_API_URL") or os.getenv("CONTEXTSMITH_API_URL") or os.getenv("API_URL") or "http://localhost:18000"
EMAIL = os.getenv("SOURCEBRIEF_EVAL_EMAIL", os.getenv("CONTEXTSMITH_EVAL_EMAIL", f"alpha-eval-{int(time.time())}@example.com"))
HEADERS = {"X-User-Email": EMAIL}
DATASET = Path("demo/alpha/golden_questions.json")
DEFAULT_REPORT = Path("artifacts/alpha-eval-report.json")


def fail(message: str) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(1)


def request(method: str, path: str, expected: int, **kwargs: Any) -> Any:
    response = requests.request(method, f"{BASE}{path}", timeout=30, **kwargs)
    if response.status_code != expected:
        fail(f"{method} {path} expected {expected}, got {response.status_code}: {response.text}")
    return response.json() if response.content else None


def build_repo_fixture(ts: int) -> tuple[str, str]:
    if shutil.which("git") is None:
        fail("git executable is required for alpha eval repo fixture")
    host_root = Path("tmp/qa-git-fixtures").resolve()
    host_root.mkdir(parents=True, exist_ok=True)
    repo_name = f"alpha-eval-repo-{ts}"
    repo_path = host_root / repo_name
    bundle_path = host_root / f"{repo_name}.bundle"
    if repo_path.exists():
        shutil.rmtree(repo_path)
    if bundle_path.exists():
        bundle_path.unlink()
    repo_path.mkdir(parents=True)
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "alpha-eval",
        "GIT_AUTHOR_EMAIL": "alpha-eval@example.com",
        "GIT_COMMITTER_NAME": "alpha-eval",
        "GIT_COMMITTER_EMAIL": "alpha-eval@example.com",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    subprocess.run(["git", "-c", "init.defaultBranch=main", "init", "-q", str(repo_path)], env=env, check=True)
    (repo_path / "README.md").write_text(
        "# Alpha Eval Repo\n\n"
        "This repository documents the Python function alpha_repo_symbol in src/context_agent.py. "
        "alpha_repo_symbol returns the repository agent context marker for repo-focused evaluation. "
        "SourceBrief exposes repository agent context through REST and central MCP tools.\n",
        encoding="utf-8",
    )
    (repo_path / "src").mkdir()
    (repo_path / "src" / "context_agent.py").write_text(
        "def alpha_repo_symbol():\n"
        "    \"\"\"Return the alpharepoagent42 marker for agent context evals.\"\"\"\n"
        "    return 'alpharepoagent42'\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo_path), "add", "-A"], env=env, check=True)
    subprocess.run(["git", "-C", str(repo_path), "commit", "-q", "-m", "alpha eval repo"], env=env, check=True)
    commit = subprocess.check_output(["git", "-C", str(repo_path), "rev-parse", "HEAD"], env=env, text=True).strip()
    subprocess.run(["git", "-C", str(repo_path), "bundle", "create", str(bundle_path), "--all"], env=env, check=True)
    return f"/qa-fixtures/{bundle_path.name}", commit


def wait_for_index_run(workspace_id: str, run_id: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request_headers = headers or HEADERS
    deadline = time.time() + 120
    current: dict[str, Any] = {"status": "queued"}
    while time.time() < deadline:
        current = request("GET", f"/workspaces/{workspace_id}/index-runs/{run_id}", 200, headers=request_headers)
        if current["status"] in {"succeeded", "failed"}:
            break
        time.sleep(1)
    if current.get("status") != "succeeded":
        fail(f"index run did not succeed: {current}")
    return current


def create_workspace_project(prefix: str, ts: int, headers: dict[str, str] | None = None) -> tuple[str, str]:
    request_headers = headers or HEADERS
    workspace = request("POST", "/workspaces", 201, json={"name": prefix, "slug": f"{prefix.lower().replace(' ', '-')}-{ts}"}, headers=request_headers)
    project = request(
        "POST",
        f"/workspaces/{workspace['id']}/projects",
        201,
        json={"name": f"{prefix} Project", "description": "alpha eval"},
        headers=request_headers,
    )
    return workspace["id"], project["id"]


def create_markdown_resource(workspace_id: str, project_id: str, name: str, uri: str, content: str, headers: dict[str, str] | None = None) -> str:
    request_headers = headers or HEADERS
    resource = request(
        "POST",
        f"/workspaces/{workspace_id}/projects/{project_id}/resources",
        201,
        json={"type": "markdown", "name": name, "uri": uri, "source_config": {"content": content}},
        headers=request_headers,
    )
    run = request("POST", f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource['id']}/refresh", 202, headers=request_headers)
    wait_for_index_run(workspace_id, run["id"], headers=request_headers)
    return resource["id"]


def create_repo_resource(workspace_id: str, project_id: str, ts: int) -> tuple[str, str]:
    repo_url, commit = build_repo_fixture(ts)
    resource = request(
        "POST",
        f"/workspaces/{workspace_id}/projects/{project_id}/resources",
        201,
        json={
            "type": "git",
            "name": "Alpha Eval Repo",
            "uri": "git://alpha-eval-repo",
            "source_config": {"url": repo_url, "branch": "main"},
        },
        headers=HEADERS,
    )
    run = request("POST", f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource['id']}/refresh", 202, headers=HEADERS)
    wait_for_index_run(workspace_id, run["id"], headers=HEADERS)
    return resource["id"], commit


def resource_hit_counts(workspace_id: str, project_id: str) -> dict[str, int]:
    usage = request("GET", f"/workspaces/{workspace_id}/projects/{project_id}/resource-usage", 200, headers=HEADERS)
    return {str(row["resource_id"]): int(row.get("hit_count") or 0) for row in usage.get("resources", [])}


def evaluate_question(workspace_id: str, project_id: str, resources: dict[str, str], golden: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    top_k = int(golden.get("top_k", 8))
    expected_resource_ids = {resources[key] for key in golden.get("expected_resources", [])}
    unexpected_resource_ids = {resources[key] for key in golden.get("unexpected_resources", [])}
    before_agent_usage = resource_hit_counts(workspace_id, project_id)
    body = request(
        "POST",
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
        200,
        json={"query": golden["query"], "runtime": "hermes", "top_k": top_k, "max_chars": 6000},
        headers=HEADERS,
    )
    after_agent_usage = resource_hit_counts(workspace_id, project_id)
    agent_context_usage_delta = {
        resource_id: after_agent_usage.get(resource_id, 0) - before_agent_usage.get(resource_id, 0)
        for resource_id in expected_resource_ids
    }
    packet = request(
        "POST",
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packets",
        201,
        json={"query": golden["query"], "top_k": top_k, "max_chars": 6000},
        headers=HEADERS,
    )
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    context = body.get("context") or ""
    citations = body.get("citations") or []
    cited_resource_ids = {str(citation.get("resource_id")) for citation in citations}
    packet_items = packet.get("items") or []
    packet_resource_ids = {str(item.get("resource_id")) for item in packet_items}
    failures: list[str] = []
    if len(citations) < int(golden.get("min_citations", 1)):
        failures.append("missing_citations")
    for expected_text in golden.get("expected_texts", []):
        if expected_text.lower() not in context.lower():
            failures.append(f"missing_expected_text:{expected_text}")
    if golden.get("expected_text") and golden["expected_text"].lower() not in context.lower():
        failures.append("missing_expected_text")
    missing_resources = sorted(expected_resource_ids - cited_resource_ids)
    if missing_resources:
        failures.append(f"missing_expected_resources:{missing_resources}")
    missing_agent_usage = sorted(
        resource_id for resource_id, delta in agent_context_usage_delta.items() if delta < 1
    )
    if missing_agent_usage:
        failures.append(f"missing_agent_context_usage:{missing_agent_usage}")
    missing_packet_resources = sorted(expected_resource_ids - packet_resource_ids)
    if missing_packet_resources:
        failures.append(f"missing_packet_resources:{missing_packet_resources}")
    unexpected_citations = sorted(unexpected_resource_ids & cited_resource_ids)
    if unexpected_citations:
        failures.append(f"unexpected_citations:{unexpected_citations}")
    unexpected_packet_resources = sorted(unexpected_resource_ids & packet_resource_ids)
    if unexpected_packet_resources:
        failures.append(f"unexpected_packet_resources:{unexpected_packet_resources}")
    hit_quality = [
        {
            "rank": item.get("rank"),
            "resource_id": str(item.get("resource_id")),
            "path": item.get("path"),
            "score": item.get("score"),
            "lexical_score": item.get("lexical_score"),
            "vector_score": item.get("vector_score"),
            "graph_score": item.get("graph_score"),
            "rerank_score": item.get("rerank_score"),
            "content_hash": item.get("content_hash"),
            "snippet": (item.get("snippet") or "")[:240],
            "expected_resource": str(item.get("resource_id")) in expected_resource_ids,
            "unexpected_resource": str(item.get("resource_id")) in unexpected_resource_ids,
        }
        for item in packet_items
    ]
    return {
        "id": golden["id"],
        "query": golden["query"],
        "passed": not failures,
        "failure_reasons": failures,
        "latency_ms": latency_ms,
        "context_chars": len(context),
        "citation_count": len(citations),
        "cited_resource_ids": sorted(cited_resource_ids),
        "packet_item_count": len(packet_items),
        "packet_resource_ids": sorted(packet_resource_ids),
        "agent_context_usage_delta": agent_context_usage_delta,
        "hit_quality": hit_quality,
    }


def assert_freshness(workspace_id: str, project_id: str, resources: dict[str, str]) -> list[dict[str, Any]]:
    review = request("GET", f"/workspaces/{workspace_id}/projects/{project_id}/resource-review", 200, headers=HEADERS)
    items = review.get("resources") or []
    by_id = {item["resource"]["id"]: item for item in items}
    failures = []
    for key, resource_id in resources.items():
        item = by_id.get(resource_id)
        if not item:
            failures.append(f"missing_review:{key}")
            continue
        if item.get("freshness_status") != "fresh" or item.get("last_index_status") != "succeeded":
            failures.append(f"stale_or_unindexed:{key}:{item}")
    if failures:
        fail("freshness assertions failed: " + "; ".join(failures))
    return items


def assert_usage(workspace_id: str, project_id: str, resources: dict[str, str]) -> list[dict[str, Any]]:
    usage = request("GET", f"/workspaces/{workspace_id}/projects/{project_id}/resource-usage", 200, headers=HEADERS)
    rows = usage.get("resources") or []
    by_id = {row["resource_id"]: row for row in rows}
    missing = [key for key, resource_id in resources.items() if int(by_id.get(resource_id, {}).get("hit_count") or 0) < 1]
    if missing:
        fail(f"usage assertions failed; resources missing hits: {missing}; usage={usage}")
    return rows


def assert_no_cross_tenant_leak(workspace_id: str, project_id: str, foreign_marker: str, foreign_resource_id: str) -> dict[str, Any]:
    body = request(
        "POST",
        f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
        200,
        json={"query": foreign_marker, "runtime": "hermes", "top_k": 5, "max_chars": 3000},
        headers=HEADERS,
    )
    packet = request(
        "POST",
        f"/workspaces/{workspace_id}/projects/{project_id}/context-packets",
        201,
        json={"query": foreign_marker, "top_k": 5, "max_chars": 3000},
        headers=HEADERS,
    )
    context = body.get("context") or ""
    citations = body.get("citations") or []
    citation_resource_ids = {str(citation.get("resource_id")) for citation in citations}
    packet_resource_ids = {str(item.get("resource_id")) for item in packet.get("items", [])}
    leaked = foreign_marker.lower() in context.lower()
    if leaked or str(foreign_resource_id) in citation_resource_ids or str(foreign_resource_id) in packet_resource_ids:
        fail(
            "cross-tenant marker/resource leaked into primary project context: "
            + json.dumps(
                {
                    "agent_context": body,
                    "packet_resource_ids": sorted(packet_resource_ids),
                    "foreign_resource_id": foreign_resource_id,
                },
                indent=2,
            )
        )
    return {
        "query": foreign_marker,
        "passed": True,
        "citation_count": len(citations),
        "context_chars": len(context),
        "foreign_resource_id": foreign_resource_id,
        "packet_item_count": len(packet.get("items", [])),
    }


def main() -> None:
    report_path = Path(os.getenv("SOURCEBRIEF_ALPHA_EVAL_REPORT", str(DEFAULT_REPORT)))
    ts = int(time.time() * 1000)
    golden_questions = json.loads(DATASET.read_text())

    workspace_id, project_id = create_workspace_project("Alpha Eval", ts)
    repo_resource_id, repo_commit = create_repo_resource(workspace_id, project_id, ts)
    runbook_resource_id = create_markdown_resource(
        workspace_id,
        project_id,
        "Alpha Eval Runbook",
        "doc://alpha-eval-runbook",
        "# Alpha Eval Runbook\n\n"
        "alpha_runbook_escalation says: if agent context lacks citations, check /provider-health, inspect index runs, and reindex the resource. "
        "The alpharunbook42 marker anchors the runbook golden question.\n",
    )
    foreign_headers = {"X-User-Email": f"foreign-alpha-eval-{ts}@example.com"}
    foreign_ws, foreign_project = create_workspace_project("Foreign Alpha Eval", ts, headers=foreign_headers)
    foreign_resource_id = create_markdown_resource(
        foreign_ws,
        foreign_project,
        "Foreign Tenant Secret",
        "doc://foreign-tenant-secret",
        "# Foreign Tenant\n\nforbiddenleak42 must never appear in the primary project context.\n",
        headers=foreign_headers,
    )

    resources = {"repo": repo_resource_id, "runbook": runbook_resource_id}
    question_results = [evaluate_question(workspace_id, project_id, resources, golden) for golden in golden_questions]
    failures = [result for result in question_results if not result["passed"]]
    if failures:
        fail("golden question failures: " + json.dumps(failures, indent=2))

    freshness = assert_freshness(workspace_id, project_id, resources)
    usage = assert_usage(workspace_id, project_id, resources)
    isolation = assert_no_cross_tenant_leak(workspace_id, project_id, "forbiddenleak42", foreign_resource_id)
    latencies = [result["latency_ms"] for result in question_results]
    context_lengths = [result["context_chars"] for result in question_results]
    report = {
        "status": "passed",
        "api_url": BASE,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "repo_commit": repo_commit,
        "resources": resources,
        "questions": question_results,
        "isolation": isolation,
        "freshness": freshness,
        "usage": usage,
        "summary": {
            "question_count": len(question_results),
            "passed_count": sum(1 for result in question_results if result["passed"]),
            "max_latency_ms": max(latencies) if latencies else 0,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0,
            "max_context_chars": max(context_lengths) if context_lengths else 0,
            "avg_context_chars": round(sum(context_lengths) / len(context_lengths), 2) if context_lengths else 0,
            "failure_reasons": [],
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(f"Alpha eval passed: {len(question_results)} golden questions, report={report_path}")


if __name__ == "__main__":
    main()
