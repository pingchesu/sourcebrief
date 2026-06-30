#!/usr/bin/env python3
"""Run a screenshot-backed 50-question SourceBrief launch walkthrough.

This is a product proof runner, not a unit benchmark. It can start the local
Compose stack, create a human-named workspace/project, import a representative
real project (the current SourceBrief repository as a git bundle by default),
run a fixed 50-question manifest through agent-context, exercise agent/runtime
scenarios, and capture sanitized browser screenshots.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUESTION_BANK = ROOT / "examples" / "sourcebrief-launch-50q" / "questions.json"
TOKEN_RE = re.compile(r"(cs_[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9_.-]{12,})")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
PASS_THRESHOLDS: dict[str, Any] = {
    "required_question_count": 50,
    "max_wrong_resource_citations": 0,
    "max_unsupported_final_answer_claims": 0,
    "required_screenshot_count": 7,
    "require_browser_console_network_transcript": True,
    "max_browser_console_errors": 0,
    "max_browser_bad_responses": 0,
}


@dataclass
class WalkthroughContext:
    api_url: str
    web_url: str
    headers: dict[str, str]
    session_token: str | None
    auth_mode: str
    workspace_id: str
    workspace_name: str
    project_id: str
    project_name: str
    resource_id: str
    resource_name: str
    index_run: dict[str, Any]


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items() if "token" not in k.lower() and "password" not in k.lower()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        value = TOKEN_RE.sub("<redacted-token>", value)
        return UUID_RE.sub("<id>", value)
    return value


def log(message: str) -> None:
    print(message, flush=True)


def run(cmd: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None, capture: bool = False) -> str:
    log("$ " + " ".join(cmd))
    completed = subprocess.run(cmd, cwd=cwd, env=env or os.environ.copy(), text=True, capture_output=capture, check=True)
    return completed.stdout if capture else ""


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env_value(name: str, env_file: dict[str, str], default: str | None = None) -> str | None:
    return os.getenv(name) or env_file.get(name) or default


def configured_url(kind: str, env_file: dict[str, str]) -> str:
    if kind == "api":
        explicit = env_value("SOURCEBRIEF_API_URL", env_file) or env_value("API_URL", env_file)
        port = env_value("SOURCEBRIEF_API_PORT", env_file) or env_value("CONTEXTSMITH_API_PORT", env_file) or "18000"
    else:
        explicit = env_value("SOURCEBRIEF_WEB_URL", env_file) or env_value("WEB_URL", env_file)
        port = env_value("SOURCEBRIEF_WEB_PORT", env_file) or env_value("CONTEXTSMITH_WEB_PORT", env_file) or "13000"
    return (explicit or f"http://localhost:{port}").rstrip("/")


def default_artifact_dir(ts: int) -> Path:
    return ROOT / "artifacts" / f"sourcebrief-launch-50q-{ts}"


def sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def failure_result(question: dict[str, Any], failure: str, latency_ms: float = 0.0) -> dict[str, Any]:
    return {
        "id": str(question.get("id", "unknown")),
        "category": question.get("category"),
        "query": str(question.get("query", "")),
        "expected_result": question.get("expected_result", "pass"),
        "mechanical_status": "fail",
        "failures": [failure],
        "answer_quality_warnings": [],
        "latency_ms": latency_ms,
        "citation_count": 0,
        "answer_outcome": None,
        "quality_note": "question failed before citation evidence could be evaluated",
        "citation_preview": [],
        "coverage_warnings": [],
    }


def launch_verdict(
    *,
    index_status: str | None,
    results: list[dict[str, Any]],
    quality_warnings: list[dict[str, Any]],
    scenario_results: dict[str, Any],
    negative_control_count: int,
    browser_capture: dict[str, Any] | None = None,
    thresholds: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    thresholds = thresholds or PASS_THRESHOLDS
    blockers: list[str] = []
    if index_status != "succeeded":
        blockers.append(f"index_status:{index_status}")
    required_question_count = int(thresholds.get("required_question_count", 0) or 0)
    if required_question_count and len(results) < required_question_count:
        blockers.append(f"incomplete_question_coverage:{len(results)}/{required_question_count}")
    failed_questions = [item["id"] for item in results if item.get("mechanical_status") != "pass"]
    if failed_questions:
        blockers.append("question_failures:" + ",".join(failed_questions[:10]))
    wrong_resource_citations = sum(int(item.get("wrong_resource_citation_count", 0) or 0) for item in results)
    max_wrong_resource = int(thresholds.get("max_wrong_resource_citations", 0) or 0)
    if wrong_resource_citations > max_wrong_resource:
        blockers.append(f"wrong_resource_citations:{wrong_resource_citations}>{max_wrong_resource}")
    unsupported_claims = sum(1 for item in results if "negative_control_answered_too_strongly" in (item.get("failures") or []))
    max_unsupported_claims = int(thresholds.get("max_unsupported_final_answer_claims", 0) or 0)
    if unsupported_claims > max_unsupported_claims:
        blockers.append(f"unsupported_final_answer_claims:{unsupported_claims}>{max_unsupported_claims}")
    if negative_control_count <= 0:
        blockers.append("missing_expected_unanswerable_negative_control")
    if scenario_results.get("mcp_context_is_error"):
        blockers.append("mcp_context_scenario_failed")
    if scenario_results.get("grep_code_is_error"):
        blockers.append("grep_code_scenario_failed")
    if scenario_results.get("cli_search_exit_code") not in {0, None}:
        blockers.append("cli_search_scenario_failed")
    if browser_capture is not None:
        required_screenshots = int(thresholds.get("required_screenshot_count", 0) or 0)
        screenshot_count = len(browser_capture.get("screenshots") or [])
        if required_screenshots and screenshot_count < required_screenshots:
            blockers.append(f"missing_screenshots:{screenshot_count}/{required_screenshots}")
        transcript = browser_capture.get("console_network") or {}
        if thresholds.get("require_browser_console_network_transcript") and not transcript.get("path"):
            blockers.append("missing_browser_console_network_transcript")
        if int(transcript.get("page_error_count", 0) or 0) > 0:
            blockers.append(f"browser_page_errors:{transcript.get('page_error_count')}")
        if int(transcript.get("failed_request_count", 0) or 0) > 0:
            blockers.append(f"browser_failed_requests:{transcript.get('failed_request_count')}")
        console_errors = int(transcript.get("console_error_count", 0) or 0)
        max_console_errors = int(thresholds.get("max_browser_console_errors", 0) or 0)
        if console_errors > max_console_errors:
            blockers.append(f"browser_console_errors:{console_errors}>{max_console_errors}")
        bad_responses = int(transcript.get("bad_response_count", 0) or 0)
        max_bad_responses = int(thresholds.get("max_browser_bad_responses", 0) or 0)
        if bad_responses > max_bad_responses:
            blockers.append(f"browser_bad_responses:{bad_responses}>{max_bad_responses}")
    if blockers:
        return "BLOCK", blockers
    if browser_capture is None:
        return "RISK", ["browser_console_network_proof_not_evaluated"]
    if quality_warnings:
        return "RISK", ["answer_quality_warnings_present"]
    return "PASS", []


def run_question_safely(api_url: str, ctx: WalkthroughContext, question: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        return evaluate_question(api_url, ctx, question)
    except Exception as exc:  # noqa: BLE001 - launch evidence must preserve first question failure
        return failure_result(question, f"exception:{type(exc).__name__}:{str(exc)[:300]}", round((time.perf_counter() - started) * 1000, 2))


def run_scenarios_safely(api_url: str, ctx: WalkthroughContext) -> dict[str, Any]:
    try:
        return run_scenarios(api_url, ctx)
    except Exception as exc:  # noqa: BLE001 - keep report generation alive for first-failure evidence
        return {
            "scenario_exception": f"{type(exc).__name__}:{str(exc)[:500]}",
            "mcp_context_is_error": True,
            "grep_code_is_error": True,
            "cli_search_exit_code": 1,
            "cli_search_has_output": False,
            "cli_search_stderr": redact(str(exc)[-500:]),
        }


def request(api_url: str, method: str, path: str, expected: int, *, headers: dict[str, str] | None = None, **kwargs: Any) -> Any:
    response = requests.request(method, f"{api_url}{path}", headers=headers or {}, timeout=60, **kwargs)
    if response.status_code != expected:
        raise RuntimeError(f"{method} {path} expected {expected}, got {response.status_code}: {response.text[:800]}")
    if not response.content:
        return None
    try:
        return response.json()
    except ValueError:
        return response.text


def wait_http(url: str, timeout_s: int = 120) -> None:
    deadline = time.time() + timeout_s
    last_error = ""
    while time.time() < deadline:
        try:
            response = requests.get(url, timeout=5)
            if response.status_code < 500:
                return
            last_error = f"HTTP {response.status_code}: {response.text[:200]}"
        except Exception as exc:  # noqa: BLE001 - report last readiness failure
            last_error = str(exc)
        time.sleep(2)
    raise RuntimeError(f"timed out waiting for {url}: {last_error}")


def dev_auth_enabled(env_file: dict[str, str]) -> bool:
    return (env_value("SOURCEBRIEF_DEV_AUTH", env_file, "") or "").lower() in {"1", "true", "yes", "on"}


def authenticate(api_url: str, env_file: dict[str, str]) -> tuple[dict[str, str], str | None, str]:
    token = env_value("SOURCEBRIEF_QA_TOKEN", env_file) or env_value("SOURCEBRIEF_TOKEN", env_file)
    if token:
        return {"Authorization": f"Bearer {token}"}, token, "bearer_token_env"
    email = env_value("SOURCEBRIEF_ADMIN_EMAIL", env_file, "admin@example.com")
    password = env_value("SOURCEBRIEF_ADMIN_PASSWORD", env_file)
    if email and password:
        try:
            body = request(api_url, "POST", "/auth/login", 200, json={"email": email, "password": password})
            session = str(body["session_token"])
            return {"Authorization": f"Bearer {session}"}, session, "session_login"
        except RuntimeError:
            if not dev_auth_enabled(env_file):
                raise
    if dev_auth_enabled(env_file):
        return {"X-User-Email": f"launch-50q-{int(time.time())}@example.com"}, None, "dev_header_local_fallback"
    raise RuntimeError("Need SOURCEBRIEF_ADMIN_PASSWORD, SOURCEBRIEF_TOKEN, or SOURCEBRIEF_DEV_AUTH=true for walkthrough auth")


def build_repo_bundle(ts: int) -> tuple[str, str, str]:
    bundle_root = ROOT / "tmp" / "qa-git-fixtures"
    bundle_root.mkdir(parents=True, exist_ok=True)
    bundle = bundle_root / f"sourcebrief-launch-50q-{ts}.bundle"
    if bundle.exists():
        bundle.unlink()
    head = run(["git", "rev-parse", "HEAD"], capture=True).strip()
    bundle_branch = f"sourcebrief-launch-head-{ts}"
    ref = f"refs/heads/{bundle_branch}"
    try:
        run(["git", "update-ref", ref, "HEAD"])
        run(["git", "bundle", "create", str(bundle), ref])
    finally:
        run(["git", "update-ref", "-d", ref])
    return f"/qa-fixtures/{bundle.name}", head, bundle_branch


def wait_index(api_url: str, workspace_id: str, run_id: str, headers: dict[str, str], timeout_s: int = 240) -> dict[str, Any]:
    deadline = time.time() + timeout_s
    latest: dict[str, Any] = {"status": "queued"}
    while time.time() < deadline:
        latest = request(api_url, "GET", f"/workspaces/{workspace_id}/index-runs/{run_id}", 200, headers=headers)
        if latest.get("status") in {"succeeded", "failed"}:
            break
        time.sleep(2)
    return latest


def create_walkthrough_project(api_url: str, headers: dict[str, str], ts: int) -> tuple[str, str, str, str, str, str, dict[str, Any], str]:
    workspace_name = f"50Q Launch Walkthrough {ts}"
    project_name = "SourceBrief 50Q Product Walkthrough"
    workspace = request(api_url, "POST", "/workspaces", 201, headers=headers, json={"name": workspace_name, "slug": f"launch-50q-{ts}"})
    project = request(api_url, "POST", f"/workspaces/{workspace['id']}/projects", 201, headers=headers, json={"name": project_name, "description": "Screenshot-backed 50-question launch walkthrough"})
    repo_url, commit, repo_branch = build_repo_bundle(ts)
    resource_name = "SourceBrief repository launch import"
    resource = request(
        api_url,
        "POST",
        f"/workspaces/{workspace['id']}/projects/{project['id']}/resources",
        201,
        headers=headers,
        json={
            "type": "git",
            "name": resource_name,
            "uri": "git://sourcebrief-launch-50q",
            "source_config": {
                "url": repo_url,
                "branch": repo_branch,
                "max_repo_files": 320,
                "max_file_bytes": 120000,
                "max_repo_bytes": 18000000,
                "import_profile": "launch-50q-bounded-real-repo",
            },
        },
    )
    refresh = request(api_url, "POST", f"/workspaces/{workspace['id']}/projects/{project['id']}/resources/{resource['id']}/refresh", 202, headers=headers)
    index_run = wait_index(api_url, workspace["id"], refresh["id"], headers)
    return workspace["id"], workspace_name, project["id"], project_name, resource["id"], resource_name, index_run, commit


def load_questions(path: Path, limit: int | None) -> list[dict[str, Any]]:
    bank = json.loads(path.read_text(encoding="utf-8"))
    questions = bank.get("questions") or []
    if limit is not None:
        questions = questions[:limit]
    if not questions:
        raise RuntimeError(f"no questions found in {path}")
    return questions


def evaluate_question(api_url: str, ctx: WalkthroughContext, question: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    payload = {
        "query": question["query"],
        "runtime": "hermes",
        "resource_ids": [ctx.resource_id],
        "top_k": int(question.get("top_k", 8)),
        "max_chars": int(question.get("max_chars", 9000)),
        "include_code_symbols": bool(question.get("include_code_symbols", True)),
    }
    body = request(api_url, "POST", f"/workspaces/{ctx.workspace_id}/projects/{ctx.project_id}/agent-context", 200, headers=ctx.headers, json=payload)
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    citations = body.get("citations") or []
    answer = body.get("answer") if isinstance(body.get("answer"), dict) else {}
    context = str(body.get("context") or "")
    expected_terms = [str(term) for term in question.get("expected_terms", [])]
    missing_terms = [term for term in expected_terms if term.lower() not in context.lower() and term.lower() not in json.dumps(answer).lower()]
    expected_result = question.get("expected_result", "pass")
    wrong_resource_citations = [citation for citation in citations if citation.get("resource_id") and str(citation.get("resource_id")) != ctx.resource_id]
    failures: list[str] = []
    quality_warnings: list[str] = []
    if expected_result == "expected_unanswerable":
        unsupported_outcomes = {"unsupported_by_sources", "insufficient_evidence"}
        if answer.get("outcome") not in unsupported_outcomes:
            failures.append("negative_control_answered_too_strongly")
    else:
        if len(citations) < int(question.get("min_citations", 1)):
            failures.append("missing_citation")
        if missing_terms:
            quality_warnings.append("missing_expected_terms:" + ",".join(missing_terms[:3]))
    return {
        "id": question["id"],
        "category": question.get("category"),
        "query": question["query"],
        "expected_result": expected_result,
        "mechanical_status": "pass" if not failures else "fail",
        "failures": failures,
        "answer_quality_warnings": quality_warnings,
        "latency_ms": latency_ms,
        "citation_count": len(citations),
        "wrong_resource_citation_count": len(wrong_resource_citations),
        "answer_outcome": answer.get("outcome"),
        "quality_note": "citation-backed context returned" if citations else "no citation evidence returned",
        "citation_preview": redact(citations[:3]),
        "coverage_warnings": redact(body.get("coverage_warnings") or []),
    }


def run_scenarios(api_url: str, ctx: WalkthroughContext) -> dict[str, Any]:
    mcp_tools = request(api_url, "POST", f"/mcp/{ctx.workspace_id}/{ctx.project_id}", 200, headers=ctx.headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    mcp_context = request(
        api_url,
        "POST",
        f"/mcp/{ctx.workspace_id}/{ctx.project_id}",
        200,
        headers=ctx.headers,
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "sourcebrief.get_agent_context", "arguments": {"query": "Where is SourceBrief CLI skill install implemented?", "resource_ids": [ctx.resource_id], "runtime": "hermes"}}},
    )
    grep_code = request(
        api_url,
        "POST",
        f"/mcp/{ctx.workspace_id}/{ctx.project_id}",
        200,
        headers=ctx.headers,
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "sourcebrief.grep_code", "arguments": {"pattern": "skill install", "resource_ids": [ctx.resource_id], "path_glob": "packages/cli/**", "max_matches": 5}}},
    )
    cli = subprocess.run(
        [
            str(ROOT / ".venv" / "bin" / "sourcebrief"),
            "--json",
            "--api-url",
            api_url,
            *( ["--token", ctx.session_token] if ctx.session_token else ["--email", ctx.headers.get("X-User-Email", "launch@example.com")] ),
            "search",
            "--workspace",
            ctx.workspace_name,
            "--project",
            ctx.project_name,
            "--resource",
            ctx.resource_name,
            "--query",
            "SourceBrief runtime install plan",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=60,
    )
    return {
        "mcp_tool_count": len(mcp_tools.get("result", {}).get("tools", [])),
        "mcp_context_is_error": bool(mcp_context.get("result", {}).get("isError")),
        "grep_code_is_error": bool(grep_code.get("result", {}).get("isError")),
        "cli_search_exit_code": cli.returncode,
        "cli_search_has_output": bool(cli.stdout.strip()),
        "cli_search_stderr": redact(cli.stderr[-500:]),
    }


def write_report_html(report: dict[str, Any], output: Path) -> None:
    rows = "\n".join(
        f"<tr><td>{html.escape(item['id'])}</td><td>{html.escape(item.get('category') or '')}</td><td>{html.escape(item['mechanical_status'])}</td><td>{item['citation_count']}</td><td>{html.escape('; '.join(item.get('failures') or []))}</td><td>{html.escape('; '.join(item.get('answer_quality_warnings') or []))}</td></tr>"
        for item in report["questions"]
    )
    body = f"""<!doctype html><html><head><meta charset='utf-8'><title>SourceBrief 50Q Walkthrough Report</title>
<style>body{{font-family:Inter,Arial,sans-serif;background:#0f172a;color:#e2e8f0;margin:32px}}.card{{background:#111827;border:1px solid #334155;border-radius:16px;padding:20px;margin:16px 0}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #334155;padding:8px;text-align:left}}.pass{{color:#86efac}}.fail{{color:#fca5a5}}</style></head><body>
<h1>SourceBrief 50Q Launch Walkthrough</h1>
<div class='card'><strong>Verdict:</strong> <span class='{html.escape(report['summary']['verdict'].lower())}'>{html.escape(report['summary']['verdict'])}</span><br>
<strong>Workspace:</strong> {html.escape(report['setup']['workspace_name'])}<br><strong>Project:</strong> {html.escape(report['setup']['project_name'])}<br><strong>Resource:</strong> {html.escape(report['setup']['resource_name'])}</div>
<div class='card'><h2>Summary</h2><pre>{html.escape(json.dumps(report['summary'], indent=2))}</pre></div>
<div class='card'><h2>Questions</h2><table><thead><tr><th>ID</th><th>Category</th><th>Status</th><th>Citations</th><th>Mechanical failures</th><th>Quality warnings</th></tr></thead><tbody>{rows}</tbody></table></div>
</body></html>"""
    output.write_text(body, encoding="utf-8")


def screenshot_inventory(screenshots: Path, artifact_dir: Path) -> list[dict[str, Any]]:
    return [
        {"label": path.stem, "path": str(path.relative_to(artifact_dir)), "sha256": sha256_file(path), "bytes": path.stat().st_size}
        for path in sorted(screenshots.glob("*.png"))
    ]


def capture_screenshots(ctx: WalkthroughContext, artifact_dir: Path, report_html: Path) -> dict[str, Any]:
    screenshots = artifact_dir / "screenshots"
    browser_dir = artifact_dir / "browser"
    screenshots.mkdir(parents=True, exist_ok=True)
    browser_dir.mkdir(parents=True, exist_ok=True)
    transcript = browser_dir / "console-network.json"
    script = artifact_dir / "capture_screenshots.cjs"
    script.write_text(
        r"""
const { chromium } = require(process.cwd() + '/node_modules/@playwright/test');
const fs = require('fs');
const path = require('path');
function redact(value) {
  if (typeof value !== 'string') return value;
  return value
    .replace(/(cs_[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9_.-]{12,})/g, '<redacted-token>')
    .replace(/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}/g, '<id>')
    .replace(new RegExp(process.cwd().replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g'), '<repo>');
}
function cleanEntry(entry) {
  return Object.fromEntries(Object.entries(entry).map(([key, value]) => [key, redact(String(value))]));
}
(async () => {
  const out = process.env.SB_SCREENSHOT_DIR;
  const transcript = process.env.SB_BROWSER_TRANSCRIPT;
  const apiBaseUrl = process.env.SB_API_URL;
  const sessionToken = process.env.SB_SESSION_TOKEN || '';
  const workspaceId = process.env.SB_WORKSPACE_ID;
  const projectId = process.env.SB_PROJECT_ID;
  const web = process.env.SB_WEB_URL;
  const report = process.env.SB_REPORT_HTML;
  const events = { runner: { name: 'playwright-chromium', viewport: '1440x1000' }, console: [], pageErrors: [], failedRequests: [], badResponses: [] };
  const browser = await chromium.launch({ headless: true });
  async function instrument(page) {
    page.on('console', msg => events.console.push(cleanEntry({ type: msg.type(), text: msg.text(), url: msg.location().url || '' })));
    page.on('pageerror', err => events.pageErrors.push(cleanEntry({ message: err.message, stack: err.stack || '' })));
    page.on('requestfailed', req => events.failedRequests.push(cleanEntry({ method: req.method(), url: req.url(), failure: req.failure()?.errorText || '' })));
    page.on('response', res => {
      if (res.status() >= 400) events.badResponses.push(cleanEntry({ status: res.status(), url: res.url() }));
    });
  }
  const clean = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const cleanPage = await clean.newPage();
  await instrument(cleanPage);
  await cleanPage.goto(`${web}/login`, { waitUntil: 'networkidle' });
  await cleanPage.screenshot({ path: path.join(out, '01-login.png'), fullPage: true });
  await clean.close();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(({ apiBaseUrl, sessionToken, workspaceId, projectId }) => {
    window.localStorage.setItem('sourcebrief.platform.settings.v2', JSON.stringify({ apiBaseUrl, workspaceId, projectId }));
    if (sessionToken) window.sessionStorage.setItem('sourcebrief.platform.session.v2', sessionToken);
  }, { apiBaseUrl, sessionToken, workspaceId, projectId });
  const page = await context.newPage();
  await instrument(page);
  const shots = [
    ['02-dashboard.png', '/'],
    ['03-selection-settings.png', '/config'],
    ['04-import-sources.png', '/sources'],
    ['05-workbench-citations.png', '/workbench'],
    ['06-agent-profile.png', '/agent-profile'],
  ];
  for (const [file, route] of shots) {
    await page.goto(`${web}${route}`, { waitUntil: 'networkidle' });
    await page.screenshot({ path: path.join(out, file), fullPage: true });
  }
  await page.goto(`file://${report}`, { waitUntil: 'load' });
  await page.screenshot({ path: path.join(out, '07-eval-report.png'), fullPage: true });
  await browser.close();
  fs.writeFileSync(transcript, JSON.stringify(events, null, 2) + '\n');
})();
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "SB_SCREENSHOT_DIR": str(screenshots),
            "SB_BROWSER_TRANSCRIPT": str(transcript),
            "SB_API_URL": ctx.api_url,
            "SB_WEB_URL": ctx.web_url,
            "SB_SESSION_TOKEN": ctx.session_token or "",
            "SB_WORKSPACE_ID": ctx.workspace_id,
            "SB_PROJECT_ID": ctx.project_id,
            "SB_REPORT_HTML": str(report_html.resolve()),
        }
    )
    run(["node", str(script)], cwd=ROOT / "apps" / "web", env=env)
    transcript_body = json.loads(transcript.read_text(encoding="utf-8"))
    console_entries = transcript_body.get("console") or []
    inventory = screenshot_inventory(screenshots, artifact_dir)
    return {
        "screenshots": inventory,
        "console_network": {
            "path": str(transcript.relative_to(artifact_dir)),
            "sha256": sha256_file(transcript),
            "console_count": len(console_entries),
            "console_error_count": sum(1 for entry in console_entries if entry.get("type") == "error"),
            "page_error_count": len(transcript_body.get("pageErrors") or []),
            "failed_request_count": len(transcript_body.get("failedRequests") or []),
            "bad_response_count": len(transcript_body.get("badResponses") or []),
            "runner": transcript_body.get("runner") or {},
        },
    }


def refresh_report_screenshot(artifact_dir: Path, report_html: Path) -> list[dict[str, Any]]:
    screenshots = artifact_dir / "screenshots"
    script = artifact_dir / "capture_final_report.cjs"
    script.write_text(
        r"""
const { chromium } = require(process.cwd() + '/node_modules/@playwright/test');
const path = require('path');
(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  await page.goto(`file://${process.env.SB_REPORT_HTML}`, { waitUntil: 'load' });
  await page.screenshot({ path: path.join(process.env.SB_SCREENSHOT_DIR, '07-eval-report.png'), fullPage: true });
  await browser.close();
})();
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update({"SB_SCREENSHOT_DIR": str(screenshots), "SB_REPORT_HTML": str(report_html.resolve())})
    run(["node", str(script)], cwd=ROOT / "apps" / "web", env=env)
    return screenshot_inventory(screenshots, artifact_dir)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--question-bank", type=Path, default=DEFAULT_QUESTION_BANK)
    parser.add_argument("--question-limit", type=int, default=50)
    parser.add_argument("--skip-compose", action="store_true", help="assume API/web services are already running")
    parser.add_argument("--skip-screenshots", action="store_true")
    parser.add_argument("--allow-risk", action="store_true", help="return 0 for RISK verdicts; BLOCK always exits nonzero")
    parser.add_argument("--api-url")
    parser.add_argument("--web-url")
    args = parser.parse_args()

    ts = int(time.time())
    env_file = load_env_file(ROOT / ".env")
    args.api_url = (args.api_url or configured_url("api", env_file)).rstrip("/")
    args.web_url = (args.web_url or configured_url("web", env_file)).rstrip("/")
    artifact_dir = (args.artifact_dir or default_artifact_dir(ts)).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if not args.skip_compose:
        run(["make", "compose-up"])
    wait_http(f"{args.api_url}/readyz")
    wait_http(f"{args.web_url}/api/health")

    headers, session_token, auth_mode = authenticate(args.api_url, env_file)
    if session_token is None and not args.skip_screenshots:
        raise RuntimeError("browser screenshot proof requires a /auth/login session token; set admin credentials or pass --skip-screenshots for API-only RISK evidence")
    workspace_id, workspace_name, project_id, project_name, resource_id, resource_name, index_run, commit = create_walkthrough_project(args.api_url, headers, ts)
    ctx = WalkthroughContext(args.api_url, args.web_url, headers, session_token, auth_mode, workspace_id, workspace_name, project_id, project_name, resource_id, resource_name, index_run)
    questions = load_questions(args.question_bank, args.question_limit)
    question_bank_sha256 = sha256_file(args.question_bank)
    negative_control_count = sum(1 for question in questions if question.get("expected_result") == "expected_unanswerable")
    results = [run_question_safely(args.api_url, ctx, question) for question in questions]
    scenario_results = run_scenarios_safely(args.api_url, ctx)
    failed = [item for item in results if item["mechanical_status"] != "pass"]
    quality_warnings = [item for item in results if item.get("answer_quality_warnings")]
    report = {
        "schema_version": "sourcebrief.launch-50q-walkthrough-report.v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "setup": redact(
            {
                "api_url": args.api_url,
                "web_url": args.web_url,
                "auth_mode": auth_mode,
                "workspace_id": workspace_id,
                "workspace_name": workspace_name,
                "project_id": project_id,
                "project_name": project_name,
                "resource_id": resource_id,
                "resource_name": resource_name,
                "repo_commit": commit,
                "index_run": index_run,
            }
        ),
        "summary": {
            "question_count": len(results),
            "negative_control_count": negative_control_count,
            "passed": len(results) - len(failed),
            "failed": len(failed),
            "answer_quality_warning_count": len(quality_warnings),
            "verdict": "PENDING",
            "verdict_reasons": [],
            "predeclared_thresholds": PASS_THRESHOLDS,
            "limitations": ["Answer-quality is mechanically screened; human signoff should review the citation previews before launch claims."],
        },
        "question_bank": {
            "path": str(args.question_bank),
            "sha256": question_bank_sha256,
            "selected_question_count": len(results),
        },
        "scenarios": redact(scenario_results),
        "questions": redact(results),
        "issues_to_open": [
            {
                "title": f"50Q answer-quality warning: {item['id']} missing expected terms",
                "labels": ["launch-50q", "answer-quality"],
                "question_id": item["id"],
                "query": item["query"],
                "warnings": item.get("answer_quality_warnings") or [],
            }
            for item in quality_warnings
        ],
    }
    report_json = artifact_dir / "report.json"
    report_md = artifact_dir / "README.md"
    report_html = artifact_dir / "report.html"
    report_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    write_report_html(report, report_html)
    browser_capture: dict[str, Any] | None = None
    if not args.skip_screenshots:
        browser_capture = capture_screenshots(ctx, artifact_dir, report_html)
        report["browser"] = browser_capture
    verdict, verdict_reasons = launch_verdict(
        index_status=index_run.get("status"),
        results=results,
        quality_warnings=quality_warnings,
        scenario_results=scenario_results,
        negative_control_count=negative_control_count,
        browser_capture=browser_capture,
    )
    report["summary"]["verdict"] = verdict
    report["summary"]["verdict_reasons"] = verdict_reasons
    write_report_html(report, report_html)
    if browser_capture is not None:
        browser_capture["screenshots"] = refresh_report_screenshot(artifact_dir, report_html)
        report["browser"] = browser_capture
    report_json.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    report_md.write_text(
        "# SourceBrief 50Q launch walkthrough\n\n"
        f"- Verdict: `{report['summary']['verdict']}`\n"
        f"- Questions: {report['summary']['passed']}/{report['summary']['question_count']} passed\n"
        f"- Workspace: `{workspace_name}`\n"
        f"- Project: `{project_name}`\n"
        f"- Resource: `{resource_name}`\n"
        "- Screenshots: `screenshots/*.png`\n"
        "\nSee `report.json` for redacted structured evidence.\n",
        encoding="utf-8",
    )
    log(f"50Q walkthrough complete: {report_json}")
    if report["summary"]["verdict"] == "PASS":
        return 0
    if report["summary"]["verdict"] == "RISK" and args.allow_risk:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
