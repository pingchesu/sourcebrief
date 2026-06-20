from __future__ import annotations

import ast
import re
from dataclasses import dataclass

_JS_DEF = re.compile(
    r"^\s*(?:export\s+)?(?:(?P<kind>class|function)\s+(?P<name>[A-Za-z_$][A-Za-z0-9_$]*)|(?:const|let|var)\s+(?P<var>[A-Za-z_$][A-Za-z0-9_$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][A-Za-z0-9_$]*)\s*=>)"
)


@dataclass(frozen=True)
class CodeSymbolRecord:
    path: str
    name: str
    kind: str
    language: str
    line_start: int
    line_end: int
    signature: str


def language_for_path(path: str | None) -> str | None:
    if not path:
        return None
    lowered = path.lower()
    if lowered.endswith(".py"):
        return "python"
    if lowered.endswith((".ts", ".tsx")):
        return "typescript"
    if lowered.endswith((".js", ".jsx", ".mjs", ".cjs")):
        return "javascript"
    return None


def _line_signature(lines: list[str], lineno: int) -> str:
    if lineno <= 0 or lineno > len(lines):
        return ""
    return lines[lineno - 1].strip()[:500]


def _extract_python_symbols(path: str, content: str) -> list[CodeSymbolRecord]:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return []
    lines = content.splitlines()
    records: list[CodeSymbolRecord] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            records.append(
                CodeSymbolRecord(
                    path=path,
                    name=node.name,
                    kind="class",
                    language="python",
                    line_start=node.lineno,
                    line_end=getattr(node, "end_lineno", node.lineno) or node.lineno,
                    signature=_line_signature(lines, node.lineno),
                )
            )
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            records.append(
                CodeSymbolRecord(
                    path=path,
                    name=node.name,
                    kind="function",
                    language="python",
                    line_start=node.lineno,
                    line_end=getattr(node, "end_lineno", node.lineno) or node.lineno,
                    signature=_line_signature(lines, node.lineno),
                )
            )
    return sorted(records, key=lambda item: (item.line_start, item.name))


def _strip_js_line(line: str, *, in_block_comment: bool, in_template: bool) -> tuple[str, bool, bool]:
    output: list[str] = []
    i = 0
    quote: str | None = None
    while i < len(line):
        ch = line[i]
        nxt = line[i + 1] if i + 1 < len(line) else ""
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue
        if in_template:
            if ch == "`" and (i == 0 or line[i - 1] != "\\"):
                in_template = False
            i += 1
            continue
        if quote is not None:
            if ch == quote and (i == 0 or line[i - 1] != "\\"):
                quote = None
            i += 1
            continue
        if ch in {"'", '"'}:
            quote = ch
            i += 1
            continue
        if ch == "`":
            in_template = True
            i += 1
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "/":
            break
        output.append(ch)
        i += 1
    return "".join(output), in_block_comment, in_template


def _extract_js_symbols(path: str, content: str, language: str) -> list[CodeSymbolRecord]:
    records: list[CodeSymbolRecord] = []
    in_block_comment = False
    in_template = False
    for idx, line in enumerate(content.splitlines(), start=1):
        code, in_block_comment, in_template = _strip_js_line(
            line,
            in_block_comment=in_block_comment,
            in_template=in_template,
        )
        if not code.strip():
            continue
        match = _JS_DEF.match(code)
        if not match:
            continue
        raw_kind = match.group("kind")
        name = match.group("name") or match.group("var")
        kind = "class" if raw_kind == "class" else "function"
        records.append(
            CodeSymbolRecord(
                path=path,
                name=name,
                kind=kind,
                language=language,
                line_start=idx,
                line_end=idx,
                signature=code.strip()[:500],
            )
        )
    return records


def extract_code_symbols(path: str | None, content: str) -> list[CodeSymbolRecord]:
    """Extract deterministic code symbols; never infer edges or behavior."""
    language = language_for_path(path)
    if language is None or path is None:
        return []
    if language == "python":
        return _extract_python_symbols(path, content)
    return _extract_js_symbols(path, content, language)
