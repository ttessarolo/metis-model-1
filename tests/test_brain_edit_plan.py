from __future__ import annotations

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from metis_model1.brain_edit_plan import (
    EDIT_PLAN_CONTRACT,
    EDIT_PLAN_SCHEMA,
    admit_edit_plan,
    validate_edit_plan,
)
from metis_model1.brain_protocol import BrainError

CONTEXT = "sha256:" + "a" * 64
WORKSPACE = "sha256:" + "b" * 64
EDIT_SOURCE = "sha256:" + "c" * 64


def _plan() -> dict[str, object]:
    return {
        "schema_version": 2,
        "contract_id": EDIT_PLAN_CONTRACT,
        "context_revision": CONTEXT,
        "workspace_base_revision": WORKSPACE,
        "edit_source_revision": EDIT_SOURCE,
        "target_ref": "hostref:target-1",
        "base_ref": "hostref:base-1",
        "basis_ref": None,
        "operations": [
            {
                "ordinal": 0,
                "kind": "replace",
                "node_ref": "hostref:node-1",
                "payload_ref": "hostref:payload-1",
            }
        ],
    }


ISSUED = {"hostref:target-1", "hostref:base-1", "hostref:node-1", "hostref:payload-1"}


def _validate(value: object, *, issued: set[str] = ISSUED, basis: str | None = None) -> list[str]:
    return validate_edit_plan(
        value,
        issued_refs=issued,
        expected_context_revision=CONTEXT,
        expected_workspace_base_revision=WORKSPACE,
        expected_edit_source_revision=EDIT_SOURCE,
        expected_basis_ref=basis,
    )


def test_schema_and_host_validator_accept_only_opaque_host_refs() -> None:
    assert Draft202012Validator.check_schema(EDIT_PLAN_SCHEMA) is None
    assert _validate(_plan()) == []
    admitted = admit_edit_plan(
        _plan(),
        issued_refs=ISSUED,
        expected_context_revision=CONTEXT,
        expected_workspace_base_revision=WORKSPACE,
        expected_edit_source_revision=EDIT_SOURCE,
        expected_basis_ref=None,
    )
    assert admitted["contract_id"] == "metis-brain-edit-plan/v2"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["operations"][0].update(node_ref="hostref:catalog:video"),
        lambda value: value["operations"][0].update(payload_ref="catalog.video.title"),
        lambda value: value.update(path="hostref:path"),
        lambda value: value.update(source="hostref:source"),
        lambda value: value.update(placement="before"),
        lambda value: value.update(mode="own-lines"),
    ],
)
def test_invented_authority_or_extra_properties_fail_closed(mutation) -> None:
    value = _plan()
    mutation(value)
    assert _validate(value)


def test_unknown_reference_is_rejected_even_when_opaque() -> None:
    value = _plan()
    value["operations"][0]["payload_ref"] = "hostref:model-invented"
    assert _validate(value)
    with pytest.raises(BrainError, match="reference"):
        admit_edit_plan(
            value,
            issued_refs=ISSUED,
            expected_context_revision=CONTEXT,
            expected_workspace_base_revision=WORKSPACE,
            expected_edit_source_revision=EDIT_SOURCE,
            expected_basis_ref=None,
        )


def test_discriminated_operation_shapes_are_closed() -> None:
    insert = _plan()
    insert["operations"] = [
        {
            "ordinal": 0,
            "kind": "insert",
            "slot_ref": "hostref:slot-1",
            "payload_ref": "hostref:payload-1",
        }
    ]
    assert _validate(insert, issued=ISSUED | {"hostref:slot-1"} - {"hostref:node-1"}) == []

    delete = _plan()
    delete["operations"] = [
        {
            "ordinal": 0,
            "kind": "delete",
            "delete_ref": "hostref:delete-1",
        }
    ]
    delete_refs = (ISSUED - {"hostref:node-1", "hostref:payload-1"}) | {"hostref:delete-1"}
    assert _validate(delete, issued=delete_refs) == []

    malformed = deepcopy(insert)
    malformed["operations"][0]["placement"] = "before"
    assert _validate(malformed)


def test_duplicate_refs_order_and_empty_operations_are_rejected() -> None:
    duplicate = _plan()
    duplicate["operations"][0]["payload_ref"] = duplicate["operations"][0]["node_ref"]
    assert "duplicate" in _validate(duplicate)[0]

    reordered = _plan()
    operation = deepcopy(reordered["operations"][0])
    reordered["operations"][0]["ordinal"] = 1
    operation["ordinal"] = 0
    operation["node_ref"] = "hostref:node-2"
    operation["payload_ref"] = "hostref:payload-2"
    reordered["operations"].append(operation)
    assert (
        "ordered"
        in _validate(reordered, issued=ISSUED | {"hostref:node-2", "hostref:payload-2"})[0]
    )

    empty = _plan()
    empty["operations"] = []
    assert _validate(empty)


def test_context_workspace_edit_source_and_basis_are_independent() -> None:
    value = _plan()
    value["context_revision"] = "sha256:" + "e" * 64
    assert "context" in _validate(value)[0]

    value = _plan()
    value["workspace_base_revision"] = "sha256:" + "e" * 64
    assert "workspace" in _validate(value)[0]

    value = _plan()
    value["edit_source_revision"] = "sha256:" + "e" * 64
    assert "edit source" in _validate(value)[0]

    value = _plan()
    value["basis_ref"] = "hostref:basis-1"
    assert (
        _validate(
            value,
            issued=ISSUED | {"hostref:basis-1"},
            basis="hostref:basis-1",
        )
        == []
    )
    assert _validate(value, issued=ISSUED | {"hostref:basis-1"})


def test_admitted_plan_is_detached_from_input() -> None:
    value = _plan()
    admitted = admit_edit_plan(
        value,
        issued_refs=ISSUED,
        expected_context_revision=CONTEXT,
        expected_workspace_base_revision=WORKSPACE,
        expected_edit_source_revision=EDIT_SOURCE,
        expected_basis_ref=None,
    )
    value["operations"][0]["payload_ref"] = "hostref:model-invented"
    assert admitted["operations"][0]["payload_ref"] == "hostref:payload-1"
