"""Offline structural helpers for the video grounding benchmark.

The builder handles task metadata and oracle references only.  It never invokes
an inference runtime and never stores model output.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from metis_model1.provenance import canonical_json_hash
from metis_model1.video_semantics_contracts import validate_task


class VideoBenchmarkContractError(ValueError):
    """Raised when a task roster cannot be frozen safely."""


FAMILIES = tuple(f"V-{index}" for index in range(1, 8))
SPLIT_FAMILY_COUNTS = {
    "dev": {"V-1": 14, "V-2": 14, "V-3": 10, "V-4": 10, "V-5": 8, "V-6": 6, "V-7": 2},
    "frozen": {"V-1": 6, "V-2": 6, "V-3": 6, "V-4": 6, "V-5": 4, "V-6": 2, "V-7": 2},
}
PROVENANCE_HASH_FIELDS = (
    "source_revision",
    "constraint_revision",
    "grammar_revision",
    "toolchain_revision",
)
PROVENANCE_ID_FIELDS = ("base_model_ref", "tokenizer_ref", "adapter_ref")


def benchmark_revision(tasks: Sequence[Mapping[str, Any]]) -> str:
    """Derive a stable revision from task metadata and oracle declarations."""

    return "sha256:" + canonical_json_hash(list(tasks))


def validate_task_roster(
    tasks: Sequence[Any], *, expected_total: int | None = None
) -> dict[str, Any]:
    """Validate a bounded task roster and return exact counts by family."""

    if not isinstance(tasks, Sequence) or isinstance(tasks, str | bytes | bytearray):
        raise VideoBenchmarkContractError("task roster must be a sequence")
    if expected_total is not None and len(tasks) != expected_total:
        raise VideoBenchmarkContractError("task roster has the wrong denominator")
    errors: list[str] = []
    task_ids: set[str] = set()
    leakage_groups: set[str] = set()
    family_counts: Counter[str] = Counter()
    for index, task in enumerate(tasks):
        task_errors = validate_task(task)
        errors.extend(f"task[{index}]: {error}" for error in task_errors)
        if isinstance(task, Mapping):
            task_id = task.get("task_id")
            group = task.get("leakage_group")
            if isinstance(task_id, str) and task_id in task_ids:
                errors.append(f"task[{index}]: duplicate task_id")
            if isinstance(task_id, str):
                task_ids.add(task_id)
            if isinstance(group, str):
                leakage_groups.add(group)
            family = task.get("family")
            if isinstance(family, str):
                family_counts[family] += 1
    if errors:
        raise VideoBenchmarkContractError("; ".join(errors))
    return {
        "in": len(tasks),
        "out": len(task_ids),
        "distinct": len(task_ids),
        "gaps": 0,
        "leakage_groups": len(leakage_groups),
        "families": dict(sorted(family_counts.items())),
        "benchmark_revision": benchmark_revision(tasks),
        "model_outputs_present": False,
    }


def _split_counts(tasks: Sequence[Mapping[str, Any]], split: str) -> dict[str, int]:
    expected = SPLIT_FAMILY_COUNTS[split]
    counts = Counter(task.get("family") for task in tasks)
    observed = {family: counts.get(family, 0) for family in FAMILIES}
    if observed != expected:
        raise VideoBenchmarkContractError(
            f"{split} family distribution differs: expected {expected}, observed {observed}"
        )
    return observed


def _provenance_pin(tasks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not tasks:
        raise VideoBenchmarkContractError("cannot pin provenance for an empty split")
    first = tasks[0].get("provenance")
    if not isinstance(first, Mapping):
        raise VideoBenchmarkContractError("task provenance is missing")
    pin: dict[str, Any] = {}
    for key in (*PROVENANCE_HASH_FIELDS, *PROVENANCE_ID_FIELDS):
        value = first.get(key)
        if key in PROVENANCE_HASH_FIELDS:
            if not isinstance(value, str) or not value.startswith("sha256:") or len(value) != 71:
                raise VideoBenchmarkContractError(f"provenance.{key} is not pinned")
        elif key != "adapter_ref" and not isinstance(value, str):
            raise VideoBenchmarkContractError(f"provenance.{key} is not pinned")
        for task in tasks[1:]:
            candidate = (
                task.get("provenance", {}).get(key)
                if isinstance(task.get("provenance"), Mapping)
                else None
            )
            if candidate != value:
                raise VideoBenchmarkContractError(f"provenance.{key} drifts across the roster")
        pin[key] = value
    return pin


def build_benchmark_freeze(
    dev_tasks: Sequence[Mapping[str, Any]],
    frozen_tasks: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a synthetic, pre-output benchmark freeze candidate.

    This function intentionally returns an in-memory contract only.  It does
    not write a terminal manifest and cannot accept model output.  The split
    roster is exact: 64 development tasks and 32 frozen tasks, with one
    disjoint leakage-group universe and twelve critical frozen tasks.
    """

    for split, tasks in (("dev", dev_tasks), ("frozen", frozen_tasks)):
        validate_task_roster(tasks, expected_total=sum(SPLIT_FAMILY_COUNTS[split].values()))
        _split_counts(tasks, split)
    dev_ids = {task["task_id"] for task in dev_tasks}
    frozen_ids = {task["task_id"] for task in frozen_tasks}
    if dev_ids & frozen_ids:
        raise VideoBenchmarkContractError("task ids overlap between dev and frozen")
    dev_groups = {task["leakage_group"] for task in dev_tasks}
    frozen_groups = {task["leakage_group"] for task in frozen_tasks}
    if dev_groups & frozen_groups:
        raise VideoBenchmarkContractError("leakage groups overlap between dev and frozen")
    all_tasks = [*dev_tasks, *frozen_tasks]
    pin = _provenance_pin(all_tasks)
    critical = [task for task in frozen_tasks if task.get("criticality") == "critical"]
    if len(critical) != 12:
        raise VideoBenchmarkContractError("frozen roster must contain exactly 12 critical tasks")
    critical_slots = [
        {"slot": f"critical-{index:02d}", "task_id": task["task_id"], "family": task["family"]}
        for index, task in enumerate(sorted(critical, key=lambda item: item["task_id"]), start=1)
    ]
    return {
        "schema_version": 1,
        "freeze_id": "video-semantics/benchmark-freeze-v1",
        "status": "synthetic_contract",
        "terminal_manifest": None,
        "benchmark_revision": benchmark_revision(all_tasks),
        "split_counts": {
            "dev": {"total": len(dev_tasks), "families": _split_counts(dev_tasks, "dev")},
            "frozen": {
                "total": len(frozen_tasks),
                "families": _split_counts(frozen_tasks, "frozen"),
            },
        },
        "critical": {"total": len(critical), "slots": critical_slots},
        "leakage_groups": {
            "dev": len(dev_groups),
            "frozen": len(frozen_groups),
            "disjoint": True,
        },
        "provenance": pin,
        "model_outputs_present": False,
        "tasks": {"dev": list(dev_tasks), "frozen": list(frozen_tasks)},
    }


freeze_benchmark = build_benchmark_freeze
freeze_task_roster = build_benchmark_freeze
