"""Verified semantic-index v2 handoff for the catalog-grounding wave.

This module joins already acquired, offline artifacts.  It performs no model,
network, tenant, credential, or source acquisition.  The join is deliberately
fail-closed in places where the older contracts do not define enough identity:

* the full local census is rebuilt from the normalized projection because its
  public receipt intentionally redacts value literals;
* ``constraint_revision`` is the canonical hash of the ledger body excluding
  that field, because the schema only specifies its syntax;
* a constraint field path must resolve to exactly one included catalog field;
* only reviewed concepts, reviewed crosswalk decisions over observed nodes,
  and reviewed constraints enter the handoff;
* a terminal absence must use an ``absent:`` locator and is retained in a
  separate hash-only roster rather than attached to a catalog node.

These rules avoid silently choosing a catalog, accepting a stale snapshot, or
turning a provisional editorial decision into runtime grounding.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from metis_model1.provenance import canonical_json_bytes, canonical_json_hash
from metis_model1.video_catalog_projection import validate_catalog_projection_receipt
from metis_model1.video_local_census import (
    build_local_census,
    validate_local_census_receipt,
)
from metis_model1.video_semantic_crosswalk import validate_crosswalk_receipt
from metis_model1.video_semantic_index import (
    build_semantic_index,
    validate_semantic_index,
)
from metis_model1.video_semantic_index import (
    index_revision as semantic_index_v1_revision,
)
from metis_model1.video_semantics_contracts import (
    validate_concepts,
    validate_constraints,
    validate_crosswalk,
)

HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
OPAQUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
MAPPED_RELATIONS = frozenset({"exact", "renamed", "synonym", "split", "merged"})
V2_REQUIRED_ENTRY_KEYS = frozenset({"canonical_locator", "semantic_refs", "constraint_refs"})
V2_AUGMENTATION_KEYS = frozenset({*V2_REQUIRED_ENTRY_KEYS, "type", "modifiers"})
RECEIPT_COUNT_KEYS = frozenset(
    {
        "entries_in",
        "entries_out",
        "entries_distinct",
        "entries_gaps",
        "catalogs",
        "fields",
        "values",
        "concepts",
        "semantic_refs",
        "semantic_entries",
        "terminal_absent_concepts",
        "constraints",
        "constraint_refs",
        "constraint_entries",
    }
)


class SemanticIndexV2Error(ValueError):
    """Raised when a v2 source artifact or deterministic join is incoherent."""


def _hash(value: Any) -> str:
    try:
        return "sha256:" + canonical_json_hash(value)
    except (TypeError, ValueError) as error:
        raise SemanticIndexV2Error("value is not canonical JSON") from error


def _hash_ref(value: Any, label: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        raise SemanticIndexV2Error(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _opaque(value: Any, label: str) -> str:
    if not isinstance(value, str) or OPAQUE_RE.fullmatch(value) is None:
        raise SemanticIndexV2Error(f"{label} must be a bounded opaque identifier")
    return value


def _contract(label: str, errors: Sequence[str]) -> None:
    if errors:
        raise SemanticIndexV2Error(f"{label} is invalid: {'; '.join(errors)}")


def _identity(entry: Mapping[str, Any]) -> tuple[Any, Any, Any, Any]:
    return (
        entry.get("node_kind"),
        entry.get("catalog"),
        entry.get("field"),
        entry.get("literal"),
    )


def _hash_roster(value: Any, label: str, *, nonempty: bool = False) -> list[str]:
    if not isinstance(value, list) or (nonempty and not value):
        raise SemanticIndexV2Error(f"{label} must be a sorted distinct hash roster")
    if any(not isinstance(item, str) or HASH_RE.fullmatch(item) is None for item in value):
        raise SemanticIndexV2Error(f"{label} must be a sorted distinct hash roster")
    if value != sorted(value) or len(value) != len(set(value)):
        raise SemanticIndexV2Error(f"{label} must be a sorted distinct hash roster")
    return list(value)


def _entry_locator(entry: Mapping[str, Any]) -> str:
    at = entry.get("at")
    if (
        not isinstance(at, Mapping)
        or not isinstance(at.get("file"), str)
        or type(at.get("line")) is not int
    ):
        raise SemanticIndexV2Error("index entry source location is invalid")
    return _hash(
        {
            "node_kind": entry.get("node_kind"),
            "catalog": entry.get("catalog"),
            "field": entry.get("field"),
            "literal": entry.get("literal"),
            "source_locator": f"{at['file']}:{at['line']}",
        }
    )


def _complete_snapshot(
    value: Any, *, projection_sha256: str, census_roster_sha256: str
) -> dict[str, str]:
    required = {
        "snapshot_id",
        "membership_sha256",
        "tenant_revision",
        "catalog_projection_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise SemanticIndexV2Error("tenant_snapshot must be the complete closed v2 contract")
    snapshot = {
        "snapshot_id": _opaque(value["snapshot_id"], "tenant_snapshot.snapshot_id"),
        "membership_sha256": _hash_ref(
            value["membership_sha256"], "tenant_snapshot.membership_sha256"
        ),
        "tenant_revision": _hash_ref(value["tenant_revision"], "tenant_snapshot.tenant_revision"),
        "catalog_projection_sha256": _hash_ref(
            value["catalog_projection_sha256"],
            "tenant_snapshot.catalog_projection_sha256",
        ),
    }
    if snapshot["catalog_projection_sha256"] != projection_sha256:
        raise SemanticIndexV2Error("tenant snapshot is bound to a different projection")
    if snapshot["membership_sha256"] != census_roster_sha256:
        raise SemanticIndexV2Error("tenant snapshot is bound to a different census membership")
    return snapshot


def _projection_counts(projection: Mapping[str, Any]) -> dict[str, int]:
    catalogs = projection.get("catalogs")
    if not isinstance(catalogs, list):
        raise SemanticIndexV2Error("projection catalog roster is missing")
    fields = 0
    finite = 0
    values = 0

    def walk(items: Any) -> None:
        nonlocal fields, finite, values
        if not isinstance(items, list):
            raise SemanticIndexV2Error("projection field roster is invalid")
        for item in items:
            if not isinstance(item, Mapping) or not isinstance(item.get("domain"), Mapping):
                raise SemanticIndexV2Error("projection field is invalid")
            fields += 1
            domain = item["domain"]
            if domain.get("kind") in {"inline", "enum", "list"} and domain.get("size", 0) > 0:
                finite += 1
            materialized = domain.get("values", [])
            if not isinstance(materialized, list):
                raise SemanticIndexV2Error("projection values roster is invalid")
            values += len(materialized)
            if "fields" in item:
                walk(item["fields"])

    for catalog in catalogs:
        if not isinstance(catalog, Mapping):
            raise SemanticIndexV2Error("projection catalog is invalid")
        walk(catalog.get("fields"))
    return {
        "catalogs": len(catalogs),
        "fields": fields,
        "finite_fields_expected": finite,
        "values": values,
        "semantic_values": values,
        "gaps": 0,
    }


def _projection_field_technical(
    projection: Mapping[str, Any],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Retain the field surface Brain needs to generate type-correct DSL."""

    result: dict[tuple[str, str], dict[str, Any]] = {}

    def walk(catalog: str, fields: Any, parent: str | None = None) -> None:
        if not isinstance(fields, list):
            raise SemanticIndexV2Error("projection field roster is invalid")
        for raw in fields:
            if not isinstance(raw, Mapping):
                raise SemanticIndexV2Error("projection field is invalid")
            name = raw.get("name")
            field_type = raw.get("type")
            modifiers = raw.get("modifiers")
            if (
                not isinstance(name, str)
                or not name
                or not isinstance(field_type, str)
                or not field_type
                or not isinstance(modifiers, list)
                or any(not isinstance(item, str) for item in modifiers)
                or len(modifiers) != len(set(modifiers))
                or any(item not in {"multi", "ordered"} for item in modifiers)
            ):
                raise SemanticIndexV2Error("projection field technical surface is invalid")
            path = name if parent is None else f"{parent}.{name}"
            key = (catalog, path)
            if key in result:
                raise SemanticIndexV2Error("projection field technical roster has duplicates")
            result[key] = {"type": field_type, "modifiers": list(modifiers)}
            if "fields" in raw:
                walk(catalog, raw["fields"], path)

    catalogs = projection.get("catalogs")
    if not isinstance(catalogs, list):
        raise SemanticIndexV2Error("projection catalog roster is invalid")
    for raw_catalog in catalogs:
        if not isinstance(raw_catalog, Mapping) or not isinstance(raw_catalog.get("name"), str):
            raise SemanticIndexV2Error("projection catalog is invalid")
        walk(raw_catalog["name"], raw_catalog.get("fields"))
    return result


def _validate_projection_binding(projection: Mapping[str, Any], projection_receipt: Any) -> str:
    _contract("projection receipt", validate_catalog_projection_receipt(projection_receipt))
    assert isinstance(projection_receipt, Mapping)
    projection_sha256 = _hash(projection)
    if projection_receipt["projection_sha256"] != projection_sha256:
        raise SemanticIndexV2Error("projection content differs from its receipt")
    expected = _projection_counts(projection)
    counts = projection_receipt["counts"]
    if any(counts[key] != value for key, value in expected.items()):
        raise SemanticIndexV2Error("projection receipt counts differ from projection content")
    return projection_sha256


def _validated_census(
    projection: Mapping[str, Any], local_census: Any, *, semantic_source_revision: str
) -> tuple[list[Mapping[str, Any]], str]:
    if not isinstance(local_census, Mapping) or set(local_census) != {
        "schema_version",
        "roster",
        "receipt",
    }:
        raise SemanticIndexV2Error("local census must be the closed full census bundle")
    receipt = local_census["receipt"]
    _contract("local census receipt", validate_local_census_receipt(receipt))
    assert isinstance(receipt, Mapping)
    if receipt["semantic_source_revision"] != semantic_source_revision:
        raise SemanticIndexV2Error("local census semantic revision differs from the handoff")
    try:
        rebuilt = build_local_census(
            projection,
            semantic_source_revision=semantic_source_revision,
            tenant_ref=receipt["tenant_ref"],
            catalog_ref=receipt["catalog_ref"],
        )
    except ValueError as error:
        raise SemanticIndexV2Error(f"local census cannot be rebuilt: {error}") from error
    if canonical_json_bytes(rebuilt) != canonical_json_bytes(local_census):
        raise SemanticIndexV2Error("local census differs from the projection-derived census")
    roster = local_census["roster"]
    assert isinstance(roster, list)
    return roster, receipt["roster_sha256"]


def _validated_concepts(concepts: Any) -> tuple[list[Mapping[str, Any]], list[str], str]:
    if not isinstance(concepts, list) or not concepts:
        raise SemanticIndexV2Error("concepts must be a non-empty array")
    _contract("concepts", validate_concepts(concepts))
    parsed = [item for item in concepts if isinstance(item, Mapping)]
    if len(parsed) != len(concepts):  # Defensive; schema validation already rejects this.
        raise SemanticIndexV2Error("concept roster contains a non-object")
    if any(item.get("review_state") != "reviewed" for item in parsed):
        raise SemanticIndexV2Error("all concepts must be reviewed before v2 handoff")
    ordered = sorted(parsed, key=lambda item: item["concept_id"])
    roster = [item["concept_id"] for item in ordered]
    return parsed, roster, _hash({"schema_version": 1, "concepts": ordered})


def _validated_crosswalk(
    crosswalk_bundle: Any,
    *,
    concept_ids: list[str],
    semantic_source_revision: str,
    census_by_locator: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, list[str]], list[str], str]:
    if not isinstance(crosswalk_bundle, Mapping) or set(crosswalk_bundle) != {
        "crosswalk",
        "receipt",
    }:
        raise SemanticIndexV2Error("crosswalk must be the closed document-and-receipt bundle")
    document = crosswalk_bundle["crosswalk"]
    receipt = crosswalk_bundle["receipt"]
    _contract(
        "crosswalk",
        validate_crosswalk(
            document,
            concept_ids=set(concept_ids),
            semantic_source_revision_ref=semantic_source_revision,
        ),
    )
    _contract("crosswalk receipt", validate_crosswalk_receipt(receipt))
    assert isinstance(document, Mapping)
    assert isinstance(receipt, Mapping)
    rows = document["rows"]
    if receipt["semantic_source_revision"] != semantic_source_revision:
        raise SemanticIndexV2Error("crosswalk receipt semantic revision differs from handoff")
    crosswalk_sha256 = _hash(document)
    if receipt["crosswalk_sha256"] != crosswalk_sha256:
        raise SemanticIndexV2Error("crosswalk content differs from its receipt")
    seen = [row["concept_id"] for row in rows]
    counts = receipt["counts"]
    if (
        set(seen) != set(concept_ids)
        or len(seen) != len(concept_ids)
        or len(seen) != len(set(seen))
        or counts
        != {
            "items_in": len(concept_ids),
            "items_out": len(rows),
            "items_distinct": len(set(seen)),
            "items_gaps": 0,
        }
        or receipt["critical_unresolved"] != 0
    ):
        raise SemanticIndexV2Error("crosswalk coverage is not closed or contains critical gaps")

    refs_by_locator: dict[str, list[str]] = {}
    terminal_absent: list[str] = []
    relations_by_locator: dict[str, list[str]] = {}
    for index, row in enumerate(rows):
        if (
            row["decision_state"] != "reviewed"
            or row["decision_required"] is not False
            or not isinstance(row["reviewer"], str)
            or OPAQUE_RE.fullmatch(row["reviewer"]) is None
        ):
            raise SemanticIndexV2Error(f"crosswalk row[{index}] is not a reviewed final decision")
        relation = row["relation"]
        field_status = row["field_status"]
        locator = row["canonical_locator"]
        if relation == "absent" or field_status == "absent":
            if (
                relation != "absent"
                or field_status != "absent"
                or row["literal"] is not None
                or not locator.startswith("absent:")
            ):
                raise SemanticIndexV2Error(
                    f"crosswalk row[{index}] has an incoherent terminal absence"
                )
            terminal_absent.append(row["concept_id"])
            continue
        if relation not in MAPPED_RELATIONS or field_status != "declared-observed":
            raise SemanticIndexV2Error(
                f"crosswalk row[{index}] is not an observed terminal mapping"
            )
        target = census_by_locator.get(locator)
        if target is None:
            raise SemanticIndexV2Error(f"crosswalk row[{index}] locator is not in the census")
        if row["literal"] != target.get("literal"):
            raise SemanticIndexV2Error(f"crosswalk row[{index}] literal differs from the census")
        if target.get("state") != "reviewed":
            raise SemanticIndexV2Error(f"crosswalk row[{index}] targets a non-reviewed node")
        refs_by_locator.setdefault(locator, []).append(row["concept_id"])
        relations_by_locator.setdefault(locator, []).append(relation)

    for locator, relations in relations_by_locator.items():
        if len(relations) > 1 and set(relations) != {"merged"}:
            raise SemanticIndexV2Error(
                f"crosswalk target {locator} requires explicit merged relations"
            )
    return (
        {locator: sorted(refs) for locator, refs in refs_by_locator.items()},
        sorted(terminal_absent),
        crosswalk_sha256,
    )


def constraint_ledger_revision(ledger: Mapping[str, Any]) -> str:
    """Return the strict v2 identity of a constraint ledger."""

    if not isinstance(ledger, Mapping):
        raise SemanticIndexV2Error("constraint ledger must be an object")
    body = {key: value for key, value in ledger.items() if key != "constraint_revision"}
    return _hash(body)


def _validated_constraints(
    ledger: Any, *, census_roster: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, list[str]], list[str], str]:
    _contract("constraint ledger", validate_constraints(ledger))
    assert isinstance(ledger, Mapping)
    revision = constraint_ledger_revision(ledger)
    if ledger["constraint_revision"] != revision:
        raise SemanticIndexV2Error("constraint_revision differs from canonical ledger material")
    constraints = ledger["constraints"]
    identifiers = [item["constraint_id"] for item in constraints]
    if len(identifiers) != len(set(identifiers)):
        raise SemanticIndexV2Error("constraint roster contains duplicate identifiers")
    if any(item["review_state"] != "reviewed" for item in constraints):
        raise SemanticIndexV2Error("all constraints must be reviewed before v2 handoff")

    fields = [item for item in census_roster if item.get("node_kind") == "field"]
    values = [item for item in census_roster if item.get("node_kind") == "value"]
    refs_by_locator: dict[str, set[str]] = {}
    for index, constraint in enumerate(constraints):
        if constraint["brain_behavior"] == "apply" and not constraint["editorial_oracle"]:
            raise SemanticIndexV2Error(
                f"constraint[{index}] cannot apply without an editorial oracle"
            )
        for field_path in constraint["fields"]:
            matches = [item for item in fields if item.get("field") == field_path]
            if len(matches) != 1:
                raise SemanticIndexV2Error(
                    f"constraint[{index}] field {field_path} does not resolve exactly once"
                )
            field = matches[0]
            if field.get("state") != "reviewed":
                raise SemanticIndexV2Error(f"constraint[{index}] targets a non-reviewed field")
            applicable = [field] + [
                item
                for item in values
                if item.get("catalog") == field.get("catalog")
                and item.get("field") == field.get("field")
            ]
            for target in applicable:
                refs_by_locator.setdefault(target["locator"], set()).add(
                    constraint["constraint_id"]
                )
    return (
        {locator: sorted(refs) for locator, refs in refs_by_locator.items()},
        sorted(identifiers),
        revision,
    )


def canonical_semantic_index_v2_bytes(index: Mapping[str, Any]) -> bytes:
    """Return the repository canonical bytes used by the v2 handoff."""

    try:
        return canonical_json_bytes(index)
    except (TypeError, ValueError) as error:
        raise SemanticIndexV2Error("index is not canonical JSON") from error


def semantic_index_v2_revision(index: Mapping[str, Any]) -> str:
    """Return the v2 index revision, excluding its self-identity field."""

    if not isinstance(index, Mapping):
        raise SemanticIndexV2Error("index must be an object")
    return _hash({key: value for key, value in index.items() if key != "revision"})


def build_semantic_index_v2(
    projection: Mapping[str, Any],
    projection_receipt: Mapping[str, Any],
    local_census: Mapping[str, Any],
    concepts: Sequence[Mapping[str, Any]],
    crosswalk: Mapping[str, Any],
    constraint_ledger: Mapping[str, Any],
    *,
    semantic_source_revision: str,
    grammar_revision: str,
    toolchain_revision: str,
    tenant_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Build a deterministic, provenance-bound index and payload-free receipt."""

    _hash_ref(semantic_source_revision, "semantic_source_revision")
    _hash_ref(grammar_revision, "grammar_revision")
    _hash_ref(toolchain_revision, "toolchain_revision")
    projection_sha256 = _validate_projection_binding(projection, projection_receipt)
    census_roster, census_roster_sha256 = _validated_census(
        projection, local_census, semantic_source_revision=semantic_source_revision
    )
    snapshot = _complete_snapshot(
        tenant_snapshot,
        projection_sha256=projection_sha256,
        census_roster_sha256=census_roster_sha256,
    )
    parsed_concepts, concept_ids, concepts_sha256 = _validated_concepts(list(concepts))
    census_by_locator = {item["locator"]: item for item in census_roster}
    if len(census_by_locator) != len(census_roster):
        raise SemanticIndexV2Error("local census contains duplicate canonical locators")
    semantic_refs, terminal_absent, crosswalk_sha256 = _validated_crosswalk(
        crosswalk,
        concept_ids=concept_ids,
        semantic_source_revision=semantic_source_revision,
        census_by_locator=census_by_locator,
    )
    constraint_refs, constraint_ids, constraint_revision = _validated_constraints(
        constraint_ledger, census_roster=census_roster
    )

    try:
        base = build_semantic_index(
            projection,
            semantic_source_revision=semantic_source_revision,
            grammar_revision=grammar_revision,
            toolchain_revision=toolchain_revision,
            tenant_snapshot=snapshot,
        )["index"]
    except ValueError as error:
        raise SemanticIndexV2Error(f"projection cannot build a v1 index: {error}") from error
    census_by_identity = {_identity(item): item for item in census_roster}
    base_identities = {_identity(item) for item in base["entries"]}
    if len(census_by_identity) != len(census_roster) or base_identities != set(census_by_identity):
        raise SemanticIndexV2Error("v1 index and local census membership differ")

    technical_by_field = _projection_field_technical(projection)
    entries: list[dict[str, Any]] = []
    for raw in base["entries"]:
        census_entry = census_by_identity[_identity(raw)]
        locator = census_entry["locator"]
        entry = {
            **raw,
            "canonical_locator": locator,
            "semantic_refs": semantic_refs.get(locator, []),
            "constraint_refs": constraint_refs.get(locator, []),
        }
        if raw["node_kind"] == "field":
            key = (raw["catalog"], raw["field"])
            technical = technical_by_field.get(key)
            if technical is None:
                raise SemanticIndexV2Error("field technical surface is missing")
            entry.update(technical)
        entries.append(entry)
    body: dict[str, Any] = {
        "schema_version": 2,
        "index_id": "video-semantics/index-v2",
        "semantic_source_revision": semantic_source_revision,
        "grammar_revision": grammar_revision,
        "toolchain_revision": toolchain_revision,
        "projection_sha256": projection_sha256,
        "census_roster_sha256": census_roster_sha256,
        "concepts_sha256": concepts_sha256,
        "crosswalk_sha256": crosswalk_sha256,
        "constraint_revision": constraint_revision,
        "tenant_snapshot": snapshot,
        "semantic_ref_roster": concept_ids,
        "terminal_absent_semantic_refs": terminal_absent,
        "constraint_ref_roster": constraint_ids,
        "entries": entries,
    }
    index = {**body, "revision": semantic_index_v2_revision(body)}
    _contract("generated semantic index v2", validate_semantic_index_v2(index))

    counts = {
        "entries_in": len(entries),
        "entries_out": len(entries),
        "entries_distinct": len(entries),
        "entries_gaps": 0,
        "catalogs": sum(item["node_kind"] == "catalog" for item in entries),
        "fields": sum(item["node_kind"] == "field" for item in entries),
        "values": sum(item["node_kind"] == "value" for item in entries),
        "concepts": len(parsed_concepts),
        "semantic_refs": sum(len(item["semantic_refs"]) for item in entries),
        "semantic_entries": sum(bool(item["semantic_refs"]) for item in entries),
        "terminal_absent_concepts": len(terminal_absent),
        "constraints": len(constraint_ids),
        "constraint_refs": sum(len(item["constraint_refs"]) for item in entries),
        "constraint_entries": sum(bool(item["constraint_refs"]) for item in entries),
    }
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "receipt_id": "video-semantics/index-v2-receipt-v1",
        "index_revision": index["revision"],
        "projection_sha256": projection_sha256,
        "census_roster_sha256": census_roster_sha256,
        "concepts_sha256": concepts_sha256,
        "crosswalk_sha256": crosswalk_sha256,
        "constraint_revision": constraint_revision,
        "semantic_source_revision": semantic_source_revision,
        "grammar_revision": grammar_revision,
        "toolchain_revision": toolchain_revision,
        "tenant_snapshot_sha256": _hash(snapshot),
        "counts": counts,
        "payload_redacted": True,
        "reasoning_present": False,
    }
    receipt["receipt_sha256"] = _hash(receipt)
    _contract("generated semantic index v2 receipt", validate_semantic_index_v2_receipt(receipt))
    return {"index": index, "receipt": receipt}


def validate_semantic_index_v2(index: Any) -> list[str]:
    """Validate a materialized v2 index without consulting original artifacts."""

    if not isinstance(index, Mapping):
        return ["index must be an object"]
    errors: list[str] = []
    required = {
        "schema_version",
        "index_id",
        "semantic_source_revision",
        "grammar_revision",
        "toolchain_revision",
        "projection_sha256",
        "census_roster_sha256",
        "concepts_sha256",
        "crosswalk_sha256",
        "constraint_revision",
        "tenant_snapshot",
        "semantic_ref_roster",
        "terminal_absent_semantic_refs",
        "constraint_ref_roster",
        "entries",
        "revision",
    }
    if set(index) != required:
        errors.append("index fields are not the closed v2 contract")
    if index.get("schema_version") != 2 or index.get("index_id") != "video-semantics/index-v2":
        errors.append("index identity is invalid")
    for key in (
        "semantic_source_revision",
        "grammar_revision",
        "toolchain_revision",
        "projection_sha256",
        "census_roster_sha256",
        "concepts_sha256",
        "crosswalk_sha256",
        "constraint_revision",
        "revision",
    ):
        try:
            _hash_ref(index.get(key), f"index.{key}")
        except SemanticIndexV2Error as error:
            errors.append(str(error))
    try:
        snapshot = _complete_snapshot(
            index.get("tenant_snapshot"),
            projection_sha256=index.get("projection_sha256"),
            census_roster_sha256=index.get("census_roster_sha256"),
        )
    except SemanticIndexV2Error as error:
        errors.append(str(error))
        snapshot = index.get("tenant_snapshot")
    try:
        semantic_roster = _hash_roster(
            index.get("semantic_ref_roster"), "index.semantic_ref_roster", nonempty=True
        )
        terminal = _hash_roster(
            index.get("terminal_absent_semantic_refs"),
            "index.terminal_absent_semantic_refs",
        )
        constraint_roster = _hash_roster(
            index.get("constraint_ref_roster"), "index.constraint_ref_roster"
        )
    except SemanticIndexV2Error as error:
        errors.append(str(error))
        semantic_roster, terminal, constraint_roster = [], [], []
    if not set(terminal) <= set(semantic_roster):
        errors.append("terminal absent semantic refs are not in the semantic roster")

    entries = index.get("entries")
    mapped_semantic: list[str] = []
    mapped_constraints: list[str] = []
    base_entries: list[dict[str, Any]] = []
    locators: list[str] = []
    field_constraints: dict[tuple[Any, Any], list[str]] = {}
    value_constraints: list[tuple[tuple[Any, Any], list[str]]] = []
    if not isinstance(entries, list) or not entries:
        errors.append("index entries are missing")
    else:
        for entry in entries:
            if not isinstance(entry, Mapping):
                errors.append("index entry is invalid")
                continue
            if not set(entry) >= V2_REQUIRED_ENTRY_KEYS:
                errors.append("index entry is missing v2 join fields")
                continue
            locator = entry.get("canonical_locator")
            if not isinstance(locator, str) or HASH_RE.fullmatch(locator) is None:
                errors.append("index entry canonical locator is invalid")
            else:
                locators.append(locator)
                try:
                    if locator != _entry_locator(entry):
                        errors.append("index entry canonical locator differs from its source node")
                except SemanticIndexV2Error as error:
                    errors.append(str(error))
            try:
                semantic_refs = _hash_roster(entry.get("semantic_refs"), "entry.semantic_refs")
                constraint_refs = _hash_roster(
                    entry.get("constraint_refs"), "entry.constraint_refs"
                )
            except SemanticIndexV2Error as error:
                errors.append(str(error))
                semantic_refs, constraint_refs = [], []
            if not set(semantic_refs) <= set(semantic_roster):
                errors.append("index entry contains a dangling semantic ref")
            if not set(constraint_refs) <= set(constraint_roster):
                errors.append("index entry contains a dangling constraint ref")
            if semantic_refs and entry.get("state") != "reviewed":
                errors.append("semantic refs target a non-reviewed index entry")
            kind = entry.get("node_kind")
            if kind == "field":
                field_type = entry.get("type")
                modifiers = entry.get("modifiers")
                if (
                    not isinstance(field_type, str)
                    or not field_type
                    or len(field_type) > 256
                    or any(ord(char) < 0x20 for char in field_type)
                    or not isinstance(modifiers, list)
                    or any(not isinstance(item, str) for item in modifiers)
                    or len(modifiers) != len(set(modifiers))
                    or any(item not in {"multi", "ordered"} for item in modifiers)
                ):
                    errors.append("field technical surface is invalid")
            elif "type" in entry or "modifiers" in entry:
                errors.append("non-field entry carries a field technical surface")
            if kind == "catalog" and constraint_refs:
                errors.append("catalog entries cannot carry field constraints")
            key = (entry.get("catalog"), entry.get("field"))
            if kind == "field":
                field_constraints[key] = constraint_refs
            elif kind == "value":
                value_constraints.append((key, constraint_refs))
            mapped_semantic.extend(semantic_refs)
            mapped_constraints.extend(constraint_refs)
            base_entries.append(
                {key: value for key, value in entry.items() if key not in V2_AUGMENTATION_KEYS}
            )
        if len(locators) != len(entries) or len(locators) != len(set(locators)):
            errors.append("index entry canonical locators are missing or duplicate")
        for key, refs in value_constraints:
            if key not in field_constraints or refs != field_constraints[key]:
                errors.append("value constraint refs differ from their field parent")
        if len(mapped_semantic) != len(set(mapped_semantic)):
            errors.append("a semantic ref is projected onto more than one entry")
        if set(mapped_semantic) & set(terminal):
            errors.append("terminal absent semantic refs are also projected")
        if set(mapped_semantic) | set(terminal) != set(semantic_roster):
            errors.append("semantic ref roster is not closed")
        if set(mapped_constraints) != set(constraint_roster):
            errors.append("constraint ref roster is not closed")

        v1_body = {
            "schema_version": 1,
            "index_id": "video-semantics/index-v1",
            "semantic_source_revision": index.get("semantic_source_revision"),
            "grammar_revision": index.get("grammar_revision"),
            "toolchain_revision": index.get("toolchain_revision"),
            "tenant_snapshot": snapshot,
            "entries": base_entries,
        }
        try:
            v1_index = {**v1_body, "revision": semantic_index_v1_revision(v1_body)}
            errors.extend(f"v1 projection: {error}" for error in validate_semantic_index(v1_index))
        except ValueError as error:
            errors.append(f"v1 projection cannot be validated: {error}")
    try:
        if index.get("revision") != semantic_index_v2_revision(index):
            errors.append("index revision is stale or tampered")
    except SemanticIndexV2Error as error:
        errors.append(str(error))
    return errors


def validate_semantic_index_v2_receipt(receipt: Any) -> list[str]:
    """Validate the exact hash/count-only v2 receipt and its arithmetic."""

    if not isinstance(receipt, Mapping):
        return ["receipt must be an object"]
    errors: list[str] = []
    required = {
        "schema_version",
        "receipt_id",
        "index_revision",
        "projection_sha256",
        "census_roster_sha256",
        "concepts_sha256",
        "crosswalk_sha256",
        "constraint_revision",
        "semantic_source_revision",
        "grammar_revision",
        "toolchain_revision",
        "tenant_snapshot_sha256",
        "counts",
        "payload_redacted",
        "reasoning_present",
        "receipt_sha256",
    }
    if set(receipt) != required:
        errors.append("receipt fields are not the closed public contract")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("receipt_id") != "video-semantics/index-v2-receipt-v1"
    ):
        errors.append("receipt identity is invalid")
    for key in required - {
        "schema_version",
        "receipt_id",
        "counts",
        "payload_redacted",
        "reasoning_present",
    }:
        try:
            _hash_ref(receipt.get(key), f"receipt.{key}")
        except SemanticIndexV2Error as error:
            errors.append(str(error))
    counts = receipt.get("counts")
    if not isinstance(counts, Mapping) or set(counts) != RECEIPT_COUNT_KEYS:
        errors.append("receipt counts are invalid")
    elif any(type(value) is not int or value < 0 for value in counts.values()):
        errors.append("receipt counts contain a non-natural value")
    elif (
        counts["entries_in"] != counts["entries_out"]
        or counts["entries_out"] != counts["entries_distinct"]
        or counts["entries_gaps"] != 0
        or counts["entries_in"] != counts["catalogs"] + counts["fields"] + counts["values"]
        or counts["concepts"] != counts["semantic_refs"] + counts["terminal_absent_concepts"]
        or counts["semantic_entries"] > counts["semantic_refs"]
        or counts["constraint_entries"] > counts["constraint_refs"]
        or (counts["constraints"] == 0) != (counts["constraint_refs"] == 0)
        or counts["constraints"] > counts["constraint_refs"]
    ):
        errors.append("receipt counts are not closed")
    if receipt.get("payload_redacted") is not True:
        errors.append("receipt payload redaction marker is invalid")
    if receipt.get("reasoning_present") is not False:
        errors.append("receipt reasoning marker is invalid")
    try:
        expected = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        if receipt.get("receipt_sha256") != _hash(expected):
            errors.append("receipt self-hash is invalid")
    except SemanticIndexV2Error as error:
        errors.append(str(error))
    return errors


__all__ = [
    "SemanticIndexV2Error",
    "build_semantic_index_v2",
    "canonical_semantic_index_v2_bytes",
    "constraint_ledger_revision",
    "semantic_index_v2_revision",
    "validate_semantic_index_v2",
    "validate_semantic_index_v2_receipt",
]
