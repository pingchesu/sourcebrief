from __future__ import annotations

import argparse
import json
import shlex
import tempfile
import time
from pathlib import Path
from typing import Any

from sourcebrief_cli import runtime_apply, skill_install
from sourcebrief_cli.client import SourceBriefClient, SourceBriefCliError
from sourcebrief_cli.scope import require_scope
from sourcebrief_shared.review_bundle import (
    build_review_bundle_from_agent_context,
    write_review_bundle,
)


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def print_kv(title: str, data: dict[str, Any], keys: list[str]) -> None:
    print(title)
    for key in keys:
        if key in data:
            print(f"  {key}: {data[key]}")


def resource_ids(values: list[str] | None) -> list[str] | None:
    return values or None


def resource_refs(args: argparse.Namespace) -> list[str] | None:
    values = getattr(args, "resource", None) or []
    return values or None


def apply_resource_refs(body: dict[str, Any], args: argparse.Namespace) -> None:
    refs = resource_refs(args)
    if not refs:
        return
    if len(refs) == 1:
        body["resource_ref"] = refs[0]
    else:
        body["resource_refs"] = refs


def split_csv_or_repeated(values: str | list[str] | None) -> list[str] | None:
    if not values:
        return None
    raw_values = [values] if isinstance(values, str) else values
    result: list[str] = []
    for value in raw_values:
        result.extend(part.strip() for part in value.split(",") if part.strip())
    return result or None


def wait_for_run(client: SourceBriefClient, workspace_id: str, index_run_id: str, timeout: int) -> dict[str, Any]:
    deadline = time.time() + timeout
    current: dict[str, Any] = {"status": "queued", "id": index_run_id}
    while time.time() < deadline:
        current = client.request("GET", f"/workspaces/{workspace_id}/index-runs/{index_run_id}")
        if current.get("status") in {"succeeded", "failed"}:
            break
        time.sleep(2)
    if current.get("status") != "succeeded":
        raise SourceBriefCliError(f"index run did not succeed before timeout: {current}")
    return current


def check_result(name: str, status: str, **extra: Any) -> dict[str, Any]:
    return {"name": name, "status": status, **extra}


def mcp_error_message(response: Any) -> str | None:
    if not isinstance(response, dict):
        return "MCP response was not a JSON object"
    error = response.get("error")
    if error:
        return json.dumps(error, sort_keys=True) if isinstance(error, dict) else str(error)
    result = response.get("result")
    if isinstance(result, dict) and result.get("isError") is True:
        content = result.get("content")
        return "MCP tool returned isError=true" + (f": {content!r}" if content else "")
    return None


def mcp_structured_payload(response: Any) -> dict[str, Any] | None:
    if not isinstance(response, dict):
        return None
    result = response.get("result")
    if not isinstance(result, dict):
        return None
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    content = result.get("content")
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "text" or not isinstance(item.get("text"), str):
                continue
            try:
                parsed = json.loads(item["text"])
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def mcp_citation_count(response: Any) -> int:
    payload = mcp_structured_payload(response)
    if not isinstance(payload, dict):
        return 0
    citations = payload.get("citations")
    if isinstance(citations, list) and citations:
        return len(citations)
    answer = payload.get("answer")
    if isinstance(answer, dict):
        citations_used = answer.get("citations_used")
        if isinstance(citations_used, list) and citations_used:
            return len(citations_used)
    return 0


def maybe_refresh(client: SourceBriefClient, args: argparse.Namespace, resource: dict[str, Any]) -> dict[str, Any]:
    if not args.refresh:
        return {"resource": resource}
    run = client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/resources/{resource['id']}/refresh",
        expected={202},
    )
    result: dict[str, Any] = {"resource": resource, "index_run": run}
    if args.wait:
        result["index_run"] = wait_for_run(client, args.workspace_id, run["id"], args.timeout)
    return result


def pick_answer_lines(context: str, *, limit: int = 3) -> list[str]:
    lines: list[str] = []
    for raw_line in context.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("[") or line.startswith("#"):
            continue
        lines.append(line)
        if len(lines) >= limit:
            break
    return lines


def human_answer_brief(data: dict[str, Any]) -> dict[str, Any]:
    citations = data.get("citations") or []
    warnings = data.get("coverage_warnings") or []
    api_answer = data.get("answer") if isinstance(data.get("answer"), dict) else None
    if api_answer and api_answer.get("text"):
        return {
            "query": data.get("query"),
            "answer": api_answer.get("text"),
            "outcome": api_answer.get("outcome", "answered"),
            "abstention_reason": api_answer.get("abstention_reason"),
            "unsupported_claim_terms": api_answer.get("unsupported_claim_terms") or [],
            "citations_used": api_answer.get("citations_used") or [],
            "confidence": api_answer.get("confidence", "medium"),
            "missing_evidence": api_answer.get("caveats") or warnings,
            "suggested_follow_up_reads": [call.get("arguments", {}) for call in data.get("suggested_tool_calls", [])[:2]],
            "raw_packet_hint": "Run with --json for the full agent-context packet.",
        }
    answer_lines = pick_answer_lines(str(data.get("context") or ""))
    if answer_lines:
        answer = " ".join(answer_lines)
    elif citations:
        answer = "SourceBrief found cited context, but no readable snippet fit the response budget. Use --json to inspect the full packet."
    else:
        answer = "No grounded answer is available from the selected SourceBrief evidence."
    cited = citations[:3]
    return {
        "query": data.get("query"),
        "answer": answer,
        "citations_used": [
            {
                "label": f"[{idx}]",
                "path": citation.get("path") or citation.get("title") or str(citation.get("resource_id")),
                "resource_id": citation.get("resource_id"),
                "snapshot_id": citation.get("snapshot_id"),
                "content_hash": citation.get("content_hash"),
                "score": citation.get("score"),
            }
            for idx, citation in enumerate(cited, start=1)
        ],
        "confidence": "low" if warnings or not citations else "medium",
        "missing_evidence": warnings,
        "suggested_follow_up_reads": [call.get("arguments", {}) for call in data.get("suggested_tool_calls", [])[:2]],
        "raw_packet_hint": "Run with --json for the full agent-context packet.",
    }


def capture_review_bundle(
    *,
    agent_context: dict[str, Any],
    args: argparse.Namespace,
    query: str,
    kind: str = "answer",
    task_brief: str = "Capture a cited SourceBrief answer for autonomous review.",
) -> dict[str, Any] | None:
    output_path = getattr(args, "review_bundle_out", None)
    if not output_path:
        return None
    bundle = build_review_bundle_from_agent_context(
        agent_context=agent_context,
        workspace_id=args.workspace_id,
        project_id=args.project_id,
        query=query,
        runtime=getattr(args, "runtime", "api"),
        top_k=getattr(args, "top_k", 8),
        max_chars=getattr(args, "max_chars", 12000),
        kind=kind,  # type: ignore[arg-type]
        command=["sourcebrief", *list(getattr(args, "_sourcebrief_argv", []) or [])],
        resource_ids=resource_ids(getattr(args, "resource_id", None)),
        task_brief=task_brief,
    )
    written = write_review_bundle(output_path, bundle)
    return {
        "path": str(written),
        "bundle_id": bundle.bundle_id,
        "schema_version": bundle.schema_version,
        "completeness": bundle.security.completeness,
        "citation_count": len(bundle.citations),
        "claim_count": len(bundle.output.claim_ids),
    }


def runtime_plan_request(client: SourceBriefClient, args: argparse.Namespace) -> dict[str, Any]:
    require_scope(args)
    plan = client.request(
        "POST",
        f"/workspaces/{args.workspace_id}/projects/{args.project_id}/runtime-install-plan",
        body={
            "target": args.target,
            "public_api_url": args.public_api_url,
            "server_name": args.server_name,
            "resource_ids": resource_ids(args.resource_id),
            "include_optional_tools": args.include_optional_tools,
        },
    )
    return runtime_apply.attach_plan_metadata(plan)


def validation_preview(plan: dict[str, Any], target: str, max_age_seconds: int) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(plan, handle)
        path = Path(handle.name)
    try:
        validation = runtime_apply.read_plan(path, target=target, max_age_seconds=max_age_seconds)
        return runtime_apply.validate_plan(validation, run=False)
    finally:
        path.unlink(missing_ok=True)


def sh_quote(value: str) -> str:
    return shlex.quote(value)


def runtime_token_command(plan: dict[str, Any]) -> str:
    parts = [
        "sourcebrief",
        "token",
        "create-runtime",
        "--workspace-id",
        sh_quote(str(plan.get("workspace_id") or "<workspace-id>")),
    ]
    if "code:read" in (plan.get("required_scopes") or []):
        parts.append("--read-code")
    else:
        parts.append("--context-only")
    project_id = plan.get("project_id")
    if project_id:
        parts.extend(["--project-id", sh_quote(str(project_id))])
    resources = (plan.get("resource_scope") or {}).get("resources") or []
    for resource_id in resources:
        parts.extend(["--resource-id", sh_quote(str(resource_id))])
    return " ".join(parts)


def read_validated_runtime_plan(args: argparse.Namespace) -> runtime_apply.PlanValidation:
    return runtime_apply.read_plan(
        Path(args.plan),
        target=args.target,
        max_age_seconds=args.max_age_seconds,
    )


def skill_export_generate_path(client: SourceBriefClient, args: argparse.Namespace) -> str:
    require_scope(args)
    version = args.pack_version
    if not version:
        current = client.request("GET", f"/workspaces/{args.workspace_id}/projects/{args.project_id}/context-packs/{args.pack_key}/current")
        version = str(current.get("version"))
    return f"/workspaces/{args.workspace_id}/projects/{args.project_id}/context-packs/{args.pack_key}/versions/{version}/skill-exports"


def skill_export_download_url(client: SourceBriefClient, args: argparse.Namespace, export: dict[str, Any]) -> str:
    export_id = export.get("id")
    return f"{client.api_url}/workspaces/{args.workspace_id}/projects/{args.project_id}/skill-exports/{export_id}/download.zip"


def skill_profile(args: argparse.Namespace) -> str:
    return args.profile or "default"


def skill_skills_dir(args: argparse.Namespace) -> Path:
    return Path(args.skills_dir).expanduser() if args.skills_dir else skill_install.default_skills_dir(skill_profile(args))


def add_common_resource_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--workspace", help="workspace name or slug; defaults to sourcebrief use selection")
    parser.add_argument("--workspace-id", help="advanced: workspace ID; defaults to sourcebrief use selection")
    parser.add_argument("--project", help="project name; defaults to sourcebrief use selection")
    parser.add_argument("--project-id", help="advanced: project ID; defaults to sourcebrief use selection")
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--update-frequency",
        default=None,
        help="refresh cadence; omitted Git repositories default to daily, other source types to manual",
    )
    parser.add_argument("--refresh", action="store_true", help="refresh after creating the resource")
    parser.add_argument("--wait", action="store_true", help="wait for refresh completion")
    parser.add_argument("--timeout", type=int, default=120, help="seconds to wait for refresh")


def print_default(command: str | None, data: Any) -> None:
    if isinstance(data, dict):
        if "resource" in data and isinstance(data["resource"], dict):
            print_kv("Resource", data["resource"], ["id", "name", "type", "uri", "status"])
            if "index_run" in data:
                print_kv("Index run", data["index_run"], ["id", "status", "documents_seen", "chunks_created", "symbols_created", "embeddings_created"])
            return
        if command in {"workspace", "project", "health"}:
            print_kv(command.title() if command else "Result", data, ["id", "name", "slug", "workspace_id", "status"])
            return
        if command == "search":
            print(f"Search: {data.get('query')} ({data.get('count', 0)} hits)")
            for hit in data.get("hits", []):
                print(f"- {hit.get('path') or hit.get('title') or hit.get('resource_id')}: {hit.get('snippet')}")
            return
        if command == "runtime" and data.get("status") == "dry_run_ready":
            print("Runtime setup: dry-run ready")
            print(f"  target: {data.get('target')}")
            print(f"  workspace_id: {data.get('workspace_id')}")
            print(f"  project_id: {data.get('project_id')}")
            print(f"  server_name: {data.get('server_name')}")
            print(f"  plan_path: {data.get('plan_path') or '(not saved; rerun with --plan-out plan.json)'}")
            print(f"  validation: {(data.get('validation') or {}).get('status')}")
            print(f"  token_command: {data.get('token_command')}")
            print("Next steps:")
            for step in data.get("next_steps", []):
                print(f"- {step}")
            return
        if command == "ask" and "answer" in data:
            print(f"Question: {data.get('query')}")
            print(f"Answer: {data.get('answer')}")
            if data.get("outcome"):
                print(f"Outcome: {data.get('outcome')}")
            if data.get("abstention_reason"):
                print(f"Abstention reason: {data.get('abstention_reason')}")
            if data.get("unsupported_claim_terms"):
                print("Unsupported claim terms: " + ", ".join(str(term) for term in data.get("unsupported_claim_terms", [])))
            print(f"Confidence: {data.get('confidence')}")
            citations = data.get("citations_used") or []
            if citations:
                print("Citations:")
                for citation in citations:
                    print(f"- {citation.get('label')} {citation.get('path')} score={citation.get('score')}")
            if data.get("missing_evidence"):
                print("Missing evidence / warnings:")
                for warning in data.get("missing_evidence", []):
                    print(f"- {warning}")
            if data.get("review_bundle"):
                print(f"Review bundle: {(data.get('review_bundle') or {}).get('path')}")
            print(data.get("raw_packet_hint"))
            return
        if command == "quickstart-demo" and data.get("status") == "indexed_and_ready_for_retrieval":
            print("Quickstart demo: indexed and ready for retrieval")
            print(f"  workspace: {data.get('workspace_name')}")
            print(f"  project: {data.get('project_name')}")
            print(f"  resource: {data.get('resource_name')}")
            print(f"  saved_defaults: {data.get('config_path')}")
            print(f"  index_status: {(data.get('index_run') or {}).get('status')}")
            if data.get("mcp_validation"):
                print(f"  mcp_validation: {(data.get('mcp_validation') or {}).get('status')}")
            answer = data.get("answer") or {}
            print(f"Answer: {answer.get('answer')}")
            if data.get("review_bundle"):
                print(f"  review_bundle: {(data.get('review_bundle') or {}).get('path')}")
            print("Citations:")
            for citation in answer.get("citations_used", []):
                print(f"- {citation.get('label')} {citation.get('path')} score={citation.get('score')}")
            print("Next:")
            print(f"- {data.get('next_command')}")
            print(f"- {data.get('cleanup')}")
            return
        if command in {"agent-context", "mcp-context", "ask", "agent", "agent-pack", "token", "runtime", "skill", "use", "status", "doctor", "login", "logout"}:
            print_json(data)
            return
    print_json(data)
