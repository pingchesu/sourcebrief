from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from contextsmith_shared.config import get_settings
from contextsmith_shared.db import get_session
from contextsmith_shared.models import ApiToken, User, WorkspaceMembership

DEV_ALL_SCOPES = {"*"}
TOKEN_PREFIX = "cs_"


@dataclass(frozen=True)
class Principal:
    user: User
    api_token: ApiToken | None = None

    @property
    def token_id(self) -> UUID | None:
        return self.api_token.id if self.api_token is not None else None

    @property
    def is_token(self) -> bool:
        return self.api_token is not None

    @property
    def scopes(self) -> set[str]:
        if self.api_token is None:
            return DEV_ALL_SCOPES
        return set(self.api_token.scopes or [])


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_plaintext_token() -> str:
    return f"{TOKEN_PREFIX}{secrets.token_urlsafe(32)}"


def get_or_create_user(session: Session, email: str, display_name: str | None = None) -> User:
    user = session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, display_name=display_name or email.split("@")[0])
        session.add(user)
        session.flush()
    return user


def _token_from_authorization(value: str | None) -> str | None:
    if not value:
        return None
    scheme, _, token = value.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid authorization header")
    return token


def _resolve_api_token(session: Session, plaintext: str) -> ApiToken:
    digest = hash_token(plaintext)
    token = session.scalar(select(ApiToken).where(ApiToken.token_hash == digest))
    if token is None or not hmac.compare_digest(token.token_hash, digest):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")
    now = datetime.now(UTC)
    if token.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token revoked")
    expires_at = token.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at is not None and expires_at <= now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token expired")
    token.last_used_at = now
    session.commit()
    return token


def require_principal(
    authorization: str | None = Header(default=None, alias="Authorization"),
    x_user_email: str | None = Header(default=None, alias="X-User-Email"),
    session: Session = Depends(get_session),
) -> Principal:
    bearer = _token_from_authorization(authorization)
    if bearer is not None:
        token = _resolve_api_token(session, bearer)
        if token.created_by is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token has no owner")
        user = session.get(User, token.created_by)
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="token owner missing")
        return Principal(user=user, api_token=token)
    if not get_settings().dev_auth:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")
    if not x_user_email:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="X-User-Email required when dev auth is enabled")
    return Principal(user=get_or_create_user(session, x_user_email))


def require_scope(principal: Principal, scope: str) -> None:
    scopes = principal.scopes
    if "*" in scopes or scope in scopes:
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"missing scope: {scope}")


def require_any_scope(principal: Principal, scopes: set[str]) -> None:
    actual = principal.scopes
    if "*" in actual or actual.intersection(scopes):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=f"missing one of scopes: {', '.join(sorted(scopes))}")


def require_workspace_member(session: Session, workspace_id: UUID, principal: Principal | User) -> WorkspaceMembership:
    user = principal.user if isinstance(principal, Principal) else principal
    token = principal.api_token if isinstance(principal, Principal) else None
    if token is not None and token.workspace_id != workspace_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workspace not found")
    membership = session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user.id,
        )
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workspace not found")
    return membership


def token_allows_project(principal: Principal, project_id: UUID) -> bool:
    token = principal.api_token
    if token is None:
        return True
    allowed = token.allowed_project_ids
    return allowed is None or project_id in allowed


def token_allows_resource(principal: Principal, resource_id: UUID) -> bool:
    token = principal.api_token
    if token is None:
        return True
    allowed = token.allowed_resource_ids
    return allowed is None or resource_id in allowed
