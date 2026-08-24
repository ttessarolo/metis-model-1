#!/usr/bin/env python3
"""Durable core for synthetic and protected-public-synthetic broker receipts.

The core deliberately has no launcher, subprocess, socket, Node, Metis, key
generation or production-authority implementation.  Execution and protected
signing are injected operator-side capabilities; no caller request can select
either one.  The synthetic Phase-A path remains the default and retains zero
authority.

The append-only ledger has two independent monotonic orderings:

* ``attempt_sequence`` is consumed and fsynced before the executor is called;
* ``receipt_sequence`` is allocated only after cleanup and publication validate.

Consequently a crashed attempt is tombstoned without creating a gap in the
consumer-visible receipt chain.  A durable receipt is returned byte-for-byte on
an idempotent resubmission and is never signed again.
"""

from __future__ import annotations

import fcntl
import os
import re
import secrets
import stat
import struct
import threading
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Protocol

from runtime import w3_broker_protocol as protocol

LEDGER_SCHEMA_VERSION = 1
LEDGER_DOMAIN = "w3-protected-broker/ledger-record/v1"
ATTEMPT_DOMAIN = "w3-protected-broker/attempt/v1"
LEDGER_GENESIS_DIGEST = protocol.SHA256_PREFIX + "0" * 64
LEDGER_MAX_RECORD_BYTES = protocol.MAX_PAYLOAD_BYTES

_RECORD_FIELDS = (
    "schema_version",
    "record_sequence",
    "previous_record_sha256",
    "record_kind",
    "payload",
    "record_sha256",
)
_ATTEMPT_FIELDS = (
    "attempt_sequence",
    "attempt_id",
    "client_nonce",
    "broker_nonce",
    "request_hash",
    "authority_id",
    "authority_sha256",
    "key_id",
    "release_id",
    "release_sha256",
    "policy_sha256",
    "status",
)
_TOMBSTONE_FIELDS = (
    "attempt_sequence",
    "attempt_id",
    "client_nonce",
    "request_hash",
    "reason",
    "status",
)
_RECEIPT_RECORD_FIELDS = (
    "attempt_id",
    "client_nonce",
    "request_hash",
    "receipt_sha256",
    "receipt",
)


class BrokerCoreError(RuntimeError):
    """Fail-closed broker error with a stable machine-readable code."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(code if not detail else f"{code}: {detail}")


class InjectedCrash(RuntimeError):
    """Test-only crash boundary; the durable ledger is intentionally untouched."""

    def __init__(self, point: str):
        self.point = point
        super().__init__(f"injected crash at {point}")


class BrokerExecutor(Protocol):
    """Injected execution boundary; caller bytes never select its implementation."""

    def __call__(
        self,
        request: Mapping[str, object],
        authority: Mapping[str, object],
        attempt: Mapping[str, object],
    ) -> Mapping[str, object]: ...


class ProtectedReceiptSigner(Protocol):
    """Operator-injected protected signer with no caller-facing selection surface."""

    def __call__(self, unsigned_receipt: Mapping[str, object]) -> Mapping[str, object]: ...


@dataclass
class _LedgerState:
    records: list[dict[str, object]]
    attempts_by_nonce: dict[str, dict[str, object]]
    attempts_by_id: dict[str, dict[str, object]]
    receipts_by_nonce: dict[str, dict[str, object]]
    tombstones_by_nonce: dict[str, dict[str, object]]
    last_attempt_sequence: int
    last_receipt_sequence: int
    last_receipt_sha256: str


def _exact_mapping(value: object, fields: tuple[str, ...], scope: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise BrokerCoreError("LEDGER_CORRUPT", f"{scope} is not an object")
    if set(value) != set(fields):
        raise BrokerCoreError("LEDGER_CORRUPT", f"{scope} fields are not exact")
    return value


def _strict_positive_int(value: object, scope: str) -> int:
    if type(value) is not int or value < 1:
        raise BrokerCoreError("LEDGER_CORRUPT", f"{scope} must be a positive integer")
    return value


def _ledger_digest(value: object, scope: str) -> str:
    if type(value) is not str:
        raise BrokerCoreError("LEDGER_CORRUPT", f"{scope} must be a digest")
    try:
        protocol.digest_to_bytes(value)
    except protocol.BrokerProtocolError as error:
        raise BrokerCoreError("LEDGER_CORRUPT", f"{scope} must be a digest") from error
    return value


def _ledger_nonce(value: object, scope: str) -> str:
    if (
        type(value) is not str
        or len(value) != 64
        or value.lower() != value
        or re.fullmatch(r"[0-9a-f]{64}", value) is None
    ):
        raise BrokerCoreError("LEDGER_CORRUPT", f"{scope} must be a nonce")
    return value


def _json_clone(value: Mapping[str, object]) -> dict[str, object]:
    cloned = protocol.parse_canonical_json(protocol.canonical_bytes(dict(value)))
    if not isinstance(cloned, dict):
        raise BrokerCoreError("CANONICAL_CLONE_FAILED")
    return cloned


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise BrokerCoreError("LEDGER_WRITE_FAILED", "short write")
        view = view[written:]


def _record_material(
    *,
    record_sequence: int,
    previous_record_sha256: str,
    record_kind: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "record_sequence": record_sequence,
        "previous_record_sha256": previous_record_sha256,
        "record_kind": record_kind,
        "payload": dict(payload),
    }


def _build_record(
    *,
    record_sequence: int,
    previous_record_sha256: str,
    record_kind: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    material = _record_material(
        record_sequence=record_sequence,
        previous_record_sha256=previous_record_sha256,
        record_kind=record_kind,
        payload=payload,
    )
    return {**material, "record_sha256": protocol.domain_digest(LEDGER_DOMAIN, material)}


def _validate_record(
    value: object,
    *,
    expected_sequence: int,
    expected_previous: str,
) -> dict[str, object]:
    record = _exact_mapping(value, _RECORD_FIELDS, "ledger record")
    if record["schema_version"] != LEDGER_SCHEMA_VERSION:
        raise BrokerCoreError("LEDGER_CORRUPT", "unsupported record schema")
    sequence = _strict_positive_int(record["record_sequence"], "record_sequence")
    if sequence != expected_sequence:
        raise BrokerCoreError("LEDGER_CORRUPT", "record sequence gap or regression")
    if record["previous_record_sha256"] != expected_previous:
        raise BrokerCoreError("LEDGER_CORRUPT", "record chain fork")
    kind = record["record_kind"]
    if kind not in {"attempt", "tombstone", "receipt"}:
        raise BrokerCoreError("LEDGER_CORRUPT", "unknown record kind")
    material = {key: record[key] for key in _RECORD_FIELDS if key != "record_sha256"}
    if record["record_sha256"] != protocol.domain_digest(LEDGER_DOMAIN, material):
        raise BrokerCoreError("LEDGER_CORRUPT", "record digest mismatch")
    return record


def _read_at(fd: int, offset: int, count: int) -> bytes:
    chunks: list[bytes] = []
    remaining = count
    position = offset
    while remaining:
        chunk = os.pread(fd, remaining, position)
        if not chunk:
            break
        chunks.append(chunk)
        position += len(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_records(fd: int, *, repair_torn_tail: bool) -> list[dict[str, object]]:
    size = os.fstat(fd).st_size
    offset = 0
    expected_sequence = 1
    expected_previous = LEDGER_GENESIS_DIGEST
    records: list[dict[str, object]] = []
    while offset < size:
        prefix = _read_at(fd, offset, 4)
        if len(prefix) < 4:
            if not repair_torn_tail:
                raise BrokerCoreError("TORN_TAIL_AMBIGUOUS", "partial length prefix")
            os.ftruncate(fd, offset)
            os.fsync(fd)
            break
        length = struct.unpack(">I", prefix)[0]
        if length == 0 or length > LEDGER_MAX_RECORD_BYTES:
            raise BrokerCoreError("LEDGER_CORRUPT", "invalid record length")
        payload = _read_at(fd, offset + 4, length)
        if len(payload) < length:
            # A complete length prefix followed by a short body is ambiguous:
            # it could be a torn final append or an attacker-corrupted interior
            # length.  Without a separate durable commit marker, truncating it
            # could silently roll the ledger back, so recovery must stop.
            raise BrokerCoreError("TORN_TAIL_AMBIGUOUS", "partial final record")
        try:
            parsed = protocol.parse_canonical_json(payload)
        except protocol.BrokerProtocolError as error:
            raise BrokerCoreError("LEDGER_CORRUPT", str(error)) from error
        record = _validate_record(
            parsed,
            expected_sequence=expected_sequence,
            expected_previous=expected_previous,
        )
        records.append(record)
        expected_sequence += 1
        expected_previous = str(record["record_sha256"])
        offset += 4 + length
    return records


def _append_record(
    fd: int,
    records: list[dict[str, object]],
    *,
    record_kind: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    previous = LEDGER_GENESIS_DIGEST if not records else str(records[-1]["record_sha256"])
    record = _build_record(
        record_sequence=len(records) + 1,
        previous_record_sha256=previous,
        record_kind=record_kind,
        payload=payload,
    )
    body = protocol.canonical_bytes(record)
    if len(body) > LEDGER_MAX_RECORD_BYTES:
        raise BrokerCoreError("LEDGER_RECORD_TOO_LARGE")
    os.lseek(fd, 0, os.SEEK_END)
    _write_all(fd, struct.pack(">I", len(body)) + body)
    os.fsync(fd)
    records.append(record)
    return record


def _state_from_records(
    records: list[dict[str, object]],
    *,
    receipt_verifier: Callable[[Mapping[str, object]], bool] | None = None,
) -> _LedgerState:
    verify_receipt = receipt_verifier or protocol.verify_receipt_signature
    attempts_by_nonce: dict[str, dict[str, object]] = {}
    attempts_by_id: dict[str, dict[str, object]] = {}
    receipts_by_nonce: dict[str, dict[str, object]] = {}
    tombstones_by_nonce: dict[str, dict[str, object]] = {}
    last_attempt_sequence = 0
    last_receipt_sequence = 0
    last_receipt_sha256 = protocol.GENESIS_RECEIPT_DIGEST

    for record in records:
        kind = record["record_kind"]
        if kind == "attempt":
            attempt = _exact_mapping(record["payload"], _ATTEMPT_FIELDS, "attempt")
            sequence = _strict_positive_int(attempt["attempt_sequence"], "attempt_sequence")
            if sequence != last_attempt_sequence + 1:
                raise BrokerCoreError("LEDGER_CORRUPT", "attempt sequence gap")
            if attempt["status"] != "PENDING":
                raise BrokerCoreError("LEDGER_CORRUPT", "attempt status")
            if attempt["authority_id"] != protocol.AUTHORITY_ID:
                raise BrokerCoreError("LEDGER_CORRUPT", "attempt authority id")
            nonce = _ledger_nonce(attempt["client_nonce"], "attempt client_nonce")
            broker_nonce = _ledger_nonce(attempt["broker_nonce"], "attempt broker_nonce")
            attempt_id = _ledger_digest(attempt["attempt_id"], "attempt_id")
            request_hash = _ledger_digest(attempt["request_hash"], "attempt request_hash")
            for field in ("authority_sha256", "key_id", "release_sha256", "policy_sha256"):
                _ledger_digest(attempt[field], f"attempt {field}")
            release_id = attempt["release_id"]
            if (
                type(release_id) is not str
                or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", release_id) is None
            ):
                raise BrokerCoreError("LEDGER_CORRUPT", "attempt release_id")
            expected_attempt_id = protocol.domain_digest(
                ATTEMPT_DOMAIN,
                {
                    "attempt_sequence": sequence,
                    "client_nonce": nonce,
                    "broker_nonce": broker_nonce,
                    "request_hash": request_hash,
                },
            )
            if attempt_id != expected_attempt_id:
                raise BrokerCoreError("LEDGER_CORRUPT", "attempt identity mismatch")
            if nonce in attempts_by_nonce or attempt_id in attempts_by_id:
                raise BrokerCoreError("LEDGER_CORRUPT", "duplicate attempt identity")
            attempts_by_nonce[nonce] = attempt
            attempts_by_id[attempt_id] = attempt
            last_attempt_sequence = sequence
        elif kind == "tombstone":
            tombstone = _exact_mapping(record["payload"], _TOMBSTONE_FIELDS, "tombstone")
            nonce = str(tombstone["client_nonce"])
            attempt = attempts_by_nonce.get(nonce)
            if attempt is None or tombstone["attempt_id"] != attempt["attempt_id"]:
                raise BrokerCoreError("LEDGER_CORRUPT", "orphan tombstone")
            if (
                tombstone["attempt_sequence"] != attempt["attempt_sequence"]
                or tombstone["client_nonce"] != attempt["client_nonce"]
                or tombstone["request_hash"] != attempt["request_hash"]
            ):
                raise BrokerCoreError("LEDGER_CORRUPT", "tombstone attempt mismatch")
            if nonce in receipts_by_nonce or nonce in tombstones_by_nonce:
                raise BrokerCoreError("LEDGER_CORRUPT", "duplicate terminal attempt state")
            if tombstone["status"] != "TOMBSTONED":
                raise BrokerCoreError("LEDGER_CORRUPT", "tombstone status")
            if type(tombstone["reason"]) is not str or not tombstone["reason"]:
                raise BrokerCoreError("LEDGER_CORRUPT", "tombstone reason")
            tombstones_by_nonce[nonce] = tombstone
        else:
            receipt_record = _exact_mapping(
                record["payload"], _RECEIPT_RECORD_FIELDS, "receipt record"
            )
            nonce = _ledger_nonce(receipt_record["client_nonce"], "receipt record client_nonce")
            _ledger_digest(receipt_record["request_hash"], "receipt record request_hash")
            _ledger_digest(receipt_record["receipt_sha256"], "receipt record receipt_sha256")
            attempt = attempts_by_nonce.get(nonce)
            if attempt is None or receipt_record["attempt_id"] != attempt["attempt_id"]:
                raise BrokerCoreError("LEDGER_CORRUPT", "orphan receipt")
            if nonce in receipts_by_nonce or nonce in tombstones_by_nonce:
                raise BrokerCoreError("LEDGER_CORRUPT", "duplicate terminal attempt state")
            try:
                receipt = protocol.validate_receipt(receipt_record["receipt"])
                signature_ok = verify_receipt(receipt)
            except protocol.BrokerProtocolError as error:
                raise BrokerCoreError("LEDGER_CORRUPT", str(error)) from error
            if not signature_ok:
                raise BrokerCoreError("LEDGER_CORRUPT", "invalid durable receipt signature")
            if receipt_record["receipt_sha256"] != protocol.receipt_hash(receipt):
                raise BrokerCoreError("LEDGER_CORRUPT", "durable receipt hash mismatch")
            if (
                receipt_record["client_nonce"] != attempt["client_nonce"]
                or receipt_record["request_hash"] != attempt["request_hash"]
            ):
                raise BrokerCoreError("LEDGER_CORRUPT", "receipt request mismatch")
            receipt_request = receipt["request"]
            expected_request_binding = {
                "request_hash": attempt["request_hash"],
                "client_nonce": attempt["client_nonce"],
                "claimed_authority_sha256": attempt["authority_sha256"],
                "claimed_release_sha256": attempt["release_sha256"],
                "claimed_policy_sha256": attempt["policy_sha256"],
            }
            if receipt_request != expected_request_binding:
                raise BrokerCoreError("LEDGER_CORRUPT", "inner receipt request mismatch")
            expected_measured = {
                "authority_sha256": attempt["authority_sha256"],
                "release_sha256": attempt["release_sha256"],
                "policy_sha256": attempt["policy_sha256"],
            }
            if receipt["measured"] != expected_measured:
                raise BrokerCoreError("LEDGER_CORRUPT", "inner receipt measurement mismatch")
            if receipt["broker_nonce"] != attempt["broker_nonce"]:
                raise BrokerCoreError("LEDGER_CORRUPT", "inner receipt broker nonce mismatch")
            if receipt["signature"]["key_id"] != attempt["key_id"]:
                raise BrokerCoreError("LEDGER_CORRUPT", "inner receipt signing key mismatch")
            if receipt["attempt_sequence"] != attempt["attempt_sequence"]:
                raise BrokerCoreError("LEDGER_CORRUPT", "receipt attempt mismatch")
            receipt_sequence = _strict_positive_int(receipt["receipt_sequence"], "receipt_sequence")
            if receipt_sequence != last_receipt_sequence + 1:
                raise BrokerCoreError("LEDGER_CORRUPT", "receipt sequence gap")
            if receipt["previous_receipt_sha256"] != last_receipt_sha256:
                raise BrokerCoreError("LEDGER_CORRUPT", "receipt chain fork")
            receipts_by_nonce[nonce] = receipt_record
            last_receipt_sequence = receipt_sequence
            last_receipt_sha256 = str(receipt_record["receipt_sha256"])

    return _LedgerState(
        records=records,
        attempts_by_nonce=attempts_by_nonce,
        attempts_by_id=attempts_by_id,
        receipts_by_nonce=receipts_by_nonce,
        tombstones_by_nonce=tombstones_by_nonce,
        last_attempt_sequence=last_attempt_sequence,
        last_receipt_sequence=last_receipt_sequence,
        last_receipt_sha256=last_receipt_sha256,
    )


def _freeze_protected_key_registry(value: object) -> Mapping[str, bytes]:
    """Validate and freeze protected-mode public keys by their mode-scoped ids."""

    if not isinstance(value, Mapping):
        raise BrokerCoreError("PROTECTED_KEY_REGISTRY_REQUIRED")
    frozen: dict[str, bytes] = {}
    for key_id, public_key in value.items():
        if type(key_id) is not str:
            raise BrokerCoreError("PROTECTED_KEY_REGISTRY_INVALID", "key id")
        try:
            protocol.digest_to_bytes(key_id)
            raw_public_key = bytes(public_key) if isinstance(public_key, bytes | bytearray) else b""
            encoded = protocol.ed25519.encode_public_key(raw_public_key)
            decoded = protocol.ed25519.decode_public_key(encoded)
            expected_key_id = protocol.ed25519.mode_scoped_key_id(
                decoded,
                mode=protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC,
            )
        except protocol.BrokerProtocolError as error:
            raise BrokerCoreError("PROTECTED_KEY_REGISTRY_INVALID", str(error)) from error
        except protocol.ed25519.Ed25519ContractError as error:
            raise BrokerCoreError("PROTECTED_KEY_REGISTRY_INVALID", error.reason) from error
        if key_id != expected_key_id or key_id in frozen:
            raise BrokerCoreError("PROTECTED_KEY_REGISTRY_INVALID", "mode-scoped key id")
        frozen[key_id] = decoded
    return MappingProxyType(frozen)


class ProtectedExecutionBroker:
    """Single-current-authority broker with a durable append-only ledger."""

    def __init__(
        self,
        *,
        authority: Mapping[str, object],
        ledger_path: str | Path,
        executor: BrokerExecutor,
        protected_signer: ProtectedReceiptSigner | None = None,
        verification_keys: Mapping[str, bytes] | None = None,
        nonce_factory: Callable[[], str] | None = None,
        max_inflight: int = 32,
        require_existing_ledger: bool = True,
        allow_unprotected_test_ledger: bool = False,
    ):
        validated_authority = protocol.validate_authority(_json_clone(authority))
        mode = validated_authority["mode"]
        if mode == protocol.MODE_PRODUCTION:
            raise BrokerCoreError("PRODUCTION_MODE_FORBIDDEN")
        if not callable(executor):
            raise BrokerCoreError("EXECUTOR_REQUIRED")
        if mode == protocol.MODE_SYNTHETIC:
            if validated_authority["signing"]["key_id"] != protocol.synthetic_key_id():
                raise BrokerCoreError("SYNTHETIC_KEY_ID_MISMATCH")
            if protected_signer is not None or verification_keys:
                raise BrokerCoreError("SYNTHETIC_PROTECTED_CAPABILITY_FORBIDDEN")
            key_registry: Mapping[str, bytes] = MappingProxyType({})
        elif mode == protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC:
            if not callable(protected_signer):
                raise BrokerCoreError("PROTECTED_SIGNER_REQUIRED")
            key_registry = _freeze_protected_key_registry(verification_keys)
            current_key_id = str(validated_authority["signing"]["key_id"])
            try:
                authority_public_key = protocol.ed25519.decode_public_key(
                    validated_authority["signing"]["public_key"]
                )
            except protocol.ed25519.Ed25519ContractError as error:
                raise BrokerCoreError("PROTECTED_AUTHORITY_KEY_INVALID", error.reason) from error
            if key_registry.get(current_key_id) != authority_public_key:
                raise BrokerCoreError("PROTECTED_CURRENT_KEY_NOT_REGISTERED")
        else:  # validate_authority already rejects every unknown mode.
            raise BrokerCoreError("BROKER_MODE_FORBIDDEN", str(mode))
        path = Path(ledger_path)
        if not path.is_absolute():
            raise BrokerCoreError("LEDGER_PATH_NOT_ABSOLUTE")
        if type(max_inflight) is not int or max_inflight < 1:
            raise BrokerCoreError("BAD_QUEUE_BOUND")
        if type(require_existing_ledger) is not bool:
            raise BrokerCoreError("BAD_LEDGER_CONFIGURATION")
        if type(allow_unprotected_test_ledger) is not bool:
            raise BrokerCoreError("BAD_LEDGER_CONFIGURATION")
        if not allow_unprotected_test_ledger and not require_existing_ledger:
            raise BrokerCoreError("SECURE_LEDGER_PRECREATION_REQUIRED")
        self._authority = validated_authority
        self._authority_sha256 = protocol.authority_hash(validated_authority)
        self._mode = str(mode)
        self._ledger_path = path
        self._executor = executor
        self._protected_signer = protected_signer
        self._verification_keys = key_registry
        self._nonce_factory = nonce_factory or (lambda: secrets.token_hex(32))
        self._slots = threading.BoundedSemaphore(max_inflight)
        self._require_existing_ledger = require_existing_ledger
        self._allow_unprotected_test_ledger = allow_unprotected_test_ledger
        self._poisoned = False
        self._poison_lock = threading.Lock()
        self._events: list[str] = []
        self._events_lock = threading.Lock()

    @property
    def authority_sha256(self) -> str:
        return self._authority_sha256

    @property
    def events(self) -> tuple[str, ...]:
        with self._events_lock:
            return tuple(self._events)

    def _event(self, name: str) -> None:
        with self._events_lock:
            self._events.append(name)

    def _verify_durable_receipt(self, receipt: Mapping[str, object]) -> bool:
        body = protocol.validate_receipt(receipt)
        receipt_mode = body["mode"]
        if receipt_mode != self._mode:
            raise protocol.ValidationError(
                "ledger-mode-mismatch",
                f"{receipt_mode} != {self._mode}",
            )
        if receipt_mode == protocol.MODE_SYNTHETIC:
            return protocol.verify_receipt_signature(body)
        if receipt_mode == protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC:
            key_id = str(body["signature"]["key_id"])
            public_key = self._verification_keys.get(key_id)
            if public_key is None:
                raise protocol.ValidationError("unknown-protected-key", key_id)
            return protocol.verify_receipt_signature(
                body,
                public_key=public_key,
                registered_key_id=key_id,
            )
        raise protocol.ValidationError(
            "production-verification-unavailable",
            "broker recovery never accepts production receipts",
        )

    def _sign_receipt(self, receipt: Mapping[str, object]) -> dict[str, object]:
        if self._mode == protocol.MODE_SYNTHETIC:
            return protocol.attach_synthetic_signature(receipt)
        if self._mode != protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC:
            raise BrokerCoreError("PRODUCTION_MODE_FORBIDDEN")
        signer = self._protected_signer
        if signer is None:  # Constructor validation makes this unreachable.
            raise BrokerCoreError("PROTECTED_SIGNER_REQUIRED")
        original_signing_bytes = protocol.receipt_signing_bytes(receipt)
        try:
            candidate_value = signer(_json_clone(receipt))
        except BaseException as error:
            if isinstance(error, (KeyboardInterrupt, SystemExit)):
                raise
            raise BrokerCoreError("PROTECTED_SIGNER_FAILED", type(error).__name__) from error
        if not isinstance(candidate_value, Mapping):
            raise BrokerCoreError("PROTECTED_SIGNER_INVALID", "not an object")
        try:
            candidate = _json_clone(candidate_value)
            candidate_signing_bytes = protocol.receipt_signing_bytes(candidate)
        except protocol.BrokerProtocolError as error:
            raise BrokerCoreError("PROTECTED_SIGNER_INVALID", str(error)) from error
        current_key_id = str(self._authority["signing"]["key_id"])
        if candidate["signature"]["key_id"] != current_key_id:
            raise BrokerCoreError("PROTECTED_SIGNER_KEY_MISMATCH")
        if candidate_signing_bytes != original_signing_bytes:
            raise BrokerCoreError("PROTECTED_SIGNER_MUTATED_SIGNED_FIELDS")
        try:
            signature_ok = self._verify_durable_receipt(candidate)
        except protocol.BrokerProtocolError as error:
            raise BrokerCoreError("PROTECTED_SIGNER_INVALID", str(error)) from error
        if not signature_ok:
            raise BrokerCoreError("PROTECTED_SIGNATURE_INVALID")
        return candidate

    def _ensure_not_poisoned(self) -> None:
        with self._poison_lock:
            if self._poisoned:
                raise BrokerCoreError("LEDGER_POISONED")

    def _poison(self) -> None:
        with self._poison_lock:
            self._poisoned = True

    def _open_parent(self) -> int:
        parent = self._ledger_path.parent
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_DIRECTORY", 0)
        if not self._allow_unprotected_test_ledger:
            current_fd = -1
            try:
                current_fd = os.open("/", flags)
                root_info = os.fstat(current_fd)
                if (
                    not stat.S_ISDIR(root_info.st_mode)
                    or root_info.st_uid != 0
                    or root_info.st_mode & 0o022
                ):
                    raise BrokerCoreError("LEDGER_PARENT_UNSAFE")
                for component in parent.parts[1:]:
                    if component in {"", ".", ".."}:
                        raise BrokerCoreError("LEDGER_PARENT_UNSAFE")
                    next_fd = os.open(component, flags, dir_fd=current_fd)
                    os.close(current_fd)
                    current_fd = next_fd
                    opened = os.fstat(current_fd)
                    if (
                        not stat.S_ISDIR(opened.st_mode)
                        or opened.st_uid != 0
                        or opened.st_mode & 0o022
                    ):
                        raise BrokerCoreError("LEDGER_PARENT_UNSAFE")
                return current_fd
            except BrokerCoreError:
                if current_fd >= 0:
                    os.close(current_fd)
                raise
            except OSError as error:
                if current_fd >= 0:
                    os.close(current_fd)
                raise BrokerCoreError("LEDGER_PARENT_UNAVAILABLE", str(error)) from error
        try:
            info = parent.lstat()
        except OSError as error:
            raise BrokerCoreError("LEDGER_PARENT_UNAVAILABLE", str(error)) from error
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise BrokerCoreError("LEDGER_PARENT_UNSAFE")
        expected_owner = {0, os.geteuid()} if self._allow_unprotected_test_ledger else {0}
        if info.st_uid not in expected_owner or info.st_mode & 0o022:
            raise BrokerCoreError("LEDGER_PARENT_UNSAFE")
        try:
            parent_fd = os.open(parent, flags)
        except OSError as error:
            raise BrokerCoreError("LEDGER_PARENT_UNAVAILABLE", str(error)) from error
        opened = os.fstat(parent_fd)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            os.close(parent_fd)
            raise BrokerCoreError("LEDGER_PARENT_RACE")
        return parent_fd

    def _verify_parent_identity(self, parent_fd: int) -> None:
        opened = os.fstat(parent_fd)
        try:
            named = os.stat(self._ledger_path.parent, follow_symlinks=False)
        except OSError as error:
            raise BrokerCoreError("LEDGER_PARENT_RACE", str(error)) from error
        expected_owner = {0, os.geteuid()} if self._allow_unprotected_test_ledger else {0}
        if (
            not stat.S_ISDIR(opened.st_mode)
            or not stat.S_ISDIR(named.st_mode)
            or opened.st_uid not in expected_owner
            or named.st_uid not in expected_owner
            or opened.st_mode & 0o022
            or named.st_mode & 0o022
            or (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise BrokerCoreError("LEDGER_PARENT_RACE")

    def _verify_named_leaf(self, fd: int, parent_fd: int) -> None:
        opened = os.fstat(fd)
        try:
            named = os.stat(self._ledger_path.name, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as error:
            raise BrokerCoreError("LEDGER_REPLACED", str(error)) from error
        if (
            not stat.S_ISREG(named.st_mode)
            or named.st_nlink != 1
            or (named.st_dev, named.st_ino) != (opened.st_dev, opened.st_ino)
            or named.st_uid != os.geteuid()
            or stat.S_IMODE(named.st_mode) != 0o600
        ):
            raise BrokerCoreError("LEDGER_REPLACED")

    def _open_ledger(self) -> tuple[int, int]:
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        cloexec = getattr(os, "O_CLOEXEC", 0)
        flags = os.O_RDWR | nofollow | cloexec
        created = False
        parent_fd = self._open_parent()
        try:
            try:
                fd = os.open(self._ledger_path.name, flags, dir_fd=parent_fd)
            except FileNotFoundError as error:
                if self._require_existing_ledger:
                    raise BrokerCoreError("LEDGER_MISSING") from error
                try:
                    fd = os.open(
                        self._ledger_path.name,
                        flags | os.O_CREAT | os.O_EXCL,
                        0o600,
                        dir_fd=parent_fd,
                    )
                    created = True
                except FileExistsError:
                    # Another broker thread/process won the O_EXCL creation
                    # race. Open the same no-follow leaf and let flock
                    # serialize initialization and all subsequent records.
                    try:
                        fd = os.open(self._ledger_path.name, flags, dir_fd=parent_fd)
                    except OSError as retry_error:
                        raise BrokerCoreError(
                            "LEDGER_OPEN_FAILED", str(retry_error)
                        ) from retry_error
                except OSError as create_error:
                    raise BrokerCoreError("LEDGER_OPEN_FAILED", str(create_error)) from create_error
            except OSError as error:
                raise BrokerCoreError("LEDGER_OPEN_FAILED", str(error)) from error
            if created:
                os.fchmod(fd, 0o600)
                os.fsync(fd)
                os.fsync(parent_fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise BrokerCoreError("LEDGER_FILE_UNSAFE")
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o600:
                raise BrokerCoreError("LEDGER_FILE_UNSAFE")
            self._verify_parent_identity(parent_fd)
            self._verify_named_leaf(fd, parent_fd)
            return fd, parent_fd
        except BaseException:
            if "fd" in locals():
                os.close(fd)
            os.close(parent_fd)
            raise

    @contextmanager
    def _locked_ledger(self):
        self._ensure_not_poisoned()
        try:
            fd, parent_fd = self._open_ledger()
        except BrokerCoreError as error:
            if error.code in {
                "LEDGER_REPLACED",
                "LEDGER_PARENT_RACE",
                "LEDGER_FILE_UNSAFE",
                "LEDGER_PARENT_UNSAFE",
            }:
                self._poison()
            raise
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                self._verify_parent_identity(parent_fd)
                self._verify_named_leaf(fd, parent_fd)
                yield fd, parent_fd
                self._verify_named_leaf(fd, parent_fd)
                self._verify_parent_identity(parent_fd)
            except BrokerCoreError as error:
                if error.code in {
                    "LEDGER_REPLACED",
                    "LEDGER_PARENT_RACE",
                    "LEDGER_FILE_UNSAFE",
                    "LEDGER_PARENT_UNSAFE",
                }:
                    self._poison()
                raise
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                try:
                    os.close(fd)
                finally:
                    os.close(parent_fd)

    @staticmethod
    def _crash(crash_at: str | None, point: str) -> None:
        if crash_at == point:
            raise InjectedCrash(point)

    def _append_tombstone(
        self,
        fd: int,
        state: _LedgerState,
        attempt: Mapping[str, object],
        reason: str,
    ) -> None:
        payload = {
            "attempt_sequence": attempt["attempt_sequence"],
            "attempt_id": attempt["attempt_id"],
            "client_nonce": attempt["client_nonce"],
            "request_hash": attempt["request_hash"],
            "reason": reason,
            "status": "TOMBSTONED",
        }
        _append_record(fd, state.records, record_kind="tombstone", payload=payload)
        state.tombstones_by_nonce[str(attempt["client_nonce"])] = payload
        self._event("tombstone_fsync")

    def _recover_pending(self, fd: int, state: _LedgerState) -> None:
        terminal = set(state.receipts_by_nonce) | set(state.tombstones_by_nonce)
        pending = [
            attempt for nonce, attempt in state.attempts_by_nonce.items() if nonce not in terminal
        ]
        for attempt in sorted(pending, key=lambda row: int(row["attempt_sequence"])):
            self._append_tombstone(fd, state, attempt, "restart-recovery")

    def _validate_execution_result(
        self,
        request: Mapping[str, object],
        result: Mapping[str, object],
    ) -> dict[str, object]:
        fields = (
            "measured",
            "identities",
            "effective_ids",
            "policy",
            "roster",
            "output",
            "cleanup",
        )
        if not isinstance(result, Mapping) or set(result) != set(fields):
            raise BrokerCoreError("EXECUTION_RESULT_INVALID", "top-level fields")
        try:
            normalized = protocol.parse_canonical_json(protocol.canonical_bytes(dict(result)))
        except protocol.BrokerProtocolError as error:
            raise BrokerCoreError("EXECUTION_RESULT_INVALID", str(error)) from error
        if not isinstance(normalized, dict):
            raise BrokerCoreError("EXECUTION_RESULT_INVALID", "not an object")

        measured = normalized["measured"]
        if not isinstance(measured, dict):
            raise BrokerCoreError("EXECUTION_RESULT_INVALID", "measured")
        release_sha256 = self._authority["release_identity"]["ancestry_root_sha256"]
        policy_identity = self._authority["policy_identity"]
        policy_sha256 = policy_identity["resolved_sha256"]
        expected_measured = {
            "authority_sha256": self._authority_sha256,
            "release_sha256": release_sha256,
            "policy_sha256": policy_sha256,
        }
        if measured != expected_measured:
            raise BrokerCoreError("CLAIMED_MEASURED_MISMATCH")
        if request["claimed_release_sha256"] != release_sha256:
            raise BrokerCoreError("RELEASE_CLAIM_MISMATCH")
        if request["claimed_policy_sha256"] != policy_sha256:
            raise BrokerCoreError("POLICY_CLAIM_MISMATCH")

        policy = normalized["policy"]
        if policy != policy_identity:
            raise BrokerCoreError("POLICY_CLAIM_MISMATCH")

        installed = self._authority["installed_code_identity"]
        identities = normalized["identities"]
        if not isinstance(identities, dict):
            raise BrokerCoreError("EXECUTED_IDENTITY_MISMATCH")
        expected_identity_hashes = {
            "broker": installed["broker_code_sha256"],
            "launcher": installed["launcher_sha256"],
            "worker": installed["worker_sha256"],
            "node": installed["node_sha256"],
            "loader": installed["loader_sha256"],
        }
        observed_identity_hashes = {
            "broker": identities.get("broker", {}).get("code_sha256"),
            "launcher": identities.get("launcher", {}).get("code_sha256"),
            "worker": identities.get("worker", {}).get("code_sha256"),
            "node": identities.get("node", {}).get("sha256"),
            "loader": identities.get("loader", {}).get("sha256"),
        }
        if observed_identity_hashes != expected_identity_hashes:
            raise BrokerCoreError("EXECUTED_IDENTITY_MISMATCH")

        broker_identity = self._authority["broker_identity"]
        runner_identity = self._authority["runner_identity"]
        launcher_identity = self._authority["launcher_identity"]
        expected_ids = {
            "broker_uid": broker_identity["uid"],
            "broker_gid": broker_identity["gid"],
            "runner_uid": runner_identity["uid"],
            "runner_gid": runner_identity["gid"],
            "launcher_uid": launcher_identity["uid"],
            "launcher_gid": launcher_identity["gid"],
        }
        if normalized["effective_ids"] != expected_ids:
            raise BrokerCoreError("EFFECTIVE_ID_MISMATCH")

        roster = normalized["roster"]
        if not isinstance(roster, dict) or roster.get("pre") != roster.get("post"):
            raise BrokerCoreError("PREIMAGE_ROSTER_CHANGED")
        rows = roster.get("pre")
        installed_roster = self._authority["installed_code_roster"]
        if rows != installed_roster or roster.get("post") != installed_roster:
            raise BrokerCoreError("PREIMAGE_ROSTER_INCOMPLETE")
        probe = self._unsigned_receipt(
            request=request,
            result=normalized,
            broker_nonce="00" * 32,
            attempt_sequence=1,
            receipt_sequence=1,
            previous_receipt_sha256=protocol.GENESIS_RECEIPT_DIGEST,
        )
        try:
            protocol.validate_receipt(probe)
        except protocol.BrokerProtocolError as error:
            raise BrokerCoreError("EXECUTION_RESULT_INVALID", str(error)) from error
        return normalized

    def _unsigned_receipt(
        self,
        *,
        request: Mapping[str, object],
        result: Mapping[str, object],
        broker_nonce: str,
        attempt_sequence: int,
        receipt_sequence: int,
        previous_receipt_sha256: str,
    ) -> dict[str, object]:
        protected = self._mode == protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC
        if protected:
            signature = {
                "algorithm": protocol.PRODUCTION_ALGORITHM,
                "key_id": self._authority["signing"]["key_id"],
                "value": protocol.ed25519.encode_signature(bytes(protocol.ed25519.SIGNATURE_BYTES)),
            }
            nonclaims = list(protocol.PROTECTED_PUBLIC_SYNTHETIC_NONCLAIMS)
        else:
            signature = {
                "algorithm": protocol.SYNTHETIC_ALGORITHM,
                "key_id": protocol.synthetic_key_id(),
                "value": "0" * 64,
            }
        return {
            "schema_version": protocol.SCHEMA_VERSION,
            "kind": protocol.KIND_RECEIPT,
            "mode": self._mode,
            "executed_preimage_authority": protected,
            "nonclaims": nonclaims if protected else list(protocol.SYNTHETIC_NONCLAIMS),
            "request": {
                "request_hash": request["request_hash"],
                "client_nonce": request["client_nonce"],
                "claimed_authority_sha256": request["claimed_authority_sha256"],
                "claimed_release_sha256": request["claimed_release_sha256"],
                "claimed_policy_sha256": request["claimed_policy_sha256"],
            },
            "measured": result["measured"],
            "broker_nonce": broker_nonce,
            "attempt_sequence": attempt_sequence,
            "receipt_sequence": receipt_sequence,
            "previous_receipt_sha256": previous_receipt_sha256,
            "identities": result["identities"],
            "effective_ids": result["effective_ids"],
            "policy": result["policy"],
            "roster": result["roster"],
            "output": result["output"],
            "cleanup": result["cleanup"],
            "signature": signature,
        }

    def handle(self, canonical_request: bytes, *, crash_at: str | None = None) -> bytes:
        """Validate, consume, synthetically execute, sign, persist and deliver."""

        self._ensure_not_poisoned()
        if not self._slots.acquire(blocking=False):
            raise BrokerCoreError("QUEUE_FULL")
        try:
            try:
                parsed = protocol.parse_canonical_json(canonical_request)
                request = protocol.validate_request(parsed)
                protocol.cross_bind_authority(request, self._authority)
            except protocol.BrokerProtocolError as error:
                raise BrokerCoreError("INVALID_REQUEST", str(error)) from error
            if (
                request["claimed_release_sha256"]
                != self._authority["release_identity"]["ancestry_root_sha256"]
            ):
                raise BrokerCoreError("RELEASE_CLAIM_MISMATCH")

            with self._locked_ledger() as (fd, parent_fd):
                records = _read_records(fd, repair_torn_tail=True)
                state = _state_from_records(
                    records,
                    receipt_verifier=self._verify_durable_receipt,
                )
                self._recover_pending(fd, state)

                nonce = str(request["client_nonce"])
                existing_receipt = state.receipts_by_nonce.get(nonce)
                if existing_receipt is not None:
                    if existing_receipt["request_hash"] != request["request_hash"]:
                        raise BrokerCoreError("NONCE_CONSUMED_NO_RECEIPT")
                    self._event("duplicate_complete")
                    return protocol.canonical_bytes(existing_receipt["receipt"])
                if nonce in state.attempts_by_nonce:
                    raise BrokerCoreError("NONCE_CONSUMED_NO_RECEIPT")

                self._crash(crash_at, "before_consume")
                attempt_sequence = state.last_attempt_sequence + 1
                broker_nonce = self._nonce_factory()
                if not isinstance(broker_nonce, str) or len(broker_nonce) != 64:
                    raise BrokerCoreError("BAD_BROKER_NONCE")
                try:
                    bytes.fromhex(broker_nonce)
                except ValueError as error:
                    raise BrokerCoreError("BAD_BROKER_NONCE") from error
                attempt_id = protocol.domain_digest(
                    ATTEMPT_DOMAIN,
                    {
                        "attempt_sequence": attempt_sequence,
                        "client_nonce": nonce,
                        "broker_nonce": broker_nonce,
                        "request_hash": request["request_hash"],
                    },
                )
                attempt = {
                    "attempt_sequence": attempt_sequence,
                    "attempt_id": attempt_id,
                    "client_nonce": nonce,
                    "broker_nonce": broker_nonce,
                    "request_hash": request["request_hash"],
                    "authority_id": self._authority["authority_id"],
                    "authority_sha256": self._authority_sha256,
                    "key_id": self._authority["signing"]["key_id"],
                    "release_id": self._authority["release_identity"]["release_id"],
                    "release_sha256": request["claimed_release_sha256"],
                    "policy_sha256": request["claimed_policy_sha256"],
                    "status": "PENDING",
                }
                _append_record(fd, state.records, record_kind="attempt", payload=attempt)
                state.attempts_by_nonce[nonce] = attempt
                state.attempts_by_id[attempt_id] = attempt
                state.last_attempt_sequence = attempt_sequence
                self._event("consume_fsync")
                self._crash(crash_at, "after_consume")
                self._event("execute_started")
                self._crash(crash_at, "during_execution")

                try:
                    raw_result = self._executor(
                        _json_clone(request),
                        _json_clone(self._authority),
                        _json_clone(attempt),
                    )
                    result = self._validate_execution_result(request, raw_result)
                    self._verify_parent_identity(parent_fd)
                    self._verify_named_leaf(fd, parent_fd)
                except InjectedCrash:
                    raise
                except Exception as error:
                    self._append_tombstone(fd, state, attempt, type(error).__name__)
                    if isinstance(error, BrokerCoreError):
                        raise
                    raise BrokerCoreError("EXECUTOR_FAILED", str(error)) from error

                self._event("cleanup_proven")
                self._crash(crash_at, "after_cleanup")
                receipt_sequence = state.last_receipt_sequence + 1
                receipt = self._unsigned_receipt(
                    request=request,
                    result=result,
                    broker_nonce=broker_nonce,
                    attempt_sequence=attempt_sequence,
                    receipt_sequence=receipt_sequence,
                    previous_receipt_sha256=state.last_receipt_sha256,
                )
                self._verify_parent_identity(parent_fd)
                self._verify_named_leaf(fd, parent_fd)
                try:
                    signed = self._sign_receipt(receipt)
                except (protocol.BrokerProtocolError, BrokerCoreError) as error:
                    self._append_tombstone(fd, state, attempt, "receipt-validation")
                    if isinstance(error, BrokerCoreError):
                        raise
                    raise BrokerCoreError("RECEIPT_INVALID", str(error)) from error
                if signed["attempt_sequence"] < signed["receipt_sequence"]:
                    self._append_tombstone(fd, state, attempt, "sequence-invariant")
                    raise BrokerCoreError("RECEIPT_SEQUENCE_INVALID")
                self._event("receipt_signed_volatile")
                self._crash(crash_at, "after_sign")

                receipt_record = {
                    "attempt_id": attempt_id,
                    "client_nonce": nonce,
                    "request_hash": request["request_hash"],
                    "receipt_sha256": protocol.receipt_hash(signed),
                    "receipt": signed,
                }
                _append_record(fd, state.records, record_kind="receipt", payload=receipt_record)
                state.receipts_by_nonce[nonce] = receipt_record
                state.last_receipt_sequence = receipt_sequence
                state.last_receipt_sha256 = str(receipt_record["receipt_sha256"])
                self._event("receipt_fsync")
                self._crash(crash_at, "after_receipt_append")
                response = protocol.canonical_bytes(signed)
            self._event("delivered")
            return response
        finally:
            self._slots.release()

    def inspect_ledger(self, *, repair_torn_tail: bool = False) -> tuple[dict[str, object], ...]:
        """Read-only Phase A diagnostic view; it exposes no request-hash lookup API."""

        with self._locked_ledger() as (fd, _parent_fd):
            records = _read_records(fd, repair_torn_tail=repair_torn_tail)
            _state_from_records(
                records,
                receipt_verifier=self._verify_durable_receipt,
            )
            return tuple(records)

    def lookup_request_hash(self, _request_hash: str) -> None:
        """Explicitly deny request-hash existence probing."""

        raise BrokerCoreError("REQUEST_HASH_PROBE_DENIED")
