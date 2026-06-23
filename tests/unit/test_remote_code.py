from __future__ import annotations

import pytest

from sourcebrief_api.remote_code import (
    RemoteCodeError,
    compile_safe_regex,
    identifier_score,
    identifier_tokens,
    line_range,
    validate_path_glob,
    validate_repo_path,
)


@pytest.mark.parametrize("path", ["/etc/passwd", "../x.py", "src/../x.py", "src\\x.py", "C:\\x.py", "file:///tmp/x.py", "", "a//b.py", "a/./b.py", "bad\x00.py"])
def test_validate_repo_path_rejects_non_repo_relative_paths(path: str) -> None:
    with pytest.raises(RemoteCodeError) as exc:
        validate_repo_path(path)
    assert exc.value.code == "invalid_path"


def test_validate_repo_path_accepts_posix_relative_path() -> None:
    assert validate_repo_path("src/service.py") == "src/service.py"


@pytest.mark.parametrize("glob", ["/tmp/*.py", "../*.py", "src\\*.py", "file://*.py", "a/../*.py", "bad\x00*"])
def test_validate_path_glob_rejects_unsafe_patterns(glob: str) -> None:
    with pytest.raises(RemoteCodeError) as exc:
        validate_path_glob(glob)
    assert exc.value.code == "invalid_path"


@pytest.mark.parametrize("pattern", ["(", "(a+)+$", "^(a?){100}a{100}$", "x" * 201, "bad\x00pattern"])
def test_compile_safe_regex_rejects_invalid_or_complex_regex(pattern: str) -> None:
    with pytest.raises(RemoteCodeError) as exc:
        compile_safe_regex(pattern, regex=True)
    assert exc.value.code == "invalid_regex"


def test_line_range_prefixes_lines_and_caps_large_ranges() -> None:
    content = "\n".join(f"line {idx}" for idx in range(1, 700))
    body, start, end, total, truncated = line_range(content, 2, 650)
    assert start == 2
    assert end == 501
    assert total == 699
    assert truncated is True
    assert body.splitlines()[0] == "2|line 2"


def test_identifier_tokens_split_code_conventions() -> None:
    assert identifier_tokens("renderCheckout src/order-service/api.ts") == [
        "render",
        "checkout",
        "src",
        "order",
        "service",
        "api",
        "ts",
    ]


def test_identifier_score_rewards_token_overlap_and_path() -> None:
    score, components = identifier_score(
        "render checkout",
        path="src/checkout-ui.ts",
        content="export function renderCheckout() { return true; }",
    )
    assert score >= 0.45
    assert components["identifier"] == 1.0
    assert components["path"] == 0.5
