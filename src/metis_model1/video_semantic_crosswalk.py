"""Explicit, non-inferential preliminary crosswalk construction.

All mappings arrive as decisions from an editor or an upstream deterministic
step.  This module only checks membership and contract invariants: it never
fuzzy-matches labels, creates aliases, or chooses a catalog on behalf of a
caller.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from metis_model1.provenance import canonical_json_hash
from metis_model1.video_semantics_contracts import (
    validate_concepts,
    validate_crosswalk,
)

HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
RELATIONS = frozenset(
    {"exact", "renamed", "synonym", "split", "merged", "absent", "conflict", "unresolved"}
)
FIELD_STATUSES = frozenset(
    {
        "declared-observed",
        "declared-unobserved",
        "live-only",
        "legacy-aggregate",
        "absent",
        "conflict",
        "unresolved",
    }
)
DECISION_STATES = frozenset({"provisional", "reviewed", "needs-decision", "rejected"})


class CrosswalkError(ValueError):
    """Raised when explicit crosswalk decisions are invalid or incomplete."""


def _hash(value: Any) -> str:
    return "sha256:" + canonical_json_hash(value)


def _opaque(value: Any, label: str, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not value or len(value) > 128:
        raise CrosswalkError(f"{label} must be a bounded opaque string")
    if any(
        char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:-"
        for char in value
    ):
        raise CrosswalkError(f"{label} is not opaque")
    return value


def _hash_identity(value: Any, label: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        raise CrosswalkError(f"{label} must be a lowercase sha256 identity")
    return value


def _strings(value: Any, label: str, *, minimum: int = 0) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum:
        raise CrosswalkError(f"{label} must be a distinct string array")
    result: list[str] = []
    for item in value:
        result.append(_opaque(item, f"{label} item") or "")
    if len(set(result)) != len(result):
        raise CrosswalkError(f"{label} must be a distinct string array")
    return result


def _roster(census: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    value = census.get("roster") if isinstance(census, Mapping) else census
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        raise CrosswalkError("local census roster is missing")
    entries: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise CrosswalkError(f"census roster entry {index} is invalid")
        locator = item.get("locator")
        if not isinstance(locator, str) or locator in seen:
            raise CrosswalkError("census roster contains duplicate or invalid locators")
        seen.add(locator)
        if not isinstance(item.get("node_kind"), str) or item.get("node_kind") not in {
            "catalog",
            "field",
            "value",
        }:
            raise CrosswalkError("census roster contains an invalid node kind")
        entries.append(item)
    if not entries:
        raise CrosswalkError("local census roster is empty")
    return entries


def _target(
    decision: Mapping[str, Any], roster: Sequence[Mapping[str, Any]]
) -> Mapping[str, Any] | None:
    catalog = decision.get("catalog")
    field = decision.get("field")
    literal = decision.get("literal")
    if catalog is None and field is None and literal is None:
        locator = decision.get("canonical_locator")
        if locator is None:
            return None
        matches = [entry for entry in roster if entry.get("locator") == locator]
        if len(matches) != 1:
            raise CrosswalkError("explicit canonical_locator is not in the census")
        return matches[0]
    if not isinstance(catalog, str) or not isinstance(field, str):
        raise CrosswalkError("decision must specify catalog and field together")
    matches = [
        entry
        for entry in roster
        if entry.get("catalog") == catalog
        and entry.get("field") == field
        and (
            (literal is None and entry.get("node_kind") == "field")
            or (
                literal is not None
                and entry.get("node_kind") == "value"
                and entry.get("literal") == literal
            )
        )
    ]
    if len(matches) != 1:
        raise CrosswalkError("decision target is absent or not unique in the census")
    explicit_locator = decision.get("canonical_locator")
    if explicit_locator is not None and explicit_locator != matches[0].get("locator"):
        raise CrosswalkError("decision canonical_locator disagrees with the census")
    return matches[0]


def build_preliminary_crosswalk(
    concepts: Sequence[Any],
    census: Mapping[str, Any] | Sequence[Mapping[str, Any]],
    decisions: Sequence[Mapping[str, Any]],
    *,
    semantic_source_revision: str,
) -> dict[str, Any]:
    """Build a schema-1 crosswalk from explicit decisions only.

    Decisions with no target are permitted only when they carry an explicit
    opaque ``canonical_locator`` (normally an ``absent:...`` or
    ``unresolved:...`` decision).  Unresolved/conflict decisions remain gaps.
    """

    _hash_identity(semantic_source_revision, "semantic_source_revision")
    concept_errors = validate_concepts(concepts)
    if concept_errors:
        raise CrosswalkError("concepts are not validated: " + "; ".join(concept_errors))
    concept_ids = {concept["concept_id"] for concept in concepts if isinstance(concept, Mapping)}
    roster = _roster(census)
    if not isinstance(decisions, Sequence) or isinstance(decisions, str | bytes | bytearray):
        raise CrosswalkError("decisions must be an array")

    rows: list[dict[str, Any]] = []
    seen_concepts: set[str] = set()
    target_relations: dict[tuple[str, Any], set[str]] = {}
    gaps = 0
    critical_unresolved = 0
    for index, decision in enumerate(decisions):
        if not isinstance(decision, Mapping):
            raise CrosswalkError(f"decision {index} is not an object")
        concept_id = _hash_identity(decision.get("concept_id"), f"decision[{index}].concept_id")
        if concept_id not in concept_ids:
            raise CrosswalkError(f"decision[{index}] has a dangling concept_id")
        if concept_id in seen_concepts:
            raise CrosswalkError("duplicate concept decision")
        seen_concepts.add(concept_id)
        relation = decision.get("relation")
        field_status = decision.get("field_status")
        if (
            not isinstance(relation, str)
            or relation not in RELATIONS
            or not isinstance(field_status, str)
            or field_status not in FIELD_STATUSES
        ):
            raise CrosswalkError(f"decision[{index}] relation or field_status is invalid")
        rationale = decision.get("reason", decision.get("rationale"))
        if not isinstance(rationale, str) or not rationale.strip() or len(rationale) > 4096:
            raise CrosswalkError(f"decision[{index}] reason is required")
        evidence_refs = _strings(
            decision.get("evidence_refs"), f"decision[{index}].evidence_refs", minimum=1
        )
        usages = _strings(
            decision.get("validated_usages", []), f"decision[{index}].validated_usages"
        )
        no_target_relation = relation in {"absent", "unresolved", "conflict"} and all(
            decision.get(key) is None for key in ("catalog", "field", "literal")
        )
        target = None if no_target_relation else _target(decision, roster)
        if target is None:
            locator = _opaque(
                decision.get("canonical_locator"), f"decision[{index}].canonical_locator"
            )
            literal = None
        else:
            locator = _opaque(target.get("locator"), f"decision[{index}] target locator")
            literal = target.get("literal")
        target_key = (locator or "", literal)
        prior_relations = target_relations.get(target_key, set())
        if prior_relations and (relation != "merged" or prior_relations != {"merged"}):
            raise CrosswalkError(
                "duplicate concept-target mapping requires explicit merged relations"
            )
        target_relations.setdefault(target_key, set()).add(relation)
        state = decision.get("decision_state")
        if state is None:
            state = (
                "needs-decision"
                if relation in {"unresolved", "conflict"}
                or field_status in {"unresolved", "conflict"}
                else "provisional"
            )
        if not isinstance(state, str) or state not in DECISION_STATES:
            raise CrosswalkError(f"decision[{index}] state is invalid")
        if "decision_required" in decision and type(decision["decision_required"]) is not bool:
            raise CrosswalkError(f"decision[{index}] decision_required is invalid")
        if "critical" in decision and type(decision["critical"]) is not bool:
            raise CrosswalkError(f"decision[{index}] critical is invalid")
        if "reviewer" in decision and decision["reviewer"] is not None:
            _opaque(decision["reviewer"], f"decision[{index}].reviewer")
        required = decision.get(
            "decision_required",
            state == "needs-decision"
            or relation in {"unresolved", "conflict"}
            or field_status in {"unresolved", "conflict"},
        )
        unresolved = (
            relation in {"unresolved", "conflict"}
            or field_status in {"unresolved", "conflict"}
            or state == "needs-decision"
        )
        if unresolved:
            gaps += 1
            if decision.get("critical", True) is True:
                critical_unresolved += 1
        rows.append(
            {
                "concept_id": concept_id,
                "canonical_locator": locator,
                "literal": literal,
                "relation": relation,
                "field_status": field_status,
                "rationale": rationale,
                "evidence_refs": evidence_refs,
                "validated_usages": usages,
                "decision_required": required,
                "reviewer": decision.get("reviewer"),
                "decision_state": state,
            }
        )

    missing_concepts = len(concept_ids - seen_concepts)
    gaps += missing_concepts
    document = {
        "schema_version": 1,
        "crosswalk_id": "video-semantics/crosswalk-v1",
        "semantic_source_revision": semantic_source_revision,
        "rows": rows,
    }
    errors = validate_crosswalk(
        document, concept_ids=concept_ids, semantic_source_revision_ref=semantic_source_revision
    )
    if errors:
        raise CrosswalkError("generated crosswalk is invalid: " + "; ".join(errors))
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "contract_id": "video-preliminary-crosswalk-v1",
        "semantic_source_revision": semantic_source_revision,
        "crosswalk_sha256": _hash(document),
        "counts": {
            "items_in": len(concept_ids),
            "items_out": len(rows),
            "items_distinct": len(seen_concepts),
            "items_gaps": gaps,
        },
        "critical_unresolved": critical_unresolved,
        "values_redacted": True,
    }
    receipt["receipt_sha256"] = _hash(receipt)
    return {"crosswalk": document, "receipt": receipt}


def validate_crosswalk_receipt(receipt: Any) -> list[str]:
    """Validate the sanitized preliminary-crosswalk receipt."""

    if not isinstance(receipt, Mapping):
        return ["receipt must be an object"]
    errors: list[str] = []
    if set(receipt) != {
        "schema_version",
        "contract_id",
        "semantic_source_revision",
        "crosswalk_sha256",
        "counts",
        "critical_unresolved",
        "values_redacted",
        "receipt_sha256",
    }:
        errors.append("receipt fields are not the closed public contract")

    def contains_forbidden(value: Any) -> bool:
        if isinstance(value, Mapping):
            return any(
                key in {"means", "aka", "literal"} or contains_forbidden(item)
                for key, item in value.items()
            )
        if isinstance(value, list):
            return any(contains_forbidden(item) for item in value)
        return False

    if contains_forbidden(receipt):
        errors.append("receipt contains semantic/value material")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("contract_id") != "video-preliminary-crosswalk-v1"
    ):
        errors.append("receipt identity is invalid")
    if any(
        not isinstance(receipt.get(key), str) or HASH_RE.fullmatch(receipt[key]) is None
        for key in ("semantic_source_revision", "crosswalk_sha256")
    ):
        errors.append("receipt revision is invalid")
    if type(receipt.get("critical_unresolved")) is not int or receipt["critical_unresolved"] < 0:
        errors.append("receipt critical unresolved count is invalid")
    if receipt.get("values_redacted") is not True:
        errors.append("receipt values redaction marker is invalid")
    counts = receipt.get("counts")
    if not isinstance(counts, Mapping) or set(counts) != {
        "items_in",
        "items_out",
        "items_distinct",
        "items_gaps",
    }:
        errors.append("receipt counts are not closed")
    elif (
        any(type(value) is not int or value < 0 for value in counts.values())
        or counts["items_out"] != counts["items_distinct"]
        or counts["items_out"] > counts["items_in"]
        or counts["items_gaps"] < counts["items_in"] - counts["items_out"]
    ):
        errors.append("receipt counts are incoherent")
    expected = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    if receipt.get("receipt_sha256") != _hash(expected):
        errors.append("receipt self-hash is invalid")
    return errors


__all__ = ["CrosswalkError", "build_preliminary_crosswalk", "validate_crosswalk_receipt"]
