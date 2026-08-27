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
