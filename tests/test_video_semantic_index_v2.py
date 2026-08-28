from __future__ import annotations

import json
from copy import deepcopy

import pytest

from metis_model1.provenance import canonical_json_hash
from metis_model1.video_brain_grounding_v2 import (
    BrainGroundingV2Error,
    adjudicate_grounding_proposal_v2,
    build_brain_context_v2_manifest,
    build_brain_semantic_context_v2,
    validate_brain_context_v2_manifest,
    validate_brain_context_v2_receipt,
    validate_brain_semantic_context_v2,
    validate_grounding_v2_receipt,
)
from metis_model1.video_catalog_projection import PROJECTION_CONTRACT
from metis_model1.video_local_census import build_local_census
from metis_model1.video_semantic_crosswalk import build_preliminary_crosswalk
from metis_model1.video_semantic_index_v2 import (
    SemanticIndexV2Error,
    build_semantic_index_v2,
    canonical_semantic_index_v2_bytes,
    constraint_ledger_revision,
    semantic_index_v2_revision,
    validate_semantic_index_v2,
    validate_semantic_index_v2_receipt,
)
from metis_model1.video_semantics_contracts import semantic_concept_id

SEMANTIC_REVISION = "sha256:" + "1" * 64
GRAMMAR_REVISION = "sha256:" + "2" * 64
TOOLCHAIN_REVISION = "sha256:" + "3" * 64
TENANT_REVISION = "sha256:" + "4" * 64
CONSTRAINT_ID = "sha256:" + "5" * 64


def _hash(value: object) -> str:
    return "sha256:" + canonical_json_hash(value)


def _semantic(state: str, line: int, *, text: str | None = None) -> dict:
    result = {"state": state, "at": {"file": "catalogs/video.metis", "line": line}}
    if text is not None:
        result["means"] = {
            "text": text,
            "at": {"file": "catalogs/video.metis", "line": line + 1},
        }
    return result


def _projection() -> dict:
    return {
        "schema": 2,
        "projection_contract": PROJECTION_CONTRACT,
        "tenant": "public-synthetic",
        "thresholds": {"inline-max": 12, "enum-max": 300},
        "catalogs": [
            {
                "name": "video",
                "driver": "opensearch",
                "file": "catalogs/video.metis",
                "semantic": _semantic("reviewed", 2, text="contenuti video"),
                "fields": [
                    {
                        "name": "color",
                        "type": "keyword",
                        "modifiers": [],
                        "semantic": _semantic("reviewed", 10, text="trattamento cromatico"),
                        "domain": {
                            "kind": "enum",
                            "size": 2,
                            "nature": "editorial",
                            "values": [
                                {
                                    "literal": "Black and white",
                                    "semantic": _semantic(
                                        "reviewed", 20, text="immagine monocromatica"
                                    ),
                                },
                                {
                                    "literal": "Color",
                                    "semantic": _semantic("reviewed", 30, text="immagine a colori"),
                                },
                            ],
                        },
                    }
                ],
            }
        ],
    }


def _projection_receipt(projection: dict) -> dict:
    receipt = {
        "schema_version": 1,
        "receipt_id": "video-semantics/catalog-projection-receipt-v1",
        "projection_sha256": _hash(projection),
        "describe_sha256": _hash({"source": "synthetic-describe"}),
        "values_projection_sha256": [_hash({"source": "synthetic-values-color"})],
        "counts": {
            "catalogs": 1,
            "fields": 1,
            "finite_fields_expected": 1,
            "values_responses": 1,
            "values": 2,
            "semantic_values": 2,
            "gaps": 0,
        },
        "payload_redacted": True,
    }
    receipt["receipt_sha256"] = _hash(receipt)
    return receipt


def _concept(label: str, locator: str) -> dict:
    concept = {
        "schema_version": 1,
        "concept_id": "",
        "editorial_source_ref": "approved-source-a",
        "source_locator": locator,
        "editorial_variant": "shared",
        "scope": ["content"],
        "source_label": label,
        "definition": f"Definition of {label}",
        "include_when": [f"include {label}"],
        "exclude_when": [f"exclude {label}"],
        "cardinality": {"kind": "one", "min": 0, "max": 1},
        "parents": [],
        "children": [],
        "dependencies": [],
        "exclusive_with": [],
        "examples": [],
        "source_quality": "explicit",
        "notes": [],
        "review_state": "reviewed",
    }
    concept["concept_id"] = semantic_concept_id(concept)
    return concept


def _constraint_ledger() -> dict:
    ledger = {
        "schema_version": 1,
        "constraint_revision": "sha256:" + "0" * 64,
        "constraints": [
            {
                "constraint_id": CONSTRAINT_ID,
                "rule": "Choose at most one color treatment.",
                "fields": ["color"],
                "grammar_expressed": True,
                "validator_verifiable": True,
                "editorial_oracle": True,
                "brain_behavior": "apply",
                "future_grammar_decision": None,
                "evidence_refs": ["approved-source-a:constraint-1"],
                "review_state": "reviewed",
            }
        ],
    }
    ledger["constraint_revision"] = constraint_ledger_revision(ledger)
    return ledger


def _bundle(*, terminal_absent: bool = False) -> dict:
    projection = _projection()
    projection_receipt = _projection_receipt(projection)
    census = build_local_census(
        projection,
        semantic_source_revision=SEMANTIC_REVISION,
        tenant_ref="public-synthetic",
    )
    monochrome = _concept("monochrome", "approved-source-a:1")
    concepts = [monochrome]
    decisions = [
        {
            "concept_id": monochrome["concept_id"],
            "catalog": "video",
            "field": "color",
            "literal": "Black and white",
            "relation": "exact",
            "field_status": "declared-observed",
            "reason": "The reviewed catalog value is the exact technical target.",
            "evidence_refs": ["approved-source-a:1"],
            "validated_usages": ["approved-usage-a:1"],
            "decision_required": False,
            "reviewer": "editor-a",
            "decision_state": "reviewed",
        }
    ]
    if terminal_absent:
        missing = _concept("not represented", "approved-source-a:2")
        concepts.append(missing)
        decisions.append(
            {
                "concept_id": missing["concept_id"],
                "catalog": None,
                "field": None,
                "literal": None,
                "canonical_locator": "absent:concept-2",
                "relation": "absent",
                "field_status": "absent",
                "reason": "Review confirmed that no technical target exists.",
                "evidence_refs": ["approved-source-a:2"],
                "validated_usages": [],
                "decision_required": False,
                "reviewer": "editor-a",
                "decision_state": "reviewed",
            }
        )
    crosswalk = build_preliminary_crosswalk(
        concepts,
        census,
        decisions,
        semantic_source_revision=SEMANTIC_REVISION,
    )
    snapshot = {
        "snapshot_id": "snapshot-001",
        "membership_sha256": census["receipt"]["roster_sha256"],
        "tenant_revision": TENANT_REVISION,
        "catalog_projection_sha256": projection_receipt["projection_sha256"],
    }
    return {
        "projection": projection,
        "projection_receipt": projection_receipt,
        "local_census": census,
        "concepts": concepts,
        "crosswalk": crosswalk,
        "constraint_ledger": _constraint_ledger(),
        "semantic_source_revision": SEMANTIC_REVISION,
        "grammar_revision": GRAMMAR_REVISION,
        "toolchain_revision": TOOLCHAIN_REVISION,
        "tenant_snapshot": snapshot,
    }


def _build(bundle: dict | None = None) -> dict:
    args = _bundle() if bundle is None else bundle
    return build_semantic_index_v2(**args)


def _rehash_crosswalk(bundle: dict) -> None:
    crosswalk = bundle["crosswalk"]
    receipt = crosswalk["receipt"]
    receipt["crosswalk_sha256"] = _hash(crosswalk["crosswalk"])
    receipt["receipt_sha256"] = _hash(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )


def test_v2_joins_explicit_semantics_constraints_and_census_locators() -> None:
    bundle = _bundle()
    result = _build(bundle)
    assert validate_semantic_index_v2(result["index"]) == []
    assert validate_semantic_index_v2_receipt(result["receipt"]) == []

    target = next(
        entry for entry in result["index"]["entries"] if entry.get("literal") == "Black and white"
    )
    census_target = next(
        entry
        for entry in bundle["local_census"]["roster"]
        if entry.get("literal") == "Black and white"
    )
    assert target["canonical_locator"] == census_target["locator"]
    assert target["semantic_refs"] == [bundle["concepts"][0]["concept_id"]]

    field = next(entry for entry in result["index"]["entries"] if entry["node_kind"] == "field")
    assert field["type"] == "keyword"
    assert field["modifiers"] == []
    values = [entry for entry in result["index"]["entries"] if entry["node_kind"] == "value"]
    assert all("type" not in entry and "modifiers" not in entry for entry in values)
    assert field["constraint_refs"] == [CONSTRAINT_ID]
    assert all(entry["constraint_refs"] == [CONSTRAINT_ID] for entry in values)
    assert result["receipt"]["counts"]["constraint_refs"] == 3


def test_v2_is_deterministic_for_identical_inputs() -> None:
    bundle = _bundle()
    first = _build(deepcopy(bundle))
    second = _build(deepcopy(bundle))
    assert first == second
    assert canonical_semantic_index_v2_bytes(first["index"]) == canonical_semantic_index_v2_bytes(
        second["index"]
    )
    assert first["index"]["revision"] == semantic_index_v2_revision(first["index"])


def test_v2_receipt_is_hash_count_only_and_rejects_payload_or_false_markers() -> None:
    receipt = _build()["receipt"]
    rendered = json.dumps(receipt, sort_keys=True)
    assert "Black and white" not in rendered
    assert "Choose at most one" not in rendered
    assert '"literal"' not in rendered
    assert '"rule"' not in rendered

    attacked = deepcopy(receipt)
    attacked["literal"] = "Black and white"
    assert validate_semantic_index_v2_receipt(attacked)
    attacked = deepcopy(receipt)
    attacked["payload_redacted"] = False
    assert validate_semantic_index_v2_receipt(attacked)
    attacked = deepcopy(receipt)
    attacked["reasoning_present"] = True
    assert validate_semantic_index_v2_receipt(attacked)


def test_v2_rejects_projection_census_and_snapshot_tamper() -> None:
    bundle = _bundle()
    bundle["projection"]["catalogs"][0]["fields"][0]["domain"]["values"][0]["literal"] = "Tampered"
    with pytest.raises(SemanticIndexV2Error, match="projection content"):
        _build(bundle)

    bundle = _bundle()
    bundle["local_census"]["roster"][2]["literal"] = "Tampered"
    with pytest.raises(SemanticIndexV2Error, match="projection-derived census"):
        _build(bundle)

    bundle = _bundle()
    bundle["tenant_snapshot"]["membership_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(SemanticIndexV2Error, match="different census membership"):
        _build(bundle)

    bundle = _bundle()
    bundle["tenant_snapshot"]["catalog_projection_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(SemanticIndexV2Error, match="different projection"):
        _build(bundle)


def test_v2_rejects_dangling_and_nonfinal_crosswalk_rows() -> None:
    bundle = _bundle()
    bundle["crosswalk"]["crosswalk"]["rows"][0]["canonical_locator"] = "sha256:" + "f" * 64
    _rehash_crosswalk(bundle)
    with pytest.raises(SemanticIndexV2Error, match="locator is not in the census"):
        _build(bundle)

    bundle = _bundle()
    bundle["crosswalk"]["crosswalk"]["rows"][0]["decision_state"] = "provisional"
    _rehash_crosswalk(bundle)
    with pytest.raises(SemanticIndexV2Error, match="reviewed final decision"):
        _build(bundle)

    bundle = _bundle()
    receipt = bundle["crosswalk"]["receipt"]
    receipt["critical_unresolved"] = 1
    receipt["receipt_sha256"] = _hash(
        {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    )
    with pytest.raises(SemanticIndexV2Error, match="critical gaps"):
        _build(bundle)


def test_v2_rejects_nonreviewed_incoherent_or_dangling_constraints() -> None:
    bundle = _bundle()
    ledger = bundle["constraint_ledger"]
    ledger["constraints"][0]["review_state"] = "draft"
    ledger["constraint_revision"] = constraint_ledger_revision(ledger)
    with pytest.raises(SemanticIndexV2Error, match="all constraints must be reviewed"):
        _build(bundle)

    bundle = _bundle()
    ledger = bundle["constraint_ledger"]
    ledger["constraints"][0]["editorial_oracle"] = False
    ledger["constraint_revision"] = constraint_ledger_revision(ledger)
    with pytest.raises(SemanticIndexV2Error, match="cannot apply"):
        _build(bundle)

    bundle = _bundle()
    ledger = bundle["constraint_ledger"]
    ledger["constraints"][0]["fields"] = ["missing"]
    ledger["constraint_revision"] = constraint_ledger_revision(ledger)
    with pytest.raises(SemanticIndexV2Error, match="does not resolve exactly once"):
        _build(bundle)


def test_v2_validator_rejects_join_and_locator_tamper_even_after_rehash() -> None:
    index = _build()["index"]
    attacked = deepcopy(index)
    target = next(entry for entry in attacked["entries"] if entry["semantic_refs"])
    target["semantic_refs"] = ["sha256:" + "f" * 64]
    attacked["revision"] = semantic_index_v2_revision(attacked)
    assert any("dangling semantic ref" in error for error in validate_semantic_index_v2(attacked))

    attacked = deepcopy(index)
    field = next(entry for entry in attacked["entries"] if entry["node_kind"] == "field")
    field["constraint_refs"] = []
    attacked["revision"] = semantic_index_v2_revision(attacked)
    assert any(
        "differ from their field parent" in error for error in validate_semantic_index_v2(attacked)
    )

    attacked = deepcopy(index)
    attacked["entries"][0]["canonical_locator"] = "sha256:" + "e" * 64
    attacked["revision"] = semantic_index_v2_revision(attacked)
    assert any(
        "differs from its source node" in error for error in validate_semantic_index_v2(attacked)
    )

    attacked = deepcopy(index)
    field = next(entry for entry in attacked["entries"] if entry["node_kind"] == "field")
    field["modifiers"] = ["multi", "multi"]
    attacked["revision"] = semantic_index_v2_revision(attacked)
    assert any(
        "field technical surface is invalid" in error
        for error in validate_semantic_index_v2(attacked)
    )


def test_v2_preserves_reviewed_terminal_absence_without_fake_mapping() -> None:
    result = _build(_bundle(terminal_absent=True))
    index = result["index"]
    absent = index["terminal_absent_semantic_refs"]
    assert len(absent) == 1
    assert absent[0] in index["semantic_ref_roster"]
    assert all(absent[0] not in entry["semantic_refs"] for entry in index["entries"])
    assert result["receipt"]["counts"]["terminal_absent_concepts"] == 1
    assert validate_semantic_index_v2(index) == []


def test_brain_context_v2_binds_reviewed_meaning_to_exact_index_membership() -> None:
    bundle = _bundle(terminal_absent=True)
    index = _build(bundle)["index"]
    result = build_brain_semantic_context_v2(
        index,
        bundle["concepts"],
        bundle["crosswalk"],
        bundle["constraint_ledger"],
    )
    context = result["context"]
    assert validate_brain_semantic_context_v2(index, context) == []
    assert validate_brain_context_v2_receipt(result["receipt"], context=context) == []
    assert (
        validate_brain_context_v2_manifest(
            index,
            context,
            result["receipt"],
            result["manifest"],
            expected_manifest_sha256=result["manifest"]["manifest_sha256"],
        )
        == []
    )
    assert result["receipt"]["counts"] == {
        "concepts": 2,
        "mapped": 1,
        "absent": 1,
        "constraints": 1,
        "gaps": 0,
    }
    rendered_receipt = json.dumps(result["receipt"], sort_keys=True)
    assert "monochrome" not in rendered_receipt
    assert "not represented" not in rendered_receipt


def _adjudicate_with_authority(
    index: dict,
    context_result: dict,
    request: str,
    proposal: dict,
) -> dict:
    manifest = context_result["manifest"]
    return adjudicate_grounding_proposal_v2(
        index,
        context_result["context"],
        request,
        proposal,
        context_receipt=context_result["receipt"],
        context_manifest=manifest,
        expected_context_manifest_sha256=manifest["manifest_sha256"],
    )


def test_grounding_v2_adjudicates_each_clause_and_redacts_public_receipt() -> None:
    bundle = _bundle(terminal_absent=True)
    index = _build(bundle)["index"]
    context_result = build_brain_semantic_context_v2(
        index,
        bundle["concepts"],
        bundle["crosswalk"],
        bundle["constraint_ledger"],
    )
    context = context_result["context"]
    mapped_ref = next(
        item["semantic_ref"] for item in context["concepts"] if item["target"]["status"] == "mapped"
    )
    absent_ref = next(
        item["semantic_ref"] for item in context["concepts"] if item["target"]["status"] == "absent"
    )
    target = next(item for item in index["entries"] if item.get("literal") == "Black and white")
    request = "Black and white, plus not represented"
    proposal = {
        "schema_version": 1,
        "proposal_id": "synthetic-proposal-001",
        "index_revision": index["revision"],
        "context_revision": context["revision"],
        "request_sha256": _hash(request),
        "clauses": [
            {
                "clause_id": "color",
                "surface": "Black and white",
                "resolution": "resolved",
                "semantic_refs": [mapped_ref],
                "target_locators": [target["canonical_locator"]],
                "candidate_locators": [],
                "requested_value": None,
                "reason_code": "SEMANTIC_SNAPSHOT_MEMBER",
            },
            {
                "clause_id": "missing",
                "surface": "not represented",
                "resolution": "unsupported",
                "semantic_refs": [absent_ref],
                "target_locators": [],
                "candidate_locators": [],
                "requested_value": None,
                "reason_code": "UNSUPPORTED_METADATA",
            },
        ],
    }
    result = _adjudicate_with_authority(index, context_result, request, proposal)
    assert result["grounding"]["status"] == "clarify"
    assert [item["resolution"] for item in result["grounding"]["clauses"]] == [
        "resolved",
        "unsupported",
    ]
    assert validate_grounding_v2_receipt(result["receipt"]) == []
    receipt_text = json.dumps(result["receipt"], sort_keys=True)
    assert "Black and white" not in receipt_text
    assert "not represented" not in receipt_text


def test_grounding_v2_requires_clarification_for_legacy_candidate_mismatch() -> None:
    bundle = _bundle(terminal_absent=True)
    index = _build(bundle)["index"]
    context_result = build_brain_semantic_context_v2(
        index,
        bundle["concepts"],
        bundle["crosswalk"],
        bundle["constraint_ledger"],
    )
    context = context_result["context"]
    absent_ref = next(
        item["semantic_ref"] for item in context["concepts"] if item["target"]["status"] == "absent"
    )
    candidate = next(item for item in index["entries"] if item.get("literal") == "Black and white")
    request = "Black and white"
    proposal = {
        "schema_version": 1,
        "proposal_id": "synthetic-proposal-legacy",
        "index_revision": index["revision"],
        "context_revision": context["revision"],
        "request_sha256": _hash(request),
        "clauses": [
            {
                "clause_id": "legacy",
                "surface": request,
                "resolution": "clarify",
                "semantic_refs": [absent_ref],
                "target_locators": [],
                "candidate_locators": [candidate["canonical_locator"]],
                "requested_value": None,
                "reason_code": "LEGACY_LITERAL_NOT_EQUIVALENT",
            }
        ],
    }
    result = _adjudicate_with_authority(index, context_result, request, proposal)
    assert result["grounding"]["status"] == "clarify"
    assert result["receipt"]["counts"]["candidates"] == 1


def test_grounding_v2_rejects_stale_context_and_invented_membership() -> None:
    bundle = _bundle(terminal_absent=True)
    index = _build(bundle)["index"]
    context_result = build_brain_semantic_context_v2(
        index,
        bundle["concepts"],
        bundle["crosswalk"],
        bundle["constraint_ledger"],
    )
    context = context_result["context"]
    attacked = deepcopy(context)
    attacked["index_revision"] = "sha256:" + "f" * 64
    assert validate_brain_semantic_context_v2(index, attacked)

    request = "invented"
    proposal = {
        "schema_version": 1,
        "proposal_id": "synthetic-proposal-invented",
        "index_revision": index["revision"],
        "context_revision": context["revision"],
        "request_sha256": _hash(request),
        "clauses": [
            {
                "clause_id": "invented",
                "surface": request,
                "resolution": "resolved",
                "semantic_refs": [],
                "target_locators": ["sha256:" + "f" * 64],
                "candidate_locators": [],
                "requested_value": None,
                "reason_code": "EXACT_SNAPSHOT_MEMBER",
            }
        ],
    }
    with pytest.raises(BrainGroundingV2Error, match="outside snapshot membership"):
        _adjudicate_with_authority(index, context_result, request, proposal)


def _proposal_for_single_target(index: dict, context: dict, request: str, surface: str) -> dict:
    target = next(item for item in index["entries"] if item["node_kind"] == "value")
    return {
        "schema_version": 1,
        "proposal_id": "synthetic-proposal-coverage",
        "index_revision": index["revision"],
        "context_revision": context["revision"],
        "request_sha256": _hash(request),
        "clauses": [
            {
                "clause_id": "only-clause",
                "surface": surface,
                "resolution": "resolved",
                "semantic_refs": target["semantic_refs"],
                "target_locators": [target["canonical_locator"]],
                "candidate_locators": [],
                "requested_value": None,
                "reason_code": "SEMANTIC_SNAPSHOT_MEMBER",
            }
        ],
    }


def test_grounding_v2_rejects_silent_omission_of_substantive_request_clause() -> None:
    bundle = _bundle()
    index = _build(bundle)["index"]
    context_result = build_brain_semantic_context_v2(
        index,
        bundle["concepts"],
        bundle["crosswalk"],
        bundle["constraint_ledger"],
    )
    context = context_result["context"]
    request = "Black and white, awards, open ending"
    proposal = _proposal_for_single_target(index, context, request, "Black and white")
    with pytest.raises(BrainGroundingV2Error, match="omits request clause"):
        _adjudicate_with_authority(index, context_result, request, proposal)


def test_grounding_v2_rejects_arbitrary_surface_for_reviewed_target() -> None:
    bundle = _bundle()
    index = _build(bundle)["index"]
    context_result = build_brain_semantic_context_v2(
        index,
        bundle["concepts"],
        bundle["crosswalk"],
        bundle["constraint_ledger"],
    )
    context = context_result["context"]
    request = "nonsense"
    proposal = _proposal_for_single_target(index, context, request, request)
    with pytest.raises(BrainGroundingV2Error, match="surface is not supported"):
        _adjudicate_with_authority(index, context_result, request, proposal)


def test_grounding_v2_rejects_one_valid_phrase_swallowing_other_clauses() -> None:
    bundle = _bundle()
    index = _build(bundle)["index"]
    context_result = build_brain_semantic_context_v2(
        index,
        bundle["concepts"],
        bundle["crosswalk"],
        bundle["constraint_ledger"],
    )
    context = context_result["context"]
    request = "Black and white, awards, open ending"
    proposal = _proposal_for_single_target(index, context, request, request)
    with pytest.raises(BrainGroundingV2Error, match="surface is not supported"):
        _adjudicate_with_authority(index, context_result, request, proposal)


def test_grounding_v2_requires_explicit_unmapped_clause_for_nonsemantic_text() -> None:
    bundle = _bundle()
    index = _build(bundle)["index"]
    context_result = build_brain_semantic_context_v2(
        index,
        bundle["concepts"],
        bundle["crosswalk"],
        bundle["constraint_ledger"],
    )
    context = context_result["context"]
    request = "Black and white, awards"
    target = next(item for item in index["entries"] if item.get("literal") == "Black and white")
    proposal = {
        "schema_version": 1,
        "proposal_id": "synthetic-proposal-explicit-gap",
        "index_revision": index["revision"],
        "context_revision": context["revision"],
        "request_sha256": _hash(request),
        "clauses": [
            {
                "clause_id": "color",
                "surface": "Black and white",
                "resolution": "resolved",
                "semantic_refs": target["semantic_refs"],
                "target_locators": [target["canonical_locator"]],
                "candidate_locators": [],
                "requested_value": None,
                "reason_code": "SEMANTIC_SNAPSHOT_MEMBER",
            },
            {
                "clause_id": "awards",
                "surface": "awards",
                "resolution": "clarify",
                "semantic_refs": [],
                "target_locators": [],
                "candidate_locators": [],
                "requested_value": None,
                "reason_code": "UNMAPPED_REQUEST_SURFACE",
            },
        ],
    }
    result = _adjudicate_with_authority(index, context_result, request, proposal)
    assert result["grounding"]["status"] == "clarify"


def test_brain_context_v2_manifest_rejects_rehashed_context_tamper() -> None:
    bundle = _bundle(terminal_absent=True)
    index = _build(bundle)["index"]
    result = build_brain_semantic_context_v2(
        index,
        bundle["concepts"],
        bundle["crosswalk"],
        bundle["constraint_ledger"],
    )
    context, receipt = result["context"], result["receipt"]
    manifest = build_brain_context_v2_manifest(context, receipt)
    assert validate_brain_context_v2_manifest(index, context, receipt, manifest) == []

    attacked = deepcopy(context)
    attacked["concepts"][0]["semantic"]["definition"] = "tampered"
    attacked["revision"] = _hash(
        {key: value for key, value in attacked.items() if key != "revision"}
    )
    assert validate_brain_semantic_context_v2(index, attacked) == []
    assert validate_brain_context_v2_manifest(index, attacked, receipt, manifest)


def test_brain_context_v2_trusted_cas_rejects_fully_rehashed_bundle() -> None:
    bundle = _bundle(terminal_absent=True)
    index = _build(bundle)["index"]
    result = build_brain_semantic_context_v2(
        index,
        bundle["concepts"],
        bundle["crosswalk"],
        bundle["constraint_ledger"],
    )
    original_authority = result["manifest"]["manifest_sha256"]
    attacked_context = deepcopy(result["context"])
    attacked_context["concepts"][0]["semantic"]["definition"] = "tampered"
    attacked_context["revision"] = _hash(
        {key: value for key, value in attacked_context.items() if key != "revision"}
    )
    attacked_receipt = deepcopy(result["receipt"])
    attacked_receipt["context_sha256"] = _hash(attacked_context)
    attacked_receipt["context_revision"] = attacked_context["revision"]
    attacked_receipt["receipt_sha256"] = _hash(
        {key: value for key, value in attacked_receipt.items() if key != "receipt_sha256"}
    )
    attacked_manifest = build_brain_context_v2_manifest(attacked_context, attacked_receipt)
    assert validate_brain_context_v2_manifest(
        index,
        attacked_context,
        attacked_receipt,
        attacked_manifest,
        expected_manifest_sha256=original_authority,
    )
