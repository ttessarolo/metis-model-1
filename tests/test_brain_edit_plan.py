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

REVISION = "sha256:" + "a" * 64
SOURCE = "sha256:" + "b" * 64
PREIMAGE = "sha256:" + "c" * 64


def _plan() -> dict[str, object]:
    return {
        "schema_version": 1,
        "contract_id": EDIT_PLAN_CONTRACT,
        "context_revision": REVISION,
        "source_revision": SOURCE,
        "target_ref": "hostref:target-1",
        "base_ref": "hostref:base-1",
        "operations": [
            {
                "ordinal": 0,
                "kind": "replace",
                "target_ref": "hostref:node-1",
                "anchor_ref": None,
                "payload_ref": "hostref:payload-1",
                "preimage_sha256": PREIMAGE,
            }
        ],
    }


ISSUED = {"hostref:target-1", "hostref:base-1", "hostref:node-1", "hostref:payload-1"}


def test_schema_and_host_validator_accept_only_opaque_host_refs() -> None:
    assert Draft202012Validator.check_schema(EDIT_PLAN_SCHEMA) is None
    assert (
        validate_edit_plan(
            _plan(),
            issued_refs=ISSUED,
            expected_context_revision=REVISION,
            expected_source_revision=SOURCE,
        )
        == []
    )
    admitted = admit_edit_plan(
        _plan(),
        issued_refs=ISSUED,
        expected_context_revision=REVISION,
        expected_source_revision=SOURCE,
    )
    assert admitted["contract_id"] == EDIT_PLAN_CONTRACT


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["operations"][0].update(target_ref="hostref:catalog:video"),
        lambda value: value["operations"][0].update(payload_ref="catalog.video.title"),
        lambda value: value["operations"][0].update(payload_ref="hostref:raw-source"),
        lambda value: value.update(path="hostref:path"),
        lambda value: value.update(source="hostref:source"),
        lambda value: value.update(fallback="hostref:fallback"),
    ],
)
def test_invented_authority_or_extra_properties_fail_closed(mutation) -> None:
    value = _plan()
    mutation(value)
    assert validate_edit_plan(
        value,
        issued_refs=ISSUED,
        expected_context_revision=REVISION,
        expected_source_revision=SOURCE,
    )


def test_unknown_reference_is_rejected_even_when_opaque() -> None:
    value = _plan()
    value["operations"][0]["payload_ref"] = "hostref:model-invented"
    assert validate_edit_plan(
        value,
        issued_refs=ISSUED,
        expected_context_revision=REVISION,
        expected_source_revision=SOURCE,
    )
    with pytest.raises(BrainError, match="reference"):
        admit_edit_plan(
            value,
            issued_refs=ISSUED,
            expected_context_revision=REVISION,
            expected_source_revision=SOURCE,
        )


def test_duplicate_refs_reorder_and_cardinality_are_rejected() -> None:
    duplicate = _plan()
    duplicate["operations"][0]["payload_ref"] = duplicate["operations"][0]["target_ref"]
    assert (
        "duplicate"
        in validate_edit_plan(
            duplicate,
            issued_refs=ISSUED,
            expected_context_revision=REVISION,
            expected_source_revision=SOURCE,
        )[0]
    )

    reordered = _plan()
    operation = deepcopy(reordered["operations"][0])
    reordered["operations"][0]["ordinal"] = 1
    operation["ordinal"] = 0
    operation["target_ref"] = "hostref:node-2"
    operation["payload_ref"] = "hostref:payload-2"
    reordered["operations"].append(operation)
    assert (
        "ordered"
        in validate_edit_plan(
            reordered,
            issued_refs=ISSUED | {"hostref:node-2", "hostref:payload-2"},
            expected_context_revision=REVISION,
            expected_source_revision=SOURCE,
        )[0]
    )

    empty = _plan()
    empty["operations"] = []
    assert validate_edit_plan(
        empty,
        issued_refs=ISSUED,
        expected_context_revision=REVISION,
        expected_source_revision=SOURCE,
    )


def test_operation_shape_enforces_insert_replace_delete_cardinality() -> None:
    value = _plan()
    value["operations"][0].update(kind="insert", anchor_ref=None)
    assert (
        "insert"
        in validate_edit_plan(
            value,
            issued_refs=ISSUED,
            expected_context_revision=REVISION,
            expected_source_revision=SOURCE,
        )[0]
    )
    value = _plan()
    value["operations"][0].update(kind="delete", payload_ref=None)
    assert (
        validate_edit_plan(
            value,
            issued_refs=ISSUED,
            expected_context_revision=REVISION,
            expected_source_revision=SOURCE,
        )
        == []
    )
    value["operations"][0].update(anchor_ref="hostref:anchor-1")
    assert (
        "delete"
        in validate_edit_plan(
            value,
            issued_refs=ISSUED | {"hostref:anchor-1"},
            expected_context_revision=REVISION,
            expected_source_revision=SOURCE,
        )[0]
    )


def test_revision_drift_and_noncanonical_hashes_are_rejected() -> None:
    assert (
        "context revision"
        in validate_edit_plan(
            _plan(),
            issued_refs=ISSUED,
            expected_context_revision="sha256:" + "d" * 64,
            expected_source_revision=SOURCE,
        )[0]
    )
    value = _plan()
    value["source_revision"] = "not-a-hash"
    assert validate_edit_plan(
        value,
        issued_refs=ISSUED,
        expected_context_revision=REVISION,
        expected_source_revision=SOURCE,
    )


def test_plan_does_not_have_a_self_hash_or_model_source_surface() -> None:
    value = _plan()
    value["plan_sha256"] = "sha256:" + "d" * 64
    assert validate_edit_plan(
        value,
        issued_refs=ISSUED,
        expected_context_revision=REVISION,
        expected_source_revision=SOURCE,
    )


def test_admitted_plan_is_detached_from_the_input() -> None:
    value = _plan()
    admitted = admit_edit_plan(
        value,
        issued_refs=ISSUED,
        expected_context_revision=REVISION,
        expected_source_revision=SOURCE,
    )
    value["operations"][0]["payload_ref"] = "hostref:model-invented"
    assert admitted["operations"][0]["payload_ref"] == "hostref:payload-1"
