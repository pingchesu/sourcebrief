from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from sourcebrief_api.schemas import RepoAgentBriefRead
from sourcebrief_shared.models import Resource

MetadataSanitizer = Callable[[str | None], str]
UriSanitizer = Callable[[str], str]


@dataclass(frozen=True)
class RepoAgentBriefDeps:
    sanitize_metadata_text: MetadataSanitizer
    sanitize_public_uri: UriSanitizer


ENTRYPOINT_RE = re.compile(r"(^|/)(main|app|server|cli|manage|index|worker|run|startup)\.(py|ts|tsx|js|go|rs|java)$", re.I)
CONFIG_RE = re.compile(r"(^|/)(Dockerfile|docker-compose.*\.ya?ml|compose.*\.ya?ml|pyproject\.toml|package\.json|Makefile|.*config.*\.(ya?ml|json|toml|py|ts)|\.github/workflows/.*\.ya?ml)$", re.I)
RUNTIME_RE = re.compile(r"(^|/)(deploy|deployment|runtime|infra|scripts|helm|k8s|compose|docker|\.github/workflows)(/|$)", re.I)
RUNBOOK_RE = re.compile(r"(^|/)(README|RUNBOOK|OPERATION|OPERATIONS|docs/.*|.*runbook.*)\.(md|rst|txt)$", re.I)

def collect_matching_paths(session: Session, resource: Resource, pattern: re.Pattern[str], *, limit: int = 8) -> list[str]:
    if resource.current_snapshot_id is None:
        return []
    rows = session.execute(
        text(
            """
            SELECT DISTINCT COALESCE(NULLIF(path, ''), title) AS path
            FROM chunks
            WHERE workspace_id = :ws
              AND project_id = :proj
              AND resource_id = :res
              AND source_snapshot_id = :snap
              AND deleted_at IS NULL
              AND COALESCE(NULLIF(path, ''), title) IS NOT NULL
            ORDER BY path ASC
            """
        ),
        {"ws": resource.workspace_id, "proj": resource.project_id, "res": resource.id, "snap": resource.current_snapshot_id},
    ).mappings().all()
    matches = [str(row["path"]) for row in rows if pattern.search(str(row["path"]))]
    return matches[:limit]


def repo_agent_readiness(resource: Resource, stats: Mapping[str, Any]) -> str:
    if resource.status != "active" or resource.archived_at is not None:
        return "inactive"
    if not resource.retrieval_enabled:
        return "retrieval-off"
    if resource.current_snapshot_id is None:
        return "not-indexed"
    if int(stats.get("chunk_count") or 0) == 0:
        return "empty-index"
    if int(stats.get("embedding_count") or 0) == 0:
        return "no-embeddings"
    if resource.review_status in {"needs_update", "stale"}:
        return "needs-review"
    return "ready"


def repo_agent_brief_response(
    session: Session,
    workspace_id: UUID,
    project_id: UUID,
    resource: Resource,
    deps: RepoAgentBriefDeps,
) -> RepoAgentBriefRead:
    if resource.type.lower() != "git":
        raise HTTPException(status_code=422, detail="repo-agent brief is only available for git resources")
    stats = cast(
        Mapping[str, Any],
        session.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM chunks c WHERE c.workspace_id = :ws AND c.project_id = :proj AND c.resource_id = :res AND c.source_snapshot_id = :snap AND c.deleted_at IS NULL) AS chunk_count,
                  (SELECT COUNT(*) FROM code_symbols cs WHERE cs.workspace_id = :ws AND cs.project_id = :proj AND cs.resource_id = :res AND cs.source_snapshot_id = :snap AND cs.deleted_at IS NULL) AS symbol_count,
                  (SELECT COUNT(*) FROM graph_nodes gn WHERE gn.workspace_id = :ws AND gn.project_id = :proj AND gn.resource_id = :res AND gn.source_snapshot_id = :snap) AS graph_node_count,
                  (SELECT COUNT(*) FROM graph_edges ge WHERE ge.workspace_id = :ws AND ge.project_id = :proj AND ge.resource_id = :res AND ge.source_snapshot_id = :snap) AS graph_edge_count,
                  (SELECT COUNT(*) FROM chunk_embeddings ce WHERE ce.workspace_id = :ws AND ce.project_id = :proj AND ce.resource_id = :res AND ce.source_snapshot_id = :snap) AS embedding_count,
                  (SELECT MAX(finished_at) FROM index_runs ir WHERE ir.workspace_id = :ws AND ir.project_id = :proj AND ir.resource_id = :res AND ir.status = 'succeeded') AS last_index_finished_at,
                  (SELECT status FROM index_runs ir WHERE ir.workspace_id = :ws AND ir.project_id = :proj AND ir.resource_id = :res ORDER BY created_at DESC LIMIT 1) AS last_index_status,
                  (SELECT metadata FROM source_snapshots ss WHERE ss.id = :snap AND ss.workspace_id = :ws AND ss.project_id = :proj AND ss.resource_id = :res) AS snapshot_metadata
                """
            ),
            {"ws": workspace_id, "proj": project_id, "res": resource.id, "snap": resource.current_snapshot_id},
        ).mappings().first()
        or {},
    )
    snapshot_metadata = cast(dict[str, Any], stats.get("snapshot_metadata") if isinstance(stats.get("snapshot_metadata"), dict) else {})
    source_config = cast(dict[str, Any], resource.source_config or {})
    entrypoints = collect_matching_paths(session, resource, ENTRYPOINT_RE)
    configs = collect_matching_paths(session, resource, CONFIG_RE)
    runtime_paths = collect_matching_paths(session, resource, RUNTIME_RE)
    runbooks = collect_matching_paths(session, resource, RUNBOOK_RE)
    symbol_rows = session.execute(
        text(
            """
            SELECT path, name, kind, language, line_start, line_end, signature, content_hash
            FROM code_symbols
            WHERE workspace_id = :ws
              AND project_id = :proj
              AND resource_id = :res
              AND source_snapshot_id = :snap
              AND deleted_at IS NULL
            ORDER BY CASE kind WHEN 'class' THEN 0 WHEN 'function' THEN 1 ELSE 2 END, path ASC, line_start ASC
            LIMIT 12
            """
        ),
        {"ws": workspace_id, "proj": project_id, "res": resource.id, "snap": resource.current_snapshot_id},
    ).mappings().all()
    symbol_samples = [
        {
            "path": row["path"],
            "name": row["name"],
            "kind": row["kind"],
            "language": row["language"],
            "line_start": row["line_start"],
            "line_end": row["line_end"],
            "signature": row["signature"],
            "content_hash": row["content_hash"],
        }
        for row in symbol_rows
    ]
    readiness = repo_agent_readiness(resource, stats)
    branch = source_config.get("branch") or source_config.get("ref") or snapshot_metadata.get("branch")
    commit = snapshot_metadata.get("commit") or snapshot_metadata.get("version")
    last_index_finished_at = stats.get("last_index_finished_at")
    suggested_questions = [
        f"What is {resource.name} responsible for? Cite exact files.",
        f"Show {resource.name}'s main entrypoints, configs, and runtime/deployment boundaries.",
        f"What tests or checks should run before changing {resource.name}?",
        f"Find runbooks, operational risks, and production-mutation boundaries for {resource.name}.",
    ]
    quality_gates = [
        "current_snapshot_id is present" if resource.current_snapshot_id else "missing current_snapshot_id",
        f"chunks={int(stats.get('chunk_count') or 0)}",
        f"embeddings={int(stats.get('embedding_count') or 0)}",
        f"symbols={int(stats.get('symbol_count') or 0)}",
        f"last_index_status={stats.get('last_index_status') or 'unknown'}",
        f"review_status={resource.review_status}",
    ]
    brief_lines = [
        f"{resource.name} is a git-backed repo sub-agent scoped to resource `{resource.id}`.",
        f"Readiness: {readiness}. Branch/ref: {branch or 'default'}. Commit/version: {commit or resource.current_snapshot_id or 'none'}.",
        f"Index shape: {int(stats.get('chunk_count') or 0)} chunks, {int(stats.get('symbol_count') or 0)} symbols, {int(stats.get('graph_node_count') or 0)} graph nodes, {int(stats.get('embedding_count') or 0)} embeddings.",
    ]
    if entrypoints:
        brief_lines.append("Likely entrypoints: " + ", ".join(entrypoints[:5]) + ".")
    if configs:
        brief_lines.append("Likely config/build files: " + ", ".join(configs[:5]) + ".")
    if runtime_paths:
        brief_lines.append("Likely runtime/deployment paths: " + ", ".join(runtime_paths[:5]) + ".")
    if runbooks:
        brief_lines.append("Likely docs/runbooks: " + ", ".join(runbooks[:5]) + ".")
    brief_lines.append("Use this repo-agent for repo-specific explanation, code navigation, cited operating briefs, and change-impact questions. Do not use it as authorization for production mutations.")
    return RepoAgentBriefRead(
        resource_id=resource.id,
        name=deps.sanitize_metadata_text(resource.name),
        uri=deps.sanitize_public_uri(resource.uri),
        readiness=readiness,
        current_snapshot_id=resource.current_snapshot_id,
        branch=branch,
        commit=commit,
        update_frequency=resource.update_frequency,
        freshness={
            "review_status": resource.review_status,
            "last_refresh_finished_at": resource.last_refresh_finished_at.isoformat() if resource.last_refresh_finished_at else None,
            "next_refresh_at": resource.next_refresh_at.isoformat() if resource.next_refresh_at else None,
            "last_index_finished_at": last_index_finished_at.isoformat() if isinstance(last_index_finished_at, datetime) else None,
            "last_index_status": stats.get("last_index_status"),
        },
        stats={
            "chunk_count": int(stats.get("chunk_count") or 0),
            "symbol_count": int(stats.get("symbol_count") or 0),
            "graph_node_count": int(stats.get("graph_node_count") or 0),
            "graph_edge_count": int(stats.get("graph_edge_count") or 0),
            "embedding_count": int(stats.get("embedding_count") or 0),
        },
        operating_brief="\n".join(brief_lines),
        entrypoint_paths=entrypoints,
        config_paths=configs,
        runtime_paths=runtime_paths,
        runbook_paths=runbooks,
        symbol_samples=symbol_samples,
        suggested_questions=suggested_questions,
        invocation={
            "endpoint": f"/workspaces/{workspace_id}/projects/{project_id}/agent-context",
            "body": {"runtime": "hermes", "resource_ids": [str(resource.id)], "include_code_symbols": True},
        },
        safety_boundary="Context only. Production mutations require Hermes approval, typed MCP tools, and evidence workflow.",
        quality_gates=quality_gates,
    )
