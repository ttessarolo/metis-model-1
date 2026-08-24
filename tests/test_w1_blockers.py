from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from metis_model1 import w1_blockers
from metis_model1.w1_blockers import (
    BlockerMapError,
    build_blocker_map,
    manifest_hash,
    validate_blocker_map,
)

ROOT = Path(__file__).parents[1]


def test_blocker_map_is_exact_and_schema_valid() -> None:
    manifest = build_blocker_map(ROOT)
    schema = json.loads((ROOT / "schemas/w1-slice-30-blocker-map.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(manifest)) == []
    assert validate_blocker_map(manifest, ROOT) == []
    assert manifest["counts"]["tasks_out"] == 30
    assert manifest["counts"]["assets_out"] == 201
    assert manifest["counts"]["leakage_groups"] == 1
    assert all(
        row["status"] == "blocked" and row["evidence_refs"] == [] for row in manifest["tasks"]
    )


def test_dependency_tags_and_blockers_follow_each_closure_row() -> None:
    manifest = build_blocker_map(ROOT)
    rows = {row["task_id"]: row for row in manifest["tasks"]}
    assert rows["slice-0001/f1-02"]["dependency_tags"] == ["semantic", "task_oracle"]
    assert "ambient" not in rows["slice-0001/f1-02"]["dependency_tags"]
    assert "external" in rows["slice-0001/f2-01"]["dependency_tags"]
    assert "sidecar" in rows["slice-0001/f2-01"]["dependency_tags"]
    assert "direct_runtime" in rows["slice-0001/f2-01"]["dependency_tags"]
    closure = json.loads((ROOT / "manifests/slice-30-closure.json").read_text())
    unresolved = next(x for x in closure["tasks"] if x["task_id"] == "slice-0001/f2-01")[
        "unresolved_dependencies"
    ]
    assert rows["slice-0001/f2-01"]["blockers"] == [
        "dependency_closure_computed_not_sealed",
        *unresolved,
    ]


def test_blocker_map_rejects_plan_closure_seam_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    original = w1_blockers._load

    def load(path: Path):
        value = original(path)
        if path.name == "slice-30-closure.json":
            value = copy.deepcopy(value)
            value["tasks"][1]["family"] = "F-2"
        return value

    monkeypatch.setattr(w1_blockers, "_load", load)
    with pytest.raises(BlockerMapError, match="task/closure family drift"):
        build_blocker_map(ROOT)


def test_blocker_map_rejects_hash_and_input_pin_drift() -> None:
    manifest = copy.deepcopy(build_blocker_map(ROOT))
    manifest["tasks"][0]["source_path"] += ".drift"
    assert "manifest_hash does not match canonical body" in validate_blocker_map(manifest, ROOT)
    manifest = copy.deepcopy(build_blocker_map(ROOT))
    manifest["input_pins"]["closure"] = "sha256:" + "0" * 64
    assert "field drift: input_pins" in validate_blocker_map(manifest, ROOT)


def test_blocker_map_rejects_duplicate_or_laundered_rows() -> None:
    manifest = copy.deepcopy(build_blocker_map(ROOT))
    manifest["tasks"][1]["task_id"] = manifest["tasks"][0]["task_id"]
    manifest["manifest_hash"] = manifest_hash(manifest)
    errors = validate_blocker_map(manifest, ROOT)
    assert "duplicate task IDs" in errors
    manifest = copy.deepcopy(build_blocker_map(ROOT))
    manifest["tasks"][0]["status"] = "ready"
    manifest["manifest_hash"] = manifest_hash(manifest)
    assert "blocked status was laundered" in validate_blocker_map(manifest, ROOT)


def test_blocker_map_rejects_count_laundering_and_evidence() -> None:
    manifest = copy.deepcopy(build_blocker_map(ROOT))
    manifest["tasks"][0]["dependency_tags"].remove("task_oracle")
    manifest["tasks"][0]["evidence_refs"] = ["unverified"]
    manifest["manifest_hash"] = manifest_hash(manifest)
    errors = validate_blocker_map(manifest, ROOT)
    assert "dependency tag counts drift" in errors
    assert "evidence_refs must remain empty" in errors
    manifest = copy.deepcopy(build_blocker_map(ROOT))
    manifest["tasks"][0]["blockers"].remove("data_rights_not_reviewed")
    manifest["manifest_hash"] = manifest_hash(manifest)
    assert "unresolved dependency counts drift" in validate_blocker_map(manifest, ROOT)
    manifest = copy.deepcopy(build_blocker_map(ROOT))
    manifest["tasks"][0]["blockers"].remove("task_specific_oracles_not_executed")
    manifest["manifest_hash"] = manifest_hash(manifest)
    assert "unresolved dependency counts drift" in validate_blocker_map(manifest, ROOT)


def test_blocker_map_rejects_any_top_level_identity_drift() -> None:
    for field, value in {
        "manifest_id": "other",
        "source_revision": "0" * 40,
        "language_version": "0.99",
        "closure_manifest_id": "other",
    }.items():
        manifest = copy.deepcopy(build_blocker_map(ROOT))
        manifest[field] = value
        manifest["manifest_hash"] = manifest_hash(manifest)
        assert f"field drift: {field}" in validate_blocker_map(manifest, ROOT)
