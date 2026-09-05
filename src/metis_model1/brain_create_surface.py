"""Private, sealed cumulative authority surface for CreateDeltaPlan rendering.

The host owns every grant.  Models see only bounded ``ref``/``roles``/``label``
projections plus the operation kinds allowed for requirement refs; payloads,
payload hashes, evidence, history digests and the canonical surface manifest
remain private.  Renderer resolution is revision- and role-bound and always
returns a detached JSON value.
"""

from __future__ import annotations

import hmac
import json
import math
import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from metis_model1.brain_create_plan import HOST_REF_RE, HOST_REF_ROLES, OPERATION_KINDS
from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json

CREATE_AUTHORITY_SURFACE_CONTRACT = "metis-brain-create-authority-surface/v2"
CREATE_AUTHORITY_HISTORY_CONTRACT = "metis-brain-create-authority-history/v1"
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
PAYLOAD_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_CONTROL_OR_DSL_PUNCTUATION_RE = re.compile(r"[`{};@\x00-\x1f\x7f]")
_PATH_LIKE_RE = re.compile(
    r"[/\\]|\.metis(?:$|[?#])",
    re.IGNORECASE,
)
_TEMPLATE_LIKE_RE = re.compile(r"\{\{|\}\}|\$\{")
_DSL_STATEMENT_RE = re.compile(
    r"(?:\b(?:endpoint|catalog|values|profile)\s+[A-Za-z0-9_.-]+\s*\{)"
    r"|(?:\b(?:take|from|where|returns|fallback)\s+"
    r"(?:append\b|substitute\b|[0-9]+\b|[\"']))",
    re.IGNORECASE,
)
_DSL_DISCLOSURE_RE = re.compile(
    r"\b(?:raw\s+dsl|metis\s+source|source\s+code|endpoint\s+template)\b",
    re.IGNORECASE,
)
_PRIVATE_HASH_RE = re.compile(r"(?:sha256:)?[0-9a-f]{32,}", re.IGNORECASE)

MAX_GRANTS = 512
MAX_LABEL_CHARACTERS = 96
MAX_LABEL_BYTES = 384
MAX_PAYLOAD_BYTES = 8_192
MAX_TOTAL_PAYLOAD_BYTES = 524_288
MAX_PAYLOAD_DEPTH = 6
MAX_PAYLOAD_NODES = 256
MAX_PAYLOAD_OBJECT_MEMBERS = 64
MAX_PAYLOAD_ARRAY_ITEMS = 64
MAX_PAYLOAD_STRING_CHARACTERS = 512
MAX_PAYLOAD_STRING_BYTES = 2_048
MAX_INSTRUCTION_BYTES = 65_536
MAX_HISTORY_MESSAGE_BYTES = MAX_INSTRUCTION_BYTES
MAX_HISTORY_MESSAGES = 20
MAX_HISTORY_BYTES = MAX_HISTORY_MESSAGES * MAX_HISTORY_MESSAGE_BYTES
MAX_EVIDENCE_BYTES = 4_096
MAX_SAFE_INTEGER = 9_007_199_254_740_991
MAX_SAFE_FLOAT_MAGNITUDE = 1_000_000_000_000.0

_FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {
        "code",
        "dsl",
        "endpoint_template",
        "file",
        "metis",
        "metis_source",
        "path",
        "raw",
        "raw_source",
        "snippet",
        "source",
        "source_path",
        "source_text",
        "template",
        "template_ref",
        "text",
    }
)


class CreateAuthoritySurfaceError(ValueError):
    """The host attempted to construct an invalid authority surface."""


@dataclass(frozen=True, slots=True)
class CreateAuthorityHistoryMessage:
    """One server-reconstructed operator message in canonical lineage order."""

    ordinal: int
    text: str
    message_sha256: str


@dataclass(frozen=True, slots=True)
class RequirementEvidence:
    """Private evidence for one requirement and the operations it may authorize.

    ``operator`` evidence is an exact UTF-8 span of ``message_ordinal`` and has
    no payload.  ``clarification`` and ``policy`` evidence has no message/span
    coordinates and instead seals a non-empty, strict-JSON payload.  Keeping the
    two shapes disjoint prevents a host decision from masquerading as operator
    text.
    """

    origin: str
    message_ordinal: int | None
    start_utf8: int | None
    end_utf8: int | None
    evidence_sha256: str
    allowed_kinds: Sequence[str]
    evidence_payload: Any | None = None


@dataclass(frozen=True, slots=True)
class CreateAuthorityGrant:
    """One host-owned private grant before canonical defensive copying."""

    ref: str
    roles: Sequence[str]
    label: str
    payload: Any
    payload_sha256: str
    requirement: RequirementEvidence | None = None


@dataclass(frozen=True, slots=True)
class _StoredHistoryMessage:
    ordinal: int
    text_bytes: bytes
    message_sha256: str


@dataclass(frozen=True, slots=True)
class _StoredRequirement:
    origin: str
    message_ordinal: int | None
    start_utf8: int | None
    end_utf8: int | None
    evidence_sha256: str
    evidence_payload_bytes: bytes | None
    allowed_kinds: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _StoredGrant:
    ref: str
    roles: tuple[str, ...]
    label: str
    payload_bytes: bytes
    payload_sha256: str
    requirement: _StoredRequirement | None


def _safe_string(value: str, *, label: bool) -> None:
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as error:
        raise CreateAuthoritySurfaceError("authority string is not valid UTF-8") from error
    character_bound = MAX_LABEL_CHARACTERS if label else MAX_PAYLOAD_STRING_CHARACTERS
    byte_bound = MAX_LABEL_BYTES if label else MAX_PAYLOAD_STRING_BYTES
    if not value or len(value) > character_bound or len(encoded) > byte_bound:
        raise CreateAuthoritySurfaceError("authority string exceeds its bound")
    if (
        _CONTROL_OR_DSL_PUNCTUATION_RE.search(value) is not None
        or _PATH_LIKE_RE.search(value) is not None
        or _TEMPLATE_LIKE_RE.search(value) is not None
        or _DSL_STATEMENT_RE.search(value) is not None
        or _DSL_DISCLOSURE_RE.search(value) is not None
        or (label and _PRIVATE_HASH_RE.search(value) is not None)
    ):
        raise CreateAuthoritySurfaceError("authority string contains unsafe DSL-like data")


def _validate_payload(value: Any, *, depth: int = 0, nodes: list[int] | None = None) -> None:
    if nodes is None:
        nodes = [0]
    nodes[0] += 1
    if depth > MAX_PAYLOAD_DEPTH or nodes[0] > MAX_PAYLOAD_NODES:
        raise CreateAuthoritySurfaceError("authority payload exceeds its structural bound")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            raise CreateAuthoritySurfaceError("authority integer is outside the JSON safe range")
        return
    if isinstance(value, float):
        if not math.isfinite(value) or abs(value) > MAX_SAFE_FLOAT_MAGNITUDE:
            raise CreateAuthoritySurfaceError("authority float is outside its bound")
        return
    if isinstance(value, str):
        _safe_string(value, label=False)
        return
    if isinstance(value, list):
        if len(value) > MAX_PAYLOAD_ARRAY_ITEMS:
            raise CreateAuthoritySurfaceError("authority payload array exceeds its bound")
        for item in value:
            _validate_payload(item, depth=depth + 1, nodes=nodes)
        return
    if isinstance(value, dict):
        if len(value) > MAX_PAYLOAD_OBJECT_MEMBERS:
            raise CreateAuthoritySurfaceError("authority payload object exceeds its bound")
        for key, item in value.items():
            if not isinstance(key, str) or PAYLOAD_KEY_RE.fullmatch(key) is None:
                raise CreateAuthoritySurfaceError("authority payload key is invalid")
            normalized = key.casefold().replace("-", "_")
            if normalized in _FORBIDDEN_PAYLOAD_KEYS:
                raise CreateAuthoritySurfaceError(
                    "authority payload cannot contain source, path, template, or DSL keys"
                )
            _validate_payload(item, depth=depth + 1, nodes=nodes)
        return
    raise CreateAuthoritySurfaceError("authority payload is not strict JSON")


def _canonical_payload(value: Any, expected_sha256: str) -> bytes:
    if not isinstance(expected_sha256, str) or HASH_RE.fullmatch(expected_sha256) is None:
        raise CreateAuthoritySurfaceError("authority payload hash is invalid")
    _validate_payload(value)
    try:
        raw = canonical_json(value)
    except BrainError as error:
        raise CreateAuthoritySurfaceError("authority payload is not canonical JSON") from error
    if not raw or len(raw) > MAX_PAYLOAD_BYTES:
        raise CreateAuthoritySurfaceError("authority payload exceeds its byte bound")
    if not hmac.compare_digest(bytes_sha256(raw), expected_sha256):
        raise CreateAuthoritySurfaceError("authority payload hash does not match")
    return raw


def _message_bytes(text: str, message_sha256: str) -> bytes:
    if not isinstance(text, str) or not text:
        raise CreateAuthoritySurfaceError("authority history message is empty")
    try:
        raw = text.encode("utf-8")
    except UnicodeError as error:
        raise CreateAuthoritySurfaceError("authority history message is not valid UTF-8") from error
    if len(raw) > MAX_HISTORY_MESSAGE_BYTES:
        raise CreateAuthoritySurfaceError("authority history message exceeds its bound")
    if (
        not isinstance(message_sha256, str)
        or HASH_RE.fullmatch(message_sha256) is None
        or not hmac.compare_digest(bytes_sha256(raw), message_sha256)
    ):
        raise CreateAuthoritySurfaceError("authority history message hash does not match")
    return raw


def _stored_history(
    history: Sequence[CreateAuthorityHistoryMessage],
) -> tuple[_StoredHistoryMessage, ...]:
    if isinstance(history, (str, bytes)) or not isinstance(history, Sequence):
        raise CreateAuthoritySurfaceError("authority history is invalid")
    if not history or len(history) > MAX_HISTORY_MESSAGES:
        raise CreateAuthoritySurfaceError("authority history exceeds its message bound")
    stored: list[_StoredHistoryMessage] = []
    total_bytes = 0
    for expected_ordinal, message in enumerate(history):
        if not isinstance(message, CreateAuthorityHistoryMessage):
            raise CreateAuthoritySurfaceError("authority history message is invalid")
        if (
            isinstance(message.ordinal, bool)
            or not isinstance(message.ordinal, int)
            or message.ordinal != expected_ordinal
        ):
            raise CreateAuthoritySurfaceError(
                "authority history ordinals must be contiguous and ordered from zero"
            )
        raw = _message_bytes(message.text, message.message_sha256)
        total_bytes += len(raw)
        if total_bytes > MAX_HISTORY_BYTES:
            raise CreateAuthoritySurfaceError("authority history exceeds its byte bound")
        stored.append(
            _StoredHistoryMessage(
                ordinal=message.ordinal,
                text_bytes=raw,
                message_sha256=message.message_sha256,
            )
        )
    return tuple(stored)


def _history_manifest(history: Sequence[_StoredHistoryMessage]) -> dict[str, Any]:
    return {
        "contract_id": CREATE_AUTHORITY_HISTORY_CONTRACT,
        "messages": [
            {
                "ordinal": message.ordinal,
                "message_sha256": message.message_sha256,
                "utf8_bytes": len(message.text_bytes),
            }
            for message in history
        ],
    }


def create_authority_history_revision(
    history: Sequence[CreateAuthorityHistoryMessage],
) -> str:
    """Validate a server-owned history roster and return its canonical revision."""

    return bytes_sha256(canonical_json(_history_manifest(_stored_history(history))))


def _stored_requirement(
    evidence: RequirementEvidence,
    *,
    history_by_ordinal: dict[int, _StoredHistoryMessage],
) -> _StoredRequirement:
    if not isinstance(evidence.origin, str) or evidence.origin not in {
        "operator",
        "clarification",
        "policy",
    }:
        raise CreateAuthoritySurfaceError("requirement evidence origin is invalid")
    if (
        not isinstance(evidence.evidence_sha256, str)
        or HASH_RE.fullmatch(evidence.evidence_sha256) is None
    ):
        raise CreateAuthoritySurfaceError("requirement evidence hash is invalid")
    if isinstance(evidence.allowed_kinds, str) or not isinstance(
        evidence.allowed_kinds, Collection
    ):
        raise CreateAuthoritySurfaceError("requirement operation allowlist is invalid")
    kinds = tuple(evidence.allowed_kinds)
    if (
        not kinds
        or any(not isinstance(kind, str) for kind in kinds)
        or len(kinds) != len(set(kinds))
        or not set(kinds).issubset(OPERATION_KINDS)
    ):
        raise CreateAuthoritySurfaceError("requirement operation allowlist is invalid")

    evidence_payload_bytes: bytes | None = None
    if evidence.origin == "operator":
        if (
            isinstance(evidence.message_ordinal, bool)
            or not isinstance(evidence.message_ordinal, int)
            or evidence.message_ordinal not in history_by_ordinal
        ):
            raise CreateAuthoritySurfaceError(
                "operator evidence message ordinal is not in authority history"
            )
        if evidence.evidence_payload is not None:
            raise CreateAuthoritySurfaceError("operator evidence cannot carry a decision payload")
        message = history_by_ordinal[evidence.message_ordinal]
        if (
            isinstance(evidence.start_utf8, bool)
            or isinstance(evidence.end_utf8, bool)
            or not isinstance(evidence.start_utf8, int)
            or not isinstance(evidence.end_utf8, int)
            or not 0 <= evidence.start_utf8 < evidence.end_utf8 <= len(message.text_bytes)
        ):
            raise CreateAuthoritySurfaceError("operator evidence span is invalid")
        span = message.text_bytes[evidence.start_utf8 : evidence.end_utf8]
        if len(span) > MAX_EVIDENCE_BYTES:
            raise CreateAuthoritySurfaceError("operator evidence span exceeds its bound")
        try:
            span.decode("utf-8")
        except UnicodeError as error:
            raise CreateAuthoritySurfaceError(
                "operator evidence offsets split a UTF-8 character"
            ) from error
        if not hmac.compare_digest(bytes_sha256(span), evidence.evidence_sha256):
            raise CreateAuthoritySurfaceError("operator evidence hash does not match")
    else:
        if (
            evidence.message_ordinal is not None
            or evidence.start_utf8 is not None
            or evidence.end_utf8 is not None
        ):
            raise CreateAuthoritySurfaceError(
                "decision and policy evidence cannot claim an operator message span"
            )
        if not isinstance(evidence.evidence_payload, dict) or not evidence.evidence_payload:
            raise CreateAuthoritySurfaceError(
                "decision and policy evidence requires a non-empty JSON payload"
            )
        evidence_payload_bytes = _canonical_payload(
            evidence.evidence_payload,
            evidence.evidence_sha256,
        )

    return _StoredRequirement(
        origin=evidence.origin,
        message_ordinal=evidence.message_ordinal,
        start_utf8=evidence.start_utf8,
        end_utf8=evidence.end_utf8,
        evidence_sha256=evidence.evidence_sha256,
        evidence_payload_bytes=evidence_payload_bytes,
        allowed_kinds=tuple(sorted(kinds)),
    )


class CreateAuthoritySurface:
    """Immutable private authority registry for cumulative operator history."""

    __slots__ = (
        "_basis_ref",
        "_history_revision",
        "_ordered",
        "_records",
        "_surface_revision",
        "_target_ref",
    )

    def __init__(
        self,
        *,
        history: Sequence[CreateAuthorityHistoryMessage],
        history_revision: str,
        target_ref: str,
        basis_ref: str | None,
        grants: Sequence[CreateAuthorityGrant],
    ) -> None:
        stored_history = _stored_history(history)
        computed_history_revision = bytes_sha256(canonical_json(_history_manifest(stored_history)))
        if (
            not isinstance(history_revision, str)
            or HASH_RE.fullmatch(history_revision) is None
            or not hmac.compare_digest(computed_history_revision, history_revision)
        ):
            raise CreateAuthoritySurfaceError("authority history revision does not match")
        history_by_ordinal = {message.ordinal: message for message in stored_history}
        if not isinstance(target_ref, str) or HOST_REF_RE.fullmatch(target_ref) is None:
            raise CreateAuthoritySurfaceError("authority target reference is invalid")
        if basis_ref is not None and (
            not isinstance(basis_ref, str) or HOST_REF_RE.fullmatch(basis_ref) is None
        ):
            raise CreateAuthoritySurfaceError("authority basis reference is invalid")
        if basis_ref == target_ref:
            raise CreateAuthoritySurfaceError("authority target and basis must be distinct")
        if isinstance(grants, (str, bytes)) or not isinstance(grants, Sequence):
            raise CreateAuthoritySurfaceError("authority grant roster is invalid")
        if not grants or len(grants) > MAX_GRANTS:
            raise CreateAuthoritySurfaceError("authority grant roster exceeds its bound")

        records: dict[str, _StoredGrant] = {}
        total_payload_bytes = 0
        for grant in grants:
            if not isinstance(grant, CreateAuthorityGrant):
                raise CreateAuthoritySurfaceError("authority grant is invalid")
            if (
                not isinstance(grant.ref, str)
                or HOST_REF_RE.fullmatch(grant.ref) is None
                or grant.ref in records
            ):
                raise CreateAuthoritySurfaceError("authority grant references are not unique")
            if isinstance(grant.roles, str) or not isinstance(grant.roles, Collection):
                raise CreateAuthoritySurfaceError("authority grant roles are invalid")
            roles = tuple(grant.roles)
            if (
                not roles
                or any(not isinstance(role, str) for role in roles)
                or len(roles) != len(set(roles))
                or not set(roles).issubset(HOST_REF_ROLES)
            ):
                raise CreateAuthoritySurfaceError("authority grant roles are invalid")
            normalized_roles = tuple(sorted(roles))
            if not isinstance(grant.label, str):
                raise CreateAuthoritySurfaceError("authority grant label is invalid")
            _safe_string(grant.label, label=True)
            payload_bytes = _canonical_payload(grant.payload, grant.payload_sha256)
            total_payload_bytes += len(payload_bytes)
            if total_payload_bytes > MAX_TOTAL_PAYLOAD_BYTES:
                raise CreateAuthoritySurfaceError("authority payload roster exceeds its bound")

            is_requirement = "requirement" in normalized_roles
            if is_requirement != (grant.requirement is not None):
                raise CreateAuthoritySurfaceError(
                    "requirement role and evidence must be present together"
                )
            if is_requirement and normalized_roles != ("requirement",):
                raise CreateAuthoritySurfaceError("requirement grants cannot carry another role")
            requirement = (
                _stored_requirement(
                    grant.requirement,
                    history_by_ordinal=history_by_ordinal,
                )
                if grant.requirement is not None
                else None
            )
            if requirement is not None and requirement.evidence_payload_bytes is not None:
                total_payload_bytes += len(requirement.evidence_payload_bytes)
                if total_payload_bytes > MAX_TOTAL_PAYLOAD_BYTES:
                    raise CreateAuthoritySurfaceError("authority payload roster exceeds its bound")
            records[grant.ref] = _StoredGrant(
                ref=grant.ref,
                roles=normalized_roles,
                label=grant.label,
                payload_bytes=payload_bytes,
                payload_sha256=grant.payload_sha256,
                requirement=requirement,
            )

        target_records = [record for record in records.values() if "target" in record.roles]
        basis_records = [record for record in records.values() if "basis" in record.roles]
        if (
            len(target_records) != 1
            or target_records[0].ref != target_ref
            or target_records[0].roles != ("target",)
        ):
            raise CreateAuthoritySurfaceError("authority target root is not exact")
        if basis_ref is None:
            if basis_records:
                raise CreateAuthoritySurfaceError("initial authority cannot contain a basis grant")
        elif (
            len(basis_records) != 1
            or basis_records[0].ref != basis_ref
            or basis_records[0].roles != ("basis",)
        ):
            raise CreateAuthoritySurfaceError("authority basis root is not exact")

        ordered = tuple(records[ref] for ref in sorted(records))
        manifest = {
            "contract_id": CREATE_AUTHORITY_SURFACE_CONTRACT,
            "history_revision": history_revision,
            "target_ref": target_ref,
            "basis_ref": basis_ref,
            "grants": [self._private_manifest_record(record) for record in ordered],
        }
        self._history_revision = history_revision
        self._target_ref = target_ref
        self._basis_ref = basis_ref
        self._ordered = ordered
        self._records = MappingProxyType({record.ref: record for record in ordered})
        self._surface_revision = bytes_sha256(canonical_json(manifest))

    @staticmethod
    def _private_manifest_record(record: _StoredGrant) -> dict[str, Any]:
        requirement = record.requirement
        return {
            "ref": record.ref,
            "roles": list(record.roles),
            "label": record.label,
            "payload": json.loads(record.payload_bytes),
            "payload_sha256": record.payload_sha256,
            "requirement": None
            if requirement is None
            else {
                "origin": requirement.origin,
                "message_ordinal": requirement.message_ordinal,
                "start_utf8": requirement.start_utf8,
                "end_utf8": requirement.end_utf8,
                "evidence_sha256": requirement.evidence_sha256,
                "evidence_payload": None
                if requirement.evidence_payload_bytes is None
                else json.loads(requirement.evidence_payload_bytes),
                "allowed_kinds": list(requirement.allowed_kinds),
            },
        }

    @property
    def surface_revision(self) -> str:
        return self._surface_revision

    @property
    def history_revision(self) -> str:
        return self._history_revision

    @property
    def target_ref(self) -> str:
        return self._target_ref

    @property
    def basis_ref(self) -> str | None:
        return self._basis_ref

    @property
    def issued_roles(self) -> dict[str, frozenset[str]]:
        """Return a detached mapping accepted by validate_create_delta_plan."""

        return {record.ref: frozenset(record.roles) for record in self._ordered}

    @property
    def expected_requirement_kinds(self) -> dict[str, frozenset[str]]:
        """Return a detached requirement-to-operation allowlist."""

        return {
            record.ref: frozenset(record.requirement.allowed_kinds)
            for record in self._ordered
            if record.requirement is not None
        }

    def model_projection(self) -> list[dict[str, Any]]:
        """Return model-safe refs, roles, labels and requirement operation kinds."""

        projection: list[dict[str, Any]] = []
        for record in self._ordered:
            item: dict[str, Any] = {
                "ref": record.ref,
                "roles": list(record.roles),
                "label": record.label,
            }
            if record.requirement is not None:
                item["allowed_kinds"] = list(record.requirement.allowed_kinds)
            projection.append(item)
        return projection

    def resolve(
        self,
        ref: str,
        *,
        required_role: str,
        expected_surface_revision: str,
    ) -> Any:
        """Resolve one private grant after exact surface and role validation."""

        if not isinstance(expected_surface_revision, str) or not hmac.compare_digest(
            expected_surface_revision, self._surface_revision
        ):
            raise BrainError(
                "CREATE_SURFACE_STALE", 409, "create authority surface revision differs"
            )
        if not isinstance(required_role, str) or required_role not in HOST_REF_ROLES:
            raise BrainError(
                "CREATE_SURFACE_ROLE_MISMATCH", 502, "create authority role is invalid"
            )
        if not isinstance(ref, str) or HOST_REF_RE.fullmatch(ref) is None:
            raise BrainError(
                "CREATE_SURFACE_REF_UNKNOWN", 502, "create authority reference is unknown"
            )
        record = self._records.get(ref)
        if record is None:
            raise BrainError(
                "CREATE_SURFACE_REF_UNKNOWN", 502, "create authority reference is unknown"
            )
        if required_role not in record.roles:
            raise BrainError("CREATE_SURFACE_ROLE_MISMATCH", 502, "create authority role differs")
        if not hmac.compare_digest(bytes_sha256(record.payload_bytes), record.payload_sha256):
            raise BrainError(
                "CREATE_SURFACE_TAMPERED", 500, "create authority payload integrity failed"
            )
        return json.loads(record.payload_bytes)


__all__ = [
    "CREATE_AUTHORITY_HISTORY_CONTRACT",
    "CREATE_AUTHORITY_SURFACE_CONTRACT",
    "CreateAuthorityGrant",
    "CreateAuthorityHistoryMessage",
    "CreateAuthoritySurface",
    "CreateAuthoritySurfaceError",
    "MAX_EVIDENCE_BYTES",
    "MAX_GRANTS",
    "MAX_HISTORY_BYTES",
    "MAX_HISTORY_MESSAGE_BYTES",
    "MAX_HISTORY_MESSAGES",
    "MAX_INSTRUCTION_BYTES",
    "MAX_LABEL_BYTES",
    "MAX_LABEL_CHARACTERS",
    "MAX_PAYLOAD_ARRAY_ITEMS",
    "MAX_PAYLOAD_BYTES",
    "MAX_PAYLOAD_DEPTH",
    "MAX_PAYLOAD_NODES",
    "MAX_PAYLOAD_OBJECT_MEMBERS",
    "MAX_PAYLOAD_STRING_BYTES",
    "MAX_PAYLOAD_STRING_CHARACTERS",
    "MAX_TOTAL_PAYLOAD_BYTES",
    "RequirementEvidence",
    "create_authority_history_revision",
]
