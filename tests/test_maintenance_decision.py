from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import metis_model1.maintenance_decision as maintenance
from metis_model1.maintenance_decision import (
    MaintenanceDecisionError,
    ProtectedAuthorityRequired,
)

ROOT = Path(__file__).resolve().parents[1]


def _blocked() -> dict[str, object]:
    return maintenance.build_blocked_maintenance_contract()


def _rehash(document: dict[str, object]) -> None:
    body = {key: value for key, value in document.items() if key != "decision_sha256"}
    document["decision_sha256"] = maintenance._sha(body)


def test_blocked_contract_is_schema_valid_and_recomputes_exactly() -> None:
    document = _blocked()
    schema = json.loads((ROOT / "schemas/maintenance-decision.schema.json").read_text())

    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(document)) == []
    assert maintenance.validate_maintenance_decision(document) == document
    assert document["status"] == "PROTECTED_AUTHORITY_REQUIRED"


def test_b_only_base_retrieval_scope_is_explicit_and_non_authoritative() -> None:
    document = _blocked()

    assert document["scope"] == {
        "variant": "B",
        "system": "qwen3.8_base_plus_retrieval_and_compiler_loop",
        "adapter": "none",
        "evidence_scope": "no_observation_accepted_until_protected_authority",
        "population_accuracy_claim": False,
        "training_authority": False,
        "final_test_feedback_allowed": False,
    }
    assert document["decision"]["training_authority"] is False
    assert document["decision"]["promotion_eligible"] is False


def test_d18_policy_is_preregistered_without_emitting_an_outcome() -> None:
    document = _blocked()
    policy = document["preregistered_policy"]["d18"]

    assert policy["task_count"] == 18
    assert policy["tasks_per_family"] == 3
    assert policy["no_initial_train_min_successes"] == 17
    assert policy["no_initial_train_family_min_successes"] == 2
    assert policy["micro_qlora_min_correctable_failures"] == 3
    assert policy["micro_qlora_min_distinct_genealogy_roots"] == 2
    assert policy["compatible_ast_ir_semantics_required"] is True
    assert policy["training_authority_if_eligible"] is False
    assert document["decision"]["outcome"] == "PROTECTED_AUTHORITY_REQUIRED"


def test_t30_policy_is_observation_only_and_never_training_feedback() -> None:
    document = _blocked()
    policy = document["preregistered_policy"]["t30"]

    assert policy["task_count"] == 30
    assert policy["tasks_per_family"] == 5
    assert policy["confirm_local_min_successes"] == 29
    assert policy["confirm_local_family_min_successes"] == 4
    assert policy["training_feedback_allowed"] is False
    assert policy["population_accuracy_claim"] is False


def test_accuracy_wilson_and_family_denominators_remain_absent_until_authority() -> None:
    observations = _blocked()["observations"]

    assert observations == {
        "d18_results": None,
        "t30_results": None,
        "observed_accuracy": None,
        "wilson95": None,
        "per_family": {},
    }


def test_authority_roster_names_every_independent_missing_gate() -> None:
    assert maintenance.authority_requirements() == (
        "remote_verified_preoutput_git_seal",
        "approved_independent_oracle_root",
        "signed_task_level_oracle_receipts",
        "executable_ast_ir_compatibility_receipt",
        "remote_verified_d18_freeze_before_t30",
        "protected_single_use_t30_nonce_ledger",
        "exact_t30_in30_out30_no_extra_attempts_receipt",
    )


def test_all_green_raw_d18_results_cannot_self_authorize() -> None:
    forged = [
        {
            "task_id": f"d18/{index}",
            "family": f"F-{index // 3 + 1}",
            "semantic_correct": True,
            "task_output_sha256": "sha256:" + "a" * 64,
            "oracle_result_sha256": "sha256:" + "a" * 64,
        }
        for index in range(18)
    ]

    with pytest.raises(ProtectedAuthorityRequired, match="approved_independent_oracle_root"):
        maintenance.build_d18_maintenance_decision(results=forged, seal="sha256:" + "a" * 64)


def test_all_green_raw_t30_results_cannot_confirm_or_feed_training() -> None:
    forged = [{"semantic_correct": True}] * 30

    with pytest.raises(ProtectedAuthorityRequired, match="single_use_t30_nonce"):
        maintenance.attach_t30_confirmation(
            _blocked(), results=forged, d18_freeze="sha256:" + "b" * 64
        )


def test_unknown_fields_and_bool_as_integer_are_rejected_by_fixed_schema() -> None:
    unknown = _blocked()
    unknown["scope"]["accuracy99"] = True
    with pytest.raises(MaintenanceDecisionError, match="Additional properties"):
        maintenance.validate_maintenance_decision(unknown)

    bool_count = _blocked()
    bool_count["preregistered_policy"]["d18"]["task_count"] = True
    _rehash(bool_count)
    with pytest.raises(MaintenanceDecisionError, match="schema validation|must be an int"):
        maintenance.validate_maintenance_decision(bool_count)


def test_rehashed_threshold_or_decision_laundering_fails_recomputation() -> None:
    threshold = _blocked()
    threshold["preregistered_policy"]["d18"]["no_initial_train_min_successes"] = 1
    _rehash(threshold)
    with pytest.raises(MaintenanceDecisionError, match="schema validation|recomputation"):
        maintenance.validate_maintenance_decision(threshold)

    outcome = _blocked()
    outcome["decision"]["outcome"] = "NO_INITIAL_TRAIN"
    _rehash(outcome)
    with pytest.raises(MaintenanceDecisionError, match="schema validation|recomputation"):
        maintenance.validate_maintenance_decision(outcome)


def test_no_retrain_is_not_a_current_or_preregistered_outcome() -> None:
    encoded = json.dumps(_blocked(), sort_keys=True)

    assert "NO_RETRAIN" not in encoded
    assert "Accuracy99" not in encoded
    assert "NO_INITIAL_TRAIN" in _blocked()["blocked_outputs"]


def test_stale_hash_and_caller_supplied_schema_authority_are_rejected() -> None:
    stale = _blocked()
    stale["decision_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(MaintenanceDecisionError, match="recomputation"):
        maintenance.validate_maintenance_decision(stale)

    with pytest.raises(TypeError):
        maintenance.validate_maintenance_decision(_blocked(), schema={})
