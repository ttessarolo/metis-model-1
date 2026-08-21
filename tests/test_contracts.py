from __future__ import annotations

import json
import shutil
from copy import deepcopy

import pytest

from metis_model1.contracts import (
    load_json,
    repository_root,
    validate_accuracy_target_contract,
    validate_artifact_policy_paths,
    validate_artifact_store_policy_contract,
    validate_benchmark_plan_contract,
    validate_foundation,
    validate_hyperparameter_grid_contract,
    validate_instance,
    validate_qualification_contract,
    validate_repository_file_contents,
)


def test_repository_foundation_is_valid() -> None:
    report = validate_foundation(repository_root())
    assert report.errors == []
    assert "schema=schemas/w3-qualification.schema.json" in report.passes
    assert "schema=schemas/w3-semantic-spec.schema.json" in report.passes
    assert "schema=schemas/w3-source-register.schema.json" in report.passes
    assert "schema=schemas/w3-run.schema.json" in report.passes
    assert "W1" not in report.open_by_wave
    assert "W4" not in report.open_by_wave
    assert report.open_nonblocking == ["O-009"]


def test_ratified_benchmark_plan_has_six_families_and_thirty_distinct_allocations() -> None:
    root = repository_root()
    plan = load_json(root / "manifests/benchmark-plan.json")

    assert validate_benchmark_plan_contract(root) == []
    assert {family["id"] for family in plan["families"]} == {
        "F-1",
        "F-2",
        "F-3",
        "F-4",
        "F-5",
        "F-6",
    }
    assert len(plan["slice_30"]["tasks"]) == 30
    assert len({task["source_blob_oid"] for task in plan["slice_30"]["tasks"]}) == 30


def test_accuracy_target_is_pre_registered_and_arithmetically_consistent() -> None:
    root = repository_root()
    target = load_json(root / "manifests/accuracy-target.json")

    assert validate_accuracy_target_contract(root) == []
    assert target["registered_before_candidate_results"] is True
    assert target["status"] == "proposed"
    assert sum(target["family_counts"].values()) == target["total"] == 600
    assert target["maximum_failures"] == 1
    assert target["minimum_distinct_leakage_groups"] == 563


def test_accuracy_target_schema_rejects_post_result_registration() -> None:
    root = repository_root()
    schema = load_json(root / "schemas/accuracy-target.schema.json")
    target = deepcopy(load_json(root / "manifests/accuracy-target.json"))
    target["registered_before_candidate_results"] = False

    errors = validate_instance(target, schema)

    assert any("True was expected" in error for error in errors)


def test_artifact_store_policy_is_ratified_and_budgeted() -> None:
    root = repository_root()
    policy = load_json(root / "manifests/artifact-store-policy.json")

    assert validate_artifact_store_policy_contract(root) == []
    assert policy["scope"] == "local_only_no_distribution"
    assert policy["budget"]["per_run_cap_bytes"] == 40 * 1024**3
    assert policy["retention"]["published_artifact_automatic_deletion"] is False


def test_artifact_store_policy_rejects_an_unfunded_reserve(tmp_path) -> None:
    root = repository_root()
    policy = deepcopy(load_json(root / "manifests/artifact-store-policy.json"))
    policy["measurement"]["filesystem_available_bytes"] = 80 * 1024**3

    destination = tmp_path / "manifests"
    destination.mkdir(parents=True)
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    shutil.copy2(root / "manifests/decision-register.json", destination)
    (destination / "artifact-store-policy.json").write_text(json.dumps(policy), encoding="utf-8")

    errors = validate_artifact_store_policy_contract(tmp_path)
    assert "artifact-store observation does not meet minimum pre-run free space" in errors
    assert "artifact-store budget cannot preserve its required post-run reserve" in errors


def test_hyperparameter_grid_is_pre_registered_bounded_and_ratified() -> None:
    root = repository_root()
    grid = load_json(root / "manifests/hyperparameter-grid.json")

    assert validate_hyperparameter_grid_contract(root) == []
    assert grid["registered_before_w5_candidate_results"] is True
    assert len(grid["screening"]["configurations"]) == 4
    assert grid["finalist_repeats"]["seeds"] == [17, 29, 43]
    assert grid["budget"]["max_total_optimizer_steps"] == 700


def test_hyperparameter_grid_rejects_cartesian_and_budget_drift(tmp_path) -> None:
    root = repository_root()
    shutil.copytree(root / "manifests", tmp_path / "manifests")
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    path = tmp_path / "manifests/hyperparameter-grid.json"
    grid = json.loads(path.read_text(encoding="utf-8"))
    grid["screening"]["configurations"][3] = deepcopy(grid["screening"]["configurations"][2])
    grid["budget"]["max_total_optimizer_steps"] = 701
    path.write_text(json.dumps(grid), encoding="utf-8")

    errors = validate_hyperparameter_grid_contract(tmp_path)

    assert "W5 grid must be the exact four-configuration rank/LR Cartesian set" in errors
    assert "W5 total step budget is inconsistent" in errors


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("fixed", "lora_dropout", 0.1),
        ("fixed", "max_seq_length", 2048),
    ],
)
def test_hyperparameter_grid_schema_rejects_unqualified_fixed_settings(
    tmp_path, section, field, value
) -> None:
    root = repository_root()
    shutil.copytree(root / "manifests", tmp_path / "manifests")
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    path = tmp_path / "manifests/hyperparameter-grid.json"
    grid = json.loads(path.read_text(encoding="utf-8"))
    grid[section][field] = value
    path.write_text(json.dumps(grid), encoding="utf-8")

    errors = validate_hyperparameter_grid_contract(tmp_path)

    assert errors
    assert any(field in error for error in errors)


@pytest.mark.parametrize("field", ["stop_rules", "non_claims"])
def test_hyperparameter_grid_schema_pins_stop_and_nonclaim_policy(tmp_path, field) -> None:
    root = repository_root()
    shutil.copytree(root / "manifests", tmp_path / "manifests")
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    path = tmp_path / "manifests/hyperparameter-grid.json"
    grid = json.loads(path.read_text(encoding="utf-8"))
    grid[field][0] = "policy_drift"
    path.write_text(json.dumps(grid), encoding="utf-8")

    errors = validate_hyperparameter_grid_contract(tmp_path)

    assert errors
    assert any(field in error for error in errors)


@pytest.mark.parametrize(
    ("section", "field", "value"),
    [
        ("publication", "atomic_rename", False),
        ("retention", "published_artifact_automatic_deletion", True),
    ],
)
def test_artifact_store_schema_rejects_unsafe_publication_policy(
    tmp_path, section, field, value
) -> None:
    root = repository_root()
    shutil.copytree(root / "manifests", tmp_path / "manifests")
    shutil.copytree(root / "schemas", tmp_path / "schemas")
    path = tmp_path / "manifests/artifact-store-policy.json"
    policy = json.loads(path.read_text(encoding="utf-8"))
    policy[section][field] = value
    path.write_text(json.dumps(policy), encoding="utf-8")

    errors = validate_artifact_store_policy_contract(tmp_path)

    assert errors
    assert any(field in error for error in errors)


def test_source_manifest_rejects_short_revision() -> None:
    root = repository_root()
    schema = load_json(root / "schemas/source-model-revisions.schema.json")
    manifest = deepcopy(load_json(root / "manifests/source-model-revisions.json"))
    manifest["source"]["revision"] = "abc123"

    errors = validate_instance(manifest, schema)

    assert any("revision" in error and "does not match" in error for error in errors)


def test_ratified_source_manifest_rejects_open_decisions() -> None:
    root = repository_root()
    schema = load_json(root / "schemas/source-model-revisions.schema.json")
    manifest = deepcopy(load_json(root / "manifests/source-model-revisions.json"))
    manifest["state"] = "ratified"
    manifest["source"]["language_version_status"] = "ratified"
    manifest["runtime"]["pinned_version"] = "0.6.15"
    manifest["runtime"]["status"] = "qualified"
    manifest["open_decision_refs"] = ["O-004"]

    errors = validate_instance(manifest, schema)

    assert any("open_decision_refs" in error and "empty" in error for error in errors)


def test_benchmark_contract_rejects_prohibited_sensitivity() -> None:
    root = repository_root()
    schema = load_json(root / "schemas/benchmark-task.schema.json")
    task = deepcopy(load_json(root / "examples/benchmark-task.draft.json"))
    task["provenance"]["sensitivity"] = "prohibited"

    errors = validate_instance(task, schema)

    assert any("prohibited" in error for error in errors)


def test_sealed_benchmark_task_requires_closed_oracles_and_ratified_language() -> None:
    root = repository_root()
    schema = load_json(root / "schemas/benchmark-task.schema.json")
    task = deepcopy(load_json(root / "examples/benchmark-task.draft.json"))
    task["status"] = "sealed"

    errors = validate_instance(task, schema)

    assert any("ratified" in error for error in errors)
    assert any("pending" in error for error in errors)


def test_sealed_source_task_rejects_semantic_waiver_without_structural_oracles() -> None:
    root = repository_root()
    schema = load_json(root / "schemas/benchmark-task.schema.json")
    task = deepcopy(load_json(root / "examples/benchmark-task.draft.json"))
    task["status"] = "sealed"
    task["metis"]["language_version_status"] = "ratified"
    task["oracles"] = [
        {
            "stage": "semantic",
            "expectation": "not_applicable",
            "evidence_ref": "waived",
        }
    ]

    errors = validate_instance(task, schema)

    assert errors
    assert any("does not contain" in error for error in errors)


def test_artifact_policy_rejects_payloads_and_secret_paths() -> None:
    errors = validate_artifact_policy_paths(
        [
            "README.md",
            "artifacts/adapter.bin",
            "models/base/model.safetensors",
            "nested/.env",
            "nested/.env.production",
            "checkpoints/optimizer.ckpt",
            "keys/signing.pem",
            "datasets/cache.parquet",
            "config/credentials.json",
            "qualification/train.jsonl",
            "qualification/process.log",
        ]
    )

    assert len(errors) == 13


def test_artifact_policy_rejects_binary_and_disguised_private_key(tmp_path) -> None:
    (tmp_path / "payload.dat").write_bytes(b"\x00\xff\x00")
    (tmp_path / "notes.txt").write_text(
        "-----BEGIN " + "PRIVATE KEY-----\nredacted-test-fixture\n",
        encoding="utf-8",
    )

    errors = validate_repository_file_contents(tmp_path, ["payload.dat", "notes.txt"])

    assert errors == [
        "binary repository file is forbidden: payload.dat",
        "private key material is forbidden: notes.txt",
    ]


def _copy_qualification_contract(tmp_path):
    root = repository_root()
    required = [
        "qualification/runtime-pin.json",
        "qualification/checkpoint-pin.json",
        "qualification/pyproject.toml",
        "qualification/train_full_state.py",
        "qualification/uv.lock",
        "manifests/source-model-revisions.json",
        "manifests/decision-register.json",
        "orchestra/runs/2026-08-20-w1-w4-entry/W4-QUALIFICATION.md",
    ]
    for relative in required:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, destination)
    return tmp_path


def test_qualification_contract_rejects_reopened_runtime(tmp_path) -> None:
    root = _copy_qualification_contract(tmp_path)
    runtime_path = root / "qualification/runtime-pin.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["status"] = "candidate_executed_environment"
    runtime["qualification_remaining"] = ["finite_backward"]
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")

    errors = validate_qualification_contract(root)

    assert "qualification runtime is not marked qualified" in errors
    assert "qualification runtime retains incomplete gates" in errors


def test_qualification_contract_rejects_resume_semantics_drift(tmp_path) -> None:
    root = _copy_qualification_contract(tmp_path)
    runtime_path = root / "qualification/runtime-pin.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    runtime["full_state_resume_semantics"] = (
        "local_wrapper_optimizer_rng_sampler_global_step_bit_exact_4_vs_2_plus_resume"
    )
    runtime_path.write_text(json.dumps(runtime), encoding="utf-8")

    errors = validate_qualification_contract(root)

    assert "qualification full-state resume semantics are missing or overstated" in errors


def test_qualification_contract_rejects_open_o004_reference(tmp_path) -> None:
    root = _copy_qualification_contract(tmp_path)
    manifest_path = root / "manifests/source-model-revisions.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["open_decision_refs"] = ["O-004"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    errors = validate_qualification_contract(root)

    assert "qualified source/model manifest retains open decision references" in errors
