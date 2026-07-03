from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal, require_principal
from sourcebrief_shared.db import get_session

RuntimeGraphOverview = Callable[[Session, UUID, UUID, Principal, dict[str, Any]], dict[str, Any]]


@dataclass(frozen=True)
class ArchitectureRouterDeps:
    runtime_graph_overview: RuntimeGraphOverview


router = APIRouter()
_deps: ArchitectureRouterDeps


def create_router(deps: ArchitectureRouterDeps) -> APIRouter:
    global _deps
    _deps = deps
    return router


@router.get("/workspaces/{workspace_id}/projects/{project_id}/architecture")
def get_project_architecture(
    workspace_id: UUID,
    project_id: UUID,
    max_resources: int = 20,
    max_items: int = 20,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    return _deps.runtime_graph_overview(
        session,
        workspace_id,
        project_id,
        principal,
        {"max_resources": max_resources, "max_items": max_items},
    )
