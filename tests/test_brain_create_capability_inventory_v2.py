from __future__ import annotations

from dataclasses import replace

import pytest

from metis_model1.brain_create_capability_inventory_v2 import (
    CREATE_V2_AUTHORITY_POLICY_SHA256,
    build_pinned_create_v2_capability_inventory,
    validate_pinned_create_v2_inventory,
)
from metis_model1.brain_create_structural_authority_v2 import (
    STRUCTURAL_CREATE_IMPLEMENTATION_SHA256,
)
from metis_model1.brain_protocol import BrainError, bytes_sha256

TOOLCHAIN = bytes_sha256(b"production-toolchain")


def test_inventory_is_deterministic_and_bound_to_current_code() -> None:
    first = build_pinned_create_v2_capability_inventory(toolchain_binding=TOOLCHAIN)
    second = build_pinned_create_v2_capability_inventory(toolchain_binding=TOOLCHAIN)

    assert first == second
    assert validate_pinned_create_v2_inventory(first) is first
    assert first.policy_revision == CREATE_V2_AUTHORITY_POLICY_SHA256
    assert first.structural_implementation_sha256 == STRUCTURAL_CREATE_IMPLEMENTATION_SHA256
    assert tuple(item.value for item in first.capabilities) == (True, False)
    assert all(item.member == "needs_time" for item in first.capabilities)


@pytest.mark.parametrize(
    "member,value",
    (
        ("builder_schema_sha256", bytes_sha256(b"forged-builder")),
        ("policy_revision", bytes_sha256(b"forged-policy")),
        ("structural_implementation_sha256", bytes_sha256(b"forged-structural")),
        ("inventory_revision", bytes_sha256(b"forged-inventory")),
        ("capabilities", ()),
    ),
)
def test_inventory_reopens_code_pins_and_rejects_drift(member: str, value: object) -> None:
    inventory = build_pinned_create_v2_capability_inventory(toolchain_binding=TOOLCHAIN)

    with pytest.raises(BrainError) as caught:
        validate_pinned_create_v2_inventory(replace(inventory, **{member: value}))

    assert caught.value.code == "CREATE_V2_CAPABILITY_INVALID"


def test_inventory_revision_changes_with_toolchain() -> None:
    first = build_pinned_create_v2_capability_inventory(toolchain_binding=TOOLCHAIN)
    second = build_pinned_create_v2_capability_inventory(
        toolchain_binding=bytes_sha256(b"other-production-toolchain")
    )

    assert first.inventory_revision != second.inventory_revision
