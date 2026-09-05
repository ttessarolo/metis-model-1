from __future__ import annotations

from metis_model1.brain_create_authority_issuer_v2 import CreateV2HostRefIssuer
from metis_model1.brain_create_capability_inventory_v2 import (
    build_pinned_create_v2_capability_inventory,
)
from metis_model1.brain_create_plan_v2 import NodeGrant, SlotGrant
from metis_model1.brain_protocol import bytes_sha256

TOOLCHAIN = bytes_sha256(b"production-toolchain")
INVENTORY = build_pinned_create_v2_capability_inventory(toolchain_binding=TOOLCHAIN)
ISSUER = CreateV2HostRefIssuer(hmac_key=b"k" * 32)
HASHES = {
    "history_revision": bytes_sha256(b"history"),
    "context_revision": bytes_sha256(b"context"),
    "semantic_revision": bytes_sha256(b"semantic"),
}


def _issue_ref(**changes: object) -> str:
    values: dict[str, object] = {
        "namespace": "node",
        "session_id": "s" * 43,
        **HASHES,
        "toolchain_binding": TOOLCHAIN,
        "inventory_revision": INVENTORY.inventory_revision,
        "policy_revision": INVENTORY.policy_revision,
        "generation": 0,
        "identity": {"member": "needs_time", "value": True},
    }
    values.update(changes)
    return ISSUER.issue_ref(**values)  # type: ignore[arg-type]


def test_host_refs_bind_every_required_authority_dimension() -> None:
    baseline = _issue_ref()
    variants = (
        _issue_ref(session_id="t" * 43),
        _issue_ref(history_revision=bytes_sha256(b"other-history")),
        _issue_ref(context_revision=bytes_sha256(b"other-context")),
        _issue_ref(semantic_revision=bytes_sha256(b"other-semantic")),
        _issue_ref(toolchain_binding=bytes_sha256(b"other-toolchain")),
        _issue_ref(inventory_revision=bytes_sha256(b"other-inventory")),
        _issue_ref(policy_revision=bytes_sha256(b"other-policy")),
        _issue_ref(generation=1),
    )

    assert all(item != baseline for item in variants)
    assert len(set(variants)) == len(variants)


def test_issuer_produces_a_minimal_valid_boolean_projection() -> None:
    result = ISSUER.issue_needs_time_authority(
        inventory=INVENTORY,
        session_id="s" * 43,
        conversation_id=bytes_sha256(b"conversation"),
        request_fingerprint=bytes_sha256(b"request"),
        endpoint="demo.endpoint",
        candidate_filename="brain-drafts/demo.metis",
        enabled=True,
        origin="operator",
        evidence_identity={"message_ordinal": 0},
        generation=0,
        parent_spec_sha256=None,
        parent_ir_sha256=None,
        parent_proposal_ref=None,
        toolchain_binding=TOOLCHAIN,
        **HASHES,
    )

    assert result.basis_ref is None
    assert result.active_requirement_handles == (0,)
    slot = next(item for item in result.projection.authorities if type(item) is SlotGrant)
    node = next(item for item in result.projection.authorities if type(item) is NodeGrant)
    assert slot.member == "needs_time"
    assert node.fragment is True
    assert node.parent_slot_ref == slot.ref
    assert result.target_ref.startswith("hostref:target:")
