from __future__ import annotations

import argparse
import getpass
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from sourcebrief_cli.client import SourceBriefClient, SourceBriefCliError
from sourcebrief_cli.config import (
    SESSION_EMAIL_CONFIG_KEY,
    SESSION_TOKEN_CONFIG_KEY,
    selected_value,
)

AuthenticatedCommandPredicate = Callable[[argparse.Namespace], bool]


def dotenv_path() -> Path:
    override = os.getenv("SOURCEBRIEF_DOTENV_PATH")
    return Path(override).expanduser() if override else Path(".env")


def dotenv_value(name: str) -> str | None:
    path = dotenv_path()
    if not path.exists():
        return None
    value = dotenv_values(path).get(name)
    return value if isinstance(value, str) and value else None


def first_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    for name in names:
        value = dotenv_value(name)
        if value:
            return value
    return None


def env_login_email(args: argparse.Namespace) -> str | None:
    explicit_email = getattr(args, "email", None) if getattr(args, "_email_explicit", False) else None
    return explicit_email or first_env(
        "SOURCEBRIEF_ADMIN_EMAIL",
        "SOURCEBRIEF_EMAIL",
        "CONTEXTSMITH_ADMIN_EMAIL",
        "CONTEXTSMITH_EMAIL",
    ) or getattr(args, "email", None)


def env_login_password() -> str | None:
    return first_env(
        "SOURCEBRIEF_ADMIN_PASSWORD",
        "SOURCEBRIEF_PASSWORD",
        "CONTEXTSMITH_ADMIN_PASSWORD",
        "CONTEXTSMITH_PASSWORD",
    )


def resolve_auth(args: argparse.Namespace, config: dict[str, Any]) -> None:
    args._auth_mode = "email_header"
    args._session_email = None
    args._session_login_password = None
    if args.token:
        args._auth_mode = "bearer_token"
        return
    saved_session = selected_value(config, SESSION_TOKEN_CONFIG_KEY)
    if saved_session:
        args.token = saved_session
        args._auth_mode = "saved_session"
        args._session_email = selected_value(config, SESSION_EMAIL_CONFIG_KEY)
        return
    password = env_login_password()
    if password:
        args._auth_mode = "session_login_env"
        args._session_email = env_login_email(args)
        args._session_login_password = password


def login_with_password(client: SourceBriefClient, email: str, password: str) -> str:
    login = client.request("POST", "/auth/login", body={"email": email, "password": password})
    session_token = login.get("session_token") if isinstance(login, dict) else None
    if not isinstance(session_token, str) or not session_token:
        raise SourceBriefCliError("/auth/login response did not include session_token")
    return session_token


def login_password_from_args(args: argparse.Namespace) -> str:
    env_name = getattr(args, "password_env", None)
    if env_name:
        value = os.getenv(env_name) or dotenv_value(env_name)
        if not value:
            raise SourceBriefCliError(f"password environment variable or .env key {env_name} is not set")
        return value
    env_password = env_login_password()
    if env_password:
        return env_password
    return getpass.getpass("SourceBrief password: ")


def maybe_session_login(
    client: SourceBriefClient,
    args: argparse.Namespace,
    *,
    command_uses_authenticated_api: AuthenticatedCommandPredicate,
) -> None:
    if getattr(args, "_auth_mode", None) != "session_login_env":
        return
    if not command_uses_authenticated_api(args):
        return
    email = getattr(args, "_session_email", None) or args.email
    password = getattr(args, "_session_login_password", None)
    if not password:
        return
    client.token = login_with_password(client, email, password)
    args.token = client.token
