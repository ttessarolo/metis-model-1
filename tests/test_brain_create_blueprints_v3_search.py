"""Prompt-provenance gate for the six independently audited search stages.

Only jq's exact allowlisted prompt projection is exposed to these tests. No
tenant checkout, existing endpoint, compiler, model or qualification oracle is
loaded. A null specification is a blocked blueprint, never a rendering proof.
"""

from __future__ import annotations

import copy
import json
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from metis_model1.brain_create_builder import (
    CREATE_ENDPOINT_SPEC_SCHEMA,
    CreateBuilderError,
    render_create_endpoint,
)

ROOT = Path(__file__).resolve().parents[1]
BLUEPRINT_PATH = ROOT / "examples/metis-brain-create-blueprints-v3-search.json"
PROMPT_PATH = ROOT / "examples/metis-brain-hard-prompts.play-prod-v2.json"
ENDPOINTS = ("search.filtered_search", "search.detail")
STAGE_IDS = tuple(f"{endpoint}:T{turn}" for endpoint in ENDPOINTS for turn in (2, 3, 4))
PROMPT_PROJECTION = """
[
  .zero_generation_scenarios[]
  | select(
      .endpoint_qualified == "search.filtered_search"
      or .endpoint_qualified == "search.detail"
    )
  | {
      endpoint_qualified,
      turns: [.turns[] | {turn, user_message}]
    }
]
"""

SLOTS_BY_TURN = {
    "search.filtered_search": {
        2: (
            "normalization.transformer_binding",
            "search.matching_contract",
            "response.projection",
        ),
        3: (
            "routes.selectors_and_content_predicates",
            "routes.take_allocation",
            "query_alternatives.ranking_contract",
        ),
        4: (
            "routes.view_all_targets",
            "routes.empty_page_fallback_targets",
            "default.flat_items_fallback_target",
        ),
    },
    "search.detail": {
        2: (
            "inputs.variant_and_4k_contract",
            "attributes.presence_guards",
            "attributes.inf_channel_guard",
            "response.cardinality_and_projection",
        ),
        3: ("blocks.take_roster_and_predicates", "blocks.deduplication_identity"),
        4: (
            "variants.infinity_selectors",
            "variants.block_routing",
            "variants.clip_fep_movie_metadata",
        ),
    },
}


@pytest.fixture(scope="module")
def blueprints() -> dict[str, Any]:
    return json.loads(BLUEPRINT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def prompts() -> dict[str, dict[int, str]]:
    # Keep extraction at the process boundary: do not load the unprojected file.
    completed = subprocess.run(
        ["jq", "-e", PROMPT_PROJECTION, str(PROMPT_PATH)],
        capture_output=True,
        check=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )
    projected = json.loads(completed.stdout)
    assert [entry["endpoint_qualified"] for entry in projected] == list(ENDPOINTS)
    assert all(set(entry) == {"endpoint_qualified", "turns"} for entry in projected)
    result = {}
    for entry in projected:
        assert [turn["turn"] for turn in entry["turns"]] == [1, 2, 3, 4]
        assert all(set(turn) == {"turn", "user_message"} for turn in entry["turns"])
        result[entry["endpoint_qualified"]] = {
            turn["turn"]: turn["user_message"] for turn in entry["turns"]
        }
    return result


def _stage(blueprints: dict[str, Any], stage_id: str) -> dict[str, Any]:
    return next(stage for stage in blueprints["stages"] if stage["stage_id"] == stage_id)


def _assert_stage_contract(stage: dict[str, Any]) -> None:
    assert set(stage) == {
        "stage_id",
        "endpoint_qualified",
        "turn",
        "parent_stage_id",
        "status",
        "spec",
        "spec_sha256",
        "required_counts",
        "missing",
    }
    endpoint = stage["endpoint_qualified"]
    turn = stage["turn"]
    assert endpoint in ENDPOINTS
    assert type(turn) is int and turn in (2, 3, 4)
    assert stage["stage_id"] == f"{endpoint}:T{turn}"
    assert stage["parent_stage_id"] == (None if turn == 2 else f"{endpoint}:T{turn - 1}")
    assert stage["status"] in {"ready", "needs_clarification"}
    assert isinstance(stage["missing"], list)
    if stage["status"] == "needs_clarification":
        assert stage["missing"], "blocked stages must identify exact unresolved slots"
        assert stage["spec"] is None, "blocked stages must not expose a speculative spec"
        assert stage["spec_sha256"] is None, "blocked stages must not claim a spec hash"
    else:
        assert not stage["missing"], "ready stages cannot carry unresolved authority"
        Draft202012Validator(CREATE_ENDPOINT_SPEC_SCHEMA).validate(stage["spec"])
        rendered = render_create_endpoint(stage["spec"])
        assert stage["spec"]["endpoint"]["name"] == endpoint
        assert stage["spec_sha256"] == rendered.spec_sha256


def _counts_from_prompts(messages: dict[int, str], through_turn: int) -> dict[str, int]:
    """Recompute the explicit number scopes without consulting fixture values."""
    cumulative = "\n".join(messages[turn] for turn in range(1, through_turn + 1))
    result = {}
    page = re.search(r"\b([0-9]+) risultati per pagina\b", cumulative)
    if page:
        result["results_per_page"] = int(page.group(1))
    for phrase, key, count in (
        ("sette percorsi distinti", "routes", 7),
        ("quattordici take", "take_statements", 14),
        ("elementi piatti sono meno di uno", "default_flat_items_below", 1),
        ("tre blocchi riusabili", "reusable_blocks", 3),
        ("nove varianti", "routed_variants", 9),
        ("tre percorsi Infinity", "infinity_variants", 3),
    ):
        if phrase in cumulative:
            result[key] = count
    return result


def test_exact_six_stage_contract_and_read_boundary(blueprints: dict[str, Any]) -> None:
    assert set(blueprints) == {"schema_version", "contract_id", "authority", "stages"}
    assert blueprints["schema_version"] == 3
    assert blueprints["contract_id"] == "metis-brain-create-stage-blueprints/v3"
    assert [stage["stage_id"] for stage in blueprints["stages"]] == list(STAGE_IDS)
    assert len({stage["stage_id"] for stage in blueprints["stages"]}) == 6
    authority = blueprints["authority"]
    assert authority["prompt_file"] == "examples/metis-brain-hard-prompts.play-prod-v2.json"
    assert authority["prompt_projection"] == (
        "zero_generation_scenarios[].{endpoint_qualified,turns[].{turn,user_message}}"
    )
    assert authority["endpoint_allowlist"] == list(ENDPOINTS)
    assert authority["tenant_declarations_reviewed"] == [
        "catalogs/video.metis",
        "catalogs/video.values.metis",
        "lib/lists.metis",
        "lib/presets.metis",
        "lib/presets.migrated.metis",
        "_tenant.metis",
    ]
    assert all(stage["status"] == "needs_clarification" for stage in blueprints["stages"])


@pytest.mark.parametrize("stage_id", STAGE_IDS)
def test_stage_has_exact_cumulative_prompt_authority(
    blueprints: dict[str, Any], prompts: dict[str, dict[int, str]], stage_id: str
) -> None:
    stage = _stage(blueprints, stage_id)
    _assert_stage_contract(stage)
    endpoint = stage["endpoint_qualified"]
    turn = stage["turn"]
    expected = {
        slot: introduced_turn
        for introduced_turn, slots in SLOTS_BY_TURN[endpoint].items()
        if introduced_turn <= turn
        for slot in slots
    }
    assert len(stage["missing"]) == len(expected)
    assert {missing["slot"]: missing["introduced_turn"] for missing in stage["missing"]} == (
        expected
    )
    for missing in stage["missing"]:
        assert set(missing) == {"slot", "introduced_turn", "prompt_excerpt", "reason"}
        assert missing["prompt_excerpt"]
        assert missing["prompt_excerpt"] in prompts[endpoint][missing["introduced_turn"]]
        assert isinstance(missing["reason"], str) and missing["reason"].strip()
    assert stage["required_counts"] == _counts_from_prompts(prompts[endpoint], turn)
    if turn > 2:
        parent = _stage(blueprints, stage["parent_stage_id"])
        inherited = {missing["slot"]: missing for missing in stage["missing"]}
        assert all(inherited[missing["slot"]] == missing for missing in parent["missing"])


@pytest.mark.parametrize("stage_id", STAGE_IDS)
def test_blocked_spec_cannot_be_rendered(blueprints: dict[str, Any], stage_id: str) -> None:
    with pytest.raises(CreateBuilderError):
        render_create_endpoint(_stage(blueprints, stage_id)["spec"])


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("spec", {}, "speculative spec"),
        ("spec_sha256", "sha256:" + "0" * 64, "claim a spec hash"),
        ("missing", [], "exact unresolved slots"),
        ("status", "ready", "unresolved authority"),
    ],
)
def test_no_speculative_promotion_of_a_blocked_stage(
    blueprints: dict[str, Any], field: str, value: Any, message: str
) -> None:
    stage = copy.deepcopy(_stage(blueprints, "search.filtered_search:T2"))
    stage[field] = value
    with pytest.raises(AssertionError, match=message):
        _assert_stage_contract(stage)


def test_cardinality_and_later_turns_do_not_cross_journeys(
    blueprints: dict[str, Any], prompts: dict[str, dict[int, str]]
) -> None:
    filtered_t2 = _stage(blueprints, "search.filtered_search:T2")
    assert filtered_t2["required_counts"] == {"results_per_page": 50}
    assert all(missing["introduced_turn"] == 2 for missing in filtered_t2["missing"])
    detail_t4 = _stage(blueprints, "search.detail:T4")
    assert "results_per_page" not in detail_t4["required_counts"]
    assert "take_statements" not in detail_t4["required_counts"]
    assert "normalization.transformer_binding" not in {
        missing["slot"] for missing in detail_t4["missing"]
    }
    assert "normalizza" not in " ".join(prompts["search.detail"].values())
