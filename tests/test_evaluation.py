from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from metis_model1.evaluation import TaskResult, aggregate_results, evaluate_gate, wilson_interval


def _rows(
    total: int = 600,
    successes: int = 600,
    *,
    leakage_groups: int | None = None,
    critical_failures: dict[int, list[str]] | None = None,
) -> list[TaskResult]:
    counts = [100, 110, 110, 110, 90, 80]
    groups = leakage_groups or total
    rows: list[TaskResult] = []
    index = 0
    for family_number, family_total in enumerate(counts, start=1):
        for _ in range(family_total):
            rows.append(
                TaskResult(
                    task_id=f"task-{index}",
                    family=f"F-{family_number}",
                    variant="D",
                    success=index < successes,
                    critical_failures=(critical_failures or {}).get(index, []),
                    leakage_group=f"group-{index % groups}",
                )
            )
            index += 1
    assert index == total
    return rows


def _target(**overrides: object) -> dict[str, object]:
    target: dict[str, object] = {
        "variant": "D",
        "total": 600,
        "family_counts": {
            "F-1": 100,
            "F-2": 110,
            "F-3": 110,
            "F-4": 110,
            "F-5": 90,
            "F-6": 80,
        },
        "point_min": 0.99,
        "confidence": 0.95,
        "wilson_lower_min": 0.99,
        "maximum_failures": 1,
        "forbidden_critical_failures": ["semantic", "invented-symbol"],
        "require_zero_unlisted_critical_failures": True,
        "minimum_distinct_leakage_groups": 563,
    }
    target.update(overrides)
    return target


@pytest.mark.parametrize("successes", [600, 599])
def test_wilson_and_gate_pass_with_at_most_one_failure(successes: int) -> None:
    result = evaluate_gate(_rows(successes=successes), _target())
    assert result.passed
    assert result.reasons == []
    assert result.aggregate.wilson95.upper <= 1.0


@pytest.mark.parametrize("successes", [598, 594])
def test_point_or_wilson_gate_rejects_insufficient_600_task_score(successes: int) -> None:
    result = evaluate_gate(_rows(successes=successes), _target())
    assert not result.passed
    assert any("Wilson lower" in reason for reason in result.reasons)


def test_all_success_minimum_sample_size_for_wilson_99_is_381() -> None:
    assert wilson_interval(380, 380).lower < 0.99
    assert wilson_interval(381, 381).lower >= 0.99


def test_one_failure_minimum_sample_size_for_wilson_99_is_563() -> None:
    assert wilson_interval(561, 562).lower < 0.99
    assert wilson_interval(562, 563).lower >= 0.99


def test_aggregate_reports_exact_fields_and_family_breakdown() -> None:
    summary = aggregate_results(_rows(leakage_groups=600))
    assert (summary.successes, summary.total, summary.rate) == (600, 600, 1.0)
    assert summary.distinct_leakage_groups == 600
    assert summary.critical_failure_union == frozenset()
    assert summary.critical_failure_counts == {}
    assert {family: item.total for family, item in summary.per_family.items()} == {
        "F-1": 100,
        "F-2": 110,
        "F-3": 110,
        "F-4": 110,
        "F-5": 90,
        "F-6": 80,
    }


def test_minimum_distinct_leakage_groups_is_a_gate() -> None:
    assert not evaluate_gate(
        _rows(leakage_groups=562), _target(minimum_distinct_leakage_groups=563)
    ).passed
    assert evaluate_gate(
        _rows(leakage_groups=563), _target(minimum_distinct_leakage_groups=563)
    ).passed


def test_duplicate_task_and_mixed_variant_are_rejected() -> None:
    rows = _rows()
    original = rows[0]
    rows[0] = TaskResult(
        rows[1].task_id,
        original.family,
        original.variant,
        original.success,
        list(original.critical_failures),
        original.leakage_group,
    )
    with pytest.raises(ValueError, match="duplicate"):
        aggregate_results(rows)

    rows = _rows()
    original = rows[1]
    rows[1] = TaskResult(
        original.task_id,
        original.family,
        "A",
        original.success,
        list(original.critical_failures),
        original.leakage_group,
    )
    with pytest.raises(ValueError, match="mixed variants"):
        aggregate_results(rows)


def test_aggregate_rejects_task_result_subclasses() -> None:
    class DerivedTaskResult(TaskResult):
        pass

    row = DerivedTaskResult("task", "F-1", "D", True, [], "group")
    with pytest.raises(TypeError, match="TaskResult instances"):
        aggregate_results([row])


def test_task_result_is_immutable_after_validation() -> None:
    row = TaskResult("task", "F-1", "D", True, [], "group")
    assert row.critical_failures == ()
    with pytest.raises(FrozenInstanceError):
        row.task_id = "changed"  # type: ignore[misc]


def test_wrong_family_denominator_is_rejected() -> None:
    result = evaluate_gate(
        _rows(),
        _target(
            family_counts={
                "F-1": 99,
                "F-2": 111,
                "F-3": 110,
                "F-4": 110,
                "F-5": 90,
                "F-6": 80,
            }
        ),
    )
    assert not result.passed
    assert any("F-1 denominator" in reason for reason in result.reasons)
    assert any("F-2 denominator" in reason for reason in result.reasons)


def test_critical_failure_is_rejected() -> None:
    rows = _rows(successes=599)
    failed = rows[599]
    rows[599] = TaskResult(
        failed.task_id,
        failed.family,
        failed.variant,
        False,
        ["semantic"],
        failed.leakage_group,
    )
    result = evaluate_gate(
        rows,
        _target(),
    )
    assert not result.passed
    assert any("forbidden critical failure" in reason for reason in result.reasons)


def test_unlisted_critical_failure_is_rejected_by_zero_unlisted_gate() -> None:
    rows = _rows(successes=599, critical_failures={599: ["unauthorized_metis_write"]})

    result = evaluate_gate(rows, _target())

    assert not result.passed
    assert result.reasons == ["unlisted critical failure 'unauthorized_metis_write': count 1"]


def test_invalid_critical_failure_names_are_rejected() -> None:
    with pytest.raises(ValueError):
        TaskResult("t", "F-1", "D", True, [""], "g")
    with pytest.raises(ValueError):
        TaskResult("t", "F-1", "D", True, ["semantic", "semantic"], "g")
    with pytest.raises(ValueError, match="successful task"):
        TaskResult("t", "F-1", "D", True, ["semantic"], "g")


def test_gate_rejects_nonfinite_thresholds_and_family_count_sum_drift() -> None:
    with pytest.raises(ValueError, match="finite"):
        evaluate_gate(_rows(), _target(point_min=float("nan")))
    with pytest.raises(ValueError, match="sum to total"):
        evaluate_gate(
            _rows(),
            _target(
                family_counts={
                    "F-1": 99,
                    "F-2": 110,
                    "F-3": 110,
                    "F-4": 110,
                    "F-5": 90,
                    "F-6": 80,
                }
            ),
        )
    with pytest.raises(ValueError, match="cannot exceed total"):
        evaluate_gate(_rows(), _target(minimum_distinct_leakage_groups=601))
    with pytest.raises(ValueError, match="confidence=0.95"):
        evaluate_gate(_rows(), _target(confidence=0.9))


def test_explicit_failure_budget_is_enforced() -> None:
    result = evaluate_gate(_rows(successes=599), _target(maximum_failures=0))
    assert not result.passed
    assert any("failure budget" in reason for reason in result.reasons)


def test_forbidden_failure_names_must_be_nonempty_and_unique() -> None:
    with pytest.raises(ValueError):
        evaluate_gate(_rows(), _target(forbidden_critical_failures=[" "]))
    with pytest.raises(ValueError):
        evaluate_gate(_rows(), _target(forbidden_critical_failures=["semantic", "semantic"]))


@pytest.mark.parametrize(
    ("successes", "total"),
    [(True, 1), (1, True), (1.0, 2)],
)
def test_wilson_rejects_bool_as_int_inputs(successes: object, total: object) -> None:
    with pytest.raises(TypeError):
        wilson_interval(successes, total)  # type: ignore[arg-type]


def test_task_result_rejects_non_strict_success_and_invalid_fields() -> None:
    with pytest.raises(TypeError, match="strict bool"):
        TaskResult("t", "F-1", "D", 1, [], "g")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        TaskResult("", "F-1", "D", True, [], "g")
    with pytest.raises(TypeError):
        TaskResult("t", "F-1", "D", True, ("failure",), "g")  # type: ignore[arg-type]
