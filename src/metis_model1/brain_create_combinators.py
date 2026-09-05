"""Code-pinned generic expansion combinators for compact CREATE plan v2.

These four routines are intentionally structural.  They know neither tenant
catalogs, endpoint source, fallback text nor Metis syntax.  Every row selects
only private projection grants and is revalidated before it emits a detached,
typed structural mutation.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from metis_model1.brain_create_plan_v2 import (
    CompactAuthorityProjection,
    CompactProjectionIndex,
    ExpansionRow,
    NodeGrant,
    RecipeGrant,
    SlotGrant,
    validate_compact_authority_projection,
)
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json

MAX_COMBINATOR_ROWS = 12
MAX_COMBINATOR_EMISSIONS = 128
MAX_ROLE_COMPOSE_STEPS = 32
COMBINATOR_SCOPE_MEMBERS = (
    "attributes",
    "blocks",
    "context",
    "input_pipeline",
    "inputs",
    "items",
    "output_pipeline",
    "variants",
    "without_input",
    "without_output",
)

_DESCRIPTORS: dict[str, dict[str, Any]] = {
    "map.attach/v1": {
        "row_type": "mapAttachRow",
        "output_type": "value",
        "scope_members": COMBINATOR_SCOPE_MEMBERS,
        "argument_fields": ("node_ref", "target_slot_ref"),
    },
    "map.set/v1": {
        "row_type": "mapSetRow",
        "output_type": "value",
        "scope_members": COMBINATOR_SCOPE_MEMBERS,
        "argument_fields": ("target_slot_ref", "value_ref"),
    },
    "matrix.attach/v1": {
        "row_type": "matrixAttachRow",
        "output_type": "value",
        "scope_members": COMBINATOR_SCOPE_MEMBERS,
        "argument_fields": ("axis_bindings", "node_ref", "target_slot_ref"),
    },
    "quota.distribute/v1": {
        "row_type": "quotaDistributeRow",
        "output_type": "value",
        "scope_members": COMBINATOR_SCOPE_MEMBERS,
        "argument_fields": ("occurrences", "strategy", "targets"),
    },
    "role.compose/v1": {
        "row_type": "roleComposeRow",
        "output_type": "value",
        "scope_members": COMBINATOR_SCOPE_MEMBERS,
        "argument_fields": ("steps",),
    },
}
COMBINATOR_CONTRACT_SHA256 = {
    name: bytes_sha256(
        canonical_json({"contract": "metis-brain-create-combinator/v1", "id": name, **descriptor})
    )
    for name, descriptor in _DESCRIPTORS.items()
}
# This is intentionally a source pin, not a descriptor hash: changing an
# algorithm, a validation branch or an allocation policy changes every recipe
# pin and forces a new server-issued projection.
_MODULE_IMPLEMENTATION_SHA256 = bytes_sha256(Path(__file__).read_bytes())
COMBINATOR_IMPLEMENTATION_SHA256 = {name: _MODULE_IMPLEMENTATION_SHA256 for name in _DESCRIPTORS}


@dataclass(frozen=True, slots=True)
class AttachEmission:
    row_ref: str
    target_slot_ref: str
    node_ref: str
    substitutions: tuple[MatrixSubstitution, ...] = ()
    kind: Literal["attach"] = "attach"


@dataclass(frozen=True, slots=True)
class SetEmission:
    row_ref: str
    target_slot_ref: str
    value_ref: str
    kind: Literal["set"] = "set"


@dataclass(frozen=True, slots=True)
class QuotaEmission:
    row_ref: str
    target_slot_ref: str
    node_ref: str
    occurrences: int
    strategy: Literal["balanced", "front_loaded"]
    kind: Literal["quota"] = "quota"


CombinatorEmission = AttachEmission | SetEmission | QuotaEmission


@dataclass(frozen=True, slots=True)
class MatrixSubstitution:
    axis_ref: str
    value_ref: str
    json_pointer: str


@dataclass(frozen=True, slots=True)
class CombinatorResult:
    recipe_ref: str
    recipe_id: str
    emissions: tuple[CombinatorEmission, ...]
    requirement_refs: frozenset[str]


def _invalid(message: str) -> BrainError:
    return BrainError("CREATE_COMBINATOR_INVALID", 502, message)


def _mapping(value: Any, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _invalid(f"{label} must be an object")
    return value


def _exact_mapping(value: Any, *, fields: tuple[str, ...], label: str) -> Mapping[str, Any]:
    mapping = _mapping(value, label=label)
    if set(mapping) != set(fields):
        raise _invalid(f"{label} has an invalid field roster")
    return mapping


def _node_by_ref(index: CompactProjectionIndex, ref: Any, *, label: str) -> NodeGrant:
    if not isinstance(ref, str):
        raise _invalid(f"{label} is invalid")
    for node in index.nodes_by_handle.values():
        if node.ref == ref:
            return node
    raise _invalid(f"{label} is not a projected node")


def _slot_by_ref(index: CompactProjectionIndex, ref: Any, *, label: str) -> SlotGrant:
    if not isinstance(ref, str):
        raise _invalid(f"{label} is invalid")
    for slot in index.slots_by_handle.values():
        if slot.ref == ref:
            return slot
    raise _invalid(f"{label} is not a projected slot")


def _rows(index: CompactProjectionIndex, row_handles: Sequence[int]) -> tuple[ExpansionRow, ...]:
    if isinstance(row_handles, (str, bytes)) or not isinstance(row_handles, Sequence):
        raise _invalid("expansion row handles are invalid")
    if not 1 <= len(row_handles) <= MAX_COMBINATOR_ROWS or len(set(row_handles)) != len(
        row_handles
    ):
        raise _invalid("expansion row handle roster is invalid")
    output: list[ExpansionRow] = []
    for handle in row_handles:
        if isinstance(handle, bool) or not isinstance(handle, int):
            raise _invalid("expansion row handle is invalid")
        try:
            output.append(index.rows_by_handle[handle])
        except KeyError as error:
            raise _invalid("expansion row handle is unknown") from error
    return tuple(output)


def _recipe(index: CompactProjectionIndex, handle: int) -> RecipeGrant:
    if isinstance(handle, bool) or not isinstance(handle, int):
        raise _invalid("recipe handle is invalid")
    try:
        recipe = index.recipes_by_handle[handle]
    except KeyError as error:
        raise _invalid("recipe handle is unknown") from error
    descriptor = _DESCRIPTORS.get(recipe.recipe_id)
    if descriptor is None or recipe.version != 1:
        raise _invalid("recipe id or version is not code-pinned")
    if (
        recipe.row_type != descriptor["row_type"]
        or recipe.output_type != descriptor["output_type"]
        or recipe.scope_members != descriptor["scope_members"]
    ):
        raise _invalid("recipe type differs from its code-pinned contract")
    expected_hash = COMBINATOR_IMPLEMENTATION_SHA256[recipe.recipe_id]
    if not hmac.compare_digest(recipe.implementation_sha256, expected_hash):
        raise _invalid("recipe implementation hash differs")
    return recipe


def _slot(index: CompactProjectionIndex, handle: int) -> SlotGrant:
    if isinstance(handle, bool) or not isinstance(handle, int):
        raise _invalid("slot handle is invalid")
    try:
        return index.slots_by_handle[handle]
    except KeyError as error:
        raise _invalid("slot handle is unknown or forward") from error


def _check_node_attach(slot: SlotGrant, node: NodeGrant, *, label: str) -> None:
    if "attach" not in slot.mutations or node.state != "new" or node.parent_slot_ref != slot.ref:
        raise _invalid(f"{label} node cannot attach to the selected slot")
    if node.fragment_type not in slot.accepts:
        raise _invalid(f"{label} node type is not accepted by the selected slot")


def _check_value_set(slot: SlotGrant, value: NodeGrant, *, label: str) -> None:
    if (
        "set" not in slot.mutations
        or value.state != "new"
        or value.fragment_type not in slot.accepts
        or value.parent_slot_ref != slot.ref
    ):
        raise _invalid(f"{label} value cannot set the selected slot")


def _in_scope(index: CompactProjectionIndex, scope: SlotGrant, target: SlotGrant) -> bool:
    """Prove target is the scope itself or its projected descendant slot."""

    if target.ref == scope.ref:
        return True
    slots_by_ref = {item.ref: item for item in index.slots_by_handle.values()}
    nodes_by_ref = {item.ref: item for item in index.nodes_by_handle.values()}
    current_anchor = target.anchor_ref
    visited: set[str] = set()
    while current_anchor not in visited:
        visited.add(current_anchor)
        if current_anchor == scope.ref:
            return True
        parent_slot = slots_by_ref.get(current_anchor)
        if parent_slot is not None:
            current_anchor = parent_slot.anchor_ref
            continue
        parent_node = nodes_by_ref.get(current_anchor)
        if parent_node is not None and parent_node.parent_slot_ref is not None:
            current_anchor = parent_node.parent_slot_ref
            continue
        return False
    return False


def _target_slot(
    index: CompactProjectionIndex, scope: SlotGrant, ref: Any, *, label: str
) -> SlotGrant:
    target = _slot_by_ref(index, ref, label=label)
    if not _in_scope(index, scope, target):
        raise _invalid(f"{label} is outside the selected expansion scope")
    return target


def _pointer_value(value: Any, pointer: Any, *, label: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise _invalid(f"{label} is invalid")
    current = value
    for raw_token in pointer[1:].split("/"):
        if "~" in raw_token and any(
            raw_token[index : index + 2] not in {"~0", "~1"}
            for index, character in enumerate(raw_token)
            if character == "~"
        ):
            raise _invalid(f"{label} is invalid")
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                raise _invalid(f"{label} is absent")
            current = current[token]
        elif isinstance(current, list):
            if not token.isdecimal() or (len(token) > 1 and token.startswith("0")):
                raise _invalid(f"{label} is invalid")
            position = int(token)
            if position >= len(current):
                raise _invalid(f"{label} is absent")
            current = current[position]
        else:
            raise _invalid(f"{label} descends through a scalar")
    return current


def _matching_pointers(value: Any, expected: Any, pointer: str = "") -> set[str]:
    if canonical_json(value) == canonical_json(expected):
        return {pointer}
    if isinstance(value, Mapping):
        output: set[str] = set()
        for key, nested in value.items():
            if isinstance(key, str):
                escaped = key.replace("~", "~0").replace("/", "~1")
                output.update(_matching_pointers(nested, expected, f"{pointer}/{escaped}"))
        return output
    if isinstance(value, list):
        output = set()
        for index, nested in enumerate(value):
            output.update(_matching_pointers(nested, expected, f"{pointer}/{index}"))
        return output
    return set()


def _balanced(total: int, targets: Sequence[SlotGrant]) -> tuple[int, ...]:
    base, remainder = divmod(total, len(targets))
    return tuple(base + (1 if index < remainder else 0) for index in range(len(targets)))


def _front_loaded(total: int, targets: Sequence[SlotGrant]) -> tuple[int, ...]:
    """Deterministic front-load with no target skipped while total permits it."""

    if total < len(targets):
        return tuple(1 if index < total else 0 for index in range(len(targets)))
    # First establish one occurrence per target.  The remainder is intentionally
    # assigned to the earliest target: a deterministic front-loaded strategy.
    return tuple((1 + total - len(targets)) if index == 0 else 1 for index in range(len(targets)))


def _map_attach(
    index: CompactProjectionIndex,
    slot: SlotGrant,
    recipe: RecipeGrant,
    rows: tuple[ExpansionRow, ...],
) -> tuple[AttachEmission, ...]:
    output: list[AttachEmission] = []
    for row in rows:
        arguments = _exact_mapping(
            row.arguments, fields=("node_ref", "target_slot_ref"), label="map.attach row"
        )
        target = _target_slot(
            index, slot, arguments["target_slot_ref"], label="map.attach target slot ref"
        )
        node = _node_by_ref(index, arguments["node_ref"], label="map.attach node ref")
        _check_node_attach(target, node, label="map.attach")
        output.append(AttachEmission(row.ref, target.ref, node.ref))
    return tuple(output)


def _map_set(
    index: CompactProjectionIndex,
    slot: SlotGrant,
    recipe: RecipeGrant,
    rows: tuple[ExpansionRow, ...],
) -> tuple[SetEmission, ...]:
    output: list[SetEmission] = []
    targets: set[str] = set()
    for row in rows:
        arguments = _exact_mapping(
            row.arguments, fields=("target_slot_ref", "value_ref"), label="map.set row"
        )
        target = _target_slot(
            index, slot, arguments["target_slot_ref"], label="map.set target slot ref"
        )
        if target.cardinality != "one" or target.ref in targets:
            raise _invalid("map.set requires distinct one-cardinality target slots")
        targets.add(target.ref)
        value = _node_by_ref(index, arguments["value_ref"], label="map.set value ref")
        _check_value_set(target, value, label="map.set")
        output.append(SetEmission(row.ref, target.ref, value.ref))
    return tuple(output)


def _matrix_attach(
    index: CompactProjectionIndex,
    slot: SlotGrant,
    recipe: RecipeGrant,
    rows: tuple[ExpansionRow, ...],
) -> tuple[AttachEmission, ...]:
    output: list[AttachEmission] = []
    for row in rows:
        arguments = _exact_mapping(
            row.arguments,
            fields=("axis_bindings", "node_ref", "target_slot_ref"),
            label="matrix.attach row",
        )
        target = _target_slot(
            index, slot, arguments["target_slot_ref"], label="matrix.attach target slot ref"
        )
        node = _node_by_ref(index, arguments["node_ref"], label="matrix.attach node ref")
        _check_node_attach(target, node, label="matrix.attach")
        raw_bindings = arguments["axis_bindings"]
        if (
            isinstance(raw_bindings, (str, bytes))
            or not isinstance(raw_bindings, Sequence)
            or not 1 <= len(raw_bindings) <= 3
        ):
            raise _invalid("matrix.attach substitution roster is invalid")
        substitutions: list[MatrixSubstitution] = []
        seen_axes: set[str] = set()
        seen_pointers: set[str] = set()
        for binding in raw_bindings:
            typed = _exact_mapping(
                binding,
                fields=("axis_ref", "json_pointer", "value_ref"),
                label="matrix.attach substitution",
            )
            axis_node = _node_by_ref(index, typed["axis_ref"], label="matrix.attach axis ref")
            value_node = _node_by_ref(
                index, typed["value_ref"], label="matrix.attach substitution value ref"
            )
            if (
                axis_node.fragment_type != "value"
                or value_node.fragment_type != "value"
                or axis_node.ref in seen_axes
                or axis_node.ref == value_node.ref
            ):
                raise _invalid("matrix.attach substitution is not closed and typed")
            pointer = typed["json_pointer"]
            if (
                _pointer_value(node.fragment, pointer, label="matrix.attach axis pointer")
                != axis_node.fragment
            ):
                raise _invalid("matrix.attach axis pointer does not bind its exact placeholder")
            if pointer in seen_pointers or _matching_pointers(
                node.fragment, axis_node.fragment
            ) != {pointer}:
                raise _invalid("matrix.attach axis placeholder is residual or ambiguous")
            seen_axes.add(axis_node.ref)
            seen_pointers.add(pointer)
            substitutions.append(MatrixSubstitution(axis_node.ref, value_node.ref, pointer))
        output.append(AttachEmission(row.ref, target.ref, node.ref, tuple(substitutions)))
    return tuple(output)


def _quota_distribute(
    index: CompactProjectionIndex,
    slot: SlotGrant,
    recipe: RecipeGrant,
    rows: tuple[ExpansionRow, ...],
) -> tuple[QuotaEmission, ...]:
    output: list[QuotaEmission] = []
    for row in rows:
        arguments = _exact_mapping(
            row.arguments,
            fields=("occurrences", "strategy", "targets"),
            label="quota.distribute row",
        )
        total = arguments["occurrences"]
        if (
            isinstance(total, bool)
            or not isinstance(total, int)
            or not 1 <= total <= recipe.max_emitted_mutations
        ):
            raise _invalid("quota.distribute occurrence count is invalid")
        strategy = arguments["strategy"]
        if strategy not in {"balanced", "front_loaded"}:
            raise _invalid("quota.distribute strategy is invalid")
        raw_targets = arguments["targets"]
        if (
            isinstance(raw_targets, (str, bytes))
            or not isinstance(raw_targets, Sequence)
            or not 1 <= len(raw_targets) <= MAX_COMBINATOR_ROWS
        ):
            raise _invalid("quota.distribute target roster is invalid")
        targets: list[tuple[SlotGrant, NodeGrant]] = []
        seen_target_refs: set[str] = set()
        for raw_target in raw_targets:
            typed = _exact_mapping(
                raw_target,
                fields=("node_ref", "target_slot_ref"),
                label="quota.distribute target",
            )
            target = _target_slot(
                index, slot, typed["target_slot_ref"], label="quota.distribute target slot ref"
            )
            if target.ref in seen_target_refs:
                raise _invalid("quota.distribute targets are duplicated")
            seen_target_refs.add(target.ref)
            node = _node_by_ref(index, typed["node_ref"], label="quota.distribute node ref")
            if target.cardinality != "many":
                raise _invalid("quota.distribute target is not an expandable collection slot")
            _check_node_attach(target, node, label="quota.distribute")
            targets.append((target, node))
        allocations = (
            _balanced(total, [target for target, _ in targets])
            if strategy == "balanced"
            else _front_loaded(total, [target for target, _ in targets])
        )
        for (target, node), count in zip(targets, allocations, strict=True):
            if count:
                output.append(QuotaEmission(row.ref, target.ref, node.ref, count, strategy))
    return tuple(output)


def _role_compose(
    index: CompactProjectionIndex,
    slot: SlotGrant,
    recipe: RecipeGrant,
    rows: tuple[ExpansionRow, ...],
) -> tuple[AttachEmission | SetEmission, ...]:
    """Expand one or more small roles over pre-authorized grants only.

    The recipe owns ordering, validation and bounds, never endpoint content.
    Every emitted fragment and every scalar used to address it remains a
    private ``NodeGrant``/``ExpansionRow`` leaf with its own evidence.  A row
    therefore cannot smuggle source, a scenario blueprint or a populated
    subtree into code-owned defaults.
    """

    nodes_by_ref = {node.ref: node for node in index.nodes_by_handle.values()}
    active_new_nodes: set[str] = set()
    materialized_nodes: set[str] = set()
    set_targets: set[str] = set()
    output: list[AttachEmission | SetEmission] = []

    def checked_target(reference: Any, *, label: str) -> SlotGrant:
        target = _target_slot(index, slot, reference, label=label)
        anchor = nodes_by_ref.get(target.anchor_ref)
        if anchor is not None and anchor.state == "new" and anchor.ref not in active_new_nodes:
            raise _invalid(f"{label} precedes its owning node")
        return target

    for row in rows:
        arguments = _exact_mapping(row.arguments, fields=("steps",), label="role.compose row")
        steps = arguments["steps"]
        if (
            isinstance(steps, (str, bytes))
            or not isinstance(steps, Sequence)
            or not 1 <= len(steps) <= MAX_ROLE_COMPOSE_STEPS
        ):
            raise _invalid("role.compose step roster is invalid")
        for step in steps:
            item = _mapping(step, label="role.compose step")
            kind = item.get("kind")
            if kind == "attach":
                typed = _exact_mapping(
                    item,
                    fields=("kind", "node_ref", "target_slot_ref"),
                    label="role.compose attach step",
                )
                target = checked_target(
                    typed["target_slot_ref"], label="role.compose attach target slot ref"
                )
                node = _node_by_ref(index, typed["node_ref"], label="role.compose node ref")
                _check_node_attach(target, node, label="role.compose")
                if node.ref in materialized_nodes:
                    raise _invalid("role.compose materializes a node more than once")
                materialized_nodes.add(node.ref)
                active_new_nodes.add(node.ref)
                output.append(AttachEmission(row.ref, target.ref, node.ref))
            elif kind == "set":
                typed = _exact_mapping(
                    item,
                    fields=("kind", "target_slot_ref", "value_ref"),
                    label="role.compose set step",
                )
                target = checked_target(
                    typed["target_slot_ref"], label="role.compose set target slot ref"
                )
                value = _node_by_ref(index, typed["value_ref"], label="role.compose value ref")
                _check_value_set(target, value, label="role.compose")
                if target.cardinality != "one" or target.ref in set_targets:
                    raise _invalid("role.compose requires distinct one-cardinality set targets")
                if value.ref in materialized_nodes:
                    raise _invalid("role.compose materializes a node more than once")
                set_targets.add(target.ref)
                materialized_nodes.add(value.ref)
                active_new_nodes.add(value.ref)
                output.append(SetEmission(row.ref, target.ref, value.ref))
            else:
                raise _invalid("role.compose step kind is invalid")
    return tuple(output)


def _requirement_refs(
    index: CompactProjectionIndex,
    rows: Sequence[ExpansionRow],
    emissions: Sequence[CombinatorEmission],
) -> frozenset[str]:
    """Return the exact row plus materialized-node evidence union."""

    output = {
        requirement_ref
        for row in rows
        for binding in row.leaf_bindings
        for requirement_ref in binding.requirement_refs
    }
    nodes_by_ref = {node.ref: node for node in index.nodes_by_handle.values()}

    def add_node(reference: str, *, label: str) -> None:
        try:
            node = nodes_by_ref[reference]
        except KeyError as error:
            raise _invalid(f"{label} is not a projected node") from error
        output.update(
            requirement_ref
            for binding in node.leaf_bindings
            for requirement_ref in binding.requirement_refs
        )

    for emission in emissions:
        if isinstance(emission, AttachEmission):
            add_node(emission.node_ref, label="attach emission node")
            for substitution in emission.substitutions:
                add_node(substitution.axis_ref, label="matrix axis node")
                add_node(substitution.value_ref, label="matrix replacement node")
        elif isinstance(emission, SetEmission):
            add_node(emission.value_ref, label="set emission value")
        elif isinstance(emission, QuotaEmission):
            add_node(emission.node_ref, label="quota emission node")
        else:  # pragma: no cover - closed emission union
            raise _invalid("unknown combinator emission")
    return frozenset(output)


def execute_combinator(
    projection: CompactAuthorityProjection,
    *,
    slot_handle: int,
    recipe_handle: int,
    row_handles: Sequence[int],
) -> CombinatorResult:
    """Execute exactly one code-pinned structural recipe over private grants."""

    index = validate_compact_authority_projection(projection)
    slot = _slot(index, slot_handle)
    recipe = _recipe(index, recipe_handle)
    rows = _rows(index, row_handles)
    if slot.member not in recipe.scope_members:
        raise _invalid("expansion scope member is not authorized by its recipe")
    if len(rows) > recipe.max_rows:
        raise _invalid("recipe row count exceeds its bound")
    if any(row.recipe_id != recipe.recipe_id or row.row_type != recipe.row_type for row in rows):
        raise _invalid("row does not match the selected recipe")
    if recipe.recipe_id == "map.attach/v1":
        emissions: tuple[CombinatorEmission, ...] = _map_attach(index, slot, recipe, rows)
    elif recipe.recipe_id == "map.set/v1":
        emissions = _map_set(index, slot, recipe, rows)
    elif recipe.recipe_id == "matrix.attach/v1":
        emissions = _matrix_attach(index, slot, recipe, rows)
    elif recipe.recipe_id == "quota.distribute/v1":
        emissions = _quota_distribute(index, slot, recipe, rows)
    elif recipe.recipe_id == "role.compose/v1":
        emissions = _role_compose(index, slot, recipe, rows)
    else:  # pragma: no cover - _recipe rejects descriptors absent from this dispatch
        raise _invalid("recipe id has no code-pinned implementation")
    if (
        not emissions
        or len(emissions) > recipe.max_emitted_mutations
        or len(emissions) > MAX_COMBINATOR_EMISSIONS
    ):
        raise _invalid("recipe emitted an invalid mutation count")
    return CombinatorResult(
        recipe.ref,
        recipe.recipe_id,
        emissions,
        _requirement_refs(index, rows, emissions),
    )


__all__ = [
    "AttachEmission",
    "COMBINATOR_CONTRACT_SHA256",
    "COMBINATOR_IMPLEMENTATION_SHA256",
    "COMBINATOR_SCOPE_MEMBERS",
    "CombinatorEmission",
    "CombinatorResult",
    "MAX_COMBINATOR_EMISSIONS",
    "MAX_COMBINATOR_ROWS",
    "MAX_ROLE_COMPOSE_STEPS",
    "MatrixSubstitution",
    "QuotaEmission",
    "SetEmission",
    "execute_combinator",
]
