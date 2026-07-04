from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal, require_principal
from sourcebrief_api.schemas import ContextPacketRead, ContextPacketRequest
from sourcebrief_shared.db import get_session

McpEndpointAction = Callable[[UUID, UUID, Request, Principal, Session], Awaitable[dict | Response]]
ContextPacketAction = Callable[[UUID, UUID, ContextPacketRequest, Principal, Session], ContextPacketRead]


@dataclass(frozen=True)
class McpContextRouterDeps:
    mcp_endpoint_action: McpEndpointAction
    create_context_packet_action: ContextPacketAction


router = APIRouter()
_deps: McpContextRouterDeps


def create_router(deps: McpContextRouterDeps) -> APIRouter:
    global _deps
    _deps = deps
    return router


@router.post("/mcp/{workspace_id}/{project_id}", response_model=None)
async def mcp_endpoint(
    workspace_id: UUID,
    project_id: UUID,
    request: Request,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> dict | Response:
    return await _deps.mcp_endpoint_action(workspace_id, project_id, request, principal, session)


@router.post(
    "/workspaces/{workspace_id}/projects/{project_id}/context-packets",
    response_model=ContextPacketRead,
    status_code=201,
)
def create_context_packet(
    workspace_id: UUID,
    project_id: UUID,
    payload: ContextPacketRequest,
    principal: Principal = Depends(require_principal),
    session: Session = Depends(get_session),
) -> ContextPacketRead:
    return _deps.create_context_packet_action(workspace_id, project_id, payload, principal, session)
