"""Contract tests for the private pre-candidate DeltaPermit v1 API.

Host integration is intentionally two-step: ``issue_delta_permit`` seals one
exact capability, then one ``DeltaPermitTranslator`` instance consumes an exact
opaque operation envelope before candidate generation.  Neither object has a
client serializer or contains source, IR, target paths, values or user text.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import fields, replace

import pytest

from metis_model1.brain_delta_permit import (
    DELTA_CONSUMPTION_CONTRACT,
    DELTA_PERMIT_CONTRACT,
    DELTA_PRIMITIVES,
    MAX_OPERATIONS,
    MAX_PERMIT_TTL_MS,
    DeltaPermitError,
    DeltaPermitTranslator,
    canonical_permit_sha256,
    canonical_receipt_sha256,
    issue_delta_permit,
)


def _sha(character: str) -> str:
    return "sha256:" + character * 64


def _ref(role: str, number: int) -> str:
    return f"hostref:{role}:{number:032x}"


def _binding() -> dict[str, object]:
    return {
        "session_id": "s" * 43,
        "turn_id": "t" * 32,
        "request_sha256": _sha("1"),
        "instruction_sha256": _sha("2"),
        "tenant_snapshot_revision": _sha("3"),
        "source_sha256": _sha("4"),
        "target_ref": _ref("target", 1),
        "target_identity_sha256": _sha("5"),
        "basis_ref": _ref("basis", 1),
        "basis_sha256": _sha("6"),
        "edit_surface_sha256": _sha("7"),
    }


def _operation(
    ordinal: int,
    primitive: str = "take_cardinality",
    *,
    grant: bool = False,
) -> dict[str, object]:
    offset = ordinal * 10
    return {
        "ordinal": ordinal,
        "kind": "replace_scalar",
        "primitive": primitive,
        "surface_ref": _ref("surface", offset + 1),
        "value_ref": _ref("value", offset + 2),
        "evidence_ref": _ref("evidence", offset + 3),
        "authority_grant_ref": (_ref("block_argument_authority", offset + 4) if grant else None),
    }


def _permit_spec(
    operations: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "contract_id": DELTA_PERMIT_CONTRACT,
        "permit_id": _ref("permit", 1),
        "nonce": _ref("nonce", 1),
        "issued_at_ms": 1_000,
        "expires_at_ms": 61_000,
        "binding": _binding(),
        "operations": operations or [_operation(0)],
    }


def _roles(spec: dict[str, object]) -> dict[str, str]:
    binding = spec["binding"]
    assert isinstance(binding, dict)
    result = {
        str(spec["permit_id"]): "permit",
        str(spec["nonce"]): "nonce",
        str(binding["target_ref"]): "target",
    }
    if binding["basis_ref"] is not None:
        result[str(binding["basis_ref"])] = "basis"
    operations = spec["operations"]
    assert isinstance(operations, list)
    for operation in operations:
        result[str(operation["surface_ref"])] = "surface"
        result[str(operation["value_ref"])] = "value"
        result[str(operation["evidence_ref"])] = "evidence"
        if operation["authority_grant_ref"] is not None:
            result[str(operation["authority_grant_ref"])] = "block_argument_authority"
    return result


def _consumption(spec: dict[str, object], permit_sha256: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "contract_id": DELTA_CONSUMPTION_CONTRACT,
        "permit_id": spec["permit_id"],
        "nonce": spec["nonce"],
        "permit_sha256": permit_sha256,
        "operations": deepcopy(spec["operations"]),
    }


def _issue(
    spec: dict[str, object] | None = None,
    *,
    roles: dict[str, str] | None = None,
):
    value = spec or _permit_spec()
    return issue_delta_permit(value, issued_ref_roles=roles or _roles(value))


def _translator(spec: dict[str, object] | None = None):
    value = spec or _permit_spec()
    roles = _roles(value)
    permit = _issue(value, roles=roles)
    return permit, DeltaPermitTranslator(permit, issued_ref_roles=roles)


def test_issue_and_consume_exact_pre_candidate_contract() -> None:
    spec = _permit_spec(
        [
            _operation(0, "take_cardinality"),
            _operation(1, "output_limit"),
            _operation(2, "display_label_or_title"),
            _operation(3, "block_argument_list", grant=True),
        ]
    )
    permit, translator = _translator(spec)

    authorized = translator.consume(
        _consumption(spec, permit.permit_sha256),
        current_binding=deepcopy(spec["binding"]),
        now_ms=2_000,
    )

    assert tuple(operation.primitive for operation in authorized.operations) == (
        "take_cardinality",
        "output_limit",
        "display_label_or_title",
        "block_argument_list",
    )
    assert authorized.receipt.operation_count == 4
    assert authorized.receipt.authority_grant_count == 1
    assert authorized.receipt.receipt_sha256 == canonical_receipt_sha256(authorized.receipt)
    assert permit.permit_sha256 == canonical_permit_sha256(permit)


def test_permit_hash_is_canonical_and_binds_every_authority_component() -> None:
    left = _permit_spec()
    reordered = {key: left[key] for key in reversed(left)}
    assert _issue(left).permit_sha256 == _issue(reordered).permit_sha256

    mutations = []
    for field_name in _binding():
        value = _permit_spec()
        binding = value["binding"]
        assert isinstance(binding, dict)
        if field_name == "basis_ref":
            binding[field_name] = _ref("basis", 2)
        elif field_name == "session_id":
            binding[field_name] = "x" * 43
        elif field_name == "turn_id":
            binding[field_name] = "y" * 32
        elif field_name == "target_ref":
            binding[field_name] = _ref("target", 2)
        else:
            binding[field_name] = _sha("8")
        mutations.append(value)
    for field_name, replacement in (
        ("permit_id", _ref("permit", 2)),
        ("nonce", _ref("nonce", 2)),
        ("issued_at_ms", 2_000),
        ("expires_at_ms", 62_000),
    ):
        value = _permit_spec()
        value[field_name] = replacement
        mutations.append(value)
    operation_mutation = _permit_spec()
    operation_mutation["operations"] = [_operation(0, "output_limit")]
    mutations.append(operation_mutation)

    original_hash = _issue(left).permit_sha256
    assert all(_issue(value).permit_sha256 != original_hash for value in mutations)


@pytest.mark.parametrize("primitive", sorted(DELTA_PRIMITIVES))
def test_only_four_generic_primitive_names_are_admitted(primitive: str) -> None:
    spec = _permit_spec([_operation(0, primitive)])
    assert _issue(spec).operations[0].primitive == primitive


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(raw_source="endpoint secret {}"),
        lambda value: value.update(raw_ir={"Endpoint": {}}),
        lambda value: value["binding"].update(target_path="endpoints/private.metis"),
        lambda value: value["operations"][0].update(literal="Italia 1"),
        lambda value: value["operations"][0].update(kind="insert"),
        lambda value: value["operations"][0].update(primitive="predicate_value"),
    ],
)
def test_unknown_raw_or_unadmitted_fields_fail_closed(mutation) -> None:
    spec = _permit_spec()
    mutation(spec)
    with pytest.raises(DeltaPermitError, match="invalid|not admitted"):
        _issue(spec)


@pytest.mark.parametrize(
    ("field_name", "invalid"),
    [
        ("request_sha256", "1" * 64),
        ("instruction_sha256", "sha256:" + "A" * 64),
        ("tenant_snapshot_revision", "sha512:" + "3" * 64),
        ("source_sha256", "sha256:" + "4" * 63),
        ("target_identity_sha256", "sha256:" + "g" * 64),
        ("edit_surface_sha256", None),
    ],
)
def test_hash_formats_are_exact(field_name: str, invalid: object) -> None:
    spec = _permit_spec()
    binding = spec["binding"]
    assert isinstance(binding, dict)
    binding[field_name] = invalid
    with pytest.raises(DeltaPermitError, match="exact sha256"):
        _issue(spec)


@pytest.mark.parametrize(
    ("location", "field_name", "invalid"),
    [
        ("permit", "permit_id", "hostref:permit:not-hex"),
        ("permit", "nonce", _ref("permit", 9)),
        ("binding", "target_ref", _ref("basis", 9)),
        ("binding", "basis_ref", "hostref:basis:" + "a" * 31),
        ("operation", "surface_ref", _ref("value", 9)),
        ("operation", "value_ref", "hostref:value:" + "z" * 32),
        ("operation", "evidence_ref", "evidence:opaque"),
    ],
)
def test_host_reference_formats_and_roles_are_exact(
    location: str, field_name: str, invalid: object
) -> None:
    spec = _permit_spec()
    target = spec if location == "permit" else spec["binding"]
    if location == "operation":
        operations = spec["operations"]
        assert isinstance(operations, list)
        target = operations[0]
    assert isinstance(target, dict)
    target[field_name] = invalid
    with pytest.raises(DeltaPermitError, match="host reference|reference role"):
        _issue(spec)


def test_issued_reference_invention_and_role_swaps_fail_closed() -> None:
    spec = _permit_spec([_operation(0, grant=True)])
    roles = _roles(spec)
    roles.pop(str(spec["permit_id"]))
    with pytest.raises(DeltaPermitError) as unknown:
        _issue(spec, roles=roles)
    assert unknown.value.code == "DELTA_PERMIT_ROLE_MISMATCH"

    roles = _roles(spec)
    operation = spec["operations"]
    assert isinstance(operation, list)
    roles[str(operation[0]["surface_ref"])] = "value"
    with pytest.raises(DeltaPermitError) as swapped:
        _issue(spec, roles=roles)
    assert swapped.value.code == "DELTA_PERMIT_ROLE_MISMATCH"

    roles = _roles(spec)
    roles[str(operation[0]["authority_grant_ref"])] = "evidence"
    with pytest.raises(DeltaPermitError) as grant:
        _issue(spec, roles=roles)
    assert grant.value.code == "DELTA_PERMIT_ROLE_MISMATCH"


def test_unused_well_formed_reference_role_fails_before_seal_or_translation() -> None:
    spec = _permit_spec()
    roles = _roles(spec)
    roles[_ref("block_argument_authority", 99)] = "block_argument_authority"
    with pytest.raises(DeltaPermitError) as issue_error:
        _issue(spec, roles=roles)
    assert issue_error.value.code == "DELTA_PERMIT_ROLE_MISMATCH"

    permit = _issue(spec)
    with pytest.raises(DeltaPermitError) as translation_error:
        DeltaPermitTranslator(permit, issued_ref_roles=roles)
    assert translation_error.value.code == "DELTA_PERMIT_ROLE_MISMATCH"


def test_optional_block_argument_authority_grant_is_opaque_and_role_bound() -> None:
    without = _issue(_permit_spec([_operation(0)]))
    with_grant = _issue(_permit_spec([_operation(0, grant=True)]))
    assert without.operations[0].authority_grant_ref is None
    assert with_grant.operations[0].authority_grant_ref == _ref("block_argument_authority", 4)
    assert with_grant.permit_sha256 != without.permit_sha256


def test_basis_ref_and_hash_are_jointly_optional() -> None:
    create = _permit_spec()
    binding = create["binding"]
    assert isinstance(binding, dict)
    binding["basis_ref"] = None
    binding["basis_sha256"] = None
    assert _issue(create).binding.basis_ref is None

    for missing in ("basis_ref", "basis_sha256"):
        malformed = _permit_spec()
        binding = malformed["binding"]
        assert isinstance(binding, dict)
        binding[missing] = None
        with pytest.raises(DeltaPermitError, match="present together"):
            _issue(malformed)


def test_operations_are_non_empty_bounded_ordered_and_nonduplicated() -> None:
    empty = _permit_spec()
    empty["operations"] = []
    with pytest.raises(DeltaPermitError, match="between 1 and 32"):
        _issue(empty)

    maximum = _permit_spec([_operation(index) for index in range(MAX_OPERATIONS)])
    assert len(_issue(maximum).operations) == MAX_OPERATIONS

    overflow = _permit_spec([_operation(index) for index in range(MAX_OPERATIONS + 1)])
    with pytest.raises(DeltaPermitError, match="between 1 and 32"):
        _issue(overflow)

    unordered = _permit_spec([_operation(1), _operation(0)])
    with pytest.raises(DeltaPermitError, match="contiguous source-order"):
        _issue(unordered)

    duplicate = _permit_spec([_operation(0), _operation(1)])
    operations = duplicate["operations"]
    assert isinstance(operations, list)
    operations[1]["evidence_ref"] = operations[0]["evidence_ref"]
    with pytest.raises(DeltaPermitError, match="duplicate references"):
        _issue(duplicate)


@pytest.mark.parametrize(
    "field_name",
    [
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
    ],
)
def test_every_runtime_binding_drift_retires_the_permit(field_name: str) -> None:
    spec = _permit_spec()
    permit, translator = _translator(spec)
    current = deepcopy(spec["binding"])
    assert isinstance(current, dict)
    if field_name == "session_id":
        current[field_name] = "x" * 43
    elif field_name == "turn_id":
        current[field_name] = "y" * 32
    elif field_name == "target_ref":
        current[field_name] = _ref("target", 2)
    elif field_name == "basis_ref":
        current[field_name] = _ref("basis", 2)
    else:
        current[field_name] = _sha("8")
    with pytest.raises(DeltaPermitError) as drift:
        translator.consume(
            _consumption(spec, permit.permit_sha256),
            current_binding=current,
            now_ms=2_000,
        )
    assert drift.value.code == "DELTA_PERMIT_DRIFT"
    with pytest.raises(DeltaPermitError) as replay:
        translator.consume(
            _consumption(spec, permit.permit_sha256),
            current_binding=spec["binding"],
            now_ms=2_000,
        )
    assert replay.value.code == "DELTA_PERMIT_REPLAY"


@pytest.mark.parametrize("field_name", ["permit_id", "nonce", "permit_sha256"])
def test_consumption_identity_drift_fails_closed(field_name: str) -> None:
    spec = _permit_spec()
    permit, translator = _translator(spec)
    consumption = _consumption(spec, permit.permit_sha256)
    if field_name == "permit_id":
        consumption[field_name] = _ref("permit", 2)
    elif field_name == "nonce":
        consumption[field_name] = _ref("nonce", 2)
    else:
        consumption[field_name] = _sha("8")
    with pytest.raises(DeltaPermitError) as error:
        translator.consume(
            consumption,
            current_binding=spec["binding"],
            now_ms=2_000,
        )
    assert error.value.code == "DELTA_PERMIT_DRIFT"


def test_operation_drift_and_unknown_consumption_fields_are_burn_after_read() -> None:
    spec = _permit_spec()
    permit, translator = _translator(spec)
    changed = _consumption(spec, permit.permit_sha256)
    operations = changed["operations"]
    assert isinstance(operations, list)
    operations[0]["primitive"] = "output_limit"
    with pytest.raises(DeltaPermitError) as drift:
        translator.consume(changed, current_binding=spec["binding"], now_ms=2_000)
    assert drift.value.code == "DELTA_PERMIT_DRIFT"

    _permit, translator = _translator(spec)
    malformed = _consumption(spec, _permit.permit_sha256)
    malformed["raw_source"] = "private"
    with pytest.raises(DeltaPermitError) as invalid:
        translator.consume(malformed, current_binding=spec["binding"], now_ms=2_000)
    assert invalid.value.code == "DELTA_PERMIT_INVALID"
    with pytest.raises(DeltaPermitError) as replay:
        translator.consume(
            _consumption(spec, _permit.permit_sha256),
            current_binding=spec["binding"],
            now_ms=2_000,
        )
    assert replay.value.code == "DELTA_PERMIT_REPLAY"


def test_expiry_is_bounded_and_expired_or_future_clock_consumption_retires() -> None:
    too_long = _permit_spec()
    too_long["expires_at_ms"] = 1_000 + MAX_PERMIT_TTL_MS + 1
    with pytest.raises(DeltaPermitError, match="expiry"):
        _issue(too_long)

    for now, expected_code in ((61_000, "DELTA_PERMIT_EXPIRED"), (999, "DELTA_PERMIT_DRIFT")):
        spec = _permit_spec()
        permit, translator = _translator(spec)
        with pytest.raises(DeltaPermitError) as error:
            translator.consume(
                _consumption(spec, permit.permit_sha256),
                current_binding=spec["binding"],
                now_ms=now,
            )
        assert error.value.code == expected_code


def test_consume_is_atomic_and_exactly_one_concurrent_caller_wins() -> None:
    spec = _permit_spec()
    permit, translator = _translator(spec)
    consumption = _consumption(spec, permit.permit_sha256)

    def consume() -> str:
        try:
            translator.consume(
                consumption,
                current_binding=spec["binding"],
                now_ms=2_000,
            )
        except DeltaPermitError as error:
            return error.code
        return "OK"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(lambda _index: consume(), range(8)))
    assert outcomes.count("OK") == 1
    assert outcomes.count("DELTA_PERMIT_REPLAY") == 7


def test_permit_tampering_and_role_registry_drift_are_rejected_by_translator() -> None:
    spec = _permit_spec()
    roles = _roles(spec)
    permit = _issue(spec, roles=roles)
    tampered = replace(permit, expires_at_ms=permit.expires_at_ms + 1)
    with pytest.raises(DeltaPermitError, match="seal differs"):
        DeltaPermitTranslator(tampered, issued_ref_roles=roles)

    nested_tamper = replace(permit, operations_sha256=_sha("8"), permit_sha256="")
    nested_tamper = replace(
        nested_tamper,
        permit_sha256=canonical_permit_sha256(nested_tamper),
    )
    with pytest.raises(DeltaPermitError, match="operation seal differs"):
        DeltaPermitTranslator(nested_tamper, issued_ref_roles=roles)

    roles[str(spec["permit_id"])] = "nonce"
    with pytest.raises(DeltaPermitError) as error:
        DeltaPermitTranslator(permit, issued_ref_roles=roles)
    assert error.value.code == "DELTA_PERMIT_ROLE_MISMATCH"


def test_private_objects_have_no_payload_serializer_or_user_data_receipt() -> None:
    spec = _permit_spec([_operation(0, "display_label_or_title", grant=True)])
    permit, translator = _translator(spec)
    authorized = translator.consume(
        _consumption(spec, permit.permit_sha256),
        current_binding=spec["binding"],
        now_ms=2_000,
    )

    assert not hasattr(permit, "payload")
    assert not hasattr(permit, "to_dict")
    assert not hasattr(permit, "__dict__")
    assert not hasattr(authorized.receipt, "payload")
    with pytest.raises(TypeError):
        json.dumps(permit)

    assert {field.name for field in fields(authorized.receipt)} == {
        "permit_sha256",
        "consumption_sha256",
        "operations_sha256",
        "operation_count",
        "authority_grant_count",
        "receipt_sha256",
    }
    receipt_text = repr(authorized.receipt)
    assert "display" not in receipt_text
    assert "session" not in receipt_text
    assert "Italia" not in receipt_text


def test_malformed_boolean_ordinals_and_timestamps_are_rejected() -> None:
    spec = _permit_spec()
    spec["issued_at_ms"] = True
    with pytest.raises(DeltaPermitError, match="issued_at_ms"):
        _issue(spec)

    spec = _permit_spec()
    operations = spec["operations"]
    assert isinstance(operations, list)
    operations[0]["ordinal"] = False
    with pytest.raises(DeltaPermitError, match="ordinals"):
        _issue(spec)

    spec = _permit_spec()
    spec["schema_version"] = True
    with pytest.raises(DeltaPermitError, match="unsupported"):
        _issue(spec)

    spec = _permit_spec()
    permit, translator = _translator(spec)
    consumption = _consumption(spec, permit.permit_sha256)
    consumption["schema_version"] = True
    with pytest.raises(DeltaPermitError, match="unsupported"):
        translator.consume(consumption, current_binding=spec["binding"], now_ms=2_000)
