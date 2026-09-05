"""Pure, client-neutral CREATE questions and conservative answer adjudication.

This module has no store, model, I/O or client identity. Its inputs are private
host-verified candidates; its outputs never authorize a compiler operation.
Only ClarificationStore turns an answer into a bound decision. Labels select
captured option refs, never reconstructed catalog/field/value authority keys.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from typing import Any

from metis_model1.brain_create_surface import create_authority_history_revision
from metis_model1.brain_dialogue_contract import (
    MAX_QUESTIONS,
    BoundChoice,
    BoundDecision,
    DialogueAnswer,
    PendingClarificationV2,
    PrivateDialogueState,
    QuestionSlot,
    invalid,
)
from metis_model1.brain_output_contract import (
    CreateQuantityMention,
    CreateQuantitySurface,
    _quoted_spans,
    parse_create_quantity_surface,
)
from metis_model1.brain_protocol import canonical_sha256

POLICY_ID = "metis-brain-dialogue-conservative/v1"
POLICY = {
    "catalog": "select_only_unique_or_explicit_authority",
    "quantity": "no_invented_count_or_target",
    "response_shape": "preserve_existing_unless_material_choice",
    "fallback": "do_not_add_unrequested_fallback",
    "structural_choice": "ask_only_when_required_and_consequential",
    "questions_per_round": MAX_QUESTIONS,
}
POLICY_SHA256 = canonical_sha256(POLICY)
_QUANTITY_KEYS = {
    "result_count": {"total", "page", "row", "pool", "fetch", "final_output"},
    "row_count": {"page"},
    "fetch_occurrences": {"fetch"},
    "block_count": {"block"},
    "instance_count": {"instance"},
    "over_fetch": {"row", "fetch"},
}
_VALUE_CONTRACT = {
    "row_count": "rows",
    "fetch_occurrences": "fetches",
    "block_count": "blocks",
    "instance_count": "instances",
    "over_fetch": "over_fetch",
}
_SUBJECT = {
    ("result_count", "total"): "risultati complessivi",
    ("result_count", "page"): "risultati per pagina",
    ("result_count", "row"): "risultati per riga",
    ("result_count", "pool"): "risultati per pool",
    ("result_count", "fetch"): "risultati per fetch",
    ("result_count", "final_output"): "risultati finali",
    ("row_count", "page"): "righe",
    ("fetch_occurrences", "fetch"): "take complessivi",
    ("block_count", "block"): "blocchi",
    ("instance_count", "instance"): "istanze",
    ("over_fetch", "row"): "volte il numero di risultati per riga",
    ("over_fetch", "fetch"): "volte il numero di risultati per fetch",
}


@dataclass(frozen=True, slots=True, repr=False)
class ChoiceNeed:
    """A host-verified candidate roster; never a raw retrieval dictionary."""

    decision_key: str
    target_key: str
    kind: str
    question: str
    choices: tuple[BoundChoice, ...]
    multiple: bool = False
    consequential: bool = True
    required: bool = True
    explicit_authority_keys: tuple[str, ...] = ()
    supersedes: str | None = None

    def __post_init__(self) -> None:
        for value in (self.multiple, self.consequential, self.required):
            if type(value) is not bool:
                invalid()
        if self.kind == "result_count":
            invalid()
        if not self.choices:
            invalid("candidate roster is empty")
        slot = self.slot()
        object.__setattr__(self, "choices", slot.choices)
        keys = tuple(self.explicit_authority_keys)
        if len(set(keys)) != len(keys) or any(not isinstance(key, str) for key in keys):
            invalid()
        object.__setattr__(self, "explicit_authority_keys", keys)

    @property
    def identity(self) -> tuple[str, str]:
        return self.decision_key, self.target_key

    def slot(self) -> QuestionSlot:
        return QuestionSlot(
            self.decision_key,
            self.target_key,
            self.kind,
            self.question,
            "option_refs" if self.multiple else "option_ref",
            tuple(self.choices),
            maximum=len(self.choices) if self.multiple else 1000,
            supersedes=self.supersedes,
        )


@dataclass(frozen=True, slots=True, repr=False)
class QuantityNeed:
    """The host supplies the exact logical target; the planner never guesses it."""

    target_key: str
    kind: str = "result_count"
    scope: str = "total"
    mode: str = "total"
    qualifier: str | None = None
    necessary: bool = False
    minimum: int = 1
    maximum: int = 1000
    supersedes: str | None = None
    evidence_suffix: str = ""
    label: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in _QUANTITY_KEYS or self.scope not in _QUANTITY_KEYS[self.kind]:
            invalid("quantity scope is unsupported")
        modes = {"total", "page_default"} if self.kind == "result_count" else {"exact"}
        if self.kind == "over_fetch":
            modes = {"multiplier"}
        if self.mode not in modes or self.qualifier not in {
            None,
            "first",
            "second",
            "final",
            "each",
        }:
            invalid()
        if self.kind == "result_count" and (
            (self.scope == "page") != (self.mode == "page_default")
        ):
            invalid()
        if self.label is not None and (not isinstance(self.label, str) or not self.label.strip()):
            invalid()
        if type(self.necessary) is not bool or not re.fullmatch(
            r"(?:\.m\d+\.s\d+\.e\d+)?", self.evidence_suffix
        ):
            invalid()
        self.slot()

    @property
    def decision_key(self) -> str:
        return (
            f"qty.{self.kind}.{self.scope}.{self.mode}."
            f"{self.qualifier or 'any'}{self.evidence_suffix}"
        )

    @property
    def identity(self) -> tuple[str, str]:
        return self.decision_key, self.target_key

    def matches(self, mention: CreateQuantityMention) -> bool:
        return (mention.kind, mention.scope, mention.mode, mention.qualifier) == (
            self.kind,
            self.scope,
            self.mode,
            self.qualifier,
        )

    def slot(self) -> QuestionSlot:
        return QuestionSlot(
            self.decision_key,
            self.target_key,
            "result_count" if self.kind == "result_count" else "structural_choice",
            f"Quanti {_SUBJECT[(self.kind, self.scope)]} vuoi esattamente"
            + (f" per «{self.label}»?" if self.label is not None else "?"),
            "integer",
            minimum=self.minimum,
            maximum=self.maximum,
            supersedes=self.supersedes,
            value_contract=self.mode if self.kind == "result_count" else _VALUE_CONTRACT[self.kind],
        )


@dataclass(frozen=True, slots=True, repr=False)
class QuantityRepairSpan:
    message_ordinal: int
    start: int
    end: int
    need: QuantityNeed


@dataclass(frozen=True, slots=True, repr=False)
class DecidedQuantity:
    """Decision provenance is distinct from untouched operator source spans."""

    span: QuantityRepairSpan
    decision: BoundDecision


@dataclass(frozen=True, slots=True, repr=False)
class ResolvedQuantityInput:
    status: str
    exact_mentions: tuple[CreateQuantityMention, ...]
    decided_quantities: tuple[DecidedQuantity, ...]
    unresolved: tuple[QuantityRepairSpan, ...]


_APPROX_STRUCTURAL = re.compile(
    r"(?<!\w)(?P<modifier>almeno|circa|oltre|entro|al\s+massimo|massimo|minimo)\s+"
    r"(?P<value>[0-9]+|[A-Za-zÀ-ÖØ-öø-ÿ]+)\s+"
    r"(?P<noun>blocch[io]|rig(?:a|he)|istanz[ae]|take)(?!\w)",
    re.I,
)


def discover_quantity_repairs(
    surface: CreateQuantitySurface, *, message_ordinal: int
) -> tuple[QuantityRepairSpan, ...]:
    """Locate only unambiguous global structural scopes, not row/fetch targets."""
    if type(message_ordinal) is not int or message_ordinal < 0:
        invalid()
    if not surface.requires_clarification:
        return ()
    spans = _quoted_spans(surface.instruction)
    result = []
    for match in _APPROX_STRUCTURAL.finditer(surface.instruction):
        if any(match.start() < end and match.end() > start for start, end in spans):
            continue
        sample = parse_create_quantity_surface(f"{match['value']} {match['noun']}")
        if sample.status != "resolved" or len(sample.mentions) != 1:
            continue
        fact = sample.mentions[0]
        if fact.kind not in _VALUE_CONTRACT or fact.value is None:
            continue
        modifier = " ".join(match["modifier"].lower().split())
        minimum = (
            fact.value + (modifier == "oltre") if modifier in {"almeno", "minimo", "oltre"} else 1
        )
        maximum = fact.value if modifier in {"entro", "massimo", "al massimo"} else 1000
        if minimum > maximum:
            continue
        need = QuantityNeed(
            target_key=f"structure.{_VALUE_CONTRACT[fact.kind]}",
            kind=fact.kind,
            scope=fact.scope,
            mode=fact.mode,
            necessary=True,
            minimum=minimum,
            maximum=maximum,
            evidence_suffix=f".m{message_ordinal}.s{match.start()}.e{match.end()}",
        )
        result.append(QuantityRepairSpan(message_ordinal, match.start(), match.end(), need))
    return tuple(result)


def resolve_quantity_input(
    *,
    surface: CreateQuantitySurface,
    dialogue: PrivateDialogueState,
    message_ordinal: int,
    repairs: tuple[QuantityRepairSpan, ...] = (),
) -> ResolvedQuantityInput:
    """Mask only answered ambiguous spans, then reparse the whole source.

    Offsets and every remaining byte are preserved. A decided integer is never
    forged into a user-authored numeric span. If any ambiguity remains, no
    source mentions are admitted (the original all-or-none rule remains true).
    """
    state = replace(dialogue)
    if not 0 <= message_ordinal < len(state.messages):
        invalid()
    if surface.instruction != state.messages[message_ordinal].text:
        invalid("quantity source differs from admitted history")
    if surface != parse_create_quantity_surface(surface.instruction):
        invalid("quantity surface differs from its source")
    decisions = {item.identity: item for item in state.decisions}
    expected = discover_quantity_repairs(surface, message_ordinal=message_ordinal)
    if any(item not in expected for item in repairs) or len(set(repairs)) != len(repairs):
        invalid("quantity repair is not a source-verified structural span")
    masked = list(surface.instruction)
    resolved, unresolved = [], []
    for repair in repairs:
        decision = decisions.get(repair.need.identity)
        if decision is None:
            unresolved.append(repair)
            continue
        slot = repair.need.slot()
        if (
            decision.kind != slot.kind
            or decision.value_contract != slot.value_contract
            or decision.integer is None
            or not slot.minimum <= decision.integer <= slot.maximum
            or decision.binding.history_revision
            not in {
                create_authority_history_revision(state.messages[:index])
                for index in range(message_ordinal + 1, len(state.messages) + 1)
            }
        ):
            invalid("scoped quantity decision differs from its source")
        masked[repair.start : repair.end] = " " * (repair.end - repair.start)
        resolved.append(DecidedQuantity(repair, replace(decision)))
    parsed = parse_create_quantity_surface("".join(masked))
    ready = not unresolved and parsed.status in {"resolved", "absent"}
    return ResolvedQuantityInput(
        "resolved"
        if ready and (parsed.mentions or resolved)
        else ("absent" if ready else "unresolved"),
        parsed.mentions if ready else (),
        tuple(resolved) if ready else (),
        tuple(unresolved),
    )


@dataclass(frozen=True, slots=True, repr=False)
class ResolvedChoice:
    decision_key: str
    target_key: str
    choices: tuple[BoundChoice, ...]
    reason: str


@dataclass(frozen=True, slots=True, repr=False)
class DialoguePlan:
    slots: tuple[QuestionSlot, ...]
    resolved_choices: tuple[ResolvedChoice, ...]
    quantities: ResolvedQuantityInput
    deferred: tuple[tuple[str, str], ...]
    blocked: tuple[str, ...]
    defaults: tuple[str, ...]
    policy_sha256: str = POLICY_SHA256


def plan_create_dialogue(
    *,
    dialogue: PrivateDialogueState,
    quantity_surface: CreateQuantitySurface,
    catalogs: ChoiceNeed | None = None,
    semantic_candidates: tuple[ChoiceNeed, ...] = (),
    choices: tuple[ChoiceNeed, ...] = (),
    quantities: tuple[QuantityNeed, ...] = (),
    message_ordinal: int | None = None,
) -> DialoguePlan:
    """Return at most five consequential questions, preserving existing choices."""
    state = replace(dialogue)
    ordinal = len(state.messages) - 1 if message_ordinal is None else message_ordinal
    repairs = discover_quantity_repairs(quantity_surface, message_ordinal=ordinal)
    quantity_input = resolve_quantity_input(
        surface=quantity_surface,
        dialogue=state,
        message_ordinal=ordinal,
        repairs=repairs,
    )
    needs = (() if catalogs is None else (catalogs,)) + tuple(semantic_candidates) + tuple(choices)
    quantity_needs = tuple(quantities) + tuple(repair.need for repair in repairs)
    if len(needs) + len(quantity_needs) > 32:
        invalid("dialogue planning roster exceeds bound")
    if catalogs is not None and catalogs.kind != "catalog":
        invalid()
    if any(item.kind != "semantic_choice" for item in semantic_candidates):
        invalid()
    identities = [item.identity for item in (*needs, *quantity_needs)]
    if len(identities) != len(set(identities)):
        invalid("duplicate logical question slot")
    previous = {item.identity: item for item in state.decisions}
    slots, resolved, blocked, defaults = [], [], [], []
    for need in needs:
        need = replace(need)
        prior = previous.get(need.identity)
        chosen = ()
        reason = ""
        if need.explicit_authority_keys:
            allowed = set(need.explicit_authority_keys)
            chosen = tuple(
                choice for choice in need.choices if set(choice.authority_keys) <= allowed
            )
            if set(key for choice in chosen for key in choice.authority_keys) != allowed or (
                not need.multiple and len(chosen) != 1
            ):
                invalid("explicit choice does not match exact candidate authority")
            if (
                prior is not None
                and {choice.authority_keys for choice in chosen}
                != {choice.authority_keys for choice in prior.choices}
                and need.supersedes != prior.decision_sha256
            ):
                invalid("explicit choice replacement lacks supersedes")
            reason = "explicit"
        elif prior is not None and need.supersedes is None:
            signatures = {
                (choice.authority_keys, choice.candidate_revision, choice.required_roles)
                for choice in need.choices
            }
            if prior.kind != need.kind or any(
                (choice.authority_keys, choice.candidate_revision, choice.required_roles)
                not in signatures
                for choice in prior.choices
            ):
                invalid("prior choice candidate revision differs")
            chosen, reason = prior.choices, "prior_decision"
        elif not need.required or not need.consequential:
            defaults.append(POLICY_ID + ":" + need.kind)
        elif len(need.choices) == 1:
            chosen, reason = need.choices, "sole_candidate"
        else:
            if need.supersedes is not None and (
                prior is None or need.supersedes != prior.decision_sha256
            ):
                invalid("question replacement lacks its exact prior decision")
            slots.append(need.slot())
        if chosen:
            resolved.append(
                ResolvedChoice(
                    need.decision_key,
                    need.target_key,
                    tuple(replace(choice) for choice in chosen),
                    reason,
                )
            )
    for need in quantity_needs:
        need = replace(need)
        prior = previous.get(need.identity)
        if prior is not None and need.supersedes is None:
            slot = need.slot()
            if (
                prior.kind != slot.kind
                or prior.value_contract != slot.value_contract
                or prior.integer is None
                or not need.minimum <= prior.integer <= need.maximum
            ):
                invalid("prior quantity decision differs")
            continue
        matches = tuple(item for item in quantity_input.exact_mentions if need.matches(item))
        if len({item.contract for item in matches}) == 1:
            continue
        if need.supersedes is not None and (
            prior is None or need.supersedes != prior.decision_sha256
        ):
            invalid("quantity replacement lacks its exact prior decision")
        if need.necessary or quantity_input.status == "unresolved":
            slots.append(need.slot())
    if quantity_input.status == "unresolved" and not quantity_needs:
        blocked.append("quantity_scope_requires_host_resolution")
    return DialoguePlan(
        tuple(slots[:MAX_QUESTIONS]),
        tuple(resolved),
        quantity_input,
        tuple(slot.identity for slot in slots[MAX_QUESTIONS:]),
        tuple(blocked),
        tuple(defaults),
    )


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def _safe_label(label: str) -> bool:
    return bool(re.fullmatch(r"[\wÀ-ÖØ-öø-ÿ @()./'-]{1,128}", label)) and not re.search(
        r"\b(?:ignore|ignora|istruzioni|instructions|system|assistant|override|option_ref|authority_keys)\b",
        label,
        re.I,
    )


_CHOICE_PREFIX = re.compile(
    r"^(?:(?:usa|uso|scegli|scelgo|prendi|preferisco|voglio)\s+)?"
    r"(?:(?:i\s+|il\s+)?catalog(?:o|hi)\s*:?\s*)?",
    re.I,
)
_CATALOG_INTRODUCER = re.compile(
    r"\b(?:(?:usa|uso|scegli|scelgo|prendi|preferisco|voglio)\s+)?"
    r"(?:(?:insieme|entrambi)\s+)?"
    r"(?:(?:il|lo|la|i|gli|le)\s+)?catalog(?:o|hi)\b\s*:?\s*",
    re.I,
)
_CATALOG_CLAUSE_END = re.compile(r"[,;\n.!?]")
_CATALOG_CONJUNCTION = re.compile(r"^(?:e|ed|and)\s+", re.I)
_CATALOG_TRAILING_ACTION = re.compile(
    r"^(?:dammi|mostra|restituisci|fammi|voglio|vorrei|desidero|"
    r"seleziona|crea|aggiungi|[0-9])\b",
    re.I,
)
_UNSAFE_ANSWER_TEXT = re.compile(
    r"\b(?:non|not|no|senza|oppure|or|ignore|ignora|istruzioni|instructions|"
    r"system|assistant|override|option_ref|authority_keys)\b",
    re.I,
)
_QUANTITY_DECISION_KEY = re.compile(
    r"^qty\.(\w+)\.(\w+)\.(\w+)\.(any|first|second|final|each)(?:\.m\d+\.s\d+\.e\d+)?$"
)


def _catalog_phrase_matches(
    message: str, catalog_slots: tuple[QuestionSlot, ...]
) -> dict[str, list[str]]:
    """Resolve exact catalog labels only after an explicit catalog introducer.

    A label is not a general-language alias for a catalog: it may be selected
    only as the complete next item in ``catalogo/cataloghi ...``.  Text after a
    completed roster is admitted solely for a small set of answer continuations
    (for example, ``e dammi 24 risultati``), never as another inferred choice.
    """
    labels: dict[str, list[tuple[QuestionSlot, BoundChoice]]] = {}
    for slot in catalog_slots:
        for choice in slot.choices:
            if _safe_label(choice.label):
                labels.setdefault(_normalize(choice.label).removeprefix("@"), []).append(
                    (slot, choice)
                )
    matches: dict[str, list[str]] = {}
    for introducer in _CATALOG_INTRODUCER.finditer(message):
        tail = message[introducer.end() :]
        ending = _CATALOG_CLAUSE_END.search(tail)
        if ending is not None:
            tail = tail[: ending.start()]
        remaining = _normalize(tail).removeprefix("@")
        selected: list[tuple[QuestionSlot, BoundChoice]] = []
        while remaining:
            candidates = [
                (label, items)
                for label, items in labels.items()
                if remaining == label or remaining.startswith(label + " ")
            ]
            if not candidates:
                selected = []
                break
            label, items = max(candidates, key=lambda item: len(item[0]))
            if len(items) != 1:
                selected = []
                break
            selected.append(items[0])
            remaining = remaining[len(label) :].strip()
            if not remaining:
                break
            conjunction = _CATALOG_CONJUNCTION.match(remaining)
            if conjunction is None:
                selected = []
                break
            remaining = remaining[conjunction.end() :]
            if _CATALOG_TRAILING_ACTION.match(remaining):
                break
        if not selected or len({choice.option_ref for _, choice in selected}) != len(selected):
            continue
        for slot, choice in selected:
            matches.setdefault(slot.question_ref, []).append(choice.option_ref)
    return matches


def adjudicate_dialogue_answer(
    *,
    message: str,
    pending: PendingClarificationV2,
    dialogue: PrivateDialogueState,
) -> tuple[DialogueAnswer, ...]:
    """Accept unique exact labels and scoped numeric facts; otherwise abstain."""
    state, group = replace(dialogue), replace(pending)
    if message != state.messages[-1].text or group.conversation_id != state.conversation_id:
        invalid("answer is not the current admitted dialogue message")
    if any(
        getattr(group.binding, key) != getattr(state.binding, key)
        for key in (
            "context_revision",
            "semantic_revision",
            "toolchain_binding",
        )
    ) or group.binding.history_revision not in {
        create_authority_history_revision(state.messages[:index])
        for index in range(1, len(state.messages) + 1)
    }:
        invalid("answer binding is stale")
    choice_slots = tuple(slot for slot in group.slots if slot.answer_kind != "integer")
    catalog_slots = tuple(slot for slot in choice_slots if slot.kind == "catalog")
    unsafe_answer_text = bool(_UNSAFE_ANSWER_TEXT.search(message))
    labels: dict[str, list[tuple[QuestionSlot, BoundChoice]]] = {}
    for slot in choice_slots:
        if slot.kind == "catalog":
            continue
        for choice in slot.choices:
            if _safe_label(choice.label):
                labels.setdefault(_normalize(choice.label).removeprefix("@"), []).append(
                    (slot, choice)
                )
    matches = {} if unsafe_answer_text else _catalog_phrase_matches(message, catalog_slots)
    if not unsafe_answer_text:
        for clause in re.split(r"[;,\n]", message):
            value = _CHOICE_PREFIX.sub("", clause.strip().rstrip(".!"))
            chunks = (
                [value]
                if _normalize(value).removeprefix("@") in labels
                else re.split(r"\s+(?:e|ed|and)\s+", value, flags=re.I)
            )
            found = [labels.get(_normalize(chunk).removeprefix("@"), []) for chunk in chunks]
            if not found or any(len(items) != 1 for items in found):
                continue
            for ((slot, choice),) in found:
                matches.setdefault(slot.question_ref, []).append(choice.option_ref)
    numeric = tuple(slot for slot in group.slots if slot.answer_kind == "integer")
    parsed = parse_create_quantity_surface(message)
    numeric_is_asserted = not unsafe_answer_text and not re.search(
        r"\b(?:se|if|forse|anzich[eé]|invece)\b", message, re.I
    )
    answers = []
    for slot in group.slots:
        if slot.answer_kind != "integer":
            refs = tuple(dict.fromkeys(matches.get(slot.question_ref, ())))
            if refs and (
                (slot.answer_kind == "option_ref" and len(refs) == 1)
                or (slot.answer_kind == "option_refs" and slot.minimum <= len(refs) <= slot.maximum)
            ):
                answers.append(
                    DialogueAnswer(
                        slot.question_ref, refs, multiple=slot.answer_kind == "option_refs"
                    )
                )
            continue
        values = set()
        key = _QUANTITY_DECISION_KEY.fullmatch(slot.decision_key)
        if key and parsed.status == "resolved" and numeric_is_asserted:
            kind, scope, mode, qualifier = key.groups()
            signature = (kind, scope, mode, None if qualifier == "any" else qualifier)
            same_scope = sum(
                bool(
                    _QUANTITY_DECISION_KEY.fullmatch(other.decision_key)
                    and _QUANTITY_DECISION_KEY.fullmatch(other.decision_key).groups()
                    == key.groups()
                )
                for other in numeric
            )
            if same_scope == 1:
                values = {
                    item.factor if kind == "over_fetch" else item.value
                    for item in parsed.mentions
                    if (item.kind, item.scope, item.mode, item.qualifier) == signature
                }
        if len(numeric) == 1 and re.fullmatch(
            r"\s*(?:[0-9]+|[A-Za-zÀ-ÖØ-öø-ÿ]+)\s*[.!]?\s*", message
        ):
            plain = parse_create_quantity_surface(message.strip().rstrip(".!") + " risultati")
            if len(plain.mentions) == 1:
                values = {plain.mentions[0].value}
        if len(values) == 1:
            value = next(iter(values))
            if type(value) is int and slot.minimum <= value <= slot.maximum:
                answers.append(DialogueAnswer(slot.question_ref, integer=value))
    return tuple(answers)


def resolve_dialogue_answer(
    *, request: Any, pending: PendingClarificationV2, dialogue: PrivateDialogueState
) -> tuple[DialogueAnswer, ...]:
    """TurnStore's resolver hook; no request text is reconstructed or persisted."""
    envelope = request.dialogue_answer
    if envelope is None or envelope.message is None:
        return ()
    return adjudicate_dialogue_answer(message=envelope.message, pending=pending, dialogue=dialogue)
