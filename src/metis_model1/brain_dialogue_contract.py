"""Closed, volatile dialogue-v2 contracts shared by all Brain clients.

Only TurnStore may own ``PrivateDialogueState`` and its operator messages.
ClarificationStore retains bindings/decisions, never that state or transcript.
Public projections are explicit allow-lists, not dataclass serialization.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from metis_model1.brain_create_plan import HOST_REF_ROLES
from metis_model1.brain_create_surface import (
    CreateAuthorityHistoryMessage,
    create_authority_history_revision,
)
from metis_model1.brain_protocol import BrainError, canonical_sha256, request_identifier

DIALOGUE_CONTRACT = "metis-brain-dialogue/v2"
MAX_QUESTIONS = 5
MAX_CHOICES = 64
MAX_DECISIONS = 32
MAX_MESSAGE_BYTES = 65_536
KINDS = frozenset(
    {
        "catalog",
        "semantic_choice",
        "result_count",
        "response_shape",
        "fallback",
        "structural_choice",
    }
)
ANSWER_KINDS = frozenset({"option_ref", "option_refs", "integer"})
VALUE_CONTRACTS = frozenset(
    {"authority", "total", "page_default", "rows", "fetches", "blocks", "instances", "over_fetch"}
)
_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,127}$")
_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")
_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


def invalid(message: str = "dialogue contract is invalid") -> None:
    raise BrainError("DIALOGUE_INVALID", 400, message)


def _text(value: Any, maximum: int, *, multiline: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        invalid()
    try:
        raw = value.encode("utf-8")
    except UnicodeError as error:
        raise BrainError("DIALOGUE_INVALID", 400, "dialogue text is invalid") from error
    if len(raw) > maximum or any(
        ord(char) < 32 and not (multiline and char in "\n\r\t") for char in value
    ):
        invalid()
    return value


def _key(value: Any) -> str:
    if not isinstance(value, str) or _KEY.fullmatch(value) is None:
        invalid()
    return value


def _hash(value: Any) -> str:
    if not isinstance(value, str) or _HASH.fullmatch(value) is None:
        invalid()
    return value


def _ref(value: Any, prefix: str) -> str:
    if not isinstance(value, str) or not value.startswith(prefix) or _REF.fullmatch(value) is None:
        invalid()
    return value


def _roster(values: Any, *, maximum: int, minimum: int = 1) -> tuple[Any, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        invalid()
    result = tuple(values)
    if not minimum <= len(result) <= maximum:
        invalid()
    return result


@dataclass(frozen=True, slots=True, repr=False)
class DialogueBinding:
    context_revision: str
    semantic_revision: str
    toolchain_binding: str
    history_revision: str
    parent_fingerprint: str

    def __post_init__(self) -> None:
        for value in self.manifest().values():
            _hash(value)

    def manifest(self) -> dict[str, str]:
        return {
            "context_revision": self.context_revision,
            "semantic_revision": self.semantic_revision,
            "toolchain_binding": self.toolchain_binding,
            "history_revision": self.history_revision,
            "parent_fingerprint": self.parent_fingerprint,
        }


@dataclass(frozen=True, slots=True, repr=False)
class BoundChoice:
    label: str
    authority_keys: tuple[str, ...]
    candidate_revision: str
    required_roles: tuple[str, ...]
    description: str | None = None
    option_ref: str | None = None

    def __post_init__(self) -> None:
        _text(self.label, 256)
        if self.description is not None:
            _text(self.description, 1024)
        _hash(self.candidate_revision)
        keys = _roster(self.authority_keys, maximum=32)
        roles = _roster(self.required_roles, maximum=32)
        for key in keys:
            _key(key)
        if any(not isinstance(role, str) for role in roles):
            invalid()
        if len(set(keys)) != len(keys) or len(set(roles)) != len(roles):
            invalid()
        if not set(roles).issubset(HOST_REF_ROLES):
            invalid()
        object.__setattr__(self, "authority_keys", keys)
        object.__setattr__(self, "required_roles", roles)
        if self.option_ref is not None:
            _ref(self.option_ref, "opt_")

    def public_payload(self) -> dict[str, Any]:
        _ref(self.option_ref, "opt_")
        result = {"option_ref": self.option_ref, "label": self.label}
        if self.description is not None:
            result["description"] = self.description
        return result

    def manifest(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "authority_keys": list(self.authority_keys),
            "candidate_revision": self.candidate_revision,
            "required_roles": list(self.required_roles),
            "description": self.description,
            "option_ref": self.option_ref,
        }


@dataclass(frozen=True, slots=True, repr=False)
class QuestionSlot:
    decision_key: str
    target_key: str
    kind: str
    question: str
    answer_kind: str
    choices: tuple[BoundChoice, ...] = ()
    minimum: int = 1
    maximum: int = 1000
    question_ref: str | None = None
    supersedes: str | None = None
    value_contract: str = "authority"

    def __post_init__(self) -> None:
        _key(self.decision_key)
        _key(self.target_key)
        _text(self.question, 512)
        if (
            not isinstance(self.kind, str)
            or not isinstance(self.answer_kind, str)
            or self.kind not in KINDS
            or self.answer_kind not in ANSWER_KINDS
        ):
            invalid()
        if not isinstance(self.value_contract, str) or self.value_contract not in VALUE_CONTRACTS:
            invalid()
        if type(self.minimum) is not int or type(self.maximum) is not int:
            invalid()
        if not 1 <= self.minimum <= self.maximum <= 1_000_000:
            invalid()
        choices = _roster(self.choices, maximum=MAX_CHOICES, minimum=0)
        if any(type(choice) is not BoundChoice for choice in choices):
            invalid()
        choices = tuple(replace(choice) for choice in choices)
        if self.answer_kind == "integer":
            if choices or self.kind not in {"result_count", "structural_choice"}:
                invalid()
            if self.value_contract == "authority":
                invalid()
            if self.value_contract == "over_fetch" and not 2 <= self.minimum <= self.maximum <= 16:
                invalid()
        else:
            if self.value_contract != "authority":
                invalid()
            if not choices or len({choice.label for choice in choices}) != len(choices):
                invalid()
            if len({choice.authority_keys for choice in choices}) != len(choices):
                invalid()
            if self.answer_kind == "option_refs" and not (
                1 <= self.minimum <= self.maximum <= len(choices)
            ):
                invalid()
        if self.question_ref is not None:
            _ref(self.question_ref, "q_")
            refs = [choice.option_ref for choice in choices]
            if len(refs) != len(set(refs)) or any(value is None for value in refs):
                invalid()
        elif any(choice.option_ref is not None for choice in choices):
            invalid()
        if self.supersedes is not None:
            _hash(self.supersedes)
        object.__setattr__(self, "choices", choices)

    @property
    def identity(self) -> tuple[str, str]:
        return self.decision_key, self.target_key

    def public_payload(self) -> dict[str, Any]:
        _ref(self.question_ref, "q_")
        schema: dict[str, Any] = {"type": self.answer_kind}
        if self.answer_kind in {"integer", "option_refs"}:
            schema.update(minimum=self.minimum, maximum=self.maximum)
        return {
            "question_ref": self.question_ref,
            "kind": self.kind,
            "question": self.question,
            "answer_schema": schema,
            "options": [choice.public_payload() for choice in self.choices],
        }


@dataclass(frozen=True, slots=True)
class DialogueAnswer:
    question_ref: str
    option_refs: tuple[str, ...] = ()
    integer: int | None = None
    multiple: bool = False

    def __post_init__(self) -> None:
        _ref(self.question_ref, "q_")
        refs = _roster(self.option_refs, maximum=MAX_CHOICES, minimum=0)
        if type(self.multiple) is not bool:
            invalid()
        for value in refs:
            _ref(value, "opt_")
        if len(refs) != len(set(refs)):
            invalid()
        if self.integer is not None:
            if type(self.integer) is not int or not 1 <= self.integer <= 1_000_000:
                invalid()
            if refs or self.multiple:
                invalid()
        elif not refs or (not self.multiple and len(refs) != 1):
            invalid()
        object.__setattr__(self, "option_refs", refs)

    @classmethod
    def parse(cls, raw: Any) -> DialogueAnswer:
        if not isinstance(raw, Mapping) or set(raw) != {"question_ref", "value"}:
            invalid()
        value = raw["value"]
        if not isinstance(value, Mapping):
            invalid()
        if set(value) == {"integer"}:
            return cls(raw["question_ref"], integer=value["integer"])
        if set(value) == {"option_ref"}:
            return cls(raw["question_ref"], option_refs=(value["option_ref"],))
        if set(value) == {"option_refs"}:
            return cls(raw["question_ref"], option_refs=value["option_refs"], multiple=True)
        invalid()

    def payload(self) -> dict[str, Any]:
        value = (
            {"integer": self.integer}
            if self.integer is not None
            else {"option_refs": list(self.option_refs)}
            if self.multiple
            else {"option_ref": self.option_refs[0]}
        )
        return {"question_ref": self.question_ref, "value": value}


def answer_roster(values: Any, *, allow_empty: bool = False) -> tuple[DialogueAnswer, ...]:
    result = tuple(
        replace(item) if type(item) is DialogueAnswer else DialogueAnswer.parse(item)
        for item in _roster(values, maximum=MAX_QUESTIONS, minimum=0 if allow_empty else 1)
    )
    if len({item.question_ref for item in result}) != len(result):
        invalid("dialogue answer contains duplicate question references")
    return result


@dataclass(frozen=True, slots=True, repr=False)
class DialogueAnswerEnvelope:
    request_id: str
    clarification_id: str
    message: str | None
    answers: tuple[DialogueAnswer, ...]

    def __post_init__(self) -> None:
        request_identifier(self.request_id)
        _ref(self.clarification_id, "clr_")
        if self.message is not None:
            _text(self.message, MAX_MESSAGE_BYTES, multiline=True)
        answers = answer_roster(self.answers, allow_empty=True)
        if self.message is None and not answers:
            invalid("dialogue answer has neither a message nor decisions")
        object.__setattr__(self, "answers", answers)

    @classmethod
    def parse(cls, raw: Any) -> DialogueAnswerEnvelope:
        if not isinstance(raw, Mapping) or set(raw) != {
            "schema_version",
            "request_id",
            "clarification_id",
            "message",
            "answers",
        }:
            invalid()
        if type(raw["schema_version"]) is not int or raw["schema_version"] != 2:
            invalid()
        return cls(raw["request_id"], raw["clarification_id"], raw["message"], raw["answers"])

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "request_id": self.request_id,
            "clarification_id": self.clarification_id,
            "message": self.message,
            "answers": [answer.payload() for answer in self.answers],
        }


@dataclass(frozen=True, slots=True, repr=False)
class BoundDecision:
    decision_key: str
    target_key: str
    kind: str
    question_ref: str
    answer_kind: str
    binding: DialogueBinding
    choices: tuple[BoundChoice, ...] = ()
    integer: int | None = None
    supersedes: str | None = None
    value_contract: str = "authority"

    def __post_init__(self) -> None:
        _key(self.decision_key)
        _key(self.target_key)
        _ref(self.question_ref, "q_")
        if (
            not isinstance(self.kind, str)
            or not isinstance(self.answer_kind, str)
            or self.kind not in KINDS
            or self.answer_kind not in ANSWER_KINDS
        ):
            invalid()
        if (
            not isinstance(self.value_contract, str)
            or self.value_contract not in VALUE_CONTRACTS
            or ((self.answer_kind == "integer") == (self.value_contract == "authority"))
        ):
            invalid()
        if type(self.binding) is not DialogueBinding:
            invalid()
        object.__setattr__(self, "binding", replace(self.binding))
        choices = _roster(self.choices, maximum=MAX_CHOICES, minimum=0)
        if any(type(choice) is not BoundChoice for choice in choices):
            invalid()
        choices = tuple(replace(choice) for choice in choices)
        refs = tuple(choice.option_ref for choice in choices)
        if len(refs) != len(set(refs)):
            invalid()
        DialogueAnswer(
            self.question_ref,
            option_refs=refs,
            integer=self.integer,
            multiple=self.answer_kind == "option_refs",
        )
        if (self.answer_kind == "integer") != (self.integer is not None):
            invalid()
        if self.answer_kind == "integer" and self.kind not in {"result_count", "structural_choice"}:
            invalid()
        if self.value_contract == "over_fetch" and not 2 <= self.integer <= 16:
            invalid()
        if self.supersedes is not None:
            _hash(self.supersedes)
        object.__setattr__(self, "choices", choices)

    @property
    def identity(self) -> tuple[str, str]:
        return self.decision_key, self.target_key

    def manifest(self) -> dict[str, Any]:
        return {
            "decision_key": self.decision_key,
            "target_key": self.target_key,
            "kind": self.kind,
            "question_ref": self.question_ref,
            "answer_kind": self.answer_kind,
            "binding": self.binding.manifest(),
            "choices": [choice.manifest() for choice in self.choices],
            "integer": self.integer,
            "supersedes": self.supersedes,
            "value_contract": self.value_contract,
        }

    @property
    def decision_sha256(self) -> str:
        return canonical_sha256(self.manifest())


def decision_roster(values: Any) -> tuple[BoundDecision, ...]:
    decisions = _roster(values, maximum=MAX_DECISIONS, minimum=0)
    latest: dict[tuple[str, str], BoundDecision] = {}
    result = []
    for decision in decisions:
        if type(decision) is not BoundDecision:
            invalid()
        decision = replace(decision)
        previous = latest.get(decision.identity)
        if previous is None:
            if decision.supersedes is not None:
                invalid("decision supersedes a different or absent slot")
        elif decision.supersedes != previous.decision_sha256 or decision.kind != previous.kind:
            invalid("decision replacement lacks its exact predecessor")
        latest[decision.identity] = decision
        result.append(decision)
    return tuple(result)


@dataclass(frozen=True, slots=True, repr=False)
class PrivateDialogueState:
    conversation_id: str
    binding: DialogueBinding
    messages: tuple[CreateAuthorityHistoryMessage, ...]
    decisions: tuple[BoundDecision, ...] = ()
    generation: int = 0
    latest_proposal_binding: str | None = None

    def __post_init__(self) -> None:
        _hash(self.conversation_id)
        if type(self.binding) is not DialogueBinding:
            invalid()
        object.__setattr__(self, "binding", replace(self.binding))
        if type(self.generation) is not int or not 0 <= self.generation <= 64:
            invalid()
        try:
            messages = tuple(replace(message) for message in self.messages)
            history_revision = create_authority_history_revision(messages)
        except (TypeError, ValueError) as error:
            raise BrainError("DIALOGUE_INVALID", 400, "dialogue history is invalid") from error
        if history_revision != self.binding.history_revision:
            invalid("dialogue history binding differs")
        decisions = decision_roster(self.decisions)
        prefixes = {
            create_authority_history_revision(messages[:index])
            for index in range(1, len(messages) + 1)
        }
        for decision in decisions:
            if (
                decision.binding.context_revision != self.binding.context_revision
                or decision.binding.semantic_revision != self.binding.semantic_revision
                or decision.binding.toolchain_binding != self.binding.toolchain_binding
                or decision.binding.history_revision not in prefixes
            ):
                invalid("dialogue decision binding differs")
        if self.latest_proposal_binding is not None:
            _hash(self.latest_proposal_binding)
        object.__setattr__(self, "messages", messages)
        object.__setattr__(self, "decisions", decisions)

    @property
    def revision(self) -> str:
        return canonical_sha256(
            {
                "contract": DIALOGUE_CONTRACT,
                "conversation_id": self.conversation_id,
                "binding": self.binding.manifest(),
                "decisions": [decision.decision_sha256 for decision in self.decisions],
                "generation": self.generation,
                "latest_proposal_binding": self.latest_proposal_binding,
            }
        )


@dataclass(frozen=True, slots=True, repr=False)
class PendingClarificationV2:
    clarification_id: str
    session_id: str
    parent_turn_id: str
    conversation_id: str
    binding: DialogueBinding
    slots: tuple[QuestionSlot, ...]
    round_index: int
    max_rounds: int
    expires_at: float

    def __post_init__(self) -> None:
        _ref(self.clarification_id, "clr_")
        _hash(self.conversation_id)
        if type(self.binding) is not DialogueBinding:
            invalid()
        object.__setattr__(self, "binding", replace(self.binding))
        slots = _roster(self.slots, maximum=MAX_QUESTIONS)
        if any(type(slot) is not QuestionSlot for slot in slots):
            invalid()
        slots = tuple(replace(slot) for slot in slots)
        refs = [slot.question_ref for slot in slots]
        options = [choice.option_ref for slot in slots for choice in slot.choices]
        if (
            None in refs
            or len(refs) != len(set(refs))
            or len(options) != len(set(options))
            or len({slot.identity for slot in slots}) != len(slots)
            or type(self.round_index) is not int
            or type(self.max_rounds) is not int
            or not 1 <= self.round_index <= self.max_rounds <= MAX_DECISIONS
            or isinstance(self.expires_at, bool)
            or not isinstance(self.expires_at, int | float)
            or not math.isfinite(self.expires_at)
        ):
            invalid()
        object.__setattr__(self, "slots", slots)

    def payload(self, *, now: float | None = None) -> dict[str, Any]:
        result = {
            "schema_version": 2,
            "clarification_id": self.clarification_id,
            "questions": [slot.public_payload() for slot in self.slots],
            "round": self.round_index,
            "max_rounds": self.max_rounds,
        }
        if now is not None:
            result["expires_in_seconds"] = round(max(0.0, self.expires_at - now), 3)
        return result


@dataclass(frozen=True, slots=True, repr=False)
class ClarificationResolutionV2:
    decisions: tuple[BoundDecision, ...]
    accepted: tuple[BoundDecision, ...]
    remaining: PendingClarificationV2 | None
