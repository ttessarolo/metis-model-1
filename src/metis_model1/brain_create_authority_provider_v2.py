"""Private host boundary for production typed CREATE v2 authority.

The orchestrator owns lifecycle and I/O; a provider owns the semantic and
structural authority decision.  This module intentionally contains no fixture
loader and no reference endpoint access.  Qualification providers may be
injected by tests, but production code can only consume the closed objects
defined here.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Protocol, TypeAlias

from metis_model1.brain_create_ir import CreateIrStageProof, isolated_ir
from metis_model1.brain_create_plan_v2 import (
    CompactAuthorityProjection,
    initial_create_endpoint_skeleton,
    validate_compact_authority_projection,
)
from metis_model1.brain_create_surface import (
    CreateAuthorityHistoryMessage,
    create_authority_history_revision,
)
from metis_model1.brain_dialogue_contract import (
    DialogueBinding,
    PrivateDialogueState,
    QuestionSlot,
    decision_roster,
)
from metis_model1.brain_protocol import BrainError, canonical_sha256
from metis_model1.brain_retrieval import RetrievalResult
from metis_model1.brain_sessions import OperationLease
from metis_model1.brain_typed_create_pipeline import TypedCreateV2RequestBinding

if TYPE_CHECKING:
    from metis_model1.brain_turns import TurnRequest

_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_CATALOG_KEY_RE = re.compile(
    r"^catalog:(?P<catalog>[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*)$"
)
_HOST_REF_RE = re.compile(r"^hostref:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def _fail(code: str, status: int, message: str) -> None:
    raise BrainError(code, status, message)


def _hash(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, f"{label} is invalid")
    return value


@dataclass(frozen=True, slots=True, repr=False)
class PrivateCreateV2Basis:
    """Detached latest-head authority supplied to a provider for refinement."""

    spec: dict[str, Any]
    spec_sha256: str
    ir: dict[str, Any]
    ir_sha256: str
    proof: CreateIrStageProof
    generation: int
    history: tuple[CreateAuthorityHistoryMessage, ...]
    history_revision: str
    proposal_ref: str

    def __post_init__(self) -> None:
        if not isinstance(self.spec, dict) or canonical_sha256(self.spec) != _hash(
            self.spec_sha256, label="basis spec hash"
        ):
            _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "basis spec differs")
        if not isinstance(self.ir, dict) or canonical_sha256(self.ir) != _hash(
            self.ir_sha256, label="basis IR hash"
        ):
            _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "basis IR differs")
        if (
            type(self.proof) is not CreateIrStageProof
            or not isinstance(self.proof.delta_operation_count, int)
            or self.proof.delta_operation_count < 0
        ):
            _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "basis IR proof is invalid")
        proof_ir = _hash(self.proof.ir_sha256, label="basis proof IR hash")
        _hash(self.proof.delta_sha256, label="basis proof delta hash")
        if proof_ir != self.ir_sha256:
            _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "basis IR proof differs")
        if self.proof.parent_ir_sha256 is not None:
            _hash(self.proof.parent_ir_sha256, label="basis proof parent IR hash")
        if type(self.generation) is not int or not 0 <= self.generation < 20:
            _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "basis generation is invalid")
        if (self.generation == 0) != (self.proof.parent_ir_sha256 is None):
            _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "basis proof generation differs")
        history = tuple(self.history)
        if create_authority_history_revision(history) != _hash(
            self.history_revision, label="basis history revision"
        ):
            _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "basis history differs")
        if not isinstance(self.proposal_ref, str) or not self.proposal_ref:
            _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "basis proposal is invalid")
        object.__setattr__(self, "spec", copy.deepcopy(self.spec))
        object.__setattr__(self, "ir", isolated_ir(self.ir))
        object.__setattr__(self, "proof", copy.deepcopy(self.proof))
        object.__setattr__(self, "history", tuple(replace(item) for item in history))


@dataclass(frozen=True, slots=True, repr=False)
class ReadyCreateV2Authority:
    """Complete private arguments for one one-pass typed CREATE execution."""

    binding: TypedCreateV2RequestBinding
    projection: CompactAuthorityProjection
    active_requirement_handles: tuple[int, ...]
    base_spec: dict[str, Any]
    target_ref: str
    basis_ref: str | None
    generation: int
    parent_spec_sha256: str | None
    parent_ir: dict[str, Any] | None
    parent_ir_sha256: str | None

    def __post_init__(self) -> None:
        if type(self.binding) is not TypedCreateV2RequestBinding:
            _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "request binding is invalid")
        try:
            projection = copy.deepcopy(self.projection)
            validate_compact_authority_projection(projection)
        except (BrainError, TypeError, ValueError) as error:
            raise BrainError(
                "CREATE_TYPED_AUTHORITY_INVALID", 500, "authority projection is invalid"
            ) from error
        handles = tuple(self.active_requirement_handles)
        known = {item.handle for item in projection.requirements}
        if (
            not handles
            or len(handles) != len(set(handles))
            or any(type(item) is not int or item not in known for item in handles)
        ):
            _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "active requirements are invalid")
        if not isinstance(self.base_spec, dict):
            _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "base spec is invalid")
        if not isinstance(self.target_ref, str) or _HOST_REF_RE.fullmatch(self.target_ref) is None:
            _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "target ref is invalid")
        if self.basis_ref is not None and _HOST_REF_RE.fullmatch(self.basis_ref) is None:
            _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "basis ref is invalid")
        if type(self.generation) is not int or not 0 <= self.generation <= 20:
            _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "generation is invalid")
        parent = (self.parent_spec_sha256, self.parent_ir, self.parent_ir_sha256, self.basis_ref)
        if self.generation == 0:
            if any(item is not None for item in parent):
                _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "initial authority has a parent")
            if self.base_spec != initial_create_endpoint_skeleton(self.binding.endpoint):
                _fail(
                    "CREATE_TYPED_AUTHORITY_INVALID",
                    500,
                    "initial authority base is not the canonical endpoint skeleton",
                )
        elif (
            self.basis_ref is None
            or self.parent_spec_sha256 is None
            or self.parent_ir is None
            or self.parent_ir_sha256 is None
        ):
            _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "refinement authority lacks parent")
        if self.parent_spec_sha256 is not None:
            _hash(self.parent_spec_sha256, label="parent spec hash")
        if self.parent_ir_sha256 is not None:
            _hash(self.parent_ir_sha256, label="parent IR hash")
            if (
                not isinstance(self.parent_ir, dict)
                or canonical_sha256(self.parent_ir) != self.parent_ir_sha256
            ):
                _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "parent IR differs")
        object.__setattr__(self, "projection", projection)
        object.__setattr__(self, "active_requirement_handles", handles)
        object.__setattr__(self, "base_spec", copy.deepcopy(self.base_spec))
        object.__setattr__(
            self, "parent_ir", None if self.parent_ir is None else isolated_ir(self.parent_ir)
        )


@dataclass(frozen=True, slots=True, repr=False)
class AskCreateV2Authority:
    """Consequential host-owned questions required before any model call."""

    slots: tuple[QuestionSlot, ...]

    def __post_init__(self) -> None:
        slots = tuple(self.slots)
        if (
            not 1 <= len(slots) <= 5
            or any(
                type(slot) is not QuestionSlot or slot.question_ref is not None for slot in slots
            )
            or len({slot.identity for slot in slots}) != len(slots)
        ):
            _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "question roster is invalid")
        object.__setattr__(self, "slots", tuple(replace(slot) for slot in slots))


CreateV2AuthorityDecision: TypeAlias = ReadyCreateV2Authority | AskCreateV2Authority


class CreateV2AuthorityProvider(Protocol):
    """Production boundary; implementations must derive only server authority."""

    def prepare(
        self,
        *,
        session_id: str,
        lease: OperationLease,
        request: TurnRequest,
        dialogue: PrivateDialogueState,
        retrieved: RetrievalResult,
        basis: PrivateCreateV2Basis | None,
    ) -> CreateV2AuthorityDecision: ...


def validate_dialogue_binding(
    *,
    lease: OperationLease,
    request: TurnRequest,
    dialogue: PrivateDialogueState,
    semantic_revision: str,
) -> DialogueBinding:
    """Rebind a private dialogue to the exact live snapshot before authority use."""

    if type(dialogue) is not PrivateDialogueState:
        _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "dialogue authority is unavailable")
    state = replace(dialogue)
    binding = state.binding
    expected_history = create_authority_history_revision(state.messages)
    if (
        binding.context_revision != lease.snapshot.revision
        or binding.context_revision != request.expected_context_revision
        or binding.semantic_revision != semantic_revision
        or binding.semantic_revision != request.expected_semantic_source_revision
        or binding.toolchain_binding != lease.snapshot.toolchain_binding
        or binding.history_revision != expected_history
    ):
        _fail("CREATE_TYPED_AUTHORITY_STALE", 409, "dialogue authority is stale")
    return replace(binding)


def selected_catalogs_from_dialogue(dialogue: PrivateDialogueState | None) -> tuple[str, ...]:
    """Extract only exact catalog keys captured in server-issued decisions.

    Labels and public option positions are never interpreted.  A malformed or
    role-swapped decision fails closed before retrieval.
    """

    if dialogue is None:
        return ()
    if type(dialogue) is not PrivateDialogueState:
        _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "dialogue authority is invalid")
    latest = {}
    for decision in decision_roster(dialogue.decisions):
        latest[decision.identity] = decision
    catalog_decisions = tuple(
        decision for decision in latest.values() if decision.kind == "catalog"
    )
    if not catalog_decisions:
        return ()
    if len(catalog_decisions) != 1:
        _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "catalog decision is ambiguous")
    decision = catalog_decisions[0]
    if decision.target_key != "target.catalogs" or not decision.choices:
        _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "catalog decision is invalid")
    selected: list[str] = []
    for choice in decision.choices:
        if choice.required_roles != ("catalog",) or len(choice.authority_keys) != 1:
            _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "catalog choice roles are invalid")
        match = _CATALOG_KEY_RE.fullmatch(choice.authority_keys[0])
        if match is None:
            _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "catalog choice key is invalid")
        selected.append(match.group("catalog"))
    if len(selected) != len(set(selected)):
        _fail("CREATE_TYPED_AUTHORITY_INVALID", 500, "catalog choice is duplicated")
    return tuple(selected)


class UnavailableCreateV2AuthorityProvider:
    """Fail-closed default until a production capability inventory is installed."""

    def prepare(self, **_: Any) -> CreateV2AuthorityDecision:
        raise BrainError(
            "CREATE_TYPED_AUTHORITY_UNAVAILABLE",
            503,
            "typed CREATE authority provider is unavailable",
        )


__all__ = [
    "AskCreateV2Authority",
    "CreateV2AuthorityDecision",
    "CreateV2AuthorityProvider",
    "PrivateCreateV2Basis",
    "ReadyCreateV2Authority",
    "UnavailableCreateV2AuthorityProvider",
    "selected_catalogs_from_dialogue",
    "validate_dialogue_binding",
]
