"""Fail-closed Ed25519 contract for a sanitized census-attestation receipt.

The verifier is intentionally offline.  It accepts already-materialized public
metadata, an externally pinned trust-store revision, and an in-memory replay
guard.  It never opens a tenant, credential store, Keychain, environment file,
or network connection.  The returned receipt is therefore cryptographic
contract evidence only; it is not evidence that VSIX P4B or live census P6 ran.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from jsonschema import Draft202012Validator, FormatChecker

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ATTESTATION_SCHEMA = PROJECT_ROOT / "schemas/video-census-attestation.schema.json"
ATTESTATION_TYPE = "video-census-read-only-v1"
CONTRACT_ID = "video-census-attestation-ed25519-v1"
EVIDENCE_SCOPE = "synthetic_attestation_contract"
ALGORITHM = "Ed25519"
EXACT_CAPABILITIES = ("metadata-read", "aggregate-read", "pit-lifecycle")
SIGNING_DOMAIN = b"METIS-VIDEO-CENSUS-ATTESTATION-V1\x00"
HASH_RE = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
HANDLE_RE = re.compile(r"\Ahmac-sha256:[0-9a-f]{64}\Z")
HEX_32_RE = re.compile(r"\A[0-9a-f]{64}\Z")
HEX_64_RE = re.compile(r"\A[0-9a-f]{128}\Z")
ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
TIMESTAMP_RE = re.compile(r"\A[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z")

TRUST_STORE_KEYS = frozenset(
    {
        "schema_version",
        "trust_store_id",
        "trust_store_revision",
        "audience",
        "max_ttl_seconds",
        "clock_skew_seconds",
        "authorities",
    }
)
AUTHORITY_KEYS = frozenset(
    {"issuer", "key_id", "algorithm", "public_key", "public_key_fingerprint", "status"}
)
ATTESTATION_KEYS = frozenset(
    {
        "schema_version",
        "attestation_type",
        "algorithm",
        "issuer",
        "key_id",
        "key_fingerprint",
        "attestation_id",
        "replay_id",
        "audience",
        "tenant_ref",
        "catalog_ref",
        "alias_ref",
        "index_ref",
        "profile_revision",
        "credential_handle_ref",
        "capabilities",
        "issued_at",
        "not_before",
        "expires_at",
        "signature",
    }
)
SCOPE_KEYS = frozenset(
    {
        "audience",
        "tenant_ref",
        "catalog_ref",
        "alias_ref",
        "index_ref",
        "profile_revision",
        "credential_handle_ref",
        "capabilities",
    }
)
RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "evidence_scope",
        "contract_id",
        "status",
        "proof_type",
        "algorithm",
        "trust_store_id",
        "trust_store_revision",
        "attestation_sha256",
        "signed_payload_sha256",
        "issuer_ref",
        "key_id_ref",
        "key_fingerprint",
        "attestation_id_ref",
        "replay_id_ref",
        "bindings",
        "validity",
        "verification",
        "sanitized",
        "nonclaims",
        "receipt_sha256",
    }
)
BINDING_KEYS = SCOPE_KEYS
VALIDITY_KEYS = frozenset(
    {
        "issued_at",
        "not_before",
        "expires_at",
        "verified_at",
        "valid_until",
        "max_ttl_seconds",
        "clock_skew_seconds",
    }
)
VERIFICATION_KEYS = frozenset(
    {
        "trust_store_pin_valid",
        "key_fingerprint_valid",
        "signature_valid",
        "audience_valid",
        "scope_valid",
        "credential_handle_valid",
        "capability_roster_exact",
        "time_window_valid",
        "replay_id_consumed",
    }
)
NONCLAIMS = (
    "no_live_census",
    "no_live_role_observation",
    "no_secret_or_credential_access",
    "no_vsix_secretstorage_integration",
    "no_p4b_completion_claim",
    "no_p6_completion_claim",
    "no_production_replay_store",
    "no_cluster_write_probe",
)


class CensusAttestationError(ValueError):
    """Raised when signed read-only authority cannot be verified exactly."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise CensusAttestationError("value is not canonical JSON") from error


def canonical_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _raw_hash(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _exact_mapping(value: Any, keys: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise CensusAttestationError(f"{label} fields differ from the exact contract")
    return value


def _identifier(value: Any, label: str) -> str:
    if type(value) is not str or ID_RE.fullmatch(value) is None:
        raise CensusAttestationError(f"{label} is not a bounded opaque identifier")
    return value


def _hash(value: Any, label: str) -> str:
    if type(value) is not str or HASH_RE.fullmatch(value) is None:
        raise CensusAttestationError(f"{label} is not a sha256 digest")
    return value


def _handle(value: Any, label: str) -> str:
    if type(value) is not str or HANDLE_RE.fullmatch(value) is None:
        raise CensusAttestationError(f"{label} is not an HMAC credential-handle reference")
    return value


def _public_key(value: Any, label: str) -> tuple[str, bytes]:
    if type(value) is not str or HEX_32_RE.fullmatch(value) is None:
        raise CensusAttestationError(f"{label} is not a 32-byte Ed25519 public key")
    raw = bytes.fromhex(value)
    try:
        Ed25519PublicKey.from_public_bytes(raw)
    except ValueError as error:
        raise CensusAttestationError(f"{label} is not an Ed25519 public key") from error
    return value, raw


def _signature(value: Any) -> tuple[str, bytes]:
    if type(value) is not str or HEX_64_RE.fullmatch(value) is None:
        raise CensusAttestationError("attestation.signature is not a 64-byte Ed25519 signature")
    return value, bytes.fromhex(value)


def public_key_fingerprint(public_key: bytes) -> str:
    if type(public_key) is not bytes or len(public_key) != 32:
        raise CensusAttestationError("public key fingerprint input must be exactly 32 bytes")
    try:
        Ed25519PublicKey.from_public_bytes(public_key)
    except ValueError as error:
        raise CensusAttestationError("public key fingerprint input is not Ed25519") from error
    return _raw_hash(public_key)


def trust_store_revision(trust_store: Mapping[str, Any]) -> str:
    body = {key: item for key, item in trust_store.items() if key != "trust_store_revision"}
    return canonical_hash(body)


def attestation_signing_bytes(attestation_body: Mapping[str, Any]) -> bytes:
    if "signature" in attestation_body:
        raise CensusAttestationError("signing body must not contain a signature")
    return SIGNING_DOMAIN + _canonical_bytes(attestation_body)


def _timestamp(value: Any, label: str) -> datetime:
    if type(value) is not str or TIMESTAMP_RE.fullmatch(value) is None:
        raise CensusAttestationError(f"{label} must be UTC second-precision RFC3339")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError as error:
        raise CensusAttestationError(f"{label} is not a real UTC timestamp") from error
    return parsed


def _context_time(value: datetime, label: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != timedelta(0)
        or value.microsecond != 0
    ):
        raise CensusAttestationError(f"{label} must be a UTC second-precision datetime")
    return value.astimezone(UTC)


def _format_time(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _capabilities(value: Any, label: str) -> tuple[str, ...]:
    if type(value) is not list or tuple(value) != EXACT_CAPABILITIES:
        raise CensusAttestationError(f"{label} must be the exact read-only capability roster")
    return EXACT_CAPABILITIES


def _validate_scope(scope: Any) -> dict[str, Any]:
    raw = _exact_mapping(scope, SCOPE_KEYS, "expected scope")
    return {
        "audience": _identifier(raw["audience"], "expected scope audience"),
        "tenant_ref": _identifier(raw["tenant_ref"], "expected scope tenant_ref"),
        "catalog_ref": _identifier(raw["catalog_ref"], "expected scope catalog_ref"),
        "alias_ref": _identifier(raw["alias_ref"], "expected scope alias_ref"),
        "index_ref": _identifier(raw["index_ref"], "expected scope index_ref"),
        "profile_revision": _hash(raw["profile_revision"], "expected scope profile_revision"),
        "credential_handle_ref": _handle(
            raw["credential_handle_ref"], "expected scope credential_handle_ref"
        ),
        "capabilities": list(_capabilities(raw["capabilities"], "expected scope capabilities")),
    }


def _validate_trust_store(
    trust_store: Any, *, expected_revision: str
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    raw = _exact_mapping(trust_store, TRUST_STORE_KEYS, "trust store")
    pin = _hash(expected_revision, "expected trust store revision")
    if raw["schema_version"] != 1:
        raise CensusAttestationError("trust store schema version is unsupported")
    trust_store_id = _identifier(raw["trust_store_id"], "trust store id")
    audience = _identifier(raw["audience"], "trust store audience")
    max_ttl = raw["max_ttl_seconds"]
    skew = raw["clock_skew_seconds"]
    if type(max_ttl) is not int or not 1 <= max_ttl <= 86400:
        raise CensusAttestationError("trust store max TTL must be between 1 and 86400 seconds")
    if type(skew) is not int or not 0 <= skew <= 300:
        raise CensusAttestationError("trust store clock skew must be between 0 and 300 seconds")
    revision = _hash(raw["trust_store_revision"], "trust store revision")
    if revision != trust_store_revision(raw):
        raise CensusAttestationError("trust store revision does not bind its canonical content")
    if revision != pin:
        raise CensusAttestationError("trust store does not match the externally pinned revision")

    authorities_raw = raw["authorities"]
    if type(authorities_raw) is not list or not 1 <= len(authorities_raw) <= 32:
        raise CensusAttestationError("trust store must contain between 1 and 32 authorities")
    authorities: list[dict[str, Any]] = []
    for index, item in enumerate(authorities_raw):
        authority = _exact_mapping(item, AUTHORITY_KEYS, f"trust authority[{index}]")
        public_hex, public_raw = _public_key(
            authority["public_key"], f"trust authority[{index}] public_key"
        )
        fingerprint = _hash(
            authority["public_key_fingerprint"],
            f"trust authority[{index}] public_key_fingerprint",
        )
        if fingerprint != public_key_fingerprint(public_raw):
            raise CensusAttestationError("trust authority public-key fingerprint mismatch")
        if authority["algorithm"] != ALGORITHM or authority["status"] != "active":
            raise CensusAttestationError("trust authority algorithm or status is not allowed")
        authorities.append(
            {
                "issuer": _identifier(authority["issuer"], f"trust authority[{index}] issuer"),
                "key_id": _identifier(authority["key_id"], f"trust authority[{index}] key_id"),
                "algorithm": ALGORITHM,
                "public_key": public_hex,
                "public_key_bytes": public_raw,
                "public_key_fingerprint": fingerprint,
                "status": "active",
            }
        )
    identities = [(item["issuer"], item["key_id"]) for item in authorities]
    fingerprints = [item["public_key_fingerprint"] for item in authorities]
    if len(identities) != len(set(identities)) or len(fingerprints) != len(set(fingerprints)):
        raise CensusAttestationError("trust store contains duplicate authority identity or key")
    if identities != sorted(identities):
        raise CensusAttestationError("trust store authorities are not in canonical order")
    canonical = {
        "schema_version": 1,
        "trust_store_id": trust_store_id,
        "trust_store_revision": revision,
        "audience": audience,
        "max_ttl_seconds": max_ttl,
        "clock_skew_seconds": skew,
    }
    return canonical, authorities


class CensusAttestationReplayGuard:
    """Process-local atomic replay guard for the synthetic verifier contract."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._consumed: set[str] = set()

    def consume(self, replay_id: str) -> str:
        replay_ref = _raw_hash(replay_id.encode("utf-8"))
        with self._lock:
            if replay_ref in self._consumed:
                raise CensusAttestationError("attestation replay ID was already consumed")
            self._consumed.add(replay_ref)
        return replay_ref

    def consumed_count(self) -> int:
        with self._lock:
            return len(self._consumed)


def _validated_attestation(attestation: Any) -> tuple[dict[str, Any], str, bytes]:
    raw = _exact_mapping(attestation, ATTESTATION_KEYS, "attestation")
    if (
        raw["schema_version"] != 1
        or raw["attestation_type"] != ATTESTATION_TYPE
        or raw["algorithm"] != ALGORITHM
    ):
        raise CensusAttestationError("attestation identity or algorithm is unsupported")
    body = {
        "schema_version": 1,
        "attestation_type": ATTESTATION_TYPE,
        "algorithm": ALGORITHM,
        "issuer": _identifier(raw["issuer"], "attestation issuer"),
        "key_id": _identifier(raw["key_id"], "attestation key_id"),
        "key_fingerprint": _hash(raw["key_fingerprint"], "attestation key_fingerprint"),
        "attestation_id": _identifier(raw["attestation_id"], "attestation ID"),
        "replay_id": _identifier(raw["replay_id"], "attestation replay ID"),
        "audience": _identifier(raw["audience"], "attestation audience"),
        "tenant_ref": _identifier(raw["tenant_ref"], "attestation tenant_ref"),
        "catalog_ref": _identifier(raw["catalog_ref"], "attestation catalog_ref"),
        "alias_ref": _identifier(raw["alias_ref"], "attestation alias_ref"),
        "index_ref": _identifier(raw["index_ref"], "attestation index_ref"),
        "profile_revision": _hash(raw["profile_revision"], "attestation profile_revision"),
        "credential_handle_ref": _handle(
            raw["credential_handle_ref"], "attestation credential_handle_ref"
        ),
        "capabilities": list(_capabilities(raw["capabilities"], "attestation capabilities")),
        "issued_at": _format_time(_timestamp(raw["issued_at"], "attestation issued_at")),
        "not_before": _format_time(_timestamp(raw["not_before"], "attestation not_before")),
        "expires_at": _format_time(_timestamp(raw["expires_at"], "attestation expires_at")),
    }
    signature_hex, signature_raw = _signature(raw["signature"])
    return body, signature_hex, signature_raw


def verify_census_attestation(
    attestation: Any,
    *,
    trust_store: Any,
    expected_trust_store_revision: str,
    expected_scope: Any,
    now: datetime,
    valid_until: datetime,
    replay_guard: CensusAttestationReplayGuard,
) -> dict[str, Any]:
    """Verify one signed attestation and emit only a sanitized receipt."""

    if not isinstance(replay_guard, CensusAttestationReplayGuard):
        raise CensusAttestationError("a process-local replay guard is required")
    verified_at = _context_time(now, "now")
    required_until = _context_time(valid_until, "valid_until")
    if required_until < verified_at:
        raise CensusAttestationError("valid_until precedes verification time")
    scope = _validate_scope(expected_scope)
    store, authorities = _validate_trust_store(
        trust_store, expected_revision=expected_trust_store_revision
    )
    body, signature_hex, signature_raw = _validated_attestation(attestation)

    if scope["audience"] != store["audience"] or body["audience"] != store["audience"]:
        raise CensusAttestationError("attestation audience mismatch")
    matches = [
        item
        for item in authorities
        if item["issuer"] == body["issuer"] and item["key_id"] == body["key_id"]
    ]
    if len(matches) != 1:
        raise CensusAttestationError("attestation issuer/key is not trusted")
    authority = matches[0]
    if body["key_fingerprint"] != authority["public_key_fingerprint"]:
        raise CensusAttestationError("attestation key fingerprint does not match trusted key")

    signed_bytes = attestation_signing_bytes(body)
    try:
        Ed25519PublicKey.from_public_bytes(authority["public_key_bytes"]).verify(
            signature_raw, signed_bytes
        )
    except (InvalidSignature, ValueError) as error:
        raise CensusAttestationError("attestation Ed25519 signature is invalid") from error

    for key in (
        "audience",
        "tenant_ref",
        "catalog_ref",
        "alias_ref",
        "index_ref",
        "profile_revision",
        "credential_handle_ref",
        "capabilities",
    ):
        if body[key] != scope[key]:
            raise CensusAttestationError(f"attestation {key} differs from effective scope")

    issued_at = _timestamp(body["issued_at"], "attestation issued_at")
    not_before = _timestamp(body["not_before"], "attestation not_before")
    expires_at = _timestamp(body["expires_at"], "attestation expires_at")
    skew = timedelta(seconds=store["clock_skew_seconds"])
    if issued_at > not_before or expires_at <= not_before:
        raise CensusAttestationError("attestation time ordering is invalid")
    if expires_at - issued_at > timedelta(seconds=store["max_ttl_seconds"]):
        raise CensusAttestationError("attestation TTL exceeds the pinned maximum")
    if issued_at > verified_at + skew:
        raise CensusAttestationError("attestation issued_at is in the future")
    if not_before > verified_at + skew:
        raise CensusAttestationError("attestation is not yet valid")
    if expires_at <= verified_at - skew:
        raise CensusAttestationError("attestation is expired")
    if expires_at < required_until:
        raise CensusAttestationError("attestation expires before the required census boundary")

    replay_ref = replay_guard.consume(body["replay_id"])
    signed_attestation = {**body, "signature": signature_hex}
    attestation_sha256 = canonical_hash(signed_attestation)
    receipt_body: dict[str, Any] = {
        "schema_version": 1,
        "evidence_scope": EVIDENCE_SCOPE,
        "contract_id": CONTRACT_ID,
        "status": "VALID",
        "proof_type": "out_of_band_signed_read_only",
        "algorithm": ALGORITHM,
        "trust_store_id": store["trust_store_id"],
        "trust_store_revision": store["trust_store_revision"],
        "attestation_sha256": attestation_sha256,
        "signed_payload_sha256": _raw_hash(signed_bytes),
        "issuer_ref": _raw_hash(body["issuer"].encode("utf-8")),
        "key_id_ref": _raw_hash(body["key_id"].encode("utf-8")),
        "key_fingerprint": body["key_fingerprint"],
        "attestation_id_ref": _raw_hash(body["attestation_id"].encode("utf-8")),
        "replay_id_ref": replay_ref,
        "bindings": scope,
        "validity": {
            "issued_at": body["issued_at"],
            "not_before": body["not_before"],
            "expires_at": body["expires_at"],
            "verified_at": _format_time(verified_at),
            "valid_until": _format_time(required_until),
            "max_ttl_seconds": store["max_ttl_seconds"],
            "clock_skew_seconds": store["clock_skew_seconds"],
        },
        "verification": {key: True for key in sorted(VERIFICATION_KEYS)},
        "sanitized": True,
        "nonclaims": list(NONCLAIMS),
    }
    receipt = {**receipt_body, "receipt_sha256": canonical_hash(receipt_body)}
    errors = validate_attestation_receipt(receipt)
    if errors:
        raise CensusAttestationError("generated attestation receipt failed its public contract")
    return receipt


def _receipt_schema_errors(receipt: Any) -> list[str]:
    try:
        schema = json.loads(ATTESTATION_SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        return [
            error.message
            for error in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
                receipt
            )
        ]
    except Exception as error:  # fail closed at the schema boundary
        return [f"{type(error).__name__}: attestation schema unavailable"]


def validate_attestation_receipt(receipt: Any) -> list[str]:
    """Validate the sanitized receipt shape; this does not recreate its signature check."""

    errors = _receipt_schema_errors(receipt)
    if errors:
        return errors
    assert isinstance(receipt, Mapping)
    if set(receipt) != RECEIPT_KEYS:
        return ["attestation receipt fields differ from the exact contract"]
    body = {key: item for key, item in receipt.items() if key != "receipt_sha256"}
    if receipt["receipt_sha256"] != canonical_hash(body):
        errors.append("attestation receipt self-hash is invalid")
    if receipt["nonclaims"] != list(NONCLAIMS):
        errors.append("attestation receipt nonclaims are incomplete")
    if tuple(receipt["bindings"]["capabilities"]) != EXACT_CAPABILITIES:
        errors.append("attestation receipt capability roster is not exact")
    if set(receipt["bindings"]) != BINDING_KEYS:
        errors.append("attestation receipt binding fields are invalid")
    if set(receipt["validity"]) != VALIDITY_KEYS:
        errors.append("attestation receipt validity fields are invalid")
    if set(receipt["verification"]) != VERIFICATION_KEYS or any(
        value is not True for value in receipt["verification"].values()
    ):
        errors.append("attestation receipt verification roster is not fully valid")
    issued_at = _timestamp(receipt["validity"]["issued_at"], "receipt issued_at")
    not_before = _timestamp(receipt["validity"]["not_before"], "receipt not_before")
    expires_at = _timestamp(receipt["validity"]["expires_at"], "receipt expires_at")
    verified_at = _timestamp(receipt["validity"]["verified_at"], "receipt verified_at")
    valid_until = _timestamp(receipt["validity"]["valid_until"], "receipt valid_until")
    skew = timedelta(seconds=receipt["validity"]["clock_skew_seconds"])
    if not (
        issued_at <= not_before
        and issued_at <= verified_at + skew
        and not_before <= verified_at + skew
        and expires_at > verified_at - skew
        and verified_at <= valid_until <= expires_at
        and expires_at - issued_at <= timedelta(seconds=receipt["validity"]["max_ttl_seconds"])
    ):
        errors.append("attestation receipt validity ordering is invalid")
    forbidden_raw_keys = {
        "issuer",
        "key_id",
        "attestation_id",
        "replay_id",
        "public_key",
        "signature",
    }
    if any(key in receipt for key in forbidden_raw_keys):
        errors.append("attestation receipt contains unsanitized authority material")
    return errors
