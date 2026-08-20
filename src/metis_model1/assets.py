"""Fail-closed local-use classification for the pinned Metis build inputs.

This module consumes only the tracked dependency-closure metadata.  It never
opens a Metis source file and never needs the Metis checkout.  The resulting
register is an operational classification for the explicitly authorised local
training/evaluation wave; it is not a legal opinion.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from metis_model1.provenance import canonical_json_hash, normalize_json

ASSET_MANIFEST_ID = "benchmark/families-v1/slice-30-assets"
CLOSURE_MANIFEST_ID = "benchmark/families-v1/slice-30-closure"
EXPECTED_ASSET_COUNT = 201
EXPECTED_SOURCE_REVISION = "a2dde2b191f6b78c2003d74875560da782470968"
EXPECTED_LANGUAGE_VERSION = "0.43"
EXPECTED_CLOSURE_POLICY = "whole_program_build_input"
EXPECTED_CLASSIFICATION = {
    "sensitivity": "internal",
    "use_scope": "local_training_and_evaluation_only",
    "external_distribution": "prohibited_pending_O009",
    "authorization_basis": "user_explicit_local_training_mandate_2026-08-20",
    "legal_review": "not_performed",
}


class AssetRegisterError(ValueError):
    """Raised when closure metadata or an asset register fails closed."""


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _closure_path() -> Path:
    return _repository_root() / "manifests" / "slice-30-closure.json"


def load_closure(path: Path | None = None) -> dict[str, Any]:
    """Load closure JSON metadata without reading any source payload."""

    candidate = _closure_path() if path is None else path
    import json

    with candidate.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise AssetRegisterError("closure manifest must be an object")
    return value


def _closure_inputs(closure: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return the exact 201 path/OID records after validating closure identity."""

    if closure.get("schema_version") != 1:
        raise AssetRegisterError("closure schema version drift")
    if closure.get("manifest_id") != CLOSURE_MANIFEST_ID:
        raise AssetRegisterError("closure manifest identity drift")
    if closure.get("status") != "computed_not_sealed":
        raise AssetRegisterError("closure status must remain computed_not_sealed")
    if closure.get("source_revision") != EXPECTED_SOURCE_REVISION:
        raise AssetRegisterError("Metis source revision drift")
    if closure.get("language_version") != EXPECTED_LANGUAGE_VERSION:
        raise AssetRegisterError("Metis language version drift")
    if closure.get("closure_policy") != EXPECTED_CLOSURE_POLICY:
        raise AssetRegisterError("closure policy drift")
    counts = closure.get("counts")
    if not isinstance(counts, Mapping):
        raise AssetRegisterError("closure counts are missing")
    expected_counts = {
        "sources_in": EXPECTED_ASSET_COUNT,
        "sources_out": EXPECTED_ASSET_COUNT,
        "source_paths_distinct": EXPECTED_ASSET_COUNT,
        "source_blob_oids_distinct": EXPECTED_ASSET_COUNT,
        "gaps": 0,
    }
    for key, expected in expected_counts.items():
        if counts.get(key) != expected:
            raise AssetRegisterError(f"closure count drift: {key}")
    closures = closure.get("shared_closures")
    if not isinstance(closures, list) or len(closures) != 1:
        raise AssetRegisterError("closure must contain exactly one shared closure")
    shared = closures[0]
    if not isinstance(shared, Mapping) or shared.get("closure_id") != "whole-tenant":
        raise AssetRegisterError("shared closure identity drift")
    inputs = shared.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != EXPECTED_ASSET_COUNT:
        raise AssetRegisterError("closure inputs are not exactly 201 records")
    normalised: list[dict[str, str]] = []
    for index, item in enumerate(inputs):
        if not isinstance(item, Mapping):
            raise AssetRegisterError(f"closure input {index} is not an object")
        path = item.get("path")
        oid = item.get("blob_oid")
        if not isinstance(path, str) or not path:
            raise AssetRegisterError(f"closure input {index} has no path")
        if (
            not isinstance(oid, str)
            or len(oid) != 40
            or any(c not in "0123456789abcdef" for c in oid)
        ):
            raise AssetRegisterError(f"closure input {path!r} has invalid blob OID")
        normalised.append({"path": path, "blob_oid": oid})
    paths = [item["path"] for item in normalised]
    oids = [item["blob_oid"] for item in normalised]
    if len(set(paths)) != EXPECTED_ASSET_COUNT:
        raise AssetRegisterError("closure paths are not distinct")
    if len(set(oids)) != EXPECTED_ASSET_COUNT:
        raise AssetRegisterError("closure blob OIDs are not distinct")
    return sorted(normalised, key=lambda item: item["path"])


def _body(register: Mapping[str, Any]) -> dict[str, Any]:
    """Return the hash envelope, excluding its self-referential digest."""

    return {key: value for key, value in register.items() if key != "manifest_hash"}


def manifest_hash(register: Mapping[str, Any]) -> str:
    """Compute the deterministic canonical hash of a register body."""

    try:
        return "sha256:" + canonical_json_hash(normalize_json(_body(register)))
    except (TypeError, ValueError) as error:
        raise AssetRegisterError(f"register cannot be canonically hashed: {error}") from error


def build_asset_register(closure: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build the local-use register from closure metadata only."""

    source = load_closure() if closure is None else closure
    inputs = _closure_inputs(source)
    classification = dict(EXPECTED_CLASSIFICATION)
    register: dict[str, Any] = {
        "schema_version": 1,
        "manifest_id": ASSET_MANIFEST_ID,
        "status": "classified_local_only",
        "source_revision": EXPECTED_SOURCE_REVISION,
        "language_version": EXPECTED_LANGUAGE_VERSION,
        "closure_manifest_id": CLOSURE_MANIFEST_ID,
        "closure_policy": EXPECTED_CLOSURE_POLICY,
        "classification": classification,
        "classification_id": "internal_local_training_only_pending_O009",
        "counts": {
            "assets_in": EXPECTED_ASSET_COUNT,
            "assets_out": len(inputs),
            "asset_paths_distinct": len({item["path"] for item in inputs}),
            "asset_blob_oids_distinct": len({item["blob_oid"] for item in inputs}),
            "gaps": 0,
        },
        "assets": [{**item, **classification} for item in inputs],
    }
    register["manifest_hash"] = manifest_hash(register)
    return register


def validate_asset_register(
    register: Mapping[str, Any], closure: Mapping[str, Any] | None = None
) -> list[str]:
    """Return all operational, identity and denominator violations."""

    errors: list[str] = []
    try:
        expected = build_asset_register(load_closure() if closure is None else closure)
    except AssetRegisterError as error:
        return [str(error)]
    if dict(register) != expected:
        if register.get("manifest_hash") != expected["manifest_hash"]:
            errors.append("manifest_hash is not deterministic")
        if register.get("assets") != expected["assets"]:
            errors.append("asset path/OID or classification records drifted")
        for field in (
            "manifest_id",
            "source_revision",
            "language_version",
            "closure_manifest_id",
            "closure_policy",
            "classification",
            "counts",
            "status",
        ):
            if register.get(field) != expected[field]:
                errors.append(f"register field drift: {field}")
    try:
        if register.get("manifest_hash") != manifest_hash(register):
            errors.append("manifest_hash does not match register body")
    except AssetRegisterError as error:
        errors.append(str(error))
    classification = register.get("classification")
    if classification != EXPECTED_CLASSIFICATION:
        errors.append("classification is not the authorised local-only policy")
    if (
        isinstance(classification, Mapping)
        and classification.get("external_distribution") != "prohibited_pending_O009"
    ):
        errors.append("external distribution must remain prohibited pending O009")
    counts = register.get("counts")
    if not isinstance(counts, Mapping) or counts.get("assets_in") != EXPECTED_ASSET_COUNT:
        errors.append("asset denominator is not 201")
    if isinstance(register.get("assets"), list):
        assets = register["assets"]
        if len(assets) != EXPECTED_ASSET_COUNT:
            errors.append("asset output denominator is not 201")
        for index, asset in enumerate(assets):
            if not isinstance(asset, Mapping) or any(
                asset.get(key) != value for key, value in EXPECTED_CLASSIFICATION.items()
            ):
                errors.append(f"asset {index} classification drift")
    return sorted(set(errors))
