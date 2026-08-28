"""Canonical, offline semantic index for validated catalog projections.

The index is a deterministic membership snapshot.  It never asks a model to
invent annotations and it never materializes values for an ``open`` domain.
The module also exposes a small compare-and-swap protocol so callers can keep
index replacement and rollback fail-closed when their snapshot is stale.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

from metis_model1.video_catalog_projection import PROJECTION_CONTRACT

HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
STATES = frozenset({"unannotated", "draft", "reviewed"})
KINDS = frozenset({"none", "inline", "list", "enum", "open"})
FINITE_KINDS = frozenset({"inline", "list", "enum"})
NATURES = frozenset({"reflected", "editorial"})


class SemanticIndexError(ValueError):
    """Raised when an index, snapshot, or CAS operation is incoherent."""


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise SemanticIndexError("value is not canonical JSON") from error


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _hash_ref(value: Any, label: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        raise SemanticIndexError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _text(value: Any, label: str, *, maximum: int = 16_384) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise SemanticIndexError(f"{label} must be a bounded non-empty string")
    if any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in value):
        raise SemanticIndexError(f"{label} contains a control character")
    return value


def _safe_name(value: Any, label: str) -> str:
    value = _text(value, label, maximum=256)
    if any(char in value for char in ("/", "\\", "\x00")):
        raise SemanticIndexError(f"{label} is not path-inert")
    return value


def _relative_file(value: Any, label: str) -> str:
    value = _text(value, label, maximum=1024)
    path = PurePosixPath(value)
    if (
        "\\" in value
        or path.is_absolute()
        or path.as_posix() != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise SemanticIndexError(f"{label} must be a relative POSIX path")
    return value


def _source_at(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"file", "line"}:
        raise SemanticIndexError(f"{label} must contain exactly file and line")
    file_ref = _relative_file(value["file"], f"{label}.file")
    if type(value["line"]) is not int or value["line"] < 1:
        raise SemanticIndexError(f"{label}.line must be positive")
    return {"file": file_ref, "line": value["line"]}


def _semantic(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SemanticIndexError(f"{label} must be an object")
    if set(value) - {"state", "at", "means", "aka", "label"}:
        raise SemanticIndexError(f"{label} has unknown fields")
    state = value.get("state")
    if not isinstance(state, str) or state not in STATES:
        raise SemanticIndexError(f"{label}.state is invalid")
    at = _source_at(value.get("at"), f"{label}.at")
    result: dict[str, Any] = {"state": state, "at": at}
    if "means" in value:
        means = value["means"]
        if not isinstance(means, Mapping) or set(means) != {"text", "at"}:
            raise SemanticIndexError(f"{label}.means is invalid")
        result["means"] = {
            "text": _text(means["text"], f"{label}.means.text"),
            "at": _source_at(means["at"], f"{label}.means.at"),
        }
    if "aka" in value:
        aka = value["aka"]
        if not isinstance(aka, Mapping) or set(aka) != {"items", "at"}:
            raise SemanticIndexError(f"{label}.aka is invalid")
        items = aka["items"]
        if (
            not isinstance(items, list)
            or not items
            or any(
                not isinstance(item, str)
                or not item
                or any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in item)
                for item in items
            )
            or len(items) != len(set(items))
        ):
            raise SemanticIndexError(f"{label}.aka.items is invalid")
        result["aka"] = {
            "items": list(items),
            "at": _source_at(aka["at"], f"{label}.aka.at"),
        }
    if "label" in value:
        label_ref = value["label"]
        if not isinstance(label_ref, Mapping) or set(label_ref) != {"text", "at"}:
            raise SemanticIndexError(f"{label}.label is invalid")
        result["label"] = {
            "text": _text(label_ref["text"], f"{label}.label.text"),
            "at": _source_at(label_ref["at"], f"{label}.label.at"),
        }
    if state == "unannotated" and any(key in result for key in ("means", "aka", "label")):
        raise SemanticIndexError(f"{label}.unannotated cannot carry annotations")
    if state in {"draft", "reviewed"} and "means" not in result:
        raise SemanticIndexError(f"{label}.{state} requires means")
    return result


def _domain(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - {"kind", "size", "nature", "values"}:
        raise SemanticIndexError(f"{label} is invalid")
    kind = value.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        raise SemanticIndexError(f"{label}.kind is invalid")
    result: dict[str, Any] = {"kind": kind}
    if "size" in value:
        if type(value["size"]) is not int or value["size"] < 0:
            raise SemanticIndexError(f"{label}.size is invalid")
        result["size"] = value["size"]
    if "nature" in value:
        if value["nature"] not in NATURES:
            raise SemanticIndexError(f"{label}.nature is invalid")
        result["nature"] = value["nature"]
    if kind in {"none", "open"} and set(result) != {"kind"}:
        raise SemanticIndexError(f"{label} {kind} must not carry a materialized domain")
    values = value.get("values")
    if values is not None:
        if not isinstance(values, list):
            raise SemanticIndexError(f"{label}.values is invalid")
        if kind in {"none", "open"}:
            raise SemanticIndexError(f"{label} {kind} must not materialize values")
        if "size" not in result or result["size"] != len(values):
            raise SemanticIndexError(f"{label}.size does not match values")
        parsed_values: list[Any] = []
        for index, item in enumerate(values):
            if isinstance(item, str):
                parsed_values.append({"literal": _text(item, f"{label}.values[{index}]")})
            elif isinstance(item, Mapping):
                if set(item) - {"literal", "semantic"}:
                    raise SemanticIndexError(f"{label}.values[{index}] has unknown fields")
                literal = _text(item.get("literal"), f"{label}.values[{index}].literal")
                parsed_values.append(dict(item))
                parsed_values[-1]["literal"] = literal
            else:
                raise SemanticIndexError(f"{label}.values[{index}] is invalid")
        result["values"] = parsed_values
    if kind in {"inline", "enum", "list"}:
        if "size" not in result:
            raise SemanticIndexError(f"{label}.{kind} requires a size")
        if result["size"] > 0 and "values" not in result:
            raise SemanticIndexError(
                f"{label}.{kind} normalized projection requires materialized values"
            )
    return result


def _snapshot(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = {"snapshot_id": value}
    if not isinstance(value, Mapping) or not value:
        raise SemanticIndexError("tenant_snapshot is required")
    allowed = {
        "snapshot_id",
        "id",
        "membership_sha256",
        "tenant_revision",
        "catalog_projection_sha256",
    }
    if set(value) - allowed or ("snapshot_id" in value and "id" in value):
        raise SemanticIndexError("tenant_snapshot contains unknown fields")
    result = dict(value)
    snapshot_id = result.get("snapshot_id", result.get("id"))
    result["snapshot_id"] = _safe_name(snapshot_id, "tenant_snapshot.snapshot_id")
    result.pop("id", None)
    for key in ("membership_sha256", "tenant_revision", "catalog_projection_sha256"):
        if key in result:
            _hash_ref(result[key], f"tenant_snapshot.{key}")
    return result


def _index_domain(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) - {"kind", "size", "nature"}:
        raise SemanticIndexError(f"{label} is invalid")
    kind = value.get("kind")
    if kind not in KINDS:
        raise SemanticIndexError(f"{label}.kind is invalid")
    result = {"kind": kind}
    if "size" in value:
        if type(value["size"]) is not int or value["size"] < 0:
            raise SemanticIndexError(f"{label}.size is invalid")
        result["size"] = value["size"]
    if "nature" in value:
        if value["nature"] not in NATURES:
            raise SemanticIndexError(f"{label}.nature is invalid")
        result["nature"] = value["nature"]
    if kind in {"none", "open"} and set(result) != {"kind"}:
        raise SemanticIndexError(f"{label} {kind} must not carry a finite domain")
    if kind in {"inline", "enum", "list"} and "size" not in result:
        raise SemanticIndexError(f"{label} finite domain requires size")
    if kind != "enum" and "nature" in result:
        raise SemanticIndexError(f"{label} nature is valid only for enum")
    return result


def _catalogs(projection: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    if (
        projection.get("schema") != 2
        or projection.get("projection_contract") != PROJECTION_CONTRACT
        or not isinstance(projection.get("catalogs"), list)
    ):
        raise SemanticIndexError(
            "projection must be the normalized schema-2 describe-plus-values contract"
        )
    catalogs = projection["catalogs"]
    if not catalogs:
        raise SemanticIndexError("projection catalogs are empty")
    if any(not isinstance(catalog, Mapping) for catalog in catalogs):
        raise SemanticIndexError("projection catalog is not an object")
    return catalogs


def _entry(
    *,
    node_kind: str,
    catalog: str,
    field: str | None,
    literal: str | None,
    semantic: Mapping[str, Any],
    domain: Mapping[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "node_kind": node_kind,
        "catalog": catalog,
        "field": field,
        "literal": literal,
        "state": semantic["state"],
        "at": semantic["at"],
        "domain": dict(domain),
    }
    for key in ("means", "aka", "label"):
        if key in semantic:
            result[key] = semantic[key]
    return result


def _walk_catalog(catalog: Mapping[str, Any]) -> list[dict[str, Any]]:
    catalog_name = _safe_name(catalog.get("name"), "catalog.name")
    if not isinstance(catalog.get("fields"), list):
        raise SemanticIndexError(f"catalog {catalog_name}.fields is invalid")
    catalog_file = _relative_file(catalog.get("file"), f"catalog {catalog_name}.file")
    catalog_semantic = _semantic(catalog.get("semantic"), f"catalog {catalog_name}.semantic")
    if catalog_semantic["at"]["file"] != catalog_file:
        raise SemanticIndexError(f"catalog {catalog_name} semantic source differs from file")
    entries = [
        _entry(
            node_kind="catalog",
            catalog=catalog_name,
            field=None,
            literal=None,
            semantic=catalog_semantic,
            domain={"kind": "none"},
        )
    ]
    seen_fields: set[str] = set()
    seen_literals: set[tuple[str, str]] = set()

    def walk(fields: list[Any], parent: str | None = None) -> None:
        for raw in fields:
            if not isinstance(raw, Mapping):
                raise SemanticIndexError(f"catalog {catalog_name} field is invalid")
            name = _safe_name(raw.get("name"), f"catalog {catalog_name}.field.name")
            path = name if parent is None else f"{parent}.{name}"
            if path in seen_fields:
                raise SemanticIndexError(f"duplicate field {path}")
            seen_fields.add(path)
            domain = _domain(raw.get("domain"), f"field {path}.domain")
            semantic = _semantic(raw.get("semantic"), f"field {path}.semantic")
            entries.append(
                _entry(
                    node_kind="field",
                    catalog=catalog_name,
                    field=path,
                    literal=None,
                    semantic=semantic,
                    domain={key: value for key, value in domain.items() if key != "values"},
                )
            )
            for item in domain.get("values", []):
                literal = item["literal"]
                key = (path, literal)
                if key in seen_literals:
                    raise SemanticIndexError(f"duplicate literal in field {path}")
                seen_literals.add(key)
                value_semantic = item.get("semantic")
                if not isinstance(value_semantic, Mapping):
                    raise SemanticIndexError(f"value {path} semantic is required and invalid")
                entries.append(
                    _entry(
                        node_kind="value",
                        catalog=catalog_name,
                        field=path,
                        literal=literal,
                        semantic=_semantic(value_semantic, f"value {path}.{literal}.semantic"),
                        domain={key: value for key, value in domain.items() if key != "values"},
                    )
                )
            children = raw.get("fields")
            if children is not None:
                if raw.get("type") != "object" or not isinstance(children, list):
                    raise SemanticIndexError(f"field {path} has incoherent nested fields")
                walk(children, path)

    walk(catalog["fields"])
    return entries


def canonical_index_bytes(index: Mapping[str, Any]) -> bytes:
    """Return the exact byte representation used for index identity."""

    return _canonical(index)


def index_revision(index: Mapping[str, Any]) -> str:
    if not isinstance(index, Mapping):
        raise SemanticIndexError("index must be an object")
    body = {key: value for key, value in index.items() if key != "revision"}
    return _hash(body)


def build_semantic_index(
    projection: Mapping[str, Any],
    *,
    semantic_source_revision: str,
    grammar_revision: str,
    toolchain_revision: str,
    tenant_snapshot: Mapping[str, Any] | str,
) -> dict[str, Any]:
    """Build a canonical index and sanitized receipt from a validated projection."""

    _hash_ref(semantic_source_revision, "semantic_source_revision")
    _hash_ref(grammar_revision, "grammar_revision")
    _hash_ref(toolchain_revision, "toolchain_revision")
    snapshot = _snapshot(tenant_snapshot)
    entries = [entry for catalog in _catalogs(projection) for entry in _walk_catalog(catalog)]
    entries.sort(
        key=lambda item: (
            item["catalog"],
            item["field"] or "",
            item["literal"] or "",
            item["node_kind"],
        )
    )
    identities = [
        (item["node_kind"], item["catalog"], item["field"], item["literal"]) for item in entries
    ]
    if len(identities) != len(set(identities)):
        raise SemanticIndexError("index roster contains duplicate identities")
    body = {
        "schema_version": 1,
        "index_id": "video-semantics/index-v1",
        "semantic_source_revision": semantic_source_revision,
        "grammar_revision": grammar_revision,
        "toolchain_revision": toolchain_revision,
        "tenant_snapshot": snapshot,
        "entries": entries,
    }
    index = {**body, "revision": index_revision(body)}
    receipt = {
        "schema_version": 1,
        "receipt_id": "video-semantics/index-receipt-v1",
        "index_revision": index["revision"],
        "semantic_source_revision": semantic_source_revision,
        "grammar_revision": grammar_revision,
        "toolchain_revision": toolchain_revision,
        "tenant_snapshot_id": snapshot["snapshot_id"],
        "counts": {
            "entries_in": len(entries),
            "entries_out": len(entries),
            "entries_distinct": len(identities),
            "entries_gaps": 0,
            "catalogs": len({item["catalog"] for item in entries}),
            "fields": sum(item["node_kind"] == "field" for item in entries),
            "values": sum(item["node_kind"] == "value" for item in entries),
        },
        "values_redacted": True,
    }
    receipt["receipt_sha256"] = _hash(receipt)
    return {"index": index, "receipt": receipt}


def validate_semantic_index_receipt(receipt: Any) -> list[str]:
    """Validate the exact public receipt shape and its closed arithmetic."""

    if not isinstance(receipt, Mapping):
        return ["receipt must be an object"]
    errors: list[str] = []
    if set(receipt) != {
        "schema_version",
        "receipt_id",
        "index_revision",
        "semantic_source_revision",
        "grammar_revision",
        "toolchain_revision",
        "tenant_snapshot_id",
        "counts",
        "values_redacted",
        "receipt_sha256",
    }:
        errors.append("receipt fields are not the closed public contract")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("receipt_id") != "video-semantics/index-receipt-v1"
    ):
        errors.append("receipt identity is invalid")
    for key in (
        "index_revision",
        "semantic_source_revision",
        "grammar_revision",
        "toolchain_revision",
        "receipt_sha256",
    ):
        try:
            _hash_ref(receipt.get(key), f"receipt.{key}")
        except SemanticIndexError as error:
            errors.append(str(error))
    try:
        _safe_name(receipt.get("tenant_snapshot_id"), "receipt.tenant_snapshot_id")
    except SemanticIndexError as error:
        errors.append(str(error))
    counts = receipt.get("counts")
    if not isinstance(counts, Mapping) or set(counts) != {
        "entries_in",
        "entries_out",
        "entries_distinct",
        "entries_gaps",
        "catalogs",
        "fields",
        "values",
    }:
        errors.append("receipt counts are invalid")
    elif (
        any(type(value) is not int or value < 0 for value in counts.values())
        or counts["entries_in"] != counts["entries_out"]
        or counts["entries_out"] != counts["entries_distinct"]
        or counts["entries_gaps"] != 0
        or counts["entries_in"] != counts["catalogs"] + counts["fields"] + counts["values"]
    ):
        errors.append("receipt counts are not closed")
    if receipt.get("values_redacted") is not True:
        errors.append("receipt values redaction marker is invalid")
    expected = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt.get("receipt_sha256") != _hash(expected):
        errors.append("receipt self-hash is invalid")
    return errors


def validate_semantic_index(index: Any) -> list[str]:
    """Validate index identity and reject stale/tampered canonical material."""

    if not isinstance(index, Mapping):
        return ["index must be an object"]
    errors: list[str] = []
    for key in ("semantic_source_revision", "grammar_revision", "toolchain_revision", "revision"):
        try:
            _hash_ref(index.get(key), f"index.{key}")
        except SemanticIndexError as error:
            errors.append(str(error))
    if index.get("schema_version") != 1 or index.get("index_id") != "video-semantics/index-v1":
        errors.append("index identity is invalid")
    try:
        _snapshot(index.get("tenant_snapshot"))
    except SemanticIndexError as error:
        errors.append(str(error))
    entries = index.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("index entries are missing")
    else:
        identities: list[bytes] = []
        identity_tuples: list[tuple[Any, ...]] = []
        fields: dict[tuple[str, str], Mapping[str, Any]] = {}
        catalogs: set[str] = set()
        value_counts: dict[tuple[str, str], int] = {}
        for entry in entries:
            if not isinstance(entry, Mapping):
                errors.append("index entry is invalid")
                continue
            allowed_keys = {
                "node_kind",
                "catalog",
                "field",
                "literal",
                "state",
                "at",
                "domain",
                "means",
                "aka",
                "label",
            }
            if set(entry) - allowed_keys or not {
                "node_kind",
                "catalog",
                "field",
                "literal",
                "state",
                "at",
                "domain",
            } <= set(entry):
                errors.append("index entry shape is invalid")
            identity = {
                "node_kind": entry.get("node_kind"),
                "catalog": entry.get("catalog"),
                "field": entry.get("field"),
                "literal": entry.get("literal"),
            }
            try:
                identities.append(_canonical(identity))
            except SemanticIndexError:
                errors.append("index entry identity is not canonical")
            identity_tuples.append(
                (
                    entry.get("catalog"),
                    entry.get("field") or "",
                    entry.get("literal") or "",
                    entry.get("node_kind"),
                )
            )
            kind = entry.get("node_kind")
            if not isinstance(kind, str) or kind not in {
                "catalog",
                "field",
                "value",
            }:
                errors.append("index entry node_kind is invalid")
            catalog = entry.get("catalog")
            if not isinstance(catalog, str):
                errors.append("index entry catalog is invalid")
                continue
            try:
                _safe_name(catalog, "index entry catalog")
                semantic = _semantic(
                    {
                        key: entry[key]
                        for key in ("state", "at", "means", "aka", "label")
                        if key in entry
                    },
                    "index entry semantic",
                )
                domain = _index_domain(entry.get("domain"), "index entry domain")
            except SemanticIndexError as error:
                errors.append(str(error))
                continue
            field = entry.get("field")
            literal = entry.get("literal")
            if kind == "catalog":
                catalogs.add(catalog)
                if field is not None or literal is not None or domain != {"kind": "none"}:
                    errors.append("catalog entry identity or domain is invalid")
            elif kind == "field":
                if not isinstance(field, str) or literal is not None:
                    errors.append("field entry identity is invalid")
                else:
                    fields[(catalog, field)] = entry
            elif kind == "value":
                if not isinstance(field, str) or not isinstance(literal, str) or not literal:
                    errors.append("value entry identity is invalid")
                else:
                    value_counts[(catalog, field)] = value_counts.get((catalog, field), 0) + 1
            if (
                isinstance(kind, str)
                and kind
                in {
                    "field",
                    "value",
                }
                and not isinstance(field, str)
            ):
                errors.append("index entry field is invalid")
            if kind == "value" and not isinstance(literal, str):
                errors.append("value entry literal is missing")
            if isinstance(domain, Mapping) and domain.get("kind") == "open" and literal is not None:
                errors.append("open domain contains a materialized literal")
            if kind != "catalog" and "label" in semantic:
                errors.append("label is valid only on catalog entries")
        if len(identities) != len(set(identities)):
            errors.append("index roster contains duplicate identities")
        if identity_tuples != sorted(identity_tuples):
            errors.append("index entries are not in canonical order")
        for (catalog, field), entry in fields.items():
            if catalog not in catalogs:
                errors.append(f"field {catalog}.{field} has no catalog entry")
            domain = entry["domain"]
            expected = domain.get("size", 0) if domain.get("kind") in FINITE_KINDS else 0
            if value_counts.get((catalog, field), 0) != expected:
                errors.append(f"field {catalog}.{field} value roster does not match domain size")
        for entry in entries:
            if not isinstance(entry, Mapping) or entry.get("node_kind") != "value":
                continue
            key = (entry.get("catalog"), entry.get("field"))
            parent = fields.get(key)
            if parent is None:
                errors.append("value entry has no field parent")
            elif entry.get("domain") != parent.get("domain"):
                errors.append("value entry domain differs from field parent")
    try:
        if index.get("revision") != index_revision(index):
            errors.append("index revision is stale or tampered")
    except SemanticIndexError as error:
        errors.append(str(error))
    return errors


def _match_spans(text: str, phrase: str) -> list[tuple[int, int]]:
    """Return bounded, Unicode-aware whole-surface matches.

    Catalog annotations are retrieval data, not executable model prompts.  The
    deterministic resolver therefore accepts only literal surfaces present in
    the pinned index and refuses substring matches inside a larger word.
    """

    folded_text = text.casefold()
    folded_phrase = phrase.casefold().strip()
    if not folded_phrase:
        return []
    pattern = re.compile(r"(?<!\w)" + re.escape(folded_phrase) + r"(?!\w)")
    return [(match.start(), match.end()) for match in pattern.finditer(folded_text)]


def _contains(text: str, phrase: str) -> bool:
    return bool(_match_spans(text, phrase))


def _maximal_match_spans(matches: list[dict[str, Any]]) -> list[tuple[int, int]]:
    """Keep only surfaces not strictly contained by a more specific match.

    Natural labels can contain another valid catalog surface: ``Italia 1``
    contains the country literal ``Italia``.  Treating both spans as independent
    concepts makes the shorter surface manufacture an ambiguity before the
    full channel label can win.  Equal spans still compete by rank/identity and
    overlapping-but-not-contained spans remain separate; only strict lexical
    containment is suppressed.
    """

    spans = sorted(
        {item["span"] for item in matches},
        key=lambda span: (span[0], -span[1]),
    )
    maximal: list[tuple[int, int]] = []
    furthest_end = -1
    for span in spans:
        if span[1] <= furthest_end:
            continue
        maximal.append(span)
        furthest_end = span[1]
    return sorted(maximal)


def _catalog_filter(
    index: Mapping[str, Any], request: str, catalog: str | None
) -> tuple[list[str], str | None]:
    catalogs = sorted({entry["catalog"] for entry in index["entries"]})
    if catalog is not None:
        if catalog not in catalogs:
            return [], "requested catalog is not in the membership snapshot"
        return [catalog], None
    catalog_entries = {
        entry["catalog"]: entry for entry in index["entries"] if entry["node_kind"] == "catalog"
    }
    named: list[str] = []
    for name in catalogs:
        entry = catalog_entries[name]
        short_name = name.rsplit(".", 1)[-1]
        surfaces = {name, short_name, "@" + short_name}
        if entry.get("state") == "reviewed":
            label = entry.get("label")
            if isinstance(label, Mapping):
                surfaces.add(label["text"])
            aka = entry.get("aka")
            if isinstance(aka, Mapping):
                surfaces.update(aka["items"])
        if any(_contains(request, surface) for surface in surfaces):
            named.append(name)
    if named:
        return named, None
    if len(catalogs) == 1:
        return catalogs, None
    return [], "multiple catalogs require explicit confirmation"


def resolve_grounding(
    index: Mapping[str, Any], request: str, *, catalog: str | None = None
) -> dict[str, Any]:
    """Resolve an exact multi-concept grounding map from snapshot membership.

    A natural-language request commonly names several metadata keys and values.
    Resolution is therefore performed per matched surface rather than by taking
    one global winner.  A tie for the same surface remains fail-closed and asks
    for clarification.
    """

    errors = validate_semantic_index(index)
    if errors:
        raise SemanticIndexError("invalid index: " + "; ".join(errors))
    request = _text(request, "request", maximum=16_384)
    allowed_catalogs, catalog_error = _catalog_filter(index, request, catalog)
    if catalog_error:
        return {
            "status": "clarify" if "multiple" in catalog_error else "unsupported",
            "reason": catalog_error,
            "candidates": [],
            "selections": [],
            "lookups": [],
            "lookup": None,
        }
    matches: list[dict[str, Any]] = []
    for entry in index["entries"]:
        if entry["node_kind"] not in {"field", "value"} or entry["catalog"] not in allowed_catalogs:
            continue
        field = entry["field"] or ""
        literal = entry.get("literal")
        surfaces: list[tuple[int, str, str]] = []
        if entry["node_kind"] == "field":
            surfaces.append((0, "technical_name_exact", field))
            leaf = field.rsplit(".", 1)[-1]
            if leaf != field:
                surfaces.append((0, "technical_leaf_exact", leaf))
        elif literal is not None:
            surfaces.append((1, "literal_exact", literal))
        if entry.get("state") == "reviewed":
            aka_items = (
                entry.get("aka", {}).get("items", [])
                if isinstance(entry.get("aka"), Mapping)
                else []
            )
            surfaces.extend((2, "reviewed_aka_exact", item) for item in aka_items)
            means = (
                entry.get("means", {}).get("text")
                if isinstance(entry.get("means"), Mapping)
                else None
            )
            if isinstance(means, str):
                surfaces.append((3, "reviewed_means_candidate", means))
        for rank, matched_by, surface in surfaces:
            for start, end in _match_spans(request, surface):
                matches.append(
                    {
                        "entry": entry,
                        "rank": rank,
                        "matched_by": matched_by,
                        "span": (start, end),
                    }
                )
    if not matches:
        return {
            "status": "unsupported",
            "reason": "no exact snapshot-member grounding",
            "candidates": [],
            "selections": [],
            "lookups": [],
            "lookup": None,
        }

    best_by_span: list[dict[str, Any]] = []
    for span in _maximal_match_spans(matches):
        span_matches = [item for item in matches if item["span"] == span]
        best_rank = min(item["rank"] for item in span_matches)
        best = [item for item in span_matches if item["rank"] == best_rank]
        identities = {
            (item["entry"]["catalog"], item["entry"]["field"], item["entry"].get("literal"))
            for item in best
        }
        if len(identities) != 1:
            candidates = [
                {
                    "catalog": item["entry"]["catalog"],
                    "field": item["entry"]["field"],
                    "literal": item["entry"].get("literal"),
                    "matched_by": item["matched_by"],
                }
                for item in best
            ]
            candidates.sort(
                key=lambda item: (
                    item["catalog"],
                    item["field"] or "",
                    item["literal"] or "",
                    item["matched_by"],
                )
            )
            return {
                "status": "clarify",
                "reason": "grounding candidates tie for the same request surface",
                "candidates": candidates,
                "selections": [],
                "lookups": [],
                "lookup": None,
            }
        best_by_span.append(best[0])

    selected_by_identity: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    for item in best_by_span:
        identity = (
            item["entry"]["catalog"],
            item["entry"]["field"],
            item["entry"].get("literal"),
        )
        previous = selected_by_identity.get(identity)
        if previous is None or (item["rank"], item["span"]) < (
            previous["rank"],
            previous["span"],
        ):
            selected_by_identity[identity] = item
    ordered = sorted(
        selected_by_identity.values(),
        key=lambda item: (
            item["span"],
            item["rank"],
            item["entry"]["catalog"],
            item["entry"]["field"],
            item["entry"].get("literal") or "",
        ),
    )
    selections = [
        {
            "catalog": item["entry"]["catalog"],
            "field": item["entry"]["field"],
            "literal": item["entry"].get("literal"),
            "domain": item["entry"]["domain"],
            "matched_by": item["matched_by"],
        }
        for item in ordered
    ]
    lookups = [
        {
            "mode": "exact_on_demand",
            "owner": "retrieval_engine",
            "catalog": selection["catalog"],
            "field": selection["field"],
            "values": None,
        }
        for selection in selections
        if selection["literal"] is None and selection["domain"]["kind"] == "open"
    ]
    return {
        "status": "resolved",
        "reason": "exact snapshot-member grounding map",
        "selected": selections[0] if len(selections) == 1 else None,
        "selections": selections,
        "candidates": [],
        "lookup": lookups[0] if len(lookups) == 1 else None,
        "lookups": lookups,
    }


def cas_replace_index(
    current: Mapping[str, Any], replacement: Mapping[str, Any], *, expected_revision: str
) -> dict[str, Any]:
    """Replace an index only when the caller's preimage revision is current."""

    _hash_ref(expected_revision, "expected_revision")
    if validate_semantic_index(current):
        raise SemanticIndexError("current index is invalid")
    if validate_semantic_index(replacement):
        raise SemanticIndexError("replacement index is invalid")
    if current["revision"] != expected_revision:
        raise SemanticIndexError("stale index preimage")
    transaction = {
        "operation": "replace",
        "preimage_revision": current["revision"],
        "preimage_sha256": _hash(current),
        "postimage_revision": replacement["revision"],
        "postimage_sha256": _hash(replacement),
        "preimage": dict(current),
    }
    return {"index": dict(replacement), "transaction": transaction}


def rollback_index(
    current: Mapping[str, Any], transaction: Mapping[str, Any], *, expected_revision: str
) -> dict[str, Any]:
    """Rollback a prior CAS transaction, rejecting stale or mismatched state."""

    _hash_ref(expected_revision, "expected_revision")
    if validate_semantic_index(current):
        raise SemanticIndexError("current index is invalid")
    if not isinstance(transaction, Mapping) or transaction.get("operation") != "replace":
        raise SemanticIndexError("transaction is invalid")
    if current["revision"] != expected_revision:
        raise SemanticIndexError("stale rollback preimage")
    if current["revision"] != transaction.get("postimage_revision") or _hash(
        current
    ) != transaction.get("postimage_sha256"):
        raise SemanticIndexError("rollback CAS postimage mismatch")
    preimage = transaction.get("preimage")
    if not isinstance(preimage, Mapping) or _hash(preimage) != transaction.get("preimage_sha256"):
        raise SemanticIndexError("rollback preimage is missing or tampered")
    if validate_semantic_index(preimage):
        raise SemanticIndexError("rollback preimage index is invalid")
    return {
        "index": dict(preimage),
        "transaction": {
            "operation": "rollback",
            "preimage_revision": current["revision"],
            "postimage_revision": preimage["revision"],
            "postimage_sha256": _hash(preimage),
        },
    }


build_index = build_semantic_index
replace_index_cas = cas_replace_index
rollback_cas = rollback_index


__all__ = [
    "SemanticIndexError",
    "build_index",
    "build_semantic_index",
    "canonical_index_bytes",
    "cas_replace_index",
    "index_revision",
    "replace_index_cas",
    "resolve_grounding",
    "rollback_cas",
    "rollback_index",
    "validate_semantic_index",
    "validate_semantic_index_receipt",
]
