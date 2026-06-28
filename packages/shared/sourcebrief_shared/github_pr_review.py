from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sourcebrief_shared.review_bundle import (
    REVIEW_BUNDLE_SCHEMA_VERSION,
    CitationRef,
    ReviewBundle,
    ReviewBundleInput,
    ReviewBundleOutput,
    ReviewBundleScope,
    RuntimeContext,
    SourceRef,
    ToolProof,
    VerificationLog,
    sanitize_review_bundle_payload,
    write_review_bundle,
)
from sourcebrief_shared.self_improvement_security import (
    ArtifactSensitivity,
    BundleCompleteness,
    ReviewArtifactPolicy,
    ReviewArtifactScope,
)


class GitHubPRBundleError(ValueError):
    """User-facing PR bundle creation error."""


def sha256_text(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_pr_metadata_fixture(path: str | Path) -> dict[str, Any]:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GitHubPRBundleError(f"PR metadata fixture is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise GitHubPRBundleError("PR metadata fixture must be a JSON object")
    return raw


def _run_gh(args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["gh", *args],
            check=True,
            text=True,
            capture_output=True,
        )
    except FileNotFoundError as exc:
        raise GitHubPRBundleError("gh CLI is required unless --metadata-fixture is provided") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        raise GitHubPRBundleError(f"gh command failed: {stderr}") from exc
    return completed.stdout


def fetch_github_pr_metadata(*, repo: str, pr_number: int) -> dict[str, Any]:
    if not repo.strip():
        raise GitHubPRBundleError("--repo is required when --metadata-fixture is not provided")
    view_json = _run_gh(
        [
            "pr",
            "view",
            str(pr_number),
            "--repo",
            repo,
            "--json",
            "number,title,body,url,headRefOid,headRefName,baseRefName,author,changedFiles",
        ]
    )
    try:
        metadata = json.loads(view_json)
    except json.JSONDecodeError as exc:
        raise GitHubPRBundleError("gh pr view did not return valid JSON") from exc
    if not isinstance(metadata, dict):
        raise GitHubPRBundleError("gh pr view returned a non-object payload")
    diff_names = _run_gh(["pr", "diff", str(pr_number), "--repo", repo, "--name-only"])
    changed_paths = [line.strip() for line in diff_names.splitlines() if line.strip()]
    metadata["repo"] = repo
    metadata["changed_paths"] = changed_paths
    metadata["diff_summary"] = "\n".join(f"- {path}" for path in changed_paths) or "No changed paths reported."
    return metadata


def _metadata_str(metadata: dict[str, Any], *keys: str, default: str = "") -> str:
    for key in keys:
        value = metadata.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _metadata_int(metadata: dict[str, Any], key: str) -> int:
    value = metadata.get(key)
    if value is None:
        raise GitHubPRBundleError(f"PR metadata field {key!r} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise GitHubPRBundleError(f"PR metadata field {key!r} must be an integer") from exc
    if number < 1:
        raise GitHubPRBundleError(f"PR metadata field {key!r} must be positive")
    return number


def _changed_paths(metadata: dict[str, Any]) -> list[str]:
    raw = metadata.get("changed_paths") or metadata.get("files") or []
    if not isinstance(raw, list):
        raise GitHubPRBundleError("PR metadata changed_paths/files must be a list")
    paths: list[str] = []
    for item in raw:
        if isinstance(item, dict):
            value = item.get("path") or item.get("filename") or item.get("file")
        else:
            value = item
        text = str(value or "").strip()
        if text:
            paths.append(text)
    if not paths:
        raise GitHubPRBundleError("PR metadata must include at least one changed path")
    return sorted(dict.fromkeys(paths))


def _verification_logs(metadata: dict[str, Any]) -> list[VerificationLog]:
    raw = metadata.get("verification_logs") or []
    if not isinstance(raw, list):
        raise GitHubPRBundleError("PR metadata verification_logs must be a list when provided")
    logs: list[VerificationLog] = []
    for item in raw:
        if not isinstance(item, dict):
            raise GitHubPRBundleError("PR metadata verification_logs entries must be objects")
        logs.append(
            VerificationLog(
                command=str(item.get("command") or "not recorded"),
                status=item.get("status") or "not_run",
                output_excerpt=item.get("output_excerpt"),
                artifact_uri=item.get("artifact_uri"),
            )
        )
    return logs


def build_review_bundle_from_github_pr_metadata(
    metadata: dict[str, Any],
    *,
    workspace_id: str,
    project_id: str,
    reviewer_backend: str = "local",
    policy: ReviewArtifactPolicy | None = None,
) -> ReviewBundle:
    pr_number = _metadata_int(metadata, "number")
    repo = _metadata_str(metadata, "repo", "repository", default="unknown/repo")
    title = _metadata_str(metadata, "title", default=f"PR #{pr_number}")
    body = _metadata_str(metadata, "body", default="")
    url = _metadata_str(metadata, "url", "html_url", default=f"https://github.com/{repo}/pull/{pr_number}")
    head_sha = _metadata_str(metadata, "head_sha", "headRefOid", "head_ref_oid", default="unknown-head-sha")
    base_ref = _metadata_str(metadata, "base_ref", "baseRefName", default="unknown-base")
    head_ref = _metadata_str(metadata, "head_ref", "headRefName", default="unknown-head")
    diff_summary = _metadata_str(metadata, "diff_summary", default="No diff summary provided.")
    paths = _changed_paths(metadata)
    resource_id = _metadata_str(metadata, "resource_id", default=f"github-pr:{repo}#{pr_number}")
    claim_ids = [
        f"claim-pr-{pr_number}-changed-paths-reviewed",
        f"claim-pr-{pr_number}-verification-recorded",
    ]

    source_refs = [
        SourceRef(
            resource_id=resource_id,
            commit_sha=head_sha,
            path=path,
            title=f"{repo}#{pr_number} {path}",
        )
        for path in paths
    ]
    citations = [
        CitationRef(
            citation_id=f"cite-pr-{pr_number}-path-{idx}",
            label=f"[{idx}]",
            source_ref=source_ref,
            snippet=f"PR #{pr_number} ({head_sha}) changed `{source_ref.path}`.",
            snippet_hash=sha256_text(f"{repo}#{pr_number}:{head_sha}:{source_ref.path}"),
            supports_claim_ids=claim_ids,
        )
        for idx, source_ref in enumerate(source_refs, start=1)
    ]
    verification_logs = _verification_logs(metadata)
    tool_proof = [
        ToolProof(
            proof_id="proof-pr-metadata",
            kind="git",
            command=["gh", "pr", "view", str(pr_number), "--repo", repo],
            status="passed",
            stdout_excerpt=f"PR #{pr_number} {head_sha} changed {len(paths)} path(s).",
            artifact_uri=url,
        )
    ]
    if verification_logs:
        tool_proof.extend(
            ToolProof(
                proof_id=f"proof-pr-verification-{idx}",
                kind="test",
                command=log.command.split(),
                status=log.status,
                stdout_excerpt=log.output_excerpt,
                artifact_uri=log.artifact_uri,
            )
            for idx, log in enumerate(verification_logs, start=1)
        )

    bundle_scope = ReviewBundleScope(workspace_id=workspace_id, project_id=project_id, resource_ids=[resource_id])
    security_scope = ReviewArtifactScope(workspace_id=workspace_id, project_id=project_id, resource_ids=(resource_id,))
    policy = policy or ReviewArtifactPolicy(
        sensitivity=ArtifactSensitivity.INTERNAL,
        retention_days=30,
        allowed_reviewer_backends=("local", "mock"),
        external_reviewer_opt_in=False,
    )
    raw_payload = {
        "schema_version": REVIEW_BUNDLE_SCHEMA_VERSION,
        "bundle_id": f"rb-pr-{repo.replace('/', '-')}-{pr_number}-{head_sha[:12]}",
        "kind": "pr_review",
        "created_at": datetime.now(UTC).isoformat(),
        "input": ReviewBundleInput(
            original_query=f"Review GitHub PR {repo}#{pr_number}: {title}",
            task_brief="Review pull request scope, tests, safety, docs, product/DX, and runtime risks from bounded PR evidence.",
            acceptance_criteria=[
                "Reviewer report references the PR number, head SHA, and changed paths.",
                "Reviewer does not merge, comment, or mutate production unless an explicit later command does so.",
            ],
            non_goals=["Do not inspect raw chat transcripts.", "Do not merge or mutate the PR."],
        ).model_dump(mode="json"),
        "output": ReviewBundleOutput(
            summary=f"GitHub PR review bundle for {repo}#{pr_number}: {title}",
            body=(
                f"PR: {repo}#{pr_number}\nURL: {url}\nHead: {head_sha}\nBase: {base_ref}\n"
                f"Head ref: {head_ref}\n\nTitle: {title}\n\nBody:\n{body or '(empty)'}\n\n"
                f"Changed paths ({len(paths)}):\n" + "\n".join(f"- {path}" for path in paths) + "\n\nDiff summary:\n" + diff_summary
            ),
            claim_ids=claim_ids,
        ).model_dump(mode="json"),
        "scope": bundle_scope.model_dump(mode="json"),
        "runtime": RuntimeContext(runtime="github_pr_review", model_backend="local", retrieval_profile="pr_metadata").model_dump(mode="json"),
        "source_refs": [source_ref.model_dump(mode="json") for source_ref in source_refs],
        "citations": [citation.model_dump(mode="json") for citation in citations],
        "tool_proof": [proof.model_dump(mode="json") for proof in tool_proof],
        "verification_logs": [log.model_dump(mode="json") for log in verification_logs],
        "reviewer_notes": [
            f"github_pr repo={repo} number={pr_number} head_sha={head_sha} url={url} changed_paths={','.join(paths)}"
        ],
    }
    sanitized, _report = sanitize_review_bundle_payload(
        raw_payload,
        policy=policy,
        scope=security_scope,
        reviewer_backend=reviewer_backend,
        completeness=BundleCompleteness.COMPLETE,
    )
    return ReviewBundle.model_validate(sanitized)


def write_github_pr_review_bundle(
    *,
    path: str | Path,
    metadata: dict[str, Any],
    workspace_id: str,
    project_id: str,
    reviewer_backend: str = "local",
) -> Path:
    bundle = build_review_bundle_from_github_pr_metadata(
        metadata,
        workspace_id=workspace_id,
        project_id=project_id,
        reviewer_backend=reviewer_backend,
    )
    return write_review_bundle(path, bundle)
