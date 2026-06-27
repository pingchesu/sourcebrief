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
DEFAULT_ARTIFACT_DIR = ROOT / "artifacts" / "sourcebrief-launch-50q"
TOKEN_RE = re.compile(r"(cs_[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9_.-]{12,})")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


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


def authenticate(api_url: str, env_file: dict[str, str]) -> tuple[dict[str, str], str | None, str]:
    token = env_value("SOURCEBRIEF_QA_TOKEN", env_file) or env_value("SOURCEBRIEF_TOKEN", env_file)
    if token:
        return {"Authorization": f"Bearer {token}"}, token, "bearer_token_env"
    email = env_value("SOURCEBRIEF_ADMIN_EMAIL", env_file, "admin@example.com")
    password = env_value("SOURCEBRIEF_ADMIN_PASSWORD", env_file)
    if email and password:
        body = request(api_url, "POST", "/auth/login", 200, json={"email": email, "password": password})
        session = str(body["session_token"])
        return {"Authorization": f"Bearer {session}"}, session, "session_login"
    if (env_value("SOURCEBRIEF_DEV_AUTH", env_file, "") or "").lower() in {"1", "true", "yes", "on"}:
        return {"X-User-Email": f"launch-50q-{int(time.time())}@example.com"}, None, "dev_header_local_fallback"
    raise RuntimeError("Need SOURCEBRIEF_ADMIN_PASSWORD, SOURCEBRIEF_TOKEN, or SOURCEBRIEF_DEV_AUTH=true for walkthrough auth")


def build_repo_bundle(ts: int) -> tuple[str, str]:
    bundle_root = ROOT / "tmp" / "qa-git-fixtures"
    bundle_root.mkdir(parents=True, exist_ok=True)
    bundle = bundle_root / f"sourcebrief-launch-50q-{ts}.bundle"
    if bundle.exists():
        bundle.unlink()
    head = run(["git", "rev-parse", "HEAD"], capture=True).strip()
    run(["git", "bundle", "create", str(bundle), "main"])
    return f"/qa-fixtures/{bundle.name}", head


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
    repo_url, commit = build_repo_bundle(ts)
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
                "branch": "main",
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
    failures: list[str] = []
    quality_warnings: list[str] = []
    if expected_result == "expected_unanswerable":
        if answer.get("outcome") not in {"unsupported_by_sources", "insufficient_evidence", None} and citations:
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
            "--workspace-id",
            ctx.workspace_id,
            "--project-id",
            ctx.project_id,
            "--resource-id",
            ctx.resource_id,
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


def capture_screenshots(ctx: WalkthroughContext, artifact_dir: Path, report_html: Path) -> list[dict[str, str]]:
    screenshots = artifact_dir / "screenshots"
    screenshots.mkdir(parents=True, exist_ok=True)
    script = artifact_dir / "capture_screenshots.cjs"
    script.write_text(
        """
const { chromium } = require(process.cwd() + '/node_modules/@playwright/test');
const fs = require('fs');
const path = require('path');
(async () => {
  const out = process.env.SB_SCREENSHOT_DIR;
  const apiBaseUrl = process.env.SB_API_URL;
  const sessionToken = process.env.SB_SESSION_TOKEN || '';
  const workspaceId = process.env.SB_WORKSPACE_ID;
  const projectId = process.env.SB_PROJECT_ID;
  const web = process.env.SB_WEB_URL;
  const report = process.env.SB_REPORT_HTML;
  const browser = await chromium.launch({ headless: true });
  const clean = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const cleanPage = await clean.newPage();
  await cleanPage.goto(`${web}/login`, { waitUntil: 'networkidle' });
  await cleanPage.screenshot({ path: path.join(out, '01-login.png'), fullPage: true });
  await clean.close();
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(({ apiBaseUrl, sessionToken, workspaceId, projectId }) => {
    window.localStorage.setItem('sourcebrief.platform.settings.v2', JSON.stringify({ apiBaseUrl, workspaceId, projectId }));
    if (sessionToken) window.sessionStorage.setItem('sourcebrief.platform.session.v2', sessionToken);
  }, { apiBaseUrl, sessionToken, workspaceId, projectId });
  const page = await context.newPage();
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
})();
""",
        encoding="utf-8",
    )
    env = os.environ.copy()
    env.update(
        {
            "SB_SCREENSHOT_DIR": str(screenshots),
            "SB_API_URL": ctx.api_url,
            "SB_WEB_URL": ctx.web_url,
            "SB_SESSION_TOKEN": ctx.session_token or "",
            "SB_WORKSPACE_ID": ctx.workspace_id,
            "SB_PROJECT_ID": ctx.project_id,
            "SB_REPORT_HTML": str(report_html.resolve()),
        }
    )
    run(["node", str(script)], cwd=ROOT / "apps" / "web", env=env)
    return [{"label": path.stem, "path": str(path.relative_to(artifact_dir))} for path in sorted(screenshots.glob("*.png"))]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--question-bank", type=Path, default=DEFAULT_QUESTION_BANK)
    parser.add_argument("--question-limit", type=int, default=50)
    parser.add_argument("--skip-compose", action="store_true", help="assume API/web services are already running")
    parser.add_argument("--skip-screenshots", action="store_true")
    parser.add_argument("--api-url", default=os.getenv("SOURCEBRIEF_API_URL") or os.getenv("API_URL") or "http://localhost:18000")
    parser.add_argument("--web-url", default=os.getenv("SOURCEBRIEF_WEB_URL") or os.getenv("WEB_URL") or "http://localhost:3105")
    args = parser.parse_args()

    artifact_dir = args.artifact_dir.resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    env_file = load_env_file(ROOT / ".env")
    if not args.skip_compose:
        run(["make", "compose-up"])
    wait_http(f"{args.api_url}/readyz")
    wait_http(f"{args.web_url}/api/health")

    headers, session_token, auth_mode = authenticate(args.api_url, env_file)
    ts = int(time.time())
    workspace_id, workspace_name, project_id, project_name, resource_id, resource_name, index_run, commit = create_walkthrough_project(args.api_url, headers, ts)
    ctx = WalkthroughContext(args.api_url, args.web_url, headers, session_token, auth_mode, workspace_id, workspace_name, project_id, project_name, resource_id, resource_name, index_run)
    questions = load_questions(args.question_bank, args.question_limit)
    results = [evaluate_question(args.api_url, ctx, question) for question in questions]
    scenario_results = run_scenarios(args.api_url, ctx)
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
            "passed": len(results) - len(failed),
            "failed": len(failed),
            "answer_quality_warning_count": len(quality_warnings),
            "verdict": "PASS" if not failed and index_run.get("status") == "succeeded" else "RISK",
            "limitations": ["Answer-quality is mechanically screened; human signoff should review the citation previews before launch claims."],
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
    if not args.skip_screenshots:
        report["screenshots"] = capture_screenshots(ctx, artifact_dir, report_html)
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
    return 0 if report["summary"]["verdict"] in {"PASS", "RISK"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
