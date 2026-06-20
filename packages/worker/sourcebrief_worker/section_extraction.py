from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from uuid import UUID

PARSER_VERSION = "section-extractor-v1"
SECTION_WINDOW_LINES = 120
SUPPORTED_SECTION_EXTS = frozenset(
    {
        ".md",
        ".mdx",
        ".txt",
        ".rst",
        ".yaml",
        ".yml",
        ".json",
        ".toml",
        ".py",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".rs",
        ".java",
        ".kt",
        ".sh",
        ".sql",
    }
)

EXTRACTION_POLICY = {
    "parser_version": PARSER_VERSION,
    "markdown_split": "atx-heading-blocks",
    "plain_window_lines": SECTION_WINDOW_LINES,
    "plain_overlap_lines": 0,
    "hash_input": "redacted-normalized-text",
}
EXTRACTION_POLICY_HASH = "sha256:" + hashlib.sha256(json.dumps(EXTRACTION_POLICY, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class ExtractedSection:
    normalized_path: str
    ordinal: int
    title: str | None
    content_text: str
    start_line: int
    end_line: int
    parser_version: str
    extraction_policy_hash: str
    section_hash: str
    content_hash: str
    occurrence_key: str
    logical_key: str
    content_bytes: int


def supports_sections(normalized_path: str) -> bool:
    return os.path.splitext(normalized_path)[1].lower() in SUPPORTED_SECTION_EXTS


def normalize_section_text(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _hash(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def logical_section_key(
    *,
    section_family_resource_id: UUID,
    normalized_path: str,
    parser_version: str,
    extraction_policy_hash: str,
    section_hash: str,
    occurrence_key: str,
) -> str:
    payload = "\n".join(
        [
            str(section_family_resource_id),
            normalized_path,
            parser_version,
            extraction_policy_hash,
            section_hash,
            occurrence_key,
        ]
    )
    return _hash(payload)


def extract_sections(*, section_family_resource_id: UUID, normalized_path: str, redacted_text: str) -> list[ExtractedSection]:
    if not supports_sections(normalized_path):
        return []
    normalized = normalize_section_text(redacted_text)
    if not normalized:
        return []
    chunks = _markdown_chunks(normalized) if os.path.splitext(normalized_path)[1].lower() in {".md", ".mdx", ".rst"} else _line_windows(normalized)
    sections: list[ExtractedSection] = []
    for ordinal, (title, content, start_line, end_line) in enumerate(chunks):
        section_text = normalize_section_text(content)
        if not section_text:
            continue
        section_hash = _hash(section_text)
        occurrence_key = f"{ordinal}:{start_line}:{end_line}"
        content_hash = section_hash
        sections.append(
            ExtractedSection(
                normalized_path=normalized_path,
                ordinal=ordinal,
                title=title,
                content_text=section_text,
                start_line=start_line,
                end_line=end_line,
                parser_version=PARSER_VERSION,
                extraction_policy_hash=EXTRACTION_POLICY_HASH,
                section_hash=section_hash,
                content_hash=content_hash,
                occurrence_key=occurrence_key,
                logical_key=logical_section_key(
                    section_family_resource_id=section_family_resource_id,
                    normalized_path=normalized_path,
                    parser_version=PARSER_VERSION,
                    extraction_policy_hash=EXTRACTION_POLICY_HASH,
                    section_hash=section_hash,
                    occurrence_key=occurrence_key,
                ),
                content_bytes=len(section_text.encode("utf-8")),
            )
        )
    return sections


def _line_windows(text: str) -> list[tuple[str | None, str, int, int]]:
    lines = text.splitlines()
    chunks: list[tuple[str | None, str, int, int]] = []
    for start in range(0, len(lines), SECTION_WINDOW_LINES):
        window = lines[start : start + SECTION_WINDOW_LINES]
        if not window:
            continue
        start_line = start + 1
        end_line = start + len(window)
        title = f"Lines {start_line}-{end_line}"
        chunks.append((title, "\n".join(window), start_line, end_line))
    return chunks


def _markdown_chunks(text: str) -> list[tuple[str | None, str, int, int]]:
    lines = text.splitlines()
    heading_re = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    starts: list[int] = []
    titles: dict[int, str] = {}
    for idx, line in enumerate(lines):
        match = heading_re.match(line)
        if match:
            starts.append(idx)
            titles[idx] = match.group(2).strip()
    if not starts:
        return _line_windows(text)
    if starts[0] != 0:
        starts.insert(0, 0)
        titles[0] = "Preamble"
    chunks: list[tuple[str | None, str, int, int]] = []
    for pos, start in enumerate(starts):
        end = starts[pos + 1] if pos + 1 < len(starts) else len(lines)
        content_lines = lines[start:end]
        if not content_lines:
            continue
        chunks.append((titles.get(start), "\n".join(content_lines), start + 1, end))
    return chunks
