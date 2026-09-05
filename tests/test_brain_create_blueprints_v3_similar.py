from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from metis_model1.brain_create_builder import render_create_endpoint

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples/metis-brain-create-blueprints-v3-similar.json"
EXPECTED_STAGE_IDS = (
    "play.similar_cinema:T2",
    "play.similar_cinema:T3",
    "play.similar_cinema:T4",
    "play.similar_serie_tv_fiction:T2",
    "play.similar_serie_tv_fiction:T3",
    "play.similar_serie_tv_fiction:T4",
    "play.similar_intrat_abtest:T2",
    "play.similar_intrat_abtest:T3",
    "play.similar_intrat_abtest:T4",
)
FORBIDDEN_AUTHORITY_KEYS = {
    "code",
    "dsl",
    "file",
    "file_path",
    "golden",
    "golden_source",
    "path",
    "raw",
    "reference_endpoint",
    "source",
    "source_path",
    "source_text",
    "template",
}


def _load() -> dict[str, Any]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _stages() -> dict[str, dict[str, Any]]:
    return {stage["stage_id"]: stage for stage in _load()["stages"]}


def _walk(value: Any) -> list[Any]:
    values = [value]
    if isinstance(value, dict):
        for child in value.values():
            values.extend(_walk(child))
    elif isinstance(value, list):
        for child in value:
            values.extend(_walk(child))
    return values


def _fetches(spec: dict[str, Any]) -> list[dict[str, Any]]:
    endpoint = spec["endpoint"]
    result = [binding["fetch"] for binding in endpoint["context"] if binding["kind"] == "fetch"]
    for container in [*endpoint["blocks"], *endpoint["variants"]]:
        result.extend(container["fetches"])
    return result


def _predicate_nodes(value: Any) -> list[dict[str, Any]]:
    return [
        item
        for item in _walk(value)
        if isinstance(item, dict)
        and isinstance(item.get("op"), str)
        and item["op"]
        in {
            "eq",
            "in",
            "contains",
            "gt",
            "gte",
            "lte",
            "similar",
            "within",
            "exists",
            "match",
            "ids",
            "and",
            "or",
            "group",
        }
    ]


def test_fixture_has_exact_prompt_derived_nine_stage_roster() -> None:
    artifact = _load()

    assert set(artifact) == {"contract_id", "derivation", "stages"}
    assert artifact["contract_id"] == "metis-brain-create-stage-blueprints/v3"
    assert artifact["derivation"] == "operator-prompts-plus-reviewed-catalog-stdlib"
    assert tuple(stage["stage_id"] for stage in artifact["stages"]) == EXPECTED_STAGE_IDS
    assert len(set(EXPECTED_STAGE_IDS)) == 9


def test_ready_specs_render_and_blocked_specs_fail_closed_with_exact_missing_slots() -> None:
    for stage_id, stage in _stages().items():
        assert set(stage) == {"stage_id", "status", "spec", "spec_sha256", "missing"}
        assert stage["status"] in {"ready", "needs_clarification"}
        if stage["status"] == "ready":
            assert stage["missing"] == []
            assert stage["spec"] is not None
            rendered = render_create_endpoint(stage["spec"])
            assert rendered.spec_sha256 == stage["spec_sha256"]
            assert rendered.metis_text.startswith("metis 0.43\n\nendpoint ")
            assert stage["spec"]["endpoint"]["name"] == stage_id.rsplit(":", 1)[0]
        else:
            assert stage["spec"] is None
            assert stage["spec_sha256"] is None
            assert stage["missing"]
            assert all(
                set(item) == {"slot", "introduced_turn", "prompt_excerpt", "reason"}
                for item in stage["missing"]
            )


def test_no_source_template_golden_or_reference_endpoint_authority_is_embedded() -> None:
    artifact = _load()
    for item in _walk(artifact):
        if not isinstance(item, dict):
            continue
        assert FORBIDDEN_AUTHORITY_KEYS.isdisjoint(key.casefold() for key in item)

    serialized = FIXTURE.read_text(encoding="utf-8").casefold()
    assert ".endpoints/" not in serialized
    assert "metis_source" not in serialized
    assert "raw_source" not in serialized


def test_every_stage_preserves_the_prompt_derived_seed_contract() -> None:
    for stage in _stages().values():
        if stage["status"] != "ready":
            continue
        endpoint = stage["spec"]["endpoint"]
        assert endpoint["reference"] is None
        assert endpoint["inputs"] == [
            {
                "name": "seed_id",
                "type": "text",
                "required": True,
                "not_empty": True,
                "default": None,
            }
        ]
        seed = endpoint["context"][0]
        assert seed["kind"] == "fetch"
        assert seed["name"] == "seed"
        assert seed["fetch"]["from"] == {"kind": "catalog", "catalog": "video"}
        assert seed["fetch"]["cardinality"] == {"mode": "total", "value": 1}
        predicate = seed["fetch"]["clauses"][0]["where"][0]
        assert predicate == {
            "op": "eq",
            "field": "video_content_id",
            "value": {"kind": "input", "name": "seed_id"},
        }


def test_cinema_t2_is_ready_but_route_and_external_fallback_authority_remain_blocked() -> None:
    stages = _stages()
    t2 = stages["play.similar_cinema:T2"]["spec"]
    assert render_create_endpoint(t2).stats.fetches == 2
    assert stages["play.similar_cinema:T3"]["status"] == "needs_clarification"
    assert [item["slot"] for item in stages["play.similar_cinema:T3"]["missing"]] == [
        "routes.activation_contract"
    ]
    assert stages["play.similar_cinema:T4"]["status"] == "needs_clarification"
    assert [item["slot"] for item in stages["play.similar_cinema:T4"]["missing"]] == [
        "routes.activation_contract",
        "fallback.most_recent_film_2_binding",
    ]


def test_series_t2_is_ready_but_named_routes_without_guards_remain_blocked() -> None:
    stages = _stages()
    t2 = stages["play.similar_serie_tv_fiction:T2"]["spec"]
    assert render_create_endpoint(t2).stats.fetches == 2
    for turn in (3, 4):
        stage = stages[f"play.similar_serie_tv_fiction:T{turn}"]
        assert stage["status"] == "needs_clarification"
        assert [item["slot"] for item in stage["missing"]] == ["routes.activation_contract"]


def test_intrattenimento_stages_preserve_four_pools_and_exact_consumer_contract() -> None:
    stages = _stages()
    t2 = stages["play.similar_intrat_abtest:T2"]["spec"]
    t3 = stages["play.similar_intrat_abtest:T3"]["spec"]
    t4 = stages["play.similar_intrat_abtest:T4"]["spec"]

    assert render_create_endpoint(t2).stats.fetches == 2
    assert render_create_endpoint(t3).stats.fetches == 6
    assert render_create_endpoint(t4).stats.fetches == 7
    assert t3["endpoint"]["context"][0] == t2["endpoint"]["context"][0]
    assert t3["endpoint"]["blocks"] == t2["endpoint"]["blocks"]
    assert t4["endpoint"]["context"] == t3["endpoint"]["context"]
    assert t3["endpoint"]["needs_time"] is True
    pools = t3["endpoint"]["context"][1:]
    assert [pool["name"] for pool in pools] == [
        "pool_same_program",
        "pool_clips_extra",
        "pool_entertainment_episodes",
        "pool_entertainment_clips",
    ]
    assert all(pool["fetch"]["cardinality"] == {"mode": "total", "value": 50} for pool in pools)
    assert all(pool["fetch"]["group_by"]["fields"] == ["id_brand"] for pool in pools)

    assert t4["endpoint"]["blocks"] == []
    assert [variant["name"] for variant in t4["endpoint"]["variants"]] == ["default"]
    main = t4["endpoint"]["variants"][0]["blocks"][0]
    consumer = main["fetches"]
    assert [fetch["cardinality"]["value"] for fetch in consumer] == [4, 24]
    for fetch in consumer:
        alternatives = fetch["clauses"][0]["where"][0]
        assert alternatives["strategy"] == "best_plus"
        assert alternatives["coefficient"] == "near_full"
        assert [item["segments"] for item in alternatives["items"]] == [
            ["pool_same_program"],
            ["pool_clips_extra"],
            ["pool_entertainment_episodes"],
            ["pool_entertainment_clips"],
        ]
    assert consumer[1]["output"] is None
    final_flow = main["output"]
    assert final_flow["steps"] == [
        {"kind": "deduplicate", "field": "video_content_id"},
        {"kind": "max", "count": 24},
    ]
    assert final_flow["fallbacks"] == [
        {
            "kind": "materialized",
            "target": "intrat_recent",
            "trigger": "nested_flat_items_below",
            "threshold": 1,
            "mode": "append",
        }
    ]
