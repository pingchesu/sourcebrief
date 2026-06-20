from __future__ import annotations

import io
import os
import stat
import time
import zipfile
from pathlib import Path

import pytest

from sourcebrief_worker.bundle_ingest import (
    ZipRejectionError,
    assert_under_uploads,
    cleanup_stale_uploads,
    extract_zip_to_sandbox,
    validate_upload_staging_dir,
    validate_zip_before_extract,
)


def make_zip(entries: dict[str, bytes], *, attrs: dict[str, int] | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries.items():
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            if attrs and name in attrs:
                info.external_attr = attrs[name] << 16
            zf.writestr(info, payload)
    return buf.getvalue()


def write_zip(path: Path, entries: dict[str, bytes], *, attrs: dict[str, int] | None = None) -> Path:
    path.write_bytes(make_zip(entries, attrs=attrs))
    return path


def test_valid_zip_passes_validation(tmp_path: Path) -> None:
    zip_path = write_zip(tmp_path / "bundle.zip", {"README.md": b"hello", "src/app.py": b"print('ok')"})
    validate_zip_before_extract(zip_path)


def test_traversal_path_rejected(tmp_path: Path) -> None:
    zip_path = write_zip(tmp_path / "bad.zip", {"../secret.txt": b"no"})
    with pytest.raises(ZipRejectionError) as exc:
        validate_zip_before_extract(zip_path)
    assert exc.value.reason == "unsafe_entry"


def test_symlink_rejected(tmp_path: Path) -> None:
    zip_path = write_zip(
        tmp_path / "bad.zip",
        {"link": b"target"},
        attrs={"link": stat.S_IFLNK | 0o777},
    )
    with pytest.raises(ZipRejectionError) as exc:
        validate_zip_before_extract(zip_path)
    assert exc.value.reason == "unsafe_entry"


def test_zip_bomb_ratio(tmp_path: Path) -> None:
    zip_path = write_zip(tmp_path / "bomb.zip", {"big.txt": b"a" * 2_000_000})
    with pytest.raises(ZipRejectionError) as exc:
        validate_zip_before_extract(zip_path)
    assert exc.value.reason == "zip_bomb_ratio"


def test_zip_bomb_total_bytes(tmp_path: Path) -> None:
    zip_path = write_zip(tmp_path / "large.zip", {"big.txt": b"a" * 4096})
    with pytest.raises(ZipRejectionError) as exc:
        validate_zip_before_extract(zip_path, max_total_bytes=1024)
    assert exc.value.reason == "zip_bomb_total_bytes"


def test_zipfile_writestr_entries_classified_as_file(tmp_path: Path) -> None:
    zip_path = write_zip(tmp_path / "plain.zip", {"docs/a.md": b"alpha"})
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    rows = extract_zip_to_sandbox(zip_path, sandbox)
    assert rows[0]["normalized_path"] == "docs/a.md"
    assert rows[0]["status"] == "pending"
    assert rows[0]["text"] == "alpha"


def test_duplicate_normalized_path_rejected(tmp_path: Path) -> None:
    zip_path = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("README.md", b"first")
        zf.writestr("README.md", b"second")
    with pytest.raises(ZipRejectionError) as exc:
        validate_zip_before_extract(zip_path)
    assert exc.value.reason == "duplicate_path"


def test_path_prefix_conflict_rejected(tmp_path: Path) -> None:
    zip_path = tmp_path / "prefix.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("a", b"file")
        zf.writestr("a/b.txt", b"child")
    with pytest.raises(ZipRejectionError) as exc:
        validate_zip_before_extract(zip_path)
    assert exc.value.reason == "path_prefix_conflict"


def test_nested_archive_unsupported_not_extracted(tmp_path: Path) -> None:
    nested = make_zip({"inner.txt": b"inner"})
    zip_path = write_zip(tmp_path / "plain.zip", {"nested.zip": nested, "README.md": b"read"})
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    rows = extract_zip_to_sandbox(zip_path, sandbox)
    nested_row = next(row for row in rows if row["normalized_path"] == "nested.zip")
    assert nested_row["status"] == "unsupported"
    assert not (sandbox / "nested.zip").exists()


def test_safe_extract_dest_rejects_escape(tmp_path: Path) -> None:
    upload_root = tmp_path / "work"
    upload_path = validate_upload_staging_dir(upload_root, required_bytes=1)
    good = upload_path / "ok.zip"
    good.write_bytes(b"PK\x03\x04")
    assert assert_under_uploads(good, upload_root) == good.resolve()
    with pytest.raises(RuntimeError):
        assert_under_uploads(tmp_path / "elsewhere.zip", upload_root)


def test_cleanup_stale_uploads_deletes_only_old_uploads(tmp_path: Path) -> None:
    uploads = validate_upload_staging_dir(tmp_path / "work", required_bytes=1)
    old_zip = uploads / "old.zip"
    old_incoming = uploads / ".incoming-old.zip"
    new_zip = uploads / "new.zip"
    keep_txt = uploads / "old.txt"
    for path in (old_zip, old_incoming, new_zip, keep_txt):
        path.write_bytes(b"x")
    old_time = time.time() - 3600
    os.utime(old_zip, (old_time, old_time))
    os.utime(old_incoming, (old_time, old_time))
    os.utime(keep_txt, (old_time, old_time))
    result = cleanup_stale_uploads(tmp_path / "work", max_age_seconds=60)
    assert result["files_deleted"] == 2
    assert not old_zip.exists()
    assert not old_incoming.exists()
    assert new_zip.exists()
    assert keep_txt.exists()
