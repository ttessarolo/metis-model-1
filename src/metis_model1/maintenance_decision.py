"""Fail-closed boundary for the Model 1 B-only maintenance decision.

The deterministic D18/T30 thresholds are preregistered here, but the repository
does not yet contain the protected authority needed to trust model outputs or
oracle verdicts.  In particular, a local hash, file, Git remote-tracking ref,
or caller-created capability cannot prove semantic correctness, chronology, or
a one-shot T30 run.

Consequently this module currently emits only ``PROTECTED_AUTHORITY_REQUIRED``.
It deliberately cannot emit ``NO_INITIAL_TRAIN``, ``MICRO_QLORA_ELIGIBLE``,
``CONFIRM_LOCAL``, an observed accuracy, or training authority.  Those APIs fail
closed until L0 wires the independently rooted authority listed below.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

SCHEMA_VERSION = 1
STATUS = "PROTECTED_AUTHORITY_REQUIRED"
FAMILIES = ("F-1", "F-2", "F-3", "F-4", "F-5", "F-6")

D18_TOTAL = 18
D18_PER_FAMILY = 3
D18_NO_INITIAL_TRAIN_MIN_SUCCESSES = 17
D18_NO_INITIAL_TRAIN_FAMILY_MIN_SUCCESSES = 2
D18_MICRO_QLORA_MIN_CORRECTABLE_FAILURES = 3
D18_MICRO_QLORA_MIN_DISTINCT_ROOTS = 2

T30_TOTAL = 30
T30_PER_FAMILY = 5
T30_CONFIRM_MIN_SUCCESSES = 29
T30_CONFIRM_FAMILY_MIN_SUCCESSES = 4

AUTHORITY_REQUIREMENTS = (
    "remote_verified_preoutput_git_seal",
    "approved_independent_oracle_root",
    "signed_task_level_oracle_receipts",
    "executable_ast_ir_compatibility_receipt",
    "remote_verified_d18_freeze_before_t30",
    "protected_single_use_t30_nonce_ledger",
    "exact_t30_in30_out30_no_extra_attempts_receipt",
)


class MaintenanceDecisionError(ValueError):
    """Raised when a maintenance decision document is malformed."""


class ProtectedAuthorityRequired(MaintenanceDecisionError):
    """Raised whenever an authoritative D18 or T30 decision is attempted."""


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise MaintenanceDecisionError("value is not canonical JSON") from error


def _sha(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value)).hexdigest()


def _strict_int(value: Any, label: str) -> int:
    if type(value) is not int:
        raise MaintenanceDecisionError(f"{label} must be an int, not bool or another type")
    return value


def _strict_bool(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise MaintenanceDecisionError(f"{label} must be a strict bool")
    return value


def authority_requirements() -> tuple[str, ...]:
    """Return the exact independent authority roster still required by L0."""

    return AUTHORITY_REQUIREMENTS


def _body() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": STATUS,
        "scope": {
            "variant": "B",
            "system": "qwen3.8_base_plus_retrieval_and_compiler_loop",
            "adapter": "none",
            "evidence_scope": "no_observation_accepted_until_protected_authority",
            "population_accuracy_claim": False,
            "training_authority": False,
            "final_test_feedback_allowed": False,
        },
        "preregistered_policy": {
            "d18": {
                "task_count": D18_TOTAL,
                "tasks_per_family": D18_PER_FAMILY,
                "no_initial_train_min_successes": D18_NO_INITIAL_TRAIN_MIN_SUCCESSES,
                "no_initial_train_family_min_successes": (
                    D18_NO_INITIAL_TRAIN_FAMILY_MIN_SUCCESSES
                ),
                "micro_qlora_min_correctable_failures": (D18_MICRO_QLORA_MIN_CORRECTABLE_FAILURES),
                "micro_qlora_min_distinct_genealogy_roots": D18_MICRO_QLORA_MIN_DISTINCT_ROOTS,
                "zero_category_ambiguity_required": True,
                "zero_veto_and_recurring_failures_for_no_initial_train": True,
                "compatible_ast_ir_semantics_required": True,
                "training_authority_if_eligible": False,
            },
            "t30": {
                "task_count": T30_TOTAL,
                "tasks_per_family": T30_PER_FAMILY,
                "confirm_local_min_successes": T30_CONFIRM_MIN_SUCCESSES,
                "confirm_local_family_min_successes": T30_CONFIRM_FAMILY_MIN_SUCCESSES,
                "zero_category_ambiguity_required": True,
                "zero_veto_and_recurring_failures_required": True,
                "training_feedback_allowed": False,
                "population_accuracy_claim": False,
            },
        },
        "authority_requirements": list(AUTHORITY_REQUIREMENTS),
        "blocked_outputs": [
            "NO_INITIAL_TRAIN",
            "MICRO_QLORA_ELIGIBLE",
            "CONFIRM_LOCAL",
            "FAIL_LOCAL",
            "observed_accuracy",
            "wilson95",
        ],
        "observations": {
            "d18_results": None,
            "t30_results": None,
            "observed_accuracy": None,
            "wilson95": None,
            "per_family": {},
        },
        "decision": {
            "outcome": STATUS,
            "reason": "protected_semantic_and_chronology_authority_not_integrated",
            "training_authority": False,
            "promotion_eligible": False,
        },
    }


def build_blocked_maintenance_contract() -> dict[str, Any]:
    """Return the only truthful decision document available at present."""

    body = _body()
    return {**body, "decision_sha256": _sha(body)}


def _load_schema() -> dict[str, Any]:
    path = _repository_root() / "schemas" / "maintenance-decision.schema.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(value)
    except (OSError, json.JSONDecodeError, SchemaError) as error:
        raise MaintenanceDecisionError("fixed maintenance decision schema is unreadable") from error
    return value


def validate_maintenance_decision(document: Any) -> dict[str, Any]:
    """Validate the fixed blocked contract; no caller-supplied schema is accepted."""

    errors = sorted(
        Draft202012Validator(_load_schema()).iter_errors(document),
        key=lambda error: list(error.absolute_path),
    )
    if errors:
        rendered = "; ".join(
            f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}"
            for error in errors
        )
        raise MaintenanceDecisionError("maintenance decision schema validation: " + rendered)
    expected = build_blocked_maintenance_contract()
    # These explicit checks pin bool/int behavior even if jsonschema changes its
    # Python type checker in a future dependency release.
    d18 = document["preregistered_policy"]["d18"]
    t30 = document["preregistered_policy"]["t30"]
    for label, value in (
        ("d18.task_count", d18["task_count"]),
        ("d18.tasks_per_family", d18["tasks_per_family"]),
        ("t30.task_count", t30["task_count"]),
        ("t30.tasks_per_family", t30["tasks_per_family"]),
    ):
        _strict_int(value, label)
    for label, value in (
        ("scope.training_authority", document["scope"]["training_authority"]),
        ("scope.final_test_feedback_allowed", document["scope"]["final_test_feedback_allowed"]),
        ("t30.training_feedback_allowed", t30["training_feedback_allowed"]),
    ):
        _strict_bool(value, label)
    if document != expected:
        raise MaintenanceDecisionError("blocked maintenance contract differs from recomputation")
    return copy.deepcopy(document)


def _authority_unavailable(operation: str) -> None:
    # Consume no caller-controlled result content before the authority exists.
    raise ProtectedAuthorityRequired(
        f"{operation} requires the protected authority hook: " + ", ".join(AUTHORITY_REQUIREMENTS)
    )


def build_d18_maintenance_decision(*args: object, **kwargs: object) -> None:
    """Fail closed until protected semantic and chronology authority is wired."""

    _authority_unavailable("D18 decision")


def attach_t30_confirmation(*args: object, **kwargs: object) -> None:
    """Fail closed until the pushed D18 freeze and one-shot T30 ledger exist."""

    _authority_unavailable("T30 confirmation")
