"""Descriptor-native structural authority for typed CREATE v2.

This module admits only structural forms whose catalog, field and finite value
identity is independently proven by the active reviewed Schema2 snapshot.
Closed regression recipes are intentionally test-only historical fixtures.
"""

from __future__ import annotations

import copy
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Literal

from metis_model1.brain_create_surface import CreateAuthorityHistoryMessage
from metis_model1.brain_output_contract import parse_create_quantity_surface
from metis_model1.brain_protocol import BrainError, canonical_sha256
from metis_model1.brain_retrieval import RetrievalResult

STRUCTURAL_CREATE_AUTHORITY_CONTRACT = "metis-brain-create-structural-authority/v2"
MAX_STRUCTURAL_MUTATIONS = 5

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,95}$")
_QUALIFIED_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,95}(?:\.[A-Za-z_][A-Za-z0-9_-]{0,95})*$")


def _invalid(message: str, *, code: str = "CREATE_STRUCTURAL_AUTHORITY_INVALID") -> None:
    raise BrainError(code, 500, message)


def _unsupported(message: str) -> None:
    raise BrainError("CREATE_TYPED_AUTHORITY_UNSUPPORTED", 422, message)


def normalize_operator_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).replace("’", "'").casefold()
    normalized = "".join(
        character for character in normalized if not unicodedata.combining(character)
    )
    normalized = re.sub(r"[^a-z0-9_+./'-]+", " ", normalized)
    return " ".join(normalized.split())


@dataclass(frozen=True, slots=True)
class StructuralLeafEvidence:
    json_pointer: str
    origin: Literal[
        "operator", "clarification", "reviewed_semantic", "pinned_technical", "policy", "basis"
    ]
    identity: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.json_pointer, str) or (
            self.json_pointer and not self.json_pointer.startswith("/")
        ):
            _invalid("structural leaf pointer is invalid")
        if self.origin not in {
            "operator",
            "clarification",
            "reviewed_semantic",
            "pinned_technical",
            "policy",
            "basis",
        }:
            _invalid("structural leaf origin is invalid")
        if not isinstance(self.identity, Mapping):
            _invalid("structural leaf identity is invalid")
        object.__setattr__(self, "identity", copy.deepcopy(dict(self.identity)))


@dataclass(frozen=True, slots=True)
class StructuralAnchor:
    """An exact original endpoint subtree, never a model-selected pointer."""

    path: tuple[str | int, ...]
    fragment_type: str
    fragment: Any

    def __post_init__(self) -> None:
        if (
            not isinstance(self.path, tuple)
            or not 1 <= len(self.path) <= 16
            or any(
                not (isinstance(item, str) and _IDENTIFIER_RE.fullmatch(item))
                and not (type(item) is int and 0 <= item <= 1024)
                for item in self.path
            )
            or self.fragment_type not in {"fetch", "container", "variant"}
            or not isinstance(self.fragment, Mapping)
        ):
            _invalid("structural anchor is invalid")
        object.__setattr__(self, "fragment", copy.deepcopy(dict(self.fragment)))


@dataclass(frozen=True, slots=True)
class StructuralMutation:
    action: Literal["attach", "set", "remove"]
    member: str
    cardinality: Literal["one", "many"]
    insertion: Literal["append", "replace", "exact"]
    fragment_type: str
    fragment: Any
    label: str
    requirement_label: str
    leaf_evidence: tuple[StructuralLeafEvidence, ...]
    basis_path: tuple[str | int, ...] | None = None
    anchor: StructuralAnchor | None = None

    def __post_init__(self) -> None:
        if self.action not in {"attach", "set", "remove"}:
            _invalid("structural mutation action is invalid")
        if not isinstance(self.member, str) or _IDENTIFIER_RE.fullmatch(self.member) is None:
            _invalid("structural mutation member is invalid")
        if self.cardinality not in {"one", "many"} or self.insertion not in {
            "append",
            "replace",
            "exact",
        }:
            _invalid("structural mutation placement is invalid")
        if (
            not isinstance(self.fragment_type, str)
            or _IDENTIFIER_RE.fullmatch(self.fragment_type) is None
        ):
            _invalid("structural mutation fragment type is invalid")
        if (
            not isinstance(self.label, str)
            or not self.label.strip()
            or not isinstance(self.requirement_label, str)
            or not self.requirement_label.strip()
        ):
            _invalid("structural mutation label is invalid")
        if not isinstance(self.leaf_evidence, tuple) or not self.leaf_evidence:
            _invalid("structural mutation evidence is absent")
        if len({item.json_pointer for item in self.leaf_evidence}) != len(self.leaf_evidence):
            _invalid("structural mutation evidence is duplicated")
        if self.action == "remove":
            if self.basis_path is None or self.anchor is not None:
                _invalid("remove mutation lacks an exact basis path")
        elif self.basis_path is not None:
            _invalid("new mutation carries a basis path")
        if self.anchor is not None and type(self.anchor) is not StructuralAnchor:
            _invalid("structural mutation anchor is invalid")


@dataclass(frozen=True, slots=True)
class StructuralIntent:
    family: str
    mutations: tuple[StructuralMutation, ...]
    semantic_proof_revision: str
    contract_id: str = STRUCTURAL_CREATE_AUTHORITY_CONTRACT

    def __post_init__(self) -> None:
        if (
            not isinstance(self.family, str)
            or _IDENTIFIER_RE.fullmatch(self.family) is None
            or not 1 <= len(self.mutations) <= MAX_STRUCTURAL_MUTATIONS
            or self.contract_id != STRUCTURAL_CREATE_AUTHORITY_CONTRACT
        ):
            _invalid("structural intent is invalid")


@dataclass(frozen=True, slots=True)
class StructuralNeed:
    target_key: str
    question: str


@dataclass(frozen=True, slots=True)
class ReviewedSemanticIndex:
    catalog: str
    catalog_ref: str
    fields: frozenset[str]
    values: frozenset[tuple[str, str]]
    proof_revision: str
    selected_values: tuple[tuple[str, tuple[str, ...]], ...] = ()

    def __post_init__(self) -> None:
        selected_values_shape_is_invalid = not isinstance(self.selected_values, tuple) or any(
            not isinstance(item, tuple)
            or len(item) != 2
            or not isinstance(item[0], str)
            or not isinstance(item[1], tuple)
            for item in self.selected_values
        )
        if (
            not isinstance(self.catalog, str)
            or _QUALIFIED_RE.fullmatch(self.catalog) is None
            or not isinstance(self.catalog_ref, str)
            or _IDENTIFIER_RE.fullmatch(self.catalog_ref) is None
            or self.catalog.rsplit(".", 1)[-1] != self.catalog_ref
            or not isinstance(self.fields, frozenset)
            or any(
                not isinstance(item, str) or _IDENTIFIER_RE.fullmatch(item) is None
                for item in self.fields
            )
            or not isinstance(self.values, frozenset)
            or any(
                not isinstance(item, tuple)
                or len(item) != 2
                or not isinstance(item[0], str)
                or item[0] not in self.fields
                or not isinstance(item[1], str)
                or not item[1]
                for item in self.values
            )
            or not isinstance(self.proof_revision, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", self.proof_revision) is None
            or selected_values_shape_is_invalid
            or (
                not selected_values_shape_is_invalid
                and len({item[0] for item in self.selected_values}) != len(self.selected_values)
            )
            or any(
                item[0] not in self.fields
                or not item[1]
                or any(not isinstance(literal, str) or not literal for literal in item[1])
                or len(item[1]) != len(set(item[1]))
                or any((item[0], literal) not in self.values for literal in item[1])
                for item in (() if selected_values_shape_is_invalid else self.selected_values)
            )
        ):
            _invalid("reviewed semantic index is invalid")

    def require_field(self, field: str) -> None:
        if field not in self.fields:
            _unsupported(f"reviewed field authority is unavailable for {field}")

    def require_value(self, field: str, literal: str) -> None:
        self.require_field(field)
        if (field, literal) not in self.values:
            _unsupported(f"reviewed value authority is unavailable for {field}")


def _semantic_state(value: Any) -> str | None:
    return (
        value.get("state")
        if isinstance(value, Mapping) and isinstance(value.get("state"), str)
        else None
    )


def reviewed_descriptor_filter_index(
    *,
    retrieved: RetrievalResult,
    context_revision: str,
    semantic_revision: str,
    toolchain_binding: str,
) -> ReviewedSemanticIndex:
    """Bind finite reviewed retrieval selections without a code-owned roster.

    This is the descriptor-native authority seam.  It accepts only identities
    already selected and resolved by Schema2 from the active snapshot.  It
    cannot add a field or literal, cannot consume an open domain and cannot
    infer an operational role from a familiar field name.
    """

    if not isinstance(retrieved, RetrievalResult):
        _invalid("retrieval authority is invalid")
    context, grounding = retrieved.context, retrieved.grounding
    if not isinstance(context, Mapping) or not isinstance(grounding, Mapping):
        _invalid("retrieval authority is invalid")
    for value, label in (
        (context_revision, "context revision"),
        (semantic_revision, "semantic revision"),
        (toolchain_binding, "toolchain binding"),
    ):
        if not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
            _invalid(f"{label} is invalid")
    if (
        context.get("semantic_schema") != 2
        or context.get("context_revision") != context_revision
        or context.get("semantic_source_revision") != semantic_revision
        or context.get("toolchain_binding") != toolchain_binding
        or retrieved.semantic_source_revision != semantic_revision
    ):
        raise BrainError("CREATE_TYPED_AUTHORITY_STALE", 409, "retrieval authority differs")
    if (
        grounding.get("status") != "resolved"
        or grounding.get("candidates") not in (None, [])
        or grounding.get("unresolved") not in (None, [])
        or grounding.get("lookup") is not None
        or grounding.get("lookups") not in (None, [])
    ):
        _unsupported("descriptor selections are unresolved")
    catalogs = grounding.get("catalogs")
    selections = grounding.get("selections")
    resolutions = grounding.get("resolutions")
    if (
        not isinstance(catalogs, list)
        or len(catalogs) != 1
        or not isinstance(catalogs[0], str)
        or _QUALIFIED_RE.fullmatch(catalogs[0]) is None
        or not isinstance(selections, list)
        or not selections
        or not isinstance(resolutions, list)
        or len(selections) != len(resolutions)
    ):
        _unsupported("one resolved descriptor catalog and selection roster are required")
    catalog = catalogs[0]
    reference_roster = context.get("catalog_reference_roster")
    if (
        not isinstance(reference_roster, list)
        or not reference_roster
        or any(
            not isinstance(item, str) or _QUALIFIED_RE.fullmatch(item) is None
            for item in reference_roster
        )
        or len(reference_roster) != len(set(reference_roster))
        or [
            item
            for item in reference_roster
            if item.rsplit(".", 1)[-1] == catalog.rsplit(".", 1)[-1]
        ]
        != [catalog]
    ):
        _unsupported("selected catalog has no unique compiler-derived short reference")
    raw_catalog = context.get("catalog")
    if (
        not isinstance(raw_catalog, Mapping)
        or raw_catalog.get("name") != catalog
        or _semantic_state(raw_catalog.get("semantic")) != "reviewed"
    ):
        _unsupported("catalog descriptor is not reviewed")
    raw_fields = context.get("fields")
    if not isinstance(raw_fields, list):
        _invalid("descriptor field context is invalid")
    fields: dict[str, Mapping[str, Any]] = {}
    for raw_field in raw_fields:
        if (
            not isinstance(raw_field, Mapping)
            or not isinstance(raw_field.get("name"), str)
            or _QUALIFIED_RE.fullmatch(raw_field["name"]) is None
            or raw_field["name"] in fields
        ):
            _invalid("descriptor field roster is invalid")
        fields[raw_field["name"]] = raw_field

    selected: dict[str, list[str]] = {}
    selected_order: list[str] = []
    evidence: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for selection, resolution in zip(selections, resolutions, strict=True):
        if not isinstance(selection, Mapping) or not isinstance(resolution, Mapping):
            _invalid("descriptor selection evidence is invalid")
        field = selection.get("field")
        literal = selection.get("literal")
        literals = selection.get("literals")
        if (
            selection.get("catalog") != catalog
            or not isinstance(field, str)
            or field not in fields
            or (literal is not None) == (literals is not None)
        ):
            _invalid("descriptor selection identity is invalid")
        if isinstance(literal, str) and literal:
            chosen = (literal,)
        elif (
            isinstance(literals, list)
            and literals
            and selection.get("value_mode") == "any_of"
            and all(isinstance(item, str) and item for item in literals)
            and len(literals) == len(set(literals))
        ):
            chosen = tuple(literals)
        else:
            _invalid("descriptor selection value roster is invalid")
        record = fields[field]
        domain = record.get("domain")
        if (
            _IDENTIFIER_RE.fullmatch(field) is None
            or not isinstance(record.get("modifiers"), list)
            or any(not isinstance(item, str) for item in record["modifiers"])
            or _semantic_state(record.get("semantic")) != "reviewed"
            or record.get("type") != "keyword"
            or not isinstance(domain, Mapping)
            or domain.get("kind") not in {"inline", "enum", "list"}
            or selection.get("type") != record.get("type")
            or selection.get("modifiers") != record.get("modifiers")
            or selection.get("domain") != domain
        ):
            _unsupported("selected descriptor is not a reviewed finite keyword field")
        if (
            resolution.get("catalog") != catalog
            or resolution.get("field") != field
            or resolution.get("literal") != literal
            or resolution.get("review_state") != "reviewed"
        ):
            _invalid("descriptor resolution differs from its selection")
        raw_values = record.get("values")
        if not isinstance(raw_values, list):
            _unsupported("selected finite descriptor values are not materialized")
        value_records: dict[str, Mapping[str, Any]] = {}
        for item in raw_values:
            if (
                not isinstance(item, Mapping)
                or not isinstance(item.get("literal"), str)
                or item["literal"] in value_records
            ):
                _invalid("materialized descriptor value roster is invalid or duplicated")
            value_records[item["literal"]] = item
        reviewed_values = {
            literal
            for literal, item in value_records.items()
            if _semantic_state(item.get("semantic")) == "reviewed"
        }
        if any(item not in reviewed_values for item in chosen):
            _unsupported("selected finite descriptor value is not reviewed")
        if field in selected:
            _unsupported("repeated field selections need explicit logical-group authority")
        selected[field] = []
        selected_order.append(field)
        for item in chosen:
            identity = (field, item)
            if identity in seen:
                _invalid("descriptor selection is duplicated")
            seen.add(identity)
            selected[field].append(item)
        evidence.append(
            {
                "field": field,
                "values": list(chosen),
                "field_semantic": record.get("semantic"),
                "value_semantics": [
                    value_records[chosen_literal].get("semantic") for chosen_literal in chosen
                ],
                "type": record.get("type"),
                "modifiers": record.get("modifiers"),
                "domain": domain,
            }
        )

    selected_values = tuple((field, tuple(selected[field])) for field in selected_order)
    proof = canonical_sha256(
        {
            "contract_id": "metis-brain-reviewed-descriptor-filter-index/v1",
            "context_revision": context_revision,
            "semantic_revision": semantic_revision,
            "toolchain_binding": toolchain_binding,
            "catalog": catalog,
            "catalog_reference_roster": reference_roster,
            "catalog_semantic": raw_catalog.get("semantic"),
            "selections": evidence,
        }
    )
    return ReviewedSemanticIndex(
        catalog=catalog,
        catalog_ref=catalog.rsplit(".", 1)[-1],
        fields=frozenset(selected),
        values=frozenset(seen),
        proof_revision=proof,
        selected_values=selected_values,
    )


def _presentation() -> dict[str, Any]:
    return {"pinned": None, "view_all": None, "meta": [], "meta_per_item": False}


def _literal(value: str, lexical: str = "text") -> dict[str, Any]:
    return {"kind": "lit", "lexical": lexical, "value": value}


def _eq(field: str, value: Mapping[str, Any]) -> dict[str, Any]:
    return {"op": "eq", "field": field, "value": dict(value)}


def _fetch(
    *,
    catalog: str,
    count: int,
    clauses: Sequence[Mapping[str, Any]],
    alias: str | None = None,
    group_by: Mapping[str, Any] | None = None,
    order: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    return {
        "from": {"kind": "catalog", "catalog": catalog},
        "cardinality": {"mode": "total", "value": count},
        "over_fetch": None,
        "alias": alias,
        "title": None,
        "activation": None,
        "presentation": _presentation(),
        "clauses": [copy.deepcopy(dict(item)) for item in clauses],
        "group_by": None if group_by is None else copy.deepcopy(dict(group_by)),
        "order": [copy.deepcopy(dict(item)) for item in order],
        "output": None,
    }


def _context_fetch(name: str, fetch: Mapping[str, Any]) -> dict[str, Any]:
    return {"kind": "fetch", "name": name, "fetch": copy.deepcopy(dict(fetch))}


def _container(
    name: str, *, fetches: Sequence[Mapping[str, Any]], output: Any = None
) -> dict[str, Any]:
    return {
        "name": name,
        "parameters": [],
        "title": None,
        "activation": None,
        "presentation": _presentation(),
        "fetches": [copy.deepcopy(dict(item)) for item in fetches],
        "blocks": [],
        "uses": [],
        "output": copy.deepcopy(output),
    }


def _variant(
    name: str,
    *,
    fetches: Sequence[Mapping[str, Any]] = (),
    blocks: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    return {
        "name": name,
        "title": None,
        "activation": None,
        "empty": False,
        "presentation": _presentation(),
        "fetches": [copy.deepcopy(dict(item)) for item in fetches],
        "blocks": [copy.deepcopy(dict(item)) for item in blocks],
        "uses": [],
        "output": None,
    }


def _leaf_pointers(value: Any, path: str = "") -> tuple[tuple[str, Any, str | None], ...]:
    """Return scalar leaves and the nearest predicate field, in canonical order."""

    output: list[tuple[str, Any, str | None]] = []

    def walk(item: Any, pointer: str, field: str | None) -> None:
        if isinstance(item, Mapping):
            local_field = item.get("field") if isinstance(item.get("field"), str) else field
            for key, nested in item.items():
                escaped = key.replace("~", "~0").replace("/", "~1")
                walk(nested, f"{pointer}/{escaped}", local_field)
            return
        if isinstance(item, list):
            for index, nested in enumerate(item):
                walk(nested, f"{pointer}/{index}", field)
            return
        output.append((pointer, item, field))

    walk(value, path, None)
    return tuple(output)


def _operator_mentions(value: Any, messages: tuple[CreateAuthorityHistoryMessage, ...]) -> bool:
    if isinstance(value, bool) or value is None:
        return False
    needle = normalize_operator_text(str(value).replace("_", " ").replace("+", " "))
    if not needle:
        return False
    return any(needle in normalize_operator_text(message.text) for message in messages)


def _evidence_for_fragment(
    fragment: Any,
    *,
    messages: tuple[CreateAuthorityHistoryMessage, ...],
    semantic: ReviewedSemanticIndex,
    policy_revision: str,
    force_basis: bool = False,
) -> tuple[StructuralLeafEvidence, ...]:
    result: list[StructuralLeafEvidence] = []
    message_roster = [
        {"ordinal": item.ordinal, "message_sha256": item.message_sha256} for item in messages
    ]
    for pointer, value, predicate_field in _leaf_pointers(fragment):
        origin: Literal["operator", "clarification", "reviewed_semantic", "policy", "basis"]
        identity: dict[str, Any]
        if force_basis:
            origin = "basis"
            identity = {"locator": pointer}
        elif pointer.endswith("/catalog") and value == semantic.catalog_ref:
            origin = "reviewed_semantic"
            identity = {"role": "catalog", "catalog": semantic.catalog}
        elif pointer.endswith("/field") and isinstance(value, str) and value in semantic.fields:
            origin = "reviewed_semantic"
            identity = {"role": "field", "catalog": semantic.catalog, "field": value}
        elif (
            predicate_field is not None
            and isinstance(value, str)
            and (predicate_field, value) in semantic.values
        ):
            origin = "reviewed_semantic"
            identity = {
                "role": "catalog_value",
                "catalog": semantic.catalog,
                "field": predicate_field,
                "literal": value,
            }
        elif _operator_mentions(value, messages):
            origin = "operator"
            identity = {"messages": message_roster, "lexical": normalize_operator_text(str(value))}
        else:
            origin = "policy"
            identity = {"policy_revision": policy_revision, "structural_pointer": pointer}
        if origin == "reviewed_semantic":
            identity["semantic_proof_revision"] = semantic.proof_revision
        result.append(StructuralLeafEvidence(pointer, origin, identity))
    return tuple(result)


def _mutation(
    *,
    action: Literal["attach", "set", "remove"],
    member: str,
    cardinality: Literal["one", "many"],
    insertion: Literal["append", "replace", "exact"],
    fragment_type: str,
    fragment: Any,
    label: str,
    messages: tuple[CreateAuthorityHistoryMessage, ...],
    semantic: ReviewedSemanticIndex,
    policy_revision: str,
    basis_path: tuple[str | int, ...] | None = None,
) -> StructuralMutation:
    return StructuralMutation(
        action=action,
        member=member,
        cardinality=cardinality,
        insertion=insertion,
        fragment_type=fragment_type,
        fragment=copy.deepcopy(fragment),
        label=label,
        requirement_label=label,
        leaf_evidence=_evidence_for_fragment(
            fragment,
            messages=messages,
            semantic=semantic,
            policy_revision=policy_revision,
            force_basis=action == "remove",
        ),
        basis_path=basis_path,
    )


def _finite_descriptor_predicate(field: str, values: tuple[str, ...]) -> dict[str, Any]:
    if len(values) == 1:
        return _eq(field, _literal(values[0]))
    return {
        "op": "in",
        "field": field,
        "value": {"kind": "vals", "items": list(values)},
    }


def filtered_collection_intent(
    *,
    count: int,
    messages: tuple[CreateAuthorityHistoryMessage, ...],
    semantic: ReviewedSemanticIndex,
    policy_revision: str,
) -> StructuralIntent:
    """Build a reviewed filtered pool and explicitly emit it in the response."""

    if type(count) is not int or not 1 <= count <= 1_000_000:
        _invalid("filtered collection count is invalid")
    if not semantic.selected_values:
        _unsupported("filtered collection has no reviewed descriptor selections")
    predicates: list[dict[str, Any]] = []
    for field, values in semantic.selected_values:
        semantic.require_field(field)
        for literal in values:
            semantic.require_value(field, literal)
        predicates.append(_finite_descriptor_predicate(field, values))
    block = _container(
        "main",
        fetches=(
            _fetch(
                catalog=semantic.catalog_ref,
                count=count,
                clauses=({"intent": "include", "where": predicates},),
            ),
        ),
    )
    mutation = _mutation(
        action="attach",
        member="blocks",
        cardinality="many",
        insertion="append",
        fragment_type="container",
        fragment=block,
        label="Aggiungi collezione filtrata dai descrittori revisionati",
        messages=messages,
        semantic=semantic,
        policy_revision=policy_revision,
    )
    response = _variant("response_root")
    response["uses"] = [{"kind": "direct", "block": block["name"]}]
    emission = _mutation(
        action="attach",
        member="variants",
        cardinality="many",
        insertion="append",
        fragment_type="variant",
        fragment=response,
        label="Emetti la collezione filtrata nella risposta",
        messages=messages,
        semantic=semantic,
        policy_revision=policy_revision,
    )
    return StructuralIntent(
        "filtered_collection",
        (mutation, emission),
        semantic.proof_revision,
    )


def total_count_from_message(message: str, *, scopes: frozenset[str]) -> int | None:
    surface = parse_create_quantity_surface(message)
    if surface.status != "resolved":
        return None
    values = {
        item.value
        for item in surface.mentions
        if item.kind == "result_count"
        and item.scope in scopes
        and item.mode == "total"
        and item.qualifier is None
        and type(item.value) is int
    }
    return next(iter(values)) if len(values) == 1 else None


_DESCRIPTOR_RECIPE_CONTRACTS = MappingProxyType(
    {
        "filtered_collection": (
            ("attach", "blocks", "many", "append", "container"),
            ("attach", "variants", "many", "append", "variant"),
        ),
    }
)


def _mutation_contract(mutation: StructuralMutation) -> tuple[str, str, str, str, str]:
    return (
        mutation.action,
        mutation.member,
        mutation.cardinality,
        mutation.insertion,
        mutation.fragment_type,
    )


def _policy_revision_from_intent(intent: StructuralIntent) -> str:
    raw_revisions = [
        item.identity.get("policy_revision")
        for mutation in intent.mutations
        for item in mutation.leaf_evidence
        if item.origin == "policy"
    ]
    if any(not isinstance(item, str) for item in raw_revisions):
        _invalid("structural intent policy evidence is invalid")
    revisions = set(raw_revisions)
    if len(revisions) != 1:
        _invalid("structural intent policy evidence differs")
    revision = next(iter(revisions))
    if not isinstance(revision, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", revision) is None:
        _invalid("structural intent policy evidence is invalid")
    return revision


def _expected_descriptor_intent(
    intent: StructuralIntent,
    *,
    policy_revision: str,
    semantic_authority: ReviewedSemanticIndex | None,
    result_count: int | None,
) -> StructuralIntent:
    if intent.family != "filtered_collection":
        _invalid("structural intent family is not descriptor-admissible")
    if (
        type(semantic_authority) is not ReviewedSemanticIndex
        or semantic_authority.proof_revision != intent.semantic_proof_revision
    ):
        _invalid("original reviewed descriptor authority is required")
    return filtered_collection_intent(
        count=result_count,
        messages=(),
        semantic=semantic_authority,
        policy_revision=policy_revision,
    )


def _validate_leaf_evidence(intent: StructuralIntent, *, policy_revision: str) -> None:
    semantic_catalogs: set[str] = set()
    for mutation in intent.mutations:
        leaf_manifest = {
            pointer: (value, field) for pointer, value, field in _leaf_pointers(mutation.fragment)
        }
        expected = set(leaf_manifest)
        observed = {item.json_pointer for item in mutation.leaf_evidence}
        if expected != observed or len(observed) != len(mutation.leaf_evidence):
            _invalid("structural leaf evidence is incomplete")
        for item in mutation.leaf_evidence:
            identity = item.identity
            if item.origin == "policy":
                if identity != {
                    "policy_revision": policy_revision,
                    "structural_pointer": item.json_pointer,
                }:
                    _invalid("structural policy evidence differs")
            elif item.origin == "basis":
                if mutation.action != "remove" or identity != {"locator": item.json_pointer}:
                    _invalid("structural basis evidence differs")
            elif item.origin == "reviewed_semantic":
                if identity.get("semantic_proof_revision") != intent.semantic_proof_revision:
                    _invalid("structural semantic proof differs")
                semantic_catalog = identity.get("catalog")
                if (
                    not isinstance(semantic_catalog, str)
                    or _QUALIFIED_RE.fullmatch(semantic_catalog) is None
                ):
                    _invalid("structural semantic catalog is invalid")
                semantic_catalogs.add(semantic_catalog)
                value, predicate_field = leaf_manifest[item.json_pointer]
                role = identity.get("role")
                if role == "catalog":
                    catalog = identity.get("catalog")
                    if (
                        not item.json_pointer.endswith("/catalog")
                        or not isinstance(catalog, str)
                        or catalog.rsplit(".", 1)[-1] != value
                    ):
                        _invalid("structural catalog evidence differs")
                elif role == "field":
                    if not item.json_pointer.endswith("/field") or identity.get("field") != value:
                        _invalid("structural field evidence differs")
                elif role == "catalog_value":
                    if identity.get("field") != predicate_field or identity.get("literal") != value:
                        _invalid("structural value evidence differs")
                else:
                    _invalid("structural semantic role is invalid")
            elif item.origin == "operator":
                roster = identity.get("messages")
                if (
                    not isinstance(roster, list)
                    or not roster
                    or not isinstance(identity.get("lexical"), str)
                    or not identity["lexical"]
                    or any(
                        not isinstance(entry, Mapping)
                        or type(entry.get("ordinal")) is not int
                        or not isinstance(entry.get("message_sha256"), str)
                        or re.fullmatch(r"sha256:[0-9a-f]{64}", entry["message_sha256"]) is None
                        for entry in roster
                    )
                ):
                    _invalid("structural operator evidence is invalid")
            else:
                _invalid("structural clarification evidence is not admitted")
    if len(semantic_catalogs) != 1:
        _invalid("structural semantic catalog evidence differs")


def validate_structural_intent(
    intent: StructuralIntent,
    *,
    policy_revision: str,
    semantic_authority: ReviewedSemanticIndex | None = None,
    result_count: int | None = None,
    construction_authority: Any = None,
) -> StructuralIntent:
    """Reopen an intent solely against independently held descriptor authority."""

    if not isinstance(intent, StructuralIntent):
        _invalid("structural intent is invalid")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", policy_revision) is None:
        _invalid("structural policy revision is invalid")
    if construction_authority is not None:
        from metis_model1.brain_create_descriptor_operations import validate_descriptor_operation

        return validate_descriptor_operation(
            intent, authority=construction_authority, policy_revision=policy_revision
        )
    descriptor = _DESCRIPTOR_RECIPE_CONTRACTS.get(intent.family)
    observed = [_mutation_contract(item) for item in intent.mutations]
    if descriptor is None or observed != list(descriptor):
        _invalid("structural intent recipe differs")
    if _policy_revision_from_intent(intent) != policy_revision:
        _invalid("structural intent policy differs")
    expected = _expected_descriptor_intent(
        intent,
        policy_revision=policy_revision,
        semantic_authority=semantic_authority,
        result_count=result_count,
    )
    for actual_mutation, expected_mutation in zip(
        intent.mutations, expected.mutations, strict=True
    ):
        if (
            actual_mutation.fragment != expected_mutation.fragment
            or actual_mutation.anchor != expected_mutation.anchor
            or actual_mutation.basis_path != expected_mutation.basis_path
            or actual_mutation.label != expected_mutation.label
            or actual_mutation.requirement_label != expected_mutation.requirement_label
        ):
            _invalid("structural intent fragment differs from reviewed descriptor authority")
        actual_leaves = {item.json_pointer: item for item in actual_mutation.leaf_evidence}
        for leaf in expected_mutation.leaf_evidence:
            actual_leaf = actual_leaves.get(leaf.json_pointer)
            if leaf.origin == "reviewed_semantic" and actual_leaf != leaf:
                _invalid("descriptor leaf differs from its original reviewed authority")
    _validate_leaf_evidence(intent, policy_revision=policy_revision)
    return intent


def _structural_intent_manifest(intent: StructuralIntent) -> dict[str, Any]:
    return {
        "family": intent.family,
        "mutations": [
            {
                "action": item.action,
                "member": item.member,
                "cardinality": item.cardinality,
                "insertion": item.insertion,
                "fragment_type": item.fragment_type,
                "fragment": item.fragment,
                "label": item.label,
                "requirement_label": item.requirement_label,
                "basis_path": item.basis_path,
                "leaf_evidence": [
                    {
                        "json_pointer": evidence.json_pointer,
                        "origin": evidence.origin,
                        "identity": evidence.identity,
                    }
                    for evidence in item.leaf_evidence
                ],
            }
            for item in intent.mutations
        ],
    }


def _descriptor_implementation_fragment_roster() -> list[dict[str, Any]]:
    semantic = ReviewedSemanticIndex(
        catalog="synthetic.assets",
        catalog_ref="assets",
        fields=frozenset({"attribute_x"}),
        values=frozenset({("attribute_x", "option_y")}),
        proof_revision="sha256:" + "2" * 64,
        selected_values=(("attribute_x", ("option_y",)),),
    )
    intent = filtered_collection_intent(
        count=7,
        messages=(),
        semantic=semantic,
        policy_revision="sha256:" + "1" * 64,
    )
    return [_structural_intent_manifest(intent)]


_STRUCTURAL_IMPLEMENTATION_MANIFEST = {
    "contract_id": STRUCTURAL_CREATE_AUTHORITY_CONTRACT,
    "authority": "reviewed-schema2-descriptor-filter-index/v1",
    "admissible_families": sorted(_DESCRIPTOR_RECIPE_CONTRACTS),
    "recipes": {
        name: [list(item) for item in recipe]
        for name, recipe in _DESCRIPTOR_RECIPE_CONTRACTS.items()
    },
    "fragments": _descriptor_implementation_fragment_roster(),
    "descriptor_operation": {
        "contract": "metis-brain-descriptor-operation/v1",
        "authority": "independent_original_base_descriptors_technical_and_bound_operation",
        "validation": "exact_reconstruction_all_mutations_anchors_and_leaf_evidence",
        "anchor": "original_endpoint_relative_nonremovable_fetch_container_or_variant",
        "technical_origin": "pinned_technical_never_editorial_review",
        "operations": [
            "add_filtered_block",
            "add_filtered_page",
            "set_cardinality",
            "order_by_field",
            "return_projection",
            "same_draft_fallback",
            "similarity_from_input",
        ],
    },
}
STRUCTURAL_CREATE_IMPLEMENTATION_SHA256 = canonical_sha256(_STRUCTURAL_IMPLEMENTATION_MANIFEST)
del _STRUCTURAL_IMPLEMENTATION_MANIFEST


__all__ = [
    "MAX_STRUCTURAL_MUTATIONS",
    "STRUCTURAL_CREATE_AUTHORITY_CONTRACT",
    "STRUCTURAL_CREATE_IMPLEMENTATION_SHA256",
    "ReviewedSemanticIndex",
    "StructuralIntent",
    "StructuralLeafEvidence",
    "StructuralMutation",
    "StructuralNeed",
    "filtered_collection_intent",
    "normalize_operator_text",
    "reviewed_descriptor_filter_index",
    "total_count_from_message",
    "validate_structural_intent",
]
