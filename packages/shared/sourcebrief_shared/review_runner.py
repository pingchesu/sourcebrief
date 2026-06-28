from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sourcebrief_shared.citation_support import citation_support_findings
from sourcebrief_shared.review_bundle import ReviewBundle, load_review_bundle
from sourcebrief_shared.review_findings import (
    ReportSubjectRef,
    ReviewerFinding,
    ReviewerReport,
    build_reviewer_report,
)

REVIEWER_PROMPT_TEMPLATE = """You are a SourceBrief self-improvement reviewer.

Review bundle: {bundle_id}
Lenses: citation_support, scope, missing_evidence, product_dx, safety, regression.

Rules:
- Return only sourcebrief.review-report.v1 JSON.
- Use blocker/major only when evidence_refs point into the bundle.
- Do not mutate prompts, skills, code, configs, or production state.
- Treat missing or redacted evidence as insufficient proof, not permission to guess.
"""


class ReviewRunnerError(ValueError):
    pass


@dataclass(frozen=True)
class ReviewRunOptions:
    backend: str = "local"
    allow_incomplete: bool = False


def build_reviewer_prompt(bundle: ReviewBundle) -> str:
    return REVIEWER_PROMPT_TEMPLATE.format(bundle_id=bundle.bundle_id)


def _incomplete_bundle_findings(bundle: ReviewBundle) -> list[ReviewerFinding]:
    if bundle.security.completeness == "complete":
        return []
    evidence_refs = [citation.citation_id for citation in bundle.citations] or [bundle.bundle_id]
    return [
        ReviewerFinding(
            finding_id=f"finding-insufficient-evidence-{bundle.bundle_id}",
            bundle_id=bundle.bundle_id,
            severity="major",
            type="missing_evidence",
            summary=f"Bundle completeness is {bundle.security.completeness}.",
            claim="Bundle does not contain enough unredacted answer/citation/tool proof for normal review.",
            claim_ids=bundle.output.claim_ids,
            evidence_refs=evidence_refs,
            impact="Reviewer output would be unreliable without complete evidence.",
            suggested_fix="Recapture the answer with citations and tool proof, or explicitly run with allow_incomplete for diagnostic review.",
            regression_candidate=False,
            confidence="high",
            reviewer_lens="missing_evidence",
            proposal_eligibility="not_eligible",
        )
    ]


def _subject_refs_for_bundle(bundle: ReviewBundle) -> list[ReportSubjectRef]:
    if bundle.kind != "pr_review":
        return []
    for note in bundle.reviewer_notes:
        if note.startswith("github_pr_json "):
            try:
                raw = json.loads(note[len("github_pr_json ") :])
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict):
                continue
            repo = str(raw.get("repo") or "unknown/repo")
            number = str(raw.get("number") or "unknown")
            raw_paths = raw.get("changed_paths") or []
            changed_paths = [str(path) for path in raw_paths] if isinstance(raw_paths, list) else []
            return [
                ReportSubjectRef(
                    kind="github_pr",
                    ref_id=f"{repo}#{number}",
                    url=str(raw["url"]) if raw.get("url") else None,
                    head_sha=str(raw["head_sha"]) if raw.get("head_sha") else None,
                    changed_paths=changed_paths,
                )
            ]
        if not note.startswith("github_pr "):
            continue
        fields: dict[str, str] = {}
        for part in note[len("github_pr ") :].split():
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            fields[key] = value
        repo = fields.get("repo") or "unknown/repo"
        number = fields.get("number") or "unknown"
        changed_paths = [path for path in (fields.get("changed_paths") or "").split(",") if path]
        return [
            ReportSubjectRef(
                kind="github_pr",
                ref_id=f"{repo}#{number}",
                url=fields.get("url"),
                head_sha=fields.get("head_sha"),
                changed_paths=changed_paths,
            )
        ]
    if bundle.source_refs:
        first = bundle.source_refs[0]
        changed_paths = [source_ref.path for source_ref in bundle.source_refs if source_ref.path]
        return [
            ReportSubjectRef(
                kind="github_pr",
                ref_id=first.resource_id.removeprefix("github-pr:"),
                head_sha=first.commit_sha,
                changed_paths=changed_paths,
            )
        ]
    return []


def run_review_bundle(bundle: ReviewBundle, *, options: ReviewRunOptions | None = None) -> ReviewerReport:
    options = options or ReviewRunOptions()
    if options.backend not in {"local", "deterministic", "mock"}:
        raise ReviewRunnerError(f"unsupported reviewer backend for local runner: {options.backend}")
    if options.backend not in bundle.security.allowed_reviewer_backends:
        raise ReviewRunnerError(f"reviewer backend {options.backend} is not allowed by bundle policy")
    if bundle.security.egress_decision == "denied":
        raise ReviewRunnerError("bundle policy denies reviewer egress for the selected backend")
    if bundle.security.completeness != "complete" and not options.allow_incomplete:
        raise ReviewRunnerError(
            f"bundle {bundle.bundle_id} is {bundle.security.completeness}; recapture it or pass allow_incomplete for diagnostic review"
        )
    findings: list[ReviewerFinding] = []
    findings.extend(_incomplete_bundle_findings(bundle))
    findings.extend(citation_support_findings(bundle))
    return build_reviewer_report(
        report_id=f"review-{bundle.bundle_id}",
        bundle_id=bundle.bundle_id,
        reviewer_backend=options.backend,
        reviewer_lenses=["citation_support", "missing_evidence"],
        generated_at=bundle.created_at,
        findings=findings,
        subject_refs=_subject_refs_for_bundle(bundle),
    )


def run_review_bundle_path(path: str | Path, *, options: ReviewRunOptions | None = None) -> ReviewerReport:
    return run_review_bundle(load_review_bundle(path), options=options)


def write_reviewer_report(path: str | Path, report: ReviewerReport) -> Path:
    output_path = Path(path).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return output_path


def reviewer_report_json_schema() -> dict[str, object]:
    return ReviewerReport.model_json_schema()


def reviewer_report_to_json(report: ReviewerReport) -> str:
    return json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
