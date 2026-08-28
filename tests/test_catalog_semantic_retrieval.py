from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from metis_model1.catalog_semantic_retrieval import (
    MAX_DEPTH,
    CatalogSemanticRetrievalError,
    adapt_catalog_semantic_response,
    validate_catalog_semantic_receipt,
)

AT = {"file": "catalogs/video.metis", "line": 2}
MEANS = {"text": "contenuti video", "at": {"file": "catalogs/video.metis", "line": 3}}


def _semantic(
    state: str = "reviewed", *, means: dict[str, Any] | None = MEANS, aka: list[str] | None = None
) -> dict[str, Any]:
    result: dict[str, Any] = {"state": state, "at": copy.deepcopy(AT)}
    if means is not None:
        result["means"] = copy.deepcopy(means)
    if aka is not None:
        result["aka"] = {"items": aka, "at": copy.deepcopy(AT)}
    return result


def _describe() -> dict[str, Any]:
    payload = {
        "schema": 2,
        "tenant": "public-synthetic",
        "thresholds": {"inline-max": 12, "enum-max": 300},
        "catalogs": [
            {
                "name": "public-synthetic.video",
                "driver": "opensearch",
                "index": "video_content",
                "file": "catalogs/video.metis",
                "fields": [
                    {
                        "name": "genre",
                        "type": "keyword",
                        "modifiers": [],
                        "domain": {"kind": "enum", "size": 2, "nature": "editorial"},
                        "semantic": _semantic("reviewed", aka=["genere"]),
                    },
                    {
                        "name": "title",
                        "type": "keyword",
                        "modifiers": ["multi"],
                        "domain": {"kind": "open"},
                        "semantic": _semantic("unannotated", means=None),
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
                                "domain": {"kind": "none"},
                                "semantic": _semantic("draft", means=MEANS),
                            }
                        ],
                        "semantic": _semantic("unannotated", means=None),
                    },
                ],
                "semantic": _semantic("reviewed", aka=["programmi"], means=MEANS),
            }
        ],
    }
    return payload


def _values(kind: str = "enum") -> dict[str, Any]:
    if kind == "open":
        return {
            "schema": 2,
            "tenant": "public-synthetic",
            "catalog": "public-synthetic.video",
            "field": "title",
            "kind": "open",
            "note": "dominio dell'indice live",
            "semantic": {"field": _semantic("reviewed", means=MEANS)},
        }
    if kind == "none":
        return {
            "schema": 2,
            "tenant": "public-synthetic",
            "catalog": "public-synthetic.video",
            "field": "unknown_metadata",
            "kind": "none",
            "note": "il campo non dichiara un dominio",
            "semantic": {"field": _semantic("unannotated", means=None)},
        }
    payload = {
        "schema": 2,
        "tenant": "public-synthetic",
        "catalog": "public-synthetic.video",
        "field": "genre",
        "kind": kind,
        "size": 2,
        "values": ["Film", "Serie"],
        "semantic": {
            "field": _semantic("reviewed", means=MEANS),
            "values": [
                {"literal": "Film", **_semantic("reviewed", means=MEANS)},
                {"literal": "Serie", **_semantic("draft", means=MEANS)},
            ],
        },
    }
    if kind == "enum":
        payload["nature"] = "editorial"
    return payload


def _raw(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode()


def _adapt(payload: dict[str, Any], operation: str = "describe"):
    requested_field = payload.get("field") if operation == "values" else None
    return adapt_catalog_semantic_response(
        operation,
        _raw(payload),
        catalog="video" if operation == "describe" else "video",
        field=requested_field,
    )


def _contains_key(value: Any, target: str) -> bool:
    if isinstance(value, dict):
        return target in value or any(_contains_key(item, target) for item in value.values())
    if isinstance(value, list):
        return any(_contains_key(item, target) for item in value)
    return False


def test_describe_returns_complete_schema2_projection_and_sanitized_receipt() -> None:
    result = _adapt(_describe())

    assert result.projection["schema"] == 2
    assert result.projection["catalogs"][0]["semantic"]["aka"]["items"] == ["programmi"]
    assert (
        result.projection["catalogs"][0]["fields"][2]["fields"][0]["semantic"]["state"] == "draft"
    )
    assert result.receipt["pin"] == {
        "commit": "0b41a25d4d5eeac88975e43e18e4bc3123d51667",
        "schema": 2,
    }
    assert not _contains_key(result.receipt, "text")
    assert not _contains_key(result.receipt, "literal")
    assert set(result.receipt) == {"query", "pin", "counts", "hashes", "receipt_sha256"}
    assert validate_catalog_semantic_receipt(result.receipt, query=result.receipt["query"]) == []


def test_values_semantic_field_and_values_are_aligned() -> None:
    result = _adapt(_values(), operation="values")
    assert result.projection["semantic"]["field"]["means"]["text"] == MEANS["text"]
    assert [item["literal"] for item in result.projection["semantic"]["values"]] == [
        "Film",
        "Serie",
    ]
    assert result.receipt["counts"]["semantic_values"] == 2
    assert result.receipt["counts"]["values"] == 2


@pytest.mark.parametrize("kind", ["open", "none"])
def test_open_and_none_never_materialize_values(kind: str) -> None:
    payload = _values(kind)
    result = _adapt(payload, operation="values")
    assert "values" not in result.projection
    assert "values" not in result.projection["semantic"]

    attacked = copy.deepcopy(payload)
    attacked["values"] = ["secret"]
    with pytest.raises(CatalogSemanticRetrievalError, match="must not materialize"):
        _adapt(attacked, operation="values")


def test_schema1_is_rejected_and_duplicate_keys_are_rejected() -> None:
    schema1 = _describe()
    schema1["schema"] = 1
    with pytest.raises(CatalogSemanticRetrievalError, match="schema 1"):
        _adapt(schema1)

    duplicate = b'{"schema":2,"schema":2,"tenant":"x","thresholds":{},"catalogs":[]}'
    with pytest.raises(CatalogSemanticRetrievalError, match="duplicate key"):
        adapt_catalog_semantic_response("describe", duplicate)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda p: p.update({"extra": True}), "extra fields"),
        (lambda p: (p["catalogs"][0].pop("semantic"), p)[1], "missing fields"),
    ],
)
def test_extra_missing_and_path_traversal_fail_closed(mutate: Any, match: str) -> None:
    payload = _describe()
    changed = mutate(payload)
    if changed is not None:
        payload = changed
    with pytest.raises(CatalogSemanticRetrievalError, match=match):
        _adapt(payload)


def test_path_traversal_mutation_is_applied_to_the_payload() -> None:
    payload = _describe()
    payload["catalogs"][0]["file"] = "../escape.metis"
    with pytest.raises(CatalogSemanticRetrievalError, match="relative POSIX"):
        _adapt(payload)


@pytest.mark.parametrize(
    "bad",
    [
        lambda p: p["catalogs"][0]["semantic"].update({"state": "unannotated", "means": MEANS}),
        lambda p: p["catalogs"][0]["fields"][1]["semantic"].update({"state": "draft"}),
        lambda p: p["catalogs"][0]["fields"][1]["semantic"].update({"state": "reviewed"}),
        lambda p: p["catalogs"][0]["fields"][1]["semantic"].update(
            {"aka": {"items": ["alias"], "at": AT}}
        ),
        lambda p: p["catalogs"][0]["fields"][0]["semantic"].update(
            {"label": {"text": "x", "at": AT}}
        ),
    ],
)
def test_semantic_state_and_scope_are_consistent(bad: Any) -> None:
    payload = _describe()
    bad(payload)
    with pytest.raises(CatalogSemanticRetrievalError):
        _adapt(payload)


def test_line_zero_and_control_unicode_fail_closed() -> None:
    line_zero = _describe()
    line_zero["catalogs"][0]["semantic"]["at"]["line"] = 0
    with pytest.raises(CatalogSemanticRetrievalError, match="1-based"):
        _adapt(line_zero)

    control = _describe()
    control["catalogs"][0]["semantic"]["means"]["text"] = "bad\u0000text"
    with pytest.raises(CatalogSemanticRetrievalError, match="control"):
        _adapt(control)


def test_semantic_values_omission_and_literal_misalignment_fail_closed() -> None:
    omitted = _values()
    omitted["semantic"].pop("values")
    with pytest.raises(CatalogSemanticRetrievalError, match="match materialized"):
        _adapt(omitted, operation="values")

    misaligned = _values()
    misaligned["semantic"]["values"][0]["literal"] = "Serie"
    with pytest.raises(CatalogSemanticRetrievalError, match="misaligned"):
        _adapt(misaligned, operation="values")


def test_receipt_hash_is_deterministic_and_tamper_is_detected() -> None:
    first = _adapt(_values(), operation="values")
    second = _adapt(_values(), operation="values")
    assert first.receipt == second.receipt
    assert first.receipt["hashes"] == second.receipt["hashes"]

    tampered = copy.deepcopy(first.receipt)
    tampered["counts"]["values"] = 99
    assert validate_catalog_semantic_receipt(tampered)


def test_bytes_items_and_depth_caps_are_enforced() -> None:
    too_large = _describe()
    too_large["tenant"] = "x" * (16_385)
    with pytest.raises(CatalogSemanticRetrievalError, match="character cap"):
        _adapt(too_large)

    too_deep: Any = {"nested": _describe()}
    for _ in range(MAX_DEPTH + 2):
        too_deep["nested"] = [too_deep["nested"]]
    with pytest.raises(CatalogSemanticRetrievalError, match="depth cap"):
        adapt_catalog_semantic_response("describe", _raw(too_deep))


def test_values_schema_requires_materialized_semantic_values_only_when_values_exist() -> None:
    unresolved = _values()
    unresolved.pop("values")
    unresolved.pop("nature")
    unresolved["note"] = "value-set non sincronizzato"
    unresolved["semantic"].pop("values")
    result = _adapt(unresolved, operation="values")
    assert result.receipt["counts"]["semantic_values"] == 0
