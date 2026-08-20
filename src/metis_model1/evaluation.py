"""Offline, fail-closed scoring contracts for binary benchmark results."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import isfinite
from statistics import NormalDist
from typing import NamedTuple

FAMILIES = frozenset({"F-1", "F-2", "F-3", "F-4", "F-5", "F-6"})
VARIANTS = frozenset({"A", "B", "C", "D"})


class WilsonInterval(NamedTuple):
    """The lower and upper endpoints of a Wilson confidence interval."""

    lower: float
    upper: float


def _require_builtin_int(value: object, name: str) -> int:
    if type(value) is not int:  # bool is an int subclass, but is not a count.
        raise TypeError(f"{name} must be an int, not bool or another type")
    return value


def wilson_interval(successes: int, total: int, confidence: float = 0.95) -> WilsonInterval:
    """Return a two-sided Wilson interval for a binomial proportion.

    Counts are deliberately restricted to builtin integers so that booleans and
    numeric lookalikes cannot silently become denominators or numerators.
    """

    successes = _require_builtin_int(successes, "successes")
    total = _require_builtin_int(total, "total")
    if total <= 0:
        raise ValueError("total must be greater than zero")
    if not 0 <= successes <= total:
        raise ValueError("successes must be between zero and total")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise TypeError("confidence must be a real number")
    confidence = float(confidence)
    if not isfinite(confidence) or not 0 < confidence < 1:
        raise ValueError("confidence must be between zero and one")

    z = NormalDist().inv_cdf(0.5 + confidence / 2.0)
    p = successes / total
    z_squared_over_n = z * z / total
    denominator = 1.0 + z_squared_over_n
    centre = (p + z_squared_over_n / 2.0) / denominator
    half_width = z * (p * (1.0 - p) / total + z * z / (4.0 * total * total)) ** 0.5 / denominator
    return WilsonInterval(max(0.0, centre - half_width), min(1.0, centre + half_width))


@dataclass(frozen=True)
class TaskResult:
    """One independently scored binary task result."""

    task_id: str
    family: str
    variant: str
    success: bool
    critical_failures: tuple[str, ...]
    leakage_group: str

    def __post_init__(self) -> None:
        if type(self.task_id) is not str or not self.task_id.strip():
            raise ValueError("task_id must be a nonempty string")
        if self.family not in FAMILIES:
            raise ValueError("family must be one of F-1 through F-6")
        if self.variant not in VARIANTS:
            raise ValueError("variant must be one of A, B, C, or D")
        if type(self.success) is not bool:
            raise TypeError("success must be a strict bool")
        if type(self.critical_failures) is not list:
            raise TypeError("critical_failures must be a list of strings")
        if any(type(failure) is not str for failure in self.critical_failures):
            raise TypeError("critical_failures must be a list of strings")
        if any(not failure.strip() for failure in self.critical_failures):
            raise ValueError("critical failure names must be nonempty strings")
        if len(self.critical_failures) != len(set(self.critical_failures)):
            raise ValueError("critical_failures must not contain duplicates")
        if self.success and self.critical_failures:
            raise ValueError("a successful task cannot contain a critical failure")
        if type(self.leakage_group) is not str or not self.leakage_group.strip():
            raise ValueError("leakage_group must be a nonempty string")
        object.__setattr__(self, "critical_failures", tuple(self.critical_failures))


BinaryTaskResult = TaskResult


@dataclass(frozen=True)
class FamilyAggregate:
    successes: int
    total: int
    rate: float
    wilson95: WilsonInterval

    @property
    def Wilson95(self) -> WilsonInterval:  # noqa: N802 - contract spelling alias
        return self.wilson95


@dataclass(frozen=True)
class EvaluationAggregate:
    successes: int
    total: int
    rate: float
    wilson95: WilsonInterval
    per_family: dict[str, FamilyAggregate]
    distinct_leakage_groups: int
    critical_failure_union: frozenset[str]
    critical_failure_counts: dict[str, int]
    variant: str

    @property
    def families(self) -> dict[str, FamilyAggregate]:
        return self.per_family

    @property
    def Wilson95(self) -> WilsonInterval:  # noqa: N802 - contract spelling alias
        return self.wilson95


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: list[str]
    aggregate: EvaluationAggregate


def _family_score(successes: int, total: int) -> FamilyAggregate:
    return FamilyAggregate(
        successes=successes,
        total=total,
        rate=successes / total,
        wilson95=wilson_interval(successes, total),
    )


def aggregate_results(results: Iterable[TaskResult]) -> EvaluationAggregate:
    """Aggregate task results, rejecting duplicate IDs and mixed variants."""

    rows = list(results)
    if not rows:
        raise ValueError("at least one task result is required")
    if any(type(row) is not TaskResult for row in rows):
        raise TypeError("results must contain TaskResult instances")

    task_ids = [row.task_id for row in rows]
    if len(task_ids) != len(set(task_ids)):
        raise ValueError("duplicate task_id")
    variants = {row.variant for row in rows}
    if len(variants) != 1:
        raise ValueError("mixed variants are not allowed")

    successes = sum(row.success for row in rows)
    total = len(rows)
    family_successes: Counter[str] = Counter()
    family_totals: Counter[str] = Counter()
    leakage_groups = {row.leakage_group for row in rows}
    failure_counts: Counter[str] = Counter(
        failure for row in rows for failure in row.critical_failures
    )
    for row in rows:
        family_totals[row.family] += 1
        family_successes[row.family] += int(row.success)

    per_family = {
        family: _family_score(family_successes[family], family_totals[family])
        for family in sorted(family_totals)
    }
    return EvaluationAggregate(
        successes=successes,
        total=total,
        rate=successes / total,
        wilson95=wilson_interval(successes, total),
        per_family=per_family,
        distinct_leakage_groups=len(leakage_groups),
        critical_failure_union=frozenset(failure_counts),
        critical_failure_counts=dict(sorted(failure_counts.items())),
        variant=next(iter(variants)),
    )


aggregate = aggregate_results
score_results = aggregate_results


def _target_int(target: Mapping[str, object], key: str, *, positive: bool = False) -> int:
    value = _require_builtin_int(target[key], key)
    if positive and value <= 0:
        raise ValueError(f"{key} must be greater than zero")
    return value


def evaluate_gate(results: Iterable[TaskResult], target: Mapping[str, object]) -> GateResult:
    """Evaluate an exact-denominator binary score against a frozen target."""

    required = {
        "variant",
        "total",
        "family_counts",
        "point_min",
        "confidence",
        "wilson_lower_min",
        "maximum_failures",
        "forbidden_critical_failures",
        "require_zero_unlisted_critical_failures",
    }
    missing = required - set(target)
    if missing:
        raise ValueError(f"target missing keys: {', '.join(sorted(missing))}")
    variant = target["variant"]
    if variant not in VARIANTS:
        raise ValueError("target variant must be one of A, B, C, or D")
    expected_total = _target_int(target, "total", positive=True)
    family_counts = target["family_counts"]
    if not isinstance(family_counts, Mapping):
        raise TypeError("family_counts must be a mapping")
    if set(family_counts) != FAMILIES:
        raise ValueError("family_counts must contain exactly F-1 through F-6")
    expected_families = {
        family: _require_builtin_int(count, f"family_counts[{family}]")
        for family, count in family_counts.items()
    }
    if any(count <= 0 for count in expected_families.values()):
        raise ValueError("family denominator counts must be greater than zero")
    if sum(expected_families.values()) != expected_total:
        raise ValueError("family denominator counts must sum to total")
    point_min = target["point_min"]
    confidence = target["confidence"]
    lower_min = target["wilson_lower_min"]
    if isinstance(point_min, bool) or not isinstance(point_min, (int, float)):
        raise TypeError("point_min must be a real number")
    if isinstance(lower_min, bool) or not isinstance(lower_min, (int, float)):
        raise TypeError("wilson_lower_min must be a real number")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise TypeError("confidence must be a real number")
    point_min = float(point_min)
    confidence = float(confidence)
    lower_min = float(lower_min)
    if not isfinite(point_min) or not isfinite(confidence) or not isfinite(lower_min):
        raise ValueError("point_min, confidence and wilson_lower_min must be finite")
    if not 0 <= point_min <= 1 or not 0 <= lower_min <= 1:
        raise ValueError("point_min and wilson_lower_min must be between zero and one")
    if confidence != 0.95:
        raise ValueError("the Wilson95 gate requires confidence=0.95")
    maximum_failures = _target_int(target, "maximum_failures")
    if maximum_failures >= expected_total:
        raise ValueError("maximum_failures must be smaller than the denominator")
    forbidden = target["forbidden_critical_failures"]
    if not isinstance(forbidden, (list, tuple, set, frozenset)):
        raise TypeError("forbidden_critical_failures must be a collection of strings")
    if any(type(item) is not str for item in forbidden):
        raise TypeError("forbidden_critical_failures must contain only strings")
    if any(not item.strip() for item in forbidden):
        raise ValueError("forbidden critical failure names must be nonempty strings")
    if len(forbidden) != len(set(forbidden)):
        raise ValueError("forbidden_critical_failures must not contain duplicates")
    require_zero_unlisted = target["require_zero_unlisted_critical_failures"]
    if type(require_zero_unlisted) is not bool:
        raise TypeError("require_zero_unlisted_critical_failures must be a strict bool")
    minimum_groups = target.get("minimum_distinct_leakage_groups")
    if minimum_groups is not None:
        minimum_groups = _require_builtin_int(minimum_groups, "minimum_distinct_leakage_groups")
        if minimum_groups <= 0:
            raise ValueError("minimum_distinct_leakage_groups must be greater than zero")
        if minimum_groups > expected_total:
            raise ValueError("minimum_distinct_leakage_groups cannot exceed total")

    summary = aggregate_results(results)
    reasons: list[str] = []
    if summary.variant != variant:
        reasons.append(f"variant mismatch: observed {summary.variant}, expected {variant}")
    if summary.total != expected_total:
        reasons.append(f"total denominator: observed {summary.total}, expected {expected_total}")
    observed_families = {
        family: summary.per_family.get(
            family, FamilyAggregate(0, 0, 0.0, WilsonInterval(0.0, 0.0))
        ).total
        for family in FAMILIES
    }
    for family in sorted(FAMILIES):
        if observed_families[family] != expected_families[family]:
            reasons.append(
                f"{family} denominator: observed {observed_families[family]}, "
                f"expected {expected_families[family]}"
            )
    if summary.rate < point_min:
        reasons.append(f"point rate {summary.rate:.17g} below minimum {point_min:.17g}")
    if summary.wilson95.lower < lower_min:
        reasons.append(f"Wilson lower {summary.wilson95.lower:.17g} below minimum {lower_min:.17g}")
    observed_failures = summary.total - summary.successes
    if observed_failures > maximum_failures:
        reasons.append(f"failure budget: observed {observed_failures}, maximum {maximum_failures}")
    if minimum_groups is not None and summary.distinct_leakage_groups < minimum_groups:
        reasons.append(
            f"distinct leakage groups: observed {summary.distinct_leakage_groups}, "
            f"minimum {minimum_groups}"
        )

    forbidden = set(forbidden)
    observed_critical_failures = set(summary.critical_failure_union)
    for failure in sorted(observed_critical_failures & forbidden):
        reasons.append(
            f"forbidden critical failure {failure!r}: "
            f"count {summary.critical_failure_counts[failure]}"
        )
    if require_zero_unlisted:
        for failure in sorted(observed_critical_failures - forbidden):
            reasons.append(
                f"unlisted critical failure {failure!r}: "
                f"count {summary.critical_failure_counts[failure]}"
            )
    return GateResult(passed=not reasons, reasons=reasons, aggregate=summary)


gate = evaluate_gate
check_gate = evaluate_gate
