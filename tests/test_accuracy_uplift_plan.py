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
    evidence = {"path": "upstream/evidence.json", "sha256": "sha256:" + "a" * 64}
    return {
        "revision": "b" * 40,
        "tree": "c" * 40,
        "language_version": "0.44",
        "grammar": evidence,
        "validator": evidence,
        "compiler": evidence,
        "ir_contract": evidence,
        "retrieval_contract": evidence,
        "semantic_oracle": evidence,
        "tenant_threshold_setting_keys": evidence,
    }


def test_accuracy_uplift_plan_is_green_and_surface_pinned_only() -> None:
    assert contracts.validate_accuracy_uplift_plan_contract(ROOT) == []

    plan = load_json(PLAN_PATH)
    assert plan["upstream_grammar_dependency"]["status"] == "surface_pinned_implementation_pending"
    assert plan["gates"]["surface_pin_complete"] is True
    assert plan["gates"]["upstream_pin_complete"] is False
    assert plan["catalog_value_domain"]["materialization_allowed"] is False
    assert plan["gates"]["training_allowed"] is False


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
            }
        ),
    )

    errors = contracts.validate_accuracy_uplift_plan_contract(ROOT)

    assert "upstream pin gate disagrees with the grammar dependency status" in errors
    assert "retrieval/oracle refresh claimed before the implementation pin" in errors


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
