from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sourcebrief_shared.regression_proposal import (
    proposal_from_finding,
    select_finding,
    write_regression_proposal,
)
from sourcebrief_shared.review_bundle import ReviewBundle, load_review_bundle, write_review_bundle
from sourcebrief_shared.review_history import scan_review_history
from sourcebrief_shared.review_runner import run_review_bundle, write_reviewer_report
from sourcebrief_shared.staged_adoption import stage_regression_proposal
from sourcebrief_shared.validation_gate import (
    validate_regression_proposal,
    write_validation_gate_result,
)

MVP_SMOKE_SCHEMA_VERSION = "sourcebrief.self-improvement-mvp-smoke.v1"

# Keep the smoke path runnable from packaged API containers that do not ship the docs/ tree.
# This mirrors the public-safe unsupported-claim golden bundle used by the CLI docs.
EMBEDDED_UNSUPPORTED_CLAIM_BUNDLE: dict[str, Any] = {
    "schema_version": "sourcebrief.review-bundle.v1",
    "bundle_id": "rb-golden-unsupported-claim-001",
    "kind": "answer",
    "created_at": "2026-06-28T17:10:00Z",
    "input": {
        "original_query": "Does SourceBrief already run a nightly optimizer that edits skills automatically?",
        "task_brief": "Answer from current self-improvement docs.",
        "acceptance_criteria": [
            "Do not claim a future sleep/replay loop is already shipped.",
            "Cite the non-goal or milestone text when discussing nightly optimization.",
        ],
        "non_goals": ["Do not infer implementation status from future roadmap text."],
        "user_corrections": [],
    },
    "output": {
        "summary": "SourceBrief already runs a nightly optimizer that edits skills automatically.",
        "body": "SourceBrief has an automatic nightly optimizer that reviews daily work and updates skills without user involvement.",
        "claim_ids": ["claim-nightly-optimizer-shipped"],
    },
    "scope": {
        "workspace_id": "workspace-demo-public",
        "project_id": "project-sourcebrief-docs",
        "resource_ids": ["resource-self-improvement-docs"],
        "context_pack_key": "sourcebrief-docs",
    },
    "security": {
        "sensitivity": "public",
        "retention_days": 30,
        "allowed_reviewer_backends": ["local", "mock"],
        "reviewer_backend": "mock",
        "egress_decision": "local_only",
        "external_reviewer_opt_in": False,
        "purge_derived_artifacts": True,
        "completeness": "complete",
        "redaction_counts": {},
        "scope": {
            "workspace_id": "workspace-demo-public",
            "project_id": "project-sourcebrief-docs",
            "resource_ids": ["resource-self-improvement-docs"],
            "context_pack_key": "sourcebrief-docs",
        },
    },
    "runtime": {
        "sourcebrief_commit": "embedded-golden-fixture",
        "runtime": "api",
        "model_backend": "mock",
        "model_name": "mock-answerer",
        "prompt_version": "golden-negative-v1",
        "skill_or_agent_pack_version": None,
        "retrieval_profile": "docs",
        "top_k": 5,
        "rerank_enabled": False,
        "max_chars": 4000,
    },
    "source_refs": [
        {
            "resource_id": "resource-self-improvement-docs",
            "source_snapshot_id": "snapshot-docs-main-embedded",
            "commit_sha": "embedded-golden-fixture",
            "path": "docs/SELF_IMPROVEMENT.md",
            "line_start": 34,
            "line_end": 43,
            "content_hash": "sha256:golden-non-goals",
            "title": "Non-goals",
        }
    ],
    "citations": [
        {
            "citation_id": "cite-non-goals",
            "label": "[1]",
            "source_ref": {
                "resource_id": "resource-self-improvement-docs",
                "source_snapshot_id": "snapshot-docs-main-embedded",
                "commit_sha": "embedded-golden-fixture",
                "path": "docs/SELF_IMPROVEMENT.md",
                "line_start": 34,
                "line_end": 43,
                "content_hash": "sha256:golden-non-goals",
                "title": "Non-goals",
            },
            "snippet": "SourceBrief self-improvement does not mean building a nightly optimizer before review bundles, findings, regression proposals, and staging exist.",
            "snippet_hash": "sha256:golden-snippet-non-goals",
            "supports_claim_ids": [],
        }
    ],
    "tool_proof": [],
    "verification_logs": [
        {
            "command": "golden fixture construction",
            "status": "passed",
            "output_excerpt": "negative fixture intentionally contains an unsupported shipped-capability claim",
            "artifact_uri": None,
        }
    ],
    "reviewer_notes": [],
}


def default_mvp_smoke_bundle_path(repo_root: str | Path | None = None) -> Path | None:
    base = Path(repo_root) if repo_root else Path.cwd()
    path = base / "docs" / "examples" / "self-improvement" / "golden" / "review-bundle-unsupported-claim.json"
    return path if path.exists() else None


def load_default_mvp_smoke_bundle(repo_root: str | Path | None = None) -> ReviewBundle:
    path = default_mvp_smoke_bundle_path(repo_root)
    if path is not None:
        return load_review_bundle(path)
    return ReviewBundle.model_validate(EMBEDDED_UNSUPPORTED_CLAIM_BUNDLE)


def run_mvp_smoke_path(
    *,
    out_dir: str | Path,
    bundle_path: str | Path | None = None,
    finding_id: str | None = None,
    owner: str = "qa",
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    output_dir = Path(out_dir).expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)
    bundle = load_review_bundle(bundle_path) if bundle_path else load_default_mvp_smoke_bundle(repo_root)
    bundle_out = write_review_bundle(output_dir / "review-bundle.json", bundle)
    report = run_review_bundle(bundle)
    report_out = write_reviewer_report(output_dir / "review-report.json", report)
    finding = select_finding(report, finding_id)
    proposal = proposal_from_finding(report, finding, owner=owner)
    proposal_out = write_regression_proposal(output_dir / "regression-proposal.json", proposal)
    gate = validate_regression_proposal(proposal)
    gate_out = write_validation_gate_result(output_dir / "validation-gate-result.json", gate)
    staged_receipt = None
    if gate.decision in {"accept", "accept_new_best"}:
        staged_receipt = stage_regression_proposal(
            proposal_path=proposal_out,
            gate_result_path=gate_out,
            out_dir=output_dir / "staged",
        )
    history = scan_review_history(output_dir)
    history_out = output_dir / "history-summary.json"
    history_out.write_text(json.dumps(history.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8")
    smoke_summary = {
        "schema_version": MVP_SMOKE_SCHEMA_VERSION,
        "status": "completed",
        "roadmap_issue": "https://github.com/pingchesu/sourcebrief/issues/157",
        "owner_issue": "https://github.com/pingchesu/sourcebrief/issues/175",
        "out_dir": str(output_dir),
        "bundle_path": str(bundle_out),
        "report_path": str(report_out),
        "proposal_path": str(proposal_out),
        "gate_result_path": str(gate_out),
        "stage_receipt_path": str(Path(staged_receipt.stage_dir) / "receipt.json") if staged_receipt else None,
        "history_summary_path": str(history_out),
        "bundle_id": bundle.bundle_id,
        "report_id": report.report_id,
        "finding_id": finding.finding_id,
        "proposal_id": proposal.proposal_id,
        "gate_decision": gate.decision,
        "history_metrics": history.metrics,
        "no_silent_mutation": True,
    }
    summary_out = output_dir / "mvp-smoke-summary.json"
    summary_out.write_text(json.dumps(smoke_summary, indent=2) + "\n", encoding="utf-8")
    return smoke_summary
