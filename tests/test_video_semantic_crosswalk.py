from __future__ import annotations

from copy import deepcopy

import pytest

from metis_model1.video_catalog_projection import PROJECTION_CONTRACT
from metis_model1.video_local_census import build_local_census
from metis_model1.video_semantic_crosswalk import (
    CrosswalkError,
    build_preliminary_crosswalk,
    validate_crosswalk_receipt,
)
from metis_model1.video_semantics_contracts import semantic_concept_id

REVISION = "sha256:" + "1" * 64


def _semantic(state: str, line: int) -> dict:
    value = {"state": state, "at": {"file": "catalogs/video.metis", "line": line}}
    if state != "unannotated":
        value["means"] = {
            "text": f"semantic text at {line}",
            "at": {"file": "catalogs/video.metis", "line": line},
        }
    return value


def _concept(label: str, locator: str) -> dict:
    concept = {
        "schema_version": 1,
        "concept_id": "",
        "editorial_source_ref": "editorial-source-a",
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
        "review_state": "draft",
    }
    concept["concept_id"] = semantic_concept_id(concept)
    return concept


def _projection() -> dict:
    return {
        "schema": 2,
        "projection_contract": PROJECTION_CONTRACT,
        "tenant": "demo",
        "thresholds": {"inline-max": 12, "enum-max": 300},
        "catalogs": [
            {
                "name": "video",
                "driver": "opensearch",
                "file": "catalogs/video.metis",
                "semantic": _semantic("reviewed", 1),
                "fields": [
                    {
                        "name": "color",
                        "type": "keyword",
                        "modifiers": [],
                        "semantic": _semantic("reviewed", 4),
                        "domain": {
                            "kind": "enum",
                            "size": 2,
                            "nature": "editorial",
                            "values": [
                                {
                                    "literal": "Black and white",
                                    "semantic": _semantic("reviewed", 5),
                                },
                                {"literal": "Color", "semantic": _semantic("reviewed", 6)},
                            ],
                        },
                    }
                ],
            }
        ],
    }


def _census() -> dict:
    return build_local_census(_projection(), semantic_source_revision=REVISION)


def test_crosswalk_uses_only_explicit_membership_and_is_schema_valid() -> None:
    concept = _concept("monochrome", "source-a:1")
    decision = {
        "concept_id": concept["concept_id"],
        "catalog": "video",
        "field": "color",
        "literal": "Black and white",
        "relation": "exact",
        "field_status": "declared-observed",
        "reason": "The explicit catalog value matches the reviewed concept.",
        "evidence_refs": ["source-a:1"],
        "validated_usages": ["usage-a:1"],
    }
    result = build_preliminary_crosswalk(
        [concept], _census(), [decision], semantic_source_revision=REVISION
    )
    row = result["crosswalk"]["rows"][0]
    expected = next(
        item["locator"] for item in _census()["roster"] if item.get("literal") == "Black and white"
    )
    assert row["canonical_locator"] == expected
    assert row["canonical_locator"].startswith("sha256:")
    assert row["literal"] == "Black and white"
    assert row["decision_state"] == "provisional"
    assert result["receipt"]["counts"] == {
        "items_in": 1,
        "items_out": 1,
        "items_distinct": 1,
        "items_gaps": 0,
    }
    assert validate_crosswalk_receipt(result["receipt"]) == []


def test_unresolved_decision_is_explicit_gap_without_fake_target() -> None:
    concept = _concept("unknown", "source-a:2")
    decision = {
        "concept_id": concept["concept_id"],
        "catalog": None,
        "field": None,
        "literal": None,
        "canonical_locator": "unresolved:concept-1",
        "relation": "unresolved",
        "field_status": "unresolved",
        "reason": "No unique technical target is evidenced.",
        "evidence_refs": ["source-a:2"],
        "critical": True,
    }
    result = build_preliminary_crosswalk(
        [concept], _census(), [decision], semantic_source_revision=REVISION
    )
    assert result["receipt"]["counts"]["items_gaps"] == 1
    assert result["receipt"]["critical_unresolved"] == 1
    assert result["crosswalk"]["rows"][0]["decision_required"] is True


def test_omitted_concept_remains_an_explicit_gap_in_the_receipt() -> None:
    mapped = _concept("mapped", "source-a:1")
    omitted = _concept("omitted", "source-a:2")
    decision = {
        "concept_id": mapped["concept_id"],
        "catalog": "video",
        "field": "color",
        "literal": "Color",
        "relation": "exact",
        "field_status": "declared-observed",
        "reason": "explicit",
        "evidence_refs": ["source-a:1"],
    }
    result = build_preliminary_crosswalk(
        [mapped, omitted], _census(), [decision], semantic_source_revision=REVISION
    )
    assert result["receipt"]["counts"] == {
        "items_in": 2,
        "items_out": 1,
        "items_distinct": 1,
        "items_gaps": 1,
    }
    assert validate_crosswalk_receipt(result["receipt"]) == []


def test_locator_only_target_preserves_the_census_literal() -> None:
    concept = _concept("monochrome", "source-a:1")
    target = next(item for item in _census()["roster"] if item.get("literal") == "Color")
    result = build_preliminary_crosswalk(
        [concept],
        _census(),
        [
            {
                "concept_id": concept["concept_id"],
                "canonical_locator": target["locator"],
                "relation": "exact",
                "field_status": "declared-observed",
                "reason": "explicit locator",
                "evidence_refs": ["source-a:1"],
            }
        ],
        semantic_source_revision=REVISION,
    )
    assert result["crosswalk"]["rows"][0]["literal"] == "Color"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda d: d.update(literal="Invented"),
        lambda d: d.update(field="missing"),
        lambda d: d.update(relation="bogus"),
        lambda d: d.update(field_status="bogus"),
        lambda d: d.update(evidence_refs=[]),
    ],
)
def test_crosswalk_rejects_dangling_or_invalid_decisions(mutator) -> None:
    concept = _concept("monochrome", "source-a:1")
    decision = {
        "concept_id": concept["concept_id"],
        "catalog": "video",
        "field": "color",
        "literal": "Black and white",
        "relation": "exact",
        "field_status": "declared-observed",
        "reason": "explicit",
        "evidence_refs": ["source-a:1"],
    }
    mutator(decision)
    with pytest.raises(CrosswalkError):
        build_preliminary_crosswalk(
            [concept], _census(), [decision], semantic_source_revision=REVISION
        )


def test_crosswalk_rejects_duplicate_concepts_and_duplicate_targets() -> None:
    first = _concept("first", "source-a:1")
    second = _concept("second", "source-a:2")
    base = {
        "catalog": "video",
        "field": "color",
        "literal": "Color",
        "relation": "exact",
        "field_status": "declared-observed",
        "reason": "explicit",
        "evidence_refs": ["source-a:1"],
    }
    with pytest.raises(CrosswalkError, match="concept decision"):
        build_preliminary_crosswalk(
            [first],
            _census(),
            [
                {**base, "concept_id": first["concept_id"]},
                {**base, "concept_id": first["concept_id"]},
            ],
            semantic_source_revision=REVISION,
        )
    with pytest.raises(CrosswalkError, match="concept-target"):
        build_preliminary_crosswalk(
            [first, second],
            _census(),
            [
                {**base, "concept_id": first["concept_id"]},
                {**base, "concept_id": second["concept_id"]},
            ],
            semantic_source_revision=REVISION,
        )


def test_multiple_concepts_may_share_one_target_only_as_explicit_merge() -> None:
    first = _concept("first", "source-a:1")
    second = _concept("second", "source-a:2")
    base = {
        "catalog": "video",
        "field": "color",
        "literal": "Color",
        "relation": "merged",
        "field_status": "declared-observed",
        "reason": "Two editorial distinctions are intentionally merged in one technical value.",
        "evidence_refs": ["source-a:1"],
    }
    result = build_preliminary_crosswalk(
        [first, second],
        _census(),
        [
            {**base, "concept_id": first["concept_id"]},
            {**base, "concept_id": second["concept_id"], "evidence_refs": ["source-a:2"]},
        ],
        semantic_source_revision=REVISION,
    )
    assert result["receipt"]["counts"] == {
        "items_in": 2,
        "items_out": 2,
        "items_distinct": 2,
        "items_gaps": 0,
    }


def test_crosswalk_receipt_self_hash_and_redaction_are_checked() -> None:
    concept = _concept("monochrome", "source-a:1")
    decision = {
        "concept_id": concept["concept_id"],
        "catalog": "video",
        "field": "color",
        "literal": "Color",
        "relation": "exact",
        "field_status": "declared-observed",
        "reason": "explicit",
        "evidence_refs": ["source-a:1"],
    }
    receipt = build_preliminary_crosswalk(
        [concept], _census(), [decision], semantic_source_revision=REVISION
    )["receipt"]
    attacked = deepcopy(receipt)
    attacked["literal"] = "forbidden"
    assert validate_crosswalk_receipt(attacked)
    attacked = deepcopy(receipt)
    attacked["counts"]["items_gaps"] = 2
    assert validate_crosswalk_receipt(attacked)
    attacked = deepcopy(receipt)
    attacked["values_redacted"] = False
    assert validate_crosswalk_receipt(attacked)
    attacked = deepcopy(receipt)
    attacked["content"] = "synthetic-unapproved-content"
    assert validate_crosswalk_receipt(attacked)
