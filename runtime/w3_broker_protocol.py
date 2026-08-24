#!/usr/bin/env python3
"""W3 protected execution broker protocol: canonical codec, framing, digests.

Phase A/L70 scope (payload-free): structure and deterministic transforms only.
This module opens no socket, persists no ledger, signs with no real key,
spawns no process, creates no user, runs no Node/Metis and claims no
production evidence.  Synthetic signatures carry zero authority.

Wire contract matches runtime/w3_privileged_launcher.c byte for byte:
magic ``M1W3LCH`` in an 8-byte slot, protocol version 1 as unsigned 32-bit
big-endian, payload length as unsigned 32-bit big-endian with
``0 < length <= 4 MiB``, 32-byte SHA-256 and nonce slots, exact reads and
no trailing bytes.

Canonical JSON semantics are the repository's single codec
(``metis_model1.provenance.canonical_json_bytes``): JSON-only types, NFC and
newline normalisation, duplicate normalised-key rejection, ``allow_nan=False``,
UTF-8, sorted keys and compact separators.  The strict parser additionally
rejects duplicate raw keys, non-canonical bytes, non-finite numbers and
nesting beyond a bounded depth.  Hashes are ``sha256:`` plus lowercase hex
over domain-separated canonical envelopes; caller-supplied digests are named
claims and never contain authority bytes or paths.
"""

import hashlib
import hmac
import json
import re
import stat
import struct
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
RUNTIME_ROOT = PROJECT_ROOT / "runtime"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(RUNTIME_ROOT) not in sys.path:
    sys.path.insert(0, str(RUNTIME_ROOT))

import w3_ed25519 as ed25519  # noqa: E402

from metis_model1.provenance import (  # noqa: E402
    NonJsonValueError,
    canonical_json_bytes,
    normalize_json,
)

SCHEMA_VERSION = 1
KIND_REQUEST = "w3-protected-broker-request"
KIND_AUTHORITY = "w3-protected-broker-authority"
KIND_RECEIPT = "w3-protected-broker-receipt"
AUTHORITY_ID = "w3-protected-broker-authority-v1"

MODE_SYNTHETIC = "synthetic"
MODE_PROTECTED_PUBLIC_SYNTHETIC = "protected-public-synthetic"
MODE_PRODUCTION = "production"
PRODUCTION_ALGORITHM = "ed25519"
SYNTHETIC_ALGORITHM = "synthetic-hmac-sha256"

SHA256_PREFIX = "sha256:"
SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
NONCE_PATTERN = r"^[0-9a-f]{64}$"
IDENTIFIER_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
INPUT_NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
POLICY_PARAM_PATTERN = r"^[A-Z][A-Z0-9_]{0,63}$"
NODE_VERSION_PATTERN = r"^v[0-9]+\.[0-9]+\.[0-9]+$"
_ROSTER_PATH_SEGMENT = r"(?:[A-Za-z0-9@_-][A-Za-z0-9@._-]*|\.[A-Za-z0-9@_-][A-Za-z0-9@._-]*)"
ROSTER_PATH_PATTERN = rf"^{_ROSTER_PATH_SEGMENT}(?:/{_ROSTER_PATH_SEGMENT})*$"

DOMAIN_REQUEST = "w3-protected-broker/request/v1"
DOMAIN_AUTHORITY = "w3-protected-broker/authority/v1"
DOMAIN_RECEIPT = "w3-protected-broker/receipt/v1"
DOMAIN_POLICY = "w3-protected-broker/policy/v1"
DOMAIN_RELEASE_ROSTER = "w3-protected-broker/release-roster/v1"
DOMAIN_SYNTHETIC_KEY = "w3-protected-broker/synthetic-key/v1"
GENESIS_RECEIPT_DIGEST = SHA256_PREFIX + "0" * 64

MAX_PAYLOAD_BYTES = 4 * 1024 * 1024
MAX_NESTING_DEPTH = 32
MAX_PAYLOAD_INPUTS = 32
MAX_POLICY_PARAMETERS = 64
EXIT_CODE_RANGE = (-255, 255)

FRAME_MAGIC = b"M1W3LCH\x00"
FRAME_MAGIC_BYTES = 8
PROTOCOL_VERSION = 1
DIGEST_BYTES = 32
NONCE_BYTES = 32
REQUEST_HEADER_BYTES = FRAME_MAGIC_BYTES + 4 + 4 + 3 * DIGEST_BYTES + NONCE_BYTES
RESPONSE_HEADER_BYTES = FRAME_MAGIC_BYTES + 4 + 4 + 4 + 2 * DIGEST_BYTES + NONCE_BYTES
STATUS_OK = 0

SYNTHETIC_NONCLAIMS = (
    "executed_preimage_authority=false",
    "no-production-authority",
    "no-production-evidence",
    "phase-a-structure-only",
    "synthetic-hmac-sha256-signature",
    "unprotected-test-stores-carry-zero-authority",
)
PROTECTED_PUBLIC_SYNTHETIC_NONCLAIMS = (
    "no-production-authority",
    "no-production-evidence",
    "public-synthetic-only",
    "no-semantic-accuracy-claim",
    "no-W5-credit",
)
SYNTHETIC_KEY_LABEL = "w3-protected-broker-phase-a-public-synthetic-key"
SYNTHETIC_KEY_MATERIAL = b"w3-protected-broker/synthetic/phase-a/no-authority"

ROSTER_ROW_FIELDS = ("path", "size", "mode", "sha256", "uid", "gid", "dev", "ino", "nlink")

REQUEST_FIELDS = (
    "schema_version",
    "kind",
    "authority_id",
    "claimed_authority_sha256",
    "claimed_release_sha256",
    "claimed_policy_sha256",
    "client_nonce",
    "payload",
    "payload_sha256",
    "request_hash",
)
REQUEST_HASHED_FIELDS = tuple(field for field in REQUEST_FIELDS if field != "request_hash")
PAYLOAD_FIELDS = ("task", "inputs")
FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "ancillary",
        "argv",
        "args",
        "binary",
        "chdir",
        "cmd",
        "command",
        "cwd",
        "env",
        "environment",
        "exec",
        "executable",
        "fd",
        "fds",
        "fork",
        "path",
        "paths",
        "socket",
        "spawn",
    }
)

AUTHORITY_FIELDS = (
    "schema_version",
    "kind",
    "authority_id",
    "mode",
    "signing",
    "broker_identity",
    "runner_identity",
    "launcher_identity",
    "installed_code_identity",
    "installed_code_paths",
    "installed_code_roster",
    "policy_identity",
    "release_identity",
)

INSTALLED_CODE_DIGEST_FIELDS = (
    "broker_code_sha256",
    "launcher_sha256",
    "worker_sha256",
    "loader_sha256",
    "runner_sha256",
    "node_sha256",
)
INSTALLED_CODE_ROLES = ("broker", "launcher", "worker", "loader", "runner", "node")
ROLE_DIGEST_FIELD = {
    "broker": "broker_code_sha256",
    "launcher": "launcher_sha256",
    "worker": "worker_sha256",
    "loader": "loader_sha256",
    "runner": "runner_sha256",
    "node": "node_sha256",
}

RECEIPT_FIELDS = (
    "schema_version",
    "kind",
    "mode",
    "executed_preimage_authority",
    "nonclaims",
    "request",
    "measured",
    "broker_nonce",
    "attempt_sequence",
    "receipt_sequence",
    "previous_receipt_sha256",
    "identities",
    "effective_ids",
    "policy",
    "roster",
    "output",
    "cleanup",
    "signature",
)

_SHA256_RE = re.compile(SHA256_PATTERN)
_NONCE_RE = re.compile(NONCE_PATTERN)
_IDENTIFIER_RE = re.compile(IDENTIFIER_PATTERN)
_INPUT_NAME_RE = re.compile(INPUT_NAME_PATTERN)
_POLICY_PARAM_RE = re.compile(POLICY_PARAM_PATTERN)
_NODE_VERSION_RE = re.compile(NODE_VERSION_PATTERN)


class BrokerProtocolError(Exception):
    """Typed protocol failure carrying a stable machine-readable reason."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(reason if not detail else f"{reason}: {detail}")


class CanonicalizationError(BrokerProtocolError):
    """Canonical JSON codec violation."""


class FramingError(BrokerProtocolError):
    """Binary framing violation."""


class ValidationError(BrokerProtocolError):
    """Request, authority or receipt contract violation."""


def _is_sha256_digest(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _require_digest(value: object, label: str) -> str:
    if not _is_sha256_digest(value):
        raise ValidationError("bad-digest", label)
    return str(value)


def _require_strict_int(value: object, label: str, *, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValidationError("bad-integer", label)
    return value


def _require_string(value: object, label: str) -> str:
    if type(value) is not str:
        raise ValidationError("bad-string", label)
    return value


def _check_path_like(label: str, value: str) -> None:
    if "/" in value or "\\" in value or "\x00" in value or value.startswith("~"):
        raise ValidationError("path-like-value", label)


# ---------------------------------------------------------------------------
# Canonical codec: strict parse plus canonical round trip.
# ---------------------------------------------------------------------------


def canonical_bytes(value: object) -> bytes:
    try:
        return canonical_json_bytes(value)
    except NonJsonValueError as error:
        raise CanonicalizationError("non-json-value", str(error)) from error


def nesting_depth(value: object) -> int:
    """Maximum container nesting depth; scalars are depth 0, ``{}`` is depth 1."""

    deepest = 0
    stack: list[tuple[object, int]] = [(value, 1)]
    while stack:
        current, depth = stack.pop()
        if isinstance(current, dict):
            children = tuple(current.values())
        elif isinstance(current, list):
            children = tuple(current)
        else:
            continue
        deepest = max(deepest, depth)
        stack.extend((child, depth + 1) for child in children)
    return deepest


def _reject_constant(token: str) -> object:
    raise CanonicalizationError("json-non-finite-constant", token)


def _rejecting_pair_hook(pairs: list[tuple[str, object]]) -> dict[str, object]:
    raw_seen: set[str] = set()
    normalized_seen: set[str] = set()
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in raw_seen:
            raise CanonicalizationError("duplicate-key", key)
        raw_seen.add(key)
        normalized = unicodedata.normalize("NFC", key)
        if normalized in normalized_seen:
            raise CanonicalizationError("duplicate-normalized-key", key)
        normalized_seen.add(normalized)
        result[key] = value
    return result


def _check_bracket_depth(text: str, cap: int) -> None:
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > cap:
                raise CanonicalizationError("nesting-too-deep", f"depth exceeds {cap}")
        elif character in "]}":
            depth -= 1


def parse_canonical_json(data: bytes | bytearray) -> object:
    """Strictly parse canonical JSON bytes: bounded, duplicate-free, canonical."""

    if not isinstance(data, bytes | bytearray):
        raise CanonicalizationError("not-bytes")
    payload = bytes(data)
    if len(payload) == 0:
        raise CanonicalizationError("empty-payload")
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise CanonicalizationError("payload-too-large", f"{len(payload)} bytes")
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CanonicalizationError("utf8-error", str(error)) from error
    _check_bracket_depth(text, MAX_NESTING_DEPTH)
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_rejecting_pair_hook,
            parse_constant=_reject_constant,
        )
    except CanonicalizationError:
        raise
    except (json.JSONDecodeError, OverflowError, RecursionError, ValueError) as error:
        raise CanonicalizationError("json-parse-error", str(error)) from error
    try:
        normalized = normalize_json(parsed)
    except NonJsonValueError as error:
        raise CanonicalizationError("non-json-value", str(error)) from error
    if canonical_json_bytes(normalized) != payload:
        raise CanonicalizationError("noncanonical-bytes")
    if nesting_depth(normalized) > MAX_NESTING_DEPTH:
        raise CanonicalizationError("nesting-too-deep", f"depth exceeds {MAX_NESTING_DEPTH}")
    return normalized


# ---------------------------------------------------------------------------
# Domain-separated digests over canonical envelopes.
# ---------------------------------------------------------------------------


def domain_digest(domain: str, body: object) -> str:
    if type(domain) is not str or not domain:
        raise CanonicalizationError("bad-domain")
    envelope = {"domain": domain, "body": normalize_json(body)}
    return SHA256_PREFIX + hashlib.sha256(canonical_bytes(envelope)).hexdigest()


def request_hash(request: object) -> str:
    return domain_digest(DOMAIN_REQUEST, request)


def authority_hash(authority: object) -> str:
    return domain_digest(DOMAIN_AUTHORITY, authority)


def receipt_hash(receipt: object) -> str:
    return domain_digest(DOMAIN_RECEIPT, receipt)


def policy_hash(template_sha256: str, parameters: object) -> str:
    return domain_digest(
        DOMAIN_POLICY,
        {"template_sha256": template_sha256, "parameters": parameters},
    )


def release_ancestry_hash(release_id: str, installed_code_roster: object) -> str:
    """Derive release ancestry from its identifier and complete installed roster."""

    if type(release_id) is not str or _IDENTIFIER_RE.fullmatch(release_id) is None:
        raise ValidationError("bad-release-id", str(release_id))
    roster = _validate_roster(installed_code_roster, "release.installed_code_roster")
    return domain_digest(
        DOMAIN_RELEASE_ROSTER,
        {"release_id": release_id, "installed_code_roster": roster},
    )


def digest_to_bytes(digest: str) -> bytes:
    if not _is_sha256_digest(digest):
        raise FramingError("frame-bad-digest", digest)
    return bytes.fromhex(digest[len(SHA256_PREFIX) :])


# ---------------------------------------------------------------------------
# Binary framing: exact reads, bounded payloads, no trailing bytes.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RequestFrame:
    payload: bytes
    request_sha256: str
    authority_sha256: str
    release_sha256: str
    broker_nonce: str


@dataclass(frozen=True)
class ResponseFrame:
    payload: bytes
    status: int
    request_sha256: str
    broker_nonce: str
    cleanup_sha256: str


def _digest_slot(digest: str, label: str) -> bytes:
    if not _is_sha256_digest(digest):
        raise FramingError("frame-bad-digest", label)
    return bytes.fromhex(digest[len(SHA256_PREFIX) :])


def _nonce_slot(nonce: str, label: str) -> bytes:
    if type(nonce) is not str or _NONCE_RE.fullmatch(nonce) is None:
        raise FramingError("frame-bad-nonce", label)
    return bytes.fromhex(nonce)


def _check_payload_bytes(payload: object) -> bytes:
    if not isinstance(payload, bytes | bytearray):
        raise FramingError("frame-payload-not-bytes")
    body = bytes(payload)
    if len(body) == 0:
        raise FramingError("frame-empty-payload")
    if len(body) > MAX_PAYLOAD_BYTES:
        raise FramingError("frame-oversize", f"{len(body)} bytes")
    return body


def encode_request_frame(
    payload: bytes,
    *,
    request_sha256: str,
    authority_sha256: str,
    release_sha256: str,
    broker_nonce: str,
) -> bytes:
    body = _check_payload_bytes(payload)
    header = (
        FRAME_MAGIC
        + struct.pack(">II", PROTOCOL_VERSION, len(body))
        + _digest_slot(request_sha256, "request_sha256")
        + _digest_slot(authority_sha256, "authority_sha256")
        + _digest_slot(release_sha256, "release_sha256")
        + _nonce_slot(broker_nonce, "broker_nonce")
    )
    return header + body


def encode_response_frame(
    payload: bytes,
    *,
    status: int,
    request_sha256: str,
    broker_nonce: str,
    cleanup_sha256: str,
) -> bytes:
    body = _check_payload_bytes(payload)
    if type(status) is not int or not 0 <= status <= 0xFFFFFFFF:
        raise FramingError("frame-bad-status")
    header = (
        FRAME_MAGIC
        + struct.pack(">III", PROTOCOL_VERSION, status, len(body))
        + _digest_slot(request_sha256, "request_sha256")
        + _nonce_slot(broker_nonce, "broker_nonce")
        + _digest_slot(cleanup_sha256, "cleanup_sha256")
    )
    return header + body


def _decode_common_header(data: bytes, header_size: int) -> tuple[int, int]:
    if not isinstance(data, bytes | bytearray):
        raise FramingError("frame-not-bytes")
    buffer = bytes(data)
    if len(buffer) < header_size:
        raise FramingError("frame-truncated-header", f"{len(buffer)} < {header_size}")
    if buffer[:FRAME_MAGIC_BYTES] != FRAME_MAGIC:
        raise FramingError("frame-bad-magic")
    return buffer, len(buffer)


def _slot_digest(buffer: bytes, offset: int, label: str) -> str:
    return SHA256_PREFIX + buffer[offset : offset + DIGEST_BYTES].hex()


def _slot_nonce(buffer: bytes, offset: int, label: str) -> str:
    return buffer[offset : offset + NONCE_BYTES].hex()


def decode_request_frame(data: bytes) -> RequestFrame:
    buffer, total = _decode_common_header(data, REQUEST_HEADER_BYTES)
    version, length = struct.unpack(">II", buffer[8:16])
    if version != PROTOCOL_VERSION:
        raise FramingError("frame-bad-version", str(version))
    if length == 0:
        raise FramingError("frame-empty-payload")
    if length > MAX_PAYLOAD_BYTES:
        raise FramingError("frame-oversize", str(length))
    remaining = total - REQUEST_HEADER_BYTES
    if remaining < length:
        raise FramingError("frame-truncated-payload", f"{remaining} < {length}")
    if remaining > length:
        raise FramingError("frame-trailing-bytes", f"{remaining} > {length}")
    offset = 16
    request_sha256 = _slot_digest(buffer, offset, "request_sha256")
    authority_sha256 = _slot_digest(buffer, offset + 32, "authority_sha256")
    release_sha256 = _slot_digest(buffer, offset + 64, "release_sha256")
    broker_nonce = _slot_nonce(buffer, offset + 96, "broker_nonce")
    return RequestFrame(
        payload=buffer[REQUEST_HEADER_BYTES:],
        request_sha256=request_sha256,
        authority_sha256=authority_sha256,
        release_sha256=release_sha256,
        broker_nonce=broker_nonce,
    )


def decode_response_frame(data: bytes) -> ResponseFrame:
    buffer, total = _decode_common_header(data, RESPONSE_HEADER_BYTES)
    version, status, length = struct.unpack(">III", buffer[8:20])
    if version != PROTOCOL_VERSION:
        raise FramingError("frame-bad-version", str(version))
    if length == 0:
        raise FramingError("frame-empty-payload")
    if length > MAX_PAYLOAD_BYTES:
        raise FramingError("frame-oversize", str(length))
    remaining = total - RESPONSE_HEADER_BYTES
    if remaining < length:
        raise FramingError("frame-truncated-payload", f"{remaining} < {length}")
    if remaining > length:
        raise FramingError("frame-trailing-bytes", f"{remaining} > {length}")
    offset = 20
    request_sha256 = _slot_digest(buffer, offset, "request_sha256")
    broker_nonce = _slot_nonce(buffer, offset + 32, "broker_nonce")
    cleanup_sha256 = _slot_digest(buffer, offset + 64, "cleanup_sha256")
    return ResponseFrame(
        payload=buffer[RESPONSE_HEADER_BYTES:],
        status=status,
        request_sha256=request_sha256,
        broker_nonce=broker_nonce,
        cleanup_sha256=cleanup_sha256,
    )


def read_exact(stream: object, count: int, label: str) -> bytes:
    read = getattr(stream, "read", None)
    if not callable(read):
        raise FramingError("frame-stream-unreadable")
    chunks: list[bytes] = []
    remaining = count
    while remaining > 0:
        chunk = read(remaining)
        if not chunk:
            raise FramingError("frame-truncated-stream", label)
        chunk = bytes(chunk)
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_request_frame(stream: object) -> RequestFrame:
    header = read_exact(stream, REQUEST_HEADER_BYTES, "request-header")
    if header[:FRAME_MAGIC_BYTES] != FRAME_MAGIC:
        raise FramingError("frame-bad-magic")
    version, length = struct.unpack(">II", header[8:16])
    if version != PROTOCOL_VERSION:
        raise FramingError("frame-bad-version", str(version))
    if length == 0:
        raise FramingError("frame-empty-payload")
    if length > MAX_PAYLOAD_BYTES:
        raise FramingError("frame-oversize", str(length))
    payload = read_exact(stream, length, "request-payload")
    read = getattr(stream, "read", None)
    trailing = read(1) if callable(read) else b""
    if trailing:
        raise FramingError("frame-trailing-bytes")
    return decode_request_frame(header + payload)


# ---------------------------------------------------------------------------
# Request, authority and receipt validation.
# ---------------------------------------------------------------------------


def _exact_keys(
    value: object,
    allowed: tuple[str, ...],
    scope: str,
    *,
    forbidden: frozenset[str] = frozenset(),
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValidationError("not-object", scope)
    for key in value:
        if not isinstance(key, str):
            raise ValidationError("not-object", scope)
        if key in forbidden:
            raise ValidationError("forbidden-field", f"{scope}.{key}")
        if key not in allowed:
            raise ValidationError("unknown-field", f"{scope}.{key}")
    for key in allowed:
        if key not in value:
            raise ValidationError("missing-field", f"{scope}.{key}")
    return value


def _check_string_fields(value: object, scope: str) -> None:
    if isinstance(value, str):
        _check_path_like(scope, value)
    elif isinstance(value, dict):
        for key, item in value.items():
            _check_string_fields(item, f"{scope}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _check_string_fields(item, f"{scope}[{index}]")


def validate_payload(payload: object) -> dict[str, object]:
    body = _exact_keys(payload, PAYLOAD_FIELDS, "payload", forbidden=FORBIDDEN_FIELD_NAMES)
    task = _require_string(body["task"], "payload.task")
    if _IDENTIFIER_RE.fullmatch(task) is None:
        raise ValidationError("bad-task-identifier", task)
    _check_path_like("payload.task", task)
    inputs = body["inputs"]
    if not isinstance(inputs, dict):
        raise ValidationError("bad-inputs", "payload.inputs")
    if len(inputs) > MAX_PAYLOAD_INPUTS:
        raise ValidationError("too-many-inputs", str(len(inputs)))
    for name, digest in inputs.items():
        if not isinstance(name, str) or _INPUT_NAME_RE.fullmatch(name) is None:
            raise ValidationError("bad-input-name", str(name))
        if name in FORBIDDEN_FIELD_NAMES:
            raise ValidationError("forbidden-field", f"payload.inputs.{name}")
        _require_digest(digest, f"payload.inputs.{name}")
    return body


def request_signing_value(request: object) -> dict[str, object]:
    body = _exact_keys(request, REQUEST_FIELDS, "request", forbidden=FORBIDDEN_FIELD_NAMES)
    return {key: body[key] for key in REQUEST_HASHED_FIELDS}


def compute_request_hash(request: object) -> str:
    return request_hash(request_signing_value(request))


def validate_request(request: object) -> dict[str, object]:
    body = _exact_keys(request, REQUEST_FIELDS, "request", forbidden=FORBIDDEN_FIELD_NAMES)
    if type(body["schema_version"]) is not int or body["schema_version"] != SCHEMA_VERSION:
        raise ValidationError("bad-schema-version", "request.schema_version")
    if body["kind"] != KIND_REQUEST:
        raise ValidationError("bad-kind", "request.kind")
    if body["authority_id"] != AUTHORITY_ID:
        raise ValidationError("bad-authority-id", str(body["authority_id"]))
    _require_digest(body["claimed_authority_sha256"], "request.claimed_authority_sha256")
    _require_digest(body["claimed_release_sha256"], "request.claimed_release_sha256")
    _require_digest(body["claimed_policy_sha256"], "request.claimed_policy_sha256")
    nonce = _require_string(body["client_nonce"], "request.client_nonce")
    if _NONCE_RE.fullmatch(nonce) is None:
        raise ValidationError("bad-client-nonce", nonce)
    payload = validate_payload(body["payload"])
    expected_payload_hash = domain_digest(DOMAIN_REQUEST + "/payload", payload)
    if body["payload_sha256"] != expected_payload_hash:
        raise ValidationError("payload-reference-mismatch", "request.payload_sha256")
    expected_request_hash = compute_request_hash(body)
    if body["request_hash"] != expected_request_hash:
        raise ValidationError("request-hash-mismatch", "request.request_hash")
    _check_string_fields(body, "request")
    return body


def payload_reference(payload: object) -> str:
    return domain_digest(DOMAIN_REQUEST + "/payload", validate_payload(payload))


def build_request(
    *,
    client_nonce: str,
    payload: object,
    claimed_authority_sha256: str,
    claimed_release_sha256: str,
    claimed_policy_sha256: str,
) -> dict[str, object]:
    body: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND_REQUEST,
        "authority_id": AUTHORITY_ID,
        "claimed_authority_sha256": claimed_authority_sha256,
        "claimed_release_sha256": claimed_release_sha256,
        "claimed_policy_sha256": claimed_policy_sha256,
        "client_nonce": client_nonce,
        "payload": validate_payload(payload),
        "payload_sha256": "",
        "request_hash": "",
    }
    body["payload_sha256"] = payload_reference(body["payload"])
    body["request_hash"] = compute_request_hash(body)
    return validate_request(body)


def _validate_principal(
    identity: object, scope: str, *, user: str, allow_root: bool = False
) -> dict[str, object]:
    body = _exact_keys(identity, ("user", "uid", "gid"), scope)
    if body["user"] != user:
        raise ValidationError("bad-user", f"{scope}.user")
    minimum = 0 if allow_root else 1
    _require_strict_int(body["uid"], f"{scope}.uid", minimum=minimum, maximum=2**32 - 1)
    _require_strict_int(body["gid"], f"{scope}.gid", minimum=minimum, maximum=2**32 - 1)
    return body


def _validate_policy_identity(policy: object, scope: str) -> dict[str, object]:
    body = _exact_keys(policy, ("template_sha256", "parameters", "resolved_sha256"), scope)
    _require_digest(body["template_sha256"], f"{scope}.template_sha256")
    parameters = body["parameters"]
    if not isinstance(parameters, dict):
        raise ValidationError("bad-policy-parameters", f"{scope}.parameters")
    if len(parameters) > MAX_POLICY_PARAMETERS:
        raise ValidationError("too-many-policy-parameters", str(len(parameters)))
    for name, value in parameters.items():
        if not isinstance(name, str) or _POLICY_PARAM_RE.fullmatch(name) is None:
            raise ValidationError("bad-policy-parameter-name", str(name))
        _require_digest(value, f"{scope}.parameters.{name}")
    expected_resolved = policy_hash(str(body["template_sha256"]), parameters)
    if body["resolved_sha256"] != expected_resolved:
        raise ValidationError("policy-resolved-mismatch", f"{scope}.resolved_sha256")
    return body


def validate_authority(authority: object) -> dict[str, object]:
    body = _exact_keys(authority, AUTHORITY_FIELDS, "authority")
    if type(body["schema_version"]) is not int or body["schema_version"] != SCHEMA_VERSION:
        raise ValidationError("bad-schema-version", "authority.schema_version")
    if body["kind"] != KIND_AUTHORITY:
        raise ValidationError("bad-kind", "authority.kind")
    if body["authority_id"] != AUTHORITY_ID:
        raise ValidationError("bad-authority-id", str(body["authority_id"]))
    mode = body["mode"]
    if mode not in (MODE_SYNTHETIC, MODE_PROTECTED_PUBLIC_SYNTHETIC, MODE_PRODUCTION):
        raise ValidationError("bad-mode", str(mode))
    signing_fields = (
        ("algorithm", "key_id", "public_key")
        if mode == MODE_PROTECTED_PUBLIC_SYNTHETIC
        else ("algorithm", "key_id")
    )
    signing = _exact_keys(body["signing"], signing_fields, "authority.signing")
    expected_algorithm = SYNTHETIC_ALGORITHM if mode == MODE_SYNTHETIC else PRODUCTION_ALGORITHM
    if signing["algorithm"] != expected_algorithm:
        raise ValidationError("algorithm-mode-mismatch", str(signing["algorithm"]))
    _require_digest(signing["key_id"], "authority.signing.key_id")
    if mode == MODE_PROTECTED_PUBLIC_SYNTHETIC:
        try:
            public_key = ed25519.decode_public_key(signing["public_key"])
            expected_key_id = ed25519.mode_scoped_key_id(public_key, mode=mode)
        except ed25519.Ed25519ContractError as error:
            raise ValidationError(error.reason, f"authority.signing.{error.detail}") from error
        if signing["key_id"] != expected_key_id:
            raise ValidationError("mode-scoped-key-id-mismatch", "authority.signing.key_id")
    broker = _validate_principal(
        body["broker_identity"], "authority.broker_identity", user="_metisbroker"
    )
    runner = _validate_principal(
        body["runner_identity"], "authority.runner_identity", user="_metisrunner"
    )
    if broker["uid"] == runner["uid"]:
        raise ValidationError("principal-uid-collision", "broker/runner uid must differ")
    launcher = _validate_principal(
        body["launcher_identity"], "authority.launcher_identity", user="root", allow_root=True
    )
    if launcher["uid"] != 0 or launcher["gid"] != 0:
        raise ValidationError("launcher-not-root", "authority.launcher_identity")
    installed = _exact_keys(
        body["installed_code_identity"],
        INSTALLED_CODE_DIGEST_FIELDS,
        "authority.installed_code_identity",
    )
    for key, value in installed.items():
        _require_digest(value, f"authority.installed_code_identity.{key}")
    paths = _exact_keys(
        body["installed_code_paths"], INSTALLED_CODE_ROLES, "authority.installed_code_paths"
    )
    path_values: list[str] = []
    for role, value in paths.items():
        path = _require_string(value, f"authority.installed_code_paths.{role}")
        if re.fullmatch(ROSTER_PATH_PATTERN, path) is None:
            raise ValidationError("bad-roster-path", path)
        path_values.append(path)
    if len(path_values) != len(set(path_values)):
        raise ValidationError("installed-path-duplicate", "authority.installed_code_paths")
    roster = _validate_roster(body["installed_code_roster"], "authority.installed_code_roster")
    if len(roster) < len(INSTALLED_CODE_ROLES):
        raise ValidationError("installed-roster-incomplete", "authority.installed_code_roster")
    roster_by_path = {str(row["path"]): row for row in roster}
    if not set(path_values) <= set(roster_by_path):
        raise ValidationError("installed-roster-path-mismatch")
    for role, path in paths.items():
        digest_field = ROLE_DIGEST_FIELD[role]
        if roster_by_path[str(path)]["sha256"] != installed[digest_field]:
            raise ValidationError("installed-roster-digest-mismatch", role)
    _validate_policy_identity(body["policy_identity"], "authority.policy_identity")
    release = _exact_keys(
        body["release_identity"],
        ("release_id", "ancestry_root_sha256"),
        "authority.release_identity",
    )
    release_id = _require_string(release["release_id"], "authority.release_identity.release_id")
    if _IDENTIFIER_RE.fullmatch(release_id) is None:
        raise ValidationError("bad-release-id", release_id)
    _require_digest(
        release["ancestry_root_sha256"], "authority.release_identity.ancestry_root_sha256"
    )
    expected_ancestry = release_ancestry_hash(release_id, roster)
    if release["ancestry_root_sha256"] != expected_ancestry:
        raise ValidationError("release-ancestry-mismatch")
    return body


def cross_bind_authority(request: object, authority: object) -> str:
    """Cross-bind a request's claimed authority digest to independent measurement.

    The caller digest is a claim only; the authority document is re-measured
    from its own canonical bytes and the claim must match.  A caller-supplied
    (bytes, digest) pair can never self-authorize.
    """

    request_body = validate_request(request)
    authority_body = validate_authority(authority)
    measured = authority_hash(authority_body)
    if request_body["claimed_authority_sha256"] != measured:
        raise ValidationError("authority-claim-mismatch", measured)
    if (
        request_body["claimed_release_sha256"]
        != authority_body["release_identity"]["ancestry_root_sha256"]
    ):
        raise ValidationError("release-claim-mismatch")
    if (
        request_body["claimed_policy_sha256"]
        != authority_body["policy_identity"]["resolved_sha256"]
    ):
        raise ValidationError("policy-claim-mismatch")
    return measured


def _validate_roster(rows: object, scope: str) -> list[dict[str, object]]:
    if not isinstance(rows, list) or not rows:
        raise ValidationError("roster-empty", scope)
    validated: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    for index, row in enumerate(rows):
        label = f"{scope}[{index}]"
        body = _exact_keys(row, ROSTER_ROW_FIELDS, label)
        path = _require_string(body["path"], f"{label}.path")
        if re.fullmatch(ROSTER_PATH_PATTERN, path) is None:
            raise ValidationError("bad-roster-path", path)
        if path in seen_paths:
            raise ValidationError("roster-path-duplicate", path)
        seen_paths.add(path)
        _require_strict_int(body["size"], f"{label}.size", minimum=0, maximum=2**63 - 1)
        mode = _require_strict_int(
            body["mode"],
            f"{label}.mode",
            minimum=stat.S_IFREG,
            maximum=stat.S_IFREG | 0o7777,
        )
        if not stat.S_ISREG(mode):
            raise ValidationError("roster-not-regular", path)
        if mode & 0o022:
            raise ValidationError("roster-writable", path)
        _require_digest(body["sha256"], f"{label}.sha256")
        uid = _require_strict_int(body["uid"], f"{label}.uid", minimum=0, maximum=2**32 - 1)
        gid = _require_strict_int(body["gid"], f"{label}.gid", minimum=0, maximum=2**32 - 1)
        if uid != 0 or gid != 0:
            raise ValidationError("roster-not-root-owned", path)
        _require_strict_int(body["dev"], f"{label}.dev", minimum=0, maximum=2**63 - 1)
        _require_strict_int(body["ino"], f"{label}.ino", minimum=0, maximum=2**63 - 1)
        nlink = _require_strict_int(body["nlink"], f"{label}.nlink", minimum=1, maximum=2**63 - 1)
        if nlink != 1:
            raise ValidationError("roster-not-single-link", path)
        validated.append(body)
    paths = [str(row["path"]) for row in validated]
    if paths != sorted(paths):
        raise ValidationError("roster-unsorted", scope)
    return validated


def validate_receipt(receipt: object) -> dict[str, object]:
    body = _exact_keys(receipt, RECEIPT_FIELDS, "receipt")
    if type(body["schema_version"]) is not int or body["schema_version"] != SCHEMA_VERSION:
        raise ValidationError("bad-schema-version", "receipt.schema_version")
    if body["kind"] != KIND_RECEIPT:
        raise ValidationError("bad-kind", "receipt.kind")
    mode = body["mode"]
    if mode not in (MODE_SYNTHETIC, MODE_PROTECTED_PUBLIC_SYNTHETIC, MODE_PRODUCTION):
        raise ValidationError("bad-mode", str(mode))
    executed = body["executed_preimage_authority"]
    if type(executed) is not bool:
        raise ValidationError("bad-executed-flag", "receipt.executed_preimage_authority")
    nonclaims = body["nonclaims"]
    if not isinstance(nonclaims, list) or any(type(item) is not str for item in nonclaims):
        raise ValidationError("bad-nonclaims", "receipt.nonclaims")
    if mode == MODE_SYNTHETIC:
        if tuple(nonclaims) != SYNTHETIC_NONCLAIMS:
            raise ValidationError("nonclaims-mismatch", "synthetic receipt nonclaims")
        if executed is not False:
            raise ValidationError("synthetic-executed-flag", "must be false")
    elif mode == MODE_PROTECTED_PUBLIC_SYNTHETIC:
        if tuple(nonclaims) != PROTECTED_PUBLIC_SYNTHETIC_NONCLAIMS:
            raise ValidationError(
                "nonclaims-mismatch", "protected-public-synthetic receipt nonclaims"
            )
        if executed is not True:
            raise ValidationError("protected-executed-flag", "must be true")
    else:
        if "executed_preimage_authority=false" in nonclaims:
            raise ValidationError("nonclaims-mismatch", "production receipt nonclaims")
        if executed is not True:
            raise ValidationError("production-executed-flag", "must be true")

    request_bind = _exact_keys(
        body["request"],
        (
            "request_hash",
            "client_nonce",
            "claimed_authority_sha256",
            "claimed_release_sha256",
            "claimed_policy_sha256",
        ),
        "receipt.request",
    )
    _require_digest(request_bind["request_hash"], "receipt.request.request_hash")
    nonce = _require_string(request_bind["client_nonce"], "receipt.request.client_nonce")
    if _NONCE_RE.fullmatch(nonce) is None:
        raise ValidationError("bad-client-nonce", nonce)
    for key in ("claimed_authority_sha256", "claimed_release_sha256", "claimed_policy_sha256"):
        _require_digest(request_bind[key], f"receipt.request.{key}")

    measured = _exact_keys(
        body["measured"],
        ("authority_sha256", "release_sha256", "policy_sha256"),
        "receipt.measured",
    )
    for key, value in measured.items():
        _require_digest(value, f"receipt.measured.{key}")

    broker_nonce = _require_string(body["broker_nonce"], "receipt.broker_nonce")
    if _NONCE_RE.fullmatch(broker_nonce) is None:
        raise ValidationError("bad-broker-nonce", broker_nonce)
    _require_strict_int(
        body["attempt_sequence"], "receipt.attempt_sequence", minimum=1, maximum=2**63 - 1
    )
    _require_strict_int(
        body["receipt_sequence"], "receipt.receipt_sequence", minimum=1, maximum=2**63 - 1
    )
    if body["attempt_sequence"] < body["receipt_sequence"]:
        raise ValidationError("receipt-sequence-exceeds-attempt", "receipt.receipt_sequence")
    _require_digest(body["previous_receipt_sha256"], "receipt.previous_receipt_sha256")

    identities = _exact_keys(
        body["identities"], ("broker", "launcher", "worker", "node", "loader"), "receipt.identities"
    )
    broker_identity = _exact_keys(
        identities["broker"], ("user", "code_sha256"), "receipt.identities.broker"
    )
    if broker_identity["user"] != "_metisbroker":
        raise ValidationError("bad-user", "receipt.identities.broker.user")
    _require_digest(broker_identity["code_sha256"], "receipt.identities.broker.code_sha256")
    for principal in ("launcher", "worker"):
        section = _exact_keys(
            identities[principal], ("code_sha256",), f"receipt.identities.{principal}"
        )
        _require_digest(section["code_sha256"], f"receipt.identities.{principal}.code_sha256")
    node = _exact_keys(identities["node"], ("sha256", "version"), "receipt.identities.node")
    _require_digest(node["sha256"], "receipt.identities.node.sha256")
    version = _require_string(node["version"], "receipt.identities.node.version")
    if _NODE_VERSION_RE.fullmatch(version) is None:
        raise ValidationError("bad-node-version", version)
    loader = _exact_keys(identities["loader"], ("sha256",), "receipt.identities.loader")
    _require_digest(loader["sha256"], "receipt.identities.loader.sha256")

    effective = _exact_keys(
        body["effective_ids"],
        ("broker_uid", "broker_gid", "runner_uid", "runner_gid", "launcher_uid", "launcher_gid"),
        "receipt.effective_ids",
    )
    for key in ("broker_uid", "broker_gid", "runner_uid", "runner_gid"):
        _require_strict_int(
            effective[key], f"receipt.effective_ids.{key}", minimum=1, maximum=2**32 - 1
        )
    if effective["broker_uid"] == effective["runner_uid"]:
        raise ValidationError("principal-uid-collision", "broker/runner uid must differ")
    launcher_uid = _require_strict_int(
        effective["launcher_uid"], "receipt.effective_ids.launcher_uid", minimum=0, maximum=0
    )
    launcher_gid = _require_strict_int(
        effective["launcher_gid"], "receipt.effective_ids.launcher_gid", minimum=0, maximum=0
    )
    if launcher_uid != 0 or launcher_gid != 0:
        raise ValidationError("launcher-not-root", "receipt.effective_ids")

    _validate_policy_identity(body["policy"], "receipt.policy")

    roster = _exact_keys(body["roster"], ("pre", "post"), "receipt.roster")
    _validate_roster(roster["pre"], "receipt.roster.pre")
    _validate_roster(roster["post"], "receipt.roster.post")

    output = _exact_keys(
        body["output"],
        ("stdout_sha256", "stderr_sha256", "exit_code", "publication"),
        "receipt.output",
    )
    _require_digest(output["stdout_sha256"], "receipt.output.stdout_sha256")
    _require_digest(output["stderr_sha256"], "receipt.output.stderr_sha256")
    _require_strict_int(
        output["exit_code"],
        "receipt.output.exit_code",
        minimum=EXIT_CODE_RANGE[0],
        maximum=EXIT_CODE_RANGE[1],
    )
    publication = _exact_keys(
        output["publication"], ("sha256", "size", "atomic"), "receipt.output.publication"
    )
    _require_digest(publication["sha256"], "receipt.output.publication.sha256")
    _require_strict_int(
        publication["size"], "receipt.output.publication.size", minimum=0, maximum=2**63 - 1
    )
    if publication["atomic"] is not True:
        raise ValidationError("publication-not-atomic", "receipt.output.publication.atomic")

    cleanup = _exact_keys(
        body["cleanup"], ("process_census", "fd_census", "temp_census"), "receipt.cleanup"
    )
    process_census = _exact_keys(
        cleanup["process_census"],
        ("residual_children", "census_sha256"),
        "receipt.cleanup.process_census",
    )
    residual_children = _require_strict_int(
        process_census["residual_children"],
        "receipt.cleanup.process_census.residual_children",
        minimum=0,
        maximum=2**31 - 1,
    )
    if residual_children != 0:
        raise ValidationError("cleanup-residual-children", "must be zero before signing")
    _require_digest(process_census["census_sha256"], "receipt.cleanup.process_census.census_sha256")
    fd_census = _exact_keys(
        cleanup["fd_census"], ("retained_fds", "census_sha256"), "receipt.cleanup.fd_census"
    )
    retained_fds = _require_strict_int(
        fd_census["retained_fds"],
        "receipt.cleanup.fd_census.retained_fds",
        minimum=0,
        maximum=2**31 - 1,
    )
    if retained_fds != 0:
        raise ValidationError("cleanup-retained-fds", "must be zero before signing")
    _require_digest(fd_census["census_sha256"], "receipt.cleanup.fd_census.census_sha256")
    temp_census = _exact_keys(
        cleanup["temp_census"], ("entries", "roster_sha256"), "receipt.cleanup.temp_census"
    )
    if temp_census["entries"] != []:
        raise ValidationError("cleanup-temp-residual", "must be empty before signing")
    _require_digest(temp_census["roster_sha256"], "receipt.cleanup.temp_census.roster_sha256")

    signature = _exact_keys(
        body["signature"], ("algorithm", "key_id", "value"), "receipt.signature"
    )
    expected_algorithm = SYNTHETIC_ALGORITHM if mode == MODE_SYNTHETIC else PRODUCTION_ALGORITHM
    if signature["algorithm"] != expected_algorithm:
        raise ValidationError("algorithm-mode-mismatch", str(signature["algorithm"]))
    _require_digest(signature["key_id"], "receipt.signature.key_id")
    value = _require_string(signature["value"], "receipt.signature.value")
    if mode == MODE_SYNTHETIC:
        if re.fullmatch(r"[0-9a-f]{64}", value) is None:
            raise ValidationError("bad-signature-value", "synthetic hmac must be 64 lowercase hex")
    else:
        try:
            ed25519.decode_signature(value)
        except ed25519.Ed25519ContractError as error:
            raise ValidationError("bad-signature-value", error.reason) from error
    return body


# ---------------------------------------------------------------------------
# Signing material and the Phase A public synthetic signer (zero authority).
# ---------------------------------------------------------------------------


def receipt_signing_bytes(receipt: object) -> bytes:
    """Canonical signed material: every receipt field except signature.value."""

    body = validate_receipt(receipt)
    signature = dict(body["signature"])
    signature.pop("value", None)
    material = {key: body[key] for key in RECEIPT_FIELDS if key != "signature"}
    material["signature"] = signature
    return canonical_bytes(material)


def synthetic_key_id() -> str:
    return domain_digest(DOMAIN_SYNTHETIC_KEY, {"label": SYNTHETIC_KEY_LABEL})


def synthetic_signature(signing_bytes: bytes) -> str:
    if not isinstance(signing_bytes, bytes | bytearray):
        raise ValidationError("bad-signing-bytes")
    return hmac.new(SYNTHETIC_KEY_MATERIAL, bytes(signing_bytes), hashlib.sha256).hexdigest()


def verify_synthetic_signature(signing_bytes: bytes, *, signature_value: str, key_id: str) -> bool:
    if key_id != synthetic_key_id():
        return False
    expected = synthetic_signature(signing_bytes)
    return hmac.compare_digest(expected, signature_value)


def attach_synthetic_signature(receipt: object) -> dict[str, object]:
    body = validate_receipt(receipt)
    if body["mode"] != MODE_SYNTHETIC:
        raise ValidationError(
            "synthetic-signer-misuse", "production receipts cannot use Phase A signer"
        )
    signature = dict(body["signature"])
    if signature["algorithm"] != SYNTHETIC_ALGORITHM:
        raise ValidationError("algorithm-mode-mismatch", str(signature["algorithm"]))
    signature["key_id"] = synthetic_key_id()
    signature["value"] = synthetic_signature(
        receipt_signing_bytes({**body, "signature": signature})
    )
    signed = {**body, "signature": signature}
    validate_receipt(signed)
    return signed


def attach_protected_public_synthetic_signature(
    receipt: object,
    *,
    private_key: bytes,
    registered_key_id: str,
) -> dict[str, object]:
    """Sign with trusted broker key bytes already bound by protected authority."""

    body = validate_receipt(receipt)
    if body["mode"] != MODE_PROTECTED_PUBLIC_SYNTHETIC:
        raise ValidationError("protected-signer-misuse", str(body["mode"]))
    try:
        public_key = ed25519.derive_public_key(private_key)
        expected_key_id = ed25519.mode_scoped_key_id(
            public_key,
            mode=MODE_PROTECTED_PUBLIC_SYNTHETIC,
        )
    except ed25519.Ed25519ContractError as error:
        raise ValidationError(error.reason, error.detail) from error
    if registered_key_id != expected_key_id:
        raise ValidationError("mode-scoped-key-id-mismatch", "registered authority")
    unsigned_signature = {
        "algorithm": PRODUCTION_ALGORITHM,
        "key_id": registered_key_id,
        "value": ed25519.encode_signature(bytes(ed25519.SIGNATURE_BYTES)),
    }
    unsigned = {**body, "signature": unsigned_signature}
    try:
        algorithm, key_id, value = ed25519.sign_protected(
            private_key,
            receipt_signing_bytes(unsigned),
        )
    except ed25519.Ed25519ContractError as error:
        raise ValidationError(error.reason, error.detail) from error
    if algorithm != PRODUCTION_ALGORITHM or key_id != registered_key_id:
        raise ValidationError("mode-scoped-key-id-mismatch", "signer result")
    signed = {**body, "signature": {**unsigned_signature, "value": value}}
    validate_receipt(signed)
    return signed


def verify_receipt_signature(
    receipt: object,
    *,
    public_key: bytes | None = None,
    registered_key_id: str | None = None,
) -> bool:
    body = validate_receipt(receipt)
    if body["mode"] == MODE_SYNTHETIC:
        return verify_synthetic_signature(
            receipt_signing_bytes(body),
            signature_value=str(body["signature"]["value"]),
            key_id=str(body["signature"]["key_id"]),
        )
    if body["mode"] == MODE_PROTECTED_PUBLIC_SYNTHETIC:
        if public_key is None or registered_key_id is None:
            raise ValidationError(
                "protected-verification-key-required",
                "registered public key and key id are out-of-band authority",
            )
        try:
            return ed25519.verify_protected(
                public_key,
                receipt_signing_bytes(body),
                signature=body["signature"]["value"],
                key_id=body["signature"]["key_id"],
                registered_key_id=registered_key_id,
            )
        except ed25519.Ed25519ContractError as error:
            raise ValidationError(error.reason, error.detail) from error
    raise ValidationError(
        "production-verification-unavailable",
        "L70 does not make production verification or a production key available",
    )
