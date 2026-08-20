from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from metis_model1.assets import (
    EXPECTED_ASSET_COUNT,
    AssetRegisterError,
    build_asset_register,
    load_closure,
    validate_asset_register,
)
from metis_model1.contracts import load_json, validate_instance

ROOT = Path(__file__).parents[1]


def test_tracked_asset_register_recomputes_from_closure_metadata_only() -> None:
    tracked = load_json(ROOT / "manifests/slice-30-assets.json")
    closure = load_closure(ROOT / "manifests/slice-30-closure.json")
    recomputed = build_asset_register(closure)

    assert tracked == recomputed
    assert validate_asset_register(tracked, closure) == []
    assert len(tracked["assets"]) == EXPECTED_ASSET_COUNT
    assert tracked["counts"] == {
        "assets_in": 201,
        "assets_out": 201,
        "asset_paths_distinct": 201,
        "asset_blob_oids_distinct": 201,
        "gaps": 0,
    }
    assert {asset["sensitivity"] for asset in tracked["assets"]} == {"internal"}
    assert {asset["use_scope"] for asset in tracked["assets"]} == {
        "local_training_and_evaluation_only"
    }


def test_register_preserves_exact_closure_path_and_oid_roster() -> None:
    closure = load_closure()
    register = build_asset_register(closure)
    expected = {
        (item["path"], item["blob_oid"]) for item in closure["shared_closures"][0]["inputs"]
    }
    actual = {(item["path"], item["blob_oid"]) for item in register["assets"]}

    assert len(expected) == len(actual) == EXPECTED_ASSET_COUNT
    assert actual == expected
    assert register["source_revision"] == closure["source_revision"]


def test_closure_mutations_fail_closed() -> None:
    closure = load_closure()
    mutated = deepcopy(closure)
    mutated["shared_closures"][0]["inputs"].pop()
    with pytest.raises(AssetRegisterError, match="exactly 201"):
        build_asset_register(mutated)

    mutated = deepcopy(closure)
    mutated["shared_closures"][0]["inputs"][1]["path"] = mutated["shared_closures"][0]["inputs"][0][
        "path"
    ]
    with pytest.raises(AssetRegisterError, match="not distinct"):
        build_asset_register(mutated)

    mutated = deepcopy(closure)
    mutated["source_revision"] = "0" * 40
    with pytest.raises(AssetRegisterError, match="revision drift"):
        build_asset_register(mutated)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("status", "sealed", "closure status"),
        ("language_version", "0.42", "language version"),
        ("closure_policy", "task_local", "closure policy"),
    ],
)
def test_closure_identity_mutations_fail_closed(field, value, message) -> None:
    closure = load_closure()
    mutated = deepcopy(closure)
    mutated[field] = value

    with pytest.raises(AssetRegisterError, match=message):
        build_asset_register(mutated)


def test_closure_rejects_malformed_input_oid() -> None:
    closure = load_closure()
    mutated = deepcopy(closure)
    mutated["shared_closures"][0]["inputs"][0]["blob_oid"] = "not-an-oid"

    with pytest.raises(AssetRegisterError, match="invalid blob OID"):
        build_asset_register(mutated)


def test_closure_rejects_shared_closure_count_drift() -> None:
    closure = load_closure()
    mutated = deepcopy(closure)
    mutated["shared_closures"].append(deepcopy(mutated["shared_closures"][0]))

    with pytest.raises(AssetRegisterError, match="exactly one shared closure"):
        build_asset_register(mutated)


def test_classification_and_distribution_mutations_are_rejected() -> None:
    register = build_asset_register()
    mutated = deepcopy(register)
    mutated["classification"]["external_distribution"] = "allowed"
    assert any("external distribution" in error for error in validate_asset_register(mutated))

    mutated = deepcopy(register)
    mutated["assets"][0]["sensitivity"] = "external"
    assert any("classification" in error for error in validate_asset_register(mutated))

    mutated = deepcopy(register)
    mutated["counts"]["gaps"] = 1
    assert any(
        "asset denominator" in error or "field drift" in error
        for error in validate_asset_register(mutated)
    )


def test_asset_schema_rejects_distribution_allowance() -> None:
    schema = load_json(ROOT / "schemas/source-asset-register.schema.json")
    register = build_asset_register()
    assert validate_instance(register, schema) == []
    register["classification"]["external_distribution"] = "allowed"

    errors = validate_instance(register, schema)

    assert errors
    assert any("prohibited_pending_O009" in error for error in errors)


def test_asset_schema_requires_direct_classification_on_every_record() -> None:
    schema = load_json(ROOT / "schemas/source-asset-register.schema.json")
    register = build_asset_register()
    del register["assets"][0]["legal_review"]

    errors = validate_instance(register, schema)

    assert any("legal_review" in error and "required" in error for error in errors)


def test_manifest_hash_is_reproducible() -> None:
    first = build_asset_register()
    second = build_asset_register(load_closure())

    assert first["manifest_hash"] == second["manifest_hash"]
    assert first == second
