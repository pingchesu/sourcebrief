from __future__ import annotations

import re
from collections.abc import Callable

from fastapi import HTTPException

from sourcebrief_api.schemas import GitResourceEnvRead
from sourcebrief_shared.models import Resource

MetadataSanitizer = Callable[[str | None], str]
UriSanitizer = Callable[[str], str]

_ENV_VAR_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")


def git_env_read(
    resource: Resource,
    *,
    sanitize_metadata_text: MetadataSanitizer,
    sanitize_public_uri: UriSanitizer,
) -> GitResourceEnvRead:
    source_config = resource.source_config or {}
    return GitResourceEnvRead(
        resource_id=resource.id,
        name=sanitize_metadata_text(resource.name),
        uri=sanitize_public_uri(resource.uri),
        branch=source_config.get("branch") or source_config.get("ref"),
        auth_token_env=source_config.get("auth_token_env"),
        clone_timeout=source_config.get("clone_timeout"),
        max_file_bytes=source_config.get("max_file_bytes"),
        max_repo_files=source_config.get("max_repo_files"),
        max_repo_bytes=source_config.get("max_repo_bytes"),
        update_frequency=resource.update_frequency,
        next_refresh_at=resource.next_refresh_at,
    )


def validate_auth_token_env(value: object) -> str | None:
    if value is None:
        return None
    env_name = str(value).strip()
    if not env_name:
        return None
    if not _ENV_VAR_NAME_RE.match(env_name):
        raise HTTPException(status_code=422, detail="auth_token_env must be an environment variable name, not a raw token value")
    return env_name
