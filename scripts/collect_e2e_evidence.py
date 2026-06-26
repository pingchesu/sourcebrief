from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

SECRET_KEY_RE = re.compile(r"(TOKEN|SECRET|PASSWORD|CREDENTIAL|PRIVATE_KEY|API_KEY|SESSION)", re.IGNORECASE)
SECRET_VALUE_RE = re.compile(r"(cs_[A-Za-z0-9_-]{8,}|Bearer\s+[A-Za-z0-9._-]+)")
DEFAULT_SECRET = "***REDACTED***"


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        values[key] = value
    return values


def redact_value(key: str, value: str | None) -> str | None:
    if value is None:
        return None
    if SECRET_KEY_RE.search(key):
        return DEFAULT_SECRET
    return SECRET_VALUE_RE.sub(DEFAULT_SECRET, value)


def redacted_env_summary(env_file: Path, environ: Mapping[str, str]) -> dict[str, str | None]:
    file_values = parse_env_file(env_file)
    keys = [
        "COMPOSE_PROJECT_NAME",
        "SOURCEBRIEF_API_PORT",
        "SOURCEBRIEF_WEB_PORT",
        "SOURCEBRIEF_POSTGRES_PORT",
        "SOURCEBRIEF_REDIS_PORT",
        "NEXT_PUBLIC_API_BASE_URL",
        "SOURCEBRIEF_DEV_AUTH",
        "SOURCEBRIEF_ADMIN_EMAIL",
        "SOURCEBRIEF_ADMIN_PASSWORD",
        "SOURCEBRIEF_TOKEN",
        "SOURCEBRIEF_QA_TOKEN",
    ]
    summary: dict[str, str | None] = {}
    for key in keys:
        value = environ.get(key, file_values.get(key))
        summary[key] = redact_value(key, value)
    return summary


def configured_urls(env_file: Path, environ: Mapping[str, str]) -> dict[str, str]:
    file_values = parse_env_file(env_file)

    def pick(name: str, default: str) -> str:
        return environ.get(name) or file_values.get(name) or default

    api_port = pick("SOURCEBRIEF_API_PORT", pick("CONTEXTSMITH_API_PORT", "18000"))
    web_port = pick("SOURCEBRIEF_WEB_PORT", pick("CONTEXTSMITH_WEB_PORT", "13000"))
    api_url = environ.get("SOURCEBRIEF_API_URL") or environ.get("API_URL") or f"http://localhost:{api_port}"
    web_url = environ.get("SOURCEBRIEF_WEB_URL") or environ.get("WEB_URL") or f"http://localhost:{web_port}"
    return {"api_url": api_url.rstrip("/"), "web_url": web_url.rstrip("/"), "api_port": api_port, "web_port": web_port}


def run_command(command: list[str], *, cwd: Path, timeout: int = 120) -> dict[str, Any]:
    started = datetime.now(UTC).isoformat()
    try:
        result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False)
        exit_code = result.returncode
        stdout = redact_value("stdout", result.stdout) or ""
        stderr = redact_value("stderr", result.stderr) or ""
    except FileNotFoundError as exc:
        exit_code = 127
        stdout = ""
        stderr = str(exc)
    except subprocess.TimeoutExpired as exc:
        exit_code = 124
        stdout = redact_value("stdout", exc.stdout if isinstance(exc.stdout, str) else "") or ""
        stderr = f"timeout after {timeout}s"
    return {"command": command, "started_at": started, "exit_code": exit_code, "stdout": stdout, "stderr": stderr}


def http_check(url: str, timeout: int = 15) -> dict[str, Any]:
    started = datetime.now(UTC).isoformat()
    try:
        with urlopen(url, timeout=timeout) as response:  # noqa: S310 - local/user-configured evidence URL
            body = response.read(4000).decode("utf-8", errors="replace")
            return {"url": url, "started_at": started, "status_code": response.status, "body": redact_value("body", body)}
    except URLError as exc:
        return {"url": url, "started_at": started, "status_code": None, "error": str(exc.reason)}


def git_state(cwd: Path) -> dict[str, Any]:
    rev = run_command(["git", "rev-parse", "HEAD"], cwd=cwd)
    status = run_command(["git", "status", "--short", "--branch"], cwd=cwd)
    branch = run_command(["git", "branch", "--show-current"], cwd=cwd)
    return {
        "head": rev["stdout"].strip() if rev["exit_code"] == 0 else None,
        "branch": branch["stdout"].strip() if branch["exit_code"] == 0 else None,
        "status": status,
    }


def write_bundle(output_dir: Path, manifest: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    lines = [
        f"# SourceBrief E2E evidence bundle {manifest['run_id']}",
        "",
        f"- Captured at: `{manifest['captured_at']}`",
        f"- Git head: `{manifest['git']['head']}`",
        f"- Branch: `{manifest['git']['branch']}`",
        f"- Compose project: `{manifest['compose']['project_name']}`",
        f"- API URL: `{manifest['urls']['api_url']}`",
        f"- Web URL: `{manifest['urls']['web_url']}`",
        "",
        "## Commands",
    ]
    for item in manifest["commands"]:
        lines.append(f"- `{ ' '.join(item['command']) }` -> exit {item['exit_code']}")
    lines.extend(["", "## Health checks"])
    for item in manifest["health_checks"]:
        lines.append(f"- `{item['url']}` -> {item.get('status_code') or item.get('error')}")
    (output_dir / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect a redacted SourceBrief E2E evidence bundle.")
    parser.add_argument("--output-dir", help="bundle directory; defaults to artifacts/e2e/<timestamp>")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--compose-project-name", help="recorded compose project name; defaults to env or sourcebrief_e2e_<timestamp>")
    parser.add_argument("--skip-docker", action="store_true", help="do not run docker compose ps")
    parser.add_argument("--skip-health", action="store_true", help="do not call API/web health endpoints")
    parser.add_argument("--command", action="append", default=[], help="extra shell command to run and capture, repeatable")
    parser.add_argument("--include-file", action="append", default=[], help="label=path file to copy/redact into included_files metadata")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cwd = Path.cwd()
    captured_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    run_id = captured_at.replace(":", "").replace("-", "").replace("Z", "")
    output_dir = Path(args.output_dir) if args.output_dir else Path("artifacts") / "e2e" / run_id
    env_file = Path(args.env_file)
    urls = configured_urls(env_file, os.environ)
    compose_project = args.compose_project_name or os.environ.get("COMPOSE_PROJECT_NAME") or parse_env_file(env_file).get("COMPOSE_PROJECT_NAME") or f"sourcebrief_e2e_{run_id}"

    commands: list[dict[str, Any]] = []
    if not args.skip_docker:
        commands.append(run_command(["docker", "compose", "ps", "--format", "json"], cwd=cwd))
    for command in args.command:
        commands.append(run_command(["bash", "-lc", command], cwd=cwd, timeout=900))

    health_checks: list[dict[str, Any]] = []
    if not args.skip_health:
        health_checks.append(http_check(f"{urls['api_url']}/readyz"))
        health_checks.append(http_check(f"{urls['web_url']}/api/health"))

    included_files: list[dict[str, Any]] = []
    for item in args.include_file:
        if "=" not in item:
            raise SystemExit(f"--include-file must be label=path, got {item!r}")
        label, raw_path = item.split("=", 1)
        path = Path(raw_path)
        content = path.read_text(encoding="utf-8") if path.exists() else ""
        included_files.append({"label": label, "path": raw_path, "exists": path.exists(), "content": redact_value(label, content)})

    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "captured_at": captured_at,
        "redaction_policy": "Secret-looking env keys and token-like values are replaced with ***REDACTED***.",
        "git": git_state(cwd),
        "compose": {"project_name": compose_project},
        "urls": urls,
        "env_summary": redacted_env_summary(env_file, os.environ),
        "health_checks": health_checks,
        "commands": commands,
        "included_files": included_files,
    }
    write_bundle(output_dir, manifest)
    print(json.dumps({"status": "written", "output_dir": str(output_dir), "manifest": str(output_dir / "manifest.json")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
