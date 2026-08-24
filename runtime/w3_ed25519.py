#!/usr/bin/env python3
"""Pinned Ed25519 primitives for protected public-synthetic broker receipts.

This module is deliberately small: it wraps ``cryptography`` raw Ed25519 keys,
uses strict canonical base64 encodings and derives mode-scoped key identifiers.
It does not generate keys, read key files, select authorities or make a
production receipt acceptable.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import sys
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from metis_model1.provenance import canonical_json_bytes  # noqa: E402

SHA256_PREFIX = "sha256:"
ALGORITHM = "ed25519"
MODE_PROTECTED_PUBLIC_SYNTHETIC = "protected-public-synthetic"
MODE_PRODUCTION = "production"
KEY_ID_MODES = frozenset((MODE_PROTECTED_PUBLIC_SYNTHETIC, MODE_PRODUCTION))
DOMAIN_KEY_ID = "w3-protected-broker/ed25519-key/v1"

PRIVATE_KEY_BYTES = 32
PUBLIC_KEY_BYTES = 32
SIGNATURE_BYTES = 64


class Ed25519ContractError(ValueError):
    """Typed fail-closed error for malformed keys, signatures or modes."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(reason if not detail else f"{reason}: {detail}")


def _require_bytes(value: object, label: str, length: int) -> bytes:
    if not isinstance(value, bytes | bytearray):
        raise Ed25519ContractError("not-bytes", label)
    raw = bytes(value)
    if len(raw) != length:
        raise Ed25519ContractError("bad-length", f"{label} must be {length} bytes")
    return raw


def _require_message(value: object) -> bytes:
    if not isinstance(value, bytes | bytearray):
        raise Ed25519ContractError("not-bytes", "message")
    return bytes(value)


def _encode_base64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _decode_base64(value: object, label: str, length: int) -> bytes:
    if type(value) is not str:
        raise Ed25519ContractError("bad-base64", f"{label} must be an ASCII string")
    try:
        encoded = value.encode("ascii")
        raw = base64.b64decode(encoded, validate=True)
    except (UnicodeEncodeError, binascii.Error, ValueError) as error:
        raise Ed25519ContractError("bad-base64", label) from error
    if len(raw) != length:
        raise Ed25519ContractError("bad-length", f"{label} must decode to {length} bytes")
    if _encode_base64(raw) != value:
        raise Ed25519ContractError("noncanonical-base64", label)
    return raw


def encode_public_key(public_key: object) -> str:
    """Return canonical base64 for exactly one raw Ed25519 public key."""

    return _encode_base64(_require_bytes(public_key, "public-key", PUBLIC_KEY_BYTES))


def decode_public_key(value: object) -> bytes:
    """Decode canonical base64 into exactly 32 raw public-key bytes."""

    return _decode_base64(value, "public-key", PUBLIC_KEY_BYTES)


def encode_signature(signature: object) -> str:
    """Return canonical base64 for exactly one raw Ed25519 signature."""

    return _encode_base64(_require_bytes(signature, "signature", SIGNATURE_BYTES))


def decode_signature(value: object) -> bytes:
    """Decode canonical base64 into exactly 64 raw signature bytes."""

    return _decode_base64(value, "signature", SIGNATURE_BYTES)


def derive_public_key(private_key: object) -> bytes:
    """Derive raw public bytes from an exact 32-byte private seed."""

    seed = _require_bytes(private_key, "private-key", PRIVATE_KEY_BYTES)
    try:
        key = Ed25519PrivateKey.from_private_bytes(seed)
        return key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    except (TypeError, ValueError) as error:
        raise Ed25519ContractError("bad-private-key", "private-key") from error


def mode_scoped_key_id(public_key: object, *, mode: str) -> str:
    """Bind a public key identifier to exactly one evidence mode.

    Production is accepted here only as a namespace for collision testing and
    future registry construction; the signing and verification APIs below
    still reject production.
    """

    if type(mode) is not str or mode not in KEY_ID_MODES:
        raise Ed25519ContractError("bad-key-mode", str(mode))
    raw = _require_bytes(public_key, "public-key", PUBLIC_KEY_BYTES)
    envelope = {
        "domain": DOMAIN_KEY_ID,
        "body": {
            "algorithm": ALGORITHM,
            "mode": mode,
            "public_key": _encode_base64(raw),
        },
    }
    return SHA256_PREFIX + hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()


def sign_protected(private_key: object, message: object) -> tuple[str, str, str]:
    """Sign protected public-synthetic bytes; return algorithm, key id, signature."""

    seed = _require_bytes(private_key, "private-key", PRIVATE_KEY_BYTES)
    payload = _require_message(message)
    public_key = derive_public_key(seed)
    try:
        signature = Ed25519PrivateKey.from_private_bytes(seed).sign(payload)
    except (TypeError, ValueError) as error:
        raise Ed25519ContractError("sign-failed") from error
    return (
        ALGORITHM,
        mode_scoped_key_id(public_key, mode=MODE_PROTECTED_PUBLIC_SYNTHETIC),
        encode_signature(signature),
    )


def verify_protected(
    public_key: object,
    message: object,
    *,
    signature: object,
    key_id: object,
    registered_key_id: object,
) -> bool:
    """Verify against a separately registered protected-mode public key.

    A false return means a well-formed but invalid signature. Malformed input,
    a stale registry value or a key-id/mode mismatch fails with a typed error.
    """

    raw_public = _require_bytes(public_key, "public-key", PUBLIC_KEY_BYTES)
    payload = _require_message(message)
    raw_signature = decode_signature(signature)
    if type(key_id) is not str or type(registered_key_id) is not str:
        raise Ed25519ContractError("bad-key-id")
    expected_key_id = mode_scoped_key_id(
        raw_public,
        mode=MODE_PROTECTED_PUBLIC_SYNTHETIC,
    )
    if registered_key_id != expected_key_id or key_id != registered_key_id:
        raise Ed25519ContractError("mode-scoped-key-id-mismatch")
    try:
        Ed25519PublicKey.from_public_bytes(raw_public).verify(raw_signature, payload)
    except InvalidSignature:
        return False
    except (TypeError, ValueError) as error:
        raise Ed25519ContractError("bad-public-key") from error
    return True


def reject_production_operation(mode: object) -> None:
    """Explicit stop used by callers before any production signing/verification."""

    if mode == MODE_PRODUCTION:
        raise Ed25519ContractError("production-mode-unavailable")
    if mode != MODE_PROTECTED_PUBLIC_SYNTHETIC:
        raise Ed25519ContractError("bad-signing-mode", str(mode))
