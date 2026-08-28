from __future__ import annotations

import shutil
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from jsonschema import Draft202012Validator

from metis_model1 import video_census_attestation as census_attestation
from metis_model1.evaluation import wilson_interval
from metis_model1.provenance import canonical_json_hash
from metis_model1.video_semantics_contracts import (
    FIXTURE_ROOT,
    PROJECT_ROOT,
    SCHEMA_FILES,
    VideoSemanticsContractError,
    literal_sha256,
    load_json,
    load_schema,
    manifest_digest,
    schema_errors,
    semantic_concept_id,
    semantic_source_revision,
    validate_acquisition_receipt,
    validate_census_receipt,
    validate_concepts,
    validate_constraints,
    validate_crosswalk,
    validate_profile,
    validate_repository_source_manifest,
    validate_scorecard,
    validate_source_manifest,
    validate_synthetic_fixture,
    validate_task,
    validate_work_item,
)


def _fixture(name: str):
    return load_json(FIXTURE_ROOT / name)


def _synthetic_attestation_receipt(scope: dict) -> dict:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public_key = private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    authority = {
        "issuer": "synthetic-readonly-authority",
        "key_id": "synthetic-key-v1",
        "algorithm": census_attestation.ALGORITHM,
        "public_key": public_key.hex(),
        "public_key_fingerprint": census_attestation.public_key_fingerprint(public_key),
        "status": "active",
    }
    trust_store = {
        "schema_version": 1,
        "trust_store_id": "synthetic-census-trust-v1",
        "trust_store_revision": "sha256:" + "0" * 64,
        "audience": scope["audience"],
        "max_ttl_seconds": 86400,
        "clock_skew_seconds": 0,
        "authorities": [authority],
    }
    trust_store["trust_store_revision"] = census_attestation.trust_store_revision(trust_store)
    body = {
        "schema_version": 1,
        "attestation_type": census_attestation.ATTESTATION_TYPE,
        "algorithm": census_attestation.ALGORITHM,
        "issuer": authority["issuer"],
        "key_id": authority["key_id"],
        "key_fingerprint": authority["public_key_fingerprint"],
        "attestation_id": "synthetic-attestation-v1",
        "replay_id": "synthetic-replay-v1",
        **scope,
        "issued_at": "2026-08-27T09:58:00Z",
        "not_before": "2026-08-27T09:58:00Z",
        "expires_at": "2026-08-27T11:00:00Z",
    }
    signed = {
        **body,
        "signature": private_key.sign(census_attestation.attestation_signing_bytes(body)).hex(),
    }
    return census_attestation.verify_census_attestation(
        signed,
        trust_store=trust_store,
        expected_trust_store_revision=trust_store["trust_store_revision"],
        expected_scope=scope,
        now=datetime(2026, 8, 27, 9, 59, 0, tzinfo=UTC),
        valid_until=datetime(2026, 8, 27, 10, 0, 1, tzinfo=UTC),
        replay_guard=census_attestation.CensusAttestationReplayGuard(),
    )


def _synthetic_live_census_receipt() -> dict:
    scope = {
        "audience": "metis-model1.video-census",
        "tenant_ref": "synthetic-tenant-v1",
        "catalog_ref": "video",
        "alias_ref": "synthetic-video-alias-v1",
        "index_ref": "synthetic-video-index-v1",
        "profile_revision": "sha256:" + "5" * 64,
        "credential_handle_ref": "hmac-sha256:" + "6" * 64,
        "capabilities": list(census_attestation.EXACT_CAPABILITIES),
    }
    live = {
        "schema_version": 1,
        "evidence_scope": "live_census",
        "receipt_id": "synthetic-live-receipt-001",
        "profile_id": "video-semantics-census-v1",
        "profile_revision": scope["profile_revision"],
        "tenant_ref": scope["tenant_ref"],
        "catalog_ref": scope["catalog_ref"],
        "alias_ref": scope["alias_ref"],
        "index_ref": scope["index_ref"],
        "mode": "pit",
        "snapshot_ref": "synthetic-snapshot-v1",
        "mapping_sha256_before": "sha256:" + "1" * 64,
        "mapping_sha256_after": "sha256:" + "1" * 64,
        "document_count_before": 2,
        "document_count_after": 2,
        "field_roster_count": 1,
        "query_count": 1,
        "query_hashes": ["sha256:" + "2" * 64],
        "state_counts": {
            "complete": 1,
            "partial": 0,
            "denied": 0,
            "non_aggregatable": 0,
            "inconsistent": 0,
        },
        "started_at": "2026-08-27T10:00:00Z",
        "ended_at": "2026-08-27T10:00:01Z",
        "status": "VALID",
        "values_redacted": True,
        "artifact_sha256": "sha256:" + "3" * 64,
        "attestation": _synthetic_attestation_receipt(scope),
    }
    live["receipt_sha256"] = manifest_digest(live)
    return live


def test_all_eleven_schemas_are_valid_draft_2020_12_documents() -> None:
    assert len(SCHEMA_FILES) == 11
    for name in SCHEMA_FILES:
        Draft202012Validator.check_schema(load_schema(name))


def test_synthetic_fixture_has_exact_roster() -> None:
    assert validate_synthetic_fixture() == {"in": 10, "out": 10, "distinct": 10, "gaps": 0}


def test_manifest_revision_is_stable_and_receipt_is_operationally_separate() -> None:
    manifest = load_json(PROJECT_ROOT / "manifests/video-semantics-sources-v1.json")
    assert validate_source_manifest(manifest) == []
    assert semantic_source_revision(manifest) == manifest["semantic_source_revision"]
    receipt = {
        "schema_version": 1,
        "receipt_id": "synthetic-receipt-001",
        "manifest_sha256": manifest_digest(manifest),
        "source_id": "VIDEO_SYNTHETIC_FIXTURE_V1",
        "status": "VALID",
        "acquired_at": "2026-08-27T10:00:00Z",
        "duration_ms": 12,
        "run_id": "synthetic-run-001",
        "runtime": {"python": "3.13", "tool_version": "synthetic-1"},
        "counts": {"items_in": 1, "items_out": 1, "items_distinct": 1, "items_gaps": 0},
    }
    receipt["receipt_sha256"] = manifest_digest(receipt)
    assert validate_acquisition_receipt(receipt, manifest) == []
    assert receipt["manifest_sha256"] != manifest["semantic_source_revision"]


def test_repository_manifest_detects_fixture_payload_drift(tmp_path: Path) -> None:
    payload_root = tmp_path / "fixture"
    payload_root.mkdir()
    shutil.copy(FIXTURE_ROOT / "payload.json", payload_root / "payload.json")
    manifest = load_json(PROJECT_ROOT / "manifests/video-semantics-sources-v1.json")
    assert validate_repository_source_manifest(manifest, fixture_root=payload_root) == []
    (payload_root / "payload.json").write_text('{"fixture_id":"drift"}\n', encoding="utf-8")
    assert validate_repository_source_manifest(manifest, fixture_root=payload_root)


def test_literal_hash_is_byte_oriented_and_structural_hash_is_separate() -> None:
    assert literal_sha256("é") != literal_sha256("e\u0301")
    assert literal_sha256(b"raw") == literal_sha256("raw")


def test_duplicate_json_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.json"
    path.write_text('{"schema_version": 1, "schema_version": 1}', encoding="utf-8")
    with pytest.raises(VideoSemanticsContractError, match="duplicate JSON key"):
        load_json(path)


def test_dangling_concept_reference_is_rejected() -> None:
    concept = _fixture("concept.json")
    attacked = deepcopy(concept)
    attacked["parents"] = ["sha256:" + "9" * 64]
    errors = validate_concepts([attacked])
    assert any("dangling parents ref" in error for error in errors)


@pytest.mark.parametrize(
    "cardinality",
    [
        {"kind": "one", "min": 2, "max": 1},
        {"kind": "max", "min": 3, "max": 2},
        {"kind": "range", "min": 5, "max": 1},
        {"kind": "unbounded", "min": 0, "max": 1},
    ],
)
def test_impossible_concept_cardinalities_are_rejected(cardinality: dict) -> None:
    concept = _fixture("concept.json")
    concept["cardinality"] = cardinality
    concept["concept_id"] = semantic_concept_id(concept)
    errors = validate_concepts([concept])
    assert any("cardinality" in error for error in errors)


def test_concept_identity_is_host_recomputed_from_canonical_material() -> None:
    concept = _fixture("concept.json")
    assert concept["concept_id"] == semantic_concept_id(concept)
    concept["definition"] = "Changed semantic definition."
    assert any("concept_id is not deterministic" in error for error in validate_concepts([concept]))


def test_concept_relations_are_reciprocal_symmetric_and_acyclic() -> None:
    first = _fixture("concept.json")
    second = deepcopy(first)
    second.update(
        source_locator="synthetic-page-002",
        source_label="second-concept",
        definition="A second synthetic concept.",
    )
    second["concept_id"] = semantic_concept_id(second)
    first_id = first["concept_id"]
    second_id = second["concept_id"]

    first["parents"] = [second_id]
    assert any(
        "parent/child relation is not reciprocal" in error
        for error in validate_concepts([first, second])
    )

    first["parents"] = []
    first["exclusive_with"] = [second_id]
    assert any(
        "exclusive_with relation is not symmetric" in error
        for error in validate_concepts([first, second])
    )

    first["exclusive_with"] = []
    first["parents"] = [second_id]
    first["children"] = [second_id]
    second["parents"] = [first_id]
    second["children"] = [first_id]
    assert "concept hierarchy contains a cycle" in validate_concepts([first, second])


def test_path_traversal_and_raw_keys_are_rejected() -> None:
    work_item = _fixture("work-item.json")
    attacked = deepcopy(work_item)
    attacked["canonical_locator"]["path"] = "../outside.metis"
    assert schema_errors("video-semantic-work-item.schema.json", attacked)
    attacked["canonical_locator"]["path"] = "catalogs/video.metis"
    attacked["password"] = "must-not-pass"
    assert schema_errors("video-semantic-work-item.schema.json", attacked)
    assert validate_work_item(work_item, concept_ids={_fixture("concept.json")["concept_id"]}) == []


def test_sensitive_and_raw_value_markers_are_rejected() -> None:
    concept = _fixture("concept.json")
    attacked = deepcopy(concept)
    attacked["examples"] = ["Bearer token: should never enter a semantic fixture"]
    assert any("forbidden sensitive/raw value" in error for error in validate_concepts([attacked]))


def test_work_item_means_aka_and_review_state_invariants_are_fail_closed() -> None:
    item = _fixture("work-item.json")
    attacked = deepcopy(item)
    attacked["candidate"]["means"] = None
    assert any("aka requires" in error for error in validate_work_item(attacked))
    attacked["candidate"]["aka"] = []
    assert any("must be unannotated" in error for error in validate_work_item(attacked))
    attacked["candidate"]["means"] = "has meaning"
    attacked["candidate"]["review_state"] = "unannotated"
    assert any("cannot be unannotated" in error for error in validate_work_item(attacked))


def test_remaining_contract_instances_are_positive_and_repository_policy_is_public_only() -> None:
    manifest = load_json(PROJECT_ROOT / "manifests/video-semantics-sources-v1.json")
    assert validate_repository_source_manifest(manifest) == []
    assert validate_constraints(_fixture("constraint.json")) == []
    assert validate_census_receipt(_fixture("census-receipt.json")) == []
    assert schema_errors("video-grounding-scorecard.schema.json", _fixture("scorecard.json")) == []

    attacked = deepcopy(manifest)
    attacked["sources"][0]["kind"] = "reserved_editorial"
    assert validate_repository_source_manifest(attacked)


def test_invalid_mapping_values_return_errors_not_python_type_errors() -> None:
    concept = _fixture("concept.json")
    attacked_concept = deepcopy(concept)
    attacked_concept["concept_id"] = ["unhashable"]
    assert validate_concepts([attacked_concept])


def test_offline_receipt_is_valid_and_cannot_be_promoted_to_live() -> None:
    offline = _fixture("census-receipt.json")
    assert validate_census_receipt(offline) == []
    attacked = deepcopy(offline)
    attacked["document_count_before"] = 1
    assert schema_errors("video-catalog-census-receipt.schema.json", attacked)


def test_census_receipt_self_hash_drift_is_rejected() -> None:
    receipt = _fixture("census-receipt.json")
    receipt["receipt_sha256"] = "sha256:" + "0" * 64
    assert any("census receipt self-hash" in error for error in validate_census_receipt(receipt))


def test_synthetic_scorecard_self_hash_drift_is_rejected() -> None:
    scorecard = _fixture("scorecard.json")
    scorecard["receipt_sha256"] = "sha256:" + "0" * 64
    assert any("scorecard self-hash" in error for error in validate_scorecard(scorecard))


def test_live_receipt_requires_verified_attestation_and_is_strictly_distinct() -> None:
    live = _synthetic_live_census_receipt()
    assert schema_errors("video-catalog-census-receipt.schema.json", live) == []
    assert validate_census_receipt(live) == []
    offline = _fixture("census-receipt.json")
    offline["evidence_scope"] = "live_census"
    assert schema_errors("video-catalog-census-receipt.schema.json", offline)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_ref", "different-tenant"),
        ("catalog_ref", "different-catalog"),
        ("alias_ref", "different-alias"),
        ("index_ref", "different-index"),
        ("profile_revision", "sha256:" + "9" * 64),
    ],
)
def test_live_census_rejects_attestation_binding_mismatch(field: str, value: str) -> None:
    live = _synthetic_live_census_receipt()
    live[field] = value
    live["receipt_sha256"] = manifest_digest(
        {key: item for key, item in live.items() if key != "receipt_sha256"}
    )

    assert any(field in error for error in validate_census_receipt(live))


def test_live_census_rejects_attestation_receipt_tamper() -> None:
    live = _synthetic_live_census_receipt()
    live["attestation"]["receipt_sha256"] = "sha256:" + "0" * 64
    live["receipt_sha256"] = manifest_digest(
        {key: item for key, item in live.items() if key != "receipt_sha256"}
    )

    assert any("attestation receipt self-hash" in error for error in validate_census_receipt(live))


def test_live_census_must_fit_inside_attestation_time_boundary() -> None:
    live = _synthetic_live_census_receipt()
    live["ended_at"] = "2026-08-27T10:00:02Z"
    live["receipt_sha256"] = manifest_digest(
        {key: item for key, item in live.items() if key != "receipt_sha256"}
    )

    assert any("time boundary" in error for error in validate_census_receipt(live))


def test_evaluated_scorecard_requires_complete_four_by_seven_roster() -> None:
    scorecard = _fixture("scorecard.json")
    scorecard.update(
        {
            "evidence_scope": "evaluated",
            "evaluation_status": "evaluated",
            "task_roster_revision": scorecard["benchmark_revision"],
            "roster_complete": True,
            "nonclaims": ["no_accuracy99_claim", "no_training_authority"],
        }
    )
    scorecard["policy"]["thresholds_ratified"] = True
    assert schema_errors("video-grounding-scorecard.schema.json", scorecard)


def test_crosswalk_duplicate_and_dangling_rows_are_rejected() -> None:
    crosswalk = _fixture("crosswalk.json")
    concept_id = _fixture("concept.json")["concept_id"]
    assert validate_crosswalk(crosswalk, concept_ids={concept_id}) == []
    attacked = deepcopy(crosswalk)
    attacked["rows"].append(deepcopy(attacked["rows"][0]))
    assert validate_crosswalk(attacked, concept_ids={concept_id})
    attacked["rows"][1]["concept_id"] = "sha256:" + "8" * 64
    assert any(
        "dangling concept ref" in error
        for error in validate_crosswalk(attacked, concept_ids={concept_id})
    )


def test_crosswalk_and_task_revisions_are_bound_to_manifest() -> None:
    manifest = load_json(PROJECT_ROOT / "manifests/video-semantics-sources-v1.json")
    concept_id = _fixture("concept.json")["concept_id"]
    crosswalk = _fixture("crosswalk.json")
    task = _fixture("task.json")
    assert (
        validate_crosswalk(
            crosswalk,
            concept_ids={concept_id},
            semantic_source_revision_ref=manifest["semantic_source_revision"],
        )
        == []
    )
    assert (
        validate_task(task, semantic_source_revision_ref=manifest["semantic_source_revision"]) == []
    )
    crosswalk["semantic_source_revision"] = "sha256:" + "0" * 64
    task["provenance"]["source_revision"] = "sha256:" + "0" * 64
    assert validate_crosswalk(
        crosswalk,
        concept_ids={concept_id},
        semantic_source_revision_ref=manifest["semantic_source_revision"],
    )
    assert validate_task(task, semantic_source_revision_ref=manifest["semantic_source_revision"])


def test_profile_allows_explicit_zero_cardinality_as_a_partial_census_budget() -> None:
    profile = _fixture("profile.json")
    assert validate_profile(profile) == []
    attacked = deepcopy(profile)
    attacked["fields"][1]["cardinality_cap"] = 0
    body = {key: value for key, value in attacked.items() if key != "profile_revision"}
    attacked["profile_revision"] = "sha256:" + canonical_json_hash(body)
    assert validate_profile(attacked) == []


def test_profile_rejects_a_finite_value_field_without_a_literal_budget() -> None:
    profile = _fixture("profile.json")
    profile["fields"][0]["max_literal_bytes"] = 0
    body = {key: value for key, value in profile.items() if key != "profile_revision"}
    profile["profile_revision"] = "sha256:" + canonical_json_hash(body)
    assert any("no literal budget" in error for error in validate_profile(profile))


def _evaluated_scorecard() -> dict:
    scorecard = _fixture("scorecard.json")
    totals = {"V-1": 20, "V-2": 20, "V-3": 16, "V-4": 16, "V-5": 12, "V-6": 8, "V-7": 4}
    families = []
    passed = 0
    total = 0
    for family, denominator in totals.items():
        score = {"passed": denominator - 1, "total": denominator}
        score["wilson95"] = list(wilson_interval(score["passed"], denominator))
        for variant in ("B0", "B1", "D0", "D1"):
            families.append({"family": family, "variant": variant, "score": deepcopy(score)})
            passed += score["passed"]
            total += denominator
    scorecard.update(
        {
            "evidence_scope": "evaluated",
            "evaluation_status": "evaluated",
            "benchmark_revision": "sha256:" + "1" * 64,
            "task_roster_revision": "sha256:" + "1" * 64,
            "roster_complete": True,
            "variants": ["B0", "B1", "D0", "D1"],
            "overall": {"passed": passed, "total": total},
            "families": families,
            "critical": {
                "total": 12,
                "passed": 10,
                "failed": 2,
                "by_variant": {
                    variant: {"total": 12, "passed": 10, "failed": 2}
                    for variant in ("B0", "B1", "D0", "D1")
                },
            },
            "error_taxonomy": {"semantic_failure": total - passed},
            "policy": {
                "accuracy99_claim": False,
                "training_authority": False,
                "raw_outputs_present": False,
                "thresholds_ratified": True,
            },
            "nonclaims": ["no_accuracy99_claim", "no_training_authority"],
        }
    )
    scorecard["overall"]["wilson95"] = list(wilson_interval(passed, total))
    scorecard["receipt_sha256"] = manifest_digest(
        {key: value for key, value in scorecard.items() if key != "receipt_sha256"}
    )
    return scorecard


def test_evaluated_scorecard_requires_384_observations_and_explicit_critical_variants() -> None:
    scorecard = _evaluated_scorecard()
    assert schema_errors("video-grounding-scorecard.schema.json", scorecard) == []
    assert validate_scorecard(scorecard) == []


@pytest.mark.parametrize("mutation", ["overall", "family", "taxonomy", "critical", "denominator"])
def test_evaluated_scorecard_rejects_arithmetic_or_coverage_gaps(mutation: str) -> None:
    scorecard = _evaluated_scorecard()
    if mutation == "overall":
        scorecard["overall"]["passed"] -= 1
    elif mutation == "family":
        scorecard["families"][0]["score"]["passed"] -= 1
    elif mutation == "taxonomy":
        scorecard["error_taxonomy"]["semantic_failure"] -= 1
    elif mutation == "critical":
        scorecard["critical"]["by_variant"]["B0"]["failed"] = 1
    else:
        scorecard["families"][0]["score"]["total"] = 1
    scorecard["receipt_sha256"] = manifest_digest(
        {key: value for key, value in scorecard.items() if key != "receipt_sha256"}
    )
    assert validate_scorecard(scorecard)


def test_evaluated_scorecard_cannot_omit_critical_variant_breakdown() -> None:
    scorecard = _evaluated_scorecard()
    del scorecard["critical"]["by_variant"]
    assert schema_errors("video-grounding-scorecard.schema.json", scorecard)
