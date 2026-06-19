"""Pure path-safety and manifest-hash helpers for Milestone A1.

No database imports, no network imports, no subprocess calls, no filesystem
reads. Every function is fully testable without a running server.
"""

from __future__ import annotations

import hashlib
import json

# ---------------------------------------------------------------------------
# Quota constants
# ---------------------------------------------------------------------------

# Soft limits: defaults for new resources unless overridden by project config
DEFAULT_MAX_MANIFEST_FILE_COUNT = 10_000
DEFAULT_MAX_MANIFEST_TOTAL_BYTES = 500_000_000  # 500 MB

# Hard limits: cannot be exceeded regardless of config
HARD_MAX_MANIFEST_FILE_COUNT = 50_000
HARD_MAX_MANIFEST_TOTAL_BYTES = 2_000_000_000  # 2 GB

# Per-file limits
MAX_SINGLE_FILE_BYTES = 50_000_000  # 50 MB
HARD_MAX_SINGLE_FILE_BYTES = 200_000_000  # 200 MB

# Path constraints
MAX_PATH_LENGTH = 512
MAX_ARCHIVE_DEPTH = 10

# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------

_VALID_ENTRY_TYPES = frozenset({"file", "dir"})


class ManifestPathError(ValueError):
    def __init__(self, reason: str, path: str = "") -> None:
        self.reason = reason
        self.path = path
        super().__init__(f"manifest path error: {reason!r} path={path!r}")


# ---------------------------------------------------------------------------
# normalize_path
# ---------------------------------------------------------------------------


def normalize_path(raw: str) -> str:
    """Convert an arbitrary client-supplied path to a canonical POSIX-safe relative path.

    Raises ManifestPathError on any rejection. Never consults the real filesystem.
    """
    raw = raw.strip()

    if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
        raise ManifestPathError(reason="invalid_characters", path=raw)

    if not raw:
        raise ManifestPathError(reason="empty_path", path=raw)

    raw = raw.replace("\\", "/")

    if raw.startswith("/") or _looks_like_windows_drive_path(raw):
        raise ManifestPathError(reason="absolute_path", path=raw)

    components: list[str] = []
    for component in raw.split("/"):
        if not component:
            # empty component from consecutive slashes or trailing slash
            continue
        if component == "..":
            raise ManifestPathError(reason="path_traversal", path=raw)
        if component == ".":
            continue
        components.append(component)

    if not components:
        raise ManifestPathError(reason="empty_path", path=raw)

    result = "/".join(components)

    if len(result) > MAX_PATH_LENGTH:
        raise ManifestPathError(reason="path_too_long", path=raw)

    return result


def _looks_like_windows_drive_path(path: str) -> bool:
    """Return True for Windows drive-prefixed paths such as C:/repo or C:repo."""
    return len(path) >= 2 and path[1] == ":" and path[0].isalpha()


# ---------------------------------------------------------------------------
# validate_archive_entry
# ---------------------------------------------------------------------------


def validate_archive_entry(name: str, entry_type: str, depth: int) -> None:
    """Validate a single archive entry before any content is extracted.

    Raises ManifestPathError on rejection. Callers must classify entry_type
    from the archive library (zipfile vs tarfile) before calling this.
    """
    if entry_type not in _VALID_ENTRY_TYPES:
        raise ManifestPathError(reason="unsafe_entry_type", path=name)

    if depth > MAX_ARCHIVE_DEPTH:
        raise ManifestPathError(reason="archive_too_deep", path=name)

    normalize_path(name)  # re-raises ManifestPathError as-is on any path violation


# ---------------------------------------------------------------------------
# compute_manifest_hash
# ---------------------------------------------------------------------------


def compute_manifest_hash(file_rows: list[dict]) -> str:
    """Produce a deterministic SHA256 fingerprint of a manifest's file contents.

    Only normalized_path, content_hash, size_bytes, parser, and parser_version
    contribute to the hash. mtime_client, mime_type, display_path, and status
    are excluded because they are not part of canonical file identity.
    """
    sorted_rows = sorted(file_rows, key=lambda r: r.get("normalized_path", ""))
    items = []
    for row in sorted_rows:
        items.append(
            {
                "content_hash": row.get("content_hash") or "",
                "normalized_path": row.get("normalized_path") or "",
                "parser": row.get("parser") or "",
                "parser_version": row.get("parser_version") or "",
                "size_bytes": row.get("size_bytes") or 0,
            }
        )
    serialized = json.dumps(items, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
