"""Deterministic, fail-closed W1 evidence-only seal sidecars.

This module deliberately describes present absence: it binds the 30 allocated
tasks to their intended oracle cells, one correlated leakage group, and the
ratified 600-task family targets.  It cannot manufacture an execution receipt,
an AST/IR signature, a legal decision, or a green seal.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from metis_model1.provenance import canonical_json_hash, normalize_json
from metis_model1.w1_blockers import validate_blocker_map
from metis_model1.w2_rights import validate_rights_dossier

EXPECTED_TASKS = 30
EXPECTED_ASSETS = 201
EXPECTED_CELLS = 160
EXPECTED_F4_F6_CELLS = 75
EXPECTED_GROUPS = 1
MINIMUM_GROUPS = 563
FAMILY_ORDER = ("F-1", "F-2", "F-3", "F-4", "F-5", "F-6")
FAMILY_TARGETS = {"F-1": 100, "F-2": 110, "F-3": 110, "F-4": 110, "F-5": 90, "F-6": 80}
INPUT_FILES = {
    "benchmark_plan": "manifests/benchmark-plan.json",
    "closure": "manifests/slice-30-closure.json",
    "assets": "manifests/slice-30-assets.json",
    "blocker_map": "manifests/w1-slice-30-blocker-map-v1.json",
    "rights_dossier": "manifests/w2-rights-dossier-v1.json",
    "accuracy_target": "manifests/accuracy-target.json",
    "decision_register": "manifests/decision-register.json",
}


class W1SealError(ValueError):
    """Raised when an evidence-only sidecar cannot prove its input contract."""


def _root(root: Path | None) -> Path:
    return Path(__file__).resolve().parents[2] if root is None else Path(root)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise W1SealError(f"{path.name} must contain an object")
    return value


def _file_hash(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(value: Mapping[str, Any]) -> str:
    return "sha256:" + canonical_json_hash(normalize_json(dict(value)))


def _body(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in manifest.items() if key != "manifest_hash"}


def manifest_hash(manifest: Mapping[str, Any]) -> str:
    return _canonical_hash(_body(manifest))


def _inputs(root: Path | None) -> tuple[Path, dict[str, Path], dict[str, dict[str, Any]]]:
    repository = _root(root)
    paths = {key: repository / relative for key, relative in INPUT_FILES.items()}
    return repository, paths, {key: _load(path) for key, path in paths.items()}


def _pins(paths: Mapping[str, Path], names: tuple[str, ...]) -> dict[str, str]:
    return {name: _file_hash(paths[name]) for name in names}


def _tasks(values: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    plan = values["benchmark_plan"]
    closure = values["closure"]
    blockers = values["blocker_map"]
    plan_rows = plan.get("slice_30", {}).get("tasks")
    closure_rows = closure.get("tasks")
    blocker_rows = blockers.get("tasks")
    if not all(
        isinstance(rows, list) and len(rows) == EXPECTED_TASKS
        for rows in (plan_rows, closure_rows, blocker_rows)
    ):
        raise W1SealError("plan, closure, and blocker task rosters must each be exactly 30")
    indexed: list[dict[str, dict[str, Any]]] = []
    for label, rows in (("plan", plan_rows), ("closure", closure_rows), ("blocker", blocker_rows)):
        index = {row.get("task_id"): row for row in rows if isinstance(row, Mapping)}
        if len(index) != EXPECTED_TASKS or None in index:
            raise W1SealError(f"{label} task IDs are missing or duplicated")
        indexed.append(index)
    plan_index, closure_index, blocker_index = indexed
    if set(plan_index) != set(closure_index) or set(plan_index) != set(blocker_index):
        raise W1SealError("task rosters are not cross-bound")
    rows: list[dict[str, Any]] = []
    for task_id in sorted(plan_index):
        plan_row, closure_row, blocker_row = (
            plan_index[task_id],
            closure_index[task_id],
            blocker_index[task_id],
        )
        for field in ("family", "mode", "source_path", "source_blob_oid"):
            if plan_row.get(field) != closure_row.get(field) or plan_row.get(
                field
            ) != blocker_row.get(field):
                raise W1SealError(f"cross-bound {field} drift for {task_id}")
        oracles = plan_row.get("intended_oracles")
        if not isinstance(oracles, list) or not oracles or len(oracles) != len(set(oracles)):
            raise W1SealError(f"oracle roster invalid for {task_id}")
        if blocker_row.get("oracle_refs") != oracles:
            raise W1SealError(f"blocker oracle roster drift for {task_id}")
        rows.append(
            {
                "task_id": task_id,
                "family": plan_row["family"],
                "mode": plan_row["mode"],
                "source_path": plan_row["source_path"],
                "source_blob_oid": plan_row["source_blob_oid"],
                "intended_oracles": list(oracles),
                "leakage_group_id": closure_row.get("leakage_group_id"),
                "closure_status": closure_row.get("closure_status"),
            }
        )
    counts = {family: sum(row["family"] == family for row in rows) for family in FAMILY_ORDER}
    if counts != {family: 5 for family in FAMILY_ORDER}:
        raise W1SealError("family allocation must be exactly five per family")
    return rows


def _require_counts(label: str, counts: object, expected: Mapping[str, int]) -> None:
    if not isinstance(counts, Mapping) or dict(counts) != dict(expected):
        raise W1SealError(f"{label} count denominator drift")


def _closure_inputs(closure: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    shared = closure.get("shared_closures")
    if not isinstance(shared, list) or len(shared) != 1 or not isinstance(shared[0], Mapping):
        raise W1SealError("closure must contain exactly one shared closure")
    inputs = shared[0].get("inputs")
    if not isinstance(inputs, list) or not all(isinstance(row, Mapping) for row in inputs):
        raise W1SealError("closure inputs are missing")
    return inputs


def _nonzero_gap(*checks: bool) -> int:
    return 0 if all(checks) else 1


def _validate_core(
    values: Mapping[str, Mapping[str, Any]], root: Path | None
) -> list[dict[str, Any]]:
    plan = values["benchmark_plan"]
    closure = values["closure"]
    assets = values["assets"]
    blockers = values["blocker_map"]
    rights = values["rights_dossier"]
    accuracy = values["accuracy_target"]
    decision = values["decision_register"]
    blocker_errors = validate_blocker_map(blockers, _root(root))
    if blocker_errors:
        raise W1SealError("blocker map upstream validation: " + "; ".join(blocker_errors))
    rights_errors = validate_rights_dossier(rights, assets)
    if rights_errors:
        raise W1SealError("rights dossier upstream validation: " + "; ".join(rights_errors))
    if plan.get("source_revision") != closure.get("source_revision"):
        raise W1SealError("benchmark plan and closure source revision drift")
    if closure.get("distinct_leakage_groups") != EXPECTED_GROUPS:
        raise W1SealError("current closure must contain exactly one leakage group")
    closure_tasks = closure.get("tasks")
    closure_inputs = _closure_inputs(closure)
    if not isinstance(closure_tasks, list) or not all(
        isinstance(row, Mapping) for row in closure_tasks
    ):
        raise W1SealError("closure tasks are missing")
    closure_task_ids = [row.get("task_id") for row in closure_tasks]
    closure_paths = [row.get("path") for row in closure_inputs]
    closure_oids = [row.get("blob_oid") for row in closure_inputs]
    closure_expected = {
        "tasks_in": EXPECTED_TASKS,
        "tasks_out": EXPECTED_TASKS,
        "task_ids_distinct": EXPECTED_TASKS,
        "sources_in": EXPECTED_ASSETS,
        "sources_out": EXPECTED_ASSETS,
        "source_paths_distinct": EXPECTED_ASSETS,
        "source_blob_oids_distinct": EXPECTED_ASSETS,
        "gaps": 0,
    }
    closure_actual = {
        "tasks_in": len(closure_tasks),
        "tasks_out": len(closure_tasks),
        "task_ids_distinct": len(set(closure_task_ids)),
        "sources_in": len(closure_inputs),
        "sources_out": len(closure_inputs),
        "source_paths_distinct": len(set(closure_paths)),
        "source_blob_oids_distinct": len(set(closure_oids)),
        "gaps": _nonzero_gap(
            len(closure_tasks) == EXPECTED_TASKS,
            len(set(closure_task_ids)) == EXPECTED_TASKS,
            len(closure_inputs) == EXPECTED_ASSETS,
            len(set(closure_paths)) == EXPECTED_ASSETS,
            len(set(closure_oids)) == EXPECTED_ASSETS,
        ),
    }
    _require_counts("closure declared", closure.get("counts"), closure_expected)
    _require_counts("closure recomputed", closure_actual, closure_expected)

    asset_rows = assets.get("assets")
    if not isinstance(asset_rows, list) or not all(isinstance(row, Mapping) for row in asset_rows):
        raise W1SealError("asset register assets are missing")
    asset_paths = [row.get("path") for row in asset_rows]
    asset_oids = [row.get("blob_oid") for row in asset_rows]
    asset_expected = {
        "assets_in": EXPECTED_ASSETS,
        "assets_out": EXPECTED_ASSETS,
        "asset_paths_distinct": EXPECTED_ASSETS,
        "asset_blob_oids_distinct": EXPECTED_ASSETS,
        "gaps": 0,
    }
    asset_actual = {
        "assets_in": len(asset_rows),
        "assets_out": len(asset_rows),
        "asset_paths_distinct": len(set(asset_paths)),
        "asset_blob_oids_distinct": len(set(asset_oids)),
        "gaps": _nonzero_gap(
            len(asset_rows) == EXPECTED_ASSETS,
            len(set(asset_paths)) == EXPECTED_ASSETS,
            len(set(asset_oids)) == EXPECTED_ASSETS,
        ),
    }
    _require_counts("asset declared", assets.get("counts"), asset_expected)
    _require_counts("asset recomputed", asset_actual, asset_expected)

    blocker_rows = blockers.get("tasks")
    if not isinstance(blocker_rows, list) or not all(
        isinstance(row, Mapping) for row in blocker_rows
    ):
        raise W1SealError("blocker map tasks are missing")
    blocker_ids = [row.get("task_id") for row in blocker_rows]
    blocker_groups = [row.get("leakage_group_id") for row in blocker_rows]
    blocker_expected = {
        "tasks_in": EXPECTED_TASKS,
        "tasks_out": EXPECTED_TASKS,
        "task_ids_distinct": EXPECTED_TASKS,
        "assets_in": EXPECTED_ASSETS,
        "assets_out": EXPECTED_ASSETS,
        "leakage_groups": EXPECTED_GROUPS,
        "gaps": 0,
    }
    blocker_actual = {
        "tasks_in": len(blocker_rows),
        "tasks_out": len(blocker_rows),
        "task_ids_distinct": len(set(blocker_ids)),
        "assets_in": len(asset_rows),
        "assets_out": len(asset_rows),
        "leakage_groups": len(set(blocker_groups)),
        "gaps": _nonzero_gap(
            len(blocker_rows) == EXPECTED_TASKS,
            len(set(blocker_ids)) == EXPECTED_TASKS,
            len(asset_rows) == EXPECTED_ASSETS,
            len(set(blocker_groups)) == EXPECTED_GROUPS,
        ),
    }
    declared_blocker_counts = blockers.get("counts")
    if not isinstance(declared_blocker_counts, Mapping):
        raise W1SealError("blocker map counts are missing")
    _require_counts(
        "blocker declared",
        {key: declared_blocker_counts.get(key) for key in blocker_expected},
        blocker_expected,
    )
    _require_counts("blocker recomputed", blocker_actual, blocker_expected)

    rights_rows = rights.get("assets")
    if not isinstance(rights_rows, list) or not all(
        isinstance(row, Mapping) for row in rights_rows
    ):
        raise W1SealError("rights dossier assets are missing")
    rights_paths = [row.get("path") for row in rights_rows]
    rights_oids = [row.get("blob_oid") for row in rights_rows]
    rights_expected = asset_expected
    rights_actual = {
        "assets_in": len(rights_rows),
        "assets_out": len(rights_rows),
        "asset_paths_distinct": len(set(rights_paths)),
        "asset_blob_oids_distinct": len(set(rights_oids)),
        "gaps": _nonzero_gap(
            len(rights_rows) == EXPECTED_ASSETS,
            len(set(rights_paths)) == EXPECTED_ASSETS,
            len(set(rights_oids)) == EXPECTED_ASSETS,
        ),
    }
    _require_counts("rights declared", rights.get("counts"), rights_expected)
    _require_counts("rights recomputed", rights_actual, rights_expected)
    rights_summary = rights.get("summary")
    _require_counts(
        "rights summary",
        rights_summary,
        {"reviewed": 0, "approved": 0, "excluded": 0, "pending": EXPECTED_ASSETS},
    )

    if (
        accuracy.get("status") != "proposed"
        or accuracy.get("family_counts") != FAMILY_TARGETS
        or accuracy.get("total") != 600
        or accuracy.get("minimum_distinct_leakage_groups") != MINIMUM_GROUPS
        or accuracy.get("decision_ref") != "O-003"
    ):
        raise W1SealError("accuracy target family counts or status drift")
    decisions = decision.get("open_decisions")
    o003 = (
        next(
            (item for item in decisions if isinstance(item, Mapping) and item.get("id") == "O-003"),
            None,
        )
        if isinstance(decisions, list)
        else None
    )
    if not isinstance(o003, Mapping) or o003.get("status") != "open":
        raise W1SealError("O-003 must remain open")
    return _tasks(values)


def _counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {family: sum(row["family"] == family for row in rows) for family in FAMILY_ORDER}


def build_oracle_receipts(root: Path | None = None) -> dict[str, Any]:
    """Build the exact 30-task/160-cell non-execution roster."""

    _, paths, values = _inputs(root)
    tasks = _validate_core(values, root)
    rows = []
    for task in tasks:
        cells = [
            {
                "predicate": predicate,
                "status": "not_run",
                "authority": None,
                "receipt_ref": None,
                "receipt_sha256": None,
            }
            for predicate in task["intended_oracles"]
        ]
        rows.append({**task, "oracle_cells": cells})
    all_cells = [cell for row in rows for cell in row["oracle_cells"]]
    f4_f6 = [
        cell
        for row in rows
        if row["family"] in {"F-4", "F-5", "F-6"}
        for cell in row["oracle_cells"]
    ]
    if len(all_cells) != EXPECTED_CELLS or len(f4_f6) != EXPECTED_F4_F6_CELLS:
        raise W1SealError("oracle-cell denominator drift")
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "manifest_id": "w1/slice-30-oracle-receipts-v1",
        "status": "unexecuted_evidence_only",
        "source_revision": values["closure"]["source_revision"],
        "input_pins": _pins(paths, ("benchmark_plan", "closure", "blocker_map")),
        "counts": {
            "tasks_in": 30,
            "tasks_out": 30,
            "task_ids_distinct": 30,
            "oracle_cells_intended": 160,
            "oracle_cells_executed": 0,
            "f4_f6_cells_intended": 75,
            "f4_f6_cells_executed": 0,
            "gaps": 160,
        },
        "future_protected_role_receipt_target": {
            "status": "planning_target_not_evidence",
            "target": 25,
            "executed": 0,
            "by_family": {
                "F-4": {"roles": ["observed", "proposed"], "target": 10},
                "F-5": {"roles": ["legacy", "canonical"], "target": 10},
                "F-6": {"roles": ["explained_source"], "target": 5},
            },
        },
        "tasks": rows,
    }
    manifest["manifest_hash"] = manifest_hash(manifest)
    return manifest


def build_leakage_assignment(root: Path | None = None) -> dict[str, Any]:
    """Build the one-group assignment without inventing AST/IR signatures."""

    _, paths, values = _inputs(root)
    tasks = _validate_core(values, root)
    group_ids = {row["leakage_group_id"] for row in tasks}
    if len(group_ids) != 1 or not all(
        isinstance(item, str) and item.startswith("sha256:") for item in group_ids
    ):
        raise W1SealError("task leakage groups are missing or inflated")
    group_id = next(iter(group_ids))
    rows = [
        {
            "task_id": task["task_id"],
            "family": task["family"],
            "source_path": task["source_path"],
            "source_blob_oid": task["source_blob_oid"],
            "leakage_group_id": group_id,
            "normalized_ast_signature": None,
            "normalized_ir_signature": None,
            "dependency_closure": "whole-tenant",
            "symbol_set": None,
            "property_family": None,
            "provenance_parent": None,
            "language_epoch": values["benchmark_plan"]["language_version"],
        }
        for task in tasks
    ]
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "manifest_id": "w1/leakage-group-assignment-v1",
        "status": "correlated_single_group_evidence_only",
        "source_revision": values["closure"]["source_revision"],
        "input_pins": _pins(paths, ("benchmark_plan", "closure", "blocker_map")),
        "counts": {
            "tasks_in": 30,
            "tasks_out": 30,
            "task_ids_distinct": 30,
            "leakage_groups_distinct": 1,
            "population_claim_groups_available": 1,
            "minimum_population_for_claim": 563,
            "gaps": 0,
        },
        "population_claim_eligible": False,
        "group_reason": "whole_tenant_dependency_closure",
        "assignments": rows,
    }
    manifest["manifest_hash"] = manifest_hash(manifest)
    return manifest


def build_held_out_map(root: Path | None = None) -> dict[str, Any]:
    """Bind the six allocated families to their ratified future denominators."""

    _, paths, values = _inputs(root)
    tasks = _validate_core(values, root)
    families = values["benchmark_plan"].get("families")
    if not isinstance(families, list) or len(families) != len(FAMILY_ORDER):
        raise W1SealError("benchmark family roster must be exactly six")
    family_index = {row.get("id"): row for row in families if isinstance(row, Mapping)}
    if set(family_index) != set(FAMILY_ORDER):
        raise W1SealError("benchmark family IDs drift")
    rows = []
    for family in FAMILY_ORDER:
        plan_family = family_index[family]
        allocated = [row["task_id"] for row in tasks if row["family"] == family]
        if len(allocated) != 5 or plan_family.get("allocated_tasks") != 5:
            raise W1SealError(f"allocated task count drift for {family}")
        rows.append(
            {
                "family": family,
                "criticality": plan_family.get("criticality"),
                "held_out_rule": plan_family.get("held_out_rule"),
                "allocated_task_ids": allocated,
                "allocated_task_count": 5,
                "target_frozen_task_count": FAMILY_TARGETS[family],
                "status": "allocation_only_not_sealed",
            }
        )
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "manifest_id": "w1/held-out-family-map-v1",
        "status": "allocation_only_not_sealed",
        "source_revision": values["benchmark_plan"]["source_revision"],
        "input_pins": _pins(paths, ("benchmark_plan", "accuracy_target", "blocker_map")),
        "counts": {
            "families_in": 6,
            "families_out": 6,
            "families_distinct": 6,
            "allocated_tasks": 30,
            "target_frozen_tasks": 600,
            "gaps": 0,
        },
        "families": rows,
    }
    manifest["manifest_hash"] = manifest_hash(manifest)
    return manifest


def _reference(identity: str, value: Mapping[str, Any], path: Path) -> dict[str, str]:
    return {
        "identity": identity,
        "file_sha256": _file_hash(path),
        "canonical_sha256": _canonical_hash(value),
    }


def build_benchmark_seal(root: Path | None = None) -> dict[str, Any]:
    """Build a permanently unsealed W1 package reference and blocker ledger."""

    repository, paths, values = _inputs(root)
    _validate_core(values, root)
    oracle_path = repository / "manifests/w1-slice-30-oracle-receipts-v1.json"
    leakage_path = repository / "manifests/w1-leakage-group-assignment-v1.json"
    held_out_path = repository / "manifests/w1-held-out-family-map-v1.json"
    generated_paths = {
        "oracle_receipts": oracle_path,
        "leakage_assignment": leakage_path,
        "held_out_map": held_out_path,
    }
    generated_values = {key: _load(path) for key, path in generated_paths.items()}
    expected_generated = {
        "oracle_receipts": build_oracle_receipts(root),
        "leakage_assignment": build_leakage_assignment(root),
        "held_out_map": build_held_out_map(root),
    }
    for key, expected in expected_generated.items():
        if generated_values[key] != expected:
            raise W1SealError(f"{key} tracked bytes do not match deterministic builder")
    references = {
        "closure": _reference(
            str(values["closure"].get("manifest_id")), values["closure"], paths["closure"]
        ),
        "assets": _reference(
            str(values["assets"].get("manifest_id")), values["assets"], paths["assets"]
        ),
        "blocker_map": _reference(
            str(values["blocker_map"].get("manifest_id")),
            values["blocker_map"],
            paths["blocker_map"],
        ),
        "rights_dossier": _reference(
            str(values["rights_dossier"].get("manifest_id")),
            values["rights_dossier"],
            paths["rights_dossier"],
        ),
        "oracle_receipts": _reference(
            str(generated_values["oracle_receipts"].get("manifest_id")),
            generated_values["oracle_receipts"],
            oracle_path,
        ),
        "leakage_assignment": _reference(
            str(generated_values["leakage_assignment"].get("manifest_id")),
            generated_values["leakage_assignment"],
            leakage_path,
        ),
        "held_out_map": _reference(
            str(generated_values["held_out_map"].get("manifest_id")),
            generated_values["held_out_map"],
            held_out_path,
        ),
        "accuracy_target": _reference(
            str(values["accuracy_target"].get("target_id")),
            values["accuracy_target"],
            paths["accuracy_target"],
        ),
    }
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "manifest_id": "w1/benchmark-seal-v1",
        "status": "unsealed_evidence_only",
        "source_revision": values["closure"]["source_revision"],
        "input_pins": _pins(paths, tuple(INPUT_FILES)),
        "references": references,
        "counts": {
            "tasks": 30,
            "assets": 201,
            "oracle_cells": 160,
            "leakage_groups": 1,
            "minimum_leakage_groups": 563,
        },
        "blockers": {
            "legal_review": {"reviewed": 0, "required": 201},
            "task_specific_oracles": {"executed": 0, "required": 30},
            "oracle_cells": {"executed": 0, "required": 160},
            "leakage_groups": {"current": 1, "minimum": 563},
            "phase_b": "absent",
            "f4_f6_typed_oracles": "absent",
            "o003": "open",
            "ab_baseline": "absent",
        },
        "seal_eligible": False,
    }
    manifest["manifest_hash"] = manifest_hash(manifest)
    return manifest


def _validate(manifest: Mapping[str, Any], expected: Mapping[str, Any], label: str) -> list[str]:
    errors: list[str] = []
    if manifest_hash(manifest) != manifest.get("manifest_hash"):
        errors.append("manifest_hash does not match canonical body")
    for field, value in expected.items():
        if field != "manifest_hash" and manifest.get(field) != value:
            errors.append(f"{label} field drift: {field}")
    return errors


def validate_oracle_receipts(manifest: Mapping[str, Any], root: Path | None = None) -> list[str]:
    try:
        errors = _validate(manifest, build_oracle_receipts(root), "oracle receipts")
    except W1SealError as error:
        return [str(error)]
    tasks = manifest.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != EXPECTED_TASKS:
        errors.append("oracle receipt task denominator is not 30")
    else:
        cells = [
            cell
            for row in tasks
            if isinstance(row, Mapping)
            for cell in row.get("oracle_cells", [])
        ]
        if len(cells) != EXPECTED_CELLS:
            errors.append("oracle cell denominator is not 160")
        if any(not isinstance(cell, Mapping) or cell.get("status") != "not_run" for cell in cells):
            errors.append("oracle execution status was laundered")
        if any(
            isinstance(cell, Mapping)
            and any(
                cell.get(key) is not None for key in ("authority", "receipt_ref", "receipt_sha256")
            )
            for cell in cells
        ):
            errors.append("oracle receipt authority was laundered")
    return sorted(set(errors))


def validate_leakage_assignment(manifest: Mapping[str, Any], root: Path | None = None) -> list[str]:
    try:
        errors = _validate(manifest, build_leakage_assignment(root), "leakage assignment")
    except W1SealError as error:
        return [str(error)]
    rows = manifest.get("assignments")
    if not isinstance(rows, list) or len(rows) != EXPECTED_TASKS:
        errors.append("leakage assignment task denominator is not 30")
    elif len({row.get("leakage_group_id") for row in rows if isinstance(row, Mapping)}) != 1:
        errors.append("leakage group count was inflated")
    if manifest.get("population_claim_eligible") is not False:
        errors.append("population claim eligibility was laundered")
    return sorted(set(errors))


def validate_held_out_map(manifest: Mapping[str, Any], root: Path | None = None) -> list[str]:
    try:
        errors = _validate(manifest, build_held_out_map(root), "held-out map")
    except W1SealError as error:
        return [str(error)]
    if manifest.get("status") != "allocation_only_not_sealed":
        errors.append("held-out map status was laundered")
    return sorted(set(errors))


def validate_benchmark_seal(manifest: Mapping[str, Any], root: Path | None = None) -> list[str]:
    try:
        errors = _validate(manifest, build_benchmark_seal(root), "benchmark seal")
    except W1SealError as error:
        return [str(error)]
    if (
        manifest.get("status") != "unsealed_evidence_only"
        or manifest.get("seal_eligible") is not False
    ):
        errors.append("benchmark seal status was laundered")
    return sorted(set(errors))


__all__ = [
    "W1SealError",
    "build_benchmark_seal",
    "build_held_out_map",
    "build_leakage_assignment",
    "build_oracle_receipts",
    "manifest_hash",
    "validate_benchmark_seal",
    "validate_held_out_map",
    "validate_leakage_assignment",
    "validate_oracle_receipts",
]
