"""Fail-closed adapter for Metis ``catalog:* --semantic`` schema 2.

The upstream TypeScript tool is the authority for the response shape.  This
module only consumes an already captured JSON response: it does not execute
Node, refresh a catalog, access a tenant, or make a live-attestation claim.
The returned projection retains the complete response for local consumers;
the separate receipt is deliberately limited to query, pin, counts and
hashes, so editorial text and catalog literals cannot be copied into it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

UPSTREAM_COMMIT = "0b41a25d4d5eeac88975e43e18e4bc3123d51667"
SCHEMA_VERSION = 2
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_ITEMS = 100_000
MAX_DEPTH = 32
MAX_STRING_CHARS = 16_384
MAX_PATH_CHARS = 1_024
MAX_LINE = 1_000_000
STATES = frozenset({"unannotated", "draft", "reviewed"})
KINDS = frozenset({"none", "inline", "list", "enum", "open"})
NATURES = frozenset({"reflected", "editorial"})
_CONTROL_MAX = 0x1F
_CONTROL_MIN = 0x7F
_CONTROL_MAX_C1 = 0x9F


class CatalogSemanticRetrievalError(ValueError):
    """Raised for any schema, semantic, provenance or bound violation."""


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
        raise CatalogSemanticRetrievalError("value is not canonical JSON") from error


def _sha256(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _hash(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 71 or not value.startswith("sha256:"):
        raise CatalogSemanticRetrievalError(f"{label} must be a sha256 hash")
    if any(character not in "0123456789abcdef" for character in value[7:]):
        raise CatalogSemanticRetrievalError(f"{label} must be a sha256 hash")
    try:
        int(value[7:], 16)
    except ValueError as error:
        raise CatalogSemanticRetrievalError(f"{label} must be a sha256 hash") from error
    return value


def _exact_object(value: Any, allowed: set[str], required: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise CatalogSemanticRetrievalError(f"{label} must be an object")
    keys = set(value)
    if keys - allowed:
        extras = ", ".join(sorted(keys - allowed))
        raise CatalogSemanticRetrievalError(f"{label} has extra fields: {extras}")
    if required - keys:
        missing = ", ".join(sorted(required - keys))
        raise CatalogSemanticRetrievalError(f"{label} is missing fields: {missing}")
    return value


def _safe_text(value: Any, label: str, *, maximum: int = MAX_STRING_CHARS) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise CatalogSemanticRetrievalError(f"{label} must be a bounded non-empty string")
    if any(
        ord(character) <= _CONTROL_MAX
        or _CONTROL_MIN <= ord(character) <= _CONTROL_MAX_C1
        or 0xD800 <= ord(character) <= 0xDFFF
        for character in value
    ):
        raise CatalogSemanticRetrievalError(f"{label} contains control or invalid Unicode")
    return value


def _integer(value: Any, label: str, *, maximum: int = MAX_ITEMS) -> int:
    if type(value) is not int or value < 0 or value > maximum:
        raise CatalogSemanticRetrievalError(f"{label} must be a bounded integer")
    return value


def _line(value: Any, label: str) -> int:
    if type(value) is not int or value < 1 or value > MAX_LINE:
        raise CatalogSemanticRetrievalError(f"{label} must be a 1-based bounded line")
    return value


def _relative_posix(value: Any, label: str) -> str:
    path = _safe_text(value, label, maximum=MAX_PATH_CHARS)
    if "\\" in path:
        raise CatalogSemanticRetrievalError(f"{label} must be a relative POSIX path")
    candidate = PurePosixPath(path)
    if (
        candidate.is_absolute()
        or candidate.as_posix() != path
        or path in {".", ".."}
        or any(part in {"", ".", ".."} for part in candidate.parts)
    ):
        raise CatalogSemanticRetrievalError(f"{label} must be a relative POSIX path")
    return path


def _bounded_array(value: Any, label: str) -> list[Any]:
    if type(value) is not list or len(value) > MAX_ITEMS:
        raise CatalogSemanticRetrievalError(f"{label} must be a bounded array")
    return value


def _parse_response(response: bytes | str) -> tuple[dict[str, Any], bytes]:
    if isinstance(response, str):
        raw = response.encode("utf-8")
    elif isinstance(response, bytes):
        raw = response
    else:
        raise CatalogSemanticRetrievalError("response must be bytes or text")
    if not raw or len(raw) > MAX_RESPONSE_BYTES:
        raise CatalogSemanticRetrievalError("response is empty or exceeds the byte cap")
    try:
        raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise CatalogSemanticRetrievalError("response is not UTF-8") from error

    def reject_constant(token: str) -> None:
        raise CatalogSemanticRetrievalError(f"response contains non-JSON number {token}")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise CatalogSemanticRetrievalError(f"response contains duplicate key {key}")
            result[key] = item
        return result

    try:
        parsed = json.loads(
            raw.decode("utf-8"),
            parse_constant=reject_constant,
            object_pairs_hook=reject_duplicate_keys,
        )
    except CatalogSemanticRetrievalError:
        raise
    except (json.JSONDecodeError, RecursionError) as error:
        raise CatalogSemanticRetrievalError("response is not one complete JSON document") from error
    if type(parsed) is not dict:
        raise CatalogSemanticRetrievalError("response root must be an object")
    _check_limits(parsed)
    return parsed, raw


def _check_limits(value: Any, depth: int = 0, seen: list[int] | None = None) -> None:
    """Bound every nested JSON container before semantic traversal."""
    if depth > MAX_DEPTH:
        raise CatalogSemanticRetrievalError("response nesting exceeds the depth cap")
    if seen is None:
        seen = [0]
    if type(value) is dict:
        if len(value) > MAX_ITEMS:
            raise CatalogSemanticRetrievalError("object exceeds the item cap")
        seen[0] += len(value)
        if seen[0] > MAX_ITEMS:
            raise CatalogSemanticRetrievalError("response exceeds the total item cap")
        for key, item in value.items():
            if not isinstance(key, str):
                raise CatalogSemanticRetrievalError("JSON object key is not text")
            _check_limits(item, depth + 1, seen)
    elif type(value) is list:
        if len(value) > MAX_ITEMS:
            raise CatalogSemanticRetrievalError("array exceeds the item cap")
        seen[0] += len(value)
        if seen[0] > MAX_ITEMS:
            raise CatalogSemanticRetrievalError("response exceeds the total item cap")
        for item in value:
            _check_limits(item, depth + 1, seen)
    elif isinstance(value, str):
        if len(value) > MAX_STRING_CHARS:
            raise CatalogSemanticRetrievalError("string exceeds the character cap")


def _source_ref(value: Any, label: str) -> dict[str, Any]:
    source = _exact_object(value, {"file", "line"}, {"file", "line"}, label)
    _relative_posix(source["file"], f"{label}.file")
    _line(source["line"], f"{label}.line")
    return source


def _means(value: Any, label: str) -> dict[str, Any]:
    means = _exact_object(value, {"text", "at"}, {"text", "at"}, label)
    _safe_text(means["text"], f"{label}.text")
    _source_ref(means["at"], f"{label}.at")
    return means


def _aka(value: Any, label: str) -> dict[str, Any]:
    aka = _exact_object(value, {"items", "at"}, {"items", "at"}, label)
    items = _bounded_array(aka["items"], f"{label}.items")
    for index, item in enumerate(items):
        _safe_text(item, f"{label}.items[{index}]")
    _source_ref(aka["at"], f"{label}.at")
    return aka


def _semantic(value: Any, label: str, *, allow_label: bool) -> dict[str, Any]:
    allowed = {"state", "at", "means", "aka"}
    if allow_label:
        allowed.add("label")
    semantic = _exact_object(value, allowed, {"state", "at"}, label)
    state = semantic["state"]
    if not isinstance(state, str) or state not in STATES:
        raise CatalogSemanticRetrievalError(f"{label}.state is unknown")
    _source_ref(semantic["at"], f"{label}.at")
    has_means = "means" in semantic
    if has_means:
        _means(semantic["means"], f"{label}.means")
    if "aka" in semantic:
        _aka(semantic["aka"], f"{label}.aka")
    if "label" in semantic:
        label_ref = _exact_object(
            semantic["label"], {"text", "at"}, {"text", "at"}, f"{label}.label"
        )
        _safe_text(label_ref["text"], f"{label}.label.text")
        _source_ref(label_ref["at"], f"{label}.label.at")
    if state == "unannotated" and (has_means or "aka" in semantic or "label" in semantic):
        raise CatalogSemanticRetrievalError(
            f"{label}.state unannotated cannot carry means, aka or label"
        )
    if state in {"draft", "reviewed"} and not has_means:
        raise CatalogSemanticRetrievalError(f"{label}.state requires means")
    if "aka" in semantic and not has_means:
        raise CatalogSemanticRetrievalError(f"{label}.aka requires means")
    return semantic


def _domain(value: Any, label: str, *, values_mode: bool) -> dict[str, Any]:
    domain = _exact_object(
        value,
        {"kind", "size", "nature", "values"},
        {"kind"},
        label,
    )
    kind = domain["kind"]
    if kind not in KINDS:
        raise CatalogSemanticRetrievalError(f"{label}.kind is unknown")
    if "size" in domain:
        _integer(domain["size"], f"{label}.size")
    if "nature" in domain and (
        not isinstance(domain["nature"], str) or domain["nature"] not in NATURES
    ):
        raise CatalogSemanticRetrievalError(f"{label}.nature is unknown")
    if "values" in domain:
        values = _bounded_array(domain["values"], f"{label}.values")
        for index, item in enumerate(values):
            _safe_text(item, f"{label}.values[{index}]")
    has_values = "values" in domain
    if kind in {"none", "open"}:
        if any(key in domain for key in ("size", "nature", "values")):
            raise CatalogSemanticRetrievalError(f"{label} {kind} must not materialize a domain")
    elif kind == "inline":
        if "size" not in domain or not has_values or "nature" in domain:
            raise CatalogSemanticRetrievalError(f"{label} inline domain is inconsistent")
        if domain["size"] != len(domain["values"]):
            raise CatalogSemanticRetrievalError(f"{label} inline size is inconsistent")
    elif kind == "list":
        if "size" not in domain or "nature" in domain:
            raise CatalogSemanticRetrievalError(f"{label} list domain is inconsistent")
        if values_mode and (not has_values or domain["size"] != len(domain["values"])):
            raise CatalogSemanticRetrievalError(f"{label} list values are inconsistent")
        if not values_mode and has_values:
            raise CatalogSemanticRetrievalError(
                f"{label} list describe must not materialize values"
            )
    else:
        if "size" not in domain:
            raise CatalogSemanticRetrievalError(f"{label} enum domain has no size")
        if not values_mode and has_values:
            raise CatalogSemanticRetrievalError(
                f"{label} enum describe must not materialize values"
            )
        if values_mode and has_values:
            if "nature" not in domain or domain["size"] != len(domain["values"]):
                raise CatalogSemanticRetrievalError(f"{label} resolved enum is inconsistent")
        elif values_mode and "nature" in domain:
            raise CatalogSemanticRetrievalError(f"{label} unresolved enum has nature")
    return domain


def _field(
    value: Any, label: str, *, values_mode: bool, depth: int = 0
) -> tuple[dict[str, Any], dict[str, int]]:
    if depth > MAX_DEPTH:
        raise CatalogSemanticRetrievalError("field nesting exceeds the depth cap")
    field = _exact_object(
        value,
        {"name", "type", "modifiers", "domain", "fields", "semantic"},
        {"name", "type", "modifiers", "domain", "semantic"},
        label,
    )
    _safe_text(field["name"], f"{label}.name")
    field_type = _safe_text(field["type"], f"{label}.type")
    modifiers = _bounded_array(field["modifiers"], f"{label}.modifiers")
    if any(not isinstance(item, str) for item in modifiers):
        raise CatalogSemanticRetrievalError(f"{label}.modifiers are invalid")
    if len(modifiers) != len(set(modifiers)) or any(
        item not in {"multi", "ordered"} for item in modifiers
    ):
        raise CatalogSemanticRetrievalError(f"{label}.modifiers are invalid")
    domain = _domain(field["domain"], f"{label}.domain", values_mode=values_mode)
    _semantic(field["semantic"], f"{label}.semantic", allow_label=False)
    children = field.get("fields")
    if (field_type == "object") != (children is not None):
        raise CatalogSemanticRetrievalError(f"{label}.fields must match object type")
    counts = {
        "fields": 1,
        "domains": int(domain["kind"] != "none"),
        "values": 0,
        "semantic_nodes": 1,
    }
    if "values" in domain:
        counts["values"] += len(domain["values"])
    if children is not None:
        children = _bounded_array(children, f"{label}.fields")
        names: set[str] = set()
        for index, child in enumerate(children):
            child_value, child_counts = _field(
                child, f"{label}.fields[{index}]", values_mode=values_mode, depth=depth + 1
            )
            if child_value["name"] in names:
                raise CatalogSemanticRetrievalError(f"{label}.fields contains duplicate names")
            names.add(child_value["name"])
            for key in counts:
                counts[key] += child_counts[key]
    return field, counts


def _validate_describe(response: Mapping[str, Any], catalog_filter: str | None) -> dict[str, int]:
    root = _exact_object(
        response,
        {"schema", "tenant", "thresholds", "catalogs"},
        {"schema", "tenant", "thresholds", "catalogs"},
        "describe response",
    )
    if type(root["schema"]) is not int or root["schema"] != SCHEMA_VERSION:
        raise CatalogSemanticRetrievalError("schema 1 is not accepted; schema 2 is required")
    _safe_text(root["tenant"], "describe response.tenant")
    thresholds = _exact_object(
        root["thresholds"], {"inline-max", "enum-max"}, {"inline-max", "enum-max"}, "thresholds"
    )
    _integer(thresholds["inline-max"], "thresholds.inline-max")
    _integer(thresholds["enum-max"], "thresholds.enum-max")
    catalogs = _bounded_array(root["catalogs"], "catalogs")
    if catalog_filter is not None and not catalogs:
        raise CatalogSemanticRetrievalError("catalog query returned no catalog")
    names: set[str] = set()
    counts = {
        "catalogs": len(catalogs),
        "fields": 0,
        "domains": 0,
        "values": 0,
        "semantic_nodes": 0,
        "semantic_values": 0,
    }
    for index, item in enumerate(catalogs):
        catalog = _exact_object(
            item,
            {"name", "driver", "index", "file", "fields", "semantic"},
            {"name", "driver", "file", "fields", "semantic"},
            f"catalogs[{index}]",
        )
        name = _safe_text(catalog["name"], f"catalogs[{index}].name")
        if name in names:
            raise CatalogSemanticRetrievalError("describe response contains duplicate catalogs")
        names.add(name)
        if (
            catalog_filter is not None
            and name != catalog_filter
            and name.rsplit(".", 1)[-1] != catalog_filter
        ):
            raise CatalogSemanticRetrievalError(
                "describe response does not match the catalog query"
            )
        _safe_text(catalog["driver"], f"catalogs[{index}].driver")
        if "index" in catalog:
            _safe_text(catalog["index"], f"catalogs[{index}].index")
        _relative_posix(catalog["file"], f"catalogs[{index}].file")
        _semantic(catalog["semantic"], f"catalogs[{index}].semantic", allow_label=True)
        counts["semantic_nodes"] += 1
        fields = _bounded_array(catalog["fields"], f"catalogs[{index}].fields")
        direct_names: set[str] = set()
        for field_index, field in enumerate(fields):
            field_value, field_counts = _field(
                field, f"catalogs[{index}].fields[{field_index}]", values_mode=False
            )
            if field_value["name"] in direct_names:
                raise CatalogSemanticRetrievalError("catalog contains duplicate field names")
            direct_names.add(field_value["name"])
            for key in ("fields", "domains", "values", "semantic_nodes"):
                counts[key] += field_counts[key]
    return counts


def _value_semantics(value: Any, label: str) -> dict[str, Any]:
    item = _exact_object(
        value, {"literal", "state", "at", "means", "aka"}, {"literal", "state", "at"}, label
    )
    _safe_text(item["literal"], f"{label}.literal")
    _semantic(
        {key: item[key] for key in ("state", "at", "means", "aka") if key in item},
        label,
        allow_label=False,
    )
    return item


def _validate_values(
    response: Mapping[str, Any], catalog_query: str, field_query: str
) -> dict[str, int]:
    root = _exact_object(
        response,
        {
            "schema",
            "tenant",
            "catalog",
            "field",
            "kind",
            "size",
            "nature",
            "values",
            "note",
            "semantic",
        },
        {"schema", "tenant", "catalog", "field", "kind", "semantic"},
        "values response",
    )
    if type(root["schema"]) is not int or root["schema"] != SCHEMA_VERSION:
        raise CatalogSemanticRetrievalError("schema 1 is not accepted; schema 2 is required")
    _safe_text(root["tenant"], "values response.tenant")
    resolved_catalog = _safe_text(root["catalog"], "values response.catalog")
    response_field = _safe_text(root["field"], "values response.field")
    if resolved_catalog != catalog_query and resolved_catalog.rsplit(".", 1)[-1] != catalog_query:
        raise CatalogSemanticRetrievalError("values response does not match the catalog query")
    if response_field != field_query:
        raise CatalogSemanticRetrievalError("values response does not match the field query")
    domain = {key: root[key] for key in ("kind", "size", "nature", "values") if key in root}
    parsed_domain = _domain(domain, "values response", values_mode=True)
    if parsed_domain["kind"] in {"none", "open"} and "note" not in root:
        raise CatalogSemanticRetrievalError("none/open response needs a note")
    if parsed_domain["kind"] in {"list"} and "note" not in root:
        raise CatalogSemanticRetrievalError("list response needs a note")
    if parsed_domain["kind"] == "enum" and "values" not in root and "note" not in root:
        raise CatalogSemanticRetrievalError("unresolved enum response needs a note")
    if "note" in root:
        _safe_text(root["note"], "values response.note")
        if parsed_domain["kind"] == "inline" or (
            parsed_domain["kind"] == "enum" and "values" in root
        ):
            raise CatalogSemanticRetrievalError("materialized response must not carry a note")
    semantic = _exact_object(
        root["semantic"], {"field", "values"}, {"field"}, "values response.semantic"
    )
    _semantic(semantic["field"], "values response.semantic.field", allow_label=False)
    has_domain_values = "values" in root
    has_semantic_values = "values" in semantic
    if has_domain_values != has_semantic_values:
        raise CatalogSemanticRetrievalError("semantic.values must match materialized values")
    semantic_count = 0
    if has_semantic_values:
        semantic_values = _bounded_array(semantic["values"], "values response.semantic.values")
        domain_values = _bounded_array(root["values"], "values response.values")
        if len(semantic_values) != len(domain_values):
            raise CatalogSemanticRetrievalError("semantic.values is misaligned with values")
        for index, item in enumerate(semantic_values):
            parsed_item = _value_semantics(item, f"values response.semantic.values[{index}]")
            if parsed_item["literal"] != domain_values[index]:
                raise CatalogSemanticRetrievalError("semantic.values literal order is misaligned")
        semantic_count = len(semantic_values)
    return {
        "catalogs": 1,
        "fields": 1,
        "domains": int(parsed_domain["kind"] != "none"),
        "values": len(root.get("values", [])),
        "semantic_nodes": 2,
        "semantic_values": semantic_count,
    }


def _query(operation: Any, catalog: Any, field: Any) -> tuple[str, str | None, str | None]:
    if not isinstance(operation, str) or operation not in {"describe", "values"}:
        raise CatalogSemanticRetrievalError("operation must be describe or values")
    if catalog is not None:
        catalog = _safe_text(catalog, "catalog", maximum=256)
        if "/" in catalog or "\\" in catalog or catalog.startswith("-"):
            raise CatalogSemanticRetrievalError("catalog query is not path-inert")
    if field is not None:
        field = _safe_text(field, "field", maximum=256)
        if "/" in field or "\\" in field or field.startswith("-"):
            raise CatalogSemanticRetrievalError("field query is not path-inert")
    if operation == "describe" and field is not None:
        raise CatalogSemanticRetrievalError("describe does not accept a field")
    if operation == "values" and (catalog is None or field is None):
        raise CatalogSemanticRetrievalError("values requires catalog and field")
    return operation, catalog, field


def _receipt_hash(receipt: Mapping[str, Any]) -> str:
    return _sha256(
        _canonical({key: value for key, value in receipt.items() if key != "receipt_sha256"})
    )


def _receipt_counts_valid(counts: Any) -> None:
    expected = {
        "catalogs",
        "fields",
        "domains",
        "values",
        "semantic_nodes",
        "semantic_values",
        "response_bytes",
    }
    counts = _exact_object(counts, expected, expected, "receipt.counts")
    for key, value in counts.items():
        _integer(
            value,
            f"receipt.counts.{key}",
            maximum=MAX_RESPONSE_BYTES if key == "response_bytes" else MAX_ITEMS,
        )


def validate_catalog_semantic_receipt(
    receipt: Any, *, query: Mapping[str, Any] | None = None
) -> list[str]:
    """Validate a sanitized schema-2 receipt without ever requiring payload text."""
    try:
        body = _exact_object(
            receipt,
            {"query", "pin", "counts", "hashes", "receipt_sha256"},
            {"query", "pin", "counts", "hashes", "receipt_sha256"},
            "receipt",
        )
        _check_limits(body)
        receipt_query = _exact_object(
            body["query"],
            {"operation", "catalog", "field"},
            {"operation", "catalog", "field"},
            "receipt.query",
        )
        operation, catalog, field = _query(
            receipt_query["operation"], receipt_query["catalog"], receipt_query["field"]
        )
        if query is not None and dict(receipt_query) != dict(query):
            raise CatalogSemanticRetrievalError("receipt query differs from requested query")
        pin = _exact_object(body["pin"], {"commit", "schema"}, {"commit", "schema"}, "receipt.pin")
        if pin["commit"] != UPSTREAM_COMMIT or pin["schema"] != SCHEMA_VERSION:
            raise CatalogSemanticRetrievalError("receipt pin differs from schema-2 authority")
        _receipt_counts_valid(body["counts"])
        hashes = _exact_object(
            body["hashes"],
            {"response_sha256", "projection_sha256"},
            {"response_sha256", "projection_sha256"},
            "receipt.hashes",
        )
        _hash(hashes["response_sha256"], "receipt.hashes.response_sha256")
        _hash(hashes["projection_sha256"], "receipt.hashes.projection_sha256")
        _hash(body["receipt_sha256"], "receipt.receipt_sha256")
        if body["receipt_sha256"] != _receipt_hash(body):
            raise CatalogSemanticRetrievalError("receipt self-hash is invalid")
        forbidden = {"text", "literal", "items", "means", "aka", "label"}
        if any(
            key in forbidden or (key == "values" and type(value) is not int)
            for key, value in _walk(body)
        ):
            raise CatalogSemanticRetrievalError(
                "receipt contains editorial text or catalog literals"
            )
        return []
    except (CatalogSemanticRetrievalError, TypeError, ValueError) as error:
        return [str(error)]


def _walk(value: Any) -> list[tuple[str, Any]]:
    found: list[tuple[str, Any]] = []
    if type(value) is dict:
        for key, item in value.items():
            found.append((str(key), item))
            found.extend(_walk(item))
    elif type(value) is list:
        for item in value:
            found.extend(_walk(item))
    return found


@dataclass(frozen=True)
class CatalogSemanticResult:
    """Complete local projection plus its payload-free receipt."""

    projection: dict[str, Any]
    receipt: dict[str, Any]

    def __iter__(self):
        yield self.projection
        yield self.receipt

    def __getitem__(self, key: str) -> dict[str, Any]:
        if key == "projection":
            return self.projection
        if key == "receipt":
            return self.receipt
        raise KeyError(key)


def adapt_catalog_semantic_response(
    operation: str,
    response: bytes | str,
    *,
    catalog: str | None = None,
    field: str | None = None,
) -> CatalogSemanticResult:
    """Parse, validate and project one committed Metis schema-2 response."""
    operation, catalog, field = _query(operation, catalog, field)
    parsed, raw = _parse_response(response)
    counts = (
        _validate_describe(parsed, catalog)
        if operation == "describe"
        else _validate_values(parsed, catalog or "", field or "")
    )
    projection = parsed
    query = {"operation": operation, "catalog": catalog, "field": field}
    receipt: dict[str, Any] = {
        "query": query,
        "pin": {"commit": UPSTREAM_COMMIT, "schema": SCHEMA_VERSION},
        "counts": {**counts, "response_bytes": len(raw)},
        "hashes": {
            "response_sha256": _sha256(raw),
            "projection_sha256": _sha256(_canonical(projection)),
        },
    }
    receipt["receipt_sha256"] = _receipt_hash(receipt)
    errors = validate_catalog_semantic_receipt(receipt, query=query)
    if errors:
        raise CatalogSemanticRetrievalError("generated receipt is invalid: " + "; ".join(errors))
    return CatalogSemanticResult(projection=projection, receipt=receipt)


parse_catalog_semantic_response = adapt_catalog_semantic_response
