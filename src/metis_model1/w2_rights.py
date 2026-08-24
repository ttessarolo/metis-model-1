"""Deterministic, evidence-only rights dossier for the W2 asset roster.

The dossier deliberately does not inspect source payloads or infer a licence or
rightsholder.  It binds the pending review records to the pinned source and
asset-register identities so that a later opaque evidence package cannot be
silently applied to a different corpus.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from metis_model1.assets import validate_asset_register
from metis_model1.provenance import canonical_json_hash, normalize_json

EXPECTED_SOURCE_REVISION = "a2dde2b191f6b78c2003d74875560da782470968"
EXPECTED_ASSET_COUNT = 201
EXPECTED_ASSET_REGISTER_FILE_SHA256 = (
    "sha256:1526f177989d6c54095542fb7488789bffe88f0b529750b3bc66e95ef1c8b68b"
)
DOSSIER_ID = "w2/rights-dossier-v1"
STATUS = "review_required_evidence_only"
PENDING_STATUS = "needs_review"
_NULL_EVIDENCE = {
    "reviewer": None,
    "reviewed_at": None,
    "expiry": None,
    "evidence_ref": None,
    "evidence_sha256": None,
}


class RightsDossierError(ValueError):
    """Raised when the W2 dossier cannot be bound to its exact input roster."""


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise RightsDossierError(f"{path.name} must contain an object")
    return value


def load_asset_register(path: Path | None = None) -> dict[str, Any]:
    return _load_json(path or (_root() / "manifests/slice-30-assets.json"))


def asset_register_file_sha256(path: Path | None = None) -> str:
    """Return the byte hash of the tracked asset-register JSON file."""

    candidate = path or (_root() / "manifests/slice-30-assets.json")
    import hashlib

    return "sha256:" + hashlib.sha256(candidate.read_bytes()).hexdigest()


def _body(dossier: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in dossier.items() if key != "dossier_sha256"}


def dossier_hash(dossier: Mapping[str, Any]) -> str:
    try:
        return "sha256:" + canonical_json_hash(normalize_json(_body(dossier)))
    except (TypeError, ValueError) as error:
        raise RightsDossierError(f"dossier cannot be canonically hashed: {error}") from error


def _asset_roster(register: Mapping[str, Any]) -> list[dict[str, str]]:
    contract_errors = validate_asset_register(register)
    if contract_errors:
        raise RightsDossierError("asset register contract: " + "; ".join(contract_errors))
    if register.get("source_revision") != EXPECTED_SOURCE_REVISION:
        raise RightsDossierError("asset register source revision drift")
    manifest_hash = register.get("manifest_hash")
    if not isinstance(manifest_hash, str) or not manifest_hash.startswith("sha256:"):
        raise RightsDossierError("asset register manifest_hash is missing")
    assets = register.get("assets")
    if not isinstance(assets, list) or len(assets) != EXPECTED_ASSET_COUNT:
        raise RightsDossierError("asset register roster is not exactly 201 records")
    roster: list[dict[str, str]] = []
    for index, asset in enumerate(assets):
        if not isinstance(asset, Mapping):
            raise RightsDossierError(f"asset {index} is not an object")
        path, oid = asset.get("path"), asset.get("blob_oid")
        if (
            not isinstance(path, str)
            or not path
            or not isinstance(oid, str)
            or len(oid) != 40
            or any(char not in "0123456789abcdef" for char in oid)
        ):
            raise RightsDossierError(f"asset {index} has invalid path/OID")
        roster.append({"path": path, "blob_oid": oid})
    if len({item["path"] for item in roster}) != EXPECTED_ASSET_COUNT:
        raise RightsDossierError("asset paths are not distinct")
    if len({item["blob_oid"] for item in roster}) != EXPECTED_ASSET_COUNT:
        raise RightsDossierError("asset OIDs are not distinct")
    return sorted(roster, key=lambda item: item["path"])


def build_rights_dossier(register: Mapping[str, Any] | None = None) -> dict[str, Any]:
    source = load_asset_register() if register is None else register
    roster = _asset_roster(source)
    entries = [
        {
            **item,
            "file_sha256": None,
            "status": PENDING_STATUS,
            "license": None,
            "rightsholder": None,
            **_NULL_EVIDENCE,
        }
        for item in roster
    ]
    dossier: dict[str, Any] = {
        "schema_version": 1,
        "manifest_id": DOSSIER_ID,
        "status": STATUS,
        "source_revision": EXPECTED_SOURCE_REVISION,
        "asset_register_manifest_hash": source["manifest_hash"],
        "asset_register_file_sha256": asset_register_file_sha256(),
        "counts": {
            "assets_in": 201,
            "assets_out": 201,
            "asset_paths_distinct": 201,
            "asset_blob_oids_distinct": 201,
            "gaps": 0,
        },
        "summary": {"reviewed": 0, "approved": 0, "excluded": 0, "pending": 201},
        "policy": {
            "evidence_mode": "opaque_hash_only",
            "required_permissions": ["training", "evaluation", "derivatives", "adapters"],
            "double_review_required": True,
            "whole_tenant_closure_blocked_by": ["needs_review", "excluded"],
        },
        "assets": entries,
    }
    dossier["dossier_sha256"] = dossier_hash(dossier)
    return dossier


def validate_rights_dossier(
    dossier: Mapping[str, Any], register: Mapping[str, Any] | None = None
) -> list[str]:
    try:
        expected = build_rights_dossier(load_asset_register() if register is None else register)
    except RightsDossierError as error:
        return [str(error)]
    errors: list[str] = []
    if dict(dossier) != expected:
        for key in expected:
            if key == "dossier_sha256":
                continue
            if dossier.get(key) != expected[key]:
                errors.append(f"dossier field drift: {key}")
    try:
        if dossier.get("dossier_sha256") != dossier_hash(dossier):
            errors.append("dossier_sha256 is not deterministic")
    except RightsDossierError as error:
        errors.append(str(error))
    return sorted(set(errors))


__all__ = [
    "RightsDossierError",
    "build_rights_dossier",
    "dossier_hash",
    "asset_register_file_sha256",
    "load_asset_register",
    "validate_rights_dossier",
]
