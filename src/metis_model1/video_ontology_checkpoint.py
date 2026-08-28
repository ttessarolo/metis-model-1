"""Fail-closed checkpoint/resume for local video-ontology authoring.

The checkpoint is deliberately an injected storage concern.  This module does
not know about the private artifact store and never writes source text.  A
caller may put the returned checkpoint in a private-IO adapter, while tests can
use a small in-memory callback.

Each unit is authored through :func:`author_ontology` as a one-unit envelope.
The host therefore retains the existing response validation and provenance
rules.  On resume, a unit is skipped only when its source identity, text hash,
model digest, record hash, and complete validated result all match the current
run.  A stale or malformed checkpoint is rejected instead of being silently
repaired.
"""

from __future__ import annotations

import base64
import copy
import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from metis_model1.video_local_ontology_author import (
    OntologyAuthoringError,
    OntologyAuthoringResult,
    _unit_roster,
    author_ontology,
)
from metis_model1.video_semantics_contracts import (
    HASH_RE,
    canonical_json_hash,
    literal_sha256,
    manifest_digest,
    validate_concepts,
)

SCHEMA_VERSION = 1
ARTIFACT_KIND = "video-semantics/ontology-authoring-checkpoint-v1"
MAX_CHECKPOINT_BYTES = 16 * 1024 * 1024
MAX_CANDIDATES_PER_UNIT = 128
MAX_CANDIDATE_RULE_CHARS = 4096
MAX_CANDIDATE_LABEL_CHARS = 256
MAX_CANDIDATE_RATIONALE_CHARS = 2048

_CHECKPOINT_KEYS = frozenset(
    {
        "schema_version",
        "artifact_kind",
        "source_envelope_sha256",
        "model_digest",
        "units",
        "checkpoint_sha256",
    }
)
_UNIT_KEYS = frozenset(
    {
        "source_ref",
        "source_locator",
        "ordinal",
        "unit_text_sha256",
        "model_digest",
        "outcome",
        "record_sha256",
    }
)
_OUTCOME_KEYS = frozenset(
    {"ontology_jsonl_b64", "disposition_roster", "private_candidates", "receipt"}
)


class OntologyCheckpointError(ValueError):
    """Raised when a checkpoint cannot be proven compatible and complete."""


class CheckpointStore(Protocol):
    """Minimal storage adapter; implementations own private persistence."""

    def load(self) -> Mapping[str, Any] | None: ...

    def save(self, checkpoint: Mapping[str, Any]) -> None: ...


def _fail(code: str) -> OntologyCheckpointError:
    return OntologyCheckpointError(code)


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise _fail("CHECKPOINT_CANONICAL_INVALID") from None


def _hash(value: Mapping[str, Any]) -> str:
    return "sha256:" + canonical_json_hash(value)


def _opaque(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and len(value) <= 128
        and all(character.isalnum() or character in "._:-" for character in value)
    )


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and bool(HASH_RE.fullmatch(value))


def _decode_jsonl(value: Any) -> tuple[bytes, list[dict[str, Any]]]:
    if not isinstance(value, str):
        raise _fail("CHECKPOINT_OUTCOME_INVALID")
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
    except (ValueError, UnicodeError):
        raise _fail("CHECKPOINT_OUTCOME_INVALID") from None
    if len(raw) > MAX_CHECKPOINT_BYTES:
        raise _fail("CHECKPOINT_TOO_LARGE")
    if not raw:
        return b"", []
    if not raw.endswith(b"\n"):
        raise _fail("CHECKPOINT_OUTCOME_INVALID")
    concepts: list[dict[str, Any]] = []
    for line in raw.splitlines():
        try:
            item = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            raise _fail("CHECKPOINT_OUTCOME_INVALID") from None
        if not isinstance(item, dict):
            raise _fail("CHECKPOINT_OUTCOME_INVALID")
        # Canonical line encoding is part of the unit outcome contract.  It
        # prevents a semantically equivalent but tampered payload being
        # accepted as a resume hit.
        if _canonical(item) + b"\n" != line + b"\n":
            raise _fail("CHECKPOINT_OUTCOME_INVALID")
        concepts.append(item)
    if validate_concepts(concepts):
        raise _fail("CHECKPOINT_CONCEPT_INVALID")
    return raw, concepts


def _validate_unit_outcome(
    value: Any,
    *,
    source_ref: str,
    source_locator: str,
    ordinal: int,
    model_digest: str,
    unit_envelope_sha256: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _OUTCOME_KEYS:
        raise _fail("CHECKPOINT_OUTCOME_INVALID")
    raw, concepts = _decode_jsonl(value["ontology_jsonl_b64"])
    roster = value["disposition_roster"]
    candidates = value["private_candidates"]
    receipt = value["receipt"]
    if (
        not isinstance(roster, Mapping)
        or not isinstance(candidates, Mapping)
        or not isinstance(receipt, Mapping)
    ):
        raise _fail("CHECKPOINT_OUTCOME_INVALID")

    candidate_items = candidates.get("candidates")
    if not isinstance(candidate_items, list) or len(candidate_items) > MAX_CANDIDATES_PER_UNIT:
        raise _fail("CHECKPOINT_CANDIDATES_INVALID")

    # The one-unit result must remain a complete authoring contract, not an
    # arbitrary partial response copied into the checkpoint.
    if set(roster) != {
        "schema_version",
        "artifact_kind",
        "source_envelope_sha256",
        "ontology_sha256",
        "entries",
        "counts",
        "roster_sha256",
    }:
        raise _fail("CHECKPOINT_ROSTER_INVALID")
    entries = roster["entries"]
    if (
        roster["schema_version"] != 1
        or roster["artifact_kind"] != "video-semantics/unit-disposition-roster-v1"
        or roster["source_envelope_sha256"] != unit_envelope_sha256
        or not isinstance(entries, list)
        or len(entries) != 1
        or not isinstance(entries[0], Mapping)
        or entries[0].get("source_ref") != source_ref
        or entries[0].get("source_locator") != source_locator
        or not isinstance(entries[0].get("concept_ids"), list)
    ):
        raise _fail("CHECKPOINT_ROSTER_INVALID")
    counts = roster["counts"]
    if counts != {"items_in": 1, "items_out": 1, "items_distinct": 1, "items_gaps": 0}:
        raise _fail("CHECKPOINT_ROSTER_INVALID")
    roster_body = {key: item for key, item in roster.items() if key != "roster_sha256"}
    if roster["roster_sha256"] != _hash(roster_body):
        raise _fail("CHECKPOINT_ROSTER_INVALID")

    concept_ids = [item.get("concept_id") for item in concepts]
    if entries[0]["concept_ids"] != concept_ids:
        raise _fail("CHECKPOINT_ROSTER_INVALID")
    if (
        set(entries[0]) != {"source_ref", "source_locator", "disposition", "reason", "concept_ids"}
        or entries[0]["disposition"] not in {"concepts", "no_concept", "excluded"}
        or not isinstance(entries[0]["reason"], str)
        or not entries[0]["reason"].strip()
        or len(entries[0]["reason"]) > 2048
        or any(
            not isinstance(concept_id, str) or not _is_hash(concept_id)
            for concept_id in entries[0]["concept_ids"]
        )
    ):
        raise _fail("CHECKPOINT_ROSTER_INVALID")
    for concept in concepts:
        if (
            concept.get("editorial_source_ref") != source_ref
            or concept.get("source_locator") != source_locator
            or concept.get("review_state") != "draft"
        ):
            raise _fail("CHECKPOINT_CONCEPT_INVALID")
    if roster["ontology_sha256"] != literal_sha256(raw):
        raise _fail("CHECKPOINT_ROSTER_INVALID")

    if set(candidates) != {
        "schema_version",
        "artifact_kind",
        "ontology_sha256",
        "candidates",
        "bundle_sha256",
    }:
        raise _fail("CHECKPOINT_CANDIDATES_INVALID")
    if (
        candidates["schema_version"] != 1
        or candidates["artifact_kind"] != "video-semantics/private-ontology-candidates-v1"
        or candidates["ontology_sha256"] != roster["ontology_sha256"]
        or not isinstance(candidates["candidates"], list)
    ):
        raise _fail("CHECKPOINT_CANDIDATES_INVALID")
    for candidate in candidate_items:
        if (
            not isinstance(candidate, Mapping)
            or candidate.get("source_ref") != source_ref
            or candidate.get("source_locator") != source_locator
            or candidate.get("ordinal") != ordinal
            or candidate.get("kind") not in {"constraint_candidates", "relation_candidates"}
            or not isinstance(candidate.get("candidate"), Mapping)
        ):
            raise _fail("CHECKPOINT_CANDIDATES_INVALID")
        item = candidate["candidate"]
        if candidate["kind"] == "constraint_candidates":
            if set(item) != {"rule", "concept_labels", "kind", "brain_behavior", "quality"}:
                raise _fail("CHECKPOINT_CANDIDATES_INVALID")
            if (
                not isinstance(item["rule"], str)
                or not item["rule"].strip()
                or len(item["rule"]) > MAX_CANDIDATE_RULE_CHARS
                or not isinstance(item["concept_labels"], list)
                or len(item["concept_labels"]) > MAX_CANDIDATES_PER_UNIT
                or not item["concept_labels"]
                or any(
                    not isinstance(label, str)
                    or not label.strip()
                    or len(label) > MAX_CANDIDATE_LABEL_CHARS
                    for label in item["concept_labels"]
                )
                or item["kind"]
                not in {"cardinality", "dependency", "exclusion", "scope", "inheritance", "other"}
                or item["brain_behavior"] not in {"apply", "clarify", "unsupported", "stop"}
                or item["quality"] not in {"explicit", "partial", "contradictory", "inferred"}
            ):
                raise _fail("CHECKPOINT_CANDIDATES_INVALID")
        else:
            if set(item) != {"subject_label", "relation", "object_label", "rationale"}:
                raise _fail("CHECKPOINT_CANDIDATES_INVALID")
            if (
                not isinstance(item["subject_label"], str)
                or not item["subject_label"].strip()
                or len(item["subject_label"]) > MAX_CANDIDATE_LABEL_CHARS
                or item["relation"]
                not in {
                    "parent",
                    "child",
                    "dependency",
                    "exclusive",
                    "equivalent-candidate",
                    "related",
                }
                or not isinstance(item["object_label"], str)
                or not item["object_label"].strip()
                or len(item["object_label"]) > MAX_CANDIDATE_LABEL_CHARS
                or not isinstance(item["rationale"], str)
                or not item["rationale"].strip()
                or len(item["rationale"]) > MAX_CANDIDATE_RATIONALE_CHARS
            ):
                raise _fail("CHECKPOINT_CANDIDATES_INVALID")
    if len({_canonical(item) for item in candidates["candidates"]}) != len(
        candidates["candidates"]
    ):
        raise _fail("CHECKPOINT_CANDIDATES_INVALID")
    candidate_body = {key: item for key, item in candidates.items() if key != "bundle_sha256"}
    if candidates["bundle_sha256"] != _hash(candidate_body):
        raise _fail("CHECKPOINT_CANDIDATES_INVALID")

    if set(receipt) != {
        "schema_version",
        "model_digest",
        "model_invocations",
        "units_in",
        "units_out",
        "units_distinct",
        "units_gaps",
        "ontology_sha256",
        "disposition_sha256",
        "receipt_sha256",
    }:
        raise _fail("CHECKPOINT_RECEIPT_INVALID")
    if (
        receipt["schema_version"] != 1
        or receipt["model_digest"] != model_digest
        or type(receipt["model_invocations"]) is not int
        or receipt["model_invocations"] < 1
        or receipt["units_in"] != 1
        or receipt["units_out"] != 1
        or receipt["units_distinct"] != 1
        or receipt["units_gaps"] != 0
        or receipt["ontology_sha256"] != roster["ontology_sha256"]
        or receipt["disposition_sha256"] != roster["roster_sha256"]
    ):
        raise _fail("CHECKPOINT_RECEIPT_INVALID")
    receipt_body = {key: item for key, item in receipt.items() if key != "receipt_sha256"}
    if receipt["receipt_sha256"] != _hash(receipt_body):
        raise _fail("CHECKPOINT_RECEIPT_INVALID")

    return {
        "ontology_jsonl_b64": value["ontology_jsonl_b64"],
        "disposition_roster": copy.deepcopy(dict(roster)),
        "private_candidates": copy.deepcopy(dict(candidates)),
        "receipt": copy.deepcopy(dict(receipt)),
    }


def _record_body(
    source_ref: str,
    source_locator: str,
    ordinal: int,
    text: str,
    model_digest: str,
    outcome: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "source_ref": source_ref,
        "source_locator": source_locator,
        "ordinal": ordinal,
        "unit_text_sha256": literal_sha256(text),
        "model_digest": model_digest,
        "outcome": copy.deepcopy(dict(outcome)),
    }


def _make_record(
    source_ref: str,
    source_locator: str,
    ordinal: int,
    text: str,
    model_digest: str,
    result: OntologyAuthoringResult,
) -> dict[str, Any]:
    outcome = {
        "ontology_jsonl_b64": base64.b64encode(result.ontology_jsonl).decode("ascii"),
        "disposition_roster": copy.deepcopy(result.disposition_roster),
        "private_candidates": copy.deepcopy(result.private_candidates),
        "receipt": copy.deepcopy(result.receipt),
    }
    body = _record_body(source_ref, source_locator, ordinal, text, model_digest, outcome)
    return dict(body, record_sha256=_hash(body))


def _validate_checkpoint(
    checkpoint: Any,
    *,
    envelope_sha256: str,
    model_digest: str,
    units: Sequence[tuple[str, str, int, str]],
    schema_version: Any,
) -> dict[tuple[str, str], dict[str, Any]]:
    if not isinstance(checkpoint, Mapping):
        raise _fail("CHECKPOINT_INVALID")
    try:
        if len(_canonical(checkpoint)) > MAX_CHECKPOINT_BYTES:
            raise _fail("CHECKPOINT_TOO_LARGE")
    except OntologyCheckpointError:
        raise
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise _fail("CHECKPOINT_INVALID") from None
    if set(checkpoint) != _CHECKPOINT_KEYS:
        raise _fail("CHECKPOINT_INVALID")
    if (
        checkpoint["schema_version"] != SCHEMA_VERSION
        or checkpoint["artifact_kind"] != ARTIFACT_KIND
        or checkpoint["source_envelope_sha256"] != envelope_sha256
        or checkpoint["model_digest"] != model_digest
        or not isinstance(checkpoint["units"], list)
        or not _is_hash(checkpoint["checkpoint_sha256"])
    ):
        raise _fail("CHECKPOINT_INVALID")
    body = {key: item for key, item in checkpoint.items() if key != "checkpoint_sha256"}
    if checkpoint["checkpoint_sha256"] != _hash(body):
        raise _fail("CHECKPOINT_HASH_INVALID")
    expected = {
        (source_ref, locator): (source_ref, locator, ordinal, text)
        for source_ref, locator, ordinal, text in units
    }
    records: dict[tuple[str, str], dict[str, Any]] = {}
    for record in checkpoint["units"]:
        if not isinstance(record, Mapping) or set(record) != _UNIT_KEYS:
            raise _fail("CHECKPOINT_UNIT_INVALID")
        source_ref, locator = record.get("source_ref"), record.get("source_locator")
        if not isinstance(source_ref, str) or not isinstance(locator, str):
            raise _fail("CHECKPOINT_UNIT_INVALID")
        key = (source_ref, locator)
        if key not in expected or key in records:
            raise _fail("CHECKPOINT_UNIT_INVALID")
        expected_ref, expected_locator, ordinal, text = expected[key]
        if (
            record.get("ordinal") != ordinal
            or record.get("unit_text_sha256") != literal_sha256(text)
            or record.get("model_digest") != model_digest
            or not _is_hash(record.get("record_sha256"))
        ):
            raise _fail("CHECKPOINT_UNIT_BINDING_INVALID")
        record_body = {item: record[item] for item in _UNIT_KEYS if item != "record_sha256"}
        if record["record_sha256"] != _hash(record_body):
            raise _fail("CHECKPOINT_UNIT_HASH_INVALID")
        outcome = _validate_unit_outcome(
            record["outcome"],
            source_ref=expected_ref,
            source_locator=expected_locator,
            ordinal=ordinal,
            model_digest=model_digest,
            unit_envelope_sha256=manifest_digest(
                {
                    "schema_version": schema_version,
                    "sources": [
                        {
                            "source_ref": expected_ref,
                            "units": [
                                {
                                    "source_locator": expected_locator,
                                    "ordinal": ordinal,
                                    "text": text,
                                }
                            ],
                        }
                    ],
                }
            ),
        )
        records[key] = dict(record, outcome=outcome)
    return records


def _checkpoint(
    records: Sequence[Mapping[str, Any]], envelope_sha256: str, model_digest: str
) -> dict[str, Any]:
    body = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "source_envelope_sha256": envelope_sha256,
        "model_digest": model_digest,
        "units": [copy.deepcopy(dict(record)) for record in records],
    }
    return dict(body, checkpoint_sha256=_hash(body))


def _empty_checkpoint(envelope_sha256: str, model_digest: str) -> dict[str, Any]:
    return _checkpoint([], envelope_sha256, model_digest)


def _single_envelope(
    envelope: Mapping[str, Any], unit: tuple[str, str, int, str]
) -> dict[str, Any]:
    source_ref, locator, ordinal, text = unit
    return {
        "schema_version": envelope.get("schema_version", 1),
        "sources": [
            {
                "source_ref": source_ref,
                "units": [{"source_locator": locator, "ordinal": ordinal, "text": text}],
            }
        ],
    }


def _aggregate(
    units: Sequence[tuple[str, str, int, str]],
    records: Mapping[tuple[str, str], Mapping[str, Any]],
    envelope: Mapping[str, Any],
    model_digest: str,
) -> OntologyAuthoringResult:
    lines = bytearray()
    entries: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    invocations = 0
    for source_ref, locator, _ordinal, _text in units:
        record = records[(source_ref, locator)]
        outcome = record["outcome"]
        raw, _concepts = _decode_jsonl(outcome["ontology_jsonl_b64"])
        lines.extend(raw)
        unit_roster = outcome["disposition_roster"]
        entries.extend(copy.deepcopy(unit_roster["entries"]))
        candidates.extend(copy.deepcopy(outcome["private_candidates"]["candidates"]))
        invocations += outcome["receipt"]["model_invocations"]
    ontology_bytes = bytes(lines)
    ontology_hash = literal_sha256(ontology_bytes)
    roster_body = {
        "schema_version": 1,
        "artifact_kind": "video-semantics/unit-disposition-roster-v1",
        "source_envelope_sha256": manifest_digest(envelope),
        "ontology_sha256": ontology_hash,
        "entries": entries,
        "counts": {
            "items_in": len(units),
            "items_out": len(units),
            "items_distinct": len(units),
            "items_gaps": 0,
        },
    }
    roster = dict(roster_body, roster_sha256=_hash(roster_body))
    candidate_body = {
        "schema_version": 1,
        "artifact_kind": "video-semantics/private-ontology-candidates-v1",
        "ontology_sha256": ontology_hash,
        "candidates": candidates,
    }
    private_candidates = dict(candidate_body, bundle_sha256=_hash(candidate_body))
    receipt_body = {
        "schema_version": 1,
        "model_digest": model_digest,
        "model_invocations": invocations,
        "units_in": len(units),
        "units_out": len(units),
        "units_distinct": len(units),
        "units_gaps": 0,
        "ontology_sha256": ontology_hash,
        "disposition_sha256": roster["roster_sha256"],
    }
    receipt = dict(receipt_body, receipt_sha256=_hash(receipt_body))
    return OntologyAuthoringResult(ontology_bytes, roster, private_candidates, receipt)


def author_ontology_checkpointed(
    envelope: Mapping[str, Any],
    client: Any,
    *,
    model_digest: str,
    checkpoint_store: CheckpointStore | None = None,
    checkpoint_load: Callable[[], Mapping[str, Any] | None] | None = None,
    checkpoint_save: Callable[[Mapping[str, Any]], None] | None = None,
    max_retries: int = 3,
    progress: Callable[[Mapping[str, int]], None] | None = None,
) -> OntologyAuthoringResult:
    """Author all units with exact-match checkpoint/resume semantics.

    ``checkpoint_load`` and ``checkpoint_save`` are intentionally callbacks so
    a production caller can connect them to private atomic I/O without this
    orchestration layer learning paths or opening files.  A save failure is
    propagated; the run never claims a durable checkpoint it did not receive.
    """
    if not isinstance(envelope, Mapping) or not _is_hash(model_digest):
        raise _fail("AUTHORING_INPUT_INVALID")
    if checkpoint_store is not None and (
        checkpoint_load is not None or checkpoint_save is not None
    ):
        raise _fail("CHECKPOINT_ADAPTER_AMBIGUOUS")
    if checkpoint_store is not None:
        checkpoint_load = checkpoint_store.load
        checkpoint_save = checkpoint_store.save
    try:
        units = _unit_roster(envelope)
    except OntologyAuthoringError:
        raise
    envelope_sha256 = manifest_digest(envelope)
    loaded = checkpoint_load() if checkpoint_load is not None else None
    checkpoint = _empty_checkpoint(envelope_sha256, model_digest) if loaded is None else loaded
    records = _validate_checkpoint(
        checkpoint,
        envelope_sha256=envelope_sha256,
        model_digest=model_digest,
        units=units,
        schema_version=envelope.get("schema_version", 1),
    )
    record_list = [
        records[(source_ref, locator)]
        for source_ref, locator, _ordinal, _text in units
        if (source_ref, locator) in records
    ]
    for unit in units:
        source_ref, locator, ordinal, text = unit
        key = (source_ref, locator)
        if key not in records:
            try:
                result = author_ontology(
                    _single_envelope(envelope, unit),
                    client,
                    model_digest=model_digest,
                    max_retries=max_retries,
                )
            except Exception:
                # Do not publish a partial or guessed record after any authoring
                # contract failure.
                raise
            record = _make_record(source_ref, locator, ordinal, text, model_digest, result)
            _validate_checkpoint(
                _checkpoint(record_list + [record], envelope_sha256, model_digest),
                envelope_sha256=envelope_sha256,
                model_digest=model_digest,
                units=units,
                schema_version=envelope.get("schema_version", 1),
            )
            records[key] = record
            record_list = [
                records[(source_ref_, locator_)]
                for source_ref_, locator_, _ordinal_, _text_ in units
                if (source_ref_, locator_) in records
            ]
            if checkpoint_save is not None:
                checkpoint_save(_checkpoint(record_list, envelope_sha256, model_digest))
        if progress is not None:
            progress(
                {
                    "units_done": sum(
                        (source_ref_, locator_) in records
                        for source_ref_, locator_, _o, _t in units
                    ),
                    "units_total": len(units),
                    "concepts": sum(
                        len(
                            _decode_jsonl(
                                records[(source_ref_, locator_)]["outcome"]["ontology_jsonl_b64"]
                            )[1]
                        )
                        for source_ref_, locator_, _o, _t in units
                        if (source_ref_, locator_) in records
                    ),
                    "model_invocations": sum(
                        records[(source_ref_, locator_)]["outcome"]["receipt"]["model_invocations"]
                        for source_ref_, locator_, _o, _t in units
                        if (source_ref_, locator_) in records
                    ),
                }
            )
    if len(records) != len(units):
        raise _fail("AUTHORING_INCOMPLETE")
    result = _aggregate(units, records, envelope, model_digest)
    if (
        result.receipt["units_in"] != result.receipt["units_out"]
        or result.receipt["units_distinct"] != len(units)
        or result.receipt["units_gaps"] != 0
    ):
        raise _fail("AGGREGATE_COVERAGE_INVALID")
    return result


# Short descriptive alias for callers that prefer the resume terminology.
resume_author_ontology = author_ontology_checkpointed


__all__ = [
    "ARTIFACT_KIND",
    "CheckpointStore",
    "OntologyCheckpointError",
    "author_ontology_checkpointed",
    "resume_author_ontology",
]
