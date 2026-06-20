from __future__ import annotations

from sourcebrief_shared.code_intel import extract_code_symbols, language_for_path


def test_extract_python_symbols() -> None:
    symbols = extract_code_symbols(
        "src/app.py",
        "class CheckoutService:\n    pass\n\nasync def refresh_resource():\n    pass\n\ndef helper(x):\n    return x\n",
    )
    assert [(s.kind, s.name, s.line_start) for s in symbols] == [
        ("class", "CheckoutService", 1),
        ("function", "refresh_resource", 4),
        ("function", "helper", 7),
    ]


def test_extract_typescript_symbols() -> None:
    symbols = extract_code_symbols(
        "app/page.tsx",
        "export class SearchPage {}\nexport function runSearch() {}\nconst buildPacket = async () => {};\n",
    )
    assert [(s.kind, s.name, s.language) for s in symbols] == [
        ("class", "SearchPage", "typescript"),
        ("function", "runSearch", "typescript"),
        ("function", "buildPacket", "typescript"),
    ]


def test_non_code_paths_are_ignored() -> None:
    assert language_for_path("README.md") is None
    assert extract_code_symbols("README.md", "def not_code(): pass") == []


def test_python_docstring_definitions_are_not_symbols() -> None:
    content = '"""\ndef fake_docstring():\n    pass\n"""\n\ndef real_symbol():\n    pass\n'
    symbols = extract_code_symbols("src/docstring.py", content)
    assert [symbol.name for symbol in symbols] == ["real_symbol"]


def test_js_block_comment_definitions_are_not_symbols() -> None:
    content = "/*\nfunction fakeComment() {}\n*/\nexport function realSymbol() {}\n"
    symbols = extract_code_symbols("src/comment.ts", content)
    assert [symbol.name for symbol in symbols] == ["realSymbol"]
