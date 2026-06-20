from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from sourcebrief_shared.models import ResourceManifestFile

ChangeType = Literal["added", "changed", "deleted", "unchanged"]
CHANGE_SORT_RANK: dict[str, int] = {"deleted": 0, "changed": 1, "added": 2, "unchanged": 3}
VALID_CHANGE_TYPES = frozenset(CHANGE_SORT_RANK)


@dataclass(frozen=True)
class ManifestDiffRow:
    normalized_path: str
    change_type: ChangeType
    base_file_id: UUID | None
    head_file_id: UUID | None
    base_status: str | None
    head_status: str | None
    base_size_bytes: int | None
    head_size_bytes: int | None
    base_content_hash: str | None
    head_content_hash: str | None
    warning_changed: bool
    reason: str


@dataclass(frozen=True)
class DeletedFileImpactStub:
    deleted_file_count: int
    impacted_sections_known: bool
    message: str


@dataclass(frozen=True)
class ManifestDiffResult:
    rows: list[ManifestDiffRow]
    added_count: int
    changed_count: int
    deleted_count: int
    unchanged_count: int
    warning_changed_count: int
    base_file_count: int
    head_file_count: int
    deleted_file_impact: DeletedFileImpactStub

    @property
    def total_row_count(self) -> int:
        return len(self.rows)


def _warnings(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def _same_file(base: ResourceManifestFile, head: ResourceManifestFile) -> bool:
    return (
        base.content_hash == head.content_hash
        and base.status == head.status
        and base.mime_type == head.mime_type
        and _warnings(base.warnings_json) == _warnings(head.warnings_json)
    )


def _reason(base: ResourceManifestFile | None, head: ResourceManifestFile | None, change_type: ChangeType, warning_changed: bool) -> str:
    if change_type == "added":
        return "path added in head manifest"
    if change_type == "deleted":
        return "path deleted from head manifest"
    if warning_changed:
        return "parser warnings changed"
    if base is not None and head is not None:
        if base.content_hash != head.content_hash:
            return "content hash changed"
        if base.status != head.status:
            return "file status changed"
        if base.mime_type != head.mime_type:
            return "mime type changed"
    return "unchanged"


def build_manifest_diff(base_files: Sequence[ResourceManifestFile], head_files: Sequence[ResourceManifestFile]) -> ManifestDiffResult:
    base_by_path = {file.normalized_path: file for file in base_files}
    head_by_path = {file.normalized_path: file for file in head_files}
    rows: list[ManifestDiffRow] = []
    warning_changed_count = 0

    for path in sorted(set(base_by_path) | set(head_by_path)):
        base = base_by_path.get(path)
        head = head_by_path.get(path)
        if base is None and head is not None:
            change_type: ChangeType = "added"
            warning_changed = False
        elif head is None and base is not None:
            change_type = "deleted"
            warning_changed = False
        elif base is not None and head is not None and _same_file(base, head):
            change_type = "unchanged"
            warning_changed = False
        elif base is not None and head is not None:
            change_type = "changed"
            warning_changed = _warnings(base.warnings_json) != _warnings(head.warnings_json)
        else:  # defensive; path union prevents this
            continue
        if warning_changed:
            warning_changed_count += 1
        rows.append(
            ManifestDiffRow(
                normalized_path=path,
                change_type=change_type,
                base_file_id=base.id if base is not None else None,
                head_file_id=head.id if head is not None else None,
                base_status=base.status if base is not None else None,
                head_status=head.status if head is not None else None,
                base_size_bytes=base.size_bytes if base is not None else None,
                head_size_bytes=head.size_bytes if head is not None else None,
                base_content_hash=base.content_hash if base is not None else None,
                head_content_hash=head.content_hash if head is not None else None,
                warning_changed=warning_changed,
                reason=_reason(base, head, change_type, warning_changed),
            )
        )

    rows.sort(key=lambda row: (CHANGE_SORT_RANK[row.change_type], row.normalized_path))
    deleted_count = sum(1 for row in rows if row.change_type == "deleted")
    return ManifestDiffResult(
        rows=rows,
        added_count=sum(1 for row in rows if row.change_type == "added"),
        changed_count=sum(1 for row in rows if row.change_type == "changed"),
        deleted_count=deleted_count,
        unchanged_count=sum(1 for row in rows if row.change_type == "unchanged"),
        warning_changed_count=warning_changed_count,
        base_file_count=len(base_by_path),
        head_file_count=len(head_by_path),
        deleted_file_impact=DeletedFileImpactStub(
            deleted_file_count=deleted_count,
            impacted_sections_known=False,
            message="Section impact is available in the Section reuse and impact panel; artifact citation impact is not available yet.",
        ),
    )


def encode_cursor(row: ManifestDiffRow) -> str:
    payload = {"rank": CHANGE_SORT_RANK[row.change_type], "path": row.normalized_path}
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[int, str]:
    padded = cursor + "=" * (-len(cursor) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
    return int(payload["rank"]), str(payload["path"])


def page_diff_rows(
    rows: Sequence[ManifestDiffRow],
    *,
    change_types: set[str] | None = None,
    limit: int = 100,
    cursor: str | None = None,
) -> tuple[list[ManifestDiffRow], str | None, int]:
    filtered = [row for row in rows if change_types is None or row.change_type in change_types]
    total_matching = len(filtered)
    if cursor:
        rank, path = decode_cursor(cursor)
        filtered = [row for row in filtered if (CHANGE_SORT_RANK[row.change_type], row.normalized_path) > (rank, path)]
    page = filtered[:limit]
    next_cursor = encode_cursor(page[-1]) if len(filtered) > limit and page else None
    return page, next_cursor, total_matching
