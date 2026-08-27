"""End-to-end local P0/P1 runner with public-safe results only.

The runner connects the bounded read-only acquisition layer, the ignored
private store, and the pure semantic validators.  Private manifests, receipts,
locators, ontology records and freeze hashes never leave the store; callers
receive only the finite redacted result contract.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from metis_model1.video_private_artifacts import PROJECT_ROOT
from metis_model1.video_private_io import (
    MAX_PRIVATE_FILE_BYTES,
    VideoPrivateIOError,
    prepare_private_store,
    read_private_bytes,
    read_private_json,
    write_private_json_atomic,
)
from metis_model1.video_semantics_tooling import (
    build_source_freeze,
    validate_ontology_jsonl,
    validate_private_roster,
    validate_source_freeze,
)
from metis_model1.video_source_acquisition import (
    VideoSourceBundle,
    acquire_video_source_roster,
    private_bundle_document,
    validate_private_bundle_document,
)
from metis_model1.video_source_extraction import (
    PUBLIC_RESULT_KEYS as SOURCE_EXTRACTION_PUBLIC_RESULT_KEYS,
)
from metis_model1.video_source_extraction import (
    extract_private_source,
    private_unit_roster,
    validate_private_envelope,
)

PRIVATE_ACQUISITION_BUNDLE = "receipts/source-acquisition-bundle-v1.json"
PRIVATE_SOURCE_FREEZE = "receipts/sources-freeze-v2.json"
PRIVATE_ONTOLOGY_JSONL = "work-items/editorial-concepts-v1.jsonl"
PRIVATE_UNIT_DISPOSITION_ROSTER = "work-items/unit-disposition-roster-v1.json"
PRIVATE_SOURCE_TEXT_BUNDLE = "work-items/source-text-bundle-v2.json"
_SYNC_MARKERS = (
    "/library/cloudstorage/",
    "/library/mobile documents/",
    "/dropbox/",
    "/google drive/",
    "/onedrive/",
)
_PUBLIC_RESULT_KEYS = frozenset(
    {
        "schema_version",
        "operation",
        "status",
        "private_roster_complete",
        "gaps",
        "sensitivity",
        "raw_payloads_present",
        "error_codes",
    }
)
_BLOCKED_CODES = frozenset({"PRIVATE_OPERATION_BLOCKED", "SOURCE_ROOT_NOT_ISOLATED"})
BLOCKED_ERROR_CODES = _BLOCKED_CODES
BLOCKED_PUBLIC_RESULT_KEYS = _PUBLIC_RESULT_KEYS
_ALLOWED_PUBLIC_OPERATIONS = frozenset(
    {
        "acquire-sources",
        "extract-sources",
        "freeze-sources",
        "private-operation",
        "validate-ontology",
    }
)


class VideoSemanticsPrivateRunnerError(RuntimeError):
    """A path- and payload-free runner failure."""

    def __init__(self, code: str = "PRIVATE_OPERATION_BLOCKED") -> None:
        self.code = code if code in _BLOCKED_CODES else "PRIVATE_OPERATION_BLOCKED"
        super().__init__(self.code)


def _blocked(code: str = "PRIVATE_OPERATION_BLOCKED") -> None:
    raise VideoSemanticsPrivateRunnerError(code)


def _canonical_source_root(source_root: Path) -> Path:
    try:
        root = source_root.resolve(strict=True)
        project = PROJECT_ROOT.resolve(strict=True)
        home = Path.home().resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        _blocked("SOURCE_ROOT_NOT_ISOLATED")
    if (
        root == Path(root.anchor)
        or root in (home, project)
        or root in home.parents
        or project in root.parents
        or root in project.parents
    ):
        _blocked("SOURCE_ROOT_NOT_ISOLATED")
    lowered = (os.fspath(root) + "/").lower()
    if any(marker in lowered for marker in _SYNC_MARKERS):
        _blocked("SOURCE_ROOT_NOT_ISOLATED")
    return root


def _bundle_parts(document: Any) -> tuple[Mapping[str, Any], list[Mapping[str, Any]]]:
    try:
        validate_private_bundle_document(document)
        if not isinstance(document, Mapping):
            _blocked()
        manifest = document["manifest"]
        roster = document["receipt_roster"]
        receipts = roster["receipts"]
        if not isinstance(manifest, Mapping) or not isinstance(receipts, list):
            _blocked()
        if not all(isinstance(receipt, Mapping) for receipt in receipts):
            _blocked()
        return manifest, receipts
    except VideoSemanticsPrivateRunnerError:
        raise
    except Exception:
        _blocked()


def _load_bundle() -> Mapping[str, Any]:
    try:
        document = read_private_json(PRIVATE_ACQUISITION_BUNDLE, MAX_PRIVATE_FILE_BYTES)
        validate_private_bundle_document(document)
        if not isinstance(document, Mapping):
            _blocked()
        return document
    except VideoSemanticsPrivateRunnerError:
        raise
    except Exception:
        _blocked()


def _stable_bundle_evidence(document: Mapping[str, Any]) -> Mapping[str, Any]:
    """Exclude receipt telemetry while preserving every acquired source claim."""

    try:
        validate_private_bundle_document(document)
        receipts = document["receipt_roster"]["receipts"]
        return {
            "manifest": document["manifest"],
            "locator_registry": document["locator_registry"],
            "receipts": [
                {
                    "schema_version": receipt["schema_version"],
                    "manifest_sha256": receipt["manifest_sha256"],
                    "source_id": receipt["source_id"],
                    "status": receipt["status"],
                    "runtime": receipt["runtime"],
                    "counts": receipt["counts"],
                }
                for receipt in receipts
            ],
        }
    except Exception:
        _blocked()


def _require_source_freeze(manifest: Mapping[str, Any], receipts: list[Mapping[str, Any]]) -> None:
    try:
        freeze = read_private_json(PRIVATE_SOURCE_FREEZE, MAX_PRIVATE_FILE_BYTES)
        validate_source_freeze(freeze, manifest, receipts)
    except VideoSemanticsPrivateRunnerError:
        raise
    except Exception:
        _blocked()


def acquire_sources(source_root: Path, *, run_id: str | None = None) -> Mapping[str, Any]:
    """Acquire and persist one atomic private source bundle."""

    prepare_private_store()
    root = _canonical_source_root(Path(source_root))
    bundle: VideoSourceBundle = acquire_video_source_roster(root, run_id=run_id)
    document = private_bundle_document(bundle)
    try:
        write_private_json_atomic(PRIVATE_ACQUISITION_BUNDLE, document)
    except VideoPrivateIOError:
        existing = _load_bundle()
        if _stable_bundle_evidence(existing) != _stable_bundle_evidence(document):
            _blocked()
    return dict(bundle.public_result)


def freeze_sources() -> Mapping[str, Any]:
    """Validate the persisted roster and write its deterministic local freeze."""

    prepare_private_store()
    document = _load_bundle()
    manifest, receipts = _bundle_parts(document)
    result = validate_private_roster(manifest, receipts)
    if result.get("status") != "VALID" or result.get("gaps") != 0:
        _blocked()
    freeze = build_source_freeze(manifest, receipts)
    try:
        write_private_json_atomic(PRIVATE_SOURCE_FREEZE, freeze)
    except VideoPrivateIOError:
        try:
            existing = read_private_json(PRIVATE_SOURCE_FREEZE, MAX_PRIVATE_FILE_BYTES)
            validate_source_freeze(existing, manifest, receipts)
        except Exception:
            _blocked()
    public = dict(result)
    public["operation"] = "freeze-sources"
    if set(public) != _PUBLIC_RESULT_KEYS:
        _blocked()
    return public


def validate_ontology() -> Mapping[str, Any]:
    """Validate the fixed private ontology JSONL against the frozen roster."""

    prepare_private_store()
    document = _load_bundle()
    manifest, receipts = _bundle_parts(document)
    _require_source_freeze(manifest, receipts)
    source_envelope = read_private_json(PRIVATE_SOURCE_TEXT_BUNDLE, MAX_PRIVATE_FILE_BYTES)
    validate_private_envelope(
        source_envelope,
        manifest,
        require_real=True,
        source_bundle=document,
    )
    payload = read_private_bytes(PRIVATE_ONTOLOGY_JSONL, MAX_PRIVATE_FILE_BYTES)
    disposition_roster = read_private_json(PRIVATE_UNIT_DISPOSITION_ROSTER, MAX_PRIVATE_FILE_BYTES)
    result = validate_ontology_jsonl(
        payload,
        manifest,
        receipts,
        private_unit_roster(source_envelope),
        disposition_roster,
        source_envelope=source_envelope,
    )
    if set(result) != _PUBLIC_RESULT_KEYS | {"ontology_valid"}:
        _blocked()
    return result


def extract_sources() -> Mapping[str, Any]:
    """Extract the frozen private source roster and persist its private envelope."""

    prepare_private_store()
    document = _load_bundle()
    manifest, receipts = _bundle_parts(document)
    _require_source_freeze(manifest, receipts)
    outcome = extract_private_source(document)
    public = dict(outcome.public_result)
    if (
        set(public) != SOURCE_EXTRACTION_PUBLIC_RESULT_KEYS
        or public.get("status") != "VALID"
        or public.get("sandbox_verified") is not True
    ):
        _blocked()
    validate_private_envelope(
        outcome.private_envelope,
        manifest,
        require_real=True,
        source_bundle=document,
    )
    try:
        write_private_json_atomic(PRIVATE_SOURCE_TEXT_BUNDLE, outcome.private_envelope)
    except VideoPrivateIOError:
        try:
            existing = read_private_json(PRIVATE_SOURCE_TEXT_BUNDLE, MAX_PRIVATE_FILE_BYTES)
            validate_private_envelope(
                existing,
                manifest,
                require_real=True,
                source_bundle=document,
            )
            if existing != outcome.private_envelope:
                _blocked()
        except Exception:
            _blocked()
    return public


def blocked_result(operation: str, code: str = "PRIVATE_OPERATION_BLOCKED") -> Mapping[str, Any]:
    """Return the only public representation of a runner/store failure."""

    safe_operation = (
        operation
        if isinstance(operation, str) and operation in _ALLOWED_PUBLIC_OPERATIONS
        else "private-operation"
    )
    safe_code = code if code in _BLOCKED_CODES else "PRIVATE_OPERATION_BLOCKED"
    result = {
        "schema_version": 1,
        "operation": safe_operation,
        "status": "BLOCKED",
        "private_roster_complete": False,
        "gaps": 1,
        "sensitivity": "internal_confidential",
        "raw_payloads_present": False,
        "error_codes": [safe_code],
    }
    if set(result) != _PUBLIC_RESULT_KEYS:
        raise AssertionError("blocked result contains an unallowlisted key")
    return result


__all__ = [
    "PRIVATE_ACQUISITION_BUNDLE",
    "PRIVATE_ONTOLOGY_JSONL",
    "PRIVATE_SOURCE_FREEZE",
    "PRIVATE_SOURCE_TEXT_BUNDLE",
    "PRIVATE_UNIT_DISPOSITION_ROSTER",
    "BLOCKED_ERROR_CODES",
    "BLOCKED_PUBLIC_RESULT_KEYS",
    "VideoSemanticsPrivateRunnerError",
    "acquire_sources",
    "blocked_result",
    "freeze_sources",
    "extract_sources",
    "validate_ontology",
]
