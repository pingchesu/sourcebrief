from __future__ import annotations

import os

from fastapi import HTTPException

from sourcebrief_api.constants import (
    FOLDER_BUNDLE_RESOURCE_TYPES,
    UPLOAD_RESOURCE_TYPES,
    URL_RESOURCE_TYPES,
)
from sourcebrief_api.git_env import validate_auth_token_env
from sourcebrief_worker.ingestion import (
    DEFAULT_MAX_CHUNKS,
    DEFAULT_MAX_DOCUMENT_BYTES,
    DEFAULT_MAX_SYMBOLS,
    DEFAULT_MAX_URL_BYTES,
    HARD_MAX_CHUNKS,
    HARD_MAX_DOCUMENT_BYTES,
    HARD_MAX_SYMBOLS,
    HARD_MAX_URL_BYTES,
    parse_positive_int,
    sanitize_remote_url,
    validate_base64_size,
    validate_git_url,
    validate_http_url,
)


def validate_source_config(resource_type: str, uri: str, source_config: dict) -> dict:
    rtype = (resource_type or "").lower()
    config = dict(source_config or {})
    if rtype in URL_RESOURCE_TYPES:
        url = config.get("url") or uri
        try:
            config["url"] = validate_http_url(url)
            config["max_url_bytes"] = parse_positive_int(
                config.get("max_url_bytes"),
                default=DEFAULT_MAX_URL_BYTES,
                hard_limit=HARD_MAX_URL_BYTES,
                name="max_url_bytes",
            )
            if "fetch_timeout" in config:
                config["fetch_timeout"] = parse_positive_int(
                    config.get("fetch_timeout"), default=20, hard_limit=60, name="fetch_timeout"
                )
            if "max_redirects" in config:
                config["max_redirects"] = parse_positive_int(
                    config.get("max_redirects"), default=3, hard_limit=10, name="max_redirects"
                )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if rtype == "git":
        try:
            _is_local, target = validate_git_url(
                config.get("url") or uri,
                allow_local=os.getenv("SOURCEBRIEF_ALLOW_LOCAL_GIT", os.getenv("CONTEXTSMITH_ALLOW_LOCAL_GIT", "false")).lower() == "true",
            )
            config["url"] = target if _is_local else sanitize_remote_url(target)
            auth_token_env = validate_auth_token_env(config.get("auth_token_env"))
            if auth_token_env is None:
                config.pop("auth_token_env", None)
            else:
                config["auth_token_env"] = auth_token_env
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if rtype in UPLOAD_RESOURCE_TYPES:
        if any(key in config for key in ("path", "file_path", "local_path")):
            raise HTTPException(status_code=422, detail="upload connector does not accept local file paths")
        if not any(isinstance(value := config.get(key), str) and value.strip() for key in ("content", "text", "base64")):
            raise HTTPException(status_code=422, detail="upload connector requires content, text, or base64")
        try:
            max_document_bytes = parse_positive_int(
                config.get("max_document_bytes"),
                default=DEFAULT_MAX_DOCUMENT_BYTES,
                hard_limit=HARD_MAX_DOCUMENT_BYTES,
                name="max_document_bytes",
            )
            config["max_document_bytes"] = max_document_bytes
            if isinstance(config.get("base64"), str):
                validate_base64_size(config["base64"], max_bytes=max_document_bytes)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if rtype in FOLDER_BUNDLE_RESOURCE_TYPES:
        raise HTTPException(status_code=422, detail="folder bundles must be created through the zip upload endpoint")
    try:
        if "max_chunks" in config:
            config["max_chunks"] = parse_positive_int(
                config.get("max_chunks"), default=DEFAULT_MAX_CHUNKS, hard_limit=HARD_MAX_CHUNKS, name="max_chunks"
            )
        if "max_symbols" in config:
            config["max_symbols"] = parse_positive_int(
                config.get("max_symbols"), default=DEFAULT_MAX_SYMBOLS, hard_limit=HARD_MAX_SYMBOLS, name="max_symbols"
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return config
