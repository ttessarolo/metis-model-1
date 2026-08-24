from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
PLAN_PATH = ROOT / "manifests/initial-local-qlora-plan-v1.json"
PLAN_SCHEMA_PATH = ROOT / "schemas/initial-local-qlora-plan.schema.json"
EXCLUSIONS_PATH = ROOT / "manifests/initial-local-qlora-exclusions-v1.json"
SUCCESSOR_PATH = ROOT / "manifests/catalog-maintenance-successor-probe-v1.json"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _self_hash(document: dict[str, Any], field: str) -> str:
    return _hash({key: value for key, value in document.items() if key != field})


def test_initial_local_qlora_plan_is_strict_and_self_hashed() -> None:
    plan = _load(PLAN_PATH)
    schema = _load(PLAN_SCHEMA_PATH)
    assert sorted(error.message for error in Draft202012Validator(schema).iter_errors(plan)) == []
    assert plan["plan_sha256"] == _self_hash(plan, "plan_sha256")
    assert plan["user_mandate"] == "INITIAL_LOCAL_QLORA_V1"
    assert plan["status"] == "user_mandated_post_output_recovery"
    assert plan["decision_boundary"] == {
        "o011_limited_waiver": "new_initial_local_adapter_only",
        "o010_delta_not_used": True,
        "o003_promotion_not_opened": True,
    }
    assert plan["pinned_inputs"]["metis_implementation"] == {
        "surface_revision": "1f7eaae9d803edc90f51ff492ea443f18570015e",
        "revision": "5e112f9148f40e7e792052e896c5a9efe8eaf0a2",
        "tree": "41c7a2b6890fa42d8123bd93f6560d0b9bfae8af",
        "language_version": "0.43",
        "external_checkout": "read_only",
    }


def test_exclusions_are_hashed_and_match_the_four_successor_author_cases() -> None:
    exclusions = _load(EXCLUSIONS_PATH)
    successor = _load(SUCCESSOR_PATH)
    assert exclusions["exclusions_sha256"] == _self_hash(exclusions, "exclusions_sha256")
    assert exclusions["source_successor_manifest"]["sha256"] == successor["manifest_sha256"]
    expected_cases = [case for case in successor["cases"] if case["mode"] == "author"]
    actual_cases = exclusions["ambiguous_successor_author_cases"]
    assert len(actual_cases) == 4
    actual_ids = [case["case_id"] for case in actual_cases]
    expected_ids = [case["case_id"] for case in expected_cases]
    assert actual_ids == expected_ids
    records = {record["path"]: record for record in successor["files"]}
    for actual, expected in zip(actual_cases, expected_cases, strict=True):
        assert actual["semantic_root"] == expected["root_id"]
        assert actual["template_id"] == expected["template_id"]
        assert actual["fixture_path"] == expected["fixture_path"]
        assert actual["fixture_sha256"] == records[actual["fixture_path"]]["sha256"]
    assert exclusions["forbidden_inputs"] == [
        "all_successor_model_outputs",
        "all_successor_prompts",
        "all_successor_oracle_records",
        "all_successor_expected_sources",
        "b12_raw_model_outputs",
    ]
    assert exclusions["forbidden_destinations"] == [
        "base_dev16",
        "adapter_dev16_step_gates",
        "frozen_b12_adapter_replay",
        "train",
        "dev",
        "checkpoint_selection",
        "adapter_package",
    ]


def test_plan_binds_exclusions_and_preserves_local_only_authority() -> None:
    plan = _load(PLAN_PATH)
    exclusions = _load(EXCLUSIONS_PATH)
    assert plan["exclusions"]["manifest_sha256"] == exclusions["exclusions_sha256"]
    assert plan["exclusions"]["ambiguous_case_count"] == 4
    assert plan["exclusions"]["b12_raw_outputs_train_dev_forbidden"] is True
    authority = plan["authority"]
    assert all(
        authority[key] is False
        for key in (
            "network_dataset_train_eval",
            "downloads",
            "live_or_tenant_data",
            "credentials_or_env_dataset_train_eval",
            "privilege_or_services",
            "promotion",
            "accuracy99",
        )
    )
    assert authority["s3_adapter_backup_authorized_post_local_package"] is True
    assert authority["s3_profile_and_bucket_bound_in_backup_preimage"] is True
    assert authority["s3_adapter_package_only"] is True
    assert authority["s3_network_exception_only"] is True


def test_fixed_counts_training_caps_and_terminal_separation() -> None:
    plan = _load(PLAN_PATH)
    dataset = plan["dataset"]
    assert dataset["total_examples"] == dataset["train_examples"] + dataset["dev_examples"] == 80
    assert (
        sum(dataset["train_family_minimums"].values()) + dataset["canonical_replay_train_examples"]
        == 64
    )
    assert sum(dataset["dev_family_counts"].values()) == 16
    evaluation = plan["evaluation"]
    assert evaluation["dev_tasks"] == sum(evaluation["dev_family_counts"].values()) == 16
    assert evaluation["adapter_off_dev_baseline_once"] is True
    assert evaluation["same_frozen_dev_at_step_gates"] is True
    assert evaluation["b12_baseline_id"] == "B12-v4"
    assert evaluation["b12_tasks"] == 12
    assert evaluation["existing_frozen_b12_base_result_only"] is True
    assert evaluation["adapter_on_b12_replay_once"] is True
    assert evaluation["b12_terminal_independent"] is True
    assert evaluation["b12_never_training_or_selection_feedback"] is True
    assert plan["training"]["step_gates"] == [25, 50, 100]
    assert plan["training"]["configurations"] == 1
    assert plan["training"]["reworks_allowed"] == 0
    assert dataset["b12_may_not_drive_examples"] is True
    assert dataset["groups_disjoint_train_dev_b12"] is True
    assert plan["state_machine"] == [
        "contract_preimage_published",
        "dataset_materialized",
        "dataset_training_freeze_published",
        "base_dev16_consumed",
        "baseline_recovery_preimage_published",
        "recovery_freeze_v2_published",
        "baseline_exact_byte_imported",
        "qlora_step25",
        "optional_qlora_step50_or100_if_dev_gain",
        "adapter_dev16_consumed",
        "frozen_b12_adapter_replay",
        "local_verdict",
        "local_package",
        "s3_adapter_backup",
    ]
    assert plan["local_verdicts"] == [
        "LOCAL_ADAPTER_UPLIFT",
        "LOCAL_ADAPTER_EXPERIMENTAL",
        "STOP_B12_REGRESSION",
        "STOP_TECHNICAL",
    ]
    assert "STOP_NO_UPLIFT" not in plan["local_verdicts"]
    assert "b24" not in plan["evaluation"]
    assert "d24" not in plan["evaluation"]
    assert plan["artifact_policy"]["package_excludes"] == [
        "base_weights",
        "dataset",
        "optimizer_state",
        "raw_model_output",
        "raw_oracle_text",
        "logs",
        "credentials",
        "env",
    ]
