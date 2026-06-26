from __future__ import annotations

from sourcebrief_api.main import _agent_unsupported_claim_terms


def test_high_assurance_negative_control_claim_families_abstain_when_unsupported() -> None:
    near_miss_context = ["[1] resource=res path=README.md\nThis repo documents agent workflow setup and ordinary security review notes."]
    cases = [
        ("Does Superpowers include a signed SOC 2 Type II audit report and name the auditor?", "SOC 2 audit report/auditor"),
        ("Does ECC guarantee HIPAA compliance and list a covered-entity deployment checklist?", "HIPAA compliance/deployment checklist"),
        ("Does Matt Pocock's skills repo provide a hosted cloud service with an SLA and uptime dashboard?", "hosted cloud service SLA/uptime dashboard"),
        ("Does gstack document FedRAMP authorization and the sponsoring agency?", "FedRAMP authorization/sponsoring agency"),
        ("Does DeerFlow promise production Kubernetes multi-tenant isolation with a published threat model?", "production Kubernetes multi-tenant isolation/threat model"),
    ]

    for query, expected in cases:
        assert expected in _agent_unsupported_claim_terms(query, near_miss_context)


def test_high_assurance_claim_family_allows_direct_supporting_context() -> None:
    supported_context = [
        "[1] resource=res path=compliance.md\nThe project has a SOC 2 Type II audit report. The auditor is Example CPA."
    ]

    assert _agent_unsupported_claim_terms(
        "Does this project include a signed SOC 2 Type II audit report and name the auditor?",
        supported_context,
    ) == []


def test_high_assurance_claim_family_rejects_near_miss_denial() -> None:
    near_miss_context = [
        "[1] resource=res path=README.md\nSOC 2 audit readiness is not documented here; no audit report or auditor is named."
    ]

    assert _agent_unsupported_claim_terms(
        "Does this project include a signed SOC 2 Type II audit report and name the auditor?",
        near_miss_context,
    ) == ["SOC 2 audit report/auditor"]


def test_high_assurance_claim_family_rejects_keyword_near_miss_without_artifact() -> None:
    near_miss_context = [
        "[1] resource=res path=security.md\nSOC 2 controls include audit logging for admin actions and access review reminders."
    ]

    assert _agent_unsupported_claim_terms(
        "Does this project include a signed SOC 2 Type II audit report and name the auditor?",
        near_miss_context,
    ) == ["SOC 2 audit report/auditor"]
