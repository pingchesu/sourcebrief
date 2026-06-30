#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
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
    api_eval_payloads,
    load_json_file,
    sha256_digest,
    validate_manifest,
)

DEV_EMAIL = "demo@example.com"
SUPPORTED_API_PROFILES = {"lexical", "vector", "hybrid", "hybrid_rerank", "hybrid-rerank", "graph", "retrieval_v2_rerank", "retrieval-v2-rerank"}
SAFE_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class EvalManifestRef:
    key: str
    path: Path
    manifest: dict[str, Any]
    digest: str


@dataclass(frozen=True)
class ProfileSpec:
    key: str
    api_profile: str | None = None
    provider_profile: str | None = None
    description: str = ""


def redact_text(value: str) -> str:
    value = re.sub(r"(?i)(authorization\s*[:=]\s*)bearer\s+[^\s,;}\]]+", r"\1Bearer <redacted>", value)
    value = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+\-/=]+", r"\1<redacted>", value)
    value = re.sub(r"(?i)((?:token|secret|password|api[_-]?key|session(?:_id)?|cookie)\s*[:=]\s*)[^\s,;}\]]+", r"\1<redacted>", value)
    return value


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        result: dict[str, Any] = {}
        for key, value in obj.items():
            key_l = key.lower().replace("-", "_")
            if any(marker in key_l for marker in ("token", "secret", "password", "authorization", "api_key", "apikey", "cookie", "session")):
                result[key] = "<redacted>"
            else:
                result[key] = redact(value)
        return result
    if isinstance(obj, list):
        return [redact(item) for item in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redact(data), indent=2, sort_keys=True) + "\n", encoding="utf-8")


class ApiClient:
    def __init__(self, api_url: str, *, email: str = DEV_EMAIL, token: str | None = None, timeout: float = 60.0) -> None:
        self.api_url = api_url.rstrip("/")
        self.email = email
        self.token = token
        self.timeout = timeout

    def request(self, method: str, path: str, *, body: dict[str, Any] | None = None, expected: set[int] | None = None) -> Any:
        expected = expected or {200}
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        else:
            headers["X-User-Email"] = self.email
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(f"{self.api_url}{path}", data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:  # noqa: S310 - operator-provided API URL
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


def safe_component(value: str, label: str) -> str:
    if not SAFE_COMPONENT_RE.match(value) or ".." in value:
        raise ValueError(f"unsafe {label} for artifact path: {value!r}")
    return value


def json_file_digest(path: str | None) -> str | None:
    if not path:
        return None
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_manifest_arg(value: str) -> tuple[str, Path]:
    if "=" in value:
        key, path = value.split("=", 1)
    else:
        path_obj = Path(value)
        key, path = path_obj.stem, value
    key = safe_component(key.strip(), "manifest key")
    return key, Path(path)


def load_manifest_ref(value: str) -> EvalManifestRef:
    key, path = parse_manifest_arg(value)
    manifest = load_json_file(path)
    validate_manifest(manifest)
    for question in manifest.get("questions", []):
        qid = question.get("id")
        if not isinstance(qid, str):
            raise ValueError("manifest question id must be a string")
        safe_component(qid, "question id")
    return EvalManifestRef(key=key, path=path, manifest=manifest, digest=sha256_digest(manifest))


def normalize_api_profile(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if value in {"none", "default", "-"}:
        return None
    normalized = value.replace("-", "_")
    if normalized not in {profile.replace("-", "_") for profile in SUPPORTED_API_PROFILES}:
        allowed = ", ".join(sorted(SUPPORTED_API_PROFILES))
        raise ValueError(f"unsupported api_profile {value!r}; allowed: {allowed}, default, none")
    return normalized


def parse_profile_spec(value: str) -> ProfileSpec:
    parts = value.split(":")
    if len(parts) > 2:
        raise ValueError("provider_profile is not executable yet; use key[:api_profile] until sidecar support lands")
    key = safe_component(parts[0].strip(), "profile key")
    if len(parts) == 1:
        if key.replace("-", "_") not in {profile.replace("-", "_") for profile in SUPPORTED_API_PROFILES}:
            raise ValueError("bare profile specs must be supported API profile names; use key:api_profile for labels")
        api_profile = normalize_api_profile(key)
    else:
        api_profile = normalize_api_profile(parts[1])
    return ProfileSpec(key=key, api_profile=api_profile)


def load_profile_specs(values: list[str], profile_matrix: str | None = None) -> list[ProfileSpec]:
    specs: list[ProfileSpec] = [parse_profile_spec(value) for value in values]
    if profile_matrix:
        data = load_json_file(profile_matrix)
        raw_profiles = data.get("profiles")
        if not isinstance(raw_profiles, list) or not raw_profiles:
            raise ValueError("profile matrix must contain a non-empty profiles list")
        for index, profile in enumerate(raw_profiles):
            if not isinstance(profile, dict):
                raise ValueError(f"profile matrix profiles[{index}] must be an object")
            key = profile.get("key")
            if not isinstance(key, str) or not key.strip():
                raise ValueError(f"profile matrix profiles[{index}].key must be a non-empty string")
            provider_profile = profile.get("provider_profile")
            if provider_profile:
                raise ValueError("provider_profile is metadata-only today and is refused until #199 sidecar execution support lands")
            specs.append(
                ProfileSpec(
                    key=safe_component(key.strip(), "profile key"),
                    api_profile=normalize_api_profile(profile.get("api_profile") if isinstance(profile.get("api_profile"), str) else None),
                    description=str(profile.get("description") or ""),
                )
            )
    if not specs:
        raise ValueError("at least one profile must be provided")
    seen: set[str] = set()
    deduped: list[ProfileSpec] = []
    for spec in specs:
        if spec.key in seen:
            raise ValueError(f"duplicate profile key: {spec.key}")
        seen.add(spec.key)
        deduped.append(spec)
    return deduped


def eval_body(payload: dict[str, Any], profile: ProfileSpec, runtime: str) -> dict[str, Any]:
    body = dict(payload)
    body["runtime"] = runtime
    if profile.api_profile is not None:
        body["profile"] = profile.api_profile
    else:
        body.pop("profile", None)
    return body


def agent_context_body(question: dict[str, Any], profile: ProfileSpec, runtime: str, max_chars: int) -> dict[str, Any]:
    body: dict[str, Any] = {
        "query": question["query"],
        "runtime": runtime,
        "top_k": question.get("top_k", 8),
        "max_chars": question.get("max_chars", max_chars),
        "include_code_symbols": question.get("include_code_symbols", True),
        "resource_ids": question.get("resource_ids") or None,
    }
    if profile.api_profile is not None:
        body["profile"] = profile.api_profile
    return body


def hermes_grade_input(
    *,
    manifest: EvalManifestRef,
    profile: ProfileSpec,
    question: dict[str, Any],
    retrieval_eval: dict[str, Any] | None,
    agent_context: dict[str, Any] | None,
    baseline_profile: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": "sourcebrief.hermes-grade-input.v1",
        "manifest_key": manifest.key,
        "manifest_sha256": manifest.digest,
        "question": question,
        "profile": profile.__dict__,
        "baseline_profile": baseline_profile,
        "rubric": {
            "instruction": "Grade only from the provided SourceBrief context and citations. Do not use outside knowledge.",
            "fields": [
                "answer_correct",
                "citation_supported",
                "missing_evidence",
                "wrong_resource",
                "unsupported_claim",
                "abstention_correct",
                "usefulness",
                "better_than_baseline",
                "supporting_citation_ids",
                "failure_reasons",
                "rationale",
            ],
        },
        "retrieval_eval": retrieval_eval,
        "agent_context": agent_context,
        "expected_output_schema": {
            "question_id": question["id"],
            "profile": profile.key,
            "answer_correct": "pass|partial|fail",
            "citation_supported": "pass|partial|fail",
            "missing_evidence": "boolean",
            "wrong_resource": "boolean",
            "unsupported_claim": "boolean",
            "abstention_correct": "boolean|null",
            "usefulness": "integer 1..5",
            "better_than_baseline": "better|same|worse|not_compared",
            "supporting_citation_ids": "array",
            "failure_reasons": "array",
            "rationale": "string",
        },
    }


def pairwise_grade_input(
    *,
    manifest: EvalManifestRef,
    question: dict[str, Any],
    baseline_profile: ProfileSpec,
    candidate_profile: ProfileSpec,
    baseline_context: dict[str, Any] | None,
    candidate_context: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    swap = int(hashlib.sha256(f"{manifest.key}:{question['id']}:{candidate_profile.key}".encode()).hexdigest(), 16) % 2 == 1
    left_profile, right_profile = (candidate_profile, baseline_profile) if swap else (baseline_profile, candidate_profile)
    left_context, right_context = (candidate_context, baseline_context) if swap else (baseline_context, candidate_context)
    grade_input = {
        "schema_version": "sourcebrief.hermes-pairwise-grade-input.v1",
        "manifest_key": manifest.key,
        "manifest_sha256": manifest.digest,
        "question": question,
        "rubric": {
            "instruction": "Blindly compare A and B using only their provided SourceBrief context and citations. Do not use outside knowledge.",
            "choices": ["A", "B", "tie", "both_fail"],
        },
        "A": {"agent_context": left_context},
        "B": {"agent_context": right_context},
        "expected_output_schema": {
            "question_id": question["id"],
            "winner": "A|B|tie|both_fail",
            "citation_supported": "pass|partial|fail",
            "rationale": "string",
        },
    }
    identity_decode = {
        "schema_version": "sourcebrief.hermes-pairwise-identity-decode.v1",
        "manifest_key": manifest.key,
        "manifest_sha256": manifest.digest,
        "question_id": question["id"],
        "A": left_profile.__dict__,
        "B": right_profile.__dict__,
        "baseline": baseline_profile.__dict__,
        "candidate": candidate_profile.__dict__,
        "warning": "Operator-only decode map. Do not pass to Hermes during blind pairwise grading.",
    }
    return grade_input, identity_decode


def detect_git_commit() -> str:
    env_value = os.getenv("SOURCEBRIEF_RUNNER_GIT_COMMIT")
    if env_value:
        return env_value
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except Exception:  # noqa: BLE001 - reproducibility metadata should not block eval execution
        return "unknown"
    if proc.returncode != 0:
        return "unknown"
    return proc.stdout.strip() or "unknown"


def summarize_retrieval_batches(batch_results: list[dict[str, Any]]) -> dict[str, Any]:
    question_count = passed_count = failed_count = error_count = 0
    latencies: list[float] = []
    failure_reasons: list[str] = []
    for result in batch_results:
        if "error" in result:
            error_count += 1
            failure_reasons.append(str(result["error"]))
            continue
        summary = result.get("summary") if isinstance(result, dict) else None
        if isinstance(summary, dict):
            question_count += int(summary.get("question_count") or 0)
            passed_count += int(summary.get("passed_count") or 0)
            failed_count += int(summary.get("failed_count") or 0)
            if summary.get("max_latency_ms") is not None:
                latencies.append(float(summary["max_latency_ms"]))
            failure_reasons.extend(str(reason) for reason in summary.get("failure_reasons") or [])
        else:
            results = result.get("results", []) if isinstance(result, dict) else []
            question_count += len(results)
            passed_count += sum(1 for item in results if item.get("passed"))
            failed_count += sum(1 for item in results if not item.get("passed"))
            latencies.extend(float(item["latency_ms"]) for item in results if item.get("latency_ms") is not None)
            for item in results:
                failure_reasons.extend(str(reason) for reason in item.get("failure_reasons") or [])
    pass_rate = passed_count / question_count if question_count else 0.0
    return {
        "question_count": question_count,
        "passed_count": passed_count,
        "failed_count": failed_count,
        "error_count": error_count,
        "pass_rate": pass_rate,
        "max_latency_ms": max(latencies) if latencies else 0.0,
        "failure_reasons": sorted(set(failure_reasons)),
    }


def run_matrix(args: argparse.Namespace) -> int:
    manifests = [load_manifest_ref(value) for value in args.manifest]
    profiles = load_profile_specs(args.profile, args.profile_matrix)
    profile_by_key = {profile.key: profile for profile in profiles}
    if args.baseline_profile and args.baseline_profile not in profile_by_key:
        raise ValueError(f"baseline profile {args.baseline_profile!r} must be included in --profile/--profile-matrix")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    client = ApiClient(args.api_url, email=args.email, token=args.token or os.getenv("SOURCEBRIEF_TOKEN"), timeout=args.timeout)

    run_started_at = datetime.now(UTC).isoformat()
    write_json(
        output_dir / "run-environment.json",
        {
            "schema_version": "sourcebrief.profile-matrix-run.v1",
            "started_at": run_started_at,
            "api_url": args.api_url,
            "workspace_id": args.workspace_id,
            "project_id": args.project_id,
            "runtime": args.runtime,
            "runner_git_commit": detect_git_commit(),
            "argv": sys.argv,
            "profile_matrix_path": args.profile_matrix,
            "profile_matrix_sha256": json_file_digest(args.profile_matrix),
            "baseline_profile": args.baseline_profile,
            "max_chars": args.max_chars,
            "skip_agent_context": args.skip_agent_context,
            "auth_mode": "bearer-token" if (args.token or os.getenv("SOURCEBRIEF_TOKEN")) else "dev-header",
            "artifact_warning": "Secret-redacted local evidence bundle. Agent-context/source snippets and queries may be present; do not publish without additional source-content redaction.",
            "manifests": [{"key": item.key, "path": str(item.path), "sha256": item.digest} for item in manifests],
            "profiles": [profile.__dict__ for profile in profiles],
        },
    )
    aggregate: dict[str, Any] = {"manifests": {}, "profiles": {}, "errors": [], "preflight_errors": []}
    for endpoint, name in (("/provider-health", "provider-health.json"), (f"/workspaces/{args.workspace_id}/projects/{args.project_id}/retrieval-profiles", "retrieval-profiles.json")):
        try:
            write_json(output_dir / name, client.request("GET", endpoint))
        except Exception as exc:  # noqa: BLE001 - evidence should preserve preflight failures
            error = {"endpoint": endpoint, "error": str(exc)}
            aggregate["preflight_errors"].append(error)
            aggregate["errors"].append({"preflight": name, **error})
            write_json(output_dir / name, error)

    agent_contexts: dict[tuple[str, str, str], dict[str, Any] | None] = {}
    for manifest in manifests:
        manifest_dir = output_dir / safe_component(manifest.key, "manifest key")
        write_json(manifest_dir / "manifest.json", manifest.manifest)
        write_json(manifest_dir / "manifest-summary.json", validate_manifest(manifest.manifest))
        payloads = api_eval_payloads(manifest.manifest)
        aggregate["manifests"][manifest.key] = {"sha256": manifest.digest, "question_count": len(manifest.manifest["questions"]), "batch_count": len(payloads), "profiles": {}}
        for profile in profiles:
            profile_dir = manifest_dir / safe_component(profile.key, "profile key")
            write_json(profile_dir / "profile-config.json", profile.__dict__)
            batch_results: list[dict[str, Any]] = []
            for index, payload in enumerate(payloads, start=1):
                body = eval_body(payload, profile, args.runtime)
                path = f"/workspaces/{args.workspace_id}/projects/{args.project_id}/retrieval-evals"
                try:
                    result = client.request("POST", path, body=body)
                except Exception as exc:  # noqa: BLE001 - keep going to preserve partial evidence
                    result = {"error": str(exc), "request": body}
                    aggregate["errors"].append({"manifest": manifest.key, "profile": profile.key, "batch": index, "error": str(exc)})
                write_json(profile_dir / "retrieval-evals" / f"batch-{index:03d}.json", result)
                batch_results.append(result)
            retrieval_summary = summarize_retrieval_batches(batch_results)
            question_results_by_id: dict[str, Any] = {}
            for result in batch_results:
                if isinstance(result, dict):
                    for detail in result.get("results", []) or []:
                        if isinstance(detail, dict) and detail.get("id"):
                            question_results_by_id[str(detail["id"])] = detail
            for question in manifest.manifest["questions"]:
                qid = safe_component(str(question["id"]), "question id")
                context_result: dict[str, Any] | None = None
                if not args.skip_agent_context:
                    body = agent_context_body(question, profile, args.runtime, args.max_chars)
                    try:
                        context_result = client.request("POST", f"/workspaces/{args.workspace_id}/projects/{args.project_id}/agent-context", body=body)
                    except Exception as exc:  # noqa: BLE001
                        context_result = {"error": str(exc), "request": body}
                        aggregate["errors"].append({"manifest": manifest.key, "profile": profile.key, "question": qid, "error": str(exc)})
                    write_json(profile_dir / "agent-context" / f"{qid}.json", context_result)
                agent_contexts[(manifest.key, profile.key, qid)] = context_result
                grade_input = hermes_grade_input(
                    manifest=manifest,
                    profile=profile,
                    question=question,
                    retrieval_eval=question_results_by_id.get(qid),
                    agent_context=context_result,
                    baseline_profile=args.baseline_profile,
                )
                write_json(profile_dir / "hermes-grade-inputs" / f"{qid}.json", grade_input)
            aggregate["profiles"].setdefault(profile.key, profile.__dict__)
            aggregate["manifests"][manifest.key]["profiles"][profile.key] = retrieval_summary
        if args.baseline_profile:
            baseline = profile_by_key[args.baseline_profile]
            for profile in profiles:
                if profile.key == baseline.key:
                    continue
                pair_dir = manifest_dir / "pairwise" / safe_component(f"{baseline.key}_vs_{profile.key}", "pairwise key")
                for question in manifest.manifest["questions"]:
                    qid = safe_component(str(question["id"]), "question id")
                    grade_input, identity_decode = pairwise_grade_input(
                        manifest=manifest,
                        question=question,
                        baseline_profile=baseline,
                        candidate_profile=profile,
                        baseline_context=agent_contexts.get((manifest.key, baseline.key, qid)),
                        candidate_context=agent_contexts.get((manifest.key, profile.key, qid)),
                    )
                    write_json(pair_dir / "grade-inputs" / f"{qid}.json", grade_input)
                    write_json(pair_dir / "identity-decodes" / f"{qid}.json", identity_decode)
    aggregate["finished_at"] = datetime.now(UTC).isoformat()
    write_json(output_dir / "aggregate-report.json", aggregate)
    print(json.dumps({"output_dir": str(output_dir), "manifest_count": len(manifests), "profile_count": len(profiles), "error_count": len(aggregate["errors"])}, indent=2, sort_keys=True))
    return 0 if not aggregate["errors"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run SourceBrief retrieval/profile matrix evals and write Hermes grade inputs.")
    parser.add_argument("--manifest", action="append", required=True, help="Manifest path or key=path. Repeatable.")
    parser.add_argument("--profile", action="append", default=[], help="Profile spec key[:api_profile]. Repeatable. provider_profile is refused until sidecar execution support lands.")
    parser.add_argument("--profile-matrix", help="Optional JSON file with profiles[].")
    parser.add_argument("--api-url", default=os.getenv("SOURCEBRIEF_API_URL", "http://127.0.0.1:18000"))
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--runtime", default="hermes")
    parser.add_argument("--email", default=DEV_EMAIL)
    parser.add_argument("--token")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-chars", type=int, default=8000)
    parser.add_argument("--baseline-profile")
    parser.add_argument("--skip-agent-context", action="store_true", help="Only run retrieval-evals and still write Hermes grade-input shells.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run_matrix(args)
    except Exception as exc:  # noqa: BLE001
        print(f"profile matrix eval error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
