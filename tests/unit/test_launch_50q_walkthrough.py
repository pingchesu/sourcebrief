from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "launch_50q_walkthrough.py"
QUESTIONS = ROOT / "examples" / "sourcebrief-launch-50q" / "questions.json"


def load_module():
    spec = importlib.util.spec_from_file_location("launch_50q_walkthrough_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_launch_50q_question_bank_has_exactly_50_sanitized_questions() -> None:
    bank = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    assert bank["schema_version"] == "sourcebrief.launch-50q-question-bank.v1"
    assert len(bank["questions"]) == 50
    ids = [question["id"] for question in bank["questions"]]
    assert len(set(ids)) == 50
    assert all(question["query"] for question in bank["questions"])
    negative_controls = [
        question for question in bank["questions"] if question.get("expected_result") == "expected_unanswerable"
    ]
    assert negative_controls
    assert all(not question.get("expected_terms") for question in negative_controls)
    serialized = json.dumps(bank)
    assert "cs_" not in serialized


def test_launch_50q_followup_terms_have_launch_doc_anchors() -> None:
    """Guard the answer-quality follow-ups opened from the screenshot-backed run."""
    guide = (ROOT / "docs" / "GUIDE.md").read_text(encoding="utf-8")
    runtime_usage = (ROOT / "docs" / "AGENT_RUNTIME_USAGE.md").read_text(encoding="utf-8")
    runtime_plan = (ROOT / "docs" / "RUNTIME_INSTALL_PLAN.md").read_text(encoding="utf-8")

    assert "sourcebrief resource add-repo" in guide
    assert "--max-files" in guide
    assert "full source corpus" in runtime_usage
    assert "SKILL.md" in runtime_usage
    assert "redact token values" in runtime_usage
    assert "--redact-token" in runtime_plan
    assert "plaintext bearer tokens" in runtime_plan


def test_launch_50q_defaults_follow_makefile_ports(tmp_path: Path, monkeypatch) -> None:
    module = load_module()
    env_file = tmp_path / ".env"
    env_file.write_text("SOURCEBRIEF_API_PORT=18123\nSOURCEBRIEF_WEB_PORT=13123\n", encoding="utf-8")
    monkeypatch.setenv("SOURCEBRIEF_API_URL", "http://localhost:18999")
    monkeypatch.delenv("SOURCEBRIEF_WEB_URL", raising=False)
    monkeypatch.delenv("CONTEXTSMITH_WEB_URL", raising=False)
    monkeypatch.delenv("WEB_URL", raising=False)
    monkeypatch.delenv("SOURCEBRIEF_WEB_PORT", raising=False)
    monkeypatch.delenv("CONTEXTSMITH_WEB_PORT", raising=False)

    assert module.configured_url("api", module.load_env_file(env_file)) == "http://localhost:18999"
    assert module.configured_url("web", module.load_env_file(env_file)) == "http://localhost:13123"
    assert module.default_artifact_dir(123).name == "sourcebrief-launch-50q-123"


def test_launch_50q_expected_unanswerable_allows_unsupported_citations(monkeypatch) -> None:
    module = load_module()
    ctx = module.WalkthroughContext(
        api_url="http://api",
        web_url="http://web",
        headers={},
        session_token=None,
        auth_mode="test",
        workspace_id="ws",
        workspace_name="Workspace",
        project_id="proj",
        project_name="Project",
        resource_id="res",
        resource_name="Resource",
        index_run={},
    )

    def fake_request(*args, **kwargs):
        return {
            "answer": {"outcome": "unsupported_by_sources"},
            "citations": [{"path": "docs/STATUS.md"}],
            "context": "public SaaS is not ready",
        }

    monkeypatch.setattr(module, "request", fake_request)
    result = module.evaluate_question(
        "http://api",
        ctx,
        {
            "id": "negative",
            "query": "What Helm command deploys public SaaS?",
            "expected_result": "expected_unanswerable",
            "expected_terms": [],
        },
    )

    assert result["mechanical_status"] == "pass"
    assert result["citation_count"] == 1
    assert result["answer_outcome"] == "unsupported_by_sources"


def test_launch_50q_expected_unanswerable_blocks_answerable_outcomes(monkeypatch) -> None:
    module = load_module()
    ctx = module.WalkthroughContext(
        api_url="http://api",
        web_url="http://web",
        headers={},
        session_token=None,
        auth_mode="test",
        workspace_id="ws",
        workspace_name="Workspace",
        project_id="proj",
        project_name="Project",
        resource_id="res",
        resource_name="Resource",
        index_run={},
    )

    def fake_request(*args, **kwargs):
        return {"answer": {"outcome": "answered"}, "citations": [{"path": "deploy.md"}], "context": "helm install"}

    monkeypatch.setattr(module, "request", fake_request)
    result = module.evaluate_question(
        "http://api",
        ctx,
        {
            "id": "negative",
            "query": "What Helm command deploys public SaaS?",
            "expected_result": "expected_unanswerable",
            "expected_terms": [],
        },
    )

    assert result["mechanical_status"] == "fail"
    assert result["failures"] == ["negative_control_answered_too_strongly"]


def test_launch_50q_verdict_blocks_failed_questions_and_missing_negative_control() -> None:
    module = load_module()
    verdict, reasons = module.launch_verdict(
        index_status="succeeded",
        results=[{"id": "q1", "mechanical_status": "fail"}],
        quality_warnings=[],
        scenario_results={"mcp_context_is_error": False, "grep_code_is_error": False, "cli_search_exit_code": 0},
        negative_control_count=0,
    )

    assert verdict == "BLOCK"
    assert "question_failures:q1" in reasons
    assert "missing_expected_unanswerable_negative_control" in reasons


def test_launch_50q_verdict_risk_for_quality_warnings_only() -> None:
    module = load_module()
    verdict, reasons = module.launch_verdict(
        index_status="succeeded",
        results=[{"id": "q1", "mechanical_status": "pass"}],
        quality_warnings=[{"id": "q1"}],
        scenario_results={"mcp_context_is_error": False, "grep_code_is_error": False, "cli_search_exit_code": 0},
        negative_control_count=1,
    )

    assert verdict == "RISK"
    assert reasons == ["answer_quality_warnings_present"]


def test_launch_50q_redaction_strips_tokens_passwords_and_ids() -> None:
    module = load_module()
    redacted = module.redact(
        {
            "session_token": "cs_abcdefghijklmnopqrstuvwxyz",
            "nested": ["Bearer abcdefghijklmnopqrstuvwxyz", "resource 123e4567-e89b-12d3-a456-426614174000"],
            "password": "secret",
            "safe": "Workspace name",
        }
    )
    assert "session_token" not in redacted
    assert "password" not in redacted
    assert redacted["nested"][0] == "<redacted-token>"
    assert redacted["nested"][1] == "resource <id>"
    assert redacted["safe"] == "Workspace name"


def test_launch_50q_report_html_contains_summary_without_raw_ids(tmp_path: Path) -> None:
    module = load_module()
    report = {
        "setup": {"workspace_name": "50Q Launch", "project_name": "Demo", "resource_name": "Repo"},
        "summary": {"verdict": "RISK", "question_count": 1, "passed": 0, "failed": 1},
        "questions": [{"id": "q1", "category": "ops", "mechanical_status": "fail", "citation_count": 0, "failures": ["missing_citation"]}],
    }
    output = tmp_path / "report.html"
    module.write_report_html(report, output)
    html = output.read_text(encoding="utf-8")
    assert "SourceBrief 50Q Launch Walkthrough" in html
    assert "missing_citation" in html
    assert "123e4567" not in html


def test_launch_50q_public_doc_links_operations_and_screenshots() -> None:
    doc = (ROOT / "docs" / "evaluations" / "sourcebrief-launch-50q-20260627.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    proof = (ROOT / "docs" / "PROOF_ARTIFACTS.md").read_text(encoding="utf-8")

    assert "## Actual operation walkthrough" in doc
    assert "## What each screenshot proves" in doc
    assert "scripts/launch_50q_walkthrough.py" in doc
    assert "examples/sourcebrief-launch-50q/questions.json" in doc
    assert "MCP `tools/list`" in doc
    assert "CLI `sourcebrief --json search`" in doc
    assert doc.count("../assets/screenshots/launch-50q/") == 7
    for name in [
        "01-login.png",
        "02-dashboard.png",
        "03-selection-settings.png",
        "04-import-sources.png",
        "05-workbench-citations.png",
        "06-agent-profile.png",
        "07-eval-report.png",
    ]:
        assert (ROOT / "docs" / "assets" / "screenshots" / "launch-50q" / name).exists()
        assert name in doc
    assert "50Q launch proof with screenshots" in readme
    assert "screenshot-by-screenshot proof table" in proof
