from apps.api.sourcebrief_api import skill_exports


def test_skill_export_safe_text_neutralizes_source_evidence_secret_patterns() -> None:
    raw = (
        "Leak scanner docs mention cs_[A-Za-z0-9_-]{12,} and /Users/ examples; "
        "real values include cs_abcdefghijklmnopqrstuvwxyz123456, /home/alice/private, "
        "SOURCEBRIEF_ADMIN_PASSWORD, CONTEXTSMITH_ADMIN_PASSWORD, and session_token fields."
    )

    safe = skill_exports._safe_text(raw, max_len=1_000)  # noqa: SLF001

    assert "cs_[A-Za-z0-9_-]{12,}" not in safe
    assert "cs_abcdefghijklmnopqrstuvwxyz123456" not in safe
    assert "/Users/" not in safe
    assert "/home/alice" not in safe
    assert "SOURCEBRIEF_ADMIN_PASSWORD" not in safe
    assert "CONTEXTSMITH_ADMIN_PASSWORD" not in safe
    assert "session_token" not in safe
    assert "[token-pattern-redacted]" in safe
    assert "[token-redacted]" in safe
    assert "[local-path-pattern-redacted]" in safe


def test_skill_export_scan_stays_strict_after_source_text_redaction() -> None:
    content = skill_exports._safe_text("source text mentions cs_[A-Za-z0-9_-]{12,} and /Users/", max_len=1_000)  # noqa: SLF001
    scan = skill_exports._scan_files([{"path": "references/resource-map.md", "bytes": len(content), "content": content}])  # noqa: SLF001

    assert scan["ok"] is True

    false_positive_prone_inventory = "docs/followups/DOCS_DEEP_PROOF_CLEANUP.md\napps/web/app/users/page.tsx"
    inventory_scan = skill_exports._scan_files(
        [{"path": "references/resource-map.md", "bytes": len(false_positive_prone_inventory), "content": false_positive_prone_inventory}]
    )  # noqa: SLF001

    assert inventory_scan["ok"] is True

    unsafe = "real secret cs_abcdefghijklmnopqrstuvwxyz123456 under /Users/alice/private"
    unsafe_scan = skill_exports._scan_files([{"path": "references/resource-map.md", "bytes": len(unsafe), "content": unsafe}])  # noqa: SLF001

    assert unsafe_scan["ok"] is False


def test_skill_export_validation_requires_self_improvement_boundary() -> None:
    files = []
    for path in sorted(skill_exports.REQUIRED_PACKAGE_PATHS):
        content = "placeholder\n"
        if path == "examples/smoke-queries.md":
            content = "## One\n## Two\n## Three\n"
        files.append({"path": path, "bytes": len(content), "content": content})

    skill_content = "\n".join(
        [
            "Non-negotiable agent operating contract",
            "MCP-first evidence path",
            "CLI fallback/toolbelt",
            "context_pack_key",
            "context_pack_version",
            "context_pack_snapshot_pin_enforced",
            "sourcebrief.get_agent_context",
            "references/data-structure.md",
            "references/resource-map.md",
            "references/task-playbooks/onboarding.md",
            "citations",
            "Mutation boundary",
        ]
    )

    result = skill_exports._validate_files(files, skill_content)  # noqa: SLF001

    assert result["ok"] is False
    messages = [error["message"] for error in result["errors"]]
    assert any("Self-improvement review loop boundary" in message for message in messages)
    assert any("sourcebrief.review-bundle.v1" in message for message in messages)
    assert any("sourcebrief review stage" in message for message in messages)


def test_skill_export_readme_distinguishes_generation_status_from_approval_state() -> None:
    class Version:
        pack_key = "demo"
        version = 7

    readme = skill_exports._render_readme(  # noqa: SLF001
        {"title": "Demo", "version": Version(), "counts": {"resources": 1, "artifacts": 2, "citations": 3}},
        "draft",
    )

    assert "Status: `draft`" not in readme
    assert "Package generation status: `draft` at creation" in readme
    assert "manifest.json" in readme
    assert "export_status" in readme
    assert "approval state is `approved`" in readme


def test_skill_export_scan_rejects_lowercase_windows_user_paths() -> None:
    unsafe = "local path c:\\users\\alice\\secret.txt should not ship"
    scan = skill_exports._scan_files([{"path": "references/resource-map.md", "bytes": len(unsafe), "content": unsafe}])  # noqa: SLF001

    assert scan["ok"] is False
    assert any(finding["message"] == r"[A-Za-z]:\\Users\\" for finding in scan["findings"])
