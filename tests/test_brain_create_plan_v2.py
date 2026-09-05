from __future__ import annotations

from dataclasses import replace

import pytest
from jsonschema import Draft202012Validator

from metis_model1.brain_create_builder import CREATE_ENDPOINT_SPEC_SCHEMA
from metis_model1.brain_create_plan_v2 import (
    CREATE_DELTA_PLAN_BODY_V2_SCHEMA,
    CREATE_DELTA_PLAN_V2_CONTRACT,
    CREATE_DELTA_PLAN_V2_SCHEMA,
    CREATE_V2_NEW_FRAGMENT_TYPES,
    AttachOpV2,
    CompactAuthorityProjection,
    ExpansionRow,
    FragmentLeafBinding,
    NodeGrant,
    RecipeGrant,
    RequirementHandle,
    SetOpV2,
    SlotGrant,
    admit_create_delta_plan_v2,
    compact_authority_projection_revision,
    initial_create_endpoint_skeleton,
    parse_create_delta_plan_v2_json,
    validate_compact_authority_projection,
    validate_create_delta_plan_v2_body_shape,
)
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json

CONTEXT = "sha256:" + "a" * 64
SEMANTIC = "sha256:" + "b" * 64
SURFACE = "sha256:" + "c" * 64
TARGET = "hostref:target"
BASIS = "hostref:basis"
REQ_A = "hostref:req-a"
REQ_B = "hostref:req-b"
EVIDENCE = "hostref:evidence"


def _hash(value: object) -> str:
    return bytes_sha256(canonical_json(value))


def _leaf(pointer: str, requirements: tuple[str, ...] = (REQ_A,)) -> FragmentLeafBinding:
    return FragmentLeafBinding(pointer, EVIDENCE, requirements, "operator")


def _all_leaf_bindings(
    value: object,
    pointer: str = "",
    requirements: tuple[str, ...] = (REQ_A,),
) -> tuple[FragmentLeafBinding, ...]:
    if isinstance(value, dict):
        return tuple(
            binding
            for key, nested in value.items()
            for binding in _all_leaf_bindings(
                nested,
                f"{pointer}/{key.replace('~', '~0').replace('/', '~1')}",
                requirements,
            )
        )
    if isinstance(value, list):
        return tuple(
            binding
            for index, nested in enumerate(value)
            for binding in _all_leaf_bindings(nested, f"{pointer}/{index}", requirements)
        )
    return (_leaf(pointer, requirements),)


def _presentation() -> dict[str, object]:
    return {"pinned": None, "view_all": None, "meta": [], "meta_per_item": False}


def _fetch() -> dict[str, object]:
    return {
        "from": {"kind": "catalog", "catalog": "video"},
        "cardinality": {"mode": "total", "value": 24},
        "over_fetch": None,
        "alias": None,
        "title": None,
        "activation": None,
        "presentation": _presentation(),
        "clauses": [
            {
                "intent": "include",
                "where": [
                    {
                        "op": "eq",
                        "field": "paesiorigine",
                        "value": {"kind": "lit", "lexical": "text", "value": "Italia"},
                    }
                ],
            }
        ],
        "group_by": None,
        "order": [],
        "output": None,
    }


def _container() -> dict[str, object]:
    return {
        "name": "selezione",
        "parameters": [],
        "title": None,
        "activation": None,
        "presentation": _presentation(),
        "fetches": [_fetch()],
        "blocks": [],
        "uses": [],
        "output": None,
    }


def _variant() -> dict[str, object]:
    return {
        "name": "principale",
        "title": None,
        "activation": None,
        "empty": False,
        "presentation": _presentation(),
        "fetches": [_fetch()],
        "blocks": [],
        "uses": [],
        "output": None,
    }


def _context_binding() -> dict[str, object]:
    return {"kind": "fetch", "name": "segnale", "fetch": _fetch()}


def _node(
    handle: int,
    ref: str,
    *,
    state: str = "new",
    parent: str | None = "hostref:slot-append",
    removable: bool = False,
    basis_path: tuple[str | int, ...] | None = None,
    requirements: tuple[str, ...] = (REQ_A,),
) -> NodeGrant:
    fragment = {"kind": "lit", "lexical": "number", "value": handle}
    return NodeGrant(
        handle=handle,
        ref=ref,
        label=f"valore {handle}",
        state=state,  # type: ignore[arg-type]
        fragment_type="value",
        fragment=fragment,
        fragment_sha256=_hash(fragment),
        leaf_bindings=(
            _leaf("/kind", requirements),
            _leaf("/lexical", requirements),
            _leaf("/value", requirements),
        ),
        basis_spec_sha256=("sha256:" + "f" * 64) if state == "basis" else None,
        basis_path=basis_path if state == "basis" else None,
        parent_slot_ref=parent,
        removable=removable,
    )


def _slot(
    handle: int,
    ref: str,
    *,
    cardinality: str = "many",
    accepts: tuple[str, ...] = ("value",),
) -> SlotGrant:
    return SlotGrant(
        handle=handle,
        ref=ref,
        label=f"posizione {handle}",
        anchor_ref="hostref:anchor",
        member="members",
        cardinality=cardinality,  # type: ignore[arg-type]
        accepts=accepts,
        mutations=frozenset({"attach", "set", "expand"}),
        insertion="append",
        basis_spec_sha256=None,
        generation=0,
    )


def _recipe(handle: int, ref: str, recipe_id: str, row_type: str, output_type: str) -> RecipeGrant:
    # The plan layer validates shape/pin format; the combinator module checks
    # the code-pinned implementation hash.
    return RecipeGrant(
        handle=handle,
        ref=ref,
        label=f"operazione ripetuta {handle}",
        recipe_id=recipe_id,
        version=1,
        row_type=row_type,
        output_type=output_type,
        scope_members=("members",),
        implementation_sha256="sha256:" + "d" * 64,
        max_rows=12,
        max_emitted_mutations=32,
    )


def _row(
    handle: int,
    ref: str,
    recipe_id: str,
    row_type: str,
    arguments: object,
    requirements: tuple[str, ...] = (REQ_A,),
) -> ExpansionRow:
    pointers = tuple(f"/{key}" for key in arguments)
    return ExpansionRow(
        handle=handle,
        ref=ref,
        label=f"riga {handle}",
        recipe_id=recipe_id,
        row_type=row_type,
        arguments=arguments,
        leaf_bindings=tuple(_leaf(pointer, requirements) for pointer in pointers),
        row_sha256=_hash(arguments),
    )


def _projection() -> CompactAuthorityProjection:
    requirements = (
        RequirementHandle(0, REQ_A, "richiesta A", frozenset({"attach", "remove", "expand"})),
        RequirementHandle(1, REQ_B, "richiesta B", frozenset({"set"})),
    )
    authorities = (
        _slot(10, "hostref:slot-append"),
        _slot(11, "hostref:slot-set", cardinality="one"),
        _node(20, "hostref:node-new", requirements=(REQ_A,)),
        _node(21, "hostref:value-new", parent="hostref:slot-set", requirements=(REQ_B,)),
        _node(
            22,
            "hostref:node-basis",
            state="basis",
            parent="hostref:slot-append",
            removable=True,
            basis_path=("blocks", 0),
        ),
        _recipe(30, "hostref:recipe", "map.attach/v1", "mapAttachRow", "value"),
        _row(
            40,
            "hostref:row",
            "map.attach/v1",
            "mapAttachRow",
            {"node_ref": "hostref:node-new", "target_slot_ref": "hostref:slot-append"},
        ),
    )
    revision = compact_authority_projection_revision(
        surface_revision=SURFACE,
        requirements=requirements,
        authorities=authorities,
    )
    return CompactAuthorityProjection(revision, SURFACE, requirements, authorities)


def _admit(body: object, *, active: tuple[int, ...] = (0, 1)):
    return admit_create_delta_plan_v2(
        body,
        projection=_projection(),
        mode="initial",
        context_revision=CONTEXT,
        semantic_revision=SEMANTIC,
        target_ref=TARGET,
        basis_ref=None,
        active_requirement_handles=active,
    )


def test_schema_is_exact_compact_anyof_wire_and_accepts_all_four_operations() -> None:
    assert Draft202012Validator.check_schema(CREATE_DELTA_PLAN_BODY_V2_SCHEMA) is None
    assert Draft202012Validator.check_schema(CREATE_DELTA_PLAN_V2_SCHEMA) is None
    assert set(CREATE_DELTA_PLAN_BODY_V2_SCHEMA["$defs"]["operation"]) == {"anyOf"}
    assert (
        validate_create_delta_plan_v2_body_shape(
            {
                "o": [
                    {"k": "a", "q": [0], "s": 10, "n": 20},
                    {"k": "s", "q": [1], "s": 11, "v": 21},
                    {"k": "d", "q": [0], "n": 22},
                    {"k": "x", "q": [0], "s": 10, "r": 30, "w": [40]},
                ]
            }
        )
        == []
    )


def test_admission_injects_all_private_headers_and_source_order_ordinals() -> None:
    plan = _admit(
        {
            "o": [
                {"k": "a", "q": [0], "s": 10, "n": 20},
                {"k": "s", "q": [1], "s": 11, "v": 21},
            ]
        }
    )
    assert plan.contract_id == CREATE_DELTA_PLAN_V2_CONTRACT
    assert plan.context_revision == CONTEXT
    assert plan.semantic_revision == SEMANTIC
    assert plan.surface_revision == SURFACE
    assert plan.target_ref == TARGET and plan.basis_ref is None
    assert plan.requirements == (REQ_A, REQ_B)
    assert isinstance(plan.operations[0], AttachOpV2)
    assert isinstance(plan.operations[1], SetOpV2)
    assert [item.ordinal for item in plan.operations] == [0, 1]
    internal = plan.internal_json()
    assert internal["schema_version"] == 2
    assert internal["body"]["o"][0] == {
        "ordinal": 0,
        "k": "a",
        "q": [REQ_A],
        "s": "hostref:slot-append",
        "n": "hostref:node-new",
    }
    assert Draft202012Validator(CREATE_DELTA_PLAN_V2_SCHEMA).is_valid(internal)


def test_model_projection_is_handle_usable_but_contains_no_private_authority() -> None:
    projection = _projection()
    payload = projection.model_projection_payload()
    assert payload["v"] == 2 and payload["p"] == projection.projection_revision
    assert payload["q"] == [
        {"h": 0, "l": "richiesta A", "o": ["attach", "expand", "remove"]},
        {"h": 1, "l": "richiesta B", "o": ["set"]},
    ]
    assert payload["s"][0] == {
        "h": 10,
        "l": "posizione 10",
        "a": ["value"],
        "m": ["attach", "expand", "set"],
        "c": "many",
        "i": "append",
        "g": "members",
    }
    assert payload["n"][0] == {
        "h": 20,
        "l": "valore 20",
        "t": "value",
        "s": "new",
        "d": False,
    }
    assert payload["r"][0]["i"] == "map.attach/v1"
    assert payload["w"][0] == {
        "h": 40,
        "l": "riga 40",
        "i": "map.attach/v1",
        "t": "mapAttachRow",
    }
    rendered = canonical_json(payload).decode("utf-8")
    for private_marker in (
        "hostref:",
        "fragment",
        "arguments",
        "evidence",
        "path",
        "source",
        "golden",
        "template",
    ):
        assert private_marker not in rendered

    unsafe = replace(projection.authorities[0], label="source policy")
    bad = replace(projection, authorities=(unsafe,) + projection.authorities[1:])
    with pytest.raises(BrainError, match="model-safe"):
        validate_compact_authority_projection(bad)


@pytest.mark.parametrize(
    "body, expected",
    [
        ({"o": []}, ""),
        ({"o": [{"k": "a", "q": [0], "s": 10, "n": 20, "x": 1}]}, ""),
        ({"o": [{"k": "a", "q": [0, 0], "s": 10, "n": 20}]}, ""),
        ({"o": [{"k": "z", "q": [0], "s": 10, "n": 20}]}, ""),
        ({"o": [{"k": "x", "q": [0], "s": 10, "r": 30, "w": list(range(13))}]}, ""),
    ],
)
def test_schema_rejects_non_compact_unknown_and_out_of_bound_wire(
    body: object, expected: str
) -> None:
    errors = validate_create_delta_plan_v2_body_shape(body)
    assert errors and expected in errors[0]


def test_exact_requirement_coverage_roles_and_reciprocal_leaf_binding_fail_closed() -> None:
    with pytest.raises(BrainError, match="does not cover"):
        _admit({"o": [{"k": "a", "q": [0], "s": 10, "n": 20}]})
    with pytest.raises(BrainError, match="not authorized"):
        _admit({"o": [{"k": "a", "q": [1], "s": 10, "n": 20}]}, active=(1,))
    projection = _projection()
    requirements = (
        projection.requirements[0],
        replace(projection.requirements[1], allowed_ops=frozenset({"attach", "set"})),
    )
    projection = replace(projection, requirements=requirements)
    projection = replace(
        projection,
        projection_revision=compact_authority_projection_revision(
            surface_revision=SURFACE, requirements=requirements, authorities=projection.authorities
        ),
    )
    with pytest.raises(BrainError, match="reciprocal"):
        admit_create_delta_plan_v2(
            {"o": [{"k": "a", "q": [0, 1], "s": 10, "n": 20}]},
            projection=projection,
            mode="initial",
            context_revision=CONTEXT,
            semantic_revision=SEMANTIC,
            target_ref=TARGET,
            basis_ref=None,
            active_requirement_handles=(0, 1),
        )


def test_unknown_swapped_and_forward_virtual_handles_fail_closed() -> None:
    with pytest.raises(BrainError, match="unknown requirement"):
        _admit({"o": [{"k": "a", "q": [63], "s": 10, "n": 20}]}, active=(0,))
    with pytest.raises(BrainError, match="unknown or forward virtual slot"):
        _admit({"o": [{"k": "a", "q": [0], "s": 20, "n": 20}]}, active=(0,))
    with pytest.raises(BrainError, match="unknown node"):
        _admit({"o": [{"k": "a", "q": [0], "s": 10, "n": 10}]}, active=(0,))


def test_projection_rejects_unproven_leaf_foreign_binding_and_bad_revision() -> None:
    projection = _projection()
    node = projection.authorities[2]
    assert isinstance(node, NodeGrant)
    incomplete = replace(node, leaf_bindings=(_leaf("/kind"),))
    bad = replace(
        projection,
        authorities=projection.authorities[:2] + (incomplete,) + projection.authorities[3:],
    )
    with pytest.raises(BrainError, match="does not prove"):
        validate_compact_authority_projection(bad)

    foreign = replace(
        node,
        leaf_bindings=(_leaf("/kind", ("hostref:foreign",)), _leaf("/value", ("hostref:foreign",))),
    )
    bad = replace(
        projection, authorities=projection.authorities[:2] + (foreign,) + projection.authorities[3:]
    )
    with pytest.raises(BrainError, match="foreign"):
        validate_compact_authority_projection(bad)

    with pytest.raises(BrainError, match="revision differs"):
        validate_compact_authority_projection(
            replace(projection, projection_revision="sha256:" + "e" * 64)
        )


def test_basis_nodes_use_exact_private_paths_not_fragment_equality() -> None:
    projection = _projection()
    first = _node(
        50,
        "hostref:basis-first",
        state="basis",
        parent="hostref:slot-append",
        removable=True,
        basis_path=("blocks", 0),
    )
    second = replace(first, handle=51, ref="hostref:basis-second", basis_path=("blocks", 1))
    authorities = projection.authorities + (first, second)
    projected = replace(
        projection,
        authorities=authorities,
        projection_revision=compact_authority_projection_revision(
            surface_revision=SURFACE,
            requirements=projection.requirements,
            authorities=authorities,
        ),
    )
    index = validate_compact_authority_projection(projected)
    assert index.nodes_by_handle[50].basis_path == ("blocks", 0)
    assert index.nodes_by_handle[51].basis_path == ("blocks", 1)
    with pytest.raises(BrainError, match="revision differs"):
        validate_compact_authority_projection(
            replace(
                projected,
                authorities=authorities[:-1] + (replace(second, basis_path=("blocks", 2)),),
            )
        )


def test_false_and_null_scalars_need_leaf_proof_and_structural_skeletons_stay_shallow() -> None:
    projection = _projection()
    node = projection.authorities[2]
    assert isinstance(node, NodeGrant)
    fragment = {"enabled": False, "fallback": None}
    smuggled = replace(node, fragment=fragment, fragment_sha256=_hash(fragment), leaf_bindings=())
    bad = replace(
        projection,
        authorities=projection.authorities[:2] + (smuggled,) + projection.authorities[3:],
    )
    with pytest.raises(BrainError, match="does not prove"):
        validate_compact_authority_projection(bad)

    shallow = {"name": "block", "children": []}
    shallow_node = replace(
        node,
        fragment_type="block",
        fragment=shallow,
        fragment_sha256=_hash(shallow),
        leaf_bindings=(_leaf("/name"),),
    )
    accepted = replace(
        projection,
        authorities=projection.authorities[:2] + (shallow_node,) + projection.authorities[3:],
    )
    accepted = replace(
        accepted,
        projection_revision=compact_authority_projection_revision(
            surface_revision=SURFACE,
            requirements=accepted.requirements,
            authorities=accepted.authorities,
        ),
    )
    assert validate_compact_authority_projection(accepted)
    populated = {"name": "block", "children": [{"name": "hidden"}]}
    nested = replace(
        shallow_node,
        fragment=populated,
        fragment_sha256=_hash(populated),
        leaf_bindings=(_leaf("/name"), _leaf("/children/0/name")),
    )
    bad = replace(
        projection, authorities=projection.authorities[:2] + (nested,) + projection.authorities[3:]
    )
    with pytest.raises(BrainError, match="populated child"):
        validate_compact_authority_projection(bad)


@pytest.mark.parametrize(
    ("fragment_type", "fragment"),
    (
        ("value", {"kind": "lit", "lexical": "text", "value": "Italia"}),
        ("title", {"kind": "literal", "value": "Film italiani"}),
        (
            "guard",
            {
                "kind": "compare",
                "left": {"kind": "field", "name": "paesiorigine"},
                "op": "eq",
                "right": {"kind": "lit", "lexical": "text", "value": "Italia"},
            },
        ),
        (
            "predicate",
            {
                "op": "eq",
                "field": "paesiorigine",
                "value": {"kind": "lit", "lexical": "text", "value": "Italia"},
            },
        ),
        ("order", {"by": "field", "direction": "ascending", "field": "annoproduzione"}),
        (
            "groupBy",
            {
                "fields": ["series_title"],
                "member_order": [],
                "member_limit": 24,
                "having": None,
            },
        ),
    ),
)
def test_exact_atomic_fragments_bypass_the_new_node_skeleton_guard(
    fragment_type: str, fragment: object
) -> None:
    projection = _projection()
    node = projection.authorities[2]
    assert isinstance(node, NodeGrant)
    atomic_node = replace(
        node,
        fragment_type=fragment_type,
        fragment=fragment,
        fragment_sha256=_hash(fragment),
        leaf_bindings=_all_leaf_bindings(fragment),
    )
    authorities = projection.authorities[:2] + (atomic_node,) + projection.authorities[3:]
    atomic_projection = replace(
        projection,
        authorities=authorities,
        projection_revision=compact_authority_projection_revision(
            surface_revision=SURFACE,
            requirements=projection.requirements,
            authorities=authorities,
        ),
    )

    assert validate_compact_authority_projection(atomic_projection)


def test_new_fragment_registry_is_the_explicit_current_non_root_builder_roster() -> None:
    assert (
        frozenset(CREATE_ENDPOINT_SPEC_SCHEMA["$defs"]) - {"endpoint"}
        == CREATE_V2_NEW_FRAGMENT_TYPES
    )
    assert "endpoint" not in CREATE_V2_NEW_FRAGMENT_TYPES


@pytest.mark.parametrize(
    ("fragment_type", "fragment", "member"),
    (
        ("container", _container(), "blocks"),
        ("variant", _variant(), "variants"),
        ("fetch", _fetch(), "fetches"),
        ("contextBinding", _context_binding(), "context"),
    ),
)
def test_exact_structural_fragments_require_their_pinned_builder_placement(
    fragment_type: str, fragment: object, member: str
) -> None:
    projection = _projection()
    parent = replace(
        projection.authorities[0],
        member=member,
        accepts=(fragment_type,),
        cardinality="many",
        insertion="append",
    )
    node = projection.authorities[2]
    assert isinstance(parent, SlotGrant) and isinstance(node, NodeGrant)
    typed = replace(
        node,
        fragment_type=fragment_type,
        fragment=fragment,
        fragment_sha256=_hash(fragment),
        leaf_bindings=_all_leaf_bindings(fragment),
        parent_slot_ref=parent.ref,
    )
    authorities = (parent,) + projection.authorities[1:2] + (typed,) + projection.authorities[3:]
    exact = replace(
        projection,
        authorities=authorities,
        projection_revision=compact_authority_projection_revision(
            surface_revision=SURFACE,
            requirements=projection.requirements,
            authorities=authorities,
        ),
    )

    assert validate_compact_authority_projection(exact)

    misplaced_parent = replace(parent, member="items")
    misplaced_authorities = (misplaced_parent,) + exact.authorities[1:]
    misplaced = replace(
        exact,
        authorities=misplaced_authorities,
        projection_revision=compact_authority_projection_revision(
            surface_revision=SURFACE,
            requirements=exact.requirements,
            authorities=misplaced_authorities,
        ),
    )
    with pytest.raises(BrainError, match="placement is incompatible"):
        validate_compact_authority_projection(misplaced)

    wrong_shape_parent = replace(parent, cardinality="one", insertion="replace")
    wrong_shape_authorities = (wrong_shape_parent,) + exact.authorities[1:]
    wrong_shape = replace(
        exact,
        authorities=wrong_shape_authorities,
        projection_revision=compact_authority_projection_revision(
            surface_revision=SURFACE,
            requirements=exact.requirements,
            authorities=wrong_shape_authorities,
        ),
    )
    with pytest.raises(BrainError, match="placement is incompatible"):
        validate_compact_authority_projection(wrong_shape)


def test_root_and_future_populated_fragment_types_never_gain_the_typed_exemption() -> None:
    projection = _projection()
    node = projection.authorities[2]
    assert isinstance(node, NodeGrant)
    endpoint = initial_create_endpoint_skeleton("demo.forbidden")["endpoint"]
    root = replace(
        node,
        fragment_type="endpoint",
        fragment=endpoint,
        fragment_sha256=_hash(endpoint),
        leaf_bindings=_all_leaf_bindings(endpoint),
    )
    authorities = projection.authorities[:2] + (root,) + projection.authorities[3:]
    forbidden = replace(
        projection,
        authorities=authorities,
        projection_revision=compact_authority_projection_revision(
            surface_revision=SURFACE,
            requirements=projection.requirements,
            authorities=authorities,
        ),
    )
    with pytest.raises(BrainError, match="root endpoint"):
        validate_compact_authority_projection(forbidden)

    future = replace(
        root,
        fragment_type="futureContainer",
        fragment=_container(),
        fragment_sha256=_hash(_container()),
        leaf_bindings=_all_leaf_bindings(_container()),
    )
    authorities = projection.authorities[:2] + (future,) + projection.authorities[3:]
    unreviewed = replace(
        projection,
        authorities=authorities,
        projection_revision=compact_authority_projection_revision(
            surface_revision=SURFACE,
            requirements=projection.requirements,
            authorities=authorities,
        ),
    )
    with pytest.raises(BrainError, match="populated child"):
        validate_compact_authority_projection(unreviewed)


def test_atomic_value_label_cannot_bypass_skeleton_with_an_endpoint_subtree_or_list() -> None:
    projection = _projection()
    node = projection.authorities[2]
    assert isinstance(node, NodeGrant)
    endpoint_subtree = initial_create_endpoint_skeleton("demo.smuggled")["endpoint"]
    endpoint_subtree["blocks"] = [{"name": "hidden"}]
    smuggled = replace(
        node,
        fragment_type="value",
        fragment=endpoint_subtree,
        fragment_sha256=_hash(endpoint_subtree),
        leaf_bindings=_all_leaf_bindings(endpoint_subtree),
    )
    authorities = projection.authorities[:2] + (smuggled,) + projection.authorities[3:]
    bad = replace(
        projection,
        authorities=authorities,
        projection_revision=compact_authority_projection_revision(
            surface_revision=SURFACE,
            requirements=projection.requirements,
            authorities=authorities,
        ),
    )

    with pytest.raises(BrainError, match="populated child"):
        validate_compact_authority_projection(bad)

    populated_list = [{"blocks": [{"name": "hidden"}]}]
    smuggled_list = replace(
        node,
        fragment_type="value",
        fragment=populated_list,
        fragment_sha256=_hash(populated_list),
        leaf_bindings=_all_leaf_bindings(populated_list),
    )
    authorities = projection.authorities[:2] + (smuggled_list,) + projection.authorities[3:]
    bad_list = replace(
        projection,
        authorities=authorities,
        projection_revision=compact_authority_projection_revision(
            surface_revision=SURFACE,
            requirements=projection.requirements,
            authorities=authorities,
        ),
    )

    with pytest.raises(BrainError, match="populated child"):
        validate_compact_authority_projection(bad_list)


def test_child_slot_is_not_usable_until_parent_new_node_was_attached() -> None:
    projection = _projection()
    child_slot = _slot(12, "hostref:slot-child")
    child_slot = replace(child_slot, anchor_ref="hostref:node-new", cardinality="one")
    value = _node(23, "hostref:value-child", parent="hostref:slot-child", requirements=(REQ_A,))
    expanded = replace(
        projection,
        authorities=projection.authorities[:2]
        + (child_slot,)
        + projection.authorities[2:]
        + (value,),
    )
    expanded = replace(
        expanded,
        requirements=(
            replace(
                expanded.requirements[0],
                allowed_ops=frozenset({"attach", "set", "remove", "expand"}),
            ),
            expanded.requirements[1],
        ),
    )
    expanded = replace(
        expanded,
        projection_revision=compact_authority_projection_revision(
            surface_revision=SURFACE,
            requirements=expanded.requirements,
            authorities=expanded.authorities,
        ),
    )
    kwargs = dict(
        projection=expanded,
        mode="initial",
        context_revision=CONTEXT,
        semantic_revision=SEMANTIC,
        target_ref=TARGET,
        basis_ref=None,
        active_requirement_handles=(0,),
    )
    with pytest.raises(BrainError, match="forward virtual"):
        admit_create_delta_plan_v2({"o": [{"k": "s", "q": [0], "s": 12, "v": 23}]}, **kwargs)
    plan = admit_create_delta_plan_v2(
        {"o": [{"k": "a", "q": [0], "s": 10, "n": 20}, {"k": "s", "q": [0], "s": 12, "v": 23}]},
        **kwargs,
    )
    assert isinstance(plan.operations[-1], SetOpV2)


def test_initial_and_refinement_basis_contracts_are_injected_not_model_supplied() -> None:
    body = {"o": [{"k": "a", "q": [0], "s": 10, "n": 20}]}
    with pytest.raises(BrainError, match="mode and basis"):
        admit_create_delta_plan_v2(
            body,
            projection=_projection(),
            mode="initial",
            context_revision=CONTEXT,
            semantic_revision=SEMANTIC,
            target_ref=TARGET,
            basis_ref=BASIS,
            active_requirement_handles=(0,),
        )
    refinement = admit_create_delta_plan_v2(
        body,
        projection=_projection(),
        mode="refinement",
        context_revision=CONTEXT,
        semantic_revision=SEMANTIC,
        target_ref=TARGET,
        basis_ref=BASIS,
        active_requirement_handles=(0,),
    )
    assert refinement.mode == "refinement" and refinement.basis_ref == BASIS


def test_strict_json_parser_rejects_duplicate_constant_and_trailing_members() -> None:
    kwargs = {
        "projection": _projection(),
        "mode": "initial",
        "context_revision": CONTEXT,
        "semantic_revision": SEMANTIC,
        "target_ref": TARGET,
        "basis_ref": None,
        "active_requirement_handles": (0,),
    }
    assert parse_create_delta_plan_v2_json(
        '{"o":[{"k":"a","q":[0],"s":10,"n":20}]}', **kwargs
    ).operations
    for raw in [
        '{"o":[],"o":[]}',
        '{"o":NaN}',
        '{"o":[{"k":"a","q":[0],"s":10,"n":20}]} false',
    ]:
        with pytest.raises(BrainError) as raised:
            parse_create_delta_plan_v2_json(raw, **kwargs)
        assert raised.value.code == "CREATE_DELTA_PLAN_V2_INVALID"


def test_initial_skeleton_is_exact_empty_typed_builder_shape() -> None:
    assert initial_create_endpoint_skeleton("demo.endpoint") == {
        "schema_version": 1,
        "contract_id": "metis-brain-create-endpoint-spec/v1",
        "endpoint": {
            "name": "demo.endpoint",
            "reference": None,
            "params": {"timeout": None, "expires": None, "paginate": None},
            "inputs": [],
            "needs_time": False,
            "attributes": [],
            "input_pipeline": [],
            "output_pipeline": [],
            "inheritance": {"without_input": [], "without_output": []},
            "context": [],
            "blocks": [],
            "variants": [],
            "output": None,
        },
    }
