from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

CommandHandler = Callable[[Any, argparse.Namespace], Any]


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
