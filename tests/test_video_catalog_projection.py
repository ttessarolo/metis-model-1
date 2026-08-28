from __future__ import annotations

from copy import deepcopy

import pytest

from metis_model1.video_catalog_projection import (
    PROJECTION_CONTRACT,
    VideoCatalogProjectionError,
    build_catalog_semantic_projection,
    validate_catalog_projection_receipt,
)
from metis_model1.video_local_census import build_local_census
from metis_model1.video_semantic_index import build_semantic_index

REVISION = "sha256:" + "1" * 64


def _semantic(state: str, line: int, *, text: str | None = None) -> dict:
    value = {"state": state, "at": {"file": "catalogs/video.metis", "line": line}}
    if text is not None:
        value["means"] = {
            "text": text,
            "at": {"file": "catalogs/video.metis", "line": line + 1},
        }
    return value


def _describe() -> dict:
    return {
        "schema": 2,
        "tenant": "public-synthetic",
        "thresholds": {"inline-max": 12, "enum-max": 300},
        "catalogs": [
            {
                "name": "public.video",
                "driver": "opensearch",
                "index": "video_content",
                "file": "catalogs/video.metis",
                "fields": [
                    {
                        "name": "kind",
                        "type": "keyword",
                        "modifiers": [],
                        "domain": {"kind": "inline", "size": 2, "values": ["Film", "Serie"]},
                        "semantic": _semantic("reviewed", 10, text="tipo di contenuto"),
                    },
                    {
                        "name": "genre",
                        "type": "keyword",
                        "modifiers": [],
                        "domain": {"kind": "enum", "size": 2, "nature": "editorial"},
                        "semantic": _semantic("reviewed", 20, text="genere editoriale"),
                    },
                    {
                        "name": "title",
                        "type": "keyword",
                        "modifiers": [],
                        "domain": {"kind": "open"},
                        "semantic": _semantic("unannotated", 30),
                    },
                ],
                "semantic": _semantic("reviewed", 2, text="contenuti video"),
            }
        ],
    }


def _values(field: str, values: list[str]) -> dict:
    described = next(item for item in _describe()["catalogs"][0]["fields"] if item["name"] == field)
    domain = described["domain"]
    result = {
        "schema": 2,
        "tenant": "public-synthetic",
        "catalog": "public.video",
        "field": field,
        "kind": domain["kind"],
        "size": domain["size"],
        "values": values,
        "semantic": {
            "field": described["semantic"],
            "values": [
                {
                    "literal": literal,
                    **_semantic(
                        "reviewed" if index == 0 else "unannotated",
                        40 + index,
                        text=f"significato {literal}" if index == 0 else None,
                    ),
                }
                for index, literal in enumerate(values)
            ],
        },
    }
    if "nature" in domain:
        result["nature"] = domain["nature"]
    return result


def _merged() -> dict:
    return build_catalog_semantic_projection(
        _describe(),
        [_values("kind", ["Film", "Serie"]), _values("genre", ["Drama", "Comedy"])],
        catalog_ref="video",
    )


def test_real_schema2_describe_and_values_are_joined_exactly() -> None:
    result = _merged()
    projection = result["projection"]
    assert projection["projection_contract"] == PROJECTION_CONTRACT
    fields = projection["catalogs"][0]["fields"]
    assert fields[0]["domain"]["values"][0] == {
        "literal": "Film",
        "semantic": _semantic("reviewed", 40, text="significato Film"),
    }
    assert [item["literal"] for item in fields[1]["domain"]["values"]] == [
        "Drama",
        "Comedy",
    ]
    assert fields[2]["domain"] == {"kind": "open"}
    assert result["receipt"]["counts"] == {
        "catalogs": 1,
        "fields": 3,
        "finite_fields_expected": 2,
        "values_responses": 2,
        "values": 4,
        "semantic_values": 4,
        "gaps": 0,
    }
    assert validate_catalog_projection_receipt(result["receipt"]) == []
    assert "Drama" not in str(result["receipt"])
    assert "significato" not in str(result["receipt"])


def test_joined_projection_is_the_only_census_and_index_input() -> None:
    projection = _merged()["projection"]
    census = build_local_census(projection, semantic_source_revision=REVISION)
    assert census["receipt"]["counts"] == {
        "items_in": 8,
        "items_out": 8,
        "items_distinct": 8,
        "items_gaps": 0,
    }
    index = build_semantic_index(
        projection,
        semantic_source_revision=REVISION,
        grammar_revision="sha256:" + "2" * 64,
        toolchain_revision="sha256:" + "3" * 64,
        tenant_snapshot="snapshot-001",
    )
    assert index["receipt"]["counts"] == {
        "entries_in": 8,
        "entries_out": 8,
        "entries_distinct": 8,
        "entries_gaps": 0,
        "catalogs": 1,
        "fields": 3,
        "values": 4,
    }

    raw_describe = _describe()
    with pytest.raises(ValueError, match="normalized"):
        build_local_census(raw_describe, semantic_source_revision=REVISION)
    with pytest.raises(ValueError, match="normalized"):
        build_semantic_index(
            raw_describe,
            semantic_source_revision=REVISION,
            grammar_revision="sha256:" + "2" * 64,
            toolchain_revision="sha256:" + "3" * 64,
            tenant_snapshot="snapshot-001",
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("missing", "has no values projection"),
        ("duplicate", "duplicate values projection"),
        ("tenant", "tenant differs"),
        ("field_semantic", "semantics differ"),
        ("domain", "domain differs"),
        ("inline", "inline values differ"),
    ],
)
def test_join_is_fail_closed(mutation: str, message: str) -> None:
    inline = _values("kind", ["Film", "Serie"])
    enum = _values("genre", ["Drama", "Comedy"])
    projections = [inline, enum]
    if mutation == "missing":
        projections.pop()
    elif mutation == "duplicate":
        projections.append(deepcopy(enum))
    elif mutation == "tenant":
        enum["tenant"] = "wrong"
    elif mutation == "field_semantic":
        enum["semantic"]["field"] = _semantic("draft", 20, text="changed")
    elif mutation == "domain":
        enum["nature"] = "reflected"
    else:
        inline["values"] = ["Serie", "Film"]
        inline["semantic"]["values"].reverse()
    with pytest.raises(VideoCatalogProjectionError, match=message):
        build_catalog_semantic_projection(_describe(), projections, catalog_ref="video")


def test_unsynchronized_nonempty_enum_is_not_misreported_as_complete() -> None:
    describe = _describe()
    describe["catalogs"][0]["fields"][1]["domain"].pop("nature")
    unresolved = _values("genre", ["Drama", "Comedy"])
    unresolved.pop("values")
    unresolved.pop("nature")
    unresolved["semantic"].pop("values")
    unresolved["note"] = "value-set non sincronizzato"
    with pytest.raises(VideoCatalogProjectionError, match="not materialized"):
        build_catalog_semantic_projection(
            describe, [_values("kind", ["Film", "Serie"]), unresolved], catalog_ref="video"
        )


def test_receipt_tamper_and_payload_injection_are_rejected() -> None:
    receipt = _merged()["receipt"]
    tampered = deepcopy(receipt)
    tampered["counts"]["gaps"] = 1
    assert validate_catalog_projection_receipt(tampered)
    leaked = deepcopy(receipt)
    leaked["literal"] = "Film"
    assert validate_catalog_projection_receipt(leaked)
    malformed_hash = deepcopy(receipt)
    malformed_hash["projection_sha256"] = "sha256:" + "A" * 64
    assert validate_catalog_projection_receipt(malformed_hash)
    missing_value_receipt = deepcopy(receipt)
    missing_value_receipt["values_projection_sha256"].pop()
    assert validate_catalog_projection_receipt(missing_value_receipt)
    unredacted = deepcopy(receipt)
    unredacted["payload_redacted"] = False
    assert validate_catalog_projection_receipt(unredacted)
    unknown = deepcopy(receipt)
    unknown["content"] = "synthetic-unapproved-content"
    assert validate_catalog_projection_receipt(unknown)
