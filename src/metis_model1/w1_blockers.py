"""Deterministic, evidence-only blocker map for the allocated W1 slice.

The map joins the ratified task plan to the computed dependency closure and
local-only asset register.  It never reads Metis payloads and cannot seal a
task: every row remains blocked until its task-specific evidence is supplied.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from metis_model1.provenance import canonical_json_hash, normalize_json

EXPECTED_TASKS = 30
EXPECTED_ASSETS = 201
EXPECTED_LEAKAGE_GROUPS = 1
DEPENDENCY_COUNTS = {
    "direct_runtime": 17,
    "ambient": 10,
    "external": 11,
    "sidecar": 3,
    "f3_mutation": 5,
    "f4_golden": 5,
    "f5_migration": 5,
    "f6_human": 5,
    "semantic": 15,
    "task_oracle": 30,
}
RAW_DEPENDENCY_COUNTS = {
    "ambient_time_runtime": 10,
    "data_rights_not_reviewed": 30,
    "external_service_or_transformer_runtime": 11,
    "materialized_fallback_sidecar": 3,
    "mutation_parent_unresolved": 5,
    "semantic_oracle_not_executed": 15,
    "task_specific_oracles_not_executed": 30,
    "golden_ir_wire_ancestor_unresolved": 5,
    "migration_pair_and_language_epoch_unresolved": 5,
    "normalized_ast_ir_and_human_oracle_unresolved": 5,
}
INPUT_FILES = {
    "benchmark_plan": "manifests/benchmark-plan.json",
    "closure": "manifests/slice-30-closure.json",
    "assets": "manifests/slice-30-assets.json",
}


class BlockerMapError(ValueError):
    """Raised when the blocker map cannot be proven deterministic."""


def _root(root: Path | None) -> Path:
    return Path(__file__).resolve().parents[2] if root is None else Path(root)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise BlockerMapError(f"{path.name} must contain an object")
    return value


def _file_pin(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _body(manifest: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in manifest.items() if key != "manifest_hash"}


def manifest_hash(manifest: Mapping[str, Any]) -> str:
    return "sha256:" + canonical_json_hash(normalize_json(_body(manifest)))


def _tags(unresolved: list[str]) -> list[str]:
    """Classify only dependencies explicitly present on the closure row."""

    tags: set[str] = set()
    mapping = {
        "ambient_time_runtime": "ambient",
        "external_service_or_transformer_runtime": "external",
        "materialized_fallback_sidecar": "sidecar",
        "mutation_parent_unresolved": "f3_mutation",
        "golden_ir_wire_ancestor_unresolved": "f4_golden",
        "migration_pair_and_language_epoch_unresolved": "f5_migration",
        "normalized_ast_ir_and_human_oracle_unresolved": "f6_human",
        "semantic_oracle_not_executed": "semantic",
        "task_specific_oracles_not_executed": "task_oracle",
    }
    tags.update(mapping[dependency] for dependency in unresolved if dependency in mapping)
    if {"ambient", "external", "sidecar"} & tags:
        tags.add("direct_runtime")
    return sorted(tags)


def build_blocker_map(root: Path | None = None) -> dict[str, Any]:
    """Build the evidence-only map from the three pinned JSON inputs."""

    repository = _root(root)
    paths = {key: repository / relative for key, relative in INPUT_FILES.items()}
    plan = _load(paths["benchmark_plan"])
    closure = _load(paths["closure"])
    assets = _load(paths["assets"])
    tasks = plan.get("slice_30", {}).get("tasks")
    closure_tasks = closure.get("tasks")
    if not isinstance(tasks, list) or len(tasks) != EXPECTED_TASKS:
        raise BlockerMapError("benchmark plan tasks are not exactly 30")
    if not isinstance(closure_tasks, list) or len(closure_tasks) != EXPECTED_TASKS:
        raise BlockerMapError("closure tasks are not exactly 30")
    closure_ids = [row.get("task_id") for row in closure_tasks if isinstance(row, Mapping)]
    if len(closure_ids) != EXPECTED_TASKS or len(set(closure_ids)) != EXPECTED_TASKS:
        raise BlockerMapError("closure task IDs are missing or duplicated")
    if closure.get("distinct_leakage_groups") != EXPECTED_LEAKAGE_GROUPS:
        raise BlockerMapError("closure leakage denominator drift")
    if plan.get("source_revision") != closure.get("source_revision"):
        raise BlockerMapError("plan/closure source revision drift")
    if plan.get("language_version") != closure.get("language_version"):
        raise BlockerMapError("plan/closure language version drift")
    if assets.get("source_revision") != closure.get("source_revision"):
        raise BlockerMapError("assets/closure source revision drift")
    if assets.get("language_version") != closure.get("language_version"):
        raise BlockerMapError("assets/closure language version drift")
    if assets.get("closure_manifest_id") != closure.get("manifest_id"):
        raise BlockerMapError("assets/closure manifest identity drift")
    closure_counts = closure.get("counts")
    if not isinstance(closure_counts, Mapping) or any(
        closure_counts.get(key) != expected
        for key, expected in {
            "tasks_in": EXPECTED_TASKS,
            "tasks_out": EXPECTED_TASKS,
            "task_ids_distinct": EXPECTED_TASKS,
            "sources_in": EXPECTED_ASSETS,
            "sources_out": EXPECTED_ASSETS,
            "source_paths_distinct": EXPECTED_ASSETS,
            "source_blob_oids_distinct": EXPECTED_ASSETS,
            "gaps": 0,
        }.items()
    ):
        raise BlockerMapError("closure denominator drift")
    asset_counts = assets.get("counts", {})
    if not isinstance(asset_counts, Mapping) or any(
        asset_counts.get(key) != expected
        for key, expected in {
            "assets_in": EXPECTED_ASSETS,
            "assets_out": EXPECTED_ASSETS,
            "asset_paths_distinct": EXPECTED_ASSETS,
            "asset_blob_oids_distinct": EXPECTED_ASSETS,
            "gaps": 0,
        }.items()
    ):
        raise BlockerMapError("asset denominator is not 201/201")
    closure_by_id = {row.get("task_id"): row for row in closure_tasks if isinstance(row, Mapping)}
    rows: list[dict[str, Any]] = []
    for index, task in enumerate(tasks):
        if not isinstance(task, Mapping):
            raise BlockerMapError(f"task {index} is not an object")
        task_id = task.get("task_id")
        closed = closure_by_id.get(task_id)
        if not isinstance(closed, Mapping):
            raise BlockerMapError(f"task {task_id!r} missing from closure")
        for field in ("family", "mode", "source_path", "source_blob_oid"):
            if task.get(field) != closed.get(field):
                raise BlockerMapError(f"task/closure {field} drift for {task_id}")
        unresolved = closed.get("unresolved_dependencies")
        if not isinstance(unresolved, list) or not all(
            isinstance(item, str) for item in unresolved
        ):
            raise BlockerMapError(f"unresolved dependencies missing for {task_id}")
        rows.append(
            {
                "task_id": task_id,
                "family": task.get("family"),
                "mode": task.get("mode"),
                "source_path": task.get("source_path"),
                "source_blob_oid": task.get("source_blob_oid"),
                "oracle_refs": list(task.get("intended_oracles", [])),
                "closure_ref": "whole-tenant",
                "closure_status": closed.get("closure_status"),
                "leakage_group_id": closed.get("leakage_group_id"),
                "dependency_tags": _tags(unresolved),
                "status": "blocked",
                "blockers": [
                    "dependency_closure_computed_not_sealed",
                    *unresolved,
                ],
                "evidence_refs": [],
            }
        )
    counts = {key: sum(key in row["dependency_tags"] for row in rows) for key in DEPENDENCY_COUNTS}
    raw_counts = {key: sum(key in row["blockers"] for row in rows) for key in RAW_DEPENDENCY_COUNTS}
    if counts != DEPENDENCY_COUNTS or raw_counts != RAW_DEPENDENCY_COUNTS:
        raise BlockerMapError(f"dependency tag counts drift: {counts}; raw: {raw_counts}")
    result: dict[str, Any] = {
        "schema_version": 1,
        "manifest_id": "benchmark/families-v1/slice-30-blocker-map-v1",
        "status": "computed_not_sealed_evidence_only",
        "source_revision": closure.get("source_revision"),
        "language_version": closure.get("language_version"),
        "closure_manifest_id": closure.get("manifest_id"),
        "input_pins": {key: _file_pin(paths[key]) for key in INPUT_FILES},
        "counts": {
            "tasks_in": EXPECTED_TASKS,
            "tasks_out": len(rows),
            "task_ids_distinct": len({row["task_id"] for row in rows}),
            "assets_in": EXPECTED_ASSETS,
            "assets_out": EXPECTED_ASSETS,
            "leakage_groups": EXPECTED_LEAKAGE_GROUPS,
            "gaps": 0,
            "dependency_tags": counts,
            "unresolved_dependencies": raw_counts,
        },
        "tasks": rows,
    }
    result["manifest_hash"] = manifest_hash(result)
    return result


def validate_blocker_map(manifest: Mapping[str, Any], root: Path | None = None) -> list[str]:
    """Return fail-closed identity, denominator, and anti-laundering errors."""

    errors: list[str] = []
    try:
        expected = build_blocker_map(root)
    except BlockerMapError as error:
        return [str(error)]
    if manifest_hash(manifest) != manifest.get("manifest_hash"):
        errors.append("manifest_hash does not match canonical body")
    for field in expected:
        if field != "manifest_hash" and manifest.get(field) != expected[field]:
            errors.append(f"field drift: {field}")
    rows = manifest.get("tasks")
    if not isinstance(rows, list) or len(rows) != EXPECTED_TASKS:
        errors.append("task denominator is not 30/30")
    else:
        ids = [row.get("task_id") for row in rows if isinstance(row, Mapping)]
        if len(ids) != len(set(ids)):
            errors.append("duplicate task IDs")
        if any(row.get("status") != "blocked" for row in rows if isinstance(row, Mapping)):
            errors.append("blocked status was laundered")
        if any(row.get("evidence_refs") != [] for row in rows if isinstance(row, Mapping)):
            errors.append("evidence_refs must remain empty")
        valid_rows = [row for row in rows if isinstance(row, Mapping)]
        observed = {
            key: sum(key in row.get("dependency_tags", []) for row in valid_rows)
            for key in DEPENDENCY_COUNTS
        }
        if observed != DEPENDENCY_COUNTS:
            errors.append("dependency tag counts drift")
        raw_observed = {
            key: sum(key in row.get("blockers", []) for row in valid_rows)
            for key in RAW_DEPENDENCY_COUNTS
        }
        if raw_observed != RAW_DEPENDENCY_COUNTS:
            errors.append("unresolved dependency counts drift")
    return sorted(set(errors))
