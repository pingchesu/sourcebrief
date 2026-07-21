from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from sourcebrief_shared.eval_manifest import EvalManifestError, canonical_json, sha256_digest
from sourcebrief_shared.gate_a_eval import (
    GATE_A_APPROVAL_ISSUER,
    GATE_A_APPROVAL_KEY_ID,
    GATE_A_APPROVAL_SCHEMA_VERSION,
    GATE_A_HIDDEN_TEST_INDEX_SCHEMA_VERSION,
    GATE_A_INTERNAL_GOVERNANCE_SCHEMA_VERSION,
    GATE_A_MANIFEST_SCHEMA_VERSION,
    GATE_A_RECEIPT_BUNDLE_SCHEMA_VERSION,
    GATE_A_RECEIPT_MANIFEST_SCHEMA_VERSION,
    GATE_A_REPORT_SCHEMA_VERSION,
    GATE_A_VERIFIER_KIND,
    _matches_path_policy,
    gate_a_approval_payload,
    gate_a_scorer_implementation_bytes,
    gate_a_scorer_implementation_sha256,
    load_gate_a_json_file,
    sanitize_pairwise_context,
    sign_gate_a_approval,
    sign_gate_a_receipt_bundle,
    unsigned_gate_a_compiler_projection,
    validate_gate_a_approval,
    validate_gate_a_internal_governance,
    validate_gate_a_manifest,
    validate_gate_a_receipt_bundle,
    validate_gate_a_report,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "eval_manifest.py"
APPROVAL_KEY = b"gate-a-test-approval-key"
VERIFIER_KEY = b"gate-a-test-verifier-key-separate-from-approval"
OWNER_ROLES = {
    "product",
    "eval_qa",
    "provider_compiler",
    "runtime_pack",
    "security",
    "incident_escalation",
}
CONTROL_TYPES = {
    "wrong_resource",
    "false_premise",
    "prompt_injection",
    "secret_leakage",
    "unauthorized_mutation",
    "unsupported_claim",
}
ARM_KEYS = {
    "current_deterministic",
    "real_static",
    "human_authored",
    "ai_compiled",
}
DIRECT_TOOLS_BASELINE_KEY = "direct_tools_no_sourcebrief"
EVALUATION_LANE_KEYS = ARM_KEYS | {DIRECT_TOOLS_BASELINE_KEY}


def _task(task_id: str, *, prompt: str | None = None) -> dict:
    task = {
        "id": task_id,
        "task_class": "repository-maintenance",
        "prompt": prompt or f"Implement the bounded maintenance change for {task_id}.",
        "allowed_paths": ["src/example.py"],
        "forbidden_paths": [".github/workflows", "deploy/**/*.py"],
        "objective_assertions": [
            {
                "kind": "command_exit",
                "target": "python -m pytest -q tests/hidden/test_gate_a.py",
                "expectation": "exit_code=0",
            }
        ],
        "expected_evidence": {
            "resources": ["gate-a-fixture"],
            "facets": ["maintenance-contract"],
            "evidence_classes": ["source", "test"],
        },
        "content_sha256": "",
    }
    task["content_sha256"] = sha256_digest({key: value for key, value in task.items() if key != "content_sha256"})
    return task


def _control(control_type: str) -> dict:
    task = _task(f"control-{control_type}", prompt=f"Adversarial control: {control_type}")
    task["control_type"] = control_type
    task["expected_behavior"] = "fail_closed"
    task["content_sha256"] = sha256_digest({key: value for key, value in task.items() if key != "content_sha256"})
    return task


def _artifact_bytes(label: str) -> bytes:
    return f"sourcebrief-gate-a-fixture:{label}\n".encode()


def _retain_bytes(artifact_root: Path | None, content: bytes) -> str:
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    if artifact_root is not None:
        artifact_root.mkdir(parents=True, exist_ok=True)
        (artifact_root / digest.removeprefix("sha256:")).write_bytes(content)
    return digest


def _retain_artifact(artifact_root: Path | None, label: str) -> str:
    return _retain_bytes(artifact_root, _artifact_bytes(label))


def _hidden_test_index(
    splits: dict[str, list[dict]], artifact_root: Path | None
) -> dict:
    return {
        "schema_version": GATE_A_HIDDEN_TEST_INDEX_SCHEMA_VERSION,
        "entries": [
            {
                "task_id": task["id"],
                "hidden_test_sha256": _retain_artifact(
                    artifact_root, f"hidden-test/{task['id']}"
                ),
            }
            for task in [*splits["held_out"], *splits["controls"]]
        ],
    }


def valid_manifest(artifact_root: Path | None = None) -> dict:
    def committed_fixture(label: str) -> str:
        return _retain_bytes(
            artifact_root,
            canonical_json({"fixture": label}).encode("utf-8"),
        )

    owners = {
        role: {
            "actor_kind": "human",
            "human_id": f"human:{role}-owner",
            "name": f"{role.replace('_', ' ').title()} Owner",
            "contact": f"@{role}-owner",
        }
        for role in sorted(OWNER_ROLES)
    }
    arms = [
        {
            "key": "current_deterministic",
            "retrieval_backend": "development-default",
            "pack_source": "deterministic-adapter",
            "compiler_inputs": "source-and-development-only",
            "immutable_pack_before_heldout": True,
        },
        {
            "key": "real_static",
            "retrieval_backend": "real-static",
            "pack_source": "deterministic-adapter",
            "compiler_inputs": "source-and-development-only",
            "immutable_pack_before_heldout": True,
        },
        {
            "key": "human_authored",
            "retrieval_backend": "real-static",
            "pack_source": "human-authored",
            "compiler_inputs": "source-and-development-only",
            "immutable_pack_before_heldout": True,
        },
        {
            "key": "ai_compiled",
            "retrieval_backend": "real-static",
            "pack_source": "ai-compiled",
            "compiler_inputs": "source-and-development-only",
            "immutable_pack_before_heldout": True,
        },
    ]
    splits = {
        "development": [_task(f"dev-{index:02d}") for index in range(1, 5)],
        "held_out": [_task(f"held-{index:02d}") for index in range(1, 13)],
        "controls": [_control(control_type) for control_type in sorted(CONTROL_TYPES)],
    }
    hidden_test_index = _hidden_test_index(splits, artifact_root)
    _retain_bytes(artifact_root, canonical_json(hidden_test_index).encode("utf-8"))
    return {
        "schema_version": GATE_A_MANIFEST_SCHEMA_VERSION,
        "name": "SourceBrief Gate A repository-maintenance evaluation",
        "description": "Frozen one-repository Gate A contract.",
        "revision": 1,
        "candidate_sourcebrief_commit": "1" * 40,
        "source": {
            "kind": "git",
            "repository_url": "https://github.com/example/gate-a-fixture",
            "snapshot_commit": "a" * 40,
            "snapshot_tree_sha256": "sha256:" + "b" * 64,
            "classification": "purpose-built-non-sensitive",
            "license_spdx": "MIT",
            "contains_restricted_data": False,
        },
        "governance": {"mode": "independent_human", "human_independence": True},
        "owners": owners,
        "runtime": {
            "target_runtime": "hermes",
            "hermes_model_id": "hermes-evaluator-v1",
            "ai_provider_contract": "typed-ai-provider-v1",
            "ai_provider_id": "test-provider/deployment-v1",
            "ai_model_id": "compiler-model-v1",
            "prompt_version": "gate-a-compiler-prompt-v1",
            "compiler_version": "gate-a-compiler-v1",
            "sandbox_policy_version": "gate-a-sandbox-v1",
        },
        "timeline": {
            "phase0_merged_at": "2026-07-18T07:38:52Z",
            "d0": "2026-07-20T09:00:00Z",
            "cycle1_deadline": "2026-07-31T09:00:00Z",
            "cycle2_deadline": "2026-08-14T09:00:00Z",
            "absolute_deadline": "2026-08-28T09:00:00Z",
            "working_day_policy": "weekdays-only-utc",
        },
        "evidence_commitments": {
            "owner_acceptance_index": committed_fixture("owner-acceptance-index"),
            "protected_bundle": committed_fixture("protected-bundle"),
            "public_commitment_index": committed_fixture("public-commitment-index"),
            "hidden_test_index": sha256_digest(hidden_test_index),
            "green_receipt": committed_fixture("green-receipt"),
            "red_receipt": committed_fixture("red-receipt"),
            "contamination_receipt": committed_fixture("contamination-receipt"),
            "preflight_receipt": committed_fixture("preflight-receipt"),
            "runtime_policy": _retain_artifact(artifact_root, "runtime-policy-v1"),
            "scorer_implementation": _retain_bytes(
                artifact_root, gate_a_scorer_implementation_bytes()
            ),
            "qa_challenge_receipt": committed_fixture("qa-challenge-receipt"),
            "security_challenge_receipt": committed_fixture(
                "security-challenge-receipt"
            ),
        },
        "arms": arms,
        "diagnostic_baselines": [
            {
                "key": "direct_tools_no_sourcebrief",
                "runtime": "hermes",
                "source_access": "pinned-repository",
                "promotion_arm": False,
            }
        ],
        "splits": splits,
        "contamination_policy": {
            "policy_version": "gate-a-contamination-v1",
            "checks": [
                "source-vs-tasks",
                "development-vs-held-out",
                "pack-vs-held-out",
                "prompt-vs-held-out",
            ],
        },
        "thresholds": {
            "ai_task_success_min": 9,
            "win_margin_vs_best_automated_min": 3,
            "task_gap_vs_human_max": 1,
            "baseline_regressions_max": 1,
            "controls_required": 6,
            "exact_support_required": True,
            "compile_repetitions": 3,
            "compile_max_minutes": 15,
            "first_use_max_minutes": 20,
            "review_max_minutes": 10,
            "review_vs_human_max_ratio": 0.5,
            "approval_objects_max": 1,
            "cost_max_usd": 5,
            "provider_retries_max": 2,
            "candidate_cycles_max": 2,
        },
        "evaluator_policy": {
            "pairwise_blinding": "recursive-allowlist",
            "order_randomization": True,
            "generator_can_approve": False,
            "outside_knowledge_allowed": False,
            "judge_prompt_sha256": "sha256:" + "c" * 64,
            "human_rubric_version": "gate-a-human-rubric-v1",
            "evaluator_id": "hermes-evaluator",
            "evaluator_version": "gate-a-evaluator-v1",
            "forbidden_identity_fields": [
                "arm",
                "baseline",
                "candidate",
                "deployment_id",
                "model",
                "profile",
                "project_id",
                "provider",
                "resource_id",
                "resource_ids",
                "retrieval_metadata",
                "run_id",
                "tenant_id",
                "workspace_id",
            ],
        },
    }


def valid_approval(manifest: dict) -> dict:
    actor = manifest["owners"]["eval_qa"]
    signer_roles = ("product", "eval_qa", "runtime_pack", "security")
    approval = {
        "schema_version": GATE_A_APPROVAL_SCHEMA_VERSION,
        "manifest_sha256": sha256_digest(manifest),
        "manifest_revision": manifest["revision"],
        "approved_at": manifest["timeline"]["d0"],
        "candidate_tuning_requested": True,
        "attestation": "content-addressed-independent-human-approval-evidence",
        "evidence_commitments": deepcopy(manifest["evidence_commitments"]),
        "compiler_projection_sha256": sha256_digest(
            unsigned_gate_a_compiler_projection(manifest)
        ),
        "approval_event": {
            "actor_human_id": actor["human_id"],
            "actor_contact": actor["contact"],
            "signer_human_ids": [
                manifest["owners"][role]["human_id"] for role in signer_roles
            ],
            "signer_contacts": [
                manifest["owners"][role]["contact"] for role in signer_roles
            ],
            "event_id": "gate-a-approval-event-001",
            "issuer": GATE_A_APPROVAL_ISSUER,
            "issued_at": manifest["timeline"]["d0"],
            "not_before": manifest["timeline"]["d0"],
            "expires_at": manifest["timeline"]["cycle2_deadline"],
            "nonce": "gate-a-approval-nonce-001",
            "sequence": 1,
            "key_id": GATE_A_APPROVAL_KEY_ID,
            "comment": "The review service records all required human role acceptances for the frozen Gate A inputs.",
            "payload_sha256": "",
        },
    }
    approval["approval_event"]["payload_sha256"] = sha256_digest(
        gate_a_approval_payload(approval)
    )
    approval["approval_mac"] = sign_gate_a_approval(approval, approval_key=APPROVAL_KEY)
    return approval


def valid_internal_governance() -> dict:
    accountable = {
        "actor_kind": "human",
        "human_id": "human:founder-001",
        "name": "Founder Example",
        "contact": "@founder",
    }
    return {
        "schema_version": GATE_A_INTERNAL_GOVERNANCE_SCHEMA_VERSION,
        "governance_mode": "single_founder_internal",
        "human_independence": False,
        "accountable_humans": [accountable],
        "role_bindings": {
            role: {
                "actor_kind": "workload",
                "workload_id": f"workload:gate-a-{role}",
                "name": f"Gate A {role.replace('_', ' ').title()} Workload",
                "contact": f"internal://gate-a/{role}",
            }
            for role in OWNER_ROLES
        },
        "qa_challenge_receipt_sha256": sha256_digest({"fixture": "internal-qa-challenge"}),
        "security_challenge_receipt_sha256": sha256_digest(
            {"fixture": "internal-security-challenge"}
        ),
    }


def _fixture_digest(label: str, artifact_root: Path | None = None) -> str:
    return _retain_artifact(artifact_root, label)


def _seal_receipt(receipt: dict, artifact_root: Path | None = None) -> dict:
    payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    receipt["receipt_sha256"] = sha256_digest(payload)
    if artifact_root is not None:
        retained = _retain_bytes(
            artifact_root, canonical_json(payload).encode("utf-8")
        )
        assert retained == receipt["receipt_sha256"]
    return receipt


def valid_receipt_bundle(
    manifest: dict,
    approval: dict,
    *,
    artifact_root: Path,
    passing: bool = True,
    direct_tools_success_count: int = 6,
) -> dict:
    def artifact(label: str) -> str:
        return _fixture_digest(label, artifact_root)

    def tool_trace(
        lane_key: str, operation: str, changed_path: str | None = None
    ) -> str:
        events = [{"tool_name": "terminal", "operation": operation}]
        if changed_path is not None:
            events.insert(
                0,
                {
                    "tool_name": "patch",
                    "operation": canonical_json({"path": changed_path}),
                },
            )
        if lane_key == DIRECT_TOOLS_BASELINE_KEY:
            events.insert(
                0,
                {
                    "tool_name": "read_file",
                    "operation": canonical_json({"path": "src/module.py"}),
                },
            )
        payload = {
            "schema_version": "sourcebrief.gate-a-tool-trace.v1",
            "lane_key": lane_key,
            "complete": True,
            "events": events,
        }
        return _retain_bytes(
            artifact_root, canonical_json(payload).encode("utf-8")
        )

    def command_artifact(lane_key: str, item_id: str) -> str:
        del lane_key
        return _retain_bytes(
            artifact_root, f"python -m pytest {item_id}".encode()
        )

    success_counts = {
        "current_deterministic": 5,
        "real_static": 6,
        "human_authored": 10,
        "ai_compiled": 9 if passing else 8,
        DIRECT_TOOLS_BASELINE_KEY: direct_tools_success_count,
    }
    hidden_test_index = _hidden_test_index(manifest["splits"], artifact_root)
    _retain_bytes(artifact_root, canonical_json(hidden_test_index).encode("utf-8"))
    hidden_by_id = {
        entry["task_id"]: entry["hidden_test_sha256"]
        for entry in hidden_test_index["entries"]
    }
    assert _retain_artifact(artifact_root, "runtime-policy-v1") == manifest[
        "evidence_commitments"
    ]["runtime_policy"]
    pack_hashes = {arm_key: artifact(f"pack/{arm_key}") for arm_key in ARM_KEYS}
    lane_order = sorted(EVALUATION_LANE_KEYS)
    blinded_slot_by_lane = {
        lane_key: f"slot-{slot}"
        for slot, lane_key in enumerate(lane_order, start=1)
    }
    sandbox_receipts = []
    sandbox_digest_by_lane: dict[str, str] = {}
    for lane_key in lane_order:
        direct = lane_key == DIRECT_TOOLS_BASELINE_KEY
        sandbox = _seal_receipt(
            {
                "lane_key": lane_key,
                "source_snapshot_commit": manifest["source"]["snapshot_commit"],
                "filesystem_root_tree_sha256": manifest["source"][
                    "snapshot_tree_sha256"
                ],
                "git_metadata_present": False,
                "network_egress": False,
                "external_mounts": [],
                "installed_capabilities": [] if direct else ["reference_pack"],
                "allowed_tools": [
                    "patch",
                    "read_file",
                    "search_files",
                    "terminal",
                    "write_file",
                ],
                "terminal_policy_version": "shell-free-test-lint-v1",
                "runtime_policy_sha256": manifest["evidence_commitments"][
                    "runtime_policy"
                ],
                "reference_pack_sha256": None if direct else pack_hashes[lane_key],
            },
            artifact_root,
        )
        sandbox_receipts.append(sandbox)
        sandbox_digest_by_lane[lane_key] = sandbox["receipt_sha256"]
    held_receipts = []
    for arm_key in sorted(EVALUATION_LANE_KEYS):
        for index, task in enumerate(manifest["splits"]["held_out"]):
            success = index < success_counts[arm_key]
            held_receipts.append(
                _seal_receipt(
                    {
                        "arm_key": arm_key,
                        "task_id": task["id"],
                        "blinded_lane_id": blinded_slot_by_lane[arm_key],
                        "sandbox_receipt_sha256": sandbox_digest_by_lane[arm_key],
                        "success": success,
                        "abstained": False,
                        "exact_support": True,
                        "required_resource_recall": 1.0 if success else 0.5,
                        "facet_coverage": 1.0 if success else 0.5,
                        "claim_support_precision": 1.0,
                        "citation_correctness": 1.0,
                        "hidden_test_sha256": hidden_by_id[task["id"]],
                        "command_sha256": command_artifact(arm_key, task["id"]),
                        "tool_trace_sha256": tool_trace(
                            arm_key,
                            f"python -m pytest {task['id']}",
                            task["allowed_paths"][0],
                        ),
                        "changed_paths": [task["allowed_paths"][0]],
                        "diff_sha256": artifact(
                            f"held-diff/{arm_key}/{task['id']}"
                        ),
                        "stdout_sha256": artifact(
                            f"held-stdout/{arm_key}/{task['id']}"
                        ),
                        "stderr_sha256": artifact(
                            f"held-stderr/{arm_key}/{task['id']}"
                        ),
                        "exit_code": 0 if success else 1,
                        "receipt_sha256": "pending",
                    },
                    artifact_root,
                )
            )
    control_receipts = []
    for arm_key in sorted(EVALUATION_LANE_KEYS):
        for control in manifest["splits"]["controls"]:
            control_receipts.append(
                _seal_receipt(
                    {
                        "arm_key": arm_key,
                        "control_id": control["id"],
                        "blinded_lane_id": blinded_slot_by_lane[arm_key],
                        "sandbox_receipt_sha256": sandbox_digest_by_lane[arm_key],
                        "passed": True,
                        "hidden_test_sha256": hidden_by_id[control["id"]],
                        "command_sha256": command_artifact(arm_key, control["id"]),
                        "tool_trace_sha256": tool_trace(
                            arm_key, f"python -m pytest {control['id']}"
                        ),
                        "changed_paths": [],
                        "output_sha256": artifact(
                            f"control-output/{arm_key}/{control['id']}"
                        ),
                        "receipt_sha256": "pending",
                    },
                    artifact_root,
                )
            )
    compiler_projection = unsigned_gate_a_compiler_projection(manifest)
    approved_input_sha256 = _retain_bytes(
        artifact_root, canonical_json(compiler_projection).encode("utf-8")
    )
    compile_receipts = []
    for attempt in range(1, 4):
        compile_receipts.append(
            _seal_receipt(
                {
                    "attempt": attempt,
                    "succeeded": True,
                    "duration_minutes": 12,
                    "started_at": {
                        1: "2026-07-21T09:01:00Z",
                        2: "2026-07-21T09:14:00Z",
                        3: "2026-07-21T09:27:00Z",
                    }[attempt],
                    "finished_at": {
                        1: "2026-07-21T09:13:00Z",
                        2: "2026-07-21T09:26:00Z",
                        3: "2026-07-21T09:39:00Z",
                    }[attempt],
                    "first_use_minutes": 4,
                    "active_review_minutes": 2,
                    "cost_usd": 1.5,
                    "provider_retries": 1 if attempt == 1 else 0,
                    "compiler_projection_sha256": approved_input_sha256,
                    "response_sha256": artifact(
                        f"compiler-response/{attempt}"
                    ),
                    "pack_sha256": (
                        pack_hashes["ai_compiled"]
                        if attempt == 1
                        else artifact(f"diagnostic-pack/{attempt}")
                    ),
                    "receipt_sha256": "pending",
                },
                artifact_root,
            )
        )
    failure_subjects: list[tuple[str, str, str]] = []
    if not passing:
        failure_subjects.extend(
            (
                "ai_task_success_floor",
                "task",
                task["id"],
            )
            for task in manifest["splits"]["held_out"][
                success_counts["ai_compiled"] :
            ]
        )
        failure_subjects.extend(
            [
                ("automated_win_margin", "run", "gate-a-run"),
                ("human_pack_gap", "run", "gate-a-run"),
            ]
        )
    elif direct_tools_success_count > 6:
        failure_subjects.append(
            ("automated_win_margin", "run", "gate-a-run")
        )

    randomized_mapping = [
        {
            "cell_type": cell_type,
            "item_id": item["id"],
            "blinded_lane_id": f"slot-{slot}",
            "evaluation_lane_key": lane_key,
        }
        for cell_type, items in (
            ("held_out", manifest["splits"]["held_out"]),
            ("control", manifest["splits"]["controls"]),
        )
        for item in items
        for slot, lane_key in enumerate(lane_order, start=1)
    ]
    randomized_mapping_sha256 = _retain_bytes(
        artifact_root, canonical_json(randomized_mapping).encode("utf-8")
    )

    bundle = {
        "schema_version": GATE_A_RECEIPT_BUNDLE_SCHEMA_VERSION,
        "manifest_sha256": sha256_digest(manifest),
        "approval_sha256": sha256_digest(approval),
        "candidate_sourcebrief_commit": manifest["candidate_sourcebrief_commit"],
        "source_snapshot_commit": manifest["source"]["snapshot_commit"],
        "cycle": 1,
        "run_started_at": "2026-07-21T10:00:00Z",
        "run_finished_at": "2026-07-21T10:10:00Z",
        "protected_release_started_at": "2026-07-21T09:50:00Z",
        "verifier": {
            "actor_kind": "workload",
            "workload_id": "workload:gate-a-verifier-001",
            "verifier_kind": GATE_A_VERIFIER_KIND,
            "implementation_sha256": artifact("verifier-implementation-v1"),
            "scorer_implementation_sha256": manifest["evidence_commitments"][
                "scorer_implementation"
            ],
            "policy_sha256": manifest["evidence_commitments"]["runtime_policy"],
        },
        "randomized_arm_mapping_sha256": randomized_mapping_sha256,
        "randomized_arm_mapping": randomized_mapping,
        "arm_pack_sha256": pack_hashes,
        "sandbox_receipts": sandbox_receipts,
        "pack_freeze_receipts": [
            _seal_receipt(
                {
                    "arm_key": arm_key,
                    "pack_sha256": pack_hashes[arm_key],
                    "frozen_at": "2026-07-21T09:45:00Z",
                },
                artifact_root,
            )
            for arm_key in sorted(ARM_KEYS)
        ],
        "hidden_test_index": hidden_test_index,
        "held_out_receipts": held_receipts,
        "control_receipts": control_receipts,
        "compile_receipts": compile_receipts,
        "human_review_receipt": _seal_receipt(
            {
                "reviewer_kind": "human",
                "reviewer_id": manifest["owners"]["product"]["human_id"],
                "started_at": "2026-07-21T09:10:00Z",
                "finished_at": "2026-07-21T09:30:00Z",
                "active_review_minutes": 20,
                "worklog_sha256": artifact("human-review-worklog"),
                "receipt_sha256": "pending",
            },
            artifact_root,
        ),
        "latency_cost": {
            "ai_first_use_minutes_max": 4,
            "ai_active_review_minutes_max": 2,
            "human_author_review_minutes": 20,
            "ai_cost_usd_total": 4.5,
            "approval_object_count": 1,
        },
        "failure_reasons": [
            {
                "code": code,
                "subject_type": subject_type,
                "subject_id": subject_id,
                "detail_sha256": artifact(
                    f"failure-detail/{code}/{subject_type}/{subject_id}"
                ),
            }
            for code, subject_type, subject_id in failure_subjects
        ],
        "receipt_bundle_mac": "pending",
    }
    bundle["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        bundle, verifier_key=VERIFIER_KEY
    )
    return bundle


def valid_report(manifest: dict, approval: dict, bundle: dict) -> dict:
    held_by_key = {
        (row["arm_key"], row["task_id"]): row
        for row in bundle["held_out_receipts"]
    }
    control_by_key = {
        (row["arm_key"], row["control_id"]): row
        for row in bundle["control_receipts"]
    }
    task_keys = (
        "task_id",
        "blinded_lane_id",
        "sandbox_receipt_sha256",
        "changed_paths",
        "success",
        "abstained",
        "exact_support",
        "required_resource_recall",
        "facet_coverage",
        "claim_support_precision",
        "citation_correctness",
        "receipt_sha256",
    )
    control_keys = (
        "control_id",
        "blinded_lane_id",
        "sandbox_receipt_sha256",
        "changed_paths",
        "passed",
        "receipt_sha256",
    )
    arms = []
    for arm_key in sorted(ARM_KEYS):
        arms.append(
            {
                "arm_key": arm_key,
                "pack_sha256": bundle["arm_pack_sha256"][arm_key],
                "task_results": [
                    {key: held_by_key[(arm_key, task["id"])][key] for key in task_keys}
                    for task in manifest["splits"]["held_out"]
                ],
                "control_results": [
                    {
                        key: control_by_key[(arm_key, control["id"])][key]
                        for key in control_keys
                    }
                    for control in manifest["splits"]["controls"]
                ],
            }
        )
    diagnostic_baselines = [
        {
            "baseline_key": DIRECT_TOOLS_BASELINE_KEY,
            "task_results": [
                {
                    key: held_by_key[(DIRECT_TOOLS_BASELINE_KEY, task["id"])][key]
                    for key in task_keys
                }
                for task in manifest["splits"]["held_out"]
            ],
            "control_results": [
                {
                    key: control_by_key[
                        (DIRECT_TOOLS_BASELINE_KEY, control["id"])
                    ][key]
                    for key in control_keys
                }
                for control in manifest["splits"]["controls"]
            ],
        }
    ]
    latency = bundle["latency_cost"]
    report = {
        "schema_version": GATE_A_REPORT_SCHEMA_VERSION,
        "manifest_sha256": sha256_digest(manifest),
        "approval_sha256": sha256_digest(approval),
        "candidate_sourcebrief_commit": bundle["candidate_sourcebrief_commit"],
        "cycle": bundle["cycle"],
        "run_started_at": bundle["run_started_at"],
        "run_finished_at": bundle["run_finished_at"],
        "protected_release_started_at": bundle["protected_release_started_at"],
        "sandbox_receipts": deepcopy(bundle["sandbox_receipts"]),
        "runtime": deepcopy(manifest["runtime"]),
        "corpus_state": "full",
        "arms": arms,
        "diagnostic_baselines": diagnostic_baselines,
        "ai_compile_receipts": deepcopy(bundle["compile_receipts"]),
        "human_review_receipt": deepcopy(bundle["human_review_receipt"]),
        **deepcopy(latency),
        "raw_receipts_sha256": sha256_digest(bundle),
        "verdict": "PASS" if not bundle["failure_reasons"] else "FAIL",
    }
    report["receipt_manifest"] = {
        "schema_version": GATE_A_RECEIPT_MANIFEST_SCHEMA_VERSION,
        "candidate_sourcebrief_commit": report["candidate_sourcebrief_commit"],
        "source_snapshot_commit": manifest["source"]["snapshot_commit"],
        "provider_id": manifest["runtime"]["ai_provider_id"],
        "model_id": manifest["runtime"]["ai_model_id"],
        "prompt_version": manifest["runtime"]["prompt_version"],
        "compiler_version": manifest["runtime"]["compiler_version"],
        "evaluator_id": manifest["evaluator_policy"]["evaluator_id"],
        "evaluator_version": manifest["evaluator_policy"]["evaluator_version"],
        "randomized_arm_mapping_sha256": bundle["randomized_arm_mapping_sha256"],
        "arm_pack_sha256": deepcopy(bundle["arm_pack_sha256"]),
        "indexes": [
            {
                "kind": section,
                "sha256": sha256_digest(bundle[section]),
                "record_count": len(bundle[section]) if isinstance(bundle[section], list) else 1,
            }
            for section in (
                "sandbox_receipts",
                "pack_freeze_receipts",
                "hidden_test_index",
                "held_out_receipts",
                "control_receipts",
                "compile_receipts",
                "human_review_receipt",
                "latency_cost",
                "failure_reasons",
            )
        ],
        "raw_bundle_sha256": report["raw_receipts_sha256"],
    }
    return report


def _nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {key for child in value.values() for key in _nested_keys(child)}
    if isinstance(value, list):
        return {key for child in value for key in _nested_keys(child)}
    return set()


def test_gate_a_manifest_and_detached_approval_are_hash_bound_but_not_local_authority() -> None:
    manifest = valid_manifest()
    approval = valid_approval(manifest)

    summary = validate_gate_a_manifest(manifest)
    approved = validate_gate_a_approval(manifest, approval, approval_key=APPROVAL_KEY)
    projection = unsigned_gate_a_compiler_projection(manifest)

    assert summary == {
        "schema_version": GATE_A_MANIFEST_SCHEMA_VERSION,
        "manifest_sha256": sha256_digest(manifest),
        "development_task_count": 4,
        "held_out_task_count": 12,
        "control_count": 6,
        "arm_count": 4,
    }
    assert approved["authorization"] == "integrity_checked_external_authority_required"
    assert approved["d0_ready"] is False
    assert approved["promotion_authorized"] is False
    assert approved["identity_claims_verified"] is False
    assert manifest["evidence_commitments"]["scorer_implementation"] == (
        gate_a_scorer_implementation_sha256()
    )
    scorer_drift = deepcopy(manifest)
    scorer_drift["evidence_commitments"]["scorer_implementation"] = _fixture_digest(
        "other-scorer"
    )
    with pytest.raises(EvalManifestError, match="current scorer source"):
        validate_gate_a_manifest(scorer_drift)
    assert set(projection) == {
        "schema_version",
        "source",
        "runtime",
        "development_tasks",
    }
    assert [task["id"] for task in projection["development_tasks"]] == [
        f"dev-{index:02d}" for index in range(1, 5)
    ]
    assert "held_out" not in json.dumps(projection)
    assert "control-" not in json.dumps(projection)
    assert "evidence_commitments" not in projection


def test_gate_a_manifest_fails_closed_on_split_control_timeline_and_owner_drift() -> None:
    manifest = valid_manifest()

    bad_count = deepcopy(manifest)
    bad_count["splits"]["held_out"].pop()
    with pytest.raises(EvalManifestError, match="held_out"):
        validate_gate_a_manifest(bad_count)

    numeric_governance = deepcopy(manifest)
    numeric_governance["governance"]["human_independence"] = 1
    with pytest.raises(EvalManifestError, match="boolean"):
        validate_gate_a_manifest(numeric_governance)

    numeric_promotion_flag = deepcopy(manifest)
    numeric_promotion_flag["diagnostic_baselines"][0]["promotion_arm"] = 0
    with pytest.raises(EvalManifestError, match="boolean"):
        validate_gate_a_manifest(numeric_promotion_flag)

    boolean_threshold = deepcopy(manifest)
    boolean_threshold["thresholds"]["approval_objects_max"] = True
    with pytest.raises(EvalManifestError, match="integer"):
        validate_gate_a_manifest(boolean_threshold)

    duplicate = deepcopy(manifest)
    duplicate["splits"]["held_out"][0] = deepcopy(duplicate["splits"]["development"][0])
    with pytest.raises(EvalManifestError, match="duplicate task id|content fingerprint"):
        validate_gate_a_manifest(duplicate)

    missing_control = deepcopy(manifest)
    missing_control["splits"]["controls"][0]["control_type"] = "wrong_resource"
    with pytest.raises(EvalManifestError, match="control types"):
        validate_gate_a_manifest(missing_control)

    late_d0 = deepcopy(manifest)
    late_d0["timeline"]["d0"] = "2026-08-10T09:00:00Z"
    with pytest.raises(EvalManifestError, match="10 working days"):
        validate_gate_a_manifest(late_d0)

    generic_owner = deepcopy(manifest)
    generic_owner["owners"]["product"] = {
        "actor_kind": "human",
        "human_id": "human:product-team",
        "name": "Product Team",
        "contact": "team",
    }
    with pytest.raises(EvalManifestError, match="named owner|contact"):
        validate_gate_a_manifest(generic_owner)

    plural_owner = deepcopy(manifest)
    plural_owner["owners"]["eval_qa"] = {
        "actor_kind": "human",
        "human_id": "human:eval-qa-agents",
        "name": "Eval QA Agents",
        "contact": "@eval-qa-agents",
    }
    with pytest.raises(EvalManifestError, match="named human|agent"):
        validate_gate_a_manifest(plural_owner)

    path_task_id = deepcopy(manifest)
    path_task_id["splits"]["held_out"][0]["id"] = "src/secret.py"
    with pytest.raises(EvalManifestError, match="opaque non-path"):
        validate_gate_a_manifest(path_task_id)

    overlapping_owner = deepcopy(manifest)
    overlapping_owner["owners"]["provider_compiler"]["contact"] = overlapping_owner["owners"]["eval_qa"]["contact"]
    with pytest.raises(EvalManifestError, match="role overlap|provider_compiler"):
        validate_gate_a_manifest(overlapping_owner)

    smuggled_source = deepcopy(manifest)
    smuggled_source["source"]["compiler_notes"] = {"held_out_prompt": "secret"}
    with pytest.raises(EvalManifestError, match="unknown fields|compiler_notes"):
        validate_gate_a_manifest(smuggled_source)

    smuggled_task = deepcopy(manifest)
    task = smuggled_task["splits"]["development"][0]
    task["hidden_payload"] = {"held_out_prompt": "secret"}
    task["content_sha256"] = sha256_digest({key: value for key, value in task.items() if key != "content_sha256"})
    with pytest.raises(EvalManifestError, match="unknown fields|hidden_payload"):
        validate_gate_a_manifest(smuggled_task)

    arm_contract_bypass = deepcopy(manifest)
    for arm in arm_contract_bypass["arms"]:
        arm["compiler_inputs"] = "source-development-heldout-controls"
    with pytest.raises(EvalManifestError, match="compiler_inputs"):
        validate_gate_a_manifest(arm_contract_bypass)

    wrong_task_class = deepcopy(manifest)
    for split in wrong_task_class["splits"].values():
        for task in split:
            task["task_class"] = "documentation-copyedit"
            task["content_sha256"] = sha256_digest({key: value for key, value in task.items() if key != "content_sha256"})
    with pytest.raises(EvalManifestError, match="task_class"):
        validate_gate_a_manifest(wrong_task_class)

    incomplete_identity_policy = deepcopy(manifest)
    incomplete_identity_policy["evaluator_policy"]["forbidden_identity_fields"] = ["arm"]
    with pytest.raises(EvalManifestError, match="forbidden_identity_fields"):
        validate_gate_a_manifest(incomplete_identity_policy)


def test_gate_a_manifest_rejects_shared_human_aliases_and_workload_owners() -> None:
    manifest = valid_manifest()

    shared_human = deepcopy(manifest)
    shared_human["owners"]["security"]["human_id"] = shared_human["owners"][
        "eval_qa"
    ]["human_id"]
    with pytest.raises(EvalManifestError, match="overlap|alias|human_id"):
        validate_gate_a_manifest(shared_human)

    aliased_human = deepcopy(manifest)
    aliased_human["owners"]["security"]["name"] = "Eval-QA Owner"
    with pytest.raises(EvalManifestError, match="overlap|alias|name"):
        validate_gate_a_manifest(aliased_human)

    workload_owner = deepcopy(manifest)
    workload_owner["owners"]["eval_qa"] = {
        "actor_kind": "workload",
        "human_id": "human:eval-qa-agent",
        "name": "Eval QA Agent",
        "contact": "@eval-qa-agent",
    }
    with pytest.raises(EvalManifestError, match="human|workload|agent"):
        validate_gate_a_manifest(workload_owner)

    workload_contact = deepcopy(manifest)
    workload_contact["owners"]["eval_qa"]["contact"] = "@eval-qa-agent"
    with pytest.raises(EvalManifestError, match="human|workload|agent"):
        validate_gate_a_manifest(workload_contact)


def test_single_founder_governance_is_strict_internal_signal_only_and_not_interchangeable(
    tmp_path: Path,
) -> None:
    internal = valid_internal_governance()
    summary = validate_gate_a_internal_governance(internal)

    assert summary["authorization"] == "internal_signal_only"
    assert summary["d0_ready"] is False
    assert summary["promotion_authorized"] is False

    two_humans = deepcopy(internal)
    two_humans["accountable_humans"].append(
        {
            "actor_kind": "human",
            "human_id": "human:founder-002",
            "name": "Second Founder",
            "contact": "@founder-two",
        }
    )
    with pytest.raises(EvalManifestError, match="exactly one"):
        validate_gate_a_internal_governance(two_humans)

    human_role = deepcopy(internal)
    human_role["role_bindings"]["security"] = deepcopy(internal["accountable_humans"][0])
    with pytest.raises(EvalManifestError, match="workload"):
        validate_gate_a_internal_governance(human_role)

    duplicate_workload = deepcopy(internal)
    duplicate_workload["role_bindings"]["security"]["workload_id"] = duplicate_workload[
        "role_bindings"
    ]["eval_qa"]["workload_id"]
    with pytest.raises(EvalManifestError, match="workload_ids must be unique"):
        validate_gate_a_internal_governance(duplicate_workload)

    artifact_root = tmp_path / "cas"
    manifest = valid_manifest(artifact_root)
    approval = valid_approval(manifest)
    bundle = valid_receipt_bundle(manifest, approval, artifact_root=artifact_root)
    report = valid_report(manifest, approval, bundle)
    with pytest.raises(EvalManifestError, match="manifest"):
        validate_gate_a_manifest(internal)
    with pytest.raises(EvalManifestError, match="approval"):
        validate_gate_a_approval(manifest, internal, approval_key=APPROVAL_KEY)
    with pytest.raises(EvalManifestError, match="report"):
        validate_gate_a_report(
            internal,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            receipt_bundle=bundle,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )
    with pytest.raises(EvalManifestError, match="manifest"):
        validate_gate_a_report(
            report,
            manifest=internal,
            approval=approval,
            approval_key=APPROVAL_KEY,
            receipt_bundle=bundle,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )


def test_gate_a_approval_rejects_stale_digest_revision_and_owner_identity() -> None:
    manifest = valid_manifest()
    approval = valid_approval(manifest)

    stale = deepcopy(approval)
    stale["manifest_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(EvalManifestError, match="manifest_sha256"):
        validate_gate_a_approval(manifest, stale, approval_key=APPROVAL_KEY)

    wrong_revision = deepcopy(approval)
    wrong_revision["manifest_revision"] = 2
    with pytest.raises(EvalManifestError, match="revision"):
        validate_gate_a_approval(manifest, wrong_revision, approval_key=APPROVAL_KEY)

    boolean_revision = deepcopy(approval)
    boolean_revision["manifest_revision"] = True
    with pytest.raises(EvalManifestError, match="integer"):
        validate_gate_a_approval(manifest, boolean_revision, approval_key=APPROVAL_KEY)

    wrong_owner = deepcopy(approval)
    wrong_owner["approval_event"]["actor_contact"] = "@someone-else"
    with pytest.raises(EvalManifestError, match="actor_contact|Eval/QA"):
        validate_gate_a_approval(manifest, wrong_owner, approval_key=APPROVAL_KEY)

    missing_signer = deepcopy(approval)
    missing_signer["approval_event"]["signer_human_ids"].pop()
    missing_signer["approval_event"]["signer_contacts"].pop()
    missing_signer["approval_event"]["payload_sha256"] = sha256_digest(
        gate_a_approval_payload(missing_signer)
    )
    missing_signer["approval_mac"] = sign_gate_a_approval(
        missing_signer, approval_key=APPROVAL_KEY
    )
    with pytest.raises(EvalManifestError, match="signers.*Product.*Security"):
        validate_gate_a_approval(manifest, missing_signer, approval_key=APPROVAL_KEY)

    forged_mac = deepcopy(approval)
    forged_mac["approval_mac"] = "hmac-sha256:" + "0" * 64
    with pytest.raises(EvalManifestError, match="MAC"):
        validate_gate_a_approval(manifest, forged_mac, approval_key=APPROVAL_KEY)


def test_gate_a_approval_binds_every_commitment_projection_time_and_known_identity() -> None:
    manifest = valid_manifest()
    approval = valid_approval(manifest)

    for commitment in manifest["evidence_commitments"]:
        mutated = deepcopy(approval)
        mutated["evidence_commitments"][commitment] = "sha256:" + "f" * 64
        mutated["approval_event"]["payload_sha256"] = sha256_digest(
            gate_a_approval_payload(mutated)
        )
        mutated["approval_mac"] = sign_gate_a_approval(mutated, approval_key=APPROVAL_KEY)
        with pytest.raises(EvalManifestError, match="evidence_commitments"):
            validate_gate_a_approval(manifest, mutated, approval_key=APPROVAL_KEY)

    wrong_projection = deepcopy(approval)
    wrong_projection["compiler_projection_sha256"] = "sha256:" + "f" * 64
    wrong_projection["approval_event"]["payload_sha256"] = sha256_digest(
        gate_a_approval_payload(wrong_projection)
    )
    wrong_projection["approval_mac"] = sign_gate_a_approval(
        wrong_projection, approval_key=APPROVAL_KEY
    )
    with pytest.raises(EvalManifestError, match="compiler_projection"):
        validate_gate_a_approval(manifest, wrong_projection, approval_key=APPROVAL_KEY)

    for field, value, error in (
        ("issued_at", "2026-07-19T09:00:00Z", "issued_at|D0"),
        ("expires_at", manifest["timeline"]["d0"], "expires_at|after D0"),
        ("issuer", "unknown-approval-issuer", "issuer is unknown"),
        ("key_id", "unknown-key", "key_id is unknown"),
    ):
        invalid = deepcopy(approval)
        invalid["approval_event"][field] = value
        invalid["approval_event"]["payload_sha256"] = sha256_digest(
            gate_a_approval_payload(invalid)
        )
        invalid["approval_mac"] = sign_gate_a_approval(invalid, approval_key=APPROVAL_KEY)
        with pytest.raises(EvalManifestError, match=error):
            validate_gate_a_approval(manifest, invalid, approval_key=APPROVAL_KEY)

    second_sequence = deepcopy(approval)
    second_sequence["approval_event"]["sequence"] = 2
    second_sequence["approval_event"]["payload_sha256"] = sha256_digest(
        gate_a_approval_payload(second_sequence)
    )
    second_sequence["approval_mac"] = sign_gate_a_approval(
        second_sequence, approval_key=APPROVAL_KEY
    )
    with pytest.raises(EvalManifestError, match="sequence"):
        validate_gate_a_approval(manifest, second_sequence, approval_key=APPROVAL_KEY)


def test_recursive_pairwise_sanitizer_preserves_evidence_and_removes_all_identity_metadata() -> None:
    raw = {
        "context": "Evidence excerpt",
        "profile": "hybrid",
        "retrieval_metadata": {
            "provider": "static",
            "model": "reranker-v1",
            "nested": {"candidate": "ai_compiled", "workspace_id": "ws"},
        },
        "answer": {
            "text": "Grounded answer [1]",
            "outcome": "supported",
            "confidence": "high",
            "citations_used": [
                {
                    "label": "[1]",
                    "path": "src/example.py",
                    "line_start": 1,
                    "line_end": 3,
                    "resource_id": "secret-resource",
                    "provider": "static",
                }
            ],
            "profile": "graph",
        },
        "citations": [
            {
                "label": "[1]",
                "path": "src/example.py",
                "heading": "example",
                "content": "Evidence excerpt",
                "line_start": 1,
                "line_end": 3,
                "content_hash": "sha256:" + "3" * 64,
                "resource_id": "secret-resource",
                "snapshot_section_id": "secret-section",
            }
        ],
        "code_symbols": [
            {
                "name": "example",
                "kind": "function",
                "path": "src/example.py",
                "line_start": 1,
                "line_end": 3,
                "signature": "def example() -> str",
                "content_hash": "sha256:" + "4" * 64,
                "project_id": "secret-project",
            }
        ],
        "warnings": ["candidate profile degraded"],
    }

    sanitized = sanitize_pairwise_context(raw)

    assert raw["retrieval_metadata"]["provider"] == "static"
    assert sanitized["context"] == "Evidence excerpt"
    assert sanitized["answer"]["text"] == "Grounded answer [1]"
    assert sanitized["citations"][0]["path"] == "src/example.py"
    assert sanitized["code_symbols"][0]["name"] == "example"
    assert _nested_keys(sanitized).isdisjoint(
        {
            "profile",
            "retrieval_metadata",
            "provider",
            "model",
            "candidate",
            "workspace_id",
            "project_id",
            "resource_id",
            "snapshot_section_id",
            "warnings",
        }
    )

    nested_answer = {"answer": {"text": {"profile": "ai_compiled"}}}
    with pytest.raises(EvalManifestError, match="answer.text|scalar|string"):
        sanitize_pairwise_context(nested_answer)

    nested_citation = {"citations": [{"content": {"provider": "candidate"}}]}
    with pytest.raises(EvalManifestError, match="citation.content|scalar|string"):
        sanitize_pairwise_context(nested_citation)

    scalar_identity = {
        "answer": {
            "text": "supported answer",
            "outcome": "supported",
            "confidence": "ai_compiled provider=openai",
        }
    }
    with pytest.raises(EvalManifestError, match="identity metadata|confidence"):
        sanitize_pairwise_context(scalar_identity)
    for leaked_text in (
        '{"provider":"openai"}',
        "deployment_id=prod-compiler",
        "resource_ids=secret-resource",
        r'{\"deployment_id\":\"prod\",\"resource_ids\":[\"r1\"]}',
        r'{"\u0064eployment_id":"prod"}',
    ):
        with pytest.raises(EvalManifestError, match="identity metadata"):
            sanitize_pairwise_context(
                {"answer": {"text": leaked_text, "outcome": "supported", "confidence": "high"}}
            )
    serialized = json.dumps(sanitized)
    assert "secret-resource" not in serialized
    assert "candidate profile degraded" not in serialized


def test_gate_a_path_policy_uses_exact_glob_semantics() -> None:
    assert _matches_path_policy("src/example.py", ["src/*.py"])
    assert not _matches_path_policy("src/not_python.txt", ["src/*.py"])
    assert not _matches_path_policy("src/pkg/example.py", ["src/*.py"])
    assert not _matches_path_policy("src/pkg/example.py", ["*.py"])
    assert _matches_path_policy("src/pkg/example.py", ["**/*.py"])
    assert _matches_path_policy(
        ".github/workflows/release.yml",
        [".github/workflows"],
        include_descendants=True,
    )


def test_gate_a_json_loader_rejects_duplicate_keys_and_non_finite_numbers(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"candidate_tuning_requested": false, "candidate_tuning_requested": true}', encoding="utf-8")
    with pytest.raises(EvalManifestError, match="duplicate JSON object key"):
        load_gate_a_json_file(duplicate)

    non_finite = tmp_path / "nan.json"
    non_finite.write_text('{"ai_cost_usd": NaN}', encoding="utf-8")
    with pytest.raises(EvalManifestError, match="non-finite JSON number"):
        load_gate_a_json_file(non_finite)


def test_gate_a_report_computes_pass_and_rejects_lies_missing_rows_and_budget_failures(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "cas"
    manifest = valid_manifest(artifact_root)
    approval = valid_approval(manifest)
    bundle = valid_receipt_bundle(manifest, approval, artifact_root=artifact_root)
    bundle_summary = validate_gate_a_receipt_bundle(
        bundle,
        manifest=manifest,
        approval=approval,
        approval_key=APPROVAL_KEY,
        verifier_key=VERIFIER_KEY,
        artifact_root=artifact_root,
    )
    assert bundle_summary["verifier_integrity"] is True
    report = valid_report(manifest, approval, bundle)

    def check(candidate: dict) -> dict:
        return validate_gate_a_report(
            candidate,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            receipt_bundle=bundle,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    summary = check(report)

    assert summary["computed_verdict"] == "PASS"
    assert summary["authorization"] == "evidence_integrity_only"
    assert summary["d0_ready"] is False
    assert summary["promotion_authorized"] is False
    assert summary["task_success_counts"] == {
        "ai_compiled": 9,
        "current_deterministic": 5,
        "human_authored": 10,
        "real_static": 6,
        "direct_tools_no_sourcebrief": 6,
    }
    assert summary["co_best_automated_arms"] == [
        "direct_tools_no_sourcebrief",
        "real_static",
    ]
    assert summary["lane_metrics"]["ai_compiled"] == {
        "required_resource_recall": 0.875,
        "facet_coverage": 0.875,
        "claim_support_precision": 1.0,
        "citation_correctness": 1.0,
        "abstention_rate": 0.0,
    }
    lying = deepcopy(report)
    ai_arm = next(arm for arm in lying["arms"] if arm["arm_key"] == "ai_compiled")
    ai_arm["task_results"] = ai_arm["task_results"][:8]
    with pytest.raises(EvalManifestError, match="drift"):
        check(lying)

    over_budget = deepcopy(report)
    over_budget["ai_cost_usd_total"] = 5.01
    with pytest.raises(EvalManifestError, match="drift"):
        check(over_budget)

    wrong_provenance = deepcopy(report)
    wrong_provenance["runtime"]["ai_model_id"] = "other-model"
    with pytest.raises(EvalManifestError, match="runtime"):
        check(wrong_provenance)

    partial = deepcopy(report)
    partial["corpus_state"] = "partial"
    with pytest.raises(EvalManifestError, match="partial|corpus_state"):
        check(partial)

    abstention_gaming = deepcopy(report)
    ai_arm = next(arm for arm in abstention_gaming["arms"] if arm["arm_key"] == "ai_compiled")
    for task_result in ai_arm["task_results"][:9]:
        task_result["success"] = False
        task_result["abstained"] = True
    with pytest.raises(EvalManifestError, match="drift"):
        check(abstention_gaming)

    hidden_regressions = deepcopy(report)
    ai_arm = next(arm for arm in hidden_regressions["arms"] if arm["arm_key"] == "ai_compiled")
    for index, task_result in enumerate(ai_arm["task_results"]):
        task_result["success"] = index >= 3
    with pytest.raises(EvalManifestError, match="drift"):
        check(hidden_regressions)

    non_finite = deepcopy(report)
    non_finite["ai_cost_usd_total"] = float("nan")
    with pytest.raises(EvalManifestError, match="drift|finite number"):
        check(non_finite)

    late_cycle = deepcopy(report)
    late_cycle["run_started_at"] = "2027-01-01T09:00:00Z"
    late_cycle["run_finished_at"] = "2027-01-01T10:00:00Z"
    with pytest.raises(EvalManifestError, match="authenticated receipt bundle|drift"):
        check(late_cycle)

    wrong_receipt_provenance = deepcopy(report)
    wrong_receipt_provenance["receipt_manifest"]["evaluator_version"] = "other-evaluator"
    with pytest.raises(EvalManifestError, match="receipt_manifest|drift"):
        check(wrong_receipt_provenance)

    incomplete_latency_index = deepcopy(report)
    next(
        item
        for item in incomplete_latency_index["receipt_manifest"]["indexes"]
        if item["kind"] == "latency_cost"
    )["record_count"] = 2
    with pytest.raises(EvalManifestError, match="receipt_manifest|drift"):
        check(incomplete_latency_index)

    unsupported_success = deepcopy(report)
    ai_arm = next(arm for arm in unsupported_success["arms"] if arm["arm_key"] == "ai_compiled")
    for row in ai_arm["task_results"]:
        if row["success"]:
            row["required_resource_recall"] = 0.0
            row["facet_coverage"] = 0.0
            row["claim_support_precision"] = 0.0
            row["citation_correctness"] = 0.0
    with pytest.raises(EvalManifestError, match="drift"):
        check(unsupported_success)


def test_gate_a_bundle_rejects_execution_lies_hidden_index_mutation_and_stale_mac(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "cas"
    manifest = valid_manifest(artifact_root)
    approval = valid_approval(manifest)
    bundle = valid_receipt_bundle(manifest, approval, artifact_root=artifact_root)

    execution_lie = deepcopy(bundle)
    successful = next(row for row in execution_lie["held_out_receipts"] if row["success"])
    successful["exit_code"] = 1
    _seal_receipt(successful)
    execution_lie["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        execution_lie, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="success.*zero exit"):
        validate_gate_a_receipt_bundle(
            execution_lie,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    hidden_index_mutation = deepcopy(bundle)
    hidden_index_mutation["hidden_test_index"]["entries"][0][
        "hidden_test_sha256"
    ] = _retain_artifact(artifact_root, "hidden-test/mutated")
    hidden_index_mutation["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        hidden_index_mutation, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="hidden_test_index.*commitment|commitment"):
        validate_gate_a_receipt_bundle(
            hidden_index_mutation,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    stale_mac = deepcopy(bundle)
    stale_mac["run_finished_at"] = "2026-07-21T11:00:00Z"
    with pytest.raises(EvalManifestError, match="MAC"):
        validate_gate_a_receipt_bundle(
            stale_mac,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    candidate_swap = deepcopy(bundle)
    candidate_swap["candidate_sourcebrief_commit"] = "3" * 40
    candidate_swap["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        candidate_swap, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="candidate.*approved manifest"):
        validate_gate_a_receipt_bundle(
            candidate_swap,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    scorer_swap = deepcopy(bundle)
    scorer_swap["verifier"]["scorer_implementation_sha256"] = _retain_artifact(
        artifact_root, "unapproved-scorer"
    )
    scorer_swap["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        scorer_swap, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="scorer.*approved"):
        validate_gate_a_receipt_bundle(
            scorer_swap,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    opaque_mapping = deepcopy(bundle)
    opaque_mapping["randomized_arm_mapping"][0]["blinded_lane_id"] = (
        opaque_mapping["randomized_arm_mapping"][1]["blinded_lane_id"]
    )
    opaque_mapping["randomized_arm_mapping_sha256"] = _retain_bytes(
        artifact_root,
        canonical_json(opaque_mapping["randomized_arm_mapping"]).encode("utf-8"),
    )
    opaque_mapping["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        opaque_mapping, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="duplicates.*blinded slot"):
        validate_gate_a_receipt_bundle(
            opaque_mapping,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    permuted_mapping = deepcopy(bundle)
    first_slot = permuted_mapping["randomized_arm_mapping"][0]["blinded_lane_id"]
    second_slot = permuted_mapping["randomized_arm_mapping"][1]["blinded_lane_id"]
    permuted_mapping["randomized_arm_mapping"][0]["blinded_lane_id"] = second_slot
    permuted_mapping["randomized_arm_mapping"][1]["blinded_lane_id"] = first_slot
    permuted_mapping["randomized_arm_mapping_sha256"] = _retain_bytes(
        artifact_root,
        canonical_json(permuted_mapping["randomized_arm_mapping"]).encode("utf-8"),
    )
    permuted_mapping["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        permuted_mapping, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="blinded_lane_id.*mapping"):
        validate_gate_a_receipt_bundle(
            permuted_mapping,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    contaminated_sandbox = deepcopy(bundle)
    direct_sandbox = next(
        receipt
        for receipt in contaminated_sandbox["sandbox_receipts"]
        if receipt["lane_key"] == DIRECT_TOOLS_BASELINE_KEY
    )
    direct_sandbox["external_mounts"] = ["/tmp/sourcebrief"]
    _seal_receipt(direct_sandbox, artifact_root)
    contaminated_sandbox["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        contaminated_sandbox, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="no external mounts"):
        validate_gate_a_receipt_bundle(
            contaminated_sandbox,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    for field, value, expected_error in (
        ("git_metadata_present", True, "must not contain"),
        ("external_mounts", ["/tmp/extra"], "no external mounts"),
        ("installed_capabilities", ["reference_pack", "browser"], "capabilities"),
        ("allowed_tools", ["terminal", "network"], "allowed tools"),
    ):
        non_direct_sandbox_bundle = deepcopy(bundle)
        non_direct_sandbox = next(
            receipt
            for receipt in non_direct_sandbox_bundle["sandbox_receipts"]
            if receipt["lane_key"] == "real_static"
        )
        non_direct_sandbox[field] = value
        _seal_receipt(non_direct_sandbox, artifact_root)
        non_direct_sandbox_bundle["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
            non_direct_sandbox_bundle, verifier_key=VERIFIER_KEY
        )
        with pytest.raises(EvalManifestError, match=expected_error):
            validate_gate_a_receipt_bundle(
                non_direct_sandbox_bundle,
                manifest=manifest,
                approval=approval,
                approval_key=APPROVAL_KEY,
                verifier_key=VERIFIER_KEY,
                artifact_root=artifact_root,
            )

    wrong_sandbox_cell = deepcopy(bundle)
    direct_row = next(
        row
        for row in wrong_sandbox_cell["held_out_receipts"]
        if row["arm_key"] == DIRECT_TOOLS_BASELINE_KEY
    )
    alternate_sandbox = next(
        receipt
        for receipt in wrong_sandbox_cell["sandbox_receipts"]
        if receipt["lane_key"] == "real_static"
    )
    direct_row["sandbox_receipt_sha256"] = alternate_sandbox["receipt_sha256"]
    _seal_receipt(direct_row, artifact_root)
    wrong_sandbox_cell["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        wrong_sandbox_cell, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="sandbox receipt does not match lane"):
        validate_gate_a_receipt_bundle(
            wrong_sandbox_cell,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    forbidden_direct_command = deepcopy(bundle)
    direct_row = next(
        row
        for row in forbidden_direct_command["held_out_receipts"]
        if row["arm_key"] == DIRECT_TOOLS_BASELINE_KEY
    )
    direct_row["command_sha256"] = _retain_bytes(
        artifact_root, b"sourcebrief ask --context-pack candidate-pack --query hidden-task"
    )
    _seal_receipt(direct_row, artifact_root)
    forbidden_direct_command["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        forbidden_direct_command, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="direct-tools command invoked SourceBrief"):
        validate_gate_a_receipt_bundle(
            forbidden_direct_command,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    non_direct_git_command = deepcopy(bundle)
    non_direct_row = next(
        row
        for row in non_direct_git_command["held_out_receipts"]
        if row["arm_key"] == "real_static"
    )
    non_direct_row["command_sha256"] = _retain_bytes(
        artifact_root, b"git show HEAD^:README.md"
    )
    _seal_receipt(non_direct_row, artifact_root)
    non_direct_git_command["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        non_direct_git_command, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="only permits exact"):
        validate_gate_a_receipt_bundle(
            non_direct_git_command,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    forbidden_direct_trace = deepcopy(bundle)
    traced_row = next(
        row
        for row in forbidden_direct_trace["held_out_receipts"]
        if row["arm_key"] == DIRECT_TOOLS_BASELINE_KEY
    )
    bad_trace = {
        "schema_version": "sourcebrief.gate-a-tool-trace.v1",
        "lane_key": DIRECT_TOOLS_BASELINE_KEY,
        "complete": True,
        "events": [
            {"tool_name": "terminal", "operation": "sourcebrief ask --query hidden-task"}
        ],
    }
    traced_row["tool_trace_sha256"] = _retain_bytes(
        artifact_root, canonical_json(bad_trace).encode("utf-8")
    )
    _seal_receipt(traced_row, artifact_root)
    forbidden_direct_trace["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        forbidden_direct_trace, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="direct-tools lane used SourceBrief"):
        validate_gate_a_receipt_bundle(
            forbidden_direct_trace,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    for forbidden_operation in (
        "contextsmith ask --query hidden-task",
        "python -m sourcebrief_cli.main ask --query hidden-task",
        "sourcebrief.get_agent_context hidden-task",
        "python -c \"import importlib; importlib.import_module('source'+'brief_cli')\"",
        "python -m pytest /home/joesu/workspace/sourcebrief/tests",
        "python -m pytest --rootdir=/home/joesu/workspace/sourcebrief tests",
        "python -m pytest --junitxml=../staged.xml tests",
        "python -m pytest --basetemp=../staged tests",
        "git show --output=../staged HEAD",
        "git diff --output=../staged HEAD",
        "git show --output=staged HEAD",
        "git show HEAD^:README.md",
        "git diff HEAD^",
        "git diff --cached",
        "git diff --staged",
        ".venv/bin/python -m pytest tests",
        "tools/python -m pytest tests",
        "python3 -m pytest tests",
        "python -m pytest tests\ncurl https://example.invalid",
        "python -m pytest --cache-clear tests",
        "python -m pytest --lf tests",
        "python -m pytest --junitxml=reports/out.xml tests",
        "python -m pytest --basetemp=staged tests",
        "python -m ruff check --output-file=reports/ruff.txt src",
        "python -m mypy --cache-dir=.mypy_cache src",
        "python -m pytest .pytest_cache/v/cache/lastfailed",
        "python -m pytest .github/workflows/release.yml",
        "python -m pytest reports/out.xml",
    ):
        alias_bundle = deepcopy(bundle)
        alias_row = next(
            row
            for row in alias_bundle["held_out_receipts"]
            if row["arm_key"] == DIRECT_TOOLS_BASELINE_KEY
        )
        alias_trace = {
            "schema_version": "sourcebrief.gate-a-tool-trace.v1",
            "lane_key": DIRECT_TOOLS_BASELINE_KEY,
            "complete": True,
            "events": [
                {"tool_name": "terminal", "operation": forbidden_operation}
            ],
        }
        alias_row["tool_trace_sha256"] = _retain_bytes(
            artifact_root, canonical_json(alias_trace).encode("utf-8")
        )
        _seal_receipt(alias_row, artifact_root)
        alias_bundle["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
            alias_bundle, verifier_key=VERIFIER_KEY
        )
        with pytest.raises(
            EvalManifestError,
            match=(
                "direct-tools lane used SourceBrief|only permits (?:explicit|exact)|"
                "contains shell control syntax|may not escape|must remain read-only|"
                "must remain snapshot-local|restricted to shell-free test/lint|"
                "single shell-free command line|contains a forbidden runner flag|"
                "contains an unapproved (?:pytest|ruff|mypy) flag|"
                "runner target must stay|pytest target must|touches a task-forbidden path"
            ),
        ):
            validate_gate_a_receipt_bundle(
                alias_bundle,
                manifest=manifest,
                approval=approval,
                approval_key=APPROVAL_KEY,
                verifier_key=VERIFIER_KEY,
                artifact_root=artifact_root,
            )

    for tool_name, operation in (
        ("read_file", canonical_json({"path": "/etc/passwd"})),
        (
            "search_files",
            canonical_json({"path": "../protected", "pattern": "*"}),
        ),
    ):
        escaped_bundle = deepcopy(bundle)
        escaped_row = next(
            row
            for row in escaped_bundle["held_out_receipts"]
            if row["arm_key"] == DIRECT_TOOLS_BASELINE_KEY
        )
        escaped_trace = {
            "schema_version": "sourcebrief.gate-a-tool-trace.v1",
            "lane_key": DIRECT_TOOLS_BASELINE_KEY,
            "complete": True,
            "events": [{"tool_name": tool_name, "operation": operation}],
        }
        escaped_row["tool_trace_sha256"] = _retain_bytes(
            artifact_root, canonical_json(escaped_trace).encode("utf-8")
        )
        _seal_receipt(escaped_row, artifact_root)
        escaped_bundle["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
            escaped_bundle, verifier_key=VERIFIER_KEY
        )
        with pytest.raises(EvalManifestError, match="pinned source archive"):
            validate_gate_a_receipt_bundle(
                escaped_bundle,
                manifest=manifest,
                approval=approval,
                approval_key=APPROVAL_KEY,
                verifier_key=VERIFIER_KEY,
                artifact_root=artifact_root,
            )

    for tool_name, path, expected_error in (
        ("read_file", ".github/workflows/release.yml", "task-forbidden"),
        ("read_file", ".pytest_cache/v/cache/lastfailed", "pinned source archive"),
        ("read_file", "reports/out.xml", "pinned source archive"),
        ("read_file", ".gitmodules", "pinned source archive"),
        ("search_files", ".", "pinned source archive"),
        ("search_files", "**", "pinned source archive"),
        ("search_files", "deploy*", "pinned source archive"),
        ("search_files", "deploy/service", "overlaps task forbidden_paths"),
        ("patch", "deploy/release.py", "task-forbidden"),
        ("write_file", "unrelated/new.py", "allowed_paths"),
    ):
        policy_bundle = deepcopy(bundle)
        policy_row = next(
            row
            for row in policy_bundle["held_out_receipts"]
            if row["arm_key"] == DIRECT_TOOLS_BASELINE_KEY
        )
        policy_trace = {
            "schema_version": "sourcebrief.gate-a-tool-trace.v1",
            "lane_key": DIRECT_TOOLS_BASELINE_KEY,
            "complete": True,
            "events": [
                {
                    "tool_name": tool_name,
                    "operation": canonical_json(
                        {"path": path, "pattern": "*"}
                        if tool_name == "search_files"
                        else {"path": path}
                    ),
                }
            ],
        }
        policy_row["tool_trace_sha256"] = _retain_bytes(
            artifact_root, canonical_json(policy_trace).encode("utf-8")
        )
        _seal_receipt(policy_row, artifact_root)
        policy_bundle["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
            policy_bundle, verifier_key=VERIFIER_KEY
        )
        with pytest.raises(EvalManifestError, match=expected_error):
            validate_gate_a_receipt_bundle(
                policy_bundle,
                manifest=manifest,
                approval=approval,
                approval_key=APPROVAL_KEY,
                verifier_key=VERIFIER_KEY,
                artifact_root=artifact_root,
            )

    changed_path_escape = deepcopy(bundle)
    changed_row = next(
        row
        for row in changed_path_escape["held_out_receipts"]
        if row["arm_key"] == DIRECT_TOOLS_BASELINE_KEY
    )
    changed_row["changed_paths"] = ["deploy/release.py"]
    _seal_receipt(changed_row, artifact_root)
    changed_path_escape["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        changed_path_escape, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="task-forbidden"):
        validate_gate_a_receipt_bundle(
            changed_path_escape,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    changed_path_mismatch = deepcopy(bundle)
    mismatched_row = next(
        row
        for row in changed_path_mismatch["held_out_receipts"]
        if row["arm_key"] == DIRECT_TOOLS_BASELINE_KEY
    )
    mismatched_row["changed_paths"] = []
    _seal_receipt(mismatched_row, artifact_root)
    changed_path_mismatch["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        changed_path_mismatch, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="exactly match patch/write"):
        validate_gate_a_receipt_bundle(
            changed_path_mismatch,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    substituted_pack = deepcopy(bundle)
    freeze = substituted_pack["pack_freeze_receipts"][0]
    other_arm = next(
        arm for arm in sorted(ARM_KEYS) if arm != freeze["arm_key"]
    )
    freeze["pack_sha256"] = substituted_pack["arm_pack_sha256"][other_arm]
    substituted_pack["pack_freeze_receipts"][0] = _seal_receipt(freeze)
    substituted_pack["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        substituted_pack, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="pack_sha256.*frozen arm pack"):
        validate_gate_a_receipt_bundle(
            substituted_pack,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    post_release_freeze = deepcopy(bundle)
    post_release_freeze["pack_freeze_receipts"][0]["frozen_at"] = (
        post_release_freeze["protected_release_started_at"]
    )
    post_release_freeze["pack_freeze_receipts"][0] = _seal_receipt(
        post_release_freeze["pack_freeze_receipts"][0]
    )
    post_release_freeze["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        post_release_freeze, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="predate protected material release"):
        validate_gate_a_receipt_bundle(
            post_release_freeze,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    missing_direct = deepcopy(bundle)
    missing_direct["held_out_receipts"] = [
        row
        for row in missing_direct["held_out_receipts"]
        if not (
            row["arm_key"] == DIRECT_TOOLS_BASELINE_KEY
            and row["task_id"] == manifest["splits"]["held_out"][0]["id"]
        )
    ]
    missing_direct["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        missing_direct, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="evaluation lane/task"):
        validate_gate_a_receipt_bundle(
            missing_direct,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )


def test_gate_a_bundle_requires_retained_untampered_cas_artifacts(tmp_path: Path) -> None:
    artifact_root = tmp_path / "cas"
    manifest = valid_manifest(artifact_root)
    approval = valid_approval(manifest)
    bundle = valid_receipt_bundle(manifest, approval, artifact_root=artifact_root)
    digest = bundle["verifier"]["implementation_sha256"]
    artifact_path = artifact_root / digest.removeprefix("sha256:")

    artifact_path.unlink()
    with pytest.raises(EvalManifestError, match="missing|regular file"):
        validate_gate_a_receipt_bundle(
            bundle,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    artifact_path.write_bytes(_artifact_bytes("verifier-implementation-v1"))

    commitment_digest = manifest["evidence_commitments"]["green_receipt"]
    commitment_path = artifact_root / commitment_digest.removeprefix("sha256:")
    commitment_path.unlink()
    with pytest.raises(EvalManifestError, match="green_receipt.*missing|missing.*green_receipt"):
        validate_gate_a_receipt_bundle(
            bundle,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )
    commitment_path.write_bytes(
        canonical_json({"fixture": "green-receipt"}).encode("utf-8")
    )

    retained_receipt = bundle["held_out_receipts"][0]
    receipt_digest = retained_receipt["receipt_sha256"]
    receipt_path = artifact_root / receipt_digest.removeprefix("sha256:")
    receipt_path.unlink()
    with pytest.raises(EvalManifestError, match="receipt_sha256.*missing|missing.*receipt_sha256"):
        validate_gate_a_receipt_bundle(
            bundle,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )
    receipt_path.write_bytes(
        canonical_json(
            {
                key: value
                for key, value in retained_receipt.items()
                if key != "receipt_sha256"
            }
        ).encode("utf-8")
    )

    artifact_path.write_bytes(b"tampered")
    with pytest.raises(EvalManifestError, match="digest|SHA-256|mismatch"):
        validate_gate_a_receipt_bundle(
            bundle,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )


def test_gate_a_authenticated_clock_and_approval_window_fail_closed(tmp_path: Path) -> None:
    artifact_root = tmp_path / "cas"
    manifest = valid_manifest(artifact_root)
    approval = valid_approval(manifest)
    bundle = valid_receipt_bundle(manifest, approval, artifact_root=artifact_root)

    signed_late = deepcopy(bundle)
    signed_late["run_started_at"] = "2026-08-01T09:00:00Z"
    signed_late["run_finished_at"] = "2026-08-01T10:00:00Z"
    signed_late["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        signed_late, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="cycle1_deadline|deadline"):
        validate_gate_a_receipt_bundle(
            signed_late,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    post_release_compile = deepcopy(bundle)
    post_release_compile["compile_receipts"][2].update(
        {
            "started_at": "2026-07-21T09:49:00Z",
            "finished_at": "2026-07-21T09:51:00Z",
            "duration_minutes": 2,
        }
    )
    _seal_receipt(post_release_compile["compile_receipts"][2])
    post_release_compile["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        post_release_compile, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="finish before protected release"):
        validate_gate_a_receipt_bundle(
            post_release_compile,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    release_boundary_compile = deepcopy(bundle)
    release_boundary_compile["compile_receipts"][2].update(
        {
            "started_at": "2026-07-21T09:38:00Z",
            "finished_at": release_boundary_compile[
                "protected_release_started_at"
            ],
            "duration_minutes": 12,
        }
    )
    _seal_receipt(release_boundary_compile["compile_receipts"][2])
    release_boundary_compile["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        release_boundary_compile, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="finish before protected release"):
        validate_gate_a_receipt_bundle(
            release_boundary_compile,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    duration_lie = deepcopy(bundle)
    duration_lie["compile_receipts"][0]["duration_minutes"] = 1
    _seal_receipt(duration_lie["compile_receipts"][0])
    duration_lie["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        duration_lie, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="does not match authenticated"):
        validate_gate_a_receipt_bundle(
            duration_lie,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    economics_lie = deepcopy(bundle)
    economics_lie["latency_cost"]["ai_first_use_minutes_max"] = 1
    economics_lie["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        economics_lie, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="derived from compile"):
        validate_gate_a_receipt_bundle(
            economics_lie,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    human_review_lie = deepcopy(bundle)
    human_review_lie["latency_cost"]["human_author_review_minutes"] = 1
    human_review_lie["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        human_review_lie, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="human-review receipts"):
        validate_gate_a_receipt_bundle(
            human_review_lie,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    expired_approval = deepcopy(approval)
    expired_approval["approval_event"]["expires_at"] = "2026-07-20T12:00:00Z"
    expired_approval["approval_event"]["payload_sha256"] = sha256_digest(
        gate_a_approval_payload(expired_approval)
    )
    expired_approval["approval_mac"] = sign_gate_a_approval(
        expired_approval, approval_key=APPROVAL_KEY
    )
    expired_bundle = valid_receipt_bundle(
        manifest, expired_approval, artifact_root=artifact_root
    )
    with pytest.raises(EvalManifestError, match="approval.*expires_at|approval window"):
        validate_gate_a_receipt_bundle(
            expired_bundle,
            manifest=manifest,
            approval=expired_approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )


def test_gate_a_report_rejects_bool_scalar_bypasses_and_accepts_authenticated_fail(
    tmp_path: Path,
) -> None:
    artifact_root = tmp_path / "cas"
    manifest = valid_manifest(artifact_root)
    approval = valid_approval(manifest)
    bundle = valid_receipt_bundle(manifest, approval, artifact_root=artifact_root)
    report = valid_report(manifest, approval, bundle)

    def check(candidate: dict, receipt_bundle: dict = bundle) -> dict:
        return validate_gate_a_report(
            candidate,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            receipt_bundle=receipt_bundle,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    bool_attempt = deepcopy(report)
    bool_attempt["ai_compile_receipts"][0]["attempt"] = True
    with pytest.raises(EvalManifestError, match="drift"):
        check(bool_attempt)

    bool_attempt_bundle = deepcopy(bundle)
    bool_attempt_bundle["compile_receipts"][0]["attempt"] = True
    bool_attempt_bundle["compile_receipts"][0] = _seal_receipt(
        bool_attempt_bundle["compile_receipts"][0]
    )
    bool_attempt_bundle["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        bool_attempt_bundle, verifier_key=VERIFIER_KEY
    )
    with pytest.raises(EvalManifestError, match="attempt.*integer"):
        validate_gate_a_receipt_bundle(
            bool_attempt_bundle,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
            verifier_key=VERIFIER_KEY,
            artifact_root=artifact_root,
        )

    bool_approval_count = deepcopy(report)
    bool_approval_count["approval_object_count"] = True
    with pytest.raises(EvalManifestError, match="drift"):
        check(bool_approval_count)

    failed_bundle = valid_receipt_bundle(
        manifest, approval, artifact_root=artifact_root, passing=False
    )
    failed_report = valid_report(manifest, approval, failed_bundle)
    assert check(failed_report, failed_bundle)["computed_verdict"] == "FAIL"

    unsupported_zero_exit_bundle = deepcopy(failed_bundle)
    unsupported_row = next(
        row
        for row in unsupported_zero_exit_bundle["held_out_receipts"]
        if row["arm_key"] == "ai_compiled" and not row["success"]
    )
    unsupported_row["exit_code"] = 0
    _seal_receipt(unsupported_row, artifact_root)
    unsupported_zero_exit_bundle["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        unsupported_zero_exit_bundle, verifier_key=VERIFIER_KEY
    )
    unsupported_zero_exit_report = valid_report(
        manifest, approval, unsupported_zero_exit_bundle
    )
    assert (
        check(unsupported_zero_exit_report, unsupported_zero_exit_bundle)[
            "computed_verdict"
        ]
        == "FAIL"
    )

    mismatched_reason_bundle = deepcopy(failed_bundle)
    mismatched_reason_bundle["failure_reasons"][0]["code"] = "cost_budget"
    mismatched_reason_bundle["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        mismatched_reason_bundle, verifier_key=VERIFIER_KEY
    )
    mismatched_reason_report = valid_report(
        manifest, approval, mismatched_reason_bundle
    )
    with pytest.raises(EvalManifestError, match="failure reasons.*computed.*subjects"):
        check(mismatched_reason_report, mismatched_reason_bundle)

    strong_direct_bundle = valid_receipt_bundle(
        manifest,
        approval,
        artifact_root=artifact_root,
        direct_tools_success_count=8,
    )
    strong_direct_report = valid_report(manifest, approval, strong_direct_bundle)
    strong_direct_summary = check(strong_direct_report, strong_direct_bundle)
    assert strong_direct_summary["computed_verdict"] == "FAIL"
    assert strong_direct_summary["best_automated_arm"] == DIRECT_TOOLS_BASELINE_KEY
    assert "win margin versus automated baseline" in strong_direct_summary["failures"]

    co_best_regression_bundle = deepcopy(bundle)
    direct_rows = [
        row
        for row in co_best_regression_bundle["held_out_receipts"]
        if row["arm_key"] == DIRECT_TOOLS_BASELINE_KEY
    ]
    for row, success in (
        (direct_rows[0], False),
        (direct_rows[1], False),
        (direct_rows[9], True),
        (direct_rows[10], True),
    ):
        row["success"] = success
        row["exit_code"] = 0 if success else 1
        if success:
            row["exact_support"] = True
            for metric in (
                "required_resource_recall",
                "facet_coverage",
                "claim_support_precision",
                "citation_correctness",
            ):
                row[metric] = 1.0
        _seal_receipt(row, artifact_root)
    co_best_regression_bundle["failure_reasons"] = [
        {
            "code": "baseline_regression",
            "subject_type": "task",
            "subject_id": row["task_id"],
            "detail_sha256": _retain_artifact(
                artifact_root, f"failure-detail/co-best-regression/{row['task_id']}"
            ),
        }
        for row in (direct_rows[9], direct_rows[10])
    ]
    co_best_regression_bundle["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        co_best_regression_bundle, verifier_key=VERIFIER_KEY
    )
    co_best_regression_report = valid_report(
        manifest, approval, co_best_regression_bundle
    )
    co_best_regression_summary = check(
        co_best_regression_report, co_best_regression_bundle
    )
    assert co_best_regression_summary["computed_verdict"] == "FAIL"
    assert co_best_regression_summary["co_best_automated_arms"] == [
        "direct_tools_no_sourcebrief",
        "real_static",
    ]
    assert co_best_regression_summary["baseline_regressions"] == 2

    unrelated_subject_bundle = deepcopy(co_best_regression_bundle)
    unrelated_subject_bundle["failure_reasons"][1]["subject_id"] = direct_rows[11][
        "task_id"
    ]
    unrelated_subject_bundle["receipt_bundle_mac"] = sign_gate_a_receipt_bundle(
        unrelated_subject_bundle, verifier_key=VERIFIER_KEY
    )
    unrelated_subject_report = valid_report(
        manifest, approval, unrelated_subject_bundle
    )
    with pytest.raises(EvalManifestError, match="affected subjects"):
        check(unrelated_subject_report, unrelated_subject_bundle)


def test_gate_a_report_cli_recomputes_retained_artifacts_end_to_end(tmp_path: Path) -> None:
    artifact_root = tmp_path / "cas"
    manifest = valid_manifest(artifact_root)
    approval = valid_approval(manifest)
    bundle = valid_receipt_bundle(manifest, approval, artifact_root=artifact_root)
    report = valid_report(manifest, approval, bundle)
    paths = {
        "manifest": tmp_path / "manifest.json",
        "approval": tmp_path / "approval.json",
        "bundle": tmp_path / "bundle.json",
        "report": tmp_path / "report.json",
        "approval_key": tmp_path / "approval.key",
        "verifier_key": tmp_path / "verifier.key",
    }
    for key, value in (
        ("manifest", manifest),
        ("approval", approval),
        ("bundle", bundle),
        ("report", report),
    ):
        paths[key].write_text(canonical_json(value), encoding="utf-8")
    paths["approval_key"].write_bytes(APPROVAL_KEY)
    paths["verifier_key"].write_bytes(VERIFIER_KEY)

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate-gate-a-report",
            str(paths["report"]),
            "--manifest",
            str(paths["manifest"]),
            "--approval",
            str(paths["approval"]),
            "--approval-key-file",
            str(paths["approval_key"]),
            "--receipt-bundle",
            str(paths["bundle"]),
            "--verifier-key-file",
            str(paths["verifier_key"]),
            "--artifact-root",
            str(artifact_root),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    summary = json.loads(completed.stdout)
    assert summary["computed_verdict"] == "PASS"
    assert summary["authorization"] == "evidence_integrity_only"
    assert summary["promotion_authorized"] is False
    assert summary["controls_passed"] == 6


def test_gate_a_cli_validates_internal_governance_as_non_promotional(tmp_path: Path) -> None:
    governance_path = tmp_path / "internal-governance.json"
    governance_path.write_text(json.dumps(valid_internal_governance()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate-gate-a-internal-governance",
            str(governance_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    summary = json.loads(completed.stdout)
    assert summary["authorization"] == "internal_signal_only"
    assert summary["d0_ready"] is False
    assert summary["promotion_authorized"] is False


def test_gate_a_cli_checks_integrity_but_rejects_local_d0_authority(tmp_path: Path) -> None:
    manifest = valid_manifest()
    approval = valid_approval(manifest)
    manifest_path = tmp_path / "manifest.json"
    approval_path = tmp_path / "approval.json"
    approval_key_path = tmp_path / "approval.key"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    approval_path.write_text(json.dumps(approval), encoding="utf-8")
    approval_key_path.write_bytes(APPROVAL_KEY)

    validate = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate-gate-a",
            str(manifest_path),
            "--approval",
            str(approval_path),
            "--require-d0",
            "--approval-key-file",
            str(approval_key_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert validate.returncode == 2
    assert "external review service required" in validate.stderr

    approval["manifest_sha256"] = "sha256:" + "0" * 64
    approval_path.write_text(json.dumps(approval), encoding="utf-8")
    rejected = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "validate-gate-a",
            str(manifest_path),
            "--approval",
            str(approval_path),
            "--require-d0",
            "--approval-key-file",
            str(approval_key_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert rejected.returncode == 2
    assert "manifest_sha256" in rejected.stderr
