from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "eval" / "gate_a" / "queuekeeper-v1"
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


def _walk(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def test_queuekeeper_pre_d0_commitment_is_metadata_only() -> None:
    payload = json.loads((CORPUS / "task-digest-index.json").read_text(encoding="utf-8"))
    assert set(payload) == {
        "blockers",
        "bundle_sha256",
        "classification",
        "compiler_preview_sha256",
        "counts",
        "d0_ready",
        "green_baseline",
        "red_baseline",
        "schema_version",
        "sealed_test_quality",
        "sealed_test_sha256",
        "similarity",
        "source",
        "split_content_sha256",
    }
    assert payload["classification"] == "pre-d0-draft-not-sealed"
    assert payload["d0_ready"] is False
    assert payload["counts"] == {"development": 4, "held_out": 12, "controls": 6}
    assert len(payload["blockers"]) >= 2

    forbidden_keys = {
        "allowed_paths",
        "control_type",
        "expected_behavior",
        "expected_evidence",
        "id",
        "objective_assertions",
        "prompt",
        "required_resources",
        "task_id",
    }
    observed_keys = {key for key, _ in _walk(payload)}
    assert forbidden_keys.isdisjoint(observed_keys)


def test_queuekeeper_commitment_digests_and_source_are_well_formed() -> None:
    payload = json.loads((CORPUS / "task-digest-index.json").read_text(encoding="utf-8"))
    source = payload["source"]
    assert source["repository_url"] == "https://github.com/pingchesu/queuekeeper"
    assert COMMIT_RE.fullmatch(source["snapshot_commit"])
    assert SHA256_RE.fullmatch(source["snapshot_tree_sha256"])
    assert source["license_spdx"] == "MIT"
    assert source["contains_restricted_data"] is False

    digest_values = []
    for key, value in _walk(payload):
        if key.endswith("sha256"):
            if isinstance(value, str):
                digest_values.append(value)
            elif isinstance(value, list):
                digest_values.extend(value)
    assert digest_values
    assert all(SHA256_RE.fullmatch(value) for value in digest_values)


def test_queuekeeper_readme_matches_machine_commitment() -> None:
    payload = json.loads((CORPUS / "task-digest-index.json").read_text(encoding="utf-8"))
    readme = (CORPUS / "README.md").read_text(encoding="utf-8")
    assert payload["source"]["snapshot_commit"] in readme
    assert payload["source"]["snapshot_tree_sha256"] in readme
    assert "PRE-D0 DRAFT" in readme
    assert "not a final sealed corpus" in readme
    assert "d0_ready" in readme
