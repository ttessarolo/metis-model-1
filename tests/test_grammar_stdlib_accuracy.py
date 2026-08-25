from __future__ import annotations

import json
from copy import deepcopy

import pytest

from metis_model1 import grammar_stdlib_accuracy as d18


def test_materialized_truth_is_preoutput_self_hashed_and_binds_ir() -> None:
    truth = json.loads(d18.TRUTH_PATH.read_text(encoding="utf-8"))
    assert truth["truth_sha256"] == d18.canonical_hash(
        {key: value for key, value in truth.items() if key != "truth_sha256"}
    )
    assert truth["counts"] == {
        "tasks_in": 18,
        "tasks_out": 18,
        "tasks_distinct": 18,
        "gaps": 0,
        "families": {family: 3 for family in d18.FAMILIES},
    }
    assert truth["model_outputs_observed"] is False
    assert truth["semantic_signature_contract"] == d18.SEMANTIC_SIGNATURE_CONTRACT
    assert truth["training_authorized"] is False
    assert truth["delta_qlora_authorized"] is False
    assert len(truth["grammar_stdlib_pin"]["overlay"]["evidence"]) == 8
    ir_task_ids = {
        task["task_id"]
        for task in truth["tasks"]
        if any(
            isinstance(task["target"].get(field), dict)
            and task["target"][field].get("semantic_ir_sha256") is not None
            for field in ("expected", "input", "repaired")
        )
    }
    assert ir_task_ids == {
        "gsl_d18_f1_02",
        "gsl_d18_f2_01",
        "gsl_d18_f2_02",
        "gsl_d18_f3_03",
        "gsl_d18_f4_01",
        "gsl_d18_f5_01",
        "gsl_d18_f6_03",
    }


def test_bound_paths_include_transitive_snapshot_inputs() -> None:
    assert {
        "manifests/catalog-maintenance-pin-v1.json",
        "schemas/catalog-maintenance-pin.schema.json",
        "src/metis_model1/catalog_retrieval.py",
    }.issubset(d18.BOUND_PATHS)
    assert len(d18.BOUND_PATHS) == 21


def test_materialized_freeze_is_zero_output_and_binds_the_published_preimage() -> None:
    freeze = json.loads(d18.FREEZE_PATH.read_text(encoding="utf-8"))
    assert freeze["freeze_sha256"] == d18.canonical_hash(
        {key: value for key, value in freeze.items() if key != "freeze_sha256"}
    )
    assert freeze["preimage_commit"] == "4c0b32a03b5159e33f9b2c6955ffbc85e5c9e5f9"
    assert freeze["preimage_tree"] == "d472c02b1993fefb60504c023f5af183d9aa7595"
    assert freeze["truth_sha256"] == (
        "sha256:0dff3f9279b00d50b3d7d544e0932bf7dcb02f3f26cd2608df2eae5b1048a542"
    )
    assert freeze["semantic_signature_contract"] == d18.SEMANTIC_SIGNATURE_CONTRACT
    assert [item["path"] for item in freeze["bound_inputs"]] == list(d18.BOUND_PATHS)
    assert len(freeze["bound_inputs"]) == 21
    assert freeze["model_outputs_observed"] is False
    assert freeze["training_authorized"] is False
    assert freeze["delta_qlora_authorized"] is False
    # The committed freeze records its historical pre-output state.  Once that
    # exact seal is consumed, current run presence belongs to run/recovery gates.
    assert freeze["run_dir"] == "artifacts/grammar-stdlib-accuracy/d18/d18-v1-20260825"


def _task(
    task_id: str,
    family: str,
    mode: str,
    *,
    top_levels: list[str],
    members: list[str],
    settings: list[str],
) -> dict[str, object]:
    value: dict[str, object] = {
        "task_id": task_id,
        "family": family,
        "kind": d18.TASK_KINDS[family],
        "task_mode": mode,
        "authority_tier": d18.TASK_TIERS[family],
        "prompt": "Public synthetic prompt.",
        "oracle": {
            "mode": "source",
            "input_status": "pinned_oracle_required_before_truth",
            "input_failure_kind": None,
            "diagnostic_substrings": [],
        },
        "coverage": {
            "top_levels": top_levels,
            "stdlib_members": members,
            "stdlib_settings": settings,
        },
        "provenance_roots": {
            "independent": f"gsl_d18_ind_{task_id}",
            "template": f"gsl_d18_tpl_{task_id}",
        },
        "model_outputs_observed": False,
        "training_input_allowed": False,
        "training_label_eligible": False,
    }
    if mode == "source_output":
        value["expected_source"] = "metis 0.43\nendpoint synthetic { }"
    else:
        value["expected_json"] = {"classification": "ok"}
    return value


def _manifest() -> dict[str, object]:
    top_levels = list(sorted(d18.TOP_LEVELS))
    members = list(sorted(d18.STDLIB_MEMBERS))
    tasks = [
        _task(
            f"gsl_d18_f{family}_{number:02d}",
            f"F-{family}",
            "source_output" if number <= 2 else "exact_json_review",
            top_levels=[top_levels[(family - 1) * 3 + number - 1]]
            if (family - 1) * 3 + number - 1 < len(top_levels)
            else [],
            members=[members[(family - 1) * 3 + number - 1]]
            if (family - 1) * 3 + number - 1 < len(members)
            else [],
            settings=["time.timezone"] if family == 1 and number == 1 else [],
        )
        for family in range(1, 7)
        for number in range(1, 4)
    ]
    return {
        "schema_version": 2,
        "roster_id": "gsl_d18_public_synthetic_v2",
        "provenance": {
            "kind": "public_synthetic",
            "namespace": "gsl_d18",
            "pin_revision": "5e112f9148f40e7e792052e896c5a9efe8eaf0a2",
            "language_version": "0.43",
            "source_validation": "pinned_oracle_required_before_truth",
            "model_outputs_observed": False,
            "training_input_allowed": False,
        },
        "tasks": tasks,
    }


def _observation(task_id: str, family: str, passed: bool) -> dict[str, object]:
    authority = d18.TASK_TIERS[family]
    automatic = authority == "pinned_oracle_required"
    return {
        "task_id": task_id,
        "family": family,
        "task_mode": "source_output",
        "authority_tier": d18.TASK_TIERS[family],
        "independent_root": f"gsl_d18_root_{task_id}",
        "mechanical_match": passed,
        "semantic_correct": passed if automatic else None,
        "critical_failure": False,
        "failure_code": (
            None
            if passed
            else "semantic_mismatch"
            if automatic
            else "human_review_mismatch"
            if authority == "human_review_required"
            else "diagnostic_review_mismatch"
        ),
        "candidate_sha256": "sha256:" + "1" * 64,
        "observed": None,
        "peak_metal_gb": 2.0,
    }


def _paired(failures: set[int]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    base, adapter = [], []
    for index in range(18):
        family = f"F-{index // 3 + 1}"
        task_id = f"gsl_d18_case_{index:02d}"
        base.append(_observation(task_id, family, True))
        adapter.append(_observation(task_id, family, index not in failures))
    return base, adapter


def test_task_contract_requires_eighteen_three_per_family_and_twelve_source() -> None:
    tasks = d18.validate_tasks(_manifest())
    assert len(tasks) == 18
    drifted = deepcopy(_manifest())
    drifted["tasks"][0]["task_mode"] = "exact_json_review"
    drifted["tasks"][0].pop("expected_source")
    drifted["tasks"][0]["expected_json"] = {"x": 1}
    with pytest.raises(d18.GrammarStdlibAccuracyError, match="task-mode census"):
        d18.validate_tasks(drifted)


def test_task_contract_rejects_oracle_and_global_root_drift() -> None:
    malformed = deepcopy(_manifest())
    malformed["tasks"][0]["oracle"]["target"] = "forbidden-in-source-mode"
    with pytest.raises(d18.GrammarStdlibAccuracyError, match="oracle specification"):
        d18.validate_tasks(malformed)

    duplicate_root = deepcopy(_manifest())
    duplicate_root["tasks"][1]["provenance_roots"]["independent"] = duplicate_root["tasks"][0][
        "provenance_roots"
    ]["independent"]
    with pytest.raises(d18.GrammarStdlibAccuracyError, match="globally disjoint"):
        d18.validate_tasks(duplicate_root)


def test_messages_do_not_inject_the_target() -> None:
    task = _task(
        "gsl_d18_f1_01",
        "F-1",
        "source_output",
        top_levels=list(d18.TOP_LEVELS),
        members=list(d18.STDLIB_MEMBERS),
        settings=["time.timezone"],
    )
    task["input_source"] = "metis 0.43\nendpoint before { }"
    messages = d18.build_messages(task)
    assert messages[0]["role"] == "system"
    assert task["expected_source"] not in messages[1]["content"]
    assert "Current Metis source" in messages[1]["content"]
    assert "Retrieved pinned reference" in messages[0]["content"]
    assert "time.fractional_second" in messages[0]["content"]
    assert "std.codec.decode" in messages[0]["content"]


def test_gate_never_authorizes_training_or_delta() -> None:
    base, adapter = _paired(set())
    decision = d18.gate_arithmetic(base, adapter)
    assert decision["verdict"] == "GRAMMAR_STDLIB_D18_REVIEW_REQUIRED"
    assert decision["authority_tier"] == "diagnostic_only"
    assert decision["training_authorized"] is False
    assert decision["delta_qlora"]["authorized"] is False
    assert decision["adapter"]["automatic_semantic_denominator"] == 9
    assert decision["adapter"]["human_review_pending"] == 6
    assert decision["adapter"]["diagnostic_only"] == 3
    assert decision["adapter"]["nonautomatic_denominator"] == 9


def test_gate_diagnoses_paired_regression_and_marks_human_review() -> None:
    base, adapter = _paired({0, 3, 6})
    decision = d18.gate_arithmetic(base, adapter)
    assert decision["verdict"] == "GRAMMAR_STDLIB_D18_DIAGNOSE"
    assert decision["paired_regressions"] == [
        "gsl_d18_case_00",
        "gsl_d18_case_03",
        "gsl_d18_case_06",
    ]
    assert decision["delta_qlora"] == {
        "threshold_met": True,
        "authorized": False,
        "authority_tier": "human_review_required",
        "action": "l0_adjudication_required",
    }


def test_human_review_failures_cannot_make_delta_automatic() -> None:
    base, adapter = _paired({12, 13, 14})
    decision = d18.gate_arithmetic(base, adapter)
    assert decision["delta_qlora"]["threshold_met"] is False
    assert decision["delta_qlora"]["authorized"] is False
    assert decision["review_required"]["authority_tier"] == "human_review_required"


def test_diagnostic_review_mismatches_do_not_enter_delta_arithmetic() -> None:
    base, adapter = _paired({0, 9, 10, 11})
    decision = d18.gate_arithmetic(base, adapter)
    assert decision["delta_qlora"]["threshold_met"] is False
    assert decision["delta_qlora"]["authorized"] is False


def test_source_scoring_uses_oracle_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    task = _task(
        "gsl_d18_f1_01",
        "F-1",
        "source_output",
        top_levels=list(d18.TOP_LEVELS),
        members=list(d18.STDLIB_MEMBERS),
        settings=["time.timezone"],
    )
    envelope = {
        "result": {
            "status": "ok",
            "ast": {"inventory": {"$type": "Model", "elements": []}},
            "diagnostics": {category: [] for category in ("parser", "link", "validation", "all")},
            "endpoint": {"name": None, "count": 0},
            "ir": {"value": None},
            "failure": None,
        },
        "evidence": {},
    }
    expected = d18._oracle_signature(envelope, task)
    monkeypatch.setattr(d18, "_extract_source", lambda _text: ("metis 0.43", None))
    monkeypatch.setattr(d18, "_oracle_task", lambda *_args: envelope)
    score = d18.score_candidate(
        task,
        {"text": "ignored", "peak_metal_gb": 1.0},
        {"target": {"expected": expected}},
        d18.DEFAULT_METIS_ROOT,
        d18.DEFAULT_NODE,
    )
    assert score["semantic_correct"] is True
    assert score["mechanical_match"] is True
    assert score["failure_code"] is None


def test_semantic_oracle_signature_ignores_layout_but_retains_meaning() -> None:
    task = _task(
        "gsl_d18_f1_01",
        "F-1",
        "source_output",
        top_levels=["Endpoint"],
        members=["time.hour"],
        settings=[],
    )
    task["oracle"] = {
        "mode": "endpoint",
        "target": "gsl_d18.panel",
        "input_status": "pinned_oracle_required_before_truth",
        "input_failure_kind": None,
        "diagnostic_substrings": [],
    }

    def envelope(offset: int, *, target: str = "gsl_d18.video", literal: int = 1):
        diagnostic = {
            "filename": "d18/gsl_d18_f1_01.metis",
            "message": "stable warning",
            "severity": 2,
            "code": "stable-code",
            "range": {
                "start": {"line": offset, "character": 0},
                "end": {"line": offset, "character": 4},
            },
        }
        return {
            "result": {
                "status": "ok",
                "ast": {
                    "inventory": {
                        "$type": "Model",
                        "$containerIndex": offset,
                        "_range": diagnostic["range"],
                        "elements": [
                            {
                                "$type": "Endpoint",
                                "$containerProperty": "elements",
                                "name": "gsl_d18.panel",
                                "limit": literal,
                                "catalog": {
                                    "$refText": target,
                                    "$refNode": {"offset": offset},
                                    "_ref": {
                                        "$type": "Catalog",
                                        "name": target,
                                        "_range": diagnostic["range"],
                                    },
                                },
                            }
                        ],
                    }
                },
                "diagnostics": {
                    "parser": [],
                    "link": [],
                    "validation": [diagnostic],
                    "all": [diagnostic],
                },
                "endpoint": {"name": "gsl_d18.panel", "count": 1},
                "ir": {
                    "value": {
                        "node": "Endpoint",
                        "provenance": {"file": "gsl_d18_f1_01.metis", "line": offset},
                        "take": literal,
                    }
                },
                "failure": None,
            },
            "evidence": {},
        }

    baseline = d18._oracle_signature(envelope(1), task)
    assert baseline == d18._oracle_signature(envelope(20), task)
    assert baseline != d18._oracle_signature(envelope(1, literal=2), task)
    assert baseline != d18._oracle_signature(envelope(1, target="gsl_d18.other"), task)


def test_semantic_diagnostics_are_order_independent_and_multiplicity_sensitive() -> None:
    def row(message: str) -> dict[str, object]:
        return {
            "filename": "d18/case.metis",
            "message": message,
            "severity": 2,
            "code": "warning",
            "range": {
                "start": {"line": 1, "character": 0},
                "end": {"line": 1, "character": 1},
            },
        }

    first, second = row("first"), row("second")
    left = {"parser": [], "link": [], "validation": [first, second], "all": [first, second]}
    reordered = {
        "parser": [],
        "link": [],
        "validation": [second, first],
        "all": [second, first],
    }
    duplicated = {
        "parser": [],
        "link": [],
        "validation": [first, second, second],
        "all": [first, second, second],
    }
    assert d18._semantic_diagnostics(left) == d18._semantic_diagnostics(reordered)
    assert d18._semantic_diagnostics(left) != d18._semantic_diagnostics(duplicated)
    with pytest.raises(d18.GrammarStdlibAccuracyError, match="phase partition"):
        d18._semantic_diagnostics(
            {"parser": [], "link": [], "validation": [first], "all": [second]}
        )


def test_pinned_oracle_semantic_signature_is_layout_invariant() -> None:
    _manifest, tasks, _raw = d18.load_tasks()
    by_id = {task["task_id"]: task for task in tasks}
    source_task = by_id["gsl_d18_f3_02"]
    endpoint_task = by_id["gsl_d18_f1_02"]
    source = source_task["expected_source"]
    endpoint = endpoint_task["expected_source"]

    with d18.oracle.grammar_stdlib_oracle_session(
        metis_root=d18.DEFAULT_METIS_ROOT, node_path=d18.DEFAULT_NODE
    ) as session:
        source_base = d18._oracle_task(
            source_task, source, d18.DEFAULT_METIS_ROOT, d18.DEFAULT_NODE, session=session
        )
        source_layout = d18._oracle_task(
            source_task,
            source.replace("metis 0.43\n", "metis 0.43\r\n\r\n"),
            d18.DEFAULT_METIS_ROOT,
            d18.DEFAULT_NODE,
            session=session,
        )
        endpoint_base = d18._oracle_task(
            endpoint_task, endpoint, d18.DEFAULT_METIS_ROOT, d18.DEFAULT_NODE, session=session
        )
        endpoint_layout = d18._oracle_task(
            endpoint_task,
            endpoint.replace("\nendpoint", "\n\nendpoint"),
            d18.DEFAULT_METIS_ROOT,
            d18.DEFAULT_NODE,
            session=session,
        )
        endpoint_mutation = d18._oracle_task(
            endpoint_task,
            endpoint.replace("time.hour >= 9", "time.hour >= 10"),
            d18.DEFAULT_METIS_ROOT,
            d18.DEFAULT_NODE,
            session=session,
        )

    assert source_base["evidence"]["ast_sha256"] != source_layout["evidence"]["ast_sha256"]
    assert (
        source_base["evidence"]["diagnostics_sha256"]
        != source_layout["evidence"]["diagnostics_sha256"]
    )
    assert d18._oracle_signature(source_base, source_task) == d18._oracle_signature(
        source_layout, source_task
    )
    assert endpoint_base["evidence"]["ir_sha256"] != endpoint_layout["evidence"]["ir_sha256"]
    assert d18._oracle_signature(endpoint_base, endpoint_task) == d18._oracle_signature(
        endpoint_layout, endpoint_task
    )
    assert d18._oracle_signature(endpoint_base, endpoint_task) != d18._oracle_signature(
        endpoint_mutation, endpoint_task
    )


def test_json_review_scoring_is_nonautomatic_and_exact_contract() -> None:
    task = _task(
        "gsl_d18_f4_01",
        "F-4",
        "exact_json_review",
        top_levels=["Endpoint"],
        members=["time.hour"],
        settings=[],
    )
    expected = {
        "classification": "diagnostic_only",
        "diagnostic_substrings": ["non dichiara `needs time`"],
        "training_label_eligible": False,
    }
    task["expected_json"] = expected
    truth = {"target": {"expected_json_sha256": d18.canonical_hash(expected)}}

    contract_drift = d18.score_candidate(
        task,
        {"text": json.dumps(expected | {"comment": "extra"}), "peak_metal_gb": 1.0},
        truth,
        d18.DEFAULT_METIS_ROOT,
        d18.DEFAULT_NODE,
    )
    assert contract_drift["mechanical_match"] is False
    assert contract_drift["semantic_correct"] is None
    assert contract_drift["failure_code"] == "diagnostic_review_mismatch"
    assert contract_drift["critical_failure"] is False

    semantic_drift = d18.score_candidate(
        task,
        {
            "text": json.dumps(expected | {"diagnostic_substrings": ["wrong"]}),
            "peak_metal_gb": 1.0,
        },
        truth,
        d18.DEFAULT_METIS_ROOT,
        d18.DEFAULT_NODE,
    )
    assert semantic_drift["mechanical_match"] is False
    assert semantic_drift["semantic_correct"] is None
    assert semantic_drift["failure_code"] == "diagnostic_review_mismatch"
    assert semantic_drift["critical_failure"] is False

    format_drift = d18.score_candidate(
        task,
        {"text": "not JSON", "peak_metal_gb": 1.0},
        truth,
        d18.DEFAULT_METIS_ROOT,
        d18.DEFAULT_NODE,
    )
    assert format_drift["mechanical_match"] is False
    assert format_drift["semantic_correct"] is None
    assert format_drift["failure_code"] == "json_format_mismatch"
    assert format_drift["critical_failure"] is False


def test_run_id_cannot_escape_ignored_root() -> None:
    assert d18._run_dir("run_01") == d18.RUN_ROOT / "run_01"
    with pytest.raises(d18.GrammarStdlibAccuracyError, match="run_id"):
        d18._run_dir("../escape")


def test_evidence_rejects_extra_ignored_run_artifact(tmp_path) -> None:
    project_root = tmp_path / "project"
    artifacts = project_root / "artifacts"
    run_root = artifacts / "grammar-stdlib-accuracy/d18"
    run_dir = run_root / "run"
    artifacts.mkdir(parents=True)
    run_dir.parent.mkdir(parents=True)
    run_dir.mkdir()
    (run_dir / "base").mkdir()
    (run_dir / "adapter").mkdir()
    for path in (
        run_dir / "base/candidates.jsonl",
        run_dir / "adapter/candidates.jsonl",
        run_dir / "report.json",
    ):
        path.write_text("{}\n", encoding="utf-8")
    original_project, original_root = d18.PROJECT_ROOT, d18.RUN_ROOT
    d18.PROJECT_ROOT, d18.RUN_ROOT = project_root, run_root
    try:
        assert len(d18._verify_run_roster(run_dir)) == 3
    finally:
        d18.PROJECT_ROOT, d18.RUN_ROOT = original_project, original_root
    (run_dir / "unexpected.txt").write_text("x", encoding="utf-8")
    d18.PROJECT_ROOT, d18.RUN_ROOT = project_root, run_root
    try:
        with pytest.raises(d18.GrammarStdlibAccuracyError, match="roster"):
            d18._verify_run_roster(run_dir)
    finally:
        d18.PROJECT_ROOT, d18.RUN_ROOT = original_project, original_root


def test_safe_publisher_is_exclusive_and_requires_direct_ancestors(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    artifacts = project_root / "artifacts"
    artifacts.mkdir(parents=True)
    run_root = artifacts / "grammar-stdlib-accuracy/d18"
    run_dir = run_root / "run"
    monkeypatch.setattr(d18, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(d18, "RUN_ROOT", run_root)

    d18._prepare_run_root(run_dir)
    published = d18._write_run_file(run_dir, run_dir / "base", "candidates.jsonl", b"{}\n")
    assert published.read_bytes() == b"{}\n"
    assert published.stat().st_nlink == 1
    with pytest.raises(d18.GrammarStdlibAccuracyError, match="cannot publish"):
        d18._write_run_file(run_dir, run_dir / "base", "candidates.jsonl", b"{}\n")


def test_worker_response_roster_is_checked_even_if_worker_helper_changes() -> None:
    tasks = [{"task_id": f"gsl_d18_case_{item}"} for item in range(18)]
    rows = [{"request_id": task["task_id"], "text": "ok", "peak_metal_gb": 1.0} for task in tasks]
    d18._verify_worker_responses(tasks, rows)
    rows[3] = {**rows[3], "request_id": "wrong"}
    with pytest.raises(d18.GrammarStdlibAccuracyError, match="roster"):
        d18._verify_worker_responses(tasks, rows)
