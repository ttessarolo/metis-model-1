"""Pure, local-only P0/P1 tooling for private video semantic evidence.

This module deliberately has no filesystem, network, credential, model, or
tenant side effects.  Callers provide already-loaded manifests/receipts and
JSONL bytes; the only durable-looking value returned by the freeze builder is
an in-memory local artifact that the owning runner may persist later.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from metis_model1.video_semantics_contracts import (
    literal_sha256,
    manifest_digest,
    validate_acquisition_receipt,
    validate_concepts,
    validate_source_manifest,
)

SCHEMA_VERSION = 1
MAX_JSONL_BYTES = 16 * 1024 * 1024
MAX_JSONL_RECORDS = 10_000
MAX_JSONL_LINE_BYTES = 128 * 1024
MAX_JSON_NESTING = 128
MAX_ROSTER_ENTRIES = 4_096
MAX_RECEIPTS = 4_096
MAX_SOURCE_UNITS = 100_000
MAX_DISPOSITION_ENTRIES = 100_000
MAX_DISPOSITION_REASON_BYTES = 2048
DISPOSITION_ROSTER_SCHEMA_VERSION = 1
_DISPOSITION_VALUES = frozenset({"concepts", "no_concept", "excluded"})
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
        "JSONL_NESTING_LIMIT",
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
        "SOURCE_COVERAGE_INCOMPLETE",
        "SOURCE_LOCATOR_MISSING",
        "SOURCE_KIND_FORBIDDEN",
        "SOURCE_REF_MISSING",
        "SOURCE_SENSITIVITY_FORBIDDEN",
        "SOURCE_STORAGE_FORBIDDEN",
        "SOURCE_ROSTER_LIMIT",
        "SOURCE_UNIT_ROSTER_INVALID",
        "DISPOSITION_ROSTER_INVALID",
        "DISPOSITION_ROSTER_LINK_INVALID",
        "DISPOSITION_ROSTER_INCOMPLETE",
        "DISPOSITION_REASON_INVALID",
        "DISPOSITION_CONCEPT_MISMATCH",
        "DISPOSITION_COUNT_DRIFT",
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
    depth = 0
    in_string = False
    escaped = False
    for character in line:
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
            if depth > MAX_JSON_NESTING:
                raise _JsonLineError("JSONL_NESTING_LIMIT")
        elif character in "]}" and depth:
            depth -= 1
    try:
        return json.loads(
            line,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except _JsonLineError:
        raise
    except (RecursionError, TypeError, ValueError, json.JSONDecodeError) as error:
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
    except (RecursionError, TypeError, ValueError, UnicodeError):
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
        except (RecursionError, TypeError, ValueError, UnicodeError):
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
            items_in = counts.get("items_in")
            items_out = counts.get("items_out")
            items_distinct = counts.get("items_distinct")
            if (items_in, items_out, items_distinct) != (1, 1, 1):
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
    source_unit_roster: Any,
    source_disposition_roster: Any = None,
    *,
    source_envelope: Any = None,
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

    source_refs = {item["source_ref"] for item in manifest["sources"]}
    unit_roster: dict[str, frozenset[str]] = {}
    total_units = 0
    opaque = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
    if not isinstance(source_unit_roster, Mapping) or set(source_unit_roster) != source_refs:
        errors.append("SOURCE_UNIT_ROSTER_INVALID")
        gaps += 1
    else:
        for source_ref, locators in source_unit_roster.items():
            if (
                not isinstance(locators, Sequence)
                or isinstance(locators, str | bytes | bytearray)
                or not locators
                or len(locators) > MAX_SOURCE_UNITS
                or not all(
                    isinstance(locator, str) and opaque.fullmatch(locator) for locator in locators
                )
                or len(set(locators)) != len(locators)
            ):
                errors.append("SOURCE_UNIT_ROSTER_INVALID")
                gaps += 1
                continue
            total_units += len(locators)
            unit_roster[source_ref] = frozenset(locators)
        if total_units > MAX_SOURCE_UNITS or set(unit_roster) != source_refs:
            errors.append("SOURCE_UNIT_ROSTER_INVALID")
            gaps += 1
    if errors:
        return _public_result(
            "validate-ontology",
            valid=False,
            gaps=gaps,
            error_codes=errors,
            ontology=True,
            roster_complete=True,
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
        try:
            contains_surrogate = _contains_surrogate(record)
        except RecursionError:
            errors.append("CONCEPT_INVALID")
            gaps += 1
            continue
        if contains_surrogate:
            errors.append("JSONL_UNICODE_INVALID")
            gaps += 1
            continue
        if not isinstance(record, Mapping):
            errors.append("CONCEPT_INVALID")
            gaps += 1
            continue
        records.append(record)

    observed_source_refs: set[str] = set()
    for record in records:
        source_ref = record.get("editorial_source_ref")
        if source_ref not in source_refs:
            errors.append("SOURCE_REF_MISSING")
            gaps += 1
        else:
            observed_source_refs.add(source_ref)
            if record.get("source_locator") not in unit_roster[source_ref]:
                errors.append("SOURCE_LOCATOR_MISSING")
                gaps += 1
    missing_source_refs = source_refs - observed_source_refs
    if missing_source_refs:
        errors.append("SOURCE_COVERAGE_INCOMPLETE")
        gaps += len(missing_source_refs)
    try:
        concept_errors = validate_concepts(records)
    except (RecursionError, TypeError, ValueError, UnicodeError):
        concept_errors = ["CONCEPT_INVALID"]
    if concept_errors:
        errors.append("CONCEPT_INVALID")
        gaps += 1

    # A source unit is terminal only when the private disposition roster says
    # how it ended.  This check deliberately runs after parsing the ontology so
    # that a concept disposition can be compared with the exact concept IDs
    # actually present in the JSONL.  The roster is private and contributes
    # only a finite public error/status outcome.
    if source_disposition_roster is not None:
        disposition_errors = _validate_disposition_roster(
            source_disposition_roster,
            source_refs=source_refs,
            unit_roster=unit_roster,
            records=records,
            payload=raw,
            source_envelope=source_envelope,
        )
        errors.extend(disposition_errors)
        gaps += len(disposition_errors)
    else:
        # Concepts alone cannot attest that every unit was deliberately
        # inspected.  Even a one-unit ontology requires an explicit terminal
        # disposition bound to the extraction envelope and ontology bytes.
        errors.append("DISPOSITION_ROSTER_INCOMPLETE")
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


def _validate_disposition_roster(
    roster: Any,
    *,
    source_refs: set[str],
    unit_roster: Mapping[str, frozenset[str]],
    records: Sequence[Any],
    payload: bytes,
    source_envelope: Any,
) -> list[str]:
    """Validate a terminal disposition for every private source unit.

    The roster is intentionally a separate private artifact.  Its self-hash,
    source-envelope hash and ontology byte hash prevent a valid roster from
    being replayed against a different extraction or ontology.  No field from
    this artifact is returned to the public result.
    """

    errors: list[str] = []
    if not isinstance(roster, Mapping):
        return ["DISPOSITION_ROSTER_INVALID", "DISPOSITION_ROSTER_INCOMPLETE"]
    required = {
        "schema_version",
        "artifact_kind",
        "source_envelope_sha256",
        "ontology_sha256",
        "entries",
        "counts",
        "roster_sha256",
    }
    if set(roster) != required:
        errors.append("DISPOSITION_ROSTER_INVALID")
    if (
        type(roster.get("schema_version")) is not int
        or roster.get("schema_version") != DISPOSITION_ROSTER_SCHEMA_VERSION
        or roster.get("artifact_kind") != "video-semantics/unit-disposition-roster-v1"
    ):
        errors.append("DISPOSITION_ROSTER_INVALID")
    source_digest = roster.get("source_envelope_sha256")
    ontology_digest = roster.get("ontology_sha256")
    try:
        expected_source_digest = (
            manifest_digest(source_envelope) if isinstance(source_envelope, Mapping) else None
        )
    except (RecursionError, TypeError, ValueError, UnicodeError):
        expected_source_digest = None
    if (
        not isinstance(source_digest, str)
        or not source_digest.startswith("sha256:")
        or expected_source_digest is None
        or source_digest != expected_source_digest
    ):
        errors.append("DISPOSITION_ROSTER_LINK_INVALID")
    if not isinstance(ontology_digest, str) or ontology_digest != literal_sha256(payload):
        errors.append("DISPOSITION_ROSTER_LINK_INVALID")
    body = {key: value for key, value in roster.items() if key != "roster_sha256"}
    try:
        expected_roster_digest = manifest_digest(body)
    except (RecursionError, TypeError, ValueError, UnicodeError):
        expected_roster_digest = None
    if roster.get("roster_sha256") != expected_roster_digest:
        errors.append("DISPOSITION_ROSTER_INVALID")

    entries = roster.get("entries")
    counts = roster.get("counts")
    expected_pairs = {
        (source_ref, locator)
        for source_ref, locators in unit_roster.items()
        for locator in locators
    }
    if not isinstance(entries, list) or len(entries) > MAX_DISPOSITION_ENTRIES:
        errors.extend(("DISPOSITION_ROSTER_INVALID", "DISPOSITION_ROSTER_INCOMPLETE"))
        entries = []
    if (
        not isinstance(counts, Mapping)
        or set(counts)
        != {
            "items_in",
            "items_out",
            "items_distinct",
            "items_gaps",
        }
        or (
            any(type(value) is not int or value < 0 for value in counts.values())
            or (counts["items_in"], counts["items_out"], counts["items_distinct"])
            != (len(entries), len(entries), len(entries))
            or counts["items_gaps"] != 0
            or len(entries) != len(expected_pairs)
        )
    ):
        errors.append("DISPOSITION_COUNT_DRIFT")

    concepts_by_pair: dict[tuple[str, str], list[str]] = {}
    for record in records:
        if not isinstance(record, Mapping):
            continue
        pair = (record.get("editorial_source_ref"), record.get("source_locator"))
        concept_id = record.get("concept_id")
        if isinstance(concept_id, str):
            concepts_by_pair.setdefault(pair, []).append(concept_id)
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != {
            "source_ref",
            "source_locator",
            "disposition",
            "reason",
            "concept_ids",
        }:
            errors.append("DISPOSITION_ROSTER_INVALID")
            continue
        source_ref = entry.get("source_ref")
        source_locator = entry.get("source_locator")
        if not isinstance(source_ref, str) or not isinstance(source_locator, str):
            errors.append("DISPOSITION_ROSTER_INVALID")
            continue
        pair = (source_ref, source_locator)
        if pair in seen:
            errors.append("DISPOSITION_ROSTER_INVALID")
        seen.add(pair)
        if pair not in expected_pairs:
            errors.append("DISPOSITION_ROSTER_INVALID")
            continue
        disposition = entry.get("disposition")
        reason = entry.get("reason")
        concept_ids = entry.get("concept_ids")
        if disposition not in _DISPOSITION_VALUES:
            errors.append("DISPOSITION_ROSTER_INVALID")
            continue
        if (
            not isinstance(reason, str)
            or not reason.strip()
            or len(reason.encode("utf-8")) > MAX_DISPOSITION_REASON_BYTES
        ):
            errors.append("DISPOSITION_REASON_INVALID")
        if (
            not isinstance(concept_ids, list)
            or any(not isinstance(item, str) for item in concept_ids)
            or len(set(concept_ids)) != len(concept_ids)
        ):
            errors.append("DISPOSITION_ROSTER_INVALID")
            continue
        expected_concepts = sorted(concepts_by_pair.get(pair, []))
        actual_concepts = sorted(concept_ids)
        if disposition == "concepts":
            if not actual_concepts or actual_concepts != expected_concepts:
                errors.append("DISPOSITION_CONCEPT_MISMATCH")
        elif actual_concepts or expected_concepts:
            errors.append("DISPOSITION_CONCEPT_MISMATCH")
    if seen != expected_pairs:
        errors.append("DISPOSITION_ROSTER_INCOMPLETE")
    return errors


def build_source_freeze(manifest: Any, receipts: Any) -> dict[str, Any]:
    """Build a deterministic local freeze artifact after exact receipt closure."""

    diagnostics = _roster_diagnostics(manifest, receipts)
    if not diagnostics["valid"]:
        raise VideoSemanticsToolingError("SOURCE_ROSTER_INCOMPLETE")
    assert isinstance(manifest, Mapping)
    receipt_records = []
    for source_id, receipt in diagnostics["receipts"]:
        runtime = receipt["runtime"]
        stable_evidence = {
            "schema_version": receipt["schema_version"],
            "manifest_sha256": receipt["manifest_sha256"],
            "source_id": source_id,
            "status": receipt["status"],
            "runtime": {
                "python": runtime["python"],
                "tool_version": runtime["tool_version"],
            },
            "counts": receipt["counts"],
        }
        receipt_records.append(
            {
                "source_id": source_id,
                "stable_evidence_sha256": manifest_digest(stable_evidence),
            }
        )
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "video-semantics/source-freeze-v2",
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


def validate_source_freeze(freeze: Any, manifest: Any, receipts: Any) -> bool:
    """Require the exact stable v2 freeze for the supplied private roster."""

    try:
        expected = build_source_freeze(manifest, receipts)
    except (
        AssertionError,
        KeyError,
        RecursionError,
        TypeError,
        ValueError,
        VideoSemanticsToolingError,
    ):
        raise VideoSemanticsToolingError("SOURCE_FREEZE_INVALID") from None
    if (
        not isinstance(freeze, Mapping)
        or type(freeze.get("schema_version")) is not int
        or type(freeze.get("gaps")) is not int
        or dict(freeze) != expected
    ):
        raise VideoSemanticsToolingError("SOURCE_FREEZE_INVALID")
    return True


__all__ = [
    "FREEZE_NONCLAIMS",
    "PUBLIC_RESULT_KEYS",
    "VideoSemanticsToolingError",
    "build_source_freeze",
    "validate_source_freeze",
    "validate_ontology_jsonl",
    "validate_private_roster",
]
