from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from metis_model1.independence import IndependenceError, audit_independence
from metis_model1.provenance import canonical_json_hash

_ROOT_MATERIALS: dict[str, dict[str, str]] = {}


def _hash(label: str) -> str:
    material = {
        "kind": "test_fixture",
        "origin": "public_synthetic",
        "authoring_session_id": f"author-{label}",
        "content_sha256": "sha256:" + canonical_json_hash({"content": label}),
    }
    root = "sha256:" + canonical_json_hash(material)
    _ROOT_MATERIALS[root] = material
    return root


def _task(
    name: str,
    *,
    family: str = "F-1",
    split: str = "frozen",
    **provenance: object,
) -> dict[str, object]:
    roots = provenance.get("roots")
    if isinstance(roots, list) and "root_evidence" not in provenance:
        provenance["root_evidence"] = [
            copy.deepcopy(_ROOT_MATERIALS[root]) for root in roots if root in _ROOT_MATERIALS
        ]
    return {"task_id": name, "family": family, "split": split, "provenance": provenance}


def _score(row: dict[str, object], success: bool = True) -> None:
    row["success"] = success
    row["critical_failures"] = []
    row["oracle_evidence"] = {
        "end_to_end_success": success,
        "all_applicable_oracles_pass": success,
        "semantic_or_human_oracle_pass": success,
        "patch_safety_pass": success,
        "tool_failure": False,
        "repair_cycles": 0,
        "oracle_result_sha256": _hash(f"oracle-{row['task_id']}"),
        "semantic_result_sha256": _hash(f"semantic-{row['task_id']}"),
    }


def _ratified_target() -> dict[str, object]:
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
        "population_attestation": {
            "status": "verified",
            "evidence_sha256": _hash("population-evidence"),
            "reviewer_session_id": "independent-reviewer-1",
        },
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
    }


def test_shared_generator_session_unions_and_cosmetic_rename_cannot_split() -> None:
    rows = [
        _task(
            "a",
            roots=[_hash("a")],
            generator_id="g",
            generator_version="1",
            generation_session_id="session",
        ),
        _task(
            "b-renamed",
            roots=[_hash("b")],
            generator_id="g",
            generator_version="1",
            generation_session_id="session",
        ),
    ]
    audit = audit_independence(rows)
    assert audit["counts"]["distinct_leakage_groups"] == 1


def test_shared_template_unions() -> None:
    rows = [
        _task("a", roots=[_hash("a")], template_id="t", template_version="1"),
        _task("b", roots=[_hash("b")], template_id="t", template_version="1"),
    ]
    assert audit_independence(rows)["counts"]["distinct_leakage_groups"] == 1


def test_root_and_parent_shared_identity_unions() -> None:
    shared = _hash("shared")
    rows = [
        _task("a", roots=[shared]),
        _task("b", roots=[_hash("b")], parents=[shared]),
    ]
    assert audit_independence(rows)["counts"]["distinct_leakage_groups"] == 1


def test_transitive_collision_unions_components() -> None:
    rows = [
        _task("a", roots=[_hash("a")], semantic_spec_id="s1"),
        _task(
            "b",
            roots=[_hash("b")],
            semantic_spec_id="s1",
            template_id="t",
            template_version="1",
        ),
        _task("c", roots=[_hash("c")], template_id="t", template_version="1"),
    ]
    assert audit_independence(rows)["counts"]["distinct_leakage_groups"] == 1


def test_same_epoch_non_migration_stays_separate() -> None:
    rows = [
        _task("a", roots=[_hash("a")], language_epoch="0.43"),
        _task("b", roots=[_hash("b")], language_epoch="0.43"),
    ]
    assert audit_independence(rows)["counts"]["distinct_leakage_groups"] == 2


def test_migration_epoch_unions_only_f5() -> None:
    root = _hash("legacy")
    rows = [
        _task("a", family="F-5", roots=[_hash("a")], legacy_epoch_root=root),
        _task("b", family="F-5", roots=[_hash("b")], legacy_epoch_root=root),
    ]
    assert audit_independence(rows)["counts"]["distinct_leakage_groups"] == 1


def test_split_crossing_is_rejected_transitively() -> None:
    rows = [
        _task("a", split="train", roots=[_hash("shared")]),
        _task("b", split="frozen", roots=[_hash("shared")]),
    ]
    with pytest.raises(IndependenceError, match="split crossing"):
        audit_independence(rows)


def test_benchmark_root_in_w3_is_rejected() -> None:
    root = _hash("benchmark")
    rows = [
        _task("benchmark", roots=[root]),
        _task("w3", split="train", roots=[_hash("w3")], benchmark_roots=[root]),
    ]
    with pytest.raises(IndependenceError, match="benchmark roots"):
        audit_independence(rows)


def test_shared_benchmark_root_unions_frozen_rows_and_counts_one_group() -> None:
    benchmark_root = _hash("frozen-benchmark-asset")
    rows = [
        _task(
            f"frozen-{index}",
            roots=[_hash(f"unique-content-{index}")],
            benchmark_roots=[benchmark_root],
        )
        for index in range(39)
    ]
    audit = audit_independence(rows)
    assert audit["counts"]["in"] == 39
    assert audit["counts"]["frozen_distinct_leakage_groups"] == 1
    assert len(audit["components"]) == 1
    assert benchmark_root in audit["components"][0]["roots"]


def test_benchmark_root_changes_canonical_component_identity() -> None:
    root = _hash("content")
    without_benchmark = audit_independence([_task("task", roots=[root])])
    with_benchmark = audit_independence(
        [_task("task", roots=[root], benchmark_roots=[_hash("benchmark")])]
    )
    assert (
        without_benchmark["components"][0]["leakage_group"]
        != with_benchmark["components"][0]["leakage_group"]
    )


@pytest.mark.parametrize("bad", [["sha256:not-a-hash"], ["not-a-hash"]])
def test_malformed_root_hash_is_rejected(bad: list[str]) -> None:
    with pytest.raises(IndependenceError, match="sha256"):
        audit_independence([_task("a", roots=bad)])


def test_unknown_parent_self_parent_and_manual_group_are_rejected() -> None:
    with pytest.raises(IndependenceError, match="unknown parent"):
        audit_independence([_task("a", roots=[_hash("a")], parents=["missing"])])
    with pytest.raises(IndependenceError, match="self-parent"):
        audit_independence([_task("a", roots=[_hash("a")], parents=["a"])])
    manual = _task("a", roots=[_hash("a")])
    manual["leakage_group"] = "fake"
    with pytest.raises(IndependenceError, match="manually"):
        audit_independence([manual])


def test_order_determinism_and_audit_counts() -> None:
    rows = [_task("a", roots=[_hash("a")]), _task("b", roots=[_hash("b")])]
    first = audit_independence(rows)
    second = audit_independence(list(reversed(copy.deepcopy(rows))))
    assert first == second
    assert first["counts"] == {
        "in": 2,
        "out": 2,
        "distinct": 2,
        "gaps": 0,
        "distinct_leakage_groups": 2,
        "frozen_distinct_leakage_groups": 2,
    }


def test_cosmetic_task_rename_does_not_change_group_identity() -> None:
    root = _hash("same-content")
    first = audit_independence([_task("first-name", roots=[root])])
    second = audit_independence([_task("cosmetic-rename", roots=[root])])
    assert first["components"][0]["leakage_group"] == second["components"][0]["leakage_group"]


def test_every_task_requires_content_genealogy() -> None:
    with pytest.raises(IndependenceError, match="content root"):
        audit_independence([_task("rootless", semantic_spec_id="unique-label")])


def test_only_frozen_tasks_can_supply_score_or_promotion_groups() -> None:
    rows = [
        _task("train", split="train", roots=[_hash("train")]),
        _task("frozen", roots=[_hash("frozen")]),
    ]
    _score(rows[0])
    _score(rows[1])
    audit = audit_independence(rows)
    assert audit["observed"]["total"] == 1
    assert audit["counts"]["frozen_distinct_leakage_groups"] == 1
    assert audit["verdict"] == "PRODUCT_EVIDENCE"


def test_thresholds_and_denominators_cannot_be_overridden() -> None:
    row = _task("frozen", roots=[_hash("frozen")])
    _score(row)
    with pytest.raises(TypeError, match="unexpected keyword"):
        audit_independence([row], point_min=0.0)  # type: ignore[call-arg]


def test_root_identity_must_match_canonical_evidence() -> None:
    row = _task("a", roots=[_hash("a")])
    row["provenance"]["root_evidence"][0]["origin"] = "tampered"  # type: ignore[index]
    with pytest.raises(IndependenceError, match="does not match"):
        audit_independence([row])


def test_partial_or_malformed_scoring_and_critical_evidence_fail_closed() -> None:
    first = _task("a", roots=[_hash("a")])
    second = _task("b", roots=[_hash("b")])
    first["success"] = True
    with pytest.raises(IndependenceError, match="full denominator"):
        audit_independence([first, second])
    first["critical_failures"] = [""]
    second["success"] = True
    with pytest.raises(IndependenceError, match="critical_failures"):
        audit_independence([first, second])


def test_observed_target_requires_per_task_oracle_evidence() -> None:
    rows = [_task(str(index), roots=[_hash(str(index))]) for index in range(600)]
    for row in rows:
        row["success"] = True
        row["critical_failures"] = []
    audit = audit_independence(rows)
    assert audit["verdict"] == "PRODUCT_EVIDENCE"
    assert not audit["observed"]["semantic_evidence_complete"]


def test_target_requires_ratified_contract_and_full_registered_roster() -> None:
    family_roster = [
        *("F-1" for _ in range(100)),
        *("F-2" for _ in range(110)),
        *("F-3" for _ in range(110)),
        *("F-4" for _ in range(110)),
        *("F-5" for _ in range(90)),
        *("F-6" for _ in range(80)),
    ]
    rows = [
        _task(str(index), family=family, roots=[_hash(str(index))])
        for index, family in enumerate(family_roster)
    ]
    for index, row in enumerate(rows):
        _score(row, success=index != 0)
    audit = audit_independence(rows)
    assert audit["verdict"] == "OBSERVED_99_ONLY"
    assert not audit["observed"]["target_contract_bound"]
    promoted = audit_independence(rows, target_contract=_ratified_target())
    assert promoted["verdict"] == "TARGET_99_CONFIRMED"


def test_unratified_or_population_unverified_contract_is_rejected() -> None:
    contract = _ratified_target()
    contract["status"] = "proposed"
    with pytest.raises(IndependenceError, match="registered status"):
        audit_independence([_task("a", roots=[_hash("a")])], target_contract=contract)
    contract = _ratified_target()
    contract["population_attestation"]["status"] = "pending"  # type: ignore[index]
    with pytest.raises(IndependenceError, match="population attestation"):
        audit_independence([_task("a", roots=[_hash("a")])], target_contract=contract)


def test_audit_matches_independence_schema() -> None:
    rows = [_task("a", roots=[_hash("a")])]
    audit = audit_independence(rows)
    schema_path = Path(__file__).parents[1] / "schemas" / "benchmark-independence.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(audit)


def test_frozen_evidence_roster_is_sorted_and_digest_bound() -> None:
    rows = [_task("b", roots=[_hash("b")]), _task("a", roots=[_hash("a")])]
    for row in rows:
        _score(row)
    audit = audit_independence(rows)
    assert [row["task_id"] for row in audit["frozen_evidence"]] == ["a", "b"]
    assert audit["frozen_evidence_sha256"] == (
        "sha256:" + canonical_json_hash(audit["frozen_evidence"])
    )
