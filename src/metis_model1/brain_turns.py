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
from metis_model1.brain_model_runtime import BrainModelRuntime
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
    instruction: str
    target: dict[str, Any]
    basis: dict[str, str] | None
    clarification_response: dict[str, Any] | None
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

    def with_server_clarification(self, value: dict[str, Any]) -> TurnRequest:
        return replace(self, server_clarification=dict(value))

    def with_server_basis_grounding(self, value: dict[str, Any]) -> TurnRequest:
        return replace(self, server_basis_grounding=dict(value))

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
    answer: dict[str, Any]

    @classmethod
    def parse(cls, value: dict[str, Any]) -> ClarificationAnswerRequest:
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
    request: TurnRequest
    payload_hash: str
    conversation_id: str | None = None
    basis_source: str | None = None
    basis_grounding: dict[str, Any] | None = None
    basis_manifest: dict[str, Any] | None = field(default=None, repr=False)
    basis_manifest_sha256: str | None = field(default=None, repr=False)
    candidate_manifest: dict[str, Any] | None = field(default=None, repr=False)
    candidate_manifest_sha256: str | None = field(default=None, repr=False)
    clarification_decision: dict[str, Any] | None = None
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
        self.basis_grounding = None
        self.basis_manifest = None
        self.basis_manifest_sha256 = None
        self.candidate_manifest = None
        self.candidate_manifest_sha256 = None
        self.clarification_decision = None

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
                return dict(self.terminal)
            return {
                "schema_version": self.request.schema_version,
                "turn_id": self.turn_id,
                "request_id": self.request.request_id,
                "status": self.status,
            }


class _OrchestratorTurnRecord:
    """Stage orchestrator-owned manifest writes away from the live store.

    The orchestrator intentionally receives a record-like object because it
    emits progress and observes cancellation throughout a turn.  Its two
    private manifest pairs, however, must not be written to the live record
    until the session lifecycle is rechecked atomically by ``TurnStore``.
    """

    __slots__ = (
        "_record",
        "basis_manifest",
        "basis_manifest_sha256",
        "candidate_manifest",
        "candidate_manifest_sha256",
    )

    _PRIVATE_NAMES = frozenset(__slots__[1:])

    def __init__(self, record: TurnRecord) -> None:
        object.__setattr__(self, "_record", record)
        object.__setattr__(self, "basis_manifest", deepcopy(record.basis_manifest))
        object.__setattr__(self, "basis_manifest_sha256", record.basis_manifest_sha256)
        object.__setattr__(self, "candidate_manifest", deepcopy(record.candidate_manifest))
        object.__setattr__(self, "candidate_manifest_sha256", record.candidate_manifest_sha256)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._record, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self._PRIVATE_NAMES:
            object.__setattr__(self, name, value)
            return
        setattr(self._record, name, value)

    def clear_private(self) -> None:
        self.basis_manifest = None
        self.basis_manifest_sha256 = None
        self.candidate_manifest = None
        self.candidate_manifest_sha256 = None


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
        self._max_queue = max_queue
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="brain-turn"
        )
        self._lock = threading.RLock()
        self._turns: dict[str, TurnRecord] = {}
        self._idempotency: dict[tuple[str, str], tuple[str, str]] = {}
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

    def _publish_private_attachments(
        self,
        record: TurnRecord,
        staged: _OrchestratorTurnRecord,
    ) -> bool:
        """Publish staged manifests only to the exact still-live turn record."""

        with self._lock:
            if (
                self._closed
                or self._turns.get(record.turn_id) is not record
                or record.cancellation.is_set()
                or record.terminal is not None
            ):
                record.clear_private()
                return False
            basis_manifest, basis_manifest_sha256 = self._private_manifest_copy(
                staged.basis_manifest,
                staged.basis_manifest_sha256,
            )
            candidate_manifest, candidate_manifest_sha256 = self._private_manifest_copy(
                staged.candidate_manifest,
                staged.candidate_manifest_sha256,
            )
            record.basis_manifest = basis_manifest
            record.basis_manifest_sha256 = basis_manifest_sha256
            record.candidate_manifest = candidate_manifest
            record.candidate_manifest_sha256 = candidate_manifest_sha256
            return True

    def _clear_private_if_current(self, record: TurnRecord) -> None:
        with self._lock:
            if self._turns.get(record.turn_id) is record:
                record.clear_private()

    def submit(
        self,
        *,
        session_id: str,
        token: str,
        request: TurnRequest,
        _private_basis_manifest: dict[str, Any] | None = None,
        _private_basis_manifest_sha256: str | None = None,
    ) -> TurnRecord:
        # Authenticate before the idempotency lookup. A retry must return its
        # terminal record even if the tenant has changed since the first turn.
        self._manager._authenticate(  # noqa: SLF001
            session_id=session_id, token=token, capability="chat.turn"
        )
        self.clarifications.touch_session(session_id)
        with self._lock:
            self._validate_basis_locked(session_id=session_id, request=request)
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
                turn_id = self._new_id(self._turns)
                proposal = basis_record.terminal.get("proposal") if basis_record else None
                basis_source = proposal.get("source") if isinstance(proposal, dict) else None
                basis_grounding = (
                    basis_record.terminal.get("grounding")
                    if basis_record and isinstance(basis_record.terminal, dict)
                    else None
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
                if basis_manifest is not None and (
                    not isinstance(basis_manifest_sha256, str)
                    or canonical_sha256(basis_manifest) != basis_manifest_sha256
                ):
                    raise BrainError(
                        "PROPOSAL_STALE", 409, "proposal structural authority is stale"
                    )
                if isinstance(basis_grounding, dict):
                    request = request.with_server_basis_grounding(basis_grounding)
                record = TurnRecord(
                    turn_id=turn_id,
                    session_id=session_id,
                    request=request,
                    payload_hash=request.payload_hash,
                    conversation_id=(
                        basis_record.conversation_id
                        if basis_record and basis_record.conversation_id
                        else request.request_fingerprint
                    ),
                    basis_source=basis_source if isinstance(basis_source, str) else None,
                    basis_grounding=(
                        dict(basis_grounding) if isinstance(basis_grounding, dict) else None
                    ),
                    basis_manifest=(
                        deepcopy(basis_manifest) if isinstance(basis_manifest, dict) else None
                    ),
                    basis_manifest_sha256=basis_manifest_sha256,
                )
                if lease.cancellation.is_set():
                    raise BrainError("SESSION_REVOKED", 409, "session was revoked")
                if request.clarification_response is not None:
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
            terminal = record.terminal
            if not isinstance(terminal, dict):
                continue
            proposal = terminal.get("proposal")
            if not isinstance(proposal, dict) or proposal.get("proposal_ref") != wanted:
                continue
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
            if isinstance(request.target.get("endpoint"), str) and (
                record.candidate_manifest is None
                or not isinstance(record.candidate_manifest_sha256, str)
                or canonical_sha256(record.candidate_manifest) != record.candidate_manifest_sha256
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
            if request.clarification_response is not None:
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

            orchestrator = BrainOrchestrator(
                retriever=self._retriever,
                model=self._model,
                compiler=self._compiler,
                clarifications=self.clarifications,
                intent_compiler=self._intent_compiler,
            )
            result = orchestrator.run(
                manager=self._manager,
                session_id=record.session_id,
                token=token,
                request=request,
                record=staged_record,
            )
            self._publish_private_attachments(record, staged_record)
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
        self.clarifications.discard_pending_for_turn(
            session_id=record.session_id,
            parent_turn_id=record.turn_id,
        )

    def _finish(self, record: TurnRecord, payload: dict[str, Any]) -> None:
        with record.condition:
            if record.terminal is not None:
                return
            record.terminal = payload
            record.emit("terminal", "terminal", "Turn terminato")
        with self._lock:
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
            self._active.clear()
            self._futures.clear()
            self._admitted_work.clear()
        self.clarifications.clear()
