"""Strict, payload-bounded protocol helpers for the local Metis Brain API."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, NoReturn

PROTOCOL_VERSION = "v1"
MAX_JSON_BYTES = 1024 * 1024
MAX_SOURCE_BYTES = 512 * 1024
IDLE_TTL_SECONDS = 20 * 60
CAPABILITIES = frozenset(
    {
        "session.read",
        "session.close",
        "context.read",
        "compile",
    }
)

_ALIAS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_CLIENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{32,96}$")
_REVISION_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


@dataclass
class BrainError(Exception):
    """One deterministic public API failure without sensitive detail."""

    code: str
    status: int
    message: str

    def __str__(self) -> str:
        return self.message

    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "error": {"code": self.code, "message": self.message},
        }


def fail(code: str, status: int, message: str) -> NoReturn:
    raise BrainError(code=code, status=status, message=message)


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise BrainError("INVALID_JSON", 400, "value is not canonical JSON") from error


def canonical_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value)).hexdigest()


def bytes_sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def parse_json_object(raw: bytes, *, label: str = "request") -> dict[str, Any]:
    if not raw or len(raw) > MAX_JSON_BYTES:
        fail("INVALID_JSON", 400, f"{label} must be bounded non-empty JSON")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                fail("DUPLICATE_FIELD", 400, f"{label} contains a duplicate field")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        fail("INVALID_JSON", 400, f"{label} contains a non-JSON number")

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except BrainError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BrainError("INVALID_JSON", 400, f"{label} is not valid JSON") from error
    if not isinstance(value, dict):
        fail("INVALID_JSON", 400, f"{label} must be a JSON object")
    return value


def exact_fields(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] | None = None,
    label: str,
) -> None:
    optional = optional or set()
    actual = set(value)
    missing = required - actual
    extra = actual - required - optional
    if missing or extra:
        fail("INVALID_SCHEMA", 400, f"{label} has an invalid field roster")


def bounded_identifier(value: Any, *, kind: str) -> str:
    pattern = {
        "client": _CLIENT_RE,
        "tenant": _ALIAS_RE,
        "session": _SESSION_RE,
    }.get(kind)
    if pattern is None:
        raise AssertionError(f"unknown identifier kind: {kind}")
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        fail("INVALID_SCHEMA", 400, f"{kind} identifier is invalid")
    return value


def revision(value: Any, *, label: str = "expected_revision") -> str:
    if not isinstance(value, str) or _REVISION_RE.fullmatch(value) is None:
        fail("INVALID_SCHEMA", 400, f"{label} is invalid")
    return value


def capability_set(value: Any, *, allow_empty: bool = False) -> frozenset[str]:
    if (
        not isinstance(value, list)
        or (not value and not allow_empty)
        or len(value) > len(CAPABILITIES)
    ):
        fail("INVALID_SCHEMA", 400, "capabilities must be a bounded non-empty list")
    if any(not isinstance(item, str) for item in value):
        fail("INVALID_SCHEMA", 400, "capabilities must contain strings")
    result = frozenset(value)
    if len(result) != len(value) or not result.issubset(CAPABILITIES):
        fail("INVALID_SCHEMA", 400, "capabilities contain duplicates or unknown values")
    return result


def bounded_source(value: Any) -> str:
    if not isinstance(value, str) or not value:
        fail("INVALID_SCHEMA", 400, "source must be a non-empty string")
    try:
        raw = value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise BrainError("INVALID_SCHEMA", 400, "source must be UTF-8") from error
    if len(raw) > MAX_SOURCE_BYTES:
        fail("PAYLOAD_TOO_LARGE", 413, "source exceeds the byte limit")
    return value
