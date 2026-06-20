"""Safe multipart folder-bundle zip ingestion helpers.

This module is deliberately ORM-free. It validates zip archives before
extraction, extracts only safe regular files into a controlled sandbox, and
returns plain rows for the worker ingestion pipeline.
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import shutil
import stat
import time
import zipfile
from pathlib import Path

from sourcebrief_worker.manifest import (
    DEFAULT_MAX_MANIFEST_FILE_COUNT,
    DEFAULT_MAX_MANIFEST_TOTAL_BYTES,
    HARD_MAX_MANIFEST_FILE_COUNT,
    HARD_MAX_MANIFEST_TOTAL_BYTES,
    HARD_MAX_SINGLE_FILE_BYTES,
    ManifestPathError,
    normalize_path,
    validate_archive_entry,
)

logger = logging.getLogger(__name__)

HARD_MAX_ZIP_UPLOAD_BYTES = 100_000_000
DEFAULT_MAX_ZIP_UPLOAD_BYTES = 50_000_000
ZIP_BOMB_MAX_RATIO = 20
ZIP_BOMB_MIN_COMPRESSED = 1024

NESTED_ARCHIVE_EXTS = {
    ".zip", ".tar", ".tgz", ".gz", ".bz2", ".xz", ".7z", ".rar",
}
SKIP_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".tiff",
    ".pdf", ".zip", ".gz", ".tar", ".tgz", ".bz2", ".xz", ".7z", ".rar",
    ".jar", ".war", ".ear", ".class", ".so", ".dll", ".dylib", ".o", ".a",
    ".bin", ".exe", ".wasm", ".pyc", ".pyo", ".pdb",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp3", ".mp4", ".mov", ".avi", ".mkv", ".wav", ".flac", ".ogg", ".webm",
    ".db", ".sqlite", ".sqlite3", ".dat", ".iso", ".dmg", ".img",
}


class ZipRejectionError(ValueError):
    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        super().__init__(f"zip rejected: {reason}: {detail}")


def _is_text_file(data: bytes) -> bool:
    if not data:
        return True
    if b"\x00" in data[:8192]:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _archive_depth(name: str) -> int:
    normalized = name.replace("\\", "/").strip("/")
    if not normalized:
        return 0
    return max(0, len([part for part in normalized.split("/") if part]) - 1)


def classify_zip_entry(info: zipfile.ZipInfo) -> str:
    mode = info.external_attr >> 16
    if info.filename.endswith("/") or stat.S_ISDIR(mode):
        return "dir"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISBLK(mode) or stat.S_ISCHR(mode):
        return "device"
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISREG(mode):
        return "file"
    if mode & 0o170000 == 0:
        # Python zipfile.writestr() usually stores permission bits without a
        # file-type bit. Treat those normal entries as files rather than
        # rejecting all programmatically generated zips.
        return "file"
    return "other"


def _is_nested_archive(path: str) -> bool:
    lower = path.lower()
    return any(lower.endswith(ext) for ext in NESTED_ARCHIVE_EXTS)


def validate_zip_before_extract(
    zip_path: str | os.PathLike[str],
    *,
    max_file_count: int = DEFAULT_MAX_MANIFEST_FILE_COUNT,
    max_total_bytes: int = DEFAULT_MAX_MANIFEST_TOTAL_BYTES,
) -> None:
    max_file_count = min(max_file_count, HARD_MAX_MANIFEST_FILE_COUNT)
    max_total_bytes = min(max_total_bytes, HARD_MAX_MANIFEST_TOTAL_BYTES)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            infos = zf.infolist()
            total_compressed = 0
            total_uncompressed = 0
            file_count = 0
            seen_paths: set[str] = set()
            for info in infos:
                entry_type = classify_zip_entry(info)
                depth = _archive_depth(info.filename)
                try:
                    validate_archive_entry(info.filename, "dir" if entry_type == "dir" else entry_type, depth)
                except ManifestPathError as exc:
                    raise ZipRejectionError("unsafe_entry", f"{exc.reason}: {info.filename}") from exc
                if entry_type == "file":
                    normalized = normalize_path(info.filename)
                    conflict = next(
                        (
                            path
                            for path in seen_paths
                            if path == normalized or path.startswith(normalized + "/") or normalized.startswith(path + "/")
                        ),
                        None,
                    )
                    if conflict is not None:
                        reason = "duplicate_path" if conflict == normalized else "path_prefix_conflict"
                        raise ZipRejectionError(reason, f"{normalized} conflicts with {conflict}")
                    seen_paths.add(normalized)
                    file_count += 1
                    total_compressed += max(0, info.compress_size)
                    total_uncompressed += max(0, info.file_size)
            if file_count > max_file_count:
                raise ZipRejectionError("too_many_files", f"{file_count}>{max_file_count}")
            if total_uncompressed > max_total_bytes:
                raise ZipRejectionError("zip_bomb_total_bytes", f"{total_uncompressed}>{max_total_bytes}")
            if total_uncompressed and total_compressed == 0:
                raise ZipRejectionError("zip_bomb_ratio", "non-empty archive reports zero compressed bytes")
            if total_compressed >= ZIP_BOMB_MIN_COMPRESSED and total_uncompressed / total_compressed > ZIP_BOMB_MAX_RATIO:
                raise ZipRejectionError("zip_bomb_ratio", f"ratio={total_uncompressed / total_compressed:.1f}")
    except zipfile.BadZipFile as exc:
        raise ZipRejectionError("not_a_zip", str(exc)) from exc


def _safe_extract_dest(dest: str | os.PathLike[str], sandbox_dir: str | os.PathLike[str]) -> None:
    resolved = os.path.realpath(dest)
    sandbox_real = os.path.realpath(sandbox_dir)
    if resolved != sandbox_real and not resolved.startswith(sandbox_real + os.sep):
        raise ZipRejectionError("unsafe_entry", f"extraction path escapes sandbox: {dest!r}")


def extract_zip_to_sandbox(
    zip_path: str | os.PathLike[str],
    sandbox_dir: str | os.PathLike[str],
    *,
    max_file_count: int = DEFAULT_MAX_MANIFEST_FILE_COUNT,
    max_total_bytes: int = DEFAULT_MAX_MANIFEST_TOTAL_BYTES,
) -> list[dict]:
    validate_zip_before_extract(zip_path, max_file_count=max_file_count, max_total_bytes=max_total_bytes)
    rows: list[dict] = []
    total_bytes_written = 0
    files_extracted = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            entry_type = classify_zip_entry(info)
            if entry_type == "dir":
                continue
            normalized = normalize_path(info.filename)
            mime_type, _encoding = mimetypes.guess_type(normalized)
            if _is_nested_archive(normalized):
                rows.append(_manifest_row(normalized, info, b"", "unsupported", mime_type=mime_type))
                continue
            if info.file_size > HARD_MAX_SINGLE_FILE_BYTES:
                rows.append(_manifest_row(normalized, info, b"", "skipped", mime_type=mime_type, warnings=["file exceeds hard per-file limit"]))
                continue
            if files_extracted >= max_file_count or total_bytes_written + info.file_size > max_total_bytes:
                rows.append(_manifest_row(normalized, info, b"", "skipped", mime_type=mime_type, warnings=["folder bundle quota exceeded"]))
                continue
            dest = os.path.join(str(sandbox_dir), normalized)
            _safe_extract_dest(dest, sandbox_dir)
            raw = zf.read(info)
            if len(raw) > HARD_MAX_SINGLE_FILE_BYTES:
                rows.append(_manifest_row(normalized, info, b"", "skipped", mime_type=mime_type, warnings=["file exceeds hard per-file limit"]))
                continue
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "wb") as fh:
                fh.write(raw)
            total_bytes_written += len(raw)
            files_extracted += 1
            ext = os.path.splitext(normalized)[1].lower()
            status = "pending" if ext not in SKIP_EXTS and _is_text_file(raw[:8192]) else "unsupported"
            row = _manifest_row(normalized, info, raw, status, mime_type=mime_type)
            if status == "pending":
                row["text"] = raw.decode("utf-8", errors="replace")
            rows.append(row)
    return rows


def _manifest_row(
    normalized: str,
    info: zipfile.ZipInfo,
    raw: bytes,
    status: str,
    *,
    mime_type: str | None = None,
    warnings: list[str] | None = None,
) -> dict:
    content_hash = f"sha256:{hashlib.sha256(raw).hexdigest()}"
    return {
        "normalized_path": normalized,
        "display_path": info.filename,
        "content_hash": content_hash,
        "size_bytes": info.file_size,
        "mime_type": mime_type,
        "status": status,
        "warnings_json": list(warnings or []),
    }


def uploads_dir(work_base: str | os.PathLike[str]) -> Path:
    return Path(work_base).resolve() / "uploads"


def validate_upload_staging_dir(work_base: str | os.PathLike[str], *, required_bytes: int = HARD_MAX_ZIP_UPLOAD_BYTES) -> Path:
    directory = uploads_dir(work_base)
    directory.mkdir(parents=True, exist_ok=True)
    probe = directory / ".probe"
    try:
        probe.write_text("ok")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise RuntimeError(f"upload staging directory is not writable: {directory}") from exc
    usage = shutil.disk_usage(directory)
    if usage.free < required_bytes:
        logger.warning("upload staging directory low on disk", extra={"free_bytes": usage.free, "required_bytes": required_bytes})
        raise RuntimeError("upload staging directory has insufficient free disk")
    return directory


def assert_under_uploads(path: str | os.PathLike[str], work_base: str | os.PathLike[str]) -> Path:
    directory = uploads_dir(work_base)
    real_directory = directory.resolve()
    real_path = Path(path).resolve()
    if real_path != real_directory and real_directory not in real_path.parents:
        raise RuntimeError("staged zip path is outside work_base/uploads")
    return real_path


def cleanup_stale_uploads(work_base: str | os.PathLike[str], max_age_seconds: int = 86_400) -> dict:
    directory = uploads_dir(work_base)
    if not directory.exists():
        return {"files_deleted": 0, "bytes_deleted": 0, "failures": 0}
    cutoff = time.time() - max_age_seconds
    files_deleted = 0
    bytes_deleted = 0
    failures = 0
    for path in directory.iterdir():
        if not path.is_file() or not (path.name.endswith(".zip") or path.name.startswith(".incoming-")):
            continue
        try:
            real_path = assert_under_uploads(path, work_base)
            stat_result = real_path.stat()
            if stat_result.st_mtime > cutoff:
                continue
            bytes_deleted += stat_result.st_size
            real_path.unlink()
            files_deleted += 1
        except OSError:
            failures += 1
            logger.exception("failed to cleanup stale upload", extra={"path": str(path)})
    result = {"files_deleted": files_deleted, "bytes_deleted": bytes_deleted, "failures": failures}
    if files_deleted or failures:
        logger.info("stale upload cleanup complete", extra=result)
    return result
