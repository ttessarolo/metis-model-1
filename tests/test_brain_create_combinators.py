from __future__ import annotations

from dataclasses import replace

import pytest

from metis_model1.brain_create_combinators import (
    COMBINATOR_CONTRACT_SHA256,
    COMBINATOR_IMPLEMENTATION_SHA256,
    COMBINATOR_SCOPE_MEMBERS,
    AttachEmission,
    MatrixSubstitution,
    QuotaEmission,
    SetEmission,
    execute_combinator,
)
from metis_model1.brain_create_plan_v2 import (
    CompactAuthorityProjection,
    ExpansionRow,
    FragmentLeafBinding,
    NodeGrant,
    RecipeGrant,
    RequirementHandle,
    SlotGrant,
    compact_authority_projection_revision,
)
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json

SURFACE = "sha256:" + "c" * 64
REQ = "hostref:req"
EVIDENCE = "hostref:evidence"


def _hash(value: object) -> str:
    return bytes_sha256(canonical_json(value))


def _bindings(value: object, path: str = "") -> tuple[FragmentLeafBinding, ...]:
    pointers: list[str] = []

    def visit(item: object, pointer: str) -> None:
        if isinstance(item, dict):
            for key, nested in item.items():
                visit(nested, f"{pointer}/{key}")
        elif isinstance(item, list):
            for index, nested in enumerate(item):
                visit(nested, f"{pointer}/{index}")
        else:
            pointers.append(pointer)

    visit(value, path)
    return tuple(FragmentLeafBinding(pointer, EVIDENCE, (REQ,), "operator") for pointer in pointers)


def _node(handle: int, ref: str, parent: str, *, fragment: object | None = None) -> NodeGrant:
    fragment = handle if fragment is None else fragment
    return NodeGrant(
        handle,
        ref,
        f"nodo {handle}",
        "new",
        "value",
        fragment,
        _hash(fragment),
        _bindings(fragment),
        None,
        None,
        parent,
        False,
    )


def _slot(
    handle: int,
    ref: str,
    *,
    anchor: str = "hostref:anchor",
    accepts: tuple[str, ...] = ("value",),
    cardinality: str = "many",
) -> SlotGrant:
    return SlotGrant(
        handle,
        ref,
        f"posizione {handle}",
        anchor,
        "items",
        cardinality,
        accepts,
        frozenset({"attach", "set", "expand"}),
        "append",
        None,
        0,
    )  # type: ignore[arg-type]


def _recipe(handle: int, ref: str, recipe_id: str, row_type: str, output_type: str) -> RecipeGrant:
    return RecipeGrant(
        handle,
        ref,
        f"operazione ripetuta {handle}",
        recipe_id,
        1,
        row_type,
        output_type,
        COMBINATOR_SCOPE_MEMBERS,
        COMBINATOR_IMPLEMENTATION_SHA256[recipe_id],
        12,
        64,
    )


def _row(handle: int, ref: str, recipe_id: str, row_type: str, arguments: object) -> ExpansionRow:
    return ExpansionRow(
        handle,
        ref,
        f"riga {handle}",
        recipe_id,
        row_type,
        arguments,
        _bindings(arguments),
        _hash(arguments),
    )


def _projection(
    recipe_id: str, *, rows: tuple[ExpansionRow, ...], recipe_output: str, recipe_row: str
) -> CompactAuthorityProjection:
    slots = (
        _slot(10, "hostref:slot-main", accepts=(recipe_output,)),
        _slot(
            11,
            "hostref:slot-extra",
            anchor="hostref:slot-main",
            accepts=(recipe_output,),
            cardinality="many",
        ),
    )
    nodes = (
        _node(
            20,
            "hostref:node-main",
            "hostref:slot-main",
            fragment={"kind": "lit", "lexical": "number", "value": 22},
        ),
        _node(21, "hostref:value-main", "hostref:slot-main"),
        _node(22, "hostref:axis-main", "hostref:slot-main"),
        _node(23, "hostref:node-extra", "hostref:slot-extra"),
    )
    recipe = _recipe(30, "hostref:recipe", recipe_id, recipe_row, recipe_output)
    requirements = (RequirementHandle(0, REQ, "richiesta", frozenset({"expand"})),)
    authorities = slots + nodes + (recipe,) + rows
    revision = compact_authority_projection_revision(
        surface_revision=SURFACE, requirements=requirements, authorities=authorities
    )
    return CompactAuthorityProjection(revision, SURFACE, requirements, authorities)


def test_map_attach_is_typed_and_emits_only_private_refs() -> None:
    row = _row(
        40,
        "hostref:row",
        "map.attach/v1",
        "mapAttachRow",
        {"node_ref": "hostref:node-main", "target_slot_ref": "hostref:slot-main"},
    )
    result = execute_combinator(
        _projection("map.attach/v1", rows=(row,), recipe_output="value", recipe_row="mapAttachRow"),
        slot_handle=10,
        recipe_handle=30,
        row_handles=(40,),
    )
    assert result.recipe_id == "map.attach/v1"
    assert result.emissions == (
        AttachEmission("hostref:row", "hostref:slot-main", "hostref:node-main"),
    )


def test_expansion_scope_is_ancestor_not_the_effective_target_and_siblings_fail() -> None:
    row = _row(
        40,
        "hostref:row",
        "map.attach/v1",
        "mapAttachRow",
        {"node_ref": "hostref:node-extra", "target_slot_ref": "hostref:slot-extra"},
    )
    projection = _projection(
        "map.attach/v1", rows=(row,), recipe_output="value", recipe_row="mapAttachRow"
    )
    projection = replace(
        projection,
        authorities=(replace(projection.authorities[0], accepts=("container",)),)
        + projection.authorities[1:],
    )
    projection = replace(
        projection,
        projection_revision=compact_authority_projection_revision(
            surface_revision=SURFACE,
            requirements=projection.requirements,
            authorities=projection.authorities,
        ),
    )
    result = execute_combinator(projection, slot_handle=10, recipe_handle=30, row_handles=(40,))
    assert result.emissions == (
        AttachEmission("hostref:row", "hostref:slot-extra", "hostref:node-extra"),
    )

    sibling_slot = _slot(12, "hostref:slot-sibling", anchor="hostref:unrelated", accepts=("value",))
    sibling_node = _node(24, "hostref:node-sibling", "hostref:slot-sibling")
    sibling_row = replace(
        row,
        arguments={"node_ref": "hostref:node-sibling", "target_slot_ref": "hostref:slot-sibling"},
        leaf_bindings=_bindings(
            {"node_ref": "hostref:node-sibling", "target_slot_ref": "hostref:slot-sibling"}
        ),
        row_sha256=_hash(
            {"node_ref": "hostref:node-sibling", "target_slot_ref": "hostref:slot-sibling"}
        ),
    )
    authorities = projection.authorities[:-1] + (sibling_slot, sibling_node, sibling_row)
    sibling_projection = replace(
        projection,
        authorities=authorities,
        projection_revision=compact_authority_projection_revision(
            surface_revision=SURFACE,
            requirements=projection.requirements,
            authorities=authorities,
        ),
    )
    with pytest.raises(BrainError, match="outside"):
        execute_combinator(sibling_projection, slot_handle=10, recipe_handle=30, row_handles=(40,))


def test_map_set_emits_typed_value_ref_on_its_explicit_target_slot() -> None:
    row = _row(
        40,
        "hostref:row",
        "map.set/v1",
        "mapSetRow",
        {"target_slot_ref": "hostref:slot-main", "value_ref": "hostref:value-main"},
    )
    projection = _projection(
        "map.set/v1", rows=(row,), recipe_output="value", recipe_row="mapSetRow"
    )
    projection = replace(
        projection,
        authorities=(replace(projection.authorities[0], cardinality="one"),)
        + projection.authorities[1:],
    )
    projection = replace(
        projection,
        projection_revision=compact_authority_projection_revision(
            surface_revision=SURFACE,
            requirements=projection.requirements,
            authorities=projection.authorities,
        ),
    )
    result = execute_combinator(projection, slot_handle=10, recipe_handle=30, row_handles=(40,))
    assert result.emissions == (
        SetEmission("hostref:row", "hostref:slot-main", "hostref:value-main"),
    )


def test_matrix_attach_requires_typed_axes_and_no_template_body() -> None:
    row = _row(
        40,
        "hostref:row",
        "matrix.attach/v1",
        "matrixAttachRow",
        {
            "axis_bindings": [
                {
                    "axis_ref": "hostref:axis-main",
                    "json_pointer": "/value",
                    "value_ref": "hostref:value-main",
                }
            ],
            "node_ref": "hostref:node-main",
            "target_slot_ref": "hostref:slot-main",
        },
    )
    result = execute_combinator(
        _projection(
            "matrix.attach/v1", rows=(row,), recipe_output="value", recipe_row="matrixAttachRow"
        ),
        slot_handle=10,
        recipe_handle=30,
        row_handles=(40,),
    )
    assert result.emissions == (
        AttachEmission(
            "hostref:row",
            "hostref:slot-main",
            "hostref:node-main",
            (MatrixSubstitution("hostref:axis-main", "hostref:value-main", "/value"),),
        ),
    )

    bad_pointer = replace(
        row,
        arguments={
            "axis_bindings": [
                {
                    "axis_ref": "hostref:axis-main",
                    "json_pointer": "/missing",
                    "value_ref": "hostref:value-main",
                }
            ],
            "node_ref": "hostref:node-main",
            "target_slot_ref": "hostref:slot-main",
        },
    )
    bad_pointer = replace(
        bad_pointer,
        leaf_bindings=_bindings(bad_pointer.arguments),
        row_sha256=_hash(bad_pointer.arguments),
    )
    projection = _projection(
        "matrix.attach/v1", rows=(bad_pointer,), recipe_output="value", recipe_row="matrixAttachRow"
    )
    with pytest.raises(BrainError, match="axis pointer"):
        execute_combinator(projection, slot_handle=10, recipe_handle=30, row_handles=(40,))

    wrong_pointer = replace(
        bad_pointer,
        arguments={
            **bad_pointer.arguments,
            "axis_bindings": [
                {
                    "axis_ref": "hostref:axis-main",
                    "json_pointer": "/kind",
                    "value_ref": "hostref:value-main",
                }
            ],
        },
    )
    wrong_pointer = replace(
        wrong_pointer,
        leaf_bindings=_bindings(wrong_pointer.arguments),
        row_sha256=_hash(wrong_pointer.arguments),
    )
    projection = _projection(
        "matrix.attach/v1",
        rows=(wrong_pointer,),
        recipe_output="value",
        recipe_row="matrixAttachRow",
    )
    with pytest.raises(BrainError, match="exact placeholder"):
        execute_combinator(projection, slot_handle=10, recipe_handle=30, row_handles=(40,))

    duplicate_pointer = replace(
        wrong_pointer,
        arguments={
            **wrong_pointer.arguments,
            "axis_bindings": [
                {
                    "axis_ref": "hostref:axis-main",
                    "json_pointer": "/value",
                    "value_ref": "hostref:value-main",
                },
                {
                    "axis_ref": "hostref:axis-second",
                    "json_pointer": "/value",
                    "value_ref": "hostref:value-main",
                },
            ],
        },
    )
    duplicate_pointer = replace(
        duplicate_pointer,
        leaf_bindings=_bindings(duplicate_pointer.arguments),
        row_sha256=_hash(duplicate_pointer.arguments),
    )
    projection = _projection(
        "matrix.attach/v1",
        rows=(duplicate_pointer,),
        recipe_output="value",
        recipe_row="matrixAttachRow",
    )
    axis_second = _node(
        24,
        "hostref:axis-second",
        "hostref:slot-main",
        fragment=22,
    )
    authorities = projection.authorities[:-1] + (axis_second, duplicate_pointer)
    projection = replace(
        projection,
        authorities=authorities,
        projection_revision=compact_authority_projection_revision(
            surface_revision=SURFACE,
            requirements=projection.requirements,
            authorities=authorities,
        ),
    )
    with pytest.raises(BrainError, match="residual or ambiguous"):
        execute_combinator(projection, slot_handle=10, recipe_handle=30, row_handles=(40,))


@pytest.mark.parametrize(
    ("strategy", "expected"),
    [
        ("balanced", (3, 2)),
        ("front_loaded", (4, 1)),
    ],
)
def test_quota_distribute_is_deterministic_balanced_or_front_loaded(
    strategy: str, expected: tuple[int, int]
) -> None:
    row = _row(
        40,
        "hostref:row",
        "quota.distribute/v1",
        "quotaDistributeRow",
        {
            "occurrences": 5,
            "strategy": strategy,
            "targets": [
                {"node_ref": "hostref:node-main", "target_slot_ref": "hostref:slot-main"},
                {"node_ref": "hostref:node-extra", "target_slot_ref": "hostref:slot-extra"},
            ],
        },
    )
    projection = _projection(
        "quota.distribute/v1", rows=(row,), recipe_output="value", recipe_row="quotaDistributeRow"
    )
    projection = replace(
        projection,
        projection_revision=compact_authority_projection_revision(
            surface_revision=SURFACE,
            requirements=projection.requirements,
            authorities=projection.authorities,
        ),
    )
    result = execute_combinator(projection, slot_handle=10, recipe_handle=30, row_handles=(40,))
    assert result.emissions == (
        QuotaEmission(
            "hostref:row", "hostref:slot-main", "hostref:node-main", expected[0], strategy
        ),
        QuotaEmission(
            "hostref:row", "hostref:slot-extra", "hostref:node-extra", expected[1], strategy
        ),
    )


def test_recipe_pin_rows_bounds_unknown_handles_and_payload_rosters_fail_closed() -> None:
    row = _row(
        40,
        "hostref:row",
        "map.attach/v1",
        "mapAttachRow",
        {"node_ref": "hostref:node-main", "target_slot_ref": "hostref:slot-main"},
    )
    projection = _projection(
        "map.attach/v1", rows=(row,), recipe_output="value", recipe_row="mapAttachRow"
    )
    recipe = next(item for item in projection.authorities if isinstance(item, RecipeGrant))
    bad_recipe = replace(recipe, implementation_sha256="sha256:" + "0" * 64)
    bad = replace(
        projection,
        authorities=tuple(
            bad_recipe if item is recipe else item for item in projection.authorities
        ),
    )
    bad = replace(
        bad,
        projection_revision=compact_authority_projection_revision(
            surface_revision=SURFACE, requirements=bad.requirements, authorities=bad.authorities
        ),
    )
    with pytest.raises(BrainError, match="implementation hash"):
        execute_combinator(bad, slot_handle=10, recipe_handle=30, row_handles=(40,))
    with pytest.raises(BrainError, match="unknown"):
        execute_combinator(projection, slot_handle=10, recipe_handle=30, row_handles=(99,))
    bad_row = replace(
        row,
        arguments={
            "node_ref": "hostref:node-main",
            "target_slot_ref": "hostref:slot-main",
            "template": "forbidden",
        },
    )
    bad = replace(projection, authorities=projection.authorities[:-1] + (bad_row,))
    bad = replace(
        bad,
        projection_revision=compact_authority_projection_revision(
            surface_revision=SURFACE, requirements=bad.requirements, authorities=bad.authorities
        ),
    )
    with pytest.raises(BrainError):
        execute_combinator(bad, slot_handle=10, recipe_handle=30, row_handles=(40,))


def test_map_set_rejects_a_duplicate_target_instead_of_last_write_wins() -> None:
    first = _row(
        40,
        "hostref:row-a",
        "map.set/v1",
        "mapSetRow",
        {"target_slot_ref": "hostref:slot-main", "value_ref": "hostref:value-main"},
    )
    second = _row(
        41,
        "hostref:row-b",
        "map.set/v1",
        "mapSetRow",
        {"target_slot_ref": "hostref:slot-main", "value_ref": "hostref:value-main"},
    )
    projection = _projection(
        "map.set/v1", rows=(first, second), recipe_output="value", recipe_row="mapSetRow"
    )
    projection = replace(
        projection,
        authorities=(replace(projection.authorities[0], cardinality="one"),)
        + projection.authorities[1:],
    )
    projection = replace(
        projection,
        projection_revision=compact_authority_projection_revision(
            surface_revision=SURFACE,
            requirements=projection.requirements,
            authorities=projection.authorities,
        ),
    )
    with pytest.raises(BrainError, match="distinct one-cardinality"):
        execute_combinator(projection, slot_handle=10, recipe_handle=30, row_handles=(40, 41))


def test_quota_rejects_content_free_row_and_source_pin_is_not_contract_digest() -> None:
    row = _row(
        40,
        "hostref:row",
        "quota.distribute/v1",
        "quotaDistributeRow",
        {
            "occurrences": 5,
            "strategy": "balanced",
            "targets": [{"target_slot_ref": "hostref:slot-main"}],
        },
    )
    projection = _projection(
        "quota.distribute/v1", rows=(row,), recipe_output="value", recipe_row="quotaDistributeRow"
    )
    with pytest.raises(BrainError):
        execute_combinator(projection, slot_handle=10, recipe_handle=30, row_handles=(40,))
    assert (
        COMBINATOR_CONTRACT_SHA256["map.attach/v1"]
        != COMBINATOR_IMPLEMENTATION_SHA256["map.attach/v1"]
    )


def test_quota_requires_one_exact_parent_bound_node_for_each_target() -> None:
    row = _row(
        40,
        "hostref:row",
        "quota.distribute/v1",
        "quotaDistributeRow",
        {
            "occurrences": 2,
            "strategy": "balanced",
            "targets": [
                {"node_ref": "hostref:node-main", "target_slot_ref": "hostref:slot-main"},
                {"node_ref": "hostref:node-main", "target_slot_ref": "hostref:slot-extra"},
            ],
        },
    )
    projection = _projection(
        "quota.distribute/v1", rows=(row,), recipe_output="value", recipe_row="quotaDistributeRow"
    )
    with pytest.raises(BrainError, match="cannot attach"):
        execute_combinator(projection, slot_handle=10, recipe_handle=30, row_handles=(40,))
