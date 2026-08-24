"""Payload-free Phase A client and receipt consumer for the W3 broker.

The client sends one canonical request byte string through a caller-provided
transport.  It never accepts executable paths, argv, environment values or
file descriptors.  The consumer verifies public-synthetic receipts against
out-of-band authority, release, policy and key registrations, then persists a
contiguous receipt-chain head before returning success.

L70 adds Ed25519 verification only for the disjoint
``protected-public-synthetic`` evidence mode.  Production remains
unconditionally unavailable.  A protected consumer sends the anchor service
only the expected anchor digest and the canonical receipt; the service derives
the next anchor independently.
"""

from __future__ import annotations

import os
import secrets
import stat
import sys
import threading
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from fcntl import LOCK_EX, LOCK_UN, flock
from importlib import util as importlib_util
from pathlib import Path
from types import ModuleType
from typing import Protocol


def _source_tree_protocol() -> ModuleType:
    source_root = Path(__file__).resolve().parent.parent
    if source_root.name != "src":
        raise ImportError("installed broker client requires packaged runtime.w3_broker_protocol")
    repository_root = source_root.parent
    path = repository_root / "runtime" / "w3_broker_protocol.py"
    if not path.is_file() or path.resolve().parent != (repository_root / "runtime").resolve():
        raise ImportError("source-tree broker protocol is unavailable")
    name = "metis_model1._source_tree_w3_broker_protocol"
    existing = sys.modules.get(name)
    if existing is not None:
        return existing
    specification = importlib_util.spec_from_file_location(name, path)
    if specification is None or specification.loader is None:
        raise ImportError("source-tree broker protocol cannot be loaded")
    module = importlib_util.module_from_spec(specification)
    sys.modules[name] = module
    try:
        specification.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


try:
    from runtime import w3_broker_protocol as protocol
except ModuleNotFoundError as error:
    if error.name != "runtime":
        raise
    protocol = _source_tree_protocol()

ANCHOR_SCHEMA_VERSION = 1
ANCHOR_KIND = "w3-protected-broker-consumer-anchor"
ANCHOR_DIGEST_DOMAIN = "w3-protected-broker/consumer-anchor/v1"
MAX_ANCHOR_BYTES = 1024 * 1024
ANCHOR_SERVICE_SCHEMA_VERSION = 1
ANCHOR_SERVICE_REQUEST_KIND = "w3-protected-anchor-service-request"
ANCHOR_SERVICE_RESPONSE_KIND = "w3-protected-anchor-service-response"
ANCHOR_SERVICE_OPERATION = "ADVANCE"
PROTECTED_RECEIPT_JOURNAL_MAX_BYTES = 64 * 1024 * 1024
PROTECTED_RECEIPT_JOURNAL_MAX_ENTRIES = 65_536


class BrokerClientError(ValueError):
    """Typed client failure with a stable machine-readable reason."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(reason if not detail else f"{reason}: {detail}")


class BrokerRequestError(BrokerClientError):
    """The caller request violates the canonical claims-only contract."""


class BrokerTransportError(BrokerClientError):
    """The byte-only broker transport failed or returned an invalid response."""


class BrokerReceiptError(BrokerClientError):
    """A receipt failed validation, registration, signature or chain checks."""


class BrokerStateError(BrokerClientError):
    """The durable consumer high-water state is unavailable or malformed."""


class BrokerTransport(Protocol):
    """Byte-only broker boundary; no path, argv, env or FD parameters exist."""

    def exchange(self, canonical_request: bytes) -> bytes:
        """Return one canonical receipt byte string for one canonical request."""


def _protocol_detail(error: protocol.BrokerProtocolError) -> str:
    return error.reason if not error.detail else f"{error.reason}: {error.detail}"


def _require_digest(value: object, label: str) -> str:
    try:
        protocol.digest_to_bytes(str(value))
    except protocol.BrokerProtocolError as error:
        raise BrokerClientError("configuration-invalid", label) from error
    if type(value) is not str:
        raise BrokerClientError("configuration-invalid", label)
    return value


def _read_protected_receipt_journal(
    journal: bytes | Iterable[Mapping[str, object]],
) -> tuple[dict[str, object], ...]:
    """Read a bounded public journal without creating a second journal writer."""

    receipts: list[dict[str, object]] = []
    if isinstance(journal, bytes):
        if not journal:
            raise BrokerStateError("protected-journal-empty")
        if len(journal) > PROTECTED_RECEIPT_JOURNAL_MAX_BYTES:
            raise BrokerStateError("protected-journal-oversize")
        offset = 0
        while offset < len(journal):
            if len(receipts) >= PROTECTED_RECEIPT_JOURNAL_MAX_ENTRIES:
                raise BrokerStateError("protected-journal-oversize", "entry count")
            if len(journal) - offset < 4:
                raise BrokerStateError("protected-journal-truncated", "length prefix")
            length = int.from_bytes(journal[offset : offset + 4], "big")
            if length == 0 or length > protocol.MAX_PAYLOAD_BYTES:
                raise BrokerStateError("protected-journal-invalid", "entry length")
            offset += 4
            end = offset + length
            if end > len(journal):
                raise BrokerStateError("protected-journal-truncated", "receipt body")
            try:
                value = protocol.parse_canonical_json(journal[offset:end])
            except protocol.BrokerProtocolError as error:
                raise BrokerStateError(
                    "protected-journal-invalid", _protocol_detail(error)
                ) from error
            if not isinstance(value, dict):
                raise BrokerStateError("protected-journal-invalid", "receipt must be an object")
            receipts.append(value)
            offset = end
    else:
        if isinstance(journal, (str, bytearray, memoryview, Mapping)):
            raise BrokerStateError("protected-journal-invalid", "journal type")
        try:
            iterator = iter(journal)
        except TypeError as error:
            raise BrokerStateError("protected-journal-invalid", "journal iterable") from error
        total_bytes = 0
        while True:
            try:
                candidate = next(iterator)
            except StopIteration:
                break
            except Exception as error:
                raise BrokerStateError("protected-journal-invalid", "journal iteration") from error
            if len(receipts) >= PROTECTED_RECEIPT_JOURNAL_MAX_ENTRIES:
                raise BrokerStateError("protected-journal-oversize", "entry count")
            if not isinstance(candidate, Mapping):
                raise BrokerStateError("protected-journal-invalid", "receipt must be an object")
            try:
                canonical = protocol.canonical_bytes(dict(candidate))
                value = protocol.parse_canonical_json(canonical)
            except (protocol.BrokerProtocolError, TypeError, ValueError) as error:
                detail = (
                    _protocol_detail(error)
                    if isinstance(error, protocol.BrokerProtocolError)
                    else str(error)
                )
                raise BrokerStateError("protected-journal-invalid", detail) from error
            if len(canonical) > protocol.MAX_PAYLOAD_BYTES or not isinstance(value, dict):
                raise BrokerStateError("protected-journal-oversize", "receipt")
            total_bytes += 4 + len(canonical)
            if total_bytes > PROTECTED_RECEIPT_JOURNAL_MAX_BYTES:
                raise BrokerStateError("protected-journal-oversize")
            receipts.append(value)
    if not receipts:
        raise BrokerStateError("protected-journal-empty")
    return tuple(receipts)


@dataclass(frozen=True)
class BrokerRequest:
    """Immutable typed view of a canonical W3 broker request."""

    client_nonce: str
    task: str
    inputs: tuple[tuple[str, str], ...]
    claimed_authority_sha256: str
    claimed_release_sha256: str
    claimed_policy_sha256: str
    payload_sha256: str
    request_hash: str

    def __post_init__(self) -> None:
        if self.inputs != tuple(sorted(self.inputs)) or len(dict(self.inputs)) != len(self.inputs):
            raise BrokerRequestError("request-invalid", "inputs must be unique and sorted")
        try:
            rebuilt = protocol.build_request(
                client_nonce=self.client_nonce,
                payload={"task": self.task, "inputs": dict(self.inputs)},
                claimed_authority_sha256=self.claimed_authority_sha256,
                claimed_release_sha256=self.claimed_release_sha256,
                claimed_policy_sha256=self.claimed_policy_sha256,
            )
        except protocol.BrokerProtocolError as error:
            raise BrokerRequestError("request-invalid", _protocol_detail(error)) from error
        if rebuilt["payload_sha256"] != self.payload_sha256:
            raise BrokerRequestError("request-invalid", "payload_sha256 mismatch")
        if rebuilt["request_hash"] != self.request_hash:
            raise BrokerRequestError("request-invalid", "request_hash mismatch")

    @classmethod
    def build(
        cls,
        *,
        client_nonce: str,
        task: str,
        inputs: Mapping[str, str],
        claimed_authority_sha256: str,
        claimed_release_sha256: str,
        claimed_policy_sha256: str,
    ) -> BrokerRequest:
        """Build through the protocol's single canonical claims-only codec."""

        try:
            document = protocol.build_request(
                client_nonce=client_nonce,
                payload={"task": task, "inputs": dict(inputs)},
                claimed_authority_sha256=claimed_authority_sha256,
                claimed_release_sha256=claimed_release_sha256,
                claimed_policy_sha256=claimed_policy_sha256,
            )
        except (protocol.BrokerProtocolError, TypeError, ValueError) as error:
            detail = (
                _protocol_detail(error)
                if isinstance(error, protocol.BrokerProtocolError)
                else str(error)
            )
            raise BrokerRequestError("request-invalid", detail) from error
        payload = document["payload"]
        ordered_inputs = tuple(
            sorted((str(name), str(value)) for name, value in payload["inputs"].items())
        )
        return cls(
            client_nonce=str(document["client_nonce"]),
            task=str(document["payload"]["task"]),
            inputs=ordered_inputs,
            claimed_authority_sha256=str(document["claimed_authority_sha256"]),
            claimed_release_sha256=str(document["claimed_release_sha256"]),
            claimed_policy_sha256=str(document["claimed_policy_sha256"]),
            payload_sha256=str(document["payload_sha256"]),
            request_hash=str(document["request_hash"]),
        )

    def to_document(self) -> dict[str, object]:
        try:
            return protocol.build_request(
                client_nonce=self.client_nonce,
                payload={"task": self.task, "inputs": dict(self.inputs)},
                claimed_authority_sha256=self.claimed_authority_sha256,
                claimed_release_sha256=self.claimed_release_sha256,
                claimed_policy_sha256=self.claimed_policy_sha256,
            )
        except protocol.BrokerProtocolError as error:
            raise BrokerRequestError("request-invalid", _protocol_detail(error)) from error

    def canonical_bytes(self) -> bytes:
        return protocol.canonical_bytes(self.to_document())

    def receipt_binding(self) -> dict[str, str]:
        return {
            "request_hash": self.request_hash,
            "client_nonce": self.client_nonce,
            "claimed_authority_sha256": self.claimed_authority_sha256,
            "claimed_release_sha256": self.claimed_release_sha256,
            "claimed_policy_sha256": self.claimed_policy_sha256,
        }


@dataclass(frozen=True)
class VerificationKeyEpoch:
    """Retained, mode-scoped public verification-key metadata.

    ``mode=None`` preserves the Phase-A constructor contract: synthetic HMAC
    infers ``synthetic`` and Ed25519 infers the still-denied ``production``
    namespace.  Protected Ed25519 registrations must name their mode explicitly.
    """

    key_id: str
    algorithm: str
    public_key: bytes | None = None
    revocation_high_water: int | None = None
    mode: str | None = None

    def __post_init__(self) -> None:
        _require_digest(self.key_id, "key_id")
        if self.algorithm not in (protocol.SYNTHETIC_ALGORITHM, protocol.PRODUCTION_ALGORITHM):
            raise BrokerClientError("configuration-invalid", "key algorithm")
        declared_mode = self.mode
        inferred_mode = (
            protocol.MODE_SYNTHETIC
            if self.algorithm == protocol.SYNTHETIC_ALGORITHM
            else protocol.MODE_PRODUCTION
        )
        effective_mode = inferred_mode if declared_mode is None else declared_mode
        if effective_mode not in (
            protocol.MODE_SYNTHETIC,
            protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC,
            protocol.MODE_PRODUCTION,
        ):
            raise BrokerClientError("configuration-invalid", "key mode")
        if self.algorithm == protocol.SYNTHETIC_ALGORITHM:
            if effective_mode != protocol.MODE_SYNTHETIC:
                raise BrokerClientError("configuration-invalid", "synthetic key mode")
        elif effective_mode == protocol.MODE_SYNTHETIC:
            raise BrokerClientError("configuration-invalid", "Ed25519 key mode")
        object.__setattr__(self, "mode", effective_mode)
        if self.public_key is not None and not isinstance(self.public_key, bytes):
            raise BrokerClientError("configuration-invalid", "public key must be bytes")
        if self.algorithm == protocol.PRODUCTION_ALGORITHM:
            if self.public_key is None or len(self.public_key) != 32:
                raise BrokerClientError(
                    "configuration-invalid", "retained Ed25519 public key must be 32 bytes"
                )
        elif self.public_key is not None:
            raise BrokerClientError(
                "configuration-invalid", "synthetic verifier accepts no public-key override"
            )
        if effective_mode == protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC:
            assert self.public_key is not None
            expected_key_id = protocol.ed25519.mode_scoped_key_id(
                self.public_key,
                mode=protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC,
            )
            if self.key_id != expected_key_id:
                raise BrokerClientError("configuration-invalid", "mode-scoped key id")
        high_water = self.revocation_high_water
        if high_water is not None and (type(high_water) is not int or high_water < 0):
            raise BrokerClientError("configuration-invalid", "revocation high-water")


@dataclass(frozen=True)
class ReleaseEvidence:
    """Out-of-band release evidence retained across release retirement."""

    authority_sha256: str
    release_id: str
    release_sha256: str
    retired_after_receipt_sequence: int | None = None

    def __post_init__(self) -> None:
        _require_digest(self.authority_sha256, "release authority_sha256")
        _require_digest(self.release_sha256, "release_sha256")
        if not self.release_id or "/" in self.release_id or "\\" in self.release_id:
            raise BrokerClientError("configuration-invalid", "release_id")
        high_water = self.retired_after_receipt_sequence
        if high_water is not None and (type(high_water) is not int or high_water < 1):
            raise BrokerClientError("configuration-invalid", "release retirement high-water")


@dataclass(frozen=True, order=True)
class ConsumerHead:
    """One persisted logical-authority chain head."""

    authority_id: str
    receipt_sequence: int
    receipt_sha256: str

    def __post_init__(self) -> None:
        if not self.authority_id or "/" in self.authority_id or "\\" in self.authority_id:
            raise BrokerStateError("state-invalid", "authority_id")
        if type(self.receipt_sequence) is not int or self.receipt_sequence < 1:
            raise BrokerStateError("state-invalid", "receipt_sequence")
        try:
            protocol.digest_to_bytes(self.receipt_sha256)
        except protocol.BrokerProtocolError as error:
            raise BrokerStateError("state-invalid", "receipt_sha256") from error


@dataclass(frozen=True)
class ConsumerAnchor:
    """Canonical high-water anchor supplied to a durable CAS store."""

    instance_id: str
    revision: int
    heads: tuple[ConsumerHead, ...] = ()

    def __post_init__(self) -> None:
        if (
            type(self.instance_id) is not str
            or len(self.instance_id) != 64
            or any(character not in "0123456789abcdef" for character in self.instance_id)
        ):
            raise BrokerStateError("anchor-invalid", "instance_id")
        if type(self.revision) is not int or self.revision < 0:
            raise BrokerStateError("anchor-invalid", "revision")
        if type(self.heads) is not tuple or any(
            not isinstance(head, ConsumerHead) for head in self.heads
        ):
            raise BrokerStateError("anchor-invalid", "heads")
        authority_ids = [head.authority_id for head in self.heads]
        if authority_ids != sorted(authority_ids) or len(authority_ids) != len(set(authority_ids)):
            raise BrokerStateError("anchor-invalid", "authority heads must be unique and sorted")

    @property
    def schema_version(self) -> int:
        return ANCHOR_SCHEMA_VERSION

    @property
    def kind(self) -> str:
        return ANCHOR_KIND

    def head_for(self, authority_id: str) -> ConsumerHead | None:
        return next((head for head in self.heads if head.authority_id == authority_id), None)

    def to_document(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "instance_id": self.instance_id,
            "revision": self.revision,
            "heads": [
                {
                    "authority_id": head.authority_id,
                    "receipt_sequence": head.receipt_sequence,
                    "receipt_sha256": head.receipt_sha256,
                }
                for head in self.heads
            ],
        }

    def canonical_bytes(self) -> bytes:
        return protocol.canonical_bytes(self.to_document())

    def digest(self) -> str:
        return protocol.domain_digest(ANCHOR_DIGEST_DOMAIN, self.to_document())

    @classmethod
    def from_bytes(cls, data: bytes) -> ConsumerAnchor:
        try:
            value = protocol.parse_canonical_json(data)
        except protocol.BrokerProtocolError as error:
            raise BrokerStateError("anchor-invalid", _protocol_detail(error)) from error
        if not isinstance(value, dict) or set(value) != {
            "schema_version",
            "kind",
            "instance_id",
            "revision",
            "heads",
        }:
            raise BrokerStateError("anchor-invalid", "top-level fields")
        if (
            type(value["schema_version"]) is not int
            or value["schema_version"] != ANCHOR_SCHEMA_VERSION
            or type(value["kind"]) is not str
            or value["kind"] != ANCHOR_KIND
            or type(value["instance_id"]) is not str
        ):
            raise BrokerStateError("anchor-invalid", "schema, kind or instance_id")
        rows = value["heads"]
        if not isinstance(rows, list):
            raise BrokerStateError("anchor-invalid", "heads")
        heads: list[ConsumerHead] = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {
                "authority_id",
                "receipt_sequence",
                "receipt_sha256",
            }:
                raise BrokerStateError("anchor-invalid", "head fields")
            if type(row["authority_id"]) is not str or type(row["receipt_sha256"]) is not str:
                raise BrokerStateError("anchor-invalid", "head types")
            heads.append(
                ConsumerHead(
                    authority_id=row["authority_id"],
                    receipt_sequence=row["receipt_sequence"],
                    receipt_sha256=row["receipt_sha256"],
                )
            )
        return cls(
            instance_id=value["instance_id"],
            revision=value["revision"],
            heads=tuple(heads),
        )

    def advanced(
        self,
        *,
        authority_id: str,
        receipt_sequence: int,
        previous_receipt_sha256: str,
        receipt_sha256: str,
    ) -> ConsumerAnchor:
        current = self.head_for(authority_id)
        expected_sequence = 1 if current is None else current.receipt_sequence + 1
        expected_previous = (
            protocol.GENESIS_RECEIPT_DIGEST if current is None else current.receipt_sha256
        )
        if receipt_sequence < expected_sequence:
            raise BrokerReceiptError("receipt-sequence-regression")
        if receipt_sequence > expected_sequence:
            raise BrokerReceiptError("receipt-sequence-gap")
        if previous_receipt_sha256 != expected_previous:
            raise BrokerReceiptError("receipt-chain-fork")
        replacement = ConsumerHead(authority_id, receipt_sequence, receipt_sha256)
        heads = [head for head in self.heads if head.authority_id != authority_id]
        heads.append(replacement)
        return ConsumerAnchor(
            instance_id=self.instance_id,
            revision=self.revision + 1,
            heads=tuple(sorted(heads)),
        )


class ConsumerAnchorStore(Protocol):
    """Durable compare-and-swap boundary for consumer high-water anchors."""

    def initialize_once(self, anchor: ConsumerAnchor) -> None:
        """Install an explicit initial anchor exactly once."""

    def load_required(self) -> ConsumerAnchor:
        """Load an existing anchor or fail closed."""

    def compare_and_swap(self, expected_anchor_sha256: str, new_anchor: ConsumerAnchor) -> None:
        """Replace the expected anchor atomically or reject the fork."""


class ProtectedAnchorTransport(Protocol):
    """Byte-only transport for the single protected ``ADVANCE`` operation."""

    def exchange(self, canonical_request: bytes) -> bytes:
        """Return one canonical protected-anchor service response."""


class ProtectedAnchorClient:
    """Client-side cache and strict wire adapter for the protected anchor.

    The cache carries no authority.  Success is returned only after the service
    has consumed the signed receipt and returned the exact state the client
    independently derives.  No next-anchor value exists on the wire.
    """

    def __init__(self, *, transport: ProtectedAnchorTransport, initial_anchor: ConsumerAnchor):
        if not isinstance(initial_anchor, ConsumerAnchor):
            raise BrokerStateError("anchor-invalid", "initial protected anchor")
        self._transport = transport
        self._anchor = initial_anchor
        self._lock = threading.Lock()

    def load_required(self) -> ConsumerAnchor:
        with self._lock:
            return self._anchor

    @staticmethod
    def _request_bytes(expected_anchor_sha256: str, receipt: Mapping[str, object]) -> bytes:
        return protocol.canonical_bytes(
            {
                "schema_version": ANCHOR_SERVICE_SCHEMA_VERSION,
                "kind": ANCHOR_SERVICE_REQUEST_KIND,
                "operation": ANCHOR_SERVICE_OPERATION,
                "expected_anchor_sha256": expected_anchor_sha256,
                "canonical_receipt": dict(receipt),
            }
        )

    def _exchange_with_one_retry(self, request_bytes: bytes) -> tuple[str, ConsumerAnchor]:
        """Retry once because a transport loss cannot reveal whether ADVANCE committed."""

        first_error: Exception | None = None
        for attempt in range(2):
            try:
                response = self._transport.exchange(request_bytes)
            except Exception as error:
                if attempt == 0:
                    first_error = error
                    continue
                detail = str(error) or (str(first_error) if first_error is not None else "")
                raise BrokerStateError("anchor-service-transport-failed", detail) from error
            if not isinstance(response, bytes):
                raise BrokerStateError("anchor-service-response-invalid", "response must be bytes")
            return self._parse_response(response)
        raise BrokerStateError("anchor-service-transport-failed")  # pragma: no cover

    @staticmethod
    def _parse_response(response: bytes) -> tuple[str, ConsumerAnchor]:
        try:
            value = protocol.parse_canonical_json(response)
        except protocol.BrokerProtocolError as error:
            raise BrokerStateError(
                "anchor-service-response-invalid", _protocol_detail(error)
            ) from error
        if not isinstance(value, dict):
            raise BrokerStateError("anchor-service-response-invalid", "response must be an object")
        common = {
            "schema_version",
            "kind",
            "operation",
            "status",
        }
        if (
            value.get("schema_version") != ANCHOR_SERVICE_SCHEMA_VERSION
            or value.get("kind") != ANCHOR_SERVICE_RESPONSE_KIND
            or value.get("operation") != ANCHOR_SERVICE_OPERATION
        ):
            raise BrokerStateError("anchor-service-response-invalid", "identity")
        status = value.get("status")
        if status == "error":
            if set(value) != common | {"error"}:
                raise BrokerStateError("anchor-service-response-invalid", "error fields")
            error = value["error"]
            if (
                not isinstance(error, dict)
                or set(error) != {"code", "detail"}
                or type(error["code"]) is not str
                or type(error["detail"]) is not str
                or not error["code"]
            ):
                raise BrokerStateError("anchor-service-response-invalid", "error shape")
            raise BrokerStateError(str(error["code"]), str(error["detail"]))
        if status not in {"advanced", "idempotent"} or set(value) != common | {"anchor"}:
            raise BrokerStateError("anchor-service-response-invalid", "success fields")
        try:
            anchor = ConsumerAnchor.from_bytes(protocol.canonical_bytes(value["anchor"]))
        except (BrokerClientError, protocol.BrokerProtocolError, TypeError, ValueError) as error:
            raise BrokerStateError("anchor-service-response-invalid", "anchor") from error
        return str(status), anchor

    def advance(self, expected_anchor_sha256: str, canonical_receipt: bytes) -> ConsumerAnchor:
        try:
            protocol.digest_to_bytes(expected_anchor_sha256)
            parsed = protocol.parse_canonical_json(canonical_receipt)
            receipt = protocol.validate_receipt(parsed)
        except protocol.BrokerProtocolError as error:
            raise BrokerStateError("anchor-advance-invalid", _protocol_detail(error)) from error
        if receipt["mode"] != protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC:
            reason = (
                "production-verification-unavailable"
                if receipt["mode"] == protocol.MODE_PRODUCTION
                else "anchor-mode-unavailable"
            )
            raise BrokerStateError(reason)

        request_bytes = self._request_bytes(expected_anchor_sha256, receipt)
        with self._lock:
            current = self._anchor
            receipt_sha256 = protocol.receipt_hash(receipt)
            head = current.head_for(protocol.AUTHORITY_ID)
            idempotent = (
                head is not None
                and head.receipt_sequence == receipt["receipt_sequence"]
                and head.receipt_sha256 == receipt_sha256
            )
            if idempotent:
                expected_next = current
                allowed_statuses = {"idempotent"}
            else:
                if expected_anchor_sha256 != current.digest():
                    raise BrokerStateError("anchor-cas-mismatch")
                expected_next = current.advanced(
                    authority_id=protocol.AUTHORITY_ID,
                    receipt_sequence=int(receipt["receipt_sequence"]),
                    previous_receipt_sha256=str(receipt["previous_receipt_sha256"]),
                    receipt_sha256=receipt_sha256,
                )
                # A first ADVANCE may have committed before its response was
                # lost.  The byte-identical retry then legitimately returns
                # idempotent for the independently derived next state.
                allowed_statuses = {"advanced", "idempotent"}
            status, returned = self._exchange_with_one_retry(request_bytes)
            if status not in allowed_statuses or returned.digest() != expected_next.digest():
                raise BrokerStateError("anchor-service-derived-state-mismatch")
            self._anchor = returned
            return returned

    def prove_replayed_head(
        self,
        replayed_anchor: ConsumerAnchor,
        canonical_receipt: bytes,
    ) -> ConsumerAnchor:
        """Prove a locally replayed journal head through ADVANCE idempotence."""

        if not isinstance(replayed_anchor, ConsumerAnchor):
            raise BrokerStateError("protected-journal-invalid", "replayed anchor")
        try:
            receipt = protocol.validate_receipt(protocol.parse_canonical_json(canonical_receipt))
        except protocol.BrokerProtocolError as error:
            raise BrokerStateError("protected-journal-invalid", _protocol_detail(error)) from error
        if receipt["mode"] != protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC:
            raise BrokerStateError("anchor-mode-unavailable")
        receipt_sha256 = protocol.receipt_hash(receipt)
        head = replayed_anchor.head_for(protocol.AUTHORITY_ID)
        if (
            head is None
            or head.receipt_sequence != receipt["receipt_sequence"]
            or head.receipt_sha256 != receipt_sha256
        ):
            raise BrokerStateError("protected-journal-head-mismatch")
        request_bytes = self._request_bytes(replayed_anchor.digest(), receipt)
        with self._lock:
            initial = self._anchor
            if initial.revision != 0 or initial.heads:
                raise BrokerStateError("protected-journal-restart-anchor-not-genesis")
            if initial.instance_id != replayed_anchor.instance_id:
                raise BrokerStateError("protected-journal-instance-mismatch")
            status, returned = self._exchange_with_one_retry(request_bytes)
            if status != "idempotent" or returned.digest() != replayed_anchor.digest():
                raise BrokerStateError("protected-journal-head-proof-failed")
            self._anchor = returned
            return returned


@contextmanager
def _exclusive_anchor_lock(anchor_path: Path) -> Iterator[None]:
    lock_path = anchor_path.parent / f".{anchor_path.name}.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as error:
        raise BrokerStateError("anchor-lock-failed", str(error)) from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise BrokerStateError("anchor-lock-failed", "lock must be a single-link regular file")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise BrokerStateError("anchor-lock-failed", "lock mode is not private")
        flock(descriptor, LOCK_EX)
        yield
    except OSError as error:
        raise BrokerStateError("anchor-lock-failed", str(error)) from error
    finally:
        try:
            flock(descriptor, LOCK_UN)
        finally:
            os.close(descriptor)


class UnprotectedTestAnchorStore:
    """File-backed Phase A test store that confers zero execution authority.

    This explicitly named backend is suitable only for deterministic tests. Its
    local files and process-local replay observation are not a protected,
    production anti-rollback root and cannot support production credit.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._marker_path = self.path.parent / f".{self.path.name}.initialized"
        self._last_seen: ConsumerAnchor | None = None

    def _fsync_parent(self) -> None:
        try:
            descriptor = os.open(
                self.path.parent,
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        except OSError as error:
            raise BrokerStateError("anchor-write-failed", str(error)) from error

    @staticmethod
    def _write_all(descriptor: int, data: bytes) -> None:
        written = 0
        while written < len(data):
            count = os.write(descriptor, data[written:])
            if count <= 0:
                raise BrokerStateError("anchor-write-failed", "short write")
            written += count
        os.fsync(descriptor)

    def _create_file(self, path: Path, data: bytes) -> None:
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = -1
        try:
            descriptor = os.open(path, flags, 0o600)
            self._write_all(descriptor, data)
        except FileExistsError as error:
            raise BrokerStateError("anchor-already-initialized") from error
        except BrokerStateError:
            raise
        except OSError as error:
            raise BrokerStateError("anchor-write-failed", str(error)) from error
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _replace_anchor(self, anchor: ConsumerAnchor) -> None:
        temporary = self.path.parent / f".{self.path.name}.tmp-{secrets.token_hex(16)}"
        try:
            self._create_file(temporary, anchor.canonical_bytes())
            os.replace(temporary, self.path)
            self._fsync_parent()
        except BrokerStateError:
            raise
        except OSError as error:
            raise BrokerStateError("anchor-write-failed", str(error)) from error
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

    def _read_required(self) -> ConsumerAnchor:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.path, flags)
        except FileNotFoundError as error:
            raise BrokerStateError("anchor-missing") from error
        except OSError as error:
            raise BrokerStateError("anchor-read-failed", str(error)) from error
        try:
            metadata = os.fstat(descriptor)
            if (
                not stat.S_ISREG(metadata.st_mode)
                or metadata.st_nlink != 1
                or stat.S_IMODE(metadata.st_mode) & 0o077
            ):
                raise BrokerStateError(
                    "anchor-invalid", "anchor must be a private single-link regular file"
                )
            if metadata.st_size <= 0 or metadata.st_size > MAX_ANCHOR_BYTES:
                raise BrokerStateError("anchor-invalid", "anchor size")
            chunks: list[bytes] = []
            remaining = metadata.st_size
            while remaining:
                chunk = os.read(descriptor, min(remaining, 64 * 1024))
                if not chunk:
                    raise BrokerStateError("anchor-invalid", "truncated anchor")
                chunks.append(chunk)
                remaining -= len(chunk)
            if os.read(descriptor, 1):
                raise BrokerStateError("anchor-invalid", "anchor grew during read")
        finally:
            os.close(descriptor)
        return ConsumerAnchor.from_bytes(b"".join(chunks))

    def _observe(self, anchor: ConsumerAnchor) -> None:
        previous = self._last_seen
        if previous is not None:
            if anchor.instance_id != previous.instance_id:
                raise BrokerStateError("anchor-instance-id-change")
            if anchor.revision < previous.revision:
                raise BrokerStateError("anchor-replay-detected")
            if anchor.revision == previous.revision and anchor.digest() != previous.digest():
                raise BrokerStateError("anchor-fork-detected")
        self._last_seen = anchor

    def initialize_once(self, anchor: ConsumerAnchor) -> None:
        if not isinstance(anchor, ConsumerAnchor):
            raise BrokerStateError("anchor-invalid", "initial anchor type")
        if not self.path.parent.is_dir():
            raise BrokerStateError("anchor-write-failed", "parent directory is unavailable")
        with _exclusive_anchor_lock(self.path):
            if self.path.exists() or self._marker_path.exists() or self._last_seen is not None:
                raise BrokerStateError("anchor-already-initialized")
            # The marker is deliberately written first: an interrupted setup is
            # permanently fail-closed instead of becoming an implicit reset.
            self._create_file(self._marker_path, b"initialized\n")
            self._create_file(self.path, anchor.canonical_bytes())
            self._fsync_parent()
            self._observe(anchor)

    def load_required(self) -> ConsumerAnchor:
        with _exclusive_anchor_lock(self.path):
            anchor = self._read_required()
            self._observe(anchor)
            return anchor

    def compare_and_swap(self, expected_anchor_sha256: str, new_anchor: ConsumerAnchor) -> None:
        if type(expected_anchor_sha256) is not str:
            raise BrokerStateError("anchor-cas-invalid", "expected digest")
        try:
            protocol.digest_to_bytes(expected_anchor_sha256)
        except protocol.BrokerProtocolError as error:
            raise BrokerStateError("anchor-cas-invalid", "expected digest") from error
        if not isinstance(new_anchor, ConsumerAnchor):
            raise BrokerStateError("anchor-invalid", "new anchor type")
        with _exclusive_anchor_lock(self.path):
            current = self._read_required()
            self._observe(current)
            if current.digest() != expected_anchor_sha256:
                raise BrokerStateError("anchor-cas-mismatch")
            if new_anchor.instance_id != current.instance_id:
                raise BrokerStateError("anchor-instance-id-change")
            if new_anchor.revision != current.revision + 1:
                raise BrokerStateError("anchor-revision-not-next")
            next_heads = {head.authority_id: head for head in new_anchor.heads}
            for head in current.heads:
                advanced = next_heads.get(head.authority_id)
                if advanced is None or advanced.receipt_sequence < head.receipt_sequence:
                    raise BrokerStateError("anchor-head-regression")
                if (
                    advanced.receipt_sequence == head.receipt_sequence
                    and advanced.receipt_sha256 != head.receipt_sha256
                ):
                    raise BrokerStateError("anchor-head-fork")
            self._replace_anchor(new_anchor)
            self._observe(new_anchor)


class ReceiptConsumer:
    """Verify receipts and advance the mode-appropriate durable anchor."""

    def __init__(
        self,
        *,
        anchor_store: ConsumerAnchorStore | None,
        authorities: Iterable[Mapping[str, object]],
        key_epochs: Iterable[VerificationKeyEpoch],
        releases: Iterable[ReleaseEvidence],
        registered_policy_sha256s: Iterable[str],
        protected_anchor: ProtectedAnchorClient | None = None,
        protected_receipt_journal: bytes | Iterable[Mapping[str, object]] | None = None,
    ):
        self._anchor_store = anchor_store
        self._protected_anchor = protected_anchor
        self._lock = threading.Lock()
        self._protected_journal_restored = False
        if self._anchor_store is None and self._protected_anchor is None:
            raise BrokerStateError("anchor-store-invalid", "no anchor backend")
        if self._anchor_store is not None:
            initial_anchor = self._anchor_store.load_required()
            if not isinstance(initial_anchor, ConsumerAnchor):
                raise BrokerStateError("anchor-store-invalid", "load_required result")
        if self._protected_anchor is not None:
            initial_protected = self._protected_anchor.load_required()
            if not isinstance(initial_protected, ConsumerAnchor):
                raise BrokerStateError("anchor-store-invalid", "protected load result")
        self._authorities: dict[str, dict[str, object]] = {}
        for authority in authorities:
            try:
                canonical = protocol.parse_canonical_json(protocol.canonical_bytes(dict(authority)))
                validated = protocol.validate_authority(canonical)
            except (protocol.BrokerProtocolError, TypeError, ValueError) as error:
                detail = (
                    _protocol_detail(error)
                    if isinstance(error, protocol.BrokerProtocolError)
                    else str(error)
                )
                raise BrokerClientError("configuration-invalid", detail) from error
            digest = protocol.authority_hash(validated)
            if digest in self._authorities:
                raise BrokerClientError("configuration-invalid", "duplicate authority digest")
            self._authorities[digest] = validated
        if not self._authorities:
            raise BrokerClientError("configuration-invalid", "no registered authority")

        self._keys: dict[tuple[str, str], VerificationKeyEpoch] = {}
        for epoch in key_epochs:
            assert epoch.mode is not None
            key = (epoch.mode, epoch.key_id)
            if key in self._keys:
                raise BrokerClientError("configuration-invalid", "duplicate key epoch")
            self._keys[key] = epoch

        self._releases: dict[tuple[str, str], ReleaseEvidence] = {}
        for release in releases:
            key = (release.authority_sha256, release.release_sha256)
            if key in self._releases:
                raise BrokerClientError("configuration-invalid", "duplicate release evidence")
            authority = self._authorities.get(release.authority_sha256)
            if authority is None:
                raise BrokerClientError("configuration-invalid", "release authority is unknown")
            registered = authority["release_identity"]
            if (
                registered["release_id"] != release.release_id
                or registered["ancestry_root_sha256"] != release.release_sha256
            ):
                raise BrokerClientError("configuration-invalid", "release evidence mismatch")
            self._releases[key] = release

        self._policies = frozenset(
            _require_digest(value, "registered policy") for value in registered_policy_sha256s
        )
        if not self._policies:
            raise BrokerClientError("configuration-invalid", "no registered policy")
        if protected_receipt_journal is not None:
            self.replay_protected_journal(protected_receipt_journal)

    @property
    def anchor(self) -> ConsumerAnchor:
        if self._protected_anchor is not None:
            return self._protected_anchor.load_required()
        if self._anchor_store is None:
            raise BrokerStateError("anchor-store-invalid", "no local anchor backend")
        anchor = self._anchor_store.load_required()
        if not isinstance(anchor, ConsumerAnchor):
            raise BrokerStateError("anchor-store-invalid", "load_required result")
        return anchor

    @property
    def state(self) -> ConsumerAnchor:
        """Compatibility view; the anchor store remains the sole durable truth."""

        return self.anchor

    def replay_protected_journal(
        self,
        journal: bytes | Iterable[Mapping[str, object]],
    ) -> ConsumerAnchor:
        """Verify a complete public receipt journal and prove its head remotely.

        The journal is caller-supplied and read-only here.  Its signed receipts
        rebuild the local cache from the pinned genesis; the final receipt is
        then submitted with the rebuilt digest so only an already-current,
        idempotent service head can succeed.
        """

        receipts = _read_protected_receipt_journal(journal)
        with self._lock:
            if self._protected_anchor is None:
                raise BrokerStateError("protected-anchor-unavailable")
            if self._protected_journal_restored:
                raise BrokerStateError("protected-journal-already-restored")
            genesis = self._protected_anchor.load_required()
            if genesis.revision != 0 or genesis.heads:
                raise BrokerStateError("protected-journal-restart-anchor-not-genesis")
            replayed = genesis
            last_receipt: dict[str, object] | None = None
            for candidate in receipts:
                body, authority = self._verify(candidate, expected_request=None)
                if body["mode"] != protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC:
                    raise BrokerReceiptError("anchor-mode-unavailable")
                receipt_sha256 = protocol.receipt_hash(body)
                replayed = replayed.advanced(
                    authority_id=str(authority["authority_id"]),
                    receipt_sequence=int(body["receipt_sequence"]),
                    previous_receipt_sha256=str(body["previous_receipt_sha256"]),
                    receipt_sha256=receipt_sha256,
                )
                last_receipt = body
            assert last_receipt is not None
            proved = self._protected_anchor.prove_replayed_head(
                replayed,
                protocol.canonical_bytes(last_receipt),
            )
            self._protected_journal_restored = True
            return proved

    def _cross_bind(
        self, body: dict[str, object], expected_request: BrokerRequest | None
    ) -> tuple[dict[str, object], ReleaseEvidence]:
        request = body["request"]
        measured = body["measured"]
        claimed_authority = request["claimed_authority_sha256"]
        if claimed_authority != measured["authority_sha256"]:
            raise BrokerReceiptError("claimed-measured-authority-mismatch")
        authority = self._authorities.get(str(claimed_authority))
        if authority is None:
            raise BrokerReceiptError("unknown-authority")
        if expected_request is not None and request != expected_request.receipt_binding():
            raise BrokerReceiptError("request-binding-mismatch")

        claimed_release = request["claimed_release_sha256"]
        if claimed_release != measured["release_sha256"]:
            raise BrokerReceiptError("claimed-measured-release-mismatch")
        release = self._releases.get((str(claimed_authority), str(claimed_release)))
        if release is None:
            raise BrokerReceiptError("unknown-release")

        claimed_policy = request["claimed_policy_sha256"]
        if claimed_policy != measured["policy_sha256"]:
            raise BrokerReceiptError("claimed-measured-policy-mismatch")
        if claimed_policy != body["policy"]["resolved_sha256"]:
            raise BrokerReceiptError("registered-policy-mismatch")
        installed_policy = authority["policy_identity"]
        if claimed_policy != installed_policy["resolved_sha256"]:
            raise BrokerReceiptError("authority-policy-claim-mismatch")
        if body["policy"] != installed_policy:
            raise BrokerReceiptError("authority-policy-identity-mismatch")
        if claimed_policy not in self._policies:
            raise BrokerReceiptError("unknown-policy")

        installed = authority["installed_code_identity"]
        identities = body["identities"]
        expected_identities = {
            "broker_code_sha256": identities["broker"]["code_sha256"],
            "launcher_sha256": identities["launcher"]["code_sha256"],
            "worker_sha256": identities["worker"]["code_sha256"],
            "loader_sha256": identities["loader"]["sha256"],
            "node_sha256": identities["node"]["sha256"],
        }
        for field, observed in expected_identities.items():
            if installed[field] != observed:
                raise BrokerReceiptError("authority-identity-mismatch", field)

        effective = body["effective_ids"]
        broker = authority["broker_identity"]
        runner = authority["runner_identity"]
        launcher = authority["launcher_identity"]
        expected_effective = {
            "broker_uid": broker["uid"],
            "broker_gid": broker["gid"],
            "runner_uid": runner["uid"],
            "runner_gid": runner["gid"],
            "launcher_uid": launcher["uid"],
            "launcher_gid": launcher["gid"],
        }
        if effective != expected_effective:
            raise BrokerReceiptError("authority-principal-mismatch")

        roster = body["roster"]
        if roster["pre"] != roster["post"]:
            raise BrokerReceiptError("pre-post-roster-mismatch")
        if roster["pre"] != authority["installed_code_roster"]:
            raise BrokerReceiptError("authority-installed-roster-mismatch")

        if body["attempt_sequence"] < body["receipt_sequence"]:
            raise BrokerReceiptError("attempt-sequence-before-receipt-sequence")
        return authority, release

    def _verify(
        self, receipt: Mapping[str, object], expected_request: BrokerRequest | None
    ) -> tuple[dict[str, object], dict[str, object]]:
        try:
            canonical = protocol.parse_canonical_json(protocol.canonical_bytes(dict(receipt)))
            body = protocol.validate_receipt(canonical)
        except (protocol.BrokerProtocolError, TypeError, ValueError) as error:
            detail = (
                _protocol_detail(error)
                if isinstance(error, protocol.BrokerProtocolError)
                else str(error)
            )
            raise BrokerReceiptError("receipt-invalid", detail) from error

        mode = str(body["mode"])
        if mode == protocol.MODE_PRODUCTION:
            raise BrokerReceiptError("production-verification-unavailable")
        authority, release = self._cross_bind(body, expected_request)
        if authority["mode"] != mode:
            raise BrokerReceiptError("authority-mode-mismatch")
        key_id = str(body["signature"]["key_id"])
        epoch = self._keys.get((mode, key_id))
        if epoch is None:
            raise BrokerReceiptError("unknown-key-epoch")
        if (
            epoch.algorithm != body["signature"]["algorithm"]
            or epoch.key_id != authority["signing"]["key_id"]
            or epoch.algorithm != authority["signing"]["algorithm"]
            or epoch.mode != mode
        ):
            raise BrokerReceiptError("key-authority-mismatch")

        sequence = int(body["receipt_sequence"])
        if epoch.revocation_high_water is not None and sequence > epoch.revocation_high_water:
            raise BrokerReceiptError("revoked-key-future-receipt")
        if (
            release.retired_after_receipt_sequence is not None
            and sequence > release.retired_after_receipt_sequence
        ):
            raise BrokerReceiptError("retired-release-future-receipt")

        try:
            if mode == protocol.MODE_SYNTHETIC:
                signature_valid = protocol.verify_receipt_signature(body)
            elif mode == protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC:
                if epoch.public_key is None:
                    raise BrokerReceiptError("key-authority-mismatch", "missing public key")
                try:
                    authority_public_key = protocol.ed25519.decode_public_key(
                        authority["signing"]["public_key"]
                    )
                except protocol.ed25519.Ed25519ContractError as error:
                    raise BrokerReceiptError("key-authority-mismatch", error.reason) from error
                if authority_public_key != epoch.public_key:
                    raise BrokerReceiptError("key-authority-mismatch", "public key")
                signature_valid = protocol.verify_receipt_signature(
                    body,
                    public_key=epoch.public_key,
                    registered_key_id=epoch.key_id,
                )
            else:  # pragma: no cover - production and unknown modes fail above/schema
                raise BrokerReceiptError("production-verification-unavailable")
        except BrokerReceiptError:
            raise
        except protocol.BrokerProtocolError as error:
            raise BrokerReceiptError("signature-verification-failed", error.reason) from error
        if not signature_valid:
            raise BrokerReceiptError("signature-invalid")
        return body, authority

    def verify_only(
        self, receipt: Mapping[str, object], *, expected_request: BrokerRequest | None = None
    ) -> dict[str, object]:
        """Verify without advancing state; used by the protected service itself."""

        with self._lock:
            body, _authority = self._verify(receipt, expected_request)
            return body

    def accept(
        self, receipt: Mapping[str, object], *, expected_request: BrokerRequest | None = None
    ) -> dict[str, object]:
        with self._lock:
            body, authority = self._verify(receipt, expected_request)
            mode = str(body["mode"])
            sequence = int(body["receipt_sequence"])
            receipt_sha256 = protocol.receipt_hash(body)
            authority_id = str(authority["authority_id"])
            if mode == protocol.MODE_PROTECTED_PUBLIC_SYNTHETIC:
                if self._protected_anchor is None:
                    raise BrokerStateError("protected-anchor-unavailable")
                current_anchor = self._protected_anchor.load_required()
                returned = self._protected_anchor.advance(
                    current_anchor.digest(),
                    protocol.canonical_bytes(body),
                )
                current_head = current_anchor.head_for(authority_id)
                if (
                    current_head is not None
                    and current_head.receipt_sequence == sequence
                    and current_head.receipt_sha256 == receipt_sha256
                ):
                    expected_anchor = current_anchor
                else:
                    expected_anchor = current_anchor.advanced(
                        authority_id=authority_id,
                        receipt_sequence=sequence,
                        previous_receipt_sha256=str(body["previous_receipt_sha256"]),
                        receipt_sha256=receipt_sha256,
                    )
                if returned.digest() != expected_anchor.digest():
                    raise BrokerStateError("anchor-service-derived-state-mismatch")
                return body

            if self._anchor_store is None:
                raise BrokerStateError("anchor-store-invalid", "synthetic store unavailable")
            current_anchor = self._anchor_store.load_required()
            if not isinstance(current_anchor, ConsumerAnchor):
                raise BrokerStateError("anchor-store-invalid", "load_required result")
            next_anchor = current_anchor.advanced(
                authority_id=authority_id,
                receipt_sequence=sequence,
                previous_receipt_sha256=str(body["previous_receipt_sha256"]),
                receipt_sha256=receipt_sha256,
            )
            self._anchor_store.compare_and_swap(current_anchor.digest(), next_anchor)
            return body


@dataclass(frozen=True)
class BrokerClient:
    """Submit typed requests and accept only durably consumed receipts."""

    transport: BrokerTransport
    consumer: ReceiptConsumer

    def submit(self, request: BrokerRequest) -> dict[str, object]:
        try:
            response = self.transport.exchange(request.canonical_bytes())
        except BrokerClientError:
            raise
        except Exception as error:
            raise BrokerTransportError("transport-failure", str(error)) from error
        if not isinstance(response, bytes):
            raise BrokerTransportError("transport-response-not-bytes")
        try:
            parsed = protocol.parse_canonical_json(response)
        except protocol.BrokerProtocolError as error:
            raise BrokerTransportError(
                "transport-response-invalid", _protocol_detail(error)
            ) from error
        if not isinstance(parsed, dict):
            raise BrokerTransportError("transport-response-invalid", "receipt must be an object")
        return self.consumer.accept(parsed, expected_request=request)


__all__ = [
    "BrokerClient",
    "BrokerClientError",
    "BrokerReceiptError",
    "BrokerRequest",
    "BrokerRequestError",
    "BrokerStateError",
    "BrokerTransport",
    "BrokerTransportError",
    "ConsumerAnchor",
    "ConsumerAnchorStore",
    "ConsumerHead",
    "ProtectedAnchorClient",
    "ProtectedAnchorTransport",
    "ReceiptConsumer",
    "ReleaseEvidence",
    "UnprotectedTestAnchorStore",
    "VerificationKeyEpoch",
]
