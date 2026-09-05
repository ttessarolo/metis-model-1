from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from metis_model1.brain_create_surface import (
    CreateAuthorityHistoryMessage,
    create_authority_history_revision,
)
from metis_model1.brain_dialogue_contract import (
    BoundChoice,
    BoundDecision,
    DialogueAnswer,
    DialogueAnswerEnvelope,
    DialogueBinding,
    PrivateDialogueState,
    QuestionSlot,
    decision_roster,
)
from metis_model1.brain_protocol import BrainError, bytes_sha256

HASH = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64


def binding(history: str = HASH) -> DialogueBinding:
    return DialogueBinding(HASH, HASH, HASH, history, HASH)


def choice(**kwargs: object) -> BoundChoice:
    values = dict(
        label="Video",
        authority_keys=("catalog.video",),
        candidate_revision=HASH,
        required_roles=("catalog",),
    )
    values.update(kwargs)
    return BoundChoice(**values)


def envelope() -> dict:
    return {
        "schema_version": 2,
        "request_id": "11111111-1111-4111-8111-111111111111",
        "clarification_id": "clr_example",
        "message": "Usa video e users.\n20 risultati per riga.",
        "answers": [],
    }


def decision(**kwargs: object) -> BoundDecision:
    values = dict(
        decision_key="count",
        target_key="row.main",
        kind="result_count",
        question_ref="q_count",
        answer_kind="integer",
        binding=binding(),
        integer=20,
        value_contract="total",
    )
    values.update(kwargs)
    return BoundDecision(**values)


def test_message_envelope_preserves_exact_text_and_matches_closed_schema() -> None:
    raw = envelope()
    parsed = DialogueAnswerEnvelope.parse(raw)
    assert parsed.payload() == raw
    schema = json.loads(
        (Path(__file__).parents[1] / "schemas/metis-brain-dialogue-v2.schema.json").read_text()
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(parsed.payload())
    assert raw["message"] not in repr(parsed)


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": True},
        {"schema_version": 1},
        {"history": []},
        {"authority_keys": ["catalog.video"]},
        {"message": " "},
        {"message": "x" * 65537},
        {"message": "é" * 32769},
        {"message": None},
        {"message": "a\0b"},
        {"answers": [{}]},
        {"request_id": "invalid"},
        {"clarification_id": "hostref:fake"},
    ],
)
def test_invalid_or_spoofed_answer_envelopes_fail(change: dict) -> None:
    with pytest.raises(BrainError):
        DialogueAnswerEnvelope.parse({**envelope(), **change})


@pytest.mark.parametrize(
    "value",
    [
        {"integer": True},
        {"integer": 0},
        {"integer": 1_000_001},
        {"integer": 3, "option_ref": "opt_a"},
        {"option_refs": []},
        {"option_refs": ["opt_a", "opt_a"]},
        {"option_ref": "catalog.video"},
        {"authority_key": "catalog.video"},
    ],
)
def test_closed_answer_values(value: dict) -> None:
    with pytest.raises(BrainError):
        DialogueAnswer.parse({"question_ref": "q_one", "value": value})


def test_public_answer_values_roundtrip_and_input_mutation_does_not_alias() -> None:
    raw = {
        **envelope(),
        "message": None,
        "answers": [
            {"question_ref": "q_one", "value": {"option_refs": ["opt_video", "opt_users"]}},
            {"question_ref": "q_two", "value": {"integer": 24}},
        ],
    }
    parsed = DialogueAnswerEnvelope.parse(raw)
    raw["answers"][0]["value"]["option_refs"].append("opt_evil")
    assert parsed.answers[0].option_refs == ("opt_video", "opt_users")
    assert parsed.answers[1].integer == 24
    with pytest.raises(BrainError):
        replace(parsed, answers=(*parsed.answers, parsed.answers[0]))


def test_choice_and_slot_copy_private_authority_without_public_leakage() -> None:
    keys, roles = ["private.video.authority"], ["catalog"]
    declared = choice(authority_keys=keys, required_roles=roles)
    keys.append("private.evil")
    roles.append("field")
    assert declared.authority_keys == ("private.video.authority",)
    assert declared.required_roles == ("catalog",)
    slot = QuestionSlot(
        "catalog", "endpoint", "catalog", "Quali cataloghi?", "option_ref", (declared,)
    )
    issued = replace(
        slot, question_ref="q_catalog", choices=(replace(declared, option_ref="opt_video"),)
    )
    public = json.dumps(issued.public_payload())
    for private in (
        "private.video.authority",
        "candidate_revision",
        "required_roles",
        "target_key",
        "decision_key",
    ):
        assert private not in public


@pytest.mark.parametrize(
    "kwargs",
    [
        {"required_roles": ("unknown_role",)},
        {"authority_keys": ()},
        {"authority_keys": ("catalog.video", "catalog.video")},
        {"candidate_revision": "stale"},
        {"option_ref": "fake"},
    ],
)
def test_invalid_choices(kwargs: dict) -> None:
    with pytest.raises(BrainError):
        choice(**kwargs)


def test_same_kind_different_slots_and_explicit_same_slot_replacement() -> None:
    first = decision()
    second = decision(target_key="pool.recent", question_ref="q_pool", integer=50)
    replacement = decision(question_ref="q_new", integer=24, supersedes=first.decision_sha256)
    assert len(decision_roster((first, second, replacement))) == 3
    for bad in (
        (first, first),
        (first, replace(second, supersedes=first.decision_sha256)),
        (first, replace(replacement, supersedes=OTHER)),
    ):
        with pytest.raises(BrainError):
            decision_roster(bad)


def test_private_history_can_exist_before_draft_and_retains_t1_t2() -> None:
    messages = tuple(
        CreateAuthorityHistoryMessage(i, text, bytes_sha256(text.encode()))
        for i, text in enumerate(("Voglio una riga", "Video, 24 totali"))
    )
    first = binding(create_authority_history_revision(messages[:1]))
    current = binding(create_authority_history_revision(messages))
    state = PrivateDialogueState(HASH, current, messages, (decision(binding=first),))
    assert state.latest_proposal_binding is None and len(state.messages) == 2
    assert "Voglio" not in repr(state)
    assert state.revision != replace(state, generation=1).revision
    for kwargs in (
        {"binding": binding(OTHER)},
        {"decisions": (decision(binding=replace(first, semantic_revision=OTHER)),)},
        {"decisions": (decision(binding=binding(OTHER)),)},
    ):
        with pytest.raises(BrainError):
            replace(state, **kwargs)


@pytest.mark.parametrize("value", [[{}], [None], [1], [["opt_a"]]])
def test_malformed_reference_rosters_fail_with_typed_error(value) -> None:
    with pytest.raises(BrainError):
        DialogueAnswer.parse({"question_ref": "q_one", "value": {"option_refs": value}})


def test_overfetch_bounds_are_not_general_count_bounds() -> None:
    for minimum, maximum in ((1, 2), (2, 17)):
        with pytest.raises(BrainError):
            QuestionSlot(
                "count",
                "fetch.main",
                "result_count",
                "Fattore?",
                "integer",
                minimum=minimum,
                maximum=maximum,
                value_contract="over_fetch",
            )
    with pytest.raises(BrainError):
        decision(integer=1, value_contract="over_fetch")
    assert decision(integer=2, value_contract="over_fetch").integer == 2
