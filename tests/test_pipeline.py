from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from metis_model1 import pipeline
from metis_model1.cli import main
from metis_model1.closure import BuildInput, shared_leakage_group_id

ROOT = Path(__file__).resolve().parents[1]


def test_validate_pilot_reports_valid_contracts_and_denominators(capsys) -> None:
    assert main(["validate-pilot", "--root", str(ROOT), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["contract_valid"] is True
    assert report["w5_readiness"] == {
        "ready": False,
        "status": "blocked",
        "blockers": [
            "leakage groups 1/563 (minimum required distinct groups: 563)",
            "closure computed_not_sealed; task-specific oracles unresolved",
            "W3 is synthetic-only; no validated real dataset is present",
            "open decisions blocking W5: O-003",
            "A/B baseline is absent",
        ],
    }
    assert report["source_anchor"] == {
        "project_root": str(ROOT),
        "metis_root": str(pipeline.DEFAULT_METIS_ROOT),
        "revision": "a2dde2b191f6b78c2003d74875560da782470968",
        "verified": True,
    }
    assert report["open_decisions"] == {
        "blocking": ["O-003"],
        "nonblocking": ["O-007", "O-008", "O-009", "O-010"],
    }
    assert report["denominators"]["closure"]["tasks_out"] == 30
    assert report["denominators"]["closure"]["distinct_leakage_groups"] == 1
    assert report["denominators"]["assets"]["assets_out"] == 201
    assert report["denominators"]["dataset"]["examples_out"] == 1
    assert report["denominators"]["evaluation"]["observations_out"] == 4


def test_validate_pilot_fails_on_dataset_fixture_mutation(monkeypatch) -> None:
    original_load = pipeline._load

    def load(path: Path):
        value = original_load(path)
        if path.name == "dataset-example.synthetic.json":
            value = deepcopy(value)
            value["positive"] = False
        return value

    monkeypatch.setattr(pipeline, "_load", load)
    report = pipeline.validate_pilot(ROOT)

    assert report["contract_valid"] is False
    assert report["checks"]["dataset"]["valid"] is False
    assert report["checks"]["dataset"]["errors"]


def test_validate_pilot_reports_an_unreadable_dataset_without_crashing(monkeypatch) -> None:
    original_load = pipeline._load

    def load(path: Path):
        if path.name == "dataset-example.synthetic.json":
            raise OSError("synthetic read failure")
        return original_load(path)

    monkeypatch.setattr(pipeline, "_load", load)
    report = pipeline.validate_pilot(ROOT)

    assert report["contract_valid"] is False
    assert report["checks"]["dataset"]["valid"] is False
    assert report["denominators"]["dataset"] == {
        "examples_in": 0,
        "examples_out": None,
        "example_ids_distinct": 0,
        "gaps": 1,
    }


def test_validate_pilot_fails_on_evaluation_fixture_mutation(monkeypatch) -> None:
    original_load = pipeline._load

    def load(path: Path):
        value = original_load(path)
        if path.name == "evaluation-report.synthetic.json":
            value = deepcopy(value)
            value["observations"][0]["task_id"] = "mutated/task"
        return value

    monkeypatch.setattr(pipeline, "_load", load)
    report = pipeline.validate_pilot(ROOT)

    assert report["contract_valid"] is False
    assert report["checks"]["evaluation"]["valid"] is False
    assert report["checks"]["evaluation"]["errors"]


def test_validate_pilot_fails_on_asset_register_mutation(monkeypatch) -> None:
    original_load = pipeline._load

    def load(path: Path):
        value = original_load(path)
        if path.name == "slice-30-assets.json":
            value = deepcopy(value)
            value["assets"][0]["sensitivity"] = "public"
        return value

    monkeypatch.setattr(pipeline, "_load", load)
    report = pipeline.validate_pilot(ROOT)

    assert report["contract_valid"] is False
    assert report["checks"]["assets"]["valid"] is False
    assert report["checks"]["assets"]["errors"]


def test_validate_pilot_reanchors_closure_to_pinned_metis_git(monkeypatch) -> None:
    original_load = pipeline._load

    def load(path: Path):
        value = original_load(path)
        if path.name == "slice-30-closure.json":
            value = deepcopy(value)
            task_paths = {task["source_path"] for task in value["tasks"]}
            non_task = next(
                entry
                for entry in value["shared_closures"][0]["inputs"]
                if entry["path"] not in task_paths
            )
            non_task["blob_oid"] = "f" * 40
            inventory = tuple(
                BuildInput(path=entry["path"], blob_oid=entry["blob_oid"])
                for entry in value["shared_closures"][0]["inputs"]
            )
            group = shared_leakage_group_id(inventory, value["source_revision"])
            value["leakage_group_id"] = group
            value["shared_closures"][0]["leakage_group_id"] = group
            for task in value["tasks"]:
                task["leakage_group_id"] = group
        return value

    monkeypatch.setattr(pipeline, "_load", load)
    report = pipeline.validate_pilot(ROOT)

    assert report["contract_valid"] is False
    assert report["checks"]["closure"] == {
        "valid": False,
        "errors": ["closure manifest does not exactly match the pinned Metis Git objects"],
    }
    assert report["source_anchor"]["verified"] is False


def test_validate_pilot_fails_closed_without_pinned_metis_checkout(tmp_path: Path) -> None:
    report = pipeline.validate_pilot(ROOT, tmp_path / "missing-metis")

    assert report["contract_valid"] is False
    assert report["checks"]["closure"]["valid"] is False
    assert report["checks"]["closure"]["errors"]
    assert report["source_anchor"]["verified"] is False


def test_assess_w5_is_nonzero_while_validate_pilot_is_contract_green(capsys) -> None:
    assert main(["validate-pilot", "--root", str(ROOT)]) == 0
    capsys.readouterr()
    assert main(["assess-w5", "--root", str(ROOT)]) == 1
    output = capsys.readouterr().out
    assert "W5 readiness=BLOCKED" in output
    assert "DENOMINATOR closure" in output
