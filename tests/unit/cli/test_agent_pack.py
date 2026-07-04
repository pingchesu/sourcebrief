# ruff: noqa: F405
from tests.unit.cli.support import *  # noqa: F401,F403


def _agent_pack_package(tmp_path: Path, *, manifest_overrides: dict[str, Any] | None = None) -> Path:
    package = tmp_path / "agent-pack"
    package.mkdir()
    skill_content = b"---\nname: demo\n---\n"
    manifest_hash_content = json.dumps({"schema_version": "skill-export.v2"}).encode() + b"\n"
    (package / "SKILL.md").write_bytes(skill_content)
    (package / "manifest.hash.json").write_bytes(manifest_hash_content)
    package_inputs = {
        "schema_version": "skill-export.v2",
        "package_kind": "sourcebrief_skill_pack",
        "export_type": "hermes_skill",
        "pack_key": "default",
        "pack_version": 3,
        "pack_hash": "sha256:" + "b" * 64,
        "files": [
            {"path": "SKILL.md", "sha256": skill_install.sha256_bytes(skill_content), "bytes": len(skill_content)},
            {"path": "manifest.hash.json", "sha256": skill_install.sha256_bytes(manifest_hash_content), "bytes": len(manifest_hash_content)},
        ],
    }
    package_hash = skill_install.sha256_bytes((json.dumps(package_inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    manifest: dict[str, Any] = {
        "package_kind": "sourcebrief_skill_pack",
        "export_status": "approved",
        "package_hash": package_hash,
        "pack_key": "default",
        "pack_version": 3,
        "pack_hash": "sha256:" + "b" * 64,
        "agent_pack_schema_version": "sourcebrief.agent-pack.v1",
        "mode": "remote-live",
        "requires_sourcebrief_remote": True,
        "runtime_access": {
            "mode": "remote-live",
            "requires_sourcebrief_remote": True,
            "local_repo_required": False,
            "local_grep_allowed": False,
            "local_edits_allowed": False,
            "current_claims_require_remote": True,
        },
        "runtime_tools": {"mcp_required": ["sourcebrief.get_agent_context"], "mcp_optional": ["sourcebrief.graph_query"], "cli": ["sourcebrief skill install --dry-run"]},
        "local_payload": {
            "contains_full_resource": False,
            "contains_raw_source": False,
            "contains_embeddings": False,
            "contains_graph_index": False,
        },
        "freshness_policy": {"require_remote_for_current_claims": True},
        "security_policy": {
            "requires_runtime_auth": True,
            "supports_revocation": True,
            "plaintext_tokens_allowed": False,
            "server_side_local_apply_allowed": False,
            "cache_mode": "none",
        },
        "cache_policy": {"mode": "none", "pinned_snapshot": False, "local_mirror": False, "full_resource_sync_default": False},
        "package_hash_inputs": package_inputs,
    }
    if manifest_overrides:
        manifest.update(manifest_overrides)
    (package / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    return package


def test_agent_pack_doctor_validates_local_package_without_remote_calls(capsys, tmp_path):
    package = _agent_pack_package(tmp_path)

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "passed"
    assert data["package"]["mode"] == "remote-live"
    assert [check["name"] for check in data["checks"]][:3] == ["package_integrity", "manifest_schema", "runtime_access"]
    assert data["remote_smoke"] is None


def test_agent_pack_doctor_runs_optional_remote_smoke(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    package = _agent_pack_package(tmp_path)

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package), "--workspace-id", "ws-1", "--project-id", "proj-1", "--query", "hello runtime"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "passed"
    assert data["remote_smoke"]["status"] == "passed"
    assert "remote_mcp_context" in [check["name"] for check in data["checks"]]
    assert any(call[1] == "/mcp/ws-1/proj-1" for call in FakeClient.instances[-1].calls)


def test_agent_pack_doctor_fails_unsafe_local_payload_policy(capsys, tmp_path):
    package = _agent_pack_package(tmp_path, manifest_overrides={"local_payload": {"contains_full_resource": True}})

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 1
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "failed"
    local_payload_check = next(check for check in data["checks"] if check["name"] == "local_payload")
    assert local_payload_check["status"] == "failed"


def test_agent_pack_doctor_uses_saved_scope_defaults_for_remote_smoke(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    config_path = tmp_path / "sourcebrief-config.json"
    monkeypatch.setenv("SOURCEBRIEF_CONFIG_PATH", str(config_path))
    config_path.write_text(json.dumps({"workspace_id": "ws-1", "project_id": "proj-1"}), encoding="utf-8")
    package = _agent_pack_package(tmp_path)

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package), "--query", "hello runtime"]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "passed"
    assert "remote_mcp_context" in [check["name"] for check in data["checks"]]
    assert any(call[1] == "/mcp/ws-1/proj-1" for call in FakeClient.instances[-1].calls)


def test_agent_pack_doctor_remote_smoke_requires_citations(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    package = _agent_pack_package(tmp_path)
    original_request = FakeClient.request

    def fake_request(self, method, path, *, body=None, expected=None):
        if path == "/mcp/ws-1/proj-1":
            return {"jsonrpc": "2.0", "id": 1, "result": {"content": [], "structuredContent": {"citations": [], "answer": {"citations_used": []}}}}
        return original_request(self, method, path, body=body, expected=expected)

    monkeypatch.setattr(FakeClient, "request", fake_request)

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package), "--workspace-id", "ws-1", "--project-id", "proj-1", "--query", "hello runtime"]) == 1
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "failed"
    remote_mcp = next(check for check in data["checks"] if check["name"] == "remote_mcp_context")
    assert remote_mcp["status"] == "failed"
    assert remote_mcp["citation_count"] == 0


def test_agent_pack_doctor_fails_unsafe_or_unknown_security_and_cache_policy(capsys, tmp_path):
    package = _agent_pack_package(
        tmp_path,
        manifest_overrides={
            "security_policy": {"requires_runtime_auth": False, "supports_revocation": False, "plaintext_tokens_allowed": False, "server_side_local_apply_allowed": False},
            "cache_policy": {},
        },
    )

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 1
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "failed"
    assert next(check for check in data["checks"] if check["name"] == "security_policy")["status"] == "failed"
    assert next(check for check in data["checks"] if check["name"] == "cache_policy")["status"] == "failed"


def test_agent_pack_doctor_redacts_secret_like_manifest_tool_values(capsys, tmp_path):
    secret = "cs_secretvalue123456789"
    package = _agent_pack_package(
        tmp_path,
        manifest_overrides={"runtime_tools": {"mcp_required": ["sourcebrief.get_agent_context"], "mcp_optional": [secret]}},
    )

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 0
    output = capsys.readouterr().out
    data = json.loads(output)

    assert secret not in output
    runtime_tools = next(check for check in data["checks"] if check["name"] == "runtime_tools")
    assert runtime_tools["mcp_optional"] == ["[redacted-secret-like-value]"]


def test_agent_pack_doctor_package_only_does_not_env_login(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("SOURCEBRIEF_ADMIN_PASSWORD", "pw")
    package = _agent_pack_package(tmp_path)

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 0
    json.loads(capsys.readouterr().out)
    assert FakeClient.instances[-1].calls == []


def test_agent_pack_doctor_package_only_ignores_named_scope_without_api_calls(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    package = _agent_pack_package(tmp_path)

    assert cli_main([
        "--json",
        "agent-pack",
        "doctor",
        "--package",
        str(package),
        "--workspace",
        "Demo Workspace",
        "--project",
        "Demo Project",
    ]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "passed"
    assert data["remote_smoke"] is None
    assert FakeClient.instances[-1].calls == []


def test_agent_pack_doctor_redacts_github_token_values_and_secret_like_keys(capsys, tmp_path):
    gh_token = "ghp_" + "x" * 24
    key_secret = "cs_secretvalue123456789"
    package = _agent_pack_package(
        tmp_path,
        manifest_overrides={
            "runtime_tools": {
                "mcp_required": ["sourcebrief.get_agent_context", {key_secret: "sourcebrief.search"}],
                "mcp_optional": [gh_token],
            }
        },
    )

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 0
    output = capsys.readouterr().out
    data = json.loads(output)

    assert gh_token not in output
    assert key_secret not in output
    runtime_tools = next(check for check in data["checks"] if check["name"] == "runtime_tools")
    assert runtime_tools["mcp_optional"] == ["[redacted-secret-like-value]"]
    assert runtime_tools["mcp_required"][1] == {"[redacted-secret-like-key]": "sourcebrief.search"}


def test_agent_pack_doctor_fails_missing_required_remote_context_tool(capsys, tmp_path):
    package = _agent_pack_package(
        tmp_path,
        manifest_overrides={"runtime_tools": {"mcp_required": [], "mcp_optional": ["sourcebrief.search"]}},
    )

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 1
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "failed"
    runtime_tools = next(check for check in data["checks"] if check["name"] == "runtime_tools")
    assert runtime_tools["status"] == "failed"


def test_agent_pack_doctor_redacts_secret_like_package_summary_fields(capsys, tmp_path):
    secret_pack_key = "sourcebrieftokenabcd1234"
    package = _agent_pack_package(tmp_path, manifest_overrides={"pack_key": secret_pack_key})

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 0
    output = capsys.readouterr().out
    data = json.loads(output)

    assert secret_pack_key not in output
    assert data["package"]["pack_key"] == "[redacted-secret-like-value]"


def test_agent_pack_doctor_redacts_secret_like_values_from_all_check_fields(capsys, tmp_path):
    secret = "sourcebrieftokenabcd1234"
    package = _agent_pack_package(
        tmp_path,
        manifest_overrides={
            "agent_pack_schema_version": secret,
            "mode": secret,
            "local_payload": {
                "contains_full_resource": False,
                "contains_raw_source": False,
                "contains_embeddings": False,
                "contains_graph_index": secret,
            },
        },
    )

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 1
    output = capsys.readouterr().out
    data = json.loads(output)

    assert secret not in output
    manifest_schema = next(check for check in data["checks"] if check["name"] == "manifest_schema")
    runtime_access = next(check for check in data["checks"] if check["name"] == "runtime_access")
    local_payload = next(check for check in data["checks"] if check["name"] == "local_payload")
    assert manifest_schema["agent_pack_schema_version"] == "[redacted-secret-like-value]"
    assert runtime_access["mode"] == "[redacted-secret-like-value]"
    assert local_payload["contains_graph_index"] == "[redacted-secret-like-value]"


def _pinned_snapshot_manifest_overrides() -> dict[str, Any]:
    return {
        "mode": "pinned-snapshot",
        "requires_sourcebrief_remote": True,
        "runtime_access": {
            "mode": "pinned-snapshot",
            "requires_sourcebrief_remote": True,
            "local_repo_required": False,
            "local_grep_allowed": False,
            "local_edits_allowed": False,
            "current_claims_require_remote": True,
        },
        "local_payload": {
            "contains_full_resource": False,
            "contains_raw_source": False,
            "contains_embeddings": False,
            "contains_graph_index": False,
            "contains_resource_map_summary": True,
            "contains_cited_excerpts": "bounded",
        },
        "freshness_policy": {
            "require_remote_for_current_claims": True,
            "pinned_snapshot": True,
            "offline_current_claims_allowed": False,
            "max_snapshot_age_days": 7,
        },
        "cache_policy": {
            "mode": "pinned-snapshot",
            "pinned_snapshot": True,
            "local_mirror": False,
            "full_resource_sync_default": False,
            "max_snapshot_age_days": 7,
        },
    }


def test_agent_pack_doctor_accepts_explicit_bounded_pinned_snapshot_policy(capsys, tmp_path):
    package = _agent_pack_package(tmp_path, manifest_overrides=_pinned_snapshot_manifest_overrides())

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "passed"
    assert data["package"]["mode"] == "pinned-snapshot"
    assert next(check for check in data["checks"] if check["name"] == "runtime_access")["status"] == "passed"
    assert next(check for check in data["checks"] if check["name"] == "local_payload")["contains_cited_excerpts"] == "bounded"
    assert next(check for check in data["checks"] if check["name"] == "freshness_policy")["offline_current_claims_allowed"] is False
    assert next(check for check in data["checks"] if check["name"] == "cache_policy")["pinned_snapshot"] is True


def test_agent_pack_doctor_rejects_pinned_snapshot_current_claims_without_remote(capsys, tmp_path):
    overrides = _pinned_snapshot_manifest_overrides()
    overrides["freshness_policy"] = {
        "require_remote_for_current_claims": False,
        "pinned_snapshot": True,
        "offline_current_claims_allowed": True,
        "max_snapshot_age_days": 7,
    }
    package = _agent_pack_package(tmp_path, manifest_overrides=overrides)

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 1
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "failed"
    assert next(check for check in data["checks"] if check["name"] == "freshness_policy")["status"] == "failed"


def test_agent_pack_doctor_rejects_pinned_snapshot_full_resource_sync(capsys, tmp_path):
    overrides = _pinned_snapshot_manifest_overrides()
    overrides["local_payload"] = {
        "contains_full_resource": True,
        "contains_raw_source": False,
        "contains_embeddings": False,
        "contains_graph_index": False,
        "contains_resource_map_summary": True,
        "contains_cited_excerpts": "bounded",
    }
    package = _agent_pack_package(tmp_path, manifest_overrides=overrides)

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 1
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "failed"
    assert next(check for check in data["checks"] if check["name"] == "local_payload")["status"] == "failed"


def test_agent_pack_doctor_rejects_pinned_snapshot_unsafe_nested_runtime_access(capsys, tmp_path):
    overrides = _pinned_snapshot_manifest_overrides()
    overrides["runtime_access"] = {
        "mode": "local-mirror",
        "requires_sourcebrief_remote": False,
        "local_repo_required": True,
        "local_grep_allowed": True,
        "local_edits_allowed": True,
        "current_claims_require_remote": False,
    }
    package = _agent_pack_package(tmp_path, manifest_overrides=overrides)

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 1
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "failed"
    runtime_access = next(check for check in data["checks"] if check["name"] == "runtime_access")
    assert runtime_access["status"] == "failed"
    assert runtime_access["runtime_access_current_claims_require_remote"] is False


def test_agent_pack_doctor_rejects_pinned_snapshot_schema_mismatch(capsys, tmp_path):
    overrides = _pinned_snapshot_manifest_overrides()
    overrides["agent_pack_schema_version"] = None
    package = _agent_pack_package(tmp_path, manifest_overrides=overrides)

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 1
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "failed"
    assert next(check for check in data["checks"] if check["name"] == "manifest_schema")["status"] == "failed"


def test_agent_pack_doctor_rejects_pinned_snapshot_boolean_snapshot_age(capsys, tmp_path):
    overrides = _pinned_snapshot_manifest_overrides()
    overrides["freshness_policy"] = {
        "require_remote_for_current_claims": True,
        "pinned_snapshot": True,
        "offline_current_claims_allowed": False,
        "max_snapshot_age_days": True,
    }
    overrides["cache_policy"] = {
        "mode": "pinned-snapshot",
        "pinned_snapshot": True,
        "local_mirror": False,
        "full_resource_sync_default": False,
        "max_snapshot_age_days": True,
    }
    package = _agent_pack_package(tmp_path, manifest_overrides=overrides)

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 1
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "failed"
    assert next(check for check in data["checks"] if check["name"] == "freshness_policy")["status"] == "failed"
    assert next(check for check in data["checks"] if check["name"] == "cache_policy")["status"] == "failed"


def test_agent_pack_doctor_rejects_pinned_snapshot_loose_snapshot_age(capsys, tmp_path):
    overrides = _pinned_snapshot_manifest_overrides()
    overrides["freshness_policy"] = {
        "require_remote_for_current_claims": True,
        "pinned_snapshot": True,
        "offline_current_claims_allowed": False,
        "max_snapshot_age_days": 365,
    }
    overrides["cache_policy"] = {
        "mode": "pinned-snapshot",
        "pinned_snapshot": True,
        "local_mirror": False,
        "full_resource_sync_default": False,
        "max_snapshot_age_days": 365,
    }
    package = _agent_pack_package(tmp_path, manifest_overrides=overrides)

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 1
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "failed"
    assert next(check for check in data["checks"] if check["name"] == "freshness_policy")["status"] == "failed"
    assert next(check for check in data["checks"] if check["name"] == "cache_policy")["status"] == "failed"


def _agent_pack_docs_json_blocks() -> list[dict[str, Any]]:
    docs = (REPO_ROOT / "docs" / "AGENT_PACKS.md").read_text(encoding="utf-8")
    return [json.loads(block) for block in re.findall(r"```json\n(.*?)\n```", docs, re.S)]


def test_agent_pack_docs_representative_remote_live_manifest_passes_doctor(capsys, tmp_path):
    manifest = _agent_pack_docs_json_blocks()[0]
    package = _agent_pack_package(tmp_path, manifest_overrides=manifest)

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "passed"
    assert data["package"]["mode"] == "remote-live"


def test_agent_pack_docs_pinned_snapshot_manifest_passes_doctor(capsys, tmp_path):
    manifest = _agent_pack_docs_json_blocks()[1]
    package = _agent_pack_package(tmp_path, manifest_overrides=manifest)

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "passed"
    assert data["package"]["mode"] == "pinned-snapshot"


def _local_mirror_manifest_overrides() -> dict[str, Any]:
    return {
        "mode": "local-mirror",
        "requires_sourcebrief_remote": False,
        "runtime_access": {
            "mode": "local-mirror",
            "requires_sourcebrief_remote": False,
            "local_repo_required": False,
            "local_grep_allowed": True,
            "local_edits_allowed": False,
            "current_claims_require_remote": True,
        },
        "local_payload": {
            "contains_full_resource": True,
            "contains_raw_source": True,
            "contains_embeddings": True,
            "contains_graph_index": True,
            "contains_resource_map_summary": True,
            "contains_cited_excerpts": "bounded",
            "sensitivity_label": "confidential",
        },
        "freshness_policy": {
            "require_remote_for_current_claims": True,
            "offline_current_claims_allowed": False,
            "max_mirror_age_hours": 24,
            "drift_check_required": True,
            "fail_closed_on_expired_mirror": True,
        },
        "cache_policy": {
            "mode": "local-mirror",
            "pinned_snapshot": False,
            "local_mirror": True,
            "full_resource_sync_default": False,
            "purge_required": True,
            "update_required": True,
            "audit_receipts_required": True,
        },
        "local_mirror_policy": {
            "explicit_opt_in": True,
            "purge_command_required": True,
            "update_command_required": True,
            "drift_detection_required": True,
            "audit_receipts_required": True,
            "sensitivity_labels_required": True,
            "local_access_control_required": True,
            "encryption_at_rest_required": True,
            "server_side_apply_allowed": False,
        },
    }


def test_agent_pack_doctor_accepts_explicit_local_mirror_policy(capsys, tmp_path):
    package = _agent_pack_package(tmp_path, manifest_overrides=_local_mirror_manifest_overrides())

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "passed"
    assert data["package"]["mode"] == "local-mirror"
    assert next(check for check in data["checks"] if check["name"] == "runtime_access")["runtime_access_local_grep_allowed"] is True
    assert next(check for check in data["checks"] if check["name"] == "local_mirror_policy")["explicit_opt_in"] is True


def test_agent_pack_doctor_rejects_local_mirror_without_explicit_controls(capsys, tmp_path):
    overrides = _local_mirror_manifest_overrides()
    overrides["local_mirror_policy"] = {"explicit_opt_in": True}
    package = _agent_pack_package(tmp_path, manifest_overrides=overrides)

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 1
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "failed"
    assert next(check for check in data["checks"] if check["name"] == "local_mirror_policy")["status"] == "failed"


def test_agent_pack_doctor_rejects_local_mirror_current_claims_without_remote(capsys, tmp_path):
    overrides = _local_mirror_manifest_overrides()
    overrides["runtime_access"] = {**overrides["runtime_access"], "current_claims_require_remote": False}
    overrides["freshness_policy"] = {
        **overrides["freshness_policy"],
        "require_remote_for_current_claims": False,
        "offline_current_claims_allowed": True,
    }
    package = _agent_pack_package(tmp_path, manifest_overrides=overrides)

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 1
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "failed"
    assert next(check for check in data["checks"] if check["name"] == "runtime_access")["status"] == "failed"
    assert next(check for check in data["checks"] if check["name"] == "freshness_policy")["status"] == "failed"


def test_agent_pack_doctor_rejects_local_mirror_edits(capsys, tmp_path):
    overrides = _local_mirror_manifest_overrides()
    overrides["runtime_access"] = {**overrides["runtime_access"], "local_edits_allowed": True}
    package = _agent_pack_package(tmp_path, manifest_overrides=overrides)

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 1
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "failed"
    assert next(check for check in data["checks"] if check["name"] == "runtime_access")["status"] == "failed"


def test_agent_pack_docs_local_mirror_manifest_passes_doctor(capsys, tmp_path):
    manifest = _agent_pack_docs_json_blocks()[2]
    package = _agent_pack_package(tmp_path, manifest_overrides=manifest)

    assert cli_main(["--json", "agent-pack", "doctor", "--package", str(package)]) == 0
    data = json.loads(capsys.readouterr().out)

    assert data["status"] == "passed"
    assert data["package"]["mode"] == "local-mirror"
