from __future__ import annotations

import json
import shutil
from copy import deepcopy

import pytest

import metis_model1.contracts as contracts
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
    validate_w3_retained_report_schema_contract,
)


def test_repository_foundation_is_valid() -> None:
    report = validate_foundation(repository_root())
    assert report.errors == []
    assert "schema=schemas/w3-bridge-replay.schema.json" in report.passes
    assert "schema=schemas/w3-production-authority.schema.json" in report.passes
    assert "schema=schemas/w3-qualification.schema.json" in report.passes
    assert "schema=schemas/w3-native-loader-evidence.schema.json" in report.passes
    assert "schema=schemas/w3-semantic-spec.schema.json" in report.passes
    assert "schema=schemas/w3-source-register.schema.json" in report.passes
    assert "schema=schemas/w3-run.schema.json" in report.passes
    assert "contract=manifests/w1-slice-30-blocker-map-v1.json" in report.passes
    assert "contract=manifests/w2-rights-dossier-v1.json" in report.passes
    assert "contract=manifests/w1-slice-30-oracle-receipts-v1.json" in report.passes
    assert "contract=manifests/w1-leakage-group-assignment-v1.json" in report.passes
    assert "contract=manifests/w1-held-out-family-map-v1.json" in report.passes
    assert "contract=manifests/w1-benchmark-seal-v1.json" in report.passes
    assert "catalog-retrieval-refresh=public-synthetic/8-goldens/redacted" in report.passes
    assert "catalog-maintenance-probe=8-cases/sealed-pre-output/no-output" in report.passes
    assert "w1-w2-evidence-package=6-semantic-sidecars" in report.passes
    assert "W1" not in report.open_by_wave
    assert "W4" not in report.open_by_wave
    assert report.open_nonblocking == ["O-009"]


def test_foundation_rejects_semantic_w2_rights_laundering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = repository_root()
    original = contracts.load_json

    def drifted(path):
        value = original(path)
        if path.name == "w2-rights-dossier-v1.json":
            value = deepcopy(value)
            value["assets"][0]["license"] = "invented-rights-claim"
        return value

    monkeypatch.setattr(contracts, "load_json", drifted)

    report = contracts.validate_foundation(root)

    assert "w2-rights-dossier: dossier field drift: assets" in report.errors


@pytest.mark.parametrize(
    ("schema_name", "variant_names"),
    [
        ("w3-production-authority.schema.json", (None,)),
        (
            "w3-qualification.schema.json",
            ("productionQualified", "productionBlocked"),
        ),
        ("w3-bridge-replay.schema.json", ("qualified", "blocked")),
    ],
)
def test_l66_production_schemas_bind_exact_native_evidence_manifest(
    schema_name: str,
    variant_names: tuple[str | None, ...],
) -> None:
    root = repository_root()
    manifest = load_json(root / "manifests/w3-native-loader-evidence.json")
    schema = load_json(root / "schemas" / schema_name)
    expected = {
        "const": {
            "path": "manifests/w3-native-loader-evidence.json",
            "manifest_sha256": manifest["manifest_sha256"],
        }
    }
    assert schema["$defs"]["nativeEvidence"] == expected
    for variant_name in variant_names:
        target = schema if variant_name is None else schema["$defs"][variant_name]
        assert "native_evidence" in target["required"]
        assert target["properties"]["native_evidence"] == {"$ref": "#/$defs/nativeEvidence"}


def test_w3_source_checkpoint_revision_is_repeated_exactly_across_four_paths() -> None:
    root = repository_root()
    expected = "5a5d817bb3df817fbd5d47b7bc4edd4517f8d9b7"
    former = "4ec625fcec8a9c41423bc048688d17775e57353c"
    paths = (
        root / "runtime/w3_bridge_gate.py",
        root / "runtime/w3_qualifier.py",
        root / "schemas/w3-production-authority.schema.json",
        root / "schemas/w3-qualification.schema.json",
    )
    assert [path.read_text().count(expected) for path in paths] == [1, 1, 1, 1]
    assert all(former not in path.read_text() for path in paths)


def test_w3_report_schemas_require_deferred_cleanup_on_all_six_variants() -> None:
    root = repository_root()
    qualification = load_json(root / "schemas/w3-qualification.schema.json")
    bridge = load_json(root / "schemas/w3-bridge-replay.schema.json")

    qualifier_variants = [
        qualification["$defs"][name]
        for name in ("qualified", "blocked", "productionQualified", "productionBlocked")
    ]
    bridge_variants = [bridge["$defs"][name] for name in ("qualified", "blocked")]

    assert all("cleanup" in variant["required"] for variant in qualifier_variants)
    assert all("cleanup" in variant["required"] for variant in bridge_variants)
    assert qualification["$defs"]["cleanup"]["properties"]["delete_attempts"] == {"const": 0}
    assert bridge["$defs"]["cleanup"]["properties"]["delete_attempts"] == {"const": 0}
    assert qualification["$defs"]["qualified"]["properties"]["cleanup"] == {
        "$ref": "#/$defs/qualifiedV1Cleanup"
    }
    assert qualification["$defs"]["productionQualified"]["properties"]["cleanup"] == {
        "$ref": "#/$defs/qualifiedV3Cleanup"
    }
    assert qualification["$defs"]["blocked"]["properties"]["cleanup"] == {
        "$ref": "#/$defs/blockedV1Cleanup"
    }
    assert qualification["$defs"]["productionBlocked"]["properties"]["cleanup"] == {
        "$ref": "#/$defs/blockedV3Cleanup"
    }
    assert bridge["$defs"]["qualified"]["properties"]["cleanup"] == {
        "$ref": "#/$defs/qualifiedReplayCleanup"
    }
    assert bridge["$defs"]["blocked"]["properties"]["cleanup"] == {
        "$ref": "#/$defs/blockedReplayCleanup"
    }
    assert bridge["$defs"]["physicalRun"]["properties"]["cleanup"] == {
        "$ref": "#/$defs/qualifiedChildCleanup"
    }
    assert bridge["$defs"]["blockedObservedRun"]["properties"]["cleanup"] == {
        "$ref": "#/$defs/blockedChildCleanup"
    }
    assert [
        item["$ref"]
        for item in bridge["$defs"]["blocked"]["properties"]["observed_runs"]["prefixItems"]
    ] == ["#/$defs/observedRun1", "#/$defs/observedRun2"]
    assert validate_w3_retained_report_schema_contract(root) == []


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
