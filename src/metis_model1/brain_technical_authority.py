"""Private, snapshot-bound catalog technical declarations from the pinned AST.

This is a Brain-owned sidecar, not an extension of upstream semantic Schema2.
Technical declarations do not acquire editorial ``reviewed`` state here. The
consumer must independently bind reviewed semantics and an operator decision.
No I/O, source parsing, domain inference or model execution occurs here.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from typing import Any

from metis_model1.brain_protocol import BrainError, canonical_json, canonical_sha256

TECHNICAL_AUTHORITY_CONTRACT = "metis-brain-tenant-technical-authority/v1"
MAX_TECHNICAL_BYTES = 512 * 1024
MAX_CATALOGS = 64
MAX_FIELDS = 4096
MAX_MEMBERS = 256
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_NAME = re.compile(r"^[A-Za-z_][\w-]*(?:\.[A-Za-z_][\w-]*)*$")
_RAW_KEYS = {"contract_id", "tenant", "catalogs"}
_BOUND_KEYS = {
    *_RAW_KEYS,
    "context_revision",
    "semantic_source_revision",
    "toolchain_binding",
    "sha256",
}
_CATALOG_KEYS = {
    "name",
    "driver",
    "capabilities",
    "fields",
    "id_field",
    "similarity_field",
    "similarity_profiles",
    "projections",
}


def _fail(message: str, *, stale: bool = False) -> None:
    raise BrainError("STALE_CONTEXT" if stale else "RETRIEVAL_INVALID", 409, message)


def _object(value: Any, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        _fail(f"technical {label} field roster is invalid")
    return value


def _text(value: Any, label: str, *, name: bool = False) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 256
        or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)
        or (name and _NAME.fullmatch(value) is None)
    ):
        _fail(f"technical {label} is invalid")
    return value


def _array(value: Any, label: str, *, maximum: int = MAX_MEMBERS) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        _fail(f"technical {label} roster is invalid")
    return value


def _names(value: Any, label: str, *, minimum: int = 0) -> list[str]:
    values = _array(value, label)
    result = [_text(item, label, name=True) for item in values]
    if len(result) < minimum or len(set(result)) != len(result):
        _fail(f"technical {label} roster is duplicated or empty")
    return result


def _hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        _fail(f"technical {label} is invalid")
    return value


def _field_roster(fields: Any, *, flattened: bool) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    def walk(items: Any, parent: str = "", depth: int = 0) -> None:
        if depth > 16:
            _fail("technical field nesting exceeds the bound")
        for raw in _array(items, "fields", maximum=MAX_FIELDS):
            if not isinstance(raw, Mapping):
                _fail("technical field is invalid")
            if flattened:
                _object(raw, {"name", "type", "modifiers"}, "field")
            name = _text(raw.get("name"), "field name", name=True)
            path = f"{parent}.{name}" if parent else name
            field_type = _text(raw.get("type"), "field type")
            modifiers = _names(raw.get("modifiers"), "field modifiers")
            if not set(modifiers).issubset({"multi", "ordered"}):
                _fail("technical field modifiers are invalid")
            result.append({"name": path, "type": field_type, "modifiers": modifiers})
            if len(result) > MAX_FIELDS:
                _fail("technical field roster exceeds the bound")
            if not flattened and "fields" in raw:
                walk(raw["fields"], path, depth + 1)

    walk(fields)
    if len({item["name"] for item in result}) != len(result):
        _fail("technical field roster contains duplicate paths")
    return result


def _raw_authority(raw: Any, projection: Mapping[str, Any] | None) -> dict[str, Any]:
    _object(raw, _RAW_KEYS, "authority")
    if raw["contract_id"] != TECHNICAL_AUTHORITY_CONTRACT:
        _fail("technical authority contract is invalid")
    _text(raw["tenant"], "tenant")
    catalogs = _array(raw["catalogs"], "catalogs", maximum=MAX_CATALOGS)
    catalog_names: set[str] = set()
    fields_total = 0
    for catalog in catalogs:
        _object(catalog, _CATALOG_KEYS, "catalog")
        name = _text(catalog["name"], "catalog name", name=True)
        if name in catalog_names:
            _fail("technical catalog roster contains duplicates")
        catalog_names.add(name)
        _text(catalog["driver"], "catalog driver", name=True)
        _names(catalog["capabilities"], "driver capabilities")
        fields = _field_roster(catalog["fields"], flattened=True)
        fields_total += len(fields)
        if fields_total > MAX_FIELDS:
            _fail("technical total field roster exceeds the bound")
        field_names = {field["name"] for field in fields}
        for role in ("id_field", "similarity_field"):
            value = catalog[role]
            if value is not None and _text(value, role, name=True) not in field_names:
                _fail(f"technical {role} is outside its catalog")
        for roster, keys in (
            ("similarity_profiles", {"name", "fields", "binding"}),
            ("projections", {"name", "fields"}),
        ):
            names: set[str] = set()
            for member in _array(catalog[roster], roster):
                _object(member, keys, roster)
                member_name = _text(member["name"], f"{roster} name", name=True)
                if "." in member_name or member_name in names:
                    _fail(f"technical {roster} identity is invalid")
                names.add(member_name)
                selected = _names(
                    member["fields"],
                    f"{roster} fields",
                    minimum=int(roster == "similarity_profiles"),
                )
                if not set(selected).issubset(field_names):
                    _fail(f"technical {roster} fields are outside their catalog")
                if roster == "similarity_profiles":
                    _text(member["binding"], "similarity binding", name=True)
    if projection is not None:
        if not isinstance(projection, Mapping) or projection.get("tenant") != raw["tenant"]:
            _fail("technical and semantic tenants differ", stale=True)
        expected: dict[str, tuple[str, list[dict[str, Any]]]] = {}
        for catalog in _array(
            projection.get("catalogs"), "semantic catalogs", maximum=MAX_CATALOGS
        ):
            if not isinstance(catalog, Mapping):
                _fail("technical semantic catalog is invalid")
            name = _text(catalog.get("name"), "semantic catalog name", name=True)
            if name in expected:
                _fail("technical semantic catalog roster contains duplicates")
            expected[name] = (
                _text(catalog.get("driver"), "semantic driver", name=True),
                _field_roster(catalog.get("fields"), flattened=False),
            )
        if catalog_names != set(expected):
            _fail("technical and semantic catalog rosters differ")
        for catalog in catalogs:
            if (catalog["driver"], catalog["fields"]) != expected[catalog["name"]]:
                _fail("technical and semantic field/driver rosters differ")
    try:
        if len(canonical_json(raw)) > MAX_TECHNICAL_BYTES:
            _fail("technical authority exceeds its byte bound")
    except (TypeError, ValueError, RecursionError) as error:
        raise BrainError("RETRIEVAL_INVALID", 409, "technical authority is not JSON") from error
    return copy.deepcopy(dict(raw))


def bind_technical_authority(
    raw: Any,
    *,
    projection: Mapping[str, Any],
    context_revision: str,
    semantic_source_revision: str,
    toolchain_binding: str,
    tenant_id: str,
) -> dict[str, Any]:
    """Validate the pinned runner sidecar and seal its exact snapshot binding."""

    result = _raw_authority(raw, projection)
    if result["tenant"] != tenant_id:
        _fail("technical authority belongs to another tenant", stale=True)
    result.update(
        context_revision=_hash(context_revision, "context revision"),
        semantic_source_revision=_hash(semantic_source_revision, "semantic revision"),
        toolchain_binding=_hash(toolchain_binding, "toolchain binding"),
    )
    result["sha256"] = canonical_sha256(result)
    return result


def validate_technical_authority(
    value: Any,
    *,
    context_revision: str,
    semantic_source_revision: str,
    toolchain_binding: str,
    tenant_id: str,
    projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Revalidate a private sealed authority, never treating its hash as trust."""

    _object(value, _BOUND_KEYS, "bound authority")
    raw = _raw_authority({key: value[key] for key in _RAW_KEYS}, projection)
    expected = {
        "context_revision": _hash(context_revision, "context revision"),
        "semantic_source_revision": _hash(semantic_source_revision, "semantic revision"),
        "toolchain_binding": _hash(toolchain_binding, "toolchain binding"),
    }
    if raw["tenant"] != tenant_id or any(value[key] != item for key, item in expected.items()):
        _fail("technical authority snapshot binding differs", stale=True)
    result = {**raw, **expected}
    if _hash(value["sha256"], "authority digest") != canonical_sha256(result):
        _fail("technical authority digest differs")
    result["sha256"] = value["sha256"]
    return result


__all__ = [
    "TECHNICAL_AUTHORITY_CONTRACT",
    "bind_technical_authority",
    "validate_technical_authority",
]
