from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from sourcebrief_shared.models import (
    ContextArtifact,
    ContextArtifactCitation,
    ContextPack,
    ContextPackArtifact,
    ContextPackResourceCoverage,
    ContextPackVersion,
)

PACK_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
PACK_STATUS_PUBLISHED = "published"
PACK_STATUS_DRAFT = "draft"
PACK_STATUS_SUPERSEDED = "superseded"
PACK_STATUS_ROLLED_BACK = "rolled_back"
PACK_STATUS_INVALIDATED = "invalidated"
PACK_STATUS_FAILED = "failed"


def canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PackBuild:
    pack_hash: str
    coverage_json: dict
    validation_json: dict
    coverage_rows: list[dict]


def validate_pack_key(pack_key: str) -> str:
    normalized = pack_key.strip().lower()
    if not PACK_KEY_RE.match(normalized):
        raise ValueError("pack_key must start with a lowercase letter/number and contain only lowercase letters, numbers, '.', '_' or '-' (max 63 chars)")
    return normalized


def get_or_create_locked_pack(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    pack_key: str,
    title: str,
    description: str | None,
    created_by: UUID,
) -> ContextPack:
    normalized = validate_pack_key(pack_key)
    pack = session.scalar(
        select(ContextPack)
        .where(ContextPack.workspace_id == workspace_id, ContextPack.project_id == project_id, ContextPack.pack_key == normalized)
        .with_for_update()
    )
    if pack is not None:
        if title and pack.title != title:
            pack.title = title
        if description is not None:
            pack.description = description
        return pack
    session.execute(
        insert(ContextPack)
        .values(
            workspace_id=workspace_id,
            project_id=project_id,
            pack_key=normalized,
            title=title,
            description=description,
            created_by=created_by,
        )
        .on_conflict_do_nothing(index_elements=["workspace_id", "project_id", "pack_key"])
    )
    return session.scalar(
        select(ContextPack)
        .where(ContextPack.workspace_id == workspace_id, ContextPack.project_id == project_id, ContextPack.pack_key == normalized)
        .with_for_update()
    ) or ContextPack(
        workspace_id=workspace_id,
        project_id=project_id,
        pack_key=normalized,
        title=title,
        description=description,
        created_by=created_by,
    )


def next_pack_version(session: Session, workspace_id: UUID, project_id: UUID, pack_key: str) -> int:
    current = session.scalar(
        select(func.max(ContextPackVersion.version)).where(
            ContextPackVersion.workspace_id == workspace_id,
            ContextPackVersion.project_id == project_id,
            ContextPackVersion.pack_key == pack_key,
        )
    )
    return int(current or 0) + 1


def build_pack_from_artifacts(artifacts: list[ContextArtifact], citation_counts: dict[UUID, int]) -> PackBuild:
    ordered = sorted(artifacts, key=lambda artifact: (str(artifact.resource_id), artifact.artifact_type, artifact.artifact_hash, str(artifact.id)))
    resource_coverage: dict[tuple[UUID, UUID, UUID], dict] = {}
    rows: list[dict] = []
    for artifact in ordered:
        key = (artifact.resource_id, artifact.source_snapshot_id, artifact.resource_manifest_id)
        coverage = resource_coverage.setdefault(
            key,
            {
                "resource_id": str(artifact.resource_id),
                "source_snapshot_id": str(artifact.source_snapshot_id),
                "resource_manifest_id": str(artifact.resource_manifest_id),
                "artifact_count": 0,
                "citation_count": 0,
                "artifact_types": [],
            },
        )
        coverage["artifact_count"] += 1
        coverage["citation_count"] += citation_counts.get(artifact.id, 0)
        if artifact.artifact_type not in coverage["artifact_types"]:
            coverage["artifact_types"].append(artifact.artifact_type)
        rows.append(
            {
                "context_artifact_id": artifact.id,
                "resource_id": artifact.resource_id,
                "source_snapshot_id": artifact.source_snapshot_id,
                "resource_manifest_id": artifact.resource_manifest_id,
                "artifact_type": artifact.artifact_type,
                "artifact_hash": artifact.artifact_hash,
            }
        )
    coverage_rows = list(resource_coverage.values())
    payload = {
        "schema_version": "context-pack.v1",
        "artifacts": [
            {
                "id": str(artifact.id),
                "resource_id": str(artifact.resource_id),
                "source_snapshot_id": str(artifact.source_snapshot_id),
                "resource_manifest_id": str(artifact.resource_manifest_id),
                "artifact_type": artifact.artifact_type,
                "artifact_hash": artifact.artifact_hash,
                "artifact_revision": artifact.artifact_revision,
            }
            for artifact in ordered
        ],
        "coverage": coverage_rows,
    }
    validation_errors: list[dict] = []
    if not ordered:
        validation_errors.append({"code": "empty_pack", "message": "Context Pack requires at least one approved artifact"})
    duplicate_keys = [key for key, count in _artifact_key_counts(ordered).items() if count > 1]
    if duplicate_keys:
        validation_errors.append({"code": "duplicate_artifact_layer", "message": "Pack contains duplicate artifact layer for a resource snapshot/type"})
    return PackBuild(
        pack_hash=canonical_hash(payload),
        coverage_json={
            "artifact_count": len(ordered),
            "resource_count": len({artifact.resource_id for artifact in ordered}),
            "snapshot_count": len({artifact.source_snapshot_id for artifact in ordered}),
            "coverage": coverage_rows,
        },
        validation_json={"ok": not validation_errors, "errors": validation_errors, "warnings": []},
        coverage_rows=rows,
    )


def _artifact_key_counts(artifacts: list[ContextArtifact]) -> dict[tuple[UUID, UUID, str], int]:
    counts: dict[tuple[UUID, UUID, str], int] = defaultdict(int)
    for artifact in artifacts:
        counts[(artifact.resource_id, artifact.source_snapshot_id, artifact.artifact_type)] += 1
    return counts


def citation_counts_for_artifacts(session: Session, artifact_ids: list[UUID]) -> dict[UUID, int]:
    if not artifact_ids:
        return {}
    rows = session.execute(
        select(ContextArtifactCitation.context_artifact_id, func.count(ContextArtifactCitation.id))
        .where(ContextArtifactCitation.context_artifact_id.in_(artifact_ids))
        .group_by(ContextArtifactCitation.context_artifact_id)
    ).all()
    return {row[0]: int(row[1]) for row in rows}


def attach_pack_rows(session: Session, version: ContextPackVersion, artifacts: list[ContextArtifact], citation_counts: dict[UUID, int]) -> None:
    for ordinal, artifact in enumerate(sorted(artifacts, key=lambda item: (str(item.resource_id), item.artifact_type, item.artifact_hash, str(item.id)))):
        session.add(
            ContextPackArtifact(
                workspace_id=version.workspace_id,
                project_id=version.project_id,
                context_pack_version_id=version.id,
                context_artifact_id=artifact.id,
                resource_id=artifact.resource_id,
                source_snapshot_id=artifact.source_snapshot_id,
                resource_manifest_id=artifact.resource_manifest_id,
                artifact_type=artifact.artifact_type,
                artifact_hash=artifact.artifact_hash,
                ordinal=ordinal,
            )
        )
    coverage: dict[tuple[UUID, UUID, UUID], dict[str, int]] = defaultdict(lambda: {"artifact_count": 0, "citation_count": 0})
    for artifact in artifacts:
        key = (artifact.resource_id, artifact.source_snapshot_id, artifact.resource_manifest_id)
        coverage[key]["artifact_count"] += 1
        coverage[key]["citation_count"] += citation_counts.get(artifact.id, 0)
    for (resource_id, source_snapshot_id, resource_manifest_id), counts in coverage.items():
        session.add(
            ContextPackResourceCoverage(
                workspace_id=version.workspace_id,
                project_id=version.project_id,
                context_pack_version_id=version.id,
                resource_id=resource_id,
                source_snapshot_id=source_snapshot_id,
                resource_manifest_id=resource_manifest_id,
                artifact_count=counts["artifact_count"],
                citation_count=counts["citation_count"],
            )
        )
