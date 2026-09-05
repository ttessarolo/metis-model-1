"""Issuer/executor unit proofs, not descriptor-engine or compiler qualification.

The construction validator is replaced by an explicit test spy so these tests
exercise the issuer's independent original-basis checks. Root integration tests
must separately exercise the real descriptor-operation authority validator.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest

import metis_model1.brain_create_authority_issuer_v2 as issuer_module
from metis_model1.brain_create_authority_issuer_v2 import (
    CreateV2HostRefIssuer,
    IssuedCreateV2Authority,
)
from metis_model1.brain_create_builder import render_create_endpoint
from metis_model1.brain_create_capability_inventory_v2 import (
    build_pinned_create_v2_capability_inventory,
)
from metis_model1.brain_create_executor_v2 import (
    CreateDeltaPlanV2ExecutionError,
    CreateDeltaPlanV2PermitConsumer,
    execute_create_delta_plan_v2,
    issue_create_delta_plan_v2_permit,
)
from metis_model1.brain_create_plan_v2 import (
    MAX_AUTHORITY_HANDLES,
    NodeGrant,
    SlotGrant,
    admit_create_delta_plan_v2,
    initial_create_endpoint_skeleton,
    validate_compact_authority_projection,
)
from metis_model1.brain_create_structural_authority_v2 import (
    StructuralAnchor,
    StructuralIntent,
    StructuralLeafEvidence,
    StructuralMutation,
)
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_sha256

TOOLCHAIN = bytes_sha256(b"nested-test-toolchain")
CONTEXT = bytes_sha256(b"nested-test-context")
SEMANTIC = bytes_sha256(b"nested-test-semantic")
ENDPOINT = "synthetic.nested"


def _presentation() -> dict[str, Any]:
    return {"pinned": None, "view_all": None, "meta": [], "meta_per_item": False}


def _fetch(count: int) -> dict[str, Any]:
    return {
        "from": {"kind": "catalog", "catalog": "records"},
        "cardinality": {"mode": "total", "value": count},
        "over_fetch": None,
        "alias": None,
        "title": None,
        "activation": None,
        "presentation": _presentation(),
        "clauses": [],
        "group_by": None,
        "order": [],
        "output": None,
    }


def _base() -> dict[str, Any]:
    base = initial_create_endpoint_skeleton(ENDPOINT)
    base["endpoint"]["blocks"] = [
        {
            "name": name,
            "parameters": [],
            "title": None,
            "activation": None,
            "presentation": _presentation(),
            "fetches": [_fetch(count)],
            "blocks": [],
            "uses": [],
            "output": None,
        }
        for name, count in (("first", 8), ("second", 24))
    ]
    return base


def _leaves(fragment: Any, pointer: str = "") -> tuple[StructuralLeafEvidence, ...]:
    if isinstance(fragment, dict):
        return tuple(
            leaf
            for key, value in fragment.items()
            for leaf in _leaves(value, f"{pointer}/{key.replace('~', '~0').replace('/', '~1')}")
        )
    if isinstance(fragment, list):
        return tuple(
            leaf
            for index, value in enumerate(fragment)
            for leaf in _leaves(value, f"{pointer}/{index}")
        )
    return (StructuralLeafEvidence(pointer, "pinned_technical", {"test_only": "issuer-unit"}),)


def _mutation(base: dict[str, Any], *, ordinal: int = 1) -> StructuralMutation:
    fragment = {"mode": "total", "value": 12}
    return StructuralMutation(
        action="set",
        member="cardinality",
        cardinality="one",
        insertion="replace",
        fragment_type="cardinality",
        fragment=fragment,
        label="Conteggio selezionato",
        requirement_label="Imposta il conteggio richiesto",
        leaf_evidence=_leaves(fragment),
        anchor=StructuralAnchor(
            ("blocks", ordinal, "fetches", 0),
            "fetch",
            base["endpoint"]["blocks"][ordinal]["fetches"][0],
        ),
    )


def _intent(*mutations: StructuralMutation) -> StructuralIntent:
    return StructuralIntent("issuer_unit_nested", mutations, SEMANTIC)


@pytest.fixture
def validator_spy(monkeypatch: pytest.MonkeyPatch) -> list[tuple[StructuralIntent, dict[str, Any]]]:
    calls: list[tuple[StructuralIntent, dict[str, Any]]] = []

    def validate(intent: StructuralIntent, **kwargs: Any) -> StructuralIntent:
        calls.append((intent, kwargs))
        return intent

    monkeypatch.setattr(issuer_module, "validate_structural_intent", validate)
    return calls


def _issue(
    intent: StructuralIntent,
    base: dict[str, Any],
    *,
    generation: int = 1,
    authority: Any = ...,
    parent_hash: str | None = None,
) -> IssuedCreateV2Authority:
    if authority is ...:
        authority = SimpleNamespace(base_spec=copy.deepcopy(base))
    issuer = CreateV2HostRefIssuer(hmac_key=b"n" * 32)
    try:
        return issuer.issue_structural_authority(
            inventory=build_pinned_create_v2_capability_inventory(toolchain_binding=TOOLCHAIN),
            intent=intent,
            construction_authority=authority,
            session_id="n" * 43,
            conversation_id=bytes_sha256(b"nested-conversation"),
            request_fingerprint=bytes_sha256(b"nested-request"),
            history_revision=bytes_sha256(b"nested-history"),
            context_revision=CONTEXT,
            semantic_revision=SEMANTIC,
            toolchain_binding=TOOLCHAIN,
            generation=generation,
            endpoint=ENDPOINT,
            candidate_filename="brain-drafts/nested.metis",
            parent_spec_sha256=(parent_hash or canonical_sha256(base)) if generation else None,
            parent_ir_sha256=bytes_sha256(b"nested-parent-ir") if generation else None,
            parent_proposal_ref="parent-nested" if generation else None,
        )
    finally:
        issuer.close()


def _execute(
    issued: IssuedCreateV2Authority, base: dict[str, Any], body: dict[str, Any]
) -> dict[str, Any]:
    plan = admit_create_delta_plan_v2(
        body,
        projection=issued.projection,
        mode="refinement",
        context_revision=CONTEXT,
        semantic_revision=SEMANTIC,
        target_ref=issued.target_ref,
        basis_ref=issued.basis_ref,
        active_requirement_handles=issued.active_requirement_handles,
    )
    parent = canonical_sha256(base)
    permit = issue_create_delta_plan_v2_permit(
        plan,
        issued.projection,
        base_spec=base,
        toolchain_binding=TOOLCHAIN,
        generation=1,
        parent_spec_sha256=parent,
    )
    result = execute_create_delta_plan_v2(
        plan,
        issued.projection,
        base_spec=base,
        parent_spec_sha256=parent,
        permit_consumer=CreateDeltaPlanV2PermitConsumer(permit),
        toolchain_binding=TOOLCHAIN,
        generation=1,
    )
    return dict(result.spec)


def test_nested_unit_issuance_and_executor_preserve_sibling_order_and_original_base(
    validator_spy: list[Any],
) -> None:
    base = _base()
    original = copy.deepcopy(base)
    mutation = _mutation(base)
    intent = _intent(mutation)
    authority = SimpleNamespace(base_spec=copy.deepcopy(base))
    issued = _issue(intent, base, authority=authority)
    assert validator_spy[0][0] is intent
    assert validator_spy[0][1]["construction_authority"] is authority
    index = validate_compact_authority_projection(issued.projection)
    anchor = index.nodes_by_handle[100]
    assert anchor.state == "basis" and not anchor.removable
    assert anchor.parent_slot_ref is None
    assert anchor.basis_path == ("blocks", 1, "fetches", 0)
    assert anchor.basis_spec_sha256 == canonical_sha256(base)
    assert index.slots_by_handle[10].anchor_ref == anchor.ref != issued.target_ref
    assert {leaf.origin for leaf in anchor.leaf_bindings} == {"basis"}
    assert {leaf.origin for leaf in index.nodes_by_handle[11].leaf_bindings} == {"pinned_technical"}
    result = _execute(issued, base, {"o": [{"k": "s", "q": [0], "s": 10, "v": 11}]})
    expected = copy.deepcopy(base)
    expected["endpoint"]["blocks"][1]["fetches"][0]["cardinality"]["value"] = 12
    assert result == expected
    assert base == original == authority.base_spec
    assert [block["name"] for block in result["endpoint"]["blocks"]] == ["first", "second"]
    assert "take 12" in render_create_endpoint(result).metis_text


def test_nested_unit_multi_mutation_has_noncolliding_handles_and_exact_slot_anchors(
    validator_spy: list[Any],
) -> None:
    del validator_spy
    base = _base()
    extra_fetch = _fetch(5)
    append = StructuralMutation(
        action="attach",
        member="fetches",
        cardinality="many",
        insertion="append",
        fragment_type="fetch",
        fragment=extra_fetch,
        label="Query aggiunta",
        requirement_label="Aggiungi la query richiesta",
        leaf_evidence=_leaves(extra_fetch),
        anchor=StructuralAnchor(("blocks", 1), "container", base["endpoint"]["blocks"][1]),
    )
    issued = _issue(_intent(_mutation(base), append), base)
    handles = [grant.handle for grant in issued.projection.authorities]
    assert len(handles) == len(set(handles)) == 6
    assert max(handles) < MAX_AUTHORITY_HANDLES
    assert set(handles) == {10, 11, 12, 13, 100, 101}
    result = _execute(
        issued,
        base,
        {"o": [{"k": "s", "q": [0], "s": 10, "v": 11}, {"k": "a", "q": [1], "s": 12, "n": 13}]},
    )
    expected = copy.deepcopy(base)
    expected["endpoint"]["blocks"][1]["fetches"][0]["cardinality"]["value"] = 12
    expected["endpoint"]["blocks"][1]["fetches"].append(extra_fetch)
    assert result == expected
    assert render_create_endpoint(result).metis_text


@pytest.mark.parametrize("authority", (None, SimpleNamespace(), SimpleNamespace(base_spec=[])))
def test_nested_unit_refuses_missing_original_construction_basis(
    validator_spy: list[Any], authority: Any
) -> None:
    del validator_spy
    base = _base()
    with pytest.raises(BrainError):
        _issue(_intent(_mutation(base)), base, authority=authority)


@pytest.mark.parametrize("anchored", (True, False))
def test_nested_unit_compares_original_base_hash_even_without_an_anchor(
    validator_spy: list[Any], anchored: bool
) -> None:
    del validator_spy
    base = _base()
    mutation = _mutation(base)
    if not anchored:
        mutation = replace(mutation, anchor=None)
    with pytest.raises(BrainError, match="construction authority basis differs") as caught:
        _issue(_intent(mutation), base, parent_hash=bytes_sha256(b"foreign-parent"))
    assert caught.value.code == "CREATE_V2_AUTHORITY_STALE"


def test_nested_unit_refuses_initial_generation_anchor(validator_spy: list[Any]) -> None:
    del validator_spy
    base = _base()
    with pytest.raises(BrainError, match="original refinement basis"):
        _issue(_intent(_mutation(base)), base, generation=0)


@pytest.mark.parametrize(
    "path",
    (
        ("blocks", 0, "fetches", 0),
        ("blocks", 9, "fetches", 0),
        ("endpoint", "blocks", 1),
        ("blocks", 1, "name"),
    ),
)
def test_nested_unit_rejects_swapped_absent_or_scalar_basis_path(
    validator_spy: list[Any], path: tuple[str | int, ...]
) -> None:
    del validator_spy
    base = _base()
    mutation = _mutation(base)
    assert mutation.anchor is not None
    forged = replace(mutation, anchor=replace(mutation.anchor, path=path))
    with pytest.raises(BrainError):
        _issue(_intent(forged), base)


def test_nested_unit_rejects_forged_anchor_fragment_and_absent_target_member(
    validator_spy: list[Any],
) -> None:
    del validator_spy
    base = _base()
    mutation = _mutation(base)
    assert mutation.anchor is not None
    forged_fragment = copy.deepcopy(mutation.anchor.fragment)
    forged_fragment["cardinality"]["value"] = 12
    forged = replace(mutation, anchor=replace(mutation.anchor, fragment=forged_fragment))
    with pytest.raises(BrainError, match="anchor differs"):
        _issue(_intent(forged), base)
    with pytest.raises(BrainError, match="member is absent"):
        _issue(_intent(replace(mutation, member="does_not_exist")), base)


def test_nested_unit_anchors_are_not_removable_or_attachable_by_a_model(
    validator_spy: list[Any],
) -> None:
    del validator_spy
    base = _base()
    issued = _issue(_intent(_mutation(base)), base)
    for operation in (
        {"k": "d", "q": [0], "n": 100},
        {"k": "a", "q": [0], "s": 10, "n": 100},
    ):
        with pytest.raises(BrainError):
            _execute(issued, base, {"o": [operation]})


def test_nested_unit_anchor_location_enters_refs_and_surface_revision(
    validator_spy: list[Any],
) -> None:
    del validator_spy
    base = _base()
    # Identical subtree contents must not collapse two different locations.
    base["endpoint"]["blocks"][0]["fetches"][0] = _fetch(24)
    first = _issue(_intent(_mutation(base, ordinal=0)), base)
    second = _issue(_intent(_mutation(base, ordinal=1)), base)
    assert first.projection.surface_revision != second.projection.surface_revision
    assert first.projection.projection_revision != second.projection.projection_revision
    for kind in (NodeGrant, SlotGrant):
        first_refs = {item.ref for item in first.projection.authorities if isinstance(item, kind)}
        second_refs = {item.ref for item in second.projection.authorities if isinstance(item, kind)}
        assert first_refs.isdisjoint(second_refs)


def test_nested_unit_executor_reopens_anchor_against_the_bound_parent(
    validator_spy: list[Any],
) -> None:
    del validator_spy
    base = _base()
    issued = _issue(_intent(_mutation(base)), base)
    tampered = copy.deepcopy(base)
    tampered["endpoint"]["blocks"][0]["fetches"][0]["cardinality"]["value"] = 99
    with pytest.raises(CreateDeltaPlanV2ExecutionError, match="basis node spec hash differs"):
        _execute(issued, tampered, {"o": [{"k": "s", "q": [0], "s": 10, "v": 11}]})


def test_nested_unit_does_not_suppress_the_construction_validator_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _base()

    def reject(*_args: Any, **_kwargs: Any) -> None:
        raise BrainError("CREATE_STRUCTURAL_AUTHORITY_INVALID", 500, "untrusted construction")

    monkeypatch.setattr(issuer_module, "validate_structural_intent", reject)
    with pytest.raises(BrainError, match="untrusted construction"):
        _issue(_intent(_mutation(base)), base)
