"""Fail-closed contract tests for the private CREATE permit.

Only digests and role-typed references cross this boundary.  Actual outlines,
plans, grants, source and IR remain in a future trusted-host registry.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import fields, replace

import pytest

from metis_model1.brain_create_permit import (
    CREATE_CONSUMPTION_CONTRACT,
    CREATE_PERMIT_CONTRACT,
    MAX_CREATE_OPERATIONS,
    MAX_CREATE_PERMIT_TTL_MS,
    CreatePermitConsumer,
    CreatePermitError,
    canonical_create_permit_sha256,
    canonical_create_receipt_sha256,
    issue_create_permit,
)


def _sha(character: str) -> str:
    return "sha256:" + character * 64


def _ref(role: str, number: int) -> str:
    return f"hostref:{role}:{number:032x}"


def _binding(*, parent: bool = False) -> dict[str, object]:
    return {
        "session_id": "s" * 43,
        "turn_id": "t" * 32,
        "request_sha256": _sha("1"),
        "instruction_sha256": _sha("2"),
        "context_revision": _sha("3"),
        "semantic_source_revision": _sha("4"),
        "toolchain_binding": _sha("5"),
        "target_ref": _ref("target", 1),
        "target_sha256": _sha("6"),
        "conversation_id": _sha("7"),
        "conversation_generation": 1 if parent else 0,
        "parent_proposal_ref": _ref("parent_proposal", 1) if parent else None,
        "parent_proposal_sha256": _sha("8") if parent else None,
        "parent_source_sha256": _sha("9") if parent else None,
        "parent_manifest_sha256": _sha("a") if parent else None,
        "parent_ir_sha256": _sha("b") if parent else None,
        "outline_sha256": _sha("c"),
        "plan_sha256": _sha("d"),
        "grants_sha256": _sha("e"),
    }


def _operation(ordinal: int, *, digest: str = "f") -> dict[str, object]:
    return {
        "ordinal": ordinal,
        "operation_ref": _ref("operation", ordinal + 1),
        "operation_sha256": _sha(digest),
    }


def _spec(
    operations: list[dict[str, object]] | None = None,
    *,
    parent: bool = False,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "contract_id": CREATE_PERMIT_CONTRACT,
        "permit_id": _ref("permit", 1),
        "nonce": _ref("nonce", 1),
        "issued_at_ms": 1_000,
        "expires_at_ms": 61_000,
        "binding": _binding(parent=parent),
        "operation_seals": operations if operations is not None else [_operation(0)],
    }


def _roles(spec: dict[str, object]) -> dict[str, str]:
    binding = spec["binding"]
    operations = spec["operation_seals"]
    assert isinstance(binding, dict)
    assert isinstance(operations, list)
    result = {
        str(spec["permit_id"]): "permit",
        str(spec["nonce"]): "nonce",
        str(binding["target_ref"]): "target",
    }
    if binding["parent_proposal_ref"] is not None:
        result[str(binding["parent_proposal_ref"])] = "parent_proposal"
    for operation in operations:
        result[str(operation["operation_ref"])] = "operation"
    return result


def _issue(spec: dict[str, object] | None = None):
    value = spec or _spec()
    return issue_create_permit(value, issued_ref_roles=_roles(value))


def _consumer(spec: dict[str, object] | None = None):
    value = spec or _spec()
    roles = _roles(value)
    permit = issue_create_permit(value, issued_ref_roles=roles)
    return permit, CreatePermitConsumer(permit, issued_ref_roles=roles)


def _consumption(spec: dict[str, object], permit_sha256: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "contract_id": CREATE_CONSUMPTION_CONTRACT,
        "permit_id": spec["permit_id"],
        "nonce": spec["nonce"],
        "permit_sha256": permit_sha256,
        "operation_seals": deepcopy(spec["operation_seals"]),
    }


def test_initial_create_issue_and_consume_returns_only_seals_and_hash_receipt() -> None:
    spec = _spec([_operation(0), _operation(1, digest="0")])
    permit, consumer = _consumer(spec)

    authorized = consumer.consume(
        _consumption(spec, permit.permit_sha256),
        current_binding=deepcopy(spec["binding"]),
        now_ms=2_000,
    )

    assert [item.ordinal for item in authorized.operation_seals] == [0, 1]
    assert authorized.receipt.receipt_sha256 == canonical_create_receipt_sha256(authorized.receipt)
    assert permit.permit_sha256 == canonical_create_permit_sha256(permit)
    assert {item.name for item in fields(authorized.receipt)} == {
        "permit_sha256",
        "consumption_sha256",
        "binding_sha256",
        "operations_sha256",
        "receipt_sha256",
    }
    assert all(
        getattr(authorized.receipt, item.name).startswith("sha256:")
        for item in fields(authorized.receipt)
    )


def test_refinement_parent_authority_is_bound_as_one_unit() -> None:
    spec = _spec(parent=True)
    permit, consumer = _consumer(spec)
    authorized = consumer.consume(
        _consumption(spec, permit.permit_sha256),
        current_binding=spec["binding"],
        now_ms=2_000,
    )
    assert permit.binding.conversation_generation == 1
    assert permit.binding.parent_proposal_ref == _ref("parent_proposal", 1)
    assert authorized.receipt.binding_sha256 == permit.binding_sha256


@pytest.mark.parametrize(
    "present_field",
    [
        "parent_proposal_ref",
        "parent_proposal_sha256",
        "parent_source_sha256",
        "parent_manifest_sha256",
        "parent_ir_sha256",
    ],
)
def test_parent_proposal_source_manifest_and_ir_are_all_or_none(present_field: str) -> None:
    spec = _spec()
    binding = spec["binding"]
    assert isinstance(binding, dict)
    binding[present_field] = (
        _ref("parent_proposal", 1) if present_field == "parent_proposal_ref" else _sha("8")
    )
    with pytest.raises(CreatePermitError, match="present together"):
        _issue(spec)

    spec = _spec(parent=True)
    binding = spec["binding"]
    assert isinstance(binding, dict)
    binding[present_field] = None
    with pytest.raises(CreatePermitError, match="present together"):
        _issue(spec)


def test_permit_hash_binds_complete_authority_and_operation_roster() -> None:
    baseline = _spec(parent=True)
    original = _issue(baseline).permit_sha256
    for field_name in _binding(parent=True):
        changed = _spec(parent=True)
        binding = changed["binding"]
        assert isinstance(binding, dict)
        if field_name == "session_id":
            binding[field_name] = "x" * 43
        elif field_name == "turn_id":
            binding[field_name] = "y" * 32
        elif field_name == "target_ref":
            binding[field_name] = _ref("target", 2)
        elif field_name == "conversation_id":
            binding[field_name] = _sha("0")
        elif field_name == "conversation_generation":
            binding[field_name] = 2
        elif field_name == "parent_proposal_ref":
            binding[field_name] = _ref("parent_proposal", 2)
        else:
            binding[field_name] = _sha("0")
        assert _issue(changed).permit_sha256 != original

    changed = _spec(parent=True)
    changed["operation_seals"] = [_operation(0, digest="0")]
    assert _issue(changed).permit_sha256 != original


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(source="endpoint private {}"),
        lambda value: value.update(relative_path="properties/private.metis"),
        lambda value: value.update(ir={"node": "Endpoint"}),
        lambda value: value["binding"].update(instruction="private prompt"),
        lambda value: value["binding"].update(outline={"endpoint": "private"}),
        lambda value: value["binding"].update(plan={"operations": []}),
        lambda value: value["binding"].update(grants=["video"]),
        lambda value: value["operation_seals"][0].update(operation={"kind": "fetch"}),
    ],
)
def test_raw_source_path_ir_text_and_payloads_are_not_admitted(mutation) -> None:
    spec = _spec()
    mutation(spec)
    with pytest.raises(CreatePermitError, match="invalid field roster"):
        _issue(spec)


@pytest.mark.parametrize(
    ("field_name", "invalid"),
    [
        ("request_sha256", "1" * 64),
        ("instruction_sha256", "sha256:" + "A" * 64),
        ("context_revision", "sha512:" + "3" * 64),
        ("semantic_source_revision", "sha256:" + "4" * 63),
        ("toolchain_binding", "sha256:" + "g" * 64),
        ("target_sha256", None),
        ("outline_sha256", {}),
        ("plan_sha256", "sha256:0"),
        ("grants_sha256", True),
    ],
)
def test_every_digest_has_exact_sha256_shape(field_name: str, invalid: object) -> None:
    spec = _spec()
    binding = spec["binding"]
    assert isinstance(binding, dict)
    binding[field_name] = invalid
    with pytest.raises(CreatePermitError, match="exact sha256"):
        _issue(spec)


def test_role_typed_refs_and_exact_registry_fail_closed() -> None:
    spec = _spec(parent=True)
    binding = spec["binding"]
    operations = spec["operation_seals"]
    assert isinstance(binding, dict)
    assert isinstance(operations, list)
    binding["target_ref"] = _ref("operation", 9)
    with pytest.raises(CreatePermitError, match="reference role"):
        _issue(spec)

    spec = _spec(parent=True)
    roles = _roles(spec)
    roles[str(spec["permit_id"])] = "nonce"
    with pytest.raises(CreatePermitError) as swapped:
        issue_create_permit(spec, issued_ref_roles=roles)
    assert swapped.value.code == "CREATE_PERMIT_ROLE_MISMATCH"

    roles = _roles(spec)
    roles[_ref("operation", 99)] = "operation"
    with pytest.raises(CreatePermitError) as invented:
        issue_create_permit(spec, issued_ref_roles=roles)
    assert invented.value.code == "CREATE_PERMIT_ROLE_MISMATCH"


def test_operation_seal_roster_is_nonempty_bounded_ordered_and_unique() -> None:
    empty = _spec([])
    with pytest.raises(CreatePermitError, match="between 1 and 1024"):
        _issue(empty)

    maximum = _spec([_operation(index) for index in range(MAX_CREATE_OPERATIONS)])
    assert len(_issue(maximum).operation_seals) == MAX_CREATE_OPERATIONS

    overflow = _spec([_operation(index) for index in range(MAX_CREATE_OPERATIONS + 1)])
    with pytest.raises(CreatePermitError, match="between 1 and 1024"):
        _issue(overflow)

    unordered = _spec([_operation(1), _operation(0)])
    with pytest.raises(CreatePermitError, match="contiguous source-order"):
        _issue(unordered)

    boolean = _spec()
    operations = boolean["operation_seals"]
    assert isinstance(operations, list)
    operations[0]["ordinal"] = False
    with pytest.raises(CreatePermitError, match="ordinals"):
        _issue(boolean)

    duplicate = _spec([_operation(0), _operation(1)])
    operations = duplicate["operation_seals"]
    assert isinstance(operations, list)
    operations[1]["operation_ref"] = operations[0]["operation_ref"]
    with pytest.raises(CreatePermitError, match="duplicate references"):
        _issue(duplicate)


def test_ttl_is_positive_and_never_exceeds_session_idle_ttl() -> None:
    for expires in (1_000, 1_000 + MAX_CREATE_PERMIT_TTL_MS + 1):
        spec = _spec()
        spec["expires_at_ms"] = expires
        with pytest.raises(CreatePermitError, match="expiry"):
            _issue(spec)

    spec = _spec()
    spec["expires_at_ms"] = 1_000 + MAX_CREATE_PERMIT_TTL_MS
    assert _issue(spec).expires_at_ms == spec["expires_at_ms"]


def _drift(binding: dict[str, object], field_name: str) -> None:
    if field_name == "session_id":
        binding[field_name] = "x" * 43
    elif field_name == "turn_id":
        binding[field_name] = "y" * 32
    elif field_name == "target_ref":
        binding[field_name] = _ref("target", 2)
    elif field_name == "conversation_id":
        binding[field_name] = _sha("0")
    elif field_name == "conversation_generation":
        binding[field_name] = 2
    elif field_name == "parent_proposal_ref":
        binding[field_name] = _ref("parent_proposal", 2)
    else:
        binding[field_name] = _sha("0")


@pytest.mark.parametrize("field_name", list(_binding(parent=True)))
def test_every_current_binding_drift_burns_the_permit(field_name: str) -> None:
    spec = _spec(parent=True)
    permit, consumer = _consumer(spec)
    current = deepcopy(spec["binding"])
    assert isinstance(current, dict)
    _drift(current, field_name)
    with pytest.raises(CreatePermitError) as drift:
        consumer.consume(
            _consumption(spec, permit.permit_sha256),
            current_binding=current,
            now_ms=2_000,
        )
    assert drift.value.code == "CREATE_PERMIT_DRIFT"
    with pytest.raises(CreatePermitError) as replay:
        consumer.consume(
            _consumption(spec, permit.permit_sha256),
            current_binding=spec["binding"],
            now_ms=2_000,
        )
    assert replay.value.code == "CREATE_PERMIT_REPLAY"


@pytest.mark.parametrize("field_name", ["permit_id", "nonce", "permit_sha256"])
def test_consumption_identity_tamper_is_burn_before_validation(field_name: str) -> None:
    spec = _spec()
    permit, consumer = _consumer(spec)
    value = _consumption(spec, permit.permit_sha256)
    value[field_name] = (
        _ref(field_name.removesuffix("_id"), 2) if field_name != "permit_sha256" else _sha("0")
    )
    with pytest.raises(CreatePermitError) as drift:
        consumer.consume(value, current_binding=spec["binding"], now_ms=2_000)
    assert drift.value.code == "CREATE_PERMIT_DRIFT"
    with pytest.raises(CreatePermitError) as replay:
        consumer.consume(
            _consumption(spec, permit.permit_sha256),
            current_binding=spec["binding"],
            now_ms=2_000,
        )
    assert replay.value.code == "CREATE_PERMIT_REPLAY"


def test_operation_or_envelope_tamper_burns_the_permit() -> None:
    spec = _spec()
    permit, consumer = _consumer(spec)
    changed = _consumption(spec, permit.permit_sha256)
    operations = changed["operation_seals"]
    assert isinstance(operations, list)
    operations[0]["operation_sha256"] = _sha("0")
    with pytest.raises(CreatePermitError) as drift:
        consumer.consume(changed, current_binding=spec["binding"], now_ms=2_000)
    assert drift.value.code == "CREATE_PERMIT_DRIFT"

    permit, consumer = _consumer(spec)
    malformed = _consumption(spec, permit.permit_sha256)
    malformed["source"] = "private"
    with pytest.raises(CreatePermitError) as invalid:
        consumer.consume(malformed, current_binding=spec["binding"], now_ms=2_000)
    assert invalid.value.code == "CREATE_PERMIT_INVALID"
    with pytest.raises(CreatePermitError) as replay:
        consumer.consume(
            _consumption(spec, permit.permit_sha256),
            current_binding=spec["binding"],
            now_ms=2_000,
        )
    assert replay.value.code == "CREATE_PERMIT_REPLAY"


@pytest.mark.parametrize(
    ("now_ms", "code"),
    [(61_000, "CREATE_PERMIT_EXPIRED"), (999, "CREATE_PERMIT_DRIFT")],
)
def test_expired_or_preissuance_clock_burns_the_permit(now_ms: int, code: str) -> None:
    spec = _spec()
    permit, consumer = _consumer(spec)
    with pytest.raises(CreatePermitError) as error:
        consumer.consume(
            _consumption(spec, permit.permit_sha256),
            current_binding=spec["binding"],
            now_ms=now_ms,
        )
    assert error.value.code == code
    with pytest.raises(CreatePermitError) as replay:
        consumer.consume(
            _consumption(spec, permit.permit_sha256),
            current_binding=spec["binding"],
            now_ms=2_000,
        )
    assert replay.value.code == "CREATE_PERMIT_REPLAY"


def test_only_one_concurrent_consumer_can_succeed() -> None:
    spec = _spec()
    permit, consumer = _consumer(spec)
    value = _consumption(spec, permit.permit_sha256)

    def consume() -> str:
        try:
            consumer.consume(value, current_binding=spec["binding"], now_ms=2_000)
        except CreatePermitError as error:
            return error.code
        return "OK"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _index: consume(), range(8)))
    assert outcomes.count("OK") == 1
    assert outcomes.count("CREATE_PERMIT_REPLAY") == 7


def test_dataclass_tamper_and_role_registry_drift_are_revalidated() -> None:
    spec = _spec(parent=True)
    roles = _roles(spec)
    permit = issue_create_permit(spec, issued_ref_roles=roles)
    tampered = replace(permit, expires_at_ms=permit.expires_at_ms + 1)
    with pytest.raises(CreatePermitError, match="seal differs"):
        CreatePermitConsumer(tampered, issued_ref_roles=roles)

    nested = replace(permit, operations_sha256=_sha("0"), permit_sha256="")
    nested = replace(nested, permit_sha256=canonical_create_permit_sha256(nested))
    with pytest.raises(CreatePermitError, match="operation seal differs"):
        CreatePermitConsumer(nested, issued_ref_roles=roles)

    roles[str(spec["permit_id"])] = "nonce"
    with pytest.raises(CreatePermitError) as role_error:
        CreatePermitConsumer(permit, issued_ref_roles=roles)
    assert role_error.value.code == "CREATE_PERMIT_ROLE_MISMATCH"


def test_private_types_have_no_serializer_repr_or_raw_receipt_fields() -> None:
    spec = _spec(parent=True)
    permit, consumer = _consumer(spec)
    authorized = consumer.consume(
        _consumption(spec, permit.permit_sha256),
        current_binding=spec["binding"],
        now_ms=2_000,
    )
    for value in (permit, authorized, authorized.receipt):
        assert not hasattr(value, "payload")
        assert not hasattr(value, "to_dict")
        assert not hasattr(value, "__dict__")
        with pytest.raises(TypeError):
            json.dumps(value)
    rendered = repr(authorized.receipt)
    assert "session" not in rendered
    assert "source" not in rendered
    assert "outline" not in rendered
    assert "plan" not in rendered


def test_boolean_contract_generation_timestamp_and_ordinal_are_rejected() -> None:
    spec = _spec()
    spec["schema_version"] = True
    with pytest.raises(CreatePermitError, match="unsupported"):
        _issue(spec)

    spec = _spec()
    spec["issued_at_ms"] = True
    with pytest.raises(CreatePermitError, match="issued_at_ms"):
        _issue(spec)

    spec = _spec()
    binding = spec["binding"]
    assert isinstance(binding, dict)
    binding["conversation_generation"] = True
    with pytest.raises(CreatePermitError, match="conversation_generation"):
        _issue(spec)
