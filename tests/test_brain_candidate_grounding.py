from __future__ import annotations

import pytest

from metis_model1.brain_candidate_grounding import adjudicate_candidate
from metis_model1.brain_protocol import BrainError


def _selection(*values: str, multi: bool = False) -> dict[str, object]:
    result: dict[str, object] = {
        "catalog": "play-demo.video",
        "field": "paesiorigine",
        "type": "keyword",
        "modifiers": ["multi"] if multi else [],
        "domain": {"kind": "enum", "size": len(values), "nature": "editorial"},
    }
    if len(values) == 1:
        result["literal"] = values[0]
    else:
        result["literal"] = None
        result["literals"] = list(values)
        result["value_mode"] = "any_of"
    return result


def _grounding(*values: str, multi: bool = False) -> dict[str, object]:
    return {
        "status": "resolved",
        "catalogs": ["play-demo.video"],
        "selections": [_selection(*values, multi=multi)],
    }


def test_italy_subset_is_rejected_with_missing_literals() -> None:
    result = adjudicate_candidate('@paesiorigine is "italia"', _grounding("ITALIA", "italia"))
    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["fields"][0]["missing"] == ["ITALIA"]


def test_extra_literal_is_rejected() -> None:
    result = adjudicate_candidate(
        '@paesiorigine is "ITALIA" or @paesiorigine is "Italia"',
        _grounding("ITALIA"),
    )
    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["fields"][0]["extra"] == ["Italia"]


def test_duplicate_predicate_is_rejected_as_multiset_mismatch() -> None:
    result = adjudicate_candidate(
        '@paesiorigine is "ITALIA" or @paesiorigine is "ITALIA"',
        _grounding("ITALIA"),
    )
    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["fields"][0]["extra"] == ["ITALIA"]


def test_scalar_any_of_requires_one_membership_predicate() -> None:
    result = adjudicate_candidate(
        '@paesiorigine in ["ITALIA", "Italia", "italia"]',
        _grounding("ITALIA", "Italia", "italia"),
    )
    assert result.ok
    assert result.diagnostic is None


def test_scalar_any_of_membership_is_order_independent() -> None:
    result = adjudicate_candidate(
        '@paesiorigine in ["italia", "ITALIA", "Italia"]',
        _grounding("ITALIA", "Italia", "italia"),
    )
    assert result.ok


def test_scalar_or_chain_is_rejected_even_when_literals_are_complete() -> None:
    result = adjudicate_candidate(
        '@paesiorigine is "ITALIA" or @paesiorigine is "Italia" or @paesiorigine is "italia"',
        _grounding("ITALIA", "Italia", "italia"),
    )
    assert not result.ok
    assert result.diagnostic is not None
    field = result.diagnostic["fields"][0]
    assert field["missing"] == []
    assert field["extra"] == []
    assert field["expected_predicates"] == [
        {"operator": "in", "literals": ["ITALIA", "Italia", "italia"]}
    ]


def test_multi_any_of_requires_has_any() -> None:
    result = adjudicate_candidate(
        '@paesiorigine has any ["Noir", "Teso"]',
        _grounding("Noir", "Teso", multi=True),
    )
    assert result.ok


@pytest.mark.parametrize(
    ("source", "grounding"),
    [
        ('@paesiorigine has any ["ITALIA", "Italia"]', _grounding("ITALIA", "Italia")),
        ('@paesiorigine in ["Noir", "Teso"]', _grounding("Noir", "Teso", multi=True)),
        ('@paesiorigine is "Noir"', _grounding("Noir", multi=True)),
        ('@paesiorigine has "Italia"', _grounding("Italia")),
    ],
)
def test_cardinality_wrong_operator_is_rejected(source: str, grounding: dict[str, object]) -> None:
    result = adjudicate_candidate(source, grounding)
    assert not result.ok


def test_unauthorized_field_is_rejected() -> None:
    result = adjudicate_candidate('@mood is "noir"', _grounding("ITALIA"))
    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["unauthorized_fields"] == ["mood"]


def test_escaped_metis_string_is_decoded_before_comparison() -> None:
    result = adjudicate_candidate(
        '@paesiorigine is "Italia\\u0020centrale"', _grounding("Italia centrale")
    )
    assert result.ok


def test_malformed_string_is_rejected_conservatively() -> None:
    result = adjudicate_candidate('@paesiorigine is "Italia', _grounding("Italia"))
    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["parse_error"] == "unterminated quoted literal"


def test_comment_and_non_predicate_strings_do_not_create_grounding() -> None:
    source = """metis 0.43
// @mood is "noir"
endpoint demo.test as "@mood is \\"noir\\"" {
  take 20 from @play-demo.video include where @paesiorigine is "Italia"
  /* @mood is "thriller" */
}
"""
    assert adjudicate_candidate(source, _grounding("Italia")).ok


@pytest.mark.parametrize(
    "selection",
    [
        {"field": "bad field"},
        {
            "literals": ["Italia", "ITALIA"],
        },
        {
            "literal": None,
            "literals": ["Italia", "Italia"],
            "value_mode": "any_of",
        },
        {"literal": "x" * 4097},
        {"type": None},
        {"modifiers": ["bogus"]},
        {"modifiers": [{}]},
        {"domain": {"kind": "open"}},
        {"domain": {"kind": [], "size": 1}},
    ],
)
def test_invalid_grounding_authority_fails_closed(selection: dict[str, object]) -> None:
    invalid = _selection("Italia")
    invalid.update(selection)
    with pytest.raises(BrainError, match="grounding"):
        adjudicate_candidate(
            '@paesiorigine is "Italia"',
            {
                "status": "resolved",
                "catalogs": ["play-demo.video"],
                "selections": [invalid],
            },
        )


def test_grounding_selection_catalog_cannot_use_authorized_prefix() -> None:
    selection = _selection("Italia")
    selection["catalog"] = "video.synthetic"
    with pytest.raises(BrainError, match="grounding catalog"):
        adjudicate_candidate(
            '@paesiorigine is "Italia"',
            {
                "status": "resolved",
                "catalogs": ["play-demo.video"],
                "selections": [selection],
            },
        )


@pytest.mark.parametrize(
    "extra",
    [
        '@mood in ["Noir"]',
        '@mood has any ["Noir", "Teso"]',
        '@mood contains "Noir"',
        '@mood is not "Noir"',
        'match @mood "Noir"',
        'match precise @mood "Noir"',
        "using preset.demo.noir",
        "ids from context.noir",
        "@score > 5",
        '@title starts with "Il"',
    ],
)
def test_non_exact_condition_surfaces_cannot_bypass_grounding(extra: str) -> None:
    result = adjudicate_candidate(
        f'@paesiorigine is "Italia" and {extra}',
        _grounding("Italia"),
    )
    assert not result.ok
    assert result.diagnostic is not None


@pytest.mark.parametrize(
    "extra",
    [
        '@mood /*comment*/ in ["Noir"]',
        "@score /*comment*/ > 5",
        'match /*comment*/ precise /*comment*/ @mood "Noir"',
        "using /*comment*/ preset.demo.noir",
    ],
)
def test_comments_cannot_hide_unauthorized_condition_surfaces(extra: str) -> None:
    result = adjudicate_candidate(
        f'@paesiorigine is "Italia" and {extra}',
        _grounding("Italia"),
    )
    assert not result.ok


def test_valid_inline_if_guard_is_not_rejected() -> None:
    assert adjudicate_candidate(
        '@paesiorigine is "Italia" if $enabled is true',
        _grounding("Italia"),
    ).ok


@pytest.mark.parametrize(
    "guard",
    [
        "@enabled exists",
        "@score > 5",
    ],
)
def test_valid_inline_field_guard_is_not_grounding(guard: str) -> None:
    assert adjudicate_candidate(
        f'@paesiorigine is "Italia" if {guard}',
        _grounding("Italia"),
    ).ok


def test_guard_block_contents_remain_grounding_checked() -> None:
    result = adjudicate_candidate(
        '@paesiorigine is "Italia"\nif @enabled exists { @mood in ["Noir"] }',
        _grounding("Italia"),
    )
    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["unauthorized_fields"] == ["mood"]


def test_bare_field_condition_after_conjunction_is_rejected() -> None:
    result = adjudicate_candidate(
        '@paesiorigine is "Italia" and @mood',
        _grounding("Italia"),
    )
    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["parse_error"] == "bare field condition is not authorized"


def test_bare_field_inside_at_least_group_is_rejected() -> None:
    result = adjudicate_candidate(
        '@paesiorigine is "Italia" and at least 1 of { @mood }',
        _grounding("Italia"),
    )
    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["parse_error"] == "bare field condition is not authorized"


def test_order_by_field_is_not_mistaken_for_bare_condition() -> None:
    source = """metis 0.43
endpoint demo.test as demo_test {
  take 20 from @play-demo.video {
    include where @paesiorigine is "Italia"
    order by @last24h_videoviews descending
    return response.expanded
  }
}
"""
    assert adjudicate_candidate(source, _grounding("Italia")).ok


def test_non_condition_using_surface_is_not_rejected() -> None:
    source = """metis 0.43
endpoint demo.match as demo_match {
  take 20 from @play-demo.video as videos
  include where @paesiorigine is "Italia"
  return response.expanded { view-all using endpoint.demo.more }
}
"""
    assert adjudicate_candidate(source, _grounding("Italia")).ok


def test_catalog_reference_is_not_mistaken_for_a_field_predicate() -> None:
    source = """metis 0.43
endpoint demo.test as demo_test {
  take 20 from @play-demo.video as videos
  include where @paesiorigine is "Italia"
  return response.expanded
}
"""
    assert adjudicate_candidate(source, _grounding("Italia")).ok


def test_authorized_short_catalog_source_is_accepted() -> None:
    source = """metis 0.43
endpoint demo.test as demo_test {
  take 20 from @video include where @paesiorigine is "Italia"
  return response.expanded
}
"""
    assert adjudicate_candidate(source, _grounding("Italia")).ok


def test_unauthorized_catalog_source_is_rejected() -> None:
    source = """metis 0.43
endpoint demo.test as demo_test {
  take 20 from @users include where @paesiorigine is "Italia"
  return response.expanded
}
"""
    result = adjudicate_candidate(source, _grounding("Italia"))
    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["unauthorized_catalogs"] == ["users"]


def test_authorized_catalog_field_source_is_accepted() -> None:
    source = """metis 0.43
endpoint demo.test as demo_test {
  take 20 from @video.items include where @paesiorigine is "Italia"
  return response.expanded
}
"""
    assert adjudicate_candidate(source, _grounding("Italia")).ok


def test_authorized_fully_qualified_catalog_field_source_is_accepted() -> None:
    source = """metis 0.43
endpoint demo.test as demo_test {
  take 20 from @play-demo.video.items include where @paesiorigine is "Italia"
  return response.expanded
}
"""
    assert adjudicate_candidate(source, _grounding("Italia")).ok
