"""Private, pre-candidate ``DeltaPermit`` v1 contract.

The permit is a server-owned capability, not a client or model payload.  It is
issued *before* candidate generation and authorizes only an exact ordered set
of scalar replacements over opaque host references.  The permit binds the
session, turn, request, instruction, tenant snapshot, source, stable target,
optional basis, edit surface, reference roles, expiry and every operation.

This module deliberately exposes no JSON/client serializer and carries no raw
Metis source, compiler IR, semantic value, target path or operator text.  A
caller may feed the returned :class:`AuthorizedDelta` only to a private renderer
or compiler adapter.  The single :class:`DeltaPermitTranslator` instance is the
replay guard: its first consume attempt retires the capability atomically,
including when that attempt is malformed, stale or expired.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

DELTA_PERMIT_CONTRACT = "metis-brain-delta-permit/v1"
DELTA_CONSUMPTION_CONTRACT = "metis-brain-delta-consumption/v1"
DELTA_RECEIPT_CONTRACT = "metis-brain-delta-receipt/v1"

MAX_OPERATIONS = 32
MAX_PERMIT_TTL_MS = 20 * 60 * 1000
MAX_TIMESTAMP_MS = (1 << 63) - 1

SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HOST_REF_RE = re.compile(
    r"^hostref:(permit|nonce|target|basis|surface|value|evidence|block_argument_authority):"
    r"[0-9a-f]{32,64}$"
)
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_-]{32,96}$")
TURN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{24,96}$")

ReferenceRole = Literal[
    "permit",
    "nonce",
    "target",
    "basis",
    "surface",
    "value",
    "evidence",
    "block_argument_authority",
]
DeltaPrimitive = Literal[
    "take_cardinality",
    "output_limit",
    "display_label_or_title",
    "block_argument_list",
]

REFERENCE_ROLES: frozenset[str] = frozenset(
    {
        "permit",
        "nonce",
        "target",
        "basis",
        "surface",
        "value",
        "evidence",
        "block_argument_authority",
    }
)
DELTA_PRIMITIVES: frozenset[str] = frozenset(
    {
        "take_cardinality",
        "output_limit",
        "display_label_or_title",
        "block_argument_list",
    }
)

_BINDING_FIELDS = frozenset(
    {
        "session_id",
        "turn_id",
        "request_sha256",
        "instruction_sha256",
        "tenant_snapshot_revision",
        "source_sha256",
        "target_ref",
        "target_identity_sha256",
        "basis_ref",
        "basis_sha256",
        "edit_surface_sha256",
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
        "operations",
    }
)
_OPERATION_FIELDS = frozenset(
    {
        "ordinal",
        "kind",
        "primitive",
        "surface_ref",
        "value_ref",
        "evidence_ref",
        "authority_grant_ref",
    }
)
_CONSUMPTION_FIELDS = frozenset(
    {
        "schema_version",
        "contract_id",
        "permit_id",
        "nonce",
        "permit_sha256",
        "operations",
    }
)


class DeltaPermitError(ValueError):
    """One deterministic, private contract failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise DeltaPermitError(code, message)


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
        raise DeltaPermitError("DELTA_PERMIT_INVALID", "value is not canonical JSON") from error


def _canonical_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_json(value)).hexdigest()


def _exact_fields(value: Any, expected: frozenset[str], *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != expected:
        _fail("DELTA_PERMIT_INVALID", f"{label} has an invalid field roster")
    return value


def _sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        _fail("DELTA_PERMIT_INVALID", f"{label} is not an exact sha256 reference")
    return value


def _host_ref(value: Any, *, role: ReferenceRole, label: str) -> str:
    if not isinstance(value, str) or HOST_REF_RE.fullmatch(value) is None:
        _fail("DELTA_PERMIT_INVALID", f"{label} is not an exact host reference")
    if not value.startswith(f"hostref:{role}:"):
        _fail("DELTA_PERMIT_ROLE_MISMATCH", f"{label} has the wrong reference role")
    return value


def _timestamp(value: Any, *, label: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_TIMESTAMP_MS:
        _fail("DELTA_PERMIT_INVALID", f"{label} is invalid")
    return value


@dataclass(frozen=True, slots=True, repr=False)
class DeltaBinding:
    """Exact private authority snapshot to which a permit is tied."""

    session_id: str
    turn_id: str
    request_sha256: str
    instruction_sha256: str
    tenant_snapshot_revision: str
    source_sha256: str
    target_ref: str
    target_identity_sha256: str
    basis_ref: str | None
    basis_sha256: str | None
    edit_surface_sha256: str


@dataclass(frozen=True, slots=True, repr=False)
class ReplaceScalarOperation:
    """One role-typed replacement; all values remain opaque host references."""

    ordinal: int
    kind: Literal["replace_scalar"]
    primitive: DeltaPrimitive
    surface_ref: str
    value_ref: str
    evidence_ref: str
    authority_grant_ref: str | None


@dataclass(frozen=True, slots=True, repr=False)
class DeltaPermit:
    """Immutable server-side permit.  It intentionally has no serializer."""

    permit_id: str
    nonce: str
    issued_at_ms: int
    expires_at_ms: int
    binding: DeltaBinding
    operations: tuple[ReplaceScalarOperation, ...]
    reference_roles_sha256: str
    operations_sha256: str
    permit_sha256: str


@dataclass(frozen=True, slots=True, repr=False)
class DeltaPermitReceipt:
    """Private proof of consumption containing hashes and counts only."""

    permit_sha256: str
    consumption_sha256: str
    operations_sha256: str
    operation_count: int
    authority_grant_count: int
    receipt_sha256: str


@dataclass(frozen=True, slots=True, repr=False)
class AuthorizedDelta:
    """Private translator result for a renderer/compiler adapter."""

    operations: tuple[ReplaceScalarOperation, ...]
    receipt: DeltaPermitReceipt


def _binding_body(binding: DeltaBinding) -> dict[str, Any]:
    return {
        "session_id": binding.session_id,
        "turn_id": binding.turn_id,
        "request_sha256": binding.request_sha256,
        "instruction_sha256": binding.instruction_sha256,
        "tenant_snapshot_revision": binding.tenant_snapshot_revision,
        "source_sha256": binding.source_sha256,
        "target_ref": binding.target_ref,
        "target_identity_sha256": binding.target_identity_sha256,
        "basis_ref": binding.basis_ref,
        "basis_sha256": binding.basis_sha256,
        "edit_surface_sha256": binding.edit_surface_sha256,
    }


def _operation_body(operation: ReplaceScalarOperation) -> dict[str, Any]:
    return {
        "ordinal": operation.ordinal,
        "kind": operation.kind,
        "primitive": operation.primitive,
        "surface_ref": operation.surface_ref,
        "value_ref": operation.value_ref,
        "evidence_ref": operation.evidence_ref,
        "authority_grant_ref": operation.authority_grant_ref,
    }


def _parse_binding(value: Any) -> DeltaBinding:
    item = _exact_fields(value, _BINDING_FIELDS, label="delta binding")
    session_id = item["session_id"]
    turn_id = item["turn_id"]
    if not isinstance(session_id, str) or SESSION_ID_RE.fullmatch(session_id) is None:
        _fail("DELTA_PERMIT_INVALID", "session_id is invalid")
    if not isinstance(turn_id, str) or TURN_ID_RE.fullmatch(turn_id) is None:
        _fail("DELTA_PERMIT_INVALID", "turn_id is invalid")
    target_ref = _host_ref(item["target_ref"], role="target", label="target_ref")
    basis_ref_value = item["basis_ref"]
    basis_sha_value = item["basis_sha256"]
    if (basis_ref_value is None) != (basis_sha_value is None):
        _fail("DELTA_PERMIT_INVALID", "basis_ref and basis_sha256 must be present together")
    basis_ref = (
        None
        if basis_ref_value is None
        else _host_ref(basis_ref_value, role="basis", label="basis_ref")
    )
    basis_sha = None if basis_sha_value is None else _sha256(basis_sha_value, label="basis_sha256")
    return DeltaBinding(
        session_id=session_id,
        turn_id=turn_id,
        request_sha256=_sha256(item["request_sha256"], label="request_sha256"),
        instruction_sha256=_sha256(item["instruction_sha256"], label="instruction_sha256"),
        tenant_snapshot_revision=_sha256(
            item["tenant_snapshot_revision"], label="tenant_snapshot_revision"
        ),
        source_sha256=_sha256(item["source_sha256"], label="source_sha256"),
        target_ref=target_ref,
        target_identity_sha256=_sha256(
            item["target_identity_sha256"], label="target_identity_sha256"
        ),
        basis_ref=basis_ref,
        basis_sha256=basis_sha,
        edit_surface_sha256=_sha256(item["edit_surface_sha256"], label="edit_surface_sha256"),
    )


def _parse_operations(value: Any) -> tuple[ReplaceScalarOperation, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or not 1 <= len(value) <= MAX_OPERATIONS
    ):
        _fail("DELTA_PERMIT_INVALID", "operations must contain between 1 and 32 items")
    operations: list[ReplaceScalarOperation] = []
    used_refs: list[str] = []
    for expected_ordinal, raw in enumerate(value):
        item = _exact_fields(raw, _OPERATION_FIELDS, label="delta operation")
        ordinal = item["ordinal"]
        if type(ordinal) is not int or ordinal != expected_ordinal:
            _fail(
                "DELTA_PERMIT_INVALID",
                "operations must have contiguous source-order ordinals",
            )
        if item["kind"] != "replace_scalar":
            _fail("DELTA_PERMIT_INVALID", "delta operation kind is not admitted")
        primitive = item["primitive"]
        if not isinstance(primitive, str) or primitive not in DELTA_PRIMITIVES:
            _fail("DELTA_PERMIT_INVALID", "delta operation primitive is not admitted")
        surface_ref = _host_ref(item["surface_ref"], role="surface", label="surface_ref")
        value_ref = _host_ref(item["value_ref"], role="value", label="value_ref")
        evidence_ref = _host_ref(item["evidence_ref"], role="evidence", label="evidence_ref")
        grant_value = item["authority_grant_ref"]
        grant_ref = (
            None
            if grant_value is None
            else _host_ref(
                grant_value,
                role="block_argument_authority",
                label="authority_grant_ref",
            )
        )
        refs = [surface_ref, value_ref, evidence_ref]
        if grant_ref is not None:
            refs.append(grant_ref)
        used_refs.extend(refs)
        operations.append(
            ReplaceScalarOperation(
                ordinal=ordinal,
                kind="replace_scalar",
                primitive=primitive,  # type: ignore[arg-type]
                surface_ref=surface_ref,
                value_ref=value_ref,
                evidence_ref=evidence_ref,
                authority_grant_ref=grant_ref,
            )
        )
    if len(used_refs) != len(set(used_refs)):
        _fail("DELTA_PERMIT_INVALID", "delta operations contain duplicate references")
    return tuple(operations)


def _used_reference_roles(
    *,
    permit_id: str,
    nonce: str,
    binding: DeltaBinding,
    operations: tuple[ReplaceScalarOperation, ...],
) -> dict[str, ReferenceRole]:
    result: dict[str, ReferenceRole] = {
        permit_id: "permit",
        nonce: "nonce",
        binding.target_ref: "target",
    }
    if binding.basis_ref is not None:
        result[binding.basis_ref] = "basis"
    for operation in operations:
        result[operation.surface_ref] = "surface"
        result[operation.value_ref] = "value"
        result[operation.evidence_ref] = "evidence"
        if operation.authority_grant_ref is not None:
            result[operation.authority_grant_ref] = "block_argument_authority"
    return result


def _validate_reference_roles(
    expected: Mapping[str, ReferenceRole], issued_ref_roles: Mapping[str, Any]
) -> str:
    if not isinstance(issued_ref_roles, Mapping):
        _fail("DELTA_PERMIT_INVALID", "issued reference roles are invalid")
    if set(issued_ref_roles) != set(expected):
        _fail("DELTA_PERMIT_ROLE_MISMATCH", "issued reference role roster differs")
    for ref, role in expected.items():
        actual = issued_ref_roles.get(ref)
        if actual != role:
            _fail("DELTA_PERMIT_ROLE_MISMATCH", "issued reference role differs")
    roster = [{"ref": ref, "role": expected[ref]} for ref in sorted(expected)]
    return _canonical_sha256(roster)


def _permit_body(permit: DeltaPermit) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contract_id": DELTA_PERMIT_CONTRACT,
        "permit_id": permit.permit_id,
        "nonce": permit.nonce,
        "issued_at_ms": permit.issued_at_ms,
        "expires_at_ms": permit.expires_at_ms,
        "binding": _binding_body(permit.binding),
        "operations": [_operation_body(item) for item in permit.operations],
        "reference_roles_sha256": permit.reference_roles_sha256,
        "operations_sha256": permit.operations_sha256,
    }


def canonical_permit_sha256(permit: DeltaPermit) -> str:
    """Recompute the deterministic seal without exposing a permit payload."""

    if type(permit) is not DeltaPermit:
        _fail("DELTA_PERMIT_INVALID", "permit type is invalid")
    return _canonical_sha256(_permit_body(permit))


def issue_delta_permit(
    value: Any,
    *,
    issued_ref_roles: Mapping[str, Any],
) -> DeltaPermit:
    """Validate and seal one private, pre-candidate capability.

    ``value`` must be assembled by trusted host code.  Passing this mapping to a
    model or client would violate the contract even though its contents are
    value-redacted.
    """

    item = _exact_fields(value, _PERMIT_FIELDS, label="delta permit")
    if (
        type(item["schema_version"]) is not int
        or item["schema_version"] != 1
        or item["contract_id"] != DELTA_PERMIT_CONTRACT
    ):
        _fail("DELTA_PERMIT_INVALID", "delta permit contract is unsupported")
    permit_id = _host_ref(item["permit_id"], role="permit", label="permit_id")
    nonce = _host_ref(item["nonce"], role="nonce", label="nonce")
    issued_at_ms = _timestamp(item["issued_at_ms"], label="issued_at_ms")
    expires_at_ms = _timestamp(item["expires_at_ms"], label="expires_at_ms")
    ttl = expires_at_ms - issued_at_ms
    if not 1 <= ttl <= MAX_PERMIT_TTL_MS:
        _fail("DELTA_PERMIT_INVALID", "delta permit expiry is outside its bound")
    binding = _parse_binding(item["binding"])
    operations = _parse_operations(item["operations"])
    expected_roles = _used_reference_roles(
        permit_id=permit_id,
        nonce=nonce,
        binding=binding,
        operations=operations,
    )
    if len(expected_roles) != 3 + (binding.basis_ref is not None) + sum(
        3 + (operation.authority_grant_ref is not None) for operation in operations
    ):
        _fail("DELTA_PERMIT_INVALID", "delta permit contains duplicate references")
    reference_roles_sha256 = _validate_reference_roles(expected_roles, issued_ref_roles)
    operations_sha256 = _canonical_sha256([_operation_body(item) for item in operations])
    provisional = DeltaPermit(
        permit_id=permit_id,
        nonce=nonce,
        issued_at_ms=issued_at_ms,
        expires_at_ms=expires_at_ms,
        binding=binding,
        operations=operations,
        reference_roles_sha256=reference_roles_sha256,
        operations_sha256=operations_sha256,
        permit_sha256="",
    )
    permit_sha256 = canonical_permit_sha256(provisional)
    return DeltaPermit(
        permit_id=permit_id,
        nonce=nonce,
        issued_at_ms=issued_at_ms,
        expires_at_ms=expires_at_ms,
        binding=binding,
        operations=operations,
        reference_roles_sha256=reference_roles_sha256,
        operations_sha256=operations_sha256,
        permit_sha256=permit_sha256,
    )


def _parse_consumption(value: Any) -> tuple[str, str, str, tuple[ReplaceScalarOperation, ...]]:
    item = _exact_fields(value, _CONSUMPTION_FIELDS, label="delta consumption")
    if (
        type(item["schema_version"]) is not int
        or item["schema_version"] != 1
        or item["contract_id"] != DELTA_CONSUMPTION_CONTRACT
    ):
        _fail("DELTA_PERMIT_INVALID", "delta consumption contract is unsupported")
    permit_id = _host_ref(item["permit_id"], role="permit", label="permit_id")
    nonce = _host_ref(item["nonce"], role="nonce", label="nonce")
    permit_sha256 = _sha256(item["permit_sha256"], label="permit_sha256")
    return permit_id, nonce, permit_sha256, _parse_operations(item["operations"])


def _receipt_body(receipt: DeltaPermitReceipt) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contract_id": DELTA_RECEIPT_CONTRACT,
        "permit_sha256": receipt.permit_sha256,
        "consumption_sha256": receipt.consumption_sha256,
        "operations_sha256": receipt.operations_sha256,
        "operation_count": receipt.operation_count,
        "authority_grant_count": receipt.authority_grant_count,
    }


def canonical_receipt_sha256(receipt: DeltaPermitReceipt) -> str:
    """Recompute the private receipt seal from its non-user-data fields."""

    if type(receipt) is not DeltaPermitReceipt:
        _fail("DELTA_PERMIT_INVALID", "receipt type is invalid")
    return _canonical_sha256(_receipt_body(receipt))


def _validate_sealed_permit(
    permit: Any,
    *,
    issued_ref_roles: Mapping[str, Any],
) -> DeltaPermit:
    """Revalidate a permit object instead of trusting dataclass construction."""

    if type(permit) is not DeltaPermit:
        _fail("DELTA_PERMIT_INVALID", "delta permit type is invalid")
    if (
        type(permit.binding) is not DeltaBinding
        or type(permit.operations) is not tuple
        or any(type(operation) is not ReplaceScalarOperation for operation in permit.operations)
    ):
        _fail("DELTA_PERMIT_INVALID", "delta permit members are invalid")
    _host_ref(permit.permit_id, role="permit", label="permit_id")
    _host_ref(permit.nonce, role="nonce", label="nonce")
    issued_at_ms = _timestamp(permit.issued_at_ms, label="issued_at_ms")
    expires_at_ms = _timestamp(permit.expires_at_ms, label="expires_at_ms")
    if not 1 <= expires_at_ms - issued_at_ms <= MAX_PERMIT_TTL_MS:
        _fail("DELTA_PERMIT_INVALID", "delta permit expiry is outside its bound")
    if _parse_binding(_binding_body(permit.binding)) != permit.binding:
        _fail("DELTA_PERMIT_INVALID", "delta permit binding is invalid")
    parsed_operations = _parse_operations(
        [_operation_body(operation) for operation in permit.operations]
    )
    if parsed_operations != permit.operations:
        _fail("DELTA_PERMIT_INVALID", "delta permit operations are invalid")
    operations_sha256 = _canonical_sha256(
        [_operation_body(operation) for operation in permit.operations]
    )
    if permit.operations_sha256 != operations_sha256:
        _fail("DELTA_PERMIT_INVALID", "delta permit operation seal differs")
    expected_roles = _used_reference_roles(
        permit_id=permit.permit_id,
        nonce=permit.nonce,
        binding=permit.binding,
        operations=permit.operations,
    )
    role_sha256 = _validate_reference_roles(expected_roles, issued_ref_roles)
    if role_sha256 != permit.reference_roles_sha256:
        _fail("DELTA_PERMIT_ROLE_MISMATCH", "delta permit role roster drifted")
    if not isinstance(permit.permit_sha256, str) or not SHA256_RE.fullmatch(permit.permit_sha256):
        _fail("DELTA_PERMIT_INVALID", "delta permit seal is invalid")
    if canonical_permit_sha256(permit) != permit.permit_sha256:
        _fail("DELTA_PERMIT_INVALID", "delta permit seal differs")
    return permit


class DeltaPermitTranslator:
    """Atomic, fail-closed, single-use translator for one private permit."""

    __slots__ = ("_lock", "_permit", "_retired")

    def __init__(
        self,
        permit: DeltaPermit,
        *,
        issued_ref_roles: Mapping[str, Any],
    ) -> None:
        self._permit = _validate_sealed_permit(
            permit,
            issued_ref_roles=issued_ref_roles,
        )
        self._lock = threading.Lock()
        self._retired = False

    def consume(
        self,
        value: Any,
        *,
        current_binding: Any,
        now_ms: int,
    ) -> AuthorizedDelta:
        """Consume exactly once and return only private opaque operations.

        Retirement occurs before validation while holding the lock.  Therefore
        concurrent calls cannot both succeed and an invalid first attempt cannot
        be retried as an oracle over private authority.
        """

        with self._lock:
            if self._retired:
                _fail("DELTA_PERMIT_REPLAY", "delta permit was already consumed")
            self._retired = True
        now = _timestamp(now_ms, label="now_ms")
        permit = self._permit
        if now < permit.issued_at_ms:
            _fail("DELTA_PERMIT_DRIFT", "delta permit clock precedes issuance")
        if now >= permit.expires_at_ms:
            _fail("DELTA_PERMIT_EXPIRED", "delta permit has expired")
        binding = _parse_binding(current_binding)
        if binding != permit.binding:
            _fail("DELTA_PERMIT_DRIFT", "delta permit binding differs")
        permit_id, nonce, permit_sha256, operations = _parse_consumption(value)
        if (
            permit_id != permit.permit_id
            or nonce != permit.nonce
            or permit_sha256 != permit.permit_sha256
        ):
            _fail("DELTA_PERMIT_DRIFT", "delta permit identity differs")
        if operations != permit.operations:
            _fail("DELTA_PERMIT_DRIFT", "delta permit operations differ")
        consumption_sha256 = _canonical_sha256(
            {
                "schema_version": 1,
                "contract_id": DELTA_CONSUMPTION_CONTRACT,
                "permit_id": permit_id,
                "nonce": nonce,
                "permit_sha256": permit_sha256,
                "operations": [_operation_body(item) for item in operations],
            }
        )
        provisional_receipt = DeltaPermitReceipt(
            permit_sha256=permit.permit_sha256,
            consumption_sha256=consumption_sha256,
            operations_sha256=permit.operations_sha256,
            operation_count=len(operations),
            authority_grant_count=sum(
                operation.authority_grant_ref is not None for operation in operations
            ),
            receipt_sha256="",
        )
        receipt_sha256 = canonical_receipt_sha256(provisional_receipt)
        receipt = DeltaPermitReceipt(
            permit_sha256=provisional_receipt.permit_sha256,
            consumption_sha256=provisional_receipt.consumption_sha256,
            operations_sha256=provisional_receipt.operations_sha256,
            operation_count=provisional_receipt.operation_count,
            authority_grant_count=provisional_receipt.authority_grant_count,
            receipt_sha256=receipt_sha256,
        )
        return AuthorizedDelta(operations=operations, receipt=receipt)


__all__ = [
    "DELTA_CONSUMPTION_CONTRACT",
    "DELTA_PERMIT_CONTRACT",
    "DELTA_PRIMITIVES",
    "DELTA_RECEIPT_CONTRACT",
    "HOST_REF_RE",
    "MAX_OPERATIONS",
    "MAX_PERMIT_TTL_MS",
    "REFERENCE_ROLES",
    "SHA256_RE",
    "AuthorizedDelta",
    "DeltaBinding",
    "DeltaPermit",
    "DeltaPermitError",
    "DeltaPermitReceipt",
    "DeltaPermitTranslator",
    "ReplaceScalarOperation",
    "canonical_permit_sha256",
    "canonical_receipt_sha256",
    "issue_delta_permit",
]
