from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from sourcebrief_cli import skill_install


def _package_manifest(status: str = "approved", files: dict[str, bytes] | None = None) -> dict:
    package_inputs: dict = {
        "schema_version": "sourcebrief.skill-export.v1",
        "package_kind": "sourcebrief_skill_pack",
        "export_type": "hermes_skill",
        "pack_key": "default",
        "pack_version": 3,
        "pack_hash": "sha256:" + "b" * 64,
        "files": [],
    }
    if files is not None:
        package_inputs["files"] = [
            {"path": path, "sha256": skill_install.sha256_bytes(content), "bytes": len(content)}
            for path, content in sorted(files.items())
        ]
    package_hash = skill_install.sha256_bytes((json.dumps(package_inputs, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    return {
        "package_kind": "sourcebrief_skill_pack",
        "export_status": status,
        "package_hash": package_hash,
        "pack_key": "default",
        "pack_version": 3,
        "pack_hash": "sha256:" + "b" * 64,
        "package_hash_inputs": package_inputs,
    }


def write_package(root: Path, *, status: str = "approved") -> Path:
    root.mkdir()
    (root / "references").mkdir()
    (root / "SKILL.md").write_text("---\nname: sourcebrief-default\n---\nUse sourcebrief.get_agent_context and citations.\n", encoding="utf-8")
    (root / "manifest.hash.json").write_text(json.dumps({"schema_version": "sourcebrief.skill-export.v1"}) + "\n", encoding="utf-8")
    (root / "references" / "freshness.md").write_text("Pack freshness and context_pack_version.\n", encoding="utf-8")
    files = {
        "SKILL.md": (root / "SKILL.md").read_bytes(),
        "manifest.hash.json": (root / "manifest.hash.json").read_bytes(),
        "references/freshness.md": (root / "references" / "freshness.md").read_bytes(),
    }
    (root / "manifest.json").write_text(json.dumps(_package_manifest(status, files)) + "\n", encoding="utf-8")
    return root


def test_skill_install_apply_and_uninstall_with_receipt(tmp_path: Path) -> None:
    package = write_package(tmp_path / "package")
    skills_dir = tmp_path / "skills"
    receipt = tmp_path / "receipt.json"

    dry_run = skill_install.dry_run_install(package, skills_dir=skills_dir, profile="default")
    assert dry_run["status"] == "dry_run"
    assert dry_run["skill_name"] == "sourcebrief-default"
    assert any(op["package_path"] == "SKILL.md" for op in dry_run["operations"])

    installed = skill_install.install_package(package, skills_dir=skills_dir, receipt_file=receipt, profile="default")
    assert installed["status"] == "installed"
    assert (skills_dir / "sourcebrief-default" / "SKILL.md").exists()
    receipt_body = json.loads(receipt.read_text(encoding="utf-8"))
    assert receipt_body["package_hash"] == skill_install.load_package(package).package_hash
    assert "SOURCEBRIEF_TOKEN" not in receipt.read_text(encoding="utf-8")

    uninstalled = skill_install.uninstall(receipt)
    assert uninstalled["status"] == "uninstalled"
    assert not (skills_dir / "sourcebrief-default" / "SKILL.md").exists()
    assert not receipt.exists()


def test_skill_uninstall_fails_closed_when_installed_file_changed(tmp_path: Path) -> None:
    package = write_package(tmp_path / "package")
    skills_dir = tmp_path / "skills"
    receipt = tmp_path / "receipt.json"
    skill_install.install_package(package, skills_dir=skills_dir, receipt_file=receipt, profile="default")
    (skills_dir / "sourcebrief-default" / "SKILL.md").write_text("local edit\n", encoding="utf-8")

    with pytest.raises(skill_install.SkillInstallError, match="modified"):
        skill_install.uninstall(receipt)
    assert (skills_dir / "sourcebrief-default" / "SKILL.md").exists()

    removed = skill_install.uninstall(receipt, force=True)
    assert removed["files_removed"] >= 1


def test_skill_install_rejects_tampered_approved_package(tmp_path: Path) -> None:
    package = write_package(tmp_path / "package")
    (package / "SKILL.md").write_text("---\nname: sourcebrief-default\n---\nTampered instructions.\n", encoding="utf-8")

    with pytest.raises(skill_install.SkillInstallError, match="hash mismatch"):
        skill_install.load_package(package)


def test_skill_uninstall_rejects_receipt_paths_outside_skill_dir(tmp_path: Path) -> None:
    package = write_package(tmp_path / "package")
    skills_dir = tmp_path / "skills"
    receipt = tmp_path / "receipt.json"
    skill_install.install_package(package, skills_dir=skills_dir, receipt_file=receipt, profile="default")
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me\n", encoding="utf-8")
    receipt_body = json.loads(receipt.read_text(encoding="utf-8"))
    receipt_body["files"] = [
        {
            "package_path": "SKILL.md",
            "target_path": str(victim),
            "existed_before": False,
            "sha256_before": None,
            "sha256_after": skill_install.sha256_file(victim),
        }
    ]
    receipt.write_text(json.dumps(receipt_body) + "\n", encoding="utf-8")

    with pytest.raises(skill_install.SkillInstallError, match="escapes installed skill directory"):
        skill_install.uninstall(receipt)
    assert victim.exists()


def test_skill_install_rejects_unapproved_traversal_and_token_packages(tmp_path: Path) -> None:
    draft = write_package(tmp_path / "draft", status="draft")
    with pytest.raises(skill_install.SkillInstallError, match="approved"):
        skill_install.load_package(draft)

    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../SKILL.md", "escape")
        archive.writestr("manifest.json", json.dumps(_package_manifest()))
    with pytest.raises(skill_install.SkillInstallError, match="invalid package file path"):
        skill_install.load_package(traversal)

    token_pkg = write_package(tmp_path / "token-pkg")
    token_value = "cs_" + "x" * 24
    (token_pkg / "README.md").write_text(f"SOURCEBRIEF_TOKEN={token_value}\n", encoding="utf-8")
    with pytest.raises(skill_install.SkillInstallError, match="plaintext SourceBrief token"):
        skill_install.load_package(token_pkg)
