from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from sourcebrief_api.auth import Principal
from sourcebrief_api.routers import remote_code as remote_code_router
from sourcebrief_api.schemas import (
    CodeSearchRequest,
    GeneratePatchRequest,
    OpenPrRequest,
    RemoteFindSymbolRequest,
    RemoteFindSymbolResponse,
    RemoteGrepCodeRequest,
    RemoteGrepCodeResponse,
    RemoteReadFileRequest,
    RemoteReadFileResponse,
    RemoteSearchCodeRequest,
    RemoteSearchCodeResponse,
    SearchRequest,
)


def remote_search_code(
    workspace_id: UUID,
    project_id: UUID,
    payload: RemoteSearchCodeRequest,
    principal: Principal,
    session: Session,
) -> RemoteSearchCodeResponse:
    return remote_code_router.remote_search_code(workspace_id, project_id, payload, principal, session)


def search_project(
    workspace_id: UUID,
    project_id: UUID,
    payload: SearchRequest,
    principal: Principal,
    session: Session,
) -> Any:
    return remote_code_router.search_project(workspace_id, project_id, payload, principal, session)


def code_search_project(
    workspace_id: UUID,
    project_id: UUID,
    payload: CodeSearchRequest,
    principal: Principal,
    session: Session,
) -> Any:
    return remote_code_router.code_search_project(workspace_id, project_id, payload, principal, session)


def remote_generate_patch(
    workspace_id: UUID,
    project_id: UUID,
    payload: GeneratePatchRequest,
    principal: Principal,
    session: Session,
) -> Any:
    return remote_code_router.remote_generate_patch(workspace_id, project_id, payload, principal, session)


def remote_open_pr(
    workspace_id: UUID,
    project_id: UUID,
    payload: OpenPrRequest,
    principal: Principal,
    session: Session,
) -> Any:
    return remote_code_router.remote_open_pr(workspace_id, project_id, payload, principal, session)


def remote_grep_code(
    workspace_id: UUID,
    project_id: UUID,
    payload: RemoteGrepCodeRequest,
    principal: Principal,
    session: Session,
) -> RemoteGrepCodeResponse:
    return remote_code_router.remote_grep_code(workspace_id, project_id, payload, principal, session)


def remote_read_file(
    workspace_id: UUID,
    project_id: UUID,
    payload: RemoteReadFileRequest,
    principal: Principal,
    session: Session,
) -> RemoteReadFileResponse:
    return remote_code_router.remote_read_file(workspace_id, project_id, payload, principal, session)


def remote_find_symbol(
    workspace_id: UUID,
    project_id: UUID,
    payload: RemoteFindSymbolRequest,
    principal: Principal,
    session: Session,
) -> RemoteFindSymbolResponse:
    return remote_code_router.remote_find_symbol(workspace_id, project_id, payload, principal, session)


def execute_remote_code_rpc_call(
    workspace_id: UUID,
    project_id: UUID,
    call_method: str,
    params: dict[str, Any],
    principal: Principal,
    session: Session,
) -> dict[str, Any]:
    return remote_code_router._execute_remote_code_rpc_call(workspace_id, project_id, call_method, params, principal, session)


def remote_code_rpc_spec(
    workspace_id: UUID,
    project_id: UUID,
    principal: Principal,
    session: Session,
) -> Any:
    return remote_code_router.remote_code_rpc_spec(workspace_id, project_id, principal, session)


def remote_code_rpc(
    workspace_id: UUID,
    project_id: UUID,
    payload: Any,
    principal: Principal,
    session: Session,
) -> Any:
    return remote_code_router.remote_code_rpc(workspace_id, project_id, payload, principal, session)
