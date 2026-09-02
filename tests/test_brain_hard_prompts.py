"""Contract checks for the inspectable play-prod hard-prompt corpus."""

from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT = ROOT / "examples/metis-brain-hard-prompts.play-prod-v1.json"
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _artifact() -> dict[str, object]:
    value = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_hard_prompt_corpus_has_exact_distinct_rosters() -> None:
    value = _artifact()
    assert value["artifact_id"] == "metis-brain-hard-prompts.play-prod-v1"
    assert value["artifact_version"] == 1

    endpoints = value["endpoints"]
    journeys = value["zero_generation_scenarios"]
    assert isinstance(endpoints, list) and len(endpoints) == 10
    assert isinstance(journeys, list) and len(journeys) == 10

    endpoint_ids = [item["endpoint_identity"]["qualified"] for item in endpoints]
    journey_ids = [item["endpoint_qualified"] for item in journeys]
    edit_prompts = [item["operator_edit_prompt_it"] for item in endpoints]
    assert len(set(endpoint_ids)) == len(endpoint_ids)
    assert len(set(journey_ids)) == len(journey_ids)
    assert set(endpoint_ids) == set(journey_ids)
    assert len(set(edit_prompts)) == len(edit_prompts)

    roster = value["census"]["selected_roster"]
    assert roster == {"in": 10, "out": 10, "distinct": 10, "gaps": 0}


def test_hard_prompt_sources_and_edit_oracles_are_bounded() -> None:
    endpoints = _artifact()["endpoints"]
    for item in endpoints:
        source = PurePosixPath(item["source_path"])
        assert not source.is_absolute()
        assert ".." not in source.parts
        assert source.parts[0] == "properties"
        assert source.suffix == ".metis"
        assert SHA256_RE.fullmatch(item["source_sha256"])
        assert item["operator_edit_prompt_it"].strip()
        for key in (
            "structural_feature_evidence",
            "expected_clarifications",
            "exact_intended_changes",
            "strict_preserve_roster",
            "grounding_oracles",
            "output_oracles",
            "compiler_oracles",
            "draft_only_oracles",
        ):
            assert isinstance(item[key], list) and item[key]
            assert all(isinstance(entry, str) and entry.strip() for entry in item[key])
        assert item["lossless_path"]["decision"] == "fail_closed_fallback"


def test_zero_generation_journeys_are_four_turn_refinements() -> None:
    journeys = _artifact()["zero_generation_scenarios"]
    for item in journeys:
        turns = item["turns"]
        assert len(turns) == 4
        assert [turn["turn"] for turn in turns] == [1, 2, 3, 4]
        assert [turn["expected_brain_action"] for turn in turns] == [
            "clarify",
            "Draft",
            "Draft",
            "Draft",
        ]
        for turn in turns:
            assert turn["user_message"].strip()
            assert turn["expected_delta_from_prior_draft"].strip()
            assert turn["invariants"]
            assert turn["compile_and_oracles"]
        convergence = item["convergence"]
        assert convergence["criterion"].strip()
        assert convergence["universal_capabilities"]


def test_hard_prompt_corpus_declares_read_only_no_apply_boundary() -> None:
    value = _artifact()
    assert value["safety_boundary"] == {
        "tenant_access": "read_only",
        "contains_secrets": False,
        "contains_credentials": False,
        "contains_raw_live_payloads": False,
        "model_or_network_execution": False,
        "apply_authorized": False,
    }
    assert value["tenant_snapshot"]["status"] == "clean"
    assert re.fullmatch(r"[0-9a-f]{40}", value["tenant_snapshot"]["head"])
