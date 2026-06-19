from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from contextsmith_shared.models import (
    ContextPackArtifact,
    ContextPackResourceCoverage,
    ContextPackVersion,
    Resource,
    SkillExport,
    SnapshotFile,
)

EXPORT_TYPE_HERMES_SKILL = "hermes_skill"
SKILL_EXPORT_STATUS_DRAFT = "draft"
SKILL_EXPORT_STATUS_APPROVED = "approved"
SKILL_EXPORT_STATUS_REJECTED = "rejected"
SKILL_EXPORT_STATUS_INVALIDATED = "invalidated"
SKILL_EXPORT_STATUS_FAILED = "failed"
GENERATOR_VERSION = "skill-export.v1"
FORBIDDEN_PATTERNS = [
    r"/home/",
    r"/tmp/",
    r"/var/lib/",
    r"/qa-fixtures/",
    r"file://",
    r"CONTEXTSMITH_ADMIN_PASSWORD",
    r"session_token",
    r"cs_[A-Za-z0-9_-]{12,}",
    r"Bearer\s+",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
]


@dataclass(frozen=True)
class CompiledSkillExport:
    status: str
    package_hash: str
    manifest: dict[str, Any]
    files: list[dict[str, Any]]
    validation: dict[str, Any]
    leak_scan: dict[str, Any]


def _sha256_text(content: str) -> str:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _file(path: str, kind: str, content: str) -> dict[str, Any]:
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    return {"path": path, "kind": kind, "sha256": _sha256_text(normalized), "bytes": len(normalized.encode("utf-8")), "content": normalized}


def _skill_name(pack_key: str) -> str:
    return f"contextsmith-{pack_key.replace('_', '-').replace('.', '-')}"


def _resource_names(session: Session, version: ContextPackVersion) -> list[str]:
    rows = session.execute(
        select(Resource.name)
        .join(ContextPackResourceCoverage, ContextPackResourceCoverage.resource_id == Resource.id)
        .where(ContextPackResourceCoverage.context_pack_version_id == version.id)
        .order_by(Resource.name.asc())
    ).all()
    seen: list[str] = []
    for (name,) in rows:
        if name not in seen:
            seen.append(name)
    return seen


def _coverage_counts(session: Session, version: ContextPackVersion) -> dict[str, int]:
    artifact_count = session.scalar(select(func.count(ContextPackArtifact.id)).where(ContextPackArtifact.context_pack_version_id == version.id)) or 0
    resource_count = session.scalar(select(func.count(func.distinct(ContextPackResourceCoverage.resource_id))).where(ContextPackResourceCoverage.context_pack_version_id == version.id)) or 0
    citation_count = session.scalar(select(func.coalesce(func.sum(ContextPackResourceCoverage.citation_count), 0)).where(ContextPackResourceCoverage.context_pack_version_id == version.id)) or 0
    return {"artifacts": int(artifact_count), "resources": int(resource_count), "citations": int(citation_count)}


def _render_skill(version: ContextPackVersion, title: str, summary: str | None, resources: list[str], counts: dict[str, int]) -> str:
    name = _skill_name(version.pack_key)
    resource_lines = "\n".join(f"- {name}" for name in resources[:20]) or "- No named resources recorded"
    description = summary or f"Use ContextSmith published pack {version.pack_key} v{version.version} for cited runtime context."
    return f"""---
name: {name}
description: {description}
version: {version.version}
contextsmith:
  pack_key: {version.pack_key}
  pack_version: {version.version}
  pack_hash: {version.pack_hash}
  runtime: contextsmith.get_agent_context
---

# ContextSmith runtime skill: {title}

Use this skill when a user asks about knowledge covered by ContextSmith Context Pack `{version.pack_key}` version `{version.version}`.

## Source-of-truth boundary

- This package contains instructions only. It intentionally does not embed source corpus, chunks, retrieved snippets, embeddings, or graph indexes.
- ContextSmith is the source of truth. Request context at runtime and cite returned evidence.
- Pack pin: `{version.pack_key}` v`{version.version}` / `{version.pack_hash}`.

## Covered source labels

{resource_lines}

Coverage counts: {counts['resources']} resources, {counts['artifacts']} artifacts, {counts['citations']} citations.

## Runtime workflow

1. Call ContextSmith with the user query and the pinned pack selector:

```http
POST /workspaces/{{workspace_id}}/projects/{{project_id}}/agent-context
{{
  "query": "<user question>",
  "runtime": "hermes",
  "top_k": 8,
  "context_pack_key": "{version.pack_key}",
  "context_pack_version": {version.version}
}}
```

If MCP is available, first call `tools/list` and prefer the artifact-aware runtime flow when these tools are advertised:

1. `contextsmith.get_context_pack` with `pack_key` / `version` to inspect the pinned pack, freshness, sources, and graph inventory.
2. `contextsmith.search` with `context_pack_key` / `context_pack_version` to find cited section evidence.
3. `contextsmith.read_section` using the canonical locator returned by `search`, `get_context_pack`, or `get_resource_map` before making source-specific claims.
4. `contextsmith.get_graph_inventory`, `contextsmith.graph_query`, or `contextsmith.graph_path` for architecture and impact questions.
5. Fall back to stable `contextsmith.get_agent_context` with the same selector when expanded MCP tools are not advertised. Use `search_code`, `grep_code`, `read_file`, and `find_symbol` only for exact repo file/symbol evidence.

2. Before answering, verify the response contains:
   - `context_pack_key == "{version.pack_key}"`
   - `context_pack_version == {version.version}`
   - `context_pack_snapshot_pin_enforced == true`
   - citations for the claims you will make.
3. Answer only from returned evidence. Cite paths/sections from ContextSmith citations. If evidence is insufficient, say so and request more context.
4. If ContextSmith is unavailable, the pack is invalidated, or the returned pack metadata does not match this file, do not guess. Report degraded context.

## Freshness and mutation boundary

- Treat ContextSmith freshness warnings as blocking for production-sensitive claims.
- Do not perform production mutations based only on generated skill text. Ask for explicit user approval and use typed, scoped tools.

## Failure modes

- Auth denied: ask the user to grant ContextSmith access; do not ask for raw bearer tokens in chat.
- Missing MCP: use REST/API fallback if configured, otherwise ask the user to configure ContextSmith runtime access.
- No citations: state that no grounded answer is available.
"""


def _render_readme(version: ContextPackVersion, title: str, status: str) -> str:
    return f"""# {title}

This is a generated ContextSmith runtime adapter for Context Pack `{version.pack_key}` v`{version.version}`.

Status: `{status}`. External install/copy is allowed only after the export is `approved` in ContextSmith.

The package contains no source corpus. It requires ContextSmith runtime access and uses the pinned `context_pack_key` + `context_pack_version` selector.

Install by copying `SKILL.md` into a runtime skill directory only after approval. Keep `manifest.json` beside it for audit.
"""


def _manifest_hash_form(version: ContextPackVersion, export_type: str, title: str, summary: str | None, resources: list[str], counts: dict[str, int]) -> dict[str, Any]:
    return {
        "schema_version": GENERATOR_VERSION,
        "export_type": export_type,
        "title": title,
        "summary": summary,
        "pack_key": version.pack_key,
        "pack_version": version.version,
        "pack_hash": version.pack_hash,
        "coverage": counts,
        "resources": resources,
        "volatile_placeholders": {"generated_at": "<excluded>", "package_hash": "<excluded>", "export_status": "<mutable>"},
    }


def _source_text_markers(session: Session, version: ContextPackVersion) -> list[str]:
    snapshot_ids = list(
        session.scalars(
            select(ContextPackResourceCoverage.source_snapshot_id)
            .where(ContextPackResourceCoverage.context_pack_version_id == version.id)
            .distinct()
        )
    )
    if not snapshot_ids:
        return []
    contents = session.scalars(
        select(SnapshotFile.content)
        .where(SnapshotFile.source_snapshot_id.in_(snapshot_ids))
        .limit(200)
    ).all()
    markers: list[str] = []
    for content in contents:
        for raw_line in str(content or "").splitlines():
            line = " ".join(raw_line.strip().split())
            if len(line) >= 48 and line not in markers:
                markers.append(line)
            if len(markers) >= 100:
                return markers
    return markers


def _scan_files(files: list[dict[str, Any]], source_markers: list[str] | None = None) -> dict[str, Any]:
    findings: list[dict[str, str]] = []
    caps = {"SKILL.md": 24_000, "README.md": 12_000, "manifest.json": 24_000}
    markers = source_markers or []
    for file in files:
        path = str(file["path"])
        content = str(file.get("content", ""))
        normalized_content = " ".join(content.split())
        if file.get("bytes", 0) > caps.get(path, 24_000):
            findings.append({"path": path, "code": "file_too_large", "message": f"{path} exceeds export size cap"})
        for pattern in FORBIDDEN_PATTERNS:
            if re.search(pattern, content):
                findings.append({"path": path, "code": "forbidden_pattern", "message": pattern})
        for marker in markers:
            if marker and marker in normalized_content:
                findings.append({"path": path, "code": "source_text_marker", "message": marker[:120]})
                break
    return {"ok": not findings, "findings": findings}


def _validate_files(files: list[dict[str, Any]], skill_content: str) -> dict[str, Any]:
    paths = {str(file["path"]) for file in files}
    errors: list[dict[str, str]] = []
    for required in {"SKILL.md", "README.md", "manifest.json"}:
        if required not in paths:
            errors.append({"code": "missing_file", "message": f"Missing {required}"})
    required_text = ["context_pack_key", "context_pack_version", "context_pack_snapshot_pin_enforced", "contextsmith.get_agent_context", "citations", "mutation boundary"]
    for needle in required_text:
        if needle not in skill_content:
            errors.append({"code": "missing_instruction", "message": f"SKILL.md missing {needle}"})
    return {"ok": not errors, "errors": errors}


def compile_skill_export(session: Session, version: ContextPackVersion, *, title: str, summary: str | None, export_type: str = EXPORT_TYPE_HERMES_SKILL) -> CompiledSkillExport:
    counts = _coverage_counts(session, version)
    resources = _resource_names(session, version)
    skill_content = _render_skill(version, title, summary, resources, counts)
    readme_content = _render_readme(version, title, SKILL_EXPORT_STATUS_DRAFT)
    manifest_hash = _manifest_hash_form(version, export_type, title, summary, resources, counts)
    manifest_hash_content = _canonical_json(manifest_hash) + "\n"
    hash_files = [_file("README.md", "markdown", readme_content), _file("SKILL.md", "skill", skill_content), _file("manifest.hash.json", "json", manifest_hash_content)]
    package_inputs = {"schema_version": GENERATOR_VERSION, "export_type": export_type, "pack_key": version.pack_key, "pack_version": version.version, "pack_hash": version.pack_hash, "files": [{"path": f["path"], "sha256": f["sha256"], "bytes": f["bytes"]} for f in sorted(hash_files, key=lambda f: str(f["path"]))]}
    package_hash = _sha256_text(_canonical_json(package_inputs) + "\n")
    manifest = {
        **manifest_hash,
        "package_hash": package_hash,
        "generated_at": datetime.now(UTC).isoformat(),
        "export_status": SKILL_EXPORT_STATUS_DRAFT,
        "approval": None,
        "package_hash_inputs": package_inputs,
    }
    manifest_content = _canonical_json(manifest) + "\n"
    files = [_file("README.md", "markdown", readme_content), _file("SKILL.md", "skill", skill_content), _file("manifest.json", "json", manifest_content)]
    validation = _validate_files(files, skill_content)
    leak_scan = _scan_files(files, _source_text_markers(session, version))
    if not validation["ok"] or not leak_scan["ok"]:
        return CompiledSkillExport(status=SKILL_EXPORT_STATUS_FAILED, package_hash=package_hash, manifest={"failed": True, "package_hash": package_hash, "validation": validation, "leak_scan": leak_scan}, files=[], validation=validation, leak_scan=leak_scan)
    return CompiledSkillExport(status=SKILL_EXPORT_STATUS_DRAFT, package_hash=package_hash, manifest=manifest, files=files, validation=validation, leak_scan=leak_scan)


def next_export_version(session: Session, version: ContextPackVersion, export_type: str) -> int:
    current = session.scalar(select(func.max(SkillExport.export_version)).where(SkillExport.context_pack_version_id == version.id, SkillExport.export_type == export_type))
    return int(current or 0) + 1
