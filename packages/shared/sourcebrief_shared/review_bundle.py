from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sourcebrief_shared.self_improvement_security import (
    BundleCompleteness,
    RedactionReport,
    ReviewArtifactPolicy,
    ReviewArtifactScope,
    build_security_metadata,
    redact_review_artifact,
)

REVIEW_BUNDLE_SCHEMA_VERSION = "sourcebrief.review-bundle.v1"

BundleKind = Literal["answer", "cli_demo", "pr_review", "runtime_agent_context"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewBundleScope(StrictModel):
    workspace_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    resource_ids: list[str] = Field(default_factory=list)
    context_pack_key: str | None = None


class ReviewBundleSecurity(StrictModel):
    sensitivity: Literal["public", "internal", "private", "secret"]
    retention_days: int = Field(ge=0)
    allowed_reviewer_backends: list[str] = Field(min_length=1)
    reviewer_backend: str = Field(min_length=1)
    egress_decision: Literal["local_only", "approved_internal", "approved_external", "denied"]
    external_reviewer_opt_in: bool = False
    purge_derived_artifacts: bool = True
    completeness: Literal["complete", "redacted_partial", "insufficient_evidence"]
    redaction_counts: dict[str, int] = Field(default_factory=dict)
    scope: ReviewBundleScope


class SourceRef(StrictModel):
    resource_id: str = Field(min_length=1)
    source_snapshot_id: str | None = None
    commit_sha: str | None = None
    path: str | None = None
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    content_hash: str | None = None
    title: str | None = None

    @field_validator("line_end")
    @classmethod
    def line_end_after_start(cls, value: int | None, info: Any) -> int | None:
        start = info.data.get("line_start")
        if value is not None and start is not None and value < start:
            raise ValueError("line_end must be >= line_start")
        return value


class CitationRef(StrictModel):
    citation_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    source_ref: SourceRef
    snippet: str | None = None
    snippet_hash: str | None = None
    supports_claim_ids: list[str] = Field(default_factory=list)


class ToolProof(StrictModel):
    proof_id: str = Field(min_length=1)
    kind: Literal["cli", "api", "mcp", "test", "browser", "git", "other"]
    command: list[str] = Field(default_factory=list)
    status: Literal["passed", "failed", "skipped", "not_run"]
    exit_code: int | None = None
    stdout_excerpt: str | None = None
    stderr_excerpt: str | None = None
    artifact_uri: str | None = None


class VerificationLog(StrictModel):
    command: str = Field(min_length=1)
    status: Literal["passed", "failed", "skipped", "not_run"]
    output_excerpt: str | None = None
    artifact_uri: str | None = None


class RuntimeContext(StrictModel):
    sourcebrief_commit: str | None = None
    runtime: str | None = None
    model_backend: str | None = None
    model_name: str | None = None
    prompt_version: str | None = None
    skill_or_agent_pack_version: str | None = None
    retrieval_profile: str | None = None
    top_k: int | None = Field(default=None, ge=1)
    rerank_enabled: bool | None = None
    max_chars: int | None = Field(default=None, ge=1)


class ReviewBundleInput(StrictModel):
    original_query: str = Field(min_length=1)
    task_brief: str = Field(min_length=1)
    acceptance_criteria: list[str] = Field(default_factory=list)
    non_goals: list[str] = Field(default_factory=list)
    user_corrections: list[str] = Field(default_factory=list)


class ReviewBundleOutput(StrictModel):
    summary: str = Field(min_length=1)
    body: str = Field(min_length=1)
    claim_ids: list[str] = Field(default_factory=list)


class ReviewBundle(StrictModel):
    schema_version: Literal["sourcebrief.review-bundle.v1"]
    bundle_id: str = Field(min_length=1)
    kind: BundleKind
    created_at: datetime
    input: ReviewBundleInput
    output: ReviewBundleOutput
    scope: ReviewBundleScope
    security: ReviewBundleSecurity
    runtime: RuntimeContext = Field(default_factory=RuntimeContext)
    source_refs: list[SourceRef] = Field(default_factory=list)
    citations: list[CitationRef] = Field(default_factory=list)
    tool_proof: list[ToolProof] = Field(default_factory=list)
    verification_logs: list[VerificationLog] = Field(default_factory=list)
    reviewer_notes: list[str] = Field(default_factory=list)

    @field_validator("security")
    @classmethod
    def security_scope_matches_bundle_scope(
        cls,
        security: ReviewBundleSecurity,
        info: Any,
    ) -> ReviewBundleSecurity:
        scope = info.data.get("scope")
        if scope is not None and security.scope != scope:
            raise ValueError("security.scope must match bundle scope")
        return security


def sanitize_review_bundle_payload(
    payload: dict[str, Any],
    *,
    policy: ReviewArtifactPolicy,
    scope: ReviewArtifactScope,
    reviewer_backend: str,
    completeness: BundleCompleteness,
) -> tuple[dict[str, Any], RedactionReport]:
    redacted_payload, report = redact_review_artifact(payload)
    if not isinstance(redacted_payload, dict):
        raise TypeError("review bundle payload must be an object")
    redacted_payload["security"] = build_security_metadata(
        policy=policy,
        scope=scope,
        reviewer_backend=reviewer_backend,
        completeness=completeness,
        redaction_report=report,
    )
    return redacted_payload, report


def load_review_bundle(path: str | Path) -> ReviewBundle:
    return ReviewBundle.model_validate_json(Path(path).read_text(encoding="utf-8"))


def review_bundle_json_schema() -> dict[str, Any]:
    return ReviewBundle.model_json_schema()


def write_review_bundle_json_schema(path: str | Path) -> None:
    Path(path).write_text(
        json.dumps(review_bundle_json_schema(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )



def _stable_token(value: str) -> str:
    import re

    slug = "-".join(part for part in re.split(r"[^a-z0-9]+", value.lower()) if part)
    return slug[:64].strip("-") or "answer"


def _context_excerpt_for_citation(agent_context: dict[str, Any], citation: dict[str, Any]) -> str | None:
    context = str(agent_context.get("context") or "")
    path = str(citation.get("path") or "")
    resource_id = str(citation.get("resource_id") or "")
    lines = [line.strip() for line in context.splitlines() if line.strip()]
    for idx, line in enumerate(lines):
        if (path and path in line) or (resource_id and resource_id in line):
            snippet_parts = [line]
            if idx + 1 < len(lines):
                snippet_parts.append(lines[idx + 1])
            return " ".join(snippet_parts)[:1000]
    return None


def _citation_source_ref(citation: dict[str, Any]) -> SourceRef:
    return SourceRef(
        resource_id=str(citation.get("resource_id") or "unknown-resource"),
        source_snapshot_id=citation.get("snapshot_id") or citation.get("source_snapshot_id"),
        commit_sha=citation.get("commit") or citation.get("commit_sha"),
        path=citation.get("path"),
        line_start=citation.get("line_start"),
        line_end=citation.get("line_end"),
        content_hash=citation.get("content_hash"),
        title=citation.get("title") or citation.get("path"),
    )


def build_review_bundle_from_agent_context(
    *,
    agent_context: dict[str, Any],
    workspace_id: str,
    project_id: str,
    query: str,
    runtime: str,
    top_k: int,
    max_chars: int,
    kind: BundleKind = "answer",
    command: list[str] | None = None,
    resource_ids: list[str] | None = None,
    context_pack_key: str | None = None,
    reviewer_backend: str = "local",
    policy: ReviewArtifactPolicy | None = None,
    task_brief: str = "Capture a cited SourceBrief answer for autonomous review.",
) -> ReviewBundle:
    """Create a sanitized review bundle from an agent-context/ask response.

    This is the first opt-in capture path for self-improvement. It does not run a
    reviewer; it persists enough cited evidence for later reviewer/gate work.
    """

    raw_answer = agent_context.get("answer")
    answer: dict[str, Any] = raw_answer if isinstance(raw_answer, dict) else {}
    answer_text = str(answer.get("text") or agent_context.get("context") or "").strip()
    summary = answer_text.split("\n", 1)[0][:240] or "SourceBrief answer capture"
    citations = [citation for citation in agent_context.get("citations") or [] if isinstance(citation, dict)]
    cited_claim_ids = answer.get("claim_ids") if isinstance(answer.get("claim_ids"), list) else None
    if cited_claim_ids:
        claim_ids = [str(claim_id) for claim_id in cited_claim_ids if str(claim_id).strip()]
    elif citations and answer_text:
        claim_ids = [f"claim-{_stable_token(answer_text)}"]
    else:
        claim_ids = []

    bundle_scope = ReviewBundleScope(
        workspace_id=workspace_id,
        project_id=project_id,
        resource_ids=sorted({str(value) for value in (resource_ids or []) if str(value).strip()}),
        context_pack_key=context_pack_key,
    )
    security_scope = ReviewArtifactScope(
        workspace_id=workspace_id,
        project_id=project_id,
        resource_ids=tuple(bundle_scope.resource_ids),
        context_pack_key=context_pack_key,
    )

    citation_refs: list[CitationRef] = []
    source_refs_by_key: dict[tuple[str, str | None, str | None, str | None], SourceRef] = {}
    for idx, citation in enumerate(citations, start=1):
        source_ref = _citation_source_ref(citation)
        source_refs_by_key[(source_ref.resource_id, source_ref.source_snapshot_id, source_ref.path, source_ref.content_hash)] = source_ref
        label = str(citation.get("label") or f"[{idx}]")
        snippet = citation.get("snippet") or _context_excerpt_for_citation(agent_context, citation)
        citation_refs.append(
            CitationRef(
                citation_id=str(citation.get("citation_id") or f"cite-{idx}"),
                label=label,
                source_ref=source_ref,
                snippet=str(snippet) if snippet else None,
                snippet_hash=citation.get("snippet_hash") or citation.get("content_hash"),
                supports_claim_ids=list(claim_ids),
            )
        )

    completeness = BundleCompleteness.COMPLETE if answer_text and citation_refs else BundleCompleteness.INSUFFICIENT_EVIDENCE
    if not resource_ids:
        resource_ids = sorted({citation.source_ref.resource_id for citation in citation_refs if citation.source_ref.resource_id != "unknown-resource"})
        bundle_scope = ReviewBundleScope(
            workspace_id=workspace_id,
            project_id=project_id,
            resource_ids=resource_ids,
            context_pack_key=context_pack_key,
        )
        security_scope = ReviewArtifactScope(
            workspace_id=workspace_id,
            project_id=project_id,
            resource_ids=tuple(resource_ids),
            context_pack_key=context_pack_key,
        )

    raw_payload = {
        "schema_version": REVIEW_BUNDLE_SCHEMA_VERSION,
        "bundle_id": f"rb-{_stable_token(kind)}-{_stable_token(query)}",
        "kind": kind,
        "created_at": datetime.now().astimezone().isoformat(),
        "input": {
            "original_query": query,
            "task_brief": task_brief,
            "acceptance_criteria": ["Answer is grounded in cited SourceBrief evidence."],
            "non_goals": ["Do not run reviewer agents during capture."],
            "user_corrections": [],
        },
        "output": {"summary": summary, "body": answer_text or "No answer text was returned.", "claim_ids": claim_ids},
        "scope": bundle_scope.model_dump(mode="json"),
        "runtime": {
            "runtime": runtime,
            "model_backend": "sourcebrief-agent-context",
            "retrieval_profile": str(agent_context.get("profile") or "agent-context"),
            "top_k": top_k,
            "rerank_enabled": None,
            "max_chars": max_chars,
        },
        "source_refs": [source_ref.model_dump(mode="json") for source_ref in source_refs_by_key.values()],
        "citations": [citation.model_dump(mode="json") for citation in citation_refs],
        "tool_proof": [
            {
                "proof_id": "proof-sourcebrief-agent-context",
                "kind": "api",
                "command": command or [],
                "status": "passed" if answer_text and citation_refs else "not_run",
                "exit_code": 0 if answer_text and citation_refs else None,
                "stdout_excerpt": summary,
                "stderr_excerpt": None,
                "artifact_uri": None,
            }
        ],
        "verification_logs": [
            {
                "command": "sourcebrief review-bundle capture",
                "status": "passed" if completeness is BundleCompleteness.COMPLETE else "skipped",
                "output_excerpt": "captured answer with citations" if citation_refs else "captured bundle marked insufficient_evidence",
                "artifact_uri": None,
            }
        ],
        "reviewer_notes": [],
    }
    sanitized_payload, report = sanitize_review_bundle_payload(
        raw_payload,
        policy=policy or ReviewArtifactPolicy(),
        scope=security_scope,
        reviewer_backend=reviewer_backend,
        completeness=completeness,
    )
    if report.redacted and completeness is BundleCompleteness.COMPLETE:
        sanitized_payload["security"]["completeness"] = BundleCompleteness.REDACTED_PARTIAL.value
    return ReviewBundle.model_validate(sanitized_payload)


def write_review_bundle(path: str | Path, bundle: ReviewBundle) -> Path:
    output_path = Path(path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(bundle.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return output_path
