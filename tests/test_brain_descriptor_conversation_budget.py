"""Actual store transitions for bounded, multi-refinement dialogue v2.

No synthetic BoundDecision admission and no model/compiler or client claim:
every decision below passes create_pending_v2, claim and answer_v2.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from metis_model1.brain_clarifications import MAX_ROUNDS, ClarificationStore
from metis_model1.brain_dialogue_contract import (
    MAX_DECISIONS,
    DialogueAnswer,
    DialogueBinding,
    QuestionSlot,
)
from metis_model1.brain_protocol import BrainError

REVISION = "sha256:" + "a" * 64
BINDING = DialogueBinding(REVISION, REVISION, REVISION, REVISION, REVISION)
SESSION = "session_" + "a" * 32
TURN = "turn_" + "a" * 32


def _slot(index: int, **kwargs: object) -> QuestionSlot:
    return QuestionSlot(
        decision_key="count",
        target_key=f"row.{index}",
        kind="result_count",
        question="Quanti risultati deve restituire questa raccolta?",
        answer_kind="integer",
        minimum=1,
        maximum=100,
        value_contract="total",
        **kwargs,
    )


def _pending(store: ClarificationStore, index: int, *, slots=None):
    return store.create_pending_v2(
        session_id=SESSION,
        parent_turn_id=TURN,
        conversation_id=REVISION,
        binding=BINDING,
        slots=(_slot(index),) if slots is None else slots,
    )


def _answer(store: ClarificationStore, pending, *, slots=None):
    args = dict(
        session_id=SESSION,
        clarification_id=pending.clarification_id,
        binding=BINDING,
        answers=tuple(
            DialogueAnswer(slot.question_ref, integer=24)
            for slot in (pending.slots if slots is None else slots)
        ),
        claim_owner=TURN,
    )
    admitted = store.validate_answers_v2(**args)
    resolution = store.answer_v2(**args)
    assert resolution.accepted == admitted
    return resolution


def _complete(store: ClarificationStore, count: int) -> None:
    for index in range(count):
        pending = _pending(store, index)
        assert pending.round_index == index + 1
        assert _answer(store, pending).remaining is None


def test_v2_actual_claimed_conversation_reaches_32_rounds_then_fails_closed() -> None:
    store = ClarificationStore()
    assert store.max_rounds_v2 == MAX_DECISIONS == 32
    _complete(store, MAX_DECISIONS)
    decisions = store.decisions_v2(session_id=SESSION, conversation_id=REVISION)
    assert len(decisions) == len({item.question_ref for item in decisions}) == 32
    assert all(item.binding == BINDING and item.integer == 24 for item in decisions)
    before = store.metrics()
    with pytest.raises(BrainError) as raised:
        _pending(store, 32)
    assert raised.value.code == "CLARIFICATION_BUDGET_EXCEEDED"
    assert raised.value.status == 409
    assert store.metrics() == before
    assert not store.has_pending(SESSION)


def test_cumulative_32_decisions_remain_bounded_independently_of_rounds() -> None:
    store = ClarificationStore()
    for group in range(6):
        _answer(store, _pending(store, group, slots=tuple(_slot(group * 5 + i) for i in range(5))))
    assert len(store.decisions_v2(session_id=SESSION, conversation_id=REVISION)) == 30
    _answer(store, _pending(store, 30))
    with pytest.raises(BrainError, match="decision capacity") as raised:
        _pending(store, 31, slots=(_slot(31), _slot(32)))
    assert raised.value.code == "CLARIFICATION_BUDGET_EXCEEDED"
    assert not store.has_pending(SESSION)
    last = _pending(store, 31)
    assert last.round_index == 8
    _answer(store, last)
    with pytest.raises(BrainError, match="decision capacity"):
        _pending(store, 32)
    assert len(store.decisions_v2(session_id=SESSION, conversation_id=REVISION)) == 32


def test_lower_v2_budget_is_explicit_and_independent_from_v1_configuration() -> None:
    store = ClarificationStore(max_rounds=1, max_rounds_v2=4)
    _complete(store, 4)
    assert store.max_rounds == 1
    assert store.max_rounds_v2 == 4
    with pytest.raises(BrainError, match="budget is exhausted"):
        _pending(store, 4)


def test_v1_wire_budget_and_admission_remain_three_rounds() -> None:
    store = ClarificationStore()
    assert store.max_rounds == MAX_ROUNDS == 3
    args = dict(
        session_id=SESSION,
        parent_turn_id=TURN,
        request_fingerprint=REVISION,
        context_revision=REVISION,
        semantic_source_revision=REVISION,
        kind="result_count",
        question="Quanti?",
        options=(),
    )
    for index in range(3):
        pending = store.create_pending(**args, question_key=f"count-{index}")
        assert pending.payload()["max_rounds"] == 3
        store.answer(
            session_id=SESSION,
            clarification_id=pending.clarification_id,
            request_fingerprint=REVISION,
            context_revision=REVISION,
            semantic_source_revision=REVISION,
            answer={"integer": 24},
        )
    with pytest.raises(BrainError) as raised:
        store.create_pending(**args, question_key="count-3")
    assert raised.value.code == "CLARIFICATION_BUDGET_EXCEEDED"


@pytest.mark.parametrize("value", [0, 33, -1, True, False, 4.0, "4", None])
def test_v2_round_configuration_is_strict_and_bounded(value) -> None:
    with pytest.raises(BrainError) as raised:
        ClarificationStore(max_rounds_v2=value)
    assert raised.value.code == "INVALID_CONFIG"
    assert raised.value.status == 500


def test_round_four_public_contract_matches_schema_and_preserves_private_boundary() -> None:
    store = ClarificationStore()
    _complete(store, 3)
    pending = _pending(store, 3)
    payload = pending.payload(now=pending.expires_at - 1200)
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas/metis-brain-dialogue-v2.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(payload)
    assert payload["round"] == 4 and payload["max_rounds"] == 32
    assert payload["expires_in_seconds"] == 1200
    encoded = json.dumps(payload)
    assert SESSION not in encoded and REVISION not in encoded
    for key in ("binding", "target_key", "decision_key", "authority_keys"):
        assert key not in encoded
    for value in (0, 33, True):
        with pytest.raises(BrainError):
            replace(pending, max_rounds=value)
        assert not Draft202012Validator(schema).is_valid({**payload, "max_rounds": value})


def test_partial_answers_after_round_three_rotate_refs_without_spending_extra_round() -> None:
    store = ClarificationStore(max_rounds_v2=4)
    _complete(store, 3)
    pending = _pending(store, 3, slots=(_slot(3), _slot(4)))
    partial = _answer(store, pending, slots=pending.slots[:1])
    assert partial.remaining is not None
    assert partial.remaining.round_index == 4
    assert partial.remaining.clarification_id != pending.clarification_id
    _answer(store, partial.remaining)
    with pytest.raises(BrainError, match="already consumed"):
        _answer(store, pending)
    assert len(store.decisions_v2(session_id=SESSION, conversation_id=REVISION)) == 5
    with pytest.raises(BrainError, match="budget is exhausted"):
        _pending(store, 5)


def test_round_four_still_rejects_stale_authority_and_claim_replay() -> None:
    store = ClarificationStore()
    _complete(store, 3)
    pending = _pending(store, 3)
    answer = DialogueAnswer(pending.slots[0].question_ref, integer=24)
    with pytest.raises(BrainError) as raised:
        store.answer_v2(
            session_id=SESSION,
            clarification_id=pending.clarification_id,
            binding=replace(BINDING, history_revision="sha256:" + "b" * 64),
            answers=(answer,),
        )
    assert raised.value.code == "CLARIFICATION_STALE"
    _answer(store, pending)
    with pytest.raises(BrainError) as replay:
        _answer(store, pending)
    assert replay.value.code == "CLARIFICATION_REPLAY"


def test_extended_conversation_pending_ttl_and_session_revocation_remain_effective() -> None:
    clock = [0.0]
    store = ClarificationStore(monotonic=lambda: clock[0], ttl_seconds=20)
    _complete(store, 4)
    pending = _pending(store, 4)
    clock[0] = 20
    with pytest.raises(BrainError) as expired:
        _answer(store, pending)
    assert expired.value.code == "CLARIFICATION_EXPIRED"
    store.drop_session(SESSION, revocation_owner=TURN)
    assert store.decisions_v2(session_id=SESSION, conversation_id=REVISION) == ()
    with pytest.raises(BrainError) as revoked:
        _pending(store, 5)
    assert revoked.value.code == "SESSION_REVOKED"
