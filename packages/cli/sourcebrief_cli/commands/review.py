from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from sourcebrief_cli.client import SourceBriefClient, SourceBriefCliError
from sourcebrief_shared.github_pr_review import (
    GitHubPRBundleError,
    build_review_bundle_from_github_pr_metadata,
    fetch_github_pr_metadata,
    load_pr_metadata_fixture,
)
from sourcebrief_shared.regression_proposal import (
    load_reviewer_report,
    proposal_from_finding,
    select_finding,
    write_regression_proposal,
)
from sourcebrief_shared.review_bundle import write_review_bundle
from sourcebrief_shared.review_history import scan_review_history, show_review_history_record
from sourcebrief_shared.review_runner import (
    ReviewRunnerError,
    ReviewRunOptions,
    run_review_bundle_path,
    write_reviewer_report,
)
from sourcebrief_shared.self_improvement_mvp import run_mvp_smoke_path
from sourcebrief_shared.self_improvement_sleep import (
    SleepReplayError,
    run_sleep_replay,
    write_sleep_replay_summary,
)
from sourcebrief_shared.staged_adoption import stage_regression_proposal
from sourcebrief_shared.validation_gate import (
    validate_regression_proposal_file,
    write_validation_gate_result,
)

CommandHandler = Callable[[Any, argparse.Namespace], Any]


def cmd_review_pr_bundle(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    try:
        metadata_source: Literal["live", "fixture"] = "live"
        if args.metadata_fixture:
            metadata_source = "fixture"
            metadata = load_pr_metadata_fixture(args.metadata_fixture)
            metadata.setdefault("repo", args.repo or metadata.get("repo") or metadata.get("repository"))
            metadata["fixture_path"] = str(Path(args.metadata_fixture).expanduser())
        else:
            if args.pr is None:
                raise GitHubPRBundleError("--pr is required when --metadata-fixture is not provided")
            metadata = fetch_github_pr_metadata(repo=args.repo or "", pr_number=args.pr)
        bundle = build_review_bundle_from_github_pr_metadata(
            metadata,
            workspace_id=args.workspace_id,
            project_id=args.project_id,
            reviewer_backend=args.reviewer_backend,
            metadata_source=metadata_source,
        )
        written = write_review_bundle(args.bundle_out, bundle)
    except (OSError, ValueError) as exc:
        raise SourceBriefCliError(str(exc)) from exc
    subject = bundle.reviewer_notes[0] if bundle.reviewer_notes else ""
    return {
        "status": "pr_review_bundle_written",
        "bundle_path": str(written),
        "bundle_id": bundle.bundle_id,
        "subject": subject,
        "changed_paths": [source_ref.path for source_ref in bundle.source_refs if source_ref.path],
        "bundle": bundle.model_dump(mode="json"),
    }


def cmd_review_run(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    options = ReviewRunOptions(backend=args.backend, allow_incomplete=args.allow_incomplete)
    try:
        report = run_review_bundle_path(args.bundle, options=options)
    except ReviewRunnerError as exc:
        raise SourceBriefCliError(str(exc)) from exc
    output_path = args.report_out
    if output_path:
        written = write_reviewer_report(output_path, report)
        return {
            "status": "reviewed",
            "verdict": report.verdict,
            "report_path": str(written),
            "report": report.model_dump(mode="json"),
        }
    return report.model_dump(mode="json")


def cmd_review_propose(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    report = load_reviewer_report(args.report)
    finding = select_finding(report, args.finding_id)
    proposal = proposal_from_finding(report, finding, owner=args.owner)
    if args.proposal_out:
        written = write_regression_proposal(args.proposal_out, proposal)
        return {
            "status": "proposal_written",
            "proposal_path": str(written),
            "proposal": proposal.model_dump(mode="json"),
        }
    return proposal.model_dump(mode="json")


def cmd_review_gate(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    result = validate_regression_proposal_file(args.proposal)
    if args.result_out:
        written = write_validation_gate_result(args.result_out, result)
        return {
            "status": "gate_evaluated",
            "decision": result.decision,
            "result_path": str(written),
            "result": result.model_dump(mode="json"),
        }
    return result.model_dump(mode="json")


def cmd_review_stage(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    try:
        receipt = stage_regression_proposal(
            proposal_path=args.proposal,
            gate_result_path=args.gate_result,
            out_dir=args.out_dir,
        )
    except (OSError, ValueError) as exc:
        raise SourceBriefCliError(str(exc)) from exc
    return {
        "status": "staged",
        "stage_dir": receipt.stage_dir,
        "receipt_path": str(Path(receipt.stage_dir) / "receipt.json"),
        "patch_path": receipt.patch_path,
        "apply_command": receipt.apply_command,
        "rollback_command": receipt.rollback_command,
        "receipt": receipt.model_dump(mode="json"),
    }


def cmd_review_history_list(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    try:
        summary = scan_review_history(args.dir)
    except (OSError, ValueError) as exc:
        raise SourceBriefCliError(str(exc)) from exc
    return summary.model_dump(mode="json")


def cmd_review_history_show(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    try:
        return show_review_history_record(args.dir, args.artifact)
    except (OSError, ValueError) as exc:
        raise SourceBriefCliError(str(exc)) from exc


def cmd_review_mvp_smoke(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    try:
        return run_mvp_smoke_path(
            out_dir=args.out_dir,
            bundle_path=Path(args.bundle).expanduser() if args.bundle else None,
            finding_id=args.finding_id,
            owner=args.owner,
        )
    except (OSError, ValueError) as exc:
        raise SourceBriefCliError(str(exc)) from exc


def cmd_review_sleep(_client: SourceBriefClient, args: argparse.Namespace) -> Any:
    try:
        summary = run_sleep_replay(
            args.dir,
            out_dir=args.out_dir,
            min_occurrences=args.min_occurrences,
            max_artifacts=args.max_artifacts,
            dry_run=True,
        )
        if args.summary_out:
            write_sleep_replay_summary(args.summary_out, summary)
    except (OSError, SleepReplayError) as exc:
        raise SourceBriefCliError(str(exc)) from exc
    return summary.model_dump(mode="json")





def register_review_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    *,
    pr_bundle_command: CommandHandler,
    run_command: CommandHandler,
    propose_command: CommandHandler,
    gate_command: CommandHandler,
    stage_command: CommandHandler,
    history_list_command: CommandHandler,
    history_show_command: CommandHandler,
    mvp_smoke_command: CommandHandler,
    sleep_command: CommandHandler,
) -> None:
    review = subparsers.add_parser(
        "review", help="self-improvement review bundle commands"
    ).add_subparsers(dest="review_command")
    review_pr_bundle = review.add_parser(
        "pr-bundle", help="create a review bundle from GitHub PR metadata"
    )
    review_pr_bundle.add_argument(
        "--repo", help="GitHub repository in owner/name form; required unless fixture includes repo"
    )
    review_pr_bundle.add_argument(
        "--pr", type=int, help="GitHub pull request number; required unless --metadata-fixture is used"
    )
    review_pr_bundle.add_argument(
        "--metadata-fixture", help="local PR metadata JSON fixture for offline/dry-run bundle creation"
    )
    review_pr_bundle.add_argument(
        "--workspace",
        "--workspace-id",
        dest="workspace_id",
        metavar="WORKSPACE",
        default="github",
        help="workspace name/slug or advanced ID to record in the bundle scope",
    )
    review_pr_bundle.add_argument(
        "--project",
        "--project-id",
        dest="project_id",
        metavar="PROJECT",
        default="github-pr",
        help="project name or advanced ID to record in the bundle scope",
    )
    review_pr_bundle.add_argument("--reviewer-backend", default="local", choices=["local", "mock"])
    review_pr_bundle.add_argument(
        "--bundle-out", required=True, help="write the sourcebrief.review-bundle.v1 PR bundle to this path"
    )
    review_pr_bundle.set_defaults(func=pr_bundle_command)

    review_run = review.add_parser("run", help="run a local reviewer over a review bundle")
    review_run.add_argument("--bundle", required=True, help="path to a sourcebrief.review-bundle.v1 JSON file")
    review_run.add_argument("--report-out", help="write the sourcebrief.review-report.v1 JSON report to this path")
    review_run.add_argument("--backend", default="local", choices=["local", "deterministic", "mock"])
    review_run.add_argument(
        "--allow-incomplete", action="store_true", help="diagnose incomplete/redacted bundles instead of failing closed"
    )
    review_run.set_defaults(func=run_command)

    review_propose = review.add_parser(
        "propose", help="create a regression proposal from a reviewer report finding"
    )
    review_propose.add_argument("--report", required=True, help="path to a sourcebrief.review-report.v1 JSON file")
    review_propose.add_argument(
        "--finding-id", help="specific proposal-eligible finding id; defaults to the first candidate"
    )
    review_propose.add_argument("--proposal-out", help="write the sourcebrief.regression-proposal.v1 artifact to this path")
    review_propose.add_argument("--owner", default="unassigned")
    review_propose.set_defaults(func=propose_command)

    review_gate = review.add_parser("gate", help="validate a regression proposal with the deterministic MVP gate")
    review_gate.add_argument("--proposal", required=True, help="path to a sourcebrief.regression-proposal.v1 JSON file")
    review_gate.add_argument("--result-out", help="write the sourcebrief.validation-gate-result.v1 artifact")
    review_gate.set_defaults(func=gate_command)

    review_stage = review.add_parser("stage", help="stage an accepted proposal as a human-reviewable patch and receipt")
    review_stage.add_argument("--proposal", required=True, help="path to a sourcebrief.regression-proposal.v1 JSON file")
    review_stage.add_argument(
        "--gate-result", required=True, help="path to an accepted sourcebrief.validation-gate-result.v1 JSON file"
    )
    review_stage.add_argument("--out-dir", required=True, help="directory where staged artifacts should be written")
    review_stage.set_defaults(func=stage_command)

    review_history = review.add_parser(
        "history", help="inspect local self-improvement artifact history"
    ).add_subparsers(dest="history_command")
    review_history_list = review_history.add_parser(
        "list", help="list review bundles, reports, proposals, gates, and staged receipts"
    )
    review_history_list.add_argument("--dir", required=True, help="artifact directory to scan recursively")
    review_history_list.set_defaults(func=history_list_command)
    review_history_show = review_history.add_parser(
        "show", help="show one redacted history artifact by id or relative path"
    )
    review_history_show.add_argument("artifact", help="artifact id or path relative to --dir")
    review_history_show.add_argument("--dir", required=True, help="artifact directory to scan recursively")
    review_history_show.set_defaults(func=history_show_command)

    review_mvp_smoke = review.add_parser("mvp-smoke", help="run the local end-to-end self-improvement MVP smoke path")
    review_mvp_smoke.add_argument(
        "--bundle", help="review bundle fixture/path; defaults to the public unsupported-claim golden bundle"
    )
    review_mvp_smoke.add_argument("--finding-id", help="specific proposal-eligible finding id; defaults to first candidate")
    review_mvp_smoke.add_argument("--owner", default="qa")
    review_mvp_smoke.add_argument("--out-dir", required=True, help="directory where smoke artifacts should be written")
    review_mvp_smoke.set_defaults(func=mvp_smoke_command)

    review_sleep = review.add_parser("sleep", help="dry-run recurring-learning mining over bounded review artifacts")
    review_sleep.add_argument("--dir", required=True, help="directory of review/proposal artifacts to scan recursively")
    review_sleep.add_argument("--out-dir", help="write dry-run candidate proposal/gate artifacts to this directory")
    review_sleep.add_argument("--summary-out", help="write the sourcebrief.sleep-replay-summary.v1 artifact")
    review_sleep.add_argument("--min-occurrences", type=int, default=2)
    review_sleep.add_argument("--max-artifacts", type=int, default=100)
    review_sleep.set_defaults(func=sleep_command)
