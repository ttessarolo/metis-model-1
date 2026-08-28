"""Pure paired-evaluation contracts for the video semantic-grounding wave.

This module is intentionally an observation and arithmetic boundary.  It does
not invoke a model, accept model text, run a compiler, or write an evaluation
artifact.  A caller may provide already-sanitised observation facts, but the
four-way roster and every denominator are recomputed here.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from metis_model1.evaluation import wilson_interval

VARIANTS = ("B0", "B1", "D0", "D1")
FAMILIES = ("V-1", "V-2", "V-3", "V-4", "V-5", "V-6", "V-7")
FAMILY_COUNTS = {
    "V-1": 20,
    "V-2": 20,
    "V-3": 16,
    "V-4": 16,
    "V-5": 12,
    "V-6": 8,
    "V-7": 4,
}
SPLIT_COUNTS = {"dev": 64, "frozen": 32}
FROZEN_FAMILY_COUNTS = {
    "V-1": 6,
    "V-2": 6,
    "V-3": 6,
    "V-4": 6,
    "V-5": 4,
    "V-6": 2,
    "V-7": 2,
}

# The taxonomy is the reporting taxonomy in docs/03, while this order is the
# remediation order in docs/24 section 18.1.  Keeping both explicit avoids a
# report silently using the diagnostic priority as a model-failure category.
FAILURE_TAXONOMY = (
    "intent_misunderstanding",
    "syntax_error",
    "linking_symbol_error",
    "validation_error",
    "compile_failure",
    "semantic_error_compile_clean",
    "nonminimal_or_regressive_patch",
    "insufficient_context_or_retrieval",
    "tool_or_repair_loop_failure",
    "benchmark_ambiguous_oracle_defect",
)
DIAGNOSTIC_ORDER = (
    "editorial_source_insufficient",
    "crosswalk_error",
    "catalog_metadata_missing",
    "description_or_alias_insufficient",
    "retrieval_ranking_or_clarification",
    "toolchain_compiler_or_oracle",
    "prompt_assembly",
    "model_procedural_behavior",
    "grammar_ast_ir_changed",
    "benchmark_ambiguous_or_contaminated",
)
_CATEGORY_ALIASES = {
    "model_procedural": "model_procedural_behavior",
    "procedural_model": "model_procedural_behavior",
    "model_procedural_behavior": "model_procedural_behavior",
    "benchmark_ambiguous_oracle_defect": "benchmark_ambiguous_or_contaminated",
}
_FORBIDDEN_OUTPUT_KEYS = frozenset(
    {"model_output", "raw_output", "output", "response", "completion", "chain_of_thought"}
)
_OBSERVATION_KEYS = frozenset(
    {
        "task_id",
        "variant",
        "first_shot_success",
        "post_repair_success",
        "repair_cycles",
        "failures",
        "failure_taxonomy",
        "critical_failures",
        "failure_roots",
        "roots",
        "semantic_refs_valid",
        "receipt_sanitized",
        "hallucinated_identifier",
        "wrong_catalog",
        "silent_unsupported",
        "diagnostic_category",
        "pins",
    }
)
_OPAQUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class VideoEvaluationError(ValueError):
    """Raised when a paired roster or scorecard is not a closed contract."""


def _strict_bool(value: Any, label: str) -> bool:
    if type(value) is not bool:
        raise VideoEvaluationError(f"{label} must be a strict bool")
    return value


def _nonempty(value: Any, label: str) -> str:
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > 256
        or any(ord(char) < 0x20 or 0x7F <= ord(char) <= 0x9F for char in value)
    ):
        raise VideoEvaluationError(f"{label} must be a bounded non-empty string")
    return value


def _opaque(value: Any, label: str) -> str:
    value = _nonempty(value, label)
    if _OPAQUE_RE.fullmatch(value) is None:
        raise VideoEvaluationError(f"{label} must be an opaque identifier")
    return value


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise VideoEvaluationError(f"{label} must be sha256:<64 lowercase hex>")
    return value


def _task_pins(task: Mapping[str, Any]) -> dict[str, Any]:
    pins = task.get("pins", task.get("provenance"))
    if not isinstance(pins, Mapping):
        raise VideoEvaluationError(f"task {task.get('task_id', '<unknown>')}: pins are required")
    return dict(pins)


def _canonical_pins(task: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
    pins = _task_pins(task)
    # These are identity pins, not arbitrary task metadata.  Requiring the
    # benchmark and oracle revision here prevents a scorecard from combining
    # rows from two freezes.
    required = (
        "benchmark_revision",
        "oracle_revision",
        "semantic_source_revision",
        "constraint_revision",
        "grammar_revision",
        "toolchain_revision",
        "base_model_ref",
        "tokenizer_ref",
        "adapter_ref",
        "decoding_profile",
    )
    if set(pins) != set(required):
        raise VideoEvaluationError("task pins must match the closed evaluation pin roster")
    result: list[tuple[str, Any]] = []
    for key in required:
        value = pins.get(key)
        if key.endswith("_revision") or key in {"benchmark_revision", "oracle_revision"}:
            _sha(value, f"pins.{key}")
        elif key == "adapter_ref" and value is None:
            pass
        else:
            _nonempty(value, f"pins.{key}")
        result.append((key, value))
    return tuple(result)


def _task_roster(
    tasks: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, Any]]:
    if not isinstance(tasks, Sequence) or isinstance(tasks, str | bytes | bytearray):
        raise VideoEvaluationError("tasks must be a sequence")
    if len(tasks) != 96:
        raise VideoEvaluationError("task denominator must be exactly 96")
    by_id: dict[str, Mapping[str, Any]] = {}
    family_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    critical_count = 0
    leakage_by_split: dict[str, set[str]] = {"dev": set(), "frozen": set()}
    pin_values: tuple[tuple[str, Any], ...] | None = None
    for index, task in enumerate(tasks):
        if not isinstance(task, Mapping):
            raise VideoEvaluationError(f"task[{index}] must be an object")
        if _FORBIDDEN_OUTPUT_KEYS & set(task):
            raise VideoEvaluationError(f"task[{index}] contains model output")
        task_id = _opaque(task.get("task_id"), f"task[{index}].task_id")
        if task_id in by_id:
            raise VideoEvaluationError(f"duplicate task_id: {task_id}")
        family = task.get("family")
        if family not in FAMILIES:
            raise VideoEvaluationError(f"task {task_id} has an invalid family")
        split = task.get("split")
        if split not in SPLIT_COUNTS:
            raise VideoEvaluationError(f"task {task_id} has an invalid split")
        group = _opaque(task.get("leakage_group"), f"task {task_id}.leakage_group")
        leakage_by_split[split].add(group)
        current_pins = _canonical_pins(task)
        if pin_values is None:
            pin_values = current_pins
        elif current_pins != pin_values:
            raise VideoEvaluationError(f"task {task_id} pin drift")
        by_id[task_id] = task
        family_counts[family] += 1
        split_counts[split] += 1
        if task.get("criticality") not in {"normal", "critical"}:
            raise VideoEvaluationError(f"task {task_id} has invalid criticality")
        if task.get("criticality") == "critical":
            if split != "frozen":
                raise VideoEvaluationError("critical task must belong to the frozen split")
            critical_count += 1
    if dict(family_counts) != FAMILY_COUNTS:
        raise VideoEvaluationError(
            f"family denominator mismatch: expected {FAMILY_COUNTS}, observed {dict(family_counts)}"
        )
    if dict(split_counts) != SPLIT_COUNTS:
        raise VideoEvaluationError(
            f"split denominator mismatch: expected {SPLIT_COUNTS}, observed {dict(split_counts)}"
        )
    if leakage_by_split["dev"] & leakage_by_split["frozen"]:
        raise VideoEvaluationError("leakage groups overlap between dev and frozen")
    frozen_family_counts = Counter(
        task["family"] for task in by_id.values() if task["split"] == "frozen"
    )
    if dict(frozen_family_counts) != FROZEN_FAMILY_COUNTS:
        raise VideoEvaluationError(
            "frozen family denominator mismatch: "
            f"expected {FROZEN_FAMILY_COUNTS}, observed {dict(frozen_family_counts)}"
        )
    if critical_count != 12:
        raise VideoEvaluationError("frozen roster must contain exactly 12 critical tasks")
    return by_id, {
        "tasks": 96,
        "distinct_tasks": len(by_id),
        "gaps": 0,
        "family_counts": dict(FAMILY_COUNTS),
        "split_counts": dict(SPLIT_COUNTS),
        "frozen_family_counts": dict(FROZEN_FAMILY_COUNTS),
        "critical_tasks": 12,
        "leakage_groups": len(leakage_by_split["dev"] | leakage_by_split["frozen"]),
        "leakage_disjoint": True,
        "pins": dict(pin_values or ()),
    }


def _observation(row: Mapping[str, Any], task: Mapping[str, Any]) -> dict[str, Any]:
    unknown_output = _FORBIDDEN_OUTPUT_KEYS & set(row)
    if unknown_output:
        raise VideoEvaluationError("model output is not accepted in observations")
    if set(row) - _OBSERVATION_KEYS:
        raise VideoEvaluationError("observation contains unknown fields")
    task_id = _opaque(row.get("task_id"), "observation.task_id")
    if task_id != task["task_id"]:
        raise VideoEvaluationError("observation task_id does not match task roster")
    variant = row.get("variant")
    if variant not in VARIANTS:
        raise VideoEvaluationError(f"observation {task_id} has an invalid variant")
    if "first_shot_success" not in row or "post_repair_success" not in row:
        raise VideoEvaluationError(f"observation {task_id}/{variant} lacks success fields")
    first = _strict_bool(row["first_shot_success"], "first_shot_success")
    post = _strict_bool(row["post_repair_success"], "post_repair_success")
    required_safety = (
        "repair_cycles",
        "semantic_refs_valid",
        "receipt_sanitized",
        "hallucinated_identifier",
        "wrong_catalog",
        "silent_unsupported",
    )
    if any(key not in row for key in required_safety):
        raise VideoEvaluationError("observation lacks explicit repair or safety fields")
    cycles = row["repair_cycles"]
    if type(cycles) is not int or not 0 <= cycles <= 2:
        raise VideoEvaluationError("repair_cycles must be an integer from 0 to 2")
    if first and (not post or cycles != 0):
        raise VideoEvaluationError("a successful first shot cannot regress or enter repair")
    if not first and post and cycles == 0:
        raise VideoEvaluationError("post-repair success requires an explicit repair cycle")
    failures = row.get("failures", row.get("failure_taxonomy", []))
    if not isinstance(failures, Sequence) or isinstance(failures, str | bytes | bytearray):
        raise VideoEvaluationError("failures must be a sequence")
    failures = list(failures)
    for failure in failures:
        if failure not in FAILURE_TAXONOMY:
            raise VideoEvaluationError(f"unknown failure taxonomy category: {failure}")
    critical = row.get("critical_failures", [])
    if not isinstance(critical, Sequence) or isinstance(critical, str | bytes | bytearray):
        raise VideoEvaluationError("critical_failures must be a sequence")
    if any(type(item) is not str or _OPAQUE_RE.fullmatch(item) is None for item in critical):
        raise VideoEvaluationError("critical_failures must contain opaque identifiers")
    roots = row.get("failure_roots", row.get("roots", []))
    if not isinstance(roots, Sequence) or isinstance(roots, str | bytes | bytearray):
        raise VideoEvaluationError("failure_roots must be a sequence")
    if any(type(root) is not str or _OPAQUE_RE.fullmatch(root) is None for root in roots):
        raise VideoEvaluationError("failure_roots must contain opaque identifiers")
    semantic_refs = row["semantic_refs_valid"]
    receipt_sanitized = row["receipt_sanitized"]
    _strict_bool(semantic_refs, "semantic_refs_valid")
    _strict_bool(receipt_sanitized, "receipt_sanitized")
    task_pins = dict(_canonical_pins(task))
    row_pins = row.get("pins")
    if row_pins is not None and row_pins != task_pins:
        raise VideoEvaluationError(f"observation {task_id}/{variant} pin drift")
    diagnostic = row.get("diagnostic_category")
    if diagnostic is not None:
        diagnostic = _CATEGORY_ALIASES.get(diagnostic, diagnostic)
        if diagnostic not in DIAGNOSTIC_ORDER:
            raise VideoEvaluationError(f"unknown diagnostic category: {diagnostic}")
    if not post and (not failures or diagnostic is None):
        raise VideoEvaluationError(
            "failed observation requires failure taxonomy and diagnostic category"
        )
    if post and critical:
        raise VideoEvaluationError("successful observation cannot carry critical failures")
    return {
        "task_id": task_id,
        "variant": variant,
        "first_shot_success": first,
        "post_repair_success": post,
        "repair_cycles": cycles,
        "failures": tuple(failures),
        "critical_failures": tuple(dict.fromkeys(critical)),
        "failure_roots": tuple(roots),
        "semantic_refs_valid": semantic_refs,
        "receipt_sanitized": receipt_sanitized,
        "hallucinated_identifier": _strict_bool(
            row["hallucinated_identifier"], "hallucinated_identifier"
        ),
        "wrong_catalog": _strict_bool(row["wrong_catalog"], "wrong_catalog"),
        "silent_unsupported": _strict_bool(row["silent_unsupported"], "silent_unsupported"),
        "diagnostic_category": diagnostic,
    }


def _aggregate(
    rows: Sequence[Mapping[str, Any]], tasks: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    total = len(rows)
    if total != 96:
        raise VideoEvaluationError("each variant must have exactly 96 observations")
    first_successes = sum(row["first_shot_success"] for row in rows)
    post_successes = sum(row["post_repair_success"] for row in rows)
    family: dict[str, dict[str, int]] = {}
    taxonomy = Counter()
    critical = Counter()
    splits: dict[str, dict[str, Any]] = {
        "dev": {"total": 0, "post_repair_successes": 0, "families": {}},
        "frozen": {"total": 0, "post_repair_successes": 0, "families": {}},
    }
    hallucinated = 0
    wrong_catalog = 0
    silent_unsupported = 0
    failure_rows: list[dict[str, Any]] = []
    critical_total = 0
    critical_passed = 0
    for row in rows:
        task = tasks[row["task_id"]]
        fam = task["family"]
        split = task["split"]
        item = family.setdefault(
            fam,
            {"first_shot_successes": 0, "post_repair_successes": 0, "total": 0},
        )
        item["total"] += 1
        item["first_shot_successes"] += int(row["first_shot_success"])
        item["post_repair_successes"] += int(row["post_repair_success"])
        taxonomy.update(row["failures"])
        critical.update(row["critical_failures"])
        split_item = splits[split]
        split_item["total"] += 1
        split_item["post_repair_successes"] += int(row["post_repair_success"])
        split_family = split_item["families"].setdefault(
            fam, {"total": 0, "post_repair_successes": 0}
        )
        split_family["total"] += 1
        split_family["post_repair_successes"] += int(row["post_repair_success"])
        hallucinated += int(row["hallucinated_identifier"])
        wrong_catalog += int(row["wrong_catalog"])
        silent_unsupported += int(row["silent_unsupported"])
        failure_rows.append(
            {
                **dict(row),
                "family": fam,
                "split": split,
                "criticality": task.get("criticality"),
            }
        )
        if task.get("split") == "frozen" and task.get("criticality") == "critical":
            critical_total += 1
            critical_passed += int(row["post_repair_success"] and not row["critical_failures"])
    for fam in FAMILIES:
        item = family.get(fam)
        if item is None or item["total"] != FAMILY_COUNTS[fam]:
            raise VideoEvaluationError(f"variant family denominator mismatch for {fam}")
    return {
        "total": total,
        "first_shot": {
            "successes": first_successes,
            "total": total,
            "wilson95": tuple(wilson_interval(first_successes, total)),
        },
        "post_repair": {
            "successes": post_successes,
            "total": total,
            "wilson95": tuple(wilson_interval(post_successes, total)),
        },
        "families": family,
        "splits": splits,
        "failure_taxonomy": {key: taxonomy.get(key, 0) for key in FAILURE_TAXONOMY},
        "critical_failures": dict(sorted(critical.items())),
        "critical": {
            "total": critical_total,
            "passed": critical_passed,
            "failed": critical_total - critical_passed,
        },
        "hallucinated_identifiers": hallucinated,
        "wrong_catalog": wrong_catalog,
        "silent_unsupported": silent_unsupported,
        "failure_rows": failure_rows,
        "semantic_refs_valid": sum(row["semantic_refs_valid"] for row in rows) == total,
        "receipts_sanitized": sum(row["receipt_sanitized"] for row in rows) == total,
    }


def evaluate_paired_observations(
    tasks: Sequence[Mapping[str, Any]], observations: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """Validate exactly 96 x 4 observations and return recomputed scorecards."""

    by_id, roster = _task_roster(tasks)
    rows = list(observations)
    if len(rows) != 384:
        raise VideoEvaluationError("observation denominator must be exactly 384 (96 x 4)")
    seen: set[tuple[str, str]] = set()
    by_variant: dict[str, list[dict[str, Any]]] = {variant: [] for variant in VARIANTS}
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise VideoEvaluationError(f"observation[{index}] must be an object")
        task_id = raw.get("task_id")
        if task_id not in by_id:
            raise VideoEvaluationError(f"observation references unknown task: {task_id}")
        parsed = _observation(raw, by_id[task_id])
        key = (parsed["task_id"], parsed["variant"])
        if key in seen:
            raise VideoEvaluationError(f"duplicate observation: {key[0]}/{key[1]}")
        seen.add(key)
        by_variant[parsed["variant"]].append(parsed)
    expected = {(task_id, variant) for task_id in by_id for variant in VARIANTS}
    if seen != expected:
        missing = sorted(expected - seen)
        raise VideoEvaluationError(f"missing observation(s): {missing[:3]}")
    scorecards = {variant: _aggregate(by_variant[variant], by_id) for variant in VARIANTS}
    return {
        "schema_version": 1,
        "evaluation_id": "video-semantics/paired-evaluation-v1",
        "roster": roster,
        "variants": list(VARIANTS),
        "observations": 384,
        "scorecards": scorecards,
        "diagnostic_order": list(DIAGNOSTIC_ORDER),
        "benchmark_revision": roster["pins"]["benchmark_revision"],
        "model_outputs_present": False,
    }


def score_paired_observations(
    tasks: Sequence[Mapping[str, Any]], observations: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """Short alias for :func:`evaluate_paired_observations`."""

    return evaluate_paired_observations(tasks, observations)


build_paired_evaluation = evaluate_paired_observations
validate_observation_roster = evaluate_paired_observations


__all__ = [
    "DIAGNOSTIC_ORDER",
    "FAILURE_TAXONOMY",
    "FAMILIES",
    "FAMILY_COUNTS",
    "FROZEN_FAMILY_COUNTS",
    "SPLIT_COUNTS",
    "VARIANTS",
    "VideoEvaluationError",
    "build_paired_evaluation",
    "evaluate_paired_observations",
    "score_paired_observations",
    "validate_observation_roster",
]
