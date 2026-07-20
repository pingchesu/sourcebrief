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


def _load_index() -> dict[str, Any]:
    def reject_duplicates(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject_nonfinite(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    payload = json.loads(
        (CORPUS / "task-digest-index.json").read_text(encoding="utf-8"),
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_nonfinite,
    )
    assert isinstance(payload, dict)
    return payload


def test_queuekeeper_pre_d0_commitment_is_metadata_only() -> None:
    payload = _load_index()
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
    payload = _load_index()
    source = payload["source"]
    assert source["repository_url"] == "https://github.com/pingchesu/queuekeeper"
    assert COMMIT_RE.fullmatch(source["snapshot_commit"])
    assert SHA256_RE.fullmatch(source["snapshot_tree_sha256"])
    assert source["license_spdx"] == "MIT"
    assert source["contains_restricted_data"] is False

    counts = payload["counts"]
    split_digests = payload["split_content_sha256"]
    test_digests = payload["sealed_test_sha256"]
    quality = payload["sealed_test_quality"]
    assert {split: len(values) for split, values in split_digests.items()} == counts
    assert {split: len(values) for split, values in test_digests.items()} == {
        "development": counts["development"],
        "held_out": counts["held_out"],
    }
    assert {split: len(values) for split, values in quality.items()} == {
        "development": counts["development"],
        "held_out": counts["held_out"],
    }

    content_values = [value for values in split_digests.values() for value in values]
    test_values = [value for values in test_digests.values() for value in values]
    assert len(content_values) == len(set(content_values)) == 22
    assert len(test_values) == len(set(test_values)) == 16
    digest_values = [
        payload["bundle_sha256"],
        payload["compiler_preview_sha256"],
        payload["green_baseline"]["receipt_sha256"],
        payload["red_baseline"]["receipt_sha256"],
        source["snapshot_tree_sha256"],
        *content_values,
        *test_values,
    ]
    assert len(digest_values) == 43
    assert all(SHA256_RE.fullmatch(value) for value in digest_values)


def test_queuekeeper_readme_matches_machine_commitment() -> None:
    payload = _load_index()
    readme = (CORPUS / "README.md").read_text(encoding="utf-8")
    assert payload["source"]["snapshot_commit"] in readme
    assert payload["source"]["snapshot_tree_sha256"] in readme
    assert "PRE-D0 DRAFT" in readme
    assert "not a final sealed corpus" in readme
    assert "d0_ready" in readme
