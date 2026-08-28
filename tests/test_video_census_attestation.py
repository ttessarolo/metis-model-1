from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from jsonschema import Draft202012Validator

from metis_model1 import video_census_attestation as attestation


def _materials(seed: bytes = bytes(range(32))) -> dict[str, Any]:
    private_key = Ed25519PrivateKey.from_private_bytes(seed)
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    authority = {
        "issuer": "synthetic-readonly-authority",
        "key_id": "synthetic-key-v1",
        "algorithm": "Ed25519",
        "public_key": public_key.hex(),
        "public_key_fingerprint": attestation.public_key_fingerprint(public_key),
        "status": "active",
    }
    trust_store = {
        "schema_version": 1,
        "trust_store_id": "synthetic-census-trust-v1",
        "trust_store_revision": "sha256:" + "0" * 64,
        "audience": "metis-model1.video-census",
        "max_ttl_seconds": 86400,
        "clock_skew_seconds": 0,
        "authorities": [authority],
    }
    trust_store["trust_store_revision"] = attestation.trust_store_revision(trust_store)
    scope = {
        "audience": "metis-model1.video-census",
        "tenant_ref": "synthetic-tenant-v1",
        "catalog_ref": "video",
        "alias_ref": "synthetic-video-alias-v1",
        "index_ref": "synthetic-video-index-v1",
        "profile_revision": "sha256:" + "1" * 64,
        "credential_handle_ref": "hmac-sha256:" + "2" * 64,
        "capabilities": list(attestation.EXACT_CAPABILITIES),
    }
    body = {
        "schema_version": 1,
        "attestation_type": attestation.ATTESTATION_TYPE,
        "algorithm": attestation.ALGORITHM,
        "issuer": authority["issuer"],
        "key_id": authority["key_id"],
        "key_fingerprint": authority["public_key_fingerprint"],
        "attestation_id": "synthetic-attestation-v1",
        "replay_id": "synthetic-replay-v1",
        **scope,
        "issued_at": "2026-08-27T09:00:00Z",
        "not_before": "2026-08-27T09:00:00Z",
        "expires_at": "2026-08-27T11:00:00Z",
    }
    signed = {
        **body,
        "signature": private_key.sign(attestation.attestation_signing_bytes(body)).hex(),
    }
    return {
        "private_key": private_key,
        "public_key": public_key,
        "trust_store": trust_store,
        "scope": scope,
        "attestation": signed,
        "now": datetime(2026, 8, 27, 10, 0, 0, tzinfo=UTC),
        "valid_until": datetime(2026, 8, 27, 10, 30, 0, tzinfo=UTC),
    }


def _resign(materials: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    body = {key: value for key, value in materials["attestation"].items() if key != "signature"}
    body.update(changes)
    return {
        **body,
        "signature": materials["private_key"]
        .sign(attestation.attestation_signing_bytes(body))
        .hex(),
    }


def _verify(
    materials: dict[str, Any],
    *,
    signed: dict[str, Any] | None = None,
    trust_store: dict[str, Any] | None = None,
    expected_revision: str | None = None,
    scope: dict[str, Any] | None = None,
    replay_guard: attestation.CensusAttestationReplayGuard | None = None,
    now: datetime | None = None,
    valid_until: datetime | None = None,
) -> dict[str, Any]:
    selected_store = trust_store or materials["trust_store"]
    return attestation.verify_census_attestation(
        signed or materials["attestation"],
        trust_store=selected_store,
        expected_trust_store_revision=(expected_revision or selected_store["trust_store_revision"]),
        expected_scope=scope or materials["scope"],
        now=now or materials["now"],
        valid_until=valid_until or materials["valid_until"],
        replay_guard=replay_guard or attestation.CensusAttestationReplayGuard(),
    )


def test_valid_ed25519_attestation_emits_only_sanitized_bound_receipt() -> None:
    materials = _materials()
    receipt = _verify(materials)

    assert attestation.validate_attestation_receipt(receipt) == []
    assert receipt["status"] == "VALID"
    assert receipt["algorithm"] == "Ed25519"
    assert receipt["trust_store_revision"] == materials["trust_store"]["trust_store_revision"]
    assert receipt["attestation_sha256"] == attestation.canonical_hash(materials["attestation"])
    body = {key: value for key, value in materials["attestation"].items() if key != "signature"}
    assert receipt["signed_payload_sha256"] == attestation._raw_hash(
        attestation.attestation_signing_bytes(body)
    )
    assert receipt["bindings"] == materials["scope"]
    assert receipt["verification"] == {
        "audience_valid": True,
        "capability_roster_exact": True,
        "credential_handle_valid": True,
        "key_fingerprint_valid": True,
        "replay_id_consumed": True,
        "scope_valid": True,
        "signature_valid": True,
        "time_window_valid": True,
        "trust_store_pin_valid": True,
    }
    assert receipt["nonclaims"] == list(attestation.NONCLAIMS)

    public = attestation._canonical_bytes(receipt).decode("utf-8")
    for raw_value in (
        materials["attestation"]["issuer"],
        materials["attestation"]["key_id"],
        materials["attestation"]["attestation_id"],
        materials["attestation"]["replay_id"],
        materials["attestation"]["signature"],
        materials["trust_store"]["authorities"][0]["public_key"],
    ):
        assert raw_value not in public


def test_attestation_schema_is_valid_draft_2020_12() -> None:
    schema = attestation._receipt_schema_errors({})
    assert schema  # the empty object must fail the loaded schema
    raw = __import__("json").loads(attestation.ATTESTATION_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(raw)


def test_signature_mutation_is_rejected() -> None:
    materials = _materials()
    attacked = copy.deepcopy(materials["attestation"])
    attacked["signature"] = ("0" if attacked["signature"][0] != "0" else "1") + attacked[
        "signature"
    ][1:]

    with pytest.raises(attestation.CensusAttestationError, match="signature is invalid"):
        _verify(materials, signed=attacked)


def test_signature_from_untrusted_private_key_is_rejected() -> None:
    materials = _materials()
    untrusted = Ed25519PrivateKey.from_private_bytes(bytes(reversed(range(32))))
    body = {key: value for key, value in materials["attestation"].items() if key != "signature"}
    attacked = {
        **body,
        "signature": untrusted.sign(attestation.attestation_signing_bytes(body)).hex(),
    }

    with pytest.raises(attestation.CensusAttestationError, match="signature is invalid"):
        _verify(materials, signed=attacked)


def test_trust_store_revision_must_match_external_pin() -> None:
    materials = _materials()

    with pytest.raises(attestation.CensusAttestationError, match="externally pinned"):
        _verify(materials, expected_revision="sha256:" + "9" * 64)


def test_trusted_key_and_signed_fingerprint_must_match() -> None:
    materials = _materials()
    replacement = Ed25519PrivateKey.from_private_bytes(bytes(reversed(range(32))))
    replacement_public = replacement.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    trust_store = copy.deepcopy(materials["trust_store"])
    authority = trust_store["authorities"][0]
    authority["public_key"] = replacement_public.hex()
    authority["public_key_fingerprint"] = attestation.public_key_fingerprint(replacement_public)
    trust_store["trust_store_revision"] = attestation.trust_store_revision(trust_store)

    with pytest.raises(attestation.CensusAttestationError, match="fingerprint"):
        _verify(materials, trust_store=trust_store)


@pytest.mark.parametrize("field", ["issuer", "key_id"])
def test_untrusted_issuer_or_key_id_is_rejected(field: str) -> None:
    materials = _materials()
    attacked = _resign(materials, {field: f"untrusted-{field}"})

    with pytest.raises(attestation.CensusAttestationError, match="not trusted"):
        _verify(materials, signed=attacked)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {
                "issued_at": "2026-08-27T08:00:00Z",
                "not_before": "2026-08-27T08:00:00Z",
                "expires_at": "2026-08-27T09:59:59Z",
            },
            "expired",
        ),
        (
            {
                "issued_at": "2026-08-27T10:00:01Z",
                "not_before": "2026-08-27T10:00:01Z",
            },
            "future",
        ),
        ({"not_before": "2026-08-27T10:00:01Z"}, "not yet valid"),
        ({"expires_at": "2026-08-27T10:29:59Z"}, "required census boundary"),
        ({"expires_at": "2026-08-28T09:00:01Z"}, "TTL exceeds"),
    ],
)
def test_expiry_future_not_before_boundary_and_ttl_are_fail_closed(
    changes: dict[str, Any], message: str
) -> None:
    materials = _materials()
    attacked = _resign(materials, changes)

    with pytest.raises(attestation.CensusAttestationError, match=message):
        _verify(materials, signed=attacked)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("audience", "different-audience"),
        ("tenant_ref", "different-tenant"),
        ("catalog_ref", "different-catalog"),
        ("alias_ref", "different-alias"),
        ("index_ref", "different-index"),
        ("profile_revision", "sha256:" + "3" * 64),
        ("credential_handle_ref", "hmac-sha256:" + "4" * 64),
    ],
)
def test_effective_audience_scope_handle_profile_and_index_mismatch_is_rejected(
    field: str, value: str
) -> None:
    materials = _materials()
    scope = copy.deepcopy(materials["scope"])
    scope[field] = value

    with pytest.raises(attestation.CensusAttestationError, match=field):
        _verify(materials, scope=scope)


@pytest.mark.parametrize(
    "capabilities",
    [
        ["metadata-read", "aggregate-read"],
        ["aggregate-read", "metadata-read", "pit-lifecycle"],
        ["metadata-read", "aggregate-read", "pit-lifecycle", "document-read"],
    ],
)
def test_capabilities_are_an_exact_ordered_read_only_roster(capabilities: list[str]) -> None:
    materials = _materials()
    attacked = _resign(materials, {"capabilities": capabilities})

    with pytest.raises(attestation.CensusAttestationError, match="capability roster"):
        _verify(materials, signed=attacked)


def test_direct_credential_hash_is_not_an_allowed_handle_reference() -> None:
    materials = _materials()
    attacked = _resign(materials, {"credential_handle_ref": "sha256:" + "2" * 64})

    with pytest.raises(attestation.CensusAttestationError, match="HMAC"):
        _verify(materials, signed=attacked)


def test_replay_id_is_consumed_atomically_after_success() -> None:
    materials = _materials()
    guard = attestation.CensusAttestationReplayGuard()

    assert _verify(materials, replay_guard=guard)["status"] == "VALID"
    assert guard.consumed_count() == 1
    with pytest.raises(attestation.CensusAttestationError, match="already consumed"):
        _verify(materials, replay_guard=guard)
    assert guard.consumed_count() == 1


def test_bad_signature_does_not_burn_replay_id() -> None:
    materials = _materials()
    guard = attestation.CensusAttestationReplayGuard()
    attacked = copy.deepcopy(materials["attestation"])
    attacked["signature"] = "0" * 128

    with pytest.raises(attestation.CensusAttestationError, match="signature is invalid"):
        _verify(materials, signed=attacked, replay_guard=guard)
    assert guard.consumed_count() == 0
    assert _verify(materials, replay_guard=guard)["status"] == "VALID"


def test_receipt_content_tamper_breaks_self_hash() -> None:
    receipt = _verify(_materials())
    receipt["bindings"]["index_ref"] = "tampered-index"

    assert "attestation receipt self-hash is invalid" in attestation.validate_attestation_receipt(
        receipt
    )


def test_rehashed_receipt_cannot_turn_a_verification_bit_false() -> None:
    receipt = _verify(_materials())
    receipt["verification"]["signature_valid"] = False
    receipt["receipt_sha256"] = attestation.canonical_hash(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )

    assert attestation.validate_attestation_receipt(receipt)


def test_receipt_rejects_raw_signature_or_public_key_smuggling() -> None:
    materials = _materials()
    receipt = _verify(materials)
    receipt["signature"] = materials["attestation"]["signature"]
    receipt["receipt_sha256"] = attestation.canonical_hash(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )

    assert attestation.validate_attestation_receipt(receipt)


def test_trust_store_fingerprint_and_revision_drift_are_rejected() -> None:
    materials = _materials()
    trust_store = copy.deepcopy(materials["trust_store"])
    trust_store["authorities"][0]["public_key_fingerprint"] = "sha256:" + "0" * 64
    trust_store["trust_store_revision"] = attestation.trust_store_revision(trust_store)

    with pytest.raises(attestation.CensusAttestationError, match="fingerprint mismatch"):
        _verify(materials, trust_store=trust_store)

    trust_store = copy.deepcopy(materials["trust_store"])
    trust_store["max_ttl_seconds"] -= 1
    with pytest.raises(attestation.CensusAttestationError, match="canonical content"):
        _verify(materials, trust_store=trust_store)


def test_extra_attestation_field_is_rejected_before_signature_use() -> None:
    materials = _materials()
    attacked = copy.deepcopy(materials["attestation"])
    attacked["password"] = "must-not-cross"

    with pytest.raises(attestation.CensusAttestationError, match="exact contract"):
        _verify(materials, signed=attacked)


@pytest.mark.parametrize(
    ("now", "valid_until"),
    [
        (datetime(2026, 8, 27, 10, 0, 0), datetime(2026, 8, 27, 10, 30, 0, tzinfo=UTC)),
        (
            datetime(2026, 8, 27, 10, 0, 0, 1, tzinfo=UTC),
            datetime(2026, 8, 27, 10, 30, 0, tzinfo=UTC),
        ),
        (
            datetime(2026, 8, 27, 10, 0, 0, tzinfo=UTC),
            datetime(2026, 8, 27, 9, 59, 59, tzinfo=UTC),
        ),
    ],
)
def test_verification_context_time_is_exact_and_bounded(
    now: datetime, valid_until: datetime
) -> None:
    materials = _materials()

    with pytest.raises(attestation.CensusAttestationError):
        _verify(materials, now=now, valid_until=valid_until)


def test_pinned_clock_skew_is_represented_consistently_in_the_receipt() -> None:
    materials = _materials()
    trust_store = copy.deepcopy(materials["trust_store"])
    trust_store["clock_skew_seconds"] = 2
    trust_store["trust_store_revision"] = attestation.trust_store_revision(trust_store)
    signed = _resign(
        materials,
        {
            "issued_at": "2026-08-27T10:00:01Z",
            "not_before": "2026-08-27T10:00:01Z",
        },
    )

    receipt = _verify(materials, signed=signed, trust_store=trust_store)
    assert receipt["validity"]["clock_skew_seconds"] == 2
    assert attestation.validate_attestation_receipt(receipt) == []
