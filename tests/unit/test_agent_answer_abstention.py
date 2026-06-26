from __future__ import annotations

from uuid import uuid4

from sourcebrief_api.main import _agent_unsupported_claim_terms, _synthesize_agent_answer
from sourcebrief_api.schemas import AgentContextCitation


def _citation(*, path: str, content_hash: str, score: float = 0.8) -> AgentContextCitation:
    return AgentContextCitation(
        resource_id=uuid4(),
        snapshot_id=uuid4(),
        chunk_id=uuid4(),
        path=path,
        ordinal=1,
        content_hash=content_hash,
        version="v1",
        version_kind="snapshot",
        score=score,
    )


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


def test_synthesized_answer_citations_follow_skipped_context_indices() -> None:
    answer = _synthesize_agent_answer(
        query="What does the implementation say?",
        context_parts=[
            "[1] resource=res path=empty.md\n| field | value |\n---",
            "[2] resource=res path=runbook.md\nRetry payment jobs with exponential backoff. Escalate after three failures.",
        ],
        citations=[
            _citation(path="empty.md", content_hash="hash-empty", score=0.3),
            _citation(path="runbook.md", content_hash="hash-runbook", score=0.9),
        ],
        resource_coverage=[],
        coverage_warnings=[],
    )

    assert "[2]" in answer.text
    assert "[1]" not in answer.text
    assert [citation["label"] for citation in answer.citations_used] == ["[2]"]
    assert answer.citations_used[0]["path"] == "runbook.md"
    assert answer.citations_used[0]["content_hash"] == "hash-runbook"


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
