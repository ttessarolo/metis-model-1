"""Neutral CREATE operations over original descriptors and typed operator choices.

This private host boundary does not interpret prose, infer domain roles, load a
tenant or execute a model. Every operation has an exact roster and reconstructs
its mutations from independently held original authority, never from a candidate.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from metis_model1.brain_create_builder import render_create_endpoint
from metis_model1.brain_create_structural_authority_v2 import (
    ReviewedSemanticIndex,
    StructuralAnchor,
    StructuralIntent,
    StructuralLeafEvidence,
    StructuralMutation,
    filtered_collection_intent,
    reviewed_descriptor_filter_index,
)
from metis_model1.brain_protocol import BrainError, canonical_sha256
from metis_model1.brain_retrieval import RetrievalResult
from metis_model1.brain_technical_authority import validate_technical_authority

DESCRIPTOR_OPERATION_FAMILY = "descriptor_operation"
DESCRIPTOR_OPERATION_CONTRACT = "metis-brain-descriptor-operation/v1"
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,95}$")
_ROSTERS = {
    "add_filtered_block": {"kind", "count", "mode"},
    "add_filtered_page": {"kind", "count"},
    "set_cardinality": {"kind", "block_index", "fetch_index", "count", "mode"},
    "order_by_field": {"kind", "block_index", "fetch_index", "field", "direction"},
    "return_projection": {"kind", "block_index", "fetch_index", "projection"},
    "same_draft_fallback": {"kind", "block_index", "target_index", "trigger", "mode"},
    "similarity_from_input": {"kind", "block_index", "fetch_index", "profile"},
}


def _fail(message: str) -> None:
    raise BrainError("CREATE_STRUCTURAL_AUTHORITY_INVALID", 409, message)


def _unsupported(message: str) -> None:
    raise BrainError("CREATE_TYPED_AUTHORITY_UNSUPPORTED", 422, message)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return copy.deepcopy(value)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return copy.deepcopy(value)


def _hash(value: Any) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        _fail("descriptor operation binding is invalid")
    return value


def _choice(value: Any, choices: set[str]) -> bool:
    return isinstance(value, str) and value in choices


def _operation(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping) or not isinstance(raw.get("kind"), str):
        _fail("descriptor operation is invalid")
    operation = _plain(raw)
    kind = operation["kind"]
    keys = _ROSTERS.get(kind)
    if keys is None:
        _unsupported("descriptor operation is not supported")
    if kind == "same_draft_fallback" and operation.get("trigger") == "below":
        keys = keys | {"threshold"}
    if set(operation) != keys:
        _fail("descriptor operation field roster is invalid")
    for key in ("block_index", "fetch_index", "target_index"):
        if key in operation and (type(operation[key]) is not int or operation[key] < 0):
            _fail("descriptor operation target index is invalid")
    for key in ("count", "threshold"):
        if key in operation and (
            type(operation[key]) is not int or not 1 <= operation[key] <= 10_000
        ):
            _fail("descriptor operation cardinality is invalid")
    if kind in {"add_filtered_block", "set_cardinality"} and not _choice(
        operation["mode"], {"total"}
    ):
        _unsupported("a named block supports a fixed total; a page needs an emitted response root")
    if kind == "order_by_field" and (
        not isinstance(operation["field"], str)
        or _IDENTIFIER.fullmatch(operation["field"]) is None
        or not _choice(operation["direction"], {"ascending", "descending"})
    ):
        _fail("descriptor operation ordering is invalid")
    if kind == "return_projection" and (
        not isinstance(operation["projection"], str)
        or _IDENTIFIER.fullmatch(operation["projection"]) is None
    ):
        _fail("descriptor operation response projection is invalid")
    if kind == "similarity_from_input" and (
        not isinstance(operation["profile"], str)
        or _IDENTIFIER.fullmatch(operation["profile"]) is None
    ):
        _fail("descriptor operation similarity profile is invalid")
    if kind == "same_draft_fallback" and (
        not _choice(operation["trigger"], {"empty", "below"})
        or not _choice(operation["mode"], {"substitute", "append"})
    ):
        _fail("descriptor operation fallback is invalid")
    return operation


@dataclass(frozen=True, slots=True)
class DescriptorOperationAuthority:
    base_spec: Mapping[str, Any]
    operation: Mapping[str, Any]
    semantic: ReviewedSemanticIndex | None
    retrieved: RetrievalResult
    context_revision: str
    semantic_revision: str
    toolchain_binding: str
    tenant_id: str
    decision_revision: str

    def __post_init__(self) -> None:
        if not isinstance(self.base_spec, Mapping) or type(self.retrieved) is not RetrievalResult:
            _fail("descriptor operation original authority is invalid")
        if self.semantic is not None and type(self.semantic) is not ReviewedSemanticIndex:
            _fail("descriptor operation semantic authority is invalid")
        for value in (
            self.context_revision,
            self.semantic_revision,
            self.toolchain_binding,
            self.decision_revision,
        ):
            _hash(value)
        if not isinstance(self.tenant_id, str) or not self.tenant_id:
            _fail("descriptor operation tenant is invalid")
        base = _plain(self.base_spec)
        render_create_endpoint(base)
        operation = _operation(self.operation)
        original = self.retrieved
        if not isinstance(original.context, Mapping) or not isinstance(original.grounding, Mapping):
            _fail("descriptor operation original retrieval is invalid")
        context = _plain(original.context)
        for key, expected in (
            ("context_revision", self.context_revision),
            ("semantic_source_revision", self.semantic_revision),
            ("toolchain_binding", self.toolchain_binding),
        ):
            if context.get(key) != expected:
                _fail("descriptor operation original retrieval is stale")
        if original.semantic_source_revision != self.semantic_revision:
            _fail("descriptor operation semantic revision differs")
        if context.get("tenant_id") != self.tenant_id:
            _fail("descriptor operation original tenant differs")
        object.__setattr__(self, "base_spec", _freeze(base))
        object.__setattr__(self, "operation", _freeze(operation))
        object.__setattr__(
            self,
            "retrieved",
            RetrievalResult(
                context=_freeze(context),
                grounding=_freeze(original.grounding),
                semantic_source_revision=original.semantic_source_revision,
                catalog_candidates=_freeze(original.catalog_candidates),
                output_request=copy.deepcopy(original.output_request),
            ),
        )


def _retrieved(authority: DescriptorOperationAuthority) -> RetrievalResult:
    original = authority.retrieved
    return RetrievalResult(
        context=_plain(original.context),
        grounding=_plain(original.grounding),
        semantic_source_revision=original.semantic_source_revision,
        catalog_candidates=tuple(_plain(original.catalog_candidates)),
        output_request=original.output_request,
    )


def _technical(authority: DescriptorOperationAuthority) -> dict[str, Any] | None:
    raw = authority.retrieved.context.get("technical_authority")
    return (
        validate_technical_authority(
            _plain(raw),
            context_revision=authority.context_revision,
            semantic_source_revision=authority.semantic_revision,
            toolchain_binding=authority.toolchain_binding,
            tenant_id=authority.tenant_id,
        )
        if raw is not None
        else None
    )


def _catalog_context(authority: DescriptorOperationAuthority, name: str) -> Mapping[str, Any]:
    context = authority.retrieved.context
    candidates = [context.get("catalog"), *context.get("catalogs", ())]
    matches = [
        item for item in candidates if isinstance(item, Mapping) and item.get("name") == name
    ]
    if len(matches) != 1 or matches[0].get("semantic", {}).get("state") != "reviewed":
        _unsupported("target catalog lacks current reviewed descriptor authority")
    return matches[0]


def _target_catalog(
    authority: DescriptorOperationAuthority,
    fetch: Mapping[str, Any],
    technical: Mapping[str, Any] | None,
) -> str:
    origin = fetch.get("from")
    if not isinstance(origin, Mapping) or origin.get("kind") != "catalog":
        _unsupported("operation requires a catalog-backed target query")
    reference = origin.get("catalog")
    roster = (
        [item["name"] for item in technical["catalogs"]]
        if technical is not None
        else authority.retrieved.context.get("catalog_reference_roster")
    )
    if not isinstance(roster, (list, tuple)) or any(not isinstance(name, str) for name in roster):
        _fail("target catalog namespace authority is absent")
    matches = [name for name in roster if reference in {name, name.rsplit(".", 1)[-1]}]
    if len(matches) != 1:
        _unsupported("target catalog reference is not unique")
    _catalog_context(authority, matches[0])
    return matches[0]


def _at(items: list[Any], index: int, label: str) -> dict[str, Any]:
    if index >= len(items) or not isinstance(items[index], dict):
        _fail(f"descriptor operation {label} target is absent")
    return items[index]


def _leaves(value: Any, pointer: str = ""):
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield from _leaves(item, pointer + "/" + key.replace("~", "~0").replace("/", "~1"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _leaves(item, f"{pointer}/{index}")
    else:
        yield pointer, value


def _new_name(endpoint: Mapping[str, Any], *, prefix: str = "block") -> str:
    names: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if key in {"blocks", "variants"} and isinstance(nested, list):
                    names.update(item["name"] for item in nested if isinstance(item, Mapping))
                walk(nested)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(endpoint)
    if prefix == "block" and "main" not in names:
        return "main"
    return next(f"{prefix}_{index}" for index in range(1, 1025) if f"{prefix}_{index}" not in names)


def _similarity_mutations(
    authority: DescriptorOperationAuthority,
    *,
    policy_revision: str,
    technical: Mapping[str, Any] | None,
) -> tuple[StructuralMutation, ...]:
    """Declare a typed ID input and exact singleton producer, never a seed value."""

    if technical is None:
        _unsupported("similarity requires the pinned catalog technical declaration")
    endpoint = _plain(authority.base_spec)["endpoint"]
    operation = _plain(authority.operation)
    block = _at(endpoint["blocks"], operation["block_index"], "block")
    fetch = _at(block["fetches"], operation["fetch_index"], "query")
    catalog = _target_catalog(authority, fetch, technical)
    declaration = next(item for item in technical["catalogs"] if item["name"] == catalog)
    profiles = [
        item for item in declaration["similarity_profiles"] if item["name"] == operation["profile"]
    ]
    fields = [item for item in declaration["fields"] if item["name"] == declaration["id_field"]]
    if "record-similarity" not in declaration["capabilities"] or len(profiles) != 1:
        _unsupported("similarity profile is not declared by the source catalog and driver")
    if (
        len(fields) != 1
        or fields[0]["type"] not in {"keyword", "number", "long", "integer", "date", "boolean"}
        or fields[0]["modifiers"]
    ):
        _unsupported("similarity seed requires an explicitly declared scalar catalog identity")
    if any(
        value == "similar" and pointer.endswith("/op")
        for pointer, value in _leaves(fetch["clauses"])
    ):
        _unsupported("target query already has similarity; replacement needs an explicit decision")

    # Allocate fresh policy symbols without interpreting any user/domain names.
    names = {
        value
        for pointer, value in _leaves(endpoint)
        if pointer.endswith("/name") and isinstance(value, str)
    }

    def fresh(prefix: str) -> str:
        for index in range(1, 1025):
            candidate = f"{prefix}_{index}"
            if candidate not in names:
                names.add(candidate)
                return candidate
        _unsupported("similarity symbol namespace exceeds the bounded allocator")
        raise AssertionError("unreachable")

    input_name, context_name = fresh("seed_id"), fresh("seed_record")
    identity = {
        "technical_sha256": technical["sha256"],
        "catalog": catalog,
        "id_field": fields[0]["name"],
        "decision_revision": authority.decision_revision,
    }
    input_fragment = {
        "name": input_name,
        "type": fields[0]["type"],
        "required": True,
        "not_empty": fields[0]["type"] == "keyword",
        "default": None,
    }
    seed_fragment = {
        "kind": "fetch",
        "name": context_name,
        "fetch": {
            "from": copy.deepcopy(fetch["from"]),
            "cardinality": {"mode": "total", "value": 1},
            "over_fetch": None,
            "alias": None,
            "title": None,
            "activation": None,
            "presentation": {"pinned": None, "view_all": None, "meta": [], "meta_per_item": False},
            "clauses": [
                {
                    "intent": "include",
                    "where": [
                        {
                            "op": "eq",
                            "field": fields[0]["name"],
                            "value": {"kind": "input", "name": input_name},
                        }
                    ],
                }
            ],
            "group_by": None,
            "order": [],
            "output": None,
        },
    }
    clause_fragment = {
        "intent": "include",
        "where": [
            {
                "op": "similar",
                "form": "record",
                "profile": profiles[0]["name"],
                "target": {"kind": "ctx", "segments": [context_name]},
            }
        ],
    }
    profile_identity = {
        **identity,
        "profile": profiles[0]["name"],
        "binding": profiles[0]["binding"],
    }
    anchor = StructuralAnchor(
        ("blocks", operation["block_index"], "fetches", operation["fetch_index"]), "fetch", fetch
    )
    result = []
    for member, fragment_type, fragment, target, technical_leaves, label in (
        (
            "inputs",
            "input",
            input_fragment,
            None,
            {"/type": identity},
            "Dichiara input ID del seed",
        ),
        (
            "context",
            "contextBinding",
            seed_fragment,
            None,
            {
                "/fetch/from/catalog": identity,
                "/fetch/clauses/0/where/0/field": identity,
            },
            "Carica il record seed dallo stesso catalogo",
        ),
        (
            "clauses",
            "clause",
            clause_fragment,
            anchor,
            {"/where/0/profile": profile_identity},
            "Seleziona contenuti simili al record seed",
        ),
    ):
        leaves = tuple(
            StructuralLeafEvidence(
                pointer,
                "pinned_technical" if pointer in technical_leaves else "policy",
                technical_leaves.get(
                    pointer,
                    {
                        "policy_revision": policy_revision,
                        "structural_pointer": pointer,
                        "operation_kind": "similarity_from_input",
                        "decision_revision": authority.decision_revision,
                    },
                ),
            )
            for pointer, _ in _leaves(fragment)
        )
        result.append(
            StructuralMutation(
                "attach",
                member,
                "many",
                "append",
                fragment_type,
                fragment,
                label,
                label,
                leaves,
                anchor=target,
            )
        )
    return tuple(result)


def _emitted_block_mutation(
    authority: DescriptorOperationAuthority,
    *,
    block: Mapping[str, Any],
    policy_revision: str,
) -> StructuralMutation:
    """Explicit add-block semantics include its use in one unambiguous response."""

    endpoint = _plain(authority.base_spec)["endpoint"]
    variants = endpoint["variants"]
    use = {"kind": "direct", "block": block["name"]}
    anchor = None
    if not variants:
        fragment = {
            "name": _new_name(endpoint, prefix="response_root"),
            "title": None,
            "activation": None,
            "empty": False,
            "presentation": {"pinned": None, "view_all": None, "meta": [], "meta_per_item": False},
            "fetches": [],
            "blocks": [],
            "uses": [use],
            "output": None,
        }
        member, fragment_type = "variants", "variant"
    else:
        if len(variants) != 1:
            _unsupported(
                "adding a response block requires an explicit target among multiple variants"
            )
        variant = variants[0]
        if variant["activation"] is not None or variant["empty"] is not False:
            _unsupported(
                "adding a response block requires an unconditional nonempty response variant"
            )

        pool = {item["name"]: item for item in endpoint["blocks"]}
        visited: set[str] = set()

        def parameterized(value: Any) -> bool:
            if isinstance(value, Mapping):
                if value.get("parameters"):
                    return True
                if "uses" in value and any(
                    use.get("kind") != "direct" or use.get("args") for use in value["uses"]
                ):
                    return True
                for item in value.get("uses", ()):
                    referenced = item["block"]
                    if referenced in pool and referenced not in visited:
                        visited.add(referenced)
                        if parameterized(pool[referenced]):
                            return True
                return any(parameterized(item) for item in value.values())
            if isinstance(value, list):
                return any(parameterized(item) for item in value)
            return False

        if parameterized(variant):
            _unsupported("adding a response block requires separate authority for parametric uses")
        fragment = use
        anchor = StructuralAnchor(("variants", 0), "variant", variant)
        member, fragment_type = "uses", "use"
    label = "Includi il nuovo blocco nella risposta"
    leaves = tuple(
        StructuralLeafEvidence(
            pointer,
            "policy",
            {
                "policy_revision": policy_revision,
                "structural_pointer": pointer,
                "decision_revision": authority.decision_revision,
                "new_block_sha256": canonical_sha256(block),
            },
        )
        for pointer, _ in _leaves(fragment)
    )
    return StructuralMutation(
        "attach",
        member,
        "many",
        "append",
        fragment_type,
        fragment,
        label,
        label,
        leaves,
        anchor=anchor,
    )


def _seal_intent(
    authority: DescriptorOperationAuthority,
    *,
    mutations: tuple[StructuralMutation, ...],
    technical: Mapping[str, Any] | None,
) -> StructuralIntent:
    base = _plain(authority.base_spec)
    candidate = copy.deepcopy(base)
    for mutation in mutations:
        parent = candidate["endpoint"]
        if mutation.anchor is not None:
            for part in mutation.anchor.path:
                parent = parent[part]
        if mutation.action == "attach":
            parent[mutation.member].append(copy.deepcopy(mutation.fragment))
        else:
            parent[mutation.member] = copy.deepcopy(mutation.fragment)
    render_create_endpoint(candidate)
    proof = canonical_sha256(
        {
            "contract_id": DESCRIPTOR_OPERATION_CONTRACT,
            "base_spec_sha256": canonical_sha256(base),
            "operation": _plain(authority.operation),
            "decision_revision": authority.decision_revision,
            "context_revision": authority.context_revision,
            "semantic_revision": authority.semantic_revision,
            "toolchain_binding": authority.toolchain_binding,
            "tenant_id": authority.tenant_id,
            "semantic_proof_revision": authority.semantic.proof_revision
            if authority.semantic
            else None,
            "technical_sha256": technical["sha256"] if technical is not None else None,
            "retrieval_context_sha256": canonical_sha256(_plain(authority.retrieved.context)),
            "retrieval_grounding_sha256": canonical_sha256(_plain(authority.retrieved.grounding)),
        }
    )
    return StructuralIntent(DESCRIPTOR_OPERATION_FAMILY, mutations, proof)


def build_descriptor_operation(
    authority: DescriptorOperationAuthority, *, policy_revision: str
) -> StructuralIntent:
    """Build one exact generic mutation from immutable original host authority."""

    if type(authority) is not DescriptorOperationAuthority:
        _fail("descriptor operation authority is unavailable")
    _hash(policy_revision)
    operation = _operation(authority.operation)
    base = _plain(authority.base_spec)
    endpoint = base["endpoint"]
    kind = operation["kind"]
    technical = _technical(authority)
    if kind == "similarity_from_input":
        return _seal_intent(
            authority,
            mutations=_similarity_mutations(
                authority, policy_revision=policy_revision, technical=technical
            ),
            technical=technical,
        )
    decision = {"decision_revision": authority.decision_revision, "operation_kind": kind}
    base_hash = canonical_sha256(base)
    origin_by_pointer: dict[str, tuple[str, dict[str, Any]]] = {}
    anchor = None
    semantic = authority.semantic

    if kind in {"add_filtered_block", "add_filtered_page"}:
        if semantic is None:
            _unsupported("adding a filtered block requires reviewed selections")
        if kind == "add_filtered_page" and (
            endpoint["variants"] or endpoint["params"]["paginate"] not in {None, "offset"}
        ):
            _unsupported("a new page requires an unselected offset/no-mode response root")
        reopened = reviewed_descriptor_filter_index(
            retrieved=_retrieved(authority),
            context_revision=authority.context_revision,
            semantic_revision=authority.semantic_revision,
            toolchain_binding=authority.toolchain_binding,
        )
        if reopened != semantic:
            _fail("original reviewed filter authority differs from retrieval")
        original = filtered_collection_intent(
            count=operation["count"],
            messages=(),
            semantic=semantic,
            policy_revision=policy_revision,
        ).mutations[0]
        fragment = copy.deepcopy(original.fragment)
        fragment["name"] = _new_name(
            endpoint, prefix="page" if kind == "add_filtered_page" else "block"
        )
        fragment["fetches"][0]["cardinality"]["mode"] = (
            "page_default" if kind == "add_filtered_page" else "total"
        )
        for leaf in original.leaf_evidence:
            origin_by_pointer[leaf.json_pointer] = (leaf.origin, dict(leaf.identity))
        for pointer in ("/fetches/0/cardinality/mode", "/fetches/0/cardinality/value"):
            origin_by_pointer[pointer] = ("clarification", decision)
        action, member, cardinality, insertion, fragment_type = (
            "attach",
            "blocks",
            "many",
            "append",
            "container",
        )
        label = "Aggiungi blocco filtrato"
        if kind == "add_filtered_page":
            fragment.pop("parameters")
            fragment["empty"] = False
            member, fragment_type, label = "variants", "variant", "Crea pagina filtrata"
    else:
        blocks = endpoint["blocks"]
        if len({item["name"] for item in blocks}) != len(blocks):
            _fail("original block namespace is ambiguous")
        block = _at(blocks, operation["block_index"], "block")
        block_path = ("blocks", operation["block_index"])
        if not block["fetches"]:
            _unsupported("operation requires a direct query in the selected block")
        catalog = _target_catalog(authority, block["fetches"][0], technical)
        action, cardinality, insertion = "set", "one", "replace"
        if kind in {"set_cardinality", "order_by_field", "return_projection"}:
            fetch = _at(block["fetches"], operation["fetch_index"], "query")
            catalog = _target_catalog(authority, fetch, technical)
            anchor = StructuralAnchor(
                (*block_path, "fetches", operation["fetch_index"]), "fetch", fetch
            )
            if kind == "set_cardinality":
                fragment = {"mode": operation["mode"], "value": operation["count"]}
                origin_by_pointer = {
                    pointer: ("clarification", decision) for pointer, _ in _leaves(fragment)
                }
                member, fragment_type, label = (
                    "cardinality",
                    "fetchCardinality",
                    "Imposta quantità fissa",
                )
            elif kind == "return_projection":
                if technical is None:
                    _unsupported(
                        "return projection requires the pinned catalog technical declaration"
                    )
                declaration = next(
                    item for item in technical["catalogs"] if item["name"] == catalog
                )
                projections = [
                    item
                    for item in declaration["projections"]
                    if item["name"] == operation["projection"]
                ]
                if len(projections) != 1:
                    _unsupported("response projection is not declared by the target catalog")
                existing = fetch["output"]
                fragment = (
                    copy.deepcopy(existing)
                    if existing is not None
                    else {
                        "projection": "default",
                        "steps": [],
                        "fallbacks": [],
                    }
                )
                origin_by_pointer.update(
                    {
                        pointer: (
                            "basis",
                            {
                                "base_spec_sha256": base_hash,
                                "anchor_path": list(anchor.path),
                                "locator": "/output" + pointer,
                            },
                        )
                        for pointer, _ in _leaves(existing)
                    }
                    if existing is not None
                    else {}
                )
                fragment["projection"] = projections[0]["name"]
                origin_by_pointer["/projection"] = (
                    "pinned_technical",
                    {
                        "technical_sha256": technical["sha256"],
                        "catalog": catalog,
                        "projection": projections[0]["name"],
                        **decision,
                    },
                )
                member, fragment_type, label = (
                    "output",
                    "returnFlow",
                    "Imposta proiezione del catalogo",
                )
            else:
                if technical is None:
                    _unsupported("ordering requires the pinned catalog technical declaration")
                catalog_technical = next(
                    item for item in technical["catalogs"] if item["name"] == catalog
                )
                context = authority.retrieved.context
                field = operation["field"]
                selected_catalog = context.get("catalog", {}).get("name")
                reviewed = [
                    item
                    for item in context.get("fields", ())
                    if item.get("name") == field
                    and item.get("catalog", selected_catalog) == catalog
                ]
                field_technical = [
                    item for item in catalog_technical["fields"] if item["name"] == field
                ]
                if len(reviewed) != 1 or reviewed[0].get("semantic", {}).get("state") != "reviewed":
                    _unsupported("ordering field lacks current reviewed semantics")
                if len(field_technical) != 1 or any(
                    _plain(reviewed[0].get(key)) != field_technical[0][key]
                    for key in ("type", "modifiers")
                ):
                    _fail("ordering field technical authority differs from semantics")
                if (
                    "search" not in catalog_technical["capabilities"]
                    or field_technical[0]["type"]
                    not in {"keyword", "number", "date", "duration", "boolean"}
                    or field_technical[0]["modifiers"]
                ):
                    _unsupported("ordering requires a scalar single-value sortable search field")
                if any(
                    item.get("by") == "field" and item.get("field") == field
                    for item in fetch["order"]
                ):
                    _unsupported("selected field already orders this query")
                fragment = {"by": "field", "field": field, "direction": operation["direction"]}
                origin_by_pointer["/field"] = (
                    "reviewed_semantic",
                    {
                        "catalog": catalog,
                        "field": field,
                        "descriptor_sha256": canonical_sha256(_plain(reviewed[0])),
                        "technical_sha256": technical["sha256"],
                    },
                )
                origin_by_pointer["/direction"] = ("clarification", decision)
                action, cardinality, insertion = "attach", "many", "append"
                member, fragment_type, label = "order", "order", "Aggiungi criterio di ordinamento"
        else:
            anchor = StructuralAnchor(block_path, "container", block)
            existing = block["output"]
            fragment = (
                copy.deepcopy(existing)
                if existing is not None
                else {"projection": "default", "steps": [], "fallbacks": []}
            )
            if existing is not None:
                origin_by_pointer.update(
                    {
                        pointer: (
                            "basis",
                            {
                                "base_spec_sha256": base_hash,
                                "anchor_path": list(block_path),
                                "locator": "/output" + pointer,
                            },
                        )
                        for pointer, _ in _leaves(existing)
                    }
                )
            if kind == "same_draft_fallback":
                target = _at(blocks, operation["target_index"], "fallback block")
                if operation["target_index"] == operation["block_index"]:
                    _unsupported("a block cannot fall back to itself")
                if target["parameters"]:
                    _unsupported("fallback target parameters require a separate explicit binding")
                if any(
                    item.get("trigger") == operation["trigger"]
                    or item.get("kind") == "materialized"
                    for item in fragment["fallbacks"]
                ):
                    _unsupported(
                        "fallback trigger is already bound or conflicts with materialized fallback"
                    )
                fallback = {
                    "kind": "direct",
                    "target": target["name"],
                    "target_kind": "block",
                    "trigger": operation["trigger"],
                    "mode": operation["mode"],
                }
                if "threshold" in operation:
                    fallback["threshold"] = operation["threshold"]
                prefix = f"/fallbacks/{len(fragment['fallbacks'])}"
                for key in ("trigger", "mode", "threshold"):
                    if key in fallback:
                        origin_by_pointer[prefix + "/" + key] = ("clarification", decision)
                origin_by_pointer[prefix + "/target"] = (
                    "basis",
                    {
                        "base_spec_sha256": base_hash,
                        "locator": ["endpoint", "blocks", operation["target_index"], "name"],
                        **decision,
                    },
                )
                fragment["fallbacks"].append(fallback)
                graph = {
                    item["name"]: [
                        fb["target"]
                        for fb in (fragment if item is block else item.get("output") or {}).get(
                            "fallbacks", []
                        )
                        if fb.get("kind") == "direct" and fb.get("target_kind") == "block"
                    ]
                    for item in blocks
                }

                completed: set[str] = set()

                def cycle(name: str, active: frozenset[str]) -> bool:
                    if name in completed:
                        return False
                    if name in active or any(
                        cycle(child, active | {name}) for child in graph.get(name, [])
                    ):
                        return True
                    completed.add(name)
                    return False

                if any(cycle(name, frozenset()) for name in graph):
                    _unsupported("same-Draft fallback would create a cycle")
                label = "Aggiungi ripiego verso un blocco della bozza"
            member, fragment_type = "output", "returnFlow"

    leaves = tuple(
        StructuralLeafEvidence(
            pointer,
            *origin_by_pointer.get(
                pointer,
                ("policy", {"policy_revision": policy_revision, "structural_pointer": pointer}),
            ),
        )
        for pointer, _value in _leaves(fragment)
    )
    mutation = StructuralMutation(
        action,
        member,
        cardinality,
        insertion,
        fragment_type,
        fragment,
        label,
        label,
        leaves,
        anchor=anchor,
    )
    mutations = (mutation,)
    if kind == "add_filtered_block":
        mutations += (
            _emitted_block_mutation(authority, block=fragment, policy_revision=policy_revision),
        )
    return _seal_intent(authority, mutations=mutations, technical=technical)


def validate_descriptor_operation(
    intent: StructuralIntent, *, authority: DescriptorOperationAuthority, policy_revision: str
) -> StructuralIntent:
    """Rebuild from original authority and compare every mutation, leaf and anchor."""

    if type(intent) is not StructuralIntent or intent != build_descriptor_operation(
        authority, policy_revision=policy_revision
    ):
        _fail("descriptor operation differs from independently held original authority")
    return intent


__all__ = [
    "DESCRIPTOR_OPERATION_FAMILY",
    "DescriptorOperationAuthority",
    "build_descriptor_operation",
    "validate_descriptor_operation",
]
