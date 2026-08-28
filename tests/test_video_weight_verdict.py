from __future__ import annotations

from copy import deepcopy

import pytest
from test_video_grounding_evaluation import _observations, _tasks

from metis_model1.video_grounding_evaluation import evaluate_paired_observations
from metis_model1.video_weight_verdict import (
    BLOCKED,
    DELTA_ELIGIBLE,
    FULL_SUCCESSOR_REQUIRED,
    NO_RETRAIN,
    decide_weight_verdict,
)


def _sha(label: str) -> str:
    return "sha256:" + (label.encode().hex() + "0" * 64)[:64]


def _evidence(
    *, delta: bool = False, repaired: bool = False, multi_root: bool = False
) -> tuple[dict, dict, dict, dict]:
    tasks = _tasks()
    rows = _observations(tasks)
    if delta or repaired or multi_root:
        normal_ids = {task["task_id"] for task in tasks if task["criticality"] == "normal"}
        d1_index = 0
        for row in rows:
            if row["variant"] == "D1" and row["task_id"] in normal_ids and d1_index < 3:
                row.update(
                    {
                        "post_repair_success": False,
                        "first_shot_success": False,
                        "repair_cycles": 1,
                        "failures": ["semantic_error_compile_clean"],
                        "diagnostic_category": "model_procedural_behavior",
                        "failure_roots": [f"root-{d1_index % 2}"],
                    }
                )
                if repaired:
                    row["post_repair_success"] = True
                if multi_root and d1_index == 0:
                    row["failure_roots"] = ["root-0", "root-1"]
                d1_index += 1
    report = evaluate_paired_observations(tasks, rows)
    benchmark = {
        "status": "terminal",
        "terminal_manifest": _sha("manifest"),
        "model_outputs_present": False,
        "benchmark_revision": report["benchmark_revision"],
        "split_counts": {
            "dev": {
                "total": 64,
                "families": {
                    "V-1": 14,
                    "V-2": 14,
                    "V-3": 10,
                    "V-4": 10,
                    "V-5": 8,
                    "V-6": 6,
                    "V-7": 2,
                },
            },
            "frozen": {
                "total": 32,
                "families": {
                    "V-1": 6,
                    "V-2": 6,
                    "V-3": 6,
                    "V-4": 6,
                    "V-5": 4,
                    "V-6": 2,
                    "V-7": 2,
                },
            },
        },
        "critical": {"total": 12},
        "leakage_groups": {"disjoint": True},
    }
    thresholds = {
        "status": "ratified",
        "ratified_before_observations": True,
        "benchmark_revision": report["benchmark_revision"],
        "frozen_semantic_min": 30,
        "full_suite_semantic_min": 92,
        "frozen_family_floor": {
            "V-1": 5,
            "V-2": 5,
            "V-3": 5,
            "V-4": 5,
            "V-5": 4,
            "V-6": 2,
            "V-7": 2,
        },
        "full_family_floor": {
            "V-1": 18,
            "V-2": 18,
            "V-3": 15,
            "V-4": 15,
            "V-5": 11,
            "V-6": 8,
            "V-7": 4,
        },
        "critical_failures_max": 0,
        "hallucinated_identifiers_max": 0,
        "wrong_catalog_max": 0,
        "silent_unsupported_max": 0,
        "semantic_refs_valid_percent": 100,
        "receipts_sanitized_percent": 100,
    }
    receipts = {
        gate: {
            "status": "PASS",
            "receipt_sha256": _sha(gate),
            "benchmark_revision": report["benchmark_revision"],
        }
        for gate in (
            "SEMANTIC_GRAMMAR_SURFACE_FROZEN",
            "SEMANTIC_CROSSWALK_COMPLETE",
            "SEMANTIC_RETRIEVAL_INJECTION_SAFE",
            "SEMANTIC_ROLLBACK_VALID",
            "OBSERVABILITY_SANITIZED",
            "BENCHMARK_FROZEN_NO_LEAKAGE",
            "VIDEO_BENCHMARK_THRESHOLD_RATIFIED",
        )
    }
    return benchmark, thresholds, receipts, report


def test_missing_frozen_benchmark_thresholds_or_receipts_block() -> None:
    benchmark, thresholds, receipts, scorecards = _evidence()
    assert (
        decide_weight_verdict(
            benchmark=None,
            thresholds=thresholds,
            gate_receipts=receipts,
            scorecards=scorecards,
        )["verdict"]
        == BLOCKED
    )
    assert (
        decide_weight_verdict(
            benchmark=benchmark,
            thresholds=None,
            gate_receipts=receipts,
            scorecards=scorecards,
        )["verdict"]
        == BLOCKED
    )
    receipts.pop("SEMANTIC_CROSSWALK_COMPLETE")
    assert (
        decide_weight_verdict(
            benchmark=benchmark,
            thresholds=thresholds,
            gate_receipts=receipts,
            scorecards=scorecards,
        )["verdict"]
        == BLOCKED
    )


def test_all_green_pair_is_no_retrain_and_never_training_authority() -> None:
    benchmark, thresholds, receipts, scorecards = _evidence()
    verdict = decide_weight_verdict(
        benchmark=benchmark,
        thresholds=thresholds,
        gate_receipts=receipts,
        scorecards=scorecards,
    )
    assert verdict["verdict"] == NO_RETRAIN
    assert verdict["training_authorized"] is False
    assert verdict["promotion_authorized"] is False


def test_three_compatible_failures_across_two_roots_are_delta_eligible() -> None:
    benchmark, thresholds, receipts, scorecards = _evidence(delta=True)
    verdict = decide_weight_verdict(
        benchmark=benchmark,
        thresholds=thresholds,
        gate_receipts=receipts,
        scorecards=scorecards,
    )
    assert verdict["verdict"] == DELTA_ELIGIBLE
    assert verdict["delta_training_authorized"] is False


def test_recurrent_repaired_procedural_failures_block_no_retrain() -> None:
    benchmark, thresholds, receipts, evaluation = _evidence(repaired=True)
    verdict = decide_weight_verdict(
        benchmark=benchmark,
        thresholds=thresholds,
        gate_receipts=receipts,
        scorecards=evaluation,
    )
    assert verdict["verdict"] == BLOCKED
    assert verdict["training_authorized"] is False


def test_one_row_cannot_self_assert_two_independent_delta_roots() -> None:
    benchmark, thresholds, receipts, evaluation = _evidence(multi_root=True)
    verdict = decide_weight_verdict(
        benchmark=benchmark,
        thresholds=thresholds,
        gate_receipts=receipts,
        scorecards=evaluation,
    )
    assert verdict["verdict"] == BLOCKED


@pytest.mark.parametrize(
    "kwargs",
    [{"contract_changed": True}, {"new_structural_family": True}, {"delta_attempted": True}],
)
def test_successor_conditions_do_not_authorize_training(kwargs: dict[str, bool]) -> None:
    benchmark, thresholds, receipts, scorecards = _evidence(delta=True)
    verdict = decide_weight_verdict(
        benchmark=benchmark,
        thresholds=thresholds,
        gate_receipts=receipts,
        scorecards=scorecards,
        **kwargs,
    )
    assert verdict["verdict"] == FULL_SUCCESSOR_REQUIRED
    assert verdict["training_authorized"] is False


def test_critical_failure_vetoes_delta() -> None:
    benchmark, thresholds, receipts, scorecards = _evidence(delta=True)
    changed = deepcopy(scorecards)
    row = changed["scorecards"]["D1"]["failure_rows"][0]
    row["critical_failures"] = ("wrong_catalog",)
    verdict = decide_weight_verdict(
        benchmark=benchmark,
        thresholds=thresholds,
        gate_receipts=receipts,
        scorecards=changed,
    )
    assert verdict["verdict"] == BLOCKED


def test_raw_or_tampered_scorecard_and_boolean_receipts_are_blocked() -> None:
    benchmark, thresholds, receipts, evaluation = _evidence()
    raw = evaluation["scorecards"]
    assert (
        decide_weight_verdict(
            benchmark=benchmark,
            thresholds=thresholds,
            gate_receipts=receipts,
            scorecards=raw,
        )["verdict"]
        == BLOCKED
    )

    changed = deepcopy(evaluation)
    changed["scorecards"]["D1"]["post_repair"]["successes"] -= 1
    assert (
        decide_weight_verdict(
            benchmark=benchmark,
            thresholds=thresholds,
            gate_receipts=receipts,
            scorecards=changed,
        )["verdict"]
        == BLOCKED
    )

    boolean_receipts = {gate: True for gate in receipts}
    assert (
        decide_weight_verdict(
            benchmark=benchmark,
            thresholds=thresholds,
            gate_receipts=boolean_receipts,
            scorecards=evaluation,
        )["verdict"]
        == BLOCKED
    )


def test_scorecard_must_bind_to_terminal_benchmark() -> None:
    benchmark, thresholds, receipts, evaluation = _evidence()
    changed = deepcopy(evaluation)
    changed["benchmark_revision"] = _sha("different")
    assert (
        decide_weight_verdict(
            benchmark=benchmark,
            thresholds=thresholds,
            gate_receipts=receipts,
            scorecards=changed,
        )["verdict"]
        == BLOCKED
    )


def test_critical_veto_precedes_successor_outcome() -> None:
    benchmark, thresholds, receipts, evaluation = _evidence(delta=True)
    changed = deepcopy(evaluation)
    row = changed["scorecards"]["D1"]["failure_rows"][0]
    row["critical_failures"] = ("wrong_catalog",)
    verdict = decide_weight_verdict(
        benchmark=benchmark,
        thresholds=thresholds,
        gate_receipts=receipts,
        scorecards=changed,
        contract_changed=True,
    )
    assert verdict["verdict"] == BLOCKED
