"""Unit contracts for the dedicated, held-out T30 runner.

The public fixture is intentionally authored by a separate blind lane.  These
tests exercise only the evaluator's fixed contract and do not run a model or a
Metis oracle checkout.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

import pytest

from metis_model1 import grammar_stdlib_t30 as t30


def _task(number: int, family: str) -> dict[str, object]:
    coverage = {"top_levels": [], "stdlib_members": [], "stdlib_settings": []}
    top = sorted(t30.TOP_LEVELS)
    member = sorted(t30.STDLIB_MEMBERS)
    if number < len(top):
        coverage["top_levels"] = [top[number]]
    if number < len(member):
        coverage["stdlib_members"] = [member[number]]
    if number == 0:
        coverage["stdlib_settings"] = ["time.timezone"]
    result: dict[str, object] = {
        "task_id": f"gsl_t30_{family.lower().replace('-', '')}_{number:02d}",
        "family": family,
        "kind": t30.TASK_KINDS[family],
        "task_mode": t30.TASK_FAMILY_MODES[family],
        "authority_tier": t30.TASK_TIERS[family],
        "prompt": f"Held-out public synthetic task {family}/{number}.",
        "oracle": {
            "mode": "source",
            "input_status": "pinned_oracle_required_before_truth",
            "input_failure_kind": None,
            "diagnostic_substrings": [],
        },
        "coverage": coverage,
        "provenance_roots": {
            "independent": f"gsl_t30_ind_{family}_{number}",
            "template": f"gsl_t30_tpl_{family}_{number}",
        },
        "model_outputs_observed": False,
        "training_input_allowed": False,
        "delta_qlora_input_allowed": False,
        "training_label_eligible": False,
    }
    if result["task_mode"] == "source_output":
        result["expected_source"] = "metis 0.43\nendpoint heldout { }"
    else:
        result["expected_json"] = {"classification": "held_out"}
    return result


def _manifest() -> dict[str, object]:
    rows = [_task(number, family) for family in t30.FAMILIES for number in range(5)]
    # Complete all denominators without relying on task order.
    rows[0]["coverage"] = {
        "top_levels": sorted(t30.TOP_LEVELS),
        "stdlib_members": sorted(t30.STDLIB_MEMBERS),
        "stdlib_settings": sorted(t30.STDLIB_SETTINGS),
    }
    return {
        "schema_version": 1,
        "roster_id": "gsl_t30_public_synthetic_v1",
        "policy_id": "grammar-stdlib-accuracy-t30-policy/v1",
        "benchmark_id": t30.BENCHMARK_ID,
        "provenance": {
            "kind": "public_synthetic",
            "namespace": "gsl_t30",
            "pin_revision": "5e112f9148f40e7e792052e896c5a9efe8eaf0a2",
            "language_version": "0.43",
            "source_validation": "pinned_oracle_required_before_truth",
            "model_outputs_observed": False,
            "training_input_allowed": False,
            "delta_qlora_input_allowed": False,
        },
        "tasks": rows,
    }


def _observation(
    task_id: str, family: str, *, automatic: bool, ok: bool = True
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "family": family,
        "task_mode": t30.TASK_FAMILY_MODES[family],
        "authority_tier": t30.TASK_TIERS[family],
        "independent_root": f"root-{task_id}",
        "mechanical_match": ok,
        "semantic_correct": ok if automatic else None,
        "final_human_review_required": family in t30.FINAL_HUMAN_REVIEW,
        "final_human_review_kind": t30.FINAL_HUMAN_REVIEW.get(family),
        "critical_failure": False,
        "failure_code": None if ok else "semantic_mismatch",
        "candidate_sha256": "sha256:" + "a" * 64,
        "observed": None,
        "observed_coverage": {
            "top_levels": [],
            "stdlib_members": [],
            "stdlib_settings": [],
        },
        "peak_metal_gb": 1.0,
    }


def _observations() -> list[dict[str, object]]:
    return [
        _observation(
            f"gsl_t30_{family.lower().replace('-', '')}_{number:02d}",
            family,
            automatic=family in {"F-1", "F-2", "F-3", "F-4"},
        )
        for family in t30.FAMILIES
        for number in range(5)
    ]


def test_source_contains_no_training_dataset_optimizer_or_promotion_path() -> None:
    source = Path(t30.__file__).read_text(encoding="utf-8")
    assert "_bounded_worker" in source  # the one sealed inference primitive
    assert 'training_authorized": False' in source
    assert 'delta_qlora_authorized": False' in source
    assert "mlx_lm.lora" not in source
    assert "train(" not in source
    assert "verify_adapter_off_restore_receipt(" not in source


def test_exact_thirty_five_per_family_taxonomy_and_coverage() -> None:
    tasks = t30.validate_tasks(_manifest())
    assert len(tasks) == 30
    assert {task["family"] for task in tasks} == set(t30.FAMILIES)
    assert {task["authority_tier"] for task in tasks if task["family"] == "F-4"} == {
        "pinned_review_oracle_required"
    }
    assert {task["authority_tier"] for task in tasks if task["family"] in {"F-5", "F-6"}} == {
        "human_review_required"
    }
    assert {task["task_mode"] for task in tasks if task["family"] == "F-4"} == {"exact_json_review"}
    assert {task["task_mode"] for task in tasks if task["family"] == "F-5"} == {"source_output"}


def test_blind_t30_fixture_and_ratified_policy_match_the_runner_contract() -> None:
    _manifest, tasks, _raw = t30.load_tasks()
    policy, _policy_raw = t30._policy()
    assert len(tasks) == 30
    assert {family: sum(task["family"] == family for task in tasks) for family in t30.FAMILIES} == {
        family: 5 for family in t30.FAMILIES
    }
    assert policy["one_shot"]["attempt_nonce"] == t30.ATTEMPT_NONCE
    assert policy["one_shot"]["partial_run_disposition"] == "permanent_stop_no_recovery_no_retry"
    assert policy["roster"]["human_review_task_ids_expected"] == 15


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value["tasks"].pop(), "thirty"),
        (lambda value: value["tasks"][0].__setitem__("task_id", "gsl_d18_overlap"), "identity"),
        (
            lambda value: value["tasks"][0].__setitem__("authority_tier", "human_review_required"),
            "taxonomy",
        ),
        (
            lambda value: value["tasks"][0]["provenance_roots"].__setitem__(
                "independent", "gsl_t30_tpl_F-1_0"
            ),
            "roots",
        ),
    ],
)
def test_roster_mutations_fail_closed(mutate: object, message: str) -> None:
    value = deepcopy(_manifest())
    mutate(value)  # type: ignore[operator]
    with pytest.raises(t30.GrammarStdlibT30Error, match=message):
        t30.validate_tasks(value)


def test_disjointness_rejects_d18_task_message_and_semantic_overlap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tasks = t30.validate_tasks(_manifest())
    truth = {
        "tasks": [
            {
                "task_id": row["task_id"],
                "target": {"expected_json_sha256": f"sha256:{index:064x}"},
            }
            for index, row in enumerate(tasks)
        ]
    }
    d18_task = dict(tasks[0])
    d18_task["task_id"] = "gsl_d18_other"
    d18_truth = {
        "tasks": [
            {
                "task_id": "gsl_d18_other",
                "target": {
                    "expected_json_sha256": truth["tasks"][0]["target"]["expected_json_sha256"]
                },
            }
        ]
    }
    monkeypatch.setattr(t30.d18, "load_tasks", lambda: ({}, [d18_task], b""))
    monkeypatch.setattr(t30.d18, "_load", lambda *_args: (d18_truth, b""))
    monkeypatch.setattr(t30.d18, "build_messages", lambda _task: [{"role": "u", "content": "d18"}])
    monkeypatch.setattr(
        t30, "build_messages", lambda task: [{"role": "u", "content": task["task_id"]}]
    )
    with pytest.raises(t30.GrammarStdlibT30Error, match="root|semantic"):
        t30._assert_disjoint(tasks, truth)


def test_gate_arithmetic_preregisters_automatic_and_human_boundaries() -> None:
    base = _observations()
    adapter = _observations()
    decision = t30.gate_arithmetic(base, adapter)
    assert decision["verdict"] == "GRAMMAR_STDLIB_T30_REVIEW_REQUIRED"
    assert decision["adapter"]["automatic"] == {"correct": 20, "denominator": 20}
    assert decision["review_required"]["count"] == 15
    assert decision["gates"]["final_adapter_29_of_30_provisional"] is True
    assert decision["gates"]["automatic_semantic_total"] is True
    assert decision["training_authorized"] is False


def test_gate_arithmetic_mutations_fail_total_family_veto_and_paired_regression() -> None:
    base = _observations()
    adapter = _observations()
    adapter[0]["mechanical_match"] = False
    adapter[0]["semantic_correct"] = False
    adapter[0]["failure_code"] = "semantic_mismatch"
    adapter[2]["mechanical_match"] = False
    adapter[2]["semantic_correct"] = False
    adapter[2]["failure_code"] = "semantic_mismatch"
    adapter[1]["critical_failure"] = True
    decision = t30.gate_arithmetic(base, adapter)
    assert decision["gates"]["automatic_semantic_total"] is False
    assert decision["gates"]["critical_invented_unauthorized_tool_retrieval_veto"] is False
    assert decision["gates"]["no_paired_regression"] is False
    assert decision["verdict"] == "GRAMMAR_STDLIB_T30_DIAGNOSE"


def test_generation_matches_the_only_worker_implementation() -> None:
    assert {
        "temperature": 0,
        "seed": t30.qlora.CONFIG["seed"],
        "thinking": False,
        "max_tokens": 512,
    } == t30.GENERATION
    assert "src/metis_model1/demo_accuracy.py" in t30.BOUND_PATHS
    assert "src/metis_model1/initial_local_qlora_backup.py" in t30.BOUND_PATHS
    assert "src/metis_model1/initial_local_qlora_train.py" in t30.BOUND_PATHS
    assert "manifests/initial-local-qlora-backup-preimage-v1.json" in t30.BOUND_PATHS


def test_historical_bound_roster_is_extracted_from_preimage_source() -> None:
    source = b'BOUND_INPUTS = ("old/contracts.py", "old/runtime.py")\n'
    assert t30._historical_bound_input_roster(source) == (
        "old/contracts.py",
        "old/runtime.py",
    )
    with pytest.raises(t30.GrammarStdlibT30Error, match="roster drift"):
        t30._historical_bound_input_roster(
            b'BOUND_INPUTS = ("old/contracts.py", "old/contracts.py")\n'
        )


def test_historical_freeze_replays_git_preimage_not_live_tree(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preimage = "a" * 40
    tree = "b" * 40
    trainer_path = "src/metis_model1/initial_local_qlora_train.py"
    trainer_source = b'BOUND_INPUTS = ("old/contracts.py", "old/runtime.py")\n'
    historical = {
        trainer_path: trainer_source,
        "old/contracts.py": b"historical contracts\n",
        "old/runtime.py": b"historical runtime\n",
    }
    base_checkpoint = {
        "revision": "base-revision",
        "config_sha256": "base-config",
        "weights": 3,
        "payload_files": 15,
        "tree_metadata_sha256": "base-tree",
        "verification_report_sha256": "sha256:" + "e" * 64,
    }
    value = {
        "schema_version": 2,
        "status": "refrozen_after_base_before_training",
        "wave": "INITIAL_LOCAL_QLORA_V1",
        "preimage_commit": preimage,
        "preimage_tree": tree,
        "preimage_published": True,
        "remote_head_at_freeze": preimage,
        "model_outputs_observed": True,
        "training_started": False,
        "model_replay_allowed": False,
        "network": "denied_during_model_and_optimizer_execution",
        "config": t30.trainer.CONFIG,
        "limits": t30.trainer.LIMITS,
        "runtime": {"runtime": "pinned"},
        "dataset_receipt_sha256": "sha256:" + "c" * 64,
        "baseline_origin": {"base_dev": {"score": 6}},
        "checkpoint": base_checkpoint,
        "checkpoint_report_sha256": base_checkpoint["verification_report_sha256"],
        "bound_inputs": {
            path: t30.raw_hash(raw) for path, raw in historical.items() if path != trainer_path
        },
    }

    def pinned(_root, *args, text=True):
        if args[:2] == ("rev-parse", f"{preimage}^{{tree}}"):
            return tree
        if args[:3] == ("merge-base", "--is-ancestor", preimage):
            return ""
        if args[0] == "show":
            relative = args[1].split(":", 1)[1]
            return historical[relative]
        raise AssertionError(args)

    monkeypatch.setattr(t30, "_pinned_git", pinned)
    assert (
        t30._verify_historical_training_freeze(
            value,
            dataset={"receipt_sha256": "sha256:" + "c" * 64},
            runtime={"runtime": "pinned"},
            base_checkpoint=base_checkpoint,
        )
        == 2
    )
    for field in (
        "config_sha256",
        "tree_metadata_sha256",
        "verification_report_sha256",
    ):
        value["checkpoint"] = {**base_checkpoint, field: "drift"}
        with pytest.raises(t30.GrammarStdlibT30Error, match="contract drift"):
            t30._verify_historical_training_freeze(
                value,
                dataset={"receipt_sha256": "sha256:" + "c" * 64},
                runtime={"runtime": "pinned"},
                base_checkpoint=base_checkpoint,
            )
    value["checkpoint"] = base_checkpoint
    value["checkpoint_report_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(t30.GrammarStdlibT30Error, match="contract drift"):
        t30._verify_historical_training_freeze(
            value,
            dataset={"receipt_sha256": "sha256:" + "c" * 64},
            runtime={"runtime": "pinned"},
            base_checkpoint=base_checkpoint,
        )
    value["checkpoint_report_sha256"] = base_checkpoint["verification_report_sha256"]
    baseline_origin = value.pop("baseline_origin")
    with pytest.raises(t30.GrammarStdlibT30Error, match="contract drift"):
        t30._verify_historical_training_freeze(
            value,
            dataset={"receipt_sha256": "sha256:" + "c" * 64},
            runtime={"runtime": "pinned"},
            base_checkpoint=base_checkpoint,
        )
    value["baseline_origin"] = baseline_origin
    value["bound_inputs"]["old/runtime.py"] = "sha256:" + "d" * 64
    with pytest.raises(t30.GrammarStdlibT30Error, match="differs at preimage"):
        t30._verify_historical_training_freeze(
            value,
            dataset={"receipt_sha256": "sha256:" + "c" * 64},
            runtime={"runtime": "pinned"},
            base_checkpoint=base_checkpoint,
        )


def test_historical_document_rejects_raw_or_self_hash_drift(tmp_path: Path) -> None:
    body = {"schema_version": 1, "status": "verified"}
    value = {**body, "receipt_sha256": t30.canonical_hash(body)}
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(value, allow_nan=False, sort_keys=True) + "\n", encoding="utf-8")
    assert t30._historical_document(path, "receipt", "receipt_sha256")[0] == value
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(t30.GrammarStdlibT30Error, match="canonical historical"):
        t30._historical_document(path, "receipt", "receipt_sha256")
    with pytest.raises(t30.GrammarStdlibT30Error, match="cannot reopen"):
        t30._historical_document(tmp_path / "absent.json", "absent", "receipt_sha256")


def test_historical_dev_bundle_replay_shares_one_pinned_oracle_scope(monkeypatch) -> None:
    replay = object()
    opened: list[tuple[Path, Path]] = []
    calls: list[tuple[str, Path | None, object]] = []

    @contextmanager
    def oracle_scope(metis_root: Path, node_path: Path):
        opened.append((metis_root, node_path))
        yield replay

    def bundle(label: str, *, dataset_receipt: Path, adapter: Path | None, oracle_replay):
        assert dataset_receipt == t30.DATASET_RECEIPT_PATH
        calls.append((label, adapter, oracle_replay))
        return {"label": label}

    monkeypatch.setattr(t30.qlora, "_dev_oracle_replay", oracle_scope)
    monkeypatch.setattr(t30.qlora, "_verified_dev_bundle", bundle)

    base, gates, restored = t30._replay_historical_dev_bundles()
    assert opened == [(t30.qlora.DEFAULT_PINNED_METIS_ROOT, t30.qlora.DEFAULT_NODE_PATH)]
    assert [item[0] for item in calls] == ["base", "step25", "step50", "restored"]
    assert all(item[2] is replay for item in calls)
    assert calls[0][1] is None and calls[3][1] is None
    assert calls[1][1] == t30.trainer.CHECKPOINT_ROOT / "step-00000025"
    assert calls[2][1] == t30.trainer.CHECKPOINT_ROOT / "step-00000050"
    assert base == {"label": "base"}
    assert gates == [{"label": "step25"}, {"label": "step50"}]
    assert restored == {"label": "restored"}


def test_package_backup_anchor_compares_all_payload_backed_members() -> None:
    assert t30.PACKAGE_LIVE_MEMBERS == {
        "dataset-receipt.json": t30.DATASET_RECEIPT_PATH,
        "training-receipt.json": t30.qlora.DEFAULT_TRAINING_RECEIPT,
        "selection-receipt.json": t30.qlora.DEFAULT_SELECTION_RECEIPT,
        "evaluation-receipt.json": t30.B12_RECEIPT_PATH,
        "restore-receipt.json": t30.qlora.DEFAULT_RESTORE_RECEIPT,
        "adapter_config.json": t30.ADAPTER_PATH / "adapter_config.json",
        "adapters.safetensors": t30.ADAPTER_PATH / "adapters.safetensors",
        "runtime.lock": t30.PROJECT_ROOT / "qualification/uv.lock",
    }


def test_complete_s3_receipt_verifier_is_bound_and_errors_are_normalized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, _raw = t30._historical_document(
        t30.BACKUP_RECEIPT_PATH, "remote backup receipt", "receipt_sha256"
    )
    monkeypatch.setattr(
        t30.backup,
        "verify_receipt",
        lambda *, require_published_remote: deepcopy(receipt),
    )
    assert t30._verified_backup_receipt(receipt) == receipt
    forged = deepcopy(receipt)
    forged["aws"]["account_id"] = "000000000000"
    with pytest.raises(t30.GrammarStdlibT30Error, match="differs"):
        t30._verified_backup_receipt(forged)

    def rejected(*, require_published_remote: bool):
        raise t30.backup.BackupContractError("receipt drift")

    monkeypatch.setattr(t30.backup, "verify_receipt", rejected)
    with pytest.raises(t30.GrammarStdlibT30Error, match="complete S3"):
        t30._verified_backup_receipt(receipt)


def test_regular_file_comparison_rejects_path_swap_race(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package = tmp_path / "package"
    live = tmp_path / "live"
    package.write_bytes(b"same bytes")
    live.write_bytes(b"same bytes")
    real_read = t30.os.read
    swapped = False

    def racing_read(descriptor: int, count: int) -> bytes:
        nonlocal swapped
        if not swapped:
            swapped = True
            live.unlink()
            live.symlink_to(package)
        return real_read(descriptor, count)

    monkeypatch.setattr(t30.os, "read", racing_read)
    with pytest.raises(t30.GrammarStdlibT30Error, match="changed while reading"):
        t30._regular_files_equal(package, live)


def test_f4_review_truth_is_derived_from_pinned_ast_inventory() -> None:
    task = {
        "oracle": {"mode": "endpoint", "target": "heldout"},
    }
    envelope = {
        "result": {
            "status": "ok",
            "endpoint": {"count": 1, "name": "heldout"},
            "ast": {
                "inventory": {
                    "$type": "Model",
                    "elements": [
                        {
                            "$type": "Endpoint",
                            "name": "heldout",
                            "members": [
                                {"$type": "NeedsDecl", "modules": ["time"]},
                                {
                                    "$type": "AttributesDecl",
                                    "attrs": [
                                        {
                                            "$type": "Attribute",
                                            "name": "clock",
                                            "expr": {"$type": "TimeRef", "member": "hour"},
                                        }
                                    ],
                                },
                            ],
                        }
                    ],
                }
            },
        }
    }
    assert t30._f4_review_target(task, envelope) == {
        "contract": t30.d18.SEMANTIC_SIGNATURE_CONTRACT,
        "status": "ok",
        "top_levels": ["Endpoint"],
        "stdlib_members": ["time.hour"],
        "stdlib_settings": [],
        "endpoint": {"count": 1, "requested": "heldout", "selected": "heldout"},
    }


def test_review_contract_marks_ast_invented_names_as_critical() -> None:
    _manifest_value, tasks, _raw = t30.load_tasks()
    f4 = next(task for task in tasks if task["family"] == "F-4")
    forged_f4 = deepcopy(f4["expected_json"])
    forged_f4["endpoint"]["selected"] = "gsl_t30_invented_endpoint"
    assert t30._review_json_contract_failure(f4, forged_f4) == "invented_symbol"

    f6 = next(
        task
        for task in tasks
        if task["family"] == "F-6" and task["expected_json"].get("declarations")
    )
    forged_f6 = deepcopy(f6["expected_json"])
    forged_f6["declarations"][0]["name"] = "gsl_t30_invented_declaration"
    assert t30._review_json_contract_failure(f6, forged_f6) == "invented_symbol"


def test_final_adjudication_credits_coverage_from_successful_observations_only() -> None:
    base = _observations()
    adapter = _observations()
    adapter[0]["observed_coverage"] = {
        "top_levels": sorted(t30.TOP_LEVELS),
        "stdlib_members": sorted(t30.STDLIB_MEMBERS),
        "stdlib_settings": sorted(t30.STDLIB_SETTINGS),
    }
    gate = t30.gate_arithmetic(base, adapter)
    reviews = {
        "reviews": [
            {"task_id": row["task_id"], "decision": "ACCEPT"}
            for row in adapter
            if row["family"] in t30.FINAL_HUMAN_REVIEW
        ]
    }
    decision = t30._final_adjudication(
        {"decision": gate, "observations": {"adapter": adapter}},
        reviews,
        {"runtime_identities": {"adapter_off_restore": {"exact_candidate_restore": True}}},
    )
    assert decision["verdict"] == "GRAMMAR_STDLIB_T30_PASS_NO_RETRAIN"
    adapter[0]["semantic_correct"] = False
    adapter[0]["mechanical_match"] = False
    gate = t30.gate_arithmetic(base, adapter)
    failed = t30._final_adjudication(
        {"decision": gate, "observations": {"adapter": adapter}},
        reviews,
        {"runtime_identities": {"adapter_off_restore": {"exact_candidate_restore": True}}},
    )
    assert failed["gates"]["coverage_all_10_top_levels"] is False
    assert failed["verdict"] == "GRAMMAR_STDLIB_T30_DIAGNOSE"


def test_o_excl_writer_never_clobbers_and_rejects_symlink(tmp_path: Path) -> None:
    directory = tmp_path / "run"
    directory.mkdir(mode=0o700)
    t30._write_ocl(directory, "attempt.json", b'{"a":1}\n')
    with pytest.raises(t30.GrammarStdlibT30Error, match="clobber"):
        t30._write_ocl(directory, "attempt.json", b'{"a":2}\n')
    linked = tmp_path / "linked"
    linked.symlink_to(directory)
    with pytest.raises(t30.GrammarStdlibT30Error, match="direct"):
        t30._write_ocl(linked, "report.json", b"{}\n")


def test_manifest_writer_is_canonical_o_excl_and_never_clobbers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "truth.json"
    monkeypatch.setattr(t30, "TRUTH_PATH", path)
    t30._write_manifest_once(path, {"z": 2, "a": 1})
    assert path.read_bytes() == b'{"a":1,"z":2}\n'
    assert path.stat().st_mode & 0o777 == 0o644
    with pytest.raises(t30.GrammarStdlibT30Error, match="clobber"):
        t30._write_manifest_once(path, {"a": 3})


def test_published_evaluation_must_equal_fresh_rescore() -> None:
    expected = {
        "observations": {"adapter": [{"task_id": "gsl_t30_f1_00", "mechanical_match": True}]},
        "decision": {"verdict": "GRAMMAR_STDLIB_T30_REVIEW_REQUIRED"},
    }
    t30._require_exact_rescored_evaluation(expected, expected)
    forged = deepcopy(expected)
    forged["observations"]["adapter"][0]["mechanical_match"] = False
    with pytest.raises(t30.GrammarStdlibT30Error, match="fresh rescore"):
        t30._require_exact_rescored_evaluation(forged, expected)


def test_freeze_fails_closed_when_run_exists_or_publication_is_not_exact(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    run = root / t30.RUN_RELATIVE
    run.mkdir(parents=True)
    monkeypatch.setattr(t30, "PROJECT_ROOT", root)
    monkeypatch.setattr(t30, "RUN_ROOT", root / "artifacts/grammar-stdlib-accuracy/t30")
    monkeypatch.setattr(
        t30, "_published", lambda _remote: ("a" * 40, "b" * 40, "refs/heads/codex/test")
    )
    with pytest.raises(t30.GrammarStdlibT30Error, match="already exists"):
        t30.build_freeze("origin", tmp_path / "metis", tmp_path / "node")


def test_attempt_receipt_is_created_before_workers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = tmp_path / t30.RUN_ID
    monkeypatch.setattr(t30, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(t30, "RUN_ROOT", tmp_path)
    requests = [
        {"request_id": f"gsl_t30_test_{index:02d}", "messages": [], "max_tokens": 512}
        for index in range(30)
    ]
    freeze = {"freeze_sha256": "sha256:" + "a" * 64, "runtime_identities": {"test": True}}
    t30._prepare_run(run, freeze, "b" * 40, "c" * 40, requests)
    assert (run / "attempt.json").exists()
    assert (run / "base").is_dir() and (run / "adapter").is_dir()
    assert (run / "attempt.json").stat().st_mode & 0o777 == 0o600
