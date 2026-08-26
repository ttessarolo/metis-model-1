"""Focused synthetic contracts for the fresh grammar/stdlib T30-v3 wrapper."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from metis_model1 import grammar_stdlib_t30 as core
from metis_model1 import grammar_stdlib_t30_v3 as v3


def _truth(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {
        "tasks": tasks,
    }
    value["truth_sha256"] = core.canonical_hash(value)
    return value


def _freshness_task(task_id: str, prompt: str) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "family": "F-1",
        "kind": "author_source",
        "task_mode": "source_output",
        "prompt": prompt,
        "oracle": {"mode": "source"},
        "expected_source": "metis 0.43\nendpoint heldout {}",
    }


def _patch_freshness_sources(
    monkeypatch: pytest.MonkeyPatch,
    *,
    v1_tasks: list[dict[str, Any]] | None = None,
    v2_tasks: list[dict[str, Any]] | None = None,
    v1_truth: dict[str, Any] | None = None,
    v2_truth: dict[str, Any] | None = None,
) -> None:
    v1_tasks = [] if v1_tasks is None else v1_tasks
    v2_tasks = [] if v2_tasks is None else v2_tasks
    v1_truth = _truth([]) if v1_truth is None else v1_truth
    v2_truth = _truth([]) if v2_truth is None else v2_truth

    def load(path, _label):
        if path == v3.V1_TASKS_PATH:
            return {"tasks": v1_tasks}, b"v1-tasks"
        if path == v3.V2_TASKS_PATH:
            return {"tasks": v2_tasks}, b"v2-tasks"
        if path == v3.V1_TRUTH_PATH:
            return v1_truth, b"v1-truth"
        if path == v3.V2_TRUTH_PATH:
            return v2_truth, b"v2-truth"
        raise AssertionError(path)

    monkeypatch.setattr(core, "_load", load)
    monkeypatch.setattr(core.d18, "load_tasks", lambda: ({}, [], b""))
    monkeypatch.setattr(core.d18, "_load", lambda *_args: ({"tasks": []}, b""))
    monkeypatch.setattr(core.d18, "build_messages", lambda _task: [])
    monkeypatch.setattr(core.qlora, "_check_receipt", lambda _path: {})


def test_v3_configuration_is_complete_and_restores_core() -> None:
    before = {name: getattr(core, name) for name in v3._OVERRIDES}
    validate_before = core.validate_tasks

    with v3.successor_configuration():
        assert core.BENCHMARK_ID == "grammar-stdlib-accuracy-t30-v3"
        assert core.ROSTER_ID == "gsl_t30_public_synthetic_v3"
        assert core.TASK_ID_PREFIX == "gsl_t30v3_"
        assert core.RUN_ID == "t30-v3-20260826"
        assert core.ATTEMPT_NONCE == "gsl-t30-v3-20260826-attempt-01"
        assert core.PRE_REVIEW_VERDICT == "GRAMMAR_STDLIB_T30_V3_REVIEW_REQUIRED"
        assert core.PASS_VERDICT == "GRAMMAR_STDLIB_T30_V3_PASS_NO_RETRAIN"
        assert core.DIAGNOSE_VERDICT == "GRAMMAR_STDLIB_T30_V3_DIAGNOSE"
        assert core.validate_tasks is v3._validate_tasks_v3
        assert core.COVERAGE_FIELDS == (
            "top_levels",
            "stdlib_modules",
            "stdlib_members",
            "stdlib_settings",
            "interaction_classes",
        )

    assert {name: getattr(core, name) for name in v3._OVERRIDES} == before
    assert core.validate_tasks is validate_before

    with pytest.raises(RuntimeError, match="synthetic restoration"), v3.successor_configuration():
        raise RuntimeError("synthetic restoration")
    assert {name: getattr(core, name) for name in v3._OVERRIDES} == before
    assert core.validate_tasks is validate_before


def test_v3_binds_v2_terminal_chain_and_fresh_wrapper_inputs() -> None:
    required = {
        "fixtures/grammar-stdlib-accuracy-v3/t30-tasks.json",
        "fixtures/grammar-stdlib-accuracy-v3/t30-reference-context.md",
        "manifests/grammar-stdlib-accuracy-t30-policy-v3.json",
        "manifests/grammar-stdlib-accuracy-t30-truth-v3.json",
        "fixtures/grammar-stdlib-accuracy-v2/t30-tasks.json",
        "manifests/grammar-stdlib-accuracy-t30-truth-v2.json",
        "manifests/grammar-stdlib-accuracy-t30-evaluation-v2.json",
        "manifests/grammar-stdlib-accuracy-t30-human-review-v2.json",
        "manifests/grammar-stdlib-accuracy-t30-adjudication-v2.json",
        "src/metis_model1/grammar_stdlib_t30_v3.py",
        "tests/test_grammar_stdlib_t30_v3.py",
    }
    assert required.issubset(v3.SUCCESSOR_BOUND_PATHS)
    assert len(v3.SUCCESSOR_BOUND_PATHS) == len(set(v3.SUCCESSOR_BOUND_PATHS))
    assert v3._OVERRIDES["ADDITIONAL_FRESHNESS_TASK_PATHS"] == (
        v3.V1_TASKS_PATH,
        v3.V2_TASKS_PATH,
    )
    assert v3._OVERRIDES["ADDITIONAL_FRESHNESS_TRUTH_PATHS"] == (
        v3.V1_TRUTH_PATH,
        v3.V2_TRUTH_PATH,
    )


def test_v3_reference_requires_the_generic_braced_attributes_rule() -> None:
    assert v3.V3_MULTI_ATTRIBUTE_RULE in v3.V3_REFERENCE_REQUIRED_MARKERS
    assert v3.V3_F1_BRACED_MULTI_ATTRIBUTE_MINIMUM == 2
    assert v3.V3_POLICY_EXTRA_CONTRACT["v3_prompt_only_cure"]["rule"] == v3.V3_MULTI_ATTRIBUTE_RULE
    assert v3.V3_POLICY_ROSTER["top_levels_required"] == 10
    assert v3.V3_POLICY_ROSTER["stdlib_modules_required"] == 3
    assert v3.V3_POLICY_ROSTER["stdlib_members_required"] == 12
    assert v3.V3_POLICY_ROSTER["stdlib_settings_required"] == 1
    assert v3.V3_POLICY_ROSTER["interaction_classes_required"] == 10
    assert v3.V3_POLICY_COVERAGE_GATE["minimum_successful_occurrences_each"] == 2
    assert "no_v2_rescore_or_promotion" in v3.V3_NONCLAIMS


def test_v3_successful_coverage_requires_two_occurrences_per_denominator_item() -> None:
    with v3.successor_configuration():
        complete = {field: sorted(values) for field, values in core._coverage_domains().items()}
        row = {"observed_coverage": complete}
        _coverage, one_gates = core._successful_coverage_gate([row])
        _coverage, two_gates = core._successful_coverage_gate([row, row])

    assert not all(one_gates.values())
    assert all(two_gates.values())


@pytest.mark.parametrize("overlap", ("task", "message", "content", "semantic"))
def test_v3_rejects_v2_task_message_content_and_semantic_target_reuse(
    monkeypatch: pytest.MonkeyPatch, overlap: str
) -> None:
    prior = _freshness_task("gsl_t30v2_f1_01", "prior prompt")
    candidate = _freshness_task("gsl_t30v3_f1_01", "fresh prompt")
    current_truth = _truth([{"task_id": candidate["task_id"], "target": {}}])
    v2_truth = _truth([])

    if overlap == "task":
        candidate["task_id"] = prior["task_id"]
        current_truth = _truth([{"task_id": candidate["task_id"], "target": {}}])
    elif overlap == "message":
        candidate["prompt"] = prior["prompt"]
        v2_truth = _truth(
            [
                {
                    "task_id": prior["task_id"],
                    "target": {
                        "messages_sha256": core.canonical_hash(
                            [{"role": "user", "content": prior["prompt"]}]
                        )
                    },
                }
            ]
        )
    elif overlap == "content":
        candidate = deepcopy(prior)
        candidate["task_id"] = "gsl_t30v3_f1_01"
        current_truth = _truth([{"task_id": candidate["task_id"], "target": {}}])
    else:
        candidates = [
            _freshness_task(f"gsl_t30v3_f1_{index:02d}", f"fresh prompt {index}")
            for index in range(30)
        ]
        candidate = candidates[0]
        v2_truth = _truth(
            [{"task_id": prior["task_id"], "target": {"expected": "same semantic target"}}]
        )
        current_truth = _truth(
            [
                {
                    "task_id": row["task_id"],
                    "target": {"expected": "same semantic target" if index == 0 else index},
                }
                for index, row in enumerate(candidates)
            ]
        )

    _patch_freshness_sources(monkeypatch, v2_tasks=[prior], v2_truth=v2_truth)
    monkeypatch.setattr(
        core,
        "build_messages",
        lambda task: [
            {
                "role": "user",
                "content": task["prompt"] if overlap != "content" else task["task_id"],
            }
        ],
    )
    expected = {"task": "identifiers", "message": "messages"}.get(overlap, overlap)
    with v3.successor_configuration(), pytest.raises(core.GrammarStdlibT30Error, match=expected):
        core._assert_disjoint(candidates if overlap == "semantic" else [candidate], current_truth)


def test_v3_requires_at_least_two_f1_braced_multi_attribute_targets() -> None:
    valid = [
        {
            "family": "F-1",
            "expected_source": (
                "endpoint alpha { attributes { first = time.now exists second = time.hour >= 6 } }"
            ),
        },
        {
            "family": "F-1",
            "expected_source": (
                'property beta { attributes { weekday = time.weekday is "monday" '
                "hour = time.hour >= 9 } }"
            ),
        },
    ]
    v3.validate_v3_braced_multi_attribute_targets(valid)

    with pytest.raises(core.GrammarStdlibT30Error, match="two F-1 braced"):
        v3.validate_v3_braced_multi_attribute_targets(valid[:1])


@pytest.mark.parametrize("decoy", ('"string_value = not_an_assignment"', "// comment = decoy\n"))
def test_v3_rejects_string_and_comment_assignment_decoys(decoy: str) -> None:
    invalid = [
        {
            "family": "F-1",
            "expected_source": (
                "endpoint alpha { attributes { only = time.weekday is " + decoy + " } }"
            ),
        },
        {
            "family": "F-1",
            "expected_source": (
                "endpoint beta { attributes { only = time.weekday is " + decoy + " } }"
            ),
        },
    ]

    with pytest.raises(core.GrammarStdlibT30Error, match="two F-1 braced"):
        v3.validate_v3_braced_multi_attribute_targets(invalid)


def test_v3_rejects_unterminated_attribute_lexical_structure() -> None:
    with pytest.raises(core.GrammarStdlibT30Error, match="unterminated string"):
        v3.validate_v3_braced_multi_attribute_targets(
            [
                {
                    "family": "F-1",
                    "expected_source": 'attributes { one = "unterminated',
                }
            ]
        )


def test_v3_binds_v2_terminal_adjudication_before_core_predecessor_receipt() -> None:
    with v3.successor_configuration():
        predecessor = core._predecessor_terminal_diagnosis()

    assert predecessor is not None
    assert predecessor["verdict"] == "GRAMMAR_STDLIB_T30_V2_DIAGNOSE"


def test_v3_rejects_rehashed_v2_terminal_adjudication(monkeypatch: pytest.MonkeyPatch) -> None:
    original_load = core._load
    adjudication = json.loads(v3.V2_ADJUDICATION_PATH.read_text(encoding="utf-8"))
    adjudication["decision"]["verdict"] = "FORGED"
    adjudication["adjudication_sha256"] = core.canonical_hash(
        {key: value for key, value in adjudication.items() if key != "adjudication_sha256"}
    )
    forged_raw = json.dumps(adjudication, allow_nan=False, sort_keys=True).encode()

    def load(path, label):
        if path == v3.V2_ADJUDICATION_PATH:
            return adjudication, forged_raw
        return original_load(path, label)

    with v3.successor_configuration():
        monkeypatch.setattr(core, "_load", load)
        with pytest.raises(core.GrammarStdlibT30Error, match="terminal adjudication"):
            core.build_truth(Path("unused-metis"), Path("unused-node"))


def test_v3_rejects_v2_adjudication_with_broken_evaluation_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_load = core._load
    adjudication = json.loads(v3.V2_ADJUDICATION_PATH.read_text(encoding="utf-8"))
    adjudication["evaluation_file_sha256"] = "sha256:" + "0" * 64
    adjudication["adjudication_sha256"] = core.canonical_hash(
        {key: value for key, value in adjudication.items() if key != "adjudication_sha256"}
    )
    original_raw = v3.V2_ADJUDICATION_PATH.read_bytes()

    def load(path, label):
        if path == v3.V2_ADJUDICATION_PATH:
            return adjudication, original_raw
        return original_load(path, label)

    with v3.successor_configuration():
        monkeypatch.setattr(core, "_load", load)
        with pytest.raises(core.GrammarStdlibT30Error, match="terminal adjudication"):
            core._predecessor_terminal_diagnosis()
