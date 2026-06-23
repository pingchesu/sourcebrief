from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from time import perf_counter

MAX_PATTERN_LENGTH = 200
MAX_GLOB_LENGTH = 200
MAX_SNIPPET_CHARS = 400
MAX_READ_LINES = 500
MAX_GREP_MATCHES = 100
MAX_SEARCH_RESULTS = 50
MAX_SYMBOL_RESULTS = 100
MAX_REGEX_SCAN_SECONDS = 1.0
MAX_SCANNED_FILES = 200
MAX_SCANNED_BYTES = 2_000_000
MAX_SEARCH_LINE_CHARS = 10_000
_REPETITION_RE = re.compile(r"(\*|\+|\?|\{\d+(?:,\d*)?\})")
_COMPLEX_REGEX_RE = re.compile(
    r"(\([^)]*[+*|][^)]*\)[+*])|([+*?]{2,})|(\([^)]*\|[^)]*\)[+*])"
)
_INVALID_PATH_PREFIXES = ("file://", "http://", "https://")

_IDENTIFIER_SPLIT_RE = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)|\d+")
_IDENTIFIER_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def identifier_tokens(value: str) -> list[str]:
    """Split code-ish names and paths into stable lexical tokens."""
    tokens: list[str] = []
    for raw in _IDENTIFIER_TOKEN_RE.findall(value or ""):
        parts = _IDENTIFIER_SPLIT_RE.findall(raw) or [raw]
        for part in parts:
            lowered = part.lower()
            if lowered and lowered not in tokens:
                tokens.append(lowered)
    return tokens


def identifier_score(query: str, *, path: str, content: str) -> tuple[float, dict[str, float]]:
    query_tokens = identifier_tokens(query)
    if not query_tokens:
        return 0.0, {"exact": 0.0, "identifier": 0.0, "path": 0.0}
    haystack = f"{path}\n{content}"
    haystack_tokens = set(identifier_tokens(haystack))
    overlap = sum(1 for token in query_tokens if token in haystack_tokens) / len(query_tokens)
    lower_query = query.lower()
    exact = 1.0 if lower_query in haystack.lower() else 0.0
    path_tokens = set(identifier_tokens(path))
    path_score = sum(1 for token in query_tokens if token in path_tokens) / len(query_tokens)
    score = min(1.0, exact * 0.45 + overlap * 0.45 + path_score * 0.10)
    return score, {"exact": exact, "identifier": overlap, "path": path_score}


@dataclass(frozen=True)
class RemoteCodeError(Exception):
    code: str
    message: str
    status_code: int = 422


def validate_repo_path(path: str) -> str:
    value = (path or "").strip()
    lower = value.lower()
    if not value:
        raise RemoteCodeError("invalid_path", "path is required")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value) or "\\" in value:
        raise RemoteCodeError("invalid_path", "path must be a repo-relative POSIX path")
    if value.startswith("/") or re.match(r"^[A-Za-z]:", value) or lower.startswith(_INVALID_PATH_PREFIXES):
        raise RemoteCodeError("invalid_path", "absolute/backend paths are not allowed")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise RemoteCodeError("invalid_path", "path traversal is not allowed")
    return value


def validate_path_glob(path_glob: str | None) -> str | None:
    if path_glob is None or path_glob == "":
        return None
    if len(path_glob) > MAX_GLOB_LENGTH:
        raise RemoteCodeError("invalid_path", "path_glob exceeds length budget")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in path_glob) or "\\" in path_glob:
        raise RemoteCodeError("invalid_path", "path_glob must use repo-relative POSIX paths")
    lower = path_glob.lower()
    if path_glob.startswith("/") or re.match(r"^[A-Za-z]:", path_glob) or lower.startswith(_INVALID_PATH_PREFIXES):
        raise RemoteCodeError("invalid_path", "absolute/backend path_glob is not allowed")
    parts = path_glob.split("/")
    if any(part in {"..", "."} for part in parts):
        raise RemoteCodeError("invalid_path", "path_glob traversal is not allowed")
    return path_glob


def compile_safe_regex(pattern: str, *, regex: bool = False) -> re.Pattern[str]:
    if not pattern or not pattern.strip():
        raise RemoteCodeError("invalid_regex", "pattern is required")
    if len(pattern) > MAX_PATTERN_LENGTH:
        raise RemoteCodeError("invalid_regex", "pattern exceeds length budget")
    if "\x00" in pattern:
        raise RemoteCodeError("invalid_regex", "pattern contains NUL byte")
    source = pattern if regex else re.escape(pattern)
    if regex and (_COMPLEX_REGEX_RE.search(source) or _REPETITION_RE.search(source)):
        raise RemoteCodeError("invalid_regex", "pattern exceeds regex complexity budget")
    try:
        return re.compile(source)
    except re.error as exc:
        raise RemoteCodeError("invalid_regex", f"invalid regex: {exc.msg}") from exc


def line_window(lines: list[str], line_number: int, context: int) -> tuple[list[str], list[str]]:
    before_start = max(0, line_number - 1 - context)
    before = lines[before_start : line_number - 1]
    after = lines[line_number : min(len(lines), line_number + context)]
    return before, after


def line_range(content: str, start_line: int, end_line: int | None) -> tuple[str, int, int, int, bool]:
    lines = content.splitlines()
    total = len(lines)
    start = max(1, start_line)
    end = end_line if end_line is not None else min(total, start + MAX_READ_LINES - 1)
    if end < start:
        raise RemoteCodeError("invalid_path", "end_line must be greater than or equal to start_line")
    requested = end - start + 1
    truncated = requested > MAX_READ_LINES
    end = min(end, start + MAX_READ_LINES - 1, total)
    selected = lines[start - 1 : end]
    body = "\n".join(f"{idx}|{text}" for idx, text in enumerate(selected, start=start))
    return body, start, end, total, truncated


def snippet_for_line(line: str) -> str:
    return line if len(line) <= MAX_SNIPPET_CHARS else line[:MAX_SNIPPET_CHARS].rstrip() + "..."


def path_matches(path: str, path_glob: str | None) -> bool:
    return path_glob is None or fnmatch.fnmatch(path, path_glob)


def check_scan_budget(started_at: float) -> None:
    if perf_counter() - started_at > MAX_REGEX_SCAN_SECONDS:
        raise RemoteCodeError("timeout", "grep exceeded time budget", status_code=504)
