"""Bounded dialogue decisions for descriptor-native structural operations."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from metis_model1.brain_clarifications import ClarificationStore
from metis_model1.brain_create_descriptor_dialogue import (
    _Choices,
    _operation_request_revision,
)
from metis_model1.brain_create_surface import (
    CreateAuthorityHistoryMessage,
    create_authority_history_revision,
)
from metis_model1.brain_dialogue_contract import (
    BoundChoice,
    BoundDecision,
    DialogueBinding,
    PrivateDialogueState,
)
from metis_model1.brain_dialogue_planner import (
    QuantityNeed,
    adjudicate_dialogue_answer,
    resolve_dialogue_answer,
)
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_sha256


def _hash(label: str) -> str:
    return bytes_sha256(label.encode("utf-8"))


def _state(messages: tuple[str, ...]) -> PrivateDialogueState:
    history = tuple(
        CreateAuthorityHistoryMessage(index, text, _hash(text))
        for index, text in enumerate(messages)
    )
    return PrivateDialogueState(
        conversation_id=_hash("descriptor-dialogue"),
        binding=DialogueBinding(
            context_revision=_hash("context"),
            semantic_revision=_hash("semantic"),
            toolchain_binding=_hash("toolchain"),
            history_revision=create_authority_history_revision(history),
            parent_fingerprint=_hash("parent"),
        ),
        messages=history,
    )


def _choice(
    *,
    key: str,
    scope: str,
    options: list[tuple[str, str, str]],
    option_ref: str = "opt_choice",
    authority_keys: tuple[str, ...] = ("operation:0",),
    candidate_revision: str | None = None,
) -> BoundChoice:
    revision = candidate_revision or canonical_sha256(
        {"scope": scope, "key": key, "options": options}
    )
    return BoundChoice(
        label=options[0][1],
        authority_keys=authority_keys,
        candidate_revision=revision,
        required_roles=("scalar",),
        description=options[0][2],
        option_ref=option_ref,
    )


def _choice_decision(
    state: PrivateDialogueState,
    *,
    key: str,
    choice: BoundChoice,
) -> BoundDecision:
    return BoundDecision(
        decision_key=f"choice.general.{key}",
        target_key=f"general.{key}",
        kind="structural_choice",
        question_ref="q_choice",
        answer_kind="option_ref",
        binding=state.binding,
        choices=(choice,),
    )


def _selected_slot_decision(
    state: PrivateDialogueState, *, slot, choice_index: int, question_ref: str
) -> BoundDecision:
    return BoundDecision(
        decision_key=slot.decision_key,
        target_key=slot.target_key,
        kind=slot.kind,
        question_ref=question_ref,
        answer_kind=slot.answer_kind,
        binding=state.binding,
        choices=(replace(slot.choices[choice_index], option_ref=f"opt_{question_ref[2:]}"),),
        value_contract=slot.value_contract,
    )


def _integer_decision(
    state: PrivateDialogueState, *, integer: int, contract: str = "total"
) -> BoundDecision:
    scope = "page" if contract == "page_default" else "total"
    return BoundDecision(
        decision_key=f"qty.result_count.{scope}.{contract}.any",
        target_key=f"general.count.{contract}",
        kind="structural_choice",
        question_ref="q_count",
        answer_kind="integer",
        binding=state.binding,
        integer=integer,
        value_contract=contract,
    )


def test_stale_choice_candidate_reasks_with_exact_supersedes() -> None:
    key, scope = "operation", _hash("scope")
    options = [("add", "Aggiungi blocco", "Crea un blocco revisionato")]
    state = _state(("Crea un blocco.",))
    prior = _choice_decision(
        state,
        key=key,
        choice=_choice(
            key=key,
            scope=scope,
            options=options,
            candidate_revision=_hash("stale-candidate"),
        ),
    )
    dialogue = replace(state, decisions=(prior,))
    choices = _Choices(dialogue, scope)

    assert choices.choice(key, "Quale blocco?", options) is None
    assert choices.used == []
    assert len(choices.pending) == 1
    assert choices.pending[0].supersedes == prior.decision_sha256


def test_fresh_choice_cannot_reuse_after_new_substantive_message() -> None:
    key, scope = "operation", _hash("scope")
    options = [("add", "Aggiungi blocco", "Crea un blocco revisionato")]
    first = _state(("Crea un blocco.",))
    prior = _choice_decision(first, key=key, choice=_choice(key=key, scope=scope, options=options))
    dialogue = replace(
        _state(("Crea un blocco.", "Aggiungi anche un fallback.")), decisions=(prior,)
    )
    choices = _Choices(dialogue, scope)

    assert choices.choice(key, "Quale blocco?", options, fresh=True) is None
    assert choices.pending[0].supersedes == prior.decision_sha256


def test_fresh_choice_accepts_exact_appended_label() -> None:
    key, scope = "operation", _hash("scope")
    options = [("add", "Aggiungi blocco", "Crea un blocco revisionato")]
    first = _state(("Crea un blocco.",))
    prior = _choice_decision(first, key=key, choice=_choice(key=key, scope=scope, options=options))
    dialogue = replace(_state(("Crea un blocco.", "aggiungi BLOCCO")), decisions=(prior,))
    choices = _Choices(dialogue, scope)

    assert choices.choice(key, "Quale blocco?", options, fresh=True) == "add"
    assert choices.pending == []
    assert choices.used == [prior.decision_sha256]


def test_integer_reuse_is_scoped_by_base_and_dependencies() -> None:
    key, scope, dependencies = "count", _hash("base-a"), {"blocks": ["main"]}
    state = _state(("Crea un blocco.",))
    scoped = canonical_sha256({"scope": scope, "key": key, "deps": dependencies})[7:31]
    prior = BoundDecision(
        decision_key="qty.result_count.total.total.any",
        target_key=f"general.{key}.{scoped}",
        kind="structural_choice",
        question_ref="q_count",
        answer_kind="integer",
        binding=state.binding,
        integer=17,
        value_contract="total",
    )
    dialogue = replace(state, decisions=(prior,))

    assert (
        _Choices(dialogue, scope).integer(
            key, "Quanti?", contract="total", dependencies=dependencies
        )
        == 17
    )
    changed_base = _Choices(dialogue, _hash("base-b"))
    changed_dependencies = _Choices(dialogue, scope)
    assert changed_base.integer(key, "Quanti?", contract="total", dependencies=dependencies) is None
    assert (
        changed_dependencies.integer(
            key, "Quanti?", contract="total", dependencies={"blocks": ["other"]}
        )
        is None
    )
    assert len(changed_base.pending) == len(changed_dependencies.pending) == 1


def test_malformed_bound_choice_is_rejected_and_reasked() -> None:
    key, scope = "operation", _hash("scope")
    options = [("add", "Aggiungi blocco", "Crea un blocco revisionato")]
    state = _state(("Crea un blocco.",))
    prior = _choice_decision(
        state,
        key=key,
        choice=_choice(key=key, scope=scope, options=options, authority_keys=("operation:other",)),
    )
    choices = _Choices(replace(state, decisions=(prior,)), scope)

    assert choices.choice(key, "Quale blocco?", options) is None
    assert choices.pending[0].supersedes == prior.decision_sha256


def test_choice_bound_is_64_and_overflow_fails_closed() -> None:
    scope = _hash("scope")
    state = _state(("Crea un blocco.",))
    allowed = [(f"value-{index}", f"Etichetta {index}", "Descrizione") for index in range(64)]
    choices = _Choices(state, scope)

    assert choices.choice("operation", "Quale blocco?", allowed) is None
    assert len(choices.pending[0].choices) == 64
    with pytest.raises(BrainError) as raised:
        choices.choice("overflow", "Quale blocco?", [*allowed, ("extra", "Extra", "Descrizione")])
    assert raised.value.code == "CREATE_TYPED_AUTHORITY_UNSUPPORTED"


def test_operation_request_revision_resets_after_new_count_request() -> None:
    first = _state(("Crea un blocco.",))
    count = _integer_decision(first, integer=24)
    dialogue = replace(
        _state(("Crea un blocco.", "24", "Nuova richiesta: 12 risultati.")), decisions=(count,)
    )

    assert _operation_request_revision(dialogue) == create_authority_history_revision(
        dialogue.messages
    )
    assert _operation_request_revision(dialogue) != first.binding.history_revision


@pytest.mark.parametrize(
    ("integer", "contract", "answer"),
    [
        (24, "total", "24 risultati"),
        (12, "page_default", "12 per pagina"),
        (12, "total", "dodici"),
    ],
)
def test_operation_request_revision_preserves_complete_scoped_integer_answer(
    integer: int, contract: str, answer: str
) -> None:
    first = _state(("Crea un blocco.",))
    dialogue = replace(
        _state(("Crea un blocco.", answer)),
        decisions=(_integer_decision(first, integer=integer, contract=contract),),
    )

    assert _operation_request_revision(dialogue) == first.binding.history_revision


def test_operation_request_revision_resets_when_integer_answer_carries_filters() -> None:
    first = _state(("Crea un blocco.",))
    dialogue = replace(
        _state(("Crea un blocco.", "24 risultati extra filters")),
        decisions=(_integer_decision(first, integer=24),),
    )

    assert _operation_request_revision(dialogue) == create_authority_history_revision(
        dialogue.messages
    )


def test_operation_request_revision_resets_when_integer_page_contract_mismatches() -> None:
    first = _state(("Crea un blocco.",))
    dialogue = replace(
        _state(("Crea un blocco.", "12 per pagina")),
        decisions=(_integer_decision(first, integer=12),),
    )

    assert _operation_request_revision(dialogue) == create_authority_history_revision(
        dialogue.messages
    )


def test_generic_integer_pending_slot_is_resolved_by_the_dialogue_resolver() -> None:
    first = _state(("Crea un blocco.",))
    pending = ClarificationStore().create_pending_v2(
        session_id="session_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        parent_turn_id="turn_aaaaaaaaaaaaaaaaaaaaaaaa",
        conversation_id=first.conversation_id,
        binding=first.binding,
        slots=(QuantityNeed("endpoint", necessary=True, maximum=50).slot(),),
    )
    dialogue = _state(("Crea un blocco.", "24 risultati"))
    request = SimpleNamespace(dialogue_answer=SimpleNamespace(message="24 risultati"))

    answers = resolve_dialogue_answer(request=request, pending=pending, dialogue=dialogue)

    assert answers[0].integer == 24


def test_operation_request_revision_preserves_exact_adjacent_label_answer() -> None:
    options = [("add", "Aggiungi blocco", "Crea un blocco revisionato")]
    first = _state(("Crea un blocco.",))
    decision = _choice_decision(
        first,
        key="operation",
        choice=_choice(key="operation", scope=_hash("scope"), options=options),
    )
    dialogue = replace(_state(("Crea un blocco.", "Aggiungi blocco")), decisions=(decision,))

    assert _operation_request_revision(dialogue) == first.binding.history_revision


def test_operation_request_revision_resets_when_label_carries_new_requirement() -> None:
    options = [("add", "Aggiungi blocco", "Crea un blocco revisionato")]
    first = _state(("Crea un blocco.",))
    decision = _choice_decision(
        first,
        key="operation",
        choice=_choice(key="operation", scope=_hash("scope"), options=options),
    )
    dialogue = replace(
        _state(("Crea un blocco.", "Aggiungi blocco e fallback.")), decisions=(decision,)
    )

    assert _operation_request_revision(dialogue) == create_authority_history_revision(
        dialogue.messages
    )


def test_operation_request_revision_resets_after_refusal_then_new_instruction() -> None:
    options = [("defer", "Serve una struttura più articolata", "Chiedi più dettagli")]
    first = _state(("Crea un blocco.",))
    decision = _choice_decision(
        first,
        key="operation",
        choice=_choice(key="operation", scope=_hash("scope"), options=options),
    )
    dialogue = replace(
        _state(
            (
                "Crea un blocco.",
                "Serve una struttura più articolata",
                "Ora crea solo una collezione filtrata.",
            )
        ),
        decisions=(decision,),
    )

    assert _operation_request_revision(dialogue) == create_authority_history_revision(
        dialogue.messages
    )


def test_paged_choice_exposes_the_last_item_of_the_second_page() -> None:
    scope = _hash("scope")
    options = [(f"value-{index}", f"Etichetta {index}", "Descrizione") for index in range(128)]
    state = _state(("Ordina il blocco.",))
    initial = _Choices(state, scope)

    assert initial.paged_choice("field", "Quale campo?", options) is None
    page_slot = initial.pending[0]
    page_decision = _selected_slot_decision(
        state, slot=page_slot, choice_index=1, question_ref="q_page"
    )
    second_page = _Choices(replace(state, decisions=(page_decision,)), scope)
    assert second_page.paged_choice("field", "Quale campo?", options) is None
    field_slot = second_page.pending[0]
    field_decision = _selected_slot_decision(
        state, slot=field_slot, choice_index=63, question_ref="q_field"
    )
    resolved = _Choices(replace(state, decisions=(page_decision, field_decision)), scope)

    assert resolved.paged_choice("field", "Quale campo?", options) == "value-127"
    assert resolved.pending == []


def test_paged_choice_over_4096_fails_closed() -> None:
    scope = _hash("scope")
    options = [(f"value-{index}", f"Etichetta {index}", "Descrizione") for index in range(4097)]

    with pytest.raises(BrainError) as raised:
        _Choices(_state(("Ordina il blocco.",)), scope).paged_choice(
            "field", "Quale campo?", options
        )

    assert raised.value.code == "CREATE_TYPED_AUTHORITY_UNSUPPORTED"


def _natural_answer(state, slot, message, store):
    pending = store.create_pending_v2(
        session_id="session_" + "n" * 32,
        parent_turn_id="turn_" + "n" * 32,
        conversation_id=state.conversation_id,
        binding=state.binding,
        slots=(slot,),
    )
    continued = replace(
        _state(tuple(item.text for item in state.messages) + (message,)),
        decisions=state.decisions,
    )
    answers = adjudicate_dialogue_answer(message=message, pending=pending, dialogue=continued)
    assert len(answers) == 1, (message, pending.payload())
    args = dict(
        session_id=pending.session_id,
        clarification_id=pending.clarification_id,
        binding=pending.binding,
        answers=answers,
        claim_owner=pending.parent_turn_id,
    )
    admitted = store.validate_answers_v2(**args)
    result = store.answer_v2(**args)
    assert result.accepted == admitted and result.remaining is None
    return replace(continued, decisions=result.decisions)


@pytest.mark.parametrize(
    ("label", "message"),
    [
        ("Ordinamento per campo", "Scelgo Ordinamento per campo"),
        ("main take 1", "main take 1"),
        ("Scelte 1-64", "Scelte 1-64"),
        ("Annulla operazione", "Annulla operazione"),
    ],
)
def test_natural_adjudication_and_store_preserve_the_operation_revision(label, message) -> None:
    state = _state(("Modifica questa raccolta.",))
    scope = _hash("natural-bound-choice")
    options = [("selected", label, "Scelta generica verificata")]
    question = _Choices(state, scope)
    assert question.choice("operation", "Quale operazione?", options, fresh=True) is None
    answered = _natural_answer(state, question.pending[0], message, ClarificationStore())
    assert _operation_request_revision(answered) == state.binding.history_revision
    resolved = _Choices(answered, scope)
    assert resolved.choice("operation", "Quale operazione?", options, fresh=True) == "selected"
    assert resolved.pending == []
    assert len(resolved.used) == 1


def test_natural_page_then_last_field_preserves_both_independently_bound_answers() -> None:
    state = _state(("Ordina questa raccolta.",))
    scope = _hash("natural-paged-choice")
    options = [(f"field-{index}", f"Misura {index}", "Misura indipendente") for index in range(69)]
    store = ClarificationStore()
    pages = _Choices(state, scope)
    assert pages.paged_choice("field", "Quale campo?", options) is None
    page_answered = _natural_answer(state, pages.pending[0], "Scelte 65-69", store)
    fields = _Choices(page_answered, scope)
    assert fields.paged_choice("field", "Quale campo?", options) is None
    field_answered = _natural_answer(page_answered, fields.pending[0], "Scelgo Misura 68", store)
    selected = _Choices(field_answered, scope)
    assert selected.paged_choice("field", "Quale campo?", options) == "field-68"
    assert _operation_request_revision(field_answered) == state.binding.history_revision
    assert len(selected.used) == 2
    assert len({decision.question_ref for decision in field_answered.decisions}) == 2


def test_answer_with_new_requirement_cannot_hide_that_requirement_as_procedural() -> None:
    state = _state(("Modifica questa raccolta.",))
    scope = _hash("natural-substantive")
    options = [("order", "Ordinamento per campo", "Ordina per un campo verificato")]
    question = _Choices(state, scope)
    assert question.choice("operation", "Quale operazione?", options) is None
    answered = _natural_answer(
        state,
        question.pending[0],
        "Scelgo Ordinamento per campo; aggiungi anche un fallback.",
        ClarificationStore(),
    )
    assert _operation_request_revision(answered) == answered.binding.history_revision
    resolved = _Choices(answered, scope)
    assert resolved.choice("operation", "Quale operazione?", options, fresh=True) is None
    assert resolved.pending[0].supersedes == answered.decisions[-1].decision_sha256
