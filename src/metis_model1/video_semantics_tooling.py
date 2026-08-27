"""Pure, local-only P0/P1 tooling for private video semantic evidence.

This module deliberately has no filesystem, network, credential, model, or
tenant side effects.  Callers provide already-loaded manifests/receipts and
JSONL bytes; the only durable-looking value returned by the freeze builder is
an in-memory local artifact that the owning runner may persist later.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from metis_model1.video_semantics_contracts import (
    manifest_digest,
    validate_acquisition_receipt,
    validate_concepts,
    validate_source_manifest,
)

SCHEMA_VERSION = 1
MAX_JSONL_BYTES = 16 * 1024 * 1024
MAX_JSONL_RECORDS = 10_000
MAX_JSONL_LINE_BYTES = 128 * 1024
MAX_ROSTER_ENTRIES = 4_096
MAX_RECEIPTS = 4_096
PRIVATE_KINDS = frozenset(
    {"reserved_editorial", "catalog", "valueset", "live_census", "validated_usage", "oracle"}
)
PRIVATE_STORAGE = "local-confidential-receipt"
PRIVATE_SENSITIVITIES = frozenset({"internal_editorial", "internal_aggregate"})
PUBLIC_RESULT_KEYS = frozenset(
    {
        "schema_version",
        "operation",
        "status",
        "private_roster_complete",
        "ontology_valid",
        "gaps",
        "sensitivity",
        "raw_payloads_present",
        "error_codes",
    }
)
FREEZE_NONCLAIMS = (
    "no_publication",
    "no_live_census",
    "no_canonical_catalog_write",
    "no_training_authority",
)
ERROR_CODES = frozenset(
    {
        "CONCEPT_INVALID",
        "DUPLICATE_JSON_KEY",
        "JSONL_BLANK_LINE",
        "JSONL_EMPTY",
        "JSONL_INPUT_INVALID",
        "JSONL_LINE_TOO_LARGE",
        "JSONL_RECORD_LIMIT",
        "JSONL_TOO_LARGE",
        "JSONL_UNICODE_INVALID",
        "MALFORMED_JSON",
        "MANIFEST_INVALID",
        "NONFINITE_JSON",
        "PRIVATE_ROSTER_INCOMPLETE",
        "RECEIPT_CONTAINER_INVALID",
        "RECEIPT_COUNT_DRIFT",
        "RECEIPT_COUNTS_INVALID",
        "RECEIPT_DUPLICATE",
        "RECEIPT_EXTRA",
        "RECEIPT_GAPS",
        "RECEIPT_INVALID",
        "RECEIPT_KEY_MISMATCH",
        "RECEIPT_MISSING",
        "RECEIPT_NOT_VALID",
        "RECEIPT_SOURCE_INVALID",
        "RECEIPT_LIMIT",
        "SOURCE_INVALID",
        "SOURCE_KIND_FORBIDDEN",
        "SOURCE_REF_MISSING",
        "SOURCE_SENSITIVITY_FORBIDDEN",
        "SOURCE_STORAGE_FORBIDDEN",
        "SOURCE_ROSTER_LIMIT",
    }
)


class VideoSemanticsToolingError(ValueError):
    """Raised when a local-only operation cannot satisfy its contract."""


class _JsonLineError(ValueError):
    """Internal parse sentinel; its message is never exposed to callers."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _JsonLineError("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise _JsonLineError("NONFINITE_JSON")


def _parse_json_line(line: str) -> Any:
    try:
        return json.loads(
            line,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except _JsonLineError:
        raise
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise _JsonLineError("MALFORMED_JSON") from error


def _public_result(
    operation: str,
    *,
    valid: bool,
    gaps: int,
    error_codes: Sequence[str],
    ontology: bool = False,
    roster_complete: bool = False,
) -> dict[str, Any]:
    result = {
        "schema_version": SCHEMA_VERSION,
        "operation": operation,
        "status": "VALID" if valid else "INVALID",
        "private_roster_complete": roster_complete,
        "gaps": max(0, gaps),
        "sensitivity": "internal_confidential",
        "raw_payloads_present": False,
        "error_codes": sorted(set(error_codes)),
    }
    if not set(error_codes) <= ERROR_CODES:
        raise AssertionError("public result contains an unknown error code")
    if ontology:
        result["ontology_valid"] = valid
    if set(result) - PUBLIC_RESULT_KEYS:
        raise AssertionError("public result contains an unallowlisted key")
    return result


def _receipt_entries(receipts: Any) -> tuple[list[tuple[str | None, Any]], list[str]]:
    """Normalize supported receipt containers without exposing their values."""

    errors: list[str] = []
    if isinstance(receipts, Mapping):
        if len(receipts) > MAX_RECEIPTS:
            return [], ["RECEIPT_LIMIT"]
        entries = [
            (key if isinstance(key, str) else None, value) for key, value in receipts.items()
        ]
        return entries, errors
    if isinstance(receipts, Sequence) and not isinstance(receipts, str | bytes | bytearray):
        if len(receipts) > MAX_RECEIPTS:
            return [], ["RECEIPT_LIMIT"]
        return [(None, value) for value in receipts], errors
    return [], ["RECEIPT_CONTAINER_INVALID"]


def _roster_diagnostics(manifest: Any, receipts: Any) -> dict[str, Any]:
    """Return private diagnostics; this structure must never be printed."""

    errors: list[str] = []
    gap_count = 0
    try:
        manifest_errors = validate_source_manifest(manifest)
    except (TypeError, ValueError, UnicodeError):
        manifest_errors = ["MANIFEST_INVALID"]
    if manifest_errors or not isinstance(manifest, Mapping):
        errors.append("MANIFEST_INVALID")
        gap_count += 1
        return {
            "valid": False,
            "errors": errors,
            "gaps": gap_count,
            "source_ids": (),
            "receipts": (),
        }

    sources = manifest.get("sources")
    if not isinstance(sources, list):
        errors.append("MANIFEST_INVALID")
        gap_count += 1
        return {
            "valid": False,
            "errors": errors,
            "gaps": gap_count,
            "source_ids": (),
            "receipts": (),
        }
    if len(sources) > MAX_ROSTER_ENTRIES:
        return {
            "valid": False,
            "errors": ["SOURCE_ROSTER_LIMIT"],
            "gaps": 1,
            "source_ids": (),
            "receipts": (),
        }

    source_ids = tuple(item["source_id"] for item in sources if isinstance(item, Mapping))
    source_id_set = set(source_ids)
    for source in sources:
        if not isinstance(source, Mapping):
            errors.append("SOURCE_INVALID")
            gap_count += 1
            continue
        if source.get("kind") not in PRIVATE_KINDS:
            errors.append("SOURCE_KIND_FORBIDDEN")
            gap_count += 1
        if source.get("identity_storage") != PRIVATE_STORAGE:
            errors.append("SOURCE_STORAGE_FORBIDDEN")
            gap_count += 1
        if source.get("sensitivity") not in PRIVATE_SENSITIVITIES:
            errors.append("SOURCE_SENSITIVITY_FORBIDDEN")
            gap_count += 1

    entries, container_errors = _receipt_entries(receipts)
    errors.extend(container_errors)
    gap_count += len(container_errors)
    receipt_ids: list[str] = []
    normalized_receipts: list[tuple[str, Mapping[str, Any]]] = []
    for hinted_id, receipt in entries:
        if not isinstance(receipt, Mapping):
            errors.append("RECEIPT_INVALID")
            gap_count += 1
            continue
        source_id = receipt.get("source_id")
        if not isinstance(source_id, str):
            errors.append("RECEIPT_SOURCE_INVALID")
            gap_count += 1
            continue
        if hinted_id is not None and hinted_id != source_id:
            errors.append("RECEIPT_KEY_MISMATCH")
            gap_count += 1
        receipt_ids.append(source_id)
        normalized_receipts.append((source_id, receipt))

    duplicate_count = len(receipt_ids) - len(set(receipt_ids))
    if duplicate_count:
        errors.append("RECEIPT_DUPLICATE")
        gap_count += duplicate_count
    missing_count = len(source_id_set - set(receipt_ids))
    extra_count = len(set(receipt_ids) - source_id_set)
    if missing_count:
        errors.append("RECEIPT_MISSING")
        gap_count += missing_count
    if extra_count:
        errors.append("RECEIPT_EXTRA")
        gap_count += extra_count

    for source_id, receipt in normalized_receipts:
        if source_id not in source_id_set:
            continue
        try:
            receipt_errors = validate_acquisition_receipt(receipt, manifest)
        except (TypeError, ValueError, UnicodeError):
            receipt_errors = ["RECEIPT_INVALID"]
        if receipt_errors:
            errors.append("RECEIPT_INVALID")
            gap_count += 1
            continue
        if receipt.get("status") != "VALID":
            errors.append("RECEIPT_NOT_VALID")
            gap_count += 1
        counts = receipt.get("counts")
        if not isinstance(counts, Mapping):
            errors.append("RECEIPT_COUNTS_INVALID")
            gap_count += 1
        else:
            if counts.get("items_gaps") != 0:
                errors.append("RECEIPT_GAPS")
                gap_count += 1
            if counts.get("items_out") != counts.get("items_distinct"):
                errors.append("RECEIPT_COUNT_DRIFT")
                gap_count += 1

    return {
        "valid": not errors and len(source_id_set) == len(receipt_ids),
        "errors": errors,
        "gaps": gap_count,
        "source_ids": tuple(sorted(source_id_set)),
        "receipts": tuple(sorted(normalized_receipts, key=lambda item: item[0])),
    }


def validate_private_roster(manifest: Any, receipts: Any) -> dict[str, Any]:
    """Validate a private manifest and exact local acquisition-receipt roster.

    The returned object is deliberately public-safe.  Detailed source IDs,
    hashes, paths, and receipt contents remain available only to the caller's
    local control flow and are never returned by this function.
    """

    diagnostics = _roster_diagnostics(manifest, receipts)
    return _public_result(
        "validate-private-roster",
        valid=bool(diagnostics["valid"]),
        gaps=int(diagnostics["gaps"]),
        error_codes=diagnostics["errors"],
        roster_complete=bool(diagnostics["valid"]),
    )


def _jsonl_bytes(value: bytes | str) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        return value.encode("utf-8")
    raise _JsonLineError("JSONL_INPUT_INVALID")


def _contains_surrogate(value: Any) -> bool:
    if isinstance(value, str):
        return any(0xD800 <= ord(character) <= 0xDFFF for character in value)
    if isinstance(value, Mapping):
        return any(
            _contains_surrogate(key) or _contains_surrogate(item) for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_surrogate(item) for item in value)
    return False


def validate_ontology_jsonl(
    payload: bytes | str,
    manifest: Any,
    receipts: Any,
) -> dict[str, Any]:
    """Parse and validate local ontology JSONL against the private roster."""

    roster = _roster_diagnostics(manifest, receipts)
    errors = list(roster["errors"])
    gaps = int(roster["gaps"])
    if not roster["valid"]:
        errors.append("PRIVATE_ROSTER_INCOMPLETE")
        gaps += 1
        return _public_result(
            "validate-ontology",
            valid=False,
            gaps=gaps,
            error_codes=errors,
            ontology=True,
            roster_complete=False,
        )

    try:
        raw = _jsonl_bytes(payload)
        if len(raw) > MAX_JSONL_BYTES:
            return _public_result(
                "validate-ontology",
                valid=False,
                gaps=1,
                error_codes=["JSONL_TOO_LARGE"],
                ontology=True,
                roster_complete=True,
            )
        text = raw.decode("utf-8")
    except UnicodeEncodeError:
        return _public_result(
            "validate-ontology",
            valid=False,
            gaps=1,
            error_codes=["JSONL_UNICODE_INVALID"],
            ontology=True,
            roster_complete=True,
        )
    except UnicodeDecodeError:
        return _public_result(
            "validate-ontology",
            valid=False,
            gaps=1,
            error_codes=["JSONL_UNICODE_INVALID"],
            ontology=True,
            roster_complete=True,
        )
    except _JsonLineError:
        return _public_result(
            "validate-ontology",
            valid=False,
            gaps=1,
            error_codes=["JSONL_INPUT_INVALID"],
            ontology=True,
            roster_complete=True,
        )

    lines = text.splitlines()
    records: list[Any] = []
    if not lines:
        errors.append("JSONL_EMPTY")
        gaps += 1
    elif sum(bool(line.strip()) for line in lines) > MAX_JSONL_RECORDS:
        return _public_result(
            "validate-ontology",
            valid=False,
            gaps=1,
            error_codes=["JSONL_RECORD_LIMIT"],
            ontology=True,
            roster_complete=True,
        )
    for line in lines:
        try:
            line_size = len(line.encode("utf-8"))
        except UnicodeEncodeError:
            errors.append("JSONL_UNICODE_INVALID")
            gaps += 1
            continue
        if line_size > MAX_JSONL_LINE_BYTES:
            errors.append("JSONL_LINE_TOO_LARGE")
            gaps += 1
            continue
        if not line.strip():
            errors.append("JSONL_BLANK_LINE")
            gaps += 1
            continue
        try:
            record = _parse_json_line(line)
        except _JsonLineError as error:
            errors.append(str(error))
            gaps += 1
            continue
        if _contains_surrogate(record):
            errors.append("JSONL_UNICODE_INVALID")
            gaps += 1
            continue
        if not isinstance(record, Mapping):
            errors.append("CONCEPT_INVALID")
            gaps += 1
            continue
        records.append(record)

    source_refs = {item["source_ref"] for item in manifest["sources"]}
    for record in records:
        if record.get("editorial_source_ref") not in source_refs:
            errors.append("SOURCE_REF_MISSING")
            gaps += 1
    if validate_concepts(records):
        errors.append("CONCEPT_INVALID")
        gaps += 1
    valid = not errors and bool(records)
    return _public_result(
        "validate-ontology",
        valid=valid,
        gaps=gaps,
        error_codes=errors,
        ontology=True,
        roster_complete=True,
    )


def build_source_freeze(manifest: Any, receipts: Any) -> dict[str, Any]:
    """Build a deterministic local freeze artifact after exact receipt closure."""

    diagnostics = _roster_diagnostics(manifest, receipts)
    if not diagnostics["valid"]:
        raise VideoSemanticsToolingError("SOURCE_ROSTER_INCOMPLETE")
    assert isinstance(manifest, Mapping)
    receipt_records = [
        {"source_id": source_id, "receipt_sha256": receipt["receipt_sha256"]}
        for source_id, receipt in diagnostics["receipts"]
    ]
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "video-semantics/source-freeze",
        "status": "FROZEN_LOCAL",
        "evidence_scope": "local_confidential",
        "manifest_sha256": manifest_digest(manifest),
        "semantic_source_revision": manifest["semantic_source_revision"],
        "source_receipts": receipt_records,
        "private_roster_complete": True,
        "gaps": 0,
        "nonclaims": list(FREEZE_NONCLAIMS),
    }
    body["freeze_sha256"] = manifest_digest(body)
    return body


__all__ = [
    "FREEZE_NONCLAIMS",
    "PUBLIC_RESULT_KEYS",
    "VideoSemanticsToolingError",
    "build_source_freeze",
    "validate_ontology_jsonl",
    "validate_private_roster",
]
