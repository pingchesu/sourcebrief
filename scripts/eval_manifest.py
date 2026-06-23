#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGES_SHARED = REPO_ROOT / "packages" / "shared"
if str(PACKAGES_SHARED) not in sys.path:
    sys.path.insert(0, str(PACKAGES_SHARED))

from sourcebrief_shared.eval_manifest import (  # noqa: E402
    EvalManifestError,
    api_eval_payloads,
    load_json_file,
    sha256_digest,
    validate_grade_report,
    validate_manifest,
)


def cmd_validate(args: argparse.Namespace) -> int:
    manifest = load_json_file(args.manifest)
    summary = validate_manifest(manifest)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def cmd_split(args: argparse.Namespace) -> int:
    manifest = load_json_file(args.manifest)
    payloads = api_eval_payloads(manifest, max_questions=args.max_questions)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, payload in enumerate(payloads, start=1):
        path = output_dir / f"batch-{index:03d}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"manifest_sha256": sha256_digest(manifest), "batch_count": len(payloads), "output_dir": str(output_dir)}, indent=2, sort_keys=True))
    return 0


def cmd_validate_report(args: argparse.Namespace) -> int:
    manifest = load_json_file(args.manifest) if args.manifest else None
    report = load_json_file(args.report)
    summary = validate_grade_report(report, manifest=manifest)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and split SourceBrief structured real-corpus eval manifests.")
    sub = parser.add_subparsers(dest="command", required=True)

    validate = sub.add_parser("validate", help="Validate a manifest and print its stable digest.")
    validate.add_argument("manifest")
    validate.set_defaults(func=cmd_validate)

    split = sub.add_parser("split", help="Write /retrieval-evals-compatible max-10-question batches.")
    split.add_argument("manifest")
    split.add_argument("--output-dir", required=True)
    split.add_argument("--max-questions", type=int, default=10)
    split.set_defaults(func=cmd_split)

    report = sub.add_parser("validate-report", help="Validate a human/retrieval grading report schema.")
    report.add_argument("report")
    report.add_argument("--manifest")
    report.set_defaults(func=cmd_validate_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except EvalManifestError as exc:
        print(f"eval manifest error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
