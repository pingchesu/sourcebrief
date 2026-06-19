from __future__ import annotations

from uuid import uuid4

from contextsmith_worker.ingestion import redact_secrets
from contextsmith_worker.section_extraction import extract_sections


def test_markdown_sections_are_deterministic_and_repeated_blocks_are_distinct() -> None:
    family_id = uuid4()
    text = "# Intro\nsame body\n\n# Intro\nsame body"
    first = extract_sections(section_family_resource_id=family_id, normalized_path="README.md", redacted_text=text)
    second = extract_sections(section_family_resource_id=family_id, normalized_path="README.md", redacted_text=text)
    assert [section.logical_key for section in first] == [section.logical_key for section in second]
    assert len(first) == 2
    assert first[0].section_hash == first[1].section_hash
    assert first[0].occurrence_key != first[1].occurrence_key
    assert first[0].logical_key != first[1].logical_key


def test_plain_text_windows_and_redacted_content_contract() -> None:
    family_id = uuid4()
    secret = "ghp_abcdefghijklmnopqrstuvwxyz"
    raw = f"token={secret}\n" + "hello\n" * 130
    redacted, counts = redact_secrets(raw)
    assert counts["github_token"] == 1
    sections = extract_sections(section_family_resource_id=family_id, normalized_path="notes.txt", redacted_text=redacted)
    assert len(sections) == 2
    assert all(secret not in section.content_text for section in sections)
    assert "[REDACTED:github_token]" in sections[0].content_text
