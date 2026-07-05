from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

ENTRYPOINT_LIMITS = {
    "packages/cli/sourcebrief_cli/main.py": {
        "max_lines": 260,
        "max_top_level_functions": 6,
        "destination": "packages/cli/sourcebrief_cli/commands/ or focused CLI support modules",
    },
    "apps/api/sourcebrief_api/main.py": {
        "max_lines": 2190,
        "max_top_level_functions": 90,
        "destination": "apps/api/sourcebrief_api/routers/, app_factory.py, or focused service/helper modules",
    },
}


def _top_level_function_count(path: Path) -> int:
    module = ast.parse(path.read_text(encoding="utf-8"))
    return sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in module.body)


def test_entrypoint_modules_stay_below_refactor_guardrails() -> None:
    failures: list[str] = []
    for rel_path, limits in ENTRYPOINT_LIMITS.items():
        path = REPO_ROOT / rel_path
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        function_count = _top_level_function_count(path)
        max_lines = limits["max_lines"]
        max_functions = limits["max_top_level_functions"]
        destination = limits["destination"]
        if line_count > max_lines or function_count > max_functions:
            failures.append(
                f"{rel_path} has {line_count} lines/{function_count} top-level functions; "
                f"guardrail is <= {max_lines} lines/{max_functions} functions. "
                f"Move new entrypoint logic to {destination}."
            )
    assert not failures, "\n".join(failures)
