from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from metis_model1.brain_create_stage_authority import (
    CREATE_STAGE_AUTHORITY_CONTRACT,
    CREATE_STAGE_AUTHORITY_PATH,
    CREATE_STAGE_MODEL_PROJECTION_CONTRACT,
    CreateStageAuthorityError,
    create_stage_model_payload,
    load_create_stage_authority,
)

PROMPT_CORPUS = Path("examples/metis-brain-hard-prompts.play-prod-v2.json")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _prompt_scope() -> tuple[list[dict[str, Any]], dict[tuple[str, int], str]]:
    corpus = json.loads(PROMPT_CORPUS.read_text(encoding="utf-8"))
    journeys = corpus["zero_generation_scenarios"]
    scope = [
        {
            "endpoint_qualified": journey["endpoint_qualified"],
            "turns": [
                {"turn": turn["turn"], "user_message": turn["user_message"]}
                for turn in journey["turns"]
            ],
        }
        for journey in journeys
    ]
    messages = {
        (journey["endpoint_qualified"], turn["turn"]): turn["user_message"]
        for journey in journeys
        for turn in journey["turns"]
    }
    return scope, messages


def _keys(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        output = set(value)
        for nested in value.values():
            output.update(_keys(nested))
        return output
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        output: set[str] = set()
        for nested in value:
            output.update(_keys(nested))
        return output
    return set()


def _write_tampered(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "tampered.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_fixture_is_exact_prompt_only_ten_by_three_census() -> None:
    bundle = load_create_stage_authority()
    scope, messages = _prompt_scope()

    assert len(bundle.authorities) == 30
    assert len(bundle.oracles) == 30
    endpoints = {authority.endpoint_qualified for authority in bundle.authorities}
    assert len(endpoints) == 10
    assert bundle.provenance == {
        "derivation": "operator-prompts-only",
        "prompt_corpus_path": "examples/metis-brain-hard-prompts.play-prod-v2.json",
        "prompt_scope": (
            "zero_generation_scenarios[].{endpoint_qualified,turns[].{turn,user_message}}"
        ),
        "prompt_scope_sha256": _sha256(scope),
        "endpoint_source_used": False,
        "tenant_used": False,
        "compiler_used": False,
    }

    for endpoint in endpoints:
        stages = [
            authority
            for authority in bundle.authorities
            if authority.endpoint_qualified == endpoint
        ]
        assert [authority.turn for authority in stages] == [2, 3, 4]
        assert [authority.generation for authority in stages] == [0, 1, 2]
        assert stages[0].parent_stage_id is None
        assert stages[1].parent_stage_id == stages[0].stage_id
        assert stages[2].parent_stage_id == stages[1].stage_id

    assert all(
        authority.instructions == messages[(authority.endpoint_qualified, authority.turn)]
        for authority in bundle.authorities
    )
    assert len({authority.stage_id for authority in bundle.authorities}) == 30
    assert {oracle.stage_id for oracle in bundle.oracles} == {
        authority.stage_id for authority in bundle.authorities
    }


def test_every_stage_has_exact_selection_and_at_least_two_distractors() -> None:
    bundle = load_create_stage_authority()

    for authority in bundle.authorities:
        oracle = bundle.oracle(authority.stage_id)
        candidate_handles = {candidate["handle"] for candidate in authority.candidates}
        selected = set(oracle.selected_candidate_handles)
        assert selected <= candidate_handles
        assert len(candidate_handles - selected) == 2
        assert len(oracle.exact_delta["operations"]) == len(selected)
        assert len(authority.requirements) == len(selected)
        assert all(operation.strip() for operation in oracle.exact_delta["operations"])
        assert oracle.authority_sha256 == authority.authority_sha256


@pytest.mark.parametrize(
    ("stage_id", "required_operation"),
    [
        ("play.similar_cinema:T2", "total = 24"),
        ("play.similar_cinema:T3", "take quota = 10"),
        ("play.similar_cinema:T4", "targeting most_recent_film_2"),
        ("play.similar_serie_tv_fiction:T3", "take quota = 9"),
        ("play.similar_serie_tv_fiction:T4", "over-fetch multiplier 2"),
        ("search.filtered_search:T2", "page size = 50"),
        ("search.filtered_search:T3", "take quota = 14"),
        ("search.filtered_search:T4", "all seven routes"),
        ("search.detail:T2", "has_query, has_channel, inf_channel"),
        ("search.detail:T3", "exact count remains unresolved"),
        ("search.detail:T4", "add nine guarded routes"),
        ("play.multiple_block_compleanno:T2", "pagination = snapshot"),
        ("play.multiple_block_compleanno:T3", "take quota = 26"),
        ("play.multiple_block_compleanno:T4", "exact cap values remain unresolved"),
        ("play.multiple_block_dem_titoli_momento:T2", "value = 30"),
        ("play.multiple_block_dem_titoli_momento:T3", "block minimum = 10"),
        ("play.multiple_block_dem_titoli_momento:T4", "personalization then clustering"),
        ("play.tvod_multiple_block:T2", "required genre parameter"),
        ("play.tvod_multiple_block:T3", "add 11 genre instances"),
        ("play.tvod_multiple_block:T4", "targeting tvod_error_page"),
        ("play.multiple_block4_k:T2", "each main row total = 20"),
        ("play.multiple_block4_k:T3", "take quota = 6"),
        ("play.multiple_block4_k:T4", "empty = true"),
        ("play.inf_multiple_block_film_serie:T2", "page row budget = 6"),
        ("play.inf_multiple_block_film_serie:T3", "add 12 instances"),
        ("play.inf_multiple_block_film_serie:T4", "anonymous row order = fixed"),
        ("play.similar_intrat_abtest:T2", "total = 24"),
        ("play.similar_intrat_abtest:T3", "four candidate pools with 50 each"),
        ("play.similar_intrat_abtest:T4", "first 4 and final 24"),
    ],
)
def test_thirty_exact_stage_deltas_have_prompt_derived_sentinel(
    stage_id: str, required_operation: str
) -> None:
    oracle = load_create_stage_authority().oracle(stage_id)
    assert any(required_operation in operation for operation in oracle.exact_delta["operations"])


def test_prompt_underspecification_is_explicit_and_fail_closed() -> None:
    bundle = load_create_stage_authority()
    detail = bundle.oracle("search.detail:T3")
    compleanno = bundle.oracle("play.multiple_block_compleanno:T4")
    filtered = bundle.oracle("search.filtered_search:T4")

    assert any(
        "exact count remains unresolved" in item for item in detail.exact_delta["operations"]
    )
    assert any(
        "exact cap values remain unresolved" in item
        for item in compleanno.exact_delta["operations"]
    )
    assert (
        sum(
            "require separately authorized target" in item
            for item in filtered.exact_delta["operations"]
        )
        == 2
    )
    assert all("take quota = 9" not in item for item in detail.exact_delta["operations"])
    assert all("limit = 24" not in item for item in compleanno.exact_delta["operations"])


def test_model_projection_has_no_oracle_selection_or_provenance() -> None:
    bundle = load_create_stage_authority()
    forbidden = {"expected", "golden", "oracle", "selected", "source", "source_path", "template"}

    for authority in bundle.authorities:
        payload = create_stage_model_payload(bundle, authority.stage_id)
        assert payload["contract_id"] == CREATE_STAGE_MODEL_PROJECTION_CONTRACT
        assert payload["projection_revision"] == authority.authority_sha256
        assert not (_keys(payload) & forbidden)
        assert "selected_candidate_handles" not in json.dumps(payload, ensure_ascii=False)
        assert bundle.oracle(authority.stage_id).oracle_sha256 not in json.dumps(payload)


def test_contract_and_set_hashes_are_stable_and_independent() -> None:
    payload = json.loads(CREATE_STAGE_AUTHORITY_PATH.read_text(encoding="utf-8"))
    bundle = load_create_stage_authority()

    assert payload["contract_id"] == CREATE_STAGE_AUTHORITY_CONTRACT
    assert bundle.authority_set_sha256 == _sha256(payload["authority_stages"])
    assert bundle.oracle_set_sha256 == _sha256(payload["oracle_stages"])
    assert bundle.authority_set_sha256 != bundle.oracle_set_sha256
    assert all(
        authority.authority_sha256 == oracle.authority_sha256
        for authority, oracle in zip(bundle.authorities, bundle.oracles, strict=True)
    )


@pytest.mark.parametrize(
    "mutation",
    ["instruction", "authority_hash", "selection", "oracle_hash", "set_hash"],
)
def test_any_authority_or_oracle_tamper_fails_closed(tmp_path: Path, mutation: str) -> None:
    payload = json.loads(CREATE_STAGE_AUTHORITY_PATH.read_text(encoding="utf-8"))
    tampered = copy.deepcopy(payload)
    if mutation == "instruction":
        tampered["authority_stages"][0]["instructions"] += " alterato"
    elif mutation == "authority_hash":
        tampered["authority_stages"][0]["authority_sha256"] = "sha256:" + "0" * 64
    elif mutation == "selection":
        tampered["oracle_stages"][0]["selected_candidate_handles"] = [999]
    elif mutation == "oracle_hash":
        tampered["oracle_stages"][0]["oracle_sha256"] = "sha256:" + "0" * 64
    else:
        tampered["authority_set_sha256"] = "sha256:" + "0" * 64

    with pytest.raises(CreateStageAuthorityError):
        load_create_stage_authority(_write_tampered(tmp_path, tampered))
