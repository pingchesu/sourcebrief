from dataclasses import dataclass
from uuid import UUID

from fastapi import Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from contextsmith_shared.models import User, WorkspaceMembership


@dataclass(frozen=True)
class Principal:
    user: User


def get_or_create_user(session: Session, email: str, display_name: str | None = None) -> User:
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, display_name=display_name or email.split("@")[0])
        session.add(user)
        session.flush()
    return user


def require_principal(
    x_user_email: str = Header(default="dev@example.com", alias="X-User-Email"),
) -> str:
    return x_user_email


def require_workspace_member(session: Session, workspace_id: UUID, user: User) -> WorkspaceMembership:
    membership = session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workspace not found")
    return membership
