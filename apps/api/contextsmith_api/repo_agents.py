from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contextsmith_shared.models import (
    ContextPackResourceCoverage,
    ContextPackVersion,
    RepoAgent,
    RepoAgentVersion,
    Resource,
    ResourceManifest,
    SkillExport,
    SourceSnapshot,
)

REPO_AGENT_SCHEMA_VERSION = "repo-agent.v0"
REPO_AGENT_STATUS_ACTIVE = "active"
REPO_AGENT_STATUS_ARCHIVED = "archived"
REPO_AGENT_VERSION_DRAFT = "draft"
REPO_AGENT_VERSION_PUBLISHED = "published"
REPO_AGENT_VERSION_SUPERSEDED = "superseded"
REPO_AGENT_VERSION_INVALIDATED = "invalidated"
REPO_AGENT_VERSION_FAILED = "failed"
AGENT_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,62}$")
RESERVED_AGENT_KEYS = {"new", "settings", "api", "admin", "current", "versions"}


@dataclass(frozen=True)
class RepoAgentCompileResult:
    version: RepoAgentVersion
    unchanged: bool = False


def normalize_agent_key(value: str) -> str:
    key = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    key = re.sub(r"-+", "-", key)[:63]
    if len(key) < 3:
        key = f"repo-{key}".strip("-")
    if not AGENT_KEY_RE.match(key) or key in RESERVED_AGENT_KEYS:
        raise ValueError("agent key must be 3-63 lowercase letters, numbers, or hyphens and cannot be reserved")
    return key


def canonical_hash(payload: dict[str, Any]) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def latest_manifest(session: Session, resource: Resource) -> tuple[SourceSnapshot | None, ResourceManifest | None]:
    snapshot_stmt = (
        select(SourceSnapshot)
        .where(
            SourceSnapshot.workspace_id == resource.workspace_id,
            SourceSnapshot.project_id == resource.project_id,
            SourceSnapshot.resource_id == resource.id,
            SourceSnapshot.status == "indexed",
        )
        .order_by(SourceSnapshot.created_at.desc())
        .limit(1)
    )
    if resource.current_snapshot_id:
        preferred = session.scalar(
            select(SourceSnapshot).where(
                SourceSnapshot.id == resource.current_snapshot_id,
                SourceSnapshot.workspace_id == resource.workspace_id,
                SourceSnapshot.project_id == resource.project_id,
                SourceSnapshot.resource_id == resource.id,
            )
        )
        snapshot = preferred or session.scalar(snapshot_stmt)
    else:
        snapshot = session.scalar(snapshot_stmt)
    if not snapshot:
        return None, None
    manifest = session.scalar(
        select(ResourceManifest).where(
            ResourceManifest.workspace_id == resource.workspace_id,
            ResourceManifest.project_id == resource.project_id,
            ResourceManifest.resource_id == resource.id,
            ResourceManifest.source_snapshot_id == snapshot.id,
        )
    )
    return snapshot, manifest


def current_pack_for_resource(session: Session, agent: RepoAgent, resource_id: UUID) -> ContextPackVersion | None:
    return session.scalar(
        select(ContextPackVersion)
        .join(ContextPackResourceCoverage, ContextPackResourceCoverage.context_pack_version_id == ContextPackVersion.id)
        .where(
            ContextPackVersion.workspace_id == agent.workspace_id,
            ContextPackVersion.project_id == agent.project_id,
            ContextPackVersion.pack_key == agent.pack_key,
            ContextPackVersion.status == "published",
            ContextPackResourceCoverage.resource_id == resource_id,
        )
        .order_by(ContextPackVersion.version.desc())
        .limit(1)
    )


def approved_skill_export_for_pack(session: Session, pack: ContextPackVersion | None) -> SkillExport | None:
    if pack is None:
        return None
    return session.scalar(
        select(SkillExport)
        .where(
            SkillExport.workspace_id == pack.workspace_id,
            SkillExport.project_id == pack.project_id,
            SkillExport.context_pack_version_id == pack.id,
            SkillExport.status == "approved",
        )
        .order_by(SkillExport.export_version.desc())
        .limit(1)
    )


def next_repo_agent_version(session: Session, agent_id: UUID) -> int:
    return int(session.scalar(select(func.coalesce(func.max(RepoAgentVersion.version), 0)).where(RepoAgentVersion.repo_agent_id == agent_id)) or 0) + 1


def current_repo_agent_version(session: Session, agent: RepoAgent) -> RepoAgentVersion | None:
    if not agent.current_version_id:
        return None
    return session.scalar(select(RepoAgentVersion).where(RepoAgentVersion.id == agent.current_version_id, RepoAgentVersion.repo_agent_id == agent.id))


def build_version_payload(
    *,
    agent: RepoAgent,
    resource: Resource | None,
    snapshot: SourceSnapshot | None,
    manifest: ResourceManifest | None,
    pack: ContextPackVersion | None,
    skill_export: SkillExport | None,
    current: RepoAgentVersion | None,
    rollback_from: RepoAgentVersion | None = None,
) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], str]:
    validation_errors: list[dict[str, str]] = []
    validation_warnings: list[dict[str, str]] = []
    if resource is None:
        validation_errors.append({"code": "resource_scrubbed", "message": "Repo Agent has no active source resource."})
    elif resource.type.lower() != "git":
        validation_errors.append({"code": "not_git", "message": "Repo Agent V0 requires a Git resource."})
    if snapshot is None or manifest is None:
        validation_errors.append({"code": "missing_index", "message": "Source needs a completed index before Repo Agent refresh."})
    if pack is None:
        validation_errors.append({"code": "missing_context_pack", "message": f"No published Context Pack '{agent.pack_key}' covers this Git resource."})
    if skill_export is None:
        validation_warnings.append({"code": "missing_skill_export", "message": "No approved generated skill export; pack-only runtime instructions will be used."})

    hash_payload = {
        "schema_version": REPO_AGENT_SCHEMA_VERSION,
        "resource_id": str(resource.id) if resource else None,
        "source_snapshot_id": str(snapshot.id) if snapshot else None,
        "resource_manifest_id": str(manifest.id) if manifest else None,
        "context_pack_version_id": str(pack.id) if pack else None,
        "context_pack_hash": pack.pack_hash if pack else None,
        "skill_export_id": str(skill_export.id) if skill_export else None,
        "skill_export_package_hash": skill_export.package_hash if skill_export else None,
        "update_policy": agent.update_policy_json,
        "rollback_from_version_hash": rollback_from.version_hash if rollback_from else None,
    }
    version_hash = canonical_hash(hash_payload)
    summary = {
        "schema_version": REPO_AGENT_SCHEMA_VERSION,
        "agent_key": agent.agent_key,
        "title": agent.title,
        "resource": {"id": str(resource.id), "name": resource.name, "uri": resource.uri, "type": resource.type, "branch": (resource.source_config or {}).get("branch")} if resource else None,
        "source_snapshot": {"id": str(snapshot.id), "version": snapshot.version, "version_kind": snapshot.version_kind, "indexed_at": snapshot.indexed_at.isoformat() if snapshot.indexed_at else None} if snapshot else None,
        "manifest": {"id": str(manifest.id), "hash": manifest.manifest_hash, "files": manifest.file_count, "sections": manifest.section_count} if manifest else None,
        "context_pack": {"pack_key": pack.pack_key, "version": pack.version, "hash": pack.pack_hash, "status": pack.status} if pack else None,
        "skill_export": {"id": str(skill_export.id), "version": skill_export.export_version, "hash": skill_export.package_hash, "status": skill_export.status} if skill_export else None,
        "read_only": True,
    }
    diff = {
        "from_version": current.version if current else None,
        "rollback_from_version": rollback_from.version if rollback_from else None,
        "source_snapshot_changed": bool(current and snapshot and str(current.source_snapshot_id) != str(snapshot.id)),
        "manifest_changed": bool(current and manifest and str(current.resource_manifest_id) != str(manifest.id)),
        "pack_changed": bool(current and pack and str(current.context_pack_version_id) != str(pack.id)),
        "skill_export_changed": bool(current and skill_export and str(current.skill_export_id) != str(skill_export.id)),
    }
    validation = {"ok": not validation_errors, "errors": validation_errors, "warnings": validation_warnings}
    install = {
        "mode": "pack_only" if skill_export is None else "generated_skill_available",
        "instructions": [
            "Use ContextSmith runtime context for this repo-agent.",
            f"Read from context_pack_key={agent.pack_key} and the published repo-agent version before answering.",
            "Do not perform production mutations unless explicitly authorized outside this Repo Agent V0 profile.",
        ],
        "skill_export_id": str(skill_export.id) if skill_export else None,
    }
    return version_hash, summary, diff, validation, install, REPO_AGENT_VERSION_DRAFT if validation["ok"] else REPO_AGENT_VERSION_FAILED


def compile_repo_agent_version(session: Session, agent: RepoAgent, resource: Resource | None, *, actor_id: UUID | None, rollback_from: RepoAgentVersion | None = None) -> RepoAgentCompileResult:
    snapshot: SourceSnapshot | None = None
    manifest: ResourceManifest | None = None
    pack: ContextPackVersion | None = None
    skill_export: SkillExport | None = None
    if resource is not None:
        snapshot, manifest = latest_manifest(session, resource)
        pack = current_pack_for_resource(session, agent, resource.id)
        skill_export = approved_skill_export_for_pack(session, pack)
    if rollback_from is not None:
        snapshot = session.get(SourceSnapshot, rollback_from.source_snapshot_id) if rollback_from.source_snapshot_id else None
        manifest = session.get(ResourceManifest, rollback_from.resource_manifest_id) if rollback_from.resource_manifest_id else None
        pack = session.get(ContextPackVersion, rollback_from.context_pack_version_id) if rollback_from.context_pack_version_id else None
        skill_export = session.get(SkillExport, rollback_from.skill_export_id) if rollback_from.skill_export_id else None
    current = current_repo_agent_version(session, agent)
    version_hash, summary, diff, validation, install, status = build_version_payload(agent=agent, resource=resource, snapshot=snapshot, manifest=manifest, pack=pack, skill_export=skill_export, current=current, rollback_from=rollback_from)
    existing = session.scalar(
        select(RepoAgentVersion).where(RepoAgentVersion.repo_agent_id == agent.id, RepoAgentVersion.version_hash == version_hash, RepoAgentVersion.status == status)
    )
    if existing:
        return RepoAgentCompileResult(existing, unchanged=True)
    version = RepoAgentVersion(
        workspace_id=agent.workspace_id,
        project_id=agent.project_id,
        repo_agent_id=agent.id,
        resource_id=resource.id if resource else None,
        version=next_repo_agent_version(session, agent.id),
        status=status,
        source_snapshot_id=snapshot.id if snapshot else None,
        resource_manifest_id=manifest.id if manifest else None,
        context_pack_version_id=pack.id if pack else None,
        skill_export_id=skill_export.id if skill_export else None,
        version_hash=version_hash,
        summary_json=summary,
        diff_json=diff,
        validation_json=validation,
        install_json=install,
        rollback_from_version_id=rollback_from.id if rollback_from else None,
        created_by=actor_id,
    )
    session.add(version)
    session.flush()
    return RepoAgentCompileResult(version, unchanged=False)
