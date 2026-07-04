# ruff: noqa: F405
from tests.unit.cli.support import *  # noqa: F401,F403


def test_cli_review_pr_bundle_from_fixture_and_run_report(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(tmp_path / "sourcebrief-config.json"))
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_PASSWORD", "local-password")
    fixture = REPO_ROOT / "docs" / "examples" / "self-improvement" / "pr-review-metadata-fixture.json"
    bundle_path = tmp_path / "pr-bundle.json"
    report_path = tmp_path / "pr-report.json"

    assert cli_main([
        "--json",
        "review",
        "pr-bundle",
        "--metadata-fixture",
        str(fixture),
        "--workspace",
        "github",
        "--project",
        "sourcebrief",
        "--bundle-out",
        str(bundle_path),
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "pr_review_bundle_written"
    assert payload["changed_paths"] == [
        "docs/STAGED_ADOPTION.md",
        "packages/shared/sourcebrief_shared/staged_adoption.py",
        "tests/unit/test_staged_adoption.py",
    ]
    assert FakeClient.instances[-1].calls == []
    bundle = load_review_bundle(bundle_path)
    assert bundle.scope.workspace_id == "github"
    assert bundle.scope.project_id == "sourcebrief"

    assert cli_main(["--json", "review", "run", "--bundle", str(bundle_path), "--report-out", str(report_path)]) == 0
    report_payload = json.loads(capsys.readouterr().out)
    assert report_payload["verdict"] == "PASS"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["subject_refs"][0]["ref_id"] == "pingchesu/sourcebrief#187"
    assert report["subject_refs"][0]["head_sha"] == "e174ea09b9edee97e1965c92b709d60f4f8d5160"


def test_cli_review_run_writes_report(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    bundle_path = REPO_ROOT / "docs" / "examples" / "self-improvement" / "golden" / "review-bundle-citation-mismatch.json"
    report_path = tmp_path / "review-report.json"

    assert cli_main(["--json", "review", "run", "--bundle", str(bundle_path), "--report-out", str(report_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "reviewed"
    assert payload["verdict"] == "BLOCK"
    assert payload["report_path"] == str(report_path)
    saved = json.loads(report_path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == "sourcebrief.review-report.v1"
    assert saved["reviewer_backend"] == "local"
    assert saved["findings"][0]["type"] == "citation_mismatch"


def test_cli_review_commands_do_not_login_with_env_password(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(tmp_path / "sourcebrief-config.json"))
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_EMAIL", "admin@sourcebrief.local")
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_PASSWORD", "local-password")
    bundle_path = REPO_ROOT / "docs" / "examples" / "self-improvement" / "golden" / "review-bundle-citation-mismatch.json"
    report_path = tmp_path / "review-report.json"

    assert cli_main(["--json", "review", "run", "--bundle", str(bundle_path), "--report-out", str(report_path)]) == 0
    assert FakeClient.instances[-1].calls == []
    capsys.readouterr()


def test_cli_review_run_incomplete_bundle_returns_actionable_error(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    bundle = load_review_bundle(REPO_ROOT / "docs" / "examples" / "self-improvement" / "review-bundle-docs-answer.json")
    data = bundle.model_dump(mode="json")
    data["security"]["completeness"] = "insufficient_evidence"
    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(json.dumps(data), encoding="utf-8")

    assert cli_main(["--json", "review", "run", "--bundle", str(incomplete)]) == 1
    err = capsys.readouterr().err
    assert "allow_incomplete" in err or "allow-incomplete" in err


def test_cli_review_propose_writes_regression_proposal(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    report_path = REPO_ROOT / "docs" / "examples" / "self-improvement" / "reviewer-report-example.json"
    proposal_path = tmp_path / "proposal.json"

    assert cli_main([
        "--json",
        "review",
        "propose",
        "--report",
        str(report_path),
        "--finding-id",
        "finding-learning-quickstart-gap",
        "--owner",
        "qa",
        "--proposal-out",
        str(proposal_path),
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "proposal_written"
    assert payload["proposal_path"] == str(proposal_path)
    saved = json.loads(proposal_path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == "sourcebrief.regression-proposal.v1"
    assert saved["source_finding_id"] == "finding-learning-quickstart-gap"
    assert saved["owner"] == "qa"


def test_cli_review_gate_writes_validation_result(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    proposal_path = REPO_ROOT / "docs" / "examples" / "self-improvement" / "regression-proposal-example.json"
    result_path = tmp_path / "gate.json"

    assert cli_main(["--json", "review", "gate", "--proposal", str(proposal_path), "--result-out", str(result_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "gate_evaluated"
    assert payload["decision"] == "accept"
    saved = json.loads(result_path.read_text(encoding="utf-8"))
    assert saved["schema_version"] == "sourcebrief.validation-gate-result.v1"
    assert saved["decision"] == "accept"


def test_cli_review_gate_invalid_schema_writes_rejected_result(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    bad = tmp_path / "bad-proposal.json"
    bad.write_text('{"proposal_id":"proposal-bad"}\n', encoding="utf-8")
    result_path = tmp_path / "gate.json"

    assert cli_main(["--json", "review", "gate", "--proposal", str(bad), "--result-out", str(result_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"] == "reject"
    saved = json.loads(result_path.read_text(encoding="utf-8"))
    assert saved["checks"]["schema_valid"] == "fail"


def test_cli_review_sleep_dry_run_mines_recurring_candidates(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    source_dir = tmp_path / "history"
    source_dir.mkdir()
    proposal = json.loads((REPO_ROOT / "docs" / "examples" / "self-improvement" / "regression-proposal-example.json").read_text(encoding="utf-8"))
    for suffix in ["a", "b"]:
        item = {**proposal, "proposal_id": f"proposal-{suffix}", "status": "proposed"}
        (source_dir / f"proposal-{suffix}.json").write_text(json.dumps(item), encoding="utf-8")
    out_dir = tmp_path / "sleep-out"
    summary_out = tmp_path / "sleep-summary.json"

    assert cli_main([
        "--json",
        "review",
        "sleep",
        "--dir",
        str(source_dir),
        "--out-dir",
        str(out_dir),
        "--summary-out",
        str(summary_out),
    ]) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema_version"] == "sourcebrief.sleep-replay-summary.v1"
    assert payload["dry_run"] is True
    assert len(payload["candidates"]) == 1
    assert payload["candidates"][0]["gate_decision"] == "accept"
    assert Path(payload["candidates"][0]["proposal_path"]).exists()
    assert summary_out.exists()


def test_cli_review_mvp_smoke_runs_full_local_path(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    out_dir = tmp_path / "mvp-smoke"

    assert cli_main(["--json", "review", "mvp-smoke", "--out-dir", str(out_dir)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["gate_decision"] == "accept"
    assert payload["no_silent_mutation"] is True
    assert Path(payload["bundle_path"]).exists()
    assert Path(payload["report_path"]).exists()
    assert Path(payload["proposal_path"]).exists()
    assert Path(payload["gate_result_path"]).exists()
    assert Path(payload["stage_receipt_path"]).exists()
    assert Path(payload["history_summary_path"]).exists()
    assert payload["history_metrics"]["record_count"] >= 5


def test_cli_review_history_list_and_show_are_redacted(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    history_dir = tmp_path / "history"
    history_dir.mkdir()
    proposal = json.loads((REPO_ROOT / "docs" / "examples" / "self-improvement" / "regression-proposal-example.json").read_text(encoding="utf-8"))
    proposal["rationale"] = "token=abcdefghijklmnopqrstuvwxyz12345 should be redacted"
    (history_dir / "proposal.json").write_text(json.dumps(proposal), encoding="utf-8")

    assert cli_main(["--json", "review", "history", "list", "--dir", str(history_dir)]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["metrics"]["proposal_count"] == 1
    assert listed["records"][0]["artifact_id"] == "proposal-finding-learning-quickstart-gap"

    assert cli_main([
        "--json",
        "review",
        "history",
        "show",
        "proposal-finding-learning-quickstart-gap",
        "--dir",
        str(history_dir),
    ]) == 0
    shown_text = capsys.readouterr().out
    assert "abcdefghijklmnopqrstuvwxyz12345" not in shown_text
    shown = json.loads(shown_text)
    assert shown["record"]["kind"] == "proposal"
    assert shown["redaction_counts"]


def test_cli_review_stage_writes_receipt_patch_and_does_not_login(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(tmp_path / "sourcebrief-config.json"))
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_EMAIL", "admin@sourcebrief.local")
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_PASSWORD", "local-password")
    proposal_path = REPO_ROOT / "docs" / "examples" / "self-improvement" / "regression-proposal-example.json"
    gate_path = REPO_ROOT / "docs" / "examples" / "self-improvement" / "validation-gate-result-example.json"
    out_dir = tmp_path / "staged"

    assert cli_main([
        "--json",
        "review",
        "stage",
        "--proposal",
        str(proposal_path),
        "--gate-result",
        str(gate_path),
        "--out-dir",
        str(out_dir),
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "staged"
    assert payload["apply_command"].startswith("git apply ")
    assert payload["rollback_command"].startswith("git apply -R ")
    assert Path(payload["receipt_path"]).exists()
    assert Path(payload["patch_path"]).exists()
    assert FakeClient.instances[-1].calls == []


def test_cli_review_stage_rejects_rejected_gate(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    proposal_path = REPO_ROOT / "docs" / "examples" / "self-improvement" / "regression-proposal-example.json"
    gate_path = tmp_path / "gate-rejected.json"
    gate = json.loads((REPO_ROOT / "docs" / "examples" / "self-improvement" / "validation-gate-result-example.json").read_text(encoding="utf-8"))
    gate["decision"] = "reject"
    gate_path.write_text(json.dumps(gate), encoding="utf-8")

    assert cli_main([
        "review",
        "stage",
        "--proposal",
        str(proposal_path),
        "--gate-result",
        str(gate_path),
        "--out-dir",
        str(tmp_path / "staged"),
    ]) == 1
    assert "only accepted gate results" in capsys.readouterr().err
