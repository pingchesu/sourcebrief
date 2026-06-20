from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sourcebrief_shared.models import ResourceManifestFile
from sourcebrief_worker.manifest_diff import build_manifest_diff, page_diff_rows


def file_row(path: str, content_hash: str, *, status: str = "pending", warnings: list[str] | None = None, size: int = 1) -> ResourceManifestFile:
    return ResourceManifestFile(
        id=uuid4(),
        workspace_id=uuid4(),
        project_id=uuid4(),
        resource_id=uuid4(),
        resource_manifest_id=uuid4(),
        normalized_path=path,
        display_path=path,
        path_hash="sha256:" + "0" * 64,
        size_bytes=size,
        content_hash=content_hash,
        mime_type="text/plain",
        status=status,
        warnings_json=warnings or [],
        created_at=datetime.now(UTC),
    )


def test_manifest_diff_classifies_added_changed_deleted_unchanged() -> None:
    base = [file_row("README.md", "old"), file_row("keep.txt", "same"), file_row("delete.txt", "gone")]
    head = [file_row("README.md", "new"), file_row("keep.txt", "same"), file_row("added.txt", "add")]
    result = build_manifest_diff(base, head)
    assert result.added_count == 1
    assert result.changed_count == 1
    assert result.deleted_count == 1
    assert result.unchanged_count == 1
    by_path = {row.normalized_path: row.change_type for row in result.rows}
    assert by_path == {"added.txt": "added", "README.md": "changed", "delete.txt": "deleted", "keep.txt": "unchanged"}
    assert result.deleted_file_impact.impacted_sections_known is False


def test_warning_change_counts_as_changed() -> None:
    result = build_manifest_diff([file_row("a.txt", "same")], [file_row("a.txt", "same", warnings=["parser skipped section"])])
    assert result.changed_count == 1
    assert result.warning_changed_count == 1
    assert result.rows[0].reason == "parser warnings changed"


def test_pagination_and_filtering_preserve_full_counts() -> None:
    base = [file_row(f"old-{i}.txt", str(i)) for i in range(3)]
    head = [file_row(f"new-{i}.txt", str(i)) for i in range(3)]
    result = build_manifest_diff(base, head)
    first, cursor, filtered = page_diff_rows(result.rows, change_types={"added"}, limit=2)
    assert len(first) == 2
    assert cursor is not None
    assert filtered == 3
    second, cursor2, filtered2 = page_diff_rows(result.rows, change_types={"added"}, limit=2, cursor=cursor)
    assert [row.normalized_path for row in first + second] == ["new-0.txt", "new-1.txt", "new-2.txt"]
    assert cursor2 is None
    assert filtered2 == 3
