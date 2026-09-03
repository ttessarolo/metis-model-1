from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from metis_model1.catalog_semantic_projection import (
    PROJECTION_CONTRACT,
    CatalogSemanticProjectionError,
    build_catalog_semantic_projection,
    validate_catalog_semantic_projection_binding,
    validate_catalog_semantic_projection_receipt,
)
from metis_model1.provenance import canonical_json_hash
from metis_model1.video_catalog_projection import (
    build_catalog_semantic_projection as join,
)
from metis_model1.video_catalog_projection import (
    validate_catalog_projection_receipt,
)
from metis_model1.video_semantic_index import build_semantic_index, resolve_grounding

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def _semantic(line: int, text: str) -> dict:
    return {
        "state": "reviewed",
        "at": {"file": "catalogs/canonical.metis", "line": line},
        "means": {
            "text": text,
            "at": {"file": "catalogs/canonical.metis", "line": line + 1},
        },
    }


def _describe(*, execution: bool = False, finite_marker: bool = False) -> dict:
    name = "execution.video_pg" if execution else "canonical.video"
    file_name = "catalogs/video_pg.metis" if execution else "catalogs/video.metis"
    fields = [
        {
            "name": "genre",
            "type": "keyword",
            "modifiers": ["multi"] if execution else [],
            "domain": ({"kind": "enum", "size": 2} if finite_marker else {"kind": "none"}),
            "semantic": {
                **_semantic(10, "generi editoriali del contenuto"),
                "at": {"file": file_name, "line": 10},
                "means": {
                    "text": "generi editoriali del contenuto",
                    "at": {"file": file_name, "line": 11},
                },
            },
        },
        {
            "name": "title",
            "type": "keyword",
            "modifiers": [],
            "domain": {"kind": "open"},
            "semantic": {
                **_semantic(20, "titolo leggibile dell'opera"),
                "at": {"file": file_name, "line": 20},
                "means": {
                    "text": "titolo leggibile dell'opera",
                    "at": {"file": file_name, "line": 21},
                },
            },
        },
    ]
    if not execution:
        fields.append(
            {
                "name": "source_only",
                "type": "keyword",
                "modifiers": [],
                "domain": {"kind": "none"},
                "semantic": _semantic(25, "campo canonico non materializzato nel mirror"),
            }
        )
    return {
        "schema": 2,
        "tenant": "synthetic-tenant",
        "thresholds": {"inline-max": 12, "enum-max": 300},
        "catalogs": [
            {
                "name": name,
                "driver": "opensearch",
                "index": "video_content",
                "file": file_name,
                "fields": fields,
                "semantic": {
                    "state": "reviewed",
                    "at": {"file": file_name, "line": 2},
                    "means": {
                        "text": "catalogo dei contenuti video",
                        "at": {"file": file_name, "line": 3},
                    },
                },
            }
        ],
    }


def _source(*, draft_value: bool = False) -> dict:
    describe = _describe()
    fields = describe["catalogs"][0]["fields"]
    fields[0]["domain"] = {"kind": "enum", "size": 2, "nature": "editorial"}
    values = {
        "schema": 2,
        "tenant": "synthetic-tenant",
        "catalog": "canonical.video",
        "field": "genre",
        "kind": "enum",
        "size": 2,
        "nature": "editorial",
        "values": ["Drama", "Comedy"],
        "semantic": {
            "field": fields[0]["semantic"],
            "values": [
                {
                    "literal": literal,
                    **_semantic(30 + index, f"significato di {literal}"),
                }
                for index, literal in enumerate(["Drama", "Comedy"])
            ],
        },
    }
    if draft_value:
        values["semantic"]["values"][1]["state"] = "draft"
    return join(describe, [values], catalog_ref="video")["projection"]


def _result(*, finite_marker: bool = False, dispositions: dict[str, str] | None = None):
    return build_catalog_semantic_projection(
        _source(),
        _describe(execution=True, finite_marker=finite_marker),
        semantic_ref=HASH_A,
        execution_ref=HASH_B,
        modifier_allowlist={"genre": {"source": [], "execution": ["multi"]}},
        domain_dispositions=dispositions,
    )


def _materialized_execution_inputs() -> tuple[dict, dict, list[dict]]:
    """One finite inline mirror and its complete progressive values proof."""

    source = _source()
    source_genre = source["catalogs"][0]["fields"][0]
    source_genre["domain"]["kind"] = "inline"
    source_genre["domain"].pop("nature")
    execution = _describe(execution=True)
    execution_genre = execution["catalogs"][0]["fields"][0]
    execution_genre["domain"] = {
        "kind": "inline",
        "size": 2,
        "values": ["Drama", "Comedy"],
    }
    values = {
        "schema": 2,
        "tenant": "synthetic-tenant",
        "catalog": "execution.video_pg",
        "field": "genre",
        "kind": "inline",
        "size": 2,
        "values": ["Drama", "Comedy"],
        "semantic": {
            "field": deepcopy(execution_genre["semantic"]),
            "values": [
                {"literal": item["literal"], **deepcopy(item["semantic"])}
                for item in source_genre["domain"]["values"]
            ],
        },
    }
    return source, execution, [values]


def test_projection_uses_execution_identity_and_source_value_items() -> None:
    result = _result(dispositions={"genre": "execution schema omits the shared value-set"})
    projection = result["projection"]
    assert projection["projection_contract"] == PROJECTION_CONTRACT
    assert projection["catalogs"][0]["name"] == "execution.video_pg"
    genre = projection["catalogs"][0]["fields"][0]
    assert genre["modifiers"] == ["multi"]
    assert [item["literal"] for item in genre["domain"]["values"]] == ["Drama", "Comedy"]
    assert genre["semantic"]["means"]["text"] == "generi editoriali del contenuto"
    assert validate_catalog_projection_receipt(result["receipt"]) == []
    receipt = result["execution_receipt"]
    assert receipt["counts"] == {
        "catalogs_in": 1,
        "catalogs_out": 1,
        "source_fields_available": 3,
        "fields_in": 2,
        "fields_out": 2,
        "fields_distinct": 2,
        "values_in": 2,
        "values_out": 2,
        "values_reviewed": 2,
        "values_draft": 0,
        "modifier_exceptions": 1,
        "domain_dispositions": 1,
        "gaps": 0,
    }
    assert validate_catalog_semantic_projection_receipt(receipt) == []
    assert (
        validate_catalog_semantic_projection_binding(
            result,
            _source(),
            _describe(execution=True),
            semantic_ref=HASH_A,
            execution_ref=HASH_B,
            modifier_allowlist={"genre": {"source": [], "execution": ["multi"]}},
            domain_dispositions={"genre": "execution schema omits the shared value-set"},
        )
        == []
    )
    assert "Drama" not in str(receipt)
    assert "significato" not in str(receipt)

    index = build_semantic_index(
        projection,
        semantic_source_revision=HASH_A,
        grammar_revision=HASH_A,
        toolchain_revision=HASH_B,
        tenant_snapshot="synthetic-snapshot",
    )["index"]
    grounding = resolve_grounding(index, "Drama", catalog="execution.video_pg")
    assert grounding["status"] == "resolved"
    assert grounding["selections"][0]["catalog"] == "execution.video_pg"
    assert grounding["selections"][0]["field"] == "genre"
    assert grounding["selections"][0]["literal"] == "Drama"


def test_finite_execution_marker_needs_no_disposition() -> None:
    result = _result(finite_marker=True)
    values = result["projection"]["catalogs"][0]["fields"][0]["domain"]["values"]
    assert values[0]["literal"] == "Drama"


def test_draft_source_value_is_carried_but_counted_for_quarantine() -> None:
    result = build_catalog_semantic_projection(
        _source(draft_value=True),
        _describe(execution=True),
        semantic_ref=HASH_A,
        execution_ref=HASH_B,
        modifier_allowlist={"genre": {"source": [], "execution": ["multi"]}},
        domain_dispositions={"genre": "execution schema omits the shared value-set"},
    )
    assert result["execution_receipt"]["counts"]["values_reviewed"] == 1
    assert result["execution_receipt"]["counts"]["values_draft"] == 1

    index = build_semantic_index(
        result["projection"],
        semantic_source_revision=HASH_A,
        grammar_revision=HASH_A,
        toolchain_revision=HASH_B,
        tenant_snapshot="synthetic-snapshot",
    )["index"]
    grounding = resolve_grounding(index, "Comedy", catalog="execution.video_pg")
    assert grounding["status"] == "unsupported"
    assert grounding["selections"] == []


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("tenant", "tenant differs"),
        ("extra", "field roster differs"),
        ("type", "field type differs"),
        ("semantic", "must be reviewed"),
        ("domain", "without an explicit disposition"),
        ("modifier", "field modifiers differ"),
        ("values", "schema-2"),
    ],
)
def test_projection_is_fail_closed(mutation: str, message: str) -> None:
    source = _source()
    execution = _describe(execution=True)
    allowlist = {"genre": {"source": [], "execution": ["multi"]}}
    dispositions = {"genre": "explicitly omitted from execution skeleton"}
    if mutation == "tenant":
        execution["tenant"] = "other"
    elif mutation == "extra":
        execution["catalogs"][0]["fields"].append(
            {
                "name": "not_in_source",
                "type": "keyword",
                "modifiers": [],
                "domain": {"kind": "none"},
                "semantic": {
                    **_semantic(40, "campo estraneo"),
                    "at": {"file": "catalogs/video_pg.metis", "line": 40},
                    "means": {
                        "text": "campo estraneo",
                        "at": {"file": "catalogs/video_pg.metis", "line": 41},
                    },
                },
            }
        )
    elif mutation == "type":
        execution["catalogs"][0]["fields"][1]["type"] = "text"
    elif mutation == "semantic":
        execution["catalogs"][0]["fields"][1]["semantic"]["state"] = "draft"
    elif mutation == "domain":
        dispositions = None
    elif mutation == "modifier":
        allowlist = None
    elif mutation == "values":
        execution["catalogs"][0]["fields"][0]["domain"] = {
            "kind": "enum",
            "size": 2,
            "nature": "editorial",
            "values": ["Drama", "Comedy"],
        }
    with pytest.raises(CatalogSemanticProjectionError, match=message):
        build_catalog_semantic_projection(
            source,
            execution,
            semantic_ref=HASH_A,
            execution_ref=HASH_B,
            modifier_allowlist=allowlist,
            domain_dispositions=dispositions,
        )


def test_materialized_inline_execution_domain_needs_exact_provenance() -> None:
    source, execution, values = _materialized_execution_inputs()
    result = build_catalog_semantic_projection(
        source,
        execution,
        semantic_ref=HASH_A,
        execution_ref=HASH_B,
        modifier_allowlist={"genre": {"source": [], "execution": ["multi"]}},
        execution_values_projections=values,
    )

    receipt = result["execution_receipt"]
    assert receipt["receipt_id"].endswith("-v2")
    assert receipt["counts"]["execution_values_responses"] == 1
    assert receipt["counts"]["materialized_finite_fields"] == 1
    assert validate_catalog_semantic_projection_receipt(receipt) == []
    assert (
        validate_catalog_semantic_projection_binding(
            result,
            source,
            execution,
            semantic_ref=HASH_A,
            execution_ref=HASH_B,
            modifier_allowlist={"genre": {"source": [], "execution": ["multi"]}},
            execution_values_projections=values,
        )
        == []
    )
    assert validate_catalog_semantic_projection_binding(
        result,
        source,
        execution,
        semantic_ref=HASH_A,
        execution_ref=HASH_B,
        modifier_allowlist={"genre": {"source": [], "execution": ["multi"]}},
    ) == ["execution values projections are required to bind a v2 receipt"]


@pytest.mark.parametrize(
    ("target", "mutation", "message"),
    [
        ("describe", "reorder", "materialized execution literals differ"),
        ("describe", "missing", "finite domain kind or size differs"),
        ("describe", "extra", "finite domain kind or size differs"),
        ("values", "reorder", "execution values literals differ"),
        ("values", "missing", "execution values domain differs"),
        ("values", "extra", "execution values domain differs"),
        ("values", "semantic", "ValueItem semantic provenance differs"),
    ],
)
def test_materialized_execution_domain_rejects_nonidentical_roster(
    target: str, mutation: str, message: str
) -> None:
    source, execution, values = _materialized_execution_inputs()
    if target == "describe":
        roster = execution["catalogs"][0]["fields"][0]["domain"]["values"]
    else:
        roster = values[0]["values"]
    if mutation == "reorder":
        roster[:] = list(reversed(roster))
        if target == "values":
            values[0]["semantic"]["values"][:] = list(reversed(values[0]["semantic"]["values"]))
    elif mutation == "missing":
        del roster[-1]
        if target == "values":
            del values[0]["semantic"]["values"][-1]
            values[0]["size"] = len(roster)
        else:
            execution["catalogs"][0]["fields"][0]["domain"]["size"] = len(roster)
    elif mutation == "extra":
        roster.append("Other")
        if target == "values":
            values[0]["semantic"]["values"].append(
                {"literal": "Other", **_semantic(99, "valore estraneo")}
            )
            values[0]["size"] = len(roster)
        else:
            execution["catalogs"][0]["fields"][0]["domain"]["size"] = len(roster)
    else:
        values[0]["semantic"]["values"][0]["means"]["text"] = "tampered"
    with pytest.raises(CatalogSemanticProjectionError, match=message):
        build_catalog_semantic_projection(
            source,
            execution,
            semantic_ref=HASH_A,
            execution_ref=HASH_B,
            modifier_allowlist={"genre": {"source": [], "execution": ["multi"]}},
            execution_values_projections=values,
        )


def test_receipt_detects_tamper_and_redacts_all_payload_text() -> None:
    result = _result(dispositions={"genre": "explicitly omitted from execution skeleton"})
    receipt = result["execution_receipt"]
    tampered = deepcopy(receipt)
    tampered["counts"]["gaps"] = 1
    assert validate_catalog_semantic_projection_receipt(tampered)
    assert not any(key in receipt for key in {"literal", "text", "means", "aka", "values"})


def test_current_video_pg_v2_receipt_is_redacted_and_internally_valid() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads(
        (root / "manifests/catalog-semantic-execution-play-demo-video-pg-v2.json").read_text(
            encoding="utf-8"
        )
    )
    receipt = manifest["execution_receipt"]
    assert manifest["mapping"]["finite_to_none_fields"] == []
    assert receipt["counts"]["execution_values_responses"] == 18
    assert receipt["counts"]["materialized_finite_fields"] == 9
    assert validate_catalog_semantic_projection_receipt(receipt) == []
    assert "Drama" not in json.dumps(manifest, ensure_ascii=False)


def test_rehashed_receipt_tamper_fails_external_binding() -> None:
    dispositions = {"genre": "explicitly omitted from execution skeleton"}
    result = _result(dispositions=dispositions)
    attacked = deepcopy(result)
    attacked["execution_receipt"]["source_projection_sha256"] = HASH_B
    body = {
        key: value
        for key, value in attacked["execution_receipt"].items()
        if key != "receipt_sha256"
    }
    attacked["execution_receipt"]["receipt_sha256"] = "sha256:" + canonical_json_hash(body)
    assert validate_catalog_semantic_projection_receipt(attacked["execution_receipt"]) == []
    assert validate_catalog_semantic_projection_binding(
        attacked,
        _source(),
        _describe(execution=True),
        semantic_ref=HASH_A,
        execution_ref=HASH_B,
        modifier_allowlist={"genre": {"source": [], "execution": ["multi"]}},
        domain_dispositions=dispositions,
    ) == ["execution receipt source_projection_sha256 differs from binding authority"]


def test_nested_execution_field_not_in_source_is_rejected() -> None:
    source = _source()
    source["catalogs"][0]["fields"].append(
        {
            "name": "history",
            "type": "object",
            "modifiers": ["multi"],
            "domain": {"kind": "none"},
            "semantic": _semantic(50, "cronologia strutturata"),
            "fields": [
                {
                    "name": "id",
                    "type": "keyword",
                    "modifiers": [],
                    "domain": {"kind": "none"},
                    "semantic": _semantic(51, "identificatore nella cronologia"),
                }
            ],
        }
    )
    execution = _describe(execution=True)
    execution["catalogs"][0]["fields"].append(
        {
            "name": "history",
            "type": "object",
            "modifiers": ["multi"],
            "domain": {"kind": "none"},
            "semantic": _semantic(50, "cronologia strutturata"),
            "fields": [
                {
                    "name": "other",
                    "type": "keyword",
                    "modifiers": [],
                    "domain": {"kind": "none"},
                    "semantic": _semantic(51, "campo estraneo nella cronologia"),
                }
            ],
        }
    )
    with pytest.raises(CatalogSemanticProjectionError, match="history.other"):
        build_catalog_semantic_projection(
            source,
            execution,
            semantic_ref=HASH_A,
            execution_ref=HASH_B,
            modifier_allowlist={"genre": {"source": [], "execution": ["multi"]}},
            domain_dispositions={"genre": "execution skeleton omits the shared value-set"},
        )
