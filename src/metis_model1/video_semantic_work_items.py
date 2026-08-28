"""Deterministically materialize reviewed inputs into semantic work items.

This module is an intentionally mechanical bridge.  It does not author or
review semantics.  A validated schema-2 projection (or its closed local census)
owns target membership and source order, source-file hashes own the patch
preimage, and host-provided technical metadata owns invariants that are absent
from a census.  Proposals may contribute only draft semantics and editorial
review metadata.

The returned ``technical_roster`` is directly consumable by
``video_semantic_patch.render_candidate_patch``.  Alias evidence remains
out-of-band in the returned ``aka_evidence`` mapping, as required by that
renderer.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from metis_model1.provenance import canonical_json_hash
from metis_model1.video_local_census import (
    build_local_census,
    validate_local_census_receipt,
)
from metis_model1.video_semantics_contracts import validate_work_item

HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
PATH_RE = re.compile(r"^(?!/)(?!.*\\)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._@+/-]+$")
OPAQUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")

TECHNICAL_KEYS = frozenset(
    {"type", "modifiers", "domain_kind", "declared_cardinality", "observed_cardinality"}
)
TARGET_KEYS = frozenset({"catalog", "field", "literal"})
TECHNICAL_RECORD_KEYS = frozenset(
    {"target", "repository_commit", "path", "preimage_sha256", "technical"}
)
PROPOSAL_REQUIRED_KEYS = frozenset(
    {
        "target",
        "means",
        "aka",
        "evidence_refs",
        "editorial_rules",
        "ambiguities",
        "author",
        "reviewer",
    }
)
PROPOSAL_OPTIONAL_KEYS = frozenset({"aka_evidence_refs"})
DOMAIN_KINDS = frozenset({"inline", "enum", "list", "open", "none"})
NODE_KINDS = frozenset({"catalog", "field", "value"})
SEMANTIC_STATES = frozenset({"unannotated", "draft", "reviewed"})
FORBIDDEN_KEYS = frozenset(
    {
        "password",
        "passwd",
        "token",
        "authorization",
        "bearer",
        "secret",
        "api_key",
        "apikey",
        "private_key",
        "_source",
        "raw_source",
        "source_text",
        "source_payload",
        "document_payload",
        "manual",
        "model_output",
        "raw_output",
        "chain_of_thought",
    }
)


class VideoSemanticWorkItemError(ValueError):
    """Raised when materialization cannot prove an exact technical target."""


def _hash(value: Any) -> str:
    try:
        return "sha256:" + canonical_json_hash(value)
    except (TypeError, ValueError) as error:
        raise VideoSemanticWorkItemError("material is not canonical JSON") from error


def _assert_sanitized(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise VideoSemanticWorkItemError(f"{path} contains a non-string key")
            if key.lower() in FORBIDDEN_KEYS:
                raise VideoSemanticWorkItemError(f"{path}.{key} is a forbidden raw/sensitive field")
            _assert_sanitized(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        for index, item in enumerate(value):
            _assert_sanitized(item, f"{path}[{index}]")
    elif isinstance(value, str) and CONTROL_RE.search(value):
        raise VideoSemanticWorkItemError(f"{path} contains an unsafe control character")


def _text(value: Any, label: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise VideoSemanticWorkItemError(f"{label} must be a bounded non-empty string")
    if CONTROL_RE.search(value):
        raise VideoSemanticWorkItemError(f"{label} contains an unsafe control character")
    return value


def _opaque(value: Any, label: str) -> str:
    value = _text(value, label, maximum=128)
    if OPAQUE_RE.fullmatch(value) is None:
        raise VideoSemanticWorkItemError(f"{label} must be an opaque identifier")
    return value


def _hash_ref(value: Any, label: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        raise VideoSemanticWorkItemError(f"{label} must be a lowercase sha256 identity")
    return value


def _path(value: Any, label: str) -> str:
    if not isinstance(value, str) or PATH_RE.fullmatch(value) is None:
        raise VideoSemanticWorkItemError(f"{label} must be a safe relative path")
    return value


def _as_sequence(value: Any, label: str, *, single_keys: frozenset[str]) -> list[Any]:
    if isinstance(value, Mapping):
        if set(value).issubset(single_keys) and set(value):
            return [value]
        if not value:
            raise VideoSemanticWorkItemError(f"{label} must not be empty")
        if any(not isinstance(key, str) or not key for key in value):
            raise VideoSemanticWorkItemError(f"{label} mapping keys must be non-empty strings")
        return list(value.values())
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        if not value:
            raise VideoSemanticWorkItemError(f"{label} must not be empty")
        return list(value)
    raise VideoSemanticWorkItemError(f"{label} must be a mapping or array")


def _target(value: Any, label: str) -> tuple[str, str | None, str | None]:
    if not isinstance(value, Mapping) or set(value) != TARGET_KEYS:
        raise VideoSemanticWorkItemError(f"{label} must contain only catalog, field and literal")
    catalog = _opaque(value["catalog"], f"{label}.catalog")
    field = value["field"]
    literal = value["literal"]
    if field is not None:
        field = _text(field, f"{label}.field", maximum=512)
        if OPAQUE_RE.fullmatch(field) is None:
            raise VideoSemanticWorkItemError(f"{label}.field must be an opaque field path")
    if literal is not None:
        literal = _text(literal, f"{label}.literal", maximum=1024)
    if literal is not None and field is None:
        raise VideoSemanticWorkItemError(f"{label}.literal requires a field")
    return catalog, field, literal


def _node_kind(identity: tuple[str, str | None, str | None]) -> str:
    if identity[1] is None:
        return "catalog"
    return "field" if identity[2] is None else "value"


def _technical(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TECHNICAL_KEYS:
        raise VideoSemanticWorkItemError(f"{label} has unknown or missing technical keys")
    _assert_sanitized(value, label)
    type_name = _text(value["type"], f"{label}.type", maximum=64)
    modifiers = value["modifiers"]
    if (
        not isinstance(modifiers, list)
        or any(not isinstance(item, str) or not item or len(item) > 64 for item in modifiers)
        or len(modifiers) != len(set(modifiers))
    ):
        raise VideoSemanticWorkItemError(f"{label}.modifiers is invalid")
    domain_kind = value["domain_kind"]
    if not isinstance(domain_kind, str) or domain_kind not in DOMAIN_KINDS:
        raise VideoSemanticWorkItemError(f"{label}.domain_kind is invalid")
    cardinalities: dict[str, int | None] = {}
    for key in ("declared_cardinality", "observed_cardinality"):
        item = value[key]
        if item is not None and (type(item) is not int or item < 0):
            raise VideoSemanticWorkItemError(f"{label}.{key} is invalid")
        cardinalities[key] = item
    return {
        "type": type_name,
        "modifiers": list(modifiers),
        "domain_kind": domain_kind,
        **cardinalities,
    }


def _source_preimages(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise VideoSemanticWorkItemError("source_preimages must be a non-empty mapping")
    result: dict[str, str] = {}
    for raw_path, raw_hash in value.items():
        path = _path(raw_path, "source_preimages path")
        if path in result:
            raise VideoSemanticWorkItemError("source_preimages contains duplicate paths")
        result[path] = _hash_ref(raw_hash, f"source_preimages[{path}]")
    return result


def _split_source_locator(value: Any, label: str) -> tuple[str, int]:
    if not isinstance(value, str) or ":" not in value:
        raise VideoSemanticWorkItemError(f"{label} is invalid")
    path_value, raw_line = value.rsplit(":", 1)
    path = _path(path_value, label)
    try:
        line = int(raw_line)
    except ValueError as error:
        raise VideoSemanticWorkItemError(f"{label} is invalid") from error
    if line < 1 or str(line) != raw_line:
        raise VideoSemanticWorkItemError(f"{label} is invalid")
    return path, line


def _validate_census(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Mapping) or set(value) != {"schema_version", "roster", "receipt"}:
        raise VideoSemanticWorkItemError("local census must be the closed census bundle")
    if value.get("schema_version") != 1:
        raise VideoSemanticWorkItemError("local census schema version is invalid")
    receipt = value["receipt"]
    errors = validate_local_census_receipt(receipt)
    if errors:
        raise VideoSemanticWorkItemError(f"local census receipt is invalid: {'; '.join(errors)}")
    roster = value["roster"]
    if not isinstance(roster, list) or not roster:
        raise VideoSemanticWorkItemError("local census roster must be a non-empty array")
    assert isinstance(receipt, Mapping)
    if receipt["node_count"] != len(roster) or receipt["counts"] != {
        "items_in": len(roster),
        "items_out": len(roster),
        "items_distinct": len(roster),
        "items_gaps": 0,
    }:
        raise VideoSemanticWorkItemError("local census receipt counts differ from its roster")
    if any(not isinstance(entry, Mapping) for entry in roster):
        raise VideoSemanticWorkItemError("local census roster contains a non-object entry")
    stable = {
        "schema_version": 1,
        "contract_id": "video-local-census-v1",
        "semantic_source_revision": receipt["semantic_source_revision"],
        "tenant_ref": receipt["tenant_ref"],
        "catalog_ref": receipt["catalog_ref"],
        "projection_schema": 2,
        "entries": [
            {key: item for key, item in entry.items() if key != "literal"} for entry in roster
        ],
    }
    if _hash(stable) != receipt["roster_sha256"]:
        raise VideoSemanticWorkItemError("local census roster differs from its receipt")

    seen: set[tuple[str, str | None, str | None]] = set()
    parsed: list[dict[str, Any]] = []
    states: Counter[str] = Counter()
    domains: Counter[str] = Counter()
    for index, raw in enumerate(roster):
        assert isinstance(raw, Mapping)
        _assert_sanitized(raw, f"local census roster[{index}]")
        kind = raw.get("node_kind")
        if not isinstance(kind, str) or kind not in NODE_KINDS:
            raise VideoSemanticWorkItemError(f"local census roster[{index}].node_kind is invalid")
        expected_keys = {
            "node_kind",
            "catalog",
            "field",
            "locator",
            "source_locator",
            "state",
            "domain",
        }
        if kind == "value":
            expected_keys.add("literal")
        if set(raw) != expected_keys:
            raise VideoSemanticWorkItemError(
                f"local census roster[{index}] has unknown or missing fields"
            )
        identity = _target(
            {
                "catalog": raw.get("catalog"),
                "field": raw.get("field"),
                "literal": raw.get("literal"),
            },
            f"local census roster[{index}] target",
        )
        if _node_kind(identity) != kind:
            raise VideoSemanticWorkItemError(f"local census roster[{index}] target kind disagrees")
        if identity in seen:
            raise VideoSemanticWorkItemError("local census contains duplicate targets")
        seen.add(identity)
        path, _ = _split_source_locator(
            raw.get("source_locator"), f"local census roster[{index}].source_locator"
        )
        expected_locator = _hash(
            {
                "node_kind": kind,
                "catalog": identity[0],
                "field": identity[1],
                "literal": identity[2],
                "source_locator": raw["source_locator"],
            }
        )
        if raw.get("locator") != expected_locator:
            raise VideoSemanticWorkItemError(f"local census roster[{index}].locator is invalid")
        state = raw.get("state")
        if not isinstance(state, str) or state not in SEMANTIC_STATES:
            raise VideoSemanticWorkItemError(f"local census roster[{index}].state is invalid")
        domain = raw.get("domain")
        if not isinstance(domain, Mapping):
            raise VideoSemanticWorkItemError(f"local census roster[{index}].domain is invalid")
        domain_kind = domain.get("kind")
        if not isinstance(domain_kind, str) or domain_kind not in DOMAIN_KINDS:
            raise VideoSemanticWorkItemError(f"local census roster[{index}].domain is invalid")
        allowed_domain_keys = {"kind"}
        if domain_kind in {"inline", "enum", "list"}:
            allowed_domain_keys.add("size")
            size = domain.get("size")
            if type(size) is not int or size < 0:
                raise VideoSemanticWorkItemError(
                    f"local census roster[{index}].domain size is invalid"
                )
            if "nature" in domain:
                allowed_domain_keys.add("nature")
                if not isinstance(domain["nature"], str) or domain["nature"] not in {
                    "editorial",
                    "reflected",
                }:
                    raise VideoSemanticWorkItemError(
                        f"local census roster[{index}].domain nature is invalid"
                    )
        if set(domain) != allowed_domain_keys:
            raise VideoSemanticWorkItemError(
                f"local census roster[{index}].domain has unknown or incoherent fields"
            )
        if kind == "catalog" and domain != {"kind": "none"}:
            raise VideoSemanticWorkItemError("catalog census node has a non-empty domain")
        states[state] += 1
        domains[domain_kind] += 1
        parsed.append(
            {
                "identity": identity,
                "node_kind": kind,
                "path": path,
                "order": index,
                "domain": dict(domain),
            }
        )
    if receipt["catalog_count"] != sum(item["node_kind"] == "catalog" for item in parsed):
        raise VideoSemanticWorkItemError("local census catalog count differs from its roster")
    if receipt["field_count"] != sum(item["node_kind"] == "field" for item in parsed):
        raise VideoSemanticWorkItemError("local census field count differs from its roster")
    if receipt["value_count"] != sum(item["node_kind"] == "value" for item in parsed):
        raise VideoSemanticWorkItemError("local census value count differs from its roster")
    if receipt["state_counts"] != dict(sorted(states.items())):
        raise VideoSemanticWorkItemError("local census state counts differ from its roster")
    if receipt["domain_counts"] != dict(sorted(domains.items())):
        raise VideoSemanticWorkItemError("local census domain counts differ from its roster")
    fields = {
        (item["identity"][0], item["identity"][1]): item
        for item in parsed
        if item["node_kind"] == "field"
    }
    for item in parsed:
        if item["node_kind"] != "value":
            continue
        parent = fields.get((item["identity"][0], item["identity"][1]))
        if parent is None or parent["domain"] != item["domain"]:
            raise VideoSemanticWorkItemError("local census value has no coherent field parent")
    return parsed


def _projection_roster(value: Mapping[str, Any]) -> list[dict[str, Any]]:
    try:
        census = build_local_census(value, semantic_source_revision=_hash(value))
    except ValueError as error:
        raise VideoSemanticWorkItemError(
            f"projection is not a validated schema-2 input: {error}"
        ) from error
    parsed = _validate_census(census)
    technical_by_identity: dict[tuple[str, str | None, str | None], dict[str, Any]] = {}

    def walk_fields(catalog: str, fields: Any, parent: str | None = None) -> None:
        assert isinstance(fields, list)
        for field in fields:
            assert isinstance(field, Mapping)
            name = field["name"]
            field_path = name if parent is None else f"{parent}.{name}"
            domain = field["domain"]
            kind = domain["kind"]
            declared = domain.get("size") if kind in {"inline", "enum", "list"} else None
            values = domain.get("values", [])
            observed = len(values) if kind in {"inline", "enum", "list"} else None
            technical = _technical(
                {
                    "type": field["type"],
                    "modifiers": field["modifiers"],
                    "domain_kind": kind,
                    "declared_cardinality": declared,
                    "observed_cardinality": observed,
                },
                f"projection field {catalog}.{field_path}",
            )
            technical_by_identity[(catalog, field_path, None)] = technical
            for item in values:
                technical_by_identity[(catalog, field_path, item["literal"])] = deepcopy(technical)
            children = field.get("fields")
            if children is not None:
                walk_fields(catalog, children, field_path)

    for catalog in value["catalogs"]:
        name = catalog["name"]
        technical_by_identity[(name, None, None)] = {
            "type": "catalog",
            "modifiers": [],
            "domain_kind": "none",
            "declared_cardinality": None,
            "observed_cardinality": None,
        }
        walk_fields(name, catalog["fields"])
    if set(technical_by_identity) != {item["identity"] for item in parsed}:
        raise VideoSemanticWorkItemError("projection technical roster differs from its census")
    return [{**item, "technical": technical_by_identity[item["identity"]]} for item in parsed]


def _technical_records(
    value: Any,
    *,
    repository_commit: str,
    source_preimages: Mapping[str, str],
) -> dict[tuple[str, str | None, str | None], dict[str, Any]]:
    records = _as_sequence(value, "technical_metadata", single_keys=TECHNICAL_RECORD_KEYS)
    result: dict[tuple[str, str | None, str | None], dict[str, Any]] = {}
    for index, raw in enumerate(records):
        if not isinstance(raw, Mapping) or set(raw) != TECHNICAL_RECORD_KEYS:
            raise VideoSemanticWorkItemError(
                f"technical_metadata[{index}] has unknown or missing keys"
            )
        _assert_sanitized(raw, f"technical_metadata[{index}]")
        identity = _target(raw["target"], f"technical_metadata[{index}].target")
        if identity in result:
            raise VideoSemanticWorkItemError("technical_metadata contains duplicate targets")
        if raw["repository_commit"] != repository_commit:
            raise VideoSemanticWorkItemError("technical metadata repository commit drift")
        path = _path(raw["path"], f"technical_metadata[{index}].path")
        preimage = _hash_ref(raw["preimage_sha256"], f"technical_metadata[{index}].preimage_sha256")
        if source_preimages.get(path) != preimage:
            raise VideoSemanticWorkItemError("technical metadata path/preimage drift")
        result[identity] = {
            "path": path,
            "preimage_sha256": preimage,
            "technical": _technical(raw["technical"], f"technical_metadata[{index}].technical"),
        }
    return result


def _canonical_roster(
    source: Mapping[str, Any],
    *,
    repository_commit: str,
    source_preimages: Mapping[str, str],
    technical_metadata: Any | None,
) -> list[dict[str, Any]]:
    if source.get("projection_contract") is not None:
        nodes = _projection_roster(source)
        supplied = (
            None
            if technical_metadata is None
            else _technical_records(
                technical_metadata,
                repository_commit=repository_commit,
                source_preimages=source_preimages,
            )
        )
    else:
        nodes = _validate_census(source)
        if technical_metadata is None:
            raise VideoSemanticWorkItemError(
                "technical_metadata is required when materializing from a local census"
            )
        supplied = _technical_records(
            technical_metadata,
            repository_commit=repository_commit,
            source_preimages=source_preimages,
        )
    source_paths = {item["path"] for item in nodes}
    if set(source_preimages) != source_paths:
        raise VideoSemanticWorkItemError("source preimage roster differs from source-file roster")
    identities = {item["identity"] for item in nodes}
    if supplied is not None and set(supplied) != identities:
        raise VideoSemanticWorkItemError("technical metadata roster differs from source roster")

    roster: list[dict[str, Any]] = []
    for item in nodes:
        identity = item["identity"]
        expected_technical = item.get("technical")
        if supplied is None:
            material = {
                "path": item["path"],
                "preimage_sha256": source_preimages[item["path"]],
                "technical": expected_technical,
            }
        else:
            material = supplied[identity]
            if material["path"] != item["path"]:
                raise VideoSemanticWorkItemError("technical metadata source path drift")
            if expected_technical is not None and material["technical"] != expected_technical:
                raise VideoSemanticWorkItemError("technical metadata changes projection invariants")
        roster.append(
            {
                "canonical_locator": {
                    "repository_commit": repository_commit,
                    "path": material["path"],
                    "catalog": identity[0],
                    "field_path": identity[1],
                    "literal": identity[2],
                    "preimage_sha256": material["preimage_sha256"],
                },
                "technical": deepcopy(material["technical"]),
                "order": item["order"],
            }
        )
    return roster


def _strings(value: Any, label: str, *, maximum: int, opaque: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise VideoSemanticWorkItemError(f"{label} must be an array")
    result = [
        _opaque(item, f"{label}[{index}]")
        if opaque
        else _text(item, f"{label}[{index}]", maximum=maximum)
        for index, item in enumerate(value)
    ]
    if len(result) != len(set(result)):
        raise VideoSemanticWorkItemError(f"{label} must contain distinct values")
    return result


def _proposal(value: Any, index: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise VideoSemanticWorkItemError(f"proposal {index} is not an object")
    _assert_sanitized(value, f"proposals[{index}]")
    keys = set(value)
    if not PROPOSAL_REQUIRED_KEYS.issubset(keys) or keys - (
        PROPOSAL_REQUIRED_KEYS | PROPOSAL_OPTIONAL_KEYS
    ):
        raise VideoSemanticWorkItemError(f"proposal {index} has unknown or missing fields")
    identity = _target(value["target"], f"proposal {index}.target")
    means = _text(value["means"], f"proposal {index}.means", maximum=4096)
    aliases = _strings(value["aka"], f"proposal {index}.aka", maximum=256)
    evidence = _strings(
        value["evidence_refs"], f"proposal {index}.evidence_refs", maximum=128, opaque=True
    )
    if not evidence:
        raise VideoSemanticWorkItemError(f"proposal {index}.evidence_refs must not be empty")
    aka_evidence = _strings(
        value.get("aka_evidence_refs", []),
        f"proposal {index}.aka_evidence_refs",
        maximum=128,
        opaque=True,
    )
    if aliases and not aka_evidence:
        raise VideoSemanticWorkItemError(f"proposal {index} has aka without explicit evidence")
    if not aliases and aka_evidence:
        raise VideoSemanticWorkItemError(f"proposal {index} has aka evidence without aliases")
    if not set(aka_evidence).issubset(evidence):
        raise VideoSemanticWorkItemError(f"proposal {index} aka evidence is outside evidence_refs")
    ambiguities = _strings(value["ambiguities"], f"proposal {index}.ambiguities", maximum=1024)
    author = _opaque(value["author"], f"proposal {index}.author")
    reviewer = value["reviewer"]
    if reviewer is not None:
        reviewer = _opaque(reviewer, f"proposal {index}.reviewer")
    rules = value["editorial_rules"]
    if not isinstance(rules, Mapping):
        raise VideoSemanticWorkItemError(f"proposal {index}.editorial_rules must be an object")
    return {
        "identity": identity,
        "means": means,
        "aka": aliases,
        "aka_evidence_refs": aka_evidence,
        "evidence_refs": evidence,
        "editorial_rules": deepcopy(dict(rules)),
        "ambiguities": ambiguities,
        "author": author,
        "reviewer": reviewer,
    }


def build_video_semantic_work_items(
    catalog_source: Mapping[str, Any],
    proposals: Mapping[str, Mapping[str, Any]] | Sequence[Mapping[str, Any]],
    *,
    repository_commit: str,
    source_preimages: Mapping[str, str],
    technical_metadata: Mapping[str, Mapping[str, Any]] | Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build schema-valid draft work items and an immutable technical roster.

    ``catalog_source`` is either a normalized schema-2 projection or a closed
    local-census bundle.  A projection carries its own technical invariants;
    supplied ``technical_metadata`` is then optional but, when present, must
    match the entire projection exactly.  A census omits field type/modifiers,
    so a complete metadata roster is mandatory.
    """

    if not isinstance(catalog_source, Mapping):
        raise VideoSemanticWorkItemError("catalog_source must be an object")
    _assert_sanitized(catalog_source, "catalog_source")
    if not isinstance(repository_commit, str) or COMMIT_RE.fullmatch(repository_commit) is None:
        raise VideoSemanticWorkItemError("repository_commit must be an exact lowercase Git OID")
    preimages = _source_preimages(source_preimages)
    roster = _canonical_roster(
        catalog_source,
        repository_commit=repository_commit,
        source_preimages=preimages,
        technical_metadata=technical_metadata,
    )
    by_identity = {
        (
            item["canonical_locator"]["catalog"],
            item["canonical_locator"]["field_path"],
            item["canonical_locator"]["literal"],
        ): item
        for item in roster
    }
    raw_proposals = _as_sequence(
        proposals,
        "proposals",
        single_keys=PROPOSAL_REQUIRED_KEYS | PROPOSAL_OPTIONAL_KEYS,
    )
    parsed = [_proposal(value, index) for index, value in enumerate(raw_proposals)]
    seen: set[tuple[str, str | None, str | None]] = set()
    materialized: list[tuple[int, dict[str, Any], list[str]]] = []
    for index, proposal in enumerate(parsed):
        identity = proposal["identity"]
        if identity in seen:
            raise VideoSemanticWorkItemError("proposals contain duplicate targets")
        seen.add(identity)
        roster_item = by_identity.get(identity)
        if roster_item is None:
            raise VideoSemanticWorkItemError(
                f"proposal {index} target does not resolve to exactly one source node"
            )
        body = {
            "schema_version": 1,
            "node_kind": _node_kind(identity),
            "canonical_locator": deepcopy(roster_item["canonical_locator"]),
            "technical": deepcopy(roster_item["technical"]),
            "candidate": {
                "means": proposal["means"],
                "aka": proposal["aka"],
                "review_state": "draft",
            },
            "editorial_rules": proposal["editorial_rules"],
            "evidence_refs": proposal["evidence_refs"],
            "ambiguities": proposal["ambiguities"],
            "author": proposal["author"],
            "reviewer": proposal["reviewer"],
        }
        item = {**body, "work_item_id": _hash(body)}
        errors = validate_work_item(item)
        if errors:
            raise VideoSemanticWorkItemError(
                f"proposal {index} cannot form a schema-valid work item: {'; '.join(errors)}"
            )
        materialized.append((roster_item["order"], item, proposal["aka_evidence_refs"]))
    materialized.sort(key=lambda item: item[0])
    work_items = [item for _, item, _ in materialized]
    aka_evidence = {item["work_item_id"]: refs for _, item, refs in materialized if refs}
    return {
        "work_items": work_items,
        "technical_roster": roster,
        "aka_evidence": aka_evidence,
    }


__all__ = ["VideoSemanticWorkItemError", "build_video_semantic_work_items"]
