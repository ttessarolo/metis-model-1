"""Regression gates for clarification-only typed CREATE refinements."""

from __future__ import annotations

import threading
import uuid
from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest

from metis_model1.brain_create_ir import create_ir_stage_proof
from metis_model1.brain_create_surface import (
    CreateAuthorityHistoryMessage,
    create_authority_history_revision,
)
from metis_model1.brain_dialogue_contract import (
    DialogueBinding,
    PrivateDialogueState,
    QuestionSlot,
)
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_sha256
from metis_model1.brain_turns import TurnRecord, TurnRequest, TurnStore, _OrchestratorTurnRecord


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _request() -> TurnRequest:
    return TurnRequest.parse(
        {
            "schema_version": 2,
            "request_id": str(uuid.uuid4()),
            "expected_context_revision": _digest("a"),
            "expected_semantic_source_revision": _digest("b"),
            "intent": "create",
            "instruction": "Aggiungi una scelta di fallback.",
            "target": {
                "mode": "create",
                "relative_path": "brain-drafts/refinement.metis",
                "endpoint": "demo.refinement",
                "base_sha256": None,
            },
            "basis": {"kind": "proposal", "proposal_ref": "proposal-parent"},
            "clarification_response": None,
        }
    )


def _history(*texts: str) -> tuple[CreateAuthorityHistoryMessage, ...]:
    return tuple(
        CreateAuthorityHistoryMessage(
            ordinal=ordinal,
            text=text,
            message_sha256=bytes_sha256(text.encode("utf-8")),
        )
        for ordinal, text in enumerate(texts)
    )


def _install_basis(record: TurnRecord) -> tuple[dict[str, Any], dict[str, Any]]:
    history = _history("Crea il primo endpoint.")
    spec = {
        "schema_version": 1,
        "contract_id": "metis-brain-create-endpoint-spec/v1",
        "endpoint": {"name": "demo.refinement"},
    }
    ir = {"kind": "Endpoint", "name": "demo.refinement", "generation": 0}
    record.basis_create_spec = deepcopy(spec)
    record.basis_create_spec_sha256 = canonical_sha256(spec)
    record.basis_create_ir = deepcopy(ir)
    record.basis_create_ir_sha256 = canonical_sha256(ir)
    record.basis_create_proof = create_ir_stage_proof(None, ir)
    record.basis_create_generation = 0
    record.basis_create_history = history
    record.basis_create_history_revision = create_authority_history_revision(history)
    return spec, ir


def _store_and_record() -> tuple[TurnStore, TurnRecord, dict[str, Any], dict[str, Any]]:
    request = _request()
    record = TurnRecord(
        turn_id="turn_" + "a" * 32,
        session_id="s" * 32,
        request=request,
        payload_hash=request.payload_hash,
        conversation_id=request.request_fingerprint,
    )
    spec, ir = _install_basis(record)
    basis_history = record.basis_create_history
    assert basis_history is not None
    dialogue_history = (
        *basis_history,
        CreateAuthorityHistoryMessage(
            ordinal=len(basis_history),
            text=request.instruction,
            message_sha256=bytes_sha256(request.instruction.encode("utf-8")),
        ),
    )
    dialogue_binding = DialogueBinding(
        request.expected_context_revision,
        request.expected_semantic_source_revision,
        _digest("c"),
        create_authority_history_revision(dialogue_history),
        request.request_fingerprint,
    )
    dialogue = PrivateDialogueState(
        request.request_fingerprint,
        dialogue_binding,
        dialogue_history,
        generation=1,
    )
    record.dialogue_state = dialogue
    record.request = replace(request, server_dialogue=dialogue)
    store = object.__new__(TurnStore)
    store._lock = threading.RLock()  # noqa: SLF001
    store._closed = False  # noqa: SLF001
    store._turns = {record.turn_id: record}  # noqa: SLF001
    store._proposal_heads = {("preserved", "head"): object()}  # noqa: SLF001
    from metis_model1.brain_clarifications import ClarificationStore

    store.clarifications = ClarificationStore()
    return store, record, spec, ir


def _issued_result(store: TurnStore, record: TurnRecord) -> dict[str, Any]:
    dialogue = record.dialogue_state
    assert type(dialogue) is PrivateDialogueState
    pending = store.clarifications.create_pending_v2(
        session_id=record.session_id,
        parent_turn_id=record.turn_id,
        conversation_id=record.conversation_id or record.request.request_fingerprint,
        binding=dialogue.binding,
        slots=(
            QuestionSlot(
                "response.total",
                "response.total",
                "result_count",
                "Quanti risultati complessivi vuoi?",
                "integer",
                minimum=1,
                maximum=200,
                value_contract="total",
            ),
        ),
    )
    return {
        "schema_version": 2,
        "turn_id": record.turn_id,
        "request_id": record.request.request_id,
        "status": "completed",
        "outcome": "needs_clarification",
        "route": "local",
        "clarification": pending.payload(),
    }


def test_refinement_clarification_preserves_private_basis_and_issued_pending() -> None:
    store, record, original_spec, original_ir = _store_and_record()
    result = _issued_result(store, record)
    staged = _OrchestratorTurnRecord(record)

    assert store._publish_private_attachments(record, staged, result=result)  # noqa: SLF001
    assert record.basis_create_spec == original_spec
    assert record.basis_create_spec is not original_spec
    assert record.basis_create_ir == original_ir
    assert record.basis_create_ir is not original_ir
    assert record.basis_create_history == _history("Crea il primo endpoint.")
    assert record.candidate_create_spec is None
    assert record.candidate_create_ir is None
    assert record.candidate_proposal_ref is None
    clarification_id = result["clarification"]["clarification_id"]
    assert (
        store.clarifications.pending_v2(  # noqa: SLF001
            session_id=record.session_id,
            clarification_id=clarification_id,
        ).payload()
        == result["clarification"]
    )
    heads_before = dict(store._proposal_heads)  # noqa: SLF001
    store._advance_head_locked(record, result)  # noqa: SLF001
    assert store._proposal_heads == heads_before  # noqa: SLF001


@pytest.mark.parametrize("outcome", ("failed", "cancelled", "proposed"))
def test_refinement_missing_candidate_fails_closed_for_non_clarification_outcomes(
    outcome: str,
) -> None:
    store, record, _spec, _ir = _store_and_record()
    staged = _OrchestratorTurnRecord(record)
    result = {
        "schema_version": 2,
        "turn_id": record.turn_id,
        "request_id": record.request.request_id,
        "status": "completed",
        "outcome": outcome,
        "route": "local",
    }

    with pytest.raises(BrainError, match="cannot discard its private authority") as raised:
        store._publish_private_attachments(record, staged, result=result)  # noqa: SLF001
    assert raised.value.code == "COMPILER_FAILED"
    assert record.basis_create_spec is not None
    assert record.candidate_create_spec is None


def test_refinement_clarification_rejects_a_tampered_dialogue_history_prefix() -> None:
    store, record, _spec, _ir = _store_and_record()
    result = _issued_result(store, record)
    staged = _OrchestratorTurnRecord(record)
    dialogue = record.dialogue_state
    assert type(dialogue) is PrivateDialogueState
    object.__setattr__(dialogue, "messages", _history("tampered dialogue"))

    with pytest.raises(BrainError) as raised:
        store._publish_private_attachments(record, staged, result=result)  # noqa: SLF001
    assert raised.value.code in {"COMPILER_FAILED", "DIALOGUE_INVALID"}
    assert record.basis_create_spec is not None


def test_refinement_clarification_rejects_unissued_or_tampered_private_authority() -> None:
    store, record, _spec, _ir = _store_and_record()
    result = _issued_result(store, record)
    staged = _OrchestratorTurnRecord(record)
    manifest = {"schema_version": 1, "endpoint": "demo.refinement"}
    staged.candidate_manifest = manifest
    staged.candidate_manifest_sha256 = canonical_sha256(manifest)

    with pytest.raises(BrainError, match="cannot discard its private authority") as raised:
        store._publish_private_attachments(record, staged, result=result)  # noqa: SLF001
    assert raised.value.code == "COMPILER_FAILED"
    assert record.basis_create_spec is not None
    assert record.candidate_manifest is None

    clean_staged = _OrchestratorTurnRecord(record)
    clean_staged.basis_create_spec["endpoint"]["name"] = "tampered"
    with pytest.raises(BrainError) as tampered:
        store._publish_private_attachments(record, clean_staged, result=result)  # noqa: SLF001
    assert tampered.value.code in {"COMPILER_FAILED", "PROPOSAL_STALE"}
    assert record.basis_create_spec["endpoint"]["name"] == "demo.refinement"


def test_refinement_clarification_requires_the_exact_issued_payload() -> None:
    store, record, _spec, _ir = _store_and_record()
    result = _issued_result(store, record)
    staged = _OrchestratorTurnRecord(record)
    result["clarification"] = {**result["clarification"], "round": 2}

    with pytest.raises(BrainError, match="cannot discard its private authority") as raised:
        store._publish_private_attachments(record, staged, result=result)  # noqa: SLF001
    assert raised.value.code == "COMPILER_FAILED"
    assert record.basis_create_spec is not None
