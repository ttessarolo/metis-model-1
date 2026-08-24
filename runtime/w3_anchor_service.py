#!/usr/bin/env python3
"""Protected receipt-anchor service for L70 public-synthetic evidence.

The daemon has one operation, ``ADVANCE(expected_anchor_sha256,
canonical_receipt)``.  It receives a launchd listener as inherited descriptor 3,
never creates a socket pathname, never accepts a caller-derived next state and
never initializes storage.  The installer must pre-create the canonical genesis
log below root-owned, non-writable ancestry.

L70 executes this module only against unprotected temporary fixtures.  No local
test is host evidence and production verification remains unavailable.
"""

from __future__ import annotations

import fcntl
import os
import socket
import stat
import struct
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

from metis_model1.w3_broker_client import (
    ANCHOR_SERVICE_OPERATION,
    ANCHOR_SERVICE_REQUEST_KIND,
    ANCHOR_SERVICE_RESPONSE_KIND,
    ANCHOR_SERVICE_SCHEMA_VERSION,
    BrokerClientError,
    BrokerReceiptError,
    BrokerStateError,
    ConsumerAnchor,
    ProtectedAnchorClient,
    ReceiptConsumer,
    ReleaseEvidence,
    VerificationKeyEpoch,
    protocol,
)

ANCHOR_LOG_KIND = "w3-protected-anchor-log-record"
ANCHOR_LOG_DOMAIN = "w3-protected-anchor/log-record/v1"
ANCHOR_LOG_GENESIS_DIGEST = protocol.SHA256_PREFIX + "0" * 64
ANCHOR_LOG_MAX_RECORD_BYTES = protocol.MAX_PAYLOAD_BYTES
ANCHOR_LISTENER_FD = 3
ANCHOR_CONNECTION_TIMEOUT_SECONDS = 5.0
ANCHOR_SOCKET_PATH = "/var/run/metis-model1/w3-anchor.sock"
INSTALLED_CALLER_UID = 501
INSTALLED_CALLER_GID = 20

# Darwin exposes AF_UNIX peer credentials as ``struct xucred`` through
# getsockopt(SOL_LOCAL, LOCAL_PEERCRED).  CPython does not expose getpeereid().
SOL_LOCAL = 0
XUCRED_VERSION = 0
XUCRED_FORMAT = "@IIh2x16I"
XUCRED_BYTES = struct.calcsize(XUCRED_FORMAT)

INSTALLED_CONFIG_PATH = Path(
    "/Library/Application Support/MetisModel1/anchor/config/w3-anchor-config.json"
)
INSTALLED_ACTIVE_AUTHORITY_PATH = Path(
    "/Library/Application Support/MetisModel1/registry/protected-authority.json"
)
INSTALLED_LOG_PATH = Path(
    "/Library/Application Support/MetisModel1/state/anchor/consumer-anchor.log"
)

_RECORD_FIELDS = (
    "schema_version",
    "kind",
    "record_sequence",
    "previous_record_sha256",
    "record_kind",
    "payload",
    "record_sha256",
)
_GENESIS_PAYLOAD_FIELDS = ("anchor",)
_ADVANCE_PAYLOAD_FIELDS = (
    "expected_anchor_sha256",
    "receipt_sha256",
    "receipt",
    "anchor",
)
_REQUEST_FIELDS = (
    "schema_version",
    "kind",
    "operation",
    "expected_anchor_sha256",
    "canonical_receipt",
)
_CONFIG_FIELDS = (
    "schema_version",
    "kind",
    "active_authority_path",
    "active_authority_sha256",
    "genesis_anchor_sha256",
    "anchor_uid",
    "anchor_gid",
    "caller_uid",
    "caller_gid",
    "authorities",
    "key_epochs",
    "releases",
    "registered_policy_sha256s",
)


class AnchorServiceError(RuntimeError):
    """Stable fail-closed service error."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(code if not detail else f"{code}: {detail}")


class _VerificationOnlyTransport:
    """Receipt verification never invokes the protected mutation transport."""

    def exchange(self, canonical_request: bytes) -> bytes:
        raise BrokerStateError("anchor-verification-transport-forbidden")


def _exact_mapping(value: object, fields: tuple[str, ...], scope: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != set(fields):
        raise AnchorServiceError("anchor-invalid", f"{scope} fields")
    return value


def _strict_int(value: object, scope: str, *, minimum: int) -> int:
    if type(value) is not int or value < minimum:
        raise AnchorServiceError("anchor-invalid", scope)
    return value


def _digest(value: object, scope: str) -> str:
    if type(value) is not str:
        raise AnchorServiceError("anchor-invalid", scope)
    try:
        protocol.digest_to_bytes(value)
    except protocol.BrokerProtocolError as error:
        raise AnchorServiceError("anchor-invalid", scope) from error
    return value


def _anchor_from_value(value: object) -> ConsumerAnchor:
    try:
        return ConsumerAnchor.from_bytes(protocol.canonical_bytes(value))
    except (BrokerClientError, protocol.BrokerProtocolError, TypeError, ValueError) as error:
        raise AnchorServiceError("anchor-invalid", "anchor document") from error


def _record_material(
    *,
    record_sequence: int,
    previous_record_sha256: str,
    record_kind: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    return {
        "schema_version": ANCHOR_SERVICE_SCHEMA_VERSION,
        "kind": ANCHOR_LOG_KIND,
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
    return {**material, "record_sha256": protocol.domain_digest(ANCHOR_LOG_DOMAIN, material)}


def encode_genesis_log(anchor: ConsumerAnchor) -> bytes:
    """Pure installer helper; returns bytes but performs no initialization write."""

    if not isinstance(anchor, ConsumerAnchor) or anchor.revision != 0 or anchor.heads:
        raise AnchorServiceError("anchor-genesis-invalid")
    record = _build_record(
        record_sequence=1,
        previous_record_sha256=ANCHOR_LOG_GENESIS_DIGEST,
        record_kind="genesis",
        payload={"anchor": anchor.to_document()},
    )
    body = protocol.canonical_bytes(record)
    return struct.pack(">I", len(body)) + body


def _write_all(descriptor: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise AnchorServiceError("anchor-write-failed", "short write")
        view = view[written:]


def _read_at(descriptor: int, offset: int, count: int) -> bytes:
    chunks: list[bytes] = []
    remaining = count
    position = offset
    while remaining:
        chunk = os.pread(descriptor, remaining, position)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
        position += len(chunk)
    return b"".join(chunks)


def _validate_record(
    value: object, *, expected_sequence: int, expected_previous: str
) -> dict[str, object]:
    record = _exact_mapping(value, _RECORD_FIELDS, "record")
    if (
        record["schema_version"] != ANCHOR_SERVICE_SCHEMA_VERSION
        or record["kind"] != ANCHOR_LOG_KIND
    ):
        raise AnchorServiceError("anchor-log-corrupt", "record identity")
    if _strict_int(record["record_sequence"], "record sequence", minimum=1) != expected_sequence:
        raise AnchorServiceError("anchor-log-corrupt", "record sequence")
    if record["previous_record_sha256"] != expected_previous:
        raise AnchorServiceError("anchor-log-corrupt", "record chain")
    if record["record_kind"] not in {"genesis", "advance"}:
        raise AnchorServiceError("anchor-log-corrupt", "record kind")
    material = {key: record[key] for key in _RECORD_FIELDS if key != "record_sha256"}
    if record["record_sha256"] != protocol.domain_digest(ANCHOR_LOG_DOMAIN, material):
        raise AnchorServiceError("anchor-log-corrupt", "record digest")
    return record


def _read_records(descriptor: int) -> list[dict[str, object]]:
    size = os.fstat(descriptor).st_size
    if size <= 0:
        raise AnchorServiceError("anchor-genesis-missing")
    offset = 0
    expected_sequence = 1
    expected_previous = ANCHOR_LOG_GENESIS_DIGEST
    records: list[dict[str, object]] = []
    while offset < size:
        prefix = _read_at(descriptor, offset, 4)
        if len(prefix) != 4:
            raise AnchorServiceError("anchor-log-torn", "length prefix")
        length = struct.unpack(">I", prefix)[0]
        if length == 0 or length > ANCHOR_LOG_MAX_RECORD_BYTES:
            raise AnchorServiceError("anchor-log-corrupt", "record length")
        payload = _read_at(descriptor, offset + 4, length)
        if len(payload) != length:
            raise AnchorServiceError("anchor-log-torn", "record body")
        try:
            value = protocol.parse_canonical_json(payload)
        except protocol.BrokerProtocolError as error:
            raise AnchorServiceError("anchor-log-corrupt", error.reason) from error
        record = _validate_record(
            value,
            expected_sequence=expected_sequence,
            expected_previous=expected_previous,
        )
        records.append(record)
        expected_sequence += 1
        expected_previous = str(record["record_sha256"])
        offset += 4 + length
    if offset != size:
        raise AnchorServiceError("anchor-log-corrupt", "trailing bytes")
    return records


class ProtectedAnchorService:
    """Single-writer protected anchor with independent receipt verification."""

    def __init__(
        self,
        *,
        log_path: str | Path,
        genesis_anchor_sha256: str,
        anchor_uid: int,
        anchor_gid: int,
        caller_uid: int,
        caller_gid: int,
        authorities: Iterable[Mapping[str, object]],
        key_epochs: Iterable[VerificationKeyEpoch],
        releases: Iterable[ReleaseEvidence],
        registered_policy_sha256s: Iterable[str],
        allow_unprotected_test_storage: bool = False,
    ):
        path = Path(log_path)
        if not path.is_absolute():
            raise AnchorServiceError("anchor-path-not-absolute")
        _digest(genesis_anchor_sha256, "genesis anchor digest")
        if type(anchor_uid) is not int or anchor_uid < 0:
            raise AnchorServiceError("anchor-owner-invalid", "uid")
        if type(anchor_gid) is not int or anchor_gid < 0:
            raise AnchorServiceError("anchor-owner-invalid", "gid")
        if type(caller_uid) is not int or caller_uid < 0:
            raise AnchorServiceError("anchor-caller-invalid", "uid")
        if type(caller_gid) is not int or caller_gid < 0:
            raise AnchorServiceError("anchor-caller-invalid", "gid")
        if type(allow_unprotected_test_storage) is not bool:
            raise AnchorServiceError("anchor-storage-configuration-invalid")
        authority_documents = [dict(authority) for authority in authorities]
        if not authority_documents or any(
            authority.get("mode") != protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC
            for authority in authority_documents
        ):
            raise AnchorServiceError("anchor-authority-mode-invalid")
        key_documents = list(key_epochs)
        if not key_documents or any(
            epoch.mode != protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC for epoch in key_documents
        ):
            raise AnchorServiceError("anchor-key-mode-invalid")

        self._log_path = path
        self._genesis_anchor_sha256 = genesis_anchor_sha256
        self._anchor_uid = anchor_uid
        self._anchor_gid = anchor_gid
        self._caller_uid = caller_uid
        self._caller_gid = caller_gid
        self._allow_unprotected_test_storage = allow_unprotected_test_storage
        self._pinned_parent_identity: tuple[int, int] | None = None
        self._pinned_leaf_identity: tuple[int, int] | None = None
        verification_anchor = ConsumerAnchor(instance_id="0" * 64, revision=0)
        verification_client = ProtectedAnchorClient(
            transport=_VerificationOnlyTransport(),
            initial_anchor=verification_anchor,
        )
        self._verifier = ReceiptConsumer(
            anchor_store=None,
            protected_anchor=verification_client,
            authorities=authority_documents,
            key_epochs=key_documents,
            releases=list(releases),
            registered_policy_sha256s=list(registered_policy_sha256s),
        )
        with self._locked_log() as (descriptor, _parent_descriptor):
            records = _read_records(descriptor)
            self._recover(records)

    def _open_parent(self) -> int:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        flags |= getattr(os, "O_DIRECTORY", 0)
        parent = self._log_path.parent
        if self._allow_unprotected_test_storage:
            try:
                info = parent.lstat()
                descriptor = os.open(parent, flags)
            except OSError as error:
                raise AnchorServiceError("anchor-parent-unavailable", str(error)) from error
            opened = os.fstat(descriptor)
            if (
                stat.S_ISLNK(info.st_mode)
                or not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.geteuid()
                or info.st_mode & 0o022
                or (info.st_dev, info.st_ino) != (opened.st_dev, opened.st_ino)
            ):
                os.close(descriptor)
                raise AnchorServiceError("anchor-parent-unsafe")
            return descriptor

        current = -1
        try:
            current = os.open("/", flags)
            root = os.fstat(current)
            if not stat.S_ISDIR(root.st_mode) or root.st_uid != 0 or root.st_mode & 0o022:
                raise AnchorServiceError("anchor-parent-unsafe")
            for component in parent.parts[1:]:
                if component in {"", ".", ".."}:
                    raise AnchorServiceError("anchor-parent-unsafe")
                following = os.open(component, flags, dir_fd=current)
                os.close(current)
                current = following
                info = os.fstat(current)
                if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                    raise AnchorServiceError("anchor-parent-unsafe")
            return current
        except AnchorServiceError:
            if current >= 0:
                os.close(current)
            raise
        except OSError as error:
            if current >= 0:
                os.close(current)
            raise AnchorServiceError("anchor-parent-unavailable", str(error)) from error

    def _verify_parent(self, descriptor: int) -> None:
        opened = os.fstat(descriptor)
        try:
            named = os.stat(self._log_path.parent, follow_symlinks=False)
        except OSError as error:
            raise AnchorServiceError("anchor-parent-replaced", str(error)) from error
        expected_uid = os.geteuid() if self._allow_unprotected_test_storage else 0
        identity = (opened.st_dev, opened.st_ino)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or not stat.S_ISDIR(named.st_mode)
            or opened.st_uid != expected_uid
            or named.st_uid != expected_uid
            or opened.st_mode & 0o022
            or named.st_mode & 0o022
            or identity != (named.st_dev, named.st_ino)
        ):
            raise AnchorServiceError("anchor-parent-replaced")
        if self._pinned_parent_identity is None:
            self._pinned_parent_identity = identity
        elif self._pinned_parent_identity != identity:
            raise AnchorServiceError("anchor-parent-replaced")

    def _verify_leaf(self, descriptor: int, parent_descriptor: int) -> None:
        opened = os.fstat(descriptor)
        try:
            named = os.stat(
                self._log_path.name,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as error:
            raise AnchorServiceError("anchor-log-replaced", str(error)) from error
        identity = (opened.st_dev, opened.st_ino)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o600
            or stat.S_IMODE(named.st_mode) != 0o600
            or opened.st_nlink != 1
            or named.st_nlink != 1
            or opened.st_uid != self._anchor_uid
            or opened.st_gid != self._anchor_gid
            or named.st_uid != self._anchor_uid
            or named.st_gid != self._anchor_gid
            or identity != (named.st_dev, named.st_ino)
        ):
            raise AnchorServiceError("anchor-log-replaced")
        if self._pinned_leaf_identity is None:
            self._pinned_leaf_identity = identity
        elif self._pinned_leaf_identity != identity:
            raise AnchorServiceError("anchor-log-replaced")

    @contextmanager
    def _locked_log(self) -> Iterator[tuple[int, int]]:
        parent_descriptor = self._open_parent()
        descriptor = -1
        try:
            self._verify_parent(parent_descriptor)
            flags = (
                os.O_RDWR | os.O_APPEND | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            )
            try:
                descriptor = os.open(self._log_path.name, flags, dir_fd=parent_descriptor)
            except FileNotFoundError as error:
                raise AnchorServiceError("anchor-genesis-missing") from error
            except OSError as error:
                raise AnchorServiceError("anchor-log-unavailable", str(error)) from error
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            self._verify_leaf(descriptor, parent_descriptor)
            self._verify_parent(parent_descriptor)
            try:
                yield descriptor, parent_descriptor
            finally:
                self._verify_parent(parent_descriptor)
                self._verify_leaf(descriptor, parent_descriptor)
        finally:
            if descriptor >= 0:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)
            os.close(parent_descriptor)

    def _recover(
        self, records: list[dict[str, object]]
    ) -> tuple[ConsumerAnchor, dict[str, object] | None]:
        if not records or records[0]["record_kind"] != "genesis":
            raise AnchorServiceError("anchor-genesis-missing")
        genesis_payload = _exact_mapping(records[0]["payload"], _GENESIS_PAYLOAD_FIELDS, "genesis")
        anchor = _anchor_from_value(genesis_payload["anchor"])
        if anchor.revision != 0 or anchor.heads or anchor.digest() != self._genesis_anchor_sha256:
            raise AnchorServiceError("anchor-genesis-mismatch")
        last_advance: dict[str, object] | None = None
        for record in records[1:]:
            if record["record_kind"] != "advance":
                raise AnchorServiceError("anchor-log-corrupt", "genesis not first-only")
            payload = _exact_mapping(record["payload"], _ADVANCE_PAYLOAD_FIELDS, "advance")
            if _digest(payload["expected_anchor_sha256"], "expected anchor") != anchor.digest():
                raise AnchorServiceError("anchor-log-corrupt", "stored CAS mismatch")
            if not isinstance(payload["receipt"], dict):
                raise AnchorServiceError("anchor-log-corrupt", "stored receipt")
            try:
                receipt = self._verifier.verify_only(payload["receipt"])
            except BrokerClientError as error:
                raise AnchorServiceError("anchor-log-corrupt", error.reason) from error
            receipt_sha256 = protocol.receipt_hash(receipt)
            if payload["receipt_sha256"] != receipt_sha256:
                raise AnchorServiceError("anchor-log-corrupt", "stored receipt digest")
            derived = anchor.advanced(
                authority_id=protocol.AUTHORITY_ID,
                receipt_sequence=int(receipt["receipt_sequence"]),
                previous_receipt_sha256=str(receipt["previous_receipt_sha256"]),
                receipt_sha256=receipt_sha256,
            )
            persisted = _anchor_from_value(payload["anchor"])
            if persisted.digest() != derived.digest():
                raise AnchorServiceError("anchor-log-corrupt", "stored derived anchor")
            anchor = persisted
            last_advance = payload
        return anchor, last_advance

    @staticmethod
    def _append_record(
        descriptor: int,
        parent_descriptor: int,
        records: list[dict[str, object]],
        payload: Mapping[str, object],
    ) -> None:
        record = _build_record(
            record_sequence=len(records) + 1,
            previous_record_sha256=str(records[-1]["record_sha256"]),
            record_kind="advance",
            payload=payload,
        )
        body = protocol.canonical_bytes(record)
        if len(body) > ANCHOR_LOG_MAX_RECORD_BYTES:
            raise AnchorServiceError("anchor-record-too-large")
        _write_all(descriptor, struct.pack(">I", len(body)) + body)
        os.fsync(descriptor)
        os.fsync(parent_descriptor)

    def advance(
        self, expected_anchor_sha256: str, canonical_receipt: Mapping[str, object]
    ) -> tuple[str, ConsumerAnchor]:
        _digest(expected_anchor_sha256, "expected anchor")
        if not isinstance(canonical_receipt, dict):
            raise AnchorServiceError("anchor-request-invalid", "canonical receipt")
        with self._locked_log() as (descriptor, parent_descriptor):
            records = _read_records(descriptor)
            current, last_advance = self._recover(records)
            try:
                receipt = self._verifier.verify_only(canonical_receipt)
            except BrokerReceiptError as error:
                raise AnchorServiceError(error.reason, error.detail) from error
            receipt_sha256 = protocol.receipt_hash(receipt)
            head = current.head_for(protocol.AUTHORITY_ID)
            if (
                head is not None
                and head.receipt_sequence == receipt["receipt_sequence"]
                and head.receipt_sha256 == receipt_sha256
            ):
                original_expected = (
                    str(last_advance["expected_anchor_sha256"])
                    if last_advance is not None
                    else current.digest()
                )
                if expected_anchor_sha256 not in {current.digest(), original_expected}:
                    raise AnchorServiceError("anchor-cas-mismatch")
                return "idempotent", current
            if expected_anchor_sha256 != current.digest():
                raise AnchorServiceError("anchor-cas-mismatch")
            try:
                derived = current.advanced(
                    authority_id=protocol.AUTHORITY_ID,
                    receipt_sequence=int(receipt["receipt_sequence"]),
                    previous_receipt_sha256=str(receipt["previous_receipt_sha256"]),
                    receipt_sha256=receipt_sha256,
                )
            except BrokerReceiptError as error:
                raise AnchorServiceError(error.reason, error.detail) from error
            payload = {
                "expected_anchor_sha256": expected_anchor_sha256,
                "receipt_sha256": receipt_sha256,
                "receipt": receipt,
                "anchor": derived.to_document(),
            }
            self._append_record(descriptor, parent_descriptor, records, payload)
            return "advanced", derived

    @staticmethod
    def _response(status: str, anchor: ConsumerAnchor) -> bytes:
        return protocol.canonical_bytes(
            {
                "schema_version": ANCHOR_SERVICE_SCHEMA_VERSION,
                "kind": ANCHOR_SERVICE_RESPONSE_KIND,
                "operation": ANCHOR_SERVICE_OPERATION,
                "status": status,
                "anchor": anchor.to_document(),
            }
        )

    @staticmethod
    def _error(error: AnchorServiceError) -> bytes:
        return protocol.canonical_bytes(
            {
                "schema_version": ANCHOR_SERVICE_SCHEMA_VERSION,
                "kind": ANCHOR_SERVICE_RESPONSE_KIND,
                "operation": ANCHOR_SERVICE_OPERATION,
                "status": "error",
                "error": {"code": error.code, "detail": error.detail},
            }
        )

    def handle(self, canonical_request: bytes) -> bytes:
        try:
            try:
                parsed = protocol.parse_canonical_json(canonical_request)
            except protocol.BrokerProtocolError as error:
                raise AnchorServiceError("anchor-request-invalid", error.reason) from error
            request = _exact_mapping(parsed, _REQUEST_FIELDS, "request")
            if (
                request["schema_version"] != ANCHOR_SERVICE_SCHEMA_VERSION
                or request["kind"] != ANCHOR_SERVICE_REQUEST_KIND
                or request["operation"] != ANCHOR_SERVICE_OPERATION
            ):
                raise AnchorServiceError("anchor-request-invalid", "identity or operation")
            status, anchor = self.advance(
                _digest(request["expected_anchor_sha256"], "expected anchor"),
                request["canonical_receipt"],
            )
            return self._response(status, anchor)
        except AnchorServiceError as error:
            return self._error(error)
        except BrokerClientError as error:
            return self._error(AnchorServiceError(error.reason, error.detail))


def _read_socket_frame(connection: socket.socket) -> bytes:
    prefix = b""
    while len(prefix) < 4:
        chunk = connection.recv(4 - len(prefix))
        if not chunk:
            raise AnchorServiceError("anchor-frame-truncated", "length prefix")
        prefix += chunk
    length = struct.unpack(">I", prefix)[0]
    if length == 0 or length > protocol.MAX_PAYLOAD_BYTES:
        raise AnchorServiceError("anchor-frame-invalid", "length")
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        chunk = connection.recv(min(remaining, 64 * 1024))
        if not chunk:
            raise AnchorServiceError("anchor-frame-truncated", "body")
        chunks.append(chunk)
        remaining -= len(chunk)
    if connection.recv(1):
        raise AnchorServiceError("anchor-frame-invalid", "trailing bytes")
    return b"".join(chunks)


def _write_socket_frame(connection: socket.socket, payload: bytes) -> None:
    connection.sendall(struct.pack(">I", len(payload)) + payload)


def _read_root_owned_document(path: Path, *, scope: str) -> object:
    unsafe_code = f"{scope}-unsafe"
    invalid_code = f"{scope}-invalid"
    unavailable_code = f"{scope}-unavailable"
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise AnchorServiceError(unsafe_code)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_DIRECTORY", 0)
    current = -1
    descriptor = -1
    try:
        current = os.open("/", flags)
        root_info = os.fstat(current)
        if (
            not stat.S_ISDIR(root_info.st_mode)
            or root_info.st_uid != 0
            or root_info.st_mode & 0o022
        ):
            raise AnchorServiceError(unsafe_code)
        for component in path.parent.parts[1:]:
            if component in {"", ".", ".."}:
                raise AnchorServiceError(unsafe_code)
            following = os.open(component, flags, dir_fd=current)
            os.close(current)
            current = following
            info = os.fstat(current)
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise AnchorServiceError(unsafe_code)
        leaf_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path.name, leaf_flags, dir_fd=current)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != 0
            or info.st_gid != 0
            or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o444
            or info.st_size <= 0
            or info.st_size > protocol.MAX_PAYLOAD_BYTES
        ):
            raise AnchorServiceError(unsafe_code)
        chunks: list[bytes] = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(remaining, 64 * 1024))
            if not chunk:
                raise AnchorServiceError(invalid_code, "truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise AnchorServiceError(invalid_code, "grew during read")
        final_info = os.fstat(descriptor)
        named_info = os.stat(path.name, dir_fd=current, follow_symlinks=False)
        identity_fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_nlink",
            "st_size",
        )
        if any(
            getattr(final_info, field) != getattr(info, field) for field in identity_fields
        ) or any(getattr(named_info, field) != getattr(info, field) for field in identity_fields):
            raise AnchorServiceError(unsafe_code, "named identity changed")
        try:
            value = protocol.parse_canonical_json(b"".join(chunks))
        except protocol.BrokerProtocolError as error:
            raise AnchorServiceError(invalid_code, error.reason) from error
        return value
    except AnchorServiceError:
        raise
    except OSError as error:
        raise AnchorServiceError(unavailable_code, str(error)) from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if current >= 0:
            os.close(current)


def _read_root_owned_config(path: Path) -> dict[str, object]:
    value = _read_root_owned_document(path, scope="anchor-config")
    if not isinstance(value, dict) or set(value) != set(_CONFIG_FIELDS):
        raise AnchorServiceError("anchor-config-invalid", "installed config fields")
    return value


def _validate_active_authority(value: object) -> dict[str, object]:
    try:
        canonical = protocol.parse_canonical_json(protocol.canonical_bytes(value))
        authority = protocol.validate_authority(canonical)
    except (protocol.BrokerProtocolError, TypeError, ValueError) as error:
        detail = error.reason if isinstance(error, protocol.BrokerProtocolError) else str(error)
        raise AnchorServiceError("anchor-active-authority-invalid", detail) from error
    if authority["mode"] != protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC:
        raise AnchorServiceError("anchor-active-authority-invalid", "mode")
    return authority


def _read_active_authority(path: Path) -> dict[str, object]:
    return _validate_active_authority(
        _read_root_owned_document(path, scope="anchor-active-authority")
    )


def _installed_service() -> ProtectedAnchorService:
    config = _read_root_owned_config(INSTALLED_CONFIG_PATH)
    if (
        config["schema_version"] != ANCHOR_SERVICE_SCHEMA_VERSION
        or config["kind"] != "w3-protected-anchor-installed-config"
        or config["active_authority_path"] != str(INSTALLED_ACTIVE_AUTHORITY_PATH)
        or config["caller_uid"] != INSTALLED_CALLER_UID
        or config["caller_gid"] != INSTALLED_CALLER_GID
    ):
        raise AnchorServiceError("anchor-config-invalid", "identity")
    try:
        expected_authority_sha256 = _digest(
            config["active_authority_sha256"], "active authority digest"
        )
    except AnchorServiceError as error:
        raise AnchorServiceError("anchor-config-invalid", "active authority digest") from error
    active_authority = _validate_active_authority(
        _read_active_authority(INSTALLED_ACTIVE_AUTHORITY_PATH)
    )
    active_authority_sha256 = protocol.authority_hash(active_authority)
    if active_authority_sha256 != expected_authority_sha256:
        raise AnchorServiceError("anchor-active-authority-mismatch", "digest")
    authorities = config["authorities"]
    key_rows = config["key_epochs"]
    release_rows = config["releases"]
    policies = config["registered_policy_sha256s"]
    if (
        not isinstance(authorities, list)
        or len(authorities) != 1
        or not isinstance(key_rows, list)
        or not isinstance(release_rows, list)
        or not isinstance(policies, list)
    ):
        raise AnchorServiceError("anchor-config-invalid", "registries")
    try:
        configured_authority = _validate_active_authority(authorities[0])
    except AnchorServiceError as error:
        raise AnchorServiceError("anchor-config-invalid", "authority registry") from error
    if protocol.canonical_bytes(configured_authority) != protocol.canonical_bytes(active_authority):
        raise AnchorServiceError("anchor-active-authority-mismatch", "authority registry")
    keys: list[VerificationKeyEpoch] = []
    for row in key_rows:
        body = _exact_mapping(
            row,
            ("mode", "algorithm", "key_id", "public_key", "revocation_high_water"),
            "key epoch",
        )
        try:
            public_key = protocol.ed25519.decode_public_key(body["public_key"])
        except protocol.ed25519.Ed25519ContractError as error:
            raise AnchorServiceError("anchor-config-invalid", error.reason) from error
        keys.append(
            VerificationKeyEpoch(
                key_id=str(body["key_id"]),
                algorithm=str(body["algorithm"]),
                public_key=public_key,
                revocation_high_water=body["revocation_high_water"],
                mode=str(body["mode"]),
            )
        )
    signing = active_authority["signing"]
    try:
        active_public_key = protocol.ed25519.decode_public_key(signing["public_key"])
    except protocol.ed25519.Ed25519ContractError as error:
        raise AnchorServiceError("anchor-active-authority-invalid", error.reason) from error
    active_keys = [
        key
        for key in keys
        if key.mode == active_authority["mode"]
        and key.algorithm == signing["algorithm"]
        and key.key_id == signing["key_id"]
        and key.public_key == active_public_key
        and key.revocation_high_water is None
    ]
    if len(active_keys) != 1:
        raise AnchorServiceError("anchor-config-invalid", "active key registry")
    releases: list[ReleaseEvidence] = []
    for row in release_rows:
        body = _exact_mapping(
            row,
            (
                "authority_sha256",
                "release_id",
                "release_sha256",
                "retired_after_receipt_sequence",
            ),
            "release evidence",
        )
        releases.append(
            ReleaseEvidence(
                authority_sha256=str(body["authority_sha256"]),
                release_id=str(body["release_id"]),
                release_sha256=str(body["release_sha256"]),
                retired_after_receipt_sequence=body["retired_after_receipt_sequence"],
            )
        )
    release_identity = active_authority["release_identity"]
    active_releases = [
        release
        for release in releases
        if release.authority_sha256 == active_authority_sha256
        and release.release_id == release_identity["release_id"]
        and release.release_sha256 == release_identity["ancestry_root_sha256"]
        and release.retired_after_receipt_sequence is None
    ]
    if len(active_releases) != 1:
        raise AnchorServiceError("anchor-config-invalid", "active release registry")
    try:
        policy_digests = [_digest(policy, "registered policy") for policy in policies]
    except AnchorServiceError as error:
        raise AnchorServiceError("anchor-config-invalid", "policy registry") from error
    if len(policy_digests) != len(set(policy_digests)) or (
        active_authority["policy_identity"]["resolved_sha256"] not in policy_digests
    ):
        raise AnchorServiceError("anchor-config-invalid", "active policy registry")
    return ProtectedAnchorService(
        log_path=INSTALLED_LOG_PATH,
        genesis_anchor_sha256=str(config["genesis_anchor_sha256"]),
        anchor_uid=config["anchor_uid"],
        anchor_gid=config["anchor_gid"],
        caller_uid=config["caller_uid"],
        caller_gid=config["caller_gid"],
        authorities=[active_authority],
        key_epochs=keys,
        releases=releases,
        registered_policy_sha256s=policy_digests,
    )


def _verify_caller_peer(
    connection: object,
    *,
    expected_uid: int,
    expected_gid: int,
) -> None:
    getsockopt = getattr(connection, "getsockopt", None)
    if not callable(getsockopt):
        raise AnchorServiceError("anchor-peer-credentials-unavailable")
    try:
        raw = getsockopt(SOL_LOCAL, socket.LOCAL_PEERCRED, XUCRED_BYTES)
        if not isinstance(raw, bytes | bytearray) or len(raw) != XUCRED_BYTES:
            raise AnchorServiceError("anchor-peer-credentials-unavailable")
        version, uid, group_count, gid, *_groups = struct.unpack(XUCRED_FORMAT, bytes(raw))
    except (OSError, struct.error) as error:
        raise AnchorServiceError("anchor-peer-credentials-unavailable", str(error)) from error
    if version != XUCRED_VERSION or group_count < 1:
        raise AnchorServiceError("anchor-peer-credentials-unavailable")
    if uid != expected_uid or gid != expected_gid:
        raise AnchorServiceError("anchor-peer-not-authorized")


def serve_inherited_fd3(service: ProtectedAnchorService) -> None:
    """Serve the one exact launchd AF_UNIX/SOCK_STREAM listener inherited as FD3."""

    listener = socket.socket(fileno=ANCHOR_LISTENER_FD)
    try:
        try:
            bound_path = listener.getsockname()
        except OSError as error:
            raise AnchorServiceError("anchor-listener-invalid", str(error)) from error
        if (
            listener.family != socket.AF_UNIX
            or listener.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) != socket.SOCK_STREAM
            or bound_path != ANCHOR_SOCKET_PATH
        ):
            raise AnchorServiceError("anchor-listener-invalid")
        while True:
            connection, _peer = listener.accept()
            with connection:
                connection.settimeout(ANCHOR_CONNECTION_TIMEOUT_SECONDS)
                try:
                    _verify_caller_peer(
                        connection,
                        expected_uid=service._caller_uid,
                        expected_gid=service._caller_gid,
                    )
                    response = service.handle(_read_socket_frame(connection))
                except AnchorServiceError as error:
                    response = service._error(error)
                except OSError as error:
                    response = service._error(AnchorServiceError("anchor-frame-io", str(error)))
                try:
                    _write_socket_frame(connection, response)
                except OSError:
                    continue
    finally:
        listener.close()


def main() -> int:
    try:
        service = _installed_service()
        serve_inherited_fd3(service)
    except (AnchorServiceError, BrokerClientError, OSError):
        os.write(2, b"w3 protected anchor service: fail closed\n")
        return 78
    return 0


__all__ = [
    "ANCHOR_LISTENER_FD",
    "ANCHOR_LOG_KIND",
    "ANCHOR_SOCKET_PATH",
    "AnchorServiceError",
    "ProtectedAnchorService",
    "encode_genesis_log",
    "serve_inherited_fd3",
]


if __name__ == "__main__":
    raise SystemExit(main())
