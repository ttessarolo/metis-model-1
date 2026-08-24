from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

import metis_model1.contracts as contracts
from metis_model1.contracts import load_json, repository_root, validate_instance

ROOT = repository_root()
PLAN_PATH = ROOT / "manifests/accuracy-uplift-plan.json"
SCHEMA_PATH = ROOT / "schemas/accuracy-uplift-plan.schema.json"


def _mutate_loaded_file(
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    mutation: Callable[[dict[str, Any]], None],
) -> None:
    original = contracts.load_json

    def load(path: Path) -> Any:
        value = original(path)
        if Path(path).name == filename:
            value = deepcopy(value)
            mutation(value)
        return value

    monkeypatch.setattr(contracts, "load_json", load)


def _complete_upstream_pin() -> dict[str, Any]:
    evidence = {
        "path": "tooling/evidence.ts",
        "blob_oid": "a" * 40,
        "sha256": "sha256:" + "a" * 64,
    }
    return {
        "revision": "5e112f9148f40e7e792052e896c5a9efe8eaf0a2",
        "tree": "41c7a2b6890fa42d8123bd93f6560d0b9bfae8af",
        "language_version": "0.43",
        "implementation_manifest": {
            "path": "manifests/catalog-maintenance-pin-v1.json",
            "sha256": "sha256:1cec5b53f7dc21a9f0100cb4ff51f7beffca00d157e557ae4e7dff336dac05f5",
        },
        "grammar": evidence,
        "validator": evidence,
        "compiler": evidence,
        "ir_contract": evidence,
        "retrieval_contract": evidence,
        "semantic_oracle": evidence,
        "tenant_threshold_setting_keys": evidence,
    }


def test_accuracy_uplift_plan_is_green_and_implementation_pinned() -> None:
    assert contracts.validate_accuracy_uplift_plan_contract(ROOT) == []

    plan = load_json(PLAN_PATH)
    assert plan["upstream_grammar_dependency"]["status"] == "pinned"
    assert plan["gates"]["surface_pin_complete"] is True
    assert plan["gates"]["upstream_pin_complete"] is True
    assert plan["gates"]["retrieval_contract_refreshed"] is False
    assert plan["gates"]["semantic_oracle_refreshed"] is False
    assert plan["status"] == "retrieval_refresh_active"
    assert plan["gates"]["active_work"] == "retrieval_refresh"
    assert plan["catalog_value_domain"]["materialization_allowed"] is False
    assert plan["gates"]["training_allowed"] is False
    assert plan["maintenance"]["default_verdict"] == "NO_INITIAL_TRAIN"
    assert plan["historical_evidence"]["fine_tuned_adapter_present"] is False
    assert plan["historical_evidence"]["semantic_score"] == "11/12"
    assert plan["historical_evidence"]["source_oracle_audit"] == "12/12"
    assert "catalog_retrieval_adapter_contract_work" in plan["execution_partition"]["allowed_now"]
    assert plan["maintenance_benchmark_evidence"] == {
        "roster": None,
        "pre_output_seal": None,
        "decision_report": None,
    }


def test_schema_rejects_provisional_surface_tokens() -> None:
    plan = load_json(PLAN_PATH)
    schema = load_json(SCHEMA_PATH)
    plan["catalog_value_domain"]["canonical_tokens"] = ["provisional"]

    errors = validate_instance(plan, schema)

    assert any("Additional properties are not allowed" in error for error in errors)


def test_schema_rejects_a_pin_while_dependency_status_is_pending() -> None:
    plan = load_json(PLAN_PATH)
    schema = load_json(SCHEMA_PATH)
    plan["upstream_grammar_dependency"]["status"] = "awaiting_upstream_pin"
    plan["upstream_grammar_dependency"]["pin"] = _complete_upstream_pin()

    assert validate_instance(plan, schema)


def test_schema_rejects_surface_pin_identity_drift() -> None:
    plan = load_json(PLAN_PATH)
    schema = load_json(SCHEMA_PATH)
    plan["upstream_grammar_dependency"]["pin"]["revision"] = "0" * 40

    assert validate_instance(plan, schema)


def test_semantic_gate_rejects_spec_hash_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    _mutate_loaded_file(
        monkeypatch,
        "accuracy-uplift-plan.json",
        lambda plan: plan["canonical_spec"].update({"sha256": "sha256:" + "0" * 64}),
    )

    assert "accuracy-uplift canonical specification hash contains drift" in (
        contracts.validate_accuracy_uplift_plan_contract(ROOT)
    )


def test_semantic_gate_rejects_split_arithmetic_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    _mutate_loaded_file(
        monkeypatch,
        "accuracy-uplift-plan.json",
        lambda plan: plan["wave"]["diagnostic"]["family_counts"].update({"F-1": 2}),
    )

    assert "accuracy-uplift diagnostic family counts do not sum to total" in (
        contracts.validate_accuracy_uplift_plan_contract(ROOT)
    )


def test_semantic_gate_rejects_training_authority_laundering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mutate_loaded_file(
        monkeypatch,
        "accuracy-uplift-plan.json",
        lambda plan: plan["gates"].update({"training_allowed": True}),
    )

    errors = contracts.validate_accuracy_uplift_plan_contract(ROOT)

    assert "accuracy-uplift planning contract cannot authorize training" in errors


def test_semantic_gate_rejects_counter_only_t30_false_seal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forge_counter_only_seal(plan: dict[str, Any]) -> None:
        plan["wave"]["final_test"].update(
            {
                "materialized": 30,
                "seal_status": "sealed_pre_output",
                "model_outputs_allowed": True,
            }
        )
        plan["wave"]["diagnostic"]["model_outputs_allowed"] = True
        plan["gates"].update(
            {
                "t30_sealed_before_model_outputs": True,
                "model_evaluation_allowed": True,
            }
        )

    _mutate_loaded_file(
        monkeypatch,
        "accuracy-uplift-plan.json",
        forge_counter_only_seal,
    )

    errors = contracts.validate_accuracy_uplift_plan_contract(ROOT)

    assert "T30 claims a seal without verified roster and pre-output evidence" in errors


def test_semantic_gate_rejects_nonexistent_evidence_false_seal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forge_nonexistent_evidence_seal(plan: dict[str, Any]) -> None:
        fake = {"path": "does/not/exist.json", "sha256": "sha256:" + "a" * 64}
        plan["maintenance_benchmark_evidence"].update({"roster": fake, "pre_output_seal": fake})
        plan["wave"]["final_test"].update(
            {
                "materialized": 30,
                "seal_status": "sealed_pre_output",
                "model_outputs_allowed": True,
            }
        )
        plan["wave"]["diagnostic"]["model_outputs_allowed"] = True
        plan["gates"].update(
            {
                "t30_sealed_before_model_outputs": True,
                "model_evaluation_allowed": True,
            }
        )

    _mutate_loaded_file(
        monkeypatch,
        "accuracy-uplift-plan.json",
        forge_nonexistent_evidence_seal,
    )

    errors = contracts.validate_accuracy_uplift_plan_contract(ROOT)

    assert any("Git pre-output verifier is not integrated" in error for error in errors)


def test_semantic_gate_rejects_unbacked_materialization_counters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forge_materialization(plan: dict[str, Any]) -> None:
        plan["wave"]["diagnostic"]["materialized"] = 18
        plan["wave"]["final_test"]["materialized"] = 30

    _mutate_loaded_file(
        monkeypatch,
        "accuracy-uplift-plan.json",
        forge_materialization,
    )

    errors = contracts.validate_accuracy_uplift_plan_contract(ROOT)

    assert any("materialization counters remain zero" in error for error in errors)


def test_semantic_gate_rejects_previous_adapter_wording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mutate_loaded_file(
        monkeypatch,
        "accuracy-uplift-plan.json",
        lambda plan: plan["maintenance"].update({"default_verdict": "NO_RETRAIN"}),
    )

    errors = contracts.validate_accuracy_uplift_plan_contract(ROOT)

    assert any("default_verdict" in error and "NO_INITIAL_TRAIN" in error for error in errors)


def test_semantic_gate_rejects_implementation_or_refresh_laundering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mutate_loaded_file(
        monkeypatch,
        "accuracy-uplift-plan.json",
        lambda plan: plan["gates"].update(
            {
                "upstream_pin_complete": True,
                "retrieval_contract_refreshed": True,
                "semantic_oracle_refreshed": True,
            }
        ),
    )

    errors = contracts.validate_accuracy_uplift_plan_contract(ROOT)

    assert any("retrieval/oracle refresh verifier is not integrated" in error for error in errors)
    assert "refreshed catalog-domain state is not ready for materialization" in errors


def test_semantic_gate_rejects_catalog_pin_evidence_laundering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mutate_loaded_file(
        monkeypatch,
        "accuracy-uplift-plan.json",
        lambda plan: plan["upstream_grammar_dependency"]["pin"]["grammar"].update(
            {"sha256": "sha256:" + "0" * 64}
        ),
    )

    errors = contracts.validate_accuracy_uplift_plan_contract(ROOT)

    assert "accuracy plan catalog pin evidence differs for grammar" in errors


def test_semantic_gate_requires_ratified_maintenance_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def remove_o010(register: dict[str, Any]) -> None:
        register["open_decisions"] = [
            decision for decision in register["open_decisions"] if decision.get("id") != "O-010"
        ]

    _mutate_loaded_file(monkeypatch, "decision-register.json", remove_o010)

    assert "O-010 is not uniquely and fully ratified" in (
        contracts.validate_accuracy_uplift_plan_contract(ROOT)
    )


@pytest.mark.parametrize(
    "forbidden",
    [
        "catalog_domain_prompt_truth",
        "catalog_domain_oracle_truth",
        "catalog_domain_split_materialization",
        "t30_model_outputs_before_complete_seal",
        "tenant_value_payloads",
        "training",
    ],
)
def test_pinned_pre_refresh_state_requires_every_forbidden_operation(
    monkeypatch: pytest.MonkeyPatch,
    forbidden: str,
) -> None:
    _mutate_loaded_file(
        monkeypatch,
        "accuracy-uplift-plan.json",
        lambda plan: plan["execution_partition"]["forbidden_now"].remove(forbidden),
    )

    errors = contracts.validate_accuracy_uplift_plan_contract(ROOT)

    assert "pre-refresh execution partition omits a fail-closed prohibition" in errors


def test_historical_score_is_distinct_from_source_oracle_audit_coverage() -> None:
    plan = load_json(PLAN_PATH)

    assert plan["historical_evidence"]["semantic_score"] == "11/12"
    assert plan["historical_evidence"]["source_oracle_audit"] == "12/12"
    assert "semantic_audit" not in plan["historical_evidence"]
