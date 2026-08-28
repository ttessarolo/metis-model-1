"""Fail-closed weight verdict for the video grounding maintenance wave.

The policy consumes a terminal benchmark, a complete paired-evaluation report,
and independently produced gate receipts. It recomputes every decision-bearing
aggregate from the 384 sanitized observation rows and never grants training or
promotion authority.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from metis_model1.evaluation import wilson_interval
from metis_model1.video_grounding_evaluation import (
    DIAGNOSTIC_ORDER,
    FAILURE_TAXONOMY,
    FAMILIES,
    FAMILY_COUNTS,
    FROZEN_FAMILY_COUNTS,
    SPLIT_COUNTS,
    VARIANTS,
)

BLOCKED = "BLOCKED"
NO_RETRAIN = "NO_RETRAIN"
DELTA_ELIGIBLE = "DELTA_ELIGIBLE"
FULL_SUCCESSOR_REQUIRED = "FULL_SUCCESSOR_REQUIRED"
OUTCOMES = (BLOCKED, NO_RETRAIN, DELTA_ELIGIBLE, FULL_SUCCESSOR_REQUIRED)

REQUIRED_UPSTREAM_GATES = (
    "SEMANTIC_GRAMMAR_SURFACE_FROZEN",
    "SEMANTIC_CROSSWALK_COMPLETE",
    "SEMANTIC_RETRIEVAL_INJECTION_SAFE",
    "SEMANTIC_ROLLBACK_VALID",
    "OBSERVABILITY_SANITIZED",
)
REQUIRED_BENCHMARK_GATES = (
    "BENCHMARK_FROZEN_NO_LEAKAGE",
    "VIDEO_BENCHMARK_THRESHOLD_RATIFIED",
)
DELTA_COMPATIBLE_DIAGNOSTICS = frozenset({"model_procedural_behavior"})
_SHA_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_OPAQUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_DEV_FAMILY_COUNTS = {
    family: FAMILY_COUNTS[family] - FROZEN_FAMILY_COUNTS[family] for family in FAMILIES
}
_EVALUATION_KEYS = frozenset(
    {
        "schema_version",
        "evaluation_id",
        "roster",
        "variants",
        "observations",
        "scorecards",
        "diagnostic_order",
        "benchmark_revision",
        "model_outputs_present",
    }
)
_VARIANT_KEYS = frozenset(
    {
        "total",
        "first_shot",
        "post_repair",
        "families",
        "splits",
        "failure_taxonomy",
        "critical_failures",
        "critical",
        "hallucinated_identifiers",
        "wrong_catalog",
        "silent_unsupported",
        "failure_rows",
        "semantic_refs_valid",
        "receipts_sanitized",
    }
)
_FAILURE_ROW_KEYS = frozenset(
    {
        "task_id",
        "variant",
        "first_shot_success",
        "post_repair_success",
        "repair_cycles",
        "failures",
        "critical_failures",
        "failure_roots",
        "semantic_refs_valid",
        "receipt_sanitized",
        "hallucinated_identifier",
        "wrong_catalog",
        "silent_unsupported",
        "diagnostic_category",
        "family",
        "split",
        "criticality",
    }
)


class VideoWeightVerdictError(ValueError):
    """Raised for malformed verdict inputs; missing authority returns BLOCKED."""


def _blocked(reasons: list[str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "verdict": BLOCKED,
        "reasons": list(dict.fromkeys(reasons)),
        "training_authorized": False,
        "promotion_authorized": False,
        "delta_training_authorized": False,
    }


def _hash(value: Any) -> bool:
    return isinstance(value, str) and _SHA_RE.fullmatch(value) is not None


def _sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray)


def _opaque_sequence(value: Any) -> bool:
    return _sequence(value) and all(
        type(item) is str and _OPAQUE_RE.fullmatch(item) is not None for item in value
    )


def _ready_benchmark(benchmark: Any) -> tuple[bool, list[str]]:
    if not isinstance(benchmark, Mapping):
        return False, ["frozen benchmark is absent"]
    reasons: list[str] = []
    if benchmark.get("status") != "terminal":
        reasons.append("frozen benchmark is not terminally frozen")
    if not _hash(benchmark.get("terminal_manifest")):
        reasons.append("frozen benchmark manifest is absent or unpinned")
    if benchmark.get("model_outputs_present") is not False:
        reasons.append("benchmark model-output absence is not explicit")
    if not _hash(benchmark.get("benchmark_revision")):
        reasons.append("frozen benchmark revision is not pinned")
    split_counts = benchmark.get("split_counts")
    expected_splits = {
        "dev": {"total": 64, "families": _DEV_FAMILY_COUNTS},
        "frozen": {"total": 32, "families": FROZEN_FAMILY_COUNTS},
    }
    if not isinstance(split_counts, Mapping) or set(split_counts) != set(expected_splits):
        reasons.append("frozen benchmark split roster is absent")
    else:
        for split, expected in expected_splits.items():
            item = split_counts.get(split)
            if not isinstance(item, Mapping) or item.get("total") != expected["total"]:
                reasons.append(f"frozen benchmark {split} denominator is invalid")
            elif item.get("families") != expected["families"]:
                reasons.append(f"frozen benchmark {split} family roster is invalid")
    critical = benchmark.get("critical")
    if not isinstance(critical, Mapping) or critical.get("total") != 12:
        reasons.append("frozen benchmark critical denominator is not 12")
    leakage = benchmark.get("leakage_groups")
    if not isinstance(leakage, Mapping) or leakage.get("disjoint") is not True:
        reasons.append("frozen benchmark leakage separation is not explicit")
    return not reasons, reasons


def _ratified_thresholds(thresholds: Any, benchmark_revision: str) -> tuple[bool, list[str]]:
    if not isinstance(thresholds, Mapping):
        return False, ["benchmark thresholds are absent"]
    reasons: list[str] = []
    if thresholds.get("status") != "ratified":
        reasons.append("benchmark thresholds are not ratified")
    if thresholds.get("ratified_before_observations") is not True:
        reasons.append("threshold ratification chronology is absent")
    if thresholds.get("benchmark_revision") != benchmark_revision:
        reasons.append("thresholds are not pinned to the frozen benchmark")
    expected = {
        "frozen_semantic_min": 30,
        "full_suite_semantic_min": 92,
        "frozen_family_floor": {
            "V-1": 5,
            "V-2": 5,
            "V-3": 5,
            "V-4": 5,
            "V-5": 4,
            "V-6": 2,
            "V-7": 2,
        },
        "full_family_floor": {
            "V-1": 18,
            "V-2": 18,
            "V-3": 15,
            "V-4": 15,
            "V-5": 11,
            "V-6": 8,
            "V-7": 4,
        },
        "critical_failures_max": 0,
        "hallucinated_identifiers_max": 0,
        "wrong_catalog_max": 0,
        "silent_unsupported_max": 0,
        "semantic_refs_valid_percent": 100,
        "receipts_sanitized_percent": 100,
    }
    for key, value in expected.items():
        if thresholds.get(key) != value:
            reasons.append(f"threshold {key} is not the preregistered value")
    return not reasons, reasons


def _green_receipts(receipts: Any, benchmark_revision: str) -> tuple[bool, list[str]]:
    if not isinstance(receipts, Mapping):
        return False, ["upstream gate receipts are absent"]
    reasons: list[str] = []
    for gate in (*REQUIRED_UPSTREAM_GATES, *REQUIRED_BENCHMARK_GATES):
        value = receipts.get(gate)
        if not (
            isinstance(value, Mapping)
            and value.get("status") == "PASS"
            and _hash(value.get("receipt_sha256"))
            and value.get("benchmark_revision") == benchmark_revision
        ):
            reasons.append(f"required gate receipt is invalid or unbound: {gate}")
    return not reasons, reasons


def _recompute_variant(
    variant: str, item: Mapping[str, Any]
) -> tuple[list[str], dict[str, tuple[str, str, str]]]:
    """Recompute every decision-bearing aggregate from sanitized task rows."""

    reasons: list[str] = []
    if set(item) != _VARIANT_KEYS:
        return [f"scorecard fields for {variant} are not the closed contract"], {}
    rows = item.get("failure_rows")
    if not isinstance(rows, list) or len(rows) != 96:
        return [f"scorecard row denominator for {variant} is not 96"], {}

    signatures: dict[str, tuple[str, str, str]] = {}
    family_total: Counter[str] = Counter()
    family_first: Counter[str] = Counter()
    family_post: Counter[str] = Counter()
    split_total: Counter[str] = Counter()
    split_post: Counter[str] = Counter()
    split_family_total = {split: Counter() for split in SPLIT_COUNTS}
    split_family_post = {split: Counter() for split in SPLIT_COUNTS}
    taxonomy: Counter[str] = Counter()
    critical_failures: Counter[str] = Counter()
    first_successes = 0
    post_successes = 0
    critical_total = 0
    critical_passed = 0
    hallucinated = 0
    wrong_catalog = 0
    silent_unsupported = 0
    all_refs = True
    all_receipts = True

    for index, row in enumerate(rows):
        label = f"{variant} row[{index}]"
        if not isinstance(row, Mapping) or set(row) != _FAILURE_ROW_KEYS:
            reasons.append(f"{label} is not the closed row contract")
            continue
        task_id = row.get("task_id")
        family = row.get("family")
        split = row.get("split")
        criticality = row.get("criticality")
        if type(task_id) is not str or _OPAQUE_RE.fullmatch(task_id) is None:
            reasons.append(f"{label} task id is invalid")
            continue
        if task_id in signatures:
            reasons.append(f"{variant} contains duplicate task id {task_id}")
            continue
        if row.get("variant") != variant:
            reasons.append(f"{label} variant is inconsistent")
        if family not in FAMILIES or split not in SPLIT_COUNTS:
            reasons.append(f"{label} family or split is invalid")
            continue
        if criticality not in {"normal", "critical"}:
            reasons.append(f"{label} criticality is invalid")
            continue
        if criticality == "critical" and split != "frozen":
            reasons.append(f"{label} critical task is outside the frozen split")
        signatures[task_id] = (family, split, criticality)

        bool_keys = (
            "first_shot_success",
            "post_repair_success",
            "semantic_refs_valid",
            "receipt_sanitized",
            "hallucinated_identifier",
            "wrong_catalog",
            "silent_unsupported",
        )
        if any(type(row.get(key)) is not bool for key in bool_keys):
            reasons.append(f"{label} contains a non-boolean fact")
            continue
        first = row["first_shot_success"]
        post = row["post_repair_success"]
        cycles = row.get("repair_cycles")
        if type(cycles) is not int or not 0 <= cycles <= 2:
            reasons.append(f"{label} repair cycle is invalid")
            continue
        if first and (not post or cycles != 0):
            reasons.append(f"{label} successful first shot is incoherent")
        if not first and post and cycles == 0:
            reasons.append(f"{label} post-repair success lacks a repair cycle")

        failures = row.get("failures")
        critical = row.get("critical_failures")
        roots = row.get("failure_roots")
        diagnostic = row.get("diagnostic_category")
        if not _sequence(failures) or any(value not in FAILURE_TAXONOMY for value in failures):
            reasons.append(f"{label} failure taxonomy is invalid")
            continue
        if not _opaque_sequence(critical) or not _opaque_sequence(roots):
            reasons.append(f"{label} critical failures or roots are invalid")
            continue
        if diagnostic is not None and diagnostic not in DIAGNOSTIC_ORDER:
            reasons.append(f"{label} diagnostic category is invalid")
            continue
        if not post and (not failures or diagnostic is None):
            reasons.append(f"{label} failed outcome lacks taxonomy or diagnosis")
        if post and critical:
            reasons.append(f"{label} successful outcome carries a critical failure")

        first_successes += int(first)
        post_successes += int(post)
        family_total[family] += 1
        family_first[family] += int(first)
        family_post[family] += int(post)
        split_total[split] += 1
        split_post[split] += int(post)
        split_family_total[split][family] += 1
        split_family_post[split][family] += int(post)
        taxonomy.update(failures)
        critical_failures.update(critical)
        hallucinated += int(row["hallucinated_identifier"])
        wrong_catalog += int(row["wrong_catalog"])
        silent_unsupported += int(row["silent_unsupported"])
        all_refs = all_refs and row["semantic_refs_valid"]
        all_receipts = all_receipts and row["receipt_sanitized"]
        if criticality == "critical":
            critical_total += 1
            critical_passed += int(post and not critical)

    if len(signatures) != 96:
        reasons.append(f"scorecard distinct row denominator for {variant} is not 96")
    if dict(family_total) != FAMILY_COUNTS:
        reasons.append(f"scorecard family denominators for {variant} drift from the roster")
    if dict(split_total) != SPLIT_COUNTS:
        reasons.append(f"scorecard split denominators for {variant} drift from the roster")
    if dict(split_family_total["frozen"]) != FROZEN_FAMILY_COUNTS:
        reasons.append(f"scorecard frozen-family denominators for {variant} drift")
    if critical_total != 12:
        reasons.append(f"critical denominator for {variant} is not 12")

    expected_scores = {
        "first_shot": (first_successes, tuple(wilson_interval(first_successes, 96))),
        "post_repair": (post_successes, tuple(wilson_interval(post_successes, 96))),
    }
    for key, (successes, interval) in expected_scores.items():
        declared = item.get(key)
        if not isinstance(declared, Mapping) or set(declared) != {
            "successes",
            "total",
            "wilson95",
        }:
            reasons.append(f"scorecard {variant}/{key} is malformed")
        elif (
            declared.get("successes") != successes
            or declared.get("total") != 96
            or tuple(declared.get("wilson95", ())) != interval
        ):
            reasons.append(f"scorecard {variant}/{key} aggregate is not recomputable")

    declared_families = item.get("families")
    if not isinstance(declared_families, Mapping) or set(declared_families) != set(FAMILIES):
        reasons.append(f"scorecard family roster for {variant} is incomplete")
    else:
        for family in FAMILIES:
            expected = {
                "first_shot_successes": family_first[family],
                "post_repair_successes": family_post[family],
                "total": FAMILY_COUNTS[family],
            }
            if declared_families.get(family) != expected:
                reasons.append(f"scorecard family aggregate for {variant}/{family} drifts")

    declared_splits = item.get("splits")
    if not isinstance(declared_splits, Mapping) or set(declared_splits) != set(SPLIT_COUNTS):
        reasons.append(f"scorecard split roster for {variant} is incomplete")
    else:
        for split in SPLIT_COUNTS:
            expected_families = {
                family: {
                    "total": split_family_total[split][family],
                    "post_repair_successes": split_family_post[split][family],
                }
                for family in FAMILIES
                if split_family_total[split][family]
            }
            expected = {
                "total": SPLIT_COUNTS[split],
                "post_repair_successes": split_post[split],
                "families": expected_families,
            }
            if declared_splits.get(split) != expected:
                reasons.append(f"scorecard split aggregate for {variant}/{split} drifts")

    expected_values = {
        "failure_taxonomy": {key: taxonomy.get(key, 0) for key in FAILURE_TAXONOMY},
        "critical_failures": dict(sorted(critical_failures.items())),
        "critical": {
            "total": critical_total,
            "passed": critical_passed,
            "failed": critical_total - critical_passed,
        },
        "hallucinated_identifiers": hallucinated,
        "wrong_catalog": wrong_catalog,
        "silent_unsupported": silent_unsupported,
        "semantic_refs_valid": all_refs,
        "receipts_sanitized": all_receipts,
    }
    for key, expected in expected_values.items():
        if item.get(key) != expected:
            reasons.append(f"scorecard aggregate for {variant}/{key} drifts")
    return reasons, signatures


def _scorecard_ready(
    evaluation: Any, benchmark_revision: str
) -> tuple[bool, list[str], Mapping[str, Any] | None]:
    if not isinstance(evaluation, Mapping):
        return False, ["paired evaluation is absent"], None
    reasons: list[str] = []
    if set(evaluation) != _EVALUATION_KEYS:
        reasons.append("paired evaluation is not the closed report contract")
    if evaluation.get("schema_version") != 1:
        reasons.append("paired evaluation schema version is invalid")
    if evaluation.get("evaluation_id") != "video-semantics/paired-evaluation-v1":
        reasons.append("paired evaluation id is invalid")
    if evaluation.get("benchmark_revision") != benchmark_revision:
        reasons.append("paired evaluation is not bound to the frozen benchmark")
    if evaluation.get("observations") != 384:
        reasons.append("paired evaluation denominator is not 384")
    if evaluation.get("variants") != list(VARIANTS):
        reasons.append("paired evaluation variant roster is incomplete")
    if evaluation.get("diagnostic_order") != list(DIAGNOSTIC_ORDER):
        reasons.append("paired evaluation diagnostic order drifts")
    if evaluation.get("model_outputs_present") is not False:
        reasons.append("paired evaluation contains model output")
    roster = evaluation.get("roster")
    if not isinstance(roster, Mapping):
        reasons.append("paired evaluation roster is absent")
    elif (
        roster.get("tasks") != 96
        or roster.get("distinct_tasks") != 96
        or roster.get("gaps") != 0
        or roster.get("family_counts") != FAMILY_COUNTS
        or roster.get("split_counts") != SPLIT_COUNTS
        or roster.get("frozen_family_counts") != FROZEN_FAMILY_COUNTS
        or roster.get("critical_tasks") != 12
        or roster.get("leakage_disjoint") is not True
        or not isinstance(roster.get("pins"), Mapping)
        or roster["pins"].get("benchmark_revision") != benchmark_revision
    ):
        reasons.append("paired evaluation roster contract is incomplete or unbound")
    scorecards = evaluation.get("scorecards")
    if not isinstance(scorecards, Mapping) or set(scorecards) != set(VARIANTS):
        reasons.append("paired evaluation scorecard roster is incomplete")
        return False, reasons, None
    reference_signatures: dict[str, tuple[str, str, str]] | None = None
    for variant in VARIANTS:
        item = scorecards[variant]
        if not isinstance(item, Mapping):
            reasons.append(f"scorecard missing variant {variant}")
            continue
        row_reasons, signatures = _recompute_variant(variant, item)
        reasons.extend(row_reasons)
        if reference_signatures is None:
            reference_signatures = signatures
        elif signatures != reference_signatures:
            reasons.append(f"scorecard task roster for {variant} differs across variants")
    return not reasons, reasons, scorecards


def _post(item: Mapping[str, Any]) -> int:
    return item["post_repair"]["successes"]


def _family_post(item: Mapping[str, Any], family: str) -> int:
    return item["families"][family]["post_repair_successes"]


def _passes_thresholds(
    scorecards: Mapping[str, Any], thresholds: Mapping[str, Any]
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    for variant in ("B1", "D1"):
        item = scorecards[variant]
        if _post(item) < thresholds["full_suite_semantic_min"]:
            reasons.append(f"{variant} full-suite semantic score is below threshold")
        for family in FAMILIES:
            if _family_post(item, family) < thresholds["full_family_floor"][family]:
                reasons.append(f"{variant} full-suite family floor failed: {family}")
        if item["critical_failures"] or item["critical"]["failed"] > 0:
            reasons.append(f"{variant} has critical failures")
        if item["hallucinated_identifiers"] > thresholds["hallucinated_identifiers_max"]:
            reasons.append(f"{variant} has invented identifiers accepted")
        if item["wrong_catalog"] > thresholds["wrong_catalog_max"]:
            reasons.append(f"{variant} has silent wrong-catalog selections")
        if item["silent_unsupported"] > thresholds["silent_unsupported_max"]:
            reasons.append(f"{variant} has silent unsupported metadata")
        if item["semantic_refs_valid"] is not True:
            reasons.append(f"{variant} semantic refs are incomplete")
        if item["receipts_sanitized"] is not True:
            reasons.append(f"{variant} receipts are not sanitized")
    d1 = scorecards["D1"]
    frozen = d1["splits"]["frozen"]
    if frozen["post_repair_successes"] < thresholds["frozen_semantic_min"]:
        reasons.append("D1 frozen semantic score is below threshold")
    for family in FAMILIES:
        value = frozen["families"][family]["post_repair_successes"]
        if value < thresholds["frozen_family_floor"][family]:
            reasons.append(f"D1 frozen family floor failed: {family}")
    if _post(d1) < _post(scorecards["B1"]):
        reasons.append("D1 regresses against B1 overall")
    for family in FAMILIES:
        if _family_post(d1, family) < _family_post(scorecards["B1"], family):
            reasons.append(f"D1 regresses against B1 in {family}")
    return not reasons, reasons


def _critical_veto(scorecards: Mapping[str, Any]) -> bool:
    return any(
        scorecards[variant]["critical_failures"] or scorecards[variant]["critical"]["failed"] > 0
        for variant in ("B1", "D1")
    )


def _procedural_rows(scorecards: Mapping[str, Any], *, persistent_only: bool) -> list[Any]:
    result: list[Any] = []
    for row in scorecards["D1"]["failure_rows"]:
        if row["diagnostic_category"] not in DELTA_COMPATIBLE_DIAGNOSTICS:
            continue
        if persistent_only and row["post_repair_success"] is not False:
            continue
        result.append(row)
    return result


def _delta_failures(scorecards: Mapping[str, Any]) -> tuple[int, set[str], bool]:
    rows = _procedural_rows(scorecards, persistent_only=True)
    roots: set[str] = set()
    invalid = False
    for row in rows:
        if row["critical_failures"] or len(row["failure_roots"]) != 1:
            invalid = True
            continue
        roots.add(row["failure_roots"][0])
    return len(rows), roots, invalid


def decide_weight_verdict(
    *,
    benchmark: Mapping[str, Any] | None,
    thresholds: Mapping[str, Any] | None,
    gate_receipts: Mapping[str, Any] | None,
    scorecards: Mapping[str, Any] | None,
    contract_changed: bool = False,
    new_structural_family: bool = False,
    delta_attempted: bool = False,
) -> dict[str, Any]:
    """Emit exactly one policy outcome; never emit training or promotion authority."""

    ready, reasons = _ready_benchmark(benchmark)
    if not ready:
        return _blocked(reasons)
    revision = benchmark["benchmark_revision"]
    ready, reasons = _ratified_thresholds(thresholds, revision)
    if not ready:
        return _blocked(reasons)
    ready, reasons = _green_receipts(gate_receipts, revision)
    if not ready:
        return _blocked(reasons)
    ready, reasons, variant_scorecards = _scorecard_ready(scorecards, revision)
    if not ready or variant_scorecards is None:
        return _blocked(reasons)
    passed, failures = _passes_thresholds(variant_scorecards, thresholds)
    recurring = len(_procedural_rows(variant_scorecards, persistent_only=False)) >= 3
    if passed and not recurring:
        return {
            "schema_version": 1,
            "verdict": NO_RETRAIN,
            "reasons": [],
            "training_authorized": False,
            "promotion_authorized": False,
            "delta_training_authorized": False,
        }
    if _critical_veto(variant_scorecards):
        return _blocked(["critical failure veto prevents a weight verdict"])
    if contract_changed or new_structural_family:
        return {
            **_blocked([]),
            "verdict": FULL_SUCCESSOR_REQUIRED,
            "reasons": ["verified contract or structural family change requires a full successor"],
        }
    if delta_attempted:
        return {
            **_blocked([]),
            "verdict": FULL_SUCCESSOR_REQUIRED,
            "reasons": ["an authorized delta did not close the verified gate"],
        }
    count, roots, invalid = _delta_failures(variant_scorecards)
    if not invalid and count >= 3 and len(roots) >= 2:
        return {
            "schema_version": 1,
            "verdict": DELTA_ELIGIBLE,
            "reasons": ["three compatible persistent failures span two semantic roots"],
            "training_authorized": False,
            "promotion_authorized": False,
            "delta_training_authorized": False,
        }
    if recurring and not failures:
        failures = ["D1 has a recurrent procedural failure"]
    return _blocked(failures or ["verified failures do not satisfy delta eligibility"])


def weight_verdict(**kwargs: Any) -> dict[str, Any]:
    """Alias for :func:`decide_weight_verdict`."""

    return decide_weight_verdict(**kwargs)


compute_weight_verdict = decide_weight_verdict
evaluate_weight_verdict = decide_weight_verdict


__all__ = [
    "BLOCKED",
    "DELTA_ELIGIBLE",
    "FULL_SUCCESSOR_REQUIRED",
    "NO_RETRAIN",
    "OUTCOMES",
    "REQUIRED_UPSTREAM_GATES",
    "VideoWeightVerdictError",
    "compute_weight_verdict",
    "decide_weight_verdict",
    "evaluate_weight_verdict",
    "weight_verdict",
]
