"""Tenant-scoped Metis Brain sessions with monotonic TTL and atomic revocation."""

from __future__ import annotations

import hmac
import os
import secrets
import stat
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from metis_model1.brain_context import ContextSnapshot, TenantRegistry
from metis_model1.brain_protocol import CAPABILITIES, IDLE_TTL_SECONDS, BrainError


@dataclass(frozen=True)
class ClientPolicy:
    client_id: str
    tenant_aliases: frozenset[str]
    capabilities: frozenset[str]

    def __post_init__(self) -> None:
        if (
            not self.client_id
            or not self.tenant_aliases
            or not self.capabilities
            or not self.capabilities.issubset(CAPABILITIES)
        ):
            raise BrainError("INVALID_CONFIG", 500, "client policy is invalid")


@dataclass(frozen=True)
class SessionLimits:
    global_sessions: int = 32
    sessions_per_client: int = 8
    sessions_per_tenant: int = 8

    def __post_init__(self) -> None:
        values = (self.global_sessions, self.sessions_per_client, self.sessions_per_tenant)
        if any(type(value) is not int or value < 1 or value > 1024 for value in values):
            raise BrainError("INVALID_CONFIG", 500, "session limits are invalid")


@dataclass(frozen=True)
class SessionOpened:
    session_id: str
    token: str
    client_id: str
    tenant_alias: str
    capabilities: tuple[str, ...]
    context_revision: str
    idle_ttl_seconds: int

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "session": {
                "id": self.session_id,
                "token": self.token,
                "client_id": self.client_id,
                "tenant_alias": self.tenant_alias,
                "capabilities": list(self.capabilities),
                "context_revision": self.context_revision,
                "idle_ttl_seconds": self.idle_ttl_seconds,
                "state": "active",
            },
        }


@dataclass(frozen=True)
class OperationLease:
    session_id: str
    client_id: str
    tenant_alias: str
    capabilities: frozenset[str]
    snapshot: ContextSnapshot
    cancellation: threading.Event


@dataclass
class _Session:
    session_id: str
    token_digest: bytes
    client_id: str
    tenant_alias: str
    capabilities: frozenset[str]
    snapshot: ContextSnapshot | None
    overlay: Path
    created_at: float
    last_activity: float
    state: str = "ACTIVE"
    in_flight: int = 0
    cancellation: threading.Event = field(default_factory=threading.Event)
    cleanup_started: bool = False
    listener_lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    listeners_completed: set[int] = field(default_factory=set, repr=False)
    listeners_in_progress: set[int] = field(default_factory=set, repr=False)


class SessionManager:
    """Pure session core shared by HTTP and future native transports."""

    def __init__(
        self,
        *,
        registry: TenantRegistry,
        policies: list[ClientPolicy],
        runtime_root: Path,
        toolchain_binding: str,
        limits: SessionLimits | None = None,
        idle_ttl_seconds: float = IDLE_TTL_SECONDS,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if idle_ttl_seconds != IDLE_TTL_SECONDS:
            raise BrainError("INVALID_CONFIG", 500, "session idle TTL must be exactly 1200 seconds")
        policy_map = {item.client_id: item for item in policies}
        if not policies or len(policy_map) != len(policies):
            raise BrainError(
                "INVALID_CONFIG", 500, "client policies must be non-empty and distinct"
            )
        for policy in policies:
            if not policy.tenant_aliases.issubset(registry.aliases):
                raise BrainError(
                    "INVALID_CONFIG", 500, "client policy references an unknown tenant"
                )

        root = Path(runtime_root)
        if not root.is_absolute():
            raise BrainError("INVALID_CONFIG", 500, "runtime root must be absolute")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        resolved_root = root.resolve(strict=True)
        if resolved_root != root:
            raise BrainError("INVALID_CONFIG", 500, "runtime root must be canonical")
        root = resolved_root
        root_stat = root.lstat()
        if root.is_symlink() or not stat.S_ISDIR(root_stat.st_mode):
            raise BrainError("INVALID_CONFIG", 500, "runtime root must be a real directory")
        os.chmod(root, 0o700)

        self._registry = registry
        self._policies = policy_map
        self._runtime_root = root
        self._toolchain_binding = toolchain_binding
        self._limits = limits or SessionLimits()
        self._idle_ttl = float(idle_ttl_seconds)
        self._monotonic = monotonic
        self._digest_key = secrets.token_bytes(32)
        self._sessions: dict[str, _Session] = {}
        self._pending_total = 0
        self._pending_by_client: dict[str, int] = {}
        self._pending_by_tenant: dict[str, int] = {}
        self._lock = threading.RLock()
        self._shutdown = False
        self._cleanup_failures = 0
        self._cleanup_listeners: list[Callable[[str], None]] = []

    @property
    def idle_ttl_seconds(self) -> int:
        return int(self._idle_ttl)

    @property
    def runtime_root(self) -> Path:
        return self._runtime_root

    def register_cleanup_listener(self, listener: Callable[[str], None]) -> None:
        """Register an in-process observer for volatile session-state cleanup.

        Listeners never receive tokens, paths or snapshots.  They are used by
        the turn service to drop its RAM-only conversation state at the same
        lifecycle boundary as the tenant session.
        """

        if not callable(listener):
            raise BrainError("INVALID_CONFIG", 500, "session cleanup listener is invalid")
        with self._lock:
            if self._shutdown:
                raise BrainError("SERVICE_UNAVAILABLE", 503, "service is shutting down")
            self._cleanup_listeners.append(listener)

    def _token_digest(self, token: str) -> bytes:
        return hmac.digest(self._digest_key, token.encode("ascii", "strict"), "sha256")

    def _new_identity(self) -> tuple[str, str]:
        while True:
            session_id = secrets.token_urlsafe(32)
            if session_id not in self._sessions:
                return session_id, secrets.token_urlsafe(32)

    def _active_counts(self, *, client_id: str, tenant_alias: str) -> tuple[int, int, int]:
        active = [item for item in self._sessions.values() if item.state != "CLOSED"]
        return (
            len(active),
            sum(item.client_id == client_id for item in active),
            sum(item.tenant_alias == tenant_alias for item in active),
        )

    def _check_capacity(self, *, client_id: str, tenant_alias: str) -> None:
        total, per_client, per_tenant = self._active_counts(
            client_id=client_id, tenant_alias=tenant_alias
        )
        if (
            total + self._pending_total >= self._limits.global_sessions
            or per_client + self._pending_by_client.get(client_id, 0)
            >= self._limits.sessions_per_client
            or per_tenant + self._pending_by_tenant.get(tenant_alias, 0)
            >= self._limits.sessions_per_tenant
        ):
            raise BrainError("SESSION_LIMIT", 429, "session capacity is exhausted")

    def _reserve_capture_locked(self, *, client_id: str, tenant_alias: str) -> None:
        self._check_capacity(client_id=client_id, tenant_alias=tenant_alias)
        self._pending_total += 1
        self._pending_by_client[client_id] = self._pending_by_client.get(client_id, 0) + 1
        self._pending_by_tenant[tenant_alias] = self._pending_by_tenant.get(tenant_alias, 0) + 1

    def _release_capture_locked(self, *, client_id: str, tenant_alias: str) -> None:
        self._pending_total -= 1
        for roster, key in (
            (self._pending_by_client, client_id),
            (self._pending_by_tenant, tenant_alias),
        ):
            roster[key] -= 1
            if roster[key] == 0:
                del roster[key]
        if self._pending_total < 0:
            raise AssertionError("negative pending session capture count")

    def create_session(
        self,
        *,
        client_id: str,
        tenant_alias: str,
        requested_capabilities: frozenset[str],
    ) -> SessionOpened:
        try:
            policy = self._policies[client_id]
        except KeyError as error:
            raise BrainError("CLIENT_NOT_AUTHORIZED", 403, "client is not authorized") from error
        if tenant_alias not in policy.tenant_aliases:
            raise BrainError("TENANT_NOT_AUTHORIZED", 403, "tenant is not authorized")
        if not requested_capabilities or not requested_capabilities.issubset(policy.capabilities):
            raise BrainError("CAPABILITY_DENIED", 403, "requested capability is not authorized")

        with self._lock:
            if self._shutdown:
                raise BrainError("SERVICE_UNAVAILABLE", 503, "service is shutting down")
            self._reserve_capture_locked(client_id=client_id, tenant_alias=tenant_alias)
        try:
            snapshot = self._registry.capture(
                tenant_alias,
                toolchain_binding=self._toolchain_binding,
            )
        except BaseException:
            with self._lock:
                self._release_capture_locked(client_id=client_id, tenant_alias=tenant_alias)
            raise

        with self._lock:
            self._release_capture_locked(client_id=client_id, tenant_alias=tenant_alias)
            if self._shutdown:
                raise BrainError("SERVICE_UNAVAILABLE", 503, "service is shutting down")
            session_id, token = self._new_identity()
            overlay = self._runtime_root / f"session-{session_id}"
            overlay.mkdir(mode=0o700)
            now = self._monotonic()
            self._sessions[session_id] = _Session(
                session_id=session_id,
                token_digest=self._token_digest(token),
                client_id=client_id,
                tenant_alias=tenant_alias,
                capabilities=requested_capabilities,
                snapshot=snapshot,
                overlay=overlay,
                created_at=now,
                last_activity=now,
            )
        return SessionOpened(
            session_id=session_id,
            token=token,
            client_id=client_id,
            tenant_alias=tenant_alias,
            capabilities=tuple(sorted(requested_capabilities)),
            context_revision=snapshot.revision,
            idle_ttl_seconds=int(self._idle_ttl),
        )

    def _schedule_cleanup_locked(self, session: _Session) -> _Session | None:
        if session.in_flight != 0 or session.cleanup_started:
            return None
        session.cleanup_started = True
        return session

    def _mark_expired_locked(self, session: _Session, now: float) -> _Session | None:
        if (
            session.state == "ACTIVE"
            and session.in_flight == 0
            and now - session.last_activity >= self._idle_ttl
        ):
            session.state = "EXPIRED"
            session.token_digest = b""
            session.cancellation.set()
            return self._schedule_cleanup_locked(session)
        return None

    def _authenticate_locked(
        self,
        *,
        session_id: str,
        token: str,
        capability: str,
        expected_revision: str | None = None,
    ) -> tuple[_Session, _Session | None]:
        session = self._sessions.get(session_id)
        if session is None:
            raise BrainError("SESSION_UNAVAILABLE", 401, "session is unavailable")
        cleanup = self._mark_expired_locked(session, self._monotonic())
        if session.state != "ACTIVE" or not session.token_digest:
            return session, cleanup
        try:
            actual = self._token_digest(token)
        except UnicodeEncodeError as error:
            raise BrainError("SESSION_UNAVAILABLE", 401, "session is unavailable") from error
        if not hmac.compare_digest(actual, session.token_digest):
            raise BrainError("SESSION_UNAVAILABLE", 401, "session is unavailable")
        if capability not in session.capabilities:
            raise BrainError("CAPABILITY_DENIED", 403, "capability is not authorized")
        snapshot = session.snapshot
        if snapshot is None:
            raise BrainError("SESSION_UNAVAILABLE", 401, "session is unavailable")
        if expected_revision is not None and expected_revision != snapshot.revision:
            raise BrainError("STALE_CONTEXT", 409, "expected context revision differs")
        return session, cleanup

    def _authenticate(
        self,
        *,
        session_id: str,
        token: str,
        capability: str,
        expected_revision: str | None = None,
    ) -> _Session:
        cleanup: _Session | None = None
        unavailable = False
        with self._lock:
            session, cleanup = self._authenticate_locked(
                session_id=session_id,
                token=token,
                capability=capability,
                expected_revision=expected_revision,
            )
            unavailable = session.state != "ACTIVE"
        if cleanup is not None:
            self._cleanup(cleanup)
        if unavailable:
            raise BrainError("SESSION_UNAVAILABLE", 401, "session is unavailable")
        return session

    def status(self, *, session_id: str, token: str) -> dict[str, Any]:
        session = self._authenticate(
            session_id=session_id,
            token=token,
            capability="session.read",
        )
        with self._lock:
            snapshot = session.snapshot
            if snapshot is None or session.state != "ACTIVE":
                raise BrainError("SESSION_UNAVAILABLE", 401, "session is unavailable")
            remaining = max(
                0.0,
                self._idle_ttl - (self._monotonic() - session.last_activity),
            )
            return {
                "schema_version": 1,
                "session": {
                    "id": session.session_id,
                    "client_id": session.client_id,
                    "tenant_alias": session.tenant_alias,
                    "capabilities": sorted(session.capabilities),
                    "context_revision": snapshot.revision,
                    "state": "active",
                    "in_flight": session.in_flight,
                    "idle_ttl_seconds": int(self._idle_ttl),
                    "expires_in_seconds": round(remaining, 3),
                },
            }

    def session_options(self, *, client_id: str) -> dict[str, Any]:
        """Return only bootstrap-authorized client grants, never roots or paths."""
        try:
            policy = self._policies[client_id]
        except KeyError as error:
            raise BrainError("CLIENT_NOT_AUTHORIZED", 403, "client is not authorized") from error
        return {
            "schema_version": 1,
            "client_id": policy.client_id,
            "tenant_aliases": sorted(policy.tenant_aliases),
            "capabilities": sorted(policy.capabilities),
        }

    @contextmanager
    def operation(
        self,
        *,
        session_id: str,
        token: str,
        capability: str,
        expected_revision: str,
    ) -> Iterator[OperationLease]:
        first = self._authenticate(
            session_id=session_id,
            token=token,
            capability=capability,
            expected_revision=expected_revision,
        )
        first_snapshot = first.snapshot
        if first_snapshot is None:
            raise BrainError("SESSION_UNAVAILABLE", 401, "session is unavailable")
        try:
            self._registry.assert_current(first_snapshot)
        except BrainError as error:
            self._revoke_stale(first, release_operation=False)
            raise BrainError("STALE_CONTEXT", 409, "tenant context changed") from error

        cleanup: _Session | None = None
        with self._lock:
            session, cleanup = self._authenticate_locked(
                session_id=session_id,
                token=token,
                capability=capability,
                expected_revision=expected_revision,
            )
            if session is not first or session.snapshot is not first_snapshot:
                raise BrainError("SESSION_UNAVAILABLE", 401, "session is unavailable")
            if session.state != "ACTIVE":
                unavailable = True
            else:
                unavailable = False
                session.in_flight += 1
                lease = OperationLease(
                    session_id=session.session_id,
                    client_id=session.client_id,
                    tenant_alias=session.tenant_alias,
                    capabilities=session.capabilities,
                    snapshot=first_snapshot,
                    cancellation=session.cancellation,
                )
        if cleanup is not None:
            self._cleanup(cleanup)
        if unavailable:
            raise BrainError("SESSION_UNAVAILABLE", 401, "session is unavailable")

        try:
            self._registry.assert_current(first_snapshot)
        except BrainError as error:
            self._revoke_stale(session, release_operation=True)
            raise BrainError("STALE_CONTEXT", 409, "tenant context changed") from error

        with self._lock:
            if session.state != "ACTIVE" or session.cancellation.is_set():
                session.in_flight -= 1
                cleanup = self._schedule_cleanup_locked(session)
                activated = False
            else:
                session.last_activity = self._monotonic()
                cleanup = None
                activated = True
        if cleanup is not None:
            self._cleanup(cleanup)
        if not activated:
            raise BrainError("SESSION_REVOKED", 409, "session was revoked")

        completed = False
        post_error: BrainError | None = None
        try:
            yield lease
            completed = True
            try:
                self._registry.assert_current(first_snapshot)
            except BrainError:
                with self._lock:
                    if session.state == "ACTIVE":
                        session.state = "STALE"
                        session.token_digest = b""
                        session.cancellation.set()
                self._notify_cleanup_listeners(session)
                post_error = BrainError("STALE_CONTEXT", 409, "tenant context changed")
        finally:
            cleanup = None
            revoked = False
            with self._lock:
                session.in_flight -= 1
                if session.in_flight < 0:
                    raise AssertionError("negative session operation count")
                if session.state != "ACTIVE" or session.cancellation.is_set():
                    revoked = True
                    cleanup = self._schedule_cleanup_locked(session)
                else:
                    # An admitted operation is activity for its entire
                    # lifetime. Start the idle window when that activity
                    # finishes; never expire a session merely because one
                    # bounded model/compile turn lasted longer than the TTL.
                    session.last_activity = self._monotonic()
            if cleanup is not None:
                self._cleanup(cleanup)
            if completed and revoked and post_error is None:
                post_error = BrainError("SESSION_REVOKED", 409, "session was revoked")
            if completed and post_error is not None:
                raise post_error

    def close(self, *, session_id: str, token: str) -> dict[str, Any]:
        session = self._authenticate(
            session_id=session_id,
            token=token,
            capability="session.close",
        )
        with self._lock:
            if session.state != "ACTIVE":
                raise BrainError("SESSION_UNAVAILABLE", 401, "session is unavailable")
            session.state = "CLOSING"
            session.token_digest = b""
            session.cancellation.set()
            cleanup = self._schedule_cleanup_locked(session)
            response = {
                "schema_version": 1,
                "session": {
                    "id": session.session_id,
                    "state": "closed" if cleanup is not None else "closing",
                },
            }
        self._notify_cleanup_listeners(session)
        if cleanup is not None:
            self._cleanup(cleanup)
        return response

    def sweep_expired(self) -> int:
        pending: list[_Session] = []
        with self._lock:
            now = self._monotonic()
            for session in list(self._sessions.values()):
                cleanup = (
                    self._mark_expired_locked(session, now)
                    if session.state == "ACTIVE"
                    else self._schedule_cleanup_locked(session)
                )
                if cleanup is not None:
                    pending.append(cleanup)
        completed = 0
        for session in pending:
            try:
                self._cleanup(session)
                completed += 1
            except BrainError:
                with self._lock:
                    self._cleanup_failures += 1
        return completed

    def _cleanup(self, session: _Session) -> None:
        # Volatile conversation state follows logical revocation, not the
        # success of best-effort filesystem removal.  A stuck overlay must
        # never retain prompts, proposals or clarification decisions in RAM.
        if not self._notify_cleanup_listeners(session):
            with self._lock:
                session.cleanup_started = False
            raise BrainError(
                "CLEANUP_FAILED",
                500,
                "session observer cleanup failed",
            )
        overlay = session.overlay
        try:
            if overlay.parent != self._runtime_root or not overlay.name.startswith("session-"):
                raise BrainError("CLEANUP_FAILED", 500, "session cleanup target is invalid")
            try:
                mode = overlay.lstat().st_mode
            except FileNotFoundError:
                mode = 0
            if stat.S_ISLNK(mode):
                overlay.unlink()
            elif stat.S_ISDIR(mode):
                for current, directories, files in os.walk(
                    overlay, topdown=False, followlinks=False
                ):
                    current_path = Path(current)
                    for name in files:
                        (current_path / name).unlink(missing_ok=True)
                    for name in directories:
                        child = current_path / name
                        if child.is_symlink():
                            child.unlink()
                        else:
                            child.rmdir()
                overlay.rmdir()
            elif mode:
                overlay.unlink()
        except (BrainError, OSError) as error:
            with self._lock:
                session.cleanup_started = False
            if isinstance(error, BrainError):
                raise
            raise BrainError("CLEANUP_FAILED", 500, "session cleanup failed") from error
        with self._lock:
            session.snapshot = None
            session.state = "CLOSED"
            self._sessions.pop(session.session_id, None)

    def _notify_cleanup_listeners(self, session: _Session) -> bool:
        """Run each volatile-state eraser to completion, retrying failures later.

        Callbacks run without the manager lock, while a per-session reentrant
        lock serializes competing close/TTL/stale paths.  Successful callbacks
        are never replayed; a failing callback remains pending and prevents the
        revoked session from being finalized, so the regular sweep can retry it.
        """

        attempted: set[int] = set()
        with session.listener_lock:
            while True:
                with self._lock:
                    pending = [
                        (index, listener)
                        for index, listener in enumerate(self._cleanup_listeners)
                        if index not in session.listeners_completed
                        and index not in session.listeners_in_progress
                        and index not in attempted
                    ]
                    for index, _listener in pending:
                        session.listeners_in_progress.add(index)
                if not pending:
                    with self._lock:
                        return len(session.listeners_completed) == len(self._cleanup_listeners)
                for index, listener in pending:
                    attempted.add(index)
                    succeeded = False
                    try:
                        listener(session.session_id)
                        succeeded = True
                    except Exception:
                        # Keep this callback pending.  Revocation has already
                        # won, and cleanup will not remove the session until a
                        # later retry confirms every eraser completed.
                        with self._lock:
                            self._cleanup_failures += 1
                    finally:
                        with self._lock:
                            session.listeners_in_progress.discard(index)
                            if succeeded:
                                session.listeners_completed.add(index)

    def _revoke_stale(self, session: _Session, *, release_operation: bool) -> None:
        """Revoke a stale snapshot and erase volatile observers immediately."""

        with self._lock:
            if session.state == "ACTIVE":
                session.state = "STALE"
                session.token_digest = b""
                session.cancellation.set()
            if release_operation:
                session.in_flight -= 1
                if session.in_flight < 0:
                    raise AssertionError("negative session operation count")
            cleanup = self._schedule_cleanup_locked(session)
        self._notify_cleanup_listeners(session)
        if cleanup is not None:
            try:
                self._cleanup(cleanup)
            except BrainError:
                # Logical revocation and volatile-memory cleanup already won.
                # The regular reaper will retry the bounded overlay removal.
                with self._lock:
                    self._cleanup_failures += 1

    def shutdown(self) -> None:
        pending: list[_Session] = []
        with self._lock:
            self._shutdown = True
            for session in list(self._sessions.values()):
                if session.state == "ACTIVE":
                    session.state = "CLOSING"
                    session.token_digest = b""
                    session.cancellation.set()
                cleanup = self._schedule_cleanup_locked(session)
                if cleanup is not None:
                    pending.append(cleanup)
            revoked = tuple(self._sessions.values())
        for session in revoked:
            self._notify_cleanup_listeners(session)
        for session in pending:
            try:
                self._cleanup(session)
            except BrainError:
                with self._lock:
                    self._cleanup_failures += 1
        with self._lock:
            empty = not self._sessions
        if empty:
            with suppress(OSError):
                self._runtime_root.rmdir()

    def aggregate_metrics(self) -> dict[str, int]:
        with self._lock:
            return {
                "sessions": len(self._sessions),
                "active": sum(item.state == "ACTIVE" for item in self._sessions.values()),
                "in_flight": sum(item.in_flight for item in self._sessions.values()),
            }
