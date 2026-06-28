import pytest

from sourcebrief_shared.self_improvement_security import (
    ArtifactSensitivity,
    BundleCompleteness,
    EgressDecision,
    ReviewArtifactPolicy,
    ReviewArtifactScope,
    ReviewArtifactSecurityError,
    build_security_metadata,
    redact_review_artifact,
    redact_text,
)


def test_redact_text_removes_tokens_and_local_paths() -> None:
    text = (
        "Authorization: Bearer cs_abcdefghijklmnopqrstuvwxyz123456 "
        "password=supersecretvalue12345 "
        "path=/home/alice/private/sourcebrief/.env "
        "openai=sk-abcdefghijklmnopqrstuvwxyz123456"
    )

    redacted, report = redact_text(text)

    assert "cs_abcdefghijklmnopqrstuvwxyz123456" not in redacted
    assert "supersecretvalue12345" not in redacted
    assert "/home/alice/private" not in redacted
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" not in redacted
    assert report.counts["bearer_token"] == 1
    assert report.counts["generic_secret_assignment"] >= 1
    assert report.counts["local_path"] == 1
    assert report.counts["openai_key"] == 1


def test_redact_review_artifact_removes_secret_keys_recursively() -> None:
    payload = {
        "task": "review this answer",
        "headers": {"Authorization": "Bearer cs_abcdefghijklmnopqrstuvwxyz123456"},
        "tool_logs": ["read /Users/bob/src/private-repo/.env"],
        "nested": {"api_key": "should-not-survive-12345"},
    }

    redacted, report = redact_review_artifact(payload)

    assert redacted["headers"]["[REDACTED:secret_key]"] == "[REDACTED:secret_value]"
    assert redacted["nested"]["[REDACTED:secret_key]"] == "[REDACTED:secret_value]"
    assert "/Users/bob" not in redacted["tool_logs"][0]
    assert report.counts["secret_key"] == 2
    assert report.counts["local_path"] == 1


def test_review_artifact_scope_preserves_workspace_project_and_resource_boundary() -> None:
    scope = ReviewArtifactScope(
        workspace_id="workspace-a",
        project_id="project-a",
        resource_ids=("resource-1", "resource-2"),
    )

    scope.require_allows(
        workspace_id="workspace-a",
        project_id="project-a",
        resource_ids=["resource-1"],
    )
    with pytest.raises(ReviewArtifactSecurityError):
        scope.require_allows(
            workspace_id="workspace-a",
            project_id="project-a",
            resource_ids=["resource-3"],
        )
    with pytest.raises(ReviewArtifactSecurityError):
        scope.require_allows(
            workspace_id="workspace-b",
            project_id="project-a",
            resource_ids=["resource-1"],
        )
    with pytest.raises(ReviewArtifactSecurityError):
        scope.require_allows(
            workspace_id="workspace-a",
            project_id="project-a",
            resource_ids=[],
        )


def test_external_reviewer_backends_are_denied_without_opt_in() -> None:
    policy = ReviewArtifactPolicy(
        sensitivity=ArtifactSensitivity.INTERNAL,
        allowed_reviewer_backends=("local", "external-llm"),
        external_reviewer_opt_in=False,
    )

    assert policy.egress_for_backend("external-llm") == EgressDecision.DENIED
    assert policy.egress_for_backend("internal") == EgressDecision.DENIED


def test_redaction_scrubs_secret_keys_and_short_assignments() -> None:
    payload = {
        "api_key_abc123": "value",
        "body": "password=hunter2 api_key=abc123 token=shorttok",
        "token=abcdefghijklmnopqrstuvwxyz12345": "bad",
    }

    redacted, report = redact_review_artifact(payload)
    serialized = str(redacted)
    assert "api_key_abc123" not in serialized
    assert "hunter2" not in serialized
    assert "abc123" not in serialized
    assert "shorttok" not in serialized
    assert "abcdefghijklmnopqrstuvwxyz12345" not in serialized
    assert report.counts["secret_key"] >= 2
    assert report.counts["generic_secret_assignment"] >= 3


def test_review_artifact_policy_denies_unapproved_external_egress() -> None:
    policy = ReviewArtifactPolicy(
        sensitivity=ArtifactSensitivity.PRIVATE,
        allowed_reviewer_backends=("local", "external-llm"),
        external_reviewer_opt_in=False,
    )

    assert policy.egress_for_backend("local") == EgressDecision.LOCAL_ONLY
    assert policy.egress_for_backend("external-llm") == EgressDecision.DENIED
    with pytest.raises(ReviewArtifactSecurityError):
        policy.require_backend_allowed("external-llm")


def test_secret_artifacts_cannot_enable_external_reviewer() -> None:
    with pytest.raises(ReviewArtifactSecurityError):
        ReviewArtifactPolicy(
            sensitivity=ArtifactSensitivity.SECRET,
            allowed_reviewer_backends=("external-llm",),
            external_reviewer_opt_in=True,
        )


def test_security_metadata_records_policy_scope_redaction_and_completeness() -> None:
    payload = {"output": "token=supersecretvalue12345"}
    redacted, report = redact_review_artifact(payload)
    policy = ReviewArtifactPolicy(
        sensitivity=ArtifactSensitivity.INTERNAL,
        retention_days=14,
        allowed_reviewer_backends=("local",),
    )
    scope = ReviewArtifactScope(
        workspace_id="workspace-a",
        project_id="project-a",
        resource_ids=("resource-1",),
        context_pack_key="repo-runtime",
    )

    metadata = build_security_metadata(
        policy=policy,
        scope=scope,
        reviewer_backend="local",
        completeness=BundleCompleteness.REDACTED_PARTIAL,
        redaction_report=report,
    )

    assert redacted["output"] == "token=[REDACTED:generic_secret_assignment]"
    assert metadata["sensitivity"] == "internal"
    assert metadata["retention_days"] == 14
    assert metadata["egress_decision"] == "local_only"
    assert metadata["completeness"] == "redacted_partial"
    assert metadata["redaction_counts"]["generic_secret_assignment"] == 1
    assert metadata["scope"]["resource_ids"] == ["resource-1"]
