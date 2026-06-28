import stat
from pathlib import Path

import pytest
from pydantic import ValidationError

from sourcebrief_shared.review_bundle import (
    REVIEW_BUNDLE_SCHEMA_VERSION,
    ReviewBundle,
    load_review_bundle,
    review_bundle_json_schema,
    sanitize_review_bundle_payload,
    write_review_bundle,
)
from sourcebrief_shared.self_improvement_security import (
    ArtifactSensitivity,
    BundleCompleteness,
    ReviewArtifactPolicy,
    ReviewArtifactScope,
    ReviewArtifactSecurityError,
    redact_review_artifact,
)

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs" / "examples" / "self-improvement"


def test_review_bundle_examples_validate_and_are_public_safe() -> None:
    examples = sorted(EXAMPLES.glob("review-bundle-*.json"))
    assert len(examples) >= 2

    for path in examples:
        bundle = load_review_bundle(path)
        assert bundle.schema_version == REVIEW_BUNDLE_SCHEMA_VERSION
        assert bundle.security.scope == bundle.scope
        assert bundle.security.egress_decision == "local_only"
        redacted, report = redact_review_artifact(bundle.model_dump(mode="json"))
        assert report.counts == {}, f"example still contains redactable content: {path} {report.counts}"
        serialized = str(redacted)
        assert "/home/" not in serialized
        assert "/Users/" not in serialized
        assert "Bearer " not in serialized
        assert "cs_" not in serialized
        assert "password=" not in serialized.lower()


def test_review_bundle_rejects_unknown_top_level_fields() -> None:
    payload = load_review_bundle(EXAMPLES / "review-bundle-docs-answer.json").model_dump(mode="json")
    payload["unexpected"] = "not allowed"

    with pytest.raises(ValidationError):
        ReviewBundle.model_validate(payload)


def test_review_bundle_security_scope_must_match_top_level_scope() -> None:
    payload = load_review_bundle(EXAMPLES / "review-bundle-docs-answer.json").model_dump(mode="json")
    payload["security"]["scope"]["resource_ids"] = ["resource-widened"]

    with pytest.raises(ValidationError, match="security.scope must match bundle scope"):
        ReviewBundle.model_validate(payload)


def test_review_bundle_rejects_inconsistent_security_metadata() -> None:
    payload = load_review_bundle(EXAMPLES / "review-bundle-docs-answer.json").model_dump(mode="json")
    payload["security"]["allowed_reviewer_backends"] = ["local"]
    payload["security"]["reviewer_backend"] = "external-llm"
    payload["security"]["egress_decision"] = "approved_external"

    with pytest.raises(ValidationError, match="egress_decision"):
        ReviewBundle.model_validate(payload)


def test_complete_review_bundle_requires_replayable_evidence() -> None:
    payload = load_review_bundle(EXAMPLES / "review-bundle-docs-answer.json").model_dump(mode="json")
    payload["citations"] = []
    payload["source_refs"] = []
    payload["tool_proof"] = []
    payload["security"]["completeness"] = "complete"

    with pytest.raises(ValidationError, match="complete review bundles require source_refs"):
        ReviewBundle.model_validate(payload)


def test_write_review_bundle_uses_private_file_mode(tmp_path: Path) -> None:
    bundle = load_review_bundle(EXAMPLES / "review-bundle-docs-answer.json")
    output = write_review_bundle(tmp_path / "bundle.json", bundle)

    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_sanitize_review_bundle_payload_injects_security_metadata_and_redacts() -> None:
    payload = load_review_bundle(EXAMPLES / "review-bundle-docs-answer.json").model_dump(mode="json")
    payload.pop("security")
    payload["tool_proof"][0]["stdout_excerpt"] = "Authorization: Bearer cs_abcdefghijklmnopqrstuvwxyz123456"
    scope = ReviewArtifactScope(
        workspace_id=payload["scope"]["workspace_id"],
        project_id=payload["scope"]["project_id"],
        resource_ids=tuple(payload["scope"]["resource_ids"]),
        context_pack_key=payload["scope"]["context_pack_key"],
    )
    policy = ReviewArtifactPolicy(
        sensitivity=ArtifactSensitivity.INTERNAL,
        retention_days=7,
        allowed_reviewer_backends=("local",),
    )

    sanitized, report = sanitize_review_bundle_payload(
        payload,
        policy=policy,
        scope=scope,
        reviewer_backend="local",
        completeness=BundleCompleteness.REDACTED_PARTIAL,
    )
    bundle = ReviewBundle.model_validate(sanitized)

    stdout_excerpt = bundle.tool_proof[0].stdout_excerpt
    assert stdout_excerpt is not None
    assert "cs_abcdefghijklmnopqrstuvwxyz123456" not in stdout_excerpt
    assert report.counts["bearer_token"] == 1
    assert bundle.security.sensitivity == "internal"
    assert bundle.security.completeness == "redacted_partial"
    assert bundle.security.redaction_counts["bearer_token"] == 1


def test_sanitize_review_bundle_payload_denies_unapproved_reviewer_backend() -> None:
    payload = load_review_bundle(EXAMPLES / "review-bundle-docs-answer.json").model_dump(mode="json")
    payload.pop("security")
    scope = ReviewArtifactScope(
        workspace_id=payload["scope"]["workspace_id"],
        project_id=payload["scope"]["project_id"],
        resource_ids=tuple(payload["scope"]["resource_ids"]),
    )
    policy = ReviewArtifactPolicy(
        sensitivity=ArtifactSensitivity.PRIVATE,
        allowed_reviewer_backends=("local",),
    )

    with pytest.raises(ReviewArtifactSecurityError):
        sanitize_review_bundle_payload(
            payload,
            policy=policy,
            scope=scope,
            reviewer_backend="external-llm",
            completeness=BundleCompleteness.COMPLETE,
        )


def test_review_bundle_json_schema_contains_security_and_citation_contracts() -> None:
    schema = review_bundle_json_schema()
    assert schema["properties"]["schema_version"]["const"] == REVIEW_BUNDLE_SCHEMA_VERSION
    assert "security" in schema["properties"]
    assert "citations" in schema["properties"]
    assert "source_refs" in schema["properties"]
