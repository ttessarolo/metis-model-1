"""Deterministic, payload-free census of a validated catalog schema-2 projection.

The projection is an input contract owned by the catalog toolchain.  This module
does not execute a catalog command and does not retrieve live values.  It walks
the already validated projection, keeps the exact in-memory target roster for a
later crosswalk, and emits a self-hashed receipt containing only structure.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from metis_model1.provenance import canonical_json_hash
from metis_model1.video_catalog_projection import PROJECTION_CONTRACT

HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
OPAQUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
DOMAIN_KINDS = frozenset({"none", "inline", "enum", "list", "open"})
DOMAIN_NATURES = frozenset({"reflected", "editorial"})
STATES = frozenset({"unannotated", "draft", "reviewed"})
NODE_KINDS = frozenset({"catalog", "field", "value"})


class LocalCensusError(ValueError):
    """Raised when a schema-2 projection is not a coherent census input."""


def _hash(value: Any) -> str:
    return "sha256:" + canonical_json_hash(value)


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and HASH_RE.fullmatch(value) is not None


def _string(value: Any, label: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise LocalCensusError(f"{label} must be a bounded non-empty string")
    if any(ord(char) < 0x20 for char in value):
        raise LocalCensusError(f"{label} contains a control character")
    return value


def _opaque(value: Any, label: str) -> str:
    value = _string(value, label, maximum=128)
    if OPAQUE_RE.fullmatch(value) is None:
        raise LocalCensusError(f"{label} is not opaque")
    return value


def _file(value: Any, label: str) -> str:
    value = _string(value, label, maximum=512)
    # Schema-2 permits a relative POSIX path (the crosswalk's older opaque
    # locator is narrower; that incompatibility is handled at its boundary).
    path = PurePosixPath(value)
    if (
        "\\" in value
        or path.is_absolute()
        or path.as_posix() != value
        or value in {".", ".."}
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise LocalCensusError(f"{label} must be a relative POSIX file reference")
    return value


def _line(node: Mapping[str, Any], label: str) -> int:
    candidates: list[Any] = [node.get("line")]
    for key in ("location", "source"):
        nested = node.get(key)
        if isinstance(nested, Mapping):
            candidates.append(nested.get("line"))
    semantic = node.get("semantic")
    if isinstance(semantic, Mapping):
        at = semantic.get("at")
        if isinstance(at, Mapping):
            candidates.append(at.get("line"))
    values = [value for value in candidates if value is not None]
    if (
        not values
        or any(type(value) is not int for value in values)
        or len(set(values)) != 1
        or values[0] < 1
    ):
        raise LocalCensusError(f"{label} must contain exactly one positive source line")
    return values[0]


def _locator(file_ref: str, line: int) -> str:
    value = f"{file_ref}:{line}"
    if line < 1 or not file_ref:
        raise LocalCensusError("source locator is invalid")
    return value


def _state(node: Mapping[str, Any], label: str) -> str:
    candidates: list[Any] = []
    if "state" in node:
        candidates.append(node["state"])
    if "review_state" in node:
        candidates.append(node["review_state"])
    semantic = node.get("semantic")
    if isinstance(semantic, Mapping) and "state" in semantic:
        candidates.append(semantic["state"])
    if (
        not candidates
        or any(not isinstance(value, str) for value in candidates)
        or len(set(candidates)) != 1
    ):
        raise LocalCensusError(f"{label} state and review_state disagree or are missing")
    state = candidates[0]
    if state not in STATES:
        raise LocalCensusError(f"{label} has an invalid semantic state")
    return state


def _node_file(node: Mapping[str, Any], label: str, fallback: str | None = None) -> str:
    """Resolve the source file while preserving schema-2 semantic locations."""

    direct: list[Any] = []
    if "file" in node:
        direct.append(node["file"])
    for key in ("location", "source"):
        nested = node.get(key)
        if isinstance(nested, Mapping) and "file" in nested:
            direct.append(nested["file"])
    if direct and (any(not isinstance(value, str) for value in direct) or len(set(direct)) != 1):
        raise LocalCensusError(f"{label} has incoherent source files")
    semantic_file: Any = None
    semantic = node.get("semantic")
    if isinstance(semantic, Mapping):
        at = semantic.get("at")
        if isinstance(at, Mapping):
            semantic_file = at.get("file")
    # A schema-2 field/catalog carries its grammar file separately from the
    # semantic annotation source.  When the semantic source has the line,
    # that source is the canonical file:line locator.
    if semantic_file is not None and not any(
        node.get(key) is not None for key in ("line", "location", "source")
    ):
        return _file(semantic_file, f"{label}.semantic.at.file")
    if direct:
        return _file(direct[0], f"{label}.file")
    if semantic_file is not None:
        return _file(semantic_file, f"{label}.semantic.at.file")
    if fallback is not None:
        return _file(fallback, f"{label}.file")
    raise LocalCensusError(f"{label}.file is missing")


def _domain(node: Mapping[str, Any], label: str) -> tuple[dict[str, Any], list[Any]]:
    raw = node.get("domain")
    if not isinstance(raw, Mapping):
        raise LocalCensusError(f"{label}.domain is required")
    allowed = {"kind", "size", "nature", "values"}
    if set(raw) - allowed or "kind" not in raw:
        raise LocalCensusError(f"{label}.domain has unknown or missing fields")
    kind = raw["kind"]
    if not isinstance(kind, str) or kind not in DOMAIN_KINDS:
        raise LocalCensusError(f"{label}.domain.kind is invalid")
    size = raw.get("size")
    nature = raw.get("nature")
    if kind in {"none", "open"}:
        if size is not None or nature is not None or "values" in raw:
            raise LocalCensusError(f"{label}.domain {kind} must not materialize a domain")
    else:
        if type(size) is not int or size < 0:
            raise LocalCensusError(f"{label}.domain.size is required for {kind}")
        if nature is not None and (not isinstance(nature, str) or nature not in DOMAIN_NATURES):
            raise LocalCensusError(f"{label}.domain.nature is invalid for {kind}")
    values = raw.get("values", [])
    if not isinstance(values, list):
        raise LocalCensusError(f"{label}.domain.values must be an array")
    if kind in {"none", "open"} and values:
        raise LocalCensusError(f"{label}.domain {kind} cannot contain values")
    if kind in {"inline", "enum", "list"} and size != len(values):
        raise LocalCensusError(f"{label}.domain normalized finite size does not match values")
    material = {"kind": kind}
    if size is not None:
        material["size"] = size
    if nature is not None:
        material["nature"] = nature
    return material, values


def _value_literal(value: Mapping[str, Any], label: str) -> str:
    if set(value) - {
        "literal",
        "line",
        "location",
        "source",
        "state",
        "review_state",
        "means",
        "aka",
        "semantic",
    }:
        raise LocalCensusError(f"{label} has unknown fields")
    if "literal" not in value:
        raise LocalCensusError(f"{label}.literal is missing")
    literal = value["literal"]
    if not isinstance(literal, str) or any(ord(char) < 0x20 for char in literal):
        raise LocalCensusError(f"{label}.literal is invalid")
    return literal


def _catalogs(projection: Mapping[str, Any]) -> list[Any]:
    schema = projection.get("schema", projection.get("schema_version"))
    if type(schema) is not int or schema != 2:
        raise LocalCensusError("projection schema must be integer 2")
    if projection.get("projection_contract") != PROJECTION_CONTRACT:
        raise LocalCensusError("projection must be the normalized describe-plus-values contract")
    catalogs = projection.get("catalogs")
    if not isinstance(catalogs, list) or not catalogs:
        raise LocalCensusError("projection catalogs must be a non-empty array")
    return catalogs


def _entry(
    *,
    node_kind: str,
    catalog: str,
    field: str | None,
    source_locator: str,
    state: str,
    domain: Mapping[str, Any],
    literal: str | None = None,
) -> dict[str, Any]:
    locator = _hash(
        {
            "node_kind": node_kind,
            "catalog": catalog,
            "field": field,
            "literal": literal,
            "source_locator": source_locator,
        }
    )
    result: dict[str, Any] = {
        "node_kind": node_kind,
        "catalog": catalog,
        "field": field,
        "locator": locator,
        "source_locator": source_locator,
        "state": state,
        "domain": dict(domain),
    }
    if node_kind == "value":
        result["literal"] = literal
    return result


def _walk_projection(projection: Mapping[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    catalog_names: set[str] = set()
    locators: set[str] = set()
    field_names: set[tuple[str, str]] = set()
    value_keys: set[tuple[str, str, str]] = set()

    for catalog_index, raw_catalog in enumerate(_catalogs(projection)):
        if not isinstance(raw_catalog, Mapping):
            raise LocalCensusError(f"catalogs[{catalog_index}] is not an object")
        name = _opaque(raw_catalog.get("name"), f"catalogs[{catalog_index}].name")
        if name in catalog_names:
            raise LocalCensusError("duplicate catalog name")
        catalog_names.add(name)
        file_ref = _node_file(raw_catalog, f"catalog {name}")
        catalog_source_locator = _locator(file_ref, _line(raw_catalog, f"catalog {name}"))
        state = _state(raw_catalog, f"catalog {name}")
        domain = {"kind": "none"}
        catalog_entry = _entry(
            node_kind="catalog",
            catalog=name,
            field=None,
            source_locator=catalog_source_locator,
            state=state,
            domain=domain,
        )
        if catalog_entry["locator"] in locators:
            raise LocalCensusError("duplicate node locator")
        locators.add(catalog_entry["locator"])
        entries.append(catalog_entry)

        fields = raw_catalog.get("fields")
        if not isinstance(fields, list):
            raise LocalCensusError(f"catalog {name}.fields must be an array")

        def walk_fields(
            items: list[Any],
            parent_path: str | None,
            *,
            catalog_name: str = name,
            catalog_file: str = file_ref,
        ) -> None:
            direct_names: set[str] = set()
            for field_index, raw_field in enumerate(items):
                if not isinstance(raw_field, Mapping):
                    raise LocalCensusError(
                        f"catalog {catalog_name} field[{field_index}] is not an object"
                    )
                field_name = _opaque(raw_field.get("name"), f"catalog {catalog_name} field name")
                if field_name in direct_names:
                    raise LocalCensusError(f"duplicate field name {field_name}")
                direct_names.add(field_name)
                field_path = field_name if parent_path is None else f"{parent_path}.{field_name}"
                if OPAQUE_RE.fullmatch(field_path) is None:
                    raise LocalCensusError(f"field path {field_path} is not opaque")
                key = (catalog_name, field_path)
                if key in field_names:
                    raise LocalCensusError("duplicate field path")
                field_names.add(key)
                field_file = _node_file(raw_field, f"field {field_path}", catalog_file)
                source_locator = _locator(field_file, _line(raw_field, f"field {field_path}"))
                domain, raw_values = _domain(raw_field, f"field {field_path}")
                field_entry = _entry(
                    node_kind="field",
                    catalog=catalog_name,
                    field=field_path,
                    source_locator=source_locator,
                    state=_state(raw_field, f"field {field_path}"),
                    domain=domain,
                )
                if field_entry["locator"] in locators:
                    raise LocalCensusError("duplicate node locator")
                locators.add(field_entry["locator"])
                entries.append(field_entry)
                local_literals: set[str] = set()
                for value_index, raw_value in enumerate(raw_values):
                    if not isinstance(raw_value, Mapping):
                        raise LocalCensusError(
                            f"field {field_path} value[{value_index}] is not an object"
                        )
                    literal = _value_literal(raw_value, f"field {field_path} value[{value_index}]")
                    if (
                        literal in local_literals
                        or (
                            catalog_name,
                            field_path,
                            literal,
                        )
                        in value_keys
                    ):
                        raise LocalCensusError(f"duplicate value literal in {field_path}")
                    local_literals.add(literal)
                    value_keys.add((catalog_name, field_path, literal))
                    value_file = _node_file(
                        raw_value, f"value {field_path}[{value_index}]", field_file
                    )
                    value_source_locator = _locator(
                        value_file, _line(raw_value, f"value {field_path}[{value_index}]")
                    )
                    value_entry = _entry(
                        node_kind="value",
                        catalog=catalog_name,
                        field=field_path,
                        source_locator=value_source_locator,
                        state=_state(raw_value, f"value {field_path}[{value_index}]"),
                        domain=domain,
                        literal=literal,
                    )
                    if value_entry["locator"] in locators:
                        raise LocalCensusError("duplicate node locator")
                    locators.add(value_entry["locator"])
                    entries.append(value_entry)
                children = raw_field.get("fields")
                if children is not None:
                    if raw_field.get("type") != "object" or not isinstance(children, list):
                        raise LocalCensusError(f"field {field_path} has incoherent nested fields")
                    walk_fields(
                        children,
                        field_path,
                        catalog_name=catalog_name,
                        catalog_file=catalog_file,
                    )

        walk_fields(fields, None)
    return entries


def build_local_census(
    projection: Mapping[str, Any],
    *,
    semantic_source_revision: str,
    tenant_ref: str | None = None,
    catalog_ref: str | None = None,
) -> dict[str, Any]:
    """Build a full in-memory roster and a sanitized, self-hashed receipt."""

    if not isinstance(projection, Mapping):
        raise LocalCensusError("projection must be an object")
    if not _is_hash(semantic_source_revision):
        raise LocalCensusError("semantic_source_revision must be a sha256 identity")
    projection_tenant = _opaque(projection.get("tenant"), "projection.tenant")
    if tenant_ref is None:
        tenant_ref = projection_tenant
    else:
        tenant_ref = _opaque(tenant_ref, "tenant_ref")
        if tenant_ref != projection_tenant:
            raise LocalCensusError("tenant_ref differs from the normalized projection")
    if catalog_ref is not None:
        catalog_ref = _opaque(catalog_ref, "catalog_ref")
        catalogs = _catalogs(projection)
        matches = [
            item
            for item in catalogs
            if isinstance(item, Mapping)
            and isinstance(item.get("name"), str)
            and (item["name"] == catalog_ref or item["name"].endswith("." + catalog_ref))
        ]
        if len(matches) != 1:
            raise LocalCensusError("catalog_ref does not resolve to exactly one catalog")
        projection = {**projection, "catalogs": matches}
    entries = _walk_projection(projection)
    if not entries:
        raise LocalCensusError("projection produced an empty roster")
    states = Counter(entry["state"] for entry in entries)
    domains = Counter(entry["domain"]["kind"] for entry in entries)
    sanitized_entries = [
        {key: value for key, value in entry.items() if key != "literal"} for entry in entries
    ]
    stable = {
        "schema_version": 1,
        "contract_id": "video-local-census-v1",
        "semantic_source_revision": semantic_source_revision,
        "tenant_ref": tenant_ref,
        "catalog_ref": catalog_ref,
        "projection_schema": 2,
        "entries": sanitized_entries,
    }
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "contract_id": "video-local-census-v1",
        "semantic_source_revision": semantic_source_revision,
        "tenant_ref": tenant_ref,
        "catalog_ref": catalog_ref,
        "projection_schema": 2,
        "node_count": len(entries),
        "catalog_count": sum(entry["node_kind"] == "catalog" for entry in entries),
        "field_count": sum(entry["node_kind"] == "field" for entry in entries),
        "value_count": sum(entry["node_kind"] == "value" for entry in entries),
        "state_counts": dict(sorted(states.items())),
        "domain_counts": dict(sorted(domains.items())),
        "roster_sha256": _hash(stable),
        "counts": {
            "items_in": len(entries),
            "items_out": len(entries),
            "items_distinct": len(entries),
            "items_gaps": 0,
        },
        "values_redacted": True,
    }
    receipt["receipt_sha256"] = _hash(receipt)
    return {"schema_version": 1, "roster": entries, "receipt": receipt}


def validate_local_census_receipt(receipt: Any) -> list[str]:
    """Validate the public receipt without admitting value/description payloads."""

    if not isinstance(receipt, Mapping):
        return ["receipt must be an object"]
    errors: list[str] = []
    if set(receipt) != {
        "schema_version",
        "contract_id",
        "semantic_source_revision",
        "tenant_ref",
        "catalog_ref",
        "projection_schema",
        "node_count",
        "catalog_count",
        "field_count",
        "value_count",
        "state_counts",
        "domain_counts",
        "roster_sha256",
        "counts",
        "values_redacted",
        "receipt_sha256",
    }:
        errors.append("receipt fields are not the closed public contract")
    forbidden = {"means", "aka", "literal"}

    def contains_forbidden(value: Any) -> bool:
        if isinstance(value, Mapping):
            return any(key in forbidden or contains_forbidden(item) for key, item in value.items())
        if isinstance(value, list):
            return any(contains_forbidden(item) for item in value)
        return False

    if contains_forbidden(receipt):
        errors.append("receipt contains forbidden semantic/value material")
    if receipt.get("schema_version") != 1 or receipt.get("contract_id") != "video-local-census-v1":
        errors.append("receipt identity is invalid")
    if not _is_hash(receipt.get("semantic_source_revision")):
        errors.append("receipt semantic_source_revision is invalid")
    if not _is_hash(receipt.get("roster_sha256")):
        errors.append("receipt roster_sha256 is invalid")
    if receipt.get("projection_schema") != 2:
        errors.append("receipt projection schema is invalid")
    if receipt.get("values_redacted") is not True:
        errors.append("receipt values redaction marker is invalid")
    for key in ("node_count", "catalog_count", "field_count", "value_count"):
        if type(receipt.get(key)) is not int or receipt[key] < 0:
            errors.append(f"receipt {key} is invalid")
    if all(
        type(receipt.get(key)) is int
        for key in ("node_count", "catalog_count", "field_count", "value_count")
    ) and (
        receipt["node_count"]
        != receipt["catalog_count"] + receipt["field_count"] + receipt["value_count"]
    ):
        errors.append("receipt node counts are incoherent")
    for key in ("state_counts", "domain_counts"):
        value = receipt.get(key)
        if not isinstance(value, Mapping) or any(
            type(name) is not str or type(count) is not int or count < 0
            for name, count in value.items()
        ):
            errors.append(f"receipt {key} is invalid")
    counts = receipt.get("counts")
    if not isinstance(counts, Mapping) or set(counts) != {
        "items_in",
        "items_out",
        "items_distinct",
        "items_gaps",
    }:
        errors.append("receipt counts are invalid")
    elif (
        counts.get("items_in") != counts.get("items_out")
        or counts.get("items_out") != counts.get("items_distinct")
        or counts.get("items_gaps") != 0
    ):
        errors.append("receipt counts are not closed")
    elif counts["items_in"] != receipt.get("node_count"):
        errors.append("receipt node denominator differs from closed counts")
    expected = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt.get("receipt_sha256") != _hash(expected):
        errors.append("receipt self-hash is invalid")
    return errors


__all__ = ["LocalCensusError", "build_local_census", "validate_local_census_receipt"]
