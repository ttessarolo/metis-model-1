"""Strict pre-output contract checks for the public-synthetic grammar/stdlib D18."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

FIXTURE = Path(__file__).parents[1] / "fixtures/grammar-stdlib-accuracy-v1/d18-tasks.json"
FAMILIES = tuple(f"F-{number}" for number in range(1, 7))
SOURCE_FAMILIES = {"F-1", "F-2", "F-3", "F-5"}
REVIEW_FAMILIES = {"F-4", "F-6"}
TOP_LEVEL_PATTERNS = {
    "Tenant": r"(?m)^tenant\s+",
    "Catalog": r"(?m)^catalog\s+",
    "Property": r"(?m)^property\s+",
    "Endpoint": r"(?m)^endpoint\s+",
    "Preset": r"(?m)^preset\s+",
    "List": r"(?m)^list\s+",
    "Transformer": r"(?m)^transformer\s+",
    "NamedBlock": r"(?m)^block\s+",
    "SettingsDecl": r"(?m)^settings\s+",
    "ValueSet": r"(?m)^values\s+",
}
STDLIB_MEMBER_PATTERNS = {
    "time.now": r"\btime\.now\b",
    "time.month": r"\btime\.month\b",
    "time.day": r"\btime\.day\b",
    "time.hour": r"\btime\.hour\b",
    "time.hhmm": r"\btime\.hhmm\b",
    "time.weekday": r"\btime\.weekday\b",
    "time.fractional_second": r"\btime\.fractional_second\b",
    "codec.decode": r"\bstd\.codec\.decode\b",
    "codec.encode": r"\bstd\.codec\.encode\b",
    "text.slugify": r"\bstd\.text\.slugify\b",
    "text.truncate": r"\bstd\.text\.truncate\b",
    "text.normalize": r"\bstd\.text\.normalize\b",
}
STDLIB_SETTING_PATTERNS = {
    "time.timezone": r"(?s)settings\s+gsl_d18\.time\s*\{.*?\btimezone\s+\"",
}
ACTUAL_DIAGNOSTIC_SUBSTRINGS = {
    "non dichiara `needs time`",
    "`std.codec.nope` non esiste",
    "`time` è una capability AMBIENTALE",
    "`codec` è un modulo PURO",
    "Expecting token of type '}' but found `url`.",
}
EXPECTED_OUTPUT_DIAGNOSTIC_SUBSTRINGS = {
    "`preset gsl_d18.featured` non è mai usato",
}


def _roster() -> dict[str, Any]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _source_fields(task: dict[str, Any]) -> list[str]:
    fields = ("input_source", "before_source", "expected_source", "expected_repaired_source")
    values = [task[field] for field in fields if field in task]
    assert all(isinstance(value, str) and value for value in values)
    return values


def _has_semantic_occurrence(task: dict[str, Any], pattern: str) -> bool:
    return any(re.search(pattern, source) is not None for source in _source_fields(task))


def test_d18_preoutput_identity_and_exact_denominators() -> None:
    roster = _roster()
    assert roster["schema_version"] == 2
    assert roster["roster_id"] == "gsl_d18_public_synthetic_v2"
    assert roster["provenance"] == {
        "kind": "public_synthetic",
        "namespace": "gsl_d18",
        "pin_revision": "5e112f9148f40e7e792052e896c5a9efe8eaf0a2",
        "language_version": "0.43",
        "source_validation": "pinned_oracle_required_before_truth",
        "model_outputs_observed": False,
        "training_input_allowed": False,
    }
    tasks = roster["tasks"]
    assert isinstance(tasks, list)
    assert len(tasks) == 18
    assert Counter(task["family"] for task in tasks) == {family: 3 for family in FAMILIES}


def test_d18_has_the_required_twelve_to_six_task_mode_partition() -> None:
    tasks = _roster()["tasks"]
    assert Counter(task["task_mode"] for task in tasks) == {
        "source_output": 12,
        "exact_json_review": 6,
    }
    for task in tasks:
        if task["family"] in SOURCE_FAMILIES:
            assert task["task_mode"] == "source_output"
        if task["family"] in REVIEW_FAMILIES:
            assert task["task_mode"] == "exact_json_review"


def test_json_review_prompts_define_the_exact_contract_and_bounded_choices() -> None:
    for task in _roster()["tasks"]:
        if task["task_mode"] != "exact_json_review":
            continue
        prompt = task["prompt"]
        assert "exactly the keys" in prompt
        assert "training_label_eligible" in prompt
        assert "false" in prompt
        for key, value in task["expected_json"].items():
            assert f"`{key}`" in prompt
            if isinstance(value, str):
                assert f"`{value}`" in prompt
            elif isinstance(value, list):
                assert all(item in prompt for item in value)


def test_task_shape_headers_source_mode_and_authority_tiers_are_fail_closed() -> None:
    required = {
        "task_id",
        "family",
        "kind",
        "task_mode",
        "authority_tier",
        "prompt",
        "oracle",
        "coverage",
        "provenance_roots",
        "model_outputs_observed",
        "training_input_allowed",
        "training_label_eligible",
    }
    expected_tiers = {
        "F-1": "pinned_oracle_required",
        "F-2": "pinned_oracle_required",
        "F-3": "pinned_oracle_required",
        "F-4": "diagnostic_only",
        "F-5": "human_review_required",
        "F-6": "human_review_required",
    }
    for task in _roster()["tasks"]:
        assert required <= set(task)
        assert task["task_id"].startswith("gsl_d18_")
        assert task["family"] in FAMILIES
        assert task["authority_tier"] == expected_tiers[task["family"]]
        assert task["model_outputs_observed"] is False
        assert task["training_input_allowed"] is False
        assert task["training_label_eligible"] is False
        oracle = task["oracle"]
        assert set(oracle) == {
            "mode",
            "input_status",
            "input_failure_kind",
            "diagnostic_substrings",
        } | ({"target"} if oracle["mode"] == "endpoint" else set()) | (
            {"expected_diagnostic_substrings"}
            if oracle.get("expected_diagnostic_substrings") is not None
            else set()
        )
        assert oracle["mode"] in {"source", "endpoint"}
        if oracle["mode"] == "endpoint":
            assert isinstance(oracle["target"], str) and oracle["target"].startswith("gsl_d18.")
        else:
            assert "target" not in oracle
        assert oracle["input_status"] == "pinned_oracle_required_before_truth"
        assert isinstance(oracle["diagnostic_substrings"], list)
        if "expected_diagnostic_substrings" in oracle:
            assert set(oracle["expected_diagnostic_substrings"]) <= (
                EXPECTED_OUTPUT_DIAGNOSTIC_SUBSTRINGS
            )
        if oracle["diagnostic_substrings"]:
            assert oracle["input_failure_kind"] in {"parser", "link", "validation"}
        else:
            assert oracle["input_failure_kind"] is None
        for source in _source_fields(task):
            assert source.startswith("metis 0.43\n")
        if task["task_mode"] == "source_output":
            assert isinstance(task.get("expected_source"), str)
            assert "expected_json" not in task
        else:
            assert isinstance(task.get("expected_json"), dict)
            assert "expected_source" not in task
        if task["family"] == "F-4":
            assert task["expected_json"]["classification"] == "diagnostic_only"
            assert task["expected_json"]["training_label_eligible"] is False
        if task["family"] in {"F-5", "F-6"}:
            assert task["authority_tier"] == "human_review_required"
            assert task["training_label_eligible"] is False


def test_coverage_is_backed_by_real_source_occurrences_not_prompts() -> None:
    tasks = _roster()["tasks"]
    top_levels = {top for task in tasks for top in task["coverage"]["top_levels"]}
    members = {member for task in tasks for member in task["coverage"]["stdlib_members"]}
    settings = {setting for task in tasks for setting in task["coverage"]["stdlib_settings"]}
    assert top_levels == set(TOP_LEVEL_PATTERNS)
    assert members == set(STDLIB_MEMBER_PATTERNS)
    assert settings == set(STDLIB_SETTING_PATTERNS)
    assert (len(top_levels), len(members), len(settings)) == (10, 12, 1)
    for task in tasks:
        coverage = task["coverage"]
        assert set(coverage) == {"top_levels", "stdlib_members", "stdlib_settings"}
        for top_level in coverage["top_levels"]:
            assert _has_semantic_occurrence(task, TOP_LEVEL_PATTERNS[top_level])
        for member in coverage["stdlib_members"]:
            assert _has_semantic_occurrence(task, STDLIB_MEMBER_PATTERNS[member])
        for setting in coverage["stdlib_settings"]:
            assert _has_semantic_occurrence(task, STDLIB_SETTING_PATTERNS[setting])


def test_value_set_tasks_use_the_canonical_external_domain_pairing() -> None:
    value_set_tasks = [
        task for task in _roster()["tasks"] if "ValueSet" in task["coverage"]["top_levels"]
    ]
    assert {task["task_id"] for task in value_set_tasks} == {
        "gsl_d18_f1_01",
        "gsl_d18_f6_01",
    }
    for task in value_set_tasks:
        source = "\n".join(_source_fields(task))
        assert "status keyword enum(1)" in source
        assert 'status editorial ["synthetic"]' in source
        assert 'id editorial ["1"]' not in source


def test_invalid_inputs_name_only_real_pinned_diagnostic_substrings() -> None:
    for task in _roster()["tasks"]:
        oracle_substrings = task["oracle"]["diagnostic_substrings"]
        if "before_source" not in task:
            assert oracle_substrings == []
            continue
        assert oracle_substrings
        assert set(oracle_substrings) <= ACTUAL_DIAGNOSTIC_SUBSTRINGS
        assert all("GSL_D18_" not in marker for marker in oracle_substrings)
        if task["task_mode"] == "exact_json_review":
            assert task["expected_json"]["diagnostic_substrings"] == oracle_substrings


def test_fresh_names_and_roots_are_unique_and_non_reserved() -> None:
    roster = _roster()
    tasks = roster["tasks"]
    independent = [task["provenance_roots"]["independent"] for task in tasks]
    templates = [task["provenance_roots"]["template"] for task in tasks]
    assert len(independent) == len(set(independent)) == 18
    assert len(templates) == len(set(templates)) == 18
    assert not set(independent) & set(templates)
    serialized = json.dumps(roster, ensure_ascii=False, sort_keys=True)
    assert "GSL_D18_" not in serialized
    assert "gsl_d18.catalog" not in serialized
    assert "gsl_d18.feed" not in serialized
    assert "play-" not in serialized.lower()
    for segment in re.findall(r"\bgsl_d18\.([A-Za-z_][A-Za-z0-9_]*)", serialized):
        assert segment not in {"catalog", "feed"}


def test_source_targets_do_not_hide_synthetic_identifiers_from_the_request() -> None:
    for task in _roster()["tasks"]:
        if task["task_mode"] != "source_output":
            continue
        request = task["prompt"] + "\n" + task.get("before_source", "")
        target_identifiers = set(
            re.findall(
                r"\bgsl_d18(?:\.[A-Za-z_][A-Za-z0-9_]*|_[A-Za-z0-9_]+)",
                task["expected_source"],
            )
        )
        assert target_identifiers
        assert all(identifier in request for identifier in target_identifiers)
