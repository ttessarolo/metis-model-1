from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from metis_model1 import w1_seal
from metis_model1.w1_seal import (
    W1SealError,
    build_benchmark_seal,
    build_held_out_map,
    build_leakage_assignment,
    build_oracle_receipts,
    manifest_hash,
    validate_benchmark_seal,
    validate_held_out_map,
    validate_leakage_assignment,
    validate_oracle_receipts,
)

ROOT = Path(__file__).parents[1]
MANIFESTS = {
    "oracle": "w1-slice-30-oracle-receipts-v1.json",
    "leakage": "w1-leakage-group-assignment-v1.json",
    "held_out": "w1-held-out-family-map-v1.json",
    "seal": "w1-benchmark-seal-v1.json",
}
SCHEMAS = {
    "oracle": "w1-slice-30-oracle-receipts.schema.json",
    "leakage": "w1-leakage-group-assignment.schema.json",
    "held_out": "w1-held-out-family-map.schema.json",
    "seal": "w1-benchmark-seal.schema.json",
}


def _tracked(name: str) -> dict:
    return json.loads((ROOT / "manifests" / MANIFESTS[name]).read_text())


def test_bundle_is_deterministic_and_schema_valid() -> None:
    builders = {
        "oracle": build_oracle_receipts,
        "leakage": build_leakage_assignment,
        "held_out": build_held_out_map,
        "seal": build_benchmark_seal,
    }
    validators = {
        "oracle": validate_oracle_receipts,
        "leakage": validate_leakage_assignment,
        "held_out": validate_held_out_map,
        "seal": validate_benchmark_seal,
    }
    for name, builder in builders.items():
        tracked = _tracked(name)
        schema = json.loads((ROOT / "schemas" / SCHEMAS[name]).read_text())
        Draft202012Validator.check_schema(schema)
        assert list(Draft202012Validator(schema).iter_errors(tracked)) == []
        assert tracked == builder(ROOT)
        assert validators[name](tracked, ROOT) == []


def test_oracle_roster_has_exact_denominators_and_future_target() -> None:
    manifest = build_oracle_receipts(ROOT)
    assert manifest["counts"] == {
        "tasks_in": 30,
        "tasks_out": 30,
        "task_ids_distinct": 30,
        "oracle_cells_intended": 160,
        "oracle_cells_executed": 0,
        "f4_f6_cells_intended": 75,
        "f4_f6_cells_executed": 0,
        "gaps": 160,
    }
    assert manifest["future_protected_role_receipt_target"]["target"] == 25
    assert (
        sum(
            entry["target"]
            for entry in manifest["future_protected_role_receipt_target"]["by_family"].values()
        )
        == 25
    )
    assert all(
        cell["status"] == "not_run"
        and cell["authority"] is None
        and cell["receipt_ref"] is None
        and cell["receipt_sha256"] is None
        for row in manifest["tasks"]
        for cell in row["oracle_cells"]
    )


def test_oracle_receipts_reject_duplicate_cross_bind_and_claim_laundering() -> None:
    manifest = copy.deepcopy(build_oracle_receipts(ROOT))
    manifest["tasks"][1]["task_id"] = manifest["tasks"][0]["task_id"]
    manifest["manifest_hash"] = manifest_hash(manifest)
    assert any("field drift: tasks" in error for error in validate_oracle_receipts(manifest, ROOT))

    manifest = copy.deepcopy(build_oracle_receipts(ROOT))
    manifest["tasks"][0]["oracle_cells"].pop()
    manifest["manifest_hash"] = manifest_hash(manifest)
    errors = validate_oracle_receipts(manifest, ROOT)
    assert any("field drift: tasks" in error for error in errors)
    assert "oracle cell denominator is not 160" in errors

    manifest = copy.deepcopy(build_oracle_receipts(ROOT))
    cell = manifest["tasks"][0]["oracle_cells"][0]
    cell["status"] = "pass"
    cell["authority"] = "synthetic-receipt"
    cell["receipt_ref"] = "artifacts/forged.json"
    cell["receipt_sha256"] = "sha256:" + "0" * 64
    manifest["manifest_hash"] = manifest_hash(manifest)
    errors = validate_oracle_receipts(manifest, ROOT)
    assert any("field drift: tasks" in error for error in errors)
    assert "oracle execution status was laundered" in errors
    assert "oracle receipt authority was laundered" in errors


def test_oracle_builder_rejects_plan_closure_cross_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    original = w1_seal._load

    def mutated(path: Path) -> dict:
        value = original(path)
        if path.name == "slice-30-closure.json":
            value = copy.deepcopy(value)
            value["tasks"][0]["family"] = "F-6"
        return value

    monkeypatch.setattr(w1_seal, "_load", mutated)
    with pytest.raises(W1SealError, match="cross-bound family drift"):
        build_oracle_receipts(ROOT)


@pytest.mark.parametrize(
    ("filename", "mutate", "message"),
    [
        (
            "w1-slice-30-blocker-map-v1.json",
            lambda value: value["input_pins"].__setitem__("closure", "sha256:" + "0" * 64),
            "blocker map upstream validation",
        ),
        (
            "w2-rights-dossier-v1.json",
            lambda value: value["assets"][0].__setitem__("status", "approved"),
            "rights dossier upstream validation",
        ),
    ],
)
def test_oracle_builder_rejects_stale_or_mutated_upstream_sidecars(
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    mutate: object,
    message: str,
) -> None:
    original = w1_seal._load

    def mutated(path: Path) -> dict:
        value = original(path)
        if path.name == filename:
            value = copy.deepcopy(value)
            assert callable(mutate)
            mutate(value)
        return value

    monkeypatch.setattr(w1_seal, "_load", mutated)
    with pytest.raises(W1SealError, match=message):
        build_oracle_receipts(ROOT)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("total", 599),
        ("minimum_distinct_leakage_groups", 562),
        ("decision_ref", "O-999"),
    ],
)
def test_oracle_builder_rejects_accuracy_target_drift(
    monkeypatch: pytest.MonkeyPatch, field: str, value: int | str
) -> None:
    original = w1_seal._load

    def mutated(path: Path) -> dict:
        payload = original(path)
        if path.name == "accuracy-target.json":
            payload = copy.deepcopy(payload)
            payload[field] = value
        return payload

    monkeypatch.setattr(w1_seal, "_load", mutated)
    with pytest.raises(W1SealError, match="accuracy target family counts or status drift"):
        build_oracle_receipts(ROOT)


def test_leakage_assignment_rejects_inflation_and_invented_signatures() -> None:
    manifest = copy.deepcopy(build_leakage_assignment(ROOT))
    manifest["assignments"][0]["leakage_group_id"] = "sha256:" + "f" * 64
    manifest["population_claim_eligible"] = True
    manifest["manifest_hash"] = manifest_hash(manifest)
    errors = validate_leakage_assignment(manifest, ROOT)
    assert any("field drift: assignments" in error for error in errors)
    assert "leakage group count was inflated" in errors
    assert "population claim eligibility was laundered" in errors

    manifest = copy.deepcopy(build_leakage_assignment(ROOT))
    manifest["assignments"][0]["normalized_ast_signature"] = "sha256:" + "a" * 64
    manifest["manifest_hash"] = manifest_hash(manifest)
    assert any(
        "field drift: assignments" in error for error in validate_leakage_assignment(manifest, ROOT)
    )


def test_held_out_map_binds_rules_allocations_and_target_counts() -> None:
    manifest = build_held_out_map(ROOT)
    assert [row["target_frozen_task_count"] for row in manifest["families"]] == [
        100,
        110,
        110,
        110,
        90,
        80,
    ]
    assert all(len(row["allocated_task_ids"]) == 5 for row in manifest["families"])
    mutated = copy.deepcopy(manifest)
    mutated["families"][3]["held_out_rule"] = "invented"
    mutated["manifest_hash"] = manifest_hash(mutated)
    assert any("field drift: families" in error for error in validate_held_out_map(mutated, ROOT))


def test_benchmark_seal_binds_every_reference_and_exact_blockers() -> None:
    manifest = build_benchmark_seal(ROOT)
    assert set(manifest["references"]) == {
        "closure",
        "assets",
        "blocker_map",
        "rights_dossier",
        "oracle_receipts",
        "leakage_assignment",
        "held_out_map",
        "accuracy_target",
    }
    assert manifest["blockers"] == {
        "legal_review": {"reviewed": 0, "required": 201},
        "task_specific_oracles": {"executed": 0, "required": 30},
        "oracle_cells": {"executed": 0, "required": 160},
        "leakage_groups": {"current": 1, "minimum": 563},
        "phase_b": "absent",
        "f4_f6_typed_oracles": "absent",
        "o003": "open",
        "ab_baseline": "absent",
    }
    assert manifest["seal_eligible"] is False
    assert manifest["status"] == "unsealed_evidence_only"


def test_benchmark_seal_rejects_hash_and_green_status_laundering() -> None:
    manifest = copy.deepcopy(build_benchmark_seal(ROOT))
    manifest["references"]["accuracy_target"]["file_sha256"] = "sha256:" + "0" * 64
    manifest["status"] = "sealed"
    manifest["seal_eligible"] = True
    manifest["manifest_hash"] = manifest_hash(manifest)
    errors = validate_benchmark_seal(manifest, ROOT)
    assert any("field drift: references" in error for error in errors)
    assert "benchmark seal status was laundered" in errors


def test_schema_rejects_bad_oracle_status_and_missing_input_pin() -> None:
    schema = json.loads((ROOT / "schemas" / SCHEMAS["oracle"]).read_text())
    manifest = copy.deepcopy(build_oracle_receipts(ROOT))
    manifest["tasks"][0]["oracle_cells"][0]["status"] = "pass"
    manifest["input_pins"].pop("closure")
    assert list(Draft202012Validator(schema).iter_errors(manifest))
