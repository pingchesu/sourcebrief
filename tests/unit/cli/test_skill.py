# ruff: noqa: F405
from tests.unit.cli.support import *  # noqa: F401,F403


def test_cli_skill_export_writes_approved_package_name_first(monkeypatch, capsys, tmp_path):
    patch_client(monkeypatch)
    out_dir = tmp_path / "skill-package"

    assert (
        cli_main(
            [
                "--json",
                "skill",
                "export",
                "--workspace",
                "Demo Workspace",
                "--project",
                "Demo Project",
                "--title",
                "Demo skill",
                "--approve-comment",
                "Approved for local install.",
                "--out",
                str(out_dir),
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["export"]["status"] == "approved"
    assert payload["download_url"].endswith("/skill-exports/skill-export-1/download.zip")
    assert (out_dir / "SKILL.md").exists()
    assert json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))["export_status"] == "approved"
    paths = [call[1] for call in FakeClient.instances[-1].calls]
    assert "/workspaces/ws-1/projects/proj-1/context-packs/default/current" in paths
    assert "/workspaces/ws-1/projects/proj-1/context-packs/default/versions/3/skill-exports" in paths
    assert "/workspaces/ws-1/projects/proj-1/skill-exports/skill-export-1/approve" in paths


def test_cli_skill_install_apply_and_uninstall(monkeypatch, capsys, tmp_path):
    package = tmp_path / "package"
    package.mkdir()
    skill_content = b"---\nname: demo\n---\n"
    manifest_hash_content = json.dumps({"schema_version": "sourcebrief.skill-export.v1"}).encode() + b"\n"
    (package / "SKILL.md").write_bytes(skill_content)
    (package / "manifest.hash.json").write_bytes(manifest_hash_content)
    package_inputs = {
        "schema_version": "sourcebrief.skill-export.v1",
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
    (package / "manifest.json").write_text(
        json.dumps(
            {
                "package_kind": "sourcebrief_skill_pack",
                "export_status": "approved",
                "package_hash": package_hash,
                "pack_key": "default",
                "pack_version": 3,
                "package_hash_inputs": package_inputs,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    skills_dir = tmp_path / "skills"
    receipt = tmp_path / "receipt.json"

    assert cli_main(["--json", "skill", "install", "--package", str(package), "--skills-dir", str(skills_dir), "--receipt", str(receipt), "--dry-run"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "dry_run"

    assert cli_main(["--json", "skill", "install", "--package", str(package), "--skills-dir", str(skills_dir), "--receipt", str(receipt), "--apply"]) == 0
    installed = json.loads(capsys.readouterr().out)
    assert installed["status"] == "installed"
    assert (skills_dir / "sourcebrief-default" / "SKILL.md").exists()

    assert cli_main(["--json", "skill", "uninstall", "--receipt", str(receipt)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "uninstalled"
    assert not (skills_dir / "sourcebrief-default" / "SKILL.md").exists()
