#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_SHARED = REPO_ROOT / "packages" / "shared"
if str(PACKAGES_SHARED) not in sys.path:
    sys.path.insert(0, str(PACKAGES_SHARED))

from sourcebrief_shared.eval_manifest import (  # noqa: E402
    sha256_digest,
    validate_grade_report,
    validate_manifest,
)

QUESTION_BANK = REPO_ROOT / "demo" / "awesome_agent_harness_50q" / "questions.json"
SOURCE_LIST_RAW_URL = "https://raw.githubusercontent.com/Picrew/awesome-agent-harness/main/README.md"
DEV_EMAIL = "demo@example.com"

SECRET_RE = re.compile(r"(?i)(authorization|token|secret|password|api[_-]?key|bearer)\s*[:=]\s*([^\s,}\]]+)")


def redact_text(value: str) -> str:
    value = SECRET_RE.sub(lambda m: f"{m.group(1)}=<redacted>", value)
    value = re.sub(r"Bearer\s+[A-Za-z0-9._~+\-/=]+", "Bearer <redacted>", value)
    return value


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        result: dict[str, Any] = {}
        for key, value in obj.items():
            if any(marker in key.lower() for marker in ("token", "secret", "password", "authorization", "api_key", "apikey")):
                result[key] = "<redacted>"
            else:
                result[key] = redact(value)
        return result
    if isinstance(obj, list):
        return [redact(item) for item in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


class ApiClient:
    def __init__(self, api_url: str, email: str = DEV_EMAIL, token: str | None = None, timeout: float = 60.0) -> None:
        self.api_url = api_url.rstrip("/")
        self.email = email
        self.token = token
        self.timeout = timeout

    def request(self, method: str, path: str, *, body: dict[str, Any] | None = None, expected: set[int] | None = None) -> Any:
        expected = expected or {200}
        data = None
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        else:
            headers["X-User-Email"] = self.email
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.api_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - local/operator-provided API URL
                payload = response.read()
                status = response.status
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"failed to reach {self.api_url}: {exc.reason}") from exc
        if status not in expected:
            raise RuntimeError(f"{method} {path} expected {sorted(expected)}, got {status}")
        if not payload:
            return None
        return json.loads(payload)


def load_dotenv(path: Path) -> dict[str, str]:
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


def first_config_value(dotenv: dict[str, str], *names: str, default: str | None = None) -> str | None:
    for name in names:
        if os.getenv(name):
            return os.getenv(name)
        if dotenv.get(name):
            return dotenv[name]
    return default


def authenticate(client: ApiClient, out_dir: Path) -> None:
    dotenv = load_dotenv(REPO_ROOT / ".env")
    email = first_config_value(dotenv, "SOURCEBRIEF_ADMIN_EMAIL", "CONTEXTSMITH_ADMIN_EMAIL", default="admin@sourcebrief.local")
    password = first_config_value(dotenv, "SOURCEBRIEF_ADMIN_PASSWORD", "CONTEXTSMITH_ADMIN_PASSWORD")
    if not email or not password:
        write_json(out_dir / "auth-mode.json", {"mode": "dev-header", "email": client.email})
        return
    login = client.request("POST", "/auth/login", body={"email": email, "password": password})
    token = login.get("session_token")
    if not isinstance(token, str) or not token:
        raise RuntimeError("/auth/login response did not include session_token")
    client.token = token
    write_json(out_dir / "auth-mode.json", {"mode": "session-login", "email": email, "login": login})


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redact(data), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fetch_source_list(out_dir: Path) -> dict[str, Any]:
    fetched_at = datetime.now(UTC).isoformat()
    data: dict[str, Any]
    try:
        with urlopen(SOURCE_LIST_RAW_URL, timeout=30) as response:  # noqa: S310 - public documentation fetch
            readme = response.read().decode("utf-8")
    except Exception as exc:  # noqa: BLE001 - evidence should record exact fetch failure
        data = {"url": SOURCE_LIST_RAW_URL, "fetched_at": fetched_at, "status": "failed", "error": str(exc)}
        write_json(out_dir / "source-list-fetch.json", data)
        return data
    anchor = '<a id="harness-architecture-orchestration"></a>'
    start = readme.find(anchor)
    section = readme[start:] if start >= 0 else readme
    next_heading = section.find("\n<a id=", len(anchor))
    if next_heading > 0:
        section = section[:next_heading]
    (out_dir / "source-list-section.md").write_text(section, encoding="utf-8")
    data = {"url": SOURCE_LIST_RAW_URL, "fetched_at": fetched_at, "status": "fetched", "bytes": len(readme)}
    write_json(out_dir / "source-list-fetch.json", data)
    return data


def wait_for_index_run(client: ApiClient, workspace_id: str, index_run_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    current: dict[str, Any] = {"id": index_run_id, "status": "queued"}
    while time.time() < deadline:
        current = client.request("GET", f"/workspaces/{workspace_id}/index-runs/{index_run_id}")
        if current.get("status") in {"succeeded", "failed"}:
            return current
        time.sleep(2)
    current["wait_error"] = f"timeout after {timeout_seconds}s"
    return current


def create_workspace_project(client: ApiClient, slug: str, out_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    workspace = client.request("POST", "/workspaces", body={"name": f"Awesome Agent Harness Eval {slug}", "slug": slug}, expected={201})
    write_json(out_dir / "workspace.json", workspace)
    project = client.request(
        "POST",
        f"/workspaces/{workspace['id']}/projects",
        body={"name": "Top 5 agent harness repos", "description": "Issue #86 real-corpus evaluation workspace"},
        expected={201},
    )
    write_json(out_dir / "project.json", project)
    return workspace, project


def _repo_attempt_configs(repo: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "attempt": "wide-5000-files",
            "max_repo_files": 5000,
            "max_file_bytes": 5000000,
            "max_repo_bytes": 100000000,
            "clone_timeout": 600,
            "name": repo["name"],
        },
        {
            "attempt": "bounded-500-files",
            "max_repo_files": 500,
            "max_file_bytes": 1000000,
            "max_repo_bytes": 20000000,
            "clone_timeout": 600,
            "name": f"{repo['name']} (bounded 500 files)",
        },
        {
            "attempt": "bounded-200-files",
            "max_repo_files": 200,
            "max_file_bytes": 1000000,
            "max_repo_bytes": 10000000,
            "clone_timeout": 600,
            "name": f"{repo['name']} (bounded 200 files)",
        },
    ]


def _should_retry_import(final_run: dict[str, Any], refreshed_resource: dict[str, Any]) -> bool:
    if final_run.get("status") == "succeeded":
        return False
    text = " ".join(str(value) for value in [final_run.get("error_message"), *(refreshed_resource.get("coverage_warnings") or [])])
    return "budget exceeded" in text or "no current snapshot" in text


def import_repo(client: ApiClient, workspace_id: str, project_id: str, repo: dict[str, Any], out_dir: Path, timeout_seconds: int) -> dict[str, Any]:
    repo_dir = out_dir / "imports" / repo["key"]
    repo_dir.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {"repo": repo, "status": "started", "started_at": datetime.now(UTC).isoformat(), "attempts": []}
    for config in _repo_attempt_configs(repo):
        attempt_name = str(config["attempt"])
        attempt_dir = repo_dir / attempt_name
        attempt_dir.mkdir(parents=True, exist_ok=True)
        attempt_record: dict[str, Any] = {"attempt": attempt_name, "source_config": {k: v for k, v in config.items() if k.startswith("max_") or k == "clone_timeout"}}
        try:
            source_config = {"url": repo["url"], **attempt_record["source_config"]}
            resource = client.request(
                "POST",
                f"/workspaces/{workspace_id}/projects/{project_id}/resources",
                body={
                    "type": "git",
                    "name": config["name"],
                    "uri": repo["url"],
                    "update_frequency": "manual",
                    "source_config": source_config,
                },
                expected={201},
            )
            write_json(attempt_dir / "resource-create.json", resource)
            run = client.request(
                "POST",
                f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource['id']}/refresh",
                expected={202},
            )
            write_json(attempt_dir / "index-run-created.json", run)
            final_run = wait_for_index_run(client, workspace_id, run["id"], timeout_seconds)
            write_json(attempt_dir / "index-run-final.json", final_run)
            refreshed_resource = client.request("GET", f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource['id']}")
            write_json(attempt_dir / "resource-final.json", refreshed_resource)
            manifest: dict[str, Any] | None = None
            if refreshed_resource.get("current_snapshot_id"):
                try:
                    manifest = client.request("GET", f"/workspaces/{workspace_id}/projects/{project_id}/resources/{resource['id']}/manifest")
                    manifest_summary = {key: manifest.get(key) for key in ("id", "file_count", "total_bytes", "parser_warning_count", "unsupported_file_count", "section_count")}
                    write_json(attempt_dir / "manifest-summary.json", manifest_summary)
                except Exception as exc:  # noqa: BLE001
                    write_json(attempt_dir / "manifest-error.json", {"error": str(exc)})
            status = "succeeded" if final_run.get("status") == "succeeded" else "failed"
            caveats = list(refreshed_resource.get("coverage_warnings") or [])
            import_type = "limited" if refreshed_resource.get("coverage_status") == "partial" or caveats else "full"
            if status != "succeeded":
                import_type = "failed"
            attempt_record.update(
                {
                    "status": status,
                    "resource_id": resource.get("id"),
                    "snapshot_id": refreshed_resource.get("current_snapshot_id"),
                    "index_run_id": final_run.get("id"),
                    "index_run_status": final_run.get("status"),
                    "documents_seen": final_run.get("documents_seen"),
                    "chunks_created": final_run.get("chunks_created"),
                    "symbols_created": final_run.get("symbols_created"),
                    "embeddings_created": final_run.get("embeddings_created"),
                    "graph_nodes_created": final_run.get("graph_nodes_created"),
                    "graph_edges_created": final_run.get("graph_edges_created"),
                    "error_message": final_run.get("error_message"),
                    "resource_status": refreshed_resource.get("status"),
                    "coverage_status": refreshed_resource.get("coverage_status"),
                    "coverage_warnings": caveats,
                    "import_type": import_type,
                    "manifest_file_count": manifest.get("file_count") if manifest else None,
                    "manifest_total_bytes": manifest.get("total_bytes") if manifest else None,
                    "finished_at": datetime.now(UTC).isoformat(),
                }
            )
            record["attempts"].append(attempt_record)
            write_json(attempt_dir / "attempt-record.json", attempt_record)
            if status == "succeeded" or not _should_retry_import(final_run, refreshed_resource):
                record.update({key: value for key, value in attempt_record.items() if key != "source_config"})
                break
        except Exception as exc:  # noqa: BLE001 - continue through all repos and record failure
            attempt_record.update({"status": "failed", "import_type": "failed", "error": str(exc), "finished_at": datetime.now(UTC).isoformat()})
            record["attempts"].append(attempt_record)
            write_json(attempt_dir / "attempt-record.json", attempt_record)
            record.update({key: value for key, value in attempt_record.items() if key != "source_config"})
            break
    if record.get("status") == "started":
        record.update({"status": "failed", "import_type": "failed", "error": "all import attempts exhausted", "finished_at": datetime.now(UTC).isoformat()})
    write_json(repo_dir / "import-record.json", record)
    return record


def load_question_bank() -> dict[str, Any]:
    return json.loads(QUESTION_BANK.read_text(encoding="utf-8"))


def build_eval_manifest(
    bank: dict[str, Any],
    *,
    sourcebrief_commit: str,
    api_url: str,
    web_url: str | None,
    workspace_id: str,
    project_id: str,
    imports: list[dict[str, Any]],
) -> dict[str, Any]:
    by_key = {record["repo"]["key"]: record for record in imports}
    resources = []
    for repo in bank["repos"]:
        record = by_key.get(repo["key"], {})
        resource_id = record.get("resource_id")
        snapshot_id = record.get("snapshot_id")
        resources.append(
            {
                "key": repo["key"],
                "target_repo": repo["url"],
                "resource_ids": [resource_id] if resource_id else [],
                "snapshot_ids": [snapshot_id] if snapshot_id else [],
                "upstream_commit": record.get("upstream_commit"),
                "import_type": record.get("import_type", "failed"),
                "corpus_caveats": record.get("coverage_warnings") or ([] if record.get("status") == "succeeded" else [record.get("error") or record.get("error_message") or "import failed"]),
            }
        )
    defaults = dict(bank.get("question_defaults") or {})
    questions = []
    for question in bank["questions"]:
        q = {**defaults, **question}
        record = by_key.get(q["target_repo"], {})
        resource_id = record.get("resource_id")
        snapshot_id = record.get("snapshot_id")
        expected_result = q.get("expected_result", "pass")
        expected_resource_ids = [] if expected_result == "expected_unanswerable" else ([resource_id] if resource_id else [])
        q.update(
            {
                "resource_ids": [resource_id] if resource_id else [],
                "snapshot_ids": [snapshot_id] if snapshot_id else [],
                "expected_resource_ids": expected_resource_ids,
                "forbidden_resource_ids": [],
                "expected_paths": q.get("expected_paths", []),
                "expected_symbols": q.get("expected_symbols", []),
                "required_texts": q.get("required_texts", []),
                "import_type": record.get("import_type", "failed"),
            }
        )
        if not resource_id:
            q["min_citations"] = 0
            q["expected_result"] = "expected_unanswerable"
            q["bad_answer_criteria"] = list(q.get("bad_answer_criteria") or []) + ["resource import failed before evaluation"]
        questions.append(q)
    manifest = {
        "schema_version": "sourcebrief.eval-manifest.v1",
        "name": "Awesome Agent Harness top 5 real-corpus eval",
        "description": "Issue #86 real SourceBrief import/evaluation pass over the top five Harness Architecture & Orchestration repos from Picrew/awesome-agent-harness.",
        "thresholds": {"pass_min_rate": 0.7, "partial_min_rate": 0.5, "block_below_rate": 0.5, "max_wrong_repo": 0, "max_unsupported_claims": 0},
        "run": {
            "sourcebrief_commit": sourcebrief_commit,
            "api_url": api_url,
            "web_url": web_url or "not-recorded",
            "workspace_id": workspace_id,
            "project_id": project_id,
            "resources": resources,
        },
        "questions": questions,
    }
    validate_manifest(manifest)
    return manifest


def eval_payloads(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    questions = manifest["questions"]
    payloads = []
    for start in range(0, len(questions), 10):
        batch = questions[start : start + 10]
        payloads.append(
            {
                "profile": "hybrid",
                "runtime": "hermes",
                "max_chars": max(int(q.get("max_chars", 8000)) for q in batch),
                "questions": [
                    {
                        "id": q["id"],
                        "query": q["query"],
                        "expected_resource_ids": q.get("expected_resource_ids", []),
                        "forbidden_resource_ids": q.get("forbidden_resource_ids", []),
                        "resource_ids": q.get("resource_ids") or None,
                        "expected_paths": q.get("expected_paths", []),
                        "expected_symbols": q.get("expected_symbols", []),
                        "required_texts": q.get("required_texts", []),
                        "min_citations": q.get("min_citations", 1),
                        "top_k": q.get("top_k", 8),
                        "include_code_symbols": q.get("include_code_symbols", True),
                    }
                    for q in batch
                ],
            }
        )
    return payloads


def run_eval_batches(client: ApiClient, workspace_id: str, project_id: str, manifest: dict[str, Any], out_dir: Path) -> list[dict[str, Any]]:
    responses = []
    for idx, payload in enumerate(eval_payloads(manifest), start=1):
        write_json(out_dir / "eval-batches" / f"batch-{idx:03d}-payload.json", payload)
        response = client.request("POST", f"/workspaces/{workspace_id}/projects/{project_id}/retrieval-evals", body=payload)
        write_json(out_dir / "eval-batches" / f"batch-{idx:03d}-response.json", response)
        responses.append(response)
    return responses


def collect_agent_contexts(client: ApiClient, workspace_id: str, project_id: str, manifest: dict[str, Any], out_dir: Path) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for question in manifest["questions"]:
        payload = {
            "query": question["query"],
            "runtime": "hermes",
            "profile": "hybrid",
            "top_k": question.get("top_k", 8),
            "resource_ids": question.get("resource_ids") or None,
            "include_code_symbols": question.get("include_code_symbols", True),
            "max_chars": question.get("max_chars", 8000),
        }
        try:
            response = client.request("POST", f"/workspaces/{workspace_id}/projects/{project_id}/agent-context", body=payload)
        except Exception as exc:  # noqa: BLE001 - preserve per-question error
            response = {"error": str(exc), "query": question["query"]}
        contexts[question["id"]] = response
        write_json(out_dir / "agent-context" / f"{question['id']}.json", response)
    return contexts


def build_grade_report(manifest: dict[str, Any], eval_responses: list[dict[str, Any]], contexts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    eval_by_id = {result["id"]: result for response in eval_responses for result in response.get("results", [])}
    results = []
    for question in manifest["questions"]:
        qid = question["id"]
        eval_result = eval_by_id.get(qid, {})
        context = contexts.get(qid, {})
        citation_count = int(eval_result.get("citation_count") or len(context.get("citations") or []))
        context_chars = int(eval_result.get("context_chars") or len(str(context.get("context") or "")))
        mechanical_ok = bool(eval_result) and not eval_result.get("failure_reasons")
        negative = question.get("expected_result") == "expected_unanswerable"
        wrong_repo_ok = not any(reason.startswith("forbidden_resources_cited") for reason in eval_result.get("failure_reasons", []))
        citation_support: str | bool
        human_demo: str | bool
        retrieval_quality: str | bool
        if negative:
            retrieval_quality = "not_applicable"
            citation_support = "partial" if citation_count else True
            human_demo = "partial" if citation_count else True
        else:
            retrieval_quality = True if citation_count >= int(question.get("min_citations", 1)) and mechanical_ok else ("partial" if citation_count else "fail")
            citation_support = True if citation_count else "fail"
            human_demo = True if citation_count and context_chars >= 200 else ("partial" if citation_count else "fail")
        partial_corpus = "partial" if question.get("import_type") == "limited" else ("fail" if question.get("import_type") == "failed" else True)
        checks = {
            "mechanical_api_success": True if mechanical_ok else "fail",
            "retrieval_quality": retrieval_quality,
            "citation_support": citation_support,
            "wrong_repo_check": True if wrong_repo_ok else "fail",
            "partial_corpus_caveat": partial_corpus,
            "human_answer_demo": human_demo,
        }
        if any(value == "fail" or value is False for value in checks.values()):
            grade = "FAIL"
        elif any(value == "partial" for value in checks.values()):
            grade = "PARTIAL"
        else:
            grade = "PASS"
        rationale = (
            f"mechanical_pass={mechanical_ok}; citations={citation_count}; context_chars={context_chars}; "
            f"failure_reasons={eval_result.get('failure_reasons', [])}; import_type={question.get('import_type')}"
        )
        results.append({"id": qid, "grade": grade, "rationale": rationale, "checks": checks})
    grade_counts = {"PASS": 0, "PARTIAL": 0, "FAIL": 0}
    for result in results:
        grade_counts[result["grade"]] += 1
    def rate(check_key: str) -> float:
        applicable = [r["checks"][check_key] for r in results if r["checks"][check_key] != "not_applicable"]
        return round(sum(1 for value in applicable if value is True or value == "pass") / len(applicable), 6) if applicable else 1.0
    wrong_repo_failures = sum(1 for result in results if result["checks"]["wrong_repo_check"] == "fail")
    unsupported_claim_failures = sum(1 for result in results if result["checks"]["citation_support"] == "fail")
    verdict = "PASS"
    if grade_counts["FAIL"] or wrong_repo_failures or unsupported_claim_failures:
        verdict = "BLOCK"
    elif grade_counts["PARTIAL"]:
        verdict = "RISK"
    report = {
        "schema_version": "sourcebrief.eval-report.v1",
        "manifest_sha256": sha256_digest(manifest),
        "generated_at": datetime.now(UTC).isoformat(),
        "aggregate": {
            "mechanical_api_success_rate": rate("mechanical_api_success"),
            "retrieval_quality_pass_rate": rate("retrieval_quality"),
            "human_answer_demo_pass_rate": rate("human_answer_demo"),
            "wrong_repo_failures": wrong_repo_failures,
            "unsupported_claim_failures": unsupported_claim_failures,
            "verdict": verdict,
        },
        "grade_counts": grade_counts,
        "results": results,
    }
    validate_grade_report(report, manifest=manifest)
    return report


def write_markdown_summary(out_dir: Path, manifest: dict[str, Any], imports: list[dict[str, Any]], report: dict[str, Any], source_fetch: dict[str, Any]) -> None:
    lines = [
        "# Awesome Agent Harness Top 5 Eval Evidence",
        "",
        f"Generated at: `{report['generated_at']}`",
        f"Source list: {source_fetch.get('url')} fetched at `{source_fetch.get('fetched_at')}` status `{source_fetch.get('status')}`",
        f"SourceBrief commit: `{manifest['run']['sourcebrief_commit']}`",
        f"API URL: `{manifest['run']['api_url']}`",
        f"Workspace: `{manifest['run']['workspace_id']}`",
        f"Project: `{manifest['run']['project_id']}`",
        f"Manifest digest: `{report['manifest_sha256']}`",
        "",
        "## Import results",
        "",
        "| Repo | Status | Import type | Files | Chunks | Symbols | Embeddings | Notes |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in imports:
        notes = "; ".join(str(x) for x in (item.get("coverage_warnings") or [])) or item.get("error") or item.get("error_message") or ""
        lines.append(
            "| {name} | {status} | {import_type} | {files} | {chunks} | {symbols} | {embeddings} | {notes} |".format(
                name=item["repo"]["name"],
                status=item.get("status"),
                import_type=item.get("import_type"),
                files=item.get("manifest_file_count"),
                chunks=item.get("chunks_created"),
                symbols=item.get("symbols_created"),
                embeddings=item.get("embeddings_created"),
                notes=str(notes).replace("|", "\\|"),
            )
        )
    lines += [
        "",
        "## Evaluation aggregate",
        "",
        "```json",
        json.dumps(report["aggregate"], indent=2, sort_keys=True),
        "```",
        "",
        "## Per-question grade counts",
        "",
        "```json",
        json.dumps(report.get("grade_counts"), indent=2, sort_keys=True),
        "```",
        "",
        "Raw redacted payloads are stored beside this README under `imports/`, `eval-batches/`, and `agent-context/`.",
    ]
    (out_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Issue #86 real-corpus eval over awesome-agent-harness top 5 repos.")
    parser.add_argument("--api-url", default=os.getenv("SOURCEBRIEF_API_URL", "http://localhost:18000"))
    parser.add_argument("--web-url", default=os.getenv("SOURCEBRIEF_WEB_URL"))
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--slug", default=f"awesome-agent-harness-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}")
    parser.add_argument("--index-timeout", type=int, default=900)
    parser.add_argument("--sourcebrief-commit", default=os.popen("git rev-parse HEAD").read().strip() or "unknown")
    args = parser.parse_args()

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    bank = load_question_bank()
    write_json(out_dir / "question-bank.json", bank)
    source_fetch = fetch_source_list(out_dir)
    client = ApiClient(args.api_url)
    health = client.request("GET", "/readyz")
    write_json(out_dir / "health-readyz.json", health)
    authenticate(client, out_dir)
    workspace, project = create_workspace_project(client, args.slug, out_dir)
    imports = [import_repo(client, workspace["id"], project["id"], repo, out_dir, args.index_timeout) for repo in bank["repos"]]
    write_json(out_dir / "import-records.json", imports)
    manifest = build_eval_manifest(
        bank,
        sourcebrief_commit=args.sourcebrief_commit,
        api_url=args.api_url,
        web_url=args.web_url,
        workspace_id=workspace["id"],
        project_id=project["id"],
        imports=imports,
    )
    write_json(out_dir / "eval-manifest.json", manifest)
    eval_responses = run_eval_batches(client, workspace["id"], project["id"], manifest, out_dir)
    contexts = collect_agent_contexts(client, workspace["id"], project["id"], manifest, out_dir)
    report = build_grade_report(manifest, eval_responses, contexts)
    write_json(out_dir / "eval-report.json", report)
    write_markdown_summary(out_dir, manifest, imports, report, source_fetch)
    print(json.dumps({"output_dir": str(out_dir), "manifest_sha256": sha256_digest(manifest), "aggregate": report["aggregate"]}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
