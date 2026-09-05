"""Asynchronous Brain turn protocol, idempotency and bounded event journal."""

from __future__ import annotations

import re
import secrets
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from metis_model1.brain_clarifications import (
    ClarificationStore,
    clarification_reference,
    clarification_text,
)
from metis_model1.brain_create_ir import CreateIrStageProof, isolated_ir, verify_ir_stage
from metis_model1.brain_create_surface import (
    CreateAuthorityHistoryMessage,
    CreateAuthoritySurfaceError,
    create_authority_history_revision,
)
from metis_model1.brain_dialogue_contract import (
    DialogueAnswer,
    DialogueAnswerEnvelope,
    DialogueBinding,
    PendingClarificationV2,
    PrivateDialogueState,
    answer_roster,
)
from metis_model1.brain_model_runtime import MAX_CREATE_PLAN_MESSAGES, BrainModelRuntime
from metis_model1.brain_protocol import (
    MAX_SOURCE_BYTES,
    BrainError,
    bytes_sha256,
    canonical_sha256,
    exact_fields,
    request_identifier,
    revision,
)
from metis_model1.brain_retrieval import BrainRetriever
from metis_model1.brain_sessions import OperationLease, SessionManager

_TURN_RE = re.compile(r"^[A-Za-z0-9_-]{24,96}$")
_REF_RE = re.compile(r"^[A-Za-z0-9_-]{1,96}$")
_ENDPOINT_REFERENCE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,95}$")
_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}\.metis$")
_INTENTS = frozenset({"create", "edit", "repair", "review", "migrate"})
MAX_SESSION_TURNS = 64
HEARTBEAT_INTERVAL_SECONDS = 4.0
MAX_EVENT_METRIC = 1_000_000
TYPED_CREATE_QUALIFICATION_RECEIPT_CONTRACT = "metis-brain-typed-create-qualification-receipt/v1"
TYPED_CREATE_CLARIFICATION_RECEIPT_CONTRACT = "metis-brain-typed-create-clarification-receipt/v1"
_CREATE_PARENT_UNAVAILABLE = object()
_EVENTS = frozenset(
    {
        "turn.accepted",
        "retrieval.started",
        "retrieval.completed",
        "intent.started",
        "intent.completed",
        "catalog.auto_selected",
        "catalog.clarification_required",
        "inference.started",
        "inference.completed",
        "compile.started",
        "compile.completed",
        "repair.started",
        "repair.completed",
        "heartbeat",
        "terminal",
    }
)


def validate_target(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BrainError("INVALID_SCHEMA", 400, "target must be an object")
    exact_fields(
        value,
        required={"mode", "relative_path", "endpoint", "base_sha256"},
        optional={"reference"},
        label="target",
    )
    mode = value["mode"]
    if mode not in {"create", "existing"}:
        raise BrainError("INVALID_SCHEMA", 400, "target mode is invalid")
    path = value["relative_path"]
    if not isinstance(path, str) or _PATH_RE.fullmatch(path) is None:
        raise BrainError("INVALID_SCHEMA", 400, "target path is invalid")
    if any(part in {"", ".", ".."} for part in path.split("/")):
        raise BrainError("INVALID_SCHEMA", 400, "target path is invalid")
    endpoint = value["endpoint"]
    if endpoint is not None and (
        not isinstance(endpoint, str) or not endpoint or len(endpoint) > 256
    ):
        raise BrainError("INVALID_SCHEMA", 400, "target endpoint is invalid")
    reference = value.get("reference")
    if reference is not None and (
        not isinstance(reference, str) or _ENDPOINT_REFERENCE_RE.fullmatch(reference) is None
    ):
        raise BrainError("INVALID_SCHEMA", 400, "target reference is invalid")
    base = value["base_sha256"]
    if base is not None and (
        not isinstance(base, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", base)
    ):
        raise BrainError("INVALID_SCHEMA", 400, "target base hash is invalid")
    if mode == "create" and base is not None:
        raise BrainError("INVALID_SCHEMA", 400, "create target requires a null base hash")
    if mode == "existing" and base is None:
        raise BrainError("INVALID_SCHEMA", 400, "existing target requires a base hash")
    if reference is not None and (mode != "create" or endpoint is None):
        raise BrainError("INVALID_SCHEMA", 400, "target reference requires a named create endpoint")
    return {
        "mode": mode,
        "relative_path": path,
        "endpoint": endpoint,
        "base_sha256": base,
        "reference": reference,
    }


@dataclass(frozen=True)
class TurnRequest:
    schema_version: int
    request_id: str
    expected_context_revision: str
    expected_semantic_source_revision: str
    intent: str
    instruction: str = field(repr=False)
    target: dict[str, Any]
    basis: dict[str, str] | None
    clarification_response: dict[str, Any] | None = field(repr=False)
    server_clarification: dict[str, Any] | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    server_basis_grounding: dict[str, Any] | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    server_flash_intent: dict[str, Any] | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    server_target_catalogs: tuple[str, ...] = field(
        default=(),
        compare=False,
        repr=False,
    )
    server_dialogue: PrivateDialogueState | None = field(default=None, compare=False, repr=False)

    @classmethod
    def parse(cls, value: dict[str, Any]) -> TurnRequest:
        exact_fields(
            value,
            required={
                "schema_version",
                "request_id",
                "expected_context_revision",
                "expected_semantic_source_revision",
                "intent",
                "instruction",
                "target",
                "basis",
                "clarification_response",
            },
            label="turn request",
        )
        schema_version = value["schema_version"]
        if type(schema_version) is not int or schema_version not in {1, 2}:
            raise BrainError("INVALID_SCHEMA", 400, "turn schema version is unsupported")
        request_id = request_identifier(value["request_id"])
        expected_context = revision(value["expected_context_revision"], label="context revision")
        expected_semantic = revision(
            value["expected_semantic_source_revision"], label="semantic source revision"
        )
        intent = value["intent"]
        if intent not in _INTENTS:
            raise BrainError("INVALID_SCHEMA", 400, "turn intent is invalid")
        instruction = value["instruction"]
        if not isinstance(instruction, str) or not instruction.strip():
            raise BrainError("INVALID_SCHEMA", 400, "instruction must be non-empty")
        if len(instruction.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise BrainError("PAYLOAD_TOO_LARGE", 413, "instruction exceeds the byte limit")
        target = validate_target(value["target"])

        basis = value["basis"]
        if basis is not None:
            if not isinstance(basis, dict):
                raise BrainError("INVALID_SCHEMA", 400, "basis is invalid")
            exact_fields(basis, required={"kind", "proposal_ref"}, label="basis")
            if basis["kind"] != "proposal" or not _REF_RE.fullmatch(str(basis["proposal_ref"])):
                raise BrainError("INVALID_SCHEMA", 400, "basis is invalid")
            basis = {"kind": "proposal", "proposal_ref": basis["proposal_ref"]}

        clarification = value["clarification_response"]
        if clarification is not None:
            if not isinstance(clarification, dict):
                raise BrainError("INVALID_SCHEMA", 400, "clarification response is invalid")
            required = {
                "clarification_id",
                "context_revision",
                "semantic_source_revision",
            }
            if schema_version == 1:
                required.add("option_ref")
            else:
                required.add("answer")
            exact_fields(clarification, required=required, label="clarification response")
            clarification_reference(clarification["clarification_id"], name="clarification_id")
            revision(clarification["context_revision"], label="clarification context revision")
            revision(
                clarification["semantic_source_revision"],
                label="clarification semantic revision",
            )
            if schema_version == 1:
                clarification_reference(clarification["option_ref"], name="option_ref")
                clarification = {
                    "clarification_id": clarification["clarification_id"],
                    "option_ref": clarification["option_ref"],
                    "context_revision": clarification["context_revision"],
                    "semantic_source_revision": clarification["semantic_source_revision"],
                }
            else:
                answer = clarification["answer"]
                if not isinstance(answer, dict):
                    raise BrainError("INVALID_SCHEMA", 400, "clarification answer is invalid")
                if set(answer) == {"option_ref"}:
                    clarification_reference(answer["option_ref"], name="option_ref")
                    parsed_answer: dict[str, Any] = {"option_ref": answer["option_ref"]}
                elif set(answer) == {"integer"}:
                    integer = answer.get("integer")
                    if type(integer) is not int or not 1 <= integer <= 1_000_000:
                        raise BrainError("INVALID_SCHEMA", 400, "clarification answer is invalid")
                    parsed_answer = {"integer": integer}
                elif set(answer) == {"text"}:
                    parsed_answer = {"text": clarification_text(answer["text"])}
                else:
                    raise BrainError("INVALID_SCHEMA", 400, "clarification answer is invalid")
                clarification = {
                    "clarification_id": clarification["clarification_id"],
                    "answer": parsed_answer,
                    "context_revision": clarification["context_revision"],
                    "semantic_source_revision": clarification["semantic_source_revision"],
                }
        return cls(
            schema_version=schema_version,
            request_id=request_id,
            expected_context_revision=expected_context,
            expected_semantic_source_revision=expected_semantic,
            intent=intent,
            instruction=instruction,
            target=target,
            basis=basis,
            clarification_response=clarification,
        )

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "request_id": self.request_id,
            "expected_context_revision": self.expected_context_revision,
            "expected_semantic_source_revision": self.expected_semantic_source_revision,
            "intent": self.intent,
            "instruction": self.instruction,
            "target": self.target,
            "basis": self.basis,
            "clarification_response": self.clarification_response,
        }

    @property
    def payload_hash(self) -> str:
        return canonical_sha256(self.payload())

    @property
    def request_fingerprint(self) -> str:
        """Stable logical request identity, excluding retry/answer envelopes."""

        return canonical_sha256(
            {
                "expected_context_revision": self.expected_context_revision,
                "expected_semantic_source_revision": self.expected_semantic_source_revision,
                "intent": self.intent,
                "instruction": self.instruction,
                "target": self.target,
                "basis": self.basis,
            }
        )

    @property
    def clarification_answer(self) -> dict[str, Any] | None:
        response = self.clarification_response
        if response is None:
            return None
        if isinstance(response.get("answer"), dict):
            return dict(response["answer"])
        option_ref = response.get("option_ref")
        return {"option_ref": option_ref} if isinstance(option_ref, str) else None

    @property
    def dialogue_answer(self) -> DialogueAnswerEnvelope | None:
        value = self.clarification_response
        if isinstance(value, dict) and value.get("schema_version") == 2:
            return DialogueAnswerEnvelope.parse(value)
        return None

    def with_server_clarification(self, value: dict[str, Any]) -> TurnRequest:
        return replace(self, server_clarification=dict(value))

    def with_server_basis_grounding(self, value: dict[str, Any]) -> TurnRequest:
        return replace(self, server_basis_grounding=deepcopy(value))

    def with_server_flash_intent(self, value: dict[str, Any]) -> TurnRequest:
        """Attach validated, volatile intent context without changing client identity."""

        return replace(self, server_flash_intent=dict(value))

    def with_server_target_catalogs(self, values: tuple[str, ...]) -> TurnRequest:
        """Attach source-derived catalog hints without changing client identity."""

        if (
            not isinstance(values, tuple)
            or len(values) > 64
            or any(not isinstance(item, str) or not item for item in values)
            or len(values) != len(set(values))
        ):
            raise BrainError("INVALID_SCHEMA", 400, "target catalog roster is invalid")
        return replace(self, server_target_catalogs=values)


@dataclass(frozen=True)
class ClarificationAnswerRequest:
    """Client-neutral answer to one server-owned pending clarification.

    ``schema_version`` versions this standalone transport envelope.  It is not
    the Turn schema version: this route already carries typed integer answers
    for schema-2 conversations and now also carries bounded catalog text.
    """

    schema_version: int
    request_id: str
    clarification_id: str
    answer: dict[str, Any] | None = None
    message: str | None = field(default=None, repr=False)
    answers: tuple[DialogueAnswer, ...] = field(default=(), repr=False)

    @classmethod
    def parse(cls, value: dict[str, Any]) -> ClarificationAnswerRequest:
        if value.get("schema_version") == 2:
            parsed = DialogueAnswerEnvelope.parse(value)
            return cls(
                2,
                parsed.request_id,
                parsed.clarification_id,
                message=parsed.message,
                answers=parsed.answers,
            )
        exact_fields(
            value,
            required={"schema_version", "request_id", "clarification_id", "answer"},
            label="clarification answer request",
        )
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise BrainError(
                "INVALID_SCHEMA", 400, "clarification answer schema version is unsupported"
            )
        request_id = request_identifier(value["request_id"])
        clarification_id = clarification_reference(
            value["clarification_id"], name="clarification_id"
        )
        answer = value["answer"]
        if not isinstance(answer, dict):
            raise BrainError("INVALID_SCHEMA", 400, "clarification answer is invalid")
        if set(answer) == {"option_ref"}:
            option_ref = clarification_reference(answer["option_ref"], name="option_ref")
            parsed_answer: dict[str, Any] = {"option_ref": option_ref}
        elif set(answer) == {"integer"}:
            integer = answer.get("integer")
            if type(integer) is not int or not 1 <= integer <= 1_000_000:
                raise BrainError("INVALID_SCHEMA", 400, "clarification answer is invalid")
            parsed_answer = {"integer": integer}
        elif set(answer) == {"text"}:
            parsed_answer = {"text": clarification_text(answer["text"])}
        else:
            raise BrainError("INVALID_SCHEMA", 400, "clarification answer is invalid")
        return cls(
            schema_version=1,
            request_id=request_id,
            clarification_id=clarification_id,
            answer=parsed_answer,
        )


@dataclass
class TurnRecord:
    turn_id: str
    session_id: str
    request: TurnRequest = field(repr=False)
    payload_hash: str
    conversation_id: str | None = None
    basis_source: str | None = None
    basis_source_sha256: str | None = field(default=None, repr=False)
    basis_grounding: dict[str, Any] | None = None
    basis_manifest: dict[str, Any] | None = field(default=None, repr=False)
    basis_manifest_sha256: str | None = field(default=None, repr=False)
    basis_create_spec: dict[str, Any] | None = field(default=None, repr=False)
    basis_create_spec_sha256: str | None = field(default=None, repr=False)
    basis_create_ir: Any | None = field(default=None, repr=False)
    basis_create_ir_sha256: str | None = field(default=None, repr=False)
    basis_create_proof: CreateIrStageProof | None = field(default=None, repr=False)
    basis_create_generation: int | None = field(default=None, repr=False)
    basis_create_history: tuple[CreateAuthorityHistoryMessage, ...] | None = field(
        default=None, repr=False
    )
    basis_create_history_revision: str | None = field(default=None, repr=False)
    head_target_identity: str | None = field(default=None, repr=False)
    expected_head_turn_id: str | None = field(default=None, repr=False)
    candidate_proposal_ref: str | None = field(default=None, repr=False)
    candidate_source: str | None = field(default=None, repr=False)
    candidate_source_sha256: str | None = field(default=None, repr=False)
    candidate_manifest: dict[str, Any] | None = field(default=None, repr=False)
    candidate_manifest_sha256: str | None = field(default=None, repr=False)
    candidate_create_spec: dict[str, Any] | None = field(default=None, repr=False)
    candidate_create_spec_sha256: str | None = field(default=None, repr=False)
    candidate_create_ir: Any | None = field(default=None, repr=False)
    candidate_create_ir_sha256: str | None = field(default=None, repr=False)
    candidate_create_proof: CreateIrStageProof | None = field(default=None, repr=False)
    candidate_create_generation: int | None = field(default=None, repr=False)
    candidate_create_history: tuple[CreateAuthorityHistoryMessage, ...] | None = field(
        default=None, repr=False
    )
    candidate_create_history_revision: str | None = field(default=None, repr=False)
    clarification_decision: dict[str, Any] | None = None
    dialogue_state: PrivateDialogueState | None = field(default=None, repr=False)
    dialogue_pending: PendingClarificationV2 | None = field(default=None, repr=False)
    status: str = "queued"
    outcome: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    terminal: dict[str, Any] | None = None
    cancellation: threading.Event = field(default_factory=threading.Event)
    condition: threading.Condition = field(default_factory=threading.Condition)
    apply_ticket: str | None = None
    apply_ticket_expires_at: datetime | None = None
    _next_sequence: int = field(default=1, repr=False)

    def clear_private(self) -> None:
        """Erase server-only proposal and conversation attachments.

        The owning :class:`TurnStore` calls this while holding its lifecycle
        lock.  Keeping the operation on the record makes every erasure site use
        the same complete roster and prevents a newly added private attachment
        from being forgotten by close, TTL cleanup, cancellation or shutdown.
        """

        self.basis_source = None
        self.basis_source_sha256 = None
        self.basis_grounding = None
        self.basis_manifest = None
        self.basis_manifest_sha256 = None
        self.basis_create_spec = None
        self.basis_create_spec_sha256 = None
        self.basis_create_ir = None
        self.basis_create_ir_sha256 = None
        self.basis_create_proof = None
        self.basis_create_generation = None
        self.basis_create_history = None
        self.basis_create_history_revision = None
        self.head_target_identity = None
        self.expected_head_turn_id = None
        self.candidate_proposal_ref = None
        self.candidate_source = None
        self.candidate_source_sha256 = None
        self.candidate_manifest = None
        self.candidate_manifest_sha256 = None
        self.candidate_create_spec = None
        self.candidate_create_spec_sha256 = None
        self.candidate_create_ir = None
        self.candidate_create_ir_sha256 = None
        self.candidate_create_proof = None
        self.candidate_create_generation = None
        self.candidate_create_history = None
        self.candidate_create_history_revision = None
        self.clarification_decision = None
        had_dialogue = self.dialogue_state is not None or self.request.server_dialogue is not None
        self.dialogue_state = None
        self.dialogue_pending = None
        self.request = replace(
            self.request,
            server_dialogue=None,
            instruction="" if had_dialogue else self.request.instruction,
            clarification_response=None if had_dialogue else self.request.clarification_response,
        )

    def emit(self, event: str, phase: str, label: str, **metrics: int | str | bool) -> None:
        if event not in _EVENTS:
            raise ValueError("event is not public")
        safe_metrics: dict[str, int | bool] = {}
        for key, value in metrics.items():
            valid_boolean = key == "replayed" and type(value) is bool
            valid_count = (
                key in {"attempt", "count", "bytes", "duration_ms", "elapsed_ms"}
                and type(value) is int
                and 0 <= value <= MAX_EVENT_METRIC
            )
            if valid_boolean or valid_count:
                safe_metrics[key] = value
        with self.condition:
            event_value = {
                "event": event,
                "data": {
                    "schema_version": 1,
                    "turn_id": self.turn_id,
                    "sequence": self._next_sequence,
                    "phase": phase,
                    "label": label,
                    **safe_metrics,
                },
            }
            self._next_sequence += 1
            self.events.append(event_value)
            if len(self.events) > 256:
                del self.events[0]
            self.condition.notify_all()

    @contextmanager
    def heartbeat_while(
        self,
        *,
        phase: str,
        label: str,
        interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS,
    ):
        """Emit bounded liveness only while one authentic phase is blocked."""

        if (
            type(interval_seconds) not in (int, float)
            or not 0.01 <= float(interval_seconds) <= 5.0
            or not isinstance(phase, str)
            or not phase
            or len(phase.encode("utf-8")) > 96
            or not isinstance(label, str)
            or not label
            or len(label.encode("utf-8")) > 160
        ):
            raise ValueError("heartbeat contract is invalid")
        stop = threading.Event()
        started = time.monotonic()

        def emit_heartbeats() -> None:
            while not stop.wait(float(interval_seconds)):
                with self.condition:
                    if self.terminal is not None:
                        return
                    elapsed_ms = min(
                        MAX_EVENT_METRIC,
                        max(0, int((time.monotonic() - started) * 1000)),
                    )
                    self.emit("heartbeat", phase, label, elapsed_ms=elapsed_ms)

        thread = threading.Thread(
            target=emit_heartbeats,
            name=f"brain-heartbeat-{self.turn_id[:12]}",
            daemon=True,
        )
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join(timeout=min(1.0, float(interval_seconds) + 0.1))

    def public_status(self) -> dict[str, Any]:
        with self.condition:
            if self.terminal is not None:
                # Client/native transports must never receive aliases to the
                # server-owned proposal graph.  A nested mutation must not be
                # able to rewrite the private source later used as a basis.
                return deepcopy(self.terminal)
            return {
                "schema_version": self.request.schema_version,
                "turn_id": self.turn_id,
                "request_id": self.request.request_id,
                "status": self.status,
            }


@dataclass(frozen=True)
class _ProposalHead:
    """Private latest-writer authority for one session-scoped target."""

    turn_id: str
    conversation_id: str
    target_identity: str
    proposal_ref: str
    source_sha256: str
    manifest_sha256: str
    create_spec_sha256: str | None
    create_ir_sha256: str | None
    create_proof: CreateIrStageProof | None
    create_generation: int | None
    create_history_revision: str | None


@dataclass(frozen=True, slots=True, repr=False)
class _PrivateCreateState:
    """One isolated, hash-bound typed CREATE stage kept only in memory."""

    spec: dict[str, Any]
    spec_sha256: str
    ir: Any
    ir_sha256: str
    proof: CreateIrStageProof
    generation: int
    history: tuple[CreateAuthorityHistoryMessage, ...]
    history_revision: str


class _OrchestratorTurnRecord:
    """Stage orchestrator-owned private attachments away from the live store.

    The orchestrator intentionally receives a record-like object because it
    emits progress and observes cancellation throughout a turn.  Its private
    source and manifest pairs, however, must not be written to the live record
    until the session lifecycle is rechecked atomically by ``TurnStore``.
    """

    __slots__ = (
        "_record",
        "basis_manifest",
        "basis_manifest_sha256",
        "basis_create_spec",
        "basis_create_spec_sha256",
        "basis_create_ir",
        "basis_create_ir_sha256",
        "basis_create_proof",
        "basis_create_generation",
        "basis_create_history",
        "basis_create_history_revision",
        "candidate_proposal_ref",
        "candidate_source",
        "candidate_source_sha256",
        "candidate_manifest",
        "candidate_manifest_sha256",
        "candidate_create_spec",
        "candidate_create_spec_sha256",
        "candidate_create_ir",
        "candidate_create_ir_sha256",
        "candidate_create_proof",
        "candidate_create_generation",
        "candidate_create_history",
        "candidate_create_history_revision",
        "dialogue_state",
        "dialogue_pending",
    )

    _PRIVATE_NAMES = frozenset(__slots__[1:])

    def __init__(self, record: TurnRecord) -> None:
        object.__setattr__(self, "_record", record)
        object.__setattr__(
            self,
            "dialogue_state",
            None if record.dialogue_state is None else replace(record.dialogue_state),
        )
        object.__setattr__(
            self,
            "dialogue_pending",
            None if record.dialogue_pending is None else replace(record.dialogue_pending),
        )
        object.__setattr__(self, "basis_manifest", deepcopy(record.basis_manifest))
        object.__setattr__(self, "basis_manifest_sha256", record.basis_manifest_sha256)
        object.__setattr__(self, "basis_create_spec", deepcopy(record.basis_create_spec))
        object.__setattr__(self, "basis_create_spec_sha256", record.basis_create_spec_sha256)
        object.__setattr__(self, "basis_create_ir", deepcopy(record.basis_create_ir))
        object.__setattr__(self, "basis_create_ir_sha256", record.basis_create_ir_sha256)
        object.__setattr__(self, "basis_create_proof", deepcopy(record.basis_create_proof))
        object.__setattr__(self, "basis_create_generation", record.basis_create_generation)
        object.__setattr__(self, "basis_create_history", deepcopy(record.basis_create_history))
        object.__setattr__(
            self, "basis_create_history_revision", record.basis_create_history_revision
        )
        object.__setattr__(self, "candidate_proposal_ref", record.candidate_proposal_ref)
        object.__setattr__(self, "candidate_source", record.candidate_source)
        object.__setattr__(self, "candidate_source_sha256", record.candidate_source_sha256)
        object.__setattr__(self, "candidate_manifest", deepcopy(record.candidate_manifest))
        object.__setattr__(self, "candidate_manifest_sha256", record.candidate_manifest_sha256)
        object.__setattr__(self, "candidate_create_spec", deepcopy(record.candidate_create_spec))
        object.__setattr__(
            self, "candidate_create_spec_sha256", record.candidate_create_spec_sha256
        )
        object.__setattr__(self, "candidate_create_ir", deepcopy(record.candidate_create_ir))
        object.__setattr__(self, "candidate_create_ir_sha256", record.candidate_create_ir_sha256)
        object.__setattr__(self, "candidate_create_proof", deepcopy(record.candidate_create_proof))
        object.__setattr__(self, "candidate_create_generation", record.candidate_create_generation)
        object.__setattr__(
            self, "candidate_create_history", deepcopy(record.candidate_create_history)
        )
        object.__setattr__(
            self, "candidate_create_history_revision", record.candidate_create_history_revision
        )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._record, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self._PRIVATE_NAMES:
            object.__setattr__(self, name, value)
            return
        setattr(self._record, name, value)

    def clear_private(self) -> None:
        self.dialogue_state = None
        self.dialogue_pending = None
        self.basis_manifest = None
        self.basis_manifest_sha256 = None
        self.basis_create_spec = None
        self.basis_create_spec_sha256 = None
        self.basis_create_ir = None
        self.basis_create_ir_sha256 = None
        self.basis_create_proof = None
        self.basis_create_generation = None
        self.basis_create_history = None
        self.basis_create_history_revision = None
        self.candidate_proposal_ref = None
        self.candidate_source = None
        self.candidate_source_sha256 = None
        self.candidate_manifest = None
        self.candidate_manifest_sha256 = None
        self.candidate_create_spec = None
        self.candidate_create_spec_sha256 = None
        self.candidate_create_ir = None
        self.candidate_create_ir_sha256 = None
        self.candidate_create_proof = None
        self.candidate_create_generation = None
        self.candidate_create_history = None
        self.candidate_create_history_revision = None


class TurnStore:
    """Bounded async turn scheduler shared by the HTTP server and clients."""

    def __init__(
        self,
        *,
        manager: SessionManager,
        retriever: BrainRetriever,
        model: BrainModelRuntime,
        compiler: Any,
        intent_compiler: Any | None = None,
        dialogue_answer_resolver: Any | None = None,
        create_authority_provider: Any | None = None,
        max_workers: int = 1,
        max_queue: int = 32,
    ) -> None:
        if type(max_workers) is not int or not 1 <= max_workers <= 8:
            raise BrainError("INVALID_CONFIG", 500, "turn worker count is invalid")
        if type(max_queue) is not int or not 1 <= max_queue <= 256:
            raise BrainError("INVALID_CONFIG", 500, "turn queue limit is invalid")
        self._manager = manager
        self._retriever = retriever
        self._model = model
        self._compiler = compiler
        self._intent_compiler = intent_compiler
        self._dialogue_answer_resolver = dialogue_answer_resolver
        self._create_authority_provider = create_authority_provider
        self._max_queue = max_queue
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="brain-turn"
        )
        self._lock = threading.RLock()
        self._turns: dict[str, TurnRecord] = {}
        self._idempotency: dict[tuple[str, str], tuple[str, str]] = {}
        self._proposal_heads: dict[tuple[str, str], _ProposalHead] = {}
        self._active: set[str] = set()
        self._futures: dict[str, Future[None]] = {}
        # The executor queue owns only opaque IDs. Prompt-bearing records and
        # bearer tokens remain in this bounded map so closing a queued session
        # can erase them immediately without reaching into executor internals.
        self._admitted_work: dict[str, tuple[TurnRecord, str]] = {}
        self._closed = False
        self.clarifications = ClarificationStore()
        self._manager.register_cleanup_listener(self.drop_session)

    @staticmethod
    def _new_id(existing: dict[str, TurnRecord]) -> str:
        while True:
            value = secrets.token_urlsafe(24)
            if value not in existing:
                return value

    @staticmethod
    def _private_manifest_copy(
        manifest: dict[str, Any] | None,
        manifest_sha256: str | None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if manifest is None and manifest_sha256 is None:
            return None, None
        if (
            not isinstance(manifest, dict)
            or not isinstance(manifest_sha256, str)
            or canonical_sha256(manifest) != manifest_sha256
        ):
            raise BrainError("COMPILER_FAILED", 503, "private manifest authority is invalid")
        return deepcopy(manifest), manifest_sha256

    @staticmethod
    def _private_source_copy(
        source: str | None,
        source_sha256: str | None,
    ) -> tuple[str | None, str | None]:
        if source is None and source_sha256 is None:
            return None, None
        if not isinstance(source, str) or not source or not isinstance(source_sha256, str):
            raise BrainError("COMPILER_FAILED", 503, "private source authority is invalid")
        try:
            raw = source.encode("utf-8")
        except UnicodeEncodeError as error:
            raise BrainError(
                "COMPILER_FAILED", 503, "private source authority is invalid"
            ) from error
        if len(raw) > MAX_SOURCE_BYTES or bytes_sha256(raw) != source_sha256:
            raise BrainError("COMPILER_FAILED", 503, "private source authority is invalid")
        return source, source_sha256

    @staticmethod
    def _private_create_state_copy(
        *,
        spec: dict[str, Any] | None,
        spec_sha256: str | None,
        ir: Any | None,
        ir_sha256: str | None,
        proof: CreateIrStageProof | None,
        generation: int | None,
        history: tuple[CreateAuthorityHistoryMessage, ...] | None,
        history_revision: str | None,
        parent_ir: Any = _CREATE_PARENT_UNAVAILABLE,
        expected_generation: int | None = None,
    ) -> _PrivateCreateState | None:
        """Validate and isolate one all-or-none private typed CREATE stage."""

        members = (
            spec,
            spec_sha256,
            ir,
            ir_sha256,
            proof,
            generation,
            history,
            history_revision,
        )
        if all(member is None for member in members):
            return None
        if any(member is None for member in members):
            raise BrainError(
                "COMPILER_FAILED",
                503,
                "private typed CREATE authority is incomplete",
            )
        if (
            not isinstance(spec, dict)
            or not isinstance(spec_sha256, str)
            or not isinstance(ir_sha256, str)
            or type(proof) is not CreateIrStageProof
            or type(generation) is not int
            or not isinstance(history, tuple)
            or not isinstance(history_revision, str)
            or not 0 <= generation <= MAX_CREATE_PLAN_MESSAGES
            or (expected_generation is not None and generation != expected_generation)
        ):
            raise BrainError(
                "COMPILER_FAILED",
                503,
                "private typed CREATE authority is invalid",
            )
        try:
            isolated_spec = isolated_ir(spec)
            isolated_normalized_ir = isolated_ir(ir)
            spec_digest = canonical_sha256(isolated_spec)
            ir_digest = canonical_sha256(isolated_normalized_ir)
            computed_history_revision = create_authority_history_revision(history)
            isolated_history = tuple(
                CreateAuthorityHistoryMessage(
                    ordinal=message.ordinal,
                    text=str(message.text),
                    message_sha256=str(message.message_sha256),
                )
                for message in history
            )
        except (BrainError, CreateAuthoritySurfaceError, TypeError, ValueError) as error:
            raise BrainError(
                "COMPILER_FAILED",
                503,
                "private typed CREATE graph is invalid",
            ) from error
        if (
            spec_digest != spec_sha256
            or ir_digest != ir_sha256
            or computed_history_revision != history_revision
            or proof.ir_sha256 != ir_sha256
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", proof.delta_sha256)
            or type(proof.delta_operation_count) is not int
            or not 0 <= proof.delta_operation_count <= 100_000
            or (
                proof.parent_ir_sha256 is not None
                and re.fullmatch(r"sha256:[0-9a-f]{64}", proof.parent_ir_sha256) is None
            )
            or (generation == 0) != (proof.parent_ir_sha256 is None)
        ):
            raise BrainError(
                "COMPILER_FAILED",
                503,
                "private typed CREATE hashes or proof are invalid",
            )
        if parent_ir is not _CREATE_PARENT_UNAVAILABLE:
            verify_ir_stage(
                parent_ir=parent_ir,
                child_ir=isolated_normalized_ir,
                expected=proof,
            )
        return _PrivateCreateState(
            spec=isolated_spec,
            spec_sha256=spec_sha256,
            ir=isolated_normalized_ir,
            ir_sha256=ir_sha256,
            proof=deepcopy(proof),
            generation=generation,
            history=isolated_history,
            history_revision=history_revision,
        )

    @classmethod
    def _create_state_from_record(
        cls,
        record: TurnRecord | _OrchestratorTurnRecord,
        *,
        prefix: str,
        parent_ir: Any = _CREATE_PARENT_UNAVAILABLE,
        expected_generation: int | None = None,
    ) -> _PrivateCreateState | None:
        return cls._private_create_state_copy(
            spec=getattr(record, f"{prefix}_create_spec"),
            spec_sha256=getattr(record, f"{prefix}_create_spec_sha256"),
            ir=getattr(record, f"{prefix}_create_ir"),
            ir_sha256=getattr(record, f"{prefix}_create_ir_sha256"),
            proof=getattr(record, f"{prefix}_create_proof"),
            generation=getattr(record, f"{prefix}_create_generation"),
            history=getattr(record, f"{prefix}_create_history"),
            history_revision=getattr(record, f"{prefix}_create_history_revision"),
            parent_ir=parent_ir,
            expected_generation=expected_generation,
        )

    @staticmethod
    def _install_create_state(
        record: TurnRecord | _OrchestratorTurnRecord,
        *,
        prefix: str,
        state: _PrivateCreateState | None,
    ) -> None:
        setattr(record, f"{prefix}_create_spec", None if state is None else state.spec)
        setattr(
            record,
            f"{prefix}_create_spec_sha256",
            None if state is None else state.spec_sha256,
        )
        setattr(record, f"{prefix}_create_ir", None if state is None else state.ir)
        setattr(
            record,
            f"{prefix}_create_ir_sha256",
            None if state is None else state.ir_sha256,
        )
        setattr(record, f"{prefix}_create_proof", None if state is None else state.proof)
        setattr(
            record,
            f"{prefix}_create_generation",
            None if state is None else state.generation,
        )
        setattr(record, f"{prefix}_create_history", None if state is None else state.history)
        setattr(
            record,
            f"{prefix}_create_history_revision",
            None if state is None else state.history_revision,
        )

    @staticmethod
    def _create_state_identity(
        state: _PrivateCreateState | None,
    ) -> tuple[str, str, CreateIrStageProof, int, str] | None:
        if state is None:
            return None
        return (
            state.spec_sha256,
            state.ir_sha256,
            state.proof,
            state.generation,
            state.history_revision,
        )

    @staticmethod
    def _validate_candidate_create_history(
        *,
        record: TurnRecord,
        basis: _PrivateCreateState | None,
        candidate: _PrivateCreateState | None,
        allow_clarification_without_candidate: bool = False,
    ) -> None:
        """Require the exact cumulative operator lineage for a typed CREATE stage."""

        if candidate is None:
            if basis is not None and not allow_clarification_without_candidate:
                raise BrainError(
                    "COMPILER_FAILED",
                    503,
                    "typed CREATE refinement cannot discard its private authority",
                )
            return
        if record.dialogue_state is not None:
            state = replace(record.dialogue_state)
            if (
                candidate.history != state.messages
                or candidate.history_revision != state.binding.history_revision
            ):
                raise BrainError(
                    "COMPILER_FAILED", 503, "typed CREATE history differs from admitted dialogue"
                )
            return
        try:
            raw_instruction = record.request.instruction.encode("utf-8")
        except UnicodeError as error:
            raise BrainError(
                "COMPILER_FAILED",
                503,
                "typed CREATE history instruction is invalid",
            ) from error
        message = CreateAuthorityHistoryMessage(
            ordinal=0 if basis is None else len(basis.history),
            text=record.request.instruction,
            message_sha256=bytes_sha256(raw_instruction),
        )
        if basis is None:
            expected = (message,)
        elif (
            record.request.clarification_response is not None
            and basis.history[-1].text == record.request.instruction
        ):
            # An answer retries the exact unresolved operator instruction.  It
            # must not append that message a second time.
            expected = basis.history
        else:
            expected = (*basis.history, message)
        if candidate.history != expected:
            raise BrainError(
                "COMPILER_FAILED",
                503,
                "typed CREATE history does not match its cumulative lineage",
            )

    @classmethod
    def _stage_candidate_source(
        cls,
        staged: _OrchestratorTurnRecord,
        result: dict[str, Any],
    ) -> None:
        proposal = result.get("proposal")
        if result.get("outcome") != "proposed":
            if proposal is not None:
                raise BrainError("INTERNAL_ERROR", 500, "turn proposal outcome is invalid")
            staged.candidate_proposal_ref = None
            staged.candidate_source = None
            staged.candidate_source_sha256 = None
            cls._install_create_state(staged, prefix="candidate", state=None)
            return
        if not isinstance(proposal, dict):
            raise BrainError("INTERNAL_ERROR", 500, "turn proposal is unavailable")
        proposal_ref = proposal.get("proposal_ref")
        if not isinstance(proposal_ref, str) or _REF_RE.fullmatch(proposal_ref) is None:
            raise BrainError("INTERNAL_ERROR", 500, "turn proposal authority is invalid")
        source, source_sha256 = cls._private_source_copy(
            proposal.get("source"),
            proposal.get("source_sha256"),
        )
        staged.candidate_proposal_ref = proposal_ref
        staged.candidate_source = source
        staged.candidate_source_sha256 = source_sha256

    @staticmethod
    def _target_identity(target: dict[str, Any]) -> str:
        return canonical_sha256(target)

    def _candidate_head(
        self,
        record: TurnRecord,
        payload: dict[str, Any],
    ) -> _ProposalHead | None:
        """Return a validated head candidate, or None for an unmanifested proposal."""

        if payload.get("outcome") != "proposed":
            return None
        manifest, manifest_sha256 = self._private_manifest_copy(
            record.candidate_manifest,
            record.candidate_manifest_sha256,
        )
        if manifest is None or manifest_sha256 is None:
            # Legacy unnamed drafts can still be presented, but cannot become
            # an incremental-create authority until the compiler identifies
            # their exact endpoint occurrence and emits its private manifest.
            return None
        source, source_sha256 = self._private_source_copy(
            record.candidate_source,
            record.candidate_source_sha256,
        )
        basis_create = self._create_state_from_record(record, prefix="basis")
        candidate_create = self._create_state_from_record(
            record,
            prefix="candidate",
            parent_ir=None if basis_create is None else basis_create.ir,
            expected_generation=0 if basis_create is None else basis_create.generation + 1,
        )
        if candidate_create is not None and record.request.target.get("mode") != "create":
            raise BrainError(
                "COMPILER_FAILED",
                503,
                "typed CREATE authority cannot attach to an existing target",
            )
        self._validate_candidate_create_history(
            record=record,
            basis=basis_create,
            candidate=candidate_create,
        )
        proposal = payload.get("proposal")
        proposal_ref = record.candidate_proposal_ref
        target_identity = record.head_target_identity
        conversation_id = record.conversation_id
        if (
            source is None
            or not isinstance(proposal, dict)
            or not isinstance(proposal_ref, str)
            or proposal.get("proposal_ref") != proposal_ref
            or proposal.get("source") != source
            or proposal.get("source_sha256") != source_sha256
            or not isinstance(target_identity, str)
            or target_identity != self._target_identity(record.request.target)
            or not isinstance(conversation_id, str)
            or not conversation_id
        ):
            raise BrainError("COMPILER_FAILED", 503, "private proposal head is invalid")
        return _ProposalHead(
            turn_id=record.turn_id,
            conversation_id=conversation_id,
            target_identity=target_identity,
            proposal_ref=proposal_ref,
            source_sha256=source_sha256,
            manifest_sha256=manifest_sha256,
            create_spec_sha256=(None if candidate_create is None else candidate_create.spec_sha256),
            create_ir_sha256=None if candidate_create is None else candidate_create.ir_sha256,
            create_proof=None if candidate_create is None else candidate_create.proof,
            create_generation=None if candidate_create is None else candidate_create.generation,
            create_history_revision=(
                None if candidate_create is None else candidate_create.history_revision
            ),
        )

    def _advance_head_locked(self, record: TurnRecord, payload: dict[str, Any]) -> None:
        proposed = payload.get("outcome") == "proposed"
        if proposed and (
            self._closed
            or self._turns.get(record.turn_id) is not record
            or record.cancellation.is_set()
        ):
            raise BrainError("SESSION_REVOKED", 409, "session was revoked")
        candidate = self._candidate_head(record, payload)
        if candidate is None:
            return
        key = (record.session_id, candidate.target_identity)
        current = self._proposal_heads.get(key)
        if (current.turn_id if current is not None else None) != record.expected_head_turn_id:
            raise BrainError("PROPOSAL_STALE", 409, "proposal head advanced")
        if current is not None and current.conversation_id != candidate.conversation_id:
            raise BrainError("PROPOSAL_STALE", 409, "proposal conversation differs")
        basis_create = self._create_state_from_record(record, prefix="basis")
        current_members = (
            ()
            if current is None
            else (
                current.create_spec_sha256,
                current.create_ir_sha256,
                current.create_proof,
                current.create_generation,
                current.create_history_revision,
            )
        )
        if (
            current_members
            and any(member is None for member in current_members)
            and not all(member is None for member in current_members)
        ):
            raise BrainError("PROPOSAL_STALE", 409, "typed CREATE proposal head is invalid")
        current_identity = (
            None
            if not current_members or all(member is None for member in current_members)
            else current_members
        )
        if current_identity != self._create_state_identity(basis_create):
            raise BrainError("PROPOSAL_STALE", 409, "typed CREATE proposal head differs")
        self._proposal_heads[key] = candidate

    @staticmethod
    def _candidate_attachments_are_empty(staged: _OrchestratorTurnRecord) -> bool:
        """Reject any proposal authority on a clarification-only refinement."""

        return all(
            getattr(staged, name) is None
            for name in (
                "candidate_proposal_ref",
                "candidate_source",
                "candidate_source_sha256",
                "candidate_manifest",
                "candidate_manifest_sha256",
                "candidate_create_spec",
                "candidate_create_spec_sha256",
                "candidate_create_ir",
                "candidate_create_ir_sha256",
                "candidate_create_proof",
                "candidate_create_generation",
                "candidate_create_history",
                "candidate_create_history_revision",
            )
        )

    def _is_exact_pending_create_clarification(
        self,
        *,
        record: TurnRecord,
        basis: _PrivateCreateState,
        result: dict[str, Any] | None,
    ) -> bool:
        """Accept a missing refined candidate only for its issued v2 question.

        A typed CREATE refinement may legitimately need one more operator
        decision.  Its predecessor remains private authority while the issued
        clarification is pending; no source, manifest or proposal head may be
        attached to that intermediate turn.
        """

        if (
            not isinstance(result, dict)
            or record.request.target.get("mode") != "create"
            or record.request.schema_version != 2
            or result.get("schema_version") != 2
            or result.get("turn_id") != record.turn_id
            or result.get("request_id") != record.request.request_id
            or result.get("status") != "completed"
            or result.get("outcome") != "needs_clarification"
            or result.get("route") != "local"
            or not isinstance(result.get("clarification"), dict)
        ):
            return False
        clarification = result["clarification"]
        try:
            clarification_id = clarification_reference(
                clarification.get("clarification_id"), name="clarification_id"
            )
            pending = self.clarifications.pending_v2(
                session_id=record.session_id,
                clarification_id=clarification_id,
            )
        except BrainError:
            return False
        dialogue = record.dialogue_state
        if (
            type(dialogue) is not PrivateDialogueState
            or not dialogue.messages
            or dialogue.binding.history_revision
            != create_authority_history_revision(dialogue.messages)
            or dialogue.messages[: len(basis.history)] != basis.history
            or clarification != pending.payload()
            or pending.session_id != record.session_id
            or pending.conversation_id != record.conversation_id
            or pending.binding != dialogue.binding
            or pending.binding.context_revision != record.request.expected_context_revision
            or pending.binding.semantic_revision != record.request.expected_semantic_source_revision
        ):
            return False
        attached_pending = record.dialogue_pending
        if attached_pending is not None:
            return attached_pending == pending
        return (
            pending.parent_turn_id == record.turn_id
            and pending.binding.parent_fingerprint == record.request.request_fingerprint
        )

    def _publish_private_attachments(
        self,
        record: TurnRecord,
        staged: _OrchestratorTurnRecord,
        *,
        result: dict[str, Any] | None = None,
    ) -> bool:
        """Publish staged manifests only to the exact still-live turn record."""

        with self._lock:
            if (
                self._closed
                or self._turns.get(record.turn_id) is not record
                or record.cancellation.is_set()
                or record.terminal is not None
            ):
                self._discard_rotated_dialogue_pending(record)
                record.clear_private()
                return False
            live_dialogue = (
                None if record.dialogue_state is None else replace(record.dialogue_state)
            )
            staged_dialogue = (
                None if staged.dialogue_state is None else replace(staged.dialogue_state)
            )
            if staged_dialogue != live_dialogue:
                raise BrainError("PROPOSAL_STALE", 409, "private dialogue changed during the turn")
            basis_manifest, basis_manifest_sha256 = self._private_manifest_copy(
                staged.basis_manifest,
                staged.basis_manifest_sha256,
            )
            candidate_manifest, candidate_manifest_sha256 = self._private_manifest_copy(
                staged.candidate_manifest,
                staged.candidate_manifest_sha256,
            )
            candidate_source, candidate_source_sha256 = self._private_source_copy(
                staged.candidate_source,
                staged.candidate_source_sha256,
            )
            live_basis_create = self._create_state_from_record(record, prefix="basis")
            staged_basis_create = self._create_state_from_record(staged, prefix="basis")
            if self._create_state_identity(staged_basis_create) != self._create_state_identity(
                live_basis_create
            ):
                raise BrainError(
                    "PROPOSAL_STALE",
                    409,
                    "private typed CREATE basis changed during the turn",
                )
            candidate_create = self._create_state_from_record(
                staged,
                prefix="candidate",
                parent_ir=None if staged_basis_create is None else staged_basis_create.ir,
                expected_generation=(
                    0 if staged_basis_create is None else staged_basis_create.generation + 1
                ),
            )
            if candidate_create is not None and record.request.target.get("mode") != "create":
                raise BrainError(
                    "COMPILER_FAILED",
                    503,
                    "typed CREATE authority cannot attach to an existing target",
                )
            allow_clarification_without_candidate = (
                staged_basis_create is not None
                and candidate_create is None
                and self._candidate_attachments_are_empty(staged)
                and self._is_exact_pending_create_clarification(
                    record=record,
                    basis=staged_basis_create,
                    result=result,
                )
            )
            self._validate_candidate_create_history(
                record=record,
                basis=staged_basis_create,
                candidate=candidate_create,
                allow_clarification_without_candidate=allow_clarification_without_candidate,
            )
            candidate_proposal_ref = staged.candidate_proposal_ref
            if candidate_proposal_ref is not None and (
                not isinstance(candidate_proposal_ref, str)
                or _REF_RE.fullmatch(candidate_proposal_ref) is None
            ):
                raise BrainError("COMPILER_FAILED", 503, "private proposal authority is invalid")
            record.basis_manifest = basis_manifest
            record.basis_manifest_sha256 = basis_manifest_sha256
            self._install_create_state(record, prefix="basis", state=staged_basis_create)
            record.candidate_proposal_ref = candidate_proposal_ref
            record.candidate_source = candidate_source
            record.candidate_source_sha256 = candidate_source_sha256
            record.candidate_manifest = candidate_manifest
            record.candidate_manifest_sha256 = candidate_manifest_sha256
            self._install_create_state(record, prefix="candidate", state=candidate_create)
            return True

    def _clear_private_if_current(self, record: TurnRecord) -> None:
        with self._lock:
            if self._turns.get(record.turn_id) is record:
                self._discard_rotated_dialogue_pending(record)
                record.clear_private()

    def _discard_rotated_dialogue_pending(self, record: TurnRecord) -> None:
        envelope = record.request.dialogue_answer
        pending = record.dialogue_pending
        if (
            envelope is not None
            and pending is not None
            and pending.clarification_id != envelope.clarification_id
        ):
            self.clarifications.discard_pending_for_turn(
                session_id=record.session_id,
                parent_turn_id=pending.parent_turn_id,
            )

    def _dialogue_pending_for_answer(
        self,
        *,
        session_id: str,
        request: TurnRequest,
        parent: TurnRecord | None,
        claim_owner: str | None = None,
    ) -> PendingClarificationV2:
        """Bind a v2 answer to its server-owned parent, never the new prompt hash."""
        answer = request.dialogue_answer
        if answer is None or parent is None or self._turns.get(parent.turn_id) is not parent:
            raise BrainError("CLARIFICATION_UNAVAILABLE", 409, "dialogue parent is unavailable")
        if parent.session_id != session_id or parent.request.target != request.target:
            raise BrainError("CLARIFICATION_MISMATCH", 409, "dialogue parent differs")
        state = parent.dialogue_state
        if state is None:
            raise BrainError("CLARIFICATION_UNAVAILABLE", 409, "parent dialogue is unavailable")
        state = replace(state)
        pending = self.clarifications.pending_v2(
            session_id=session_id,
            clarification_id=answer.clarification_id,
        )
        issued_by = self._turns.get(pending.parent_turn_id)
        if (
            issued_by is None
            or issued_by.session_id != session_id
            or issued_by.conversation_id != state.conversation_id
            or pending.binding.parent_fingerprint != issued_by.request.request_fingerprint
            or pending.conversation_id != state.conversation_id
            or pending.binding.context_revision != request.expected_context_revision
            or pending.binding.semantic_revision != request.expected_semantic_source_revision
            or pending.binding.toolchain_binding != state.binding.toolchain_binding
            or pending.binding.history_revision
            not in {
                create_authority_history_revision(state.messages[:index])
                for index in range(1, len(state.messages) + 1)
            }
        ):
            raise BrainError("CLARIFICATION_STALE", 409, "dialogue parent binding differs")
        if answer.answers:
            self.clarifications.validate_answers_v2(
                session_id=session_id,
                clarification_id=pending.clarification_id,
                binding=pending.binding,
                answers=answer.answers,
                claim_owner=claim_owner,
            )
        return pending

    @staticmethod
    def _dialogue_for_request(
        *,
        request: TurnRequest,
        conversation_id: str,
        toolchain_binding: str,
        parent: PrivateDialogueState | None,
    ) -> PrivateDialogueState:
        parent = None if parent is None else replace(parent)
        if parent is not None and (
            parent.conversation_id != conversation_id
            or parent.binding.context_revision != request.expected_context_revision
            or parent.binding.semantic_revision != request.expected_semantic_source_revision
            or parent.binding.toolchain_binding != toolchain_binding
        ):
            raise BrainError("PROPOSAL_STALE", 409, "dialogue parent authority differs")
        messages = () if parent is None else parent.messages
        answer = request.dialogue_answer
        # A button-only answer adds no operator utterance. V1 resumes its exact
        # prior instruction; a v2 message is a new utterance even if text repeats.
        append = (
            answer.message is not None
            if answer is not None
            else request.clarification_response is None
        )
        if not messages or append:
            text = request.instruction
            messages = (
                *messages,
                CreateAuthorityHistoryMessage(
                    ordinal=len(messages),
                    text=text,
                    message_sha256=bytes_sha256(text.encode("utf-8")),
                ),
            )
        binding = DialogueBinding(
            request.expected_context_revision,
            request.expected_semantic_source_revision,
            toolchain_binding,
            create_authority_history_revision(messages),
            request.request_fingerprint,
        )
        return PrivateDialogueState(
            conversation_id=conversation_id,
            binding=binding,
            messages=messages,
            decisions=() if parent is None else parent.decisions,
            generation=0 if parent is None else parent.generation + 1,
            latest_proposal_binding=None if parent is None else parent.latest_proposal_binding,
        )

    def submit(
        self,
        *,
        session_id: str,
        token: str,
        request: TurnRequest,
        _private_basis_manifest: dict[str, Any] | None = None,
        _private_basis_manifest_sha256: str | None = None,
        _private_dialogue_parent: TurnRecord | None = None,
    ) -> TurnRecord:
        # Authenticate before the idempotency lookup. A retry must return its
        # terminal record even if the tenant has changed since the first turn.
        self._manager._authenticate(  # noqa: SLF001
            session_id=session_id, token=token, capability="chat.turn"
        )
        self.clarifications.touch_session(session_id)
        with self._lock:
            if self._closed:
                raise BrainError("SERVICE_UNAVAILABLE", 503, "turn service is shutting down")
            key = (session_id, request.request_id)
            old = self._idempotency.get(key)
            if old is not None:
                old_hash, old_turn_id = old
                if old_hash != request.payload_hash:
                    raise BrainError(
                        "IDEMPOTENCY_KEY_REUSE",
                        409,
                        "request_id was used with another payload",
                    )
                return self._turns[old_turn_id]
            self._validate_basis_locked(session_id=session_id, request=request)
            if session_id in self._active:
                raise BrainError("TURN_ACTIVE", 409, "one turn is already active for this session")
            if request.clarification_response is None and self.clarifications.has_pending(
                session_id
            ):
                raise BrainError(
                    "CLARIFICATION_PENDING", 409, "answer the pending clarification first"
                )
            session_turns = sum(record.session_id == session_id for record in self._turns.values())
            if session_turns >= MAX_SESSION_TURNS:
                raise BrainError("TURN_LIMIT", 429, "session turn history is full")
            if len(self._active) >= self._max_queue:
                raise BrainError("TURN_QUEUE_FULL", 429, "turn queue is full")
        # Admission performs the same immutable snapshot and target checks as the worker.
        with self._manager.operation(
            session_id=session_id,
            token=token,
            capability="chat.turn",
            expected_revision=request.expected_context_revision,
        ) as lease:
            self._validate_target_snapshot(lease, request)
            if request.expected_semantic_source_revision == "sha256:" + "0" * 64:
                raise BrainError("STALE_CONTEXT", 409, "semantic source revision is unavailable")
            # Keep the authoritative session lease until the record is inserted
            # and the worker is accepted.  A concurrent close/TTL cleanup can no
            # longer finish and then be followed by a resurrected turn record.
            with self._lock:
                if lease.cancellation.is_set():
                    raise BrainError("SESSION_REVOKED", 409, "session was revoked")
                # Another request can have won the race while the snapshot was captured.
                key = (session_id, request.request_id)
                old = self._idempotency.get(key)
                if old is not None:
                    if old[0] != request.payload_hash:
                        raise BrainError(
                            "IDEMPOTENCY_KEY_REUSE",
                            409,
                            "request_id was used with another payload",
                        )
                    return self._turns[old[1]]
                if session_id in self._active:
                    raise BrainError(
                        "TURN_ACTIVE", 409, "one turn is already active for this session"
                    )
                if request.clarification_response is None and self.clarifications.has_pending(
                    session_id
                ):
                    raise BrainError(
                        "CLARIFICATION_PENDING", 409, "answer the pending clarification first"
                    )
                if request.clarification_response is not None:
                    if request.dialogue_answer is not None:
                        self._dialogue_pending_for_answer(
                            session_id=session_id, request=request, parent=_private_dialogue_parent
                        )
                    else:
                        response = request.clarification_response
                        self.clarifications.validate_answer(
                            session_id=session_id,
                            clarification_id=response["clarification_id"],
                            request_fingerprint=request.request_fingerprint,
                            context_revision=response["context_revision"],
                            semantic_source_revision=response["semantic_source_revision"],
                            answer=request.clarification_answer or {},
                        )
                if lease.cancellation.is_set():
                    raise BrainError("SESSION_REVOKED", 409, "session was revoked")
                basis_record = self._validate_basis_locked(session_id=session_id, request=request)
                head_target_identity = self._target_identity(request.target)
                current_head = self._proposal_heads.get((session_id, head_target_identity))
                if basis_record is None:
                    if current_head is not None:
                        raise BrainError("PROPOSAL_STALE", 409, "proposal head already exists")
                    expected_head_turn_id = None
                else:
                    expected_head_turn_id = basis_record.turn_id
                turn_id = self._new_id(self._turns)
                basis_source = basis_record.candidate_source if basis_record is not None else None
                basis_source_sha256 = (
                    basis_record.candidate_source_sha256 if basis_record is not None else None
                )
                dialogue_parent_terminal = (
                    _private_dialogue_parent.terminal
                    if _private_dialogue_parent is not None
                    and isinstance(_private_dialogue_parent.terminal, dict)
                    else None
                )
                dialogue_parent_grounding = (
                    dialogue_parent_terminal.get("grounding")
                    if isinstance(dialogue_parent_terminal, dict)
                    and dialogue_parent_terminal.get("status") == "completed"
                    and dialogue_parent_terminal.get("outcome") == "needs_clarification"
                    and isinstance(dialogue_parent_terminal.get("grounding"), dict)
                    else _private_dialogue_parent.basis_grounding
                    if _private_dialogue_parent is not None
                    and isinstance(_private_dialogue_parent.basis_grounding, dict)
                    else None
                )
                basis_grounding = (
                    basis_record.terminal.get("grounding")
                    if basis_record and isinstance(basis_record.terminal, dict)
                    else dialogue_parent_grounding
                )
                basis_manifest = (
                    basis_record.candidate_manifest
                    if basis_record is not None
                    else _private_basis_manifest
                )
                basis_manifest_sha256 = (
                    basis_record.candidate_manifest_sha256
                    if basis_record is not None
                    else _private_basis_manifest_sha256
                )
                try:
                    basis_create = (
                        None
                        if basis_record is None
                        else self._create_state_from_record(
                            basis_record,
                            prefix="candidate",
                            parent_ir=(
                                None
                                if basis_record.basis_create_generation is None
                                else basis_record.basis_create_ir
                            ),
                            expected_generation=(
                                0
                                if basis_record.basis_create_generation is None
                                else basis_record.basis_create_generation + 1
                            ),
                        )
                    )
                except BrainError as error:
                    raise BrainError(
                        "PROPOSAL_STALE",
                        409,
                        "proposal typed CREATE authority is stale",
                    ) from error
                if basis_manifest is not None and (
                    not isinstance(basis_manifest_sha256, str)
                    or canonical_sha256(basis_manifest) != basis_manifest_sha256
                ):
                    raise BrainError(
                        "PROPOSAL_STALE", 409, "proposal structural authority is stale"
                    )
                if isinstance(basis_grounding, dict):
                    request = request.with_server_basis_grounding(basis_grounding)
                dialogue_parent = _private_dialogue_parent or basis_record
                conversation_id = (
                    dialogue_parent.conversation_id
                    if dialogue_parent is not None and dialogue_parent.conversation_id
                    else request.request_fingerprint
                )
                dialogue_state = None
                if request.schema_version == 2:
                    dialogue_state = self._dialogue_for_request(
                        request=request,
                        conversation_id=conversation_id,
                        toolchain_binding=lease.snapshot.toolchain_binding,
                        parent=None if dialogue_parent is None else dialogue_parent.dialogue_state,
                    )
                    request = replace(request, server_dialogue=replace(dialogue_state))
                record = TurnRecord(
                    turn_id=turn_id,
                    session_id=session_id,
                    request=request,
                    payload_hash=request.payload_hash,
                    conversation_id=conversation_id,
                    dialogue_state=dialogue_state,
                    basis_source=basis_source if isinstance(basis_source, str) else None,
                    basis_source_sha256=basis_source_sha256,
                    basis_grounding=(
                        deepcopy(basis_grounding) if isinstance(basis_grounding, dict) else None
                    ),
                    basis_manifest=(
                        deepcopy(basis_manifest) if isinstance(basis_manifest, dict) else None
                    ),
                    basis_manifest_sha256=basis_manifest_sha256,
                    basis_create_spec=None if basis_create is None else basis_create.spec,
                    basis_create_spec_sha256=(
                        None if basis_create is None else basis_create.spec_sha256
                    ),
                    basis_create_ir=None if basis_create is None else basis_create.ir,
                    basis_create_ir_sha256=(
                        None if basis_create is None else basis_create.ir_sha256
                    ),
                    basis_create_proof=None if basis_create is None else basis_create.proof,
                    basis_create_generation=(
                        None if basis_create is None else basis_create.generation
                    ),
                    basis_create_history=None if basis_create is None else basis_create.history,
                    basis_create_history_revision=(
                        None if basis_create is None else basis_create.history_revision
                    ),
                    head_target_identity=head_target_identity,
                    expected_head_turn_id=expected_head_turn_id,
                )
                if lease.cancellation.is_set():
                    raise BrainError("SESSION_REVOKED", 409, "session was revoked")
                if request.clarification_response is not None:
                    if request.dialogue_answer is not None:
                        record.dialogue_pending = self._dialogue_pending_for_answer(
                            session_id=session_id,
                            request=request,
                            parent=_private_dialogue_parent,
                            claim_owner=record.turn_id,
                        )
                    else:
                        response = request.clarification_response
                        self.clarifications.validate_answer(
                            session_id=session_id,
                            clarification_id=response["clarification_id"],
                            request_fingerprint=request.request_fingerprint,
                            context_revision=response["context_revision"],
                            semantic_source_revision=response["semantic_source_revision"],
                            answer=request.clarification_answer or {},
                            claim_owner=record.turn_id,
                        )
                self._turns[record.turn_id] = record
                self._idempotency[key] = (request.payload_hash, record.turn_id)
                self._active.add(session_id)
                record.emit("turn.accepted", "accepted", "Turn accettato")
                self._admitted_work[record.turn_id] = (record, token)
                try:
                    future = self._executor.submit(
                        self._run_admitted,
                        record.turn_id,
                        record.session_id,
                    )
                except RuntimeError as error:
                    self._admitted_work.pop(record.turn_id, None)
                    self._active.discard(session_id)
                    self._turns.pop(record.turn_id, None)
                    self._idempotency.pop(key, None)
                    self.clarifications.release_answer_claim(
                        session_id=session_id,
                        owner=record.turn_id,
                    )
                    raise BrainError(
                        "SERVICE_UNAVAILABLE", 503, "turn service is unavailable"
                    ) from error
                self._futures[record.turn_id] = future
                future.add_done_callback(
                    lambda completed, turn_id=record.turn_id, owner_session=session_id: (
                        self._forget_future(
                            turn_id,
                            owner_session,
                            completed,
                        )
                    )
                )
                return record

    def _run_admitted(self, turn_id: str, session_id: str) -> None:
        with self._lock:
            work = self._admitted_work.pop(turn_id, None)
        if work is None:
            self.clarifications.release_answer_claim(
                session_id=session_id,
                owner=turn_id,
            )
            self.clarifications.release_revocation_guard(session_id, owner=turn_id)
            return
        record, token = work
        self._run(record, token)

    def _forget_future(
        self,
        turn_id: str,
        session_id: str,
        completed: Future[None],
    ) -> None:
        with self._lock:
            if self._futures.get(turn_id) is completed:
                self._futures.pop(turn_id, None)
            self._admitted_work.pop(turn_id, None)
        if completed.cancelled():
            self.clarifications.release_answer_claim(
                session_id=session_id,
                owner=turn_id,
            )
            self.clarifications.release_revocation_guard(session_id, owner=turn_id)

    def _validate_basis_locked(self, *, session_id: str, request: TurnRequest) -> TurnRecord | None:
        if request.basis is None:
            return None
        wanted = request.basis["proposal_ref"]
        for record in self._turns.values():
            if record.candidate_proposal_ref != wanted:
                continue
            terminal = record.terminal
            if not isinstance(terminal, dict):
                continue
            proposal = terminal.get("proposal")
            if not isinstance(proposal, dict) or proposal.get("proposal_ref") != wanted:
                raise BrainError("PROPOSAL_STALE", 409, "proposal authority differs")
            if record.session_id != session_id:
                raise BrainError("PROPOSAL_STALE", 409, "proposal is scoped to another session")
            if (
                record.request.expected_context_revision != request.expected_context_revision
                or record.request.expected_semantic_source_revision
                != request.expected_semantic_source_revision
            ):
                raise BrainError("PROPOSAL_STALE", 409, "proposal revision is stale")
            if record.request.target != request.target:
                raise BrainError("PROPOSAL_STALE", 409, "proposal target differs")
            try:
                candidate_source, candidate_source_sha256 = self._private_source_copy(
                    record.candidate_source,
                    record.candidate_source_sha256,
                )
            except BrainError as error:
                raise BrainError(
                    "PROPOSAL_STALE", 409, "proposal source authority is unavailable"
                ) from error
            if (
                candidate_source is None
                or proposal.get("source") != candidate_source
                or proposal.get("source_sha256") != candidate_source_sha256
            ):
                raise BrainError("PROPOSAL_STALE", 409, "proposal source authority differs")
            target_identity = self._target_identity(request.target)
            current = self._proposal_heads.get((session_id, target_identity))
            manifest = record.candidate_manifest
            manifest_sha256 = record.candidate_manifest_sha256
            try:
                parent_create = self._create_state_from_record(record, prefix="basis")
                candidate_create = self._create_state_from_record(
                    record,
                    prefix="candidate",
                    parent_ir=None if parent_create is None else parent_create.ir,
                    expected_generation=(
                        0 if parent_create is None else parent_create.generation + 1
                    ),
                )
            except BrainError as error:
                raise BrainError(
                    "PROPOSAL_STALE",
                    409,
                    "proposal typed CREATE authority is unavailable",
                ) from error
            if (
                current is None
                or current.turn_id != record.turn_id
                or current.conversation_id != record.conversation_id
                or current.target_identity != target_identity
                or current.proposal_ref != wanted
                or current.source_sha256 != candidate_source_sha256
                or current.manifest_sha256 != manifest_sha256
                or current.create_spec_sha256
                != (None if candidate_create is None else candidate_create.spec_sha256)
                or current.create_ir_sha256
                != (None if candidate_create is None else candidate_create.ir_sha256)
                or current.create_proof
                != (None if candidate_create is None else candidate_create.proof)
                or current.create_generation
                != (None if candidate_create is None else candidate_create.generation)
                or current.create_history_revision
                != (None if candidate_create is None else candidate_create.history_revision)
            ):
                raise BrainError("PROPOSAL_STALE", 409, "proposal is not the latest head")
            if (
                manifest is None
                or not isinstance(manifest_sha256, str)
                or canonical_sha256(manifest) != manifest_sha256
            ):
                raise BrainError(
                    "PROPOSAL_STALE", 409, "proposal structural authority is unavailable"
                )
            return record
        raise BrainError("PROPOSAL_STALE", 409, "proposal is unavailable")

    def drop_session(self, session_id: str) -> None:
        """Erase every volatile turn/proposal byte owned by one closed session."""

        with self._lock:
            doomed = [
                turn_id
                for turn_id, record in self._turns.items()
                if record.session_id == session_id
            ]
            revocation_owner: str | None = None
            if session_id in self._active:
                revocation_owner = next(
                    (
                        turn_id
                        for turn_id in reversed(doomed)
                        if self._turns[turn_id].terminal is None
                    ),
                    doomed[-1] if doomed else None,
                )
            for turn_id in doomed:
                record = self._turns.pop(turn_id)
                record.cancellation.set()
                self._admitted_work.pop(turn_id, None)
                record.clear_private()
            for key in [key for key in self._idempotency if key[0] == session_id]:
                self._idempotency.pop(key, None)
            for key in [key for key in self._proposal_heads if key[0] == session_id]:
                self._proposal_heads.pop(key, None)
            self._active.discard(session_id)
            self.clarifications.drop_session(
                session_id,
                revocation_owner=revocation_owner,
            )
            for turn_id in doomed:
                future = self._futures.get(turn_id)
                if future is not None:
                    future.cancel()

    def aggregate_metrics(self) -> dict[str, int]:
        with self._lock:
            turn_metrics = {
                "turns": len(self._turns),
                "conversations": len(
                    {
                        (record.session_id, record.conversation_id)
                        for record in self._turns.values()
                        if record.conversation_id is not None
                    }
                ),
            }
        clarification_metrics = self.clarifications.metrics()
        return {
            **turn_metrics,
            "pending": clarification_metrics["pending"],
            "clarification_decisions": clarification_metrics["decisions"],
            "clarification_assumptions": clarification_metrics["assumptions"],
        }

    @staticmethod
    def _validate_target_snapshot(lease: OperationLease, request: TurnRequest) -> None:
        path = request.target["relative_path"]
        source_map = lease.snapshot.source_map()
        current = source_map.get(path)
        if request.target["mode"] == "create":
            if current is not None:
                raise BrainError("TARGET_EXISTS", 409, "create target already exists")
        else:
            if current is None:
                raise BrainError("TARGET_UNAVAILABLE", 409, "target is unavailable")
            if bytes_sha256(current.encode("utf-8")) != request.target["base_sha256"]:
                raise BrainError("BASE_STALE", 409, "target base revision differs")

    def get(self, *, session_id: str, token: str, turn_id: str) -> dict[str, Any]:
        record = self._authenticate_record(
            session_id=session_id, token=token, turn_id=turn_id, capability="chat.read"
        )
        return record.public_status()

    def seal_typed_create_qualification_receipt(
        self,
        *,
        session_id: str,
        token: str,
        turn_id: str,
    ) -> dict[str, Any]:
        """Seal a hash-only proof for an in-process, completed typed CREATE Draft.

        This deliberately is not an HTTP surface.  Qualification must obtain the
        proof while the owning session is live; normal session erasure removes
        the private typed graph before any post-run oracle is loaded.
        """

        record = self._authenticate_record(
            session_id=session_id,
            token=token,
            turn_id=turn_id,
            capability="chat.read",
        )
        with record.condition, self._lock:
            if self._closed or self._turns.get(turn_id) is not record:
                raise BrainError("TURN_UNAVAILABLE", 404, "turn is unavailable")
            terminal = record.terminal
            if (
                not isinstance(terminal, dict)
                or terminal.get("status") != "completed"
                or terminal.get("outcome") != "proposed"
                or record.request.target.get("mode") != "create"
            ):
                raise BrainError(
                    "QUALIFICATION_PROOF_UNAVAILABLE",
                    409,
                    "typed CREATE qualification proof is unavailable",
                )
            basis = self._create_state_from_record(record, prefix="basis")
            candidate = self._create_state_from_record(
                record,
                prefix="candidate",
                parent_ir=None if basis is None else basis.ir,
                expected_generation=0 if basis is None else basis.generation + 1,
            )
            source, source_sha256 = self._private_source_copy(
                record.candidate_source,
                record.candidate_source_sha256,
            )
            manifest, manifest_sha256 = self._private_manifest_copy(
                record.candidate_manifest,
                record.candidate_manifest_sha256,
            )
            proposal = terminal.get("proposal")
            validation = terminal.get("validation")
            identity = terminal.get("identity")
            compiler_receipt_sha256 = (
                validation.get("compiler_receipt_sha256") if isinstance(validation, dict) else None
            )
            if (
                candidate is None
                or source is None
                or manifest is None
                or not isinstance(source_sha256, str)
                or not isinstance(manifest_sha256, str)
                or not isinstance(proposal, dict)
                or proposal.get("source_sha256") != source_sha256
                or not isinstance(validation, dict)
                or validation.get("status") != "ok"
                or not isinstance(identity, dict)
                or identity.get("generation_strategy") != "model_create_plan_v2"
                or not isinstance(compiler_receipt_sha256, str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", compiler_receipt_sha256) is None
            ):
                raise BrainError(
                    "QUALIFICATION_PROOF_UNAVAILABLE",
                    409,
                    "typed CREATE qualification proof is unavailable",
                )
            proof = candidate.proof
            body = {
                "contract_id": TYPED_CREATE_QUALIFICATION_RECEIPT_CONTRACT,
                "turn_id": record.turn_id,
                "generation": candidate.generation,
                "source_sha256": source_sha256,
                "manifest_sha256": manifest_sha256,
                "spec_sha256": candidate.spec_sha256,
                "ir_sha256": candidate.ir_sha256,
                "parent_ir_sha256": proof.parent_ir_sha256,
                "delta_sha256": proof.delta_sha256,
                "delta_operation_count": proof.delta_operation_count,
                "history_revision": candidate.history_revision,
                "compiler_receipt_sha256": compiler_receipt_sha256,
                "generation_strategy": "model_create_plan_v2",
            }
            return {**body, "receipt_sha256": canonical_sha256(body)}

    def seal_typed_create_clarification_receipt(
        self,
        *,
        session_id: str,
        token: str,
        turn_id: str,
    ) -> dict[str, Any]:
        """Seal a redacted private gap roster for one completed CREATE Ask.

        The question wording, option references and authority keys are excluded.
        A post-close qualification oracle can therefore verify that the Ask
        addresses an expected structural gap without revealing an oracle to the
        running model or accepting an arbitrary clarification as success.
        """

        record = self._authenticate_record(
            session_id=session_id,
            token=token,
            turn_id=turn_id,
            capability="chat.read",
        )
        with record.condition, self._lock:
            if self._closed or self._turns.get(turn_id) is not record:
                raise BrainError("TURN_UNAVAILABLE", 404, "turn is unavailable")
            terminal = record.terminal
            clarification = terminal.get("clarification") if isinstance(terminal, dict) else None
            if (
                not isinstance(terminal, dict)
                or terminal.get("status") != "completed"
                or terminal.get("outcome") != "needs_clarification"
                or record.request.target.get("mode") != "create"
                or not isinstance(clarification, dict)
                or not isinstance(clarification.get("clarification_id"), str)
            ):
                raise BrainError(
                    "QUALIFICATION_PROOF_UNAVAILABLE",
                    409,
                    "typed CREATE clarification proof is unavailable",
                )
            clarification_id = clarification["clarification_id"]
            conversation_id = record.conversation_id

        # The issuing turn does not retain a second private copy of the pending
        # question: ClarificationStore is its single authority.  Resolve it
        # outside TurnStore's lock, then re-authenticate/recheck the turn below
        # so session revocation or concurrent erasure still fails closed.
        pending = self.clarifications.pending_v2(
            session_id=session_id,
            clarification_id=clarification_id,
        )
        self._authenticate_record(
            session_id=session_id,
            token=token,
            turn_id=turn_id,
            capability="chat.read",
        )
        with record.condition, self._lock:
            terminal = record.terminal
            clarification = terminal.get("clarification") if isinstance(terminal, dict) else None
            issued_by = self._turns.get(pending.parent_turn_id)
            if (
                self._closed
                or self._turns.get(turn_id) is not record
                or not isinstance(terminal, dict)
                or terminal.get("status") != "completed"
                or terminal.get("outcome") != "needs_clarification"
                or record.request.target.get("mode") != "create"
                or not isinstance(clarification, dict)
                or clarification.get("clarification_id") != pending.clarification_id
                or pending.session_id != record.session_id
                or pending.conversation_id != conversation_id
                or issued_by is None
                or issued_by.session_id != record.session_id
                or issued_by.conversation_id != conversation_id
                or pending.binding.parent_fingerprint != issued_by.request.request_fingerprint
                or (
                    record.dialogue_pending is not None
                    and record.dialogue_pending.clarification_id != pending.clarification_id
                )
            ):
                raise BrainError(
                    "QUALIFICATION_PROOF_UNAVAILABLE",
                    409,
                    "typed CREATE clarification proof is unavailable",
                )
            slots = [
                {
                    "decision_key": slot.decision_key,
                    "target_key": slot.target_key,
                    "kind": slot.kind,
                    "answer_kind": slot.answer_kind,
                    "value_contract": slot.value_contract,
                    "minimum": slot.minimum,
                    "maximum": slot.maximum,
                    "choice_count": len(slot.choices),
                }
                for slot in pending.slots
            ]
            body = {
                "contract_id": TYPED_CREATE_CLARIFICATION_RECEIPT_CONTRACT,
                "turn_id": record.turn_id,
                "round": pending.round_index,
                "slot_contracts": slots,
                "slot_contracts_sha256": canonical_sha256(slots),
                "binding_sha256": canonical_sha256(pending.binding.manifest()),
            }
            return {**body, "receipt_sha256": canonical_sha256(body)}

    def answer(
        self,
        *,
        session_id: str,
        token: str,
        parent_turn_id: str,
        answer: ClarificationAnswerRequest,
    ) -> TurnRecord:
        """Resume a pending request without making the client replay its original envelope."""

        parent = self._authenticate_record(
            session_id=session_id,
            token=token,
            turn_id=parent_turn_id,
            capability="chat.turn",
        )
        terminal = parent.public_status()
        clarification = terminal.get("clarification")
        if (
            terminal.get("status") != "completed"
            or terminal.get("outcome") != "needs_clarification"
            or not isinstance(clarification, dict)
        ):
            raise BrainError(
                "CLARIFICATION_UNAVAILABLE", 409, "parent turn has no pending clarification"
            )
        if clarification.get("clarification_id") != answer.clarification_id:
            raise BrainError(
                "CLARIFICATION_MISMATCH", 409, "clarification does not belong to parent turn"
            )
        original = parent.request
        if answer.schema_version == 2:
            envelope = DialogueAnswerEnvelope(
                answer.request_id,
                answer.clarification_id,
                answer.message,
                answer.answers,
            )
            request = TurnRequest(
                schema_version=2,
                request_id=answer.request_id,
                expected_context_revision=original.expected_context_revision,
                expected_semantic_source_revision=original.expected_semantic_source_revision,
                intent=original.intent,
                instruction=answer.message if answer.message is not None else original.instruction,
                target=deepcopy(original.target),
                basis=deepcopy(original.basis),
                clarification_response=envelope.payload(),
            )
            return self.submit(
                session_id=session_id,
                token=token,
                request=request,
                _private_basis_manifest=parent.basis_manifest,
                _private_basis_manifest_sha256=parent.basis_manifest_sha256,
                _private_dialogue_parent=parent,
            )
        request = TurnRequest(
            schema_version=2,
            request_id=answer.request_id,
            expected_context_revision=original.expected_context_revision,
            expected_semantic_source_revision=original.expected_semantic_source_revision,
            intent=original.intent,
            instruction=original.instruction,
            target=dict(original.target),
            basis=dict(original.basis) if original.basis is not None else None,
            clarification_response={
                "clarification_id": answer.clarification_id,
                "answer": dict(answer.answer),
                "context_revision": original.expected_context_revision,
                "semantic_source_revision": original.expected_semantic_source_revision,
            },
            server_flash_intent=(
                dict(original.server_flash_intent)
                if original.server_flash_intent is not None
                else None
            ),
        )
        return self.submit(
            session_id=session_id,
            token=token,
            request=request,
            _private_basis_manifest=parent.basis_manifest,
            _private_basis_manifest_sha256=parent.basis_manifest_sha256,
            _private_dialogue_parent=parent,
        )

    def cancel(self, *, session_id: str, token: str, turn_id: str) -> dict[str, Any]:
        record = self._authenticate_record(
            session_id=session_id, token=token, turn_id=turn_id, capability="chat.cancel"
        )
        with record.condition:
            if record.terminal is None:
                record.cancellation.set()
                self._clear_private_if_current(record)
                if record.status == "queued":
                    with self._lock:
                        self._admitted_work.pop(record.turn_id, None)
                        future = self._futures.get(record.turn_id)
                        if future is not None:
                            future.cancel()
                    self.clarifications.release_answer_claim(
                        session_id=record.session_id,
                        owner=record.turn_id,
                    )
                    record.status = "cancelled"
                    self._finish(record, self._cancelled_payload(record))
            return record.public_status()

    def events(
        self, *, session_id: str, token: str, turn_id: str, last_event_id: int = 0
    ) -> tuple[TurnRecord, list[dict[str, Any]]]:
        record = self._authenticate_record(
            session_id=session_id, token=token, turn_id=turn_id, capability="chat.read"
        )
        if last_event_id < 0:
            raise BrainError("INVALID_SCHEMA", 400, "Last-Event-ID is invalid")
        with record.condition:
            earliest = record.events[0]["data"]["sequence"] if record.events else 1
            if last_event_id and last_event_id + 1 < earliest:
                raise BrainError("REPLAY_GAP", 409, "event replay gap is no longer available")
            return record, [
                item for item in record.events if item["data"]["sequence"] > last_event_id
            ]

    def apply_preflight(
        self, *, session_id: str, token: str, turn_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        record = self._authenticate_record(
            session_id=session_id,
            token=token,
            turn_id=turn_id,
            capability="chat.apply-preflight",
        )
        exact_fields(body, required={"schema_version", "proposal_ref"}, label="apply preflight")
        if body["schema_version"] != 1 or not isinstance(body["proposal_ref"], str):
            raise BrainError("INVALID_SCHEMA", 400, "apply preflight is invalid")
        terminal = record.public_status()
        proposal = terminal.get("proposal")
        if not isinstance(proposal, dict) or proposal.get("proposal_ref") != body["proposal_ref"]:
            raise BrainError("PROPOSAL_STALE", 409, "proposal is unavailable")
        with self._manager.operation(
            session_id=session_id,
            token=token,
            capability="chat.apply-preflight",
            expected_revision=record.request.expected_context_revision,
        ) as lease:
            self._validate_target_snapshot(lease, record.request)
        now = datetime.now(UTC)
        if record.apply_ticket_expires_at is not None and now >= record.apply_ticket_expires_at:
            raise BrainError("APPLY_TICKET_EXPIRED", 409, "apply ticket has expired")
        if record.apply_ticket is None:
            ticket = "ticket-" + secrets.token_urlsafe(24)
            record.apply_ticket = ticket
            record.apply_ticket_expires_at = now + timedelta(minutes=5)
        else:
            ticket = record.apply_ticket
        result = {
            "schema_version": 1,
            "apply_ticket": ticket,
            "expires_at": record.apply_ticket_expires_at.isoformat().replace("+00:00", "Z"),
            "proposal_ref": proposal["proposal_ref"],
            "context_revision": record.request.expected_context_revision,
            "semantic_source_revision": terminal["identity"]["semantic_source_revision"],
            "base_sha256": proposal["base_sha256"],
            "source_sha256": proposal["source_sha256"],
        }
        return result

    def _authenticate_record(
        self, *, session_id: str, token: str, turn_id: str, capability: str
    ) -> TurnRecord:
        if not isinstance(turn_id, str) or _TURN_RE.fullmatch(turn_id) is None:
            raise BrainError("TURN_UNAVAILABLE", 404, "turn is unavailable")
        self._manager._authenticate(session_id=session_id, token=token, capability=capability)  # noqa: SLF001
        with self._lock:
            record = self._turns.get(turn_id)
            if record is None or record.session_id != session_id:
                raise BrainError("TURN_UNAVAILABLE", 404, "turn is unavailable")
            return record

    def _run(self, record: TurnRecord, token: str) -> None:
        with record.condition:
            if record.terminal is not None:
                return
            record.status = "running"
        staged_record = _OrchestratorTurnRecord(record)
        try:
            from metis_model1.brain_orchestrator import BrainOrchestrator

            request = record.request
            dialogue_terminal = None
            if request.dialogue_answer is not None:
                envelope = request.dialogue_answer
                pending = record.dialogue_pending
                state = record.dialogue_state
                if pending is None or state is None:
                    raise BrainError(
                        "CLARIFICATION_UNAVAILABLE", 409, "dialogue authority is unavailable"
                    )
                answers = envelope.answers
                if not answers and self._dialogue_answer_resolver is not None:
                    answers = answer_roster(
                        self._dialogue_answer_resolver(
                            request=request,
                            pending=replace(pending),
                            dialogue=replace(state),
                        ),
                        allow_empty=True,
                    )
                    if answers:
                        self.clarifications.validate_answers_v2(
                            session_id=record.session_id,
                            clarification_id=pending.clarification_id,
                            binding=pending.binding,
                            answers=answers,
                            claim_owner=record.turn_id,
                        )
                remaining = pending
                with self._lock:
                    if (
                        self._closed
                        or self._turns.get(record.turn_id) is not record
                        or record.cancellation.is_set()
                    ):
                        raise BrainError("SESSION_REVOKED", 409, "session was revoked")
                    # Consuming/rotating the binding and publishing its owner
                    # are one lifecycle transaction with cancel/drop/shutdown.
                    if answers:
                        resolution = self.clarifications.answer_v2(
                            session_id=record.session_id,
                            clarification_id=pending.clarification_id,
                            binding=pending.binding,
                            answers=answers,
                            claim_owner=record.turn_id,
                        )
                        state = replace(state, decisions=resolution.decisions)
                        remaining = resolution.remaining
                    record.dialogue_state = replace(state)
                    record.dialogue_pending = None if remaining is None else replace(remaining)
                    staged_record.dialogue_state = replace(state)
                    staged_record.dialogue_pending = (
                        None if remaining is None else replace(remaining)
                    )
                    request = replace(request, server_dialogue=replace(state))
                    record.request = request
                if remaining is not None:
                    dialogue_terminal = {
                        "schema_version": request.schema_version,
                        "turn_id": record.turn_id,
                        "request_id": request.request_id,
                        "status": "completed",
                        "outcome": "needs_clarification",
                        "route": "local",
                        "clarification": remaining.payload(),
                        "claims": {
                            "compile_clean": None,
                            "semantic_grounded": False,
                            "semantic_correctness": False,
                            "tenant_modified": False,
                        },
                    }
            elif request.clarification_response is not None:
                response = request.clarification_response
                resolution = self.clarifications.answer(
                    session_id=record.session_id,
                    clarification_id=response["clarification_id"],
                    request_fingerprint=request.request_fingerprint,
                    context_revision=response["context_revision"],
                    semantic_source_revision=response["semantic_source_revision"],
                    answer=request.clarification_answer or {},
                    claim_owner=record.turn_id,
                )
                record.clarification_decision = {
                    **resolution.decision.payload(),
                    "resolved_value": resolution.answer.resolved_value,
                }
            server_context = self.clarifications.server_context(
                session_id=record.session_id,
                request_fingerprint=record.conversation_id or request.request_fingerprint,
            )
            if server_context is not None and server_context["decisions"]:
                latest = server_context["decisions"][-1]
                current_decision = (
                    {"current_decision": dict(record.clarification_decision)}
                    if record.clarification_decision is not None
                    else {}
                )
                request = request.with_server_clarification(
                    {
                        **latest,
                        **server_context,
                        **current_decision,
                    }
                )
                record.request = request

            if dialogue_terminal is None:
                orchestrator = BrainOrchestrator(
                    retriever=self._retriever,
                    model=self._model,
                    compiler=self._compiler,
                    clarifications=self.clarifications,
                    intent_compiler=self._intent_compiler,
                    create_authority_provider=self._create_authority_provider,
                )
                result = orchestrator.run(
                    manager=self._manager,
                    session_id=record.session_id,
                    token=token,
                    request=request,
                    record=staged_record,
                )
            else:
                result = dialogue_terminal
            self._stage_candidate_source(staged_record, result)
            self._publish_private_attachments(record, staged_record, result=result)
            if record.cancellation.is_set():
                self._clear_private_if_current(record)
            with record.condition:
                if record.cancellation.is_set():
                    record.status = "cancelled"
                    self._discard_cancelled_pending(record)
                    result = self._cancelled_payload(record)
                else:
                    record.status = "completed"
                self._finish(record, result)
        except BrainError as error:
            self._clear_private_if_current(record)
            with record.condition:
                record.status = "cancelled" if record.cancellation.is_set() else "failed"
                self._discard_turn_pending(record)
                self._finish(record, self._error_payload(record, error))
        except Exception:
            self._clear_private_if_current(record)
            with record.condition:
                record.status = "cancelled" if record.cancellation.is_set() else "failed"
                self._discard_turn_pending(record)
                self._finish(
                    record,
                    self._error_payload(record, BrainError("INTERNAL_ERROR", 500, "turn failed")),
                )
        finally:
            try:
                if record.cancellation.is_set() and record.terminal is None:
                    # If cancellation raced with retrieval, the orchestrator may
                    # have created a question that never became visible in the
                    # terminal response.  Remove only that turn's pending state;
                    # accepted decisions from earlier rounds remain available.
                    self.clarifications.discard_pending_for_turn(
                        session_id=record.session_id,
                        parent_turn_id=record.turn_id,
                    )
            finally:
                try:
                    self.clarifications.release_answer_claim(
                        session_id=record.session_id,
                        owner=record.turn_id,
                    )
                finally:
                    try:
                        self.clarifications.release_revocation_guard(
                            record.session_id,
                            owner=record.turn_id,
                        )
                    finally:
                        staged_record.clear_private()

    def _discard_cancelled_pending(self, record: TurnRecord) -> None:
        if record.cancellation.is_set():
            self._discard_turn_pending(record)

    def _discard_turn_pending(self, record: TurnRecord) -> None:
        # A partial v2 answer rotates the ID while retaining the issue-time
        # parent binding. Its hidden successor still belongs to this turn.
        self._discard_rotated_dialogue_pending(record)
        self.clarifications.discard_pending_for_turn(
            session_id=record.session_id,
            parent_turn_id=record.turn_id,
        )

    def _finish(self, record: TurnRecord, payload: dict[str, Any]) -> None:
        with record.condition:
            if record.terminal is not None:
                return
            with self._lock:
                self._advance_head_locked(record, payload)
                if record.dialogue_state is not None:
                    if payload.get("outcome") == "proposed":
                        record.dialogue_state = replace(
                            record.dialogue_state,
                            latest_proposal_binding=canonical_sha256(payload.get("proposal")),
                        )
                        record.request = replace(
                            record.request, server_dialogue=replace(record.dialogue_state)
                        )
                    elif payload.get("outcome") != "needs_clarification":
                        record.dialogue_state = None
                        record.dialogue_pending = None
                        record.request = replace(
                            record.request,
                            server_dialogue=None,
                            instruction="",
                            clarification_response=None,
                        )
                record.terminal = payload
                record.emit("terminal", "terminal", "Turn terminato")
                self._active.discard(record.session_id)

    @staticmethod
    def _error_payload(record: TurnRecord, error: BrainError) -> dict[str, Any]:
        cancelled = record.cancellation.is_set() or error.code == "SESSION_REVOKED"
        return {
            "schema_version": record.request.schema_version,
            "turn_id": record.turn_id,
            "request_id": record.request.request_id,
            "status": "cancelled" if cancelled else "failed",
            "route": "local",
            "error": {
                "code": "TURN_CANCELLED" if cancelled else error.code,
                "message": "turn was cancelled" if cancelled else error.message,
            },
        }

    @staticmethod
    def _cancelled_payload(record: TurnRecord) -> dict[str, Any]:
        return {
            "schema_version": record.request.schema_version,
            "turn_id": record.turn_id,
            "request_id": record.request.request_id,
            "status": "cancelled",
            "route": "local",
            "error": {"code": "TURN_CANCELLED", "message": "turn was cancelled"},
        }

    def shutdown(self) -> None:
        with self._lock:
            self._closed = True
            self._proposal_heads.clear()
            for record in self._turns.values():
                record.clear_private()
                if record.terminal is None:
                    record.cancellation.set()
            self._admitted_work.clear()
            for future in tuple(self._futures.values()):
                future.cancel()
        self._executor.shutdown(wait=True, cancel_futures=True)
        with self._lock:
            for record in self._turns.values():
                record.clear_private()
            self._turns.clear()
            self._idempotency.clear()
            self._proposal_heads.clear()
            self._active.clear()
            self._futures.clear()
            self._admitted_work.clear()
        self.clarifications.clear()
