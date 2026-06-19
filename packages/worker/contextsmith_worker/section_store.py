from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from contextsmith_shared.models import (
    AuditEvent,
    Resource,
    ResourceManifest,
    ResourceManifestFile,
    Section,
    SnapshotSection,
)
from contextsmith_worker.section_extraction import (
    EXTRACTION_POLICY_HASH,
    PARSER_VERSION,
    ExtractedSection,
    extract_sections,
)


@dataclass(frozen=True)
class SectionBuildResult:
    section_count: int
    sections_reused_count: int
    sections_extracted_count: int
    sections_from_deleted_files_count: int
    sections_absent_count: int


def source_family_resource_id(resource: Resource) -> UUID:
    raw = (resource.source_config or {}).get("source_family_id")
    return UUID(str(raw)) if raw else resource.id


def predecessor_resource_id(resource: Resource) -> UUID | None:
    raw = (resource.source_config or {}).get("supersedes_resource_id")
    return UUID(str(raw)) if raw else None


def build_snapshot_sections(
    session: Session,
    *,
    resource: Resource,
    manifest: ResourceManifest,
    redacted_docs: list[dict],
    actor_user_id: UUID | None = None,
    actor_token_id: UUID | None = None,
) -> SectionBuildResult:
    family_id = source_family_resource_id(resource)
    doc_text_by_path = {str(doc.get("path") or doc.get("title") or ""): str(doc.get("content") or "") for doc in redacted_docs}
    manifest_files = list(
        session.scalars(
            select(ResourceManifestFile)
            .where(ResourceManifestFile.resource_manifest_id == manifest.id)
            .order_by(ResourceManifestFile.normalized_path.asc())
        )
    )
    current_paths = {file.normalized_path for file in manifest_files}
    previous_snapshot_id, previous_sections_by_path, previous_file_hash_by_path = _previous_sections(session, resource, family_id)
    previous_snapshot_by_logical_key = {
        section.logical_key: snapshot_section.id
        for rows in previous_sections_by_path.values()
        for section, snapshot_section in rows
    }
    previous_snapshot_ids_by_path_and_section_hash: dict[str, dict[str, list[UUID]]] = {}
    for path, rows in previous_sections_by_path.items():
        by_hash = previous_snapshot_ids_by_path_and_section_hash.setdefault(path, {})
        for section, snapshot_section in rows:
            by_hash.setdefault(section.section_hash, []).append(snapshot_section.id)
    mapped_previous_ids: set[UUID] = set()

    reused = 0
    extracted = 0
    total = 0

    for manifest_file in manifest_files:
        text = doc_text_by_path.get(manifest_file.normalized_path)
        can_extract = text is not None and manifest_file.status == "pending"
        previous_rows = previous_sections_by_path.get(manifest_file.normalized_path, [])
        can_reuse = (
            previous_snapshot_id is not None
            and previous_rows
            and previous_file_hash_by_path.get(manifest_file.normalized_path) == manifest_file.content_hash
            and all(row[0].parser_version == PARSER_VERSION and row[0].extraction_policy_hash == EXTRACTION_POLICY_HASH for row in previous_rows)
        )
        if can_reuse:
            for section, previous_snapshot_section in previous_rows:
                session.add(
                    SnapshotSection(
                        workspace_id=resource.workspace_id,
                        project_id=resource.project_id,
                        version_resource_id=resource.id,
                        section_family_resource_id=family_id,
                        source_snapshot_id=manifest.source_snapshot_id,
                        resource_manifest_id=manifest.id,
                        resource_manifest_file_id=manifest_file.id,
                        section_id=section.id,
                        normalized_path=manifest_file.normalized_path,
                        ordinal=previous_snapshot_section.ordinal,
                        reused_from_snapshot_id=previous_snapshot_id,
                        reuse_status="reused",
                    )
                )
                mapped_previous_ids.add(previous_snapshot_section.id)
                reused += 1
                total += 1
            manifest_file.section_count = len(previous_rows)
            continue
        if not can_extract:
            manifest_file.section_count = 0
            continue
        assert text is not None
        sections = extract_sections(section_family_resource_id=family_id, normalized_path=manifest_file.normalized_path, redacted_text=text)
        manifest_file.section_count = len(sections)
        for section_input in sections:
            section = _upsert_section(session, resource, family_id, section_input)
            previous_snapshot_section_id = previous_snapshot_by_logical_key.get(section_input.logical_key)
            if previous_snapshot_section_id is None:
                candidates = previous_snapshot_ids_by_path_and_section_hash.get(manifest_file.normalized_path, {}).get(section_input.section_hash, [])
                while candidates and candidates[0] in mapped_previous_ids:
                    candidates.pop(0)
                previous_snapshot_section_id = candidates.pop(0) if candidates else None
            if previous_snapshot_section_id is not None:
                mapped_previous_ids.add(previous_snapshot_section_id)
            session.flush()
            session.add(
                SnapshotSection(
                    workspace_id=resource.workspace_id,
                    project_id=resource.project_id,
                    version_resource_id=resource.id,
                    section_family_resource_id=family_id,
                    source_snapshot_id=manifest.source_snapshot_id,
                    resource_manifest_id=manifest.id,
                    resource_manifest_file_id=manifest_file.id,
                    section_id=section.id,
                    normalized_path=manifest_file.normalized_path,
                    ordinal=section_input.ordinal,
                    reused_from_snapshot_id=None,
                    reuse_status="extracted",
                )
            )
            extracted += 1
            total += 1

    previous_rows_all = [snapshot_section for rows in previous_sections_by_path.values() for _section, snapshot_section in rows]
    previous_ids = {row.id for row in previous_rows_all}
    absent = len(previous_ids - mapped_previous_ids) if previous_rows_all else 0
    from_deleted_files = sum(len(rows) for path, rows in previous_sections_by_path.items() if path not in current_paths)
    manifest.section_count = total
    manifest.sections_reused_count = reused
    manifest.sections_extracted_count = extracted
    manifest.sections_from_deleted_files_count = from_deleted_files
    manifest.sections_absent_count = absent
    session.add(
        AuditEvent(
            workspace_id=resource.workspace_id,
            actor_user_id=actor_user_id,
            actor_token_id=actor_token_id,
            action="section_extraction.completed",
            target_type="resource_manifest",
            target_id=manifest.id,
            target_ref={"resource_id": str(resource.id), "snapshot_id": str(manifest.source_snapshot_id)},
            meta={
                "section_count": total,
                "sections_reused_count": reused,
                "sections_extracted_count": extracted,
                "sections_from_deleted_files_count": from_deleted_files,
                "sections_absent_count": absent,
                "source_family_label": (resource.source_config or {}).get("source_family_label"),
                "version_label": (resource.source_config or {}).get("version_label"),
            },
        )
    )
    session.flush()
    return SectionBuildResult(total, reused, extracted, from_deleted_files, absent)


def _upsert_section(session: Session, resource: Resource, family_id: UUID, section_input: ExtractedSection) -> Section:
    section = session.scalar(select(Section).where(Section.project_id == resource.project_id, Section.logical_key == section_input.logical_key))
    if section is not None:
        return section
    section = Section(
        workspace_id=resource.workspace_id,
        project_id=resource.project_id,
        section_family_resource_id=family_id,
        normalized_path=section_input.normalized_path,
        parser_version=section_input.parser_version,
        extraction_policy_hash=section_input.extraction_policy_hash,
        section_hash=section_input.section_hash,
        occurrence_key=section_input.occurrence_key,
        logical_key=section_input.logical_key,
        title=section_input.title,
        content_hash=section_input.content_hash,
        content_text=section_input.content_text,
        content_bytes=section_input.content_bytes,
        ordinal=section_input.ordinal,
        start_line=section_input.start_line,
        end_line=section_input.end_line,
        metadata_json={},
    )
    session.add(section)
    return section


def _previous_sections(
    session: Session, resource: Resource, family_id: UUID
) -> tuple[UUID | None, dict[str, list[tuple[Section, SnapshotSection]]], dict[str, str]]:
    predecessor_id = predecessor_resource_id(resource)
    if predecessor_id is None:
        return None, {}, {}
    predecessor = session.get(Resource, predecessor_id)
    if predecessor is None or predecessor.workspace_id != resource.workspace_id or predecessor.project_id != resource.project_id:
        return None, {}, {}
    if predecessor.current_snapshot_id is None:
        return None, {}, {}
    file_hash_rows = list(
        session.execute(
            select(ResourceManifestFile.normalized_path, ResourceManifestFile.content_hash)
            .join(ResourceManifest, ResourceManifestFile.resource_manifest_id == ResourceManifest.id)
            .where(
                ResourceManifest.workspace_id == resource.workspace_id,
                ResourceManifest.project_id == resource.project_id,
                ResourceManifest.resource_id == predecessor.id,
                ResourceManifest.source_snapshot_id == predecessor.current_snapshot_id,
            )
        ).all()
    )
    previous_file_hash_by_path = {str(path): str(file_hash) for path, file_hash in file_hash_rows}
    rows = list(
        session.execute(
            select(Section, SnapshotSection)
            .join(SnapshotSection, SnapshotSection.section_id == Section.id)
            .where(
                SnapshotSection.workspace_id == resource.workspace_id,
                SnapshotSection.project_id == resource.project_id,
                SnapshotSection.version_resource_id == predecessor.id,
                SnapshotSection.section_family_resource_id == family_id,
                SnapshotSection.source_snapshot_id == predecessor.current_snapshot_id,
            )
            .order_by(SnapshotSection.normalized_path.asc(), SnapshotSection.ordinal.asc())
        ).all()
    )
    by_path: dict[str, list[tuple[Section, SnapshotSection]]] = {}
    for section, snapshot_section in rows:
        by_path.setdefault(snapshot_section.normalized_path, []).append((section, snapshot_section))
    return predecessor.current_snapshot_id, by_path, previous_file_hash_by_path
