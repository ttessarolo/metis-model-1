"""Asynchronous Brain turn protocol, idempotency and bounded event journal."""

from __future__ import annotations

import re
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

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
_PATH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,255}\.metis$")
_INTENTS = frozenset({"create", "edit", "repair", "review", "migrate"})
_EVENTS = frozenset(
    {
        "turn.accepted",
        "retrieval.started",
        "retrieval.completed",
        "catalog.auto_selected",
        "catalog.clarification_required",
        "inference.started",
        "inference.completed",
        "compile.started",
        "compile.completed",
        "repair.started",
        "repair.completed",
        "terminal",
    }
)


def validate_target(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BrainError("INVALID_SCHEMA", 400, "target must be an object")
    exact_fields(
        value,
        required={"mode", "relative_path", "endpoint", "base_sha256"},
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
    base = value["base_sha256"]
    if base is not None and (
        not isinstance(base, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", base)
    ):
        raise BrainError("INVALID_SCHEMA", 400, "target base hash is invalid")
    if mode == "create" and base is not None:
        raise BrainError("INVALID_SCHEMA", 400, "create target requires a null base hash")
    if mode == "existing" and base is None:
        raise BrainError("INVALID_SCHEMA", 400, "existing target requires a base hash")
    return {"mode": mode, "relative_path": path, "endpoint": endpoint, "base_sha256": base}


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
    clarification_response: dict[str, str] | None

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
        if value["schema_version"] != 1:
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
            exact_fields(
                clarification,
                required={
                    "clarification_id",
                    "option_ref",
                    "context_revision",
                    "semantic_source_revision",
                },
                label="clarification response",
            )
            if not _REF_RE.fullmatch(str(clarification["clarification_id"])):
                raise BrainError("INVALID_SCHEMA", 400, "clarification response is invalid")
            if not _REF_RE.fullmatch(str(clarification["option_ref"])):
                raise BrainError("INVALID_SCHEMA", 400, "clarification response is invalid")
            revision(clarification["context_revision"], label="clarification context revision")
            revision(
                clarification["semantic_source_revision"],
                label="clarification semantic revision",
            )
            clarification = {
                "clarification_id": clarification["clarification_id"],
                "option_ref": clarification["option_ref"],
                "context_revision": clarification["context_revision"],
                "semantic_source_revision": clarification["semantic_source_revision"],
            }
        return cls(
            schema_version=1,
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


@dataclass
class TurnRecord:
    turn_id: str
    session_id: str
    request: TurnRequest
    payload_hash: str
    status: str = "queued"
    outcome: str | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    terminal: dict[str, Any] | None = None
    cancellation: threading.Event = field(default_factory=threading.Event)
    condition: threading.Condition = field(default_factory=threading.Condition)
    apply_ticket: str | None = None
    apply_ticket_expires_at: datetime | None = None

    def emit(self, event: str, phase: str, label: str, **metrics: int | str | bool) -> None:
        if event not in _EVENTS:
            raise ValueError("event is not public")
        safe_metrics = {
            key: value
            for key, value in metrics.items()
            if key in {"attempt", "count", "bytes", "duration_ms", "replayed"}
            and isinstance(value, (int, str, bool))
        }
        with self.condition:
            event_value = {
                "event": event,
                "data": {
                    "schema_version": 1,
                    "turn_id": self.turn_id,
                    "sequence": len(self.events) + 1,
                    "phase": phase,
                    "label": label,
                    **safe_metrics,
                },
            }
            self.events.append(event_value)
            if len(self.events) > 256:
                del self.events[0]
            self.condition.notify_all()

    def public_status(self) -> dict[str, Any]:
        with self.condition:
            if self.terminal is not None:
                return dict(self.terminal)
            return {
                "schema_version": 1,
                "turn_id": self.turn_id,
                "request_id": self.request.request_id,
                "status": self.status,
            }


class TurnStore:
    """Bounded async turn scheduler shared by the HTTP server and clients."""

    def __init__(
        self,
        *,
        manager: SessionManager,
        retriever: BrainRetriever,
        model: BrainModelRuntime,
        compiler: Any,
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
        self._max_queue = max_queue
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="brain-turn"
        )
        self._lock = threading.RLock()
        self._turns: dict[str, TurnRecord] = {}
        self._idempotency: dict[tuple[str, str], tuple[str, str]] = {}
        self._active: set[str] = set()
        self._closed = False

    @staticmethod
    def _new_id(existing: dict[str, TurnRecord]) -> str:
        while True:
            value = secrets.token_urlsafe(24)
            if value not in existing:
                return value

    def submit(self, *, session_id: str, token: str, request: TurnRequest) -> TurnRecord:
        # Authenticate before the idempotency lookup. A retry must return its
        # terminal record even if the tenant has changed since the first turn.
        self._manager._authenticate(  # noqa: SLF001
            session_id=session_id, token=token, capability="chat.turn"
        )
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
        with self._lock:
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
                raise BrainError("TURN_ACTIVE", 409, "one turn is already active for this session")
            record = TurnRecord(
                turn_id=self._new_id(self._turns),
                session_id=session_id,
                request=request,
                payload_hash=request.payload_hash,
            )
            self._turns[record.turn_id] = record
            self._idempotency[key] = (request.payload_hash, record.turn_id)
            self._active.add(session_id)
            record.emit("turn.accepted", "accepted", "Turn accettato")
            try:
                self._executor.submit(self._run, record, token)
            except RuntimeError as error:
                self._active.discard(session_id)
                self._turns.pop(record.turn_id, None)
                self._idempotency.pop(key, None)
                raise BrainError(
                    "SERVICE_UNAVAILABLE", 503, "turn service is unavailable"
                ) from error
            return record

    def _validate_basis_locked(self, *, session_id: str, request: TurnRequest) -> None:
        if request.basis is None:
            return
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
            return
        raise BrainError("PROPOSAL_STALE", 409, "proposal is unavailable")

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

    def cancel(self, *, session_id: str, token: str, turn_id: str) -> dict[str, Any]:
        record = self._authenticate_record(
            session_id=session_id, token=token, turn_id=turn_id, capability="chat.cancel"
        )
        with record.condition:
            if record.terminal is None:
                record.cancellation.set()
                if record.status == "queued":
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
        try:
            from metis_model1.brain_orchestrator import BrainOrchestrator

            orchestrator = BrainOrchestrator(
                retriever=self._retriever,
                model=self._model,
                compiler=self._compiler,
            )
            result = orchestrator.run(
                manager=self._manager,
                session_id=record.session_id,
                token=token,
                request=record.request,
                record=record,
            )
            with record.condition:
                if record.cancellation.is_set():
                    record.status = "cancelled"
                    result = self._cancelled_payload(record)
                else:
                    record.status = "completed"
                self._finish(record, result)
        except BrainError as error:
            with record.condition:
                record.status = "cancelled" if record.cancellation.is_set() else "failed"
                self._finish(record, self._error_payload(record, error))
        except Exception:
            with record.condition:
                record.status = "failed"
                self._finish(
                    record,
                    self._error_payload(record, BrainError("INTERNAL_ERROR", 500, "turn failed")),
                )

    def _finish(self, record: TurnRecord, payload: dict[str, Any]) -> None:
        if record.terminal is not None:
            return
        record.terminal = payload
        record.emit("terminal", "terminal", "Turn terminato")
        with self._lock:
            self._active.discard(record.session_id)
        record.condition.notify_all()

    @staticmethod
    def _error_payload(record: TurnRecord, error: BrainError) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "turn_id": record.turn_id,
            "request_id": record.request.request_id,
            "status": "cancelled" if error.code == "SESSION_REVOKED" else "failed",
            "route": "local",
            "error": {"code": error.code, "message": error.message},
        }

    @staticmethod
    def _cancelled_payload(record: TurnRecord) -> dict[str, Any]:
        return {
            "schema_version": 1,
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
                if record.terminal is None:
                    record.cancellation.set()
        self._executor.shutdown(wait=True, cancel_futures=False)
