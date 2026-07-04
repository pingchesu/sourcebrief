from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from sourcebrief_api.auth import (
    Principal,
    hash_password,
    hash_token,
    new_plaintext_token,
    require_principal,
    require_scope,
    require_workspace_member,
    session_scopes_for_role,
    token_allows_project,
    verify_password,
)
from sourcebrief_api.constants import ALLOWED_TOKEN_SCOPES
from sourcebrief_api.schemas import (
    ApiTokenCreate,
    ApiTokenCreateResponse,
    ApiTokenRead,
    AuthLoginRequest,
    AuthLoginResponse,
    AuthLogoutResponse,
    CurrentUserResponse,
    ProjectCreate,
    ProjectRead,
    UserRead,
    WorkspaceCreate,
    WorkspaceMemberCreate,
    WorkspaceMemberRead,
    WorkspaceMemberUpdate,
    WorkspaceRead,
)
from sourcebrief_shared.db import get_session
from sourcebrief_shared.models import (
    AgentProfile,
    ApiToken,
    AuditEvent,
    Project,
    ProjectMembership,
    Resource,
    User,
    Workspace,
    WorkspaceMembership,
)

ProjectAccessAuthorizer = Callable[[Session, UUID, UUID, Principal], Project]
AgentProfileEnsurer = Callable[[Session, UUID, Project, UUID], AgentProfile]


@dataclass(frozen=True)
class AuthWorkspaceRouterDeps:
    require_project_access: ProjectAccessAuthorizer
    ensure_agent_profile: AgentProfileEnsurer


def require_workspace_admin(session: Session, workspace_id: UUID, principal: Principal) -> WorkspaceMembership:
    membership = require_workspace_member(session, workspace_id, principal)
    if membership.role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="workspace admin role required")
    return membership


def validate_token_scopes(scopes: list[str]) -> list[str]:
    normalized = sorted(set(scopes))
    invalid = sorted(set(normalized) - ALLOWED_TOKEN_SCOPES)
    if invalid:
        raise HTTPException(status_code=422, detail=f"invalid token scopes: {', '.join(invalid)}")
    if not normalized:
        raise HTTPException(status_code=422, detail="token scopes cannot be empty")
    return normalized


def user_read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        is_active=getattr(user, "is_active", True),
        is_platform_admin=getattr(user, "is_platform_admin", False),
        created_at=user.created_at,
    )


def workspace_member_read(session: Session, membership: WorkspaceMembership) -> WorkspaceMemberRead:
    user = session.get(User, membership.user_id)
    if user is None:
        raise HTTPException(status_code=500, detail="workspace membership references missing user")
    return WorkspaceMemberRead(
        id=membership.id,
        workspace_id=membership.workspace_id,
        user=user_read(user),
        role=membership.role,
        created_at=membership.created_at,
    )


def api_token_read(token: ApiToken) -> ApiTokenRead:
    return ApiTokenRead(
        id=token.id,
        workspace_id=token.workspace_id,
        name=token.name,
        scopes=list(token.scopes or []),
        allowed_project_ids=token.allowed_project_ids,
        allowed_resource_ids=token.allowed_resource_ids,
        created_by=token.created_by,
        expires_at=token.expires_at,
        last_used_at=token.last_used_at,
        revoked_at=token.revoked_at,
        created_at=token.created_at,
    )


def current_user_response(session: Session, principal: Principal) -> CurrentUserResponse:
    memberships = list(
        session.scalars(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.user_id == principal.user.id)
            .order_by(WorkspaceMembership.created_at.asc())
        )
    )
    workspace_ids = [membership.workspace_id for membership in memberships]
    workspaces: list[Workspace] = []
    projects_by_workspace: dict[UUID, list[ProjectRead]] = {}
    if workspace_ids:
        workspaces = list(
            session.scalars(
                select(Workspace)
                .where(Workspace.id.in_(workspace_ids), Workspace.deleted_at.is_(None))
                .order_by(Workspace.created_at.asc())
            )
        )
        for workspace in workspaces:
            project_membership_ids = set(
                session.scalars(
                    select(ProjectMembership.project_id).where(
                        ProjectMembership.workspace_id == workspace.id,
                        ProjectMembership.user_id == principal.user.id,
                    )
                )
            )
            projects = list(
                session.scalars(
                    select(Project)
                    .where(Project.workspace_id == workspace.id, Project.deleted_at.is_(None))
                    .order_by(Project.created_at.asc())
                )
            )
            visible_projects = [
                project
                for project in projects
                if project.visibility in {"workspace", "public"} or project.id in project_membership_ids
            ]
            projects_by_workspace[workspace.id] = [
                ProjectRead.model_validate(project, from_attributes=True) for project in visible_projects
            ]
    default_workspace_id = workspaces[0].id if workspaces else None
    default_project_id = None
    if default_workspace_id is not None and projects_by_workspace.get(default_workspace_id):
        default_project_id = projects_by_workspace[default_workspace_id][0].id
    return CurrentUserResponse(
        user=user_read(principal.user),
        workspaces=[WorkspaceRead.model_validate(workspace, from_attributes=True) for workspace in workspaces],
        memberships=[workspace_member_read(session, membership) for membership in memberships],
        projects_by_workspace=projects_by_workspace,
        default_workspace_id=default_workspace_id,
        default_project_id=default_project_id,
    )


def session_scopes_for_role_alias(role: str) -> list[str]:
    return sorted(session_scopes_for_role(role))


def revoke_user_sessions(session: Session, workspace_id: UUID, user_id: UUID) -> None:
    now = datetime.now(UTC)
    for token in session.scalars(
        select(ApiToken).where(
            ApiToken.workspace_id == workspace_id,
            ApiToken.created_by == user_id,
            ApiToken.token_type == "session",
            ApiToken.revoked_at.is_(None),
        )
    ):
        token.revoked_at = now


def admin_count(session: Session, workspace_id: UUID) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(WorkspaceMembership)
            .join(User, WorkspaceMembership.user_id == User.id)
            .where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.role.in_(["owner", "admin"]),
                User.is_active.is_(True),
                User.password_hash.is_not(None),
            )
        )
        or 0
    )


def is_admin_role(role: str | None) -> bool:
    return role in {"owner", "admin"}


def assert_login_capable_admin(user: User, role: str) -> None:
    if is_admin_role(role) and (not user.is_active or not user.password_hash):
        raise HTTPException(status_code=422, detail="admin users must be active and have a password")


def assert_not_last_admin_transition(
    session: Session,
    workspace_id: UUID,
    membership: WorkspaceMembership,
    next_role: str,
    next_active: bool,
    next_password_hash: str | None,
) -> None:
    current_user = session.get(User, membership.user_id)
    current_is_login_admin = (
        current_user is not None
        and is_admin_role(membership.role)
        and current_user.is_active
        and current_user.password_hash is not None
    )
    next_is_login_admin = is_admin_role(next_role) and next_active and next_password_hash is not None
    if current_is_login_admin and not next_is_login_admin and admin_count(session, workspace_id) <= 1:
        raise HTTPException(status_code=422, detail="cannot remove the final active admin")


def create_router(deps: AuthWorkspaceRouterDeps) -> APIRouter:
    router = APIRouter()

    @router.post("/auth/login", response_model=AuthLoginResponse)
    def login(payload: AuthLoginRequest, session: Session = Depends(get_session)) -> AuthLoginResponse:
        email = payload.email.strip().lower()
        user = session.scalar(select(User).where(User.email == email))
        if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password")
        membership = session.scalar(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.user_id == user.id)
            .order_by(WorkspaceMembership.created_at.asc())
        )
        if membership is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user has no workspace access")
        plaintext = new_plaintext_token()
        token = ApiToken(
            workspace_id=membership.workspace_id,
            name=f"Web session for {user.email}",
            token_type="session",
            token_hash=hash_token(plaintext),
            scopes=session_scopes_for_role_alias(membership.role),
            allowed_project_ids=None,
            allowed_resource_ids=None,
            created_by=user.id,
            expires_at=datetime.now(UTC) + timedelta(hours=12),
        )
        session.add(token)
        session.flush()
        response = current_user_response(session, Principal(user=user, api_token=token))
        session.commit()
        return AuthLoginResponse(session_token=plaintext, **response.model_dump())

    @router.get("/auth/me", response_model=CurrentUserResponse)
    def me(
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> CurrentUserResponse:
        if principal.is_token:
            raise HTTPException(status_code=403, detail="account session required")
        return current_user_response(session, principal)

    @router.post("/auth/logout", response_model=AuthLogoutResponse)
    def logout(
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> AuthLogoutResponse:
        if principal.api_token is not None and principal.api_token.revoked_at is None:
            principal.api_token.revoked_at = datetime.now(UTC)
            session.commit()
        return AuthLogoutResponse(status="ok")

    @router.post("/workspaces", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
    def create_workspace(
        payload: WorkspaceCreate,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> Workspace:
        if principal.is_token:
            raise HTTPException(status_code=403, detail="workspace creation requires user authentication")
        user = principal.user
        workspace = Workspace(name=payload.name, slug=payload.slug)
        session.add(workspace)
        session.flush()
        session.add(WorkspaceMembership(workspace_id=workspace.id, user_id=user.id, role="owner"))
        session.add(
            AuditEvent(
                workspace_id=workspace.id,
                actor_user_id=user.id,
                actor_token_id=principal.token_id,
                action="workspace.create",
                target_type="workspace",
                target_id=workspace.id,
            )
        )
        session.commit()
        return workspace

    @router.get("/workspaces", response_model=list[WorkspaceRead])
    def list_workspaces(
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> list[Workspace]:
        require_scope(principal, "project:read")
        if principal.is_token:
            token = principal.api_token
            if token is None:
                return []
            workspace = session.get(Workspace, token.workspace_id)
            if workspace is None or workspace.deleted_at is not None:
                return []
            return [workspace]
        memberships = session.scalars(
            select(WorkspaceMembership).where(WorkspaceMembership.user_id == principal.user.id)
        ).all()
        workspace_ids = [membership.workspace_id for membership in memberships]
        if not workspace_ids:
            return []
        return list(
            session.scalars(
                select(Workspace)
                .where(Workspace.id.in_(workspace_ids), Workspace.deleted_at.is_(None))
                .order_by(Workspace.created_at.asc())
            )
        )

    @router.get("/workspaces/{workspace_id}", response_model=WorkspaceRead)
    def get_workspace(
        workspace_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> Workspace:
        require_scope(principal, "project:read")
        require_workspace_member(session, workspace_id, principal)
        workspace = session.get(Workspace, workspace_id)
        if workspace is None or workspace.deleted_at is not None:
            raise HTTPException(status_code=404, detail="workspace not found")
        return workspace

    @router.post("/workspaces/{workspace_id}/api-tokens", response_model=ApiTokenCreateResponse, status_code=201)
    def create_api_token(
        workspace_id: UUID,
        payload: ApiTokenCreate,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> ApiTokenCreateResponse:
        if principal.is_token:
            raise HTTPException(status_code=403, detail="token creation requires user authentication")
        require_scope(principal, "token:admin")
        require_workspace_admin(session, workspace_id, principal)
        scopes = validate_token_scopes(payload.scopes)
        for project_id in payload.allowed_project_ids or []:
            deps.require_project_access(session, workspace_id, project_id, principal)
        for resource_id in payload.allowed_resource_ids or []:
            resource = session.get(Resource, resource_id)
            if resource is None or resource.workspace_id != workspace_id or resource.deleted_at is not None:
                raise HTTPException(status_code=404, detail="resource not found")
            deps.require_project_access(session, workspace_id, resource.project_id, principal)
        if payload.name.startswith("Web session for "):
            raise HTTPException(status_code=422, detail="token name uses a reserved session prefix")
        plaintext = new_plaintext_token()
        token = ApiToken(
            workspace_id=workspace_id,
            name=payload.name,
            token_hash=hash_token(plaintext),
            scopes=scopes,
            allowed_project_ids=payload.allowed_project_ids,
            allowed_resource_ids=payload.allowed_resource_ids,
            created_by=principal.user.id,
            expires_at=payload.expires_at,
        )
        session.add(token)
        session.flush()
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="api_token.create",
                target_type="api_token",
                target_id=token.id,
                meta={"scopes": scopes, "name": payload.name},
            )
        )
        session.commit()
        return ApiTokenCreateResponse(token=plaintext, api_token=api_token_read(token))

    @router.get("/workspaces/{workspace_id}/api-tokens", response_model=list[ApiTokenRead])
    def list_api_tokens(
        workspace_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> list[ApiTokenRead]:
        require_scope(principal, "token:admin")
        require_workspace_admin(session, workspace_id, principal)
        tokens = list(
            session.scalars(
                select(ApiToken)
                .where(ApiToken.workspace_id == workspace_id, ApiToken.token_type == "api")
                .order_by(ApiToken.created_at.asc())
            )
        )
        return [api_token_read(token) for token in tokens]

    @router.delete("/workspaces/{workspace_id}/api-tokens/{token_id}", response_model=ApiTokenRead)
    def revoke_api_token(
        workspace_id: UUID,
        token_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> ApiTokenRead:
        require_scope(principal, "token:admin")
        require_workspace_admin(session, workspace_id, principal)
        token = session.scalar(
            select(ApiToken).where(
                ApiToken.workspace_id == workspace_id,
                ApiToken.id == token_id,
                ApiToken.token_type == "api",
            )
        )
        if token is None:
            raise HTTPException(status_code=404, detail="token not found")
        if token.revoked_at is None:
            token.revoked_at = datetime.now(UTC)
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="api_token.revoke",
                target_type="api_token",
                target_id=token.id,
                meta={"name": token.name},
            )
        )
        session.commit()
        return api_token_read(token)

    @router.get("/workspaces/{workspace_id}/projects", response_model=list[ProjectRead])
    def list_projects(
        workspace_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> list[Project]:
        require_scope(principal, "project:read")
        require_workspace_member(session, workspace_id, principal)
        predicates = [Project.workspace_id == workspace_id, Project.deleted_at.is_(None)]
        projects = list(session.scalars(select(Project).where(*predicates).order_by(Project.created_at.asc())))
        visible: list[Project] = []
        for project in projects:
            if not token_allows_project(principal, project.id):
                continue
            try:
                visible.append(deps.require_project_access(session, workspace_id, project.id, principal))
            except HTTPException as exc:
                if exc.status_code == status.HTTP_404_NOT_FOUND:
                    continue
                raise
        return visible

    @router.get("/workspaces/{workspace_id}/members", response_model=list[WorkspaceMemberRead])
    def list_workspace_members(
        workspace_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> list[WorkspaceMemberRead]:
        require_scope(principal, "project:read")
        if principal.is_token:
            require_scope(principal, "token:admin")
        require_workspace_admin(session, workspace_id, principal)
        memberships = list(
            session.scalars(
                select(WorkspaceMembership)
                .where(WorkspaceMembership.workspace_id == workspace_id)
                .order_by(WorkspaceMembership.created_at.asc())
            )
        )
        return [workspace_member_read(session, membership) for membership in memberships]

    @router.post("/workspaces/{workspace_id}/members", response_model=WorkspaceMemberRead, status_code=201)
    def create_workspace_member(
        workspace_id: UUID,
        payload: WorkspaceMemberCreate,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> WorkspaceMemberRead:
        if principal.is_token:
            raise HTTPException(status_code=403, detail="user management requires user authentication")
        require_workspace_admin(session, workspace_id, principal)
        email = payload.email.strip().lower()
        user = session.scalar(select(User).where(User.email == email))
        user_created = False
        if user is None:
            user = User(
                email=email,
                display_name=payload.display_name or email.split("@")[0],
                password_hash=hash_password(payload.password) if payload.password else None,
                is_active=True,
            )
            session.add(user)
            session.flush()
            user_created = True
        if payload.display_name is not None:
            user.display_name = payload.display_name
        if not user_created and payload.password:
            if not principal.user.is_platform_admin:
                raise HTTPException(status_code=403, detail="existing-user password reset requires platform admin")
            user.password_hash = hash_password(payload.password)
        if user_created:
            user.is_active = True
        if is_admin_role(payload.role) and not user.password_hash:
            raise HTTPException(status_code=422, detail="admin users require a password")
        membership = session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.user_id == user.id,
            )
        )
        if membership is None:
            membership = WorkspaceMembership(workspace_id=workspace_id, user_id=user.id, role=payload.role)
            session.add(membership)
        else:
            assert_not_last_admin_transition(
                session, workspace_id, membership, payload.role, user.is_active, user.password_hash
            )
            if membership.role != payload.role:
                revoke_user_sessions(session, workspace_id, user.id)
            membership.role = payload.role
        projects = list(
            session.scalars(select(Project).where(Project.workspace_id == workspace_id, Project.deleted_at.is_(None)))
        )
        for project in projects:
            project_membership = session.scalar(
                select(ProjectMembership).where(
                    ProjectMembership.project_id == project.id,
                    ProjectMembership.user_id == user.id,
                )
            )
            if project_membership is None:
                session.add(
                    ProjectMembership(
                        workspace_id=workspace_id,
                        project_id=project.id,
                        user_id=user.id,
                        role=payload.role,
                    )
                )
            else:
                project_membership.role = payload.role
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="workspace_member.upsert",
                target_type="user",
                target_id=user.id,
                meta={"email": user.email, "role": payload.role},
            )
        )
        session.commit()
        return workspace_member_read(session, membership)

    @router.patch("/workspaces/{workspace_id}/members/{membership_id}", response_model=WorkspaceMemberRead)
    def update_workspace_member(
        workspace_id: UUID,
        membership_id: UUID,
        payload: WorkspaceMemberUpdate,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> WorkspaceMemberRead:
        if principal.is_token:
            raise HTTPException(status_code=403, detail="user management requires user authentication")
        require_workspace_admin(session, workspace_id, principal)
        membership = session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace_id,
                WorkspaceMembership.id == membership_id,
            )
        )
        if membership is None:
            raise HTTPException(status_code=404, detail="member not found")
        user = session.get(User, membership.user_id)
        if user is None:
            raise HTTPException(status_code=500, detail="workspace membership references missing user")
        next_role = payload.role if payload.role is not None else membership.role
        next_active = payload.is_active if payload.is_active is not None else user.is_active
        next_password_hash: str | None
        if payload.password:
            if not principal.user.is_platform_admin:
                raise HTTPException(status_code=403, detail="password reset requires platform admin")
            next_password_hash = hash_password(payload.password)
        else:
            next_password_hash = user.password_hash
        assert_not_last_admin_transition(session, workspace_id, membership, next_role, next_active, next_password_hash)
        if is_admin_role(next_role) and (not next_active or not next_password_hash):
            raise HTTPException(status_code=422, detail="admin users must be active and have a password")
        sessions_should_revoke = bool(payload.password or payload.is_active is not None or payload.role is not None)
        if sessions_should_revoke:
            revoke_user_sessions(session, workspace_id, user.id)
        if payload.display_name is not None:
            user.display_name = payload.display_name
        if payload.password:
            if not principal.user.is_platform_admin:
                raise HTTPException(status_code=403, detail="password reset requires platform admin")
            user.password_hash = hash_password(payload.password)
        if payload.is_active is not None:
            if not principal.user.is_platform_admin:
                raise HTTPException(status_code=403, detail="user activation changes require platform admin")
            user.is_active = payload.is_active
        if payload.role is not None:
            membership.role = payload.role
            projects = list(
                session.scalars(
                    select(Project).where(Project.workspace_id == workspace_id, Project.deleted_at.is_(None))
                )
            )
            for project in projects:
                project_membership = session.scalar(
                    select(ProjectMembership).where(
                        ProjectMembership.project_id == project.id,
                        ProjectMembership.user_id == user.id,
                    )
                )
                if project_membership is None:
                    session.add(
                        ProjectMembership(
                            workspace_id=workspace_id,
                            project_id=project.id,
                            user_id=user.id,
                            role=payload.role,
                        )
                    )
                else:
                    project_membership.role = payload.role
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=principal.user.id,
                actor_token_id=principal.token_id,
                action="workspace_member.update",
                target_type="user",
                target_id=user.id,
                meta={"role": membership.role, "is_active": user.is_active},
            )
        )
        session.commit()
        return workspace_member_read(session, membership)

    @router.post("/workspaces/{workspace_id}/projects", response_model=ProjectRead, status_code=201)
    def create_project(
        workspace_id: UUID,
        payload: ProjectCreate,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> Project:
        if principal.is_token:
            raise HTTPException(status_code=403, detail="project creation requires user authentication")
        user = principal.user
        require_scope(principal, "token:admin")
        require_workspace_admin(session, workspace_id, principal)
        project = Project(
            workspace_id=workspace_id,
            name=payload.name,
            description=payload.description,
            created_by=user.id,
        )
        session.add(project)
        session.flush()
        deps.ensure_agent_profile(session, workspace_id, project, user.id)
        session.add(
            ProjectMembership(
                workspace_id=workspace_id,
                project_id=project.id,
                user_id=user.id,
                role="owner",
            )
        )
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_user_id=user.id,
                actor_token_id=principal.token_id,
                action="project.create",
                target_type="project",
                target_id=project.id,
            )
        )
        session.commit()
        return project

    @router.get("/workspaces/{workspace_id}/projects/{project_id}", response_model=ProjectRead)
    def get_project(
        workspace_id: UUID,
        project_id: UUID,
        principal: Principal = Depends(require_principal),
        session: Session = Depends(get_session),
    ) -> Project:
        require_scope(principal, "project:read")
        return deps.require_project_access(session, workspace_id, project_id, principal)

    return router
