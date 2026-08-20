from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from metis_model1.evaluator import EvaluationError, Observation, evaluate_observations


def _rows(task_ids: tuple[str, ...] = ("task-1", "task-2")) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index, task_id in enumerate(task_ids):
        for variant in ("A", "B", "C", "D"):
            enabled_context = variant in ("B", "D")
            enabled_adapter = variant in ("C", "D")
            rows.append(
                {
                    "task_id": task_id,
                    "family": "F-1" if index == 0 else "F-2",
                    "variant": variant,
                    "leakage_group": f"group-{index}",
                    "evidence": {
                        "output_sha256": "sha256:" + "d" * 64,
                        "first_shot_oracles": {
                            key: "sha256:" + "f" * 64
                            for key in ("parse", "link", "validate", "compile", "semantic")
                        },
                        "post_repair_oracles": {
                            key: "sha256:" + "e" * 64
                            for key in ("parse", "link", "validate", "compile", "semantic")
                        },
                    },
                    "config": {
                        "prompt_hash": ("a" if index == 0 else "b") * 64,
                        "sampling_hash": "c" * 64,
                        "reasoning_mode": "reasoning",
                        "context_budget": 1024,
                        "repair_budget": 2,
                        "context_enabled": enabled_context,
                        "compiler_loop": enabled_context,
                        "adapter_enabled": enabled_adapter,
                    },
                    "first_shot_success": True,
                    "post_repair_success": True,
                    "repair_cycles": 0,
                    "first_shot_outcomes": {
                        "parse": "pass",
                        "link": "pass",
                        "validate": "pass",
                        "compile": "pass",
                        "semantic": "pass",
                    },
                    "post_repair_outcomes": {
                        "parse": "pass",
                        "link": "pass",
                        "validate": "pass",
                        "compile": "pass",
                        "semantic": "pass",
                    },
                    "tool_failure": False,
                    "critical_failures": [],
                    "identity": {
                        "seed": 17,
                        "base_model_hash": "b" * 64,
                        "adapter_hash": "a" * 64 if enabled_adapter else "none",
                        "dataset_manifest_hash": "d" * 64,
                        "compiler_hash": "git:" + "c" * 40,
                        "benchmark_hash": "e" * 64,
                        "runtime_hash": "f" * 64,
                    },
                }
            )
            if index > 0:
                rows[-1]["first_shot_outcomes"]["patch_minimality"] = "pass"
                rows[-1]["post_repair_outcomes"]["patch_minimality"] = "pass"
                rows[-1]["evidence"]["first_shot_oracles"]["patch_minimality"] = (
                    "sha256:" + "f" * 64
                )
                rows[-1]["evidence"]["post_repair_oracles"]["patch_minimality"] = (
                    "sha256:" + "e" * 64
                )
    return rows


def _row(rows: list[dict[str, object]], task_id: str, variant: str) -> dict[str, object]:
    return next(row for row in rows if row["task_id"] == task_id and row["variant"] == variant)


def _mark_post_repair_failure(row: dict[str, object]) -> None:
    row["first_shot_success"] = False
    row["post_repair_success"] = False
    row["repair_cycles"] = 1
    row["post_repair_outcomes"] = {
        **row["post_repair_outcomes"],
        "semantic": "fail",
    }
    row["failure_category"] = "semantic"


def test_valid_report_has_unfiltered_4n_denominator_and_paired_deltas() -> None:
    report = evaluate_observations(_rows())

    assert report["denominator"] == {
        "tasks": 2,
        "observations": 8,
        "expected_observations": 8,
        "distinct_task_ids": 2,
        "in": 8,
        "out": 8,
        "distinct_task": 2,
        "gaps": 0,
        "filtered": 0,
        "conditional": False,
        "policy": "all_tasks_unfiltered",
    }
    assert report["variants"]["D"]["post_repair"]["denominator"] == 2
    assert report["paired_deltas"]["B-A"]["post_repair"]["delta_rate"] == 0
    assert report["paired_deltas"]["C-A"]["post_repair"]["delta_rate"] == 0
    assert report["paired_deltas"]["D-B"]["post_repair"]["delta_rate"] == 0
    assert report["paired_deltas"]["D-C"]["post_repair"]["delta_rate"] == 0
    assert report["prompt_roster_hash"] == report["config_identity"]["prompt_roster_hash"]


def test_distinct_task_prompts_are_allowed_but_within_task_drift_is_not() -> None:
    report = evaluate_observations(_rows(("task-1", "task-2")))
    assert report["denominator"]["tasks"] == 2
    rows = _rows(("task-1", "task-2"))
    rows[4]["config"] = {**rows[4]["config"], "prompt_hash": "f" * 64}
    with pytest.raises(EvaluationError, match="comparable-config"):
        evaluate_observations(rows)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda rows: rows.pop(),
        lambda rows: rows.__setitem__(3, {**rows[3], "variant": "C"}),
        lambda rows: rows.__setitem__(1, {**rows[1], "family": "F-2"}),
        lambda rows: rows.__setitem__(1, {**rows[1], "leakage_group": "other"}),
        lambda rows: rows.__setitem__(
            1, {**rows[1], "config": {**rows[1]["config"], "prompt_hash": "drift"}}
        ),
        lambda rows: rows.__setitem__(
            1, {**rows[1], "identity": {**rows[1]["identity"], "seed": 18}}
        ),
    ],
)
def test_roster_pair_identity_mutations_fail_closed(mutation) -> None:
    rows = _rows(("task-1",))
    mutation(rows)
    with pytest.raises(EvaluationError):
        evaluate_observations(rows)


def test_context_compiler_and_adapter_ablation_is_enforced() -> None:
    rows = _rows(("task-1",))
    rows[1]["config"] = {**rows[1]["config"], "compiler_loop": False}
    with pytest.raises(EvaluationError, match="context/compiler"):
        evaluate_observations(rows)

    rows = _rows(("task-1",))
    rows[2]["config"] = {**rows[2]["config"], "adapter_enabled": False}
    with pytest.raises(EvaluationError, match="adapter"):
        evaluate_observations(rows)


def test_repair_and_structural_semantic_tool_predicates_are_not_bypassed() -> None:
    rows = _rows(("task-1",))
    rows[0]["first_shot_success"] = False
    rows[0]["post_repair_success"] = True
    rows[0]["repair_cycles"] = 1
    rows[0]["post_repair_outcomes"] = {
        **rows[0]["post_repair_outcomes"],
        "semantic": "fail",
    }
    rows[0]["failure_category"] = "semantic"
    rows[1]["tool_failure"] = True
    rows[1]["first_shot_success"] = False
    rows[1]["post_repair_success"] = False
    rows[1]["repair_cycles"] = 2
    rows[1]["failure_category"] = "loop_or_tool"
    report = evaluate_observations(rows)
    assert report["variants"]["A"]["post_repair"]["successes"] == 0
    assert report["variants"]["B"]["post_repair"]["successes"] == 0
    assert report["failure_taxonomy"]["A"]["semantic"] == 1
    assert report["failure_taxonomy"]["B"]["loop_or_tool"] == 1


def test_repair_cycles_and_strict_booleans_are_coherent() -> None:
    rows = _rows(("task-1",))
    rows[0]["repair_cycles"] = 3
    with pytest.raises(EvaluationError, match="repair_cycles"):
        evaluate_observations(rows)

    rows = _rows(("task-1",))
    rows[0]["first_shot_success"] = 1
    with pytest.raises(EvaluationError, match="strict bool"):
        evaluate_observations(rows)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda row: row.update({"repair_cycles": 1}),
            "first-shot success requires zero repair_cycles",
        ),
        (
            lambda row: row.update(
                {"first_shot_success": False, "post_repair_success": True, "repair_cycles": 0}
            ),
            "post-repair success after first-shot failure needs a repair cycle",
        ),
    ],
)
def test_repair_cycle_success_coherence_branches_are_fail_closed(mutation, message: str) -> None:
    rows = _rows(("task-1",))
    mutation(rows[0])

    with pytest.raises(EvaluationError, match=message):
        evaluate_observations(rows)


def test_invented_identifier_is_propagated_as_critical_failure() -> None:
    rows = _rows(("task-1",))
    rows[0]["critical_failures"] = ["accepted_invented_identifier"]
    rows[0]["failure_category"] = "invented_identifier"
    report = evaluate_observations(rows)
    assert report["status"] == "complete"
    assert report["all_observations_post_repair_pass"] is False
    assert report["variants"]["A"]["critical_failures"] == {"accepted_invented_identifier": 1}
    assert report["failure_taxonomy"]["A"]["invented_identifier"] == 1
    assert report["variants"]["A"]["post_repair"]["successes"] == 0


def test_other_critical_vetoes_are_reported_fail_closed() -> None:
    rows = _rows(("task-1",))
    rows[0]["critical_failures"] = ["unauthorized_metis_write"]
    rows[0]["failure_category"] = "unknown"

    report = evaluate_observations(rows)

    assert report["all_observations_post_repair_pass"] is False
    assert report["critical_failures"] == {"unauthorized_metis_write": 1}
    assert report["variants"]["A"]["post_repair"]["successes"] == 0


def test_conditional_denominator_is_rejected() -> None:
    rows = _rows(("task-1",))
    rows[0]["conditional_denominator"] = True
    with pytest.raises(EvaluationError, match="denominator"):
        evaluate_observations(rows)


def test_synthetic_fixture_matches_schema() -> None:
    root = Path(__file__).parents[1]
    schema = json.loads((root / "schemas/evaluation-report.schema.json").read_text())
    fixture = json.loads((root / "examples/evaluation-report.synthetic.json").read_text())
    assert list(Draft202012Validator(schema).iter_errors(fixture)) == []
    generated = evaluate_observations(fixture["observations"])
    assert list(Draft202012Validator(schema).iter_errors(generated)) == []
    assert generated["denominator"] == fixture["denominator"]
    assert generated["identity_hashes"] == fixture["identity_hashes"]
    assert generated["paired_deltas"] == fixture["paired_deltas"]

    missing_variant = json.loads(json.dumps(generated))
    del missing_variant["family_breakdown"]["D"]
    assert list(Draft202012Validator(schema).iter_errors(missing_variant))

    malformed_prompt = json.loads(json.dumps(generated))
    malformed_prompt["observations"][0]["config"]["prompt_hash"] = "not-a-hash"
    assert list(Draft202012Validator(schema).iter_errors(malformed_prompt))


def test_preconstructed_observation_cannot_bypass_mapping_validation() -> None:
    rows = _rows(("task-1",))
    parsed = Observation.from_mapping(rows[0])
    with pytest.raises(EvaluationError, match="plain mappings"):
        evaluate_observations([parsed, *rows[1:]])


@pytest.mark.parametrize(
    ("where", "key"),
    [
        ("row", "unknown"),
        ("config", "unknown"),
        ("first_shot_outcomes", "unknown"),
        ("identity", "unknown"),
    ],
)
def test_unknown_fields_are_rejected_at_each_contract_boundary(where: str, key: str) -> None:
    rows = _rows(("task-1",))
    target = rows[0] if where == "row" else rows[0][where]
    target[key] = "drift"
    with pytest.raises(EvaluationError, match="unknown"):
        evaluate_observations(rows)


def test_conflicting_flat_outcomes_alias_is_rejected() -> None:
    rows = _rows(("task-1",))
    rows[0]["outcomes"] = {**rows[0]["post_repair_outcomes"], "semantic": "fail"}
    with pytest.raises(EvaluationError, match="conflicting"):
        evaluate_observations(rows)


def test_identity_is_complete_and_adapter_partition_is_exact() -> None:
    rows = _rows(("task-1",))
    del rows[0]["identity"]["compiler_hash"]
    with pytest.raises(EvaluationError, match="complete immutable"):
        evaluate_observations(rows)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row["evidence"].pop("output_sha256"),
        lambda row: row["evidence"]["first_shot_oracles"].pop("parse"),
        lambda row: row["evidence"]["post_repair_oracles"].__setitem__("parse", "bad"),
        lambda row: row["identity"].__setitem__("runtime_hash", "bad"),
        lambda row: row["identity"].__setitem__("base_model_hash", "bad"),
    ],
)
def test_evidence_and_typed_identity_mutations_fail_closed(mutation) -> None:
    rows = _rows(("task-1",))
    mutation(rows[0])
    with pytest.raises(EvaluationError):
        evaluate_observations(rows)
    rows = _rows(("task-1",))
    rows[0]["identity"]["adapter_hash"] = "1" * 64
    with pytest.raises(EvaluationError, match="adapter"):
        evaluate_observations(rows)


def test_family_oracle_registry_rejects_missing_or_not_applicable_required_oracle() -> None:
    rows = _rows(("task-1",))
    for row in rows:
        row["family"] = "F-2"
        row["first_shot_outcomes"] = {**row["first_shot_outcomes"], "patch_minimality": "pass"}
        row["post_repair_outcomes"] = {
            **row["post_repair_outcomes"],
            "patch_minimality": "not_applicable",
        }
    with pytest.raises(EvaluationError, match="not_applicable"):
        evaluate_observations(rows)


def test_first_shot_outcomes_are_scored_separately_from_post_repair() -> None:
    rows = _rows(("task-1",))
    rows[0]["first_shot_success"] = False
    rows[0]["post_repair_success"] = True
    rows[0]["repair_cycles"] = 1
    rows[0]["first_shot_outcomes"] = {**rows[0]["first_shot_outcomes"], "semantic": "fail"}
    report = evaluate_observations(rows)
    assert report["variants"]["A"]["first_shot"]["successes"] == 0
    assert report["variants"]["A"]["post_repair"]["successes"] == 1


def test_computed_post_repair_failure_requires_failure_category() -> None:
    rows = _rows(("task-1",))
    rows[0]["first_shot_success"] = False
    rows[0]["post_repair_success"] = False
    rows[0]["repair_cycles"] = 1
    rows[0]["post_repair_outcomes"] = {
        **rows[0]["post_repair_outcomes"],
        "semantic": "fail",
    }

    with pytest.raises(EvaluationError, match="requires an enumerated failure_category"):
        evaluate_observations(rows)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("sampling_hash", "d" * 64),
        ("reasoning_mode", "different-reasoning"),
        ("context_budget", 2048),
        ("repair_budget", 1),
    ],
)
def test_comparable_configuration_cannot_mix_across_tasks(key: str, value: object) -> None:
    rows = _rows(("task-1", "task-2"))
    for row in rows:
        if row["task_id"] == "task-2":
            row["config"] = {**row["config"], key: value}

    with pytest.raises(EvaluationError, match=f"mixed comparable configuration for {key}"):
        evaluate_observations(rows)


def test_failure_category_must_be_enumerated_and_coherent() -> None:
    rows = _rows(("task-1",))
    rows[0]["first_shot_success"] = False
    rows[0]["post_repair_success"] = False
    rows[0]["repair_cycles"] = 2
    rows[0]["post_repair_outcomes"] = {**rows[0]["post_repair_outcomes"], "semantic": "fail"}
    rows[0]["failure_category"] = "made_up"
    with pytest.raises(EvaluationError, match="taxonomy"):
        evaluate_observations(rows)
    rows[0]["failure_category"] = "compile"
    with pytest.raises(EvaluationError, match="incoherent"):
        evaluate_observations(rows)


def test_failure_category_derives_patch_and_benchmark_oracle_failures() -> None:
    rows = _rows(("task-1", "task-2"))
    rows[4]["first_shot_outcomes"]["patch_minimality"] = "pass"
    rows[4]["post_repair_outcomes"]["patch_minimality"] = "fail"
    rows[4]["failure_category"] = "nonminimal_or_regressive"
    rows[5]["critical_failures"] = ["benchmark_oracle_defect"]
    rows[5]["failure_category"] = "benchmark_oracle"
    report = evaluate_observations(rows)
    assert report["failure_taxonomy"]["A"]["nonminimal_or_regressive"] == 1
    assert report["failure_taxonomy"]["B"]["benchmark_oracle"] == 1


def test_paired_report_contains_discordance_and_exact_sign_test() -> None:
    rows = _rows(("task-1", "task-2"))
    for index in (0, 4):
        rows[index]["first_shot_success"] = False
        rows[index]["post_repair_success"] = False
        rows[index]["repair_cycles"] = 2
        rows[index]["post_repair_outcomes"] = {
            **rows[index]["post_repair_outcomes"],
            "semantic": "fail",
        }
        rows[index]["failure_category"] = "semantic"
    report = evaluate_observations(rows)
    paired = report["paired_deltas"]["C-A"]["post_repair"]
    assert (
        paired["discordant_left_wins"],
        paired["discordant_right_wins"],
        paired["discordant_total"],
    ) == (2, 0, 2)
    assert paired["sign_test_p_value"] == pytest.approx(0.5)


@pytest.mark.parametrize(
    ("pair", "left", "right"),
    [("B-A", "B", "A"), ("D-B", "D", "B"), ("D-C", "D", "C")],
)
def test_named_paired_deltas_have_exact_sign_test_cases(pair: str, left: str, right: str) -> None:
    zero_discordant = evaluate_observations(_rows(("task-1",)))
    zero = zero_discordant["paired_deltas"][pair]["post_repair"]
    assert (zero["discordant_left_wins"], zero["discordant_right_wins"]) == (0, 0)
    assert zero["sign_test_p_value"] == pytest.approx(1.0)

    one_each_rows = _rows(("task-1", "task-2"))
    _mark_post_repair_failure(_row(one_each_rows, "task-1", right))
    _mark_post_repair_failure(_row(one_each_rows, "task-2", left))
    one_each_report = evaluate_observations(one_each_rows)
    one_each = one_each_report["paired_deltas"][pair]["post_repair"]
    assert (one_each["discordant_left_wins"], one_each["discordant_right_wins"]) == (1, 1)
    assert one_each["sign_test_p_value"] == pytest.approx(1.0)

    three_one_rows = _rows(("task-1", "task-2", "task-3", "task-4"))
    for task_id in ("task-1", "task-2", "task-3"):
        _mark_post_repair_failure(_row(three_one_rows, task_id, right))
    _mark_post_repair_failure(_row(three_one_rows, "task-4", left))
    three_one_report = evaluate_observations(three_one_rows)
    three_one = three_one_report["paired_deltas"][pair]["post_repair"]
    assert (three_one["discordant_left_wins"], three_one["discordant_right_wins"]) == (3, 1)
    assert three_one["sign_test_p_value"] == pytest.approx(0.625)
