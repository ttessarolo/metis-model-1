from __future__ import annotations

import json
import subprocess
from copy import deepcopy

import pytest

from metis_model1 import demo_accuracy as demo


def _observation(task_id: str, family: str, passed: bool) -> dict[str, object]:
    return {
        "task_id": task_id,
        "family": family,
        "output_kind": "metis_source",
        "semantic_correct": passed,
        "critical_failure": False,
        "failure_code": None if passed else "semantic_mismatch",
        "invented_identifiers": [],
        "candidate_sha256": "sha256:" + "1" * 64,
        "normalized_sha256": "sha256:" + ("2" if passed else "3") * 64,
        "expected_normalized_sha256": "sha256:" + "2" * 64,
        "peak_metal_gb": 20.0,
    }


def _paired(*, base_failures: set[int], adapter_failures: set[int]):
    base = []
    adapter = []
    for index in range(12):
        family = f"F-{index // 2 + 1}"
        task_id = f"demoacc_task_{index:02d}"
        base.append(_observation(task_id, family, index not in base_failures))
        adapter.append(_observation(task_id, family, index not in adapter_failures))
    return base, adapter


def test_demo_task_manifest_is_pre_output_and_exactly_balanced() -> None:
    manifest, tasks, raw = demo.load_tasks()

    assert manifest["model_outputs_observed"] is False
    assert manifest["authority_scope"] == "public_synthetic_catalog_domain_only"
    assert manifest["generation"] == demo.GENERATION
    assert manifest["thresholds"] == demo.THRESHOLDS
    assert len(tasks) == len({task["task_id"] for task in tasks}) == 12
    assert {
        family: sum(task["family"] == family for task in tasks) for family in demo.FAMILIES
    } == {family: 2 for family in demo.FAMILIES}
    assert sum(task["output_kind"] == "metis_source" for task in tasks) == 8
    assert sum(task["output_kind"] == "json" for task in tasks) == 4
    assert b"demoacc_" in raw
    assert all(
        "catalog public.video" in task.get("input_source", task.get("expected_source", ""))
        for task in tasks
    )


def test_demo_task_contract_rejects_post_output_or_family_drift() -> None:
    manifest, _, _ = demo.load_tasks()
    post_output = deepcopy(manifest)
    post_output["model_outputs_observed"] = True
    with pytest.raises(demo.DemoAccuracyError, match="header"):
        demo.validate_tasks(post_output)

    family_drift = deepcopy(manifest)
    family_drift["tasks"][0]["family"] = "F-2"
    with pytest.raises(demo.DemoAccuracyError, match="family census"):
        demo.validate_tasks(family_drift)


def test_messages_include_current_source_without_target_injection() -> None:
    _, tasks, _ = demo.load_tasks()
    edit = next(task for task in tasks if task["task_id"] == "demoacc_f2_edit_inline4_to_enum4")
    messages = demo.build_messages(edit)

    assert [message["role"] for message in messages] == ["system", "user"]
    assert "Current source:\nmetis 0.43" in messages[1]["content"]
    assert edit["expected_source"].strip() not in messages[1]["content"]


def test_every_task_is_fully_specified_without_full_target_injection() -> None:
    _, tasks, _ = demo.load_tasks()

    assert all(
        task["expected_source"].strip() not in demo.build_messages(task)[1]["content"]
        for task in tasks
        if task["output_kind"] == "metis_source"
    )
    assert all(
        json.dumps(task["expected_json"], sort_keys=True)
        not in demo.build_messages(task)[1]["content"]
        for task in tasks
        if task["output_kind"] == "json"
    )
    f1 = [task for task in tasks if task["family"] == "F-1"]
    assert all("driver opensearch" in task["prompt"] for task in f1)
    f4 = [task for task in tasks if task["family"] == "F-4"]
    assert all("exact controlled code" in task["prompt"] for task in f4)
    f6 = [task for task in tasks if task["family"] == "F-6"]
    assert all("controlled domain_kind vocabulary" in task["prompt"] for task in f6)


def test_json_extraction_accepts_one_object_and_rejects_prose() -> None:
    expected = {"findings": [{"code": "x", "path": "y"}]}

    assert demo._extract_json(json.dumps(expected)) == (expected, None)
    assert demo._extract_json(f"```json\n{json.dumps(expected)}\n```") == (expected, None)
    assert demo._extract_json("answer: {}") == (None, "invalid_json")


def test_source_scoring_is_layout_insensitive_but_identifier_strict() -> None:
    _, tasks, _ = demo.load_tasks()
    task = tasks[0]
    normalized = {"catalogs": [{"name": "public.video", "fields": ["id"]}]}
    truth = {"target": {"normalized_sha256": demo.canonical_hash(normalized)}}
    response = {"text": task["expected_source"], "peak_metal_gb": 19.0}
    score = demo.score_candidate(task, response, truth, lambda _source: (normalized, {}))

    assert score["semantic_correct"] is True
    assert score["critical_failure"] is False
    assert score["invented_identifiers"] == []

    invented = dict(response)
    invented["text"] = response["text"].replace(
        "demoacc_title_f1_01 keyword open",
        "demoacc_title_f1_01 keyword open\n    demoacc_invented keyword",
    )
    rejected = demo.score_candidate(task, invented, truth, lambda _source: (normalized, {}))
    assert rejected["semantic_correct"] is False
    assert rejected["invented_identifiers"] == ["demoacc_invented"]


def test_gate_passes_at_eleven_without_regression() -> None:
    base, adapter = _paired(base_failures={10, 11}, adapter_failures={11})

    decision = demo.gate_arithmetic(base, adapter)

    assert decision["verdict"] == "DEMO_ACCURACY_V1_PASS"
    assert decision["base"]["semantic_correct"] == 10
    assert decision["adapter"]["semantic_correct"] == 11
    assert decision["paired_regressions"] == []
    assert decision["delta_qlora"]["eligible"] is False


def test_gate_accepts_honest_base_adapter_parity() -> None:
    base, adapter = _paired(base_failures={11}, adapter_failures={11})

    decision = demo.gate_arithmetic(base, adapter)

    assert decision["verdict"] == "DEMO_ACCURACY_V1_PASS"
    assert decision["base"]["semantic_correct"] == 11
    assert decision["adapter"]["semantic_correct"] == 11
    assert decision["paired_regressions"] == []


def test_gate_fails_on_one_paired_regression_even_at_eleven() -> None:
    base, adapter = _paired(base_failures={0}, adapter_failures={1})

    decision = demo.gate_arithmetic(base, adapter)

    assert decision["adapter"]["semantic_correct"] == 11
    assert decision["verdict"] == "DEMO_ACCURACY_V1_DIAGNOSE"
    assert decision["paired_regressions"] == ["demoacc_task_01"]


def test_delta_qlora_requires_three_genuine_failures_across_two_families() -> None:
    base, adapter = _paired(base_failures={0, 2, 4}, adapter_failures={0, 2, 4})

    decision = demo.gate_arithmetic(base, adapter)

    assert decision["verdict"] == "DEMO_ACCURACY_V1_DIAGNOSE"
    assert decision["delta_qlora"] == {
        "threshold_met": True,
        "eligible": False,
        "adjudication_required": True,
        "genuine_failure_count": 3,
        "families": ["F-1", "F-2", "F-3"],
        "action": "l0_oracle_adjudication",
    }


def test_truth_receipt_is_self_hashed_and_pre_output_when_present() -> None:
    if not demo.TRUTH_PATH.exists():
        pytest.skip("truth is generated only after static review")
    truth = json.loads(demo.TRUTH_PATH.read_text(encoding="utf-8"))

    demo._validate_self_hash(truth, "truth_sha256")
    assert truth["status"] == "truth_fixed_before_model_output"
    assert truth["model_outputs_observed"] is False
    assert truth["training_input_allowed"] is False
    assert len(truth["tasks"]) == 12


def test_truth_must_equal_a_fresh_pinned_reconstruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = {"status": "truth_fixed_before_model_output", "tasks": []}
    value = {**body, "truth_sha256": demo.canonical_hash(body)}
    monkeypatch.setattr(demo, "build_truth", lambda *_args: value)

    demo._verify_truth_against_pinned_inputs(value, demo.DEFAULT_METIS_ROOT, demo.DEFAULT_NODE)

    drifted_body = {**body, "tasks": [{"task_id": "drift"}]}
    drifted = {**drifted_body, "truth_sha256": demo.canonical_hash(drifted_body)}
    with pytest.raises(demo.DemoAccuracyError, match="reconstruction"):
        demo._verify_truth_against_pinned_inputs(
            drifted, demo.DEFAULT_METIS_ROOT, demo.DEFAULT_NODE
        )


def test_bound_inputs_include_transitive_catalog_oracle_closure() -> None:
    assert {
        "src/metis_model1/catalog_retrieval.py",
        "src/metis_model1/oracles.py",
        "manifests/catalog-retrieval-public-synthetic-v1.json",
        "manifests/catalog-retrieval-execution-v1.json",
        "fixtures/catalog-maintenance/public-synthetic-v1/metis.toml",
        "fixtures/catalog-maintenance/public-synthetic-v1/catalogs/aa-video.metis",
    }.issubset(demo.BOUND_PATHS)


def test_run_roster_rejects_an_extra_directory(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    run_dir = tmp_path / "artifacts/demo-accuracy-v1"
    (run_dir / "base").mkdir(parents=True)
    (run_dir / "adapter").mkdir()
    (run_dir / "base/candidates.jsonl").write_text("{}\n", encoding="utf-8")
    (run_dir / "adapter/candidates.jsonl").write_text("{}\n", encoding="utf-8")
    (run_dir / "report.json").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(demo, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(demo, "RUN_DIR", run_dir)

    assert len(demo._verified_run_file_roster()) == 3
    (run_dir / "extra").mkdir()
    with pytest.raises(demo.DemoAccuracyError, match="roster"):
        demo._verified_run_file_roster()


def test_raw_candidate_rows_are_canonical_ordered_and_metric_bound(tmp_path) -> None:
    _, tasks, _ = demo.load_tasks()
    responses = [
        {
            "request_id": task["task_id"],
            "text": "candidate",
            "peak_metal_gb": 18.5,
        }
        for task in tasks
    ]
    path = tmp_path / "candidates.jsonl"
    path.write_bytes(demo._candidate_lines(tasks, responses))

    assert demo._candidate_responses(path, tasks) == responses

    rows = path.read_text(encoding="utf-8").splitlines()
    first = json.loads(rows[0])
    first["task_id"] = tasks[1]["task_id"]
    rows[0] = json.dumps(first, sort_keys=True, separators=(",", ":"))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(demo.DemoAccuracyError, match="fixed contract"):
        demo._candidate_responses(path, tasks)


def test_run_roster_rejects_a_replaced_root_symlink(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    run_dir = artifact_root / "demo-accuracy-v1"
    run_dir.symlink_to(external, target_is_directory=True)
    monkeypatch.setattr(demo, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(demo, "RUN_DIR", run_dir)

    with pytest.raises(demo.DemoAccuracyError, match="run root"):
        demo._verified_run_file_roster()


def test_run_file_publication_is_anchored_to_a_direct_child(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_dir = tmp_path / "artifacts/demo-accuracy-v1"
    run_dir.mkdir(parents=True)
    monkeypatch.setattr(demo, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(demo, "RUN_DIR", run_dir)
    demo._create_run_children()

    path = demo._write_run_file(run_dir / "base", "candidates.jsonl", b"{}\n")

    assert path.read_bytes() == b"{}\n"
    assert path.stat().st_nlink == 1


def test_freeze_lineage_requires_preoutput_flags_tree_and_ancestor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preimage = "1" * 40
    tree = "2" * 40
    freeze = {
        "status": "frozen_before_model_output",
        "model_outputs_observed": False,
        "training_authorized": False,
        "preimage_commit": preimage,
        "preimage_tree": tree,
    }
    monkeypatch.setattr(
        demo,
        "_git",
        lambda *args, **_kwargs: tree if args == ("rev-parse", f"{preimage}^{{tree}}") else "",
    )
    monkeypatch.setattr(
        demo.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0),
    )

    demo._verify_freeze_lineage(freeze, "3" * 40)

    post_output = {**freeze, "model_outputs_observed": True}
    with pytest.raises(demo.DemoAccuracyError, match="pre-output"):
        demo._verify_freeze_lineage(post_output, "3" * 40)
