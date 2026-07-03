from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal, require_principal, require_scope
from sourcebrief_api.schemas import (
    SelfImprovementArtifactResponse,
    SelfImprovementHistoryResponse,
    SelfImprovementOverviewResponse,
    SelfImprovementRunRequest,
    SelfImprovementRunResponse,
    SelfImprovementSleepRequest,
)
from sourcebrief_shared.config import get_settings
from sourcebrief_shared.db import get_session
from sourcebrief_shared.models import AuditEvent
from sourcebrief_shared.review_history import (
    ReviewHistoryError,
    scan_review_history,
    show_review_history_record,
)
from sourcebrief_shared.self_improvement_mvp import run_mvp_smoke_path
from sourcebrief_shared.self_improvement_sleep import (
    SleepReplayError,
    run_sleep_replay,
    write_sleep_replay_summary,
)

ProjectAccessAuthorizer = Callable[[Session, UUID, UUID, Principal], object]
ProjectMemberAuthorizer = Callable[..., object]


@dataclass(frozen=True)
class SelfImprovementRouterDeps:
    require_project_access: ProjectAccessAuthorizer
    require_project_member: ProjectMemberAuthorizer


def self_improvement_project_root(workspace_id: UUID, project_id: UUID) -> Path:
    configured = Path(get_settings().self_improvement_root).expanduser()
    base = configured if configured.is_absolute() else Path.cwd() / configured
    return base / str(workspace_id) / str(project_id)


def history_response(root: Path) -> dict[str, Any]:
    if not root.exists():
        return {"root": str(root), "records": [], "metrics": {"record_count": 0}, "provenance": []}
    return scan_review_history(root).model_dump(mode="json")


def run_dir(root: Path, prefix: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return root / "runs" / f"{prefix}-{stamp}"


def create_router(deps: SelfImprovementRouterDeps) -> APIRouter:
    router = APIRouter()

    @router.get(
        "/workspaces/{workspace_id}/projects/{project_id}/self-improvement",
        response_model=SelfImprovementOverviewResponse,
    )
    def get_self_improvement_overview(
        workspace_id: UUID,
        project_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        require_scope(principal, "review:read")
        deps.require_project_access(session, workspace_id, project_id, principal)
        root = self_improvement_project_root(workspace_id, project_id)
        return {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "root": str(root),
            "no_silent_mutation": True,
            "shipped_surfaces": [
                "review-bundle capture",
                "local reviewer report",
                "regression proposal",
                "deterministic validation gate",
                "staged patch/receipt",
                "review history",
                "MVP smoke",
                "sleep/replay dry-run",
            ],
            "next_safe_actions": [
                "Run MVP smoke to create a complete local artifact chain.",
                "Inspect redacted artifact history before adopting any proposed improvement.",
                "Run sleep/replay dry-run only after multiple proposal artifacts exist.",
            ],
            "history": history_response(root),
        }

    @router.get(
        "/workspaces/{workspace_id}/projects/{project_id}/self-improvement/history",
        response_model=SelfImprovementHistoryResponse,
    )
    def list_self_improvement_history(
        workspace_id: UUID,
        project_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        require_scope(principal, "review:read")
        deps.require_project_access(session, workspace_id, project_id, principal)
        return history_response(self_improvement_project_root(workspace_id, project_id))

    @router.get(
        "/workspaces/{workspace_id}/projects/{project_id}/self-improvement/artifacts/{artifact_id}",
        response_model=SelfImprovementArtifactResponse,
    )
    def get_self_improvement_artifact(
        workspace_id: UUID,
        project_id: UUID,
        artifact_id: str,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        require_scope(principal, "review:read")
        deps.require_project_access(session, workspace_id, project_id, principal)
        root = self_improvement_project_root(workspace_id, project_id)
        try:
            return show_review_history_record(root, artifact_id)
        except ReviewHistoryError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/self-improvement/mvp-smoke",
        response_model=SelfImprovementRunResponse,
    )
    def run_self_improvement_mvp_smoke(
        workspace_id: UUID,
        project_id: UUID,
        payload: SelfImprovementRunRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        require_scope(principal, "review:write")
        deps.require_project_member(
            session, workspace_id, project_id, principal, required_scopes={"review:write"}
        )
        root = self_improvement_project_root(workspace_id, project_id)
        out_dir = run_dir(root, "mvp-smoke")
        try:
            summary = run_mvp_smoke_path(
                out_dir=out_dir, finding_id=payload.finding_id, owner=payload.owner
            )
            history = history_response(root)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="self_improvement.mvp_smoke",
                target_type="project",
                target_id=project_id,
                meta={
                    "out_dir": str(out_dir),
                    "proposal_id": summary.get("proposal_id"),
                    "gate_decision": summary.get("gate_decision"),
                },
            )
        )
        session.commit()
        return {"status": "completed", "out_dir": str(out_dir), "summary": summary, "history": history}

    @router.post(
        "/workspaces/{workspace_id}/projects/{project_id}/self-improvement/sleep",
        response_model=SelfImprovementRunResponse,
    )
    def run_self_improvement_sleep(
        workspace_id: UUID,
        project_id: UUID,
        payload: SelfImprovementSleepRequest,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> dict[str, Any]:
        require_scope(principal, "review:write")
        deps.require_project_member(
            session, workspace_id, project_id, principal, required_scopes={"review:write"}
        )
        root = self_improvement_project_root(workspace_id, project_id)
        root.mkdir(parents=True, exist_ok=True)
        out_dir = run_dir(root, "sleep")
        try:
            summary_model = run_sleep_replay(
                root,
                out_dir=out_dir,
                min_occurrences=payload.min_occurrences,
                max_artifacts=payload.max_artifacts,
                dry_run=True,
            )
            summary_path = out_dir / "summary.json"
            write_sleep_replay_summary(summary_path, summary_model)
            history = history_response(root)
        except (OSError, SleepReplayError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        summary = summary_model.model_dump(mode="json")
        summary["summary_path"] = str(summary_path)
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="self_improvement.sleep_dry_run",
                target_type="project",
                target_id=project_id,
                meta={"out_dir": str(out_dir), "candidate_count": len(summary_model.candidates)},
            )
        )
        session.commit()
        return {"status": "completed", "out_dir": str(out_dir), "summary": summary, "history": history}

    return router
