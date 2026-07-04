# ruff: noqa: F405
from tests.unit.cli.support import *  # noqa: F401,F403


def test_quickstart_demo_can_write_review_bundle(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(tmp_path / "sourcebrief-config.json"))
    bundle_path = tmp_path / "quickstart-bundle.json"

    assert cli_main(["--json", "quickstart-demo", "--slug", "sourcebrief-demo-test", "--review-bundle-out", str(bundle_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["review_bundle"]["path"] == str(bundle_path)

    bundle = load_review_bundle(bundle_path)
    assert bundle.kind == "cli_demo"
    assert bundle.scope.resource_ids == ["res-1"]
    assert bundle.input.task_brief.startswith("Capture the deterministic quickstart demo")
    assert bundle.security.completeness == "complete"
    assert bundle.verification_logs[0].status == "passed"

def test_quickstart_demo_creates_isolated_resource_and_prints_answer(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    config_path = tmp_path / "sourcebrief-config.json"
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(config_path))

    assert cli_main(["quickstart-demo", "--slug", "demo-cli-test"]) == 0

    out = capsys.readouterr().out
    assert "Quickstart demo: indexed and ready for retrieval" in out
    assert "Answer:" in out
    assert 'sourcebrief ask --resource "Payment retry runbook"' in out
    assert "workspace_id:" not in out
    assert "resource_id:" not in out
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["workspace_id"] == "ws-1"
    assert saved["project_id"] == "proj-1"
    client = FakeClient.instances[-1]
    assert client.calls[0][0:2] == ("GET", "/readyz")
    assert client.calls[1][0:2] == ("POST", "/workspaces")
    assert client.calls[2][0:2] == ("POST", "/workspaces/ws-1/projects")
    agent_context_call = next(call for call in client.calls if call[1] == "/workspaces/ws-1/projects/proj-1/agent-context")
    assert agent_context_call[2]["resource_ref"] == "Payment retry runbook"


def test_quickstart_demo_can_validate_mcp(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(tmp_path / "sourcebrief-config.json"))

    assert cli_main(["quickstart-demo", "--validate-mcp"]) == 0

    out = capsys.readouterr().out
    assert "mcp_validation: passed" in out
    assert any(call[1] == "/mcp/ws-1/proj-1" for call in FakeClient.instances[-1].calls)
