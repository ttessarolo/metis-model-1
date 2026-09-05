"""Deterministic private executor for admitted compact CREATE plan v2.

The decoder never reaches this module.  It receives only an already-admitted
``CreateDeltaPlanV2``; every fragment, locator, evidence binding and expansion
row remains in the validated private projection.  This executor deliberately
does not parse/render Metis, run a compiler, read a tenant or infer structure
from labels or fragment equality.
"""

from __future__ import annotations

import hmac
import json
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NoReturn

from metis_model1.brain_create_combinators import (
    AttachEmission,
    QuotaEmission,
    SetEmission,
    execute_combinator,
)
from metis_model1.brain_create_plan_v2 import (
    AttachOpV2,
    CompactAuthorityProjection,
    CompactProjectionIndex,
    CreateDeltaOperationV2,
    CreateDeltaPlanV2,
    ExpandOpV2,
    NodeGrant,
    RemoveOpV2,
    SetOpV2,
    SlotGrant,
    validate_compact_authority_projection,
)
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json

CREATE_DELTA_PLAN_V2_PERMIT_CONTRACT = "metis-brain-create-delta-plan-v2-permit/v1"
CREATE_DELTA_PLAN_V2_RECEIPT_CONTRACT = "metis-brain-create-delta-plan-v2-receipt/v1"
CREATE_DELTA_PLAN_V2_EXECUTION_CONTRACT = "metis-brain-create-delta-plan-v2-execution/v1"
MAX_EXECUTION_PATH_DEPTH = 24
MAX_EXECUTION_EMISSIONS = 128
MAX_GENERATION = (1 << 31) - 1


class CreateDeltaPlanV2ExecutionError(ValueError):
    """One fail-closed V2 permit, locator or deterministic-expansion error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> NoReturn:
    raise CreateDeltaPlanV2ExecutionError(code, message)


def _sha(value: Any) -> str:
    try:
        return bytes_sha256(canonical_json(value))
    except (BrainError, TypeError, UnicodeError, ValueError) as error:
        _fail("CREATE_V2_EXECUTOR_INVALID", "value is not strict canonical JSON")
        raise AssertionError from error


def _copy(value: Any, *, label: str) -> Any:
    try:
        return json.loads(canonical_json(value))
    except (BrainError, TypeError, UnicodeError, ValueError) as error:
        _fail("CREATE_V2_EXECUTOR_INVALID", f"{label} is not strict canonical JSON")
        raise AssertionError from error


def _hash(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
        _fail("CREATE_V2_EXECUTOR_INVALID", f"{label} is not an exact sha256")
    try:
        int(value[7:], 16)
    except ValueError:
        _fail("CREATE_V2_EXECUTOR_INVALID", f"{label} is not an exact sha256")
    return value


def _generation(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_GENERATION:
        _fail("CREATE_V2_EXECUTOR_INVALID", "generation is invalid")
    return value


def _path(value: Sequence[str | int], *, label: str) -> tuple[str | int, ...]:
    if isinstance(value, (str, bytes)) or not 1 <= len(value) <= MAX_EXECUTION_PATH_DEPTH:
        _fail("CREATE_V2_EXECUTOR_INVALID", f"{label} is invalid")
    output: list[str | int] = []
    for token in value:
        if isinstance(token, bool):
            _fail("CREATE_V2_EXECUTOR_INVALID", f"{label} is invalid")
        if isinstance(token, int):
            if token < 0:
                _fail("CREATE_V2_EXECUTOR_INVALID", f"{label} is invalid")
        elif not isinstance(token, str) or not token:
            _fail("CREATE_V2_EXECUTOR_INVALID", f"{label} is invalid")
        output.append(token)
    return tuple(output)


def _at(value: Any, path: Sequence[str | int], *, label: str) -> Any:
    current = value
    for token in _path(path, label=label):
        if isinstance(current, Mapping) and isinstance(token, str):
            if token not in current:
                _fail("CREATE_V2_LOCATOR_INVALID", f"{label} is absent")
            current = current[token]
        elif isinstance(current, list) and isinstance(token, int):
            if token >= len(current):
                _fail("CREATE_V2_LOCATOR_INVALID", f"{label} is absent")
            current = current[token]
        else:
            _fail("CREATE_V2_LOCATOR_INVALID", f"{label} has the wrong container type")
    return current


def _at_json_pointer(value: Any, pointer: str, *, label: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        _fail("CREATE_V2_LOCATOR_INVALID", f"{label} is invalid")
    current = value
    for raw in pointer[1:].split("/"):
        if "~" in raw and any(
            raw[index : index + 2] not in {"~0", "~1"}
            for index, character in enumerate(raw)
            if character == "~"
        ):
            _fail("CREATE_V2_LOCATOR_INVALID", f"{label} is invalid")
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                _fail("CREATE_V2_LOCATOR_INVALID", f"{label} is absent")
            current = current[token]
        elif isinstance(current, list):
            if not token.isdecimal() or (len(token) > 1 and token.startswith("0")):
                _fail("CREATE_V2_LOCATOR_INVALID", f"{label} is invalid")
            position = int(token)
            if position >= len(current):
                _fail("CREATE_V2_LOCATOR_INVALID", f"{label} is absent")
            current = current[position]
        else:
            _fail("CREATE_V2_LOCATOR_INVALID", f"{label} descends through a scalar")
    return current


def _decode_json_pointer(pointer: Any, *, label: str) -> tuple[str, ...]:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        _fail("CREATE_V2_LOCATOR_INVALID", f"{label} is invalid")
    tokens: list[str] = []
    for raw in pointer[1:].split("/"):
        if "~" in raw and any(
            raw[index : index + 2] not in {"~0", "~1"}
            for index, character in enumerate(raw)
            if character == "~"
        ):
            _fail("CREATE_V2_LOCATOR_INVALID", f"{label} is invalid")
        tokens.append(raw.replace("~1", "/").replace("~0", "~"))
    return tuple(tokens)


def _replace_json_pointer(value: Any, pointer: str, replacement: Any, *, label: str) -> None:
    tokens = _decode_json_pointer(pointer, label=label)
    current = value
    for token in tokens[:-1]:
        if isinstance(current, Mapping) and token in current:
            current = current[token]
        elif (
            isinstance(current, list)
            and token.isdecimal()
            and (len(token) == 1 or not token.startswith("0"))
            and int(token) < len(current)
        ):
            current = current[int(token)]
        else:
            _fail("CREATE_V2_LOCATOR_INVALID", f"{label} is absent")
    final = tokens[-1]
    if isinstance(current, dict) and final in current:
        current[final] = replacement
    elif (
        isinstance(current, list)
        and final.isdecimal()
        and (len(final) == 1 or not final.startswith("0"))
        and int(final) < len(current)
    ):
        current[int(final)] = replacement
    else:
        _fail("CREATE_V2_LOCATOR_INVALID", f"{label} is absent")


def _remove_at(value: Any, path: Sequence[str | int], *, label: str) -> None:
    checked = _path(path, label=label)
    if len(checked) < 1:
        _fail("CREATE_V2_LOCATOR_INVALID", f"{label} is invalid")
    parent = value if len(checked) == 1 else _at(value, checked[:-1], label=label)
    token = checked[-1]
    if isinstance(parent, list) and isinstance(token, int) and token < len(parent):
        parent.pop(token)
    elif isinstance(parent, dict) and isinstance(token, str) and token in parent:
        del parent[token]
    else:
        _fail("CREATE_V2_LOCATOR_INVALID", f"{label} is absent")


@dataclass(frozen=True, slots=True, repr=False)
class CreateDeltaPlanV2Permit:
    """Private exact binding for one execution; payload source is never exposed."""

    plan_sha256: str
    context_revision: str
    semantic_revision: str
    surface_revision: str
    projection_revision: str
    toolchain_binding: str
    generation: int
    target_ref: str
    basis_ref: str | None
    base_spec_sha256: str
    parent_spec_sha256: str | None
    binding_sha256: str
    permit_sha256: str
    contract_id: str = CREATE_DELTA_PLAN_V2_PERMIT_CONTRACT


@dataclass(frozen=True, slots=True, repr=False)
class CreateDeltaPlanV2PermitReceipt:
    permit_sha256: str
    binding_sha256: str
    receipt_sha256: str
    contract_id: str = CREATE_DELTA_PLAN_V2_RECEIPT_CONTRACT


@dataclass(frozen=True, slots=True)
class CreateDeltaPlanV2ProofInput:
    plan_sha256: str
    projection_revision: str
    surface_revision: str
    context_revision: str
    semantic_revision: str
    toolchain_binding: str
    generation: int
    target_ref: str
    basis_ref: str | None
    base_spec_sha256: str
    parent_spec_sha256: str | None
    operation_sha256: tuple[str, ...]
    emitted_mutations: int
    receipt: CreateDeltaPlanV2PermitReceipt


@dataclass(frozen=True, slots=True)
class CreateDeltaPlanV2Execution:
    """Detached private builder input plus hashes needed by the next authority gate."""

    spec: Mapping[str, Any]
    spec_sha256: str
    proof_input: CreateDeltaPlanV2ProofInput
    contract_id: str = CREATE_DELTA_PLAN_V2_EXECUTION_CONTRACT


def _binding_body(
    plan: CreateDeltaPlanV2,
    projection: CompactAuthorityProjection,
    *,
    toolchain_binding: str,
    generation: int,
    base_spec_sha256: str,
    parent_spec_sha256: str | None,
) -> dict[str, Any]:
    return {
        "plan_sha256": _sha(plan.internal_json()),
        "context_revision": plan.context_revision,
        "semantic_revision": plan.semantic_revision,
        "surface_revision": plan.surface_revision,
        "projection_revision": plan.projection_revision,
        "toolchain_binding": _hash(toolchain_binding, label="toolchain binding"),
        "generation": _generation(generation),
        "target_ref": plan.target_ref,
        "basis_ref": plan.basis_ref,
        "base_spec_sha256": _hash(base_spec_sha256, label="base spec sha256"),
        "parent_spec_sha256": (
            None
            if parent_spec_sha256 is None
            else _hash(parent_spec_sha256, label="parent spec sha256")
        ),
    }


def _validate_mode_and_parent(
    plan: CreateDeltaPlanV2, *, base_spec_sha256: str, parent_spec_sha256: str | None
) -> None:
    _hash(base_spec_sha256, label="base spec sha256")
    if plan.mode == "initial":
        if plan.basis_ref is not None or parent_spec_sha256 is not None:
            _fail("CREATE_V2_PARENT_INVALID", "initial execution cannot carry parent authority")
    elif plan.mode == "refinement":
        if plan.basis_ref is None or parent_spec_sha256 is None:
            _fail("CREATE_V2_PARENT_INVALID", "refinement requires exact parent authority")
        _hash(parent_spec_sha256, label="parent spec sha256")
        if not hmac.compare_digest(base_spec_sha256, parent_spec_sha256):
            _fail("CREATE_V2_PARENT_DRIFT", "base spec differs from the parent authority")
    else:
        _fail("CREATE_V2_EXECUTOR_INVALID", "plan mode is invalid")


def issue_create_delta_plan_v2_permit(
    plan: CreateDeltaPlanV2,
    projection: CompactAuthorityProjection,
    *,
    base_spec: Mapping[str, Any],
    toolchain_binding: str,
    generation: int,
    parent_spec_sha256: str | None = None,
) -> CreateDeltaPlanV2Permit:
    """Seal the exact already-admitted V2 plan and its immutable input spec."""

    _validate_plan_and_projection(plan, projection)
    base = _copy(base_spec, label="base spec")
    base_sha256 = _sha(base)
    _validate_mode_and_parent(
        plan, base_spec_sha256=base_sha256, parent_spec_sha256=parent_spec_sha256
    )
    body = _binding_body(
        plan,
        projection,
        toolchain_binding=toolchain_binding,
        generation=generation,
        base_spec_sha256=base_sha256,
        parent_spec_sha256=parent_spec_sha256,
    )
    binding_sha256 = _sha(body)
    permit_sha256 = _sha(
        {"contract_id": CREATE_DELTA_PLAN_V2_PERMIT_CONTRACT, "binding_sha256": binding_sha256}
    )
    return CreateDeltaPlanV2Permit(
        plan_sha256=body["plan_sha256"],
        context_revision=body["context_revision"],
        semantic_revision=body["semantic_revision"],
        surface_revision=body["surface_revision"],
        projection_revision=body["projection_revision"],
        toolchain_binding=body["toolchain_binding"],
        generation=body["generation"],
        target_ref=body["target_ref"],
        basis_ref=body["basis_ref"],
        base_spec_sha256=body["base_spec_sha256"],
        parent_spec_sha256=body["parent_spec_sha256"],
        binding_sha256=binding_sha256,
        permit_sha256=permit_sha256,
    )


class CreateDeltaPlanV2PermitConsumer:
    """Burn-before-validate, process-local one-shot authority consumer."""

    __slots__ = ("_lock", "_permit", "_retired")

    def __init__(self, permit: CreateDeltaPlanV2Permit) -> None:
        if not isinstance(permit, CreateDeltaPlanV2Permit):
            _fail("CREATE_V2_PERMIT_INVALID", "permit is invalid")
        if permit.contract_id != CREATE_DELTA_PLAN_V2_PERMIT_CONTRACT:
            _fail("CREATE_V2_PERMIT_INVALID", "permit contract differs")
        _hash(permit.plan_sha256, label="permit plan sha256")
        _hash(permit.context_revision, label="permit context revision")
        _hash(permit.semantic_revision, label="permit semantic revision")
        _hash(permit.surface_revision, label="permit surface revision")
        _hash(permit.projection_revision, label="permit projection revision")
        _hash(permit.toolchain_binding, label="permit toolchain binding")
        _hash(permit.base_spec_sha256, label="permit base spec sha256")
        if permit.parent_spec_sha256 is not None:
            _hash(permit.parent_spec_sha256, label="permit parent spec sha256")
        _generation(permit.generation)
        if not isinstance(permit.target_ref, str) or not permit.target_ref:
            _fail("CREATE_V2_PERMIT_INVALID", "permit target ref is invalid")
        body = {
            "plan_sha256": permit.plan_sha256,
            "context_revision": permit.context_revision,
            "semantic_revision": permit.semantic_revision,
            "surface_revision": permit.surface_revision,
            "projection_revision": permit.projection_revision,
            "toolchain_binding": permit.toolchain_binding,
            "generation": permit.generation,
            "target_ref": permit.target_ref,
            "basis_ref": permit.basis_ref,
            "base_spec_sha256": permit.base_spec_sha256,
            "parent_spec_sha256": permit.parent_spec_sha256,
        }
        if not hmac.compare_digest(_sha(body), permit.binding_sha256) or not hmac.compare_digest(
            _sha({"contract_id": permit.contract_id, "binding_sha256": permit.binding_sha256}),
            permit.permit_sha256,
        ):
            _fail("CREATE_V2_PERMIT_INVALID", "permit hashes differ")
        self._permit = permit
        self._lock = threading.Lock()
        self._retired = False

    def consume(
        self,
        plan: CreateDeltaPlanV2,
        projection: CompactAuthorityProjection,
        *,
        base_spec_sha256: str,
        toolchain_binding: str,
        generation: int,
        parent_spec_sha256: str | None,
    ) -> CreateDeltaPlanV2PermitReceipt:
        with self._lock:
            if self._retired:
                _fail("CREATE_V2_PERMIT_REPLAY", "permit was already consumed")
            self._retired = True
        _validate_plan_and_projection(plan, projection)
        _validate_mode_and_parent(
            plan, base_spec_sha256=base_spec_sha256, parent_spec_sha256=parent_spec_sha256
        )
        body = _binding_body(
            plan,
            projection,
            toolchain_binding=toolchain_binding,
            generation=generation,
            base_spec_sha256=base_spec_sha256,
            parent_spec_sha256=parent_spec_sha256,
        )
        permit = self._permit
        expected = {
            "plan_sha256": permit.plan_sha256,
            "context_revision": permit.context_revision,
            "semantic_revision": permit.semantic_revision,
            "surface_revision": permit.surface_revision,
            "projection_revision": permit.projection_revision,
            "toolchain_binding": permit.toolchain_binding,
            "generation": permit.generation,
            "target_ref": permit.target_ref,
            "basis_ref": permit.basis_ref,
            "base_spec_sha256": permit.base_spec_sha256,
            "parent_spec_sha256": permit.parent_spec_sha256,
        }
        if any(body[key] != value for key, value in expected.items()) or not hmac.compare_digest(
            _sha(body), permit.binding_sha256
        ):
            _fail("CREATE_V2_PERMIT_DRIFT", "permit binding differs")
        receipt_sha256 = _sha(
            {
                "contract_id": CREATE_DELTA_PLAN_V2_RECEIPT_CONTRACT,
                "permit_sha256": permit.permit_sha256,
                "binding_sha256": permit.binding_sha256,
            }
        )
        return CreateDeltaPlanV2PermitReceipt(
            permit_sha256=permit.permit_sha256,
            binding_sha256=permit.binding_sha256,
            receipt_sha256=receipt_sha256,
        )


def _node_evidence(node: NodeGrant) -> frozenset[str]:
    return frozenset(
        reference for binding in node.leaf_bindings for reference in binding.requirement_refs
    )


def _index_by_ref(
    index: CompactProjectionIndex,
) -> tuple[dict[str, SlotGrant], dict[str, NodeGrant], dict[str, int], dict[str, int]]:
    slots = {item.ref: item for item in index.slots_by_handle.values()}
    nodes = {item.ref: item for item in index.nodes_by_handle.values()}
    recipes = {item.ref: item.handle for item in index.recipes_by_handle.values()}
    rows = {item.ref: item.handle for item in index.rows_by_handle.values()}
    return slots, nodes, recipes, rows


def _validate_plan_and_projection(
    plan: CreateDeltaPlanV2, projection: CompactAuthorityProjection
) -> CompactProjectionIndex:
    if not isinstance(plan, CreateDeltaPlanV2):
        _fail("CREATE_V2_PLAN_INVALID", "plan is not admitted V2 authority")
    try:
        index = validate_compact_authority_projection(projection)
    except BrainError as error:
        _fail("CREATE_V2_PROJECTION_INVALID", "projection is invalid")
        raise AssertionError from error
    if (
        plan.surface_revision != projection.surface_revision
        or plan.projection_revision != projection.projection_revision
        or plan.contract_id != "metis-brain-create-delta-plan/v2"
        or plan.schema_version != 2
    ):
        _fail("CREATE_V2_PLAN_INVALID", "plan headers differ from projection")
    if not plan.operations or len(plan.operations) > 5:
        _fail("CREATE_V2_PLAN_INVALID", "operation roster is invalid")
    expected_requirements = set(plan.requirements)
    known_requirements = {item.ref for item in index.requirements_by_handle.values()}
    if not expected_requirements or not expected_requirements <= known_requirements:
        _fail("CREATE_V2_PLAN_INVALID", "plan requirements are invalid")
    if len(expected_requirements) != len(plan.requirements):
        _fail("CREATE_V2_PLAN_INVALID", "plan requirements are duplicated")
    for ordinal, operation in enumerate(plan.operations):
        if operation.ordinal != ordinal:
            _fail("CREATE_V2_PLAN_INVALID", "operation ordinals are not source ordered")
        refs = frozenset(operation.requirement_refs)
        if not refs or not refs <= expected_requirements:
            _fail("CREATE_V2_PLAN_INVALID", "operation requirements are invalid")
    if (
        set().union(*(set(item.requirement_refs) for item in plan.operations))
        != expected_requirements
    ):
        _fail("CREATE_V2_PLAN_INVALID", "operation coverage differs from plan requirements")
    return index


def _register_basis_nodes(
    root: Mapping[str, Any], index: CompactProjectionIndex, *, base_spec_sha256: str
) -> dict[str, Any]:
    registered: dict[str, Any] = {}
    for node in index.nodes_by_handle.values():
        if node.state != "basis":
            continue
        if node.basis_path is None or node.basis_spec_sha256 is None:
            _fail("CREATE_V2_LOCATOR_INVALID", "basis node lacks exact locator")
        if not hmac.compare_digest(node.basis_spec_sha256, base_spec_sha256):
            _fail("CREATE_V2_LOCATOR_DRIFT", "basis node spec hash differs")
        actual = _at(root, node.basis_path, label="basis node path")
        if not hmac.compare_digest(_sha(actual), node.fragment_sha256):
            _fail("CREATE_V2_LOCATOR_DRIFT", "basis node at exact path differs")
        registered[node.ref] = actual
    return registered


def _resolve_slot(
    slot: SlotGrant,
    *,
    root: Mapping[str, Any],
    target_ref: str,
    registered: Mapping[str, Any],
) -> tuple[dict[str, Any], str]:
    anchor = root if slot.anchor_ref == target_ref else registered.get(slot.anchor_ref)
    if not isinstance(anchor, dict):
        _fail("CREATE_V2_SLOT_INVALID", "slot anchor is absent or not a registered node")
    if slot.member not in anchor:
        _fail("CREATE_V2_SLOT_INVALID", "slot member is absent from its exact anchor")
    return anchor, slot.member


def _check_evidence(operation: CreateDeltaOperationV2, evidence: frozenset[str]) -> None:
    if frozenset(operation.requirement_refs) != evidence:
        _fail(
            "CREATE_V2_REQUIREMENT_MISMATCH",
            "operation requirements do not exactly bind leaf evidence",
        )


def _materialize_node(
    node: NodeGrant,
    nodes: Mapping[str, NodeGrant],
    *,
    substitutions: Sequence[Any] = (),
) -> Any:
    materialized = _copy(node.fragment, label="node fragment")
    for substitution in substitutions:
        try:
            axis = nodes[substitution.axis_ref]
            value = nodes[substitution.value_ref]
        except (AttributeError, KeyError) as error:
            _fail("CREATE_V2_EXPANSION_INVALID", "matrix substitution is not projected")
            raise AssertionError from error
        pointed = _at_json_pointer(
            materialized, substitution.json_pointer, label="matrix axis pointer"
        )
        if not hmac.compare_digest(_sha(pointed), axis.fragment_sha256):
            _fail("CREATE_V2_EXPANSION_INVALID", "matrix axis pointer differs from its exact axis")
        _replace_json_pointer(
            materialized,
            substitution.json_pointer,
            _copy(value.fragment, label="matrix value fragment"),
            label="matrix axis pointer",
        )
    return materialized


def _attach(
    slot: SlotGrant,
    node: NodeGrant,
    *,
    root: Mapping[str, Any],
    target_ref: str,
    registered: dict[str, Any],
    nodes: Mapping[str, NodeGrant],
    substitutions: Sequence[Any] = (),
    register: bool = True,
) -> None:
    if (
        slot.cardinality != "many"
        or slot.insertion != "append"
        or "attach" not in slot.mutations
        or node.state != "new"
        or node.parent_slot_ref != slot.ref
        or node.fragment_type not in slot.accepts
    ):
        _fail(
            "CREATE_V2_ATTACHMENT_INVALID",
            "attach is incompatible with its exact slot/node authority",
        )
    anchor, member = _resolve_slot(slot, root=root, target_ref=target_ref, registered=registered)
    collection = anchor[member]
    if not isinstance(collection, list):
        _fail("CREATE_V2_SLOT_INVALID", "append slot is not a list")
    if register and node.ref in registered:
        _fail("CREATE_V2_ATTACHMENT_INVALID", "new node reference was already materialized")
    materialized = _materialize_node(node, nodes, substitutions=substitutions)
    collection.append(materialized)
    if register:
        registered[node.ref] = materialized


def _set(
    slot: SlotGrant,
    node: NodeGrant,
    *,
    root: Mapping[str, Any],
    target_ref: str,
    registered: dict[str, Any],
    nodes: Mapping[str, NodeGrant],
) -> None:
    if (
        slot.cardinality != "one"
        or slot.insertion not in {"replace", "exact"}
        or "set" not in slot.mutations
        or node.state != "new"
        or node.parent_slot_ref != slot.ref
        or node.fragment_type not in slot.accepts
    ):
        _fail("CREATE_V2_SET_INVALID", "set is incompatible with its exact slot/value authority")
    anchor, member = _resolve_slot(slot, root=root, target_ref=target_ref, registered=registered)
    if node.ref in registered:
        _fail("CREATE_V2_SET_INVALID", "new value reference was already materialized")
    materialized = _materialize_node(node, nodes)
    anchor[member] = materialized
    registered[node.ref] = materialized


def _remove(
    node: NodeGrant,
    *,
    root: Mapping[str, Any],
    registered: Mapping[str, Any],
    slots: Mapping[str, SlotGrant],
    target_ref: str,
) -> None:
    if node.state != "basis" or not node.removable or node.basis_path is None:
        _fail("CREATE_V2_REMOVE_INVALID", "remove may target only a removable basis node")
    actual = _at(root, node.basis_path, label="basis node path")
    if registered.get(node.ref) is not actual or not hmac.compare_digest(
        _sha(actual), node.fragment_sha256
    ):
        _fail("CREATE_V2_LOCATOR_DRIFT", "basis node locator drifted")
    if node.parent_slot_ref is None or node.parent_slot_ref not in slots:
        _fail("CREATE_V2_REMOVE_INVALID", "basis node lacks exact parent slot")
    slot = slots[node.parent_slot_ref]
    anchor, member = _resolve_slot(slot, root=root, target_ref=target_ref, registered=registered)
    container = anchor[member]
    if isinstance(container, list):
        if not any(item is actual for item in container):
            _fail("CREATE_V2_LOCATOR_DRIFT", "basis node is not in its exact parent slot")
    elif anchor.get(member) is not actual:
        _fail("CREATE_V2_LOCATOR_DRIFT", "basis node is not in its exact parent slot")
    _remove_at(root, node.basis_path, label="basis node path")


def _operation_json(plan: CreateDeltaPlanV2) -> tuple[dict[str, Any], ...]:
    body = plan.internal_json()["body"]["o"]
    if not isinstance(body, list):
        _fail("CREATE_V2_PLAN_INVALID", "internal operation body is invalid")
    return tuple(body)


def execute_create_delta_plan_v2(
    plan: CreateDeltaPlanV2,
    projection: CompactAuthorityProjection,
    *,
    base_spec: Mapping[str, Any],
    parent_spec_sha256: str | None,
    permit_consumer: CreateDeltaPlanV2PermitConsumer,
    toolchain_binding: str,
    generation: int,
) -> CreateDeltaPlanV2Execution:
    """Burn an exact permit then apply only its admitted V2 operations."""

    base = _copy(base_spec, label="base spec")
    if not isinstance(base, dict) or not isinstance(base.get("endpoint"), dict):
        _fail("CREATE_V2_SPEC_INVALID", "base spec does not contain a detached endpoint object")
    base_sha256 = _sha(base)
    receipt = permit_consumer.consume(
        plan,
        projection,
        base_spec_sha256=base_sha256,
        toolchain_binding=toolchain_binding,
        generation=generation,
        parent_spec_sha256=parent_spec_sha256,
    )
    index = _validate_plan_and_projection(plan, projection)
    root = base["endpoint"]
    registered = _register_basis_nodes(root, index, base_spec_sha256=base_sha256)
    slots, nodes, recipe_handles, row_handles = _index_by_ref(index)
    emissions = 0
    operation_hashes: list[str] = []

    for operation, operation_json in zip(plan.operations, _operation_json(plan), strict=True):
        operation_hashes.append(_sha(operation_json))
        if isinstance(operation, AttachOpV2):
            slot = slots.get(operation.slot_ref)
            node = nodes.get(operation.node_ref)
            if slot is None or node is None:
                _fail("CREATE_V2_PLAN_INVALID", "attach reference is not projected")
            _check_evidence(operation, _node_evidence(node))
            _attach(
                slot,
                node,
                root=root,
                target_ref=plan.target_ref,
                registered=registered,
                nodes=nodes,
            )
            emissions += 1
        elif isinstance(operation, SetOpV2):
            slot = slots.get(operation.slot_ref)
            node = nodes.get(operation.value_ref)
            if slot is None or node is None:
                _fail("CREATE_V2_PLAN_INVALID", "set reference is not projected")
            _check_evidence(operation, _node_evidence(node))
            _set(
                slot,
                node,
                root=root,
                target_ref=plan.target_ref,
                registered=registered,
                nodes=nodes,
            )
            emissions += 1
        elif isinstance(operation, RemoveOpV2):
            node = nodes.get(operation.node_ref)
            if node is None:
                _fail("CREATE_V2_PLAN_INVALID", "remove reference is not projected")
            _check_evidence(operation, _node_evidence(node))
            _remove(
                node,
                root=root,
                registered=registered,
                slots=slots,
                target_ref=plan.target_ref,
            )
            emissions += 1
        elif isinstance(operation, ExpandOpV2):
            if operation.slot_ref not in slots or operation.recipe_ref not in recipe_handles:
                _fail("CREATE_V2_PLAN_INVALID", "expand slot or recipe is not projected")
            if any(reference not in row_handles for reference in operation.row_refs):
                _fail("CREATE_V2_PLAN_INVALID", "expand row is not projected")
            try:
                result = execute_combinator(
                    projection,
                    slot_handle=slots[operation.slot_ref].handle,
                    recipe_handle=recipe_handles[operation.recipe_ref],
                    row_handles=tuple(row_handles[reference] for reference in operation.row_refs),
                )
            except BrainError as error:
                _fail("CREATE_V2_EXPANSION_INVALID", str(error))
                raise AssertionError from error
            _check_evidence(
                operation,
                result.requirement_refs,
            )
            for emission in result.emissions:
                if emissions >= MAX_EXECUTION_EMISSIONS:
                    _fail("CREATE_V2_EXECUTION_LIMIT", "expansion exceeds its mutation bound")
                if isinstance(emission, AttachEmission):
                    slot = slots.get(emission.target_slot_ref)
                    node = nodes.get(emission.node_ref)
                    if slot is None or node is None:
                        _fail("CREATE_V2_EXPANSION_INVALID", "attach emission is not projected")
                    _attach(
                        slot,
                        node,
                        root=root,
                        target_ref=plan.target_ref,
                        registered=registered,
                        nodes=nodes,
                        substitutions=emission.substitutions,
                    )
                    emissions += 1
                elif isinstance(emission, SetEmission):
                    slot = slots.get(emission.target_slot_ref)
                    node = nodes.get(emission.value_ref)
                    if slot is None or node is None:
                        _fail("CREATE_V2_EXPANSION_INVALID", "set emission is not projected")
                    _set(
                        slot,
                        node,
                        root=root,
                        target_ref=plan.target_ref,
                        registered=registered,
                        nodes=nodes,
                    )
                    emissions += 1
                elif isinstance(emission, QuotaEmission):
                    slot = slots.get(emission.target_slot_ref)
                    node = nodes.get(emission.node_ref)
                    if slot is None or node is None:
                        _fail("CREATE_V2_EXPANSION_INVALID", "quota emission is not projected")
                    has_child_slot = any(child.anchor_ref == node.ref for child in slots.values())
                    if emission.occurrences > 1 and has_child_slot:
                        _fail(
                            "CREATE_V2_EXPANSION_INVALID",
                            "repeated quota prototype cannot anchor a child slot",
                        )
                    for copy_number in range(emission.occurrences):
                        if emissions >= MAX_EXECUTION_EMISSIONS:
                            _fail(
                                "CREATE_V2_EXECUTION_LIMIT", "expansion exceeds its mutation bound"
                            )
                        _attach(
                            slot,
                            node,
                            root=root,
                            target_ref=plan.target_ref,
                            registered=registered,
                            nodes=nodes,
                            register=copy_number == 0 and emission.occurrences == 1,
                        )
                        emissions += 1
                else:
                    _fail("CREATE_V2_EXPANSION_INVALID", "unknown combinator emission")
        else:
            _fail("CREATE_V2_PLAN_INVALID", "operation type is unknown")

    detached = _copy(base, label="detached execution spec")
    proof = CreateDeltaPlanV2ProofInput(
        plan_sha256=_sha(plan.internal_json()),
        projection_revision=plan.projection_revision,
        surface_revision=plan.surface_revision,
        context_revision=plan.context_revision,
        semantic_revision=plan.semantic_revision,
        toolchain_binding=_hash(toolchain_binding, label="toolchain binding"),
        generation=_generation(generation),
        target_ref=plan.target_ref,
        basis_ref=plan.basis_ref,
        base_spec_sha256=base_sha256,
        parent_spec_sha256=parent_spec_sha256,
        operation_sha256=tuple(operation_hashes),
        emitted_mutations=emissions,
        receipt=receipt,
    )
    return CreateDeltaPlanV2Execution(spec=detached, spec_sha256=_sha(detached), proof_input=proof)


__all__ = [
    "CREATE_DELTA_PLAN_V2_EXECUTION_CONTRACT",
    "CREATE_DELTA_PLAN_V2_PERMIT_CONTRACT",
    "CREATE_DELTA_PLAN_V2_RECEIPT_CONTRACT",
    "CreateDeltaPlanV2Execution",
    "CreateDeltaPlanV2ExecutionError",
    "CreateDeltaPlanV2Permit",
    "CreateDeltaPlanV2PermitConsumer",
    "CreateDeltaPlanV2PermitReceipt",
    "CreateDeltaPlanV2ProofInput",
    "execute_create_delta_plan_v2",
    "issue_create_delta_plan_v2_permit",
]
