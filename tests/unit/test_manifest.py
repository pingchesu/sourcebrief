"""Unit tests for contextsmith_worker.manifest — pure Python, no DB or network."""

from __future__ import annotations

import pytest

from contextsmith_worker.manifest import (
    MAX_ARCHIVE_DEPTH,
    MAX_PATH_LENGTH,
    ManifestPathError,
    compute_manifest_hash,
    normalize_path,
    validate_archive_entry,
)

# ---------------------------------------------------------------------------
# normalize_path — valid cases
# ---------------------------------------------------------------------------


def test_normalize_simple() -> None:
    assert normalize_path("docs/guide.md") == "docs/guide.md"


def test_normalize_backslash() -> None:
    assert normalize_path("docs\\guide.md") == "docs/guide.md"


def test_normalize_trailing_slash() -> None:
    assert normalize_path("docs/") == "docs"


def test_normalize_dot_component() -> None:
    assert normalize_path("a/./b") == "a/b"


def test_normalize_consecutive_slashes() -> None:
    assert normalize_path("a//b") == "a/b"


# ---------------------------------------------------------------------------
# normalize_path — rejection cases
# ---------------------------------------------------------------------------


def test_normalize_absolute_rejected() -> None:
    with pytest.raises(ManifestPathError) as exc_info:
        normalize_path("/etc/passwd")
    assert exc_info.value.reason == "absolute_path"


def test_normalize_traversal_simple() -> None:
    with pytest.raises(ManifestPathError) as exc_info:
        normalize_path("../etc/passwd")
    assert exc_info.value.reason == "path_traversal"


def test_normalize_traversal_embedded() -> None:
    with pytest.raises(ManifestPathError) as exc_info:
        normalize_path("docs/../../../etc/passwd")
    assert exc_info.value.reason == "path_traversal"


def test_normalize_traversal_windows() -> None:
    with pytest.raises(ManifestPathError) as exc_info:
        normalize_path("docs\\..\\..\\etc\\passwd")
    assert exc_info.value.reason == "path_traversal"


def test_normalize_windows_drive_path_rejected() -> None:
    with pytest.raises(ManifestPathError) as exc_info:
        normalize_path("C:\\Users\\alice\\secrets.txt")
    assert exc_info.value.reason == "absolute_path"


def test_normalize_empty_string() -> None:
    with pytest.raises(ManifestPathError) as exc_info:
        normalize_path("")
    assert exc_info.value.reason == "empty_path"


def test_normalize_whitespace_only() -> None:
    with pytest.raises(ManifestPathError) as exc_info:
        normalize_path("   ")
    assert exc_info.value.reason == "empty_path"


def test_normalize_only_dots_rejected() -> None:
    # "." collapses to an empty component list → empty_path
    with pytest.raises(ManifestPathError) as exc_info:
        normalize_path(".")
    assert exc_info.value.reason == "empty_path"


def test_normalize_path_too_long() -> None:
    # "a/" * 513 = 1026 chars raw; normalizes to 1025 chars > MAX_PATH_LENGTH
    long_path = "a/" * 513
    with pytest.raises(ManifestPathError) as exc_info:
        normalize_path(long_path)
    assert exc_info.value.reason == "path_too_long"


def test_normalize_null_byte_rejected() -> None:
    with pytest.raises(ManifestPathError) as exc_info:
        normalize_path("docs/\x00evil.md")
    assert exc_info.value.reason == "invalid_characters"


def test_normalize_control_character_rejected() -> None:
    with pytest.raises(ManifestPathError) as exc_info:
        normalize_path("docs/evil\nname.md")
    assert exc_info.value.reason == "invalid_characters"


def test_normalize_path_at_exactly_max_length_passes() -> None:
    # Construct a path whose normalized length is exactly MAX_PATH_LENGTH
    # Use a single component of exactly MAX_PATH_LENGTH chars
    component = "a" * MAX_PATH_LENGTH
    result = normalize_path(component)
    assert len(result) == MAX_PATH_LENGTH


def test_normalize_path_one_over_max_rejected() -> None:
    component = "a" * (MAX_PATH_LENGTH + 1)
    with pytest.raises(ManifestPathError) as exc_info:
        normalize_path(component)
    assert exc_info.value.reason == "path_too_long"


# ---------------------------------------------------------------------------
# validate_archive_entry — valid cases
# ---------------------------------------------------------------------------


def test_validate_entry_file_ok() -> None:
    validate_archive_entry("a/b/c.md", "file", depth=2)  # no exception


def test_validate_entry_dir_ok() -> None:
    validate_archive_entry("a", "dir", depth=0)  # no exception


def test_validate_entry_max_depth_ok() -> None:
    validate_archive_entry("a/b.txt", "file", depth=MAX_ARCHIVE_DEPTH)  # exactly at limit


# ---------------------------------------------------------------------------
# validate_archive_entry — rejection cases
# ---------------------------------------------------------------------------


def test_validate_entry_symlink() -> None:
    with pytest.raises(ManifestPathError) as exc_info:
        validate_archive_entry("a/link", "symlink", depth=1)
    assert exc_info.value.reason == "unsafe_entry_type"


def test_validate_entry_hardlink() -> None:
    with pytest.raises(ManifestPathError) as exc_info:
        validate_archive_entry("a/link", "hardlink", depth=1)
    assert exc_info.value.reason == "unsafe_entry_type"


def test_validate_entry_device() -> None:
    with pytest.raises(ManifestPathError) as exc_info:
        validate_archive_entry("dev/null", "device", depth=1)
    assert exc_info.value.reason == "unsafe_entry_type"


def test_validate_entry_socket() -> None:
    with pytest.raises(ManifestPathError) as exc_info:
        validate_archive_entry("var/run/foo.sock", "socket", depth=2)
    assert exc_info.value.reason == "unsafe_entry_type"


def test_validate_entry_fifo() -> None:
    with pytest.raises(ManifestPathError) as exc_info:
        validate_archive_entry("pipes/input", "fifo", depth=1)
    assert exc_info.value.reason == "unsafe_entry_type"


def test_validate_entry_other() -> None:
    with pytest.raises(ManifestPathError) as exc_info:
        validate_archive_entry("unknown", "other", depth=0)
    assert exc_info.value.reason == "unsafe_entry_type"


def test_validate_entry_max_depth() -> None:
    with pytest.raises(ManifestPathError) as exc_info:
        validate_archive_entry("a/b.txt", "file", depth=MAX_ARCHIVE_DEPTH + 1)
    assert exc_info.value.reason == "archive_too_deep"


def test_validate_entry_traversal_in_name() -> None:
    with pytest.raises(ManifestPathError) as exc_info:
        validate_archive_entry("../evil", "file", depth=0)
    assert exc_info.value.reason == "path_traversal"


def test_validate_entry_absolute_in_name() -> None:
    with pytest.raises(ManifestPathError) as exc_info:
        validate_archive_entry("/etc/passwd", "file", depth=0)
    assert exc_info.value.reason == "absolute_path"


# ---------------------------------------------------------------------------
# compute_manifest_hash
# ---------------------------------------------------------------------------

_SAMPLE_ROWS = [
    {"normalized_path": "docs/a.md", "content_hash": "sha256:aaa", "size_bytes": 100, "parser": "markdown", "parser_version": "1"},
    {"normalized_path": "src/b.py", "content_hash": "sha256:bbb", "size_bytes": 200, "parser": "python", "parser_version": "1"},
]


def test_manifest_hash_deterministic() -> None:
    h1 = compute_manifest_hash(list(_SAMPLE_ROWS))
    h2 = compute_manifest_hash(list(_SAMPLE_ROWS))
    assert h1 == h2
    assert h1.startswith("sha256:")


def test_manifest_hash_order_independent() -> None:
    h1 = compute_manifest_hash([_SAMPLE_ROWS[0], _SAMPLE_ROWS[1]])
    h2 = compute_manifest_hash([_SAMPLE_ROWS[1], _SAMPLE_ROWS[0]])
    assert h1 == h2


def test_manifest_hash_differs_on_content() -> None:
    modified = [dict(_SAMPLE_ROWS[0], content_hash="sha256:changed"), _SAMPLE_ROWS[1]]
    assert compute_manifest_hash(_SAMPLE_ROWS) != compute_manifest_hash(modified)


def test_manifest_hash_differs_on_path() -> None:
    modified = [dict(_SAMPLE_ROWS[0], normalized_path="docs/renamed.md"), _SAMPLE_ROWS[1]]
    assert compute_manifest_hash(_SAMPLE_ROWS) != compute_manifest_hash(modified)


def test_manifest_hash_differs_on_parser_version() -> None:
    modified = [dict(_SAMPLE_ROWS[0], parser_version="2"), _SAMPLE_ROWS[1]]
    assert compute_manifest_hash(_SAMPLE_ROWS) != compute_manifest_hash(modified)


def test_manifest_hash_ignores_mtime() -> None:
    rows_no_mtime = [{"normalized_path": "a.md", "content_hash": "sha256:abc", "size_bytes": 10}]
    rows_with_mtime = [{"normalized_path": "a.md", "content_hash": "sha256:abc", "size_bytes": 10, "mtime_client": "2026-01-01T00:00:00Z"}]
    assert compute_manifest_hash(rows_no_mtime) == compute_manifest_hash(rows_with_mtime)


def test_manifest_hash_canonicalizes_missing_nullable_parser_fields() -> None:
    missing = [{"normalized_path": "a.md", "content_hash": "sha256:abc", "size_bytes": 10}]
    nulls = [
        {
            "normalized_path": "a.md",
            "content_hash": "sha256:abc",
            "size_bytes": 10,
            "parser": None,
            "parser_version": None,
        }
    ]
    empty = [
        {
            "normalized_path": "a.md",
            "content_hash": "sha256:abc",
            "size_bytes": 10,
            "parser": "",
            "parser_version": "",
        }
    ]
    assert compute_manifest_hash(missing) == compute_manifest_hash(nulls)
    assert compute_manifest_hash(missing) == compute_manifest_hash(empty)


def test_manifest_hash_ignores_mime_type() -> None:
    rows_a = [{"normalized_path": "a.md", "content_hash": "sha256:abc", "size_bytes": 10, "mime_type": "text/markdown"}]
    rows_b = [{"normalized_path": "a.md", "content_hash": "sha256:abc", "size_bytes": 10, "mime_type": "application/octet-stream"}]
    assert compute_manifest_hash(rows_a) == compute_manifest_hash(rows_b)


def test_manifest_hash_ignores_display_path() -> None:
    rows_a = [{"normalized_path": "a/b.md", "content_hash": "sha256:abc", "size_bytes": 10, "display_path": "a\\b.md"}]
    rows_b = [{"normalized_path": "a/b.md", "content_hash": "sha256:abc", "size_bytes": 10, "display_path": "a/b.md"}]
    assert compute_manifest_hash(rows_a) == compute_manifest_hash(rows_b)


def test_manifest_hash_ignores_status() -> None:
    rows_a = [{"normalized_path": "a.md", "content_hash": "sha256:abc", "size_bytes": 10, "status": "pending"}]
    rows_b = [{"normalized_path": "a.md", "content_hash": "sha256:abc", "size_bytes": 10, "status": "parsed"}]
    assert compute_manifest_hash(rows_a) == compute_manifest_hash(rows_b)


def test_manifest_hash_empty_list() -> None:
    h = compute_manifest_hash([])
    assert h.startswith("sha256:")
    # Two empty lists produce the same hash
    assert compute_manifest_hash([]) == h


def test_manifest_hash_missing_optional_keys_default() -> None:
    # Rows with missing parser/parser_version should hash the same as rows with empty strings
    rows_missing = [{"normalized_path": "a.md", "content_hash": "sha256:abc", "size_bytes": 10}]
    rows_empty = [{"normalized_path": "a.md", "content_hash": "sha256:abc", "size_bytes": 10, "parser": "", "parser_version": ""}]
    assert compute_manifest_hash(rows_missing) == compute_manifest_hash(rows_empty)


# ---------------------------------------------------------------------------
# ManifestPathError structure
# ---------------------------------------------------------------------------


def test_manifest_path_error_attributes() -> None:
    err = ManifestPathError(reason="path_traversal", path="../evil")
    assert err.reason == "path_traversal"
    assert err.path == "../evil"
    assert isinstance(err, ValueError)
    assert "path_traversal" in str(err)


def test_manifest_path_error_default_path() -> None:
    err = ManifestPathError(reason="empty_path")
    assert err.path == ""
