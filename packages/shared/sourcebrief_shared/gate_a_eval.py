from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sourcebrief_shared.eval_manifest import EvalManifestError, canonical_json, sha256_digest

GATE_A_MANIFEST_SCHEMA_VERSION = "sourcebrief.gate-a-manifest.v2"
GATE_A_APPROVAL_SCHEMA_VERSION = "sourcebrief.gate-a-approval.v1"
GATE_A_REPORT_SCHEMA_VERSION = "sourcebrief.gate-a-report.v1"

ARM_KEYS = {"current_deterministic", "real_static", "human_authored", "ai_compiled"}
NORMATIVE_ARMS = {
    "current_deterministic": {
        "retrieval_backend": "development-default",
        "pack_source": "deterministic-adapter",
        "compiler_inputs": "source-and-development-only",
    },
    "real_static": {
        "retrieval_backend": "real-static",
        "pack_source": "deterministic-adapter",
        "compiler_inputs": "source-and-development-only",
    },
    "human_authored": {
        "retrieval_backend": "real-static",
        "pack_source": "human-authored",
        "compiler_inputs": "source-and-development-only",
    },
    "ai_compiled": {
        "retrieval_backend": "real-static",
        "pack_source": "ai-compiled",
        "compiler_inputs": "source-and-development-only",
    },
}
AUTOMATED_ARM_KEYS = {"current_deterministic", "real_static"}
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
CONTAMINATION_CHECKS = {
    "source-vs-tasks",
    "development-vs-held-out",
    "pack-vs-held-out",
    "prompt-vs-held-out",
}
FORBIDDEN_IDENTITY_FIELDS = {
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
}
NORMATIVE_THRESHOLDS: dict[str, int | float | bool] = {
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
}

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_IDENTITY_FIELD_PATTERN = "|".join(sorted(FORBIDDEN_IDENTITY_FIELDS, key=len, reverse=True))
_BLINDED_IDENTITY_RE = re.compile(
    r"(?i)\b(?:ai_compiled|human_authored|current_deterministic|real_static)\b"
    rf"|[\"']?(?:{_IDENTITY_FIELD_PATTERN})[\"']?\s*[:=]"
)


def _exact_keys(value: dict[str, Any], expected: set[str], context: str) -> None:
    missing = expected - set(value)
    unknown = set(value) - expected
    if missing:
        raise EvalManifestError(f"{context} is missing required fields: {sorted(missing)}")
    if unknown:
        raise EvalManifestError(f"{context} contains unknown fields: {sorted(unknown)}")


def load_gate_a_json_file(path: str | Path) -> dict[str, Any]:
    def reject_constant(value: str) -> None:
        raise EvalManifestError(f"non-finite JSON number is forbidden: {value}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise EvalManifestError(f"duplicate JSON object key is forbidden: {key}")
            result[key] = value
        return result

    try:
        raw = json.loads(
            Path(path).read_text(encoding="utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except json.JSONDecodeError as exc:
        raise EvalManifestError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise EvalManifestError(f"Gate A JSON in {path} must be an object")
    return raw


def _object(value: Any, context: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvalManifestError(f"{context} must be an object")
    return value


def _list(value: Any, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise EvalManifestError(f"{context} must be a list")
    return value


def _string(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EvalManifestError(f"{context} must be a non-empty string")
    return value


def _boolean(value: Any, context: str) -> bool:
    if not isinstance(value, bool):
        raise EvalManifestError(f"{context} must be a boolean")
    return value


def _integer(value: Any, context: str, minimum: int | None = None) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise EvalManifestError(f"{context} must be an integer")
    if minimum is not None and value < minimum:
        raise EvalManifestError(f"{context} must be >= {minimum}")
    return value


def _number(value: Any, context: str, minimum: float = 0, maximum: float | None = None) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise EvalManifestError(f"{context} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise EvalManifestError(f"{context} must be a finite number")
    if result < minimum or (maximum is not None and result > maximum):
        raise EvalManifestError(f"{context} must be between {minimum} and {maximum}")
    return result


def _digest(value: Any, context: str) -> str:
    result = _string(value, context)
    if not _SHA256_RE.fullmatch(result):
        raise EvalManifestError(f"{context} must be a sha256 digest")
    return result


def _timestamp(value: Any, context: str) -> datetime:
    text = _string(value, context)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvalManifestError(f"{context} must be RFC3339") from exc
    if parsed.tzinfo is None:
        raise EvalManifestError(f"{context} must include a timezone")
    return parsed.astimezone(UTC)


def _working_days(start: datetime, end: datetime) -> int:
    if end < start:
        return -1
    day = start.date()
    final = end.date()
    count = 0
    while day <= final:
        if day.weekday() < 5:
            count += 1
        day += timedelta(days=1)
    return count


def _owners(value: Any, context: str) -> dict[str, Any]:
    owners = _object(value, context)
    if set(owners) != OWNER_ROLES:
        raise EvalManifestError(f"{context} must name exactly {sorted(OWNER_ROLES)}")
    for role, raw in owners.items():
        owner = _object(raw, f"{context}.{role}")
        _exact_keys(owner, {"name", "contact"}, f"{context}.{role}")
        name = _string(owner.get("name"), f"{context}.{role}.name")
        contact = _string(owner.get("contact"), f"{context}.{role}.contact")
        compact_name = re.sub(r"[^a-z]", "", name.lower())
        if compact_name in {"team", "productteam", "qateam", "securityteam", "platformteam"} or not contact.startswith("@"):
            raise EvalManifestError(f"{context}.{role} must have a named owner and @contact")
    normalized_contacts = {
        role: str(owner["contact"]).strip().lower()
        for role, owner in owners.items()
    }
    for left, right in (
        ("provider_compiler", "eval_qa"),
        ("provider_compiler", "security"),
        ("eval_qa", "security"),
    ):
        if normalized_contacts[left] == normalized_contacts[right]:
            raise EvalManifestError(f"{context} role overlap is forbidden between {left} and {right}")
    return owners


def _task(value: Any, context: str, *, control: bool = False) -> dict[str, Any]:
    task = _object(value, context)
    expected_keys = {
        "id",
        "task_class",
        "prompt",
        "allowed_paths",
        "forbidden_paths",
        "objective_assertions",
        "expected_evidence",
        "content_sha256",
    }
    if control:
        expected_keys |= {"control_type", "expected_behavior"}
    _exact_keys(task, expected_keys, context)
    _string(task.get("id"), f"{context}.id")
    if _string(task.get("task_class"), f"{context}.task_class") != "repository-maintenance":
        raise EvalManifestError(f"{context}.task_class must be 'repository-maintenance'")
    _string(task.get("prompt"), f"{context}.prompt")
    for key in ("allowed_paths", "forbidden_paths"):
        values = _list(task.get(key), f"{context}.{key}")
        if not all(isinstance(item, str) and item.strip() for item in values):
            raise EvalManifestError(f"{context}.{key} must contain non-empty strings")
    assertions = _list(task.get("objective_assertions"), f"{context}.objective_assertions")
    if not assertions:
        raise EvalManifestError(f"{context}.objective_assertions must not be empty")
    for index, raw in enumerate(assertions):
        assertion = _object(raw, f"{context}.objective_assertions[{index}]")
        _exact_keys(assertion, {"kind", "target", "expectation"}, f"{context}.objective_assertions[{index}]")
        for key in ("kind", "target", "expectation"):
            _string(assertion.get(key), f"{context}.objective_assertions[{index}].{key}")
    evidence = _object(task.get("expected_evidence"), f"{context}.expected_evidence")
    _exact_keys(evidence, {"resources", "facets", "evidence_classes"}, f"{context}.expected_evidence")
    for key in ("resources", "facets", "evidence_classes"):
        values = _list(evidence.get(key), f"{context}.expected_evidence.{key}")
        if not values or not all(isinstance(item, str) and item.strip() for item in values):
            raise EvalManifestError(f"{context}.expected_evidence.{key} must contain non-empty strings")
    if control:
        if task.get("control_type") not in CONTROL_TYPES:
            raise EvalManifestError(f"{context}.control_type is unsupported")
        if task.get("expected_behavior") != "fail_closed":
            raise EvalManifestError(f"{context}.expected_behavior must be 'fail_closed'")
    declared = _digest(task.get("content_sha256"), f"{context}.content_sha256")
    actual = sha256_digest({key: item for key, item in task.items() if key != "content_sha256"})
    if declared != actual:
        raise EvalManifestError(f"{context}.content_sha256 does not match task content")
    return task


def _timeline(value: Any) -> dict[str, Any]:
    timeline = _object(value, "manifest.timeline")
    _exact_keys(
        timeline,
        {"phase0_merged_at", "d0", "cycle1_deadline", "cycle2_deadline", "absolute_deadline", "working_day_policy"},
        "manifest.timeline",
    )
    phase0 = _timestamp(timeline.get("phase0_merged_at"), "manifest.timeline.phase0_merged_at")
    d0 = _timestamp(timeline.get("d0"), "manifest.timeline.d0")
    cycle1 = _timestamp(timeline.get("cycle1_deadline"), "manifest.timeline.cycle1_deadline")
    cycle2 = _timestamp(timeline.get("cycle2_deadline"), "manifest.timeline.cycle2_deadline")
    absolute = _timestamp(timeline.get("absolute_deadline"), "manifest.timeline.absolute_deadline")
    if timeline.get("working_day_policy") != "weekdays-only-utc":
        raise EvalManifestError("manifest.timeline.working_day_policy must be 'weekdays-only-utc'")
    if _working_days(phase0, d0) > 10:
        raise EvalManifestError("manifest.timeline.d0 must be within 10 working days of Phase 0")
    if not phase0 <= d0 <= cycle1 <= cycle2 <= absolute:
        raise EvalManifestError("manifest.timeline deadlines must be ordered")
    if _working_days(d0, cycle1) > 10 or _working_days(d0, cycle2) > 20:
        raise EvalManifestError("manifest.timeline cycle deadlines exceed the 10/20 working-day budget")
    if _working_days(phase0, absolute) > 30:
        raise EvalManifestError("manifest.timeline absolute deadline exceeds 30 working days")
    return timeline


def validate_gate_a_manifest(manifest: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        manifest,
        {
            "schema_version",
            "name",
            "description",
            "revision",
            "source",
            "owners",
            "runtime",
            "timeline",
            "arms",
            "diagnostic_baselines",
            "splits",
            "contamination_policy",
            "thresholds",
            "evaluator_policy",
        },
        "manifest",
    )
    if manifest.get("schema_version") != GATE_A_MANIFEST_SCHEMA_VERSION:
        raise EvalManifestError(f"schema_version must be {GATE_A_MANIFEST_SCHEMA_VERSION!r}")
    _string(manifest.get("name"), "manifest.name")
    _string(manifest.get("description"), "manifest.description")
    _integer(manifest.get("revision"), "manifest.revision", 1)

    source = _object(manifest.get("source"), "manifest.source")
    _exact_keys(
        source,
        {
            "kind",
            "repository_url",
            "snapshot_commit",
            "snapshot_tree_sha256",
            "classification",
            "license_spdx",
            "contains_restricted_data",
        },
        "manifest.source",
    )
    if source.get("kind") != "git":
        raise EvalManifestError("manifest.source.kind must be 'git'")
    _string(source.get("repository_url"), "manifest.source.repository_url")
    commit = _string(source.get("snapshot_commit"), "manifest.source.snapshot_commit")
    if not _COMMIT_RE.fullmatch(commit):
        raise EvalManifestError("manifest.source.snapshot_commit must be a 40-character lowercase Git SHA")
    _digest(source.get("snapshot_tree_sha256"), "manifest.source.snapshot_tree_sha256")
    _string(source.get("classification"), "manifest.source.classification")
    _string(source.get("license_spdx"), "manifest.source.license_spdx")
    if _boolean(source.get("contains_restricted_data"), "manifest.source.contains_restricted_data"):
        raise EvalManifestError("Gate A source must not contain restricted data")

    _owners(manifest.get("owners"), "manifest.owners")
    runtime = _object(manifest.get("runtime"), "manifest.runtime")
    runtime_keys = {
        "target_runtime",
        "hermes_model_id",
        "ai_provider_contract",
        "ai_provider_id",
        "ai_model_id",
        "prompt_version",
        "compiler_version",
        "sandbox_policy_version",
    }
    _exact_keys(runtime, runtime_keys, "manifest.runtime")
    for key in (
        "target_runtime",
        "hermes_model_id",
        "ai_provider_contract",
        "ai_provider_id",
        "ai_model_id",
        "prompt_version",
        "compiler_version",
        "sandbox_policy_version",
    ):
        _string(runtime.get(key), f"manifest.runtime.{key}")
    if runtime.get("target_runtime") != "hermes":
        raise EvalManifestError("manifest.runtime.target_runtime must be 'hermes'")
    _timeline(manifest.get("timeline"))

    arms = _list(manifest.get("arms"), "manifest.arms")
    if len(arms) != 4:
        raise EvalManifestError("manifest.arms must contain exactly four promotion arms")
    arm_keys: set[str] = set()
    retrievals: dict[str, str] = {}
    for index, raw in enumerate(arms):
        arm = _object(raw, f"manifest.arms[{index}]")
        _exact_keys(
            arm,
            {"key", "pack_source", "retrieval_backend", "compiler_inputs", "immutable_pack_before_heldout"},
            f"manifest.arms[{index}]",
        )
        key = _string(arm.get("key"), f"manifest.arms[{index}].key")
        arm_keys.add(key)
        expected_arm = NORMATIVE_ARMS.get(key)
        if expected_arm is None:
            raise EvalManifestError(f"manifest.arms[{index}].key is unsupported")
        retrievals[key] = _string(arm.get("retrieval_backend"), f"manifest.arms[{index}].retrieval_backend")
        for field in ("pack_source", "compiler_inputs"):
            _string(arm.get(field), f"manifest.arms[{index}].{field}")
        for field, expected in expected_arm.items():
            if arm.get(field) != expected:
                raise EvalManifestError(f"manifest arm {key}.{field} must be {expected!r}")
        if not _boolean(arm.get("immutable_pack_before_heldout"), f"manifest.arms[{index}].immutable_pack_before_heldout"):
            raise EvalManifestError("every arm must freeze one immutable pack before held-out reveal")
    if arm_keys != ARM_KEYS:
        raise EvalManifestError(f"manifest.arms keys must be {sorted(ARM_KEYS)}")
    if not (retrievals["real_static"] == retrievals["human_authored"] == retrievals["ai_compiled"]):
        raise EvalManifestError("real_static, human_authored, and ai_compiled must use the same static retrieval backend")

    diagnostic = _list(manifest.get("diagnostic_baselines"), "manifest.diagnostic_baselines")
    if len(diagnostic) != 1:
        raise EvalManifestError("manifest.diagnostic_baselines must declare exactly the direct-tool baseline")
    direct = _object(diagnostic[0], "manifest.diagnostic_baselines[0]")
    expected_direct = {
        "key": "direct_tools_no_sourcebrief",
        "runtime": "hermes",
        "source_access": "pinned-repository",
        "promotion_arm": False,
    }
    if direct != expected_direct:
        raise EvalManifestError("manifest diagnostic direct-tool baseline contract is invalid")

    splits = _object(manifest.get("splits"), "manifest.splits")
    _exact_keys(splits, {"development", "held_out", "controls"}, "manifest.splits")
    development = _list(splits.get("development"), "manifest.splits.development")
    held_out = _list(splits.get("held_out"), "manifest.splits.held_out")
    controls = _list(splits.get("controls"), "manifest.splits.controls")
    if (len(development), len(held_out), len(controls)) != (4, 12, 6):
        raise EvalManifestError("Gate A splits require exactly 4 development, 12 held_out, and 6 controls")
    raw_control_types = {
        item.get("control_type") for item in controls if isinstance(item, dict)
    }
    if raw_control_types != CONTROL_TYPES:
        raise EvalManifestError(f"Gate A control types must be exactly {sorted(CONTROL_TYPES)}")
    all_tasks = [
        *[_task(item, f"manifest.splits.development[{index}]") for index, item in enumerate(development)],
        *[_task(item, f"manifest.splits.held_out[{index}]") for index, item in enumerate(held_out)],
        *[_task(item, f"manifest.splits.controls[{index}]", control=True) for index, item in enumerate(controls)],
    ]
    ids = [item["id"] for item in all_tasks]
    fingerprints = [item["content_sha256"] for item in all_tasks]
    if len(ids) != len(set(ids)):
        raise EvalManifestError("duplicate task id across Gate A splits")
    if len(fingerprints) != len(set(fingerprints)):
        raise EvalManifestError("duplicate task content fingerprint across Gate A splits")
    if {item["control_type"] for item in controls} != CONTROL_TYPES:
        raise EvalManifestError(f"Gate A control types must be exactly {sorted(CONTROL_TYPES)}")

    contamination = _object(manifest.get("contamination_policy"), "manifest.contamination_policy")
    _exact_keys(contamination, {"policy_version", "checks"}, "manifest.contamination_policy")
    _string(contamination.get("policy_version"), "manifest.contamination_policy.policy_version")
    if set(_list(contamination.get("checks"), "manifest.contamination_policy.checks")) != CONTAMINATION_CHECKS:
        raise EvalManifestError(f"manifest contamination checks must be exactly {sorted(CONTAMINATION_CHECKS)}")
    thresholds = _object(manifest.get("thresholds"), "manifest.thresholds")
    if thresholds != NORMATIVE_THRESHOLDS:
        raise EvalManifestError("manifest.thresholds must exactly match the normative Gate A thresholds")

    evaluator = _object(manifest.get("evaluator_policy"), "manifest.evaluator_policy")
    _exact_keys(
        evaluator,
        {
            "pairwise_blinding",
            "order_randomization",
            "generator_can_approve",
            "outside_knowledge_allowed",
            "judge_prompt_sha256",
            "human_rubric_version",
            "evaluator_id",
            "evaluator_version",
            "forbidden_identity_fields",
        },
        "manifest.evaluator_policy",
    )
    if evaluator.get("pairwise_blinding") != "recursive-allowlist":
        raise EvalManifestError("manifest evaluator must use recursive-allowlist blinding")
    if not _boolean(evaluator.get("order_randomization"), "manifest.evaluator_policy.order_randomization"):
        raise EvalManifestError("Gate A requires randomized pairwise order")
    if _boolean(evaluator.get("generator_can_approve"), "manifest.evaluator_policy.generator_can_approve"):
        raise EvalManifestError("Gate A generator cannot approve")
    if _boolean(evaluator.get("outside_knowledge_allowed"), "manifest.evaluator_policy.outside_knowledge_allowed"):
        raise EvalManifestError("Gate A evaluator cannot use outside knowledge")
    _digest(evaluator.get("judge_prompt_sha256"), "manifest.evaluator_policy.judge_prompt_sha256")
    _string(evaluator.get("human_rubric_version"), "manifest.evaluator_policy.human_rubric_version")
    _string(evaluator.get("evaluator_id"), "manifest.evaluator_policy.evaluator_id")
    _string(evaluator.get("evaluator_version"), "manifest.evaluator_policy.evaluator_version")
    forbidden = _list(evaluator.get("forbidden_identity_fields"), "manifest.evaluator_policy.forbidden_identity_fields")
    if set(forbidden) != FORBIDDEN_IDENTITY_FIELDS or len(forbidden) != len(FORBIDDEN_IDENTITY_FIELDS):
        raise EvalManifestError(
            f"forbidden_identity_fields must be exactly {sorted(FORBIDDEN_IDENTITY_FIELDS)}"
        )

    return {
        "schema_version": GATE_A_MANIFEST_SCHEMA_VERSION,
        "manifest_sha256": sha256_digest(manifest),
        "development_task_count": 4,
        "held_out_task_count": 12,
        "control_count": 6,
        "arm_count": 4,
    }


def sign_gate_a_approval(approval: dict[str, Any], *, approval_key: bytes) -> str:
    if not approval_key:
        raise EvalManifestError("approval HMAC key must not be empty")
    unsigned = {key: value for key, value in approval.items() if key != "approval_signature"}
    signature = hmac.new(approval_key, canonical_json(unsigned).encode("utf-8"), hashlib.sha256).hexdigest()
    return f"hmac-sha256:{signature}"


def validate_gate_a_approval(
    manifest: dict[str, Any],
    approval: dict[str, Any],
    *,
    approval_key: bytes,
) -> dict[str, Any]:
    validate_gate_a_manifest(manifest)
    _exact_keys(
        approval,
        {
            "schema_version",
            "manifest_sha256",
            "manifest_revision",
            "approved_at",
            "candidate_tuning_authorized",
            "attestation_kind",
            "approvers",
            "approval_event",
            "approval_signature",
        },
        "approval",
    )
    if approval.get("schema_version") != GATE_A_APPROVAL_SCHEMA_VERSION:
        raise EvalManifestError(f"approval.schema_version must be {GATE_A_APPROVAL_SCHEMA_VERSION!r}")
    if approval.get("manifest_sha256") != sha256_digest(manifest):
        raise EvalManifestError("approval.manifest_sha256 does not match manifest")
    if approval.get("manifest_revision") != manifest.get("revision"):
        raise EvalManifestError("approval.manifest_revision does not match manifest revision")
    approved_at = _timestamp(approval.get("approved_at"), "approval.approved_at")
    if approved_at != _timestamp(manifest["timeline"]["d0"], "manifest.timeline.d0"):
        raise EvalManifestError("approval.approved_at must equal frozen D0")
    if not _boolean(approval.get("candidate_tuning_authorized"), "approval.candidate_tuning_authorized"):
        raise EvalManifestError("approval must authorize candidate tuning")
    if approval.get("attestation_kind") != "content-addressed-human-approval":
        raise EvalManifestError("approval.attestation_kind is invalid")
    approvers = _owners(approval.get("approvers"), "approval.approvers")
    if approvers != manifest.get("owners"):
        raise EvalManifestError("approval.approvers must exactly match manifest owners")

    event = _object(approval.get("approval_event"), "approval.approval_event")
    _exact_keys(
        event,
        {
            "event_id",
            "issuer",
            "actor_id",
            "actor_contact",
            "issued_at",
            "comment",
            "signer_contacts",
            "payload_sha256",
        },
        "approval.approval_event",
    )
    scalar_event_fields = {
        key: _string(event.get(key), f"approval.approval_event.{key}")
        for key in ("event_id", "issuer", "actor_id", "actor_contact", "comment")
    }
    if scalar_event_fields["actor_contact"].strip().lower() != approvers["eval_qa"]["contact"].strip().lower():
        raise EvalManifestError("approval event actor_contact must be the Eval/QA owner")
    if _timestamp(event.get("issued_at"), "approval.approval_event.issued_at") != approved_at:
        raise EvalManifestError("approval event issued_at must equal approved_at")
    signer_contacts = _list(event.get("signer_contacts"), "approval.approval_event.signer_contacts")
    expected_signers = {
        approvers[role]["contact"]
        for role in ("product", "eval_qa", "runtime_pack", "security")
    }
    if set(signer_contacts) != expected_signers or len(signer_contacts) != len(expected_signers):
        raise EvalManifestError("approval event signer_contacts must exactly include Product, Eval/QA, Runtime Pack, and Security")
    payload = {
        "manifest_sha256": approval["manifest_sha256"],
        "manifest_revision": approval["manifest_revision"],
        "approved_at": approval["approved_at"],
        "candidate_tuning_authorized": approval["candidate_tuning_authorized"],
        "event_id": event["event_id"],
        "issuer": event["issuer"],
        "actor_id": event["actor_id"],
        "actor_contact": event["actor_contact"],
        "issued_at": event["issued_at"],
        "comment": event["comment"],
        "signer_contacts": signer_contacts,
    }
    if event.get("payload_sha256") != sha256_digest(payload):
        raise EvalManifestError("approval event payload_sha256 does not match signed payload")
    expected_signature = sign_gate_a_approval(approval, approval_key=approval_key)
    signature = _string(approval.get("approval_signature"), "approval.approval_signature")
    if not hmac.compare_digest(signature, expected_signature):
        raise EvalManifestError("approval signature verification failed")
    return {
        "schema_version": GATE_A_APPROVAL_SCHEMA_VERSION,
        "approval_sha256": sha256_digest(approval),
        "manifest_sha256": approval["manifest_sha256"],
        "approval_event_id": event["event_id"],
        "d0_ready": True,
    }


def compiler_input(
    manifest: dict[str, Any],
    *,
    approval: dict[str, Any],
    approval_key: bytes,
) -> dict[str, Any]:
    validate_gate_a_approval(manifest, approval, approval_key=approval_key)
    source_keys = (
        "kind",
        "repository_url",
        "snapshot_commit",
        "snapshot_tree_sha256",
        "classification",
        "license_spdx",
        "contains_restricted_data",
    )
    runtime_keys = (
        "target_runtime",
        "hermes_model_id",
        "ai_provider_contract",
        "ai_provider_id",
        "ai_model_id",
        "prompt_version",
        "compiler_version",
        "sandbox_policy_version",
    )
    task_keys = (
        "id",
        "task_class",
        "prompt",
        "allowed_paths",
        "forbidden_paths",
        "objective_assertions",
        "expected_evidence",
        "content_sha256",
    )
    return {
        "schema_version": "sourcebrief.gate-a-compiler-input.v1",
        "manifest_sha256": sha256_digest(manifest),
        "approval_sha256": sha256_digest(approval),
        "source": {key: deepcopy(manifest["source"][key]) for key in source_keys},
        "runtime": {key: deepcopy(manifest["runtime"][key]) for key in runtime_keys},
        "development_tasks": [
            {key: deepcopy(task[key]) for key in task_keys}
            for task in manifest["splits"]["development"]
        ],
        "compiler_visibility": "source-and-development-only",
    }


def _blinded_string(value: Any, context: str) -> str:
    result = _string(value, context)
    normalized = result
    for _ in range(3):
        normalized = re.sub(
            r"\\u([0-9a-fA-F]{4})",
            lambda match: chr(int(match.group(1), 16)),
            normalized,
        )
        normalized = normalized.replace(r'\"', '"').replace(r"\'", "'").replace(r"\\", "\\")
    if _BLINDED_IDENTITY_RE.search(normalized):
        raise EvalManifestError(f"{context} contains candidate/provider/profile identity metadata")
    return result


def _safe_citation(value: Any) -> dict[str, Any]:
    item = _object(value, "pairwise citation")
    result: dict[str, Any] = {}
    for key in ("label", "path", "heading", "content"):
        if key in item:
            result[key] = _blinded_string(item[key], f"pairwise citation.{key}")
    if "content_hash" in item:
        result["content_hash"] = _digest(item["content_hash"], "pairwise citation.content_hash")
    for key in ("line_start", "line_end"):
        if key in item:
            result[key] = _integer(item[key], f"pairwise citation.{key}", 1)
    return result


def _safe_symbol(value: Any) -> dict[str, Any]:
    item = _object(value, "pairwise code symbol")
    result: dict[str, Any] = {}
    for key in ("name", "kind", "path", "signature"):
        if key in item:
            result[key] = _blinded_string(item[key], f"pairwise code symbol.{key}")
    if "content_hash" in item:
        result["content_hash"] = _digest(item["content_hash"], "pairwise code symbol.content_hash")
    for key in ("line_start", "line_end"):
        if key in item:
            result[key] = _integer(item[key], f"pairwise code symbol.{key}", 1)
    return result


def sanitize_pairwise_context(raw: dict[str, Any]) -> dict[str, Any]:
    """Build the evaluator view from scalar/typed allowlists; never pass nested metadata."""
    source = _object(raw, "pairwise context")
    result: dict[str, Any] = {}
    if "context" in source:
        result["context"] = _blinded_string(source["context"], "pairwise context.context")
    if "answer" in source:
        answer_raw = _object(source["answer"], "pairwise answer")
        answer: dict[str, Any] = {}
        for key in ("text", "outcome"):
            if key in answer_raw:
                answer[key] = _blinded_string(answer_raw[key], f"pairwise answer.{key}")
        if "confidence" in answer_raw:
            confidence = answer_raw["confidence"]
            if isinstance(confidence, str):
                normalized = _blinded_string(confidence, "pairwise answer.confidence").lower()
                if normalized not in {"low", "medium", "high"}:
                    raise EvalManifestError("pairwise answer.confidence string must be low, medium, or high")
                answer["confidence"] = normalized
            elif isinstance(confidence, int | float) and not isinstance(confidence, bool):
                answer["confidence"] = _number(confidence, "pairwise answer.confidence", 0, 1)
            else:
                raise EvalManifestError("pairwise answer.confidence must be a string or finite numeric scalar")
        if "citations_used" in answer_raw:
            answer["citations_used"] = [
                _safe_citation(item)
                for item in _list(answer_raw["citations_used"], "pairwise answer.citations_used")
            ]
        result["answer"] = answer
    if "citations" in source:
        result["citations"] = [
            _safe_citation(item)
            for item in _list(source["citations"], "pairwise citations")
        ]
    if "code_symbols" in source:
        result["code_symbols"] = [
            _safe_symbol(item)
            for item in _list(source["code_symbols"], "pairwise code_symbols")
        ]
    return result


def _task_result(value: Any, context: str) -> dict[str, Any]:
    result = _object(value, context)
    _exact_keys(
        result,
        {
            "task_id",
            "success",
            "abstained",
            "exact_support",
            "required_resource_recall",
            "facet_coverage",
            "claim_support_precision",
            "citation_correctness",
            "receipt_sha256",
        },
        context,
    )
    _string(result.get("task_id"), f"{context}.task_id")
    success = _boolean(result.get("success"), f"{context}.success")
    abstained = _boolean(result.get("abstained"), f"{context}.abstained")
    if success and abstained:
        raise EvalManifestError(f"{context} cannot be both successful and abstained")
    _boolean(result.get("exact_support"), f"{context}.exact_support")
    for key in ("required_resource_recall", "facet_coverage", "claim_support_precision", "citation_correctness"):
        _number(result.get(key), f"{context}.{key}", 0, 1)
    _digest(result.get("receipt_sha256"), f"{context}.receipt_sha256")
    return result


def _validate_receipt_manifest(
    value: Any,
    *,
    report: dict[str, Any],
    manifest: dict[str, Any],
    arms: dict[str, dict[str, Any]],
) -> None:
    receipt = _object(value, "report.receipt_manifest")
    _exact_keys(
        receipt,
        {
            "schema_version",
            "candidate_sourcebrief_commit",
            "source_snapshot_commit",
            "provider_id",
            "model_id",
            "prompt_version",
            "compiler_version",
            "evaluator_id",
            "evaluator_version",
            "randomized_arm_mapping_sha256",
            "arm_pack_sha256",
            "indexes",
            "raw_bundle_sha256",
        },
        "report.receipt_manifest",
    )
    if receipt.get("schema_version") != "sourcebrief.gate-a-receipts.v1":
        raise EvalManifestError("report.receipt_manifest schema_version is invalid")
    expected_scalars = {
        "candidate_sourcebrief_commit": report["candidate_sourcebrief_commit"],
        "source_snapshot_commit": manifest["source"]["snapshot_commit"],
        "provider_id": manifest["runtime"]["ai_provider_id"],
        "model_id": manifest["runtime"]["ai_model_id"],
        "prompt_version": manifest["runtime"]["prompt_version"],
        "compiler_version": manifest["runtime"]["compiler_version"],
        "evaluator_id": manifest["evaluator_policy"]["evaluator_id"],
        "evaluator_version": manifest["evaluator_policy"]["evaluator_version"],
    }
    for key, expected in expected_scalars.items():
        if receipt.get(key) != expected:
            raise EvalManifestError(f"report.receipt_manifest {key} provenance does not match frozen contract")
    _digest(receipt.get("randomized_arm_mapping_sha256"), "report.receipt_manifest.randomized_arm_mapping_sha256")
    pack_hashes = _object(receipt.get("arm_pack_sha256"), "report.receipt_manifest.arm_pack_sha256")
    if set(pack_hashes) != ARM_KEYS:
        raise EvalManifestError("report.receipt_manifest arm_pack_sha256 must include every arm")
    for key in ARM_KEYS:
        if pack_hashes.get(key) != arms[key]["pack_sha256"]:
            raise EvalManifestError(f"report.receipt_manifest pack hash does not match arm {key}")
        _digest(pack_hashes[key], f"report.receipt_manifest.arm_pack_sha256.{key}")
    indexes = _list(receipt.get("indexes"), "report.receipt_manifest.indexes")
    by_kind: dict[str, dict[str, Any]] = {}
    for index, raw_index in enumerate(indexes):
        item = _object(raw_index, f"report.receipt_manifest.indexes[{index}]")
        _exact_keys(item, {"kind", "sha256", "record_count"}, f"report.receipt_manifest.indexes[{index}]")
        kind = _string(item.get("kind"), f"report.receipt_manifest.indexes[{index}].kind")
        if kind in by_kind:
            raise EvalManifestError(f"duplicate receipt index kind: {kind}")
        _digest(item.get("sha256"), f"report.receipt_manifest.indexes[{index}].sha256")
        _integer(item.get("record_count"), f"report.receipt_manifest.indexes[{index}].record_count", 0)
        by_kind[kind] = item
    if set(by_kind) != {"task_results", "latency_cost", "failure_reasons"}:
        raise EvalManifestError("report.receipt_manifest must include task_results, latency_cost, and failure_reasons indexes")
    if by_kind["task_results"]["record_count"] != 72:
        raise EvalManifestError("report.receipt_manifest task_results must contain 72 held-out/control records")
    if by_kind["latency_cost"]["record_count"] < int(NORMATIVE_THRESHOLDS["compile_repetitions"]):
        raise EvalManifestError("report.receipt_manifest latency_cost index must cover all three compile repetitions")
    raw_bundle = _digest(receipt.get("raw_bundle_sha256"), "report.receipt_manifest.raw_bundle_sha256")
    if raw_bundle != report.get("raw_receipts_sha256"):
        raise EvalManifestError("report.receipt_manifest raw bundle hash does not match report")


def validate_gate_a_report(
    report: dict[str, Any],
    *,
    manifest: dict[str, Any],
    approval: dict[str, Any],
    approval_key: bytes,
) -> dict[str, Any]:
    validate_gate_a_approval(manifest, approval, approval_key=approval_key)
    _exact_keys(
        report,
        {
            "schema_version",
            "manifest_sha256",
            "approval_sha256",
            "candidate_sourcebrief_commit",
            "cycle",
            "run_started_at",
            "run_finished_at",
            "runtime",
            "corpus_state",
            "arms",
            "ai_compile_receipts",
            "ai_first_use_minutes",
            "ai_active_review_minutes",
            "human_author_review_minutes",
            "ai_cost_usd",
            "approval_object_count",
            "raw_receipts_sha256",
            "receipt_manifest",
            "verdict",
        },
        "report",
    )
    if report.get("schema_version") != GATE_A_REPORT_SCHEMA_VERSION:
        raise EvalManifestError(f"report.schema_version must be {GATE_A_REPORT_SCHEMA_VERSION!r}")
    if report.get("manifest_sha256") != sha256_digest(manifest):
        raise EvalManifestError("report.manifest_sha256 does not match manifest")
    if report.get("approval_sha256") != sha256_digest(approval):
        raise EvalManifestError("report.approval_sha256 does not match approval")
    commit = _string(report.get("candidate_sourcebrief_commit"), "report.candidate_sourcebrief_commit")
    if not _COMMIT_RE.fullmatch(commit):
        raise EvalManifestError("report candidate commit is invalid")
    cycle = _integer(report.get("cycle"), "report.cycle", 1)
    if cycle > int(NORMATIVE_THRESHOLDS["candidate_cycles_max"]):
        raise EvalManifestError("report.cycle exceeds candidate-cycle budget")
    started = _timestamp(report.get("run_started_at"), "report.run_started_at")
    finished = _timestamp(report.get("run_finished_at"), "report.run_finished_at")
    if finished < started:
        raise EvalManifestError("report run timestamps are reversed")
    d0 = _timestamp(manifest["timeline"]["d0"], "manifest.timeline.d0")
    cycle_deadline_key = f"cycle{cycle}_deadline"
    cycle_deadline = _timestamp(manifest["timeline"][cycle_deadline_key], f"manifest.timeline.{cycle_deadline_key}")
    absolute_deadline = _timestamp(manifest["timeline"]["absolute_deadline"], "manifest.timeline.absolute_deadline")
    if started < d0 or finished > cycle_deadline or finished > absolute_deadline:
        raise EvalManifestError(f"report run must fall between D0 and manifest.timeline.{cycle_deadline_key}")
    if report.get("runtime") != manifest.get("runtime"):
        raise EvalManifestError("report.runtime provenance must exactly match manifest.runtime")
    if report.get("corpus_state") != "full":
        raise EvalManifestError("report.corpus_state must be full; partial corpora cannot authorize Gate A")

    held_ids = {item["id"] for item in manifest["splits"]["held_out"]}
    control_ids = {item["id"] for item in manifest["splits"]["controls"]}
    raw_arms = _list(report.get("arms"), "report.arms")
    if len(raw_arms) != 4:
        raise EvalManifestError("report.arms must contain four arms")
    arms: dict[str, dict[str, Any]] = {}
    for arm_index, raw in enumerate(raw_arms):
        arm = _object(raw, f"report.arms[{arm_index}]")
        _exact_keys(arm, {"arm_key", "pack_sha256", "task_results", "control_results"}, f"report.arms[{arm_index}]")
        key = _string(arm.get("arm_key"), f"report.arms[{arm_index}].arm_key")
        if key in arms:
            raise EvalManifestError(f"duplicate report arm: {key}")
        _digest(arm.get("pack_sha256"), f"report.arms[{arm_index}].pack_sha256")
        results = [_task_result(item, f"report.arms[{arm_index}].task_results[{index}]") for index, item in enumerate(_list(arm.get("task_results"), f"report.arms[{arm_index}].task_results"))]
        if len(results) != len(held_ids) or {item["task_id"] for item in results} != held_ids:
            raise EvalManifestError(f"report arm {key} task_results must exactly match held-out tasks")
        controls = _list(arm.get("control_results"), f"report.arms[{arm_index}].control_results")
        seen_controls: set[str] = set()
        for index, raw_control in enumerate(controls):
            control = _object(raw_control, f"report.arms[{arm_index}].control_results[{index}]")
            _exact_keys(
                control,
                {"control_id", "passed", "receipt_sha256"},
                f"report.arms[{arm_index}].control_results[{index}]",
            )
            seen_controls.add(_string(control.get("control_id"), "control_result.control_id"))
            _boolean(control.get("passed"), "control_result.passed")
            _digest(control.get("receipt_sha256"), "control_result.receipt_sha256")
        if len(controls) != len(control_ids) or seen_controls != control_ids:
            raise EvalManifestError(f"report arm {key} control_results must exactly match held-out controls")
        arms[key] = arm
    if set(arms) != ARM_KEYS:
        raise EvalManifestError(f"report arm keys must be {sorted(ARM_KEYS)}")
    _validate_receipt_manifest(report.get("receipt_manifest"), report=report, manifest=manifest, arms=arms)

    success_counts = {key: sum(bool(item["success"]) for item in arm["task_results"]) for key, arm in sorted(arms.items())}
    lane_metrics: dict[str, dict[str, float]] = {}
    for key, arm in sorted(arms.items()):
        results = arm["task_results"]
        lane_metrics[key] = {
            metric: sum(float(item[metric]) for item in results) / len(results)
            for metric in ("required_resource_recall", "facet_coverage", "claim_support_precision", "citation_correctness")
        }
        lane_metrics[key]["abstention_rate"] = sum(bool(item["abstained"]) for item in results) / len(results)

    ai_results = arms["ai_compiled"]["task_results"]
    best_automated_key = max(
        AUTOMATED_ARM_KEYS,
        key=lambda key: (success_counts[key], key == "real_static"),
    )
    best_automated = success_counts[best_automated_key]
    ai_by_task = {item["task_id"]: item for item in ai_results}
    baseline_regressions = sum(
        bool(item["success"]) and not bool(ai_by_task[item["task_id"]]["success"])
        for item in arms[best_automated_key]["task_results"]
    )
    controls_passed = sum(bool(item["passed"]) for item in arms["ai_compiled"]["control_results"])
    exact_support_ok = all(bool(item["exact_support"]) for item in ai_results if item["success"])
    support_metrics_ok = all(
        all(
            float(item[metric]) == 1.0
            for metric in ("required_resource_recall", "facet_coverage", "claim_support_precision", "citation_correctness")
        )
        for item in ai_results
        if item["success"]
    )

    compile_receipts = _list(report.get("ai_compile_receipts"), "report.ai_compile_receipts")
    compile_ok = len(compile_receipts) == int(NORMATIVE_THRESHOLDS["compile_repetitions"])
    attempts: set[int] = set()
    for index, raw in enumerate(compile_receipts):
        receipt = _object(raw, f"report.ai_compile_receipts[{index}]")
        _exact_keys(
            receipt,
            {"attempt", "succeeded", "duration_minutes", "provider_retries", "receipt_sha256"},
            f"report.ai_compile_receipts[{index}]",
        )
        attempts.add(_integer(receipt.get("attempt"), f"compile_receipt[{index}].attempt", 1))
        compile_ok = compile_ok and _boolean(receipt.get("succeeded"), f"compile_receipt[{index}].succeeded")
        compile_ok = compile_ok and _number(receipt.get("duration_minutes"), f"compile_receipt[{index}].duration_minutes") <= float(NORMATIVE_THRESHOLDS["compile_max_minutes"])
        compile_ok = compile_ok and _integer(receipt.get("provider_retries"), f"compile_receipt[{index}].provider_retries", 0) <= int(NORMATIVE_THRESHOLDS["provider_retries_max"])
        _digest(receipt.get("receipt_sha256"), f"compile_receipt[{index}].receipt_sha256")
    compile_ok = compile_ok and attempts == {1, 2, 3}

    first_use = _number(report.get("ai_first_use_minutes"), "report.ai_first_use_minutes")
    ai_review = _number(report.get("ai_active_review_minutes"), "report.ai_active_review_minutes")
    human_review = _number(report.get("human_author_review_minutes"), "report.human_author_review_minutes")
    cost = _number(report.get("ai_cost_usd"), "report.ai_cost_usd")
    approvals = _integer(report.get("approval_object_count"), "report.approval_object_count", 0)
    _digest(report.get("raw_receipts_sha256"), "report.raw_receipts_sha256")

    failures: list[str] = []
    if success_counts["ai_compiled"] < int(NORMATIVE_THRESHOLDS["ai_task_success_min"]):
        failures.append("AI task-success floor")
    if success_counts["ai_compiled"] - best_automated < int(NORMATIVE_THRESHOLDS["win_margin_vs_best_automated_min"]):
        failures.append("win margin versus automated baseline")
    if success_counts["human_authored"] - success_counts["ai_compiled"] > int(NORMATIVE_THRESHOLDS["task_gap_vs_human_max"]):
        failures.append("task gap versus human pack")
    if baseline_regressions > int(NORMATIVE_THRESHOLDS["baseline_regressions_max"]):
        failures.append("baseline regressions")
    if controls_passed != int(NORMATIVE_THRESHOLDS["controls_required"]):
        failures.append("negative/security controls")
    if not exact_support_ok:
        failures.append("exact support")
    if not support_metrics_ok:
        failures.append("complete resource/facet/claim/citation support")
    if lane_metrics["ai_compiled"]["abstention_rate"] > 0 and success_counts["ai_compiled"] < int(NORMATIVE_THRESHOLDS["ai_task_success_min"]):
        failures.append("abstention gaming")
    if not compile_ok:
        failures.append("compile repetitions/latency/retry budget")
    if first_use > float(NORMATIVE_THRESHOLDS["first_use_max_minutes"]):
        failures.append("first-use budget")
    if ai_review > float(NORMATIVE_THRESHOLDS["review_max_minutes"]) or ai_review > human_review * float(NORMATIVE_THRESHOLDS["review_vs_human_max_ratio"]):
        failures.append("review economics")
    if cost > float(NORMATIVE_THRESHOLDS["cost_max_usd"]):
        failures.append("cost budget")
    if approvals > int(NORMATIVE_THRESHOLDS["approval_objects_max"]):
        failures.append("approval object count")

    computed = "PASS" if not failures else "FAIL"
    declared = _string(report.get("verdict"), "report.verdict")
    if declared != computed:
        raise EvalManifestError(f"report declared verdict {declared!r} does not match computed {computed!r}: {', '.join(failures) or 'no failures'}")
    return {
        "schema_version": GATE_A_REPORT_SCHEMA_VERSION,
        "report_sha256": sha256_digest(report),
        "computed_verdict": computed,
        "task_success_counts": success_counts,
        "lane_metrics": lane_metrics,
        "best_automated_arm": best_automated_key,
        "baseline_regressions": baseline_regressions,
        "controls_passed": controls_passed,
        "failures": failures,
    }
