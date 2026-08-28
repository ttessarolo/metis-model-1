"""Normalize committed Metis schema-2 catalog retrieval for local consumers.

Upstream deliberately exposes two separate contracts: ``catalog:describe``
keeps a light skeleton, while ``catalog:values`` returns one field domain at a
time.  Model 1 consumers must not pretend that value semantics are embedded in
the describe response.  This module validates both upstream shapes through the
pinned adapter, joins them by exact catalog/field identity, and emits one
explicitly named local projection plus a payload-free receipt.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from metis_model1.catalog_semantic_retrieval import (
    CatalogSemanticRetrievalError,
    adapt_catalog_semantic_response,
)
from metis_model1.provenance import canonical_json_hash

PROJECTION_CONTRACT = "metis-model1/catalog-semantic-normalized-v1"
FINITE_KINDS = frozenset({"inline", "enum", "list"})
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class VideoCatalogProjectionError(ValueError):
    """Raised when describe/values retrieval cannot be joined exactly."""


def _canonical_hash(value: Any) -> str:
    return "sha256:" + canonical_json_hash(value)


def _validated(
    operation: str,
    value: Mapping[str, Any],
    *,
    catalog: str | None = None,
    field: str | None = None,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise VideoCatalogProjectionError(f"{operation} projection must be an object")
    try:
        raw = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=False,
        )
        return adapt_catalog_semantic_response(
            operation, raw, catalog=catalog, field=field
        ).projection
    except (CatalogSemanticRetrievalError, TypeError, ValueError) as error:
        raise VideoCatalogProjectionError(
            f"{operation} projection is not the pinned schema-2 contract: {error}"
        ) from None


def _field_roster(catalogs: Sequence[Mapping[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    roster: dict[tuple[str, str], dict[str, Any]] = {}

    def walk(catalog: str, fields: Sequence[Any], parent: str | None = None) -> None:
        for raw in fields:
            if not isinstance(raw, Mapping):
                raise VideoCatalogProjectionError("describe field roster is invalid")
            name = raw["name"]
            path = name if parent is None else f"{parent}.{name}"
            key = (catalog, path)
            if key in roster:
                raise VideoCatalogProjectionError("describe contains a duplicate field path")
            roster[key] = dict(raw)
            children = raw.get("fields")
            if children is not None:
                walk(catalog, children, path)

    for catalog in catalogs:
        walk(catalog["name"], catalog["fields"])
    return roster


def _domain_material(response: Mapping[str, Any]) -> dict[str, Any]:
    return {key: response[key] for key in ("kind", "size", "nature") if key in response}


def _join_one_field(field: dict[str, Any], response: Mapping[str, Any]) -> None:
    described = field["domain"]
    returned = _domain_material(response)
    described_material = {
        key: described[key] for key in ("kind", "size", "nature") if key in described
    }
    if returned != described_material:
        raise VideoCatalogProjectionError("values domain differs from describe skeleton")
    if response["semantic"]["field"] != field["semantic"]:
        raise VideoCatalogProjectionError("values field semantics differ from describe skeleton")

    literals = response.get("values")
    semantics = response["semantic"].get("values")
    if literals is None or semantics is None:
        if described["kind"] in FINITE_KINDS and described.get("size", 0) > 0:
            raise VideoCatalogProjectionError("finite field values are not materialized")
        return
    if len(literals) != len(semantics):
        raise VideoCatalogProjectionError("values semantics are not aligned")
    if described["kind"] == "inline" and described.get("values") != literals:
        raise VideoCatalogProjectionError("inline values differ from describe skeleton")
    if len(set(literals)) != len(literals):
        raise VideoCatalogProjectionError("values response contains duplicate literals")
    field["domain"] = {
        **described_material,
        "values": [
            {
                "literal": literal,
                "semantic": {
                    key: deepcopy(value) for key, value in semantic.items() if key != "literal"
                },
            }
            for literal, semantic in zip(literals, semantics, strict=True)
        ],
    }


def build_catalog_semantic_projection(
    describe_projection: Mapping[str, Any],
    values_projections: Sequence[Mapping[str, Any]],
    *,
    catalog_ref: str | None = None,
) -> dict[str, Any]:
    """Join one describe result and its per-field values results fail-closed.

    Every finite non-empty field must have exactly one values response.  Open
    and none domains remain unmaterialized.  No fuzzy name matching, inference,
    live lookup, or model output is involved.
    """

    describe = _validated("describe", describe_projection, catalog=catalog_ref)
    if not isinstance(values_projections, Sequence) or isinstance(
        values_projections, (str, bytes, bytearray)
    ):
        raise VideoCatalogProjectionError("values projections must be an array")
    catalogs = deepcopy(describe["catalogs"])
    roster = _field_roster(catalogs)
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    value_receipts: list[str] = []
    for index, raw in enumerate(values_projections):
        if not isinstance(raw, Mapping):
            raise VideoCatalogProjectionError(f"values projection {index} is invalid")
        catalog = raw.get("catalog")
        field = raw.get("field")
        if not isinstance(catalog, str) or not isinstance(field, str):
            raise VideoCatalogProjectionError("values projection identity is missing")
        parsed = _validated("values", raw, catalog=catalog, field=field)
        if parsed["tenant"] != describe["tenant"]:
            raise VideoCatalogProjectionError("values tenant differs from describe tenant")
        key = (parsed["catalog"], parsed["field"])
        if key not in roster:
            raise VideoCatalogProjectionError("values projection targets an unknown field")
        if key in by_key:
            raise VideoCatalogProjectionError("duplicate values projection")
        by_key[key] = parsed
        value_receipts.append(_canonical_hash(parsed))

    # Re-walk the copied hierarchy so the merged values end up in the emitted
    # projection rather than in the detached roster dictionary.
    finite_expected = 0
    value_count = 0
    semantic_value_count = 0

    def merge_fields(catalog: str, fields: list[Any], parent: str | None = None) -> None:
        nonlocal finite_expected, value_count, semantic_value_count
        for field in fields:
            name = field["name"]
            path = name if parent is None else f"{parent}.{name}"
            domain = field["domain"]
            required = domain["kind"] in FINITE_KINDS and domain.get("size", 0) > 0
            if required:
                finite_expected += 1
                response = by_key.get((catalog, path))
                if response is None:
                    raise VideoCatalogProjectionError(
                        f"finite field {catalog}.{path} has no values projection"
                    )
                _join_one_field(field, response)
                value_count += len(field["domain"].get("values", []))
                semantic_value_count += len(field["domain"].get("values", []))
            elif (catalog, path) in by_key:
                _join_one_field(field, by_key[(catalog, path)])
            children = field.get("fields")
            if children is not None:
                merge_fields(catalog, children, path)

    for catalog in catalogs:
        merge_fields(catalog["name"], catalog["fields"])

    unused = sorted(set(by_key) - set(roster))
    if unused:  # Defensive; unknown fields are already rejected above.
        raise VideoCatalogProjectionError("values projection roster is not closed")

    projection = {
        "schema": 2,
        "projection_contract": PROJECTION_CONTRACT,
        "tenant": describe["tenant"],
        "thresholds": deepcopy(describe["thresholds"]),
        "catalogs": catalogs,
    }
    field_count = len(roster)
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "receipt_id": "video-semantics/catalog-projection-receipt-v1",
        "projection_sha256": _canonical_hash(projection),
        "describe_sha256": _canonical_hash(describe),
        "values_projection_sha256": sorted(value_receipts),
        "counts": {
            "catalogs": len(catalogs),
            "fields": field_count,
            "finite_fields_expected": finite_expected,
            "values_responses": len(by_key),
            "values": value_count,
            "semantic_values": semantic_value_count,
            "gaps": 0,
        },
        "payload_redacted": True,
    }
    receipt["receipt_sha256"] = _canonical_hash(receipt)
    return {"projection": projection, "receipt": receipt}


def validate_catalog_projection_receipt(receipt: Any) -> list[str]:
    """Validate the public receipt without exposing catalog or editorial data."""

    if not isinstance(receipt, Mapping):
        return ["receipt must be an object"]
    errors: list[str] = []
    if set(receipt) != {
        "schema_version",
        "receipt_id",
        "projection_sha256",
        "describe_sha256",
        "values_projection_sha256",
        "counts",
        "payload_redacted",
        "receipt_sha256",
    }:
        errors.append("receipt fields are not the closed public contract")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("receipt_id") != "video-semantics/catalog-projection-receipt-v1"
    ):
        errors.append("receipt identity is invalid")
    counts = receipt.get("counts")
    if not isinstance(counts, Mapping) or set(counts) != {
        "catalogs",
        "fields",
        "finite_fields_expected",
        "values_responses",
        "values",
        "semantic_values",
        "gaps",
    }:
        errors.append("receipt counts are invalid")
    elif (
        any(type(value) is not int or value < 0 for value in counts.values())
        or counts["gaps"] != 0
        or counts["values"] != counts["semantic_values"]
        or counts["values_responses"] < counts["finite_fields_expected"]
        or counts["values_responses"] > counts["fields"]
    ):
        errors.append("receipt roster is not closed")
    for key in ("projection_sha256", "describe_sha256", "receipt_sha256"):
        value = receipt.get(key)
        if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
            errors.append(f"receipt {key} is invalid")
    values_hashes = receipt.get("values_projection_sha256")
    if (
        not isinstance(values_hashes, list)
        or values_hashes != sorted(values_hashes)
        or len(values_hashes) != len(set(values_hashes))
        or any(
            not isinstance(value, str) or HASH_RE.fullmatch(value) is None
            for value in values_hashes
        )
        or (isinstance(counts, Mapping) and len(values_hashes) != counts.get("values_responses"))
    ):
        errors.append("receipt values projection roster is invalid")
    forbidden = {"means", "aka", "label", "literal", "catalog", "field", "tenant"}

    def walk(value: Any) -> bool:
        if isinstance(value, Mapping):
            return any(key in forbidden or walk(item) for key, item in value.items())
        if isinstance(value, list):
            return any(walk(item) for item in value)
        return False

    if walk(receipt):
        errors.append("receipt contains catalog or editorial payload")
    if receipt.get("payload_redacted") is not True:
        errors.append("receipt payload redaction marker is invalid")
    expected = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt.get("receipt_sha256") != _canonical_hash(expected):
        errors.append("receipt self-hash is invalid")
    return errors


__all__ = [
    "PROJECTION_CONTRACT",
    "VideoCatalogProjectionError",
    "build_catalog_semantic_projection",
    "validate_catalog_projection_receipt",
]
