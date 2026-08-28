from __future__ import annotations

from copy import deepcopy

import pytest

from metis_model1.video_catalog_projection import PROJECTION_CONTRACT
from metis_model1.video_local_census import (
    LocalCensusError,
    build_local_census,
    validate_local_census_receipt,
)

REVISION = "sha256:" + "1" * 64


def _semantic(state: str, line: int) -> dict:
    result = {"state": state, "at": {"file": "catalogs/video.metis", "line": line}}
    if state != "unannotated":
        result["means"] = {
            "text": f"semantic text at {line}",
            "at": {"file": "catalogs/video.metis", "line": line},
        }
    return result


def projection() -> dict:
    return {
        "schema": 2,
        "projection_contract": PROJECTION_CONTRACT,
        "tenant": "demo",
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
                    },
                    {
                        "name": "title",
                        "type": "keyword",
                        "modifiers": [],
                        "semantic": _semantic("unannotated", 8),
                        "domain": {"kind": "open"},
                    },
                    {
                        "name": "metadata",
                        "type": "object",
                        "modifiers": [],
                        "semantic": _semantic("draft", 10),
                        "domain": {"kind": "none"},
                        "fields": [
                            {
                                "name": "country",
                                "type": "keyword",
                                "modifiers": [],
                                "semantic": _semantic("draft", 11),
                                "domain": {
                                    "kind": "enum",
                                    "size": 1,
                                    "nature": "reflected",
                                    "values": [
                                        {
                                            "literal": "Italy",
                                            "semantic": _semantic("reviewed", 12),
                                        }
                                    ],
                                },
                            }
                        ],
                    },
                ],
            }
        ],
    }


def test_census_walks_catalog_fields_values_and_nested_fields() -> None:
    result = build_local_census(projection(), semantic_source_revision=REVISION)
    roster = result["roster"]
    assert len(roster) == 8
    assert [entry["node_kind"] for entry in roster] == [
        "catalog",
        "field",
        "value",
        "value",
        "field",
        "field",
        "field",
        "value",
    ]
    assert roster[1]["source_locator"] == "catalogs/video.metis:4"
    assert roster[1]["locator"].startswith("sha256:")
    assert roster[2]["literal"] == "Black and white"
    assert roster[-1]["field"] == "metadata.country"
    receipt = result["receipt"]
    assert receipt["counts"] == {
        "items_in": 8,
        "items_out": 8,
        "items_distinct": 8,
        "items_gaps": 0,
    }
    assert validate_local_census_receipt(receipt) == []
    assert "literal" not in str(receipt)
    assert "means" not in str(receipt)
    assert "aka" not in str(receipt)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda p: p["catalogs"].append(deepcopy(p["catalogs"][0])), "duplicate catalog"),
        (
            lambda p: p["catalogs"][0]["fields"].append(deepcopy(p["catalogs"][0]["fields"][0])),
            "duplicate field",
        ),
        (lambda p: p["catalogs"][0]["fields"][0]["domain"].update(size=3), "size"),
        (lambda p: p["catalogs"][0]["fields"][1]["domain"].update(size=1), "open"),
        (
            lambda p: p["catalogs"][0]["fields"][0]["domain"]["values"][1].update(
                literal="Black and white"
            ),
            "duplicate value",
        ),
    ],
)
def test_census_rejects_incoherent_projection(mutator, message: str) -> None:
    candidate = deepcopy(projection())
    mutator(candidate)
    with pytest.raises(LocalCensusError, match=message):
        build_local_census(candidate, semantic_source_revision=REVISION)


def test_census_rejects_missing_line_state_conflict_and_wrong_schema() -> None:
    candidate = deepcopy(projection())
    del candidate["catalogs"][0]["fields"][0]["semantic"]["at"]["line"]
    with pytest.raises(LocalCensusError, match="line"):
        build_local_census(candidate, semantic_source_revision=REVISION)

    candidate = deepcopy(projection())
    candidate["catalogs"][0]["fields"][0]["semantic"]["state"] = "invalid"
    with pytest.raises(LocalCensusError, match="invalid semantic state"):
        build_local_census(candidate, semantic_source_revision=REVISION)

    candidate = deepcopy(projection())
    candidate["schema"] = 1
    with pytest.raises(LocalCensusError, match="schema"):
        build_local_census(candidate, semantic_source_revision=REVISION)


def test_census_binds_tenant_and_catalog_scope_to_the_projection() -> None:
    scoped = build_local_census(
        projection(),
        semantic_source_revision=REVISION,
        tenant_ref="demo",
        catalog_ref="video",
    )
    assert scoped["receipt"]["tenant_ref"] == "demo"
    assert scoped["receipt"]["catalog_ref"] == "video"

    with pytest.raises(LocalCensusError, match="tenant_ref differs"):
        build_local_census(
            projection(),
            semantic_source_revision=REVISION,
            tenant_ref="other",
        )
    with pytest.raises(LocalCensusError, match="exactly one catalog"):
        build_local_census(
            projection(),
            semantic_source_revision=REVISION,
            catalog_ref="people",
        )


def test_census_receipt_self_hash_and_revision_are_checked() -> None:
    receipt = build_local_census(projection(), semantic_source_revision=REVISION)["receipt"]
    attacked = deepcopy(receipt)
    attacked["counts"]["items_gaps"] = 1
    assert validate_local_census_receipt(attacked)
    attacked = deepcopy(receipt)
    attacked["literal"] = "forbidden"
    assert validate_local_census_receipt(attacked)
    attacked = deepcopy(receipt)
    attacked["values_redacted"] = False
    assert validate_local_census_receipt(attacked)
    attacked = deepcopy(receipt)
    attacked["content"] = "synthetic-unapproved-content"
    assert validate_local_census_receipt(attacked)


def test_census_accepts_validated_schema2_semantic_locations_and_posix_paths() -> None:
    candidate = {
        "schema": 2,
        "projection_contract": PROJECTION_CONTRACT,
        "tenant": "public-synthetic",
        "thresholds": {"inline-max": 12, "enum-max": 300},
        "catalogs": [
            {
                "name": "public-synthetic.video",
                "driver": "opensearch",
                "file": "catalogs/video.metis",
                "fields": [
                    {
                        "name": "genre",
                        "type": "keyword",
                        "modifiers": [],
                        "domain": {"kind": "enum", "size": 0, "nature": "editorial", "values": []},
                        "semantic": {
                            "state": "reviewed",
                            "at": {"file": "catalogs/video.metis", "line": 11},
                        },
                    },
                    {
                        "name": "metadata",
                        "type": "object",
                        "modifiers": [],
                        "domain": {"kind": "none"},
                        "fields": [
                            {
                                "name": "language",
                                "type": "keyword",
                                "modifiers": [],
                                "domain": {"kind": "open"},
                                "semantic": {
                                    "state": "draft",
                                    "at": {"file": "catalogs/video.metis", "line": 21},
                                },
                            }
                        ],
                        "semantic": {
                            "state": "unannotated",
                            "at": {"file": "catalogs/video.metis", "line": 20},
                        },
                    },
                ],
                "semantic": {
                    "state": "reviewed",
                    "at": {"file": "catalogs/video.metis", "line": 2},
                },
            }
        ],
    }
    result = build_local_census(candidate, semantic_source_revision=REVISION)
    assert [entry["source_locator"] for entry in result["roster"]] == [
        "catalogs/video.metis:2",
        "catalogs/video.metis:11",
        "catalogs/video.metis:20",
        "catalogs/video.metis:21",
    ]
    assert result["roster"][-1]["field"] == "metadata.language"
    assert result["roster"][1]["domain"] == {
        "kind": "enum",
        "size": 0,
        "nature": "editorial",
    }


def test_census_rejects_schema2_conflicting_semantic_locator() -> None:
    candidate = {
        "schema": 2,
        "projection_contract": PROJECTION_CONTRACT,
        "tenant": "public-synthetic",
        "thresholds": {"inline-max": 12, "enum-max": 300},
        "catalogs": [
            {
                "name": "video",
                "driver": "opensearch",
                "file": "catalogs/video.metis",
                "line": 2,
                "fields": [],
                "semantic": {
                    "state": "reviewed",
                    "at": {"file": "catalogs/video.metis", "line": 3},
                },
            }
        ],
    }
    with pytest.raises(LocalCensusError, match="source line"):
        build_local_census(candidate, semantic_source_revision=REVISION)
