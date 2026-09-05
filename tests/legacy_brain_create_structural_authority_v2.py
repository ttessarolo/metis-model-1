"""Reviewed-semantic structural authority for typed CREATE v2.

The descriptor-native path translates reviewed selections from the active
tenant into detached endpoint-spec fragments without naming a tenant, field or
literal in Python.  A separate compatibility roster still supports previously
sealed regression recipes; callers must opt into that legacy surface
explicitly. This test-only fixture is never product authority. Neither path
inspects an endpoint implementation or model output,
and every executable semantic leaf is bound to the immutable session snapshot.
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
_CATEGORY_FIELD = "tipologia"
_CONTENT_IDENTITY_FIELD = "video_content_id"
_DEDUPLICATION_FIELD = _CONTENT_IDENTITY_FIELD
_EDITORIAL_TYPE_FIELD = "editorial_type"
_PROGRAM_IDENTITY_FIELD = "id_brand"
_PROGRAM_TYPE_FIELD = "programtype"
_RECENCY_FIELD = "publication_date"
_SEED_CONTEXT_NAME = "seed"
_SEED_INPUT_NAME = "seed_id"
_SIMILARITY_PROFILE = "content_fingerprint"

_STRUCTURAL_VALUE_ROSTERS = MappingProxyType(
    {
        "similar_film": ((_CATEGORY_FIELD, "Film"),),
        "similar_series": ((_CATEGORY_FIELD, "Serie TV"), (_CATEGORY_FIELD, "Fiction")),
        "similar_entertainment": ((_CATEGORY_FIELD, "Intrattenimento"),),
        "recent": ((_CATEGORY_FIELD, "Film"), (_CATEGORY_FIELD, "Serie TV")),
        "entertainment_pools": (
            (_CATEGORY_FIELD, "Intrattenimento"),
            (_PROGRAM_TYPE_FIELD, "Episode"),
            (_EDITORIAL_TYPE_FIELD, "Clip"),
            (_EDITORIAL_TYPE_FIELD, "Extra"),
        ),
        "entertainment_consumer_new": (),
    }
)
_RECIPE_CONTRACTS = MappingProxyType(
    {
        "filtered_collection": (("attach", "blocks", "many", "append", "container"),),
        "similar_row": (
            ("attach", "inputs", "many", "append", "input"),
            ("attach", "context", "many", "append", "contextBinding"),
            ("attach", "blocks", "many", "append", "container"),
        ),
        "recent_page": (
            ("attach", "variants", "many", "append", "variant"),
            ("set", "output", "one", "replace", "returnFlow"),
        ),
        "entertainment_pools": (
            ("set", "needs_time", "one", "replace", "boolean"),
            ("attach", "context", "many", "append", "contextBinding"),
            ("attach", "context", "many", "append", "contextBinding"),
            ("attach", "context", "many", "append", "contextBinding"),
            ("attach", "context", "many", "append", "contextBinding"),
        ),
        "entertainment_consumer": (
            ("remove", "blocks", "many", "exact", "container"),
            ("attach", "variants", "many", "append", "variant"),
        ),
    }
)
_STRUCTURAL_RECIPE_MANIFEST = {
    "contract_id": STRUCTURAL_CREATE_AUTHORITY_CONTRACT,
    "recognition": "closed-normalized-token-contract/v1",
    "evidence": "complete-scalar-leaves/exact-origin/v1",
    "basis": "exact-latest-head-locator/v1",
    "rejected_retrieval": {
        "contract": "metis-brain-dialogue-cumulative-grounding/v1",
        "source": "server_dialogue",
        "status": "rejected",
        "authority": "reviewed-schema2-fields-plus-host-exact-value-resolver",
        "empty": ["selections", "resolutions", "candidates", "lookups"],
    },
    "recipes": {
        name: [list(item) for item in recipe] for name, recipe in _RECIPE_CONTRACTS.items()
    },
    "policy_defaults": {
        "seed_input": _SEED_INPUT_NAME,
        "seed_context": _SEED_CONTEXT_NAME,
        "similarity_profile": _SIMILARITY_PROFILE,
        "recent_order": [_RECENCY_FIELD, "descending"],
        "program_identity_field": _PROGRAM_IDENTITY_FIELD,
        "deduplicate_field": _DEDUPLICATION_FIELD,
        "semantic_roles": {
            "category": _CATEGORY_FIELD,
            "content_identity": _CONTENT_IDENTITY_FIELD,
            "editorial_type": _EDITORIAL_TYPE_FIELD,
            "program_type": _PROGRAM_TYPE_FIELD,
            "recency": _RECENCY_FIELD,
        },
    },
    "closed_recipe_constants": {
        "pool_count": 50,
        "episode_window": "18M",
        "recent_window": "14d",
        "consumer_first": 4,
        "consumer_final": 24,
        "consumer_strategy": ["best_plus", "near_full"],
        "fallback": ["nested_flat_items_below", 1, "append"],
    },
    "semantic_values": {
        name: [list(item) for item in roster] for name, roster in _STRUCTURAL_VALUE_ROSTERS.items()
    },
}

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
    origin: Literal["operator", "clarification", "reviewed_semantic", "policy", "basis"]
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
            "policy",
            "basis",
        }:
            _invalid("structural leaf origin is invalid")
        if not isinstance(self.identity, Mapping):
            _invalid("structural leaf identity is invalid")
        object.__setattr__(self, "identity", copy.deepcopy(dict(self.identity)))


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
            if self.basis_path is None:
                _invalid("remove mutation lacks an exact basis path")
        elif self.basis_path is not None:
            _invalid("new mutation carries a basis path")


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
class StructuralSemanticRequirements:
    resolver_identities: tuple[tuple[str, str, str], ...]
    cumulative_identities: tuple[tuple[str, str, str], ...]

    def __post_init__(self) -> None:
        for roster in (self.resolver_identities, self.cumulative_identities):
            if (
                not isinstance(roster, tuple)
                or len(roster) != len(set(roster))
                or any(
                    not isinstance(item, tuple)
                    or len(item) != 3
                    or _QUALIFIED_RE.fullmatch(item[0]) is None
                    or _IDENTIFIER_RE.fullmatch(item[1]) is None
                    or not isinstance(item[2], str)
                    or not item[2]
                    for item in roster
                )
            ):
                _invalid("structural semantic requirement roster is invalid")


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


def reviewed_semantic_index(
    *,
    retrieved: RetrievalResult,
    context_revision: str,
    semantic_revision: str,
    toolchain_binding: str,
    dialogue_message_count: int,
    expected_value_identities: tuple[tuple[str, str, str], ...],
    expected_cumulative_identities: tuple[tuple[str, str, str], ...],
    exact_value_authority: Mapping[str, Any] | None,
) -> ReviewedSemanticIndex:
    """Reopen the bounded retrieval projection and retain only reviewed facts."""

    if not isinstance(retrieved, RetrievalResult):
        _invalid("retrieval authority is invalid")
    context, grounding = retrieved.context, retrieved.grounding
    if not isinstance(context, Mapping) or not isinstance(grounding, Mapping):
        _invalid("retrieval authority is invalid")
    if (
        context.get("semantic_schema") != 2
        or context.get("context_revision") != context_revision
        or context.get("semantic_source_revision") != semantic_revision
        or context.get("toolchain_binding") != toolchain_binding
        or retrieved.semantic_source_revision != semantic_revision
    ):
        raise BrainError("CREATE_TYPED_AUTHORITY_STALE", 409, "retrieval authority differs")
    if type(dialogue_message_count) is not int or dialogue_message_count < 2:
        _invalid("structural dialogue cardinality is invalid")
    cumulative_rejection = {
        "contract": "metis-brain-dialogue-cumulative-grounding/v1",
        "source": "server_dialogue",
        "message_count": dialogue_message_count,
        "status": "rejected",
    }
    raw_cumulative = grounding.get("cumulative_dialogue_semantics")
    rejection_mode = (
        grounding.get("status") == "unsupported" and raw_cumulative == cumulative_rejection
    )
    cumulative_admission = {**cumulative_rejection, "status": "admitted"}
    admission_mode = (
        grounding.get("status") == "resolved" and raw_cumulative == cumulative_admission
    )
    if rejection_mode:
        # A rejected cumulative resolver has made no semantic selection.  A
        # closed structural recipe may still reopen the reviewed schema-2
        # projection below, but no partial/current resolver output can become
        # authority through this path.
        if (
            grounding.get("selected") is not None
            or grounding.get("selections") != []
            or grounding.get("resolutions") != []
            or grounding.get("candidates") != []
            or grounding.get("catalog_candidates") != []
            or grounding.get("lookup") is not None
            or grounding.get("lookups") != []
            or not isinstance(grounding.get("unresolved"), list)
            or len(grounding["unresolved"]) != 1
            or not isinstance(grounding["unresolved"][0], str)
            or not grounding["unresolved"][0].strip()
        ):
            _invalid("rejected cumulative grounding retains semantic authority")
    elif not admission_mode:
        _unsupported("reviewed catalog semantics are unresolved")
    elif (
        grounding.get("candidates") != []
        or grounding.get("unresolved") != []
        or grounding.get("lookup") is not None
        or grounding.get("lookups") != []
    ):
        _invalid("admitted cumulative grounding retains unresolved authority")
    catalogs = grounding.get("catalogs")
    if not isinstance(catalogs, list) or len(catalogs) != 1 or not isinstance(catalogs[0], str):
        _unsupported("one reviewed catalog is required")
    catalog = catalogs[0]
    if _QUALIFIED_RE.fullmatch(catalog) is None:
        _invalid("reviewed catalog identity is invalid")
    raw_catalog = context.get("catalog")
    if not isinstance(raw_catalog, Mapping) or raw_catalog.get("name") != catalog:
        _invalid("reviewed catalog context differs")
    if _semantic_state(raw_catalog.get("semantic")) != "reviewed":
        _unsupported("catalog semantics are not reviewed")

    raw_fields = context.get("fields")
    if not isinstance(raw_fields, list):
        _invalid("reviewed field context is invalid")
    fields: dict[str, Mapping[str, Any]] = {}
    context_reviewed_values: set[tuple[str, str]] = set()
    field_manifest: list[dict[str, Any]] = []
    for item in raw_fields:
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            _invalid("reviewed field context is invalid")
        name = item["name"]
        if name in fields or _IDENTIFIER_RE.fullmatch(name) is None:
            _invalid("reviewed field roster is invalid")
        fields[name] = item
        values: list[str] = []
        raw_values = item.get("values", [])
        if not isinstance(raw_values, list):
            _invalid("reviewed value context is invalid")
        for value in raw_values:
            if not isinstance(value, Mapping) or not isinstance(value.get("literal"), str):
                _invalid("reviewed value context is invalid")
            if _semantic_state(value.get("semantic")) == "reviewed":
                context_reviewed_values.add((name, value["literal"]))
                values.append(value["literal"])
        field_manifest.append(
            {
                "name": name,
                "state": _semantic_state(item.get("semantic")),
                "type": item.get("type"),
                "modifiers": item.get("modifiers"),
                "domain": item.get("domain"),
                "reviewed_values": values,
            }
        )

    expected_values = tuple(expected_value_identities)
    expected_cumulative = tuple(expected_cumulative_identities)
    for roster in (expected_values, expected_cumulative):
        if len(roster) != len(set(roster)) or any(
            not isinstance(item, tuple)
            or len(item) != 3
            or item[0] != catalog
            or item[1] not in fields
            or not isinstance(item[2], str)
            or not item[2]
            for item in roster
        ):
            _invalid("expected structural semantic roster is invalid")
    required_fields = {field for _catalog, field, _literal in expected_values}
    if any(
        _semantic_state(fields[field].get("semantic")) != "reviewed" for field in required_fields
    ):
        _unsupported("required field semantics are not reviewed")

    authority_manifest: dict[str, Any] | None = None
    if not expected_values:
        if exact_value_authority is not None:
            _invalid("unexpected exact reviewed value authority")
        authorized_values: set[tuple[str, str]] = set()
    else:
        if not isinstance(exact_value_authority, Mapping) or set(exact_value_authority) != {
            "contract",
            "context_revision",
            "semantic_source_revision",
            "toolchain_binding",
            "index_revision",
            "outcomes",
            "selections",
            "resolutions",
        }:
            _invalid("exact reviewed value authority is invalid")
        if (
            exact_value_authority.get("contract") != "metis-brain-exact-reviewed-value-authority/v1"
            or exact_value_authority.get("context_revision") != context_revision
            or exact_value_authority.get("semantic_source_revision") != semantic_revision
            or exact_value_authority.get("toolchain_binding") != toolchain_binding
            or not isinstance(exact_value_authority.get("index_revision"), str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", exact_value_authority["index_revision"]) is None
        ):
            raise BrainError(
                "CREATE_TYPED_AUTHORITY_STALE", 409, "exact reviewed value authority differs"
            )
        outcomes = exact_value_authority.get("outcomes")
        authority_selections = exact_value_authority.get("selections")
        authority_resolutions = exact_value_authority.get("resolutions")
        if (
            not isinstance(outcomes, tuple)
            or not isinstance(authority_selections, tuple)
            or not isinstance(authority_resolutions, tuple)
            or not len(outcomes)
            == len(authority_selections)
            == len(authority_resolutions)
            == len(expected_values)
        ):
            _invalid("exact reviewed value authority roster is invalid")
        authority_manifest = {
            "contract": exact_value_authority["contract"],
            "index_revision": exact_value_authority["index_revision"],
            "outcomes": [],
            "selections": [],
            "resolutions": [],
        }
        for identity, outcome, selection, resolution in zip(
            expected_values,
            outcomes,
            authority_selections,
            authority_resolutions,
            strict=True,
        ):
            expected_catalog, expected_field, expected_literal = identity
            record = fields[expected_field]
            if (
                not isinstance(outcome, Mapping)
                or dict(outcome)
                != {
                    "catalog": expected_catalog,
                    "field": expected_field,
                    "literal": expected_literal,
                    "status": "reviewed_exact",
                }
                or not isinstance(selection, Mapping)
                or set(selection)
                != {
                    "catalog",
                    "field",
                    "literal",
                    "domain",
                    "matched_by",
                    "type",
                    "modifiers",
                }
                or selection.get("catalog") != expected_catalog
                or selection.get("field") != expected_field
                or selection.get("literal") != expected_literal
                or selection.get("matched_by") != "compiler_exact_reviewed_value"
                or selection.get("type") != record.get("type")
                or selection.get("modifiers") != record.get("modifiers")
                or selection.get("domain") != record.get("domain")
                or not isinstance(resolution, Mapping)
                or dict(resolution)
                != {
                    "concept": expected_literal,
                    "catalog": expected_catalog,
                    "field": expected_field,
                    "literal": expected_literal,
                    "review_state": "reviewed",
                }
            ):
                _invalid("exact reviewed value authority differs")
            authority_manifest["outcomes"].append(dict(outcome))
            authority_manifest["selections"].append(dict(selection))
            authority_manifest["resolutions"].append(dict(resolution))
        authorized_values = {(field, literal) for _catalog, field, literal in expected_values}

    selections, resolutions = grounding.get("selections"), grounding.get("resolutions")
    if (
        not isinstance(selections, list)
        or not isinstance(resolutions, list)
        or len(selections) != len(resolutions)
    ):
        _invalid("reviewed selection roster is invalid")
    seen: set[tuple[str, str, str]] = set()
    for selection, resolution in zip(selections, resolutions, strict=True):
        if not isinstance(selection, Mapping) or not isinstance(resolution, Mapping):
            _invalid("reviewed semantic evidence is invalid")
        field, literal = selection.get("field"), selection.get("literal")
        literals = selection.get("literals")
        if literal is not None and literals is not None:
            _invalid("reviewed semantic selection has conflicting literals")
        selected_literals = (
            (literal,)
            if isinstance(literal, str)
            else tuple(literals)
            if isinstance(literals, list)
            and literals
            and all(isinstance(item, str) and item for item in literals)
            and len(literals) == len(set(literals))
            else ()
        )
        identities = tuple((selection.get("catalog"), field, item) for item in selected_literals)
        if (
            selection.get("catalog") != catalog
            or not isinstance(field, str)
            or field not in fields
            or not selected_literals
            or any(identity in seen for identity in identities)
            or resolution.get("catalog") != catalog
            or resolution.get("field") != field
            or resolution.get("literal") != literal
            or resolution.get("review_state") != "reviewed"
        ):
            _invalid("reviewed semantic evidence differs")
        seen.update(identities)
        record = fields[field]
        if _semantic_state(record.get("semantic")) != "reviewed":
            _unsupported("selected field semantics are not reviewed")
        if (
            selection.get("type") != record.get("type")
            or selection.get("modifiers") != record.get("modifiers")
            or selection.get("domain") != record.get("domain")
        ):
            _invalid("reviewed field technical surface differs")
        if any((field, item) not in context_reviewed_values for item in selected_literals):
            _unsupported("selected finite value semantics are not reviewed")
    if admission_mode and seen != set(expected_cumulative):
        _invalid("admitted cumulative semantic roster differs")
    if rejection_mode and seen:
        _invalid("rejected cumulative semantic roster is not empty")

    proof = canonical_sha256(
        {
            "contract_id": "metis-brain-reviewed-semantic-index/v2",
            "context_revision": context_revision,
            "semantic_revision": semantic_revision,
            "toolchain_binding": toolchain_binding,
            "catalog": catalog,
            "catalog_state": "reviewed",
            "fields": field_manifest,
            "selections": [list(item) for item in sorted(seen)],
            "authority_mode": (
                "reviewed_schema2_after_explicit_cumulative_rejection"
                if rejection_mode
                else "resolved_grounding"
            ),
            "cumulative_rejection": cumulative_rejection if rejection_mode else None,
            "exact_value_authority": authority_manifest,
            "expected_value_identities": [list(item) for item in expected_values],
            "expected_cumulative_identities": [list(item) for item in expected_cumulative],
        }
    )
    return ReviewedSemanticIndex(
        catalog=catalog,
        catalog_ref=catalog.rsplit(".", 1)[-1],
        fields=frozenset(
            name
            for name, item in fields.items()
            if _semantic_state(item.get("semantic")) == "reviewed"
        ),
        values=frozenset(authorized_values),
        proof_revision=proof,
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


def _within(field: str, duration: str) -> dict[str, Any]:
    return {
        "op": "within",
        "field": field,
        "amount": _literal(duration, "duration"),
        "target": _literal("now", "time"),
    }


def _similar_seed() -> dict[str, Any]:
    return {
        "op": "similar",
        "form": "record",
        "profile": _SIMILARITY_PROFILE,
        "target": {"kind": "ctx", "segments": [_SEED_CONTEXT_NAME]},
    }


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


def _tipologia_predicate(values: tuple[str, ...]) -> dict[str, Any]:
    if len(values) == 1:
        return _eq("tipologia", _literal(values[0]))
    return {
        "op": "group",
        "strategy": "any",
        "items": [_eq("tipologia", _literal(value)) for value in values],
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
    """Build one plain filtered block solely from reviewed descriptor selections."""

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
    return StructuralIntent(
        "filtered_collection",
        (mutation,),
        semantic.proof_revision,
    )


def _require_similar_semantics(semantic: ReviewedSemanticIndex, values: tuple[str, ...]) -> None:
    for field in (_CONTENT_IDENTITY_FIELD, _CATEGORY_FIELD):
        semantic.require_field(field)
    for value in values:
        semantic.require_value(_CATEGORY_FIELD, value)


def similar_row_intent(
    *,
    values: tuple[str, ...],
    count: int,
    messages: tuple[CreateAuthorityHistoryMessage, ...],
    semantic: ReviewedSemanticIndex,
    policy_revision: str,
) -> StructuralIntent:
    _require_similar_semantics(semantic, values)
    seed_input = {
        "name": _SEED_INPUT_NAME,
        "type": "text",
        "required": True,
        "not_empty": True,
        "default": None,
    }
    seed = _context_fetch(
        _SEED_CONTEXT_NAME,
        _fetch(
            catalog=semantic.catalog_ref,
            count=1,
            clauses=(
                {
                    "intent": "include",
                    "where": [
                        _eq(
                            _CONTENT_IDENTITY_FIELD,
                            {"kind": "input", "name": _SEED_INPUT_NAME},
                        )
                    ],
                },
            ),
        ),
    )
    row = _container(
        "main",
        fetches=(
            _fetch(
                catalog=semantic.catalog_ref,
                count=count,
                clauses=(
                    {
                        "intent": "include",
                        "where": [_tipologia_predicate(values), _similar_seed()],
                    },
                ),
            ),
        ),
    )
    mutations = (
        _mutation(
            action="attach",
            member="inputs",
            cardinality="many",
            insertion="append",
            fragment_type="input",
            fragment=seed_input,
            label="Aggiungi parametro seed",
            messages=messages,
            semantic=semantic,
            policy_revision=policy_revision,
        ),
        _mutation(
            action="attach",
            member="context",
            cardinality="many",
            insertion="append",
            fragment_type="contextBinding",
            fragment=seed,
            label="Aggiungi recupero del seed",
            messages=messages,
            semantic=semantic,
            policy_revision=policy_revision,
        ),
        _mutation(
            action="attach",
            member="blocks",
            cardinality="many",
            insertion="append",
            fragment_type="container",
            fragment=row,
            label="Aggiungi riga di contenuti simili",
            messages=messages,
            semantic=semantic,
            policy_revision=policy_revision,
        ),
    )
    return StructuralIntent("similar_row", mutations, semantic.proof_revision)


def recent_page_intent(
    *,
    values: tuple[str, ...],
    count: int,
    messages: tuple[CreateAuthorityHistoryMessage, ...],
    semantic: ReviewedSemanticIndex,
    policy_revision: str,
) -> StructuralIntent:
    semantic.require_field(_CATEGORY_FIELD)
    semantic.require_field(_RECENCY_FIELD)
    for value in values:
        semantic.require_value(_CATEGORY_FIELD, value)
    fetch = _fetch(
        catalog=semantic.catalog_ref,
        count=count,
        clauses=(
            {
                "intent": "include",
                "where": [
                    {
                        "op": "in",
                        "field": _CATEGORY_FIELD,
                        "value": {"kind": "vals", "items": list(values)},
                    }
                ],
            },
        ),
        order=({"by": "field", "direction": "descending", "field": _RECENCY_FIELD},),
    )
    variant = _variant("default", fetches=(fetch,))
    output = {"projection": "default", "steps": [{"kind": "max", "count": count}], "fallbacks": []}
    mutations = (
        _mutation(
            action="attach",
            member="variants",
            cardinality="many",
            insertion="append",
            fragment_type="variant",
            fragment=variant,
            label="Aggiungi pagina dei titoli recenti",
            messages=messages,
            semantic=semantic,
            policy_revision=policy_revision,
        ),
        _mutation(
            action="set",
            member="output",
            cardinality="one",
            insertion="replace",
            fragment_type="returnFlow",
            fragment=output,
            label="Limita il risultato della pagina",
            messages=messages,
            semantic=semantic,
            policy_revision=policy_revision,
        ),
    )
    return StructuralIntent("recent_page", mutations, semantic.proof_revision)


def entertainment_pools_intent(
    *,
    count: int,
    episode_window: str,
    recent_window: str,
    messages: tuple[CreateAuthorityHistoryMessage, ...],
    semantic: ReviewedSemanticIndex,
    policy_revision: str,
) -> StructuralIntent:
    for field in (
        _CATEGORY_FIELD,
        _PROGRAM_TYPE_FIELD,
        _PROGRAM_IDENTITY_FIELD,
        _EDITORIAL_TYPE_FIELD,
        _RECENCY_FIELD,
    ):
        semantic.require_field(field)
    for field, literal in (
        (_CATEGORY_FIELD, "Intrattenimento"),
        (_PROGRAM_TYPE_FIELD, "Episode"),
        (_EDITORIAL_TYPE_FIELD, "Clip"),
        (_EDITORIAL_TYPE_FIELD, "Extra"),
    ):
        semantic.require_value(field, literal)
    category = _eq(_CATEGORY_FIELD, _literal("Intrattenimento"))
    episode = _eq(_PROGRAM_TYPE_FIELD, _literal("Episode"))
    similar = _similar_seed()
    group = {
        "fields": [_PROGRAM_IDENTITY_FIELD],
        "member_order": [],
        "member_limit": None,
        "having": None,
    }
    definitions = (
        (
            "pool_same_program",
            [
                category,
                episode,
                _eq(
                    _PROGRAM_IDENTITY_FIELD,
                    {
                        "kind": "ctx",
                        "segments": [_SEED_CONTEXT_NAME, _PROGRAM_IDENTITY_FIELD],
                    },
                ),
                _within(_RECENCY_FIELD, episode_window),
                similar,
            ],
        ),
        (
            "pool_clips_extra",
            [
                category,
                {
                    "op": "group",
                    "strategy": "any",
                    "items": [
                        _eq(_EDITORIAL_TYPE_FIELD, _literal("Clip")),
                        _eq(_EDITORIAL_TYPE_FIELD, _literal("Extra")),
                    ],
                },
                _within(_RECENCY_FIELD, recent_window),
                similar,
            ],
        ),
        (
            "pool_entertainment_episodes",
            [category, episode, _within(_RECENCY_FIELD, episode_window), similar],
        ),
        (
            "pool_entertainment_clips",
            [
                category,
                _eq(_EDITORIAL_TYPE_FIELD, _literal("Clip")),
                _within(_RECENCY_FIELD, recent_window),
                similar,
            ],
        ),
    )
    mutations: list[StructuralMutation] = [
        _mutation(
            action="set",
            member="needs_time",
            cardinality="one",
            insertion="replace",
            fragment_type="boolean",
            fragment=True,
            label="Abilita il tempo corrente",
            messages=messages,
            semantic=semantic,
            policy_revision=policy_revision,
        )
    ]
    for name, predicates in definitions:
        binding = _context_fetch(
            name,
            _fetch(
                catalog=semantic.catalog_ref,
                count=count,
                clauses=({"intent": "include", "where": predicates},),
                group_by=group,
            ),
        )
        mutations.append(
            _mutation(
                action="attach",
                member="context",
                cardinality="many",
                insertion="append",
                fragment_type="contextBinding",
                fragment=binding,
                label=f"Aggiungi pool {name.replace('_', ' ')}",
                messages=messages,
                semantic=semantic,
                policy_revision=policy_revision,
            )
        )
    return StructuralIntent("entertainment_pools", tuple(mutations), semantic.proof_revision)


def entertainment_consumer_intent(
    *,
    first_count: int,
    final_count: int,
    recent_window: str,
    fallback_target: str,
    basis_block: Mapping[str, Any],
    messages: tuple[CreateAuthorityHistoryMessage, ...],
    semantic: ReviewedSemanticIndex,
    policy_revision: str,
) -> StructuralIntent:
    semantic.require_field(_RECENCY_FIELD)
    semantic.require_field(_DEDUPLICATION_FIELD)
    if _QUALIFIED_RE.fullmatch(fallback_target) is None:
        _unsupported("fallback target is not an exact identifier")
    pools = [
        "pool_same_program",
        "pool_clips_extra",
        "pool_entertainment_episodes",
        "pool_entertainment_clips",
    ]

    def consumer_fetch(alias: str, count: int) -> dict[str, Any]:
        alternatives = {
            "op": "group",
            "strategy": "best_plus",
            "coefficient": "near_full",
            "items": [{"op": "ids", "segments": [name]} for name in pools],
        }
        return _fetch(
            catalog=semantic.catalog_ref,
            count=count,
            alias=alias,
            clauses=(
                {"intent": "include", "where": [alternatives]},
                {"intent": "promote", "where": [_within(_RECENCY_FIELD, recent_window)]},
            ),
        )

    output = {
        "projection": "default",
        "steps": [
            {"kind": "deduplicate", "field": _DEDUPLICATION_FIELD},
            {"kind": "max", "count": final_count},
        ],
        "fallbacks": [
            {
                "kind": "materialized",
                "target": fallback_target,
                "trigger": "nested_flat_items_below",
                "threshold": 1,
                "mode": "append",
            }
        ],
    }
    block = _container(
        "main",
        fetches=(
            consumer_fetch("consumer_first", first_count),
            consumer_fetch("consumer_final", final_count),
        ),
        output=output,
    )
    variant = _variant("default", blocks=(block,))
    mutations = (
        _mutation(
            action="remove",
            member="blocks",
            cardinality="many",
            insertion="exact",
            fragment_type="container",
            fragment=copy.deepcopy(dict(basis_block)),
            label="Rimuovi la riga iniziale",
            messages=messages,
            semantic=semantic,
            policy_revision=policy_revision,
            basis_path=("blocks", 0),
        ),
        _mutation(
            action="attach",
            member="variants",
            cardinality="many",
            insertion="append",
            fragment_type="variant",
            fragment=variant,
            label="Aggiungi consumer e fallback",
            messages=messages,
            semantic=semantic,
            policy_revision=policy_revision,
        ),
    )
    return StructuralIntent("entertainment_consumer", mutations, semantic.proof_revision)


def _validation_semantic(catalog_ref: str) -> ReviewedSemanticIndex:
    fields = frozenset(
        {
            "editorial_type",
            "id_brand",
            "programtype",
            "publication_date",
            "tipologia",
            "video_content_id",
        }
    )
    return ReviewedSemanticIndex(
        catalog=f"authority.{catalog_ref}",
        catalog_ref=catalog_ref,
        fields=fields,
        values=frozenset(
            {
                ("editorial_type", "Clip"),
                ("editorial_type", "Extra"),
                ("programtype", "Episode"),
                ("tipologia", "Fiction"),
                ("tipologia", "Film"),
                ("tipologia", "Intrattenimento"),
                ("tipologia", "Serie TV"),
            }
        ),
        proof_revision="sha256:" + "0" * 64,
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


def _expected_intent(
    intent: StructuralIntent,
    policy_revision: str,
    semantic_authority: ReviewedSemanticIndex | None = None,
    result_count: int | None = None,
) -> StructuralIntent:
    """Rebuild the only admitted fragment from bounded variable leaves."""

    try:
        if intent.family == "filtered_collection":
            if (
                type(semantic_authority) is not ReviewedSemanticIndex
                or semantic_authority.proof_revision != intent.semantic_proof_revision
            ):
                _invalid("original reviewed descriptor authority is required")
            # Reopen the independent host index, never derive permission from
            # the candidate fragment or its self-reported leaf identities.
            return filtered_collection_intent(
                count=result_count,
                messages=(),
                semantic=semantic_authority,
                policy_revision=policy_revision,
            )
        if intent.family == "similar_row":
            row = intent.mutations[2].fragment
            fetch = row["fetches"][0]
            catalog_ref = fetch["from"]["catalog"]
            count = fetch["cardinality"]["value"]
            predicate = fetch["clauses"][0]["where"][0]
            if predicate.get("op") == "eq":
                values = (predicate["value"]["value"],)
            else:
                values = tuple(item["value"]["value"] for item in predicate["items"])
            if values not in {("Film",), ("Serie TV", "Fiction"), ("Intrattenimento",)}:
                _invalid("similar row content roster is not code-owned")
            if type(count) is not int or not 1 <= count <= 1_000_000:
                _invalid("similar row count is invalid")
            return similar_row_intent(
                values=values,
                count=count,
                messages=(),
                semantic=_validation_semantic(catalog_ref),
                policy_revision=policy_revision,
            )
        if intent.family == "recent_page":
            variant = intent.mutations[0].fragment
            fetch = variant["fetches"][0]
            catalog_ref = fetch["from"]["catalog"]
            count = fetch["cardinality"]["value"]
            if type(count) is not int or not 1 <= count <= 1_000_000:
                _invalid("recent page count is invalid")
            return recent_page_intent(
                values=("Film", "Serie TV"),
                count=count,
                messages=(),
                semantic=_validation_semantic(catalog_ref),
                policy_revision=policy_revision,
            )
        if intent.family == "entertainment_pools":
            binding = intent.mutations[1].fragment
            catalog_ref = binding["fetch"]["from"]["catalog"]
            return entertainment_pools_intent(
                count=50,
                episode_window="18M",
                recent_window="14d",
                messages=(),
                semantic=_validation_semantic(catalog_ref),
                policy_revision=policy_revision,
            )
        if intent.family == "entertainment_consumer":
            basis_block = intent.mutations[0].fragment
            variant = intent.mutations[1].fragment
            block = variant["blocks"][0]
            catalog_ref = block["fetches"][0]["from"]["catalog"]
            fallback_target = block["output"]["fallbacks"][0]["target"]
            if fallback_target != "intrat_recent":
                _invalid("consumer fallback target is not code-owned")
            return entertainment_consumer_intent(
                first_count=4,
                final_count=24,
                recent_window="14d",
                fallback_target=fallback_target,
                basis_block=basis_block,
                messages=(),
                semantic=_validation_semantic(catalog_ref),
                policy_revision=policy_revision,
            )
    except (KeyError, IndexError, TypeError, AttributeError) as error:
        raise BrainError(
            "CREATE_STRUCTURAL_AUTHORITY_INVALID", 500, "structural fragment is malformed"
        ) from error
    _invalid("structural intent family is not code-owned")
    raise AssertionError("unreachable")


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
) -> StructuralIntent:
    """Reopen a detached intent against the exact code-owned recipe registry."""

    if not isinstance(intent, StructuralIntent):
        _invalid("structural intent is invalid")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", policy_revision) is None:
        _invalid("structural policy revision is invalid")
    descriptor = _RECIPE_CONTRACTS.get(intent.family)
    observed = [_mutation_contract(item) for item in intent.mutations]
    if descriptor is None or observed != list(descriptor):
        _invalid("structural intent recipe differs")
    if _policy_revision_from_intent(intent) != policy_revision:
        _invalid("structural intent policy differs")
    expected = _expected_intent(intent, policy_revision, semantic_authority, result_count)
    for actual_mutation, expected_mutation in zip(
        intent.mutations, expected.mutations, strict=True
    ):
        if (
            actual_mutation.fragment != expected_mutation.fragment
            or actual_mutation.basis_path != expected_mutation.basis_path
            or actual_mutation.label != expected_mutation.label
            or actual_mutation.requirement_label != expected_mutation.requirement_label
        ):
            _invalid("structural intent fragment differs from its code-owned recipe")
        if intent.family == "filtered_collection":
            actual_leaves = {item.json_pointer: item for item in actual_mutation.leaf_evidence}
            for leaf in expected_mutation.leaf_evidence:
                actual_leaf = actual_leaves.get(leaf.json_pointer)
                if leaf.origin == "reviewed_semantic" and actual_leaf != leaf:
                    _invalid("descriptor leaf differs from its original reviewed authority")
    _validate_leaf_evidence(intent, policy_revision=policy_revision)
    return intent


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


def _negated(text: str, token: str) -> bool:
    escaped = re.escape(normalize_operator_text(token))
    return re.search(rf"\b(?:non|senza)\b(?:\s+\w+){{0,3}}\s+{escaped}\b", text) is not None


def _has_similarity(text: str) -> bool:
    return any(token in text for token in ("simil", "affin", "correlat"))


_COMMON_CONTRACT_TOKENS = frozenset(
    {
        "a",
        "al",
        "alla",
        "che",
        "ciascuno",
        "come",
        "con",
        "da",
        "dal",
        "dei",
        "del",
        "della",
        "delle",
        "dello",
        "degli",
        "di",
        "e",
        "gli",
        "i",
        "il",
        "in",
        "l",
        "la",
        "le",
        "lo",
        "mi",
        "nel",
        "per",
        "quello",
        "quattro",
        "se",
        "sono",
        "una",
        "uno",
        "un",
    }
)


def _closed_tokens(
    text: str,
    *,
    prefixes: frozenset[str],
    numbers: frozenset[int],
) -> bool:
    """Require every meaningful operator token to belong to the parsed contract."""

    normalized = normalize_operator_text(text)
    observed_numbers = {int(item) for item in re.findall(r"\b[0-9]+\b", normalized)}
    if observed_numbers != set(numbers):
        return False
    for token in re.findall(r"[a-z_]+", normalized):
        if token in _COMMON_CONTRACT_TOKENS:
            continue
        if token not in prefixes:
            return False
    return True


_SIMILAR_FIRST_PREFIXES = frozenset(
    {
        "affine",
        "affini",
        "cinema",
        "cinematografici",
        "cinematografico",
        "contenuti",
        "contenuto",
        "correlata",
        "correlate",
        "correlati",
        "correlato",
        "crea",
        "fiction",
        "film",
        "guarda",
        "guardando",
        "intrattenimento",
        "riga",
        "sezione",
        "serie",
        "simile",
        "simili",
        "sta",
        "tv",
        "utente",
        "visto",
        "voglio",
        "vorrei",
    }
)
_SIMILAR_SECOND_PREFIXES = frozenset(
    {
        "catalogo",
        "contenuto",
        "dammi",
        "partendo",
        "riga",
        "risultati",
        "seed",
        "totali",
        "usa",
        "usando",
        "video",
        "visto",
    }
)
_RECENT_FIRST_PREFIXES = frozenset({"crea", "momento", "pagina", "titoli"})
_RECENT_SECOND_PREFIXES = frozenset(
    {
        "catalogo",
        "film",
        "pagina",
        "recenti",
        "risultati",
        "serie",
        "totali",
        "tv",
        "video",
    }
)
_POOLS_PREFIXES = frozenset(
    {
        "candidati",
        "clip",
        "contenuti",
        "costruisci",
        "elementi",
        "episodi",
        "extra",
        "finestra",
        "giorni",
        "intrattenimento",
        "mesi",
        "pool",
        "programma",
        "raggruppa",
        "recenti",
        "stesso",
        "usa",
    }
)
_CONSUMER_PREFIXES = frozenset(
    {
        "aggiungi",
        "alternative",
        "best",
        "coda",
        "combina",
        "consumer",
        "contenuti",
        "deduplica",
        "elementi",
        "fallback",
        "finale",
        "full",
        "intrat_recent",
        "limita",
        "meno",
        "near",
        "piatti",
        "pool",
        "plus",
        "primo",
        "promuovi",
        "recenti",
        "take",
        "usa",
    }
)
_POOLS_REQUIRED_PHRASES = (
    "quattro pool",
    "50 elementi ciascuno",
    "18 mesi per gli episodi",
    "14 giorni per i contenuti recenti",
    "raggruppa per programma",
)
_CONSUMER_REQUIRED_PHRASES = (
    "primo take da 4",
    "finale da 24",
    "combina i pool con alternative best plus near full",
    "promuovi contenuti recenti",
    "deduplica",
    "limita a 24",
    "se gli elementi piatti sono meno di uno",
    "aggiungi in coda il fallback intrat recent",
)


def _similar_family(text: str) -> str | None:
    hits = tuple(
        family
        for family, present in (
            (
                "similar_entertainment",
                "intrattenimento" in text and not _negated(text, "intrattenimento"),
            ),
            (
                "similar_series",
                "serie" in text
                and "fiction" in text
                and not (_negated(text, "serie") or _negated(text, "fiction")),
            ),
            (
                "similar_film",
                any(token in text for token in ("film", "cinema", "cinematograf"))
                and not _negated(text, "film"),
            ),
        )
        if present
    )
    return hits[0] if len(hits) == 1 else None


def _initial_contract_need(
    messages: tuple[CreateAuthorityHistoryMessage, ...],
) -> StructuralNeed | None:
    if len(messages) != 2:
        return StructuralNeed(
            "structure.initial_contract", "Specifica la struttura iniziale completa."
        )
    first, latest = (normalize_operator_text(item.text) for item in messages)
    if _negated(latest, "catalogo") or _negated(latest, "risultati"):
        return StructuralNeed(
            "structure.initial_contract", "Conferma catalogo e quantità richiesti."
        )
    count = total_count_from_message(messages[-1].text, scopes=frozenset({"total", "row"}))
    if "titoli del momento" in first:
        if (
            count is None
            or "recent" not in latest
            or "film" not in latest
            or "serie tv" not in latest
            or not _closed_tokens(
                messages[0].text, prefixes=_RECENT_FIRST_PREFIXES, numbers=frozenset()
            )
            or not _closed_tokens(
                messages[-1].text,
                prefixes=_RECENT_SECOND_PREFIXES,
                numbers=frozenset({count}),
            )
        ):
            return StructuralNeed(
                "structure.recent_page_contract",
                "Specifica quantità, tipi di contenuto e criterio di recenza della pagina.",
            )
        return None
    if _has_similarity(first):
        if _similar_family(first) is None:
            return StructuralNeed(
                "structure.content_type",
                "Quale singola famiglia di contenuti deve alimentare la riga simile?",
            )
        if (
            count is None
            or not any(token in latest for token in ("seed", "contenuto visto"))
            or _negated(latest, "seed")
            or _negated(latest, "contenuto visto")
            or not _closed_tokens(
                messages[0].text,
                prefixes=_SIMILAR_FIRST_PREFIXES,
                numbers=frozenset(),
            )
            or not _closed_tokens(
                messages[-1].text,
                prefixes=_SIMILAR_SECOND_PREFIXES,
                numbers=frozenset({count}),
            )
        ):
            return StructuralNeed(
                "structure.seed_and_count",
                "Specifica tipo, seed e numero esatto di risultati della riga.",
            )
        return None
    need = blocked_structure_need(messages)
    return StructuralNeed(need.target_key, need.question)


def _has_exact_pool_composition(text: str) -> bool:
    return (
        "episodi dello stesso programma" in text
        and re.search(r"\bclip(?:/| e | ed )extra\b", text) is not None
        and "episodi di intrattenimento" in text
        and "clip di intrattenimento" in text
    )


def presemantic_structural_need(
    messages: tuple[CreateAuthorityHistoryMessage, ...], *, generation: int
) -> StructuralNeed | None:
    """Classify unsupported structure before demanding a single-catalog projection."""

    if not messages:
        _invalid("structural dialogue is absent")
    first = normalize_operator_text(messages[0].text)
    if generation == 0:
        if len(messages) > 2:
            need = blocked_structure_need(messages)
            return StructuralNeed(need.target_key, need.question)
        return _initial_contract_need(messages)
    if "intrattenimento" not in first or not _has_similarity(first):
        need = blocked_structure_need(messages)
        return StructuralNeed(need.target_key, need.question)
    latest = normalize_operator_text(messages[-1].text)
    if generation == 1:
        if (
            all(token in latest for token in _POOLS_REQUIRED_PHRASES)
            and _has_exact_pool_composition(latest)
            and not any(_negated(latest, token) for token in ("pool", "raggruppa"))
            and _closed_tokens(
                messages[-1].text,
                prefixes=_POOLS_PREFIXES,
                numbers=frozenset({14, 18, 50}),
            )
        ):
            return None
        return StructuralNeed(
            "context.pools.contract",
            "Specifica numero, composizione, finestre e raggruppamento di ogni pool.",
        )
    if generation == 2:
        lexical = latest.replace("-", " ").replace("_", " ")
        match = re.search(r"\bfallback\s+([a-z_][a-z0-9_.-]*)\b", latest)
        if match is None or match.group(1) != "intrat_recent":
            return StructuralNeed(
                "consumer.fallback_target", "Qual è il target materializzato esatto del fallback?"
            )
        if (
            not all(token in lexical for token in _CONSUMER_REQUIRED_PHRASES)
            or _negated(latest, "fallback")
            or not _closed_tokens(
                messages[-1].text,
                prefixes=_CONSUMER_PREFIXES,
                numbers=frozenset({4, 24}),
            )
        ):
            return StructuralNeed(
                "consumer.output_and_fallback_contract",
                "Specifica take, composizione, deduplica, limite e fallback del consumer.",
            )
        return None
    raise BrainError("CREATE_TYPED_AUTHORITY_STALE", 409, "refinement generation differs")


def closed_structural_semantic_requirements(
    messages: tuple[CreateAuthorityHistoryMessage, ...],
    *,
    generation: int,
    catalog: str,
) -> StructuralSemanticRequirements:
    """Return the exact code-owned value roster for one closed recipe.

    This function runs only after the complete operator utterance passes the
    same closed structural recognizer used by the builders.  It names exact
    catalog identities for the host resolver; it does not assert that those
    identities exist or are reviewed.
    """

    if _QUALIFIED_RE.fullmatch(catalog) is None:
        _invalid("structural semantic catalog is invalid")
    if presemantic_structural_need(messages, generation=generation) is not None:
        _invalid("structural semantic requirements need a closed recipe")
    first = normalize_operator_text(messages[0].text)
    if generation == 0:
        roster = "recent" if "titoli del momento" in first else _similar_family(first)
        if roster is None:  # pragma: no cover - the closed recognizer establishes one family
            _invalid("closed initial semantic family is invalid")
        pairs = _STRUCTURAL_VALUE_ROSTERS[roster]
        identities = tuple((catalog, field, literal) for field, literal in pairs)
        return StructuralSemanticRequirements(identities, identities)
    cumulative = tuple(
        (catalog, field, literal)
        for field, literal in _STRUCTURAL_VALUE_ROSTERS["entertainment_pools"]
    )
    if generation == 1:
        return StructuralSemanticRequirements(cumulative, cumulative)
    if generation == 2:
        return StructuralSemanticRequirements((), cumulative)
    raise BrainError("CREATE_TYPED_AUTHORITY_STALE", 409, "refinement generation differs")


def initial_family_need(message: str) -> tuple[str, str, str] | None:
    """Choose one T1 question that a richer natural follow-up can answer."""

    text = normalize_operator_text(message)
    if "dettaglio" in text or "compleanno" in text:
        return ("catalog", "catalog.selection", "Quali cataloghi devo usare?")
    if "ricerca" in text and "dettaglio" not in text:
        return ("page", "endpoint.results.page", "Quanti risultati vuoi per pagina?")
    if "divisi per genere" in text:
        return ("rows", "endpoint.rows.page", "Quante righe vuoi nella pagina?")
    if "4k" in text or "intrattenimento" in text:
        return ("row", "endpoint.results.row", "Quanti risultati vuoi nella riga?")
    if _has_similarity(text) or any(
        word in text for word in ("tvod", "titoli del momento", "pagina")
    ):
        return ("total", "endpoint.results.total", "Quanti risultati totali vuoi?")
    return None


def initial_ready_intent(
    *,
    messages: tuple[CreateAuthorityHistoryMessage, ...],
    semantic: ReviewedSemanticIndex,
    policy_revision: str,
) -> StructuralIntent | StructuralNeed:
    need = _initial_contract_need(messages)
    if need is not None:
        return need
    first = normalize_operator_text(messages[0].text)
    count = total_count_from_message(messages[-1].text, scopes=frozenset({"total", "row"}))
    if count is None:  # pragma: no cover - proven by _initial_contract_need
        _invalid("resolved initial quantity is absent")
    if "titoli del momento" in first:
        return recent_page_intent(
            values=("Film", "Serie TV"),
            count=count,
            messages=messages,
            semantic=semantic,
            policy_revision=policy_revision,
        )
    if _has_similarity(first):
        family = _similar_family(first)
        if family is None:
            return StructuralNeed(
                "structure.content_type",
                "Quale tipo di contenuto deve alimentare la riga simile?",
            )
        values = tuple(literal for _field, literal in _STRUCTURAL_VALUE_ROSTERS[family])
        return similar_row_intent(
            values=values,
            count=count,
            messages=messages,
            semantic=semantic,
            policy_revision=policy_revision,
        )
    return StructuralNeed(*blocked_structure_need(messages).target_key_question)


@dataclass(frozen=True, slots=True)
class _NeedPair:
    target_key: str
    question: str

    @property
    def target_key_question(self) -> tuple[str, str]:
        return self.target_key, self.question


def blocked_structure_need(messages: tuple[CreateAuthorityHistoryMessage, ...]) -> _NeedPair:
    """Return the earliest unresolved host-owned structural slot."""

    first = normalize_operator_text(messages[0].text)
    if _has_similarity(first) and any(
        token in normalize_operator_text(messages[-1].text)
        for token in ("rami", "percorsi", "variante")
    ):
        return _NeedPair(
            "routes.activation_contract",
            "Quali condizioni di attivazione verificabili distinguono i rami richiesti?",
        )
    if "dettaglio" in first and "ricerca" in first:
        return _NeedPair(
            "inputs.variant_and_4k_contract",
            "Specifica tipi, obbligatorietà e valori ammessi per variante e capacità 4K.",
        )
    if "ricerca" in first:
        return _NeedPair(
            "normalization.transformer_binding",
            "Quale trasformatore verificato deve normalizzare il testo di ricerca?",
        )
    if "compleanno" in first:
        return _NeedPair(
            "endpoint.variants.fetches.clauses.birthday",
            "Specifica il predicato verificato che identifica il compleanno.",
        )
    if "titoli del momento" in first:
        return _NeedPair(
            "endpoint.blocks.fetches.take_plan",
            "Specifica l'allocazione esatta dei take fra i blocchi richiesti.",
        )
    if "tvod" in first:
        return _NeedPair(
            "endpoint.blocks.genre.fetches.clauses.genre",
            "Specifica il parametro e il predicato verificato per le sezioni di genere.",
        )
    if "4k" in first:
        return _NeedPair(
            "endpoint.context.user.fetch.clauses",
            "Specifica il recupero utente e la condizione verificata "
            "sulla capacità del dispositivo.",
        )
    if "divisi per genere" in first:
        return _NeedPair(
            "endpoint.context.user.fetch.clauses",
            "Specifica il recupero verificato del contesto utente.",
        )
    return _NeedPair(
        "structure.contract",
        "Specifica il contratto strutturale mancante senza riferimenti impliciti.",
    )


def _basis_has_exact_similar_entertainment(spec: Mapping[str, Any]) -> bool:
    endpoint = spec.get("endpoint")
    if not isinstance(endpoint, Mapping):
        return False
    blocks, context, inputs = (
        endpoint.get("blocks"),
        endpoint.get("context"),
        endpoint.get("inputs"),
    )
    if (
        not isinstance(blocks, list)
        or len(blocks) != 1
        or not isinstance(context, list)
        or len(context) != 1
    ):
        return False
    if not isinstance(inputs, list) or len(inputs) != 1:
        return False
    try:
        predicate = blocks[0]["fetches"][0]["clauses"][0]["where"][0]
        similar = blocks[0]["fetches"][0]["clauses"][0]["where"][1]
    except (KeyError, IndexError, TypeError):
        return False
    return (
        predicate == _eq("tipologia", _literal("Intrattenimento"))
        and similar == _similar_seed()
        and endpoint.get("variants") == []
    )


def refinement_ready_intent(
    *,
    messages: tuple[CreateAuthorityHistoryMessage, ...],
    base_spec: Mapping[str, Any],
    generation: int,
    semantic: ReviewedSemanticIndex,
    policy_revision: str,
) -> StructuralIntent | StructuralNeed:
    need = presemantic_structural_need(messages, generation=generation)
    if need is not None:
        return need
    latest = normalize_operator_text(messages[-1].text)
    first = normalize_operator_text(messages[0].text)
    if "intrattenimento" not in first or not _has_similarity(first):
        need = blocked_structure_need(messages)
        return StructuralNeed(need.target_key, need.question)
    if generation == 1:
        if not _basis_has_exact_similar_entertainment(base_spec):
            raise BrainError("CREATE_TYPED_AUTHORITY_STALE", 409, "refinement basis differs")
        if not all(token in latest for token in _POOLS_REQUIRED_PHRASES) or any(
            _negated(latest, token) for token in ("pool", "raggruppa")
        ):
            return StructuralNeed(
                "context.pools.contract",
                "Specifica numero, composizione, finestre e raggruppamento di ogni pool.",
            )
        if not _has_exact_pool_composition(latest):
            return StructuralNeed(
                "context.pools.contract",
                "Specifica numero, composizione, finestre e raggruppamento di ogni pool.",
            )
        return entertainment_pools_intent(
            count=50,
            episode_window="18M",
            recent_window="14d",
            messages=messages,
            semantic=semantic,
            policy_revision=policy_revision,
        )
    if generation == 2:
        endpoint = base_spec.get("endpoint")
        if not isinstance(endpoint, Mapping):
            raise BrainError("CREATE_TYPED_AUTHORITY_STALE", 409, "refinement basis differs")
        blocks, context = endpoint.get("blocks"), endpoint.get("context")
        names = [item.get("name") for item in context] if isinstance(context, list) else []
        if (
            endpoint.get("needs_time") is not True
            or not isinstance(blocks, list)
            or len(blocks) != 1
            or names
            != [
                "seed",
                "pool_same_program",
                "pool_clips_extra",
                "pool_entertainment_episodes",
                "pool_entertainment_clips",
            ]
        ):
            raise BrainError("CREATE_TYPED_AUTHORITY_STALE", 409, "refinement basis differs")
        lexical = latest.replace("-", " ").replace("_", " ")
        match = re.search(r"\bfallback\s+([a-z_][a-z0-9_.-]*)\b", latest)
        if match is None or match.group(1) != "intrat_recent":
            return StructuralNeed(
                "consumer.fallback_target",
                "Qual è il target materializzato esatto del fallback?",
            )
        if not all(token in lexical for token in _CONSUMER_REQUIRED_PHRASES) or _negated(
            latest, "fallback"
        ):
            return StructuralNeed(
                "consumer.output_and_fallback_contract",
                "Specifica take, composizione, deduplica, limite e fallback del consumer.",
            )
        return entertainment_consumer_intent(
            first_count=4,
            final_count=24,
            recent_window="14d",
            fallback_target=match.group(1),
            basis_block=blocks[0],
            messages=messages,
            semantic=semantic,
            policy_revision=policy_revision,
        )
    raise BrainError("CREATE_TYPED_AUTHORITY_STALE", 409, "refinement generation differs")


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


def _implementation_fragment_roster() -> list[dict[str, Any]]:
    semantic = _validation_semantic("video")
    policy = "sha256:" + "1" * 64
    descriptor_semantic = ReviewedSemanticIndex(
        catalog="synthetic.assets",
        catalog_ref="assets",
        fields=frozenset({"attribute_x"}),
        values=frozenset({("attribute_x", "option_y")}),
        proof_revision="sha256:" + "2" * 64,
        selected_values=(("attribute_x", ("option_y",)),),
    )
    descriptor_collection = filtered_collection_intent(
        count=7,
        messages=(),
        semantic=descriptor_semantic,
        policy_revision=policy,
    )
    similar_film = similar_row_intent(
        values=("Film",),
        count=24,
        messages=(),
        semantic=semantic,
        policy_revision=policy,
    )
    similar_series = similar_row_intent(
        values=("Serie TV", "Fiction"),
        count=24,
        messages=(),
        semantic=semantic,
        policy_revision=policy,
    )
    similar_entertainment = similar_row_intent(
        values=("Intrattenimento",),
        count=24,
        messages=(),
        semantic=semantic,
        policy_revision=policy,
    )
    recent = recent_page_intent(
        values=("Film", "Serie TV"),
        count=30,
        messages=(),
        semantic=semantic,
        policy_revision=policy,
    )
    pools = entertainment_pools_intent(
        count=50,
        episode_window="18M",
        recent_window="14d",
        messages=(),
        semantic=semantic,
        policy_revision=policy,
    )
    consumer = entertainment_consumer_intent(
        first_count=4,
        final_count=24,
        recent_window="14d",
        fallback_target="intrat_recent",
        basis_block=similar_entertainment.mutations[2].fragment,
        messages=(),
        semantic=semantic,
        policy_revision=policy,
    )
    return [
        _structural_intent_manifest(item)
        for item in (
            descriptor_collection,
            similar_film,
            similar_series,
            similar_entertainment,
            recent,
            pools,
            consumer,
        )
    ]


_STRUCTURAL_RECIPE_MANIFEST["recognizers"] = {
    "similar_first": sorted(_SIMILAR_FIRST_PREFIXES),
    "similar_second": sorted(_SIMILAR_SECOND_PREFIXES),
    "recent_first": sorted(_RECENT_FIRST_PREFIXES),
    "recent_second": sorted(_RECENT_SECOND_PREFIXES),
    "pools": sorted(_POOLS_PREFIXES),
    "consumer": sorted(_CONSUMER_PREFIXES),
    "pools_required_phrases": list(_POOLS_REQUIRED_PHRASES),
    "consumer_required_phrases": list(_CONSUMER_REQUIRED_PHRASES),
    "similar": {
        "family_cardinality": "exactly_one",
        "seed_surfaces": ["seed", "contenuto visto"],
    },
    "recent": {
        "first_surface": "titoli del momento",
        "second_surfaces": ["film", "serie tv", "recent"],
    },
}
_STRUCTURAL_RECIPE_MANIFEST["fragments"] = _implementation_fragment_roster()
STRUCTURAL_CREATE_IMPLEMENTATION_SHA256 = canonical_sha256(_STRUCTURAL_RECIPE_MANIFEST)
del _STRUCTURAL_RECIPE_MANIFEST


__all__ = [
    "MAX_STRUCTURAL_MUTATIONS",
    "STRUCTURAL_CREATE_AUTHORITY_CONTRACT",
    "STRUCTURAL_CREATE_IMPLEMENTATION_SHA256",
    "ReviewedSemanticIndex",
    "StructuralSemanticRequirements",
    "StructuralIntent",
    "StructuralLeafEvidence",
    "StructuralMutation",
    "StructuralNeed",
    "blocked_structure_need",
    "closed_structural_semantic_requirements",
    "filtered_collection_intent",
    "initial_family_need",
    "initial_ready_intent",
    "normalize_operator_text",
    "presemantic_structural_need",
    "refinement_ready_intent",
    "reviewed_semantic_index",
    "reviewed_descriptor_filter_index",
    "total_count_from_message",
    "validate_structural_intent",
]
