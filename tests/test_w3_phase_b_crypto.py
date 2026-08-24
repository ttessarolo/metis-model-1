"""L70.1 Ed25519 cases for protected public-synthetic receipts.

Exactly 12 named cases, all deterministic and key-generation-free:
three RFC8032 known-answer tests, three single-input mutations, wrong-key and
mode-scoped-key rejection, three malformed-encoding cases and production
denial. The private bytes below are published RFC test-vector seeds only.
"""

from __future__ import annotations

import base64
import importlib.util
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parents[1]
ED25519_PATH = PROJECT_ROOT / "runtime/w3_ed25519.py"

_SPEC = importlib.util.spec_from_file_location("w3_ed25519_under_test", ED25519_PATH)
assert _SPEC and _SPEC.loader
ED25519 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ED25519)

KAT_EMPTY = {
    "seed": "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
    "public": "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
    "message": "",
    "signature": (
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
    ),
}
KAT_72 = {
    "seed": "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
    "public": "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
    "message": "72",
    "signature": (
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
        "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"
    ),
}
KAT_AF82 = {
    "seed": "c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
    "public": "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
    "message": "af82",
    "signature": (
        "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac"
        "18ff9b538d16f290ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a"
    ),
}


def _bytes(vector: dict[str, str], field: str) -> bytes:
    return bytes.fromhex(vector[field])


def _assert_kat(vector: dict[str, str]) -> None:
    seed = _bytes(vector, "seed")
    public_key = _bytes(vector, "public")
    message = _bytes(vector, "message")
    expected_signature = _bytes(vector, "signature")

    assert ED25519.derive_public_key(seed) == public_key
    algorithm, key_id, encoded_signature = ED25519.sign_protected(seed, message)
    assert algorithm == ED25519.ALGORITHM
    assert ED25519.decode_signature(encoded_signature) == expected_signature
    assert key_id == ED25519.mode_scoped_key_id(
        public_key,
        mode=ED25519.MODE_PROTECTED_PUBLIC_SYNTHETIC,
    )
    assert ED25519.verify_protected(
        public_key,
        message,
        signature=encoded_signature,
        key_id=key_id,
        registered_key_id=key_id,
    )


def test_ed25519_rfc8032_kat_empty() -> None:
    _assert_kat(KAT_EMPTY)


def test_ed25519_rfc8032_kat_message_72() -> None:
    _assert_kat(KAT_72)


def test_ed25519_rfc8032_kat_message_af82() -> None:
    _assert_kat(KAT_AF82)


def test_ed25519_message_mutation_rejected() -> None:
    seed = _bytes(KAT_72, "seed")
    public_key = _bytes(KAT_72, "public")
    _, key_id, signature = ED25519.sign_protected(seed, _bytes(KAT_72, "message"))
    assert not ED25519.verify_protected(
        public_key,
        b"s",
        signature=signature,
        key_id=key_id,
        registered_key_id=key_id,
    )


def test_ed25519_signature_mutation_rejected() -> None:
    public_key = _bytes(KAT_AF82, "public")
    signature = bytearray(_bytes(KAT_AF82, "signature"))
    signature[31] ^= 0x01
    key_id = ED25519.mode_scoped_key_id(
        public_key,
        mode=ED25519.MODE_PROTECTED_PUBLIC_SYNTHETIC,
    )
    assert not ED25519.verify_protected(
        public_key,
        _bytes(KAT_AF82, "message"),
        signature=ED25519.encode_signature(signature),
        key_id=key_id,
        registered_key_id=key_id,
    )


def test_ed25519_public_key_mutation_rejected() -> None:
    public_key = bytearray(_bytes(KAT_EMPTY, "public"))
    public_key[0] ^= 0x01
    mutated_key_id = ED25519.mode_scoped_key_id(
        public_key,
        mode=ED25519.MODE_PROTECTED_PUBLIC_SYNTHETIC,
    )
    assert not ED25519.verify_protected(
        public_key,
        _bytes(KAT_EMPTY, "message"),
        signature=ED25519.encode_signature(_bytes(KAT_EMPTY, "signature")),
        key_id=mutated_key_id,
        registered_key_id=mutated_key_id,
    )


def test_ed25519_wrong_key_rejected() -> None:
    wrong_public_key = _bytes(KAT_72, "public")
    wrong_key_id = ED25519.mode_scoped_key_id(
        wrong_public_key,
        mode=ED25519.MODE_PROTECTED_PUBLIC_SYNTHETIC,
    )
    assert not ED25519.verify_protected(
        wrong_public_key,
        _bytes(KAT_EMPTY, "message"),
        signature=ED25519.encode_signature(_bytes(KAT_EMPTY, "signature")),
        key_id=wrong_key_id,
        registered_key_id=wrong_key_id,
    )


def test_ed25519_key_id_is_mode_scoped() -> None:
    public_key = _bytes(KAT_EMPTY, "public")
    protected_key_id = ED25519.mode_scoped_key_id(
        public_key,
        mode=ED25519.MODE_PROTECTED_PUBLIC_SYNTHETIC,
    )
    production_key_id = ED25519.mode_scoped_key_id(
        public_key,
        mode=ED25519.MODE_PRODUCTION,
    )
    assert protected_key_id != production_key_id
    with pytest.raises(ED25519.Ed25519ContractError, match="bad-key-mode"):
        ED25519.mode_scoped_key_id(public_key, mode="synthetic")
    with pytest.raises(ED25519.Ed25519ContractError, match="mode-scoped-key-id-mismatch"):
        ED25519.verify_protected(
            public_key,
            _bytes(KAT_EMPTY, "message"),
            signature=ED25519.encode_signature(_bytes(KAT_EMPTY, "signature")),
            key_id=production_key_id,
            registered_key_id=production_key_id,
        )


def test_ed25519_private_key_encoding_rejected() -> None:
    for malformed in (b"", bytes(31), bytes(33), "00" * 32):
        with pytest.raises(ED25519.Ed25519ContractError):
            ED25519.derive_public_key(malformed)
        with pytest.raises(ED25519.Ed25519ContractError):
            ED25519.sign_protected(malformed, b"message")


def test_ed25519_public_key_encoding_rejected() -> None:
    for malformed in (b"", bytes(31), bytes(33), "not-raw-bytes"):
        with pytest.raises(ED25519.Ed25519ContractError):
            ED25519.encode_public_key(malformed)
    for malformed in ("", "not-base64!", base64.b64encode(bytes(31)).decode("ascii"), "é" * 44):
        with pytest.raises(ED25519.Ed25519ContractError):
            ED25519.decode_public_key(malformed)


def test_ed25519_signature_encoding_rejected() -> None:
    canonical = ED25519.encode_signature(bytes(64))
    noncanonical_pad_bits = canonical[:-3] + "B=="
    for malformed in (
        "",
        "not-base64!",
        base64.b64encode(bytes(63)).decode("ascii"),
        base64.b64encode(bytes(65)).decode("ascii"),
        canonical + "\n",
        noncanonical_pad_bits,
        "é" * 88,
    ):
        with pytest.raises(ED25519.Ed25519ContractError):
            ED25519.decode_signature(malformed)


def test_production_mode_is_denied() -> None:
    public_key = _bytes(KAT_EMPTY, "public")
    production_key_id = ED25519.mode_scoped_key_id(
        public_key,
        mode=ED25519.MODE_PRODUCTION,
    )
    assert production_key_id.startswith(ED25519.SHA256_PREFIX)
    with pytest.raises(ED25519.Ed25519ContractError, match="production-mode-unavailable"):
        ED25519.reject_production_operation(ED25519.MODE_PRODUCTION)
    with pytest.raises(ED25519.Ed25519ContractError, match="bad-signing-mode"):
        ED25519.reject_production_operation("synthetic")
