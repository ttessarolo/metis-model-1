from __future__ import annotations

import json

import pytest

from metis_model1.video_semantics_contracts import (
    FIXTURE_ROOT,
    PROJECT_ROOT,
    literal_sha256,
    load_json,
    manifest_digest,
    semantic_concept_id,
    semantic_source_revision,
)
from metis_model1.video_semantics_tooling import (
    MAX_JSONL_BYTES,
    MAX_JSONL_LINE_BYTES,
    MAX_JSONL_RECORDS,
    PUBLIC_RESULT_KEYS,
    VideoSemanticsToolingError,
    build_source_freeze,
    validate_ontology_jsonl,
    validate_private_roster,
    validate_source_freeze,
)


def _private_manifest() -> dict:
    manifest = load_json(PROJECT_ROOT / "manifests/video-semantics-sources-v1.json")
    source = manifest["sources"][0]
    source.update(
        {
            "kind": "reserved_editorial",
            "identity_storage": "local-confidential-receipt",
            "sensitivity": "internal_editorial",
        }
    )
    manifest["semantic_source_revision"] = semantic_source_revision(manifest)
    return manifest


def _receipt(manifest: dict, *, source_id: str | None = None, status: str = "VALID") -> dict:
    value = {
        "schema_version": 1,
        "receipt_id": "synthetic-receipt-001",
        "manifest_sha256": manifest_digest(manifest),
        "source_id": source_id or manifest["sources"][0]["source_id"],
        "status": status,
        "acquired_at": "2026-08-27T10:00:00Z",
        "duration_ms": 12,
        "run_id": "synthetic-run-001",
        "runtime": {"python": "3.13", "tool_version": "synthetic-1"},
        "counts": {"items_in": 1, "items_out": 1, "items_distinct": 1, "items_gaps": 0},
    }
    value["receipt_sha256"] = manifest_digest(value)
    return value


def _concept() -> dict:
    return load_json(FIXTURE_ROOT / "concept.json")


def _unit_roster(manifest: dict) -> dict[str, tuple[str, ...]]:
    return {source["source_ref"]: ("synthetic-page-001",) for source in manifest["sources"]}


def _disposition_roster(
    manifest: dict,
    payload: bytes,
    unit_roster: dict[str, tuple[str, ...]],
    concept_ids: dict[tuple[str, str], list[str]],
    source_envelope: dict | None = None,
) -> dict:
    source_envelope = source_envelope or {"synthetic": "source-envelope"}
    entries = []
    for source_ref, locators in unit_roster.items():
        for locator in locators:
            ids = concept_ids.get((source_ref, locator), [])
            entries.append(
                {
                    "source_ref": source_ref,
                    "source_locator": locator,
                    "disposition": "concepts" if ids else "no_concept",
                    "reason": "synthetic terminal disposition",
                    "concept_ids": ids,
                }
            )
    body = {
        "schema_version": 1,
        "artifact_kind": "video-semantics/unit-disposition-roster-v1",
        "source_envelope_sha256": manifest_digest(source_envelope),
        "ontology_sha256": literal_sha256(payload),
        "entries": entries,
        "counts": {
            "items_in": len(entries),
            "items_out": len(entries),
            "items_distinct": len(entries),
            "items_gaps": 0,
        },
    }
    body["roster_sha256"] = manifest_digest(body)
    return body


def _make_partial(manifest: dict, receipts: list[dict]) -> None:
    receipts[0]["status"] = "PARTIAL"
    body = {key: value for key, value in receipts[0].items() if key != "receipt_sha256"}
    receipts[0]["receipt_sha256"] = manifest_digest(body)


def _public_safe(result: dict) -> None:
    assert set(result) <= PUBLIC_RESULT_KEYS
    serialized = json.dumps(result, sort_keys=True)
    assert "source_id" not in serialized
    assert "receipt_sha256" not in serialized
    assert "/Users/" not in serialized


def test_private_roster_validates_exact_receipts_and_redacts_public_output() -> None:
    manifest = _private_manifest()
    receipt = _receipt(manifest)
    result = validate_private_roster(manifest, [receipt])
    assert result["status"] == "VALID"
    assert result["private_roster_complete"] is True
    assert result["gaps"] == 0
    _public_safe(result)


@pytest.mark.parametrize(
    ("mutator", "code"),
    [
        (lambda manifest, receipts: receipts.clear(), "RECEIPT_MISSING"),
        (
            lambda manifest, receipts: receipts.append(
                _receipt(manifest, source_id="extra-source")
            ),
            "RECEIPT_EXTRA",
        ),
        (
            _make_partial,
            "RECEIPT_NOT_VALID",
        ),
        (
            lambda manifest, receipts: receipts[0].update(receipt_sha256="sha256:" + "0" * 64),
            "RECEIPT_INVALID",
        ),
    ],
)
def test_private_roster_rejects_missing_extra_partial_and_tampered_receipts(mutator, code) -> None:
    manifest = _private_manifest()
    receipts = [_receipt(manifest)]
    mutator(manifest, receipts)
    result = validate_private_roster(manifest, receipts)
    assert result["status"] == "INVALID"
    assert code in result["error_codes"]
    assert result["private_roster_complete"] is False
    _public_safe(result)


def test_private_roster_rejects_public_source_policy() -> None:
    manifest = _private_manifest()
    manifest["sources"][0]["kind"] = "synthetic_fixture"
    manifest["semantic_source_revision"] = semantic_source_revision(manifest)
    result = validate_private_roster(manifest, [_receipt(manifest)])
    assert "SOURCE_KIND_FORBIDDEN" in result["error_codes"]


def test_private_roster_rejects_duplicate_receipts() -> None:
    manifest = _private_manifest()
    receipt = _receipt(manifest)
    result = validate_private_roster(manifest, [receipt, dict(receipt)])
    assert result["status"] == "INVALID"
    assert "RECEIPT_DUPLICATE" in result["error_codes"]


@pytest.mark.parametrize(
    "counts",
    [
        {"items_in": 0, "items_out": 0, "items_distinct": 0, "items_gaps": 0},
        {"items_in": 2, "items_out": 2, "items_distinct": 2, "items_gaps": 0},
        {"items_in": 1, "items_out": 2, "items_distinct": 2, "items_gaps": 0},
        {"items_in": 2, "items_out": 1, "items_distinct": 2, "items_gaps": 0},
        {"items_in": 2, "items_out": 1, "items_distinct": 0, "items_gaps": 0},
    ],
)
def test_private_roster_rejects_impossible_or_drifting_counts(counts: dict) -> None:
    manifest = _private_manifest()
    receipt = _receipt(manifest)
    receipt["counts"] = counts
    body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    receipt["receipt_sha256"] = manifest_digest(body)
    result = validate_private_roster(manifest, [receipt])
    assert result["status"] == "INVALID"
    assert "RECEIPT_COUNT_DRIFT" in result["error_codes"]
    _public_safe(result)


def test_private_roster_rejects_oversized_receipt_roster() -> None:
    manifest = _private_manifest()
    receipts = [_receipt(manifest) for _ in range(4097)]
    result = validate_private_roster(manifest, receipts)
    assert result["status"] == "INVALID"
    assert result["gaps"] == 2
    assert result["error_codes"] == ["RECEIPT_LIMIT", "RECEIPT_MISSING"]
    _public_safe(result)


def test_private_roster_rejects_oversized_source_roster() -> None:
    manifest = _private_manifest()
    source = dict(manifest["sources"][0])
    manifest["sources"] = [
        {
            **source,
            "source_id": f"private-source-{index:04d}",
            "source_ref": f"private-source-ref-{index:04d}",
        }
        for index in range(4097)
    ]
    manifest["semantic_source_revision"] = semantic_source_revision(manifest)
    result = validate_private_roster(manifest, [])
    assert result["status"] == "INVALID"
    assert result["gaps"] == 1
    assert result["error_codes"] == ["SOURCE_ROSTER_LIMIT"]
    _public_safe(result)


def test_ontology_jsonl_validates_source_refs_and_preserves_public_boundary() -> None:
    manifest = _private_manifest()
    receipt = _receipt(manifest)
    concept = _concept()
    payload = (json.dumps(concept, ensure_ascii=False) + "\n").encode("utf-8")
    units = _unit_roster(manifest)
    source_envelope = {"synthetic": "source-envelope"}
    dispositions = _disposition_roster(
        manifest,
        payload,
        units,
        {(concept["editorial_source_ref"], concept["source_locator"]): [concept["concept_id"]]},
        source_envelope,
    )
    result = validate_ontology_jsonl(
        payload,
        manifest,
        [receipt],
        units,
        dispositions,
        source_envelope=source_envelope,
    )
    assert result["status"] == "VALID"
    assert result["ontology_valid"] is True
    assert result["private_roster_complete"] is True
    assert result["gaps"] == 0
    _public_safe(result)

    missing_dispositions = validate_ontology_jsonl(payload, manifest, [receipt], units)
    assert missing_dispositions["status"] == "INVALID"
    assert "DISPOSITION_ROSTER_INCOMPLETE" in missing_dispositions["error_codes"]


def test_ontology_requires_coverage_for_every_frozen_source() -> None:
    manifest = _private_manifest()
    second = dict(manifest["sources"][0])
    second.update(
        source_id="private-source-0002",
        source_ref="private-source-ref-0002",
        content_sha256="sha256:" + "1" * 64,
    )
    manifest["sources"].append(second)
    manifest["semantic_source_revision"] = semantic_source_revision(manifest)
    first_receipt = _receipt(manifest)
    second_receipt = _receipt(manifest, source_id=second["source_id"])
    second_receipt["receipt_id"] = "synthetic-receipt-002"
    second_receipt["receipt_sha256"] = manifest_digest(
        {key: value for key, value in second_receipt.items() if key != "receipt_sha256"}
    )
    concept = _concept()
    concept["editorial_source_ref"] = manifest["sources"][0]["source_ref"]
    payload = json.dumps(concept, ensure_ascii=False) + "\n"
    result = validate_ontology_jsonl(
        payload,
        manifest,
        [first_receipt, second_receipt],
        _unit_roster(manifest),
    )
    assert result["status"] == "INVALID"
    assert result["ontology_valid"] is False
    assert result["gaps"] == 2
    assert "SOURCE_COVERAGE_INCOMPLETE" in result["error_codes"]
    assert "DISPOSITION_ROSTER_INCOMPLETE" in result["error_codes"]
    _public_safe(result)


def test_ontology_requires_exact_unit_roster_and_bound_locator() -> None:
    manifest = _private_manifest()
    receipt = _receipt(manifest)
    concept = _concept()
    payload = json.dumps(concept, ensure_ascii=False) + "\n"
    missing_roster = validate_ontology_jsonl(payload, manifest, [receipt], None)
    assert missing_roster["status"] == "INVALID"
    assert "SOURCE_UNIT_ROSTER_INVALID" in missing_roster["error_codes"]

    concept["source_locator"] = "invented-page-999999"
    invented = validate_ontology_jsonl(
        json.dumps(concept, ensure_ascii=False) + "\n",
        manifest,
        [receipt],
        _unit_roster(manifest),
    )
    assert invented["status"] == "INVALID"
    assert "SOURCE_LOCATOR_MISSING" in invented["error_codes"]
    _public_safe(invented)


def test_ontology_requires_terminal_disposition_for_every_unit() -> None:
    manifest = _private_manifest()
    receipt = _receipt(manifest)
    source_ref = manifest["sources"][0]["source_ref"]
    source_envelope = {"synthetic": "source-envelope"}
    units = {source_ref: ("synthetic-page-001", "synthetic-page-002")}
    concept = _concept()
    concept["editorial_source_ref"] = source_ref
    concept["source_locator"] = "synthetic-page-001"
    concept["concept_id"] = semantic_concept_id(concept)
    payload = (json.dumps(concept, ensure_ascii=False) + "\n").encode("utf-8")
    incomplete = _disposition_roster(
        manifest,
        payload,
        {source_ref: ("synthetic-page-001",)},
        {(source_ref, "synthetic-page-001"): [concept["concept_id"]]},
        source_envelope,
    )
    result = validate_ontology_jsonl(
        payload, manifest, [receipt], units, incomplete, source_envelope=source_envelope
    )
    assert result["status"] == "INVALID"
    assert "DISPOSITION_ROSTER_INCOMPLETE" in result["error_codes"]
    _public_safe(result)

    complete = _disposition_roster(
        manifest,
        payload,
        units,
        {(source_ref, "synthetic-page-001"): [concept["concept_id"]]},
        source_envelope,
    )
    result = validate_ontology_jsonl(
        payload,
        manifest,
        [receipt],
        units,
        complete,
        source_envelope=source_envelope,
    )
    assert result["status"] == "VALID"
    assert result["gaps"] == 0
    _public_safe(result)


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ('{"schema_version":1,"schema_version":1}\n', "DUPLICATE_JSON_KEY"),
        ('{"schema_version": NaN}\n', "NONFINITE_JSON"),
        ('{"schema_version":1}\n\n', "JSONL_BLANK_LINE"),
        ("not-json\n", "MALFORMED_JSON"),
        ("[" * 2000 + "0" + "]" * 2000 + "\n", "JSONL_NESTING_LIMIT"),
    ],
)
def test_ontology_jsonl_rejects_malformed_duplicate_nonfinite_and_blank(payload, code) -> None:
    manifest = _private_manifest()
    result = validate_ontology_jsonl(
        payload, manifest, [_receipt(manifest)], _unit_roster(manifest)
    )
    assert result["status"] == "INVALID"
    assert code in result["error_codes"]
    _public_safe(result)


def test_ontology_jsonl_rejects_dangling_source_and_sensitive_nested_value() -> None:
    manifest = _private_manifest()
    receipt = _receipt(manifest)
    concept = _concept()
    concept["editorial_source_ref"] = "missing-private-source"
    concept["examples"] = ["Bearer token: never persist this"]
    result = validate_ontology_jsonl(
        json.dumps(concept) + "\n", manifest, [receipt], _unit_roster(manifest)
    )
    assert result["status"] == "INVALID"
    assert "SOURCE_REF_MISSING" in result["error_codes"]
    assert "CONCEPT_INVALID" in result["error_codes"]
    _public_safe(result)


def test_ontology_jsonl_rejects_duplicate_concept_ids() -> None:
    manifest = _private_manifest()
    receipt = _receipt(manifest)
    concept = _concept()
    payload = json.dumps(concept) + "\n" + json.dumps(concept) + "\n"
    result = validate_ontology_jsonl(payload, manifest, [receipt], _unit_roster(manifest))
    assert result["status"] == "INVALID"
    assert "CONCEPT_INVALID" in result["error_codes"]


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        (b"x" * (MAX_JSONL_BYTES + 1), "JSONL_TOO_LARGE"),
        (b"x" * (MAX_JSONL_LINE_BYTES + 1), "JSONL_LINE_TOO_LARGE"),
        ("\ud800", "JSONL_UNICODE_INVALID"),
        (b'"\xed\xa0\x80"\n', "JSONL_UNICODE_INVALID"),
        (b'"\\ud800"\n', "JSONL_UNICODE_INVALID"),
        (b"{}\n" * (MAX_JSONL_RECORDS + 1), "JSONL_RECORD_LIMIT"),
    ],
    ids=(
        "payload-too-large",
        "line-too-large",
        "surrogate-text",
        "surrogate-utf8",
        "surrogate-json-escape",
        "record-limit",
    ),
)
def test_ontology_jsonl_has_deterministic_input_limits_and_unicode_rejection(payload, code) -> None:
    manifest = _private_manifest()
    result = validate_ontology_jsonl(
        payload, manifest, [_receipt(manifest)], _unit_roster(manifest)
    )
    assert result["status"] == "INVALID"
    assert code in result["error_codes"]
    _public_safe(result)


def test_source_freeze_is_stable_self_hashed_and_local_only() -> None:
    manifest = _private_manifest()
    receipt = _receipt(manifest)
    first = build_source_freeze(manifest, [receipt])
    second = build_source_freeze(manifest, [receipt])
    assert first == second
    body = {key: value for key, value in first.items() if key != "freeze_sha256"}
    assert first["freeze_sha256"] == manifest_digest(body)
    assert first["status"] == "FROZEN_LOCAL"
    assert first["evidence_scope"] == "local_confidential"
    assert first["nonclaims"]


def test_source_freeze_excludes_operational_receipt_volatility() -> None:
    manifest = _private_manifest()
    first_receipt = _receipt(manifest)
    second_receipt = dict(first_receipt)
    second_receipt.update(
        receipt_id="synthetic-receipt-999",
        acquired_at="2026-08-27T11:30:00Z",
        duration_ms=9_999,
        run_id="synthetic-run-999",
    )
    second_receipt["receipt_sha256"] = manifest_digest(
        {key: value for key, value in second_receipt.items() if key != "receipt_sha256"}
    )
    assert first_receipt["receipt_sha256"] != second_receipt["receipt_sha256"]
    assert build_source_freeze(manifest, [first_receipt]) == build_source_freeze(
        manifest, [second_receipt]
    )


def test_source_freeze_fails_closed_until_receipts_are_complete() -> None:
    manifest = _private_manifest()
    with pytest.raises(VideoSemanticsToolingError, match="SOURCE_ROSTER_INCOMPLETE"):
        build_source_freeze(manifest, [])


def test_source_freeze_validator_rejects_rehashed_semantic_tamper() -> None:
    manifest = _private_manifest()
    receipt = _receipt(manifest)
    freeze = build_source_freeze(manifest, [receipt])
    assert validate_source_freeze(freeze, manifest, [receipt]) is True
    tampered = dict(freeze)
    tampered["semantic_source_revision"] = "sha256:" + "0" * 64
    tampered["freeze_sha256"] = manifest_digest(
        {key: value for key, value in tampered.items() if key != "freeze_sha256"}
    )
    with pytest.raises(VideoSemanticsToolingError, match="SOURCE_FREEZE_INVALID"):
        validate_source_freeze(tampered, manifest, [receipt])

    for field, value in (("schema_version", True), ("gaps", False)):
        tampered_type = dict(freeze)
        tampered_type[field] = value
        tampered_type["freeze_sha256"] = manifest_digest(
            {key: item for key, item in tampered_type.items() if key != "freeze_sha256"}
        )
        with pytest.raises(VideoSemanticsToolingError, match="SOURCE_FREEZE_INVALID"):
            validate_source_freeze(tampered_type, manifest, [receipt])
