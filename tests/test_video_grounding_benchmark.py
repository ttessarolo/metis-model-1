from __future__ import annotations

from copy import deepcopy

import pytest

from metis_model1.video_grounding_benchmark import (
    VideoBenchmarkContractError,
    build_benchmark_freeze,
    validate_task_roster,
)
from metis_model1.video_semantics_contracts import FIXTURE_ROOT, load_json


def _task() -> dict:
    return load_json(FIXTURE_ROOT / "task.json")


def test_synthetic_task_roster_is_model_output_free() -> None:
    report = validate_task_roster([_task()])
    assert report["in"] == report["out"] == report["distinct"] == 1
    assert report["gaps"] == 0
    assert report["model_outputs_present"] is False
    assert report["families"] == {"V-1": 1}


def test_duplicate_task_ids_are_rejected() -> None:
    task = _task()
    with pytest.raises(VideoBenchmarkContractError, match="duplicate task_id"):
        validate_task_roster([task, deepcopy(task)])


def test_family_drift_is_rejected() -> None:
    task = _task()
    task["family"] = "V-2"
    with pytest.raises(VideoBenchmarkContractError, match="task family"):
        validate_task_roster([task])


def test_model_output_field_is_rejected() -> None:
    task = _task()
    task["model_output"] = "not allowed in a task specification"
    with pytest.raises(VideoBenchmarkContractError, match="model_output"):
        validate_task_roster([task])


def test_unhashable_task_identity_returns_contract_error() -> None:
    task = _task()
    task["task_id"] = ["unhashable"]
    with pytest.raises(VideoBenchmarkContractError, match="not of type"):
        validate_task_roster([task])


def _split_rosters() -> tuple[list[dict], list[dict]]:
    counts = {
        "dev": {"V-1": 14, "V-2": 14, "V-3": 10, "V-4": 10, "V-5": 8, "V-6": 6, "V-7": 2},
        "frozen": {"V-1": 6, "V-2": 6, "V-3": 6, "V-4": 6, "V-5": 4, "V-6": 2, "V-7": 2},
    }
    result: dict[str, list[dict]] = {"dev": [], "frozen": []}
    for split, family_counts in counts.items():
        for family, count in family_counts.items():
            for ordinal in range(count):
                task = _task()
                suffix = ordinal + 1 if split == "dev" else ordinal + 51
                task["task_id"] = f"{family}-{suffix:02d}"
                task["family"] = family
                task["leakage_group"] = f"{split}-{family}-{ordinal:02d}"
                if split == "frozen" and len(result[split]) < 12:
                    task["criticality"] = "critical"
                result[split].append(task)
    return result["dev"], result["frozen"]


def test_benchmark_freeze_enforces_exact_split_and_critical_contract() -> None:
    dev, frozen = _split_rosters()
    freeze = build_benchmark_freeze(dev, frozen)
    assert freeze["status"] == "synthetic_contract"
    assert freeze["terminal_manifest"] is None
    assert freeze["split_counts"]["dev"]["total"] == 64
    assert freeze["split_counts"]["frozen"]["total"] == 32
    assert freeze["critical"]["total"] == 12
    assert len(freeze["critical"]["slots"]) == 12
    assert freeze["leakage_groups"]["disjoint"] is True
    assert freeze["model_outputs_present"] is False


@pytest.mark.parametrize("mutation", ["family", "leakage", "critical", "provenance", "output"])
def test_benchmark_freeze_rejects_roster_or_provenance_drift(mutation: str) -> None:
    dev, frozen = _split_rosters()
    if mutation == "family":
        dev[0]["family"] = "V-2"
    elif mutation == "leakage":
        frozen[0]["leakage_group"] = dev[0]["leakage_group"]
    elif mutation == "critical":
        for task in frozen[:12]:
            task["criticality"] = "normal"
    elif mutation == "provenance":
        frozen[0]["provenance"]["grammar_revision"] = "sha256:" + "f" * 64
    else:
        frozen[0]["model_output"] = "must never enter a task"
    with pytest.raises(VideoBenchmarkContractError):
        build_benchmark_freeze(dev, frozen)
