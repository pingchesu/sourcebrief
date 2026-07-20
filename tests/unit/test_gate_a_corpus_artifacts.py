from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "eval" / "gate_a" / "queuekeeper-v1"
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
EXPECTED_COUNTS = {"development": 4, "held_out": 12, "controls": 6}
EXPECTED_BLOCKERS = [
    "named human owners and protected approval event are not yet supplied",
    (
        "final held-out, control, and grader content must be independently re-authored on the isolated QA host "
        "because this draft received LLM-assisted review"
    ),
]


def _parse_index_text(text: str) -> dict[str, Any]:
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
        text,
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_nonfinite,
    )
    assert isinstance(payload, dict)
    return payload


def _load_index() -> dict[str, Any]:
    return _parse_index_text((CORPUS / "task-digest-index.json").read_text(encoding="utf-8"))


def _assert_digest(value: Any) -> None:
    assert isinstance(value, str)
    assert SHA256_RE.fullmatch(value)


def _validate_index(payload: dict[str, Any]) -> None:
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
    assert payload["schema_version"] == "sourcebrief.gate-a-task-digest-index.v1"
    assert payload["classification"] == "pre-d0-draft-not-sealed"
    assert payload["d0_ready"] is False
    assert payload["blockers"] == EXPECTED_BLOCKERS
    assert payload["counts"] == EXPECTED_COUNTS
    _assert_digest(payload["bundle_sha256"])
    _assert_digest(payload["compiler_preview_sha256"])

    source = payload["source"]
    assert set(source) == {
        "contains_restricted_data",
        "kind",
        "license_spdx",
        "repository_url",
        "snapshot_commit",
        "snapshot_tree_sha256",
    }
    assert source["kind"] == "git"
    assert source["repository_url"] == "https://github.com/pingchesu/queuekeeper"
    assert COMMIT_RE.fullmatch(source["snapshot_commit"])
    _assert_digest(source["snapshot_tree_sha256"])
    assert source["license_spdx"] == "MIT"
    assert source["contains_restricted_data"] is False

    green = payload["green_baseline"]
    assert set(green) == {"all_commands_green", "receipt_sha256"}
    assert green["all_commands_green"] is True
    _assert_digest(green["receipt_sha256"])
    red = payload["red_baseline"]
    assert set(red) == {"all_tasks_red", "receipt_sha256"}
    assert red["all_tasks_red"] is True
    _assert_digest(red["receipt_sha256"])

    similarity = payload["similarity"]
    assert set(similarity) == {"dev_held_max_5gram_jaccard", "held_held_max_5gram_jaccard"}
    assert all(type(value) in {int, float} and 0 <= value <= 1 for value in similarity.values())

    split_digests = payload["split_content_sha256"]
    assert set(split_digests) == set(EXPECTED_COUNTS)
    assert {split: len(values) for split, values in split_digests.items()} == EXPECTED_COUNTS
    content_values = [value for values in split_digests.values() for value in values]
    assert len(content_values) == len(set(content_values)) == 22
    assert all(SHA256_RE.fullmatch(value) for value in content_values)

    expected_task_splits = {"development", "held_out"}
    test_digests = payload["sealed_test_sha256"]
    quality = payload["sealed_test_quality"]
    assert set(test_digests) == expected_task_splits
    assert set(quality) == expected_task_splits
    expected_test_counts = {
        "development": EXPECTED_COUNTS["development"],
        "held_out": EXPECTED_COUNTS["held_out"],
    }
    assert {split: len(values) for split, values in test_digests.items()} == expected_test_counts
    assert {split: len(values) for split, values in quality.items()} == expected_test_counts
    test_values = [value for values in test_digests.values() for value in values]
    assert len(test_values) == len(set(test_values)) == 16
    assert all(SHA256_RE.fullmatch(value) for value in test_values)
    for entries in quality.values():
        for entry in entries:
            assert set(entry) == {"assertions", "raises_oracles", "test_functions"}
            assert type(entry["assertions"]) is int and entry["assertions"] >= 0
            assert type(entry["raises_oracles"]) is int and entry["raises_oracles"] >= 0
            assert type(entry["test_functions"]) is int and entry["test_functions"] >= 2
            assert entry["assertions"] + entry["raises_oracles"] >= 4

    all_digests = [
        payload["bundle_sha256"],
        payload["compiler_preview_sha256"],
        green["receipt_sha256"],
        red["receipt_sha256"],
        source["snapshot_tree_sha256"],
        *content_values,
        *test_values,
    ]
    assert len(all_digests) == 43
    assert all(SHA256_RE.fullmatch(value) for value in all_digests)


def test_queuekeeper_pre_d0_commitment_has_exact_metadata_schema() -> None:
    _validate_index(_load_index())


def test_strict_parser_rejects_duplicate_keys_and_nonfinite_numbers() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        _parse_index_text('{"source": {}, "source": {"prompt": "leak"}}')
    with pytest.raises(ValueError, match="non-finite"):
        _parse_index_text('{"value": NaN}')


def test_schema_rejects_nested_plaintext_and_malformed_digest_collections() -> None:
    payload = _load_index()
    nested = copy.deepcopy(payload)
    nested["source"]["hidden_test"] = "plaintext"
    with pytest.raises(AssertionError):
        _validate_index(nested)

    malformed = copy.deepcopy(payload)
    malformed["sealed_test_sha256"]["held_out"][0] = "NOT-A-DIGEST"
    with pytest.raises(AssertionError):
        _validate_index(malformed)

    incomplete = copy.deepcopy(payload)
    incomplete["split_content_sha256"]["controls"].pop()
    with pytest.raises(AssertionError):
        _validate_index(incomplete)


def test_queuekeeper_readme_matches_machine_commitment() -> None:
    payload = _load_index()
    readme = (CORPUS / "README.md").read_text(encoding="utf-8")
    assert payload["source"]["snapshot_commit"] in readme
    assert payload["source"]["snapshot_tree_sha256"] in readme
    assert "PRE-D0 DRAFT" in readme
    assert "not a final sealed corpus" in readme
    assert "d0_ready" in readme
