from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ArtifactSensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PRIVATE = "private"
    SECRET = "secret"


class BundleCompleteness(StrEnum):
    COMPLETE = "complete"
    REDACTED_PARTIAL = "redacted_partial"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class EgressDecision(StrEnum):
    LOCAL_ONLY = "local_only"
    APPROVED_INTERNAL = "approved_internal"
    APPROVED_EXTERNAL = "approved_external"
    DENIED = "denied"


class ReviewArtifactSecurityError(ValueError):
    """Raised when a self-improvement artifact would cross a safety boundary."""


_LOCAL_REVIEWER_BACKENDS = {"local", "mock", "offline", "deterministic", "deterministic-citation-support"}
_INTERNAL_REVIEWER_BACKENDS = {"internal", "internal-reviewer"}
_SECRET_KEY_RE = re.compile(r"(?i)(authorization|cookie|password|passwd|secret|token|api[_-]?key|session)")
_LOCAL_PATH_RE = re.compile(r"(?<![\w:/.-])(?:file://)?/(?:home|Users)/[A-Za-z0-9._-]+/[^\s)\]}'\"]+")
_BEARER_RE = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}")
_SOURCEBRIEF_TOKEN_RE = re.compile(r"\bcs_[A-Za-z0-9_-]{20,}\b")
_GITHUB_TOKEN_RE = re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")
_SLACK_TOKEN_RE = re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")
_OPENAI_KEY_RE = re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")
_AWS_ACCESS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_GENERIC_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|token|secret|password|passwd|session[_-]?token)\s*[:=]\s*['\"]?([^\s'\"]+)"
)

_SECRET_VALUE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("bearer_token", _BEARER_RE),
    ("sourcebrief_token", _SOURCEBRIEF_TOKEN_RE),
    ("github_token", _GITHUB_TOKEN_RE),
    ("slack_token", _SLACK_TOKEN_RE),
    ("openai_key", _OPENAI_KEY_RE),
    ("aws_access_key_id", _AWS_ACCESS_KEY_RE),
    ("generic_secret_assignment", _GENERIC_ASSIGNMENT_RE),
    ("local_path", _LOCAL_PATH_RE),
)


@dataclass(frozen=True)
class RedactionReport:
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def redacted(self) -> bool:
        return bool(self.counts)

    def add(self, name: str, count: int = 1) -> None:
        if count:
            self.counts[name] = self.counts.get(name, 0) + count

    def merge(self, other: RedactionReport) -> None:
        for name, count in other.counts.items():
            self.add(name, count)


@dataclass(frozen=True)
class ReviewArtifactScope:
    """Workspace/project/resource boundary inherited from the source task.

    Empty ``resource_ids`` means project-scoped review inside the same workspace and
    project. A non-empty set means reviewers must stay within that resource subset.
    """

    workspace_id: str
    project_id: str
    resource_ids: tuple[str, ...] = ()
    context_pack_key: str | None = None

    def allows(self, *, workspace_id: str, project_id: str, resource_ids: Sequence[str] = ()) -> bool:
        if workspace_id != self.workspace_id or project_id != self.project_id:
            return False
        if not self.resource_ids:
            return True
        if not resource_ids:
            return False
        return set(resource_ids).issubset(set(self.resource_ids))

    def require_allows(
        self,
        *,
        workspace_id: str,
        project_id: str,
        resource_ids: Sequence[str] = (),
    ) -> None:
        if not self.allows(workspace_id=workspace_id, project_id=project_id, resource_ids=resource_ids):
            raise ReviewArtifactSecurityError("review artifact scope cannot widen workspace/project/resource access")


@dataclass(frozen=True)
class ReviewArtifactPolicy:
    sensitivity: ArtifactSensitivity = ArtifactSensitivity.INTERNAL
    retention_days: int = 30
    allowed_reviewer_backends: tuple[str, ...] = ("local", "mock")
    external_reviewer_opt_in: bool = False
    purge_derived_artifacts: bool = True

    def __post_init__(self) -> None:
        if self.retention_days < 0:
            raise ReviewArtifactSecurityError("retention_days must be non-negative")
        if not self.allowed_reviewer_backends:
            raise ReviewArtifactSecurityError("at least one reviewer backend must be allowed")
        if self.sensitivity is ArtifactSensitivity.SECRET and self.external_reviewer_opt_in:
            raise ReviewArtifactSecurityError("secret artifacts cannot opt in to external reviewer egress")

    def egress_for_backend(self, backend: str) -> EgressDecision:
        if backend not in self.allowed_reviewer_backends:
            return EgressDecision.DENIED
        if backend in _LOCAL_REVIEWER_BACKENDS:
            return EgressDecision.LOCAL_ONLY
        if backend in _INTERNAL_REVIEWER_BACKENDS:
            return EgressDecision.APPROVED_INTERNAL
        if not self.external_reviewer_opt_in:
            return EgressDecision.DENIED
        if self.sensitivity is ArtifactSensitivity.SECRET:
            return EgressDecision.DENIED
        return EgressDecision.APPROVED_EXTERNAL

    def require_backend_allowed(self, backend: str) -> EgressDecision:
        decision = self.egress_for_backend(backend)
        if decision is EgressDecision.DENIED:
            raise ReviewArtifactSecurityError("reviewer backend is not allowed for this artifact policy")
        return decision


def redact_text(value: str) -> tuple[str, RedactionReport]:
    report = RedactionReport()
    redacted = value
    for name, pattern in _SECRET_VALUE_PATTERNS:
        def replacement(match: re.Match[str], redaction_name: str = name) -> str:
            if redaction_name == "generic_secret_assignment":
                return f"{match.group(1)}=[REDACTED:{redaction_name}]"
            return f"[REDACTED:{redaction_name}]"

        redacted, count = pattern.subn(replacement, redacted)
        report.add(name, count)
    return redacted, report


def redact_review_artifact(value: Any) -> tuple[Any, RedactionReport]:
    """Recursively redact artifact payloads before storage or reviewer egress.

    Dict values with secret-looking keys are replaced entirely, while free-form
    strings are scrubbed for token and private-path patterns. The function is
    intentionally deterministic so schema examples and review bundles can be
    tested without calling an LLM.
    """

    report = RedactionReport()
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        output: dict[Any, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            redacted_key, key_report = redact_text(key_str)
            report.merge(key_report)
            output_key = redacted_key
            if _SECRET_KEY_RE.search(key_str):
                output_key = "[REDACTED:secret_key]"
                output[output_key] = "[REDACTED:secret_value]"
                report.add("secret_key")
                continue
            redacted_item, child_report = redact_review_artifact(item)
            output[output_key] = redacted_item
            report.merge(child_report)
        return output, report
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray):
        output_list = []
        for item in value:
            redacted_item, child_report = redact_review_artifact(item)
            output_list.append(redacted_item)
            report.merge(child_report)
        return output_list, report
    return value, report


def build_security_metadata(
    *,
    policy: ReviewArtifactPolicy,
    scope: ReviewArtifactScope,
    reviewer_backend: str,
    completeness: BundleCompleteness,
    redaction_report: RedactionReport,
) -> dict[str, Any]:
    decision = policy.require_backend_allowed(reviewer_backend)
    return {
        "sensitivity": policy.sensitivity.value,
        "retention_days": policy.retention_days,
        "allowed_reviewer_backends": list(policy.allowed_reviewer_backends),
        "reviewer_backend": reviewer_backend,
        "egress_decision": decision.value,
        "external_reviewer_opt_in": policy.external_reviewer_opt_in,
        "purge_derived_artifacts": policy.purge_derived_artifacts,
        "completeness": completeness.value,
        "redaction_counts": dict(redaction_report.counts),
        "scope": {
            "workspace_id": scope.workspace_id,
            "project_id": scope.project_id,
            "resource_ids": list(scope.resource_ids),
            "context_pack_key": scope.context_pack_key,
        },
    }
