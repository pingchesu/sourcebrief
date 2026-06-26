from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def load_module():
    script = Path(__file__).resolve().parents[2] / "scripts" / "collect_e2e_evidence.py"
    spec = importlib.util.spec_from_file_location("collect_e2e_evidence_under_test", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_env_summary_redacts_secret_keys_and_uses_configured_ports(tmp_path):
    module = load_module()
    env_file = tmp_path / ".env"
    env_file.write_text(
        "SOURCEBRIEF_API_PORT=18111\n"
        "SOURCEBRIEF_WEB_PORT=13111\n"
        "SOURCEBRIEF_ADMIN_PASSWORD=super-secret\n"
        "SOURCEBRIEF_TOKEN=cs_abc123456789\n"
        "SOURCEBRIEF_DEV_AUTH=true\n",
        encoding="utf-8",
    )

    urls = module.configured_urls(env_file, {})
    summary = module.redacted_env_summary(env_file, {})

    assert urls["api_url"] == "http://localhost:18111"
    assert urls["web_url"] == "http://localhost:13111"
    assert summary["SOURCEBRIEF_ADMIN_PASSWORD"] == "***REDACTED***"
    assert summary["SOURCEBRIEF_TOKEN"] == "***REDACTED***"
    assert summary["SOURCEBRIEF_DEV_AUTH"] == "true"


def test_bundle_writer_creates_redacted_manifest_without_live_checks(tmp_path, monkeypatch):
    module = load_module()
    output = tmp_path / "bundle"
    env_file = tmp_path / ".env"
    env_file.write_text(
        "COMPOSE_PROJECT_NAME=sourcebrief_e2e_test\n"
        "SOURCEBRIEF_API_PORT=18123\n"
        "SOURCEBRIEF_ADMIN_PASSWORD=super-secret\n"
        "SOURCEBRIEF_TOKEN=plain-token\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    exit_code = module.main(
        [
            "--output-dir",
            str(output),
            "--env-file",
            str(env_file),
            "--skip-docker",
            "--skip-health",
            "--command",
            "printf 'SOURCEBRIEF_ADMIN_PASSWORD=super-secret\\nSOURCEBRIEF_TOKEN=plain-token\\nAuthorization: Bearer abc.def.ghi\\n'",
            "--include-file",
            f"sample={env_file}",
        ]
    )

    assert exit_code == 0
    manifest_text = (output / "manifest.json").read_text(encoding="utf-8")
    readme_text = (output / "README.md").read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    assert manifest["compose"]["project_name"] == "sourcebrief_e2e_test"
    assert manifest["urls"]["api_url"] == "http://localhost:18123"
    assert manifest["health_checks"] == []
    assert manifest["commands"][0]["exit_code"] == 0
    for forbidden in ["super-secret", "plain-token", "Bearer abc.def.ghi"]:
        assert forbidden not in manifest_text
        assert forbidden not in readme_text
    assert "***REDACTED***" in manifest_text
    assert "***REDACTED***" in readme_text
