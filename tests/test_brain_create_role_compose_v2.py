"""Adversarial gates for the generic, source-free role composition recipe."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from metis_model1.brain_create_builder import render_create_endpoint
from metis_model1.brain_create_combinators import (
    COMBINATOR_IMPLEMENTATION_SHA256,
    COMBINATOR_SCOPE_MEMBERS,
    AttachEmission,
    SetEmission,
    execute_combinator,
)
from metis_model1.brain_create_executor_v2 import (
    CreateDeltaPlanV2PermitConsumer,
    execute_create_delta_plan_v2,
    issue_create_delta_plan_v2_permit,
)
from metis_model1.brain_create_plan_v2 import (
    CompactAuthorityProjection,
    ExpansionRow,
    FragmentLeafBinding,
    NodeGrant,
    RecipeGrant,
    RequirementHandle,
    SlotGrant,
    admit_create_delta_plan_v2,
    compact_authority_projection_revision,
    initial_create_endpoint_skeleton,
)
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json

TARGET = "hostref:role-target"
STRUCTURE = "hostref:requirement-structure"
CONTENT = "hostref:requirement-content"
EVIDENCE = "hostref:role-evidence"
CONTEXT = bytes_sha256(b"role-compose-context")
SEMANTIC = bytes_sha256(b"role-compose-semantic")
SURFACE = bytes_sha256(b"role-compose-surface")
TOOLCHAIN = bytes_sha256(b"role-compose-toolchain")


def _sha(value: Any) -> str:
    return bytes_sha256(canonical_json(value))


def _leaf_pointers(value: Any, pointer: str = "") -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(
            child
            for key, nested in value.items()
            for child in _leaf_pointers(
                nested, f"{pointer}/{key.replace('~', '~0').replace('/', '~1')}"
            )
        )
    if isinstance(value, list):
        return tuple(
            child
            for index, nested in enumerate(value)
            for child in _leaf_pointers(nested, f"{pointer}/{index}")
        )
    return (pointer,)


def _bindings(value: Any, *requirements: str) -> tuple[FragmentLeafBinding, ...]:
    return tuple(
        FragmentLeafBinding(pointer, EVIDENCE, tuple(requirements), "operator")
        for pointer in _leaf_pointers(value)
    )


def _presentation() -> dict[str, Any]:
    return {"pinned": None, "view_all": None, "meta": [], "meta_per_item": False}


def _fetch(*, count: int) -> dict[str, Any]:
    return {
        "from": {"kind": "catalog", "catalog": "video"},
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


def _full_block() -> dict[str, Any]:
    return {
        "name": "film_italiani",
        "parameters": [],
        "title": None,
        "activation": None,
        "presentation": _presentation(),
        "fetches": [_fetch(count=24)],
        "blocks": [],
        "uses": [],
        "output": None,
    }


def _slot(
    handle: int,
    ref: str,
    *,
    anchor: str = TARGET,
    member: str = "items",
    cardinality: str = "many",
    accepts: tuple[str, ...] = ("value",),
    mutations: frozenset[str] = frozenset({"attach", "expand"}),
    insertion: str = "append",
) -> SlotGrant:
    return SlotGrant(
        handle,
        ref,
        f"posizione verificata {handle}",
        anchor,
        member,
        cardinality,  # type: ignore[arg-type]
        accepts,
        mutations,
        insertion,  # type: ignore[arg-type]
        None,
        0,
    )


def _node(
    handle: int,
    ref: str,
    fragment: Any,
    *,
    parent: str,
    fragment_type: str,
    requirements: tuple[str, ...],
) -> NodeGrant:
    return NodeGrant(
        handle,
        ref,
        f"elemento verificato {handle}",
        "new",
        fragment_type,
        fragment,
        _sha(fragment),
        _bindings(fragment, *requirements),
        None,
        None,
        parent,
        False,
    )


def _recipe(
    handle: int = 30,
    *,
    recipe_id: str = "role.compose/v1",
    row_type: str = "roleComposeRow",
) -> RecipeGrant:
    return RecipeGrant(
        handle,
        f"hostref:recipe-{handle}",
        "composizione di ruolo verificata",
        recipe_id,
        1,
        row_type,
        "value",
        COMBINATOR_SCOPE_MEMBERS,
        COMBINATOR_IMPLEMENTATION_SHA256[recipe_id],
        12,
        64,
    )


def _row(
    handle: int,
    arguments: Any,
    *,
    requirements: tuple[str, ...],
    recipe_id: str = "role.compose/v1",
    row_type: str = "roleComposeRow",
) -> ExpansionRow:
    return ExpansionRow(
        handle,
        f"hostref:row-{handle}",
        f"ruolo verificato {handle}",
        recipe_id,
        row_type,
        arguments,
        _bindings(arguments, *requirements),
        _sha(arguments),
    )


def _requirement(handle: int, ref: str) -> RequirementHandle:
    return RequirementHandle(handle, ref, f"requisito verificato {handle}", frozenset({"expand"}))


def _projection(
    requirements: tuple[RequirementHandle, ...], *authorities: Any
) -> CompactAuthorityProjection:
    revision = compact_authority_projection_revision(
        surface_revision=SURFACE,
        requirements=requirements,
        authorities=authorities,
    )
    return CompactAuthorityProjection(revision, SURFACE, requirements, tuple(authorities))


def _admit(
    projection: CompactAuthorityProjection,
    *,
    slot: SlotGrant,
    recipe: RecipeGrant,
    row: ExpansionRow,
    requirement_handles: tuple[int, ...],
):
    return admit_create_delta_plan_v2(
        {
            "o": [
                {
                    "k": "x",
                    "q": list(requirement_handles),
                    "s": slot.handle,
                    "r": recipe.handle,
                    "w": [row.handle],
                }
            ]
        },
        projection=projection,
        mode="initial",
        context_revision=CONTEXT,
        semantic_revision=SEMANTIC,
        target_ref=TARGET,
        basis_ref=None,
        active_requirement_handles=requirement_handles,
    )


def _execute(plan: Any, projection: CompactAuthorityProjection) -> Any:
    base = initial_create_endpoint_skeleton("demo.role_compose")
    base["endpoint"]["items"] = []
    permit = issue_create_delta_plan_v2_permit(
        plan,
        projection,
        base_spec=base,
        toolchain_binding=TOOLCHAIN,
        generation=0,
    )
    return execute_create_delta_plan_v2(
        plan,
        projection,
        base_spec=base,
        parent_spec_sha256=None,
        permit_consumer=CreateDeltaPlanV2PermitConsumer(permit),
        toolchain_binding=TOOLCHAIN,
        generation=0,
    )


def _role_authorities(
    *, row_requirements: tuple[str, ...] = (STRUCTURE, CONTENT)
) -> tuple[
    SlotGrant, SlotGrant, SlotGrant, NodeGrant, NodeGrant, NodeGrant, RecipeGrant, ExpansionRow
]:
    root = _slot(10, "hostref:slot-root", accepts=("container",))
    children = _slot(
        11,
        "hostref:slot-children",
        anchor="hostref:node-container",
        accepts=("value",),
    )
    enabled = _slot(
        12,
        "hostref:slot-enabled",
        anchor="hostref:node-container",
        member="enabled",
        cardinality="one",
        accepts=("boolean",),
        mutations=frozenset({"set"}),
        insertion="replace",
    )
    container = _node(
        20,
        "hostref:node-container",
        {"name": "gruppo", "items": [], "enabled": False},
        parent=root.ref,
        fragment_type="container",
        requirements=(STRUCTURE,),
    )
    child = _node(
        21,
        "hostref:node-child",
        {"kind": "lit", "lexical": "text", "value": "contenuto"},
        parent=children.ref,
        fragment_type="value",
        requirements=(CONTENT,),
    )
    true_value = _node(
        22,
        "hostref:value-enabled",
        True,
        parent=enabled.ref,
        fragment_type="boolean",
        requirements=(CONTENT,),
    )
    recipe = _recipe()
    row = _row(
        40,
        {
            "steps": [
                {"kind": "attach", "node_ref": container.ref, "target_slot_ref": root.ref},
                {"kind": "attach", "node_ref": child.ref, "target_slot_ref": children.ref},
                {"kind": "set", "target_slot_ref": enabled.ref, "value_ref": true_value.ref},
            ]
        },
        requirements=row_requirements,
    )
    return root, children, enabled, container, child, true_value, recipe, row


def test_role_compose_is_generic_ordered_and_model_payload_contains_no_private_steps() -> None:
    authorities = _role_authorities()
    root, _, enabled, container, child, true_value, recipe, row = authorities
    requirements = (_requirement(0, STRUCTURE), _requirement(1, CONTENT))
    projection = _projection(requirements, *authorities)

    result = execute_combinator(
        projection,
        slot_handle=root.handle,
        recipe_handle=recipe.handle,
        row_handles=(row.handle,),
    )

    assert result.recipe_id == "role.compose/v1"
    assert result.emissions == (
        AttachEmission(row.ref, root.ref, container.ref),
        AttachEmission(row.ref, authorities[1].ref, child.ref),
        SetEmission(row.ref, enabled.ref, true_value.ref),
    )
    assert result.requirement_refs == frozenset({STRUCTURE, CONTENT})
    model_payload = projection.model_projection_payload()
    model_json = canonical_json(model_payload).decode("utf-8")
    assert all(
        private_value not in model_json
        for private_value in ("steps", "gruppo", "contenuto", "hostref:")
    )
    assert model_payload["r"] == [
        {
            "h": recipe.handle,
            "l": recipe.label,
            "i": "role.compose/v1",
            "t": "roleComposeRow",
            "o": "value",
            "g": list(COMBINATOR_SCOPE_MEMBERS),
            "m": 12,
        }
    ]


def test_role_compose_executes_parent_before_child_and_sets_only_projected_value() -> None:
    authorities = _role_authorities()
    root, _, _, _, _, _, recipe, row = authorities
    requirements = (_requirement(0, STRUCTURE), _requirement(1, CONTENT))
    projection = _projection(requirements, *authorities)
    plan = _admit(
        projection,
        slot=root,
        recipe=recipe,
        row=row,
        requirement_handles=(0, 1),
    )

    result = _execute(plan, projection)

    assert result.spec["endpoint"]["items"] == [
        {
            "name": "gruppo",
            "items": [{"kind": "lit", "lexical": "text", "value": "contenuto"}],
            "enabled": True,
        }
    ]
    assert result.proof_input.emitted_mutations == 3


def test_role_compose_materializes_full_builder_typed_block_and_fetch() -> None:
    blocks = _slot(
        10,
        "hostref:slot-blocks",
        member="blocks",
        accepts=("container",),
    )
    block_fragment = _full_block()
    block = _node(
        20,
        "hostref:node-block",
        block_fragment,
        parent=blocks.ref,
        fragment_type="container",
        requirements=(STRUCTURE, CONTENT),
    )
    recipe = _recipe()
    row = _row(
        40,
        {
            "steps": [
                {"kind": "attach", "node_ref": block.ref, "target_slot_ref": blocks.ref},
            ]
        },
        requirements=(STRUCTURE, CONTENT),
    )
    requirements = (_requirement(0, STRUCTURE), _requirement(1, CONTENT))
    projection = _projection(requirements, blocks, block, recipe, row)
    plan = _admit(
        projection,
        slot=blocks,
        recipe=recipe,
        row=row,
        requirement_handles=(0, 1),
    )
    base = initial_create_endpoint_skeleton("demo.full_role")
    permit = issue_create_delta_plan_v2_permit(
        plan,
        projection,
        base_spec=base,
        toolchain_binding=TOOLCHAIN,
        generation=0,
    )
    result = execute_create_delta_plan_v2(
        plan,
        projection,
        base_spec=base,
        parent_spec_sha256=None,
        permit_consumer=CreateDeltaPlanV2PermitConsumer(permit),
        toolchain_binding=TOOLCHAIN,
        generation=0,
    )

    assert result.spec["endpoint"]["blocks"] == [block_fragment]
    rendered = render_create_endpoint(result.spec).metis_text
    assert "block film_italiani" in rendered and "take 24 from @video" in rendered


def test_role_compose_rejects_child_before_owner_duplicate_node_and_unknown_step() -> None:
    authorities = _role_authorities()
    root, _, _, container, child, _, recipe, row = authorities
    requirements = (_requirement(0, STRUCTURE), _requirement(1, CONTENT))

    reversed_steps = replace(
        row,
        arguments={
            "steps": [
                {
                    "kind": "attach",
                    "node_ref": child.ref,
                    "target_slot_ref": authorities[1].ref,
                },
                {"kind": "attach", "node_ref": container.ref, "target_slot_ref": root.ref},
            ]
        },
    )
    reversed_steps = replace(
        reversed_steps,
        leaf_bindings=_bindings(reversed_steps.arguments, STRUCTURE, CONTENT),
        row_sha256=_sha(reversed_steps.arguments),
    )
    projection = _projection(requirements, *authorities[:-1], reversed_steps)
    with pytest.raises(BrainError, match="precedes its owning node"):
        execute_combinator(
            projection,
            slot_handle=root.handle,
            recipe_handle=recipe.handle,
            row_handles=(row.handle,),
        )

    duplicate = replace(
        row,
        arguments={
            "steps": [
                {"kind": "attach", "node_ref": container.ref, "target_slot_ref": root.ref},
                {"kind": "attach", "node_ref": container.ref, "target_slot_ref": root.ref},
            ]
        },
    )
    duplicate = replace(
        duplicate,
        leaf_bindings=_bindings(duplicate.arguments, STRUCTURE, CONTENT),
        row_sha256=_sha(duplicate.arguments),
    )
    projection = _projection(requirements, *authorities[:-1], duplicate)
    with pytest.raises(BrainError, match="more than once"):
        execute_combinator(
            projection,
            slot_handle=root.handle,
            recipe_handle=recipe.handle,
            row_handles=(row.handle,),
        )

    unknown = replace(row, arguments={"steps": [{"kind": "remove", "node_ref": child.ref}]})
    unknown = replace(
        unknown,
        leaf_bindings=_bindings(unknown.arguments, STRUCTURE, CONTENT),
        row_sha256=_sha(unknown.arguments),
    )
    projection = _projection(requirements, *authorities[:-1], unknown)
    with pytest.raises(BrainError, match="step kind"):
        execute_combinator(
            projection,
            slot_handle=root.handle,
            recipe_handle=recipe.handle,
            row_handles=(row.handle,),
        )


def test_role_compose_rejects_source_like_private_row_payload() -> None:
    authorities = _role_authorities()
    root, _, _, _, _, _, recipe, row = authorities
    requirements = (_requirement(0, STRUCTURE), _requirement(1, CONTENT))
    forbidden = replace(
        row,
        arguments={**row.arguments, "source": "endpoint hidden"},
    )
    forbidden = replace(
        forbidden,
        leaf_bindings=_bindings(forbidden.arguments, STRUCTURE, CONTENT),
        row_sha256=_sha(forbidden.arguments),
    )
    projection = _projection(requirements, *authorities[:-1], forbidden)

    with pytest.raises(BrainError, match="forbidden source-like key"):
        execute_combinator(
            projection,
            slot_handle=root.handle,
            recipe_handle=recipe.handle,
            row_handles=(row.handle,),
        )


def test_admission_rejects_emitted_node_evidence_absent_from_expansion_row() -> None:
    root = _slot(10, "hostref:slot-root")
    node = _node(
        20,
        "hostref:node-content",
        {"kind": "lit", "lexical": "text", "value": "contenuto"},
        parent=root.ref,
        fragment_type="value",
        requirements=(CONTENT,),
    )
    recipe = _recipe()
    row = _row(
        40,
        {
            "steps": [
                {"kind": "attach", "node_ref": node.ref, "target_slot_ref": root.ref},
            ]
        },
        requirements=(STRUCTURE,),
    )
    requirements = (_requirement(0, STRUCTURE), _requirement(1, CONTENT))
    projection = _projection(requirements, root, node, recipe, row)
    with pytest.raises(BrainError, match="reciprocal and exact"):
        _admit(
            projection,
            slot=root,
            recipe=recipe,
            row=row,
            requirement_handles=(0,),
        )


def test_admission_rejects_substitution_value_evidence_absent_from_matrix_row() -> None:
    root = _slot(10, "hostref:slot-root")
    axis_slot = _slot(11, "hostref:slot-axis", member="axis_holder")
    value_slot = _slot(12, "hostref:slot-value", member="value_holder")
    axis = _node(
        20,
        "hostref:axis",
        "asse",
        parent=axis_slot.ref,
        fragment_type="value",
        requirements=(STRUCTURE,),
    )
    replacement = _node(
        21,
        "hostref:replacement",
        "nuovo",
        parent=value_slot.ref,
        fragment_type="value",
        requirements=(CONTENT,),
    )
    prototype = _node(
        22,
        "hostref:prototype",
        {"kind": "lit", "lexical": "text", "value": "asse"},
        parent=root.ref,
        fragment_type="value",
        requirements=(STRUCTURE,),
    )
    recipe = _recipe(recipe_id="matrix.attach/v1", row_type="matrixAttachRow")
    row = _row(
        40,
        {
            "axis_bindings": [
                {"axis_ref": axis.ref, "json_pointer": "/value", "value_ref": replacement.ref}
            ],
            "node_ref": prototype.ref,
            "target_slot_ref": root.ref,
        },
        requirements=(STRUCTURE,),
        recipe_id=recipe.recipe_id,
        row_type=recipe.row_type,
    )
    requirements = (_requirement(0, STRUCTURE), _requirement(1, CONTENT))
    projection = _projection(
        requirements,
        root,
        axis_slot,
        value_slot,
        axis,
        replacement,
        prototype,
        recipe,
        row,
    )
    with pytest.raises(BrainError, match="reciprocal and exact"):
        _admit(
            projection,
            slot=root,
            recipe=recipe,
            row=row,
            requirement_handles=(0,),
        )
