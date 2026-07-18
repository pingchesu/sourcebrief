from __future__ import annotations

import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from sourcebrief_shared.eval_manifest import EvalManifestError, sha256_digest
from sourcebrief_shared.gate_a_eval import (
    GATE_A_APPROVAL_SCHEMA_VERSION,
    GATE_A_MANIFEST_SCHEMA_VERSION,
    GATE_A_REPORT_SCHEMA_VERSION,
    compiler_input,
    load_gate_a_json_file,
    sanitize_pairwise_context,
    sign_gate_a_approval,
    validate_gate_a_approval,
    validate_gate_a_manifest,
    validate_gate_a_report,
)

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "eval_manifest.py"
APPROVAL_KEY = b"gate-a-test-approval-key"
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


def _task(task_id: str, *, prompt: str | None = None) -> dict:
    task = {
        "id": task_id,
        "task_class": "repository-maintenance",
        "prompt": prompt or f"Implement the bounded maintenance change for {task_id}.",
        "allowed_paths": ["packages/shared/sourcebrief_shared/example.py"],
        "forbidden_paths": [".github/workflows", "deploy"],
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


def valid_manifest() -> dict:
    owners = {
        role: {"name": f"{role.replace('_', ' ').title()} Owner", "contact": f"@{role}-owner"}
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
    return {
        "schema_version": GATE_A_MANIFEST_SCHEMA_VERSION,
        "name": "SourceBrief Gate A repository-maintenance evaluation",
        "description": "Frozen one-repository Gate A contract.",
        "revision": 1,
        "source": {
            "kind": "git",
            "repository_url": "https://github.com/example/gate-a-fixture",
            "snapshot_commit": "a" * 40,
            "snapshot_tree_sha256": "sha256:" + "b" * 64,
            "classification": "purpose-built-non-sensitive",
            "license_spdx": "MIT",
            "contains_restricted_data": False,
        },
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
        "arms": arms,
        "diagnostic_baselines": [
            {
                "key": "direct_tools_no_sourcebrief",
                "runtime": "hermes",
                "source_access": "pinned-repository",
                "promotion_arm": False,
            }
        ],
        "splits": {
            "development": [_task(f"dev-{index:02d}") for index in range(1, 5)],
            "held_out": [_task(f"held-{index:02d}") for index in range(1, 13)],
            "controls": [_control(control_type) for control_type in sorted(CONTROL_TYPES)],
        },
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
    signer_contacts = [
        manifest["owners"][role]["contact"]
        for role in ("product", "eval_qa", "runtime_pack", "security")
    ]
    approval = {
        "schema_version": GATE_A_APPROVAL_SCHEMA_VERSION,
        "manifest_sha256": sha256_digest(manifest),
        "manifest_revision": manifest["revision"],
        "approved_at": manifest["timeline"]["d0"],
        "candidate_tuning_authorized": True,
        "attestation_kind": "content-addressed-human-approval",
        "approvers": deepcopy(manifest["owners"]),
        "approval_event": {
            "event_id": "gate-a-approval-event-001",
            "issuer": "sourcebrief-review-service",
            "actor_id": "eval-qa-owner-001",
            "actor_contact": manifest["owners"]["eval_qa"]["contact"],
            "issued_at": manifest["timeline"]["d0"],
            "comment": "Approve candidate tuning for the frozen Gate A manifest.",
            "signer_contacts": signer_contacts,
            "payload_sha256": sha256_digest(
                {
                    "manifest_sha256": sha256_digest(manifest),
                    "manifest_revision": manifest["revision"],
                    "approved_at": manifest["timeline"]["d0"],
                    "candidate_tuning_authorized": True,
                    "event_id": "gate-a-approval-event-001",
                    "issuer": "sourcebrief-review-service",
                    "actor_id": "eval-qa-owner-001",
                    "actor_contact": manifest["owners"]["eval_qa"]["contact"],
                    "issued_at": manifest["timeline"]["d0"],
                    "comment": "Approve candidate tuning for the frozen Gate A manifest.",
                    "signer_contacts": signer_contacts,
                }
            ),
        },
    }
    approval["approval_signature"] = sign_gate_a_approval(approval, approval_key=APPROVAL_KEY)
    return approval


def _task_result(task_id: str, *, success: bool = True, exact_support: bool = True) -> dict:
    return {
        "task_id": task_id,
        "success": success,
        "abstained": False,
        "exact_support": exact_support,
        "required_resource_recall": 1.0 if success else 0.5,
        "facet_coverage": 1.0 if success else 0.5,
        "claim_support_precision": 1.0 if exact_support else 0.0,
        "citation_correctness": 1.0 if exact_support else 0.0,
        "receipt_sha256": "sha256:" + "d" * 64,
    }


def valid_report(manifest: dict, approval: dict) -> dict:
    held_ids = [task["id"] for task in manifest["splits"]["held_out"]]
    control_ids = [task["id"] for task in manifest["splits"]["controls"]]
    success_counts = {
        "current_deterministic": 5,
        "real_static": 6,
        "human_authored": 10,
        "ai_compiled": 9,
    }
    arms = []
    for arm_key in sorted(ARM_KEYS):
        success_count = success_counts[arm_key]
        arms.append(
            {
                "arm_key": arm_key,
                "pack_sha256": "sha256:" + ("e" if arm_key == "ai_compiled" else "f") * 64,
                "task_results": [
                    _task_result(task_id, success=index < success_count)
                    for index, task_id in enumerate(held_ids)
                ],
                "control_results": [
                    {
                        "control_id": control_id,
                        "passed": True,
                        "receipt_sha256": "sha256:" + "1" * 64,
                    }
                    for control_id in control_ids
                ],
            }
        )
    report = {
        "schema_version": GATE_A_REPORT_SCHEMA_VERSION,
        "manifest_sha256": sha256_digest(manifest),
        "approval_sha256": sha256_digest(approval),
        "candidate_sourcebrief_commit": "2" * 40,
        "cycle": 1,
        "run_started_at": "2026-07-21T09:00:00Z",
        "run_finished_at": "2026-07-21T10:00:00Z",
        "runtime": deepcopy(manifest["runtime"]),
        "corpus_state": "full",
        "arms": arms,
        "ai_compile_receipts": [
            {
                "attempt": index,
                "succeeded": True,
                "duration_minutes": 12,
                "provider_retries": 1 if index == 1 else 0,
                "receipt_sha256": "sha256:" + str(index) * 64,
            }
            for index in range(1, 4)
        ],
        "ai_first_use_minutes": 18,
        "ai_active_review_minutes": 8,
        "human_author_review_minutes": 20,
        "ai_cost_usd": 4.5,
        "approval_object_count": 1,
        "raw_receipts_sha256": "sha256:" + "9" * 64,
        "verdict": "PASS",
    }
    report["receipt_manifest"] = {
        "schema_version": "sourcebrief.gate-a-receipts.v1",
        "candidate_sourcebrief_commit": report["candidate_sourcebrief_commit"],
        "source_snapshot_commit": manifest["source"]["snapshot_commit"],
        "provider_id": manifest["runtime"]["ai_provider_id"],
        "model_id": manifest["runtime"]["ai_model_id"],
        "prompt_version": manifest["runtime"]["prompt_version"],
        "compiler_version": manifest["runtime"]["compiler_version"],
        "evaluator_id": manifest["evaluator_policy"]["evaluator_id"],
        "evaluator_version": manifest["evaluator_policy"]["evaluator_version"],
        "randomized_arm_mapping_sha256": "sha256:" + "7" * 64,
        "arm_pack_sha256": {arm["arm_key"]: arm["pack_sha256"] for arm in arms},
        "indexes": [
            {"kind": "task_results", "sha256": "sha256:" + "4" * 64, "record_count": 72},
            {"kind": "latency_cost", "sha256": "sha256:" + "5" * 64, "record_count": 7},
            {"kind": "failure_reasons", "sha256": "sha256:" + "6" * 64, "record_count": 0},
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


def test_gate_a_manifest_and_detached_approval_are_hash_bound_and_compiler_input_is_dev_only() -> None:
    manifest = valid_manifest()
    approval = valid_approval(manifest)

    summary = validate_gate_a_manifest(manifest)
    approved = validate_gate_a_approval(manifest, approval, approval_key=APPROVAL_KEY)
    compiler = compiler_input(manifest, approval=approval, approval_key=APPROVAL_KEY)

    assert summary == {
        "schema_version": GATE_A_MANIFEST_SCHEMA_VERSION,
        "manifest_sha256": sha256_digest(manifest),
        "development_task_count": 4,
        "held_out_task_count": 12,
        "control_count": 6,
        "arm_count": 4,
    }
    assert approved["d0_ready"] is True
    assert compiler["manifest_sha256"] == sha256_digest(manifest)
    assert [task["id"] for task in compiler["development_tasks"]] == [f"dev-{index:02d}" for index in range(1, 5)]
    assert "held_out" not in json.dumps(compiler)
    assert "control-" not in json.dumps(compiler)


def test_gate_a_manifest_fails_closed_on_split_control_timeline_and_owner_drift() -> None:
    manifest = valid_manifest()

    bad_count = deepcopy(manifest)
    bad_count["splits"]["held_out"].pop()
    with pytest.raises(EvalManifestError, match="held_out"):
        validate_gate_a_manifest(bad_count)

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
    generic_owner["owners"]["product"] = {"name": "Product Team", "contact": "team"}
    with pytest.raises(EvalManifestError, match="named owner|contact"):
        validate_gate_a_manifest(generic_owner)

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

    wrong_owner = deepcopy(approval)
    wrong_owner["approvers"]["security"]["contact"] = "@someone-else"
    with pytest.raises(EvalManifestError, match="approvers"):
        validate_gate_a_approval(manifest, wrong_owner, approval_key=APPROVAL_KEY)

    forged_signature = deepcopy(approval)
    forged_signature["approval_signature"] = "hmac-sha256:" + "0" * 64
    with pytest.raises(EvalManifestError, match="signature"):
        validate_gate_a_approval(manifest, forged_signature, approval_key=APPROVAL_KEY)


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
    serialized = json.dumps(sanitized)
    assert "secret-resource" not in serialized
    assert "candidate profile degraded" not in serialized


def test_gate_a_json_loader_rejects_duplicate_keys_and_non_finite_numbers(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"candidate_tuning_authorized": false, "candidate_tuning_authorized": true}', encoding="utf-8")
    with pytest.raises(EvalManifestError, match="duplicate JSON object key"):
        load_gate_a_json_file(duplicate)

    non_finite = tmp_path / "nan.json"
    non_finite.write_text('{"ai_cost_usd": NaN}', encoding="utf-8")
    with pytest.raises(EvalManifestError, match="non-finite JSON number"):
        load_gate_a_json_file(non_finite)


def test_gate_a_report_computes_pass_and_rejects_lies_missing_rows_and_budget_failures() -> None:
    manifest = valid_manifest()
    approval = valid_approval(manifest)
    report = valid_report(manifest, approval)

    summary = validate_gate_a_report(report, manifest=manifest, approval=approval, approval_key=APPROVAL_KEY)

    assert summary["computed_verdict"] == "PASS"
    assert summary["task_success_counts"] == {
        "ai_compiled": 9,
        "current_deterministic": 5,
        "human_authored": 10,
        "real_static": 6,
    }
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
    with pytest.raises(EvalManifestError, match="exactly match held-out tasks"):
        validate_gate_a_report(lying, manifest=manifest, approval=approval, approval_key=APPROVAL_KEY)

    over_budget = deepcopy(report)
    over_budget["ai_cost_usd"] = 5.01
    with pytest.raises(EvalManifestError, match="declared verdict|cost"):
        validate_gate_a_report(over_budget, manifest=manifest, approval=approval, approval_key=APPROVAL_KEY)

    wrong_provenance = deepcopy(report)
    wrong_provenance["runtime"]["ai_model_id"] = "other-model"
    with pytest.raises(EvalManifestError, match="runtime"):
        validate_gate_a_report(wrong_provenance, manifest=manifest, approval=approval, approval_key=APPROVAL_KEY)

    partial = deepcopy(report)
    partial["corpus_state"] = "partial"
    with pytest.raises(EvalManifestError, match="partial|corpus_state"):
        validate_gate_a_report(partial, manifest=manifest, approval=approval, approval_key=APPROVAL_KEY)

    abstention_gaming = deepcopy(report)
    ai_arm = next(arm for arm in abstention_gaming["arms"] if arm["arm_key"] == "ai_compiled")
    for task_result in ai_arm["task_results"][:9]:
        task_result["success"] = False
        task_result["abstained"] = True
    with pytest.raises(EvalManifestError, match="declared verdict|task-success|abstention"):
        validate_gate_a_report(abstention_gaming, manifest=manifest, approval=approval, approval_key=APPROVAL_KEY)

    hidden_regressions = deepcopy(report)
    ai_arm = next(arm for arm in hidden_regressions["arms"] if arm["arm_key"] == "ai_compiled")
    for index, task_result in enumerate(ai_arm["task_results"]):
        task_result["success"] = index >= 3
    with pytest.raises(EvalManifestError, match="declared verdict|baseline regressions"):
        validate_gate_a_report(hidden_regressions, manifest=manifest, approval=approval, approval_key=APPROVAL_KEY)

    non_finite = deepcopy(report)
    non_finite["ai_cost_usd"] = float("nan")
    with pytest.raises(EvalManifestError, match="finite|ai_cost_usd"):
        validate_gate_a_report(non_finite, manifest=manifest, approval=approval, approval_key=APPROVAL_KEY)

    late_cycle = deepcopy(report)
    late_cycle["run_started_at"] = "2027-01-01T09:00:00Z"
    late_cycle["run_finished_at"] = "2027-01-01T10:00:00Z"
    with pytest.raises(EvalManifestError, match="cycle1_deadline|deadline"):
        validate_gate_a_report(late_cycle, manifest=manifest, approval=approval, approval_key=APPROVAL_KEY)

    wrong_receipt_provenance = deepcopy(report)
    wrong_receipt_provenance["receipt_manifest"]["evaluator_version"] = "other-evaluator"
    with pytest.raises(EvalManifestError, match="receipt_manifest|evaluator"):
        validate_gate_a_report(
            wrong_receipt_provenance,
            manifest=manifest,
            approval=approval,
            approval_key=APPROVAL_KEY,
        )


def test_gate_a_cli_validates_approval_prepares_compiler_input_and_rejects_stale_approval(tmp_path: Path) -> None:
    manifest = valid_manifest()
    approval = valid_approval(manifest)
    manifest_path = tmp_path / "manifest.json"
    approval_path = tmp_path / "approval.json"
    approval_key_path = tmp_path / "approval.key"
    compiler_path = tmp_path / "compiler-input.json"
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
        check=True,
    )
    assert json.loads(validate.stdout)["d0_ready"] is True

    prepared = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "prepare-gate-a-compiler-input",
            str(manifest_path),
            "--approval",
            str(approval_path),
            "--approval-key-file",
            str(approval_key_path),
            "--output",
            str(compiler_path),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(prepared.stdout)["output"] == str(compiler_path)
    compiler = json.loads(compiler_path.read_text())
    assert len(compiler["development_tasks"]) == 4
    assert "held_out" not in compiler

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
