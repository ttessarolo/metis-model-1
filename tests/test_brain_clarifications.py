from __future__ import annotations

import threading
from dataclasses import replace

import pytest

from metis_model1.brain_clarifications import (
    ClarificationChoice,
    ClarificationStore,
)
from metis_model1.brain_dialogue_contract import (
    BoundChoice,
    DialogueAnswer,
    DialogueBinding,
    QuestionSlot,
)
from metis_model1.brain_protocol import IDLE_TTL_SECONDS, BrainError

REVISION = "sha256:" + "a" * 64
SEMANTIC_REVISION = "sha256:" + "b" * 64
FINGERPRINT = "sha256:" + "c" * 64
SESSION = "session_" + "a" * 32
OTHER_SESSION = "session_" + "b" * 32
TURN = "turn_" + "a" * 32


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _store(clock: Clock, **kwargs: object) -> ClarificationStore:
    return ClarificationStore(monotonic=clock, **kwargs)


def _pending(store: ClarificationStore, *, kind: str = "catalog", **kwargs: object):
    defaults: dict[str, object] = {
        "session_id": SESSION,
        "parent_turn_id": TURN,
        "request_fingerprint": FINGERPRINT,
        "context_revision": REVISION,
        "semantic_source_revision": SEMANTIC_REVISION,
        "kind": kind,
        "question": "Quale scelta vuoi usare?",
        "question_key": f"q-{kind}",
        "options": [ClarificationChoice("A", "value-a"), ClarificationChoice("B", "value-b")],
    }
    defaults.update(kwargs)
    return store.create_pending(**defaults)


def test_all_five_kinds_have_typed_bounded_public_contract() -> None:
    clock = Clock()
    for index, kind in enumerate(("catalog", "semantic_choice", "response_shape", "fallback")):
        store = _store(clock, max_result_count=50)
        pending = _pending(store, kind=kind, question_key=f"q-{index}")
        assert pending.kind == kind
        assert pending.payload()["answer_schema"] == {"type": "option_ref"}
        assert all(option.option_ref.startswith("opt_") for option in pending.options)
        store.answer(
            session_id=SESSION,
            clarification_id=pending.clarification_id,
            request_fingerprint=FINGERPRINT,
            context_revision=REVISION,
            semantic_source_revision=SEMANTIC_REVISION,
            answer={"option_ref": pending.options[0].option_ref},
        )
    count_store = _store(clock, max_result_count=50)
    count = _pending(
        count_store,
        kind="result_count",
        question="Quanti risultati?",
        question_key="q-count",
        options=(),
        min_value=1,
        max_value=50,
    )
    assert count.payload()["answer_schema"] == {"type": "integer", "minimum": 1, "maximum": 50}
    resolved = count_store.answer(
        session_id=SESSION,
        clarification_id=count.clarification_id,
        request_fingerprint=FINGERPRINT,
        context_revision=REVISION,
        semantic_source_revision=SEMANTIC_REVISION,
        answer={"integer": 24},
    )
    assert resolved.answer.integer == 24


def test_option_refs_are_server_owned_and_values_resolve_only_after_valid_answer() -> None:
    clock = Clock()
    store = _store(clock)
    pending = _pending(store)
    assert pending.options[0].option_ref != "value-a"
    with pytest.raises(BrainError) as raised:
        store.answer(
            session_id=SESSION,
            clarification_id=pending.clarification_id,
            request_fingerprint=FINGERPRINT,
            context_revision=REVISION,
            semantic_source_revision=SEMANTIC_REVISION,
            answer={"option_ref": "value-a"},
        )
    assert raised.value.code == "CLARIFICATION_OPTION_UNKNOWN"
    resolved = store.answer(
        session_id=SESSION,
        clarification_id=pending.clarification_id,
        request_fingerprint=FINGERPRINT,
        context_revision=REVISION,
        semantic_source_revision=SEMANTIC_REVISION,
        answer={"option_ref": pending.options[0].option_ref},
    )
    assert resolved.answer.resolved_value == "value-a"
    assert resolved.decision.label == "A"


def test_catalog_public_field_is_preserved_without_exposing_private_option_value() -> None:
    clock = Clock()
    store = _store(clock)
    pending = _pending(
        store,
        options=[
            ClarificationChoice("Video", "play-demo.video", catalog="play-demo.video"),
            ClarificationChoice("Utenti", "play-demo.users", catalog="play-demo.users"),
        ],
    )

    payload = pending.payload()["options"][0]
    assert payload == {
        "option_ref": pending.options[0].option_ref,
        "catalog": "play-demo.video",
        "label": "Video",
    }
    assert "value" not in payload and "resolved_value" not in payload


def test_catalog_overflow_uses_complete_exact_reference_roster() -> None:
    clock = Clock()
    store = _store(clock)
    catalogs = [f"play-prod-v2.catalog_{index}" for index in range(6)]
    pending = _pending(
        store,
        options=[
            ClarificationChoice(
                f"Catalogo {index}",
                catalog,
                catalog=catalog,
            )
            for index, catalog in enumerate(catalogs)
        ],
    )

    payload = pending.payload()
    assert payload["options"] == []
    assert payload["catalog_refs"] == catalogs
    assert payload["answer_schema"] == {
        "type": "text",
        "format": "catalog-ref",
        "max_bytes": 256,
    }
    resolved = store.answer(
        session_id=SESSION,
        clarification_id=pending.clarification_id,
        request_fingerprint=FINGERPRINT,
        context_revision=REVISION,
        semantic_source_revision=SEMANTIC_REVISION,
        answer={"text": "play-prod-v2.catalog_5"},
    )
    assert resolved.answer.payload() == {"text": "play-prod-v2.catalog_5"}
    assert resolved.answer.resolved_value == "play-prod-v2.catalog_5"


def test_catalog_overflow_requires_one_exact_case_sensitive_reference() -> None:
    clock = Clock()
    store = _store(clock)
    catalogs = [
        "tenant-a.video",
        "tenant-b.video",
        "tenant-a.users",
        "tenant-a.links",
        "tenant-a.trending",
        "tenant-a.sessions",
    ]
    pending = _pending(
        store,
        options=[ClarificationChoice(catalog, catalog, catalog=catalog) for catalog in catalogs],
    )
    common = {
        "session_id": SESSION,
        "clarification_id": pending.clarification_id,
        "request_fingerprint": FINGERPRINT,
        "context_revision": REVISION,
        "semantic_source_revision": SEMANTIC_REVISION,
    }

    with pytest.raises(BrainError) as raised:
        store.validate_answer(**common, answer={"text": "missing"})
    assert raised.value.code == "CLARIFICATION_CATALOG_UNKNOWN"
    with pytest.raises(BrainError) as raised:
        store.validate_answer(**common, answer={"text": "video"})
    assert raised.value.code == "CLARIFICATION_CATALOG_UNKNOWN"
    with pytest.raises(BrainError) as raised:
        store.validate_answer(**common, answer={"text": "TENANT-B.VIDEO"})
    assert raised.value.code == "CLARIFICATION_CATALOG_UNKNOWN"
    for padded in (" tenant-b.video", "tenant-b.video "):
        with pytest.raises(BrainError) as raised:
            store.validate_answer(**common, answer={"text": padded})
        assert raised.value.code == "INVALID_SCHEMA"
    store.validate_answer(**common, answer={"text": "tenant-b.video"})


def test_option_ref_factory_collision_is_retried_within_one_question() -> None:
    clock = Clock()
    values = iter(["opt_same", "opt_same", "opt_other"])
    store = _store(clock, option_ref_factory=lambda: next(values))
    pending = _pending(store)
    assert [item.option_ref for item in pending.options] == ["opt_same", "opt_other"]


@pytest.mark.parametrize("leading", ["_", "-"])
def test_generated_session_and_turn_ids_accept_urlsafe_leading_characters(leading: str) -> None:
    clock = Clock()
    store = _store(clock)
    pending = _pending(
        store,
        session_id=leading + "s" * 31,
        parent_turn_id=leading + "t" * 23,
    )

    assert pending.session_id.startswith(leading)
    assert pending.parent_turn_id.startswith(leading)


def test_session_and_parent_turn_id_lengths_match_public_protocol() -> None:
    clock = Clock()
    store = _store(clock)
    assert (
        _pending(
            store,
            session_id="s" * 96,
            parent_turn_id="t" * 96,
        ).session_id
        == "s" * 96
    )
    with pytest.raises(BrainError) as raised:
        _pending(store, session_id="s" * 31)
    assert raised.value.code == "INVALID_SCHEMA"
    with pytest.raises(BrainError) as raised:
        _pending(store, session_id="s" * 97)
    assert raised.value.code == "INVALID_SCHEMA"
    with pytest.raises(BrainError) as raised:
        _pending(store, parent_turn_id="t" * 23)
    assert raised.value.code == "INVALID_SCHEMA"
    with pytest.raises(BrainError) as raised:
        _pending(store, parent_turn_id="t" * 97)
    assert raised.value.code == "INVALID_SCHEMA"


def test_pending_expiry_does_not_drop_session_decisions_or_proposal_lineage() -> None:
    clock = Clock()
    store = _store(clock)
    pending = _pending(store)
    store.answer(
        session_id=SESSION,
        clarification_id=pending.clarification_id,
        request_fingerprint=FINGERPRINT,
        context_revision=REVISION,
        semantic_source_revision=SEMANTIC_REVISION,
        answer={"option_ref": pending.options[0].option_ref},
    )
    store.set_latest_proposal(
        session_id=SESSION,
        request_fingerprint=FINGERPRINT,
        proposal_ref="proposal_kept",
    )
    expiring = _pending(store, question_key="expires-without-session")
    clock.advance(IDLE_TTL_SECONDS)
    store.sweep_expired()

    summary = store.conversation(session_id=SESSION, request_fingerprint=FINGERPRINT)
    assert store.metrics()["sessions"] == 1
    assert store.metrics()["pending"] == 0
    assert summary.latest_proposal_ref == "proposal_kept"
    assert len(summary.decisions) == 1
    with pytest.raises(BrainError) as raised:
        store.answer(
            session_id=SESSION,
            clarification_id=expiring.clarification_id,
            request_fingerprint=FINGERPRINT,
            context_revision=REVISION,
            semantic_source_revision=SEMANTIC_REVISION,
            answer={"option_ref": expiring.options[0].option_ref},
        )
    assert raised.value.code == "CLARIFICATION_EXPIRED"

    store.drop_session(SESSION)
    assert store.metrics()["sessions"] == 0


def test_admitted_answer_claim_survives_queue_time_past_question_expiry() -> None:
    clock = Clock()
    store = _store(clock, ttl_seconds=10)
    pending = _pending(store)
    clock.advance(9)
    store.validate_answer(
        session_id=SESSION,
        clarification_id=pending.clarification_id,
        request_fingerprint=FINGERPRINT,
        context_revision=REVISION,
        semantic_source_revision=SEMANTIC_REVISION,
        answer={"option_ref": pending.options[0].option_ref},
        claim_owner=TURN,
    )

    clock.advance(20)
    assert store.sweep_expired() == 0
    resolved = store.answer(
        session_id=SESSION,
        clarification_id=pending.clarification_id,
        request_fingerprint=FINGERPRINT,
        context_revision=REVISION,
        semantic_source_revision=SEMANTIC_REVISION,
        answer={"option_ref": pending.options[0].option_ref},
        claim_owner=TURN,
    )
    assert resolved.decision.round_index == 1
    assert store.metrics()["pending"] == 0


def test_released_queued_answer_claim_returns_to_normal_expiry() -> None:
    clock = Clock()
    store = _store(clock, ttl_seconds=10)
    pending = _pending(store)
    store.validate_answer(
        session_id=SESSION,
        clarification_id=pending.clarification_id,
        request_fingerprint=FINGERPRINT,
        context_revision=REVISION,
        semantic_source_revision=SEMANTIC_REVISION,
        answer={"option_ref": pending.options[0].option_ref},
        claim_owner=TURN,
    )
    assert store.release_answer_claim(session_id=SESSION, owner=TURN)
    clock.advance(10)
    with pytest.raises(BrainError) as raised:
        store.answer(
            session_id=SESSION,
            clarification_id=pending.clarification_id,
            request_fingerprint=FINGERPRINT,
            context_revision=REVISION,
            semantic_source_revision=SEMANTIC_REVISION,
            answer={"option_ref": pending.options[0].option_ref},
        )
    assert raised.value.code == "CLARIFICATION_EXPIRED"


def test_one_pending_per_session_and_exact_repeat_and_three_round_budget() -> None:
    clock = Clock()
    store = _store(clock)
    first = _pending(store)
    with pytest.raises(BrainError) as raised:
        _pending(store, question_key="another")
    assert raised.value.code == "CLARIFICATION_PENDING"
    store.answer(
        session_id=SESSION,
        clarification_id=first.clarification_id,
        request_fingerprint=FINGERPRINT,
        context_revision=REVISION,
        semantic_source_revision=SEMANTIC_REVISION,
        answer={"option_ref": first.options[0].option_ref},
    )
    with pytest.raises(BrainError) as raised:
        _pending(store, assumptions=["mai ammessa per ripetizione"])
    assert raised.value.code == "CLARIFICATION_REPEAT"
    assert (
        store.conversation(
            session_id=SESSION,
            request_fingerprint=FINGERPRINT,
        ).assumptions
        == ()
    )
    for index in (1, 2):
        pending = _pending(store, question_key=f"round-{index}")
        result = store.answer(
            session_id=SESSION,
            clarification_id=pending.clarification_id,
            request_fingerprint=FINGERPRINT,
            context_revision=REVISION,
            semantic_source_revision=SEMANTIC_REVISION,
            answer={"option_ref": pending.options[0].option_ref},
        )
        assert result.decision.round_index == index + 1
    with pytest.raises(BrainError) as raised:
        _pending(store, question_key="round-4", assumptions=["mai ammessa"])
    assert raised.value.code == "CLARIFICATION_BUDGET_EXCEEDED"
    assert store.metrics()["pending"] == 0
    assert (
        store.conversation(
            session_id=SESSION,
            request_fingerprint=FINGERPRINT,
        ).assumptions
        == ()
    )


def test_server_owned_conversation_key_preserves_budget_but_not_answer_binding() -> None:
    clock = Clock()
    store = _store(clock)
    refined_fingerprint = "sha256:" + "d" * 64

    for index in range(2):
        pending = _pending(store, question_key=f"initial-{index}")
        store.answer(
            session_id=SESSION,
            clarification_id=pending.clarification_id,
            request_fingerprint=FINGERPRINT,
            context_revision=REVISION,
            semantic_source_revision=SEMANTIC_REVISION,
            answer={"option_ref": pending.options[0].option_ref},
        )

    refined = _pending(
        store,
        question_key="refined-third",
        request_fingerprint=refined_fingerprint,
        conversation_key=FINGERPRINT,
    )
    with pytest.raises(BrainError) as raised:
        store.validate_answer(
            session_id=SESSION,
            clarification_id=refined.clarification_id,
            request_fingerprint=FINGERPRINT,
            context_revision=REVISION,
            semantic_source_revision=SEMANTIC_REVISION,
            answer={"option_ref": refined.options[0].option_ref},
        )
    assert raised.value.code == "CLARIFICATION_REQUEST_MISMATCH"

    resolved = store.answer(
        session_id=SESSION,
        clarification_id=refined.clarification_id,
        request_fingerprint=refined_fingerprint,
        context_revision=REVISION,
        semantic_source_revision=SEMANTIC_REVISION,
        answer={"option_ref": refined.options[0].option_ref},
    )
    assert resolved.conversation.rounds_used == 3
    context = store.server_context(session_id=SESSION, request_fingerprint=FINGERPRINT)
    assert context is not None
    assert len(context["decisions"]) == 3
    assert (
        store.server_context(
            session_id=SESSION,
            request_fingerprint=refined_fingerprint,
        )
        is None
    )

    with pytest.raises(BrainError) as raised:
        _pending(
            store,
            question_key="refined-fourth",
            request_fingerprint=refined_fingerprint,
            conversation_key=FINGERPRINT,
        )
    assert raised.value.code == "CLARIFICATION_BUDGET_EXCEEDED"


def test_answer_rejections_are_distinct_and_pending_remains_usable() -> None:
    clock = Clock()
    store = _store(clock)
    pending = _pending(store)
    cases = [
        (
            OTHER_SESSION,
            FINGERPRINT,
            REVISION,
            SEMANTIC_REVISION,
            None,
            "CLARIFICATION_CROSS_SESSION",
        ),
        (
            SESSION,
            "sha256:" + "d" * 64,
            REVISION,
            SEMANTIC_REVISION,
            None,
            "CLARIFICATION_REQUEST_MISMATCH",
        ),
        (
            SESSION,
            FINGERPRINT,
            "sha256:" + "d" * 64,
            SEMANTIC_REVISION,
            None,
            "CLARIFICATION_STALE_CONTEXT",
        ),
        (
            SESSION,
            FINGERPRINT,
            REVISION,
            "sha256:" + "d" * 64,
            None,
            "CLARIFICATION_STALE_SEMANTIC",
        ),
        (
            SESSION,
            FINGERPRINT,
            REVISION,
            SEMANTIC_REVISION,
            "result_count",
            "CLARIFICATION_WRONG_KIND",
        ),
    ]
    for session, fingerprint, context, semantic, kind, code in cases:
        with pytest.raises(BrainError) as raised:
            store.answer(
                session_id=session,
                clarification_id=pending.clarification_id,
                request_fingerprint=fingerprint,
                context_revision=context,
                semantic_source_revision=semantic,
                answer={"option_ref": pending.options[0].option_ref},
                expected_kind=kind,
            )
        assert raised.value.code == code
    assert store.metrics()["pending"] == 1


def test_one_shot_replay_unknown_and_expiry_are_distinct() -> None:
    clock = Clock()
    store = _store(clock)
    pending = _pending(store)
    store.answer(
        session_id=SESSION,
        clarification_id=pending.clarification_id,
        request_fingerprint=FINGERPRINT,
        context_revision=REVISION,
        semantic_source_revision=SEMANTIC_REVISION,
        answer={"option_ref": pending.options[0].option_ref},
    )
    with pytest.raises(BrainError) as raised:
        store.answer(
            session_id=SESSION,
            clarification_id=pending.clarification_id,
            request_fingerprint=FINGERPRINT,
            context_revision=REVISION,
            semantic_source_revision=SEMANTIC_REVISION,
            answer={"option_ref": pending.options[0].option_ref},
        )
    assert raised.value.code == "CLARIFICATION_REPLAY"
    with pytest.raises(BrainError) as raised:
        store.answer(
            session_id=SESSION,
            clarification_id="clr_unknown",
            request_fingerprint=FINGERPRINT,
            context_revision=REVISION,
            semantic_source_revision=SEMANTIC_REVISION,
            answer={"option_ref": "opt_unknown"},
        )
    assert raised.value.code == "CLARIFICATION_UNKNOWN"

    expired = _pending(store, question_key="expired")
    clock.advance(IDLE_TTL_SECONDS)
    with pytest.raises(BrainError) as raised:
        store.answer(
            session_id=SESSION,
            clarification_id=expired.clarification_id,
            request_fingerprint=FINGERPRINT,
            context_revision=REVISION,
            semantic_source_revision=SEMANTIC_REVISION,
            answer={"option_ref": expired.options[0].option_ref},
        )
    assert raised.value.code == "CLARIFICATION_EXPIRED"


def test_result_count_rejects_bool_out_of_range_and_extra_fields() -> None:
    clock = Clock()
    store = _store(clock, max_result_count=20)
    pending = _pending(store, kind="result_count", question_key="count", options=(), max_value=20)
    for answer, code in (
        ({"integer": True}, "CLARIFICATION_VALUE_OUT_OF_RANGE"),
        ({"integer": 0}, "CLARIFICATION_VALUE_OUT_OF_RANGE"),
        ({"integer": 21}, "CLARIFICATION_VALUE_OUT_OF_RANGE"),
        ({"integer": 4, "option_ref": "x"}, "INVALID_SCHEMA"),
    ):
        with pytest.raises(BrainError) as raised:
            store.answer(
                session_id=SESSION,
                clarification_id=pending.clarification_id,
                request_fingerprint=FINGERPRINT,
                context_revision=REVISION,
                semantic_source_revision=SEMANTIC_REVISION,
                answer=answer,
            )
        assert raised.value.code == code
    assert store.metrics()["pending"] == 1


def test_decisions_assumptions_and_refine_lineage_are_bounded_and_visible() -> None:
    clock = Clock()
    store = _store(clock)
    pending = _pending(store, assumptions=["catalogo unico verificato"])
    resolved = store.answer(
        session_id=SESSION,
        clarification_id=pending.clarification_id,
        request_fingerprint=FINGERPRINT,
        context_revision=REVISION,
        semantic_source_revision=SEMANTIC_REVISION,
        answer={"option_ref": pending.options[1].option_ref},
    )
    assert resolved.conversation.payload()["assumptions"] == ["catalogo unico verificato"]
    assert resolved.conversation.payload()["decisions"][0]["label"] == "B"
    summary = store.set_latest_proposal(
        session_id=SESSION,
        request_fingerprint=FINGERPRINT,
        proposal_ref="proposal_123",
    )
    assert summary.latest_proposal_ref == "proposal_123"
    assert (
        store.conversation(session_id=SESSION, request_fingerprint=FINGERPRINT).latest_proposal_ref
        == "proposal_123"
    )


def test_cancelled_turn_discards_only_its_pending_question_and_can_retry() -> None:
    clock = Clock()
    store = _store(clock)
    accepted = _pending(store, question_key="accepted", assumptions=["decisione conservata"])
    store.answer(
        session_id=SESSION,
        clarification_id=accepted.clarification_id,
        request_fingerprint=FINGERPRINT,
        context_revision=REVISION,
        semantic_source_revision=SEMANTIC_REVISION,
        answer={"option_ref": accepted.options[0].option_ref},
    )
    cancelled = _pending(
        store,
        question_key="cancelled",
        assumptions=["ipotesi mai mostrata"],
    )

    assert not store.discard_pending_for_turn(
        session_id=SESSION,
        parent_turn_id="turn_" + "b" * 32,
    )
    assert store.discard_pending_for_turn(
        session_id=SESSION,
        parent_turn_id=cancelled.parent_turn_id,
    )
    summary = store.conversation(session_id=SESSION, request_fingerprint=FINGERPRINT)
    assert [item.question_key for item in summary.decisions] == ["accepted"]
    assert summary.assumptions == ("decisione conservata",)
    assert store.metrics()["pending"] == 0

    retried = _pending(
        store,
        question_key="cancelled",
        assumptions=["ipotesi mai mostrata"],
    )
    assert retried.round_index == 2


def test_ttl_is_monotonic_bounded_and_drop_session_releases_everything() -> None:
    clock = Clock()
    store = _store(clock, ttl_seconds=10)
    pending = _pending(store)
    assert pending.expires_at == 10
    assert store.metrics()["sessions"] == 1
    removed = store.drop_session(SESSION)
    assert removed >= 2
    assert store.metrics() == {
        "sessions": 0,
        "conversations": 0,
        "pending": 0,
        "retired": 0,
        "decisions": 0,
        "assumptions": 0,
    }
    with pytest.raises(BrainError) as raised:
        store.answer(
            session_id=SESSION,
            clarification_id=pending.clarification_id,
            request_fingerprint=FINGERPRINT,
            context_revision=REVISION,
            semantic_source_revision=SEMANTIC_REVISION,
            answer={"option_ref": pending.options[0].option_ref},
        )
    assert raised.value.code == "CLARIFICATION_UNKNOWN"
    with pytest.raises(BrainError):
        ClarificationStore(ttl_seconds=IDLE_TTL_SECONDS + 1)


def test_revocation_guard_is_owned_and_a_late_worker_cannot_release_a_new_guard() -> None:
    clock = Clock()
    store = _store(clock)
    _pending(store)
    older_worker = "turn_" + "1" * 32
    current_worker = "turn_" + "2" * 32
    store.drop_session(SESSION, revocation_owner=current_worker)

    with pytest.raises(BrainError) as raised:
        _pending(store)
    assert raised.value.code == "SESSION_REVOKED"
    store.release_revocation_guard(SESSION, owner=older_worker)
    with pytest.raises(BrainError) as raised:
        _pending(store)
    assert raised.value.code == "SESSION_REVOKED"

    store.release_revocation_guard(SESSION, owner=current_worker)
    assert _pending(store).session_id == SESSION


def test_concurrent_answers_have_exactly_one_winner() -> None:
    clock = Clock()
    store = _store(clock)
    pending = _pending(store)
    barrier = threading.Barrier(2)
    results: list[str] = []

    def worker() -> None:
        barrier.wait()
        try:
            store.answer(
                session_id=SESSION,
                clarification_id=pending.clarification_id,
                request_fingerprint=FINGERPRINT,
                context_revision=REVISION,
                semantic_source_revision=SEMANTIC_REVISION,
                answer={"option_ref": pending.options[0].option_ref},
            )
        except BrainError as error:
            results.append(error.code)
        else:
            results.append("won")

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
    assert sorted(results) == ["CLARIFICATION_REPLAY", "won"]


def test_invalid_question_contracts_fail_closed() -> None:
    clock = Clock()
    store = _store(clock)
    for kwargs in (
        {"kind": "unknown"},
        {"kind": "catalog", "options": ["only"]},
        {"kind": "result_count", "options": ["forbidden"]},
        {"kind": "result_count", "options": (), "min_value": 0},
        {"kind": "result_count", "options": (), "max_value": 1001},
    ):
        with pytest.raises(BrainError) as raised:
            _pending(store, **kwargs)
        assert raised.value.status == 400


def test_clear_removes_all_sessions_and_replay_guards() -> None:
    clock = Clock()
    store = _store(clock)
    pending = _pending(store)
    store.answer(
        session_id=SESSION,
        clarification_id=pending.clarification_id,
        request_fingerprint=FINGERPRINT,
        context_revision=REVISION,
        semantic_source_revision=SEMANTIC_REVISION,
        answer={"option_ref": pending.options[0].option_ref},
    )
    assert store.metrics()["retired"] == 1
    assert store.clear() >= 2
    assert store.metrics() == {
        "sessions": 0,
        "conversations": 0,
        "pending": 0,
        "retired": 0,
        "decisions": 0,
        "assumptions": 0,
    }


V2_BINDING = DialogueBinding(REVISION, SEMANTIC_REVISION, FINGERPRINT, REVISION, FINGERPRINT)


def _v2_slot(target: str = "endpoint.catalogs", *, count: bool = False, **kwargs: object):
    defaults = dict(
        decision_key="count" if count else "catalog",
        target_key=target,
        kind="result_count" if count else "catalog",
        question="Quanti?" if count else "Quali?",
        answer_kind="integer" if count else "option_refs",
        minimum=1,
        maximum=100 if count else 2,
        value_contract="total" if count else "authority",
        choices=()
        if count
        else tuple(
            BoundChoice(name, (f"private.catalog.{name}",), REVISION, ("catalog",))
            for name in ("video", "users")
        ),
    )
    defaults.update(kwargs)
    return QuestionSlot(**defaults)


def _v2_pending(store, *, slots=None, **kwargs):
    args = dict(
        session_id=SESSION,
        parent_turn_id=TURN,
        conversation_id=FINGERPRINT,
        binding=V2_BINDING,
        slots=slots or (_v2_slot(),),
    )
    args.update(kwargs)
    return store.create_pending_v2(**args)


def _v2_answer(store, pending, answers, **kwargs):
    args = dict(
        session_id=SESSION,
        clarification_id=pending.clarification_id,
        binding=V2_BINDING,
        answers=answers,
    )
    args.update(kwargs)
    return store.answer_v2(**args)


def _v2_choice_answer(slot):
    return DialogueAnswer(
        slot.question_ref, tuple(choice.option_ref for choice in slot.choices), multiple=True
    )


def test_v2_multi_catalog_same_kind_counts_and_exact_private_mapping() -> None:
    store = _store(Clock())
    pending = _v2_pending(
        store,
        slots=(_v2_slot(), _v2_slot("row.main", count=True), _v2_slot("pool.seed", count=True)),
    )
    result = _v2_answer(
        store,
        pending,
        [
            _v2_choice_answer(pending.slots[0]),
            DialogueAnswer(pending.slots[1].question_ref, integer=24),
            DialogueAnswer(pending.slots[2].question_ref, integer=50),
        ],
    )
    assert result.remaining is None and len(result.decisions) == 3
    assert tuple(choice.authority_keys for choice in result.accepted[0].choices) == (
        ("private.catalog.video",),
        ("private.catalog.users",),
    )
    assert [(item.target_key, item.integer) for item in result.accepted[1:]] == [
        ("row.main", 24),
        ("pool.seed", 50),
    ]
    assert result.accepted[1].value_contract == "total"
    assert all(item.binding == V2_BINDING for item in result.accepted)
    assert store.metrics()["decisions"] == 3
    assert not store.has_pending(SESSION)
    with pytest.raises(BrainError, match="already consumed"):
        _v2_answer(store, pending, [_v2_choice_answer(pending.slots[0])])


def test_v2_same_kind_semantic_choices_at_distinct_targets_are_independent() -> None:
    store = _store(Clock())
    slots = tuple(
        _v2_slot(target, kind="semantic_choice")
        for target in ("predicate.origin", "predicate.audio")
    )
    pending = _v2_pending(store, slots=slots)
    result = _v2_answer(store, pending, [_v2_choice_answer(slot) for slot in pending.slots])
    assert len(result.decisions) == 2
    assert result.decisions[0].kind == result.decisions[1].kind == "semantic_choice"
    assert result.decisions[0].target_key != result.decisions[1].target_key


def test_v2_partial_rotates_single_use_id_but_does_not_spend_another_round() -> None:
    store = _store(Clock())
    pending = _v2_pending(store, slots=(_v2_slot(), _v2_slot("row.main", count=True)))
    partial = _v2_answer(store, pending, [_v2_choice_answer(pending.slots[0])])
    assert partial.remaining is not None
    assert partial.remaining.clarification_id != pending.clarification_id
    assert partial.remaining.round_index == pending.round_index == 1
    assert len(partial.remaining.slots) == 1
    assert partial.remaining.expires_at == pending.expires_at
    final = _v2_answer(
        store,
        partial.remaining,
        [DialogueAnswer(partial.remaining.slots[0].question_ref, integer=24)],
    )
    assert final.remaining is None and len(final.decisions) == 2
    following = _v2_pending(store, slots=(_v2_slot("row.other", count=True),))
    assert following.round_index == 2


@pytest.mark.parametrize(
    "mutation",
    ["unknown_question", "unknown_option", "cross_slot", "duplicate", "wrong_kind", "out_of_range"],
)
def test_v2_invalid_answers_are_atomic_and_leave_original_pending(mutation: str) -> None:
    store = _store(Clock())
    pending = _v2_pending(
        store, slots=(_v2_slot(), _v2_slot("other.catalogs"), _v2_slot("row.main", count=True))
    )
    first, second, count = pending.slots
    answers = [_v2_choice_answer(first)]
    if mutation == "unknown_question":
        answers.append(DialogueAnswer("q_unknown", integer=24))
    elif mutation == "unknown_option":
        answers.append(DialogueAnswer(second.question_ref, ("opt_unknown",), multiple=True))
    elif mutation == "cross_slot":
        answers.append(
            DialogueAnswer(second.question_ref, (first.choices[0].option_ref,), multiple=True)
        )
    elif mutation == "duplicate":
        answers.append(answers[0])
    elif mutation == "wrong_kind":
        answers.append(DialogueAnswer(count.question_ref, (first.choices[0].option_ref,)))
    else:
        answers.append(DialogueAnswer(count.question_ref, integer=101))
    with pytest.raises(BrainError):
        _v2_answer(store, pending, answers)
    assert store.has_pending(SESSION) and store.metrics()["decisions"] == 0
    assert len(_v2_answer(store, pending, [_v2_choice_answer(first)]).accepted) == 1


@pytest.mark.parametrize(
    "field",
    [
        "context_revision",
        "semantic_revision",
        "toolchain_binding",
        "history_revision",
        "parent_fingerprint",
    ],
)
def test_v2_all_five_authority_bindings_are_exact(field: str) -> None:
    store = _store(Clock())
    pending = _v2_pending(store)
    with pytest.raises(BrainError) as error:
        _v2_answer(
            store,
            pending,
            [_v2_choice_answer(pending.slots[0])],
            binding=replace(V2_BINDING, **{field: "sha256:" + "d" * 64}),
        )
    assert error.value.code == "CLARIFICATION_STALE"
    assert store.metrics()["decisions"] == 0


def test_v2_input_and_returned_objects_cannot_mutate_stored_authority() -> None:
    store = _store(Clock())
    slot = _v2_slot()
    pending = _v2_pending(store, slots=[slot])
    valid_answer = _v2_choice_answer(pending.slots[0])
    object.__setattr__(slot.choices[0], "authority_keys", ("evil.input",))
    object.__setattr__(pending.slots[0].choices[0], "authority_keys", ("evil.output",))
    result = _v2_answer(store, pending, [valid_answer])
    assert result.accepted[0].choices[0].authority_keys == ("private.catalog.video",)
    object.__setattr__(result.accepted[0].choices[0], "authority_keys", ("evil.result",))
    assert store.decisions_v2(session_id=SESSION, conversation_id=FINGERPRINT)[0].choices[
        0
    ].authority_keys == ("private.catalog.video",)


def test_v2_private_binding_never_appears_in_public_payload() -> None:
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator

    pending = _v2_pending(_store(Clock()))
    payload = pending.payload(now=0)
    encoded = json.dumps(payload)
    for secret in (
        "private.catalog",
        "authority_keys",
        "candidate_revision",
        "required_roles",
        "history_revision",
        "parent_fingerprint",
        SESSION,
        FINGERPRINT,
    ):
        assert secret not in encoded
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas/metis-brain-dialogue-v2.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(payload)


def test_v2_explicit_supersedes_is_same_logical_slot_only() -> None:
    store = _store(Clock())
    first = _v2_pending(store, slots=(_v2_slot("row.main", count=True),))
    decision = _v2_answer(
        store, first, [DialogueAnswer(first.slots[0].question_ref, integer=20)]
    ).accepted[0]
    with pytest.raises(BrainError):
        _v2_pending(store, slots=(_v2_slot("row.main", count=True),))
    with pytest.raises(BrainError):
        _v2_pending(
            store, slots=(_v2_slot("row.other", count=True, supersedes=decision.decision_sha256),)
        )
    next_pending = _v2_pending(
        store, slots=(_v2_slot("row.main", count=True, supersedes=decision.decision_sha256),)
    )
    result = _v2_answer(
        store, next_pending, [DialogueAnswer(next_pending.slots[0].question_ref, integer=24)]
    )
    assert len(result.decisions) == 2
    assert result.decisions[-1].supersedes == result.decisions[0].decision_sha256


def test_v2_ttl_claim_release_cross_session_and_drop() -> None:
    clock = Clock()
    store = _store(clock)
    pending = _v2_pending(store)
    answers = [_v2_choice_answer(pending.slots[0])]
    with pytest.raises(BrainError) as error:
        _v2_answer(store, pending, answers, session_id=OTHER_SESSION)
    assert error.value.code == "CLARIFICATION_CROSS_SESSION"
    store.validate_answers_v2(
        session_id=SESSION,
        clarification_id=pending.clarification_id,
        binding=V2_BINDING,
        answers=answers,
        claim_owner=TURN,
    )
    clock.advance(IDLE_TTL_SECONDS)
    assert store.sweep_expired() == 0
    with pytest.raises(BrainError) as error:
        _v2_answer(store, pending, answers)
    assert error.value.code == "CLARIFICATION_CLAIMED"
    assert store.release_answer_claim(session_id=SESSION, owner=TURN)
    assert store.sweep_expired() == 1
    with pytest.raises(BrainError) as error:
        _v2_answer(store, pending, answers)
    assert error.value.code == "CLARIFICATION_EXPIRED"
    assert store.drop_session(SESSION, revocation_owner=TURN) >= 1
    with pytest.raises(BrainError):
        _v2_pending(store)
    store.clear()
    assert all(value == 0 for value in store.metrics().values())


def test_v1_v2_share_one_pending_and_wrong_version_fails_closed() -> None:
    store = _store(Clock())
    pending = _v2_pending(store)
    with pytest.raises(BrainError):
        _pending(store)
    with pytest.raises(BrainError) as error:
        store.answer(
            session_id=SESSION,
            clarification_id=pending.clarification_id,
            request_fingerprint=FINGERPRINT,
            context_revision=REVISION,
            semantic_source_revision=SEMANTIC_REVISION,
            answer={"option_ref": pending.slots[0].choices[0].option_ref},
        )
    assert error.value.code == "CLARIFICATION_WRONG_VERSION"
    assert store.discard_pending_for_turn(session_id=SESSION, parent_turn_id=TURN)
    old = _pending(store)
    with pytest.raises(BrainError):
        _v2_pending(store)
    with pytest.raises(BrainError) as error:
        store.answer_v2(
            session_id=SESSION,
            clarification_id=old.clarification_id,
            binding=V2_BINDING,
            answers=[DialogueAnswer("q_a", integer=10)],
        )
    assert error.value.code == "CLARIFICATION_WRONG_VERSION"


def test_v2_three_round_limit_and_five_slot_limit() -> None:
    store = _store(Clock())
    with pytest.raises(BrainError):
        _v2_pending(store, slots=tuple(_v2_slot(f"row.{i}", count=True) for i in range(6)))
    for i in range(3):
        pending = _v2_pending(store, slots=(_v2_slot(f"row.{i}", count=True),))
        _v2_answer(store, pending, [DialogueAnswer(pending.slots[0].question_ref, integer=20)])
    with pytest.raises(BrainError) as error:
        _v2_pending(store, slots=(_v2_slot("row.final", count=True),))
    assert error.value.code == "CLARIFICATION_BUDGET_EXCEEDED"


def test_v2_stable_conversation_survives_new_parent_fingerprint_without_transcript_storage() -> (
    None
):
    store = _store(Clock())
    first = _v2_pending(store)
    _v2_answer(store, first, [_v2_choice_answer(first.slots[0])])
    next_binding = replace(
        V2_BINDING, parent_fingerprint="sha256:" + "e" * 64, history_revision="sha256:" + "f" * 64
    )
    second = _v2_pending(store, slots=(_v2_slot("row.main", count=True),), binding=next_binding)
    recovered = store.pending_v2(session_id=SESSION, clarification_id=second.clarification_id)
    assert recovered.conversation_id == first.conversation_id == FINGERPRINT
    assert recovered.binding.parent_fingerprint != first.binding.parent_fingerprint
    assert len(store.decisions_v2(session_id=SESSION, conversation_id=FINGERPRINT)) == 1
    assert not hasattr(store._conversations_v2[(SESSION, FINGERPRINT)], "messages")
    assert not hasattr(recovered, "messages")
    result = _v2_answer(
        store,
        second,
        [DialogueAnswer(second.slots[0].question_ref, integer=24)],
        binding=recovered.binding,
    )
    assert len(result.decisions) == 2
    store.drop_session(SESSION)
    assert store.decisions_v2(session_id=SESSION, conversation_id=FINGERPRINT) == ()
    assert all(value == 0 for value in store.metrics().values())


def test_v2_claim_binds_exact_answer_roster_and_release_allows_new_choice() -> None:
    store = _store(Clock())
    pending = _v2_pending(store, slots=(_v2_slot("row.main", count=True),))
    first = [DialogueAnswer(pending.slots[0].question_ref, integer=20)]
    changed = [DialogueAnswer(pending.slots[0].question_ref, integer=24)]
    args = dict(
        session_id=SESSION,
        clarification_id=pending.clarification_id,
        binding=V2_BINDING,
        claim_owner=TURN,
    )
    store.validate_answers_v2(**args, answers=first)
    with pytest.raises(BrainError) as error:
        store.answer_v2(**args, answers=changed)
    assert error.value.code == "CLARIFICATION_CLAIM_MISMATCH"
    assert store.metrics()["decisions"] == 0
    assert store.release_answer_claim(session_id=SESSION, owner=TURN)
    store.validate_answers_v2(**args, answers=changed)
    assert store.answer_v2(**args, answers=changed).accepted[0].integer == 24


def test_v2_concurrent_consumers_have_one_winner() -> None:
    store = _store(Clock())
    pending = _v2_pending(store, slots=(_v2_slot("row.main", count=True),))
    barrier = threading.Barrier(2)
    outcomes = []

    def consume():
        barrier.wait()
        try:
            _v2_answer(store, pending, [DialogueAnswer(pending.slots[0].question_ref, integer=24)])
            outcomes.append("accepted")
        except BrainError as error:
            outcomes.append(error.code)

    threads = [threading.Thread(target=consume) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()
    assert sorted(outcomes) == ["CLARIFICATION_REPLAY", "accepted"]
    assert store.metrics()["decisions"] == 1
