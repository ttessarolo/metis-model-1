"""Pinned, code-owned capability inventory for the first production CREATE v2 slice.

This module deliberately inventories only capabilities that can be proven from
the tracked private builder and combinator implementations.  It does not read a
tenant, an endpoint instance, or model output.  Catalog
semantics remain a separate reviewed authority boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from metis_model1.brain_create_builder import (
    CREATE_ENDPOINT_SPEC_CONTRACT,
    CREATE_ENDPOINT_SPEC_SCHEMA,
)
from metis_model1.brain_create_combinators import COMBINATOR_IMPLEMENTATION_SHA256
from metis_model1.brain_create_structural_authority_v2 import (
    STRUCTURAL_CREATE_IMPLEMENTATION_SHA256,
)
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json, canonical_sha256

CREATE_V2_CAPABILITY_INVENTORY_CONTRACT = "metis-brain-create-capability-inventory/v2"
CREATE_V2_AUTHORITY_POLICY_ID = "metis-brain-create-authority-policy/production-structural-v2"

_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_MEMBER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")

# Full-utterance recognition is intentional.  A mixed or richer instruction is
# not silently reduced to this small capability and must fail closed upstream.
ENABLE_CURRENT_TIME_COMMANDS = frozenset(
    {
        "abilita il tempo corrente",
        "abilita l'ora corrente",
        "usa il tempo corrente",
        "usa l'ora corrente",
        "enable current time",
        "use current time",
    }
)
DISABLE_CURRENT_TIME_COMMANDS = frozenset(
    {
        "disabilita il tempo corrente",
        "disabilita l'ora corrente",
        "non usare il tempo corrente",
        "non usare l'ora corrente",
        "disable current time",
        "do not use current time",
    }
)
AMBIGUOUS_CURRENT_TIME_COMMANDS = frozenset(
    {
        "configura il tempo corrente",
        "configura l'ora corrente",
        "gestisci il tempo corrente",
        "gestisci l'ora corrente",
        "configure current time",
    }
)

_AUTHORITY_POLICY = {
    "policy_id": CREATE_V2_AUTHORITY_POLICY_ID,
    "recognized_capability": "endpoint.needs_time",
    "recognition": "normalized_full_utterance_only",
    "enable_commands": sorted(ENABLE_CURRENT_TIME_COMMANDS),
    "disable_commands": sorted(DISABLE_CURRENT_TIME_COMMANDS),
    "ambiguous_commands": sorted(AMBIGUOUS_CURRENT_TIME_COMMANDS),
    "semantic_authority": "schema2_reviewed_exact_snapshot_only",
    "exact_value_bridge": "metis-brain-exact-reviewed-value-authority/v1:reviewed_exact_only",
    "cumulative_grounding": (
        "metis-brain-dialogue-cumulative-grounding/v1:admitted_or_explicit_rejection"
    ),
    "structural_archetypes": [
        "descriptor_filtered_collection",
    ],
    "structural_authority": "original_reviewed_descriptor_index_plus_exact_count",
    "structural_confirmation": "exact_filters_count_inventory_and_covered_history",
    "legacy_closed_recipes": "explicit_compatibility_only_disabled_by_default",
    "refinement_basis": "exact_private_latest_head",
    "unknown_structure": "fail_closed",
    "unrequested_fallback": "do_not_add",
}
CREATE_V2_AUTHORITY_POLICY_SHA256 = canonical_sha256(_AUTHORITY_POLICY)


def _fail(message: str) -> None:
    raise BrainError("CREATE_V2_CAPABILITY_INVALID", 500, message)


def _hash(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        _fail(f"{label} is invalid")
    return value


def _builder_schema_sha256() -> str:
    return bytes_sha256(canonical_json(CREATE_ENDPOINT_SPEC_SCHEMA))


def _combinator_roster() -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted((name, digest) for name, digest in COMBINATOR_IMPLEMENTATION_SHA256.items())
    )


@dataclass(frozen=True, slots=True)
class CreateV2CodeCapability:
    """One exact builder member/value pair admitted by host code."""

    key: str
    label: str
    member: str
    fragment_type: str
    value: bool
    required_role: str = "scalar"
    mutation: str = "set"

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or _KEY_RE.fullmatch(self.key) is None:
            _fail("capability key is invalid")
        if not isinstance(self.label, str) or not self.label.strip() or len(self.label) > 160:
            _fail("capability label is invalid")
        if not isinstance(self.member, str) or _MEMBER_RE.fullmatch(self.member) is None:
            _fail("capability member is invalid")
        if self.fragment_type != "boolean" or type(self.value) is not bool:
            _fail("capability fragment is invalid")
        if self.required_role != "scalar" or self.mutation != "set":
            _fail("capability role or mutation is invalid")

    def manifest(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "member": self.member,
            "fragment_type": self.fragment_type,
            "value": self.value,
            "required_role": self.required_role,
            "mutation": self.mutation,
        }


_EXPECTED_CAPABILITIES = (
    CreateV2CodeCapability(
        key="capability:endpoint.needs_time.enable",
        label="Abilita il tempo corrente",
        member="needs_time",
        fragment_type="boolean",
        value=True,
    ),
    CreateV2CodeCapability(
        key="capability:endpoint.needs_time.disable",
        label="Disabilita il tempo corrente",
        member="needs_time",
        fragment_type="boolean",
        value=False,
    ),
)


@dataclass(frozen=True, slots=True)
class PinnedCreateV2CapabilityInventory:
    """Content-addressed code authority for one exact Brain toolchain."""

    toolchain_binding: str
    inventory_revision: str
    builder_contract: str
    builder_schema_sha256: str
    combinator_implementation_sha256: tuple[tuple[str, str], ...]
    structural_implementation_sha256: str
    capabilities: tuple[CreateV2CodeCapability, ...]
    policy_revision: str
    contract_id: str = CREATE_V2_CAPABILITY_INVENTORY_CONTRACT

    def __post_init__(self) -> None:
        _hash(self.toolchain_binding, label="toolchain binding")
        _hash(self.inventory_revision, label="inventory revision")
        _hash(self.builder_schema_sha256, label="builder schema hash")
        _hash(self.structural_implementation_sha256, label="structural implementation hash")
        _hash(self.policy_revision, label="policy revision")
        if self.contract_id != CREATE_V2_CAPABILITY_INVENTORY_CONTRACT:
            _fail("inventory contract differs")
        if self.builder_contract != CREATE_ENDPOINT_SPEC_CONTRACT:
            _fail("builder contract differs")
        if type(self.combinator_implementation_sha256) is not tuple:
            _fail("combinator roster is invalid")
        names: list[str] = []
        for item in self.combinator_implementation_sha256:
            if (
                type(item) is not tuple
                or len(item) != 2
                or not isinstance(item[0], str)
                or not item[0]
            ):
                _fail("combinator roster is invalid")
            _hash(item[1], label="combinator implementation hash")
            names.append(item[0])
        if names != sorted(names) or len(names) != len(set(names)):
            _fail("combinator roster is not canonical")
        if (
            type(self.capabilities) is not tuple
            or not self.capabilities
            or any(type(item) is not CreateV2CodeCapability for item in self.capabilities)
            or len({item.key for item in self.capabilities}) != len(self.capabilities)
        ):
            _fail("capability roster is invalid")

    def manifest(self, *, include_revision: bool = True) -> dict[str, Any]:
        result = {
            "contract_id": self.contract_id,
            "toolchain_binding": self.toolchain_binding,
            "builder_contract": self.builder_contract,
            "builder_schema_sha256": self.builder_schema_sha256,
            "combinator_implementation_sha256": [
                {"recipe_id": name, "sha256": digest}
                for name, digest in self.combinator_implementation_sha256
            ],
            "structural_implementation_sha256": self.structural_implementation_sha256,
            "capabilities": [item.manifest() for item in self.capabilities],
            "policy_revision": self.policy_revision,
        }
        if include_revision:
            result["inventory_revision"] = self.inventory_revision
        return result

    def capability(self, key: str) -> CreateV2CodeCapability:
        matches = tuple(item for item in self.capabilities if item.key == key)
        if len(matches) != 1:
            _fail("capability is unavailable")
        return matches[0]


def create_v2_capability_inventory_revision(
    inventory: PinnedCreateV2CapabilityInventory,
) -> str:
    if not isinstance(inventory, PinnedCreateV2CapabilityInventory):
        _fail("inventory is invalid")
    return canonical_sha256(inventory.manifest(include_revision=False))


def validate_pinned_create_v2_inventory(
    inventory: PinnedCreateV2CapabilityInventory,
) -> PinnedCreateV2CapabilityInventory:
    """Reopen every local code pin and return only an exact current inventory."""

    if not isinstance(inventory, PinnedCreateV2CapabilityInventory):
        _fail("inventory is invalid")
    if inventory.builder_schema_sha256 != _builder_schema_sha256():
        _fail("builder schema drifted")
    if inventory.combinator_implementation_sha256 != _combinator_roster():
        _fail("combinator implementation drifted")
    if inventory.structural_implementation_sha256 != STRUCTURAL_CREATE_IMPLEMENTATION_SHA256:
        _fail("structural authority implementation drifted")
    if inventory.capabilities != _EXPECTED_CAPABILITIES:
        _fail("code capability roster drifted")
    if inventory.policy_revision != CREATE_V2_AUTHORITY_POLICY_SHA256:
        _fail("authority policy drifted")
    if inventory.inventory_revision != create_v2_capability_inventory_revision(inventory):
        _fail("inventory revision differs")
    return inventory


def build_pinned_create_v2_capability_inventory(
    *, toolchain_binding: str
) -> PinnedCreateV2CapabilityInventory:
    _hash(toolchain_binding, label="toolchain binding")
    provisional = PinnedCreateV2CapabilityInventory(
        toolchain_binding=toolchain_binding,
        inventory_revision="sha256:" + "0" * 64,
        builder_contract=CREATE_ENDPOINT_SPEC_CONTRACT,
        builder_schema_sha256=_builder_schema_sha256(),
        combinator_implementation_sha256=_combinator_roster(),
        structural_implementation_sha256=STRUCTURAL_CREATE_IMPLEMENTATION_SHA256,
        capabilities=_EXPECTED_CAPABILITIES,
        policy_revision=CREATE_V2_AUTHORITY_POLICY_SHA256,
    )
    inventory = PinnedCreateV2CapabilityInventory(
        toolchain_binding=provisional.toolchain_binding,
        inventory_revision=create_v2_capability_inventory_revision(provisional),
        builder_contract=provisional.builder_contract,
        builder_schema_sha256=provisional.builder_schema_sha256,
        combinator_implementation_sha256=provisional.combinator_implementation_sha256,
        structural_implementation_sha256=provisional.structural_implementation_sha256,
        capabilities=provisional.capabilities,
        policy_revision=provisional.policy_revision,
    )
    return validate_pinned_create_v2_inventory(inventory)


__all__ = [
    "AMBIGUOUS_CURRENT_TIME_COMMANDS",
    "CREATE_V2_AUTHORITY_POLICY_ID",
    "CREATE_V2_AUTHORITY_POLICY_SHA256",
    "CREATE_V2_CAPABILITY_INVENTORY_CONTRACT",
    "CreateV2CodeCapability",
    "DISABLE_CURRENT_TIME_COMMANDS",
    "ENABLE_CURRENT_TIME_COMMANDS",
    "PinnedCreateV2CapabilityInventory",
    "build_pinned_create_v2_capability_inventory",
    "create_v2_capability_inventory_revision",
    "validate_pinned_create_v2_inventory",
]
