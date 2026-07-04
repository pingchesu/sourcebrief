# ruff: noqa: F405
from tests.unit.cli.support import *  # noqa: F401,F403


def test_token_create_runtime_presets(monkeypatch, capsys):
    patch_client(monkeypatch)

    assert (
        cli_main(
            [
                "--json",
                "token",
                "create-runtime",
                "--workspace-id",
                "ws-1",
                "--name",
                "Hermes Runtime",
                "--project-id",
                "proj-1",
                "--read-code",
            ]
        )
        == 0
    )
    body = FakeClient.instances[-1].calls[0][2]
    assert body is not None
    assert body["name"] == "Hermes Runtime"
    assert body["scopes"] == ["project:read", "project:query", "resource:read", "review:read", "code:read"]
    assert body["allowed_project_ids"] == ["proj-1"]
    capsys.readouterr()

    assert cli_main(["--json", "token", "create-runtime", "--workspace-id", "ws-1", "--context-only"]) == 1
    assert "requires --project/--project-id/--resource-id or explicit --workspace-wide" in capsys.readouterr().err

    assert cli_main(["--json", "token", "create-runtime", "--workspace-id", "ws-1", "--context-only", "--workspace-wide"]) == 0
    body = FakeClient.instances[-1].calls[0][2]
    assert body is not None
    assert body["scopes"] == ["project:read", "project:query", "resource:read", "review:read"]
    assert body["allowed_project_ids"] is None

def test_token_commands_and_bearer_client(monkeypatch, capsys):
    patch_client(monkeypatch)

    exit_code = cli_main(
        [
            "--token",
            "cs_existing",
            "--json",
            "token",
            "create",
            "--workspace-id",
            "ws-1",
            "--name",
            "Hermes",
            "--scope",
            "project:query,resource:read",
            "--project-id",
            "proj-1",
            "--resource-id",
            "res-1",
        ]
    )
    assert exit_code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["token"] == "cs_secret"
    client = FakeClient.instances[0]
    assert client.token == "cs_existing"
    assert client.calls[0] == (
        "POST",
        "/workspaces/ws-1/api-tokens",
        {
            "name": "Hermes",
            "scopes": ["project:query", "resource:read"],
            "allowed_project_ids": ["proj-1"],
            "allowed_resource_ids": ["res-1"],
            "expires_at": None,
        },
        {201},
    )

    assert cli_main(["--json", "token", "list", "--workspace-id", "ws-1"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["id"] == "tok-1"

    assert (
        cli_main(["--json", "token", "revoke", "--workspace-id", "ws-1", "--token-id", "tok-1"])
        == 0
    )
    assert json.loads(capsys.readouterr().out)["id"] == "tok-1"

def test_hermes_integration_allow_empty_creates_empty_resource_allowlist(monkeypatch):
    module = importlib.import_module("scripts.hermes_integration")
    calls: list[dict[str, Any]] = []

    def fake_request_json(method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        calls.append({"method": method, "url": url, **kwargs})
        return {
            "token": "cs_secret",
            "api_token": {
                "scopes": ["project:read"],
                "allowed_project_ids": ["proj-1"],
                "allowed_resource_ids": [],
            },
        }

    monkeypatch.setattr(module, "request_json", fake_request_json)
    args = module.build_parser().parse_args(
        [
            "--workspace-id",
            "ws-1",
            "--project-id",
            "proj-1",
            "--query",
            "demo",
            "--allow-empty",
            "--scope",
            "project:read",
        ]
    )
    args.api_url = args.api_url.rstrip("/")
    args.public_api_url = None
    args.scope = module.split_scopes(args.scope)

    module.create_token(args)

    assert calls[0]["json"]["allowed_resource_ids"] == []


def test_hermes_integration_token_env_avoids_token_argv(monkeypatch):
    module = importlib.import_module("scripts.hermes_integration")

    def fail_request_json(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("token-env should skip token creation")

    monkeypatch.setattr(module, "request_json", fail_request_json)
    monkeypatch.setenv("SOURCEBRIEF_TOKEN", "cs_env_secret")
    args = module.build_parser().parse_args(
        [
            "--workspace-id",
            "ws-1",
            "--project-id",
            "proj-1",
            "--query",
            "demo",
            "--token-env",
            "SOURCEBRIEF_TOKEN",
        ]
    )

    token, api_token = module.create_token(args)

    assert token == "cs_env_secret"
    assert api_token is None
