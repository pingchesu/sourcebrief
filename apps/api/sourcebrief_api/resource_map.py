from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sourcebrief_shared.models import (
    ContextArtifact,
    Resource,
    ResourceManifest,
    ResourceManifestFile,
    Section,
    SnapshotSection,
    SourceSnapshot,
)

ARTIFACT_TYPE_RESOURCE_MAP = "resource_map"
RESOURCE_MAP_SCHEMA_VERSION = "resource-map-v1"


@dataclass(frozen=True)
class ResourceMapBuild:
    artifact_hash: str
    title: str
    summary: str
    content_json: dict
    coverage_json: dict
    validation_json: dict
    sources: list[dict]
    citations: list[dict]
    status: str = "draft"
    error_message: str | None = None


def canonical_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def classify_coverage(file: ResourceManifestFile) -> tuple[str, list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []
    status = (file.status or "").lower()
    parser_warnings = list(file.warnings_json or [])
    if status in {"parsed", "pending"}:
        if parser_warnings and file.section_count > 0:
            warnings.append("parser warnings need review")
            return "warning", warnings, errors
        if file.section_count <= 0:
            warnings.append("supported file has no extracted sections")
            return "empty", warnings, errors
        return "covered", warnings, errors
    if status == "unsupported":
        warnings.append("file type is tracked but not parsed into sections")
        return "unsupported", warnings, errors
    if status == "skipped":
        warnings.append("file was skipped by ingestion policy")
        return "skipped", warnings, errors
    if status == "failed":
        errors.append("file failed parsing")
        return "failed", warnings, errors
    errors.append(f"unknown manifest file status: {file.status}")
    return "failed", warnings, errors


def _preview(text: str, limit: int = 160) -> str:
    compact = " ".join((text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def build_resource_map(session: Session, resource: Resource, manifest: ResourceManifest, snapshot: SourceSnapshot) -> ResourceMapBuild:
    files = list(
        session.scalars(
            select(ResourceManifestFile)
            .where(
                ResourceManifestFile.workspace_id == resource.workspace_id,
                ResourceManifestFile.project_id == resource.project_id,
                ResourceManifestFile.resource_id == resource.id,
                ResourceManifestFile.resource_manifest_id == manifest.id,
            )
            .order_by(ResourceManifestFile.normalized_path.asc())
        )
    )
    section_rows = session.execute(
        select(SnapshotSection, Section)
        .join(Section, SnapshotSection.section_id == Section.id)
        .where(
            SnapshotSection.workspace_id == resource.workspace_id,
            SnapshotSection.project_id == resource.project_id,
            SnapshotSection.version_resource_id == resource.id,
            SnapshotSection.source_snapshot_id == snapshot.id,
            SnapshotSection.resource_manifest_id == manifest.id,
        )
        .order_by(SnapshotSection.normalized_path.asc(), SnapshotSection.ordinal.asc())
    ).all()
    sections_by_file: dict[UUID, list[tuple[SnapshotSection, Section]]] = {}
    for snapshot_section, section in section_rows:
        sections_by_file.setdefault(snapshot_section.resource_manifest_file_id, []).append((snapshot_section, section))

    entries: list[dict] = []
    source_rows: list[dict] = []
    citation_rows: list[dict] = []
    validation_errors: list[dict] = []
    validation_warnings: list[dict] = []
    counts = {
        "file_count": len(files),
        "covered_file_count": 0,
        "warning_file_count": 0,
        "empty_file_count": 0,
        "unsupported_file_count": 0,
        "skipped_file_count": 0,
        "failed_file_count": 0,
        "section_count": 0,
        "warning_count": 0,
        "error_count": 0,
    }

    for file in files:
        file_sections = sections_by_file.get(file.id, [])
        coverage_status, warnings, errors = classify_coverage(file)
        for warning in warnings:
            validation_warnings.append({"path": file.normalized_path, "message": warning})
        for error in errors:
            validation_errors.append({"path": file.normalized_path, "message": error})
        section_entries = []
        for snapshot_section, section in file_sections:
            if snapshot_section.normalized_path != file.normalized_path:
                validation_errors.append({"path": file.normalized_path, "message": "section path does not match manifest file"})
            section_entries.append(
                {
                    "title": section.title,
                    "ordinal": snapshot_section.ordinal,
                    "line_start": section.start_line,
                    "line_end": section.end_line,
                    "content_hash": section.content_hash,
                    "preview": _preview(section.content_text),
                }
            )
            citation_rows.append(
                {
                    "resource_manifest_file_id": file.id,
                    "snapshot_section_id": snapshot_section.id,
                    "section_id": section.id,
                    "section_family_resource_id": snapshot_section.section_family_resource_id,
                    "normalized_path": file.normalized_path,
                    "ordinal": snapshot_section.ordinal,
                    "title": section.title,
                    "content_hash": section.content_hash,
                    "line_start": section.start_line,
                    "line_end": section.end_line,
                }
            )
        section_count = len(section_entries)
        expected_section_count = int(file.section_count or 0)
        if expected_section_count != section_count:
            validation_errors.append(
                {
                    "path": file.normalized_path,
                    "message": f"manifest expected {expected_section_count} sections but {section_count} snapshot sections were found",
                }
            )
            coverage_status = "failed"
        counts["section_count"] += section_count
        if coverage_status == "covered":
            counts["covered_file_count"] += 1
        elif coverage_status == "warning":
            counts["warning_file_count"] += 1
        elif coverage_status == "empty":
            counts["empty_file_count"] += 1
        elif coverage_status == "unsupported":
            counts["unsupported_file_count"] += 1
        elif coverage_status == "skipped":
            counts["skipped_file_count"] += 1
        elif coverage_status == "failed":
            counts["failed_file_count"] += 1
        source_rows.append(
            {
                "resource_manifest_file_id": file.id,
                "normalized_path": file.normalized_path,
                "status": file.status,
                "section_count": section_count,
                "coverage_status": coverage_status,
                "metadata_json": {"size_bytes": file.size_bytes, "warnings": list(file.warnings_json or [])},
            }
        )
        entries.append(
            {
                "path": file.normalized_path,
                "status": file.status,
                "coverage_status": coverage_status,
                "section_count": section_count,
                "sections": section_entries,
                "warnings": warnings + list(file.warnings_json or []),
            }
        )

    counts["warning_count"] = len(validation_warnings)
    counts["error_count"] = len(validation_errors)
    counts["source_count"] = len(files)
    counts["citation_count"] = len(citation_rows)
    coverage_json = dict(counts)
    validation_json = {"ok": not validation_errors, "errors": validation_errors, "warnings": validation_warnings}
    title = f"Resource Map · {resource.name}"
    summary = f"{resource.name}: {counts['file_count']} files, {counts['section_count']} sections"

    content_json = {
        "schema_version": RESOURCE_MAP_SCHEMA_VERSION,
        "resource": {"name": resource.name, "type": resource.type},
        "snapshot": {"version": snapshot.version, "indexed_at": snapshot.indexed_at.isoformat() if snapshot.indexed_at else None},
        "coverage": coverage_json,
        "entries": entries,
        "validation": validation_json,
    }
    if validation_errors:
        error_payload = {
            "schema_version": RESOURCE_MAP_SCHEMA_VERSION,
            "resource": {"name": resource.name, "type": resource.type},
            "snapshot": {"version": snapshot.version},
            "validation": validation_json,
        }
        return ResourceMapBuild(
            artifact_hash=canonical_hash(error_payload),
            title=title,
            summary=summary,
            content_json={},
            coverage_json=coverage_json,
            validation_json=validation_json,
            sources=[],
            citations=[],
            status="failed",
            error_message=f"Resource Map validation failed: {validation_errors[0]['message']}",
        )
    return ResourceMapBuild(
        artifact_hash=canonical_hash(content_json),
        title=title,
        summary=summary,
        content_json=content_json,
        coverage_json=coverage_json,
        validation_json=validation_json,
        sources=source_rows,
        citations=citation_rows,
    )


def next_artifact_revision(session: Session, resource: Resource, snapshot_id: UUID, artifact_hash: str) -> int:
    current = session.scalar(
        select(func.max(ContextArtifact.artifact_revision)).where(
            ContextArtifact.workspace_id == resource.workspace_id,
            ContextArtifact.project_id == resource.project_id,
            ContextArtifact.resource_id == resource.id,
            ContextArtifact.source_snapshot_id == snapshot_id,
            ContextArtifact.artifact_type == ARTIFACT_TYPE_RESOURCE_MAP,
            ContextArtifact.artifact_hash == artifact_hash,
        )
    )
    return int(current or 0) + 1


def latest_same_hash_artifact(session: Session, resource: Resource, snapshot_id: UUID, artifact_hash: str) -> ContextArtifact | None:
    return session.scalar(
        select(ContextArtifact)
        .where(
            ContextArtifact.workspace_id == resource.workspace_id,
            ContextArtifact.project_id == resource.project_id,
            ContextArtifact.resource_id == resource.id,
            ContextArtifact.source_snapshot_id == snapshot_id,
            ContextArtifact.artifact_type == ARTIFACT_TYPE_RESOURCE_MAP,
            ContextArtifact.artifact_hash == artifact_hash,
        )
        .order_by(ContextArtifact.artifact_revision.desc(), ContextArtifact.created_at.desc())
        .limit(1)
    )
