from __future__ import annotations

import copy

import pytest

from metis_model1.brain_candidate_grounding import (
    TakeContract,
    adjudicate_candidate,
    adjudicate_candidate_manifest,
    adjudicate_candidate_shape,
    adjudicate_manifest_preservation,
    candidate_manifest_delta,
    candidate_target_diagnostic,
    source_endpoint_catalogs,
    source_endpoint_has_fallback,
    source_take_contract,
)
from metis_model1.brain_protocol import BrainError


def test_create_target_oracle_accepts_exact_name_reference_and_ignores_decoys() -> None:
    source = """metis 0.43

// endpoint demo.comment as "commentReference" {}
block helper {
  use endpoint.demo.nested
}
endpoint demo.target as "brainTarget" {
  take 12 from @play-demo.video {
    include where { @tipologia is "endpoint demo.string as \\"stringReference\\"" }
    return response.default
  }
}
"""
    target = {
        "mode": "create",
        "endpoint": "demo.target",
        "reference": "brainTarget",
    }

    assert candidate_target_diagnostic(source, target) is None


@pytest.mark.parametrize(
    "source",
    [
        "endpoint demo.target { take 12 from @play-demo.video }",
        'endpoint demo.target as "wrongReference" { take 12 from @play-demo.video }',
        'endpoint demo.other as "brainTarget" { take 12 from @play-demo.video }',
        """endpoint demo.target as "brainTarget" { take 12 from @play-demo.video }
endpoint demo.other { take 1 from @play-demo.video }
""",
    ],
)
def test_create_target_oracle_rejects_missing_wrong_or_extra_header(source: str) -> None:
    diagnostic = candidate_target_diagnostic(
        source,
        {"mode": "create", "endpoint": "demo.target", "reference": "brainTarget"},
    )

    assert diagnostic is not None
    assert diagnostic["code"] == "CANDIDATE_TARGET_MISMATCH"


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


def _grounding(
    *values: str,
    multi: bool = False,
    take: dict[str, object] | None = None,
) -> dict[str, object]:
    grounding: dict[str, object] = {
        "status": "resolved",
        "catalogs": ["play-demo.video"],
        "selections": [_selection(*values, multi=multi)],
    }
    if take is not None:
        grounding["output_contract"] = {"take": take}
    return grounding


def _manifest_predicate(
    *,
    catalog: str,
    field: str,
    value: object = "ITALIA",
    intent: str = "include",
    origin_kind: str = "inline",
) -> dict[str, object]:
    return {
        "intent": intent,
        "clause_index": 0,
        "leaf_path": "constraints[0].predicate",
        "catalog": catalog,
        "field": field,
        "operator": "eq" if value is not None else "exists",
        "value": {"lit": value} if isinstance(value, str) else None,
        "amount": None,
        "graded": False,
        "origin": {
            "kind": origin_kind,
            "ref": "demo.preset" if origin_kind == "preset" else None,
        },
        "clause_guard_sha256": None,
        "leaf_guard_sha256": None,
        "expression_sha256": "sha256:" + "1" * 64,
    }


def _compiled_manifest(
    fetches: list[tuple[str, str, list[dict[str, object]]]],
) -> dict[str, object]:
    containers = [
        {
            "path": "endpoint",
            "kind": "endpoint",
            "name": "demo.target",
            "activation_sha256": None,
            "output_sha256": None,
            "fallback_sha256": None,
            "uses_sha256": None,
            "semantics_sha256": "sha256:" + "8" * 64,
            "presentation_sha256": "sha256:" + "2" * 64,
        },
        *[
            {
                "path": f"endpoint/blocks[{index}]:row{index}",
                "kind": "block",
                "name": f"row{index}",
                "activation_sha256": None,
                "output_sha256": None,
                "fallback_sha256": None,
                "uses_sha256": None,
                "semantics_sha256": "sha256:" + "8" * 64,
                "presentation_sha256": "sha256:" + "2" * 64,
            }
            for index in range(len(fetches))
        ],
    ]
    return {
        "schema_version": 1,
        "endpoint": "demo.target",
        "endpoint_sha256": "sha256:" + "3" * 64,
        "containers": containers,
        "fetches": [
            {
                "occurrence": index,
                "stage_id": stage,
                "container_path": f"endpoint/blocks[{index}]:row{index}",
                "source": {"kind": "catalog", "ref": catalog},
                "catalog": catalog,
                "count": {"skip": 0, "take": index + 1},
                "activation_sha256": None,
                "ordering_sha256": "sha256:" + "4" * 64,
                "output_sha256": None,
                "fallback_sha256": None,
                "predicates": predicates,
                "semantics_sha256": "sha256:" + "5" * 64,
            }
            for index, (stage, catalog, predicates) in enumerate(fetches)
        ],
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


def test_compiled_manifest_grounding_accepts_exact_catalog_qualified_occurrence() -> None:
    manifest = _compiled_manifest(
        [
            (
                "block.1.row0.take.1",
                "play-demo.video",
                [_manifest_predicate(catalog="play-demo.video", field="paesiorigine")],
            )
        ]
    )

    assert adjudicate_candidate_manifest(manifest, _grounding("ITALIA")).ok


def test_compiled_manifest_grounding_rejects_catalog_descendant_prefix() -> None:
    manifest = _compiled_manifest(
        [
            (
                "block.1.row0.take.1",
                "play-demo.video.shadow",
                [
                    _manifest_predicate(
                        catalog="play-demo.video.shadow",
                        field="paesiorigine",
                    )
                ],
            )
        ]
    )

    result = adjudicate_candidate_manifest(manifest, _grounding("ITALIA"))

    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["unauthorized_catalogs"] == ["play-demo.video.shadow"]


@pytest.mark.parametrize(
    "predicate",
    [
        _manifest_predicate(
            catalog="play-demo.video",
            field="paesiorigine",
            origin_kind="preset",
        ),
        _manifest_predicate(
            catalog="play-demo.video",
            field="paesiorigine",
            value=None,
        ),
        _manifest_predicate(
            catalog="play-demo.video",
            field="paesiorigine",
            intent="exclude",
        ),
    ],
)
def test_compiled_manifest_grounding_fails_closed_without_explicit_predicate_authority(
    predicate: dict[str, object],
) -> None:
    manifest = _compiled_manifest([("block.1.row0.take.1", "play-demo.video", [predicate])])

    result = adjudicate_candidate_manifest(manifest, _grounding("ITALIA"))
    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["unauthorized_predicates"]


def test_occurrence_manifest_preserves_multi_catalog_multi_take_endpoint() -> None:
    reference = _compiled_manifest(
        [
            (
                "block.1.row0.take.1",
                "play-demo.video",
                [_manifest_predicate(catalog="play-demo.video", field="paesiorigine")],
            ),
            (
                "block.2.row1.take.1",
                "play-demo.users",
                [_manifest_predicate(catalog="play-demo.users", field="segment", value="Family")],
            ),
        ]
    )

    assert adjudicate_manifest_preservation(reference, copy.deepcopy(reference)).ok
    assert candidate_manifest_delta(reference, copy.deepcopy(reference)) == []


@pytest.mark.parametrize("mutation", ["duplicate", "removed", "moved", "wrong_catalog"])
def test_occurrence_manifest_rejects_adversarial_predicate_changes(mutation: str) -> None:
    reference = _compiled_manifest(
        [
            (
                "block.1.row0.take.1",
                "play-demo.video",
                [_manifest_predicate(catalog="play-demo.video", field="paesiorigine")],
            ),
            (
                "block.2.row1.take.1",
                "play-demo.video",
                [_manifest_predicate(catalog="play-demo.video", field="genre", value="Azione")],
            ),
        ]
    )
    candidate = copy.deepcopy(reference)
    first = candidate["fetches"][0]
    second = candidate["fetches"][1]
    if mutation == "duplicate":
        first["predicates"].append(copy.deepcopy(first["predicates"][0]))
    elif mutation == "removed":
        first["predicates"].clear()
    elif mutation == "moved":
        second["predicates"].append(first["predicates"].pop())
    else:
        first["source"] = {"kind": "catalog", "ref": "play-demo.users"}
        first["catalog"] = "play-demo.users"
        first["predicates"][0]["catalog"] = "play-demo.users"

    result = adjudicate_manifest_preservation(reference, candidate)
    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["code"] == "CANDIDATE_STRUCTURE_MISMATCH"
    components = {item["component"] for item in result.diagnostic["deltas"]}
    assert "predicates" in components
    if mutation == "wrong_catalog":
        assert {"source", "catalog"} <= components


def test_occurrence_manifest_rejects_fetch_and_container_reordering() -> None:
    reference = _compiled_manifest(
        [
            ("block.1.row0.take.1", "play-demo.video", []),
            ("block.2.row1.take.1", "play-demo.users", []),
        ]
    )
    candidate = copy.deepcopy(reference)
    candidate["containers"][1:] = reversed(candidate["containers"][1:])
    candidate["fetches"] = list(reversed(candidate["fetches"]))
    for index, fetch in enumerate(candidate["fetches"]):
        fetch["occurrence"] = index

    deltas = candidate_manifest_delta(reference, candidate)
    assert {item["component"] for item in deltas} >= {
        "container_roster",
        "fetch_roster",
    }


def test_occurrence_manifest_rejects_other_direct_container_semantics() -> None:
    reference = _compiled_manifest([("block.1.row0.take.1", "play-demo.video", [])])
    candidate = copy.deepcopy(reference)
    candidate["containers"][1]["semantics_sha256"] = "sha256:" + "f" * 64

    result = adjudicate_manifest_preservation(reference, candidate)

    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["deltas"] == [
        {
            "locator": "container:endpoint/blocks[0]:row0",
            "component": "semantics",
        }
    ]


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


@pytest.mark.parametrize(
    "surface",
    [
        'include where @paesiorigine is "Italia"',
        'include where { @paesiorigine is "Italia" }',
    ],
)
def test_reviewed_finite_predicate_is_authorized_only_as_include(surface: str) -> None:
    source = f"""metis 0.43
endpoint demo.test as demo_test {{
  take 20 from @play-demo.video
  {surface}
  return response.expanded
}}
"""
    assert adjudicate_candidate(source, _grounding("Italia")).ok


@pytest.mark.parametrize(
    "surface",
    [
        'exclude where @paesiorigine is "Italia"',
        'exclude where { @paesiorigine is "Italia" }',
        'exclude if @enabled exists { @paesiorigine is "Italia" }',
        'exclude at least 1 of { @paesiorigine is "Italia" }',
        'promote where @paesiorigine is "Italia"',
        'promote where { @paesiorigine is "Italia" }',
        'promote if @enabled exists { @paesiorigine is "Italia" }',
        'promote at least 1 of { @paesiorigine is "Italia" }',
    ],
)
def test_exclude_and_promote_finite_predicates_are_not_grounding_authority(
    surface: str,
) -> None:
    source = f"""metis 0.43
endpoint demo.test as demo_test {{
  take 20 from @play-demo.video
  {surface}
  return response.expanded
}}
"""
    result = adjudicate_candidate(source, _grounding("Italia"))
    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["parse_error"].endswith("finite predicates are not authorized")


def test_tenant_pagination_requires_bare_page_and_ignores_text_trivia() -> None:
    source = """metis 0.43
endpoint demo.test as "take page default 99" {
  // take page default 88
  take /* page default 77 */ page from @play-demo.video include where @paesiorigine is "Italia"
  return response.expanded { note "take page default 66" }
}
"""
    grounding = _grounding("Italia", take={"mode": "page", "page_size": {"mode": "tenant"}})
    assert adjudicate_candidate(source, grounding).ok


def test_tenant_pagination_rejects_local_default() -> None:
    source = """endpoint demo.test as "Test" {
  take page default 20 from @play-demo.video where @paesiorigine is "Italia"
}
"""
    result = adjudicate_candidate(
        source,
        _grounding("Italia", take={"mode": "page", "page_size": {"mode": "tenant"}}),
    )
    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["take"] == {
        "expected": {"mode": "page", "value": None},
        "actual": [{"mode": "page", "value": 20}],
    }


def test_nested_block_take_does_not_replace_endpoint_cardinality() -> None:
    source = """metis 0.43
endpoint demo.target as "Target" {
  block card "Card" {
    take 1 from @play-demo.video
  }
  take 24 from @play-demo.video include where @paesiorigine is "Italia"
  return response.expanded
}
"""
    grounding = _grounding(
        "Italia",
        take={"mode": "count", "value": 24, "source": "existing_source"},
    )
    assert source_take_contract(source, "demo.target") == TakeContract("count", 24)
    assert adjudicate_candidate(source, grounding).ok


def test_nested_take_does_not_hide_duplicate_endpoint_level_cardinality() -> None:
    source = """endpoint demo.target {
  block card { take 1 from @play-demo.video }
  take 24 from @play-demo.video
  take 30 from @play-demo.video
}
"""
    with pytest.raises(BrainError) as raised:
        source_take_contract(source, "demo.target")
    assert raised.value.code == "OUTPUT_CONTRACT_UNAVAILABLE"


@pytest.mark.parametrize(
    "source",
    [
        """metis 0.43
block helper { take 1 from @play-demo.video include where @paesiorigine is "Italia" }
endpoint demo.target {
  take 24 from @play-demo.video
  return response.expanded
}
""",
        """metis 0.43
endpoint demo.target {
  block helper { take 1 from @play-demo.video include where @paesiorigine is "Italia" }
  take 24 from @play-demo.video
  return response.expanded
}
""",
    ],
)
def test_unused_block_cannot_satisfy_endpoint_grounding(source: str) -> None:
    grounding = _grounding(
        "Italia",
        take={"mode": "count", "value": 24, "source": "operator_confirmed"},
    )
    result = adjudicate_candidate(source, grounding)
    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["fields"][0]["missing"] == ["Italia"]


def test_endpoint_take_predicate_satisfies_scoped_grounding() -> None:
    source = """endpoint demo.target {
  block helper { take 1 from @play-demo.video }
  take 24 from @play-demo.video include where @paesiorigine is "Italia"
  return response.expanded
}
"""
    grounding = _grounding(
        "Italia",
        take={"mode": "count", "value": 24, "source": "operator_confirmed"},
    )
    assert adjudicate_candidate(source, grounding).ok


def test_from_all_is_rejected_without_an_explicit_scope_contract() -> None:
    source = """endpoint demo.target {
  take 24 from all @play-demo.video include where @paesiorigine is "Italia"
}
"""
    result = adjudicate_candidate(
        source,
        _grounding(
            "Italia",
            take={"mode": "count", "value": 24, "source": "operator_confirmed"},
        ),
    )

    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["parse_error"] == "from all is not authorized"


@pytest.mark.parametrize(
    "source",
    [
        """endpoint demo.target {
  @mood is "BAD"
  take 24 from @play-demo.video include where @paesiorigine is "Italia"
}
""",
        """endpoint demo.target {
  take 24 from @play-demo.video {
    include where @paesiorigine is "Italia"
  }
  @mood is "BAD"
}
""",
    ],
)
def test_finite_predicate_outside_endpoint_take_is_rejected(source: str) -> None:
    result = adjudicate_candidate(
        source,
        _grounding(
            "Italia",
            take={"mode": "count", "value": 24, "source": "operator_confirmed"},
        ),
    )

    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["parse_error"] == ("finite predicate exists outside the endpoint take")


@pytest.mark.parametrize(
    "source",
    [
        """block helper { take 1 from @play-demo.video include where @paesiorigine is "Italia" }
endpoint demo.target { take 24 from @play-demo.video return response.expanded }
""",
        """endpoint demo.target {
  block helper { take 1 from @play-demo.video include where @paesiorigine is "Italia" }
  take 24 from @play-demo.video
  return response.expanded
}
""",
        """endpoint demo.decoy {
  take 1 from @play-demo.video include where @paesiorigine is "Italia"
}
endpoint demo.target { take 24 from @play-demo.video return response.expanded }
""",
    ],
)
def test_v1_without_take_contract_still_scopes_predicates_to_one_endpoint_take(
    source: str,
) -> None:
    result = adjudicate_candidate(source, _grounding("Italia"))
    assert not result.ok
    assert result.diagnostic is not None


def test_v1_scoped_endpoint_take_accepts_the_expected_predicate() -> None:
    source = """endpoint demo.target {
  block helper { take 1 from @play-demo.video }
  take 24 from @play-demo.video include where @paesiorigine is "Italia"
  return response.expanded
}
"""
    assert adjudicate_candidate(source, _grounding("Italia")).ok


@pytest.mark.parametrize(
    "fallback",
    [
        "fallback to block.zero_results when empty",
        "fallback to materialized.zero_results when page blocks below 1 substitute",
    ],
)
def test_unrequested_fallback_is_rejected_even_when_candidate_otherwise_matches(
    fallback: str,
) -> None:
    source = f"""endpoint demo.target {{
  take 24 from @play-demo.video include where @paesiorigine is "Italia"
  return response {fallback}
}}
"""
    grounding = _grounding(
        "Italia",
        take={"mode": "count", "value": 24, "source": "operator_confirmed"},
    )
    grounding["output_contract"]["fallback"] = {"mode": "none"}
    result = adjudicate_candidate(source, grounding)
    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["fallback"] == {"expected": "none", "actual": "present"}


def test_fallback_none_accepts_absence_and_ignores_comments_and_labels() -> None:
    source = """endpoint demo.target as "fallback is not enabled" {
  // fallback to block.decoy when empty
  take 24 from @play-demo.video include where @paesiorigine is "Italia"
  return response.expanded
}
"""
    grounding = _grounding(
        "Italia",
        take={"mode": "count", "value": 24, "source": "operator_confirmed"},
    )
    grounding["output_contract"]["fallback"] = {"mode": "none"}
    assert adjudicate_candidate(source, grounding).ok


def test_explicit_total_count_requires_take_n_not_pagination() -> None:
    grounding = _grounding(
        "Italia",
        take={"mode": "count", "value": 20, "source": "operator_confirmed"},
    )
    assert adjudicate_candidate(
        """endpoint demo.test as "Test" {
  take 20 from @play-demo.video where @paesiorigine is "Italia"
}
""",
        grounding,
    ).ok
    mismatched = adjudicate_candidate(
        """endpoint demo.test as "Test" {
  take 24 from @play-demo.video where @paesiorigine is "Italia"
}
""",
        grounding,
    )
    assert not mismatched.ok
    paginated = adjudicate_candidate(
        """endpoint demo.test as "Test" {
  take page default 20 from @play-demo.video where @paesiorigine is "Italia"
}
""",
        grounding,
    )
    assert not paginated.ok


def test_page_defaults_in_comments_and_strings_do_not_satisfy_local_contract() -> None:
    source = """endpoint demo.test as "take page" {
  /* take page default 20 */
  take page from @play-demo.video where @paesiorigine is "Italia"
}
"""
    result = adjudicate_candidate(
        source,
        _grounding(
            "Italia",
            take={
                "mode": "page",
                "page_size": {
                    "mode": "local_default",
                    "value": 20,
                    "source": "operator_confirmed",
                },
            },
        ),
    )
    assert not result.ok


def test_take_contract_rejects_second_endpoint_decoy() -> None:
    source = """metis 0.43
endpoint demo.real as "Real" {
  take 1 from @play-demo.video where @paesiorigine is "Italia"
}
endpoint demo.decoy as "Decoy" {
  take 20 from @play-demo.video where @paesiorigine is "Italia"
}
"""
    result = adjudicate_candidate(
        source,
        _grounding("Italia", take={"mode": "count", "value": 20, "source": "operator_confirmed"}),
    )
    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["parse_error"] == "candidate must contain exactly one endpoint"


def test_existing_source_take_selects_exact_endpoint_from_multi_endpoint_file() -> None:
    source = """metis 0.43
// endpoint demo.target { take 999 from @users }
endpoint demo.other as "take 888" {
  take page default 12 from @play-demo.video
}
endpoint demo.target as "Target" {
  take 24 from @play-demo.video
  return response.expanded { note "take page default 77" }
}
"""
    assert source_take_contract(source, "demo.target") == TakeContract("count", 24)
    assert source_take_contract(source, "demo.other") == TakeContract("page", 12)


def test_existing_source_catalogs_select_exact_endpoint_and_ignore_decoys() -> None:
    source = """metis 0.43
// endpoint demo.target { take 1 from @comment }
endpoint demo.other { take 1 from @users }
endpoint demo.target as "from @label" {
  inputs { free_text text default "" }
  take 24 from @play-demo.video {
    include where { @title is "from @string" }
    fallback { take 1 from @play-demo.archive }
  }
}
"""

    assert source_endpoint_catalogs(source, "demo.target") == (
        "play-demo.video",
        "play-demo.archive",
    )


def test_empty_source_string_does_not_relax_empty_predicate_rejection() -> None:
    result = adjudicate_candidate('@paesiorigine is ""', _grounding("ITALIA"))
    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["parse_error"] == "empty literal is not authorized"


@pytest.mark.parametrize(
    "source",
    [
        "endpoint demo.other { take 1 from @video }",
        "endpoint demo.target { take 1 from @video } endpoint demo.target { take 1 from @users }",
        "endpoint demo.target { take 1 from all }",
        "endpoint demo.target { take 1 from @video /*",
    ],
)
def test_existing_source_catalogs_fail_closed_on_untrusted_target_surface(source: str) -> None:
    with pytest.raises(BrainError) as raised:
        source_endpoint_catalogs(source, "demo.target")
    assert raised.value.code == "CATALOG_CONTEXT_UNAVAILABLE"


def test_existing_source_take_preserves_bare_pagination() -> None:
    source = """endpoint demo.target as \"Target\" {
  take page from @play-demo.video
}
"""
    assert source_take_contract(source, "demo.target") == TakeContract("page")


@pytest.mark.parametrize(
    "source, endpoint",
    [
        ("endpoint demo.other { take 20 from @play-demo.video }", "demo.target"),
        (
            """endpoint demo.target { take 20 from @play-demo.video }
endpoint demo.target { take 20 from @play-demo.video }
""",
            "demo.target",
        ),
        ("endpoint demo.target { return response.expanded }", "demo.target"),
        (
            "endpoint demo.target { take 20 from @video take 30 from @video }",
            "demo.target",
        ),
    ],
)
def test_existing_source_take_fails_closed_when_identity_or_take_is_not_unique(
    source: str, endpoint: str
) -> None:
    with pytest.raises(BrainError) as raised:
        source_take_contract(source, endpoint)
    assert raised.value.code == "OUTPUT_CONTRACT_UNAVAILABLE"


def test_existing_source_authority_is_accepted_and_still_exact() -> None:
    grounding = _grounding(
        "Italia",
        take={"mode": "count", "value": 24, "source": "existing_source"},
    )
    assert adjudicate_candidate(
        """endpoint demo.target {
  take 24 from @play-demo.video where @paesiorigine is "Italia"
}
""",
        grounding,
    ).ok
    assert not adjudicate_candidate(
        """endpoint demo.target {
  take page default 24 from @play-demo.video where @paesiorigine is "Italia"
}
""",
        grounding,
    ).ok


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


@pytest.mark.parametrize(
    "take_line",
    [
        'take 20 from list.any include where @paesiorigine is "Italia"',
        'take 20 include where @paesiorigine is "Italia"',
        'take 20 from @video from @video include where @paesiorigine is "Italia"',
    ],
)
def test_endpoint_take_requires_exactly_one_authorized_catalog_source(
    take_line: str,
) -> None:
    result = adjudicate_candidate(
        f"endpoint demo.test {{ {take_line} }}",
        _grounding("Italia"),
    )
    assert not result.ok
    assert result.diagnostic is not None
    assert result.diagnostic["catalog_source"]["expected"] == (
        "exactly_one_authorized_catalog_source"
    )


def test_exact_endpoint_fallback_probe_ignores_other_endpoints_comments_and_labels() -> None:
    source = """endpoint demo.other {
  take 1 from @video
  return response fallback to block.empty when empty
}
endpoint demo.target as "fallback label only" {
  // fallback to block.decoy when empty
  take 20 from @video
  return response.expanded
}
endpoint demo.with_fallback {
  take 20 from @video
  return response fallback to block.empty when empty
}
"""
    assert source_endpoint_has_fallback(source, "demo.target") is False
    assert source_endpoint_has_fallback(source, "demo.with_fallback") is True


def test_candidate_shape_oracle_ignores_comments_and_labels_but_reads_real_tokens() -> None:
    source = """metis 0.43
endpoint demo.target as "response.expanded order by decoy" {
  take 24 from @video as items "Etichetta libera" {
    include where {
      @mood is "Romantico"
    }
    // order by @decoy ascending; return response.default
    order by @publication_date descending
    return response.expanded
  }
}
"""
    assert adjudicate_candidate_shape(
        source,
        endpoint="demo.target",
        take_mode="count",
        take_value=24,
        order_field="publication_date",
        order_direction="descending",
        response="response.expanded",
    ).ok


@pytest.mark.parametrize(
    "replacement",
    [
        "order by @publication_date ascending",
        "order by @title descending",
        "return response.default",
    ],
)
def test_candidate_shape_oracle_rejects_wrong_order_or_response(replacement: str) -> None:
    source = """metis 0.43
endpoint demo.target {
  take 24 from @video {
    include where { @mood is "Romantico" }
    order by @publication_date descending
    return response.expanded
  }
}
"""
    original = (
        "return response.expanded"
        if replacement.startswith("return")
        else "order by @publication_date descending"
    )
    result = adjudicate_candidate_shape(
        source.replace(original, replacement),
        endpoint="demo.target",
        take_mode="count",
        take_value=24,
        order_field="publication_date",
        order_direction="descending",
        response="response.expanded",
    )
    assert not result.ok


def test_candidate_shape_oracle_rejects_wrong_take_count() -> None:
    source = """metis 0.43
endpoint demo.target {
  take 12 from @video {
    include where { @mood is "Romantico" }
    order by @publication_date descending
    return response.expanded
  }
}
"""
    result = adjudicate_candidate_shape(
        source,
        endpoint="demo.target",
        take_mode="count",
        take_value=24,
        order_field="publication_date",
        order_direction="descending",
        response="response.expanded",
    )
    assert not result.ok
