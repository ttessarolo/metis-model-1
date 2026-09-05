"""Session-bound issuer for compact production CREATE v2 authority.

The issuer expands one already-adjudicated code capability into opaque refs and
an exact private projection.  It performs no natural-language interpretation
and no I/O.
"""

from __future__ import annotations

import copy
import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Literal

from metis_model1.brain_create_capability_inventory_v2 import (
    PinnedCreateV2CapabilityInventory,
    validate_pinned_create_v2_inventory,
)
from metis_model1.brain_create_plan_v2 import (
    CompactAuthorityProjection,
    FragmentLeafBinding,
    NodeGrant,
    RequirementHandle,
    SlotGrant,
    compact_authority_projection_revision,
    validate_compact_authority_projection,
)
from metis_model1.brain_create_structural_authority_v2 import (
    StructuralIntent,
    validate_structural_intent,
)
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json, canonical_sha256

CREATE_V2_HOST_REF_ISSUER_CONTRACT = "metis-brain-create-host-ref-issuer/v2"

_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{32,96}$")
_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,20}$")
_ENDPOINT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,95}(?:\.[A-Za-z_][A-Za-z0-9_-]{0,95})*$")


def _fail(message: str, *, code: str = "CREATE_V2_AUTHORITY_ISSUER_INVALID") -> None:
    raise BrainError(code, 500, message)


def _hash(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        _fail(f"{label} is invalid")
    return value


@dataclass(frozen=True, slots=True, repr=False)
class IssuedCreateV2Authority:
    projection: CompactAuthorityProjection
    active_requirement_handles: tuple[int, ...]
    target_ref: str
    basis_ref: str | None

    def __post_init__(self) -> None:
        validate_compact_authority_projection(self.projection)
        known = {item.handle for item in self.projection.requirements}
        if (
            not self.active_requirement_handles
            or len(self.active_requirement_handles) != len(set(self.active_requirement_handles))
            or any(item not in known for item in self.active_requirement_handles)
        ):
            _fail("active requirement roster is invalid")


class CreateV2HostRefIssuer:
    """Issue refs scoped to every mutable authority dimension."""

    __slots__ = ("_closed", "_secret")

    def __init__(self, *, hmac_key: bytes) -> None:
        if not isinstance(hmac_key, bytes) or not 32 <= len(hmac_key) <= 128:
            raise ValueError("CREATE v2 authority HMAC key is invalid")
        self._secret = bytearray(hmac_key)
        self._closed = False

    def close(self) -> None:
        """Retire this process-local issuer and overwrite its mutable key copy."""

        if self._closed:
            return
        for index in range(len(self._secret)):
            self._secret[index] = 0
        self._closed = True

    def issue_ref(
        self,
        *,
        namespace: str,
        session_id: str,
        history_revision: str,
        context_revision: str,
        semantic_revision: str,
        toolchain_binding: str,
        inventory_revision: str,
        policy_revision: str,
        generation: int,
        identity: Mapping[str, Any],
    ) -> str:
        if self._closed:
            _fail("host ref issuer is closed", code="CREATE_V2_AUTHORITY_RETIRED")
        if not isinstance(namespace, str) or _NAMESPACE_RE.fullmatch(namespace) is None:
            _fail("host ref namespace is invalid")
        if not isinstance(session_id, str) or _SESSION_RE.fullmatch(session_id) is None:
            _fail("host ref session is invalid")
        for value, label in (
            (history_revision, "history revision"),
            (context_revision, "context revision"),
            (semantic_revision, "semantic revision"),
            (toolchain_binding, "toolchain binding"),
            (inventory_revision, "inventory revision"),
            (policy_revision, "policy revision"),
        ):
            _hash(value, label=label)
        if type(generation) is not int or not 0 <= generation <= 20:
            _fail("host ref generation is invalid")
        if not isinstance(identity, Mapping):
            _fail("host ref identity is invalid")
        material = canonical_json(
            {
                "contract_id": CREATE_V2_HOST_REF_ISSUER_CONTRACT,
                "namespace": namespace,
                "session_id": session_id,
                "history_revision": history_revision,
                "context_revision": context_revision,
                "semantic_revision": semantic_revision,
                "toolchain_binding": toolchain_binding,
                "inventory_revision": inventory_revision,
                "policy_revision": policy_revision,
                "generation": generation,
                "identity": dict(identity),
            }
        )
        digest = hmac.new(bytes(self._secret), material, sha256).hexdigest()
        return f"hostref:{namespace}:{digest[:48]}"

    def issue_structural_authority(
        self,
        *,
        inventory: PinnedCreateV2CapabilityInventory,
        intent: StructuralIntent,
        session_id: str,
        conversation_id: str,
        request_fingerprint: str,
        history_revision: str,
        context_revision: str,
        semantic_revision: str,
        toolchain_binding: str,
        generation: int,
        endpoint: str,
        candidate_filename: str,
        parent_spec_sha256: str | None,
        parent_ir_sha256: str | None,
        parent_proposal_ref: str | None,
    ) -> IssuedCreateV2Authority:
        """Issue direct grants for one already-resolved generic structural intent."""

        inventory = validate_pinned_create_v2_inventory(inventory)
        if inventory.toolchain_binding != toolchain_binding:
            _fail("inventory toolchain differs", code="CREATE_V2_AUTHORITY_STALE")
        validate_structural_intent(intent, policy_revision=inventory.policy_revision)
        if (
            _HASH_RE.fullmatch(conversation_id or "") is None
            or _HASH_RE.fullmatch(request_fingerprint or "") is None
        ):
            _fail("conversation binding is invalid")
        if not isinstance(endpoint, str) or _ENDPOINT_RE.fullmatch(endpoint) is None:
            _fail("endpoint identity is invalid")
        if not isinstance(candidate_filename, str) or not candidate_filename.endswith(".metis"):
            _fail("candidate filename is invalid")
        if generation == 0:
            if any(
                value is not None
                for value in (parent_spec_sha256, parent_ir_sha256, parent_proposal_ref)
            ):
                _fail("initial authority has a parent", code="CREATE_V2_AUTHORITY_STALE")
        else:
            _hash(parent_spec_sha256, label="parent spec hash")
            _hash(parent_ir_sha256, label="parent IR hash")
            if not isinstance(parent_proposal_ref, str) or not parent_proposal_ref:
                _fail("refinement parent is invalid", code="CREATE_V2_AUTHORITY_STALE")

        common = {
            "session_id": session_id,
            "history_revision": history_revision,
            "context_revision": context_revision,
            "semantic_revision": semantic_revision,
            "toolchain_binding": toolchain_binding,
            "inventory_revision": inventory.inventory_revision,
            "policy_revision": inventory.policy_revision,
            "generation": generation,
        }

        def ref(namespace: str, identity: Mapping[str, Any]) -> str:
            return self.issue_ref(
                namespace=namespace,
                identity={
                    "conversation_id": conversation_id,
                    "request_fingerprint": request_fingerprint,
                    **dict(identity),
                },
                **common,
            )

        target_ref = ref(
            "target",
            {"endpoint": endpoint, "candidate_filename": candidate_filename},
        )
        basis_ref = (
            None
            if generation == 0
            else ref(
                "basis",
                {
                    "parent_spec_sha256": parent_spec_sha256,
                    "parent_ir_sha256": parent_ir_sha256,
                    "parent_proposal_ref": parent_proposal_ref,
                },
            )
        )
        requirements: list[RequirementHandle] = []
        authorities: list[SlotGrant | NodeGrant] = []
        mutation_manifest: list[dict[str, Any]] = []
        for index, mutation in enumerate(intent.mutations):
            requirement_ref = ref(
                "requirement",
                {"family": intent.family, "ordinal": index, "action": mutation.action},
            )
            requirements.append(
                RequirementHandle(
                    handle=index,
                    ref=requirement_ref,
                    label=mutation.requirement_label,
                    allowed_ops=frozenset({mutation.action}),
                )
            )
            slot_ref = ref(
                "slot",
                {
                    "family": intent.family,
                    "ordinal": index,
                    "member": mutation.member,
                    "placement": [mutation.cardinality, mutation.insertion],
                },
            )
            authorities.append(
                SlotGrant(
                    handle=10 + index * 2,
                    ref=slot_ref,
                    label=f"Destinazione {mutation.label.lower()}",
                    anchor_ref=target_ref,
                    member=mutation.member,
                    cardinality=mutation.cardinality,
                    accepts=(mutation.fragment_type,),
                    # A remove operation names its basis node directly.  The
                    # slot is still projected as an exact locator parent, but
                    # it cannot make that basis node attachable.
                    mutations=frozenset(
                        {mutation.action} if mutation.action != "remove" else {"attach"}
                    ),
                    insertion=mutation.insertion,
                    basis_spec_sha256=parent_spec_sha256,
                    generation=generation,
                )
            )
            fragment_sha256 = bytes_sha256(canonical_json(mutation.fragment))
            node_ref = ref(
                "node",
                {
                    "family": intent.family,
                    "ordinal": index,
                    "action": mutation.action,
                    "member": mutation.member,
                    "fragment_type": mutation.fragment_type,
                    "fragment_sha256": fragment_sha256,
                    "basis_path": list(mutation.basis_path) if mutation.basis_path else None,
                },
            )
            leaf_bindings: list[FragmentLeafBinding] = []
            for leaf in mutation.leaf_evidence:
                evidence_ref = ref(
                    "evidence",
                    {
                        "family": intent.family,
                        "ordinal": index,
                        "pointer": leaf.json_pointer,
                        "origin": leaf.origin,
                        "identity": dict(leaf.identity),
                        "semantic_proof_revision": intent.semantic_proof_revision,
                    },
                )
                leaf_bindings.append(
                    FragmentLeafBinding(
                        json_pointer=leaf.json_pointer,
                        evidence_ref=evidence_ref,
                        requirement_refs=(requirement_ref,),
                        origin=leaf.origin,
                    )
                )
            authorities.append(
                NodeGrant(
                    handle=11 + index * 2,
                    ref=node_ref,
                    label=mutation.label,
                    state="basis" if mutation.action == "remove" else "new",
                    fragment_type=mutation.fragment_type,
                    fragment=copy.deepcopy(mutation.fragment),
                    fragment_sha256=fragment_sha256,
                    leaf_bindings=tuple(leaf_bindings),
                    basis_spec_sha256=(parent_spec_sha256 if mutation.action == "remove" else None),
                    basis_path=mutation.basis_path,
                    parent_slot_ref=slot_ref,
                    removable=mutation.action == "remove",
                )
            )
            mutation_manifest.append(
                {
                    "action": mutation.action,
                    "member": mutation.member,
                    "fragment_type": mutation.fragment_type,
                    "fragment_sha256": fragment_sha256,
                    "basis_path": list(mutation.basis_path) if mutation.basis_path else None,
                }
            )
        surface_revision = canonical_sha256(
            {
                "contract_id": "metis-brain-create-authority-surface/v2",
                "session_id": session_id,
                "conversation_id": conversation_id,
                "request_fingerprint": request_fingerprint,
                "history_revision": history_revision,
                "context_revision": context_revision,
                "semantic_revision": semantic_revision,
                "semantic_proof_revision": intent.semantic_proof_revision,
                "toolchain_binding": toolchain_binding,
                "inventory_revision": inventory.inventory_revision,
                "policy_revision": inventory.policy_revision,
                "generation": generation,
                "target_ref": target_ref,
                "basis_ref": basis_ref,
                "family": intent.family,
                "mutations": mutation_manifest,
            }
        )
        projection = CompactAuthorityProjection(
            projection_revision=compact_authority_projection_revision(
                surface_revision=surface_revision,
                requirements=requirements,
                authorities=authorities,
            ),
            surface_revision=surface_revision,
            requirements=tuple(requirements),
            authorities=tuple(authorities),
        )
        validate_compact_authority_projection(projection)
        return IssuedCreateV2Authority(
            projection,
            tuple(range(len(requirements))),
            target_ref,
            basis_ref,
        )

    def issue_needs_time_authority(
        self,
        *,
        inventory: PinnedCreateV2CapabilityInventory,
        session_id: str,
        conversation_id: str,
        request_fingerprint: str,
        history_revision: str,
        context_revision: str,
        semantic_revision: str,
        toolchain_binding: str,
        generation: int,
        endpoint: str,
        candidate_filename: str,
        enabled: bool,
        origin: Literal["operator", "clarification"],
        evidence_identity: Mapping[str, Any],
        parent_spec_sha256: str | None,
        parent_ir_sha256: str | None,
        parent_proposal_ref: str | None,
    ) -> IssuedCreateV2Authority:
        inventory = validate_pinned_create_v2_inventory(inventory)
        if inventory.toolchain_binding != toolchain_binding:
            _fail("inventory toolchain differs", code="CREATE_V2_AUTHORITY_STALE")
        if (
            _HASH_RE.fullmatch(conversation_id or "") is None
            or _HASH_RE.fullmatch(request_fingerprint or "") is None
        ):
            _fail("conversation binding is invalid")
        if not isinstance(endpoint, str) or _ENDPOINT_RE.fullmatch(endpoint) is None:
            _fail("endpoint identity is invalid")
        if not isinstance(candidate_filename, str) or not candidate_filename.endswith(".metis"):
            _fail("candidate filename is invalid")
        if type(enabled) is not bool or origin not in {"operator", "clarification"}:
            _fail("capability decision is invalid")
        if generation == 0:
            if any(
                value is not None
                for value in (parent_spec_sha256, parent_ir_sha256, parent_proposal_ref)
            ):
                _fail("initial authority has a parent", code="CREATE_V2_AUTHORITY_STALE")
        else:
            _hash(parent_spec_sha256, label="parent spec hash")
            _hash(parent_ir_sha256, label="parent IR hash")
            if not isinstance(parent_proposal_ref, str) or not parent_proposal_ref:
                _fail("refinement parent is invalid", code="CREATE_V2_AUTHORITY_STALE")

        capability_key = (
            "capability:endpoint.needs_time.enable"
            if enabled
            else "capability:endpoint.needs_time.disable"
        )
        capability = inventory.capability(capability_key)
        common = {
            "session_id": session_id,
            "history_revision": history_revision,
            "context_revision": context_revision,
            "semantic_revision": semantic_revision,
            "toolchain_binding": toolchain_binding,
            "inventory_revision": inventory.inventory_revision,
            "policy_revision": inventory.policy_revision,
            "generation": generation,
        }

        def ref(namespace: str, identity: Mapping[str, Any]) -> str:
            return self.issue_ref(
                namespace=namespace,
                identity={
                    "conversation_id": conversation_id,
                    "request_fingerprint": request_fingerprint,
                    **dict(identity),
                },
                **common,
            )

        target_ref = ref(
            "target",
            {"endpoint": endpoint, "candidate_filename": candidate_filename},
        )
        basis_ref = (
            None
            if generation == 0
            else ref(
                "basis",
                {
                    "parent_spec_sha256": parent_spec_sha256,
                    "parent_ir_sha256": parent_ir_sha256,
                    "parent_proposal_ref": parent_proposal_ref,
                },
            )
        )
        requirement_ref = ref("requirement", {"capability": capability.key})
        evidence_ref = ref(
            "evidence",
            {"capability": capability.key, "origin": origin, "evidence": dict(evidence_identity)},
        )
        slot_ref = ref("slot", {"anchor": "target", "member": capability.member})
        node_ref = ref(
            "node",
            {
                "slot": capability.member,
                "fragment_type": capability.fragment_type,
                "value": enabled,
            },
        )
        requirements = (
            RequirementHandle(
                handle=0,
                ref=requirement_ref,
                label=capability.label,
                allowed_ops=frozenset({"set"}),
            ),
        )
        authorities = (
            SlotGrant(
                handle=10,
                ref=slot_ref,
                label="Impostazione del tempo corrente",
                anchor_ref=target_ref,
                member=capability.member,
                cardinality="one",
                accepts=(capability.fragment_type,),
                mutations=frozenset({"set"}),
                insertion="replace",
                basis_spec_sha256=parent_spec_sha256,
                generation=generation,
            ),
            NodeGrant(
                handle=20,
                ref=node_ref,
                label=capability.label,
                state="new",
                fragment_type=capability.fragment_type,
                fragment=enabled,
                fragment_sha256=bytes_sha256(canonical_json(enabled)),
                leaf_bindings=(
                    FragmentLeafBinding(
                        json_pointer="",
                        evidence_ref=evidence_ref,
                        requirement_refs=(requirement_ref,),
                        origin=origin,
                    ),
                ),
                basis_spec_sha256=None,
                basis_path=None,
                parent_slot_ref=slot_ref,
                removable=False,
            ),
        )
        surface_revision = canonical_sha256(
            {
                "contract_id": "metis-brain-create-authority-surface/v2",
                "session_id": session_id,
                "conversation_id": conversation_id,
                "request_fingerprint": request_fingerprint,
                "history_revision": history_revision,
                "context_revision": context_revision,
                "semantic_revision": semantic_revision,
                "toolchain_binding": toolchain_binding,
                "inventory_revision": inventory.inventory_revision,
                "policy_revision": inventory.policy_revision,
                "generation": generation,
                "target_ref": target_ref,
                "basis_ref": basis_ref,
                "capability": capability.key,
            }
        )
        projection = CompactAuthorityProjection(
            projection_revision=compact_authority_projection_revision(
                surface_revision=surface_revision,
                requirements=requirements,
                authorities=authorities,
            ),
            surface_revision=surface_revision,
            requirements=requirements,
            authorities=authorities,
        )
        validate_compact_authority_projection(projection)
        return IssuedCreateV2Authority(projection, (0,), target_ref, basis_ref)


__all__ = [
    "CREATE_V2_HOST_REF_ISSUER_CONTRACT",
    "CreateV2HostRefIssuer",
    "IssuedCreateV2Authority",
]
