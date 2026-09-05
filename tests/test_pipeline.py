from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from metis_model1 import contracts, pipeline
from metis_model1.cli import main
from metis_model1.closure import BuildInput, shared_leakage_group_id

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def validated_foundation_report():
    """Provide one real, green Foundation report to downstream mutation tests."""

    report = pipeline.validate_foundation(ROOT)
    assert report.ok
    return report


@pytest.fixture
def reuse_validated_foundation(monkeypatch, validated_foundation_report):
    """Replay only an independently checked Foundation result, by value."""

    baseline = deepcopy(validated_foundation_report)
    call_roots: list[Path] = []

    def validate_foundation(root: Path):
        assert root == ROOT
        call_roots.append(root)
        report = deepcopy(validated_foundation_report)
        assert report is not validated_foundation_report
        assert report.passes is not validated_foundation_report.passes
        assert report.errors is not validated_foundation_report.errors
        return report

    monkeypatch.setattr(pipeline, "validate_foundation", validate_foundation)
    yield

    assert call_roots == [ROOT]
    assert validated_foundation_report == baseline


def test_validate_pilot_reports_valid_contracts_and_denominators(capsys) -> None:
    assert main(["validate-pilot", "--root", str(ROOT), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["contract_valid"] is True
    expected_w5 = {
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
    assert report["schema_version"] == 1
    assert set(report) == {
        "schema_version",
        "status",
        "contract_valid",
        "w5_readiness",
        "checks",
        "denominators",
        "source_anchor",
        "open_decisions",
    }
    assert report["w5_readiness"] == expected_w5
    assert report["source_anchor"] == {
        "project_root": str(ROOT),
        "metis_root": str(pipeline.DEFAULT_METIS_ROOT),
        "revision": "a2dde2b191f6b78c2003d74875560da782470968",
        "verified": True,
    }
    assert report["open_decisions"] == {
        "blocking": ["O-003"],
        "nonblocking": ["O-007", "O-008", "O-009"],
    }
    assert report["denominators"]["closure"]["tasks_out"] == 30
    assert report["denominators"]["closure"]["distinct_leakage_groups"] == 1
    assert report["denominators"]["assets"]["assets_out"] == 201
    assert report["denominators"]["dataset"]["examples_out"] == 1
    assert report["denominators"]["evaluation"]["observations_out"] == 4


def test_validate_pilot_fails_on_dataset_fixture_mutation(
    monkeypatch, reuse_validated_foundation
) -> None:
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


def test_validate_pilot_reports_an_unreadable_dataset_without_crashing(
    monkeypatch, reuse_validated_foundation
) -> None:
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


def test_validate_pilot_fails_on_evaluation_fixture_mutation(
    monkeypatch, reuse_validated_foundation
) -> None:
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


def test_validate_pilot_fails_on_asset_register_mutation(
    monkeypatch, reuse_validated_foundation
) -> None:
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


def test_validate_pilot_reanchors_closure_to_pinned_metis_git(
    monkeypatch, reuse_validated_foundation
) -> None:
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


def test_validate_pilot_fails_closed_without_pinned_metis_checkout(
    tmp_path: Path, reuse_validated_foundation
) -> None:
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
    assert "BLOCKER leakage groups 1/563" in output
    assert "DENOMINATOR closure" in output
    assert "EXPERIMENT" not in output
    assert "PROMOTION_BLOCKER" not in output


def test_assess_experiment_is_plan_only_and_green(capsys) -> None:
    assert main(["assess-experiment", "--root", str(ROOT), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["status"] == "EXPERIMENT_PLAN_READY"
    assert report["ready"] is True
    assert report["planned_next_stage"] == "REQUEST_W5_XS_EXECUTION_MANDATE"
    assert report["execution_authorized"] is False
    assert report["physical_checkpoint_verified"] is False
    assert report["blockers"] == []
    assert "no_training_authority" in report["nonclaims"]


def test_w5_xs_plan_contract_is_green() -> None:
    assert contracts.validate_w5_xs_plan_contract(ROOT) == []


@pytest.mark.parametrize(
    ("field_path", "mutated"),
    [
        (("canonical_spec", "sha256"), "sha256:" + "0" * 64),
        (("gate", "execution_authorized"), True),
        (("baseline", "diagnostic_task_count"), 13),
        (("dataset", "total_examples"), 256),
        (("training", "rank"), 16),
        (("artifact_policy", "artifact_root"), "artifacts/w5"),
        (("artifact_policy", "max_new_bytes"), 42949672960),
        (("artifact_policy", "max_wall_clock_hours"), 18),
    ],
)
def test_w5_xs_plan_contract_rejects_scope_drift(
    monkeypatch, field_path: tuple[str, str], mutated: object
) -> None:
    original_load = contracts.load_json

    def load(path: Path):
        value = original_load(path)
        if path.name == "w5-xs-plan.json":
            value = deepcopy(value)
            value[field_path[0]][field_path[1]] = mutated
        return value

    monkeypatch.setattr(contracts, "load_json", load)
    assert contracts.validate_w5_xs_plan_contract(ROOT)


def test_w5_xs_plan_contract_requires_unique_ratified_o011(monkeypatch) -> None:
    original_load = contracts.load_json

    def load(path: Path):
        value = original_load(path)
        if path.name == "decision-register.json":
            value = deepcopy(value)
            value["open_decisions"] = [
                decision for decision in value["open_decisions"] if decision["id"] != "O-011"
            ]
        return value

    monkeypatch.setattr(contracts, "load_json", load)
    assert "O-011 is not uniquely and fully ratified" in contracts.validate_w5_xs_plan_contract(
        ROOT
    )


def test_w5_xs_plan_contract_rejects_critical_failure_roster_drift(monkeypatch) -> None:
    original_load = contracts.load_json

    def load(path: Path):
        value = original_load(path)
        if path.name == "accuracy-target.json":
            value = deepcopy(value)
            value["forbidden_critical_failures"] = []
        return value

    monkeypatch.setattr(contracts, "load_json", load)
    errors = contracts.validate_w5_xs_plan_contract(ROOT)

    assert any("critical-failure roster" in error for error in errors)


def test_assess_experiment_fails_closed_on_validator_exception(monkeypatch) -> None:
    def fail(_root: Path) -> list[str]:
        raise OSError("plan unavailable")

    monkeypatch.setattr(pipeline, "validate_w5_xs_plan_contract", fail)
    report = pipeline.assess_experiment_plan(ROOT)

    assert report["status"] == "EXPERIMENT_PLAN_BLOCKED"
    assert report["ready"] is False
    assert report["execution_authorized"] is False
    assert report["physical_checkpoint_verified"] is False
    assert report["blockers"]
