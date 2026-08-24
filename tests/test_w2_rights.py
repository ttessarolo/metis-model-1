from __future__ import annotations

from copy import deepcopy
from pathlib import Path

from metis_model1.contracts import load_json, validate_instance
from metis_model1.w2_rights import (
    EXPECTED_ASSET_COUNT,
    EXPECTED_ASSET_REGISTER_FILE_SHA256,
    asset_register_file_sha256,
    build_rights_dossier,
    dossier_hash,
    load_asset_register,
    validate_rights_dossier,
)

ROOT = Path(__file__).parents[1]


def test_tracked_dossier_is_deterministic_and_exact() -> None:
    tracked = load_json(ROOT / "manifests/w2-rights-dossier-v1.json")
    register = load_asset_register()
    assert tracked == build_rights_dossier(register)
    assert validate_rights_dossier(tracked, register) == []
    assert tracked["source_revision"] == register["source_revision"]
    assert tracked["asset_register_manifest_hash"] == register["manifest_hash"]
    assert tracked["asset_register_file_sha256"] == EXPECTED_ASSET_REGISTER_FILE_SHA256
    assert asset_register_file_sha256() == EXPECTED_ASSET_REGISTER_FILE_SHA256
    assert tracked["counts"] == {
        "assets_in": 201,
        "assets_out": 201,
        "asset_paths_distinct": 201,
        "asset_blob_oids_distinct": 201,
        "gaps": 0,
    }
    assert tracked["summary"] == {"reviewed": 0, "approved": 0, "excluded": 0, "pending": 201}
    assert len(tracked["assets"]) == EXPECTED_ASSET_COUNT
    assert all(item["status"] == "needs_review" for item in tracked["assets"])
    assert all(item["file_sha256"] is None for item in tracked["assets"])


def test_schema_accepts_pending_dossier() -> None:
    schema = load_json(ROOT / "schemas/w2-rights-dossier.schema.json")
    dossier = build_rights_dossier()
    assert validate_instance(dossier, schema) == []


def test_missing_asset_fails_closed() -> None:
    register = deepcopy(load_asset_register())
    register["assets"].pop()
    errors = validate_rights_dossier(build_rights_dossier(), register)
    assert any("asset register contract" in error for error in errors)


def test_duplicate_path_and_oid_fail_closed() -> None:
    register = deepcopy(load_asset_register())
    register["assets"][1]["path"] = register["assets"][0]["path"]
    errors = validate_rights_dossier(build_rights_dossier(), register)
    assert any("asset register contract" in error for error in errors)

    register = deepcopy(load_asset_register())
    register["assets"][1]["blob_oid"] = register["assets"][0]["blob_oid"]
    errors = validate_rights_dossier(build_rights_dossier(), register)
    assert any("asset register contract" in error for error in errors)


def test_source_revision_and_register_hash_are_bound() -> None:
    dossier = build_rights_dossier()
    mutated = deepcopy(dossier)
    mutated["source_revision"] = "0" * 40
    assert any("source_revision" in error for error in validate_rights_dossier(mutated))

    mutated = deepcopy(dossier)
    mutated["asset_register_manifest_hash"] = "sha256:" + "0" * 64
    assert any(
        "asset_register_manifest_hash" in error for error in validate_rights_dossier(mutated)
    )

    register = deepcopy(load_asset_register())
    register["assets"][0]["path"] += ".mutated"
    assert any(
        "asset register contract" in error for error in validate_rights_dossier(dossier, register)
    )


def test_asset_register_file_hash_mutation_is_rejected() -> None:
    dossier = build_rights_dossier()
    mutated = deepcopy(dossier)
    mutated["asset_register_file_sha256"] = "sha256:" + "0" * 64
    assert any("asset_register_file_sha256" in error for error in validate_rights_dossier(mutated))


def test_default_approval_and_evidence_are_not_invented() -> None:
    dossier = build_rights_dossier()
    for item in dossier["assets"]:
        assert item["license"] is None
        assert item["rightsholder"] is None
        assert item["reviewer"] is None
        assert item["reviewed_at"] is None
        assert item["expiry"] is None
        assert item["evidence_ref"] is None
        assert item["evidence_sha256"] is None

    schema = load_json(ROOT / "schemas/w2-rights-dossier.schema.json")
    mutated = deepcopy(dossier)
    mutated["assets"][0]["status"] = "approved"
    assert validate_instance(mutated, schema)


def test_dossier_hash_and_roster_mutations_are_rejected() -> None:
    dossier = build_rights_dossier()
    mutated = deepcopy(dossier)
    mutated["assets"][0]["blob_oid"] = "0" * 40
    assert any("assets" in error for error in validate_rights_dossier(mutated))

    mutated = deepcopy(dossier)
    mutated["dossier_sha256"] = "sha256:" + "0" * 64
    assert any("dossier_sha256" in error for error in validate_rights_dossier(mutated))


def test_recomputed_hash_does_not_authorise_identity_mutations() -> None:
    dossier = build_rights_dossier()
    for field, value in (("manifest_id", "w2/other"), ("schema_version", 99)):
        mutated = deepcopy(dossier)
        mutated[field] = value
        mutated["dossier_sha256"] = dossier_hash(mutated)
        assert any(
            f"dossier field drift: {field}" in error for error in validate_rights_dossier(mutated)
        )


def test_non_hex_oid_is_rejected_explicitly() -> None:
    dossier = build_rights_dossier()
    mutated = deepcopy(dossier)
    mutated["assets"][0]["blob_oid"] = "g" * 40
    assert any("dossier field drift: assets" in error for error in validate_rights_dossier(mutated))
