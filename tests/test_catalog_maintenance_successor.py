from __future__ import annotations

from pathlib import Path

import pytest

from metis_model1 import catalog_maintenance_successor as successor

ROOT = Path(__file__).resolve().parents[1]


def _cases() -> list[dict]:
    _manifest, _schema, cases = successor.load_probe_contract()
    return cases


def _passing_observation(case: dict) -> dict:
    return {
        "case_id": case["case_id"],
        "root_id": case["provenance"]["semantic_root"],
        "semantic_correct": 1,
        "skeleton_match": True,
        "critical_failure": 0,
        "invented_values": 0,
        "legacy_inline": 0,
        "retrieval_error": 0,
        "required_missing": [],
        "forbidden_hits": [],
        "retrieval_error_text": None,
    }


def test_successor_messages_use_system_role_and_explicit_canonical_surface() -> None:
    for case in _cases():
        retrieval = (
            {"value": "Curated", "size": 1}
            if case["retrieval"]["kind"] == "public_synthetic_value"
            else None
        )
        messages = successor.build_messages(case, retrieval)
        assert [message["role"] for message in messages] == ["system", "user"]
        system = messages[0]["content"]
        assert "first line must be exactly: metis 0.43" in system
        assert "name keyword enum(N)" in system
        assert "name enum(N)" in system
        assert "catalog example.items" in system
        assert case["target"]["expected_source"].strip() not in "\n".join(
            message["content"] for message in messages
        )


def test_system_example_is_disjoint_from_every_case_target() -> None:
    for case in _cases():
        expected = case["target"]["expected_source"]
        for token in ("example.items", "example_items", "item_id", "status keyword enum(7)"):
            assert token not in expected


def test_requests_describe_semantics_without_copying_required_fragments() -> None:
    for case in _cases():
        request = case["prompt"]["request"]
        assert all(fragment not in request for fragment in case["target"]["required_fragments"])


def test_retrieval_value_reaches_only_the_retrieval_case() -> None:
    for case in _cases():
        retrieval = (
            {"value": "Curated", "size": 1}
            if case["retrieval"]["kind"] == "public_synthetic_value"
            else None
        )
        rendered = "\n".join(
            message["content"] for message in successor.build_messages(case, retrieval)
        )
        assert ("Curated" in rendered) is (retrieval is not None)


@pytest.mark.parametrize(
    ("failure_code", "required_text"),
    [
        ("missing_metis_0_43_prefix", "exact required first line"),
        ("catalog describe rejected candidate", "follows the scalar type `keyword`"),
        ("text_outside_code_fence", "wrapper text"),
        (None, "catalog skeleton did not satisfy the request"),
    ],
)
def test_repair_feedback_is_structural_and_non_truth_leaking(
    failure_code: str | None, required_text: str
) -> None:
    feedback = successor.build_repair_message(failure_code)
    assert required_text in feedback
    assert "metis 0.43" in feedback
    for case in _cases():
        assert case["target"]["expected_source"].strip() not in feedback
        assert all(fragment not in feedback for fragment in case["target"]["required_fragments"])


def test_score_requires_keyword_domain_form_and_exact_skeleton() -> None:
    case = next(item for item in _cases() if item["case_id"] == "edit-category-inline3-to-enum3")
    skeleton = {"catalogs": [{"name": "public.video"}]}
    good = successor.score_candidate(
        case,
        "metis 0.43\ncategory keyword enum(3)\n",
        skeleton,
        expected_skeleton=skeleton,
    )
    assert good["semantic_correct"] == 1
    missing_keyword = successor.score_candidate(
        case,
        "metis 0.43\ncategory enum(3)\n",
        skeleton,
        expected_skeleton=skeleton,
    )
    assert missing_keyword["semantic_correct"] == 0
    assert missing_keyword["required_missing"] == ["category keyword enum(3)"]


def test_tiny_inline_successor_construct_is_not_marked_as_invented() -> None:
    case = next(item for item in _cases() if item["case_id"] == "author-availability-inline")
    score = successor.score_candidate(
        case,
        'metis 0.43\navailability keyword values ["Free", "Premium"]\n',
        {"catalogs": []},
        expected_skeleton={"catalogs": []},
    )
    assert score["invented_values"] == 0


def test_gate_green_requires_exact_eight_case_roster_and_zero_veto() -> None:
    cases = _cases()
    passing = [_passing_observation(case) for case in cases]
    decision = successor.gate_arithmetic(passing)
    assert decision["verdict"] == "NO_RETRAIN_PROMPT_CURE"
    assert decision["counts"] == {
        "critical_failure": 0,
        "invented_values": 0,
        "legacy_inline": 0,
        "retrieval_error": 0,
        "semantic_correct": 8,
        "cases_in": 8,
        "cases_out": 8,
        "cases_distinct": 8,
        "gaps": 0,
    }
    assert decision["training_authorized"] is False
    assert decision["promotion_claim"] is False
    assert decision["accuracy_claim"] is False


def test_gate_fails_closed_on_one_failure_or_wrong_root() -> None:
    cases = _cases()
    observations = [_passing_observation(case) for case in cases]
    observations[0]["semantic_correct"] = 0
    assert successor.gate_arithmetic(observations)["verdict"] == "DIAGNOSE"
    observations[0]["semantic_correct"] = 1
    observations[0]["root_id"] = "wrong-root"
    assert successor.gate_arithmetic(observations)["verdict"] == "DIAGNOSE"


def test_gate_rejects_duplicate_case_ids() -> None:
    cases = _cases()
    observations = [_passing_observation(cases[0]), _passing_observation(cases[1])]
    observations[1]["case_id"] = cases[0]["case_id"]
    with pytest.raises(successor.CatalogMaintenanceSuccessorError, match="duplicate"):
        successor.gate_arithmetic(observations)


@pytest.mark.parametrize("mutation", ["missing", "extra", "non_binary"])
def test_gate_rejects_malformed_observation_schema(mutation: str) -> None:
    case = _cases()[0]
    observation = _passing_observation(case)
    if mutation == "missing":
        del observation["retrieval_error"]
    elif mutation == "extra":
        observation["unexpected"] = 0
    else:
        observation["semantic_correct"] = True
    with pytest.raises(successor.CatalogMaintenanceSuccessorError, match="observation"):
        successor.gate_arithmetic([observation])


def test_gate_rejects_green_score_without_a_matching_skeleton() -> None:
    observation = _passing_observation(_cases()[0])
    observation["skeleton_match"] = False
    with pytest.raises(successor.CatalogMaintenanceSuccessorError, match="inconsistent"):
        successor.gate_arithmetic([observation])


def test_successor_sandbox_denies_project_writes() -> None:
    policy = successor._successor_worker_sandbox_policy(ROOT / "artifacts")
    assert f'(deny file-write* (subpath "{ROOT!s}"))' in policy


def test_successor_output_rejects_symlink_path(tmp_path: Path) -> None:
    link = tmp_path / "link"
    link.symlink_to(ROOT / "artifacts", target_is_directory=True)
    with pytest.raises(successor.CatalogMaintenanceSuccessorError, match="symlink"):
        successor._require_safe_output_dir(link / "nested")


def test_successor_run_directory_is_single_use_and_fixed() -> None:
    freeze = {"run_dir": successor.RUN_OUTPUT_RELATIVE}
    assert (
        successor._frozen_run_dir(freeze, successor.DEFAULT_RUN_DIR)
        == (ROOT / successor.RUN_OUTPUT_RELATIVE).resolve()
    )
    with pytest.raises(successor.CatalogMaintenanceSuccessorError, match="differs"):
        successor._frozen_run_dir(
            freeze, ROOT / "artifacts/catalog-maintenance-successor-v1-replay"
        )
