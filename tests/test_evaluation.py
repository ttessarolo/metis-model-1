from __future__ import annotations

import copy
from dataclasses import FrozenInstanceError

import pytest

import metis_model1.evaluation as evaluation_module
from metis_model1.evaluation import TaskResult, aggregate_results, evaluate_gate, wilson_interval
from metis_model1.independence import audit_independence
from metis_model1.provenance import canonical_json_hash


def _group(label: object) -> str:
    return "sha256:" + canonical_json_hash({"group": label})


def _ratified_contract() -> dict[str, object]:
    return {
        "target_id": "accuracy-99/end-to-end-v1",
        "status": "ratified",
        "registered_before_candidate_results": True,
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
        "minimum_distinct_leakage_groups": 563,
        "repair_budget": 2,
        "forbidden_critical_failures": [
            "accepted_invented_identifier",
            "benchmark_leakage",
            "identity_mismatch",
            "prohibited_data_exposure",
            "semantic_wrong_compile_clean_accepted",
            "unauthorized_metis_write",
            "unrelated_destructive_change",
        ],
        "require_zero_unlisted_critical_failures": True,
        "population_attestation": {
            "status": "verified",
            "evidence_sha256": _group("population-evidence"),
            "reviewer_session_id": "independent-reviewer-1",
        },
    }


def _contract_digest(contract: dict[str, object]) -> str:
    return "sha256:" + canonical_json_hash(contract)


@pytest.fixture(autouse=True)
def _ratified_anchor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        evaluation_module,
        "REGISTERED_TARGET_CONTRACT_SHA256",
        _contract_digest(_ratified_contract()),
    )


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
                    leakage_group=_group(index % groups),
                )
            )
            index += 1
    assert index == total
    return rows


_DEFAULT_CONTRACT = object()


def _audit_for(
    rows: list[TaskResult],
    *,
    target_contract: object = _DEFAULT_CONTRACT,
) -> tuple[list[TaskResult], dict[str, object]]:
    records: list[dict[str, object]] = []
    for index, row in enumerate(rows):
        material = {
            "kind": "test_fixture",
            "origin": "public_synthetic",
            "authoring_session_id": f"author-{index}",
            "content_sha256": _group(f"content-{index}"),
        }
        root = "sha256:" + canonical_json_hash(material)
        records.append(
            {
                "task_id": row.task_id,
                "family": row.family,
                "split": "frozen",
                "provenance": {
                    "roots": [root],
                    "root_evidence": [material],
                    "generator_id": f"generator-{row.leakage_group}",
                    "generator_version": "1",
                },
                "success": row.success,
                "critical_failures": list(row.critical_failures),
                "oracle_evidence": {
                    "end_to_end_success": row.success,
                    "all_applicable_oracles_pass": row.success,
                    "semantic_or_human_oracle_pass": row.success,
                    "patch_safety_pass": row.success,
                    "tool_failure": False,
                    "repair_cycles": 0,
                    "oracle_result_sha256": _group(f"oracle-{index}"),
                    "semantic_result_sha256": _group(f"semantic-{index}"),
                },
            }
        )
    # The fixture deliberately uses the same generator identity as the result
    # group, so the audit's canonical component IDs are authoritative.
    audit_contract = (
        _ratified_contract() if target_contract is _DEFAULT_CONTRACT else target_contract
    )
    audit = audit_independence(records, target_contract=audit_contract)  # type: ignore[arg-type]
    groups_by_task = {
        task_id: component["leakage_group"]
        for component in audit["components"]
        for task_id in component["task_ids"]
    }
    evidence_by_task = {evidence["task_id"]: evidence for evidence in audit["frozen_evidence"]}
    bound = [
        TaskResult(
            row.task_id,
            row.family,
            row.variant,
            row.success,
            list(row.critical_failures),
            groups_by_task[row.task_id],
            oracle_result_sha256=evidence_by_task[row.task_id]["oracle_result_sha256"],
            semantic_result_sha256=evidence_by_task[row.task_id]["semantic_result_sha256"],
            end_to_end_success=evidence_by_task[row.task_id]["end_to_end_success"],
            all_applicable_oracles_pass=evidence_by_task[row.task_id][
                "all_applicable_oracles_pass"
            ],
            semantic_or_human_oracle_pass=evidence_by_task[row.task_id][
                "semantic_or_human_oracle_pass"
            ],
            patch_safety_pass=evidence_by_task[row.task_id]["patch_safety_pass"],
            tool_failure=evidence_by_task[row.task_id]["tool_failure"],
            repair_cycles=evidence_by_task[row.task_id]["repair_cycles"],
        )
        for row in rows
    ]
    return bound, audit


def _evaluate(rows: list[TaskResult], target: dict[str, object]):
    bound, audit = _audit_for(rows)
    return evaluate_gate(
        bound,
        target,
        independence_audit=audit,
        target_contract=_ratified_contract(),
    )


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
        "forbidden_critical_failures": [
            "accepted_invented_identifier",
            "benchmark_leakage",
            "identity_mismatch",
            "prohibited_data_exposure",
            "semantic_wrong_compile_clean_accepted",
            "unauthorized_metis_write",
            "unrelated_destructive_change",
        ],
        "require_zero_unlisted_critical_failures": True,
        "minimum_distinct_leakage_groups": 563,
    }
    target.update(overrides)
    return target


@pytest.mark.parametrize("successes", [600, 599])
def test_wilson_and_gate_pass_with_at_most_one_failure(successes: int) -> None:
    result = _evaluate(_rows(successes=successes), _target())
    assert result.passed
    assert result.reasons == []
    assert result.aggregate.wilson95.upper <= 1.0


@pytest.mark.parametrize("successes", [598, 594])
def test_point_or_wilson_gate_rejects_insufficient_600_task_score(successes: int) -> None:
    result = _evaluate(_rows(successes=successes), _target())
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
    assert _evaluate(_rows(leakage_groups=563), _target(minimum_distinct_leakage_groups=563)).passed


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

    row = DerivedTaskResult("task", "F-1", "D", True, [], _group("group"))
    with pytest.raises(TypeError, match="TaskResult instances"):
        aggregate_results([row])


def test_task_result_is_immutable_after_validation() -> None:
    row = TaskResult("task", "F-1", "D", True, [], _group("group"))
    assert row.critical_failures == ()
    with pytest.raises(FrozenInstanceError):
        row.task_id = "changed"  # type: ignore[misc]


def test_wrong_family_denominator_is_rejected() -> None:
    result = _evaluate(
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
    assert "target control mismatch: family_counts" in result.reasons


def test_critical_failure_is_rejected() -> None:
    rows = _rows(successes=599)
    failed = rows[599]
    rows[599] = TaskResult(
        failed.task_id,
        failed.family,
        failed.variant,
        False,
        ["semantic_wrong_compile_clean_accepted"],
        failed.leakage_group,
    )
    result = _evaluate(rows, _target())
    assert not result.passed
    assert any("forbidden critical failure" in reason for reason in result.reasons)


def test_unlisted_critical_failure_is_rejected_by_zero_unlisted_gate() -> None:
    rows = _rows(successes=599, critical_failures={599: ["unlisted_test_failure"]})

    result = _evaluate(rows, _target())

    assert not result.passed
    assert "unlisted critical failure 'unlisted_test_failure': count 1" in result.reasons


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
    result = _evaluate(_rows(successes=599), _target(maximum_failures=0))
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
        TaskResult("t", "F-1", "D", 1, [], _group("g"))  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        TaskResult("", "F-1", "D", True, [], _group("g"))
    with pytest.raises(TypeError):
        TaskResult("t", "F-1", "D", True, ("failure",), _group("g"))  # type: ignore[arg-type]


def test_gate_fails_closed_without_authoritative_independence_audit() -> None:
    result = evaluate_gate(_rows(), _target())
    assert not result.passed
    assert "authoritative independence audit evidence is required" in result.reasons


def test_gate_rejects_forged_component_hash() -> None:
    rows, audit = _audit_for(_rows())
    forged = dict(audit)
    forged["components"] = [dict(component) for component in audit["components"]]
    forged["components"][0]["leakage_group"] = _group("forged")  # type: ignore[index]
    with pytest.raises(ValueError, match="hash does not match"):
        evaluate_gate(rows, _target(), independence_audit=forged)


def test_gate_rejects_rootless_component_even_with_recomputed_group_and_results() -> None:
    rows, audit = _audit_for(_rows())
    forged = copy.deepcopy(audit)
    component = forged["components"][0]
    original_group = component["leakage_group"]
    component["roots"] = []
    replacement_group = "sha256:" + canonical_json_hash(
        {"schema_version": 1, "roots": [], "edges": component["edges"]}
    )
    component["leakage_group"] = replacement_group
    task_id = component["task_ids"][0]
    row_index = next(index for index, row in enumerate(rows) if row.task_id == task_id)
    row = rows[row_index]
    assert row.leakage_group == original_group
    rows[row_index] = TaskResult(
        row.task_id,
        row.family,
        row.variant,
        row.success,
        list(row.critical_failures),
        replacement_group,
        oracle_result_sha256=row.oracle_result_sha256,
        semantic_result_sha256=row.semantic_result_sha256,
        end_to_end_success=row.end_to_end_success,
        all_applicable_oracles_pass=row.all_applicable_oracles_pass,
        semantic_or_human_oracle_pass=row.semantic_or_human_oracle_pass,
        patch_safety_pass=row.patch_safety_pass,
        tool_failure=row.tool_failure,
        repair_cycles=row.repair_cycles,
    )

    with pytest.raises(ValueError, match="roots are not canonical"):
        evaluate_gate(rows, _target(), independence_audit=forged)


def test_gate_rejects_result_group_not_bound_to_frozen_component() -> None:
    rows, audit = _audit_for(_rows())
    row = rows[0]
    rows[0] = TaskResult(
        row.task_id,
        row.family,
        row.variant,
        row.success,
        list(row.critical_failures),
        _group("spoofed-result-group"),
    )
    result = evaluate_gate(rows, _target(), independence_audit=audit)
    assert not result.passed
    assert any("not bound to its frozen component" in reason for reason in result.reasons)


def test_gate_rejects_result_task_id_not_in_frozen_components() -> None:
    rows, audit = _audit_for(_rows())
    row = rows[0]
    rows[0] = TaskResult(
        "spoofed-task-id",
        row.family,
        row.variant,
        row.success,
        list(row.critical_failures),
        row.leakage_group,
    )
    result = evaluate_gate(rows, _target(), independence_audit=audit)
    assert not result.passed
    assert any("do not match the frozen independence roster" in reason for reason in result.reasons)


def test_gate_rejects_task_result_success_and_critical_evidence_divergence() -> None:
    rows, audit = _audit_for(_rows())
    row = rows[0]
    rows[0] = TaskResult(
        row.task_id,
        row.family,
        row.variant,
        False,
        ["forged_failure"],
        row.leakage_group,
        oracle_result_sha256=row.oracle_result_sha256,
        semantic_result_sha256=row.semantic_result_sha256,
        end_to_end_success=False,
        all_applicable_oracles_pass=False,
        semantic_or_human_oracle_pass=False,
        patch_safety_pass=False,
        tool_failure=False,
        repair_cycles=row.repair_cycles,
    )
    result = evaluate_gate(
        rows,
        _target(),
        independence_audit=audit,
        target_contract=_ratified_contract(),
    )
    assert not result.passed
    assert any("success is not bound" in reason for reason in result.reasons)
    assert any("critical failures are not bound" in reason for reason in result.reasons)


def test_gate_rejects_task_result_oracle_hash_divergence() -> None:
    rows, audit = _audit_for(_rows())
    row = rows[0]
    rows[0] = TaskResult(
        row.task_id,
        row.family,
        row.variant,
        row.success,
        list(row.critical_failures),
        row.leakage_group,
        oracle_result_sha256=_group("forged-oracle-result"),
        semantic_result_sha256=row.semantic_result_sha256,
        end_to_end_success=row.end_to_end_success,
        all_applicable_oracles_pass=row.all_applicable_oracles_pass,
        semantic_or_human_oracle_pass=row.semantic_or_human_oracle_pass,
        patch_safety_pass=row.patch_safety_pass,
        tool_failure=row.tool_failure,
        repair_cycles=row.repair_cycles,
    )
    result = evaluate_gate(
        rows,
        _target(),
        independence_audit=audit,
        target_contract=_ratified_contract(),
    )
    assert not result.passed
    assert any("oracle_result_sha256 is not bound" in reason for reason in result.reasons)


def test_gate_rejects_task_result_without_promotion_oracle_evidence() -> None:
    rows, audit = _audit_for(_rows())
    row = rows[0]
    rows[0] = TaskResult(
        row.task_id,
        row.family,
        row.variant,
        row.success,
        list(row.critical_failures),
        row.leakage_group,
    )
    result = evaluate_gate(
        rows,
        _target(),
        independence_audit=audit,
        target_contract=_ratified_contract(),
    )
    assert not result.passed
    assert any("oracle evidence is incomplete for promotion" in reason for reason in result.reasons)


def test_canonical_all_success_audit_without_target_contract_cannot_pass() -> None:
    rows, audit = _audit_for(_rows(), target_contract=None)
    result = evaluate_gate(
        rows,
        _target(),
        independence_audit=audit,
        target_contract=_ratified_contract(),
    )
    assert not result.passed
    assert any("not bound to a ratified target contract" in reason for reason in result.reasons)


def test_self_attested_contract_cannot_pass_when_registered_digest_is_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(evaluation_module, "REGISTERED_TARGET_CONTRACT_SHA256", None)
    rows, audit = _audit_for(_rows())
    result = evaluate_gate(
        rows,
        _target(),
        independence_audit=audit,
        target_contract=_ratified_contract(),
    )
    assert not result.passed
    assert "trusted target contract digest authority is unset" in result.reasons


def test_product_evidence_zero_score_cannot_certify_all_success_results() -> None:
    rows, audit = _audit_for(_rows())
    audit["observed"] = dict(audit["observed"])
    audit["observed"]["successes"] = 0  # type: ignore[index]
    audit["observed"]["wilson_lower"] = 0.0  # type: ignore[index]
    audit["verdict"] = "PRODUCT_EVIDENCE"
    with pytest.raises(ValueError, match="observed successes"):
        evaluate_gate(
            rows,
            _target(),
            independence_audit=audit,
            target_contract=_ratified_contract(),
        )


def test_rewritten_zero_success_audit_aggregates_cannot_certify_all_success_results() -> None:
    _, zero_audit = _audit_for(_rows(successes=0))
    all_success_rows, _ = _audit_for(_rows(successes=600))
    forged_audit = copy.deepcopy(zero_audit)
    forged_audit["observed"] = dict(forged_audit["observed"])
    forged_audit["observed"]["successes"] = 600  # type: ignore[index]
    forged_audit["observed"]["wilson_lower"] = 1.0  # type: ignore[index]
    forged_audit["verdict"] = "TARGET_99_CONFIRMED"

    with pytest.raises(ValueError, match="observed successes"):
        evaluate_gate(
            all_success_rows,
            _target(),
            independence_audit=forged_audit,
            target_contract=_ratified_contract(),
        )


def test_components_with_only_f1_cannot_certify_mixed_target_task_results() -> None:
    rows, audit = _audit_for(_rows(successes=600))
    forged_audit = copy.deepcopy(audit)
    for component in forged_audit["components"]:
        component["families"] = ["F-1"]
        component["task_families"] = {task_id: "F-1" for task_id in component["task_ids"]}

    with pytest.raises(ValueError, match="family counts"):
        evaluate_gate(
            rows,
            _target(),
            independence_audit=forged_audit,
            target_contract=_ratified_contract(),
        )


def test_semantic_and_critical_audit_mismatches_cannot_pass() -> None:
    rows, audit = _audit_for(_rows())
    audit["observed"] = dict(audit["observed"])
    audit["observed"]["semantic_evidence_complete"] = False  # type: ignore[index]
    audit["observed"]["critical_failure_count"] = 1  # type: ignore[index]
    with pytest.raises(ValueError, match="critical evidence"):
        evaluate_gate(
            rows,
            _target(),
            independence_audit=audit,
            target_contract=_ratified_contract(),
        )


def test_target_contract_hash_mismatch_cannot_pass() -> None:
    rows, audit = _audit_for(_rows())
    mismatched_contract = _ratified_contract()
    mismatched_contract["population_attestation"] = {
        "status": "verified",
        "evidence_sha256": _group("different-population-evidence"),
        "reviewer_session_id": "independent-reviewer-1",
    }
    result = evaluate_gate(
        rows,
        _target(),
        independence_audit=audit,
        target_contract=mismatched_contract,
    )
    assert not result.passed
    assert any("does not match trusted authority digest" in reason for reason in result.reasons)


def test_relaxed_target_critical_policy_cannot_admit_a_critical_failure() -> None:
    rows = _rows(successes=599)
    failed = rows[-1]
    rows[-1] = TaskResult(
        failed.task_id,
        failed.family,
        failed.variant,
        False,
        ["semantic_wrong_compile_clean_accepted"],
        failed.leakage_group,
    )
    result = _evaluate(
        rows,
        _target(
            forbidden_critical_failures=[],
            require_zero_unlisted_critical_failures=False,
        ),
    )
    assert not result.passed
    assert any(
        "target control mismatch: forbidden_critical_failures" in reason
        for reason in result.reasons
    )
    assert any("critical_failure_count must be zero" in reason for reason in result.reasons)
