from __future__ import annotations

import copy
import json
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from metis_model1.brain_create_builder import (
    CREATE_ENDPOINT_SPEC_CONTRACT,
    CREATE_ENDPOINT_SPEC_SCHEMA,
    CreateBuilderError,
    quote_metis_string,
    render_create_endpoint,
)


def _lit(value: str, lexical: str = "text") -> dict[str, Any]:
    return {"kind": "lit", "lexical": lexical, "value": value}


def _ctx(*segments: str) -> dict[str, Any]:
    return {"kind": "ctx", "segments": list(segments)}


def _input(name: str) -> dict[str, Any]:
    return {"kind": "input", "name": name}


def _empty_presentation() -> dict[str, Any]:
    return {"pinned": None, "view_all": None, "meta": [], "meta_per_item": False}


def _empty_flow() -> dict[str, Any]:
    return {"projection": "default", "steps": [], "fallbacks": []}


def _fetch(
    *,
    catalog: str = "video",
    cardinality: dict[str, Any] | None = None,
    clauses: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "from": {"kind": "catalog", "catalog": catalog},
        "cardinality": ({"mode": "total", "value": 20} if cardinality is None else cardinality),
        "over_fetch": None,
        "alias": None,
        "title": None,
        "activation": None,
        "presentation": _empty_presentation(),
        "clauses": clauses or [],
        "group_by": None,
        "order": [],
        "output": None,
    }


def _block(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "parameters": [],
        "title": None,
        "activation": None,
        "presentation": _empty_presentation(),
        "fetches": [],
        "blocks": [],
        "uses": [],
        "output": None,
    }


def _variant(name: str) -> dict[str, Any]:
    result = _block(name)
    result.pop("parameters")
    result["empty"] = False
    return result


def _base_spec() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contract_id": CREATE_ENDPOINT_SPEC_CONTRACT,
        "endpoint": {
            "name": "play.brain_create",
            "reference": "brainCreate",
            "params": {"timeout": None, "expires": None, "paginate": None},
            "inputs": [],
            "needs_time": False,
            "attributes": [],
            "input_pipeline": [],
            "output_pipeline": [],
            "inheritance": {"without_input": [], "without_output": []},
            "context": [],
            "blocks": [],
            "variants": [],
            "output": None,
        },
    }


def _representative_spec() -> dict[str, Any]:
    spec = _base_spec()
    endpoint = spec["endpoint"]
    endpoint["params"] = {
        "timeout": {"kind": "scale", "value": "standard"},
        "expires": {
            "value": _lit("soon"),
            "guard": {
                "kind": "compare",
                "left": {"kind": "input", "name": "userId"},
                "op": "not_empty",
            },
            "else": _lit("12h", "duration"),
        },
        "paginate": "snapshot",
    }
    endpoint["inputs"] = [
        {
            "name": "query",
            "type": "text",
            "required": True,
            "not_empty": True,
            "default": None,
        },
        {
            "name": "params_genre",
            "type": "text",
            "required": False,
            "not_empty": False,
            "default": _lit("Azione"),
        },
    ]
    endpoint["needs_time"] = True
    endpoint["attributes"] = [
        {
            "name": "has_query",
            "guard": {
                "kind": "compare",
                "left": {"kind": "input", "name": "query"},
                "op": "not_empty",
            },
        }
    ]
    endpoint["input_pipeline"] = ["play_search"]
    endpoint["output_pipeline"] = ["decorate"]
    endpoint["inheritance"] = {
        "without_input": ["play_persona_input"],
        "without_output": [],
    }
    seed = _fetch(
        cardinality={"mode": "total", "value": 1},
        clauses=[
            {
                "intent": "include",
                "where": [{"op": "eq", "field": "video_content_id", "value": _input("query")}],
            }
        ],
    )
    endpoint["context"] = [
        {
            "kind": "transform",
            "name": "search",
            "value": _input("query"),
            "transformer": "play_search",
        },
        {"kind": "fetch", "name": "seed", "fetch": seed},
    ]

    fallback = _block("fallback_recent")
    fallback["fetches"] = [_fetch(cardinality={"mode": "total", "value": 12})]

    genre = _block("genre_row")
    genre["parameters"] = [
        {"name": "genre", "required": True, "type": None, "default": None},
        {
            "name": "is_pinned",
            "required": False,
            "type": "boolean",
            "default": {"kind": "bool", "value": True},
        },
    ]
    genre["title"] = {"kind": "literal", "value": "Scelti per te"}
    genre["activation"] = {
        "kind": "compare",
        "left": {"kind": "attr", "name": "has_query"},
        "op": "truthy",
    }
    genre["presentation"] = {
        "pinned": {"kind": "arg", "name": "is_pinned"},
        "view_all": {"kind": "endpoint", "name": "play.view_all_person"},
        "meta": [
            {"kind": "ui_preset", "value": "POSTER"},
            {"kind": "entry", "key": "movable", "value": {"kind": "bool", "value": True}},
        ],
        "meta_per_item": False,
    }
    query = _fetch(
        cardinality={"mode": "total", "value": 32},
        clauses=[
            {
                "intent": "include",
                "where": [
                    {
                        "op": "group",
                        "strategy": "best_plus",
                        "coefficient": "near_full",
                        "items": [
                            {
                                "op": "match",
                                "profile": "broad",
                                "field": "search_title",
                                "value": _input("query"),
                                "fuzzy": True,
                                "min": 0,
                            },
                            {
                                "op": "similar",
                                "form": "field",
                                "field": "genere_mcm",
                                "value": _input("query"),
                                "fuzzy": "auto",
                            },
                        ],
                    },
                    {
                        "op": "contains",
                        "membership": "has_any",
                        "field": "content_channels",
                        "value": {"kind": "list_ref", "name": "active_channels"},
                    },
                    {
                        "op": "within",
                        "field": "publication_date",
                        "amount": _lit("18M", "duration"),
                        "target": _lit("now", "time"),
                    },
                ],
            },
            {"intent": "exclude", "presets": ["blacklist", "video_format_exclude_4k"]},
            {
                "intent": "promote",
                "where": [
                    {
                        "op": "similar",
                        "form": "record",
                        "profile": "content_fingerprint",
                        "target": _ctx("seed"),
                        "guard": {
                            "kind": "compare",
                            "left": {"kind": "ctx", "segments": ["seed"]},
                            "op": "exists",
                        },
                    }
                ],
            },
        ],
    )
    query["over_fetch"] = 2
    query["alias"] = "genre_candidates"
    query["title"] = {
        "kind": "context_parts",
        "parts": [
            {"kind": "text", "value": "Perché hai visto "},
            {"kind": "ctx", "segments": ["seed", "title"]},
        ],
        "fallback": "Consigliati per te",
    }
    query["group_by"] = {
        "fields": ["brand_title"],
        "member_order": [{"by": "field", "field": "video_format", "direction": "ascending"}],
        "member_limit": 1,
        "having": None,
    }
    query["order"] = [
        {"by": "relevance", "direction": "descending"},
        {
            "by": "field",
            "field": "publication_date",
            "direction": "descending",
            "guard": {
                "kind": "compare",
                "left": {"kind": "input", "name": "query"},
                "op": "not_empty",
            },
        },
    ]
    query["output"] = {
        "projection": "expanded",
        "steps": [
            {"kind": "deduplicate", "field": "video_content_id"},
            {"kind": "shuffle"},
            {"kind": "max", "count": 30},
            {
                "kind": "limit",
                "field": "tipologia",
                "count": 8,
                "op": "eq",
                "value": _lit("Film"),
            },
            {"kind": "limit_per", "field": "brand_title", "count": 2},
            {
                "kind": "order",
                "orders": [{"by": "similarity", "target": _ctx("seed"), "direction": "descending"}],
            },
        ],
        "fallbacks": [
            {
                "kind": "direct",
                "target_kind": "block",
                "target": "fallback_recent",
                "trigger": "empty",
                "mode": "substitute",
            }
        ],
    }
    genre["fetches"] = [query]

    personalized = _variant("personalized")
    personalized["activation"] = {
        "kind": "compare",
        "left": {"kind": "attr", "name": "has_query"},
        "op": "truthy",
    }
    nested = _block("featured")
    nested["fetches"] = [_fetch(cardinality={"mode": "total", "value": 8})]
    personalized["blocks"] = [nested]
    personalized["uses"] = [
        {
            "kind": "matrix",
            "block": "genre_row",
            "rows": [
                {
                    "alias": "azione",
                    "title": {"kind": "literal", "value": "Azione"},
                    "args": [
                        {"name": "genre", "value": _lit("Azione")},
                        {"name": "is_pinned", "value": {"kind": "bool", "value": False}},
                    ],
                },
                {
                    "alias": "commedia",
                    "title": {"kind": "literal", "value": "Commedia"},
                    "args": [
                        {"name": "genre", "value": _lit("Commedia")},
                        {"name": "is_pinned", "value": {"kind": "bool", "value": False}},
                    ],
                },
            ],
        }
    ]
    empty = _variant("unavailable")
    empty["empty"] = True
    endpoint["blocks"] = [fallback, genre]
    endpoint["variants"] = [personalized, empty]
    endpoint["output"] = {
        "projection": "default",
        "steps": [],
        "fallbacks": [
            {
                "kind": "materialized",
                "target": "page_fallback",
                "trigger": "page_blocks_below",
                "threshold": 1,
                "mode": "substitute",
            }
        ],
    }
    return spec


def _compiler_realistic_order_spec() -> dict[str, Any]:
    """A §9.70-valid shape apart from tenant-owned cross-reference resolution."""

    spec = _base_spec()
    endpoint = spec["endpoint"]
    endpoint["name"] = "play.ordered_create"
    endpoint["reference"] = None
    endpoint["params"]["timeout"] = {"kind": "scale", "value": "standard"}
    endpoint["inputs"] = [
        {
            "name": "query",
            "type": "text",
            "required": False,
            "not_empty": False,
            "default": None,
        }
    ]
    endpoint["input_pipeline"] = ["normalize"]
    endpoint["context"] = [
        {
            "kind": "fetch",
            "name": "seed",
            "fetch": _fetch(
                cardinality={"mode": "total", "value": 1},
                clauses=[
                    {
                        "intent": "include",
                        "where": [
                            {
                                "op": "eq",
                                "field": "video_content_id",
                                "value": _input("query"),
                            }
                        ],
                    }
                ],
            ),
        }
    ]
    endpoint["attributes"] = [
        {
            "name": "has_query",
            "guard": {
                "kind": "compare",
                "left": {"kind": "input", "name": "query"},
                "op": "not_empty",
            },
        }
    ]
    results = _block("results")
    results["fetches"] = [
        _fetch(
            cardinality={"mode": "total", "value": 24},
            clauses=[
                {
                    "intent": "include",
                    "where": [{"op": "eq", "field": "tipologia", "value": _lit("Film")}],
                }
            ],
        )
    ]
    endpoint["blocks"] = [results]
    unavailable = _variant("unavailable")
    unavailable["empty"] = True
    endpoint["variants"] = [unavailable]
    endpoint["output_pipeline"] = ["decorate"]
    endpoint["output"] = _empty_flow()
    return spec


def test_schema_is_valid_and_has_no_raw_escape_hatch() -> None:
    assert Draft202012Validator.check_schema(CREATE_ENDPOINT_SPEC_SCHEMA) is None
    forbidden = {"raw", "dsl", "expression", "path", "template", "source"}

    def property_keys(value: Any) -> set[str]:
        if isinstance(value, dict):
            here = (
                set(value.get("properties", {}))
                if isinstance(value.get("properties"), dict)
                else set()
            )
            return here | set().union(*(property_keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(property_keys(item) for item in value))
        return set()

    assert forbidden.isdisjoint(property_keys(CREATE_ENDPOINT_SPEC_SCHEMA))


def test_fetch_cardinality_renders_all_four_exact_metis_surfaces() -> None:
    spec = _base_spec()
    cardinalities = [
        ({"mode": "none"}, "unbounded"),
        ({"mode": "total", "value": 24}, "total"),
        ({"mode": "page"}, "paged"),
        ({"mode": "page_default", "value": 20}, "paged_default"),
    ]
    fetches = []
    for cardinality, alias in cardinalities:
        fetch = _fetch(cardinality=cardinality)
        fetch["alias"] = alias
        fetches.append(fetch)
    spec["endpoint"]["blocks"] = [{**_block("cardinality_forms"), "fetches": fetches}]

    assert (
        render_create_endpoint(spec).metis_text
        == """metis 0.43

endpoint play.brain_create as "brainCreate" {
  block cardinality_forms {
    take from @video as unbounded
    take 24 from @video as total
    take page from @video as paged
    take page default 20 from @video as paged_default
  }
}
"""
    )


@pytest.mark.parametrize(
    "cardinality",
    [
        None,
        {},
        {"mode": "none", "value": 1},
        {"mode": "total"},
        {"mode": "total", "value": 0},
        {"mode": "total", "value": True},
        {"mode": "total", "value": 10_001},
        {"mode": "page", "value": 20},
        {"mode": "page_default"},
        {"mode": "page_default", "value": 0},
        {"mode": "page_default", "value": 20, "scope": "endpoint"},
        {"mode": "unknown"},
    ],
)
def test_fetch_cardinality_union_rejects_ambiguous_or_invalid_shapes(
    cardinality: Any,
) -> None:
    spec = _base_spec()
    fetch = _fetch()
    fetch["cardinality"] = cardinality
    spec["endpoint"]["blocks"] = [{**_block("invalid"), "fetches": [fetch]}]

    with pytest.raises(CreateBuilderError) as error:
        render_create_endpoint(spec)
    assert error.value.code == "INVALID_SPEC"


@pytest.mark.parametrize(
    ("cardinality", "factor"),
    [
        ({"mode": "none"}, 2),
        ({"mode": "page"}, 2),
        ({"mode": "page_default", "value": 20}, 2),
        ({"mode": "total", "value": 24}, 1),
        ({"mode": "total", "value": 24}, 17),
        ({"mode": "total", "value": 24}, True),
    ],
)
def test_over_fetch_is_closed_to_bounded_total_cardinality(
    cardinality: dict[str, Any], factor: Any
) -> None:
    spec = _base_spec()
    fetch = _fetch(cardinality=cardinality)
    fetch["over_fetch"] = factor
    spec["endpoint"]["blocks"] = [{**_block("invalid"), "fetches": [fetch]}]

    with pytest.raises(CreateBuilderError) as error:
        render_create_endpoint(spec)
    assert error.value.code == "INVALID_SPEC"


def test_legacy_nullable_fetch_count_is_rejected() -> None:
    spec = _base_spec()
    fetch = _fetch()
    fetch.pop("cardinality")
    fetch["count"] = None
    spec["endpoint"]["blocks"] = [{**_block("legacy"), "fetches": [fetch]}]

    with pytest.raises(CreateBuilderError) as error:
        render_create_endpoint(spec)
    assert error.value.code == "INVALID_SPEC"


def test_representative_create_renders_deterministically() -> None:
    spec = _representative_spec()
    first = render_create_endpoint(spec)
    second = render_create_endpoint(copy.deepcopy(spec))

    assert first == second
    assert first.metis_text.startswith(
        'metis 0.43\n\nendpoint play.brain_create as "brainCreate" {'
    )
    assert "params {\n    timeout standard" in first.metis_text
    assert "expires soon if $userId is not empty else 12h" in first.metis_text
    assert "paginate snapshot" in first.metis_text
    assert "search = $query -> transformer.play_search" in first.metis_text
    assert "take 32 * 2 from @video as genre_candidates" in first.metis_text
    assert "best plus near_full from alternatives" in first.metis_text
    assert "@content_channels has any list.active_channels" in first.metis_text
    assert "@publication_date within 18M of time.now" in first.metis_text
    assert "@genere_mcm similar to $query fuzzy auto" in first.metis_text
    assert "match broad @search_title $query fuzzy min 0" in first.metis_text
    assert "group by @brand_title {" in first.metis_text
    assert "return response.expanded -> deduplicate using @video_content_id" in first.metis_text
    assert "fallback to block.fallback_recent when empty substitute" in first.metis_text
    assert "use blocks {" in first.metis_text
    assert 'genre_row(genre = "Azione", is_pinned = false) as azione "Azione"' in first.metis_text
    assert "variant unavailable empty" in first.metis_text
    assert (
        "fallback to materialized.page_fallback when page blocks below 1 substitute"
        in first.metis_text
    )
    assert first.stats.containers == 5
    assert first.stats.fetches == 4
    assert first.stats.expanded_uses == 2
    assert first.stats.argument_bindings == 4
    assert first.metis_sha256.startswith("sha256:")
    assert first.spec_sha256.startswith("sha256:")


def test_endpoint_sections_have_exact_canonical_source_order() -> None:
    rendered = render_create_endpoint(_compiler_realistic_order_spec()).metis_text
    assert (
        rendered
        == """metis 0.43

endpoint play.ordered_create {
  params timeout standard
  input query text
  in -> transformer.normalize
  context {
    seed = take 1 from @video {
      include where @video_content_id is $query
    }
  }
  attributes has_query = $query is not empty
  block results {
    take 24 from @video {
      include where @tipologia is "Film"
    }
  }
  variant unavailable empty
  out -> transformer.decorate
  return response
}
"""
    )

    stages = [
        "  params ",
        "  input ",
        "  in ->",
        "  context {",
        "  attributes ",
        "  block ",
        "  variant ",
        "  out ->",
        "  return response\n}",
    ]
    offsets = [rendered.index(stage) for stage in stages]
    assert offsets == sorted(offsets)


def test_all_four_group_forms_and_fourteen_predicate_ops_are_closed() -> None:
    spec = _base_spec()
    leaf = {"op": "eq", "field": "tipologia", "value": _lit("Film")}
    predicates: list[dict[str, Any]] = [
        leaf,
        {"op": "in", "field": "tipologia", "value": {"kind": "vals", "items": ["Film"]}},
        {
            "op": "contains",
            "membership": "has",
            "field": "content_channels",
            "value": _lit("Infinity"),
        },
        {"op": "gt", "field": "score", "value": {"kind": "lit", "lexical": "number", "value": 1}},
        {
            "op": "gte",
            "field": "year",
            "value": {"kind": "lit", "lexical": "number", "value": 2020},
        },
        {
            "op": "lte",
            "field": "year",
            "value": {"kind": "lit", "lexical": "number", "value": 2030},
        },
        {
            "op": "similar",
            "form": "field",
            "field": "fingerprint",
            "value": _ctx("seed", "fingerprint"),
        },
        {
            "op": "within",
            "field": "date",
            "amount": _lit("1y", "duration"),
            "target": _lit("now", "time"),
        },
        {"op": "exists", "field": "production_value"},
        {"op": "match", "field": "title", "value": _input("query")},
        {"op": "ids", "segments": ["watched", "id"]},
        {"op": "and", "items": [leaf, leaf]},
        {"op": "or", "items": [leaf, leaf]},
        {"op": "group", "strategy": "any", "items": [leaf, leaf]},
        {"op": "group", "strategy": "best", "items": [leaf, leaf]},
        {
            "op": "group",
            "strategy": "best_plus",
            "coefficient": "near_full",
            "items": [leaf, leaf],
        },
        {"op": "group", "strategy": "at_least", "threshold": 2, "items": [leaf, leaf]},
    ]
    spec["endpoint"]["blocks"] = [
        {
            **_block("coverage"),
            "fetches": [_fetch(clauses=[{"intent": "include", "where": predicates}])],
        }
    ]
    rendered = render_create_endpoint(spec).metis_text
    assert "any of" in rendered
    assert "only best of" in rendered
    assert "best plus near_full from alternatives" in rendered
    assert "at least 2 of" in rendered


@pytest.mark.parametrize("bad", ['quote"', "back\\slash", "line\nbreak", "tab\tvalue", "x\x7f"])
def test_metis_string_rejects_unrepresentable_characters(bad: str) -> None:
    with pytest.raises(CreateBuilderError, match="unsupported character") as error:
        quote_metis_string(bad)
    assert error.value.code == "INVALID_STRING"


def test_metis_string_property_for_safe_unicode_and_empty_literal() -> None:
    alphabet = ["", "a", "Italia 1", "caffè", "映画", "emoji 🎬", "{} backtick `"]
    for text in alphabet:
        assert quote_metis_string(text) == f'"{text}"'
    spec = _base_spec()
    spec["endpoint"]["blocks"] = [
        {
            **_block("empty_value"),
            "fetches": [
                _fetch(
                    clauses=[
                        {
                            "intent": "include",
                            "where": [{"op": "eq", "field": "id_series", "value": _lit("")}],
                        }
                    ]
                )
            ],
        }
    ]
    assert '@id_series is ""' in render_create_endpoint(spec).metis_text


@pytest.mark.parametrize(
    "field",
    ["raw", "dsl", "expression", "path", "template", "source", "source_text"],
)
def test_raw_escape_hatches_are_rejected_before_schema(field: str) -> None:
    spec = _base_spec()
    spec["endpoint"][field] = "endpoint injected {}"
    with pytest.raises(CreateBuilderError, match="forbidden field") as error:
        render_create_endpoint(spec)
    assert error.value.code == "FORBIDDEN_FIELD"


def test_identifier_and_interpolated_title_injection_fail_closed() -> None:
    spec = _base_spec()
    spec["endpoint"]["name"] = "play.good } endpoint evil.bad {"
    with pytest.raises(CreateBuilderError) as error:
        render_create_endpoint(spec)
    assert error.value.code == "INVALID_SPEC"

    spec = _representative_spec()
    spec["endpoint"]["blocks"][1]["fetches"][0]["title"]["parts"][0]["value"] = "x}` evil `"
    with pytest.raises(CreateBuilderError) as error:
        render_create_endpoint(spec)
    assert error.value.code == "INVALID_STRING"


def test_matrix_is_bounded_and_requires_exact_ordered_columns() -> None:
    spec = _representative_spec()
    matrix = spec["endpoint"]["variants"][0]["uses"][0]
    matrix["rows"][1]["args"].reverse()
    with pytest.raises(CreateBuilderError, match="same ordered columns") as error:
        render_create_endpoint(spec)
    assert error.value.code == "INVALID_SPEC"

    spec = _representative_spec()
    matrix = spec["endpoint"]["variants"][0]["uses"][0]
    matrix["rows"] = matrix["rows"] * 7
    with pytest.raises(CreateBuilderError) as error:
        render_create_endpoint(spec)
    assert error.value.code == "INVALID_SPEC"


def test_empty_variant_and_fallback_arity_fail_closed() -> None:
    spec = _representative_spec()
    spec["endpoint"]["variants"][1]["fetches"] = [_fetch()]
    with pytest.raises(CreateBuilderError, match="empty variant"):
        render_create_endpoint(spec)

    spec = _representative_spec()
    fallback = spec["endpoint"]["output"]["fallbacks"][0]
    fallback["threshold"] = None
    with pytest.raises(CreateBuilderError):
        render_create_endpoint(spec)

    spec = _representative_spec()
    fallback = spec["endpoint"]["output"]["fallbacks"][0]
    fallback["mode"] = "append"
    with pytest.raises(CreateBuilderError, match="require substitute") as error:
        render_create_endpoint(spec)
    assert error.value.code == "INVALID_SPEC"


def test_schema_rejects_unknown_operator_and_literal_kind() -> None:
    spec = _base_spec()
    spec["endpoint"]["blocks"] = [
        {
            **_block("bad"),
            "fetches": [
                _fetch(
                    clauses=[
                        {
                            "intent": "include",
                            "where": [
                                {
                                    "op": "shell",
                                    "field": "x",
                                    "value": {"kind": "code", "value": "x"},
                                }
                            ],
                        }
                    ]
                )
            ],
        }
    ]
    with pytest.raises(CreateBuilderError) as error:
        render_create_endpoint(spec)
    assert error.value.code == "INVALID_SPEC"


def test_result_is_not_a_public_json_serializer() -> None:
    result = render_create_endpoint(_base_spec())
    assert set(result.__dataclass_fields__) == {
        "metis_text",
        "metis_sha256",
        "spec_sha256",
        "stats",
    }
    assert not hasattr(result, "to_document")
    assert json.loads(json.dumps({"digest": result.metis_sha256})) == {
        "digest": result.metis_sha256
    }
