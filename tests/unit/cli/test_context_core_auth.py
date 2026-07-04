# ruff: noqa: F405
from tests.unit.cli.support import *  # noqa: F401,F403


def test_search_json_output(monkeypatch, capsys):
    patch_client(monkeypatch)

    exit_code = cli_main(
        [
            "--json",
            "search",
            "--workspace-id",
            "ws-1",
            "--project-id",
            "proj-1",
            "--query",
            "demo",
            "--resource-id",
            "res-1",
        ]
    )

    assert exit_code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["query"] == "demo"
    client = FakeClient.instances[0]
    assert client.calls[0][2] == {"query": "demo", "top_k": 10, "resource_ids": ["res-1"]}


def test_cli_use_status_and_ask_defaults(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    config_path = tmp_path / "sourcebrief-config.json"
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(config_path))

    assert (
        cli_main(
            [
                "--api-url",
                "http://api.example",
                "use",
                "--workspace-id",
                "ws-1",
                "--project-id",
                "proj-1",
            ]
        )
        == 0
    )
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved == {"api_url": "http://api.example", "project_id": "proj-1", "workspace_id": "ws-1"}
    assert json.loads(capsys.readouterr().out)["status"] == "saved"

    assert cli_main(["--token", "cs_existing", "--json", "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["workspace_id"] == "ws-1"
    assert status["project_id"] == "proj-1"
    assert status["auth_mode"] == "bearer_token"
    assert status["token_set"] is True
    assert "cs_existing" not in json.dumps(status)

    assert cli_main(["ask", "Where is retry policy?", "--json", "--runtime", "hermes", "--resource-id", "res-1"]) == 0
    ask_json = json.loads(capsys.readouterr().out)
    assert ask_json["context"].startswith("[1] resource=res-1")
    assert ask_json["citations"][0]["path"] == "runbooks/payment-retry.md"
    client = FakeClient.instances[-1]
    assert client.calls[0] == (
        "POST",
        "/workspaces/ws-1/projects/proj-1/agent-context",
        {
            "query": "Where is retry policy?",
            "runtime": "hermes",
            "top_k": 8,
            "resource_ids": ["res-1"],
            "include_code_symbols": True,
            "include_answer": True,
            "max_chars": 12000,
        },
        None,
    )


def test_cli_ask_can_write_valid_review_bundle(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    config_path = tmp_path / "sourcebrief-config.json"
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(config_path))
    config_path.write_text(json.dumps({"api_url": "http://api.example", "workspace_id": "ws-1", "project_id": "proj-1"}), encoding="utf-8")
    bundle_path = tmp_path / "review-bundles" / "ask.json"

    assert cli_main(["ask", "Where is retry policy?", "--json", "--resource-id", "res-1", "--review-bundle-out", str(bundle_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["review_bundle"]["path"] == str(bundle_path)
    assert payload["review_bundle"]["completeness"] == "complete"

    bundle = load_review_bundle(bundle_path)
    assert bundle.kind == "answer"
    assert bundle.scope.workspace_id == "ws-1"
    assert bundle.scope.project_id == "proj-1"
    assert bundle.scope.resource_ids == ["res-1"]
    assert bundle.input.original_query == "Where is retry policy?"
    assert bundle.security.egress_decision == "local_only"
    assert bundle.security.completeness == "complete"
    assert bundle.citations[0].source_ref.resource_id == "res-1"
    assert bundle.citations[0].supports_claim_ids == bundle.output.claim_ids
    assert bundle.tool_proof[0].kind == "api"
    assert "cs_" not in bundle_path.read_text(encoding="utf-8")

def test_explicit_workspace_id_does_not_inherit_saved_project(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    config_path = tmp_path / "sourcebrief-config.json"
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(config_path))
    config_path.write_text(json.dumps({"workspace_id": "ws-saved", "project_id": "proj-saved"}), encoding="utf-8")

    exit_code = cli_main(["--token", "cs_existing", "--json", "search", "--workspace-id", "ws-explicit", "--query", "demo"])

    assert exit_code == 1
    assert "--project / --project-id required" in capsys.readouterr().err
    assert FakeClient.instances[-1].calls == []


def test_resource_add_commands_require_scope_before_reading_local_inputs(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(tmp_path / "sourcebrief-config.json"))
    upload = tmp_path / "upload.md"
    upload.write_text("secret local content\n", encoding="utf-8")

    commands = [
        ["resource", "add-doc", "--name", "Runbook", "--uri", "doc://runbook", "--content", "hi"],
        ["resource", "add-repo", "--name", "Repo", "--repo-url", "https://example.test/repo.git"],
        ["resource", "add-url", "--name", "Page", "--url", "https://example.test/page"],
        ["resource", "add-upload", "--name", "Upload", "--path", str(upload)],
    ]
    for argv in commands:
        FakeClient.instances.clear()
        assert cli_main(["--token", "cs_existing", "--json", *argv]) == 1
        assert "--workspace / --workspace-id" in capsys.readouterr().err
        assert FakeClient.instances[-1].calls == []


def test_name_first_use_logs_in_before_resolving_names(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    config_path = tmp_path / "sourcebrief-config.json"
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_EMAIL", "admin@sourcebrief.local")
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_PASSWORD", "local-password")

    assert cli_main(["--json", "use", "--workspace", "Demo Workspace", "--project", "Demo Project"]) == 0
    saved = json.loads(capsys.readouterr().out)
    assert saved["workspace_id"] == "ws-1"
    assert saved["project_id"] == "proj-1"
    client = FakeClient.instances[-1]
    assert client.calls[:3] == [
        ("POST", "/auth/login", {"email": "admin@sourcebrief.local", "password": "local-password"}, None),
        ("GET", "/workspaces", None, None),
        ("GET", "/workspaces/ws-1/projects", None, None),
    ]
    assert client.token == "session-for-admin@sourcebrief.local"


def test_id_only_use_remains_local_only_with_env_password(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(tmp_path / "sourcebrief-config.json"))
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_EMAIL", "admin@sourcebrief.local")
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_PASSWORD", "local-password")

    assert cli_main(["--json", "use", "--workspace-id", "ws-1", "--project-id", "proj-1"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "saved"
    assert FakeClient.instances[-1].calls == []


def test_cli_login_saves_session_token_and_logout_removes_it(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    config_path = tmp_path / "sourcebrief-config.json"
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("SOURCEBRIEF_LOGIN_PASSWORD", "local-password")

    assert cli_main(["--api-url", "http://api.example", "--json", "login", "--email", "admin@sourcebrief.local", "--password-env", "SOURCEBRIEF_LOGIN_PASSWORD"]) == 0
    login = json.loads(capsys.readouterr().out)
    assert login["status"] == "logged_in"
    assert login["auth_mode"] == "saved_session"
    assert "session-for-admin@sourcebrief.local" not in json.dumps(login)
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["session_token"] == "session-for-admin@sourcebrief.local"
    assert saved["session_email"] == "admin@sourcebrief.local"
    assert saved["api_url"] == "http://api.example"
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600

    assert cli_main(["--json", "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["auth_mode"] == "saved_session"
    assert status["email"] == "admin@sourcebrief.local"
    assert status["token_set"] is True
    assert "session-for-admin@sourcebrief.local" not in json.dumps(status)

    assert cli_main(["--json", "logout"]) == 0
    logout = json.loads(capsys.readouterr().out)
    assert logout == {"config_path": str(config_path), "removed_session": True, "status": "logged_out"}
    assert "session_token" not in json.loads(config_path.read_text(encoding="utf-8"))


def test_cli_login_replaces_existing_permissive_config_with_private_file(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    config_path = tmp_path / "sourcebrief-config.json"
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("SOURCEBRIEF_LOGIN_PASSWORD", "local-password")
    config_path.write_text(json.dumps({"workspace_id": "ws-1"}), encoding="utf-8")
    config_path.chmod(0o644)

    assert cli_main(["--json", "login", "--email", "admin@sourcebrief.local", "--password-env", "SOURCEBRIEF_LOGIN_PASSWORD"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "logged_in"
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["workspace_id"] == "ws-1"
    assert saved["session_token"] == "session-for-admin@sourcebrief.local"
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


def test_cli_env_password_logs_in_before_command(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(tmp_path / "sourcebrief-config.json"))
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_EMAIL", "admin@sourcebrief.local")
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_PASSWORD", "local-password")

    assert cli_main(["--json", "search", "--workspace-id", "ws-1", "--project-id", "proj-1", "--query", "demo"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["query"] == "demo"
    client = FakeClient.instances[0]
    assert client.calls[0] == (
        "POST",
        "/auth/login",
        {"email": "admin@sourcebrief.local", "password": "local-password"},
        None,
    )
    assert client.token == "session-for-admin@sourcebrief.local"
    assert client.calls[1][0:2] == ("POST", "/workspaces/ws-1/projects/proj-1/search")


def test_cli_env_password_global_email_overrides_admin_env(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(tmp_path / "sourcebrief-config.json"))
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_EMAIL", "admin@sourcebrief.local")
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_PASSWORD", "local-password")

    assert cli_main([
        "--email",
        "global@sourcebrief.local",
        "--json",
        "search",
        "--workspace-id",
        "ws-1",
        "--project-id",
        "proj-1",
        "--query",
        "demo",
    ]) == 0
    assert json.loads(capsys.readouterr().out)["query"] == "demo"
    client = FakeClient.instances[-1]
    assert client.calls[0] == (
        "POST",
        "/auth/login",
        {"email": "global@sourcebrief.local", "password": "local-password"},
        None,
    )
    assert client.token == "session-for-global@sourcebrief.local"


def test_cli_login_reads_email_and_password_from_dotenv_file(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    config_path = tmp_path / "sourcebrief-config.json"
    dotenv_path = tmp_path / ".env"
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("SOURCEBRIEF_DOTENV_PATH", str(dotenv_path))
    dotenv_path.write_text(
        'SOURCEBRIEF_ADMIN_EMAIL="admin@sourcebrief.local"\n'
        'SOURCEBRIEF_ADMIN_PASSWORD="password with spaces"\n',
        encoding="utf-8",
    )

    assert cli_main(["--api-url", "http://api.example", "--json", "login", "--password-env", "SOURCEBRIEF_ADMIN_PASSWORD"]) == 0
    login = json.loads(capsys.readouterr().out)
    assert login["status"] == "logged_in"
    assert login["email"] == "admin@sourcebrief.local"
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["session_token"] == "session-for-admin@sourcebrief.local"
    client = FakeClient.instances[1]
    assert client.calls[0] == (
        "POST",
        "/auth/login",
        {"email": "admin@sourcebrief.local", "password": "password with spaces"},
        None,
    )


def test_cli_auth_precedence_token_over_saved_session_over_env_password(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    config_path = tmp_path / "sourcebrief-config.json"
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(config_path))
    config_path.write_text(json.dumps({"session_token": "saved-session", "session_email": "saved@example.com"}), encoding="utf-8")
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_EMAIL", "admin@sourcebrief.local")
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_PASSWORD", "local-password")

    assert cli_main(["--json", "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["auth_mode"] == "saved_session"
    assert status["email"] == "saved@example.com"
    assert status["password_env_set"] is False

    assert cli_main(["--token", "explicit-token", "--json", "status"]) == 0
    explicit = json.loads(capsys.readouterr().out)
    assert explicit["auth_mode"] == "bearer_token"
    assert explicit["email"] is None
    assert "explicit-token" not in json.dumps(explicit)


def test_cli_dotenv_token_takes_precedence_over_dotenv_password(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    config_path = tmp_path / "sourcebrief-config.json"
    dotenv_path = tmp_path / ".env"
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("SOURCEBRIEF_DOTENV_PATH", str(dotenv_path))
    dotenv_path.write_text(
        "SOURCEBRIEF_TOKEN=dotenv-token\n"
        "SOURCEBRIEF_ADMIN_EMAIL=admin@sourcebrief.local\n"
        "SOURCEBRIEF_ADMIN_PASSWORD=local-password\n",
        encoding="utf-8",
    )

    assert cli_main(["--json", "status"]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["auth_mode"] == "bearer_token"
    assert status["token_set"] is True
    assert status["password_env_set"] is False
    assert "dotenv-token" not in json.dumps(status)

    assert cli_main(["--json", "search", "--workspace-id", "ws-1", "--project-id", "proj-1", "--query", "demo"]) == 0
    assert json.loads(capsys.readouterr().out)["query"] == "demo"
    client = FakeClient.instances[-1]
    assert client.token == "dotenv-token"
    assert client.calls[0][0:2] == ("POST", "/workspaces/ws-1/projects/proj-1/search")


def test_cli_login_accepts_global_email(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    config_path = tmp_path / "sourcebrief-config.json"
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("SOURCEBRIEF_LOGIN_PASSWORD", "local-password")
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_EMAIL", "admin@sourcebrief.local")

    assert cli_main(["--api-url", "http://api.example", "--email", "global@sourcebrief.local", "--json", "login", "--password-env", "SOURCEBRIEF_LOGIN_PASSWORD"]) == 0
    login = json.loads(capsys.readouterr().out)
    assert login["email"] == "global@sourcebrief.local"
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["session_token"] == "session-for-global@sourcebrief.local"


def test_cli_env_password_does_not_login_for_health_or_use(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    config_path = tmp_path / "sourcebrief-config.json"
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(config_path))
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_EMAIL", "admin@sourcebrief.local")
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_PASSWORD", "local-password")

    assert cli_main(["--json", "health"]) == 0
    assert FakeClient.instances[-1].calls == [("GET", "/readyz", None, None)]
    capsys.readouterr()

    assert cli_main(["use", "--workspace-id", "ws-1", "--project-id", "proj-1"]) == 0
    assert FakeClient.instances[-1].calls == []
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["workspace_id"] == "ws-1"
    assert "session_token" not in saved


def test_cli_selected_defaults_apply_to_search_and_resource_list(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    config_path = tmp_path / "sourcebrief-config.json"
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(config_path))
    config_path.write_text(json.dumps({"workspace_id": "ws-1", "project_id": "proj-1"}), encoding="utf-8")

    assert cli_main(["--json", "search", "--query", "demo", "--resource", "Runbook"]) == 0
    search_call = FakeClient.instances[-1].calls[0]
    assert search_call[0:2] == ("POST", "/workspaces/ws-1/projects/proj-1/search")
    assert search_call[2] == {"query": "demo", "top_k": 10, "resource_ids": None, "resource_ref": "Runbook"}
    capsys.readouterr()

    assert cli_main(["--json", "search", "--query", "compare", "--resource", "Runbook", "--resource", "Comparison notes", "--resource-id", "res-explicit"]) == 0
    multi_search_call = FakeClient.instances[-1].calls[0]
    assert multi_search_call[2] == {"query": "compare", "top_k": 10, "resource_ids": ["res-explicit"], "resource_refs": ["Runbook", "Comparison notes"]}
    capsys.readouterr()

    assert cli_main(["--json", "mcp-context", "--query", "compare", "--resource", "Runbook", "--resource", "Comparison notes"]) == 0
    mcp_call = FakeClient.instances[-1].calls[0]
    assert mcp_call[2] is not None
    assert mcp_call[2]["params"]["arguments"]["resource_refs"] == ["Runbook", "Comparison notes"]
    capsys.readouterr()

    assert cli_main(["--json", "resource", "list"]) == 0
    assert FakeClient.instances[-1].calls[0][0:2] == ("GET", "/workspaces/ws-1/projects/proj-1/resources")
    capsys.readouterr()

    assert cli_main(["resource", "add-doc", "--name", "Runbook", "--uri", "doc://runbook", "--content", "hello", "--refresh", "--wait"]) == 0
    resource_out = capsys.readouterr().out
    assert "Resource" in resource_out
    client = FakeClient.instances[-1]
    assert client.calls[0][0:2] == ("POST", "/workspaces/ws-1/projects/proj-1/resources")
    assert client.calls[-1][0:2] == ("GET", "/workspaces/ws-1/index-runs/run-1")

    assert cli_main(["--json", "search", "--workspace-id", "ws-explicit", "--project-id", "proj-explicit", "--query", "demo"]) == 0
    assert FakeClient.instances[-1].calls[0][0:2] == (
        "POST",
        "/workspaces/ws-explicit/projects/proj-explicit/search",
    )

    assert cli_main(["--json", "search", "--workspace", "demo-workspace", "--project", "Demo Project", "--query", "demo"]) == 0
    named_client = FakeClient.instances[-1]
    assert named_client.calls[0][0:2] == ("GET", "/workspaces")
    assert named_client.calls[1][0:2] == ("GET", "/workspaces/ws-1/projects")
    assert named_client.calls[2][0:2] == ("POST", "/workspaces/ws-1/projects/proj-1/search")
    capsys.readouterr()

    assert cli_main(["search", "--workspace", "demo-workspace", "--query", "demo"]) == 1
    assert "--project / --project-id required" in capsys.readouterr().err


def test_cli_use_can_save_name_first_scope_and_rejects_ambiguous_names(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    config_path = tmp_path / "sourcebrief-config.json"
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(config_path))

    assert cli_main(["--json", "use", "--workspace", "Demo Workspace", "--project", "Demo Project"]) == 0
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["workspace_id"] == "ws-1"
    assert saved["workspace_name"] == "Demo Workspace"
    assert saved["workspace_slug"] == "demo-workspace"
    assert saved["project_id"] == "proj-1"
    assert saved["project_name"] == "Demo Project"
    out = json.loads(capsys.readouterr().out)
    assert out["workspace"] == "Demo Workspace"
    assert out["project"] == "Demo Project"

    assert cli_main(["use", "--workspace", "Duplicate Workspace"]) == 1
    assert "workspace 'Duplicate Workspace' is ambiguous" in capsys.readouterr().err

    assert cli_main(["use", "--workspace", "Demo Workspace", "--project", "Duplicate Project"]) == 1
    assert "project 'Duplicate Project' is ambiguous" in capsys.readouterr().err


def test_cli_runtime_token_can_resolve_project_name_under_saved_workspace(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    config_path = tmp_path / "sourcebrief-config.json"
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(config_path))
    config_path.write_text(json.dumps({"workspace_id": "ws-1", "workspace_name": "Demo Workspace"}), encoding="utf-8")

    assert cli_main(["--json", "token", "create-runtime", "--context-only", "--project", "Demo Project"]) == 0
    body = FakeClient.instances[-1].calls[-1][2]
    assert body is not None
    assert body["allowed_project_ids"] == ["proj-1"]

def test_cli_missing_selected_scope_errors(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(tmp_path / "missing.json"))

    assert cli_main(["search", "--query", "demo"]) == 1
    err = capsys.readouterr().err
    assert "--workspace / --workspace-id and --project / --project-id required" in err
    assert "sourcebrief use" in err


def test_cli_use_clear_and_partial_update_do_not_restore_stale_defaults(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    config_path = tmp_path / "sourcebrief-config.json"
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(config_path))
    config_path.write_text(
        json.dumps({"api_url": "http://api.example", "workspace_id": "ws-old", "project_id": "proj-old"}),
        encoding="utf-8",
    )

    assert cli_main(["use", "--clear"]) == 0
    cleared = json.loads(config_path.read_text(encoding="utf-8"))
    assert cleared == {"api_url": "http://api.example"}
    capsys.readouterr()

    config_path.write_text(
        json.dumps({"api_url": "http://api.example", "workspace_id": "ws-old", "project_id": "proj-old"}),
        encoding="utf-8",
    )
    assert cli_main(["use", "--workspace-id", "ws-new"]) == 0
    updated = json.loads(config_path.read_text(encoding="utf-8"))
    assert updated == {"api_url": "http://api.example", "workspace_id": "ws-new"}
    assert json.loads(capsys.readouterr().out)["project_id"] is None


def test_cli_saved_api_url_is_used_but_not_silently_overwritten(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    config_path = tmp_path / "sourcebrief-config.json"
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(config_path))
    config_path.write_text(
        json.dumps({"api_url": "http://api.example", "workspace_id": "ws-1", "project_id": "proj-1"}),
        encoding="utf-8",
    )

    assert cli_main(["--json", "status"]) == 0
    assert json.loads(capsys.readouterr().out)["api_url"] == "http://api.example"

    assert cli_main(["--json", "ask", "demo"]) == 0
    assert FakeClient.instances[-1].api_url == "http://api.example"
    capsys.readouterr()

    assert cli_main(["ask", "demo", "--resource", "Payment retry runbook"]) == 0
    ask_out = capsys.readouterr().out
    assert "Answer:" in ask_out
    assert "Outcome: answered" in ask_out
    assert "Confidence:" in ask_out
    assert "Citations:" in ask_out
    body = FakeClient.instances[-1].calls[0][2]
    assert body is not None
    assert body["resource_ref"] == "Payment retry runbook"

    assert cli_main(["--json", "mcp-context", "--query", "demo", "--resource", "Payment retry runbook"]) == 0
    mcp_body = FakeClient.instances[-1].calls[0][2]
    assert mcp_body is not None
    assert mcp_body["params"]["arguments"]["resource_ref"] == "Payment retry runbook"

    assert cli_main(["--api-url", "http://override.example", "--json", "ask", "demo"]) == 0
    assert FakeClient.instances[-1].api_url == "http://override.example"
    capsys.readouterr()

    assert cli_main(["use", "--project-id", "proj-2"]) == 0
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["api_url"] == "http://api.example"
    assert saved["project_id"] == "proj-2"


def test_cli_selected_defaults_do_not_affect_token_scope_project_ids(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    config_path = tmp_path / "sourcebrief-config.json"
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(config_path))
    config_path.write_text(json.dumps({"workspace_id": "ws-selected", "project_id": "proj-selected"}), encoding="utf-8")

    assert cli_main(["--json", "token", "create", "--workspace-id", "ws-1", "--name", "Hermes", "--scope", "project:query"]) == 0
    body = FakeClient.instances[-1].calls[0][2]
    assert body is not None
    assert body["allowed_project_ids"] is None
    assert body["allowed_resource_ids"] is None
    assert body["scopes"] == ["project:query"]

def test_cli_use_clear_recovers_from_invalid_config(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    config_path = tmp_path / "sourcebrief-config.json"
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(config_path))
    config_path.write_text("not json", encoding="utf-8")

    assert cli_main(["use", "--clear"]) == 0
    assert json.loads(config_path.read_text(encoding="utf-8"))["api_url"] == "http://localhost:18000"
