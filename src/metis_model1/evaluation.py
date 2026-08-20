"""Offline, fail-closed scoring contracts for binary benchmark results."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from math import isfinite
from statistics import NormalDist
from typing import NamedTuple

from metis_model1.provenance import NonJsonValueError, canonical_json_hash, normalize_json

FAMILIES = frozenset({"F-1", "F-2", "F-3", "F-4", "F-5", "F-6"})
VARIANTS = frozenset({"A", "B", "C", "D"})
_SHA256_PREFIX = "sha256:"


class WilsonInterval(NamedTuple):
    """The lower and upper endpoints of a Wilson confidence interval."""

    lower: float
    upper: float


def _require_builtin_int(value: object, name: str) -> int:
    if type(value) is not int:  # bool is an int subclass, but is not a count.
        raise TypeError(f"{name} must be an int, not bool or another type")
    return value


def _sha256_identity(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.startswith(_SHA256_PREFIX):
        raise ValueError(f"{name} must be a canonical sha256 identity")
    digest = value[len(_SHA256_PREFIX) :]
    if len(digest) != 64 or digest != digest.lower():
        raise ValueError(f"{name} must be a canonical sha256 identity")
    try:
        int(digest, 16)
    except ValueError as error:
        raise ValueError(f"{name} must be a canonical sha256 identity") from error
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
    oracle_result_sha256: str | None = None
    semantic_result_sha256: str | None = None
    end_to_end_success: bool | None = None
    all_applicable_oracles_pass: bool | None = None
    semantic_or_human_oracle_pass: bool | None = None
    patch_safety_pass: bool | None = None
    tool_failure: bool | None = None
    repair_cycles: int | None = None

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
        _sha256_identity(self.leakage_group, "leakage_group")
        for field in (
            "oracle_result_sha256",
            "semantic_result_sha256",
        ):
            value = getattr(self, field)
            if value is not None:
                _sha256_identity(value, field)
        for field in (
            "end_to_end_success",
            "all_applicable_oracles_pass",
            "semantic_or_human_oracle_pass",
            "patch_safety_pass",
            "tool_failure",
        ):
            value = getattr(self, field)
            if value is not None and type(value) is not bool:
                raise TypeError(f"{field} must be a strict bool when supplied")
        if self.end_to_end_success is not None and self.end_to_end_success is not self.success:
            raise ValueError("end_to_end_success must match success")
        if self.repair_cycles is not None and (
            type(self.repair_cycles) is not int or not 0 <= self.repair_cycles <= 2
        ):
            raise ValueError("repair_cycles must be an integer from 0 to 2")
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


_REGISTERED_TARGET_ID = "accuracy-99/end-to-end-v1"
_REGISTERED_TARGET_FAMILIES = {
    "F-1": 100,
    "F-2": 110,
    "F-3": 110,
    "F-4": 110,
    "F-5": 90,
    "F-6": 80,
}
_REGISTERED_FORBIDDEN_CRITICAL_FAILURES = {
    "accepted_invented_identifier",
    "benchmark_leakage",
    "identity_mismatch",
    "prohibited_data_exposure",
    "semantic_wrong_compile_clean_accepted",
    "unauthorized_metis_write",
    "unrelated_destructive_change",
}

# O-003 is not ratified in the current repository.  Once ratified, this is the
# pinned digest loaded from the registered target contract.  Until then the
# evaluator cannot promote, even if a caller supplies a self-consistent
# contract and audit.  Tests must patch this registered anchor to simulate a
# future ratification; callers cannot supply an authority override.
REGISTERED_TARGET_CONTRACT_SHA256: str | None = None


def _validate_target_contract(
    contract: Mapping[str, object],
) -> tuple[Mapping[str, object], str]:
    """Validate the registered target controls and return their canonical hash."""

    if not isinstance(contract, Mapping):
        raise TypeError("target_contract must be a mapping")
    try:
        normalized = normalize_json(contract)
    except (NonJsonValueError, TypeError, ValueError) as error:
        raise ValueError("target_contract must be finite canonical JSON") from error
    if not isinstance(normalized, Mapping):
        raise ValueError("target_contract must be an object")
    exact = {
        "target_id": _REGISTERED_TARGET_ID,
        "status": "ratified",
        "registered_before_candidate_results": True,
        "variant": "D",
        "total": 600,
        "family_counts": _REGISTERED_TARGET_FAMILIES,
        "point_min": 0.99,
        "confidence": 0.95,
        "wilson_lower_min": 0.99,
        "maximum_failures": 1,
        "minimum_distinct_leakage_groups": 563,
        "repair_budget": 2,
    }
    for field, expected in exact.items():
        if normalized.get(field) != expected:
            raise ValueError(f"target_contract does not match registered {field}")
    population = normalized.get("population_attestation")
    if not isinstance(population, Mapping) or population.get("status") != "verified":
        raise ValueError("target_contract lacks a verified population attestation")
    _sha256_identity(
        population.get("evidence_sha256"),
        "population_attestation.evidence_sha256",
    )
    reviewer = population.get("reviewer_session_id")
    if not isinstance(reviewer, str) or not reviewer.strip():
        raise ValueError("population reviewer session must be nonempty")
    forbidden = normalized.get("forbidden_critical_failures")
    if (
        not isinstance(forbidden, list)
        or len(forbidden) != len(_REGISTERED_FORBIDDEN_CRITICAL_FAILURES)
        or any(type(item) is not str or not item.strip() for item in forbidden)
        or len(set(forbidden)) != len(forbidden)
        or set(forbidden) != _REGISTERED_FORBIDDEN_CRITICAL_FAILURES
    ):
        raise ValueError("target_contract forbidden critical-failure roster is not registered")
    if normalized.get("require_zero_unlisted_critical_failures") is not True:
        raise ValueError("target_contract must require zero unlisted critical failures")
    return normalized, _SHA256_PREFIX + canonical_json_hash(normalized)


def _validate_independence_audit(
    audit: Mapping[str, object],
    *,
    expected_total: int,
    expected_families: Mapping[str, int],
    minimum_groups: int,
) -> tuple[dict[str, str], Mapping[str, object], dict[str, Mapping[str, object]]]:
    """Validate the immutable, self-consistent output of ``audit_independence``.

    This intentionally duplicates only the audit's structural arithmetic and
    component hash check.  Importing ``independence`` here would create a
    cycle because that module uses ``wilson_interval`` from this module.
    """

    if not isinstance(audit, Mapping):
        raise TypeError("independence_audit must be a mapping")
    try:
        normalize_json(audit)
    except (NonJsonValueError, TypeError, ValueError) as error:
        raise ValueError("independence_audit must be finite canonical JSON") from error
    required = {
        "schema_version",
        "counts",
        "components",
        "counts_by_split",
        "counts_by_family",
        "cross_split_violations",
        "benchmark_root_violations",
        "frozen_evidence",
        "frozen_evidence_sha256",
        "observed",
        "verdict",
    }
    if set(audit) != required:
        raise ValueError("independence_audit has an unexpected shape")
    if audit["schema_version"] != 1:
        raise ValueError("independence_audit schema_version must be 1")
    if audit["cross_split_violations"] != [] or audit["benchmark_root_violations"] != []:
        raise ValueError("independence_audit contains violations")

    components = audit["components"]
    if not isinstance(components, list):
        raise TypeError("independence_audit components must be a list")
    task_to_group: dict[str, str] = {}
    frozen_task_ids: set[str] = set()
    groups: set[str] = set()
    for component in components:
        if not isinstance(component, Mapping):
            raise TypeError("independence component must be an object")
        if set(component) != {
            "leakage_group",
            "task_ids",
            "roots",
            "edges",
            "splits",
            "families",
            "task_families",
        }:
            raise ValueError("independence component has an unexpected shape")
        group = _sha256_identity(component["leakage_group"], "component leakage_group")
        if group in groups:
            raise ValueError("independence components must have unique groups")
        groups.add(group)
        task_ids = component["task_ids"]
        roots = component["roots"]
        edges = component["edges"]
        splits = component["splits"]
        families = component["families"]
        task_families = component["task_families"]
        if (
            not isinstance(task_ids, list)
            or not task_ids
            or task_ids != sorted(task_ids)
            or len(task_ids) != len(set(task_ids))
            or any(type(task_id) is not str or not task_id for task_id in task_ids)
        ):
            raise ValueError("independence component task_ids are not canonical")
        if (
            not isinstance(roots, list)
            or not roots
            or roots != sorted(roots)
            or len(roots) != len(set(roots))
            or any(_sha256_identity(root, "component root") != root for root in roots)
        ):
            raise ValueError("independence component roots are not canonical")
        if (
            not isinstance(edges, list)
            or edges != sorted(edges)
            or len(edges) != len({tuple(edge) for edge in edges if isinstance(edge, list)})
        ):
            raise ValueError("independence component edges are not canonical")
        for edge in edges:
            if (
                not isinstance(edge, list)
                or len(edge) != 2
                or any(type(value) is not str or not value for value in edge)
            ):
                raise ValueError("independence component edges are malformed")
        expected_group = _SHA256_PREFIX + canonical_json_hash(
            {"schema_version": 1, "roots": roots, "edges": edges}
        )
        if group != expected_group:
            raise ValueError("independence component leakage_group hash does not match its content")
        if (
            not isinstance(splits, list)
            or not splits
            or splits != sorted(splits)
            or len(splits) != len(set(splits))
            or any(split not in {"train", "dev", "internal_test", "frozen"} for split in splits)
        ):
            raise ValueError("independence component splits are malformed")
        if len(splits) != 1:
            raise ValueError("independence audit has a cross-split component")
        if (
            not isinstance(families, list)
            or not families
            or families != sorted(families)
            or len(families) != len(set(families))
            or any(family not in FAMILIES for family in families)
        ):
            raise ValueError("independence component families are malformed")
        if (
            not isinstance(task_families, Mapping)
            or set(task_families) != set(task_ids)
            or any(family not in FAMILIES for family in task_families.values())
            or sorted(set(task_families.values())) != families
        ):
            raise ValueError("independence component task_families are malformed")
        for task_id in task_ids:
            if task_id in task_to_group:
                raise ValueError("independence task IDs must be unique across components")
            task_to_group[task_id] = group
            if splits == ["frozen"]:
                frozen_task_ids.add(task_id)

    counts = audit["counts"]
    if not isinstance(counts, Mapping) or set(counts) != {
        "in",
        "out",
        "distinct",
        "gaps",
        "distinct_leakage_groups",
        "frozen_distinct_leakage_groups",
    }:
        raise ValueError("independence audit counts are malformed")
    count_values = {key: _require_builtin_int(counts[key], f"counts.{key}") for key in counts}
    if count_values["in"] != count_values["out"] or count_values["out"] != count_values["distinct"]:
        raise ValueError("independence audit counts disagree")
    if count_values["gaps"] != 0 or count_values["out"] != len(task_to_group):
        raise ValueError("independence audit task denominator is inconsistent")
    if count_values["distinct_leakage_groups"] != len(components):
        raise ValueError("independence audit group denominator is inconsistent")
    frozen_groups = {
        component["leakage_group"] for component in components if component["splits"] == ["frozen"]
    }
    if count_values["frozen_distinct_leakage_groups"] != len(frozen_groups):
        raise ValueError("independence audit frozen group denominator is inconsistent")
    if len(frozen_task_ids) != expected_total:
        raise ValueError("independence audit frozen task denominator does not match target")
    counts_by_split = audit["counts_by_split"]
    if not isinstance(counts_by_split, Mapping) or set(counts_by_split) != {
        "train",
        "dev",
        "internal_test",
        "frozen",
    }:
        raise ValueError("independence audit split counts are malformed")
    for split in counts_by_split:
        split_components = [component for component in components if component["splits"] == [split]]
        split_counts = counts_by_split[split]
        if (
            not isinstance(split_counts, Mapping)
            or set(split_counts) != {"tasks", "distinct_groups"}
            or split_counts["tasks"]
            != sum(len(component["task_ids"]) for component in split_components)
            or split_counts["distinct_groups"] != len(split_components)
        ):
            raise ValueError("independence audit split counts are inconsistent")

    counts_by_family = audit["counts_by_family"]
    if not isinstance(counts_by_family, Mapping) or set(counts_by_family) != FAMILIES:
        raise ValueError("independence audit family counts are malformed")
    for family in FAMILIES:
        family_components = [
            component for component in components if family in component["families"]
        ]
        family_tasks = sum(
            sum(task_family == family for task_family in component["task_families"].values())
            for component in family_components
        )
        family_counts = counts_by_family[family]
        if (
            not isinstance(family_counts, Mapping)
            or set(family_counts) != {"tasks", "distinct_groups"}
            or family_counts["tasks"] != family_tasks
            or family_counts["distinct_groups"] != len(family_components)
        ):
            raise ValueError("independence audit family counts are inconsistent")

    derived_frozen_family_counts = {
        family: sum(
            task_family == family
            for component in components
            if component["splits"] == ["frozen"]
            for task_family in component["task_families"].values()
        )
        for family in FAMILIES
    }
    if derived_frozen_family_counts != dict(expected_families):
        raise ValueError("independence audit frozen component family counts do not match target")

    frozen_evidence = audit["frozen_evidence"]
    if not isinstance(frozen_evidence, list):
        raise TypeError("independence audit frozen_evidence must be a list")
    frozen_evidence_sha256 = _sha256_identity(
        audit["frozen_evidence_sha256"],
        "frozen_evidence_sha256",
    )
    expected_frozen_evidence_sha256 = _SHA256_PREFIX + canonical_json_hash(frozen_evidence)
    if frozen_evidence_sha256 != expected_frozen_evidence_sha256:
        raise ValueError("independence audit frozen evidence hash does not match its content")
    evidence_by_id: dict[str, Mapping[str, object]] = {}
    for evidence in frozen_evidence:
        if not isinstance(evidence, Mapping):
            raise TypeError("independence frozen evidence entries must be objects")
        if set(evidence) != {
            "task_id",
            "family",
            "success",
            "critical_failures",
            "end_to_end_success",
            "all_applicable_oracles_pass",
            "semantic_or_human_oracle_pass",
            "patch_safety_pass",
            "tool_failure",
            "repair_cycles",
            "oracle_result_sha256",
            "semantic_result_sha256",
        }:
            raise ValueError("independence frozen evidence has an unexpected shape")
        task_id = evidence["task_id"]
        if type(task_id) is not str or not task_id.strip() or task_id != task_id.strip():
            raise ValueError("independence frozen evidence task_id is not canonical")
        if task_id in evidence_by_id:
            raise ValueError("independence frozen evidence task IDs must be unique")
        family = evidence["family"]
        if family not in FAMILIES:
            raise ValueError("independence frozen evidence family is malformed")
        success = evidence["success"]
        if type(success) is not bool:
            raise TypeError("independence frozen evidence success must be a strict bool")
        critical_failures = evidence["critical_failures"]
        if (
            not isinstance(critical_failures, list)
            or any(type(failure) is not str or not failure.strip() for failure in critical_failures)
            or len(critical_failures) != len(set(critical_failures))
        ):
            raise ValueError("independence frozen evidence critical_failures are malformed")
        if success and critical_failures:
            raise ValueError("a successful frozen evidence row cannot have critical failures")
        if type(evidence["end_to_end_success"]) is not bool:
            raise TypeError("independence frozen evidence end_to_end_success must be a strict bool")
        if evidence["end_to_end_success"] is not success:
            raise ValueError("independence frozen evidence contradicts success")
        for field in (
            "all_applicable_oracles_pass",
            "semantic_or_human_oracle_pass",
            "patch_safety_pass",
            "tool_failure",
        ):
            if type(evidence[field]) is not bool:
                raise TypeError(f"independence frozen evidence {field} must be a strict bool")
        cycles = evidence["repair_cycles"]
        if type(cycles) is not int or not 0 <= cycles <= 2:
            raise ValueError("independence frozen evidence repair_cycles must be from 0 to 2")
        _sha256_identity(evidence["oracle_result_sha256"], "oracle_result_sha256")
        _sha256_identity(evidence["semantic_result_sha256"], "semantic_result_sha256")
        if task_id not in frozen_task_ids:
            raise ValueError("independence frozen evidence contains a non-frozen task")
        component_family = next(
            component["task_families"][task_id]
            for component in components
            if task_id in component["task_families"]
        )
        if family != component_family:
            raise ValueError("independence frozen evidence family does not match component")
        evidence_by_id[task_id] = evidence
    evidence_ids = list(evidence_by_id)
    if evidence_ids != sorted(evidence_ids):
        raise ValueError("independence frozen evidence is not sorted by task_id")
    if set(evidence_by_id) != frozen_task_ids:
        raise ValueError("independence frozen evidence does not cover the frozen roster")

    evidence_total = len(evidence_by_id)
    evidence_successes = sum(evidence["success"] for evidence in evidence_by_id.values())
    evidence_wilson_lower = wilson_interval(evidence_successes, evidence_total).lower
    evidence_critical_count = sum(
        len(evidence["critical_failures"]) for evidence in evidence_by_id.values()
    )
    evidence_semantic_contradictions = sum(
        evidence["success"]
        and not (
            evidence["all_applicable_oracles_pass"]
            and evidence["semantic_or_human_oracle_pass"]
            and evidence["patch_safety_pass"]
            and not evidence["tool_failure"]
        )
        for evidence in evidence_by_id.values()
    )

    observed = audit["observed"]
    if not isinstance(observed, Mapping):
        raise TypeError("independence audit observed evidence must be an object")
    expected_observed_fields = {
        "successes",
        "total",
        "wilson_lower",
        "point_min",
        "confidence",
        "wilson_lower_min",
        "minimum_distinct_leakage_groups",
        "required_frozen_tasks",
        "required_family_counts",
        "frozen_family_counts",
        "family_counts_match",
        "critical_evidence_complete",
        "critical_failure_count",
        "semantic_evidence_complete",
        "semantic_evidence_contradictions",
        "target_contract_bound",
        "target_contract_sha256",
    }
    if set(observed) != expected_observed_fields:
        raise ValueError("independence audit observed evidence has an unexpected shape")
    if observed["minimum_distinct_leakage_groups"] != minimum_groups:
        raise ValueError("independence audit minimum group threshold does not match target")
    if observed["required_frozen_tasks"] != expected_total:
        raise ValueError("independence audit required frozen denominator does not match target")
    family_counts = observed["frozen_family_counts"]
    if not isinstance(family_counts, Mapping) or set(family_counts) != FAMILIES:
        raise ValueError("independence audit frozen family counts are malformed")
    observed_frozen_family_counts = {
        family: _require_builtin_int(family_counts[family], f"frozen_family_counts.{family}")
        for family in FAMILIES
    }
    if observed_frozen_family_counts != derived_frozen_family_counts:
        raise ValueError("independence audit observed frozen family counts do not match components")
    if observed_frozen_family_counts != dict(expected_families):
        raise ValueError("independence audit frozen family counts do not match target")
    if observed["required_family_counts"] != dict(expected_families):
        raise ValueError("independence audit required family counts do not match target")
    family_counts_match = derived_frozen_family_counts == dict(expected_families)
    if observed["family_counts_match"] is not family_counts_match:
        raise ValueError("independence audit frozen family counts are invalid")
    for field in (
        "target_contract_bound",
        "critical_evidence_complete",
        "semantic_evidence_complete",
        "family_counts_match",
    ):
        if type(observed[field]) is not bool:
            raise ValueError(f"independence audit observed {field} must be a strict bool")
    target_contract_sha256 = observed["target_contract_sha256"]
    if target_contract_sha256 is not None:
        _sha256_identity(target_contract_sha256, "target_contract_sha256")

    observed_successes = _require_builtin_int(observed["successes"], "observed.successes")
    observed_total = _require_builtin_int(observed["total"], "observed.total")
    if observed_successes != evidence_successes:
        raise ValueError("independence audit observed successes do not match frozen evidence")
    if observed_total != evidence_total:
        raise ValueError("independence audit observed total does not match frozen evidence")
    observed_wilson_lower = observed["wilson_lower"]
    if (
        isinstance(observed_wilson_lower, bool)
        or not isinstance(observed_wilson_lower, (int, float))
        or not isfinite(float(observed_wilson_lower))
        or float(observed_wilson_lower) != evidence_wilson_lower
    ):
        raise ValueError(
            "independence audit observed Wilson evidence does not match frozen evidence"
        )
    if observed["critical_evidence_complete"] is not True:
        raise ValueError("independence audit critical evidence is incomplete")
    observed_critical_count = _require_builtin_int(
        observed["critical_failure_count"],
        "observed.critical_failure_count",
    )
    if observed_critical_count != evidence_critical_count:
        raise ValueError(
            "independence audit observed critical evidence does not match frozen evidence"
        )
    if observed["semantic_evidence_complete"] is not True:
        raise ValueError("independence audit semantic evidence is incomplete")
    observed_semantic_contradictions = _require_builtin_int(
        observed["semantic_evidence_contradictions"],
        "observed.semantic_evidence_contradictions",
    )
    if observed_semantic_contradictions != evidence_semantic_contradictions:
        raise ValueError(
            "independence audit observed semantic evidence does not match frozen evidence"
        )

    score_pass = evidence_successes / evidence_total >= 0.99 and evidence_wilson_lower >= 0.99
    operational_score_pass = (
        score_pass and evidence_critical_count == 0 and evidence_semantic_contradictions == 0
    )
    target_contract_pass = (
        operational_score_pass
        and observed["target_contract_bound"] is True
        and len(frozen_groups) >= minimum_groups
        and family_counts_match
    )
    expected_verdict = (
        "TARGET_99_CONFIRMED"
        if target_contract_pass
        else "OBSERVED_99_ONLY"
        if operational_score_pass
        else "PRODUCT_EVIDENCE"
    )
    if audit["verdict"] != expected_verdict:
        raise ValueError(
            f"independence audit verdict does not match frozen evidence: "
            f"expected {expected_verdict}, got {audit['verdict']!r}"
        )
    return (
        {task_id: task_to_group[task_id] for task_id in frozen_task_ids},
        observed,
        evidence_by_id,
    )


def evaluate_gate(
    results: Iterable[TaskResult],
    target: Mapping[str, object],
    *,
    independence_audit: Mapping[str, object] | None = None,
    target_contract: Mapping[str, object] | None = None,
) -> GateResult:
    """Evaluate a score only when it is bound to an independence audit.

    ``independence_audit`` must be the canonical output of
    :func:`audit_independence` (validated locally to avoid a circular import).
    The separately supplied ``target_contract`` is required for a promotion
    verdict; its registered controls are hashed and matched to the audit and
    the repository trust anchor.  The repository anchor is deliberately unset
    until ratification, so a caller cannot self-authorize a digest.
    Missing or contradictory evidence is represented as a failed gate.
    """

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
        "minimum_distinct_leakage_groups",
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
    minimum_groups = _require_builtin_int(
        target["minimum_distinct_leakage_groups"], "minimum_distinct_leakage_groups"
    )
    if minimum_groups <= 0:
        raise ValueError("minimum_distinct_leakage_groups must be greater than zero")
    if minimum_groups > expected_total:
        raise ValueError("minimum_distinct_leakage_groups cannot exceed total")

    rows = list(results)
    summary = aggregate_results(rows)
    reasons: list[str] = []
    audit_groups: dict[str, str] = {}
    audit_observed: Mapping[str, object] | None = None
    audit_evidence: dict[str, Mapping[str, object]] = {}
    contract_values: Mapping[str, object] | None = None
    contract_sha256: str | None = None
    if target_contract is None:
        reasons.append("ratified target contract evidence is required")
    else:
        try:
            contract_values, contract_sha256 = _validate_target_contract(target_contract)
        except (TypeError, ValueError) as error:
            reasons.append(f"target contract evidence: {error}")
        else:
            for field in (
                "variant",
                "total",
                "family_counts",
                "point_min",
                "confidence",
                "wilson_lower_min",
                "maximum_failures",
                "minimum_distinct_leakage_groups",
                "forbidden_critical_failures",
                "require_zero_unlisted_critical_failures",
            ):
                if target.get(field) != contract_values.get(field):
                    reasons.append(f"target control mismatch: {field}")
    if independence_audit is None:
        reasons.append("authoritative independence audit evidence is required")
    else:
        audit_total = expected_total
        audit_families = expected_families
        audit_minimum_groups = minimum_groups
        if contract_values is not None:
            audit_total = _require_builtin_int(contract_values["total"], "target_contract.total")
            audit_families = {
                family: _require_builtin_int(
                    contract_values["family_counts"][family],
                    f"target_contract.family_counts[{family}]",
                )
                for family in FAMILIES
            }
            audit_minimum_groups = _require_builtin_int(
                contract_values["minimum_distinct_leakage_groups"],
                "target_contract.minimum_distinct_leakage_groups",
            )
        audit_groups, audit_observed, audit_evidence = _validate_independence_audit(
            independence_audit,
            expected_total=audit_total,
            expected_families=audit_families,
            minimum_groups=audit_minimum_groups,
        )
        result_ids = {row.task_id for row in rows}
        if result_ids != set(audit_groups):
            reasons.append("result task IDs do not match the frozen independence roster")
        for row in rows:
            expected_group = audit_groups.get(row.task_id)
            if expected_group is not None and row.leakage_group != expected_group:
                reasons.append(
                    f"task {row.task_id!r} leakage group is not bound to its frozen component"
                )
            evidence = audit_evidence.get(row.task_id)
            if evidence is None:
                reasons.append(f"task {row.task_id!r} has no frozen evidence row")
                continue
            if row.family != evidence["family"]:
                reasons.append(f"task {row.task_id!r} family is not bound to frozen evidence")
            if row.success is not evidence["success"]:
                reasons.append(f"task {row.task_id!r} success is not bound to frozen evidence")
            if list(row.critical_failures) != evidence["critical_failures"]:
                reasons.append(
                    f"task {row.task_id!r} critical failures are not bound to frozen evidence"
                )
            oracle_fields = (
                "oracle_result_sha256",
                "semantic_result_sha256",
                "end_to_end_success",
                "all_applicable_oracles_pass",
                "semantic_or_human_oracle_pass",
                "patch_safety_pass",
                "tool_failure",
                "repair_cycles",
            )
            if any(getattr(row, field) is None for field in oracle_fields):
                reasons.append(f"task {row.task_id!r} oracle evidence is incomplete for promotion")
            else:
                for field in oracle_fields:
                    if getattr(row, field) != evidence[field]:
                        reasons.append(
                            f"task {row.task_id!r} {field} is not bound to frozen evidence"
                        )
        if audit_observed.get("target_contract_bound") is not True:
            reasons.append("independence audit is not bound to a ratified target contract")
        trusted_digest = REGISTERED_TARGET_CONTRACT_SHA256
        if trusted_digest is not None:
            _sha256_identity(trusted_digest, "REGISTERED_TARGET_CONTRACT_SHA256")
        if trusted_digest is None:
            reasons.append("trusted target contract digest authority is unset")
        if contract_sha256 is None:
            reasons.append("independence audit target contract cannot be verified")
        elif trusted_digest is not None and contract_sha256 != trusted_digest:
            reasons.append("target contract does not match trusted authority digest")
        elif audit_observed.get("target_contract_sha256") != trusted_digest:
            reasons.append("independence audit target contract hash mismatch")
        if independence_audit.get("verdict") != "TARGET_99_CONFIRMED":
            reasons.append(
                f"independence audit verdict is not TARGET_99_CONFIRMED: "
                f"{independence_audit.get('verdict')!r}"
            )
        registered_controls = contract_values or target
        for field in (
            "point_min",
            "confidence",
            "wilson_lower_min",
            "minimum_distinct_leakage_groups",
            "total",
        ):
            if audit_observed.get(field) != registered_controls.get(field):
                reasons.append(f"independence audit control mismatch: {field}")
        observed_successes = audit_observed.get("successes")
        observed_total = audit_observed.get("total")
        observed_wilson_lower = audit_observed.get("wilson_lower")
        if (
            type(observed_successes) is not int
            or type(observed_total) is not int
            or observed_successes != summary.successes
            or observed_total != summary.total
        ):
            reasons.append("independence audit score evidence does not match TaskResults")
        if (
            not isinstance(observed_wilson_lower, (int, float))
            or isinstance(observed_wilson_lower, bool)
            or not isfinite(float(observed_wilson_lower))
            or float(observed_wilson_lower) != summary.wilson95.lower
        ):
            reasons.append("independence audit Wilson evidence does not match TaskResults")
        expected_critical_count = sum(len(row.critical_failures) for row in rows)
        if audit_observed.get("critical_evidence_complete") is not True:
            reasons.append("independence audit critical evidence is incomplete")
        if audit_observed.get("critical_failure_count") != expected_critical_count:
            reasons.append("independence audit critical evidence does not match TaskResults")
        if audit_observed.get("critical_failure_count") != 0:
            reasons.append("independence audit critical_failure_count must be zero")
        if audit_observed.get("semantic_evidence_complete") is not True:
            reasons.append("independence audit semantic evidence is incomplete")
        if audit_observed.get("semantic_evidence_contradictions") != 0:
            reasons.append("independence audit semantic evidence contradicts TaskResults")
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
