"""Pure host adapters for the typed Metis Brain CREATE authority chain.

This module is deliberately smaller than the orchestrator.  It reconstructs
only server-owned facts and returns the issuer's typed inputs; it never reads a
tenant, invokes a model/compiler, accepts source text, or guesses structural
capabilities.
"""

from __future__ import annotations

import copy
import hmac
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Literal, NoReturn

from metis_model1.brain_create_authority_issuer import (
    AuthorityCandidate,
    FlashExactSpan,
    ReviewedSemanticAuthority,
    SafeReviewedProjection,
    TypedDecision,
    TypedFragment,
    clarification_decisions_revision,
    decision_sha256,
    safe_reviewed_projection_revision,
)
from metis_model1.brain_create_surface import (
    MAX_HISTORY_MESSAGES,
    CreateAuthorityHistoryMessage,
    CreateAuthoritySurfaceError,
    create_authority_history_revision,
)
from metis_model1.brain_intent_ir import IntentCompileRequest, IntentIR
from metis_model1.brain_protocol import bytes_sha256, canonical_json
from metis_model1.brain_retrieval import RetrievalResult
from metis_model1.brain_turns import TurnRequest

HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,95}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,95}$")
QUALIFIED_IDENTIFIER_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_-]{0,95}(?:\.[A-Za-z_][A-Za-z0-9_-]{0,95})*$"
)
MAX_SEMANTIC_AUTHORITIES = 384
MAX_SERVER_DECISIONS = 32

_ISSUER_DECISION_KINDS = frozenset(
    {
        "catalog",
        "semantic_choice",
        "result_count",
        "response_shape",
        "fallback",
        "structural_choice",
    }
)
_SERVER_ENVELOPE_KEYS = frozenset(
    {
        "kind",
        "question_key",
        "round",
        "answer",
        "label",
        "resolved_value",
        "conversation",
        "decisions",
        "current_decision",
    }
)
_SERVER_DECISION_KEYS = frozenset(
    {"kind", "question_key", "round", "answer", "label", "resolved_value"}
)
_CONVERSATION_KEYS = frozenset(
    {
        "request_fingerprint",
        "context_revision",
        "semantic_source_revision",
        "rounds_used",
        "max_rounds",
        "decisions",
        "assumptions",
        "latest_proposal_ref",
    }
)


class CreateAuthorityAssemblyError(ValueError):
    """A trusted host input could not be converted without guessing."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CreateHistoryAssembly:
    messages: tuple[CreateAuthorityHistoryMessage, ...]
    history_revision: str
    current_message_ordinal: int
    appended: bool


@dataclass(frozen=True, slots=True)
class CreateDecisionAssembly:
    decisions: tuple[TypedDecision, ...]
    decisions_revision: str
    current_decision_key: str | None


def _fail(code: str, message: str) -> NoReturn:
    raise CreateAuthorityAssemblyError(code, message)


def _hash(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or HASH_RE.fullmatch(value) is None:
        _fail("CREATE_AUTHORITY_BINDING_INVALID", f"{label} is invalid")
    return value


def _strict_requirement_keys(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        _fail("CREATE_REQUIREMENT_INVALID", "requirement keys are invalid")
    result = tuple(values)
    if (
        not result
        or len(result) != len(set(result))
        or any(not isinstance(item, str) or KEY_RE.fullmatch(item) is None for item in result)
    ):
        _fail("CREATE_REQUIREMENT_INVALID", "requirement keys are invalid")
    return result


def _authority_requirement_map(
    value: Mapping[tuple[str, ...], Sequence[str]],
) -> dict[tuple[str, ...], tuple[str, ...]]:
    if not isinstance(value, Mapping):
        _fail("CREATE_REQUIREMENT_INVALID", "authority requirement map is invalid")
    result: dict[tuple[str, ...], tuple[str, ...]] = {}
    for raw_identity, raw_requirements in value.items():
        if not isinstance(raw_identity, tuple) or not raw_identity:
            _fail("CREATE_REQUIREMENT_INVALID", "authority identity is invalid")
        identity = tuple(raw_identity)
        role = identity[0] if identity else None
        expected_size = {"catalog": 2, "field": 3, "catalog_value": 4}.get(role)
        if (
            expected_size is None
            or len(identity) != expected_size
            or any(not isinstance(item, str) or not item for item in identity)
            or identity in result
        ):
            _fail("CREATE_REQUIREMENT_INVALID", "authority identity is invalid")
        result[identity] = _strict_requirement_keys(raw_requirements)
    return result


def _isolated_history(
    values: Sequence[CreateAuthorityHistoryMessage],
) -> tuple[CreateAuthorityHistoryMessage, ...]:
    try:
        snapshot = tuple(values)
    except (TypeError, ValueError) as error:
        raise CreateAuthorityAssemblyError(
            "CREATE_HISTORY_INVALID", "parent CREATE history is invalid"
        ) from error
    try:
        create_authority_history_revision(snapshot)
    except (CreateAuthoritySurfaceError, TypeError, ValueError) as error:
        raise CreateAuthorityAssemblyError(
            "CREATE_HISTORY_INVALID", "parent CREATE history is invalid"
        ) from error
    return tuple(
        CreateAuthorityHistoryMessage(
            ordinal=item.ordinal,
            text=str(item.text),
            message_sha256=str(item.message_sha256),
        )
        for item in snapshot
    )


def _has_current_server_decision(request: TurnRequest) -> bool:
    context = request.server_clarification
    return isinstance(context, Mapping) and isinstance(context.get("current_decision"), Mapping)


def assemble_create_authority_history(
    *,
    request: TurnRequest,
    parent_history: Sequence[CreateAuthorityHistoryMessage] | None = None,
) -> CreateHistoryAssembly:
    """Append one admitted operator instruction, or reuse it on answer retry.

    A repeated sentence is still a distinct refinement unless the host attached
    a ``current_decision`` reconstructed by ``TurnStore``.  The public
    ``clarification_response`` field alone therefore cannot suppress a message.
    """

    if not isinstance(request, TurnRequest):
        _fail("CREATE_REQUEST_INVALID", "CREATE request is invalid")
    if request.intent != "create" or request.target.get("mode") != "create":
        _fail("CREATE_REQUEST_INVALID", "request is not a CREATE request")
    try:
        raw_instruction = request.instruction.encode("utf-8")
    except UnicodeError as error:
        raise CreateAuthorityAssemblyError(
            "CREATE_HISTORY_INVALID", "CREATE instruction is not UTF-8"
        ) from error
    if not raw_instruction:
        _fail("CREATE_HISTORY_INVALID", "CREATE instruction is empty")

    if parent_history is None:
        parent: tuple[CreateAuthorityHistoryMessage, ...] = ()
    else:
        parent = _isolated_history(parent_history)
    retry = _has_current_server_decision(request)
    already_current = bool(parent and parent[-1].text == request.instruction)
    append = not (retry and already_current)
    if append and len(parent) >= MAX_HISTORY_MESSAGES:
        _fail("CREATE_HISTORY_LIMIT", "CREATE history exceeds its message bound")
    messages = parent
    if append:
        messages = (
            *parent,
            CreateAuthorityHistoryMessage(
                ordinal=len(parent),
                text=request.instruction,
                message_sha256=bytes_sha256(raw_instruction),
            ),
        )
    if not messages:
        _fail("CREATE_HISTORY_INVALID", "CREATE history is empty")
    try:
        history_revision = create_authority_history_revision(messages)
    except CreateAuthoritySurfaceError as error:
        raise CreateAuthorityAssemblyError(
            "CREATE_HISTORY_INVALID", "CREATE history is invalid"
        ) from error
    return CreateHistoryAssembly(
        messages=messages,
        history_revision=history_revision,
        current_message_ordinal=len(messages) - 1,
        appended=append,
    )


def _public_decision(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: copy.deepcopy(item) for key, item in value.items() if key != "resolved_value"}


def _validate_server_decision(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("CREATE_DECISION_SPOOFED", "server decision is invalid")
    keys = set(value)
    if not keys.issubset(_SERVER_DECISION_KEYS) or not {
        "kind",
        "question_key",
        "round",
        "answer",
        "resolved_value",
    }.issubset(keys):
        _fail("CREATE_DECISION_SPOOFED", "server decision envelope is incomplete")
    kind = value.get("kind")
    question_key = value.get("question_key")
    round_index = value.get("round")
    answer = value.get("answer")
    if (
        kind not in _ISSUER_DECISION_KINDS
        or not isinstance(question_key, str)
        or not question_key
        or type(round_index) is not int
        or round_index < 1
        or not isinstance(answer, Mapping)
    ):
        _fail("CREATE_DECISION_SPOOFED", "server decision fields are invalid")
    if kind == "result_count":
        if (
            set(answer) != {"integer"}
            or type(answer.get("integer")) is not int
            or not 1 <= answer["integer"] <= 1_000_000
            or value.get("resolved_value") is not None
        ):
            _fail("CREATE_DECISION_SPOOFED", "result-count decision is invalid")
    elif (
        set(answer) not in ({"option_ref"}, {"text"})
        or not isinstance(next(iter(answer.values()), None), str)
        or not next(iter(answer.values()), "")
        or not isinstance(value.get("resolved_value"), str)
        or not value["resolved_value"]
    ):
        _fail("CREATE_DECISION_SPOOFED", "choice decision is invalid")
    return copy.deepcopy(dict(value))


def _server_decision_roster(
    request: TurnRequest,
    *,
    context_revision: str,
    semantic_revision: str,
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any] | None]:
    source_context = request.server_clarification
    if source_context is None:
        if request.clarification_response is not None:
            _fail(
                "CREATE_DECISION_SPOOFED",
                "client clarification has no server-owned decision",
            )
        return (), None
    if not isinstance(source_context, Mapping):
        _fail("CREATE_DECISION_SPOOFED", "server clarification envelope is invalid")
    try:
        context = copy.deepcopy(dict(source_context))
    except Exception as error:  # noqa: BLE001 - snapshot an internal untrusted graph.
        raise CreateAuthorityAssemblyError(
            "CREATE_DECISION_SPOOFED", "server clarification envelope is invalid"
        ) from error
    if not set(context).issubset(_SERVER_ENVELOPE_KEYS):
        _fail("CREATE_DECISION_SPOOFED", "server clarification envelope is invalid")
    conversation = context.get("conversation")
    raw_decisions = context.get("decisions")
    if (
        not isinstance(conversation, Mapping)
        or set(conversation) != _CONVERSATION_KEYS
        or not isinstance(raw_decisions, list)
        or not 1 <= len(raw_decisions) <= MAX_SERVER_DECISIONS
    ):
        _fail("CREATE_DECISION_SPOOFED", "server clarification roster is invalid")
    if (
        conversation.get("context_revision") != context_revision
        or conversation.get("semantic_source_revision") != semantic_revision
        or request.expected_context_revision != context_revision
        or request.expected_semantic_source_revision != semantic_revision
        or type(conversation.get("rounds_used")) is not int
        or conversation["rounds_used"] != len(raw_decisions)
        or type(conversation.get("max_rounds")) is not int
        or conversation["max_rounds"] < conversation["rounds_used"]
        or not isinstance(conversation.get("decisions"), list)
        or len(conversation["decisions"]) != len(raw_decisions)
        or not isinstance(conversation.get("assumptions"), list)
    ):
        _fail("CREATE_DECISION_BINDING_DRIFT", "server clarification binding differs")

    decisions = tuple(_validate_server_decision(item) for item in raw_decisions)
    if any(item["round"] != ordinal for ordinal, item in enumerate(decisions, start=1)):
        _fail("CREATE_DECISION_SPOOFED", "server decision rounds are not contiguous")
    if [_public_decision(item) for item in decisions] != conversation["decisions"]:
        _fail("CREATE_DECISION_SPOOFED", "public and private decision rosters differ")
    latest = decisions[-1]
    duplicated_latest = {
        key: copy.deepcopy(value)
        for key, value in context.items()
        if key not in {"conversation", "decisions", "current_decision"}
    }
    if duplicated_latest != latest:
        _fail("CREATE_DECISION_SPOOFED", "latest server decision differs from its roster")

    current_value = context.get("current_decision")
    current: dict[str, Any] | None = None
    if current_value is not None:
        current = _validate_server_decision(current_value)
        if current != latest or request.clarification_response is None:
            _fail("CREATE_DECISION_SPOOFED", "current server decision is not admitted")
        response = request.clarification_response
        assert response is not None
        if (
            response.get("context_revision") != context_revision
            or response.get("semantic_source_revision") != semantic_revision
            or request.clarification_answer != current["answer"]
        ):
            _fail("CREATE_DECISION_BINDING_DRIFT", "clarification answer binding differs")
    elif request.clarification_response is not None:
        _fail("CREATE_DECISION_SPOOFED", "client clarification lacks a current decision")
    return decisions, current


def typed_decisions_from_server_request(
    *,
    request: TurnRequest,
    context_revision: str,
    semantic_revision: str,
    authority_keys_by_choice: Mapping[tuple[str, str], str] | None = None,
    result_count_modes: Mapping[str, Literal["count", "page"]] | None = None,
) -> CreateDecisionAssembly:
    """Convert only a complete TurnStore decision envelope to issuer values.

    Choice identities and count modes are explicit host adjudication inputs.
    This adapter never derives them from a label, option position, or client
    answer.
    """

    if not isinstance(request, TurnRequest):
        _fail("CREATE_REQUEST_INVALID", "CREATE request is invalid")
    context_revision = _hash(context_revision, label="context revision")
    semantic_revision = _hash(semantic_revision, label="semantic revision")
    authority_keys_by_choice = {} if authority_keys_by_choice is None else authority_keys_by_choice
    result_count_modes = {} if result_count_modes is None else result_count_modes
    if not isinstance(authority_keys_by_choice, Mapping) or not isinstance(
        result_count_modes, Mapping
    ):
        _fail("CREATE_DECISION_MAPPING_INVALID", "decision bindings are invalid")
    try:
        authority_keys_by_choice = copy.deepcopy(dict(authority_keys_by_choice))
        result_count_modes = copy.deepcopy(dict(result_count_modes))
    except Exception as error:  # noqa: BLE001 - snapshot host-provided maps.
        raise CreateAuthorityAssemblyError(
            "CREATE_DECISION_MAPPING_INVALID", "decision bindings are invalid"
        ) from error
    raw, current = _server_decision_roster(
        request,
        context_revision=context_revision,
        semantic_revision=semantic_revision,
    )
    seen_kinds: set[str] = set()
    result: list[TypedDecision] = []
    current_key: str | None = None
    for item in raw:
        kind = item["kind"]
        if kind in seen_kinds:
            _fail("CREATE_DECISION_DUPLICATED", "decision kind is duplicated")
        seen_kinds.add(kind)
        question_key = item["question_key"]
        if kind == "result_count":
            mode = result_count_modes.get(question_key)
            if mode not in {"count", "page"}:
                _fail(
                    "CREATE_DECISION_MAPPING_INVALID",
                    "result-count mode has no exact host binding",
                )
            value: Any = {"mode": mode, "value": item["answer"]["integer"]}
        else:
            choice = item["resolved_value"]
            authority_key = authority_keys_by_choice.get((kind, choice))
            if not isinstance(authority_key, str) or KEY_RE.fullmatch(authority_key) is None:
                _fail(
                    "CREATE_DECISION_MAPPING_INVALID",
                    "choice has no exact authority binding",
                )
            value = {"authority_key": authority_key}
        identity = {
            "question_key": question_key,
            "kind": kind,
            "round": item["round"],
            "answer": item["answer"],
            "resolved_value": item["resolved_value"],
            "context_revision": context_revision,
            "semantic_revision": semantic_revision,
        }
        key = "decision." + bytes_sha256(canonical_json(identity))[7:39]
        digest = decision_sha256(
            key=key,
            kind=kind,
            value=value,
            context_revision=context_revision,
            semantic_revision=semantic_revision,
        )
        typed = TypedDecision(
            key=key,
            kind=kind,
            value=copy.deepcopy(value),
            context_revision=context_revision,
            semantic_revision=semantic_revision,
            decision_sha256=digest,
        )
        result.append(typed)
        if current is not None and hmac.compare_digest(
            canonical_json(item), canonical_json(current)
        ):
            current_key = key
    decisions = tuple(result)
    return CreateDecisionAssembly(
        decisions=decisions,
        decisions_revision=clarification_decisions_revision(decisions),
        current_decision_key=current_key,
    )


def derive_unique_flash_spans(
    *,
    request: TurnRequest,
    history: CreateHistoryAssembly,
    flash_intent: IntentIR | None,
) -> tuple[FlashExactSpan, ...]:
    """Bind every Flash concept to its sole exact current-turn UTF-8 span."""

    if flash_intent is None:
        return ()
    if not isinstance(request, TurnRequest) or not isinstance(history, CreateHistoryAssembly):
        _fail("CREATE_FLASH_INVALID", "Flash authority input is invalid")
    if not history.messages or history.messages[-1].text != request.instruction:
        _fail("CREATE_FLASH_BINDING_DRIFT", "Flash instruction differs from CREATE history")
    if create_authority_history_revision(history.messages) != history.history_revision:
        _fail("CREATE_FLASH_BINDING_DRIFT", "CREATE history revision differs")
    if not isinstance(flash_intent, IntentIR):
        _fail("CREATE_FLASH_INVALID", "Flash intent is invalid")
    try:
        parsed = IntentIR.parse(
            flash_intent.value,
            request=IntentCompileRequest(
                instruction=request.instruction,
                intent="create",
                target_mode="create",
            ),
        )
    except Exception as error:  # IntentIR uses the public Brain error boundary.
        raise CreateAuthorityAssemblyError(
            "CREATE_FLASH_INVALID", "Flash intent is not request-bound"
        ) from error
    spans: list[FlashExactSpan] = []
    for concept_index, concept in enumerate(parsed.value["concepts"]):
        source = concept["source"]
        starts: list[int] = []
        cursor = 0
        while True:
            start = request.instruction.find(source, cursor)
            if start < 0:
                break
            starts.append(start)
            cursor = start + 1
        if not starts:
            _fail("CREATE_FLASH_SOURCE_MISSING", "Flash source is absent from the current turn")
        if len(starts) != 1:
            _fail(
                "CREATE_FLASH_SOURCE_AMBIGUOUS",
                "Flash source is not unique in the current turn",
            )
        start = starts[0]
        start_utf8 = len(request.instruction[:start].encode("utf-8"))
        end_utf8 = start_utf8 + len(source.encode("utf-8"))
        spans.append(
            FlashExactSpan(
                concept_index=concept_index,
                message_ordinal=history.current_message_ordinal,
                start_utf8=start_utf8,
                end_utf8=end_utf8,
            )
        )
    return tuple(spans)


def _semantic_key(role: str, identity: Mapping[str, Any]) -> str:
    return f"semantic.{role}." + bytes_sha256(canonical_json(dict(identity)))[7:39]


def _projection_status(
    *,
    context_revision: str,
    semantic_revision: str,
    toolchain_binding: str,
    status: Literal["resolved", "clarify", "unsupported"],
    authorities: Sequence[ReviewedSemanticAuthority] = (),
    ambiguities: Sequence[str] = (),
    unresolved: Sequence[str] = (),
) -> SafeReviewedProjection:
    provisional = SafeReviewedProjection(
        context_revision=context_revision,
        semantic_revision=semantic_revision,
        toolchain_binding=toolchain_binding,
        projection_revision="sha256:" + "0" * 64,
        status=status,
        authorities=tuple(authorities),
        ambiguities=tuple(ambiguities),
        unresolved=tuple(unresolved),
    )
    return replace(
        provisional,
        projection_revision=safe_reviewed_projection_revision(provisional),
    )


def _domain_kind(value: Any) -> Literal["finite", "open", "none"]:
    if not isinstance(value, Mapping) or not isinstance(value.get("kind"), str):
        _fail("CREATE_SEMANTIC_DOMAIN_INVALID", "semantic domain is invalid")
    kind = value["kind"]
    if kind in {"inline", "enum", "list"}:
        return "finite"
    if kind == "open":
        return "open"
    if kind == "none":
        return "none"
    _fail("CREATE_SEMANTIC_DOMAIN_INVALID", "semantic domain kind is unsupported")


def _semantic_state(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    state = value.get("state")
    return state if isinstance(state, str) else None


def _context_catalogs(context: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw: list[Any]
    if isinstance(context.get("catalog"), Mapping):
        raw = [context["catalog"]]
    elif isinstance(context.get("catalogs"), list):
        raw = context["catalogs"]
    else:
        _fail("CREATE_SEMANTIC_BINDING_INVALID", "retrieval catalog context is invalid")
    result: dict[str, Mapping[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            _fail("CREATE_SEMANTIC_BINDING_INVALID", "retrieval catalog is invalid")
        if item["name"] in result:
            _fail("CREATE_SEMANTIC_BINDING_INVALID", "retrieval catalog is duplicated")
        result[item["name"]] = item
    return result


def _context_fields(
    context: Mapping[str, Any], catalogs: Mapping[str, Mapping[str, Any]]
) -> dict[tuple[str, str], Mapping[str, Any]]:
    raw = context.get("fields")
    if not isinstance(raw, list):
        _fail("CREATE_SEMANTIC_BINDING_INVALID", "retrieval field context is invalid")
    single_catalog = next(iter(catalogs)) if len(catalogs) == 1 else None
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for item in raw:
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            _fail("CREATE_SEMANTIC_BINDING_INVALID", "retrieval field is invalid")
        catalog = item.get("catalog", single_catalog)
        if not isinstance(catalog, str) or catalog not in catalogs:
            _fail("CREATE_SEMANTIC_BINDING_INVALID", "retrieval field catalog is invalid")
        identity = (catalog, item["name"])
        if identity in result:
            _fail("CREATE_SEMANTIC_BINDING_INVALID", "retrieval field is duplicated")
        result[identity] = item
    return result


def prune_reviewed_retrieval(
    *,
    retrieved: RetrievalResult,
    context_revision: str,
    semantic_revision: str,
    toolchain_binding: str,
    authority_requirement_keys: Mapping[tuple[str, ...], Sequence[str]],
) -> SafeReviewedProjection:
    """Rebuild a minimal semantic grant roster from exact reviewed evidence.

    Endpoint templates, source locations, paths, descriptions, aliases and raw
    unresolved prose are intentionally never copied into the returned graph.
    """

    if not isinstance(retrieved, RetrievalResult):
        _fail("CREATE_SEMANTIC_BINDING_INVALID", "retrieval result is invalid")
    context_revision = _hash(context_revision, label="context revision")
    semantic_revision = _hash(semantic_revision, label="semantic revision")
    toolchain_binding = _hash(toolchain_binding, label="toolchain binding")
    try:
        requirement_map = _authority_requirement_map(
            copy.deepcopy(dict(authority_requirement_keys))
        )
    except CreateAuthorityAssemblyError:
        raise
    except Exception as error:  # noqa: BLE001 - snapshot a private authority map.
        raise CreateAuthorityAssemblyError(
            "CREATE_REQUIREMENT_INVALID", "authority requirement map is invalid"
        ) from error
    if not isinstance(retrieved.context, Mapping) or not isinstance(retrieved.grounding, Mapping):
        _fail("CREATE_SEMANTIC_BINDING_INVALID", "retrieval result is invalid")
    try:
        context = copy.deepcopy(dict(retrieved.context))
        grounding = copy.deepcopy(dict(retrieved.grounding))
    except Exception as error:  # noqa: BLE001 - snapshot the retriever boundary.
        raise CreateAuthorityAssemblyError(
            "CREATE_SEMANTIC_BINDING_INVALID", "retrieval result is invalid"
        ) from error
    if (
        context.get("semantic_schema") != 2
        or context.get("context_revision") != context_revision
        or context.get("semantic_source_revision") != semantic_revision
        or context.get("toolchain_binding") != toolchain_binding
        or retrieved.semantic_source_revision != semantic_revision
    ):
        _fail("CREATE_SEMANTIC_BINDING_DRIFT", "retrieval authority binding differs")

    status = grounding.get("status")
    if status == "clarify":
        if requirement_map:
            _fail("CREATE_REQUIREMENT_EXTRA", "unresolved retrieval has authority bindings")
        ambiguity = "semantic_choice" if grounding.get("candidates") else "catalog"
        return _projection_status(
            context_revision=context_revision,
            semantic_revision=semantic_revision,
            toolchain_binding=toolchain_binding,
            status="clarify",
            ambiguities=(ambiguity,),
        )
    if status != "resolved":
        if requirement_map:
            _fail("CREATE_REQUIREMENT_EXTRA", "unresolved retrieval has authority bindings")
        return _projection_status(
            context_revision=context_revision,
            semantic_revision=semantic_revision,
            toolchain_binding=toolchain_binding,
            status="unsupported",
            unresolved=("retrieval_not_resolved",),
        )
    if grounding.get("candidates"):
        if requirement_map:
            _fail("CREATE_REQUIREMENT_EXTRA", "ambiguous retrieval has authority bindings")
        return _projection_status(
            context_revision=context_revision,
            semantic_revision=semantic_revision,
            toolchain_binding=toolchain_binding,
            status="clarify",
            ambiguities=("semantic_choice",),
        )
    if grounding.get("unresolved") or grounding.get("lookups") or grounding.get("lookup"):
        if requirement_map:
            _fail("CREATE_REQUIREMENT_EXTRA", "unresolved retrieval has authority bindings")
        return _projection_status(
            context_revision=context_revision,
            semantic_revision=semantic_revision,
            toolchain_binding=toolchain_binding,
            status="unsupported",
            unresolved=("semantic_lookup_or_residue",),
        )

    catalogs = _context_catalogs(context)
    raw_catalogs = grounding.get("catalogs")
    selections = grounding.get("selections")
    resolutions = grounding.get("resolutions")
    if (
        not isinstance(raw_catalogs, list)
        or not raw_catalogs
        or len(raw_catalogs) != len(set(raw_catalogs))
        or any(not isinstance(item, str) or item not in catalogs for item in raw_catalogs)
        or not isinstance(selections, list)
        or not isinstance(resolutions, list)
        or len(selections) != len(resolutions)
    ):
        _fail("CREATE_SEMANTIC_BINDING_INVALID", "retrieval semantic roster is invalid")
    fields = _context_fields(context, catalogs)

    authorities: list[ReviewedSemanticAuthority] = []
    authority_identities: set[tuple[str, ...]] = set()
    consumed_requirement_identities: set[tuple[str, ...]] = set()

    def add(
        *,
        role: Literal["catalog", "field", "catalog_value"],
        identity: tuple[str, ...],
        label: str,
        fragment: TypedFragment,
        domain: Literal["finite", "open", "none"],
    ) -> None:
        if identity in authority_identities:
            return
        requirements = requirement_map.get(identity)
        if requirements is None:
            _fail("CREATE_REQUIREMENT_MISSING", "semantic authority has no requirement binding")
        authority_identities.add(identity)
        consumed_requirement_identities.add(identity)
        authorities.append(
            ReviewedSemanticAuthority(
                authority=AuthorityCandidate(
                    key=_semantic_key(role, {"identity": list(identity)}),
                    roles=(role,),
                    label=label,
                    fragment=fragment,
                    requirement_keys=requirements,
                ),
                state="reviewed",
                domain=domain,
                resolved=True,
            )
        )

    for catalog in raw_catalogs:
        record = catalogs[catalog]
        if _semantic_state(record.get("semantic")) != "reviewed":
            return _projection_status(
                context_revision=context_revision,
                semantic_revision=semantic_revision,
                toolchain_binding=toolchain_binding,
                status="unsupported",
                unresolved=("catalog_not_reviewed",),
            )
        if QUALIFIED_IDENTIFIER_RE.fullmatch(catalog) is None:
            _fail("CREATE_SEMANTIC_FRAGMENT_INVALID", "catalog identifier is unsupported")
        add(
            role="catalog",
            identity=("catalog", catalog),
            label=f"Catalogo {catalog}",
            fragment=TypedFragment("qualifiedIdentifier", catalog),
            domain="none",
        )

    seen_selections: set[tuple[str, str, str | None]] = set()
    for selection, resolution in zip(selections, resolutions, strict=True):
        if not isinstance(selection, Mapping) or not isinstance(resolution, Mapping):
            _fail("CREATE_SEMANTIC_BINDING_INVALID", "semantic evidence is invalid")
        catalog = selection.get("catalog")
        field = selection.get("field")
        literal = selection.get("literal")
        if (
            not isinstance(catalog, str)
            or catalog not in raw_catalogs
            or not isinstance(field, str)
            or (literal is not None and not isinstance(literal, str))
            or selection.get("literals") is not None
        ):
            _fail("CREATE_SEMANTIC_BINDING_INVALID", "semantic selection is invalid")
        identity = (catalog, field, literal)
        if identity in seen_selections:
            _fail("CREATE_SEMANTIC_BINDING_INVALID", "semantic selection is duplicated")
        seen_selections.add(identity)
        if (
            resolution.get("catalog") != catalog
            or resolution.get("field") != field
            or resolution.get("literal") != literal
            or resolution.get("review_state") != "reviewed"
        ):
            _fail(
                "CREATE_SEMANTIC_REVIEW_INVALID",
                "selection and reviewed resolution are not one-to-one",
            )
        field_record = fields.get((catalog, field))
        if field_record is None:
            _fail("CREATE_SEMANTIC_BINDING_INVALID", "selected field is absent from context")
        if _semantic_state(field_record.get("semantic")) != "reviewed":
            return _projection_status(
                context_revision=context_revision,
                semantic_revision=semantic_revision,
                toolchain_binding=toolchain_binding,
                status="unsupported",
                unresolved=("field_not_reviewed",),
            )
        if (
            selection.get("type") != field_record.get("type")
            or selection.get("modifiers") != field_record.get("modifiers")
            or canonical_json(selection.get("domain")) != canonical_json(field_record.get("domain"))
        ):
            _fail("CREATE_SEMANTIC_BINDING_DRIFT", "selected field technical surface differs")
        if IDENTIFIER_RE.fullmatch(field) is None:
            _fail("CREATE_SEMANTIC_FRAGMENT_INVALID", "field identifier is unsupported")
        domain = _domain_kind(field_record.get("domain"))
        add(
            role="field",
            identity=("field", catalog, field),
            label=f"Campo {field}",
            fragment=TypedFragment("identifier", field),
            domain=domain,
        )
        if literal is None:
            continue
        if domain != "finite":
            return _projection_status(
                context_revision=context_revision,
                semantic_revision=semantic_revision,
                toolchain_binding=toolchain_binding,
                status="unsupported",
                unresolved=("value_without_finite_domain",),
            )
        raw_values = field_record.get("values")
        if not isinstance(raw_values, list):
            _fail("CREATE_SEMANTIC_BINDING_INVALID", "finite value evidence is absent")
        matches = [
            item
            for item in raw_values
            if isinstance(item, Mapping) and item.get("literal") == literal
        ]
        if len(matches) != 1 or _semantic_state(matches[0].get("semantic")) != "reviewed":
            return _projection_status(
                context_revision=context_revision,
                semantic_revision=semantic_revision,
                toolchain_binding=toolchain_binding,
                status="unsupported",
                unresolved=("value_not_reviewed",),
            )
        add(
            role="catalog_value",
            identity=("catalog_value", catalog, field, literal),
            label=f"Valore {literal}",
            fragment=TypedFragment(
                "value",
                {"kind": "lit", "lexical": "text", "value": literal},
            ),
            domain="finite",
        )
    if not authorities or len(authorities) > MAX_SEMANTIC_AUTHORITIES:
        _fail("CREATE_SEMANTIC_LIMIT", "semantic authority roster exceeds its bound")
    if consumed_requirement_identities != set(requirement_map):
        _fail("CREATE_REQUIREMENT_EXTRA", "authority requirement map contains unused bindings")
    return _projection_status(
        context_revision=context_revision,
        semantic_revision=semantic_revision,
        toolchain_binding=toolchain_binding,
        status="resolved",
        authorities=authorities,
    )


__all__ = [
    "CreateAuthorityAssemblyError",
    "CreateDecisionAssembly",
    "CreateHistoryAssembly",
    "assemble_create_authority_history",
    "derive_unique_flash_spans",
    "prune_reviewed_retrieval",
    "typed_decisions_from_server_request",
]
