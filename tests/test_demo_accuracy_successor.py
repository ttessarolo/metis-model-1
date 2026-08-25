from __future__ import annotations

import json
import subprocess
from copy import deepcopy

import pytest

from metis_model1 import demo_accuracy as core
from metis_model1 import demo_accuracy_successor as successor


def _sealed_v2_freeze() -> dict[str, object]:
    return {
        "schema_version": 1,
        "freeze_id": core.FREEZE_ID,
        "status": "frozen_before_model_output",
        "authority_scope": core.EXECUTION_AUTHORITY_SCOPE,
        "preimage_commit": "1" * 40,
        "preimage_tree": "2" * 40,
        "remote": "origin",
        "remote_ref": "refs/heads/codex/test",
        "bound_inputs": [],
        "truth_sha256": "sha256:" + "3" * 64,
        "tasks_file_sha256": "sha256:" + "4" * 64,
        "runtime": {},
        "identities": {},
        "sandbox_policy_sha256": core.canonical_hash(core.qlora.EVALUATION_SANDBOX_POLICY),
        "generation": core.GENERATION,
        "thresholds": core.THRESHOLDS,
        "counts": {
            "tasks_in": 12,
            "tasks_out": 12,
            "tasks_distinct": 12,
            "gaps": 0,
            "families": {family: 2 for family in core.FAMILIES},
        },
        "run_dir": str(core.RUN_DIR.relative_to(core.PROJECT_ROOT)),
        "model_outputs_observed": False,
        "training_authorized": False,
        "nonclaims": core.NONCLAIMS,
        "freeze_sha256": "sha256:" + "5" * 64,
    }


def test_successor_prompt_is_generic_and_repairs_only_observed_syntax() -> None:
    prompt = successor.SUCCESSOR_SOURCE_SYSTEM_PROMPT

    assert "brace-delimited blocks" in prompt
    assert "Newlines and indentation never" in prompt
    assert 'index "<index-name>"' in prompt
    assert "demoacc_" not in prompt
    assert "public.video" not in prompt


def test_successor_configuration_is_complete_and_restores_v1() -> None:
    before = {name: getattr(core, name) for name in successor._OVERRIDES}

    with successor.successor_configuration():
        assert core.BENCHMARK_ID == "demo-accuracy-v2"
        assert core.TASK_ID_PREFIX == "demoacc_v2_"
        assert core.TRUTH_ID.endswith("/v2")
        assert core.FREEZE_ID.endswith("/v2")
        assert core.EVIDENCE_ID.endswith("/v2")
        assert core.PASS_VERDICT == "DEMO_ACCURACY_V2_PASS"
        assert core.RUN_DIR == successor.V2_RUN_DIR
        assert core.IDENTIFIER_RE.fullmatch("demoacc_v2_status_f1_01")

    assert {name: getattr(core, name) for name in successor._OVERRIDES} == before


def test_successor_manifest_is_fresh_balanced_and_v2_specific() -> None:
    with successor.successor_configuration():
        manifest, tasks, raw = core.load_tasks()

    assert manifest["benchmark_id"] == "demo-accuracy-v2"
    assert manifest["authority_scope"] == "public_synthetic_catalog_domain_successor_only"
    assert len(tasks) == len({task["task_id"] for task in tasks}) == 12
    assert all(task["task_id"].startswith("demoacc_v2_") for task in tasks)
    assert all(task["source"].startswith("public-synthetic/demoacc/v2/") for task in tasks)
    assert b"demoacc_v2_" in raw
    assert not any(
        task["task_id"].encode() in successor.V1_TASKS_PATH.read_bytes() for task in tasks
    )


def test_successor_binds_engine_wrapper_tests_and_v1_freshness_source() -> None:
    required = {
        "fixtures/demo-accuracy-v2/tasks.json",
        "manifests/demo-accuracy-truth-v2.json",
        "fixtures/demo-accuracy-v1/tasks.json",
        "src/metis_model1/demo_accuracy.py",
        "src/metis_model1/demo_accuracy_successor.py",
        "tests/test_demo_accuracy.py",
        "tests/test_demo_accuracy_successor.py",
    }

    assert required.issubset(successor.SUCCESSOR_BOUND_PATHS)
    assert len(successor.SUCCESSOR_BOUND_PATHS) == len(set(successor.SUCCESSOR_BOUND_PATHS))
    assert "manifests/demo-accuracy-truth-v1.json" not in successor.SUCCESSOR_BOUND_PATHS


def test_successor_truth_is_self_hashed_and_binds_configured_messages() -> None:
    truth = json.loads(successor.V2_TRUTH_PATH.read_text(encoding="utf-8"))

    with successor.successor_configuration():
        _, tasks, raw = core.load_tasks()
        core._validate_self_hash(truth, "truth_sha256")
        by_id = {item["task_id"]: item for item in truth["tasks"]}
        assert truth["truth_id"] == core.TRUTH_ID
        assert truth["tasks_file_sha256"] == core.raw_hash(raw)
        assert all(
            by_id[task["task_id"]]["messages_sha256"]
            == core.canonical_hash(core.build_messages(task))
            for task in tasks
        )
        assert all(
            task["expected_source"].strip() not in core.build_messages(task)[1]["content"]
            for task in tasks
            if task["output_kind"] == "metis_source"
        )
        assert all(
            json.dumps(task["expected_json"], sort_keys=True)
            not in core.build_messages(task)[1]["content"]
            for task in tasks
            if task["output_kind"] == "json"
        )

    assert truth["model_outputs_observed"] is False
    assert truth["training_input_allowed"] is False


@pytest.mark.parametrize(
    ("field", "bad_value"),
    (
        ("freeze_id", "demo-accuracy-freeze/v1"),
        ("authority_scope", "public_synthetic_catalog_domain_mac_demo_accuracy_only"),
        ("run_dir", "artifacts/demo-accuracy-v1"),
    ),
)
def test_successor_rejects_v1_freeze_identity(
    field: str,
    bad_value: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with successor.successor_configuration():
        value = _sealed_v2_freeze()
        value[field] = bad_value
        monkeypatch.setattr(
            core,
            "_git",
            lambda *args, **_kwargs: (
                "2" * 40 if args == ("rev-parse", f"{'1' * 40}^{{tree}}") else ""
            ),
        )
        monkeypatch.setattr(
            core.subprocess,
            "run",
            lambda *_args, **_kwargs: subprocess.CompletedProcess([], 0),
        )

        with pytest.raises(core.DemoAccuracyError, match="pre-output seal"):
            core._verify_freeze_lineage(value, "6" * 40)


@pytest.mark.parametrize(
    "target",
    (
        "src/metis_model1/demo_accuracy_successor.py",
        "fixtures/demo-accuracy-v1/tasks.json",
    ),
)
def test_bound_input_mutation_blocks_successor(
    target: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with successor.successor_configuration():
        records = [
            {"path": path, "bytes": 1, "sha256": "sha256:" + "1" * 64, "git_blob_oid": "a"}
            for path in core.BOUND_PATHS
        ]

        def tracked(path: str) -> dict[str, object]:
            record = next(item for item in records if item["path"] == path)
            if path == target:
                return {**record, "sha256": "sha256:" + "2" * 64}
            return record

        monkeypatch.setattr(core, "_tracked_record", tracked)
        with pytest.raises(core.DemoAccuracyError, match="bound input changed"):
            core._verify_bound_inputs(records)


def test_v2_verdict_does_not_relabel_as_v1() -> None:
    with successor.successor_configuration():
        observations = []
        for index in range(12):
            family = f"F-{index // 2 + 1}"
            observations.append(
                {
                    "task_id": f"demoacc_v2_task_{index}",
                    "family": family,
                    "semantic_correct": True,
                    "critical_failure": False,
                    "invented_identifiers": [],
                    "failure_code": None,
                    "peak_metal_gb": 1.0,
                }
            )
        decision = core.gate_arithmetic(deepcopy(observations), deepcopy(observations))

    assert decision["verdict"] == "DEMO_ACCURACY_V2_PASS"
