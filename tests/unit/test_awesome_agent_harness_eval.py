from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


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
    assert report["aggregate"]["partial_corpus_risk_count"] == 0


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


def test_grade_report_counts_partial_corpus_risk_separately() -> None:
    module = load_eval_module()
    manifest = manifest_with_question(
        {
            "id": "limited-answer",
            "query": "What does the runbook say?",
            "category": "runbook",
            "customer_job": "understand runbook",
            "difficulty": "medium",
            "demo_type": "human-answer-demo",
            "target_repo": "demo",
            "target_repos": ["demo"],
            "expected_result": "pass",
            "min_citations": 1,
            "import_type": "limited",
        }
    )
    report = module.build_grade_report(
        manifest,
        [
            {
                "results": [
                    {"id": "limited-answer", "citation_count": 1, "context_chars": 240, "failure_reasons": []},
                    negative_eval_response(),
                ]
            }
        ],
        {
            "limited-answer": {
                "answer": {"text": "Based on cited context: retry with exponential backoff. [1]"},
                "citations": [{"path": "runbook.md"}],
                "context": "x" * 240,
            },
            "negative-control": negative_context(),
        },
    )

    limited_result = next(result for result in report["results"] if result["id"] == "limited-answer")
    assert limited_result["checks"]["partial_corpus_caveat"] == "partial"
    assert limited_result["checks"]["retrieval_quality"] is True
    assert report["aggregate"]["partial_corpus_risk_count"] == 1

def test_authenticate_fails_before_mutation_with_actionable_auth_guidance(tmp_path, monkeypatch) -> None:
    module = load_eval_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    for name in (
        "SOURCEBRIEF_TOKEN",
        "CONTEXTSMITH_TOKEN",
        "SOURCEBRIEF_ADMIN_EMAIL",
        "CONTEXTSMITH_ADMIN_EMAIL",
        "SOURCEBRIEF_ADMIN_PASSWORD",
        "CONTEXTSMITH_ADMIN_PASSWORD",
    ):
        monkeypatch.delenv(name, raising=False)

    class RejectingClient:
        email = "demo@example.com"
        token = None

        def request(self, method: str, path: str, *, body=None, expected=None):
            assert (method, path) == ("GET", "/auth/me")
            raise RuntimeError('GET /auth/me failed with HTTP 401: {"detail":"authentication required"}')

    with pytest.raises(RuntimeError) as excinfo:
        module.authenticate(RejectingClient(), tmp_path / "out")

    message = str(excinfo.value)
    assert "Authentication preflight failed before creating eval resources" in message
    assert "SOURCEBRIEF_ADMIN_EMAIL" in message
    assert "SOURCEBRIEF_ADMIN_PASSWORD" in message
    assert "SOURCEBRIEF_TOKEN" in message
    auth_mode = module.json.loads((tmp_path / "out" / "auth-mode.json").read_text(encoding="utf-8"))
    assert auth_mode["mode"] == "unsupported/missing-auth"
    assert auth_mode["usable"] is False
    assert auth_mode["attempted"] == ["dev-header"]
    assert "authentication required" in auth_mode["reason"]


def test_capture_run_environment_records_raw_generation_source_state(tmp_path, monkeypatch) -> None:
    module = load_eval_module()
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "load_dotenv", lambda _path: {})
    monkeypatch.setattr(
        module,
        "run_local_command",
        lambda command, timeout=60: {"command": command, "exit_code": 0, "stdout": "ok\n", "stderr": ""},
    )
    monkeypatch.setattr(module, "http_check", lambda url, timeout=30: {"url": url, "ok": True})
    source_state = {
        "git_head": "head-sha",
        "git_branch": "main",
        "repo_dirty": False,
        "dirty_paths": [],
        "script_commit": "script-sha",
        "question_bank_commit": "questions-sha",
    }

    environment = module.capture_run_environment(
        tmp_path / "out",
        api_url="http://api.local",
        web_url=None,
        argv=["runner", "--output-dir", "out"],
        source_state=source_state,
    )

    assert environment["raw_generation_command"]["argv"] == ["runner", "--output-dir", "out"]
    assert environment["validation_or_reuse_command"] is None
    assert environment["script_commit"] == "script-sha"
    assert environment["question_bank_commit"] == "questions-sha"
    assert environment["repo_dirty"] is False
    persisted = module.json.loads((tmp_path / "out" / "run-environment.json").read_text(encoding="utf-8"))
    assert persisted["source_state"]["script_commit"] == "script-sha"


def test_reuse_existing_evidence_preserves_raw_command_and_records_validation_command(tmp_path, monkeypatch) -> None:
    module = load_eval_module()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
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
        [{"results": [{"id": "answered", "citation_count": 1, "context_chars": 240, "failure_reasons": []}, negative_eval_response()]}],
        {
            "answered": {"answer": {"text": "Based on cited context: retry. [1]"}, "citations": [{"path": "runbook.md"}], "context": "x" * 240},
            "negative-control": negative_context(),
        },
    )
    raw_command = {"argv": ["runner", "--output-dir", str(out_dir)], "exit_code": 0}
    raw_source_state = {
        "script_commit": "raw-script-sha",
        "question_bank_commit": "raw-questions-sha",
        "repo_dirty": False,
        "dirty_paths": [],
    }
    (out_dir / "eval-manifest.json").write_text(module.json.dumps(manifest), encoding="utf-8")
    (out_dir / "eval-report.json").write_text(module.json.dumps(report), encoding="utf-8")
    (out_dir / "run-environment.json").write_text(
        module.json.dumps({"raw_generation_command": raw_command, "source_state": raw_source_state}),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "load_dotenv", lambda _path: {})
    monkeypatch.setattr(
        module,
        "run_local_command",
        lambda command, timeout=60: {"command": command, "exit_code": 0, "stdout": "ok\n", "stderr": ""},
    )
    monkeypatch.setattr(module, "http_check", lambda url, timeout=30: {"url": url, "ok": True})

    reused_manifest, reused_report, previous_raw_command, previous_raw_source_state = module.validate_existing_evidence(out_dir)
    environment = module.capture_run_environment(
        out_dir,
        api_url="http://api.local",
        web_url="http://web.local",
        argv=["runner", "--reuse-existing-evidence", "--output-dir", str(out_dir)],
        source_state=previous_raw_source_state,
        raw_generation=False,
        previous_raw_generation_command=previous_raw_command,
        validation_source_state={"script_commit": "validation-script-sha", "question_bank_commit": "validation-questions-sha", "repo_dirty": True},
    )

    assert reused_manifest["run"]["sourcebrief_commit"] == manifest["run"]["sourcebrief_commit"]
    assert reused_report["aggregate"]["verdict"] == report["aggregate"]["verdict"]
    assert environment["raw_generation_command"] == raw_command
    assert environment["source_state"] == raw_source_state
    assert environment["script_commit"] == "raw-script-sha"
    assert environment["question_bank_commit"] == "raw-questions-sha"
    assert environment["repo_dirty"] is False
    assert environment["validation_source_state"]["script_commit"] == "validation-script-sha"
    assert environment["validation_source_state"]["repo_dirty"] is True
    assert environment["validation_or_reuse_command"]["argv"] == ["runner", "--reuse-existing-evidence", "--output-dir", str(out_dir)]


def test_reuse_existing_evidence_without_raw_provenance_fails_cleanly(tmp_path, monkeypatch, capsys) -> None:
    module = load_eval_module()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
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
        [{"results": [{"id": "answered", "citation_count": 1, "context_chars": 240, "failure_reasons": []}, negative_eval_response()]}],
        {
            "answered": {"answer": {"text": "Based on cited context: retry. [1]"}, "citations": [{"path": "runbook.md"}], "context": "x" * 240},
            "negative-control": negative_context(),
        },
    )
    (out_dir / "eval-manifest.json").write_text(module.json.dumps(manifest), encoding="utf-8")
    (out_dir / "eval-report.json").write_text(module.json.dumps(report), encoding="utf-8")
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "evidence_source_state", lambda: {"script_commit": "validation-script-sha", "repo_dirty": True})
    monkeypatch.setattr(
        module.sys,
        "argv",
        ["runner", "--reuse-existing-evidence", "--output-dir", str(out_dir), "--api-url", "http://api.local"],
    )

    assert module.main() == 2
    assert "cannot safely infer raw-generation provenance" in capsys.readouterr().err
    assert not (out_dir / "run-environment.json").exists()


def test_reuse_existing_evidence_rejects_malformed_raw_source_state(tmp_path, monkeypatch, capsys) -> None:
    module = load_eval_module()
    out_dir = tmp_path / "out"
    out_dir.mkdir()
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
        [{"results": [{"id": "answered", "citation_count": 1, "context_chars": 240, "failure_reasons": []}, negative_eval_response()]}],
        {
            "answered": {"answer": {"text": "Based on cited context: retry. [1]"}, "citations": [{"path": "runbook.md"}], "context": "x" * 240},
            "negative-control": negative_context(),
        },
    )
    (out_dir / "eval-manifest.json").write_text(module.json.dumps(manifest), encoding="utf-8")
    (out_dir / "eval-report.json").write_text(module.json.dumps(report), encoding="utf-8")
    (out_dir / "run-environment.json").write_text(
        module.json.dumps(
            {
                "raw_generation_command": {"argv": ["runner"], "exit_code": 0},
                "source_state": {"script_commit": "", "question_bank_commit": "raw-questions-sha", "repo_dirty": "false"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "evidence_source_state", lambda: {"script_commit": "validation-script-sha", "repo_dirty": False})
    monkeypatch.setattr(
        module.sys,
        "argv",
        ["runner", "--reuse-existing-evidence", "--output-dir", str(out_dir), "--api-url", "http://api.local"],
    )

    assert module.main() == 2
    assert "cannot safely infer raw-generation provenance" in capsys.readouterr().err


def test_dirty_evidence_guard_requires_explicit_override(monkeypatch) -> None:
    module = load_eval_module()
    monkeypatch.setattr(module, "evidence_source_state", lambda: {"repo_dirty": True, "dirty_paths": [" M scripts/run_awesome_agent_harness_eval.py"]})

    with pytest.raises(RuntimeError, match="--allow-dirty-evidence"):
        module.assert_clean_evidence_source(allow_dirty=False)

    assert module.assert_clean_evidence_source(allow_dirty=True)["repo_dirty"] is True
