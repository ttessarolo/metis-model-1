"""Read-only build-input closure for the pinned Metis tenant.

The Metis compiler is a whole-program compiler: a task does not get a smaller
source snapshot merely because its local symbols are few.  This module keeps
that fact explicit and computes the exact Git-object inventory without reading
the checkout contents or running the Metis toolchain.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

PINNED_REVISION = "a2dde2b191f6b78c2003d74875560da782470968"
TENANT_PREFIX = "examples/play-prod-v2"
ROOT_METADATA = (
    "metis.toml",
    "legacy-wire.json",
    "names.map.json",
    "materialized-fallbacks.source.json",
)
EXPECTED_METIS_FILES = 197
EXPECTED_BUILD_INPUTS = 201


@dataclass(frozen=True)
class BuildInput:
    path: str
    blob_oid: str


class ClosureError(ValueError):
    """Raised when a closure inventory is incomplete or internally inconsistent."""


def shared_leakage_group_id(
    inventory: tuple[BuildInput, ...],
    revision: str = PINNED_REVISION,
) -> str:
    """Return the single content-derived leakage group for the shared closure."""

    payload = {
        "source_revision": revision,
        "closure_policy": "whole_program_build_input",
        "inputs": [entry.__dict__ for entry in inventory],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def inventory_from_ls_tree(lines: Iterable[str]) -> tuple[BuildInput, ...]:
    """Parse ``git ls-tree --format='%(objectname) %(path)'`` output.

    This pure parser is intentionally used by tests with a synthetic inventory;
    it never opens a source file and rejects duplicate paths or object IDs.
    """

    entries: list[BuildInput] = []
    for raw in lines:
        line = raw.rstrip("\n")
        if not line:
            continue
        try:
            oid, path = line.split("\t", 1)
        except ValueError as exc:
            raise ClosureError(f"invalid ls-tree row: {line!r}") from exc
        if len(oid) != 40 or any(char not in "0123456789abcdef" for char in oid):
            raise ClosureError(f"invalid blob oid for {path!r}: {oid!r}")
        entries.append(BuildInput(path=path, blob_oid=oid))
    paths = [entry.path for entry in entries]
    oids = [entry.blob_oid for entry in entries]
    if len(paths) != len(set(paths)):
        raise ClosureError("inventory contains duplicate paths")
    if len(oids) != len(set(oids)):
        raise ClosureError("inventory contains duplicate blob oids")
    return tuple(sorted(entries, key=lambda entry: entry.path))


def compute_build_input_inventory(
    repo: Path,
    revision: str = PINNED_REVISION,
    tenant_prefix: str = TENANT_PREFIX,
) -> tuple[BuildInput, ...]:
    """Compute the build-input inventory from Git objects only.

    The recursive `.metis` set models ``loadTenantDocs``.  Root metadata models
    ``relevantTenantInputs`` and is included only when present in the pinned
    tree.  No working-tree path is opened.
    """

    tree = _git(
        repo,
        "ls-tree",
        "-r",
        "--full-tree",
        "--format=%(objectname)\t%(path)",
        revision,
        "--",
        tenant_prefix,
    )
    all_entries = inventory_from_ls_tree(tree.splitlines())
    selected = [
        entry
        for entry in all_entries
        if entry.path.endswith(".metis")
        or entry.path in {f"{tenant_prefix}/{name}" for name in ROOT_METADATA}
    ]
    selected = tuple(sorted(selected, key=lambda entry: entry.path))
    metis_count = sum(entry.path.endswith(".metis") for entry in selected)
    if metis_count != EXPECTED_METIS_FILES:
        raise ClosureError(
            f"expected {EXPECTED_METIS_FILES} tenant .metis files, found {metis_count}"
        )
    return selected


def _task_unresolved(task: dict[str, object], source_text: str) -> list[str]:
    family = str(task["family"])
    unresolved = [
        "data_rights_not_reviewed",
        "task_specific_oracles_not_executed",
    ]
    if family in {"F-1", "F-2", "F-3"}:
        unresolved.append("semantic_oracle_not_executed")
    if family == "F-3":
        unresolved.append("mutation_parent_unresolved")
    if family == "F-4":
        unresolved.append("golden_ir_wire_ancestor_unresolved")
    if family == "F-5":
        unresolved.append("migration_pair_and_language_epoch_unresolved")
    if family == "F-6":
        unresolved.append("normalized_ast_ir_and_human_oracle_unresolved")
    if "time." in source_text or "needs time" in source_text:
        unresolved.append("ambient_time_runtime")
    if "materialized." in source_text:
        unresolved.append("materialized_fallback_sidecar")
    if "service." in source_text or "transformer." in source_text:
        unresolved.append("external_service_or_transformer_runtime")
    return sorted(set(unresolved))


def build_manifest(
    repo: Path,
    plan_path: Path,
    revision: str = PINNED_REVISION,
) -> dict[str, object]:
    """Build the tracked closure manifest from the benchmark allocation."""

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    tasks = plan["slice_30"]["tasks"]
    if len(tasks) != 30 or len({task["task_id"] for task in tasks}) != 30:
        raise ClosureError("benchmark plan must contain 30 distinct tasks")
    inventory = compute_build_input_inventory(repo, revision)
    if len(inventory) != EXPECTED_BUILD_INPUTS:
        raise ClosureError(f"expected {EXPECTED_BUILD_INPUTS} build inputs, found {len(inventory)}")
    by_path = {entry.path: entry.blob_oid for entry in inventory}
    leakage_group_id = shared_leakage_group_id(inventory, revision)
    task_records = []
    for task in tasks:
        source_path = str(task["source_path"])
        source_oid = _git(repo, "rev-parse", f"{revision}:{source_path}").strip()
        declared_oid = str(task.get("source_blob_oid", ""))
        if declared_oid != source_oid:
            raise ClosureError(
                f"benchmark plan source_blob_oid mismatch for {source_path}: "
                f"declared {declared_oid}, Git {source_oid}"
            )
        if source_path not in by_path or by_path[source_path] != source_oid:
            raise ClosureError(f"task source is absent or mismatched in closure: {source_path}")
        source_text = _git(repo, "show", f"{revision}:{source_path}")
        task_records.append(
            {
                "task_id": task["task_id"],
                "family": task["family"],
                "mode": task["mode"],
                "source_path": source_path,
                "source_blob_oid": source_oid,
                "closure_ref": "whole-tenant",
                "closure_status": "computed_not_sealed",
                "leakage_group_id": leakage_group_id,
                "task_asset_identity": (
                    f"non-split|source_asset_id={source_oid}|family={task['family']}"
                ),
                "unresolved_dependencies": _task_unresolved(task, source_text),
            }
        )
    return {
        "schema_version": 1,
        "manifest_id": "benchmark/families-v1/slice-30-closure",
        "status": "computed_not_sealed",
        "source_revision": revision,
        "language_version": "0.43",
        "tenant_prefix": TENANT_PREFIX,
        "closure_policy": "whole_program_build_input",
        "leakage_group_id": leakage_group_id,
        "distinct_leakage_groups": 1,
        "independence_status": "correlated_single_whole_tenant_group",
        "counts": {
            "tasks_in": 30,
            "tasks_out": len(task_records),
            "task_ids_distinct": len({task["task_id"] for task in task_records}),
            "sources_in": EXPECTED_BUILD_INPUTS,
            "sources_out": len(inventory),
            "source_paths_distinct": len({entry.path for entry in inventory}),
            "source_blob_oids_distinct": len({entry.blob_oid for entry in inventory}),
            "gaps": 0,
        },
        "shared_closures": [
            {
                "closure_id": "whole-tenant",
                "status": "computed_not_sealed",
                "leakage_group_id": leakage_group_id,
                "reason": "Metis build loads and compiles the complete tenant whole-program",
                "inputs": [entry.__dict__ for entry in inventory],
                "unresolved_runtime_dependencies": [
                    "external_catalog_datastore_values",
                    "external_services_and_transformer_sources",
                    "materialized_fallback_sidecar_semantics",
                ],
            }
        ],
        "tasks": task_records,
    }


def validate_manifest(manifest: dict[str, object]) -> None:
    """Validate closure denominators and shared-reference invariants."""

    counts = manifest.get("counts")
    tasks = manifest.get("tasks")
    closures = manifest.get("shared_closures")
    leakage_group_id = manifest.get("leakage_group_id")
    if (
        not isinstance(counts, dict)
        or not isinstance(tasks, list)
        or not isinstance(closures, list)
        or not isinstance(leakage_group_id, str)
    ):
        raise ClosureError("manifest has invalid top-level closure sections")
    if counts.get("tasks_in") != 30 or counts.get("tasks_out") != 30:
        raise ClosureError("task denominator is not 30/30")
    if counts.get("task_ids_distinct") != 30:
        raise ClosureError("task IDs are not distinct")
    if (
        counts.get("sources_in") != EXPECTED_BUILD_INPUTS
        or counts.get("sources_out") != EXPECTED_BUILD_INPUTS
    ):
        raise ClosureError("source denominator is not 201/201")
    if counts.get("source_paths_distinct") != EXPECTED_BUILD_INPUTS:
        raise ClosureError("source paths are not distinct")
    if counts.get("source_blob_oids_distinct") != EXPECTED_BUILD_INPUTS:
        raise ClosureError("source blob OIDs are not distinct")
    if counts.get("gaps") != 0 or len(closures) != 1:
        raise ClosureError("closure inventory is incomplete")
    if manifest.get("distinct_leakage_groups") != 1:
        raise ClosureError("whole-tenant closure must have exactly one leakage group")
    if manifest.get("independence_status") != "correlated_single_whole_tenant_group":
        raise ClosureError("independence status must be correlated single whole-tenant group")
    if closures[0].get("leakage_group_id") != leakage_group_id:
        raise ClosureError("shared closure leakage-group drift")
    inputs = closures[0].get("inputs")
    if not isinstance(inputs, list) or len(inputs) != EXPECTED_BUILD_INPUTS:
        raise ClosureError("closure input inventory is not 201 entries")
    revision = manifest.get("source_revision")
    if revision != PINNED_REVISION:
        raise ClosureError("closure source revision is not the pinned Metis revision")
    inventory_rows: list[str] = []
    for entry in inputs:
        if not isinstance(entry, dict):
            raise ClosureError("closure inventory entry is not an object")
        path = entry.get("path")
        oid = entry.get("blob_oid")
        if not isinstance(path, str) or not isinstance(oid, str):
            raise ClosureError("closure inventory path or blob oid is not a string")
        inventory_rows.append(f"{oid}\t{path}")
    inventory = inventory_from_ls_tree(inventory_rows)
    expected_group = shared_leakage_group_id(inventory, revision)
    if leakage_group_id != expected_group:
        raise ClosureError("closure leakage-group identity is not content-derived")
    paths = [entry.get("path") for entry in inputs]
    oids = [entry.get("blob_oid") for entry in inputs]
    if len(paths) != len(set(paths)):
        raise ClosureError("closure inventory contains duplicate paths")
    if len(oids) != len(set(oids)):
        raise ClosureError("closure inventory contains duplicate blob oids")
    by_path = dict(zip(paths, oids, strict=True))
    task_ids = [task.get("task_id") for task in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise ClosureError("task IDs are not distinct")
    for task in tasks:
        if by_path.get(task.get("source_path")) != task.get("source_blob_oid"):
            raise ClosureError(f"task source is absent or mismatched: {task.get('source_path')}")
        if task.get("leakage_group_id") != leakage_group_id:
            raise ClosureError("task leakage-group drift")
    if any(task.get("closure_ref") != "whole-tenant" for task in tasks):
        raise ClosureError("not every task references the shared whole-tenant closure")
    if any(task.get("closure_status") != "computed_not_sealed" for task in tasks):
        raise ClosureError("unresolved closure was incorrectly sealed")
