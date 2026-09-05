from __future__ import annotations

import math

import pytest

from metis_model1.brain_create_ir import (
    CREATE_IR_DELTA_CONTRACT,
    MAX_IR_DEPTH,
    CreateIrStageProof,
    canonical_ir_delta,
    create_ir_stage_proof,
    isolated_ir,
    verify_ir_stage,
)
from metis_model1.brain_protocol import BrainError, canonical_sha256


def _parent() -> dict[str, object]:
    return {
        "kind": "Endpoint",
        "name": "demo.create",
        "blocks": [{"name": "main", "take": 24}],
        "paginate": None,
    }


def test_initial_stage_is_one_exact_root_add() -> None:
    child = _parent()
    delta = canonical_ir_delta(None, child)

    assert delta == {
        "schema_version": 1,
        "contract_id": CREATE_IR_DELTA_CONTRACT,
        "parent_ir_sha256": None,
        "child_ir_sha256": canonical_sha256(child),
        "operations": [
            {
                "kind": "add",
                "path": "",
                "before_sha256": None,
                "after_sha256": canonical_sha256(child),
            }
        ],
    }


def test_delta_is_key_order_independent_but_array_order_exact() -> None:
    parent = _parent()
    same = {
        "paginate": None,
        "blocks": [{"take": 24, "name": "main"}],
        "name": "demo.create",
        "kind": "Endpoint",
    }
    assert canonical_ir_delta(parent, same)["operations"] == []

    reordered = dict(same)
    reordered["blocks"] = [
        {"name": "fallback", "take": 24},
        {"name": "main", "take": 24},
    ]
    operations = canonical_ir_delta(parent, reordered)["operations"]
    assert operations == [
        {
            "kind": "replace",
            "path": "/blocks",
            "before_sha256": canonical_sha256(parent["blocks"]),
            "after_sha256": canonical_sha256(reordered["blocks"]),
        }
    ]


def test_mapping_delta_has_canonical_paths_and_exact_node_hashes() -> None:
    parent = _parent()
    child = {
        "kind": "Endpoint",
        "name": "demo.create",
        "blocks": parent["blocks"],
        "fallback/key~name": "recent",
    }

    delta = canonical_ir_delta(parent, child)
    assert delta["operations"] == [
        {
            "kind": "remove",
            "path": "/paginate",
            "before_sha256": canonical_sha256(None),
            "after_sha256": None,
        },
        {
            "kind": "add",
            "path": "/fallback~1key~0name",
            "before_sha256": None,
            "after_sha256": canonical_sha256("recent"),
        },
    ]


def test_stage_proof_rejects_extra_missing_and_parent_drift() -> None:
    parent = _parent()
    child = {**parent, "fallback": "recent"}
    proof = create_ir_stage_proof(parent, child)

    assert verify_ir_stage(parent_ir=parent, child_ir=child, expected=proof) == proof
    for wrong_parent, wrong_child in (
        (parent, {**child, "extra": True}),
        (parent, parent),
        ({**parent, "blocks": []}, child),
    ):
        with pytest.raises(BrainError) as raised:
            verify_ir_stage(
                parent_ir=wrong_parent,
                child_ir=wrong_child,
                expected=proof,
            )
        assert raised.value.code == "CREATE_IR_MISMATCH"


def test_expected_proof_must_be_the_exact_type() -> None:
    with pytest.raises(BrainError) as raised:
        verify_ir_stage(parent_ir=None, child_ir=_parent(), expected=object())  # type: ignore[arg-type]
    assert raised.value.code == "CREATE_IR_INVALID"


def test_ir_copy_is_isolated_and_non_json_values_fail_closed() -> None:
    source = _parent()
    copied = isolated_ir(source)
    copied["blocks"][0]["take"] = 99
    assert source["blocks"] == [{"name": "main", "take": 24}]

    for invalid in ({"bad": math.nan}, {"bad": {1, 2}}, {1: "bad"}):
        with pytest.raises(BrainError) as raised:
            isolated_ir(invalid)
        assert raised.value.code == "CREATE_IR_INVALID"


def test_ir_depth_is_bounded() -> None:
    value: object = "leaf"
    for _ in range(MAX_IR_DEPTH + 2):
        value = [value]
    with pytest.raises(BrainError) as raised:
        isolated_ir(value)
    assert raised.value.code == "CREATE_IR_INVALID"


def test_proof_dataclass_is_hash_only() -> None:
    proof = create_ir_stage_proof(None, _parent())
    assert isinstance(proof, CreateIrStageProof)
    assert set(proof.__dataclass_fields__) == {
        "ir_sha256",
        "parent_ir_sha256",
        "delta_sha256",
        "delta_operation_count",
    }
