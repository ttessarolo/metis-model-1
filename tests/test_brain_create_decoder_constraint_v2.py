"""Focused gates for the handle-only CREATE-v2 decoder constraint."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from metis_model1.brain_create_plan_v2 import (
    CompactAuthorityProjection,
    CreatePlanV2DecoderConstraint,
    ExpansionRow,
    FragmentLeafBinding,
    NodeGrant,
    RecipeGrant,
    RequirementHandle,
    SlotGrant,
    compact_authority_projection_revision,
    derive_create_plan_v2_decoder_constraint,
    validate_create_plan_v2_decoder_constraint_membership,
)
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json

SURFACE = "sha256:" + "c" * 64
REQ_ATTACH = "hostref:req-attach"
REQ_SET = "hostref:req-set"
EVIDENCE = "hostref:evidence"


def _hash(value: Any) -> str:
    return bytes_sha256(canonical_json(value))


def _bindings(value: Any, requirements: tuple[str, ...]) -> tuple[FragmentLeafBinding, ...]:
    def collect(item: Any, pointer: str = "") -> tuple[str, ...]:
        if isinstance(item, dict):
            return tuple(
                child
                for key, nested in item.items()
                for child in collect(nested, f"{pointer}/{key}")
            )
        if isinstance(item, list):
            return tuple(
                child
                for index, nested in enumerate(item)
                for child in collect(nested, f"{pointer}/{index}")
            )
        return (pointer,)

    return tuple(
        FragmentLeafBinding(pointer, EVIDENCE, requirements, "operator")
        for pointer in collect(value)
    )


def _slot(handle: int, ref: str, *, mutations: frozenset[str]) -> SlotGrant:
    return SlotGrant(
        handle,
        ref,
        f"slot {handle}",
        "hostref:anchor",
        "items",
        "many",
        ("value",),
        mutations,
        "append",
        None,
        0,
    )


def _node(
    handle: int,
    ref: str,
    *,
    parent: str,
    requirements: tuple[str, ...],
    state: str = "new",
    removable: bool = False,
) -> NodeGrant:
    fragment = {"kind": "lit", "lexical": "number", "value": handle}
    return NodeGrant(
        handle,
        ref,
        f"node {handle}",
        state,  # type: ignore[arg-type]
        "value",
        fragment,
        _hash(fragment),
        _bindings(fragment, requirements),
        "sha256:" + "f" * 64 if state == "basis" else None,
        ("endpoint", "items", handle) if state == "basis" else None,
        parent,
        removable,
    )


def _projection() -> CompactAuthorityProjection:
    requirements = (
        RequirementHandle(
            0, REQ_ATTACH, "requirement attach", frozenset({"attach", "remove", "expand"})
        ),
        RequirementHandle(1, REQ_SET, "requirement set", frozenset({"set"})),
    )
    attach_slot = _slot(10, "hostref:slot-attach", mutations=frozenset({"attach", "expand"}))
    set_slot = _slot(12, "hostref:slot-set", mutations=frozenset({"set"}))
    attach_node = _node(
        11, "hostref:node-attach", parent=attach_slot.ref, requirements=(REQ_ATTACH,)
    )
    set_node = _node(13, "hostref:node-set", parent=set_slot.ref, requirements=(REQ_SET,))
    removable = _node(
        14,
        "hostref:node-remove",
        parent=attach_slot.ref,
        requirements=(REQ_ATTACH,),
        state="basis",
        removable=True,
    )
    arguments = {"role": "editorial"}
    recipe = RecipeGrant(
        20,
        "hostref:recipe",
        "recipe",
        "role.compose/v1",
        1,
        "roleComposeRow",
        "value",
        ("items",),
        "sha256:" + "d" * 64,
        12,
        16,
    )
    row = ExpansionRow(
        30,
        "hostref:row",
        "row",
        recipe.recipe_id,
        recipe.row_type,
        arguments,
        _bindings(arguments, (REQ_ATTACH,)),
        _hash(arguments),
    )
    authorities = (attach_slot, set_slot, attach_node, set_node, removable, recipe, row)
    revision = compact_authority_projection_revision(
        surface_revision=SURFACE, requirements=requirements, authorities=authorities
    )
    return CompactAuthorityProjection(revision, SURFACE, requirements, authorities)


def _body(*operations: dict[str, Any]) -> dict[str, Any]:
    return {"o": list(operations)}


def test_constraint_is_canonical_handle_only_and_binds_projection_and_active_roster() -> None:
    projection = _projection()
    first = derive_create_plan_v2_decoder_constraint(projection, (1, 0))
    second = derive_create_plan_v2_decoder_constraint(projection, (0, 1))

    assert first == second
    assert first.active_requirement_handles == (0, 1)
    assert first.projection_revision == projection.projection_revision
    assert first.constraint_sha256 == _hash(first.payload())
    assert first.payload() == {
        "v": 1,
        "p": projection.projection_revision,
        "a": [0, 1],
        "d": [
            {"k": "a", "q": [0], "s": 10, "n": 11},
            {"k": "d", "q": [0], "n": 14},
            {"k": "s", "q": [1], "s": 12, "v": 13},
        ],
        "x": [{"s": 10, "r": 20, "w": [30]}],
    }
    serialized = canonical_json(first.payload())
    for forbidden in (b"hostref", b"evidence", b"node-attach", b"editorial", b"path"):
        assert forbidden not in serialized


def test_case06_canonical_direct_operations_are_members_and_role_swaps_are_rejected() -> None:
    constraint = derive_create_plan_v2_decoder_constraint(_projection(), (0, 1))
    canonical = _body(
        {"k": "a", "q": [0], "s": 10, "n": 11},
        {"k": "s", "q": [1], "s": 12, "v": 13},
    )
    assert validate_create_plan_v2_decoder_constraint_membership(canonical, constraint) is None

    for swapped in (
        _body({"k": "a", "q": [0], "s": 12, "n": 11}),
        _body({"k": "s", "q": [1], "s": 10, "v": 13}),
        _body({"k": "a", "q": [0], "s": 10, "n": 99}),
        _body({"k": "a", "q": [1], "s": 10, "n": 11}),
    ):
        with pytest.raises(BrainError, match="direct authority grammar"):
            validate_create_plan_v2_decoder_constraint_membership(swapped, constraint)


def test_expansion_descriptor_accepts_only_its_role_tuple_and_active_handles() -> None:
    constraint = derive_create_plan_v2_decoder_constraint(_projection(), (0, 1))
    assert (
        validate_create_plan_v2_decoder_constraint_membership(
            _body({"k": "x", "q": [0], "s": 10, "r": 20, "w": [30]}), constraint
        )
        is None
    )

    for invalid in (
        _body({"k": "x", "q": [0], "s": 12, "r": 20, "w": [30]}),
        _body({"k": "x", "q": [0], "s": 10, "r": 99, "w": [30]}),
        _body({"k": "x", "q": [0], "s": 10, "r": 20, "w": [99]}),
        _body({"k": "x", "q": [99], "s": 10, "r": 20, "w": [30]}),
    ):
        with pytest.raises(BrainError):
            validate_create_plan_v2_decoder_constraint_membership(invalid, constraint)


def test_constraint_digest_and_immutable_canonical_rosters_fail_closed_when_tampered() -> None:
    constraint = derive_create_plan_v2_decoder_constraint(_projection(), (0, 1))
    tampered_digest = replace(constraint, constraint_sha256="sha256:" + "0" * 64)
    tampered_roster = replace(constraint, active_requirement_handles=(1, 0))

    for tampered in (tampered_digest, tampered_roster):
        with pytest.raises(BrainError):
            validate_create_plan_v2_decoder_constraint_membership(
                _body({"k": "a", "q": [0], "s": 10, "n": 11}), tampered
            )
    assert isinstance(constraint, CreatePlanV2DecoderConstraint)
