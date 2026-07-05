from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal, token_allows_resource
from sourcebrief_api.constants import COMMON_AGENT_INSTRUCTION, RUNTIME_INSTRUCTIONS
from sourcebrief_api.schemas import AgentContextCitation, AgentContextRequest, AgentContextResponse
from sourcebrief_shared.models import (
    AgentProfile,
    ContextArtifactCitation,
    ContextPackArtifact,
    ContextPackVersion,
    SnapshotFile,
)

RuntimeCallable = Callable[..., Any]


@dataclass(frozen=True)
class AgentContextBuilderDeps:
    make_snippet: RuntimeCallable
    agent_context_resource_coverage: RuntimeCallable
    principal_has_scope: Callable[[Principal, str], bool]
    synthesize_agent_answer: RuntimeCallable
    agent_context_suggested_tool_calls: RuntimeCallable

def build_pack_agent_context_response(
    session: Session,
    *,
    workspace_id: UUID,
    project_id: UUID,
    payload: AgentContextRequest,
    principal: Principal,
    pack_version: ContextPackVersion,
    deps: AgentContextBuilderDeps,
) -> AgentContextResponse:
    predicates = [
        ContextPackArtifact.context_pack_version_id == pack_version.id,
        ContextArtifactCitation.workspace_id == workspace_id,
        ContextArtifactCitation.project_id == project_id,
    ]
    if payload.resource_ids:
        predicates.append(ContextArtifactCitation.resource_id.in_(payload.resource_ids))
    rows = session.execute(
        select(ContextArtifactCitation, SnapshotFile)
        .join(
            SnapshotFile,
            (SnapshotFile.source_snapshot_id == ContextArtifactCitation.source_snapshot_id)
            & (SnapshotFile.path == ContextArtifactCitation.normalized_path),
        )
        .join(ContextPackArtifact, ContextPackArtifact.context_artifact_id == ContextArtifactCitation.context_artifact_id)
        .where(*predicates)
        .order_by(ContextPackArtifact.ordinal.asc(), ContextArtifactCitation.normalized_path.asc(), ContextArtifactCitation.ordinal.asc())
        .limit(payload.top_k)
    ).all()
    citations: list[AgentContextCitation] = []
    context_parts: list[str] = []
    used_chars = 0
    for rank, (citation, snapshot_file) in enumerate(rows, start=1):
        if not token_allows_resource(principal, citation.resource_id):
            continue
        header = f"[{rank}] pack={pack_version.pack_key} v{pack_version.version} resource={citation.resource_id} snapshot={citation.source_snapshot_id} path={citation.normalized_path} ordinal={citation.ordinal}\n"
        remaining = payload.max_chars - used_chars - (2 if context_parts else 0)
        if remaining <= len(header):
            break
        snippet = deps.make_snippet(snapshot_file.content, limit=min(1200, max(120, remaining - len(header))))
        entry = header + snippet
        if len(entry) > remaining:
            entry = entry[:remaining]
        context_parts.append(entry)
        used_chars += len(entry) + (2 if len(context_parts) > 1 else 0)
        citations.append(
            AgentContextCitation(
                resource_id=citation.resource_id,
                snapshot_id=citation.source_snapshot_id,
                chunk_id=citation.section_id,
                path=citation.normalized_path,
                title=citation.title,
                ordinal=citation.ordinal,
                content_hash=citation.content_hash,
                version=pack_version.pack_hash,
                version_kind="context_pack",
                commit=None,
                score=1.0,
                graph_score=0.0,
            )
        )
    profile = session.scalar(select(AgentProfile).where(AgentProfile.workspace_id == workspace_id, AgentProfile.project_id == project_id))
    actual_runtime = payload.runtime or (profile.default_runtime if profile else "api")
    resource_coverage, coverage_warnings = deps.agent_context_resource_coverage(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        resource_ids=payload.resource_ids,
        citations=citations,
        principal=principal,
    )
    instruction_parts = [COMMON_AGENT_INSTRUCTION, RUNTIME_INSTRUCTIONS[actual_runtime], f"Use published Context Pack `{pack_version.pack_key}` v{pack_version.version}. Snapshot pinning is enforced; do not use newer source snapshots for this answer."]
    if coverage_warnings:
        instruction_parts.append("Coverage warning: " + " ".join(coverage_warnings))
    if profile and profile.system_prompt:
        instruction_parts.append(profile.system_prompt)
    can_read_code = deps.principal_has_scope(principal, "code:read")
    return AgentContextResponse(
        query=payload.query,
        profile="context_pack",
        runtime=actual_runtime,
        instruction=" ".join(instruction_parts),
        context="\n\n".join(context_parts),
        answer=(
            deps.synthesize_agent_answer(
                query=payload.query,
                context_parts=context_parts,
                citations=citations,
                resource_coverage=resource_coverage,
                coverage_warnings=coverage_warnings,
            )
            if payload.include_answer
            else None
        ),
        citations=citations,
        symbols=[],
        suggested_tool_calls=deps.agent_context_suggested_tool_calls(citations, payload.query, include_code_tools=can_read_code),
        token_budget_hint=max(1, payload.max_chars // 4),
        resource_coverage=resource_coverage,
        coverage_warnings=coverage_warnings,
        context_pack_key=pack_version.pack_key,
        context_pack_version=pack_version.version,
        context_pack_version_id=pack_version.id,
        context_pack_status=pack_version.status,
        context_pack_snapshot_pin_enforced=True,
    )
