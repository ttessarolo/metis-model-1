"""Read-only integrated pilot checks for the Model 1 foundation.

The pilot command deliberately validates the contracts that can be checked
offline, while keeping the W5 promotion decision separate.  A green contract
report therefore does not imply that a real benchmark or a training run has
been completed.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from metis_model1.assets import validate_asset_register
from metis_model1.closure import (
    PINNED_REVISION,
    build_manifest,
    validate_manifest,
)
from metis_model1.contracts import (
    load_json,
    repository_root,
    validate_foundation,
    validate_w5_xs_plan_contract,
)
from metis_model1.dataset import (
    build_split_manifest,
    dataset_manifest,
    validate_dataset,
    validate_example,
    validate_split_manifest,
)
from metis_model1.evaluator import evaluate_observations

DEFAULT_METIS_ROOT = Path("/Users/tommasotessarolo/Developer/ares-matioska/metis")


def _error_text(error: object) -> str:
    return f"{type(error).__name__}: {error}"


def _load(path: Path) -> Any:
    return load_json(path)


def _dataset_check(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    dataset: Mapping[str, Any] = {}
    try:
        row = _load(root / "examples/dataset-example.synthetic.json")
        dataset = _load(root / "examples/dataset-manifest.synthetic.json")
        split = _load(root / "examples/split-manifest.synthetic.json")
        rows = [row]

        errors = validate_example(row)
        errors.extend(validate_dataset(rows, dataset))
        expected_split = build_split_manifest(rows)
        errors.extend(validate_split_manifest(rows, split))
        expected_dataset = dataset_manifest(
            rows, split_manifest_id=expected_split["split_manifest_id"]
        )
        if dataset != expected_dataset:
            errors.append("dataset manifest is not byte-for-byte deterministic")
        if split != expected_split:
            errors.append("split manifest is not byte-for-byte deterministic")
    except Exception as error:  # noqa: BLE001 - malformed fixtures are reportable failures
        errors = [_error_text(error)]
    example_ids = [row.get("example_id") for row in rows if isinstance(row.get("example_id"), str)]
    denominators = {
        "examples_in": len(rows),
        "examples_out": dataset.get("example_count") if isinstance(dataset, Mapping) else None,
        "example_ids_distinct": len(set(example_ids)),
        "gaps": 0 if len(rows) == 1 else 1,
    }
    return {"valid": not errors, "errors": sorted(set(errors))}, denominators


def _closure_check(
    root: Path, metis_root: Path
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
    errors: list[str] = []
    try:
        manifest = _load(root / "manifests/slice-30-closure.json")
        validate_manifest(manifest)
        recomputed = build_manifest(
            metis_root,
            root / "manifests/benchmark-plan.json",
            PINNED_REVISION,
        )
        if manifest != recomputed:
            errors.append("closure manifest does not exactly match the pinned Metis Git objects")
    except Exception as error:  # noqa: BLE001 - malformed fixtures are reportable failures
        manifest = {}
        errors.append(_error_text(error))
    if not isinstance(manifest, Mapping):
        manifest = {}
    counts = manifest.get("counts", {}) if isinstance(manifest, Mapping) else {}
    denominators = {
        "tasks_in": counts.get("tasks_in"),
        "tasks_out": counts.get("tasks_out"),
        "task_ids_distinct": counts.get("task_ids_distinct"),
        "sources_in": counts.get("sources_in"),
        "sources_out": counts.get("sources_out"),
        "source_paths_distinct": counts.get("source_paths_distinct"),
        "source_blob_oids_distinct": counts.get("source_blob_oids_distinct"),
        "gaps": counts.get("gaps"),
        "distinct_leakage_groups": manifest.get("distinct_leakage_groups"),
    }
    return {"valid": not errors, "errors": errors}, denominators, dict(manifest)


def _asset_check(
    root: Path, closure: Mapping[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        register = _load(root / "manifests/slice-30-assets.json")
        errors = validate_asset_register(register, closure)
    except Exception as error:  # noqa: BLE001 - malformed fixtures are reportable failures
        register, errors = {}, [_error_text(error)]
    counts = register.get("counts", {}) if isinstance(register, Mapping) else {}
    return (
        {"valid": not errors, "errors": sorted(set(errors))},
        {
            "assets_in": counts.get("assets_in"),
            "assets_out": counts.get("assets_out"),
            "asset_paths_distinct": counts.get("asset_paths_distinct"),
            "asset_blob_oids_distinct": counts.get("asset_blob_oids_distinct"),
            "gaps": counts.get("gaps"),
        },
    )


def _evaluation_check(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    errors: list[str] = []
    try:
        fixture = _load(root / "examples/evaluation-report.synthetic.json")
        generated = evaluate_observations(fixture["observations"])
        if generated != fixture:
            errors.append("evaluation fixture is not an exact regeneration from observations")
    except Exception as error:  # noqa: BLE001 - malformed fixtures are reportable failures
        generated = {}
        errors.append(_error_text(error))
    denominator = generated.get("denominator", {})
    return (
        {"valid": not errors, "errors": errors},
        {
            "tasks": denominator.get("tasks"),
            "observations_in": denominator.get("in"),
            "observations_out": denominator.get("out"),
            "expected_observations": denominator.get("expected_observations"),
            "distinct_task_ids": denominator.get("distinct_task_ids"),
            "gaps": denominator.get("gaps"),
        },
    )


def _open_decisions(root: Path) -> dict[str, list[str]]:
    """Derive the current W5 decision roster from the tracked register."""

    register = _load(root / "manifests/decision-register.json")
    decisions = register.get("open_decisions")
    if not isinstance(decisions, list):
        raise ValueError("decision register has no open_decisions roster")
    blocking: list[str] = []
    nonblocking: list[str] = []
    for decision in decisions:
        if not isinstance(decision, Mapping) or decision.get("status") != "open":
            continue
        decision_id = decision.get("id")
        blocks = decision.get("blocks")
        if not isinstance(decision_id, str) or not isinstance(blocks, list):
            raise ValueError("open decision has an invalid id or blocks roster")
        (blocking if "W5" in blocks else nonblocking).append(decision_id)
    return {"blocking": sorted(blocking), "nonblocking": sorted(nonblocking)}


def _accuracy99_promotion_readiness(
    root: Path,
    closure: Mapping[str, Any] | None,
    open_decisions: Mapping[str, list[str]],
) -> tuple[bool, list[str]]:
    """Return strict Accuracy-99 promotion readiness without research shortcuts."""

    accuracy_target = _load(root / "manifests/accuracy-target.json")
    minimum_groups = accuracy_target.get("minimum_distinct_leakage_groups")
    groups = closure.get("distinct_leakage_groups") if closure else None
    blockers: list[str] = []
    if not isinstance(minimum_groups, int) or groups is None or groups < minimum_groups:
        blockers.append(
            f"leakage groups {groups}/{minimum_groups} "
            f"(minimum required distinct groups: {minimum_groups})"
        )
    closure_status = closure.get("status") if closure else None
    tasks = closure.get("tasks") if closure else None
    unresolved = not isinstance(tasks, list) or any(
        not isinstance(task, Mapping)
        or task.get("closure_status") != "sealed"
        or bool(task.get("unresolved_dependencies"))
        for task in tasks
    )
    if closure_status != "sealed" or unresolved:
        blockers.append(f"closure {closure_status}; task-specific oracles unresolved")
    # The integrated W3 path deliberately validates only the synthetic contract
    # fixture.  A future real-data path must add its own validator before this
    # blocker can be removed; mere file presence can never make W5 ready.
    blockers.append("W3 is synthetic-only; no validated real dataset is present")
    if open_decisions.get("blocking"):
        blockers.append("open decisions blocking W5: " + ",".join(open_decisions["blocking"]))
    blockers.append("A/B baseline is absent")
    return not blockers, blockers


_EXPERIMENT_NONCLAIMS = (
    "no_physical_checkpoint_verification",
    "no_inference_authority",
    "no_dataset_authority",
    "no_training_authority",
    "no_semantic_uplift_evidence",
    "nonpromotable",
    "non99",
)


def assess_experiment_plan(root: Path | None = None) -> dict[str, Any]:
    """Assess only the tracked W5-XS plan; never inspect or execute model payloads."""

    root = (root or repository_root()).resolve()
    try:
        blockers = validate_w5_xs_plan_contract(root)
    except Exception as error:  # noqa: BLE001 - the command must fail closed
        blockers = [f"W5-XS plan validation failed: {_error_text(error)}"]
    ready = not blockers
    return {
        "schema_version": 1,
        "status": "EXPERIMENT_PLAN_READY" if ready else "EXPERIMENT_PLAN_BLOCKED",
        "ready": ready,
        "planned_next_stage": "REQUEST_W5_XS_EXECUTION_MANDATE",
        "first_stage_after_execution_mandate": "XS0_THIN_RUNNER_AND_B12_ROSTER",
        "execution_authorized": False,
        "physical_checkpoint_verified": False,
        "blockers": list(blockers),
        "nonclaims": list(_EXPERIMENT_NONCLAIMS),
    }


def render_experiment_plan_text(report: Mapping[str, Any]) -> str:
    """Render the plan-only W5-XS gate without implying execution authority."""

    lines = [
        f"EXPERIMENT plan={'READY' if report['ready'] else 'BLOCKED'} "
        f"next={report['planned_next_stage']}",
        "EXECUTION authorized=false physical_checkpoint_verified=false",
    ]
    lines.extend(f"PLAN_BLOCKER {blocker}" for blocker in report["blockers"])
    lines.extend(f"NONCLAIM {nonclaim}" for nonclaim in report["nonclaims"])
    return "\n".join(lines)


def validate_pilot(
    root: Path | None = None,
    metis_root: Path | None = None,
) -> dict[str, Any]:
    """Validate the integrated offline pilot without writing any runtime files."""

    root = (root or repository_root()).resolve()
    metis_root = (metis_root or DEFAULT_METIS_ROOT).resolve()
    try:
        foundation = validate_foundation(root)
        foundation_result = {
            "valid": foundation.ok,
            "errors": list(foundation.errors),
            "passes": len(foundation.passes),
        }
    except Exception as error:  # noqa: BLE001 - malformed foundations are reportable failures
        foundation_result = {
            "valid": False,
            "errors": [_error_text(error)],
            "passes": 0,
        }
    closure_result, closure_denominators, closure = _closure_check(root, metis_root)
    asset_result, asset_denominators = _asset_check(root, closure)
    dataset_result, dataset_denominators = _dataset_check(root)
    evaluation_result, evaluation_denominators = _evaluation_check(root)
    checks = {
        "foundation": foundation_result,
        "closure": closure_result,
        "assets": asset_result,
        "dataset": dataset_result,
        "evaluation": evaluation_result,
    }
    contract_valid = all(check["valid"] for check in checks.values())
    try:
        open_decisions = _open_decisions(root)
        promotion_ready, promotion_blockers = _accuracy99_promotion_readiness(
            root, closure, open_decisions
        )
    except Exception as error:  # noqa: BLE001 - readiness must fail closed
        open_decisions = {"blocking": ["decision-register-unreadable"], "nonblocking": []}
        promotion_ready = False
        promotion_blockers = [f"readiness contract invalid: {_error_text(error)}"]
    return {
        "schema_version": 1,
        "status": "valid" if contract_valid else "invalid",
        "contract_valid": contract_valid,
        "w5_readiness": {
            "ready": promotion_ready,
            "status": "ready" if promotion_ready else "blocked",
            "blockers": promotion_blockers,
        },
        "checks": checks,
        "denominators": {
            "closure": closure_denominators,
            "assets": asset_denominators,
            "dataset": dataset_denominators,
            "evaluation": evaluation_denominators,
        },
        "source_anchor": {
            "project_root": str(root),
            "metis_root": str(metis_root),
            "revision": PINNED_REVISION,
            "verified": closure_result["valid"],
        },
        "open_decisions": open_decisions,
    }


def render_pilot_text(report: Mapping[str, Any]) -> str:
    """Render a compact, denominator-bearing report for terminal use."""

    lines = [
        f"PILOT contracts={'VALID' if report['contract_valid'] else 'INVALID'}",
        f"W5 readiness={'READY' if report['w5_readiness']['ready'] else 'BLOCKED'}",
    ]
    for name, values in report["denominators"].items():
        rendered = " ".join(f"{key}={value}" for key, value in values.items())
        lines.append(f"DENOMINATOR {name} {rendered}")
    for blocker in report["w5_readiness"]["blockers"]:
        lines.append(f"BLOCKER {blocker}")
    for name, check in report["checks"].items():
        lines.append(f"CHECK {name}={'PASS' if check['valid'] else 'FAIL'}")
        lines.extend(f"ERROR {name}: {error}" for error in check["errors"])
    return "\n".join(lines)
