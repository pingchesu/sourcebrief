"""Transactional ResourceManifest creation helpers.

The path/hash helpers in ``contextsmith_worker.manifest`` intentionally remain
pure. This module owns the DB-side A1 creation contract so future upload and
refresh paths get manifest rows, child file rows, and audit evidence in one
transaction instead of duplicating that logic in API/worker call sites.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from contextsmith_shared.models import (
    AuditEvent,
    ResourceManifest,
    ResourceManifestFile,
    SourceSnapshot,
)
from contextsmith_worker.manifest import compute_manifest_hash, normalize_path


@dataclass(frozen=True)
class ManifestFileInput:
    normalized_path: str
    content_hash: str
    size_bytes: int = 0
    display_path: str | None = None
    mime_type: str | None = None
    mtime_client: datetime | None = None
    parser: str | None = None
    parser_version: str | None = None
    extraction_policy_hash: str | None = None
    status: str = "pending"
    section_count: int = 0
    warnings_json: list[str] = field(default_factory=list)


def compute_path_hash(normalized_path: str) -> str:
    """Return the canonical sha256-prefixed path hash for a normalized path."""
    normalized = normalize_path(normalized_path)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def create_resource_manifest(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    resource_id: UUID,
    source_snapshot_id: UUID,
    files: list[ManifestFileInput],
    actor_user_id: UUID | None = None,
    actor_token_id: UUID | None = None,
) -> ResourceManifest:
    """Create a manifest, file rows, and audit event in the caller's transaction.

    The snapshot must belong to the same workspace/project/resource tuple. The
    DB constraints enforce this too; this preflight gives callers a clearer
    error before flush.
    """
    snapshot = session.get(SourceSnapshot, source_snapshot_id)
    if snapshot is None:
        raise ValueError("source snapshot not found")
    if (
        snapshot.workspace_id != workspace_id
        or snapshot.project_id != project_id
        or snapshot.resource_id != resource_id
    ):
        raise ValueError("source snapshot scope does not match manifest scope")

    canonical_rows: list[dict] = []
    for file_input in files:
        normalized_path = normalize_path(file_input.normalized_path)
        canonical_rows.append(
            {
                "normalized_path": normalized_path,
                "content_hash": file_input.content_hash,
                "size_bytes": file_input.size_bytes,
                "parser": file_input.parser,
                "parser_version": file_input.parser_version,
            }
        )

    manifest_hash = compute_manifest_hash(canonical_rows)
    manifest = ResourceManifest(
        workspace_id=workspace_id,
        project_id=project_id,
        resource_id=resource_id,
        source_snapshot_id=source_snapshot_id,
        manifest_hash=manifest_hash,
        file_count=len(files),
        total_bytes=sum(file_input.size_bytes for file_input in files),
        parser_warning_count=sum(1 for file_input in files if file_input.warnings_json),
        unsupported_file_count=sum(1 for file_input in files if file_input.status == "unsupported"),
    )
    session.add(manifest)
    session.flush()

    for file_input, canonical in zip(files, canonical_rows, strict=True):
        session.add(
            ResourceManifestFile(
                workspace_id=workspace_id,
                project_id=project_id,
                resource_id=resource_id,
                resource_manifest_id=manifest.id,
                normalized_path=canonical["normalized_path"],
                display_path=file_input.display_path,
                path_hash=compute_path_hash(canonical["normalized_path"]),
                content_hash=file_input.content_hash,
                size_bytes=file_input.size_bytes,
                mime_type=file_input.mime_type,
                mtime_client=file_input.mtime_client,
                parser=file_input.parser,
                parser_version=file_input.parser_version,
                extraction_policy_hash=file_input.extraction_policy_hash,
                status=file_input.status,
                section_count=file_input.section_count,
                warnings_json=file_input.warnings_json,
            )
        )

    session.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            action="manifest.created",
            target_type="resource_manifest",
            target_id=manifest.id,
            target_ref={
                "resource_id": str(resource_id),
                "snapshot_id": str(source_snapshot_id),
            },
            meta={
                "manifest_hash": manifest_hash,
                "file_count": manifest.file_count,
                "total_bytes": manifest.total_bytes,
                "parser_warning_count": manifest.parser_warning_count,
                "unsupported_file_count": manifest.unsupported_file_count,
            },
        )
    )
    session.flush()
    return manifest
