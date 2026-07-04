from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RECEIPT_SCHEMA_VERSION = "sourcebrief.skill-install-receipt.v1"
DEFAULT_RECEIPT_DIR = Path("~/.sourcebrief/skill-receipts")
DEFAULT_SKILLS_DIR = Path("~/.hermes/skills")
_ALLOWED_TOP_LEVEL_FILES = {"SKILL.md", "README.md", "manifest.json", "manifest.hash.json"}
_ALLOWED_TOP_LEVEL_DIRS = {"references", "examples", "scripts"}
_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
_TOKEN_VALUE_RE = re.compile(r"(?i)(sourcebrief|contextsmith)[_-]?token\s*=\s*['\"]?[A-Za-z0-9_./+=:-]{12,}")


class SkillInstallError(RuntimeError):
    """User-facing skill install error."""


@dataclass(frozen=True)
class LoadedPackage:
    source: Path
    manifest: dict[str, Any]
    files: dict[str, bytes]
    package_hash: str


def canonical_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _canonical_package_json(data: Any) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.exists():
        return None
    return sha256_bytes(path.read_bytes())


def default_skills_dir(profile: str = "default") -> Path:
    if profile == "default":
        return DEFAULT_SKILLS_DIR.expanduser()
    if not _SKILL_NAME_RE.match(profile):
        raise SkillInstallError("Hermes profile names must be simple lowercase slugs")
    return (Path("~/.hermes/profiles") / profile / "skills").expanduser()


def receipt_path(path: str | None = None) -> Path:
    if path:
        return Path(path).expanduser()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    suffix = uuid.uuid4().hex[:8]
    return (DEFAULT_RECEIPT_DIR / f"sourcebrief-skill-{stamp}-{suffix}.json").expanduser()


def _validate_package_path(path: str) -> str:
    normalized = path.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if normalized.startswith("/") or ".." in parts or not parts:
        raise SkillInstallError(f"invalid package file path: {path!r}")
    if len(parts) == 1:
        if parts[0] not in _ALLOWED_TOP_LEVEL_FILES:
            raise SkillInstallError(f"unsupported top-level package file: {path!r}")
    elif parts[0] not in _ALLOWED_TOP_LEVEL_DIRS:
        raise SkillInstallError(f"unsupported package directory: {path!r}")
    return "/".join(parts)


def _load_package_dir(path: Path) -> dict[str, bytes]:
    if not path.is_dir():
        raise SkillInstallError(f"package path is not a directory: {path}")
    files: dict[str, bytes] = {}
    for child in sorted(path.rglob("*")):
        if child.is_symlink():
            raise SkillInstallError(f"package contains symlink: {child.relative_to(path)}")
        if not child.is_file():
            continue
        rel = _validate_package_path(child.relative_to(path).as_posix())
        files[rel] = child.read_bytes()
    return files


def _load_package_zip(path: Path) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    try:
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                rel = _validate_package_path(info.filename)
                files[rel] = archive.read(info)
    except zipfile.BadZipFile as exc:
        raise SkillInstallError(f"package zip is invalid: {path}") from exc
    return files


def _detect_plaintext_token(files: dict[str, bytes]) -> None:
    for rel, content in files.items():
        text = content.decode("utf-8", errors="ignore")
        if _TOKEN_VALUE_RE.search(text):
            raise SkillInstallError(f"package file {rel} appears to contain a plaintext SourceBrief token")


def _load_manifest(files: dict[str, bytes]) -> dict[str, Any]:
    raw = files.get("manifest.json")
    if raw is None:
        raise SkillInstallError("package is missing manifest.json")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SkillInstallError("manifest.json is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise SkillInstallError("manifest.json must be a JSON object")
    if manifest.get("package_kind") != "sourcebrief_skill_pack":
        raise SkillInstallError("manifest package_kind must be sourcebrief_skill_pack")
    if manifest.get("export_status") != "approved":
        raise SkillInstallError("skill package must be approved before local install")
    if not isinstance(manifest.get("package_hash"), str) or not str(manifest.get("package_hash")).startswith("sha256:"):
        raise SkillInstallError("manifest is missing package_hash")
    if "SKILL.md" not in files:
        raise SkillInstallError("package is missing SKILL.md")
    return manifest


def _verify_package_integrity(files: dict[str, bytes], manifest: dict[str, Any]) -> None:
    package_inputs = manifest.get("package_hash_inputs")
    if not isinstance(package_inputs, dict):
        raise SkillInstallError("manifest is missing package_hash_inputs")
    input_files = package_inputs.get("files")
    if not isinstance(input_files, list):
        raise SkillInstallError("manifest package_hash_inputs.files must be a list")
    listed: set[str] = set()
    for item in input_files:
        if not isinstance(item, dict):
            raise SkillInstallError("manifest package_hash_inputs.files entries must be objects")
        rel = _validate_package_path(str(item.get("path") or ""))
        if rel == "manifest.json":
            raise SkillInstallError("manifest.json must not be part of package_hash_inputs.files")
        if rel in listed:
            raise SkillInstallError(f"duplicate package_hash_inputs file: {rel}")
        content = files.get(rel)
        if content is None:
            raise SkillInstallError(f"package is missing integrity-listed file: {rel}")
        if item.get("sha256") != sha256_bytes(content):
            raise SkillInstallError(f"package file hash mismatch: {rel}")
        if item.get("bytes") != len(content):
            raise SkillInstallError(f"package file byte count mismatch: {rel}")
        listed.add(rel)
    extra_files = set(files) - {"manifest.json"} - listed
    if extra_files:
        raise SkillInstallError(f"package contains files not covered by package_hash_inputs: {', '.join(sorted(extra_files))}")
    computed_package_hash = sha256_bytes((_canonical_package_json(package_inputs) + "\n").encode("utf-8"))
    if manifest.get("package_hash") != computed_package_hash:
        raise SkillInstallError("manifest package_hash does not match package_hash_inputs")


def load_package(path: Path) -> LoadedPackage:
    source = path.expanduser()
    files = _load_package_zip(source) if source.suffix.lower() == ".zip" else _load_package_dir(source)
    files = {_validate_package_path(rel): content for rel, content in files.items()}
    _detect_plaintext_token(files)
    manifest = _load_manifest(files)
    _verify_package_integrity(files, manifest)
    return LoadedPackage(source=source, manifest=manifest, files=files, package_hash=str(manifest["package_hash"]))


def default_skill_name(manifest: dict[str, Any]) -> str:
    pack_key = str(manifest.get("pack_key") or "default")
    safe = re.sub(r"[^a-z0-9_-]+", "-", pack_key.lower().replace("_", "-"))
    safe = safe.strip("-") or "default"
    return f"sourcebrief-{safe}"[:64]


def _validate_skill_name(name: str) -> str:
    if not _SKILL_NAME_RE.match(name):
        raise SkillInstallError("skill name must match ^[a-z0-9][a-z0-9_-]{1,63}$")
    return name


def _target_paths(package: LoadedPackage, skills_dir: Path, skill_name: str) -> dict[str, Path]:
    skill_root = (skills_dir / skill_name).expanduser()
    try:
        root_resolved = skill_root.resolve(strict=False)
    except OSError as exc:
        raise SkillInstallError(f"invalid skill root: {skill_root}") from exc
    result: dict[str, Path] = {}
    for rel in package.files:
        safe_rel = _validate_package_path(rel)
        target = skill_root / safe_rel
        try:
            resolved = target.resolve(strict=False)
        except OSError as exc:
            raise SkillInstallError(f"invalid target path for {rel}") from exc
        if root_resolved != resolved and root_resolved not in resolved.parents:
            raise SkillInstallError(f"package path escapes skill directory: {rel}")
        result[safe_rel] = target
    return result


def dry_run_install(package_path: Path, *, skills_dir: Path, profile: str, skill_name: str | None = None) -> dict[str, Any]:
    package = load_package(package_path)
    name = _validate_skill_name(skill_name or default_skill_name(package.manifest))
    targets = _target_paths(package, skills_dir.expanduser(), name)
    return {
        "status": "dry_run",
        "target": "hermes",
        "profile": profile,
        "skill_name": name,
        "skill_dir": str(skills_dir.expanduser() / name),
        "package_hash": package.package_hash,
        "context_pack": {"pack_key": package.manifest.get("pack_key"), "version": package.manifest.get("pack_version")},
        "operations": [
            {
                "op": "write",
                "package_path": rel,
                "target_path": str(target),
                "exists": target.exists(),
                "current_sha256": sha256_file(target),
                "new_sha256": sha256_bytes(package.files[rel]),
            }
            for rel, target in sorted(targets.items())
        ],
    }


def _atomic_write(path: Path, content: bytes, *, mode_from: Path | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        if mode_from is not None and mode_from.exists():
            tmp_path.chmod(mode_from.stat().st_mode & 0o777)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def install_package(
    package_path: Path,
    *,
    skills_dir: Path,
    receipt_file: Path,
    profile: str,
    skill_name: str | None = None,
    force: bool = False,
) -> dict[str, Any]:
    package = load_package(package_path)
    name = _validate_skill_name(skill_name or default_skill_name(package.manifest))
    skills_root = skills_dir.expanduser()
    targets = _target_paths(package, skills_root, name)
    if receipt_file.suffix.lower() != ".json":
        raise SkillInstallError("receipt path must end in .json")
    file_records: list[dict[str, Any]] = []
    for rel, target in sorted(targets.items()):
        before_hash = sha256_file(target)
        new_hash = sha256_bytes(package.files[rel])
        if target.exists() and before_hash != new_hash and not force:
            raise SkillInstallError(f"target file already exists and differs; use --force to overwrite: {target}")
        file_records.append(
            {
                "package_path": rel,
                "target_path": str(target),
                "existed_before": target.exists(),
                "sha256_before": before_hash,
                "sha256_after": new_hash,
            }
        )
    for record in file_records:
        target = Path(str(record["target_path"]))
        _atomic_write(target, package.files[str(record["package_path"])], mode_from=target if target.exists() else None)
        if str(record["package_path"]).startswith("scripts/"):
            target.chmod(target.stat().st_mode | 0o111)
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "target": "hermes",
        "profile": profile,
        "skill_name": name,
        "skill_dir": str(skills_root / name),
        "installed_at": datetime.now(UTC).isoformat(),
        "package_source": str(package.source),
        "package_hash": package.package_hash,
        "context_pack": {"pack_key": package.manifest.get("pack_key"), "version": package.manifest.get("pack_version"), "pack_hash": package.manifest.get("pack_hash")},
        "files": file_records,
    }
    receipt_file = receipt_file.expanduser()
    _atomic_write(receipt_file, (canonical_json(receipt) + "\n").encode("utf-8"))
    receipt_file.chmod(0o600)
    return {"status": "installed", "target": "hermes", "profile": profile, "skill_name": name, "skill_dir": str(skills_root / name), "receipt": str(receipt_file), "package_hash": package.package_hash, "files_written": len(file_records)}


def _load_receipt(path: Path) -> dict[str, Any]:
    try:
        receipt = json.loads(path.expanduser().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillInstallError(f"invalid receipt: {path}") from exc
    if not isinstance(receipt, dict) or receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise SkillInstallError("unsupported skill install receipt")
    if not isinstance(receipt.get("files"), list):
        raise SkillInstallError("receipt files must be a list")
    return receipt


def _resolve_contained_path(root: Path, target: Path, *, kind: str) -> Path:
    root_resolved = root.expanduser().resolve(strict=False)
    target_resolved = target.expanduser().resolve(strict=False)
    if target_resolved != root_resolved and root_resolved not in target_resolved.parents:
        raise SkillInstallError(f"receipt {kind} escapes installed skill directory: {target}")
    return target_resolved


def uninstall(receipt_file: Path, *, force: bool = False) -> dict[str, Any]:
    receipt_path_expanded = receipt_file.expanduser()
    receipt = _load_receipt(receipt_path_expanded)
    skill_dir = Path(str(receipt.get("skill_dir"))).expanduser()
    skill_root = skill_dir.resolve(strict=False)
    files = list(receipt["files"])
    removed: list[str] = []
    for record in files:
        target = Path(str(record.get("target_path", ""))).expanduser()
        target_resolved = _resolve_contained_path(skill_root, target, kind="target_path")
        if not target_resolved.exists():
            continue
        current_hash = sha256_file(target_resolved)
        expected_hash = record.get("sha256_after")
        if current_hash != expected_hash and not force:
            raise SkillInstallError(f"installed file was modified; use --force to remove: {target_resolved}")
    for record in reversed(files):
        target = Path(str(record.get("target_path", ""))).expanduser()
        target_resolved = _resolve_contained_path(skill_root, target, kind="target_path")
        if target_resolved.exists():
            target_resolved.unlink()
            removed.append(str(target_resolved))
            parent = target_resolved.parent
            while parent != skill_root.parent and parent.exists() and (parent == skill_root or skill_root in parent.parents):
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
    if receipt_path_expanded.exists():
        receipt_path_expanded.unlink()
    return {"status": "uninstalled", "target": receipt.get("target"), "profile": receipt.get("profile"), "skill_name": receipt.get("skill_name"), "receipt": str(receipt_path_expanded), "files_removed": len(removed)}


def write_export_files(export: dict[str, Any], out_dir: Path, *, force: bool = False) -> dict[str, Any]:
    files = export.get("files")
    if not isinstance(files, list):
        raise SkillInstallError("skill export response does not include files")
    out = out_dir.expanduser()
    written: list[str] = []
    for file in files:
        if not isinstance(file, dict):
            raise SkillInstallError("skill export file entry must be an object")
        rel = _validate_package_path(str(file.get("path") or ""))
        content = file.get("content")
        if not isinstance(content, str):
            raise SkillInstallError(f"skill export file {rel} is missing content")
        target = out / rel
        if target.exists() and not force:
            raise SkillInstallError(f"output file already exists; use --force to overwrite: {target}")
        _atomic_write(target, content.encode("utf-8"), mode_from=target if target.exists() else None)
        written.append(str(target))
    return {"status": "written", "path": str(out), "files_written": len(written)}
