from __future__ import annotations

import importlib.util
from pathlib import Path


def load_eval_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "run_awesome_agent_harness_eval.py"
    spec = importlib.util.spec_from_file_location("run_awesome_agent_harness_eval", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def manifest_with_question(question: dict) -> dict:
    negative = {
        "id": "negative-control",
        "query": "Does this repo have a SOC 2 auditor?",
        "category": "negative-control",
        "customer_job": "avoid unsupported compliance claims",
        "difficulty": "medium",
        "demo_type": "abstention",
        "target_repo": "demo",
        "target_repos": ["demo"],
        "import_type": "full",
        "expected_result": "expected_unanswerable",
        "bad_answer_criteria": ["Names an auditor without evidence"],
        "min_citations": 0,
    }
    return {
        "schema_version": "sourcebrief.eval-manifest.v1",
        "name": "unit eval",
        "description": "unit eval manifest",
        "thresholds": {},
        "run": {
            "sourcebrief_commit": "abc123",
            "api_url": "http://localhost:18000",
            "workspace_id": "ws",
            "project_id": "proj",
            "resources": [{"key": "demo", "target_repo": "demo", "import_type": "full", "resource_ids": ["res"]}],
        },
        "questions": [question, negative],
    }


def negative_context(*, citation_count: int = 0) -> dict:
    citations = [{"path": "near-miss.md"}] if citation_count else []
    return {
        "answer": {
            "outcome": "unsupported_by_sources",
            "text": "Insufficient evidence: the cited SourceBrief context does not support the requested claim.",
            "citations_used": citations,
            "confidence": "none",
            "abstention_reason": "Retrieved evidence does not directly support the claim.",
        },
        "citations": citations,
        "context": "near-miss context" if citation_count else "",
    }


def negative_eval_response(*, citation_count: int = 0) -> dict:
    return {"id": "negative-control", "citation_count": citation_count, "context_chars": 80 if citation_count else 0, "failure_reasons": []}


def test_grade_report_accepts_structured_synthesized_answer() -> None:
    module = load_eval_module()
    manifest = manifest_with_question(
        {
            "id": "answered",
            "query": "What does the runbook say?",
            "category": "runbook",
            "customer_job": "understand runbook",
            "difficulty": "medium",
            "demo_type": "human-answer-demo",
            "target_repo": "demo",
            "target_repos": ["demo"],
            "expected_result": "pass",
            "min_citations": 1,
            "import_type": "full",
            "expected_evidence_type": "runbook",
            "bad_answer_criteria": ["No citation"],
        }
    )
    report = module.build_grade_report(
        manifest,
        [
            {
                "results": [
                    {
                        "id": "answered",
                        "citation_count": 1,
                        "context_chars": 240,
                        "failure_reasons": [],
                    },
                    negative_eval_response(),
                ]
            }
        ],
        {
            "answered": {
                "answer": {
                    "text": "Based on cited context: retry with exponential backoff. [1]",
                    "citations_used": [{"label": "[1]", "path": "runbook.md"}],
                },
                "citations": [{"path": "runbook.md"}],
                "context": "x" * 240,
            },
            "negative-control": negative_context(),
        },
    )

    assert report["results"][0]["checks"]["human_answer_demo"] is True
    assert report["results"][1]["checks"]["abstained_correctly"] is True
    assert report["grade_counts"] == {"PASS": 2, "PARTIAL": 0, "FAIL": 0}
    assert report["aggregate"]["human_answer_demo_pass_rate"] == 1.0
    assert report["aggregate"]["abstention_pass_rate"] == 1.0


def test_grade_report_separates_failed_negative_abstention() -> None:
    module = load_eval_module()
    manifest = manifest_with_question(
        {
            "id": "answered",
            "query": "What does the runbook say?",
            "category": "runbook",
            "customer_job": "understand runbook",
            "difficulty": "medium",
            "demo_type": "human-answer-demo",
            "target_repo": "demo",
            "target_repos": ["demo"],
            "expected_result": "pass",
            "min_citations": 1,
            "import_type": "full",
        }
    )
    report = module.build_grade_report(
        manifest,
        [
            {
                "results": [
                    {"id": "answered", "citation_count": 1, "context_chars": 240, "failure_reasons": []},
                    negative_eval_response(citation_count=1),
                ]
            }
        ],
        {
            "answered": {
                "answer": {"text": "Based on cited context: retry with exponential backoff. [1]"},
                "citations": [{"path": "runbook.md"}],
                "context": "x" * 240,
            },
            "negative-control": {"citations": [{"path": "near-miss.md"}], "context": "near-miss context"},
        },
    )

    negative_result = next(result for result in report["results"] if result["id"] == "negative-control")
    assert negative_result["checks"]["abstained_correctly"] is False
    assert negative_result["grade"] == "FAIL"
    assert report["aggregate"]["abstention_pass_rate"] == 0.0


def test_grade_report_keeps_context_only_response_partial() -> None:
    module = load_eval_module()
    manifest = manifest_with_question(
        {
            "id": "context-only",
            "query": "What does the runbook say?",
            "category": "runbook",
            "customer_job": "understand runbook",
            "difficulty": "medium",
            "demo_type": "human-answer-demo",
            "target_repo": "demo",
            "target_repos": ["demo"],
            "expected_result": "pass",
            "min_citations": 1,
            "import_type": "full",
        }
    )
    report = module.build_grade_report(
        manifest,
        [
            {
                "results": [
                    {"id": "context-only", "citation_count": 1, "context_chars": 240, "failure_reasons": []},
                    negative_eval_response(),
                ]
            }
        ],
        {"context-only": {"citations": [{"path": "runbook.md"}], "context": "x" * 240}, "negative-control": negative_context()},
    )

    assert report["results"][0]["checks"]["human_answer_demo"] == "partial"
    assert "not a synthesized human answer" in report["results"][0]["quality_notes"][0]
