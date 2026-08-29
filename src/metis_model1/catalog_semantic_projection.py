"""Project canonical catalog semantics onto an execution catalog.

The canonical catalog is the only source of value domains.  An execution
catalog may have a different name and a deliberately smaller technical
surface, but its field identity and local editorial semantics must still be
explicitly checked.  This module is intentionally pure: it accepts captured
JSON-like mappings and never reads a tenant, performs retrieval, or writes an
artifact.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from metis_model1.catalog_semantic_retrieval import (
    CatalogSemanticRetrievalError,
    adapt_catalog_semantic_response,
)
from metis_model1.provenance import canonical_json_hash
from metis_model1.video_catalog_projection import (
    PROJECTION_CONTRACT as NORMALIZED_PROJECTION_CONTRACT,
)
from metis_model1.video_catalog_projection import (
    validate_catalog_projection_receipt,
)
from metis_model1.video_semantic_index import _catalogs, _walk_catalog

# The result intentionally remains the standard normalized projection consumed
# by the semantic index.  The execution join has its own receipt identity; a
# private projection contract would make the result impossible to serve.
PROJECTION_CONTRACT = NORMALIZED_PROJECTION_CONTRACT
RECEIPT_ID = "metis-model1/catalog-semantic-execution-receipt-v1"
FINITE_KINDS = frozenset({"inline", "enum", "list"})


def _is_hash(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


class CatalogSemanticProjectionError(ValueError):
    """Raised when the source and execution catalog cannot be joined exactly."""


def _canonical_hash(value: Any) -> str:
    return "sha256:" + canonical_json_hash(value)


def _ref(value: Any, label: str) -> str:
    if not _is_hash(value):
        raise CatalogSemanticProjectionError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _adapt_execution_describe(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CatalogSemanticProjectionError("execution describe must be an object")
    try:
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        return adapt_catalog_semantic_response("describe", raw).projection
    except (CatalogSemanticRetrievalError, TypeError, ValueError) as error:
        raise CatalogSemanticProjectionError(
            f"execution describe is not schema-2: {error}"
        ) from None


def _one_catalog(projection: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    try:
        catalogs = _catalogs(projection)
    except ValueError as error:
        raise CatalogSemanticProjectionError(
            f"{label} is not normalized schema-2: {error}"
        ) from None
    if len(catalogs) != 1:
        raise CatalogSemanticProjectionError(f"{label} must contain exactly one catalog")
    return catalogs[0]


def _one_execution_catalog(projection: Mapping[str, Any], label: str) -> Mapping[str, Any]:
    catalogs = projection.get("catalogs")
    if not isinstance(catalogs, list) or len(catalogs) != 1:
        raise CatalogSemanticProjectionError(f"{label} must contain exactly one catalog")
    return catalogs[0]


def _field_map(catalog: Mapping[str, Any], label: str) -> dict[str, Mapping[str, Any]]:
    fields: dict[str, Mapping[str, Any]] = {}

    def walk(items: Any, parent: str | None = None) -> None:
        if not isinstance(items, list):
            raise CatalogSemanticProjectionError(f"{label} fields are invalid")
        for field in items:
            if not isinstance(field, Mapping):
                raise CatalogSemanticProjectionError(f"{label} field is invalid")
            name = field.get("name")
            if not isinstance(name, str) or not name:
                raise CatalogSemanticProjectionError(f"{label} field name is invalid")
            path = name if parent is None else f"{parent}.{name}"
            if path in fields:
                raise CatalogSemanticProjectionError(f"{label} has duplicate field {path}")
            fields[path] = field
            children = field.get("fields")
            if children is not None:
                walk(children, path)

    walk(catalog.get("fields"))
    return fields


def _reviewed(value: Any, label: str) -> None:
    if not isinstance(value, Mapping) or value.get("state") != "reviewed":
        raise CatalogSemanticProjectionError(f"{label} must be reviewed")
    if not isinstance(value.get("means"), Mapping):
        raise CatalogSemanticProjectionError(f"{label} reviewed semantics require means")


def _disposed_value(value: Any, label: str) -> str:
    if not isinstance(value, Mapping) or value.get("state") not in {"reviewed", "draft"}:
        raise CatalogSemanticProjectionError(f"{label} must be reviewed or draft")
    if not isinstance(value.get("means"), Mapping):
        raise CatalogSemanticProjectionError(f"{label} requires means")
    return str(value["state"])


def _source_domains(
    source_fields: Mapping[str, Mapping[str, Any]], selected_paths: set[str]
) -> tuple[int, int, int]:
    count = 0
    reviewed = 0
    draft = 0
    for path in sorted(selected_paths):
        field = source_fields[path]
        domain = field.get("domain")
        if not isinstance(domain, Mapping):
            raise CatalogSemanticProjectionError(f"source field {path} domain is invalid")
        kind = domain.get("kind")
        if kind in FINITE_KINDS:
            values = domain.get("values")
            if not isinstance(values, list) or len(values) != domain.get("size"):
                raise CatalogSemanticProjectionError(
                    f"source finite field {path} has no complete ValueItem roster"
                )
            for index, item in enumerate(values):
                if not isinstance(item, Mapping) or not isinstance(item.get("literal"), str):
                    raise CatalogSemanticProjectionError(
                        f"source field {path} ValueItem {index} is invalid"
                    )
                state = _disposed_value(
                    item.get("semantic"), f"source field {path} value {index}.semantic"
                )
                if state == "reviewed":
                    reviewed += 1
                else:
                    draft += 1
            count += len(values)
        elif kind in {"open", "none"}:
            if "values" in domain:
                raise CatalogSemanticProjectionError(
                    f"source {kind} field {path} must not materialize values"
                )
        else:
            raise CatalogSemanticProjectionError(f"source field {path} domain kind is invalid")
    return count, reviewed, draft


def _allowlist(
    value: Mapping[str, Mapping[str, Sequence[str]]] | None,
    source_fields: Mapping[str, Mapping[str, Any]],
    execution_fields: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, list[str]]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise CatalogSemanticProjectionError("modifier_allowlist must be an object")
    result: dict[str, dict[str, list[str]]] = {}
    for path, entry in value.items():
        if path not in source_fields or path not in execution_fields:
            raise CatalogSemanticProjectionError(f"modifier allowlist has unknown field {path}")
        if not isinstance(entry, Mapping) or set(entry) != {"source", "execution"}:
            raise CatalogSemanticProjectionError(
                f"modifier allowlist for {path} must contain source and execution"
            )
        source = entry["source"]
        execution = entry["execution"]
        if (
            not isinstance(source, Sequence)
            or isinstance(source, str | bytes | bytearray)
            or not isinstance(execution, Sequence)
            or isinstance(execution, str | bytes | bytearray)
        ):
            raise CatalogSemanticProjectionError(f"modifier allowlist for {path} is invalid")
        source_list = list(source)
        execution_list = list(execution)
        if (
            any(not isinstance(item, str) for item in source_list + execution_list)
            or len(source_list) != len(set(source_list))
            or len(execution_list) != len(set(execution_list))
            or any(item not in {"multi", "ordered"} for item in source_list + execution_list)
            or source_list == execution_list
        ):
            raise CatalogSemanticProjectionError(
                f"modifier allowlist for {path} is not an exact divergence"
            )
        result[path] = {"source": source_list, "execution": execution_list}
    return result


def _domain_dispositions(
    value: Mapping[str, str] | None,
    source_fields: Mapping[str, Mapping[str, Any]],
    execution_fields: Mapping[str, Mapping[str, Any]],
) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise CatalogSemanticProjectionError("domain_dispositions must be an object")
    result: dict[str, str] = {}
    for path, reason in value.items():
        if path not in source_fields or path not in execution_fields:
            raise CatalogSemanticProjectionError(f"domain disposition has unknown field {path}")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1024:
            raise CatalogSemanticProjectionError(f"domain disposition for {path} is invalid")
        result[path] = reason
    return result


def _check_domain_compatibility(
    path: str,
    source: Mapping[str, Any],
    execution: Mapping[str, Any],
    dispositions: Mapping[str, str],
) -> None:
    source_kind = source.get("kind")
    execution_kind = execution.get("kind")
    if source_kind in {"open", "none"}:
        if execution_kind != source_kind:
            raise CatalogSemanticProjectionError(
                f"domain kind differs for {path}: {source_kind} versus {execution_kind}"
            )
        if path in dispositions:
            raise CatalogSemanticProjectionError(
                f"domain disposition is not needed for non-finite field {path}"
            )
        return
    if source_kind not in FINITE_KINDS:
        raise CatalogSemanticProjectionError(f"source domain kind is invalid for {path}")
    if execution_kind == "none":
        if path not in dispositions:
            raise CatalogSemanticProjectionError(
                f"finite field {path} mapped to none without an explicit disposition"
            )
        return
    if execution_kind not in FINITE_KINDS:
        raise CatalogSemanticProjectionError(
            f"finite field {path} has incompatible execution domain {execution_kind}"
        )
    if execution.get("size") != source.get("size"):
        raise CatalogSemanticProjectionError(f"finite domain size differs for {path}")
    if "nature" in execution and "nature" in source and execution["nature"] != source["nature"]:
        raise CatalogSemanticProjectionError(f"finite domain nature differs for {path}")
    if "values" in execution:
        raise CatalogSemanticProjectionError(f"execution describe materializes values for {path}")
    if path in dispositions:
        raise CatalogSemanticProjectionError(
            f"domain disposition is only valid for finite-to-none field {path}"
        )


def _replace_domains(
    fields: list[Any],
    source_fields: Mapping[str, Mapping[str, Any]],
    parent: str | None = None,
) -> None:
    for field in fields:
        path = field["name"] if parent is None else f"{parent}.{field['name']}"
        field["domain"] = deepcopy(source_fields[path]["domain"])
        children = field.get("fields")
        if children is not None:
            _replace_domains(children, source_fields, path)


def _receipt_hash(receipt: Mapping[str, Any]) -> str:
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    return _canonical_hash(body)


def _standard_projection_receipt(
    projection: Mapping[str, Any], execution_projection: Mapping[str, Any]
) -> dict[str, Any]:
    """Build the standard receipt required by ``video_semantic_index_v2``."""

    catalog = _one_execution_catalog(projection, "projection")
    fields = _field_map(catalog, "projection")
    finite = {
        path: field
        for path, field in fields.items()
        if field["domain"]["kind"] in FINITE_KINDS and field["domain"].get("size", 0) > 0
    }
    values = sum(len(field["domain"].get("values", [])) for field in finite.values())
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "receipt_id": "video-semantics/catalog-projection-receipt-v1",
        "projection_sha256": _canonical_hash(projection),
        "describe_sha256": _canonical_hash(execution_projection),
        "values_projection_sha256": sorted(
            _canonical_hash({"path": path, "domain": field["domain"]})
            for path, field in finite.items()
        ),
        "counts": {
            "catalogs": 1,
            "fields": len(fields),
            "finite_fields_expected": len(finite),
            "values_responses": len(finite),
            "values": values,
            "semantic_values": values,
            "gaps": 0,
        },
        "payload_redacted": True,
    }
    receipt["receipt_sha256"] = _canonical_hash(receipt)
    errors = validate_catalog_projection_receipt(receipt)
    if errors:  # Defensive: never emit a receipt the V2 consumer rejects.
        raise CatalogSemanticProjectionError(
            "generated standard projection receipt is invalid: " + "; ".join(errors)
        )
    return receipt


def build_catalog_semantic_projection(
    semantic_source: Mapping[str, Any],
    execution_describe: Mapping[str, Any],
    *,
    semantic_ref: str,
    execution_ref: str,
    modifier_allowlist: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
    domain_dispositions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Join one canonical normalized projection to one execution describe.

    The returned projection keeps the execution catalog name, file, driver,
    technical fields and *local* reviewed field/catalog semantics.  Every
    domain, including its ordered ``ValueItem`` objects, comes from the
    canonical source.  A finite execution domain may be a marker-only domain,
    or it may be ``none`` only with an explicit human-readable disposition.
    """

    semantic_ref = _ref(semantic_ref, "semantic_ref")
    execution_ref = _ref(execution_ref, "execution_ref")
    source_catalog = _one_catalog(semantic_source, "semantic_source")
    execution_projection = _adapt_execution_describe(execution_describe)
    execution_catalog = _one_execution_catalog(execution_projection, "execution_describe")
    if semantic_source.get("tenant") != execution_projection.get("tenant"):
        raise CatalogSemanticProjectionError("tenant differs between semantic source and execution")
    if semantic_source.get("thresholds") != execution_projection.get("thresholds"):
        raise CatalogSemanticProjectionError(
            "thresholds differ between semantic source and execution"
        )

    # The existing normalized validator checks schema, names, nesting, field
    # domains and every ValueItem.  We still check review state explicitly
    # because this projection is not allowed to carry an unreviewed authority.
    try:
        _walk_catalog(source_catalog)
    except ValueError as error:
        raise CatalogSemanticProjectionError(f"semantic source is invalid: {error}") from None
    _reviewed(source_catalog.get("semantic"), "semantic source catalog.semantic")
    source_fields = _field_map(source_catalog, "semantic source")
    execution_fields = _field_map(execution_catalog, "execution")
    _reviewed(execution_catalog.get("semantic"), "execution catalog.semantic")
    for path, field in source_fields.items():
        _reviewed(field.get("semantic"), f"semantic source field {path}.semantic")
    for path, field in execution_fields.items():
        _reviewed(field.get("semantic"), f"execution field {path}.semantic")

    source_names = set(source_fields)
    execution_names = set(execution_fields)
    extra = sorted(execution_names - source_names)
    if extra:
        raise CatalogSemanticProjectionError(
            f"field roster differs: execution fields absent from source={extra}"
        )
    source_value_count, source_values_reviewed, source_values_draft = _source_domains(
        source_fields, execution_names
    )
    allowlist = _allowlist(modifier_allowlist, source_fields, execution_fields)
    dispositions = _domain_dispositions(domain_dispositions, source_fields, execution_fields)
    for path in sorted(execution_names):
        source_field = source_fields[path]
        execution_field = execution_fields[path]
        if source_field.get("type") != execution_field.get("type"):
            raise CatalogSemanticProjectionError(f"field type differs for {path}")
        source_modifiers = source_field.get("modifiers")
        execution_modifiers = execution_field.get("modifiers")
        if source_modifiers != execution_modifiers:
            expected = allowlist.get(path)
            if (
                expected is None
                or expected["source"] != source_modifiers
                or expected["execution"] != execution_modifiers
            ):
                raise CatalogSemanticProjectionError(f"field modifiers differ for {path}")
        elif path in allowlist:
            raise CatalogSemanticProjectionError(
                f"modifier allowlist is not a divergence for {path}"
            )
        _check_domain_compatibility(
            path,
            source_field["domain"],
            execution_field["domain"],
            dispositions,
        )

    output_catalog = deepcopy(execution_catalog)
    _replace_domains(output_catalog["fields"], source_fields)
    projection = {
        "schema": 2,
        "projection_contract": PROJECTION_CONTRACT,
        "tenant": execution_projection["tenant"],
        "thresholds": deepcopy(execution_projection["thresholds"]),
        "catalogs": [output_catalog],
    }
    counts = {
        "catalogs_in": 1,
        "catalogs_out": 1,
        "source_fields_available": len(source_fields),
        "fields_in": len(execution_fields),
        "fields_out": len(execution_fields),
        "fields_distinct": len(execution_names),
        "values_in": source_value_count,
        "values_out": source_value_count,
        "values_reviewed": source_values_reviewed,
        "values_draft": source_values_draft,
        "modifier_exceptions": len(allowlist),
        "domain_dispositions": len(dispositions),
        "gaps": 0,
    }
    execution_receipt: dict[str, Any] = {
        "schema_version": 1,
        "receipt_id": RECEIPT_ID,
        "semantic_ref": semantic_ref,
        "execution_ref": execution_ref,
        "source_projection_sha256": _canonical_hash(semantic_source),
        "execution_describe_sha256": _canonical_hash(execution_projection),
        "modifier_allowlist_sha256": _canonical_hash(allowlist),
        "domain_dispositions_sha256": _canonical_hash(dispositions),
        "projection_sha256": _canonical_hash(projection),
        "counts": counts,
        "payload_redacted": True,
    }
    execution_receipt["receipt_sha256"] = _receipt_hash(execution_receipt)
    return {
        "projection": projection,
        "receipt": _standard_projection_receipt(projection, execution_projection),
        "execution_receipt": execution_receipt,
    }


def validate_catalog_semantic_projection_receipt(receipt: Any) -> list[str]:
    """Validate the payload-free, self-hashed receipt."""

    errors: list[str] = []
    if not isinstance(receipt, Mapping):
        return ["receipt must be an object"]
    required = {
        "schema_version",
        "receipt_id",
        "semantic_ref",
        "execution_ref",
        "source_projection_sha256",
        "execution_describe_sha256",
        "modifier_allowlist_sha256",
        "domain_dispositions_sha256",
        "projection_sha256",
        "counts",
        "payload_redacted",
        "receipt_sha256",
    }
    if set(receipt) != required:
        errors.append("receipt fields are not the closed contract")
    if receipt.get("schema_version") != 1 or receipt.get("receipt_id") != RECEIPT_ID:
        errors.append("receipt identity is invalid")
    for key in (
        "semantic_ref",
        "execution_ref",
        "source_projection_sha256",
        "execution_describe_sha256",
        "modifier_allowlist_sha256",
        "domain_dispositions_sha256",
        "projection_sha256",
        "receipt_sha256",
    ):
        if not _is_hash(receipt.get(key)):
            errors.append(f"receipt {key} is invalid")
    counts = receipt.get("counts")
    if not isinstance(counts, Mapping) or set(counts) != {
        "catalogs_in",
        "catalogs_out",
        "source_fields_available",
        "fields_in",
        "fields_out",
        "fields_distinct",
        "values_in",
        "values_out",
        "values_reviewed",
        "values_draft",
        "modifier_exceptions",
        "domain_dispositions",
        "gaps",
    }:
        errors.append("receipt counts are invalid")
    elif any(type(value) is not int or value < 0 for value in counts.values()):
        errors.append("receipt counts are not bounded")
    elif (
        counts["catalogs_in"] != 1
        or counts["catalogs_out"] != 1
        or counts["fields_in"] != counts["fields_out"]
        or counts["fields_out"] != counts["fields_distinct"]
        or counts["source_fields_available"] < counts["fields_in"]
        or counts["values_in"] != counts["values_out"]
        or counts["values_reviewed"] + counts["values_draft"] != counts["values_out"]
        or counts["gaps"] != 0
    ):
        errors.append("receipt counts are incoherent")
    if receipt.get("payload_redacted") is not True:
        errors.append("receipt redaction marker is invalid")
    forbidden = {"literal", "text", "means", "aka", "label", "values", "tenant", "catalog", "field"}

    def contains_forbidden(value: Any) -> bool:
        if isinstance(value, Mapping):
            return any(key in forbidden or contains_forbidden(item) for key, item in value.items())
        if isinstance(value, list):
            return any(contains_forbidden(item) for item in value)
        return False

    if contains_forbidden(receipt):
        errors.append("receipt contains catalog literals or editorial text")
    if _is_hash(receipt.get("receipt_sha256")) and receipt["receipt_sha256"] != _receipt_hash(
        receipt
    ):
        errors.append("receipt self-hash is invalid")
    return errors


def validate_catalog_semantic_projection_binding(
    result: Any,
    semantic_source: Mapping[str, Any],
    execution_describe: Mapping[str, Any],
    *,
    semantic_ref: str,
    execution_ref: str,
    modifier_allowlist: Mapping[str, Mapping[str, Sequence[str]]] | None = None,
    domain_dispositions: Mapping[str, str] | None = None,
) -> list[str]:
    """Bind both receipts to the externally supplied inputs and policies.

    Receipt self-hashes detect accidental corruption; this validator is the
    promotion boundary because it also compares every content and policy hash
    with independently supplied authority.
    """

    if not isinstance(result, Mapping) or set(result) != {
        "projection",
        "receipt",
        "execution_receipt",
    }:
        return ["result must be the closed projection bundle"]
    errors: list[str] = []
    projection = result["projection"]
    standard_receipt = result["receipt"]
    execution_receipt = result["execution_receipt"]
    errors.extend(
        f"standard receipt: {error}"
        for error in validate_catalog_projection_receipt(standard_receipt)
    )
    errors.extend(
        f"execution receipt: {error}"
        for error in validate_catalog_semantic_projection_receipt(execution_receipt)
    )
    try:
        semantic_ref = _ref(semantic_ref, "semantic_ref")
        execution_ref = _ref(execution_ref, "execution_ref")
        execution_projection = _adapt_execution_describe(execution_describe)
        source_catalog = _one_catalog(semantic_source, "semantic_source")
        execution_catalog = _one_execution_catalog(execution_projection, "execution_describe")
        source_fields = _field_map(source_catalog, "semantic source")
        execution_fields = _field_map(execution_catalog, "execution")
        allowlist = _allowlist(modifier_allowlist, source_fields, execution_fields)
        dispositions = _domain_dispositions(domain_dispositions, source_fields, execution_fields)
    except CatalogSemanticProjectionError as error:
        return [*errors, f"binding inputs are invalid: {error}"]
    if not isinstance(standard_receipt, Mapping) or not isinstance(execution_receipt, Mapping):
        return errors
    expected = {
        "semantic_ref": semantic_ref,
        "execution_ref": execution_ref,
        "source_projection_sha256": _canonical_hash(semantic_source),
        "execution_describe_sha256": _canonical_hash(execution_projection),
        "modifier_allowlist_sha256": _canonical_hash(allowlist),
        "domain_dispositions_sha256": _canonical_hash(dispositions),
        "projection_sha256": _canonical_hash(projection),
    }
    for key, value in expected.items():
        if execution_receipt.get(key) != value:
            errors.append(f"execution receipt {key} differs from binding authority")
    if standard_receipt.get("projection_sha256") != expected["projection_sha256"]:
        errors.append("standard receipt projection differs from bundle content")
    if standard_receipt.get("describe_sha256") != expected["execution_describe_sha256"]:
        errors.append("standard receipt describe differs from execution authority")
    return errors


# Explicit aliases make the execution projection name discoverable without
# duplicating implementation or creating a second contract.
build_execution_catalog_semantic_projection = build_catalog_semantic_projection
validate_execution_catalog_semantic_projection_receipt = (
    validate_catalog_semantic_projection_receipt
)
validate_execution_catalog_semantic_projection_binding = (
    validate_catalog_semantic_projection_binding
)

__all__ = [
    "PROJECTION_CONTRACT",
    "RECEIPT_ID",
    "CatalogSemanticProjectionError",
    "build_catalog_semantic_projection",
    "build_execution_catalog_semantic_projection",
    "validate_catalog_semantic_projection_binding",
    "validate_catalog_semantic_projection_receipt",
    "validate_execution_catalog_semantic_projection_binding",
    "validate_execution_catalog_semantic_projection_receipt",
]
