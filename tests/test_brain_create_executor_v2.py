"""Adversarial tests for the private, deterministic compact CREATE V2 executor.

These tests deliberately use a small builder-shaped object with an additional
generic ``items`` collection.  They prove authority plumbing and deterministic
mutation only; a compiler/builder-schema gate remains a later authority.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from metis_model1.brain_create_combinators import (
    COMBINATOR_IMPLEMENTATION_SHA256,
    COMBINATOR_SCOPE_MEMBERS,
)
from metis_model1.brain_create_executor_v2 import (
    CreateDeltaPlanV2ExecutionError,
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
from metis_model1.brain_protocol import bytes_sha256, canonical_json

TARGET = "hostref:target-v2"
REQUIREMENT = "hostref:requirement-v2"
EVIDENCE = "hostref:evidence-v2"
BASIS = "hostref:basis-v2"
CONTEXT = bytes_sha256(b"executor-v2-context")
SEMANTIC = bytes_sha256(b"executor-v2-semantic")
SURFACE = bytes_sha256(b"executor-v2-surface")
TOOLCHAIN = bytes_sha256(b"executor-v2-toolchain")
OTHER_TOOLCHAIN = bytes_sha256(b"executor-v2-other-toolchain")


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


def _bindings(value: Any, *, origin: str = "operator") -> tuple[FragmentLeafBinding, ...]:
    return tuple(
        FragmentLeafBinding(pointer, EVIDENCE, (REQUIREMENT,), origin)  # type: ignore[arg-type]
        for pointer in _leaf_pointers(value)
    )


def _slot(
    handle: int,
    ref: str,
    *,
    anchor: str = TARGET,
    member: str,
    cardinality: str = "many",
    accepts: tuple[str, ...] = ("value",),
    mutations: frozenset[str] = frozenset({"attach", "expand"}),
    insertion: str = "append",
) -> SlotGrant:
    return SlotGrant(
        handle,
        ref,
        f"slot {member}",
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
    parent: str | None,
    fragment_type: str = "value",
    state: str = "new",
    basis_spec_sha256: str | None = None,
    basis_path: tuple[str | int, ...] | None = None,
    removable: bool = False,
) -> NodeGrant:
    return NodeGrant(
        handle,
        ref,
        f"node {handle}",
        state,  # type: ignore[arg-type]
        fragment_type,
        fragment,
        _sha(fragment),
        _bindings(fragment, origin="basis" if state == "basis" else "operator"),
        basis_spec_sha256,
        basis_path,
        parent,
        removable,
    )


def _recipe(handle: int, ref: str, recipe_id: str) -> RecipeGrant:
    descriptor = {
        "map.attach/v1": ("mapAttachRow", "value"),
        "matrix.attach/v1": ("matrixAttachRow", "value"),
        "quota.distribute/v1": ("quotaDistributeRow", "value"),
    }[recipe_id]
    return RecipeGrant(
        handle,
        ref,
        "bounded expansion recipe",
        recipe_id,
        1,
        descriptor[0],
        descriptor[1],
        COMBINATOR_SCOPE_MEMBERS,
        COMBINATOR_IMPLEMENTATION_SHA256[recipe_id],
        12,
        64,
    )


def _row(handle: int, ref: str, recipe_id: str, row_type: str, arguments: Any) -> ExpansionRow:
    return ExpansionRow(
        handle,
        ref,
        f"row {handle}",
        recipe_id,
        row_type,
        arguments,
        _bindings(arguments),
        _sha(arguments),
    )


def _projection(*authorities: Any) -> CompactAuthorityProjection:
    requirements = (
        RequirementHandle(
            0,
            REQUIREMENT,
            "Operator requested structure",
            frozenset({"attach", "set", "remove", "expand"}),
        ),
    )
    return CompactAuthorityProjection(
        compact_authority_projection_revision(
            surface_revision=SURFACE, requirements=requirements, authorities=authorities
        ),
        SURFACE,
        requirements,
        tuple(authorities),
    )


def _initial_base() -> dict[str, Any]:
    base = initial_create_endpoint_skeleton("demo.executor_v2")
    base["endpoint"]["items"] = []
    return base


def _admit(body: dict[str, Any], projection: CompactAuthorityProjection, *, mode: str = "initial"):
    return admit_create_delta_plan_v2(
        body,
        projection=projection,
        mode=mode,  # type: ignore[arg-type]
        context_revision=CONTEXT,
        semantic_revision=SEMANTIC,
        target_ref=TARGET,
        basis_ref=BASIS if mode == "refinement" else None,
        active_requirement_handles=(0,),
    )


def _execute(plan, projection, base, *, parent_sha: str | None = None, toolchain: str = TOOLCHAIN):
    permit = issue_create_delta_plan_v2_permit(
        plan,
        projection,
        base_spec=base,
        toolchain_binding=TOOLCHAIN,
        generation=0,
        parent_spec_sha256=parent_sha,
    )
    return execute_create_delta_plan_v2(
        plan,
        projection,
        base_spec=base,
        parent_spec_sha256=parent_sha,
        permit_consumer=CreateDeltaPlanV2PermitConsumer(permit),
        toolchain_binding=toolchain,
        generation=0,
    )


def test_executor_applies_direct_attach_set_and_parent_registered_map_expansion() -> None:
    items = _slot(10, "hostref:slot-items", member="items")
    child_items = _slot(
        11, "hostref:slot-child-items", anchor="hostref:node-parent", member="items"
    )
    needs_time = _slot(
        12,
        "hostref:slot-needs-time",
        member="needs_time",
        cardinality="one",
        accepts=("boolean",),
        mutations=frozenset({"set"}),
        insertion="replace",
    )
    parent = _node(20, "hostref:node-parent", {"name": "parent", "items": []}, parent=items.ref)
    child = _node(21, "hostref:node-child", {"name": "child"}, parent=child_items.ref)
    enabled = _node(
        22, "hostref:value-needs-time", True, parent=needs_time.ref, fragment_type="boolean"
    )
    repeat = _node(23, "hostref:node-repeat", {"name": "repeat"}, parent=items.ref)
    recipe = _recipe(30, "hostref:recipe-map", "map.attach/v1")
    row = _row(
        40,
        "hostref:row-map",
        recipe.recipe_id,
        recipe.row_type,
        {"node_ref": repeat.ref, "target_slot_ref": items.ref},
    )
    projection = _projection(
        items, child_items, needs_time, parent, child, enabled, repeat, recipe, row
    )
    plan = _admit(
        {
            "o": [
                {"k": "a", "q": [0], "s": items.handle, "n": parent.handle},
                {"k": "a", "q": [0], "s": child_items.handle, "n": child.handle},
                {"k": "s", "q": [0], "s": needs_time.handle, "v": enabled.handle},
                {"k": "x", "q": [0], "s": items.handle, "r": recipe.handle, "w": [row.handle]},
            ]
        },
        projection,
    )
    base = _initial_base()
    result = _execute(plan, projection, base)

    assert base["endpoint"]["items"] == []
    assert result.spec["endpoint"]["needs_time"] is True
    assert result.spec["endpoint"]["items"] == [
        {"name": "parent", "items": [{"name": "child"}]},
        {"name": "repeat"},
    ]
    assert result.proof_input.emitted_mutations == 4
    assert result.spec_sha256 == _sha(result.spec)


def test_executor_applies_matrix_and_content_bound_quota_emissions() -> None:
    items = _slot(10, "hostref:slot-items", member="items")
    axis_slot = _slot(11, "hostref:slot-axis", member="axis_holder")
    values_slot = _slot(12, "hostref:slot-values", member="value_holder")
    axis_fragment = "axis"
    replacement_fragment = "new"
    quota_fragment = {"kind": "lit", "lexical": "text", "value": "quota"}
    axis = _node(20, "hostref:axis", axis_fragment, parent=axis_slot.ref)
    replacement = _node(21, "hostref:replacement", replacement_fragment, parent=values_slot.ref)
    matrix_node = _node(
        22,
        "hostref:matrix-node",
        {"kind": "lit", "lexical": "text", "value": axis_fragment},
        parent=items.ref,
    )
    quota_node = _node(23, "hostref:quota-node", quota_fragment, parent=items.ref)
    matrix = _recipe(30, "hostref:recipe-matrix", "matrix.attach/v1")
    quota = _recipe(31, "hostref:recipe-quota", "quota.distribute/v1")
    matrix_row = _row(
        40,
        "hostref:row-matrix",
        matrix.recipe_id,
        matrix.row_type,
        {
            "axis_bindings": [
                {"axis_ref": axis.ref, "json_pointer": "/value", "value_ref": replacement.ref}
            ],
            "node_ref": matrix_node.ref,
            "target_slot_ref": items.ref,
        },
    )
    quota_row = _row(
        41,
        "hostref:row-quota",
        quota.recipe_id,
        quota.row_type,
        {
            "occurrences": 3,
            "strategy": "balanced",
            "targets": [{"node_ref": quota_node.ref, "target_slot_ref": items.ref}],
        },
    )
    projection = _projection(
        items,
        axis_slot,
        values_slot,
        axis,
        replacement,
        matrix_node,
        quota_node,
        matrix,
        quota,
        matrix_row,
        quota_row,
    )
    plan = _admit(
        {
            "o": [
                {
                    "k": "x",
                    "q": [0],
                    "s": items.handle,
                    "r": matrix.handle,
                    "w": [matrix_row.handle],
                },
                {"k": "x", "q": [0], "s": items.handle, "r": quota.handle, "w": [quota_row.handle]},
            ]
        },
        projection,
    )
    result = _execute(plan, projection, _initial_base())

    assert result.spec["endpoint"]["items"] == [
        {"kind": "lit", "lexical": "text", "value": replacement_fragment},
        quota_fragment,
        quota_fragment,
        quota_fragment,
    ]
    assert result.proof_input.emitted_mutations == 4


def test_refinement_remove_uses_exact_basis_path_not_equal_fragment_search() -> None:
    base = _initial_base()
    base["endpoint"]["items"] = [{"token": "same"}, {"token": "same"}]
    base_sha = _sha(base)
    items = _slot(10, "hostref:slot-items", member="items")
    second_equal_item = _node(
        20,
        "hostref:basis-second-item",
        {"token": "same"},
        parent=items.ref,
        state="basis",
        basis_spec_sha256=base_sha,
        basis_path=("items", 1),
        removable=True,
    )
    projection = _projection(items, second_equal_item)
    plan = _admit(
        {"o": [{"k": "d", "q": [0], "n": second_equal_item.handle}]}, projection, mode="refinement"
    )
    result = _execute(plan, projection, base, parent_sha=base_sha)

    assert base["endpoint"]["items"] == [{"token": "same"}, {"token": "same"}]
    assert result.spec["endpoint"]["items"] == [{"token": "same"}]
    assert result.proof_input.parent_spec_sha256 == base_sha


def test_permit_burns_before_toolchain_drift_and_rejects_replay() -> None:
    items = _slot(10, "hostref:slot-items", member="items")
    node = _node(20, "hostref:node", {"name": "one"}, parent=items.ref)
    projection = _projection(items, node)
    plan = _admit({"o": [{"k": "a", "q": [0], "s": items.handle, "n": node.handle}]}, projection)
    base = _initial_base()
    permit = issue_create_delta_plan_v2_permit(
        plan, projection, base_spec=base, toolchain_binding=TOOLCHAIN, generation=0
    )
    consumer = CreateDeltaPlanV2PermitConsumer(permit)

    with pytest.raises(CreateDeltaPlanV2ExecutionError, match="permit binding differs") as drift:
        execute_create_delta_plan_v2(
            plan,
            projection,
            base_spec=base,
            parent_spec_sha256=None,
            permit_consumer=consumer,
            toolchain_binding=OTHER_TOOLCHAIN,
            generation=0,
        )
    assert drift.value.code == "CREATE_V2_PERMIT_DRIFT"
    with pytest.raises(CreateDeltaPlanV2ExecutionError, match="already consumed") as replay:
        execute_create_delta_plan_v2(
            plan,
            projection,
            base_spec=base,
            parent_spec_sha256=None,
            permit_consumer=consumer,
            toolchain_binding=TOOLCHAIN,
            generation=0,
        )
    assert replay.value.code == "CREATE_V2_PERMIT_REPLAY"


def test_executor_refuses_forged_requirement_coverage_before_permit_issue() -> None:
    items = _slot(10, "hostref:slot-items", member="items")
    node = _node(20, "hostref:node", {"name": "one"}, parent=items.ref)
    projection = _projection(items, node)
    plan = _admit({"o": [{"k": "a", "q": [0], "s": items.handle, "n": node.handle}]}, projection)
    forged = replace(plan, operations=(replace(plan.operations[0], requirement_refs=()),))

    with pytest.raises(
        CreateDeltaPlanV2ExecutionError, match="operation requirements are invalid"
    ) as error:
        issue_create_delta_plan_v2_permit(
            forged,
            projection,
            base_spec=_initial_base(),
            toolchain_binding=TOOLCHAIN,
            generation=0,
        )
    assert error.value.code == "CREATE_V2_PLAN_INVALID"


def test_quota_refuses_repeated_node_when_a_virtual_child_slot_would_be_ambiguous() -> None:
    items = _slot(10, "hostref:slot-items", member="items")
    quota_node = _node(20, "hostref:quota-node", {"kind": "quota", "items": []}, parent=items.ref)
    child_items = _slot(11, "hostref:quota-child-items", anchor=quota_node.ref, member="items")
    quota = _recipe(30, "hostref:recipe-quota", "quota.distribute/v1")
    row = _row(
        40,
        "hostref:row-quota",
        quota.recipe_id,
        quota.row_type,
        {
            "occurrences": 2,
            "strategy": "front_loaded",
            "targets": [{"node_ref": quota_node.ref, "target_slot_ref": items.ref}],
        },
    )
    projection = _projection(items, child_items, quota_node, quota, row)
    plan = _admit(
        {"o": [{"k": "x", "q": [0], "s": items.handle, "r": quota.handle, "w": [row.handle]}]},
        projection,
    )

    with pytest.raises(
        CreateDeltaPlanV2ExecutionError, match="cannot anchor a child slot"
    ) as error:
        _execute(plan, projection, _initial_base())
    assert error.value.code == "CREATE_V2_EXPANSION_INVALID"
