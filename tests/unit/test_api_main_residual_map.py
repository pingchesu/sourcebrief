from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "refactor" / "sourcebrief-api-main-residual-map.md"


def test_api_main_residual_map_tracks_remaining_service_boundaries() -> None:
    text = DOC.read_text(encoding="utf-8")
    for required in [
        "Project/auth/resource access helpers",
        "Agent-context synthesis and coverage helpers",
        "MCP/runtime tool implementation",
        "Context-packet action",
        "route signature parity",
        "sourcebrief_api.main.app",
    ]:
        assert required in text


def test_api_main_residual_map_records_current_guardrail_context() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert "2,364 lines" in text
    assert "84 top-level functions" in text
    assert "tests/unit/test_entrypoint_size_guardrails.py" in text
