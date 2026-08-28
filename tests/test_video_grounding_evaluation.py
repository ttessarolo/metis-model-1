from __future__ import annotations

from copy import deepcopy

import pytest

from metis_model1.video_grounding_evaluation import (
    DIAGNOSTIC_ORDER,
    FAILURE_TAXONOMY,
    VARIANTS,
    VideoEvaluationError,
    evaluate_paired_observations,
)


def _sha(label: str) -> str:
    return "sha256:" + (label.encode().hex() + "0" * 64)[:64]


def _tasks() -> list[dict[str, object]]:
    counts = {
        "V-1": 20,
        "V-2": 20,
        "V-3": 16,
        "V-4": 16,
        "V-5": 12,
        "V-6": 8,
        "V-7": 4,
    }
    frozen_counts = {"V-1": 6, "V-2": 6, "V-3": 6, "V-4": 6, "V-5": 4, "V-6": 2, "V-7": 2}
    tasks: list[dict[str, object]] = []
    pins = {
        "benchmark_revision": _sha("benchmark"),
        "oracle_revision": _sha("oracle"),
        "semantic_source_revision": _sha("source"),
        "constraint_revision": _sha("constraint"),
        "grammar_revision": _sha("grammar"),
        "toolchain_revision": _sha("toolchain"),
        "base_model_ref": "qwen3.8-base",
        "tokenizer_ref": "qwen3.8-tokenizer",
        "adapter_ref": "adapter-current",
        "decoding_profile": "temperature-0-seed-v1",
    }
    index = 0
    for family, total in counts.items():
        for ordinal in range(total):
            split = "frozen" if ordinal < frozen_counts[family] else "dev"
            tasks.append(
                {
                    "task_id": f"video-{index:03d}",
                    "family": family,
                    "split": split,
                    "leakage_group": f"group-{index:03d}",
                    "criticality": "normal",
                    "pins": pins,
                }
            )
            index += 1
    frozen = [task for task in tasks if task["split"] == "frozen"]
    for task in frozen[:12]:
        task["criticality"] = "critical"
    return tasks


def _observations(tasks: list[dict[str, object]]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for task in tasks:
        for variant in VARIANTS:
            rows.append(
                {
                    "task_id": task["task_id"],
                    "variant": variant,
                    "first_shot_success": True,
                    "post_repair_success": True,
                    "repair_cycles": 0,
                    "semantic_refs_valid": True,
                    "receipt_sanitized": True,
                    "hallucinated_identifier": False,
                    "wrong_catalog": False,
                    "silent_unsupported": False,
                }
            )
    return rows


def test_exact_paired_roster_and_scorecard_arithmetic() -> None:
    report = evaluate_paired_observations(_tasks(), _observations(_tasks()))
    assert report["observations"] == 384
    assert report["variants"] == list(VARIANTS)
    assert report["roster"]["tasks"] == 96
    assert report["roster"]["gaps"] == 0
    assert report["scorecards"]["D1"]["post_repair"]["successes"] == 96
    assert report["scorecards"]["D1"]["splits"]["frozen"]["total"] == 32
    assert report["scorecards"]["D1"]["splits"]["frozen"]["post_repair_successes"] == 32
    assert report["model_outputs_present"] is False


def test_duplicate_and_missing_observations_are_rejected() -> None:
    tasks = _tasks()
    rows = _observations(tasks)
    rows[-1] = deepcopy(rows[0])
    with pytest.raises(VideoEvaluationError, match="duplicate observation"):
        evaluate_paired_observations(tasks, rows)

    rows = _observations(tasks)[:-1]
    with pytest.raises(VideoEvaluationError, match="384"):
        evaluate_paired_observations(tasks, rows)


def test_pins_and_model_output_are_not_laundered() -> None:
    tasks = _tasks()
    rows = _observations(tasks)
    rows[0]["model_output"] = "forbidden"
    with pytest.raises(VideoEvaluationError, match="model output"):
        evaluate_paired_observations(tasks, rows)

    rows = _observations(tasks)
    rows[0]["pins"] = dict(tasks[0]["pins"])
    rows[0]["pins"]["oracle_revision"] = _sha("other-oracle")
    with pytest.raises(VideoEvaluationError, match="pin drift"):
        evaluate_paired_observations(tasks, rows)

    tasks = _tasks()
    del tasks[0]["pins"]["oracle_revision"]
    with pytest.raises(VideoEvaluationError, match="closed evaluation pin roster"):
        evaluate_paired_observations(tasks, _observations(tasks))


def test_failure_taxonomy_and_diagnostic_order_are_pinned() -> None:
    assert len(FAILURE_TAXONOMY) == 10
    assert len(DIAGNOSTIC_ORDER) == 10
    tasks = _tasks()
    rows = _observations(tasks)
    rows[0]["first_shot_success"] = False
    rows[0]["post_repair_success"] = False
    rows[0]["failures"] = ["semantic_error_compile_clean"]
    rows[0]["diagnostic_category"] = "model_procedural_behavior"
    report = evaluate_paired_observations(tasks, rows)
    assert report["scorecards"]["B0"]["failure_taxonomy"]["semantic_error_compile_clean"] == 1


@pytest.mark.parametrize(
    "missing",
    [
        "repair_cycles",
        "semantic_refs_valid",
        "receipt_sanitized",
        "hallucinated_identifier",
        "wrong_catalog",
        "silent_unsupported",
    ],
)
def test_safety_and_repair_facts_must_be_explicit(missing: str) -> None:
    tasks = _tasks()
    rows = _observations(tasks)
    del rows[0][missing]
    with pytest.raises(VideoEvaluationError, match="explicit repair or safety"):
        evaluate_paired_observations(tasks, rows)


def test_failed_observation_requires_taxonomy_diagnosis_and_coherent_repair() -> None:
    tasks = _tasks()
    rows = _observations(tasks)
    rows[0]["first_shot_success"] = False
    rows[0]["post_repair_success"] = False
    with pytest.raises(VideoEvaluationError, match="failure taxonomy"):
        evaluate_paired_observations(tasks, rows)

    rows = _observations(tasks)
    rows[0]["first_shot_success"] = False
    rows[0]["repair_cycles"] = 0
    with pytest.raises(VideoEvaluationError, match="repair cycle"):
        evaluate_paired_observations(tasks, rows)
