"""Pure, payload-redacting adapter for the pinned catalog retrieval schema.

Execution and live-pin authority intentionally live outside this module.  This
adapter accepts one already-captured stdout document, validates the complete
``schema: 1`` response, and returns a hash-bound receipt which contains counts
and domain metadata but never catalog values.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator

import metis_model1.catalog_maintenance_pin as pin_module

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = PROJECT_ROOT / "schemas/catalog-retrieval-receipt.schema.json"
NONCLAIMS = [
    "no_execution_authority",
    "no_retrieval_refresh_claim",
    "no_semantic_truth",
    "no_training_authority",
    "no_accuracy_claim",
    "nonpromotable",
]
KINDS = frozenset({"none", "inline", "list", "enum", "open"})
NATURES = frozenset({"reflected", "editorial"})
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_COLLECTION_ITEMS = 100_000
MAX_NESTING = 32


class CatalogRetrievalError(ValueError):
    """Raised when a retrieval response or receipt fails closed."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CatalogRetrievalError(f"value is not canonical JSON: {error}") from error


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _exact_object(
    value: Any, allowed: set[str], required: set[str], label: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CatalogRetrievalError(f"{label} must be an object")
    keys = set(value)
    if keys - allowed or required - keys:
        raise CatalogRetrievalError(f"{label} has missing or extra fields")
    return value


def _string(value: Any, label: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise CatalogRetrievalError(f"{label} must be a bounded non-empty string")
    if any(ord(character) < 0x20 for character in value):
        raise CatalogRetrievalError(f"{label} contains a control character")
    return value


def _integer(value: Any, label: str) -> int:
    if type(value) is not int or value < 0 or value > MAX_COLLECTION_ITEMS:
        raise CatalogRetrievalError(f"{label} must be a bounded non-negative integer")
    return value


def _hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
        raise CatalogRetrievalError(f"{label} must be a sha256 identity")
    try:
        int(value[7:], 16)
    except ValueError as error:
        raise CatalogRetrievalError(f"{label} must be a sha256 identity") from error
    return value


def _parse_response(value: bytes | str) -> tuple[dict[str, Any], bytes]:
    if isinstance(value, str):
        raw = value.encode("utf-8")
    elif isinstance(value, bytes):
        raw = value
    else:
        raise CatalogRetrievalError("response must be bytes or text")
    if not raw or len(raw) > MAX_RESPONSE_BYTES:
        raise CatalogRetrievalError("response is empty or exceeds the byte cap")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise CatalogRetrievalError("response is not UTF-8") from error

    def reject_constant(token: str) -> None:
        raise CatalogRetrievalError(f"response contains non-JSON number {token}")

    def exact_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise CatalogRetrievalError(f"response contains duplicate key {key}")
            result[key] = item
        return result

    try:
        parsed = json.loads(text, parse_constant=reject_constant, object_pairs_hook=exact_pairs)
    except CatalogRetrievalError:
        raise
    except json.JSONDecodeError as error:
        raise CatalogRetrievalError("response is not one complete JSON document") from error
    if not isinstance(parsed, dict):
        raise CatalogRetrievalError("response root must be an object")
    return parsed, raw


def _safe_relative_file(value: Any, label: str) -> str:
    path = _string(value, label)
    if "\\" in path:
        raise CatalogRetrievalError(f"{label} must be a relative POSIX path")
    relative = PurePosixPath(path)
    if relative.is_absolute() or relative.as_posix() != path or ".." in relative.parts:
        raise CatalogRetrievalError(f"{label} must be a relative POSIX path")
    return path


def _strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_COLLECTION_ITEMS:
        raise CatalogRetrievalError(f"{label} must be a bounded array")
    return [_string(item, f"{label} item") for item in value]


def _domain(value: Any, label: str, *, describe: bool) -> tuple[str, int | None, str | None, int]:
    domain = _exact_object(
        value,
        {"kind", "size", "nature", "values"},
        {"kind"},
        label,
    )
    kind = domain["kind"]
    if kind not in KINDS:
        raise CatalogRetrievalError(f"{label}.kind is unknown")
    size = _integer(domain["size"], f"{label}.size") if "size" in domain else None
    nature = domain.get("nature")
    if nature is not None and nature not in NATURES:
        raise CatalogRetrievalError(f"{label}.nature is unknown")
    values = _strings(domain["values"], f"{label}.values") if "values" in domain else None

    if kind in {"none", "open"}:
        if size is not None or nature is not None or values is not None:
            raise CatalogRetrievalError(f"{label} {kind} must not materialize a domain")
    elif kind == "inline":
        if size is None or values is None or nature is not None or size != len(values):
            raise CatalogRetrievalError(f"{label} inline domain is inconsistent")
    elif kind == "list":
        if size is None or nature is not None or (describe and values is not None):
            raise CatalogRetrievalError(f"{label} list domain is inconsistent")
        if not describe and (values is None or size != len(values)):
            raise CatalogRetrievalError(f"{label} list values are inconsistent")
    else:
        if size is None or (describe and values is not None):
            raise CatalogRetrievalError(f"{label} enum domain is inconsistent")
        if not describe and values is not None and size != len(values):
            raise CatalogRetrievalError(f"{label} enum values are inconsistent")
        if not describe and ((values is None) != (nature is None)):
            raise CatalogRetrievalError(
                f"{label} resolved enum requires nature and values together"
            )
    return kind, size, nature, 0 if values is None else len(values)


def _field(value: Any, label: str, depth: int) -> tuple[int, int, int]:
    if depth > MAX_NESTING:
        raise CatalogRetrievalError("field nesting exceeds the cap")
    field = _exact_object(
        value,
        {"name", "type", "modifiers", "domain", "fields"},
        {"name", "type", "modifiers", "domain"},
        label,
    )
    _string(field["name"], f"{label}.name")
    field_type = _string(field["type"], f"{label}.type")
    modifiers = field["modifiers"]
    if (
        not isinstance(modifiers, list)
        or any(item not in {"multi", "ordered"} for item in modifiers)
        or len(modifiers) != len(set(modifiers))
    ):
        raise CatalogRetrievalError(f"{label}.modifiers are invalid")
    kind, _, _, value_count = _domain(field["domain"], f"{label}.domain", describe=True)
    domain_count = 0 if kind == "none" else 1
    children = field.get("fields")
    if (field_type == "object") != (children is not None):
        raise CatalogRetrievalError(f"{label}.fields must appear exactly for object fields")
    count = 1
    if children is not None:
        if not isinstance(children, list) or len(children) > MAX_COLLECTION_ITEMS:
            raise CatalogRetrievalError(f"{label}.fields must be a bounded array")
        names: set[str] = set()
        for index, child in enumerate(children):
            child_count, child_domains, child_values = _field(
                child, f"{label}.fields[{index}]", depth + 1
            )
            child_name = child["name"]
            if child_name in names:
                raise CatalogRetrievalError(f"{label}.fields contains duplicate names")
            names.add(child_name)
            count += child_count
            domain_count += child_domains
            value_count += child_values
    return count, domain_count, value_count


def _validate_describe(response: Mapping[str, Any], catalog_filter: str | None) -> dict[str, Any]:
    root = _exact_object(
        response,
        {"schema", "tenant", "thresholds", "catalogs"},
        {"schema", "tenant", "thresholds", "catalogs"},
        "describe response",
    )
    if type(root["schema"]) is not int or root["schema"] != 1:
        raise CatalogRetrievalError("describe response schema must be integer 1")
    tenant = _string(root["tenant"], "describe response tenant")
    thresholds = _exact_object(
        root["thresholds"], {"inline-max", "enum-max"}, {"inline-max", "enum-max"}, "thresholds"
    )
    _integer(thresholds["inline-max"], "thresholds.inline-max")
    _integer(thresholds["enum-max"], "thresholds.enum-max")
    catalogs = root["catalogs"]
    if not isinstance(catalogs, list) or len(catalogs) > MAX_COLLECTION_ITEMS:
        raise CatalogRetrievalError("catalogs must be a bounded array")
    if catalog_filter is not None and not catalogs:
        raise CatalogRetrievalError("filtered describe returned no catalog")
    names: set[str] = set()
    field_count = 0
    domain_count = 0
    value_count = 0
    for index, item in enumerate(catalogs):
        catalog = _exact_object(
            item,
            {"name", "driver", "index", "file", "fields"},
            {"name", "driver", "file", "fields"},
            f"catalogs[{index}]",
        )
        name = _string(catalog["name"], f"catalogs[{index}].name")
        if name in names:
            raise CatalogRetrievalError("describe response contains duplicate catalogs")
        names.add(name)
        if (
            catalog_filter is not None
            and name != catalog_filter
            and name.rsplit(".", 1)[-1] != catalog_filter
        ):
            raise CatalogRetrievalError("describe response does not match the catalog query")
        _string(catalog["driver"], f"catalogs[{index}].driver")
        if "index" in catalog:
            _string(catalog["index"], f"catalogs[{index}].index")
        _safe_relative_file(catalog["file"], f"catalogs[{index}].file")
        fields = catalog["fields"]
        if not isinstance(fields, list) or len(fields) > MAX_COLLECTION_ITEMS:
            raise CatalogRetrievalError(f"catalogs[{index}].fields must be a bounded array")
        direct_names: set[str] = set()
        for field_index, field in enumerate(fields):
            count, domains, values = _field(field, f"catalogs[{index}].fields[{field_index}]", 0)
            if field["name"] in direct_names:
                raise CatalogRetrievalError("catalog contains duplicate field names")
            direct_names.add(field["name"])
            field_count += count
            domain_count += domains
            value_count += values
    return {
        "tenant": tenant,
        "kind": "describe",
        "size": None,
        "nature": None,
        "catalog_count": len(catalogs),
        "field_count": field_count,
        "domain_count": domain_count,
        "value_count": value_count,
    }


def _validate_values(response: Mapping[str, Any], catalog: str, field: str) -> dict[str, Any]:
    root = _exact_object(
        response,
        {"schema", "tenant", "catalog", "field", "kind", "size", "nature", "values", "note"},
        {"schema", "tenant", "catalog", "field", "kind"},
        "values response",
    )
    if type(root["schema"]) is not int or root["schema"] != 1:
        raise CatalogRetrievalError("values response schema must be integer 1")
    tenant = _string(root["tenant"], "values response tenant")
    resolved_catalog = _string(root["catalog"], "values response catalog")
    response_field = _string(root["field"], "values response field")
    if resolved_catalog != catalog and resolved_catalog.rsplit(".", 1)[-1] != catalog:
        raise CatalogRetrievalError("values response does not match the catalog query")
    if response_field != field:
        raise CatalogRetrievalError("values response does not match the field query")
    domain = {key: root[key] for key in ("kind", "size", "nature", "values") if key in root}
    kind, size, nature, value_count = _domain(domain, "values response", describe=False)
    note = root.get("note")
    if note is not None:
        _string(note, "values response note")
    if kind in {"none", "open"} and note is None:
        raise CatalogRetrievalError(f"values response {kind} needs a note")
    if kind == "inline" and note is not None:
        raise CatalogRetrievalError("inline response must not carry a note")
    if kind == "list" and note is None:
        raise CatalogRetrievalError("list response needs its provenance note")
    if kind == "enum":
        resolved = "values" in root
        if resolved and note is not None:
            raise CatalogRetrievalError("resolved enum response must not carry a note")
        if not resolved and note is None:
            raise CatalogRetrievalError("unmaterialized enum response needs a note")
    return {
        "tenant": tenant,
        "kind": kind,
        "size": size,
        "nature": nature,
        "catalog_count": 1,
        "field_count": 1,
        "domain_count": 0 if kind == "none" else 1,
        "value_count": value_count,
    }


def _query(operation: Any, catalog: Any, field: Any) -> tuple[str, str | None, str | None]:
    if operation not in {"describe", "values"}:
        raise CatalogRetrievalError("operation must be describe or values")
    if catalog is not None:
        catalog = _string(catalog, "catalog", maximum=256)
        if "/" in catalog or "\\" in catalog or catalog.startswith("-"):
            raise CatalogRetrievalError("catalog is not path-inert")
    if field is not None:
        field = _string(field, "field", maximum=256)
        if "/" in field or "\\" in field or field.startswith("-"):
            raise CatalogRetrievalError("field is not path-inert")
    if operation == "describe" and field is not None:
        raise CatalogRetrievalError("describe does not accept a field")
    if operation == "values" and (catalog is None or field is None):
        raise CatalogRetrievalError("values requires catalog and field")
    return operation, catalog, field


def _receipt_hash(receipt: Mapping[str, Any]) -> str:
    return _sha256(
        _canonical({key: value for key, value in receipt.items() if key != "receipt_sha256"})
    )


def adapt_catalog_retrieval_response(
    operation: str,
    response: bytes | str,
    *,
    tenant_input_sha256: str,
    catalog: str | None = None,
    field: str | None = None,
    root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    """Validate one schema-1 response and return a payload-free local receipt.

    The tracked pin manifest is structurally checked, but this function does
    not execute Metis and deliberately records no live-pin or refresh claim.
    """

    operation, catalog, field = _query(operation, catalog, field)
    tenant_input_sha256 = _hash(tenant_input_sha256, "tenant_input_sha256")
    pin_errors = pin_module.validate_catalog_maintenance_pin_contract(root)
    if pin_errors:
        raise CatalogRetrievalError("catalog maintenance pin is invalid: " + "; ".join(pin_errors))
    manifest = pin_module.load_catalog_maintenance_pin(root)
    parsed, raw = _parse_response(response)
    summary = (
        _validate_describe(parsed, catalog)
        if operation == "describe"
        else _validate_values(parsed, catalog or "", field or "")
    )
    query = {
        "operation": operation,
        "tenant": summary.pop("tenant"),
        "catalog": catalog,
        "field": field,
    }
    upstream = {
        "pin_id": manifest["pin_id"],
        "revision": manifest["revision"],
        "tree": manifest["tree"],
        "manifest_sha256": pin_module.manifest_sha256(manifest),
        "verification": "manifest_contract_only",
    }
    request_material = {
        "query": query,
        "tenant_input_sha256": tenant_input_sha256,
        "upstream": upstream,
    }
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "status": "validated_response_non_authoritative",
        "query": query,
        "upstream": upstream,
        "tenant_input": {"sha256": tenant_input_sha256},
        "summary": summary,
        "hashes": {
            "request_sha256": _sha256(_canonical(request_material)),
            "response_sha256": _sha256(_canonical(parsed)),
            "output_sha256": _sha256(raw),
            "output_bytes": len(raw),
        },
        "policy": {
            "response_schema": 1,
            "values_redacted": True,
            "execution_verified": False,
            "retrieval_refresh_verified": False,
        },
        "nonclaims": list(NONCLAIMS),
    }
    receipt["receipt_sha256"] = _receipt_hash(receipt)
    errors = validate_catalog_retrieval_receipt(receipt, root=root)
    if errors:
        raise CatalogRetrievalError("generated receipt is invalid: " + "; ".join(errors))
    return receipt


def validate_catalog_retrieval_receipt(
    receipt: Any,
    *,
    root: Path = PROJECT_ROOT,
) -> list[str]:
    """Return schema and deterministic semantic errors for one receipt."""

    try:
        schema = json.loads(
            (root / SCHEMA_PATH.relative_to(PROJECT_ROOT)).read_text(encoding="utf-8")
        )
        Draft202012Validator.check_schema(schema)
        errors = sorted(
            Draft202012Validator(schema).iter_errors(receipt),
            key=lambda item: tuple(str(part) for part in item.absolute_path),
        )
        if errors:
            return [
                (
                    f"{'.'.join(str(part) for part in error.absolute_path) or '<root>'}: "
                    f"{error.message}"
                )
                for error in errors
            ]
        assert isinstance(receipt, Mapping)
        semantic: list[str] = []
        pin_errors = pin_module.validate_catalog_maintenance_pin_contract(root)
        semantic.extend(f"catalog maintenance pin: {error}" for error in pin_errors)
        manifest = pin_module.load_catalog_maintenance_pin(root)
        expected_upstream = {
            "pin_id": manifest["pin_id"],
            "revision": manifest["revision"],
            "tree": manifest["tree"],
            "manifest_sha256": pin_module.manifest_sha256(manifest),
            "verification": "manifest_contract_only",
        }
        if receipt["upstream"] != expected_upstream:
            semantic.append("receipt upstream identity differs from the tracked catalog pin")

        query = receipt["query"]
        operation, catalog, field = _query(query["operation"], query["catalog"], query["field"])
        _string(query["tenant"], "receipt query tenant")
        summary = receipt["summary"]
        if operation == "describe":
            if (
                summary["kind"] != "describe"
                or summary["size"] is not None
                or summary["nature"] is not None
                or summary["domain_count"] > summary["field_count"]
                or (catalog is not None and summary["catalog_count"] == 0)
            ):
                semantic.append("describe query and summary are inconsistent")
        else:
            if (
                summary["kind"] == "describe"
                or summary["catalog_count"] != 1
                or summary["field_count"] != 1
                or summary["domain_count"] != (0 if summary["kind"] == "none" else 1)
            ):
                semantic.append("values query and summary are inconsistent")
            if summary["kind"] in {"none", "open"} and (
                summary["size"] is not None
                or summary["nature"] is not None
                or summary["value_count"] != 0
            ):
                semantic.append("none/open summary must not claim a materialized domain")
            if summary["kind"] in {"inline", "list"} and (
                summary["size"] != summary["value_count"] or summary["nature"] is not None
            ):
                semantic.append("inline/list summary is inconsistent")
            if summary["kind"] == "enum" and (
                summary["size"] is None
                or (summary["nature"] is None and summary["value_count"] != 0)
                or (summary["nature"] is not None and summary["size"] != summary["value_count"])
            ):
                semantic.append("enum summary is inconsistent")

        request_material = {
            "query": dict(query),
            "tenant_input_sha256": receipt["tenant_input"]["sha256"],
            "upstream": dict(receipt["upstream"]),
        }
        if receipt["hashes"]["request_sha256"] != _sha256(_canonical(request_material)):
            semantic.append("request_sha256 does not bind query, tenant input and upstream pin")
        for key, value in _walk(receipt):
            if key == "values":
                semantic.append("receipt must never contain catalog values")
            integer_field = key.endswith("_count") or key in {
                "schema_version",
                "response_schema",
                "output_bytes",
                "size",
            }
            if integer_field and value is not None and type(value) is not int:
                semantic.append(f"{key} must be an integer, never a boolean")
        if receipt["receipt_sha256"] != _receipt_hash(receipt):
            semantic.append("receipt_sha256 does not match the canonical receipt")
        if receipt["nonclaims"] != NONCLAIMS:
            semantic.append("receipt nonclaims drift")
        return semantic
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        CatalogRetrievalError,
        pin_module.CatalogMaintenancePinError,
    ) as error:
        return [f"receipt validation failed closed: {error}"]


def _walk(value: Any) -> Sequence[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            found.append((str(key), item))
            found.extend(_walk(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk(item))
    return found
