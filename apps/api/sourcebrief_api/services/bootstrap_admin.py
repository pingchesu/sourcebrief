from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from sourcebrief_shared.models import (
    Project,
    ProjectMembership,
    User,
    Workspace,
    WorkspaceMembership,
)

RuntimeCallable = Callable[..., Any]


@dataclass(frozen=True)
class BootstrapAdminDeps:
    get_settings: RuntimeCallable
    get_sessionmaker: RuntimeCallable
    normalize_email: Callable[[str], str]
    hash_password: Callable[[str], str]
    ensure_agent_profile: RuntimeCallable


def default_bootstrap_admin_deps(
    *,
    normalize_email: Callable[[str], str],
    ensure_agent_profile: RuntimeCallable,
) -> BootstrapAdminDeps:
    from sourcebrief_api.auth import hash_password
    from sourcebrief_shared.config import get_settings
    from sourcebrief_shared.db import get_sessionmaker

    return BootstrapAdminDeps(
        get_settings=get_settings,
        get_sessionmaker=get_sessionmaker,
        normalize_email=normalize_email,
        hash_password=hash_password,
        ensure_agent_profile=ensure_agent_profile,
    )


def bootstrap_default_admin(deps: BootstrapAdminDeps) -> None:
    settings = deps.get_settings()
    if not settings.admin_email or not settings.admin_password:
        return
    if settings.admin_password in {"change-me-before-compose-up", "sourcebrief-admin"}:
        raise RuntimeError("SOURCEBRIEF_ADMIN_PASSWORD must be changed from the sample/default value before startup")
    SessionLocal = deps.get_sessionmaker()
    with SessionLocal() as session:
        email = deps.normalize_email(settings.admin_email)
        admin = session.scalar(select(User).where(User.email == email))
        if admin is None:
            admin = User(
                email=email,
                display_name=settings.admin_display_name,
                password_hash=deps.hash_password(settings.admin_password),
                is_active=True,
                is_platform_admin=True,
            )
            session.add(admin)
            session.flush()
        if not admin.display_name or admin.display_name == "ContextSmith Admin":
            admin.display_name = settings.admin_display_name
        admin.password_hash = deps.hash_password(settings.admin_password)
        admin.is_active = True
        admin.is_platform_admin = True

        workspace = session.scalar(select(Workspace).where(Workspace.slug == settings.bootstrap_workspace_slug))
        if workspace is None and settings.bootstrap_workspace_slug == "sourcebrief":
            legacy_workspace = session.scalar(select(Workspace).where(Workspace.slug == "contextsmith"))
            if legacy_workspace is not None and legacy_workspace.name == "ContextSmith":
                legacy_workspace.name = settings.bootstrap_workspace_name
                legacy_workspace.slug = settings.bootstrap_workspace_slug
                workspace = legacy_workspace
        if workspace is None:
            workspace = Workspace(name=settings.bootstrap_workspace_name, slug=settings.bootstrap_workspace_slug)
            session.add(workspace)
            session.flush()
        elif workspace.name == "ContextSmith" and settings.bootstrap_workspace_name == "SourceBrief":
            workspace.name = settings.bootstrap_workspace_name
        membership = session.scalar(
            select(WorkspaceMembership).where(
                WorkspaceMembership.workspace_id == workspace.id,
                WorkspaceMembership.user_id == admin.id,
            )
        )
        if membership is None:
            session.add(WorkspaceMembership(workspace_id=workspace.id, user_id=admin.id, role="owner"))
        elif membership.role not in {"owner", "admin"}:
            membership.role = "owner"

        project = session.scalar(
            select(Project).where(
                Project.workspace_id == workspace.id,
                Project.name == settings.bootstrap_project_name,
                Project.deleted_at.is_(None),
            )
        )
        if project is None:
            project = Project(
                workspace_id=workspace.id,
                name=settings.bootstrap_project_name,
                description="Bootstrap project for the initial SourceBrief console.",
                created_by=admin.id,
            )
            session.add(project)
            session.flush()
        elif project.description == "Bootstrap project for the initial ContextSmith console.":
            project.description = "Bootstrap project for the initial SourceBrief console."
        project_membership = session.scalar(
            select(ProjectMembership).where(
                ProjectMembership.project_id == project.id,
                ProjectMembership.user_id == admin.id,
            )
        )
        if project_membership is None:
            session.add(
                ProjectMembership(
                    workspace_id=workspace.id,
                    project_id=project.id,
                    user_id=admin.id,
                    role="owner",
                )
            )
        elif project_membership.role not in {"owner", "admin"}:
            project_membership.role = "owner"
        deps.ensure_agent_profile(session, workspace.id, project, admin.id)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
