from __future__ import annotations

from copy import deepcopy

import pytest

from metis_model1.video_grounding_benchmark import VideoBenchmarkContractError, validate_task_roster
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
