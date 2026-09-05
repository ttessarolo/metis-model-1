"""Private, one-shot authority for a future ``CreateDeltaPlan``.

This module seals only digests and opaque, role-typed host references.  It has
no serializer and deliberately carries no Metis source, path, compiler IR,
outline, plan, grants, user text or operation payload.  Trusted host code keeps
those values in a separate private registry and may use an authorized operation
seal only after the complete current binding has been compared with the issued
binding.

Consumption is burn-before-read: the first attempt retires the permit while
holding a lock, before timestamps, bindings or the consumption envelope are
validated.  Malformed, stale and expired first attempts therefore cannot turn
the permit into an oracle over private authority.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

CREATE_PERMIT_CONTRACT = "metis-brain-create-permit/v1"
CREATE_CONSUMPTION_CONTRACT = "metis-brain-create-consumption/v1"
CREATE_RECEIPT_CONTRACT = "metis-brain-create-receipt/v1"

# The measured hard-prompt corpus peaks at 451 predicate nodes, 428 clauses,
# 32 fetches and 16 containers in one endpoint.  1024 is the smallest round
# conservative outer envelope that can seal a fully expanded operation roster
# without conflating it with the much smaller per-family maxima.
MAX_CREATE_OPERATIONS = 1024
MAX_CREATE_PERMIT_TTL_MS = 20 * 60 * 1000
MAX_TIMESTAMP_MS = (1 << 63) - 1
MAX_CONVERSATION_GENERATION = (1 << 31) - 1

SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HOST_REF_RE = re.compile(
    r"^hostref:(permit|nonce|target|parent_proposal|operation):[0-9a-f]{32,64}$"
)
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{32,96}$")
TURN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{24,96}$")
CONVERSATION_ID_RE = re.compile(r"^(?:sha256:[0-9a-f]{64}|[A-Za-z0-9][A-Za-z0-9_-]{31,127})$")

ReferenceRole = Literal["permit", "nonce", "target", "parent_proposal", "operation"]

REFERENCE_ROLES: frozenset[str] = frozenset(
    {"permit", "nonce", "target", "parent_proposal", "operation"}
)

_BINDING_FIELDS = frozenset(
    {
        "session_id",
        "turn_id",
        "request_sha256",
        "instruction_sha256",
        "context_revision",
        "semantic_source_revision",
        "toolchain_binding",
        "target_ref",
        "target_sha256",
        "conversation_id",
        "conversation_generation",
        "parent_proposal_ref",
        "parent_proposal_sha256",
        "parent_source_sha256",
        "parent_manifest_sha256",
        "parent_ir_sha256",
        "outline_sha256",
        "plan_sha256",
        "grants_sha256",
    }
)
_PERMIT_FIELDS = frozenset(
    {
        "schema_version",
        "contract_id",
        "permit_id",
        "nonce",
        "issued_at_ms",
        "expires_at_ms",
        "binding",
        "operation_seals",
    }
)
_OPERATION_SEAL_FIELDS = frozenset({"ordinal", "operation_ref", "operation_sha256"})
_CONSUMPTION_FIELDS = frozenset(
    {
        "schema_version",
        "contract_id",
        "permit_id",
        "nonce",
        "permit_sha256",
        "operation_seals",
    }
)


class CreatePermitError(ValueError):
    """One deterministic failure of the private CREATE authority contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise CreatePermitError(code, message)


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CreatePermitError("CREATE_PERMIT_INVALID", "value is not canonical JSON") from error


def _canonical_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _exact_fields(value: Any, expected: frozenset[str], *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        _fail("CREATE_PERMIT_INVALID", f"{label} has an invalid field roster")
    return value


def _sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        _fail("CREATE_PERMIT_INVALID", f"{label} is not an exact sha256 reference")
    return value


def _host_ref(value: Any, *, role: ReferenceRole, label: str) -> str:
    if not isinstance(value, str) or HOST_REF_RE.fullmatch(value) is None:
        _fail("CREATE_PERMIT_INVALID", f"{label} is not an exact host reference")
    if not value.startswith(f"hostref:{role}:"):
        _fail("CREATE_PERMIT_ROLE_MISMATCH", f"{label} has the wrong reference role")
    return value


def _timestamp(value: Any, *, label: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_TIMESTAMP_MS:
        _fail("CREATE_PERMIT_INVALID", f"{label} is invalid")
    return value


@dataclass(frozen=True, slots=True, repr=False)
class CreateBinding:
    """Complete private authority snapshot for one CREATE/refinement turn."""

    session_id: str
    turn_id: str
    request_sha256: str
    instruction_sha256: str
    context_revision: str
    semantic_source_revision: str
    toolchain_binding: str
    target_ref: str
    target_sha256: str
    conversation_id: str
    conversation_generation: int
    parent_proposal_ref: str | None
    parent_proposal_sha256: str | None
    parent_source_sha256: str | None
    parent_manifest_sha256: str | None
    parent_ir_sha256: str | None
    outline_sha256: str
    plan_sha256: str
    grants_sha256: str


@dataclass(frozen=True, slots=True, repr=False)
class CreateOperationSeal:
    """Opaque registry handle plus the digest of one exact plan operation."""

    ordinal: int
    operation_ref: str
    operation_sha256: str


@dataclass(frozen=True, slots=True, repr=False)
class CreatePermit:
    """Immutable private permit; intentionally has no payload serializer."""

    permit_id: str
    nonce: str
    issued_at_ms: int
    expires_at_ms: int
    binding: CreateBinding
    operation_seals: tuple[CreateOperationSeal, ...]
    reference_roles_sha256: str
    binding_sha256: str
    operations_sha256: str
    permit_sha256: str


@dataclass(frozen=True, slots=True, repr=False)
class CreatePermitReceipt:
    """Hash-only proof that one exact permit and operation roster was consumed."""

    permit_sha256: str
    consumption_sha256: str
    binding_sha256: str
    operations_sha256: str
    receipt_sha256: str


@dataclass(frozen=True, slots=True, repr=False)
class AuthorizedCreatePlan:
    """Private handoff to a future registry-backed deterministic renderer."""

    operation_seals: tuple[CreateOperationSeal, ...]
    receipt: CreatePermitReceipt


def _binding_body(binding: CreateBinding) -> dict[str, Any]:
    return {
        "session_id": binding.session_id,
        "turn_id": binding.turn_id,
        "request_sha256": binding.request_sha256,
        "instruction_sha256": binding.instruction_sha256,
        "context_revision": binding.context_revision,
        "semantic_source_revision": binding.semantic_source_revision,
        "toolchain_binding": binding.toolchain_binding,
        "target_ref": binding.target_ref,
        "target_sha256": binding.target_sha256,
        "conversation_id": binding.conversation_id,
        "conversation_generation": binding.conversation_generation,
        "parent_proposal_ref": binding.parent_proposal_ref,
        "parent_proposal_sha256": binding.parent_proposal_sha256,
        "parent_source_sha256": binding.parent_source_sha256,
        "parent_manifest_sha256": binding.parent_manifest_sha256,
        "parent_ir_sha256": binding.parent_ir_sha256,
        "outline_sha256": binding.outline_sha256,
        "plan_sha256": binding.plan_sha256,
        "grants_sha256": binding.grants_sha256,
    }


def _operation_body(operation: CreateOperationSeal) -> dict[str, Any]:
    return {
        "ordinal": operation.ordinal,
        "operation_ref": operation.operation_ref,
        "operation_sha256": operation.operation_sha256,
    }


def _parse_binding(value: Any) -> CreateBinding:
    item = _exact_fields(value, _BINDING_FIELDS, label="create binding")
    session_id = item["session_id"]
    turn_id = item["turn_id"]
    conversation_id = item["conversation_id"]
    generation = item["conversation_generation"]
    if not isinstance(session_id, str) or SESSION_ID_RE.fullmatch(session_id) is None:
        _fail("CREATE_PERMIT_INVALID", "session_id is invalid")
    if not isinstance(turn_id, str) or TURN_ID_RE.fullmatch(turn_id) is None:
        _fail("CREATE_PERMIT_INVALID", "turn_id is invalid")
    if (
        not isinstance(conversation_id, str)
        or CONVERSATION_ID_RE.fullmatch(conversation_id) is None
    ):
        _fail("CREATE_PERMIT_INVALID", "conversation_id is invalid")
    if type(generation) is not int or not 0 <= generation <= MAX_CONVERSATION_GENERATION:
        _fail("CREATE_PERMIT_INVALID", "conversation_generation is invalid")

    parent_values = (
        item["parent_proposal_ref"],
        item["parent_proposal_sha256"],
        item["parent_source_sha256"],
        item["parent_manifest_sha256"],
        item["parent_ir_sha256"],
    )
    if any(member is None for member in parent_values) and not all(
        member is None for member in parent_values
    ):
        _fail(
            "CREATE_PERMIT_INVALID",
            "parent proposal, source, manifest and IR authority must be present together",
        )
    parent_ref = (
        None
        if parent_values[0] is None
        else _host_ref(parent_values[0], role="parent_proposal", label="parent_proposal_ref")
    )
    parent_hashes = tuple(
        None if member is None else _sha256(member, label=label)
        for member, label in zip(
            parent_values[1:],
            (
                "parent_proposal_sha256",
                "parent_source_sha256",
                "parent_manifest_sha256",
                "parent_ir_sha256",
            ),
            strict=True,
        )
    )
    return CreateBinding(
        session_id=session_id,
        turn_id=turn_id,
        request_sha256=_sha256(item["request_sha256"], label="request_sha256"),
        instruction_sha256=_sha256(item["instruction_sha256"], label="instruction_sha256"),
        context_revision=_sha256(item["context_revision"], label="context_revision"),
        semantic_source_revision=_sha256(
            item["semantic_source_revision"], label="semantic_source_revision"
        ),
        toolchain_binding=_sha256(item["toolchain_binding"], label="toolchain_binding"),
        target_ref=_host_ref(item["target_ref"], role="target", label="target_ref"),
        target_sha256=_sha256(item["target_sha256"], label="target_sha256"),
        conversation_id=conversation_id,
        conversation_generation=generation,
        parent_proposal_ref=parent_ref,
        parent_proposal_sha256=parent_hashes[0],
        parent_source_sha256=parent_hashes[1],
        parent_manifest_sha256=parent_hashes[2],
        parent_ir_sha256=parent_hashes[3],
        outline_sha256=_sha256(item["outline_sha256"], label="outline_sha256"),
        plan_sha256=_sha256(item["plan_sha256"], label="plan_sha256"),
        grants_sha256=_sha256(item["grants_sha256"], label="grants_sha256"),
    )


def _parse_operation_seals(value: Any) -> tuple[CreateOperationSeal, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not 1 <= len(value) <= MAX_CREATE_OPERATIONS
    ):
        _fail(
            "CREATE_PERMIT_INVALID",
            f"operation seals must contain between 1 and {MAX_CREATE_OPERATIONS} items",
        )
    result: list[CreateOperationSeal] = []
    refs: list[str] = []
    for expected_ordinal, raw in enumerate(value):
        item = _exact_fields(raw, _OPERATION_SEAL_FIELDS, label="create operation seal")
        ordinal = item["ordinal"]
        if type(ordinal) is not int or ordinal != expected_ordinal:
            _fail(
                "CREATE_PERMIT_INVALID",
                "operation seals must have contiguous source-order ordinals",
            )
        operation_ref = _host_ref(item["operation_ref"], role="operation", label="operation_ref")
        refs.append(operation_ref)
        result.append(
            CreateOperationSeal(
                ordinal=ordinal,
                operation_ref=operation_ref,
                operation_sha256=_sha256(item["operation_sha256"], label="operation_sha256"),
            )
        )
    if len(refs) != len(set(refs)):
        _fail("CREATE_PERMIT_INVALID", "operation seals contain duplicate references")
    return tuple(result)


def _used_reference_roles(
    *,
    permit_id: str,
    nonce: str,
    binding: CreateBinding,
    operation_seals: tuple[CreateOperationSeal, ...],
) -> dict[str, ReferenceRole]:
    result: dict[str, ReferenceRole] = {
        permit_id: "permit",
        nonce: "nonce",
        binding.target_ref: "target",
    }
    if binding.parent_proposal_ref is not None:
        result[binding.parent_proposal_ref] = "parent_proposal"
    for operation in operation_seals:
        result[operation.operation_ref] = "operation"
    return result


def _validate_reference_roles(
    expected: Mapping[str, ReferenceRole], issued_ref_roles: Mapping[str, Any]
) -> str:
    if not isinstance(issued_ref_roles, Mapping):
        _fail("CREATE_PERMIT_INVALID", "issued reference roles are invalid")
    if set(issued_ref_roles) != set(expected):
        _fail("CREATE_PERMIT_ROLE_MISMATCH", "issued reference role roster differs")
    for ref, role in expected.items():
        if issued_ref_roles.get(ref) != role:
            _fail("CREATE_PERMIT_ROLE_MISMATCH", "issued reference role differs")
    return _canonical_sha256([{"ref": ref, "role": expected[ref]} for ref in sorted(expected)])


def _permit_body(permit: CreatePermit) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contract_id": CREATE_PERMIT_CONTRACT,
        "permit_id": permit.permit_id,
        "nonce": permit.nonce,
        "issued_at_ms": permit.issued_at_ms,
        "expires_at_ms": permit.expires_at_ms,
        "binding": _binding_body(permit.binding),
        "operation_seals": [_operation_body(item) for item in permit.operation_seals],
        "reference_roles_sha256": permit.reference_roles_sha256,
        "binding_sha256": permit.binding_sha256,
        "operations_sha256": permit.operations_sha256,
    }


def canonical_create_permit_sha256(permit: CreatePermit) -> str:
    """Recompute the deterministic seal without exposing a permit payload."""

    if type(permit) is not CreatePermit:
        _fail("CREATE_PERMIT_INVALID", "create permit type is invalid")
    return _canonical_sha256(_permit_body(permit))


def issue_create_permit(
    value: Any,
    *,
    issued_ref_roles: Mapping[str, Any],
) -> CreatePermit:
    """Validate and seal one trusted-host, pre-render CREATE capability."""

    item = _exact_fields(value, _PERMIT_FIELDS, label="create permit")
    if (
        type(item["schema_version"]) is not int
        or item["schema_version"] != 1
        or item["contract_id"] != CREATE_PERMIT_CONTRACT
    ):
        _fail("CREATE_PERMIT_INVALID", "create permit contract is unsupported")
    permit_id = _host_ref(item["permit_id"], role="permit", label="permit_id")
    nonce = _host_ref(item["nonce"], role="nonce", label="nonce")
    issued_at_ms = _timestamp(item["issued_at_ms"], label="issued_at_ms")
    expires_at_ms = _timestamp(item["expires_at_ms"], label="expires_at_ms")
    if not 1 <= expires_at_ms - issued_at_ms <= MAX_CREATE_PERMIT_TTL_MS:
        _fail("CREATE_PERMIT_INVALID", "create permit expiry is outside its bound")
    binding = _parse_binding(item["binding"])
    operation_seals = _parse_operation_seals(item["operation_seals"])
    expected_roles = _used_reference_roles(
        permit_id=permit_id,
        nonce=nonce,
        binding=binding,
        operation_seals=operation_seals,
    )
    expected_count = 3 + (binding.parent_proposal_ref is not None) + len(operation_seals)
    if len(expected_roles) != expected_count:
        _fail("CREATE_PERMIT_INVALID", "create permit contains duplicate references")
    roles_sha256 = _validate_reference_roles(expected_roles, issued_ref_roles)
    binding_sha256 = _canonical_sha256(_binding_body(binding))
    operations_sha256 = _canonical_sha256(
        [_operation_body(operation) for operation in operation_seals]
    )
    provisional = CreatePermit(
        permit_id=permit_id,
        nonce=nonce,
        issued_at_ms=issued_at_ms,
        expires_at_ms=expires_at_ms,
        binding=binding,
        operation_seals=operation_seals,
        reference_roles_sha256=roles_sha256,
        binding_sha256=binding_sha256,
        operations_sha256=operations_sha256,
        permit_sha256="",
    )
    permit_sha256 = canonical_create_permit_sha256(provisional)
    return CreatePermit(
        permit_id=permit_id,
        nonce=nonce,
        issued_at_ms=issued_at_ms,
        expires_at_ms=expires_at_ms,
        binding=binding,
        operation_seals=operation_seals,
        reference_roles_sha256=roles_sha256,
        binding_sha256=binding_sha256,
        operations_sha256=operations_sha256,
        permit_sha256=permit_sha256,
    )


def _parse_consumption(
    value: Any,
) -> tuple[str, str, str, tuple[CreateOperationSeal, ...]]:
    item = _exact_fields(value, _CONSUMPTION_FIELDS, label="create consumption")
    if (
        type(item["schema_version"]) is not int
        or item["schema_version"] != 1
        or item["contract_id"] != CREATE_CONSUMPTION_CONTRACT
    ):
        _fail("CREATE_PERMIT_INVALID", "create consumption contract is unsupported")
    return (
        _host_ref(item["permit_id"], role="permit", label="permit_id"),
        _host_ref(item["nonce"], role="nonce", label="nonce"),
        _sha256(item["permit_sha256"], label="permit_sha256"),
        _parse_operation_seals(item["operation_seals"]),
    )


def _receipt_body(receipt: CreatePermitReceipt) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contract_id": CREATE_RECEIPT_CONTRACT,
        "permit_sha256": receipt.permit_sha256,
        "consumption_sha256": receipt.consumption_sha256,
        "binding_sha256": receipt.binding_sha256,
        "operations_sha256": receipt.operations_sha256,
    }


def canonical_create_receipt_sha256(receipt: CreatePermitReceipt) -> str:
    """Recompute the hash-only receipt seal."""

    if type(receipt) is not CreatePermitReceipt:
        _fail("CREATE_PERMIT_INVALID", "create receipt type is invalid")
    return _canonical_sha256(_receipt_body(receipt))


def _validate_sealed_permit(
    permit: Any,
    *,
    issued_ref_roles: Mapping[str, Any],
) -> CreatePermit:
    if type(permit) is not CreatePermit:
        _fail("CREATE_PERMIT_INVALID", "create permit type is invalid")
    if (
        type(permit.binding) is not CreateBinding
        or type(permit.operation_seals) is not tuple
        or any(type(operation) is not CreateOperationSeal for operation in permit.operation_seals)
    ):
        _fail("CREATE_PERMIT_INVALID", "create permit members are invalid")
    _host_ref(permit.permit_id, role="permit", label="permit_id")
    _host_ref(permit.nonce, role="nonce", label="nonce")
    issued_at_ms = _timestamp(permit.issued_at_ms, label="issued_at_ms")
    expires_at_ms = _timestamp(permit.expires_at_ms, label="expires_at_ms")
    if not 1 <= expires_at_ms - issued_at_ms <= MAX_CREATE_PERMIT_TTL_MS:
        _fail("CREATE_PERMIT_INVALID", "create permit expiry is outside its bound")
    if _parse_binding(_binding_body(permit.binding)) != permit.binding:
        _fail("CREATE_PERMIT_INVALID", "create permit binding is invalid")
    parsed_operations = _parse_operation_seals(
        [_operation_body(operation) for operation in permit.operation_seals]
    )
    if parsed_operations != permit.operation_seals:
        _fail("CREATE_PERMIT_INVALID", "create permit operations are invalid")
    binding_sha256 = _canonical_sha256(_binding_body(permit.binding))
    operations_sha256 = _canonical_sha256(
        [_operation_body(operation) for operation in permit.operation_seals]
    )
    if permit.binding_sha256 != binding_sha256:
        _fail("CREATE_PERMIT_INVALID", "create permit binding seal differs")
    if permit.operations_sha256 != operations_sha256:
        _fail("CREATE_PERMIT_INVALID", "create permit operation seal differs")
    roles = _used_reference_roles(
        permit_id=permit.permit_id,
        nonce=permit.nonce,
        binding=permit.binding,
        operation_seals=permit.operation_seals,
    )
    role_sha256 = _validate_reference_roles(roles, issued_ref_roles)
    if role_sha256 != permit.reference_roles_sha256:
        _fail("CREATE_PERMIT_ROLE_MISMATCH", "create permit role roster drifted")
    _sha256(permit.permit_sha256, label="permit_sha256")
    if canonical_create_permit_sha256(permit) != permit.permit_sha256:
        _fail("CREATE_PERMIT_INVALID", "create permit seal differs")
    return permit


class CreatePermitConsumer:
    """Atomic single-use consumer for one private CREATE permit."""

    __slots__ = ("_lock", "_permit", "_retired")

    def __init__(
        self,
        permit: CreatePermit,
        *,
        issued_ref_roles: Mapping[str, Any],
    ) -> None:
        self._permit = _validate_sealed_permit(permit, issued_ref_roles=issued_ref_roles)
        self._lock = threading.Lock()
        self._retired = False

    def consume(
        self,
        value: Any,
        *,
        current_binding: Any,
        now_ms: int,
    ) -> AuthorizedCreatePlan:
        """Burn the permit, then validate time, current binding and operation seals."""

        with self._lock:
            if self._retired:
                _fail("CREATE_PERMIT_REPLAY", "create permit was already consumed")
            self._retired = True
        now = _timestamp(now_ms, label="now_ms")
        permit = self._permit
        if now < permit.issued_at_ms:
            _fail("CREATE_PERMIT_DRIFT", "create permit clock precedes issuance")
        if now >= permit.expires_at_ms:
            _fail("CREATE_PERMIT_EXPIRED", "create permit has expired")
        binding = _parse_binding(current_binding)
        if binding != permit.binding:
            _fail("CREATE_PERMIT_DRIFT", "create permit binding differs")
        permit_id, nonce, permit_sha256, operation_seals = _parse_consumption(value)
        if (
            permit_id != permit.permit_id
            or nonce != permit.nonce
            or permit_sha256 != permit.permit_sha256
        ):
            _fail("CREATE_PERMIT_DRIFT", "create permit identity differs")
        if operation_seals != permit.operation_seals:
            _fail("CREATE_PERMIT_DRIFT", "create permit operation seals differ")
        consumption_sha256 = _canonical_sha256(
            {
                "schema_version": 1,
                "contract_id": CREATE_CONSUMPTION_CONTRACT,
                "permit_id": permit_id,
                "nonce": nonce,
                "permit_sha256": permit_sha256,
                "operation_seals": [_operation_body(item) for item in operation_seals],
            }
        )
        provisional = CreatePermitReceipt(
            permit_sha256=permit.permit_sha256,
            consumption_sha256=consumption_sha256,
            binding_sha256=permit.binding_sha256,
            operations_sha256=permit.operations_sha256,
            receipt_sha256="",
        )
        receipt = CreatePermitReceipt(
            permit_sha256=provisional.permit_sha256,
            consumption_sha256=provisional.consumption_sha256,
            binding_sha256=provisional.binding_sha256,
            operations_sha256=provisional.operations_sha256,
            receipt_sha256=canonical_create_receipt_sha256(provisional),
        )
        return AuthorizedCreatePlan(operation_seals=operation_seals, receipt=receipt)


__all__ = [
    "CREATE_CONSUMPTION_CONTRACT",
    "CREATE_PERMIT_CONTRACT",
    "CREATE_RECEIPT_CONTRACT",
    "HOST_REF_RE",
    "MAX_CONVERSATION_GENERATION",
    "MAX_CREATE_OPERATIONS",
    "MAX_CREATE_PERMIT_TTL_MS",
    "REFERENCE_ROLES",
    "SHA256_RE",
    "AuthorizedCreatePlan",
    "CreateBinding",
    "CreateOperationSeal",
    "CreatePermit",
    "CreatePermitConsumer",
    "CreatePermitError",
    "CreatePermitReceipt",
    "canonical_create_permit_sha256",
    "canonical_create_receipt_sha256",
    "issue_create_permit",
]
