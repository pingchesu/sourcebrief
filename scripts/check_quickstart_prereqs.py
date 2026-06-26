from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlparse

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class CheckResult:
    def __init__(self, name: str, ok: bool, message: str, remediation: str | None = None) -> None:
        self.name = name
        self.ok = ok
        self.message = message
        self.remediation = remediation


def run_text(command: list[str]) -> str:
    try:
        result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return (result.stdout or result.stderr).strip()


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def env_value(values: dict[str, str], name: str, default: str) -> str:
    """Return the value the README `make compose-up` path will use.

    GNU make includes `.env` in this repository, and that file assignment wins over
    an inherited shell variable with the same name. Prefer parsed env-file values so
    the doctor cannot pass a shell-exported remote setting while compose still uses
    a stale local-only `.env` value.
    """
    return values.get(name) or os.environ.get(name) or default


def command_check(command: str, label: str, remediation: str) -> CheckResult:
    path = shutil.which(command)
    if not path:
        return CheckResult(label, False, f"{command} not found", remediation)
    return CheckResult(label, True, f"{command} found at {path}")


def docker_compose_check() -> CheckResult:
    if not shutil.which("docker"):
        return CheckResult("docker compose", False, "docker not found", "Install Docker Engine or Docker Desktop with the Compose plugin, then rerun `docker compose version`.")
    output = run_text(["docker", "compose", "version"])
    if not output:
        return CheckResult("docker compose", False, "docker compose did not return a version", "Install or enable the Docker Compose plugin, then rerun `docker compose version`.")
    return CheckResult("docker compose", True, output)


def python_check() -> CheckResult:
    if not shutil.which("python3"):
        return CheckResult("python3", False, "python3 not found", "Install Python 3.11+ or a Python package manager that can run this script.")
    output = run_text(["python3", "--version"])
    return CheckResult("python3", True, f"{output}. SourceBrief uses `uv venv --python 3.11`; host python may be newer if uv can provision Python 3.11.")


def uv_check() -> CheckResult:
    if not shutil.which("uv"):
        return CheckResult(
            "uv",
            False,
            "uv not found",
            "Install uv with `curl -LsSf https://astral.sh/uv/install.sh | sh`, add `$HOME/.local/bin` to PATH, then run `uv python install 3.11` if Python 3.11 is not already available.",
        )
    output = run_text(["uv", "--version"])
    return CheckResult("uv", True, output or "uv found")


def node_check() -> CheckResult:
    if not shutil.which("node"):
        return CheckResult("node", False, "node not found", "Install Node.js 20+ and npm before running the web frontend.")
    output = run_text(["node", "--version"])
    version = output.lstrip("v").split(".", 1)[0]
    if version.isdigit() and int(version) < 20:
        return CheckResult("node", False, output, "Install Node.js 20+; older Node versions may fail frontend install/build.")
    return CheckResult("node", True, output or "node found")


def remote_browser_check(values: dict[str, str], origin: str | None) -> list[CheckResult]:
    if not origin:
        return []
    results: list[CheckResult] = []
    parsed_origin = urlparse(origin)
    origin_host = parsed_origin.hostname or ""
    web_port = env_value(values, "SOURCEBRIEF_WEB_PORT", env_value(values, "CONTEXTSMITH_WEB_PORT", "13000"))
    api_port = env_value(values, "SOURCEBRIEF_API_PORT", env_value(values, "CONTEXTSMITH_API_PORT", "18000"))
    expected_origin = origin.rstrip("/")
    api_base = env_value(values, "NEXT_PUBLIC_API_BASE_URL", f"http://localhost:{api_port}").rstrip("/")
    parsed_api = urlparse(api_base)
    cors_raw = env_value(values, "SOURCEBRIEF_CORS_ORIGINS", env_value(values, "CONTEXTSMITH_CORS_ORIGINS", ""))
    cors = {item.strip().rstrip("/") for item in cors_raw.split(",") if item.strip()}

    if origin_host not in LOCAL_HOSTS and (parsed_api.hostname or "") in LOCAL_HOSTS:
        results.append(
            CheckResult(
                "remote browser API URL",
                False,
                f"remote browser origin {expected_origin} would use local-only NEXT_PUBLIC_API_BASE_URL={api_base}",
                f"Set NEXT_PUBLIC_API_BASE_URL=http://{origin_host}:{api_port} before `make compose-up`, then rebuild with `docker compose up -d --build`.",
            )
        )
    else:
        results.append(CheckResult("remote browser API URL", True, f"NEXT_PUBLIC_API_BASE_URL={api_base}"))

    if expected_origin not in cors:
        results.append(
            CheckResult(
                "remote browser CORS origin",
                False,
                f"SOURCEBRIEF_CORS_ORIGINS does not include {expected_origin}",
                f"Add {expected_origin} to SOURCEBRIEF_CORS_ORIGINS before startup; keep localhost origins too for host-side checks. Example web port: {web_port}.",
            )
        )
    else:
        results.append(CheckResult("remote browser CORS origin", True, f"SOURCEBRIEF_CORS_ORIGINS includes {expected_origin}"))
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check SourceBrief quickstart prerequisites with actionable remediation hints.")
    parser.add_argument("--env-file", default=".env", help="environment file to inspect for remote browser settings")
    parser.add_argument(
        "--remote-browser-origin",
        help="browser-visible web origin for remote/self-host checks, e.g. http://10.10.70.17:13000",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    env_values = parse_env_file(Path(args.env_file))
    checks = [
        docker_compose_check(),
        python_check(),
        uv_check(),
        node_check(),
        command_check("npm", "npm", "Install npm with Node.js 20+ or your OS package manager."),
        command_check("git", "git", "Install git before cloning SourceBrief."),
    ]
    checks.extend(remote_browser_check(env_values, args.remote_browser_origin))

    failed = False
    for check in checks:
        prefix = "PASS" if check.ok else "FAIL"
        print(f"[{prefix}] {check.name}: {check.message}")
        if not check.ok and check.remediation:
            print(f"       fix: {check.remediation}")
        failed = failed or not check.ok
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
