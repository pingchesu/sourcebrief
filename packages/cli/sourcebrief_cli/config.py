from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from sourcebrief_cli.client import SourceBriefCliError

SESSION_TOKEN_CONFIG_KEY = "session_token"
SESSION_EMAIL_CONFIG_KEY = "session_email"


def config_path() -> Path:
    override = os.getenv("SOURCEBRIEF_CONFIG_PATH")
    if override:
        return Path(override).expanduser()
    config_home = os.getenv("XDG_CONFIG_HOME")
    if config_home:
        return Path(config_home).expanduser() / "sourcebrief" / "config.json"
    return Path.home() / ".config" / "sourcebrief" / "config.json"


def load_cli_config() -> dict[str, Any]:
    path = config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SourceBriefCliError(f"invalid CLI config at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SourceBriefCliError(f"invalid CLI config at {path}: expected object")
    return data


def save_cli_config(config: dict[str, Any]) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(config, indent=2, sort_keys=True) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent, text=True)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        temp_path.chmod(0o600)
        os.replace(temp_path, path)
        path.chmod(0o600)
    finally:
        temp_path.unlink(missing_ok=True)
    return path


def selected_value(config: dict[str, Any], key: str) -> str | None:
    value = config.get(key)
    return value if isinstance(value, str) and value else None
