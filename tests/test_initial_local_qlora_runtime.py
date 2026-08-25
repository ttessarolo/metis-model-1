import hashlib
import io
import json
import subprocess
import tarfile
from contextlib import contextmanager

import pytest

from metis_model1 import initial_local_qlora_runtime as rt


def _dataset(tmp_path):
    directory = tmp_path / "dataset"
    directory.mkdir()
    for name in rt.DATASET_FILES - {"receipt.json"}:
        (directory / name).write_text("{}\n")
    hashes = {
        name: rt._prefixed_sha256(directory / name) for name in rt.DATASET_FILES - {"receipt.json"}
    }
    body = {
        "schema_version": 1,
        "status": "materialized_verified",
        "wave": "INITIAL_LOCAL_QLORA_V1",
        "catalog_pin_sha256": rt.CATALOG_PIN_SHA256,
        "exclusions_sha256": rt.EXCLUSIONS_SHA256,
        "b12_roster_sha256": rt.B12_ROSTER_SHA256,
        "counts": {
            "train": {"F-1": 22, "F-2": 21, "F-3": 21},
            "dev": {"F-1": 5, "F-2": 5, "F-3": 6},
        },
        "hashes": hashes,
        "split_manifest": "sha256:" + "b" * 64,
        "dataset_manifest": "sha256:" + "c" * 64,
    }
    receipt = {**body, "receipt_sha256": rt._canonical_hash(body)}
    (directory / "receipt.json").write_text(json.dumps(receipt))
    return directory


def _adapter(tmp_path, dataset=None, runtime_lock="lock"):
    dataset = dataset or _dataset(tmp_path)
    training_file = dataset / "train.jsonl"
    p = tmp_path / "adapter"
    p.mkdir()
    (p / "adapters.safetensors").write_bytes(b"adapter")
    (p / "adapter_config.json").write_text("{}")
    (p / "state.safetensors").write_bytes(b"state")
    state = {
        "schema_version": 1,
        "status": "complete",
        "global_step": 25,
        "last_metrics": {"loss": 1.0, "peak_metal_gb": 1.0},
        "training_config": {
            "batch_size": 1,
            "gradient_accumulation_steps": 1,
            "learning_rate": 1e-5,
            "lora_alpha": 16,
            "lora_dropout": 0.0,
            "lora_rank": 8,
            "max_seq_length": 1024,
            "seed": 17,
            "train_on_completions": True,
        },
        "model": {"revision": "r", "model_type": "qwen3_5"},
        "dataset": {
            "split": "train",
            "fingerprint": {
                "path": str(training_file.resolve()),
                "file_count": 1,
                "sha256": rt._dataset_fingerprint(training_file),
            },
        },
        "runtime": {"uv_lock_sha256": runtime_lock},
    }
    (p / "state.json").write_text(json.dumps(state))
    manifest = {
        "model_revision": "r",
        "adapter_sha256": rt._sha256(p / "adapters.safetensors"),
        "adapter_config_sha256": rt._sha256(p / "adapter_config.json"),
        "telemetry": {"loss": 1.0},
    }
    files = {
        name: {"bytes": (p / name).stat().st_size, "sha256": rt._sha256(p / name)}
        for name in (
            "state.json",
            "state.safetensors",
            "adapters.safetensors",
            "adapter_config.json",
        )
    }
    (p / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "status": "complete", "global_step": 25, "files": files})
    )
    return p, manifest


def _dev_bundle(label, adapter=None, score=11):
    directory = {
        "base": "base-dev",
        "restored": "base-dev-restored",
        "step25": "step25-dev",
    }[label]
    pin = rt._json(rt.CHECKPOINT_PIN)
    identity = {
        "base_revision": pin["revision"],
        "base_config_sha256": pin["config_sha256"],
        "base_tree_metadata_sha256": pin["tree_metadata_sha256"],
        "base_verification_report_sha256": rt._prefixed_sha256(rt.CHECKPOINT_REPORT),
        "base_payload_files": 15,
        "adapter_enabled": adapter is not None,
        "adapter": (
            {
                "global_step": 25,
                "manifest_sha256": rt._prefixed_sha256(adapter / "manifest.json"),
                "adapter_sha256": rt._prefixed_sha256(adapter / "adapters.safetensors"),
            }
            if adapter is not None
            else None
        ),
    }
    files = {
        "candidates": {
            "path": f"{directory}/candidates.jsonl",
            "bytes": 10,
            "sha256": "sha256:" + "1" * 64,
        },
        "generation": {
            "path": f"{directory}/generation.json",
            "bytes": 20,
            "sha256": "sha256:" + "2" * 64,
        },
        "semantic": {
            "path": f"{directory}/semantic.json",
            "bytes": 30,
            "sha256": "sha256:" + "3" * 64,
        },
    }
    body = {"label": label, "score": score, "identity": identity, "files": files}
    return {**body, "bundle_sha256": rt._canonical_hash(body)}


def _training_receipt(tmp_path, dataset, adapter):
    retained = {
        "global_step": 25,
        "manifest_sha256": rt._prefixed_sha256(adapter / "manifest.json"),
        "checkpoint_sha256": "sha256:" + "9" * 64,
    }
    phase = {
        "step": 25,
        "marker_sha256": "sha256:" + "1" * 64,
        "marker_self_sha256": "sha256:" + "2" * 64,
        "phase_receipt_sha256": "sha256:" + "3" * 64,
        "phase_receipt_self_sha256": "sha256:" + "4" * 64,
        "telemetry_summary_sha256": "sha256:" + "5" * 64,
        "continuation_authority_sha256": "sha256:" + "6" * 64,
        "retained_checkpoints": [retained],
    }
    body = {
        "schema_version": 1,
        "status": "verified",
        "wave": "INITIAL_LOCAL_QLORA_V1",
        "mode": "single_config_no_retry_qlora",
        "dataset_receipt_sha256": rt._prefixed_sha256(dataset / "receipt.json"),
        "evidence": {
            "freeze_file_sha256": "sha256:" + "7" * 64,
            "freeze_self_sha256": "sha256:" + "8" * 64,
            "baseline_reuse_receipt_file_sha256": "sha256:" + "a" * 64,
            "baseline_reuse_receipt_self_sha256": "sha256:" + "b" * 64,
            "baseline_origin_sha256": "sha256:" + "c" * 64,
            "preimage_commit": "a" * 40,
            "published_execution_head": "b" * 40,
            "checkpoint": {
                "global_step": 25,
                "model_revision": "r",
                "manifest_sha256": rt._prefixed_sha256(adapter / "manifest.json"),
                "adapter_sha256": rt._prefixed_sha256(adapter / "adapters.safetensors"),
                "adapter_config_sha256": rt._prefixed_sha256(adapter / "adapter_config.json"),
            },
            "phases": [phase],
        },
    }
    value = {**body, "training_sha256": rt._canonical_hash(body)}
    path = tmp_path / "training.json"
    path.write_text(json.dumps(value))
    return path


def _selection_receipt(tmp_path, adapter, dataset, training):
    base = _dev_bundle("base")
    gate = _dev_bundle("step25", adapter)
    evidence = {"base": base, "gates": [gate]}
    body = {
        "schema_version": 1,
        "status": "selected",
        "wave": "INITIAL_LOCAL_QLORA_V1",
        "selection_surface": "frozen_dev16_only",
        "b12_observed": False,
        "selected_step": 25,
        "checkpoint_manifest_sha256": rt._prefixed_sha256(adapter / "manifest.json"),
        "adapter_sha256": rt._prefixed_sha256(adapter / "adapters.safetensors"),
        "adapter_config_sha256": rt._prefixed_sha256(adapter / "adapter_config.json"),
        "model_revision": "r",
        "dataset_receipt_sha256": rt._prefixed_sha256(dataset / "receipt.json"),
        "training_receipt_sha256": rt._prefixed_sha256(training),
        "training_self_sha256": json.loads(training.read_text())["training_sha256"],
        "base_semantic_correct": 11,
        "selected_semantic_correct": 11,
        "base_evidence": base,
        "gate_evidence": [gate],
        "evidence_roster_sha256": rt._canonical_hash(evidence),
    }
    value = {**body, "selection_sha256": rt._canonical_hash(body)}
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(value))
    return path


def _restore_receipt(tmp_path, adapter, dataset, selection):
    initial = json.loads(selection.read_text())["base_evidence"]
    restored = _dev_bundle("restored")
    body = {
        "schema_version": 1,
        "status": "verified",
        "wave": "INITIAL_LOCAL_QLORA_V1",
        "mode": "adapter_off_exact_restore",
        "dataset_receipt_sha256": rt._prefixed_sha256(dataset / "receipt.json"),
        "selection_receipt_sha256": rt._prefixed_sha256(selection),
        "selection_self_sha256": json.loads(selection.read_text())["selection_sha256"],
        "selected_step": 25,
        "adapter_sha256": rt._prefixed_sha256(adapter / "adapters.safetensors"),
        "initial_base_evidence": initial,
        "restored_base_evidence": restored,
        "exact_candidate_restore": True,
    }
    value = {**body, "restore_sha256": rt._canonical_hash(body)}
    path = tmp_path / "restore.json"
    path.write_text(json.dumps(value))
    return path


def _evaluation_receipt(
    tmp_path,
    adapter,
    dataset,
    selection,
    restore,
    verdict="LOCAL_ADAPTER_EXPERIMENTAL",
):
    freeze = json.loads(rt.B12_FREEZE.read_text())
    observations = [
        {
            "task_id": task["task_id"],
            "family": task["family"],
            "post_repair_success": index < 11,
            "accepted_invented_identifiers": 0,
        }
        for index, task in enumerate(freeze["tasks"])
    ]
    body = {
        "schema_version": 1,
        "status": "verified",
        "wave": "INITIAL_LOCAL_QLORA_V1",
        "mode": "adapter_on_b12_terminal_replay",
        "training_authorized": False,
        "selection_feedback": False,
        "verdict": verdict,
        "dataset_receipt_sha256": rt._prefixed_sha256(dataset / "receipt.json"),
        "selection_receipt_sha256": rt._prefixed_sha256(selection),
        "adapter_off_restore_receipt_sha256": rt._prefixed_sha256(restore),
        "adapter_off_restore_self_sha256": json.loads(restore.read_text())["restore_sha256"],
        "counts": {
            "in": 12,
            "out": 12,
            "distinct": 12,
            "gaps": 0,
            "semantic_correct": 11,
        },
        "baseline": {
            "id": "B12-v4",
            "file_sha256": rt.B12_BASELINE_FILE_SHA256,
            "report_sha256": rt.B12_BASELINE_REPORT_SHA256,
            "semantic_correct": 11,
        },
        "critical_failures": [],
        "accepted_invented_identifiers": 0,
        "adapter": {
            "global_step": 25,
            "manifest_sha256": rt._prefixed_sha256(adapter / "manifest.json"),
            "adapter_sha256": rt._prefixed_sha256(adapter / "adapters.safetensors"),
        },
        "runtime": {"peak_metal_gb": 1.0},
        "identity": {
            "roster_file_sha256": rt.B12_ROSTER_SHA256,
            "freeze_file_sha256": rt.B12_FREEZE_FILE_SHA256,
            "freeze_sha256": rt.B12_FREEZE_SHA256,
            "oracle_runner_sha256": rt.B12_ORACLE_RUNNER_SHA256,
            "project_before": {"head": "x"},
            "project_after": {"head": "x"},
            "metis_before": {"head": "y"},
            "metis_after": {"head": "y"},
        },
        "recurring_failure_categories": [],
        "observations": observations,
    }
    value = {**body, "receipt_sha256": rt._canonical_hash(body)}
    path = tmp_path / "evaluation.json"
    path.write_text(json.dumps(value))
    return path


def test_exact_normalized_and_messages_reject_target_role():
    assert rt.exact_normalized(" a\n b ", "a b")
    with pytest.raises(rt.RuntimeContractError):
        rt._messages({"messages": [{"role": "assistant", "content": "secret"}]})


def test_metal_jit_sandbox_canary_uses_both_darwin_cache_aliases(tmp_path, monkeypatch):
    cache = tmp_path.resolve() / "evaluation-cache"
    policy = rt.EVALUATION_SANDBOX_POLICY.replace(
        str(rt.EVALUATION_CACHE_ROOT.resolve(strict=False)),
        str(cache),
    )
    monkeypatch.setattr(rt, "EVALUATION_CACHE_ROOT", cache)
    monkeypatch.setattr(rt, "EVALUATION_SANDBOX_POLICY", policy)
    result = rt._metal_jit_sandbox_canary()
    assert result["status"] == "pass"
    assert result["darwin_cache_aliases"] == list(rt.DARWIN_USER_CACHE_ROOTS)
    assert result["metal_cache_roots"] == list(rt.DARWIN_METAL_CACHE_ROOTS)
    assert len(result["darwin_cache_aliases"]) == 2
    assert len(result["metal_cache_roots"]) == 4


def test_project_coordinator_requires_exact_qualification_runtime_proof(monkeypatch):
    pin = rt._json(rt.RUNTIME_PIN)
    expected = {
        "python": pin["python"],
        "python_prefix": str((rt.PROJECT_ROOT / "qualification/.venv").resolve()),
        "packages": pin["packages"],
        "lock_sha256": pin["lock_sha256"],
    }
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=(json.dumps(expected, sort_keys=True) + "\n").encode(),
            stderr=b"",
        )

    monkeypatch.setattr(rt.subprocess, "run", run)
    assert rt._check_runtime() == expected
    assert calls[0][0][0] == str(rt.PROJECT_ROOT / "qualification/.venv/bin/python")
    assert calls[0][0][2] == "runtime-proof"
    assert calls[0][1]["timeout"] == 30
    assert calls[0][1]["env"] == {
        "PATH": "/usr/bin:/bin",
        "PYTHONHASHSEED": "0",
        "PYTHONNOUSERSITE": "1",
        "LC_ALL": "C",
        "LANG": "C",
    }


@pytest.mark.parametrize(
    ("returncode", "stdout", "stderr"),
    [
        (1, b"", b"failure"),
        (0, b"{}\n{}\n", b""),
        (0, b"\n{}", b""),
        (0, b"{}\n ", b""),
        (0, b"{}\n", b"unexpected"),
        (0, b"x" * (16 * 1024 + 1) + b"\n", b""),
    ],
)
def test_project_coordinator_rejects_bad_runtime_proof(monkeypatch, returncode, stdout, stderr):
    monkeypatch.setattr(
        rt.subprocess,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, returncode, stdout=stdout, stderr=stderr
        ),
    )
    with pytest.raises(rt.RuntimeContractError, match="runtime proof"):
        rt._check_runtime()


def test_verify_checkpoint_hash_and_finite_telemetry(tmp_path):
    p, _ = _adapter(tmp_path)
    pin = tmp_path / "pin.json"
    pin.write_text(json.dumps({"revision": "r", "model_type": "qwen3_5"}))
    old = rt.CHECKPOINT_PIN
    rt.CHECKPOINT_PIN = pin
    runtime_pin = tmp_path / "runtime.json"
    runtime_pin.write_text(json.dumps({"lock_sha256": "lock"}))
    old_runtime = rt.RUNTIME_PIN
    rt.RUNTIME_PIN = runtime_pin
    assert rt.verify_checkpoint(p)["model_revision"] == "r"
    state = {"last_metrics": {"loss": float("nan")}, "training_config": {}}
    (p / "state.json").write_text(json.dumps(state, allow_nan=True))
    m = {
        "schema_version": 1,
        "status": "complete",
        "files": {
            "state.json": {
                "bytes": (p / "state.json").stat().st_size,
                "sha256": rt._sha256(p / "state.json"),
            }
        },
    }
    (p / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(rt.RuntimeContractError):
        rt.verify_checkpoint(p)
    rt.CHECKPOINT_PIN = old
    rt.RUNTIME_PIN = old_runtime


def test_checkpoint_identity_binds_full_state_payload(tmp_path, monkeypatch):
    dataset = _dataset(tmp_path)
    adapter, _ = _adapter(tmp_path, dataset)
    pin = tmp_path / "pin.json"
    pin.write_text(json.dumps({"revision": "r", "model_type": "qwen3_5"}))
    runtime_pin = tmp_path / "runtime.json"
    runtime_pin.write_text(json.dumps({"lock_sha256": "lock"}))
    monkeypatch.setattr(rt, "CHECKPOINT_PIN", pin)
    monkeypatch.setattr(rt, "RUNTIME_PIN", runtime_pin)
    before = rt.verify_checkpoint(adapter, expected_dataset=dataset / "train.jsonl")
    (adapter / "state.safetensors").write_bytes(b"altered-resume-state")
    manifest = json.loads((adapter / "manifest.json").read_text())
    manifest["files"]["state.safetensors"] = {
        "bytes": (adapter / "state.safetensors").stat().st_size,
        "sha256": rt._sha256(adapter / "state.safetensors"),
    }
    (adapter / "manifest.json").write_text(json.dumps(manifest))
    after = rt.verify_checkpoint(adapter, expected_dataset=dataset / "train.jsonl")
    assert after["checkpoint_sha256"] != before["checkpoint_sha256"]
    assert after["manifest_sha256"] != before["manifest_sha256"]


def test_receipt_hashes_do_not_launder_semantically_invalid_dataset(tmp_path):
    dataset = _dataset(tmp_path)
    with pytest.raises(rt.RuntimeContractError, match="semantic verification"):
        rt._check_receipt(dataset / "receipt.json")


def test_package_rejects_extra_and_is_atomic(tmp_path, monkeypatch):
    dataset = _dataset(tmp_path)
    pin = tmp_path / "pin.json"
    pin.write_text(
        json.dumps(
            {
                "revision": "r",
                "model_type": "qwen3_5",
                "config_sha256": "c" * 64,
                "tree_metadata_sha256": "d" * 64,
            }
        )
    )
    monkeypatch.setattr(rt, "CHECKPOINT_PIN", pin)
    checkpoint_report = tmp_path / "checkpoint-report.json"
    checkpoint_report.write_text("{}")
    monkeypatch.setattr(rt, "CHECKPOINT_REPORT", checkpoint_report)
    runtime_lock = tmp_path / "lock"
    runtime_lock.write_text("lock")
    lock_sha256 = rt._sha256(runtime_lock)
    adapter, _ = _adapter(tmp_path, dataset, runtime_lock=lock_sha256)
    (adapter / "optimizer.bin").write_bytes(b"forbidden")
    root = tmp_path / "artifacts"
    monkeypatch.setattr(rt, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(rt, "RUNTIME_LOCK", runtime_lock)
    runtime_pin = tmp_path / "runtime.json"
    runtime_pin.write_text(json.dumps({"lock_sha256": lock_sha256}))
    monkeypatch.setattr(rt, "RUNTIME_PIN", runtime_pin)
    monkeypatch.setattr(rt, "_semantic_dataset_errors", lambda _path: [])
    monkeypatch.setattr(rt, "_check_runtime", lambda: {"status": "test"})
    training = _training_receipt(tmp_path, dataset, adapter)
    monkeypatch.setattr(rt, "DEFAULT_TRAINING_RECEIPT", training)
    selection = _selection_receipt(tmp_path, adapter, dataset, training)
    restore = _restore_receipt(tmp_path, adapter, dataset, selection)
    receipt = _evaluation_receipt(tmp_path, adapter, dataset, selection, restore)
    monkeypatch.setattr(rt, "verify_evaluation_receipt", lambda *_args, **_kwargs: {})
    with pytest.raises(rt.RuntimeContractError):
        rt.package(
            adapter,
            root,
            "LOCAL_ADAPTER_EXPERIMENTAL",
            receipt,
            dataset / "receipt.json",
            selection,
            restore,
        )
    (adapter / "optimizer.bin").unlink()
    result = rt.package(
        adapter,
        root,
        "LOCAL_ADAPTER_EXPERIMENTAL",
        receipt,
        dataset / "receipt.json",
        selection,
        restore,
    )
    out = rt.Path(result["package"])
    assert sorted(p.name for p in out.iterdir()) == [
        "CARD.md",
        "adapter_config.json",
        "adapters.safetensors",
        "dataset-receipt.json",
        "evaluation-receipt.json",
        "manifest.json",
        "package-checksum.json",
        "restore-receipt.json",
        "runtime.lock",
        "selection-receipt.json",
        "training-receipt.json",
    ]
    assert rt.verify_package(out)["status"] == "verified"
    assert rt.Path(result["archive"]["path"]).is_file()
    archive_receipt = json.loads(rt.Path(result["archive_receipt"]).read_text())
    assert archive_receipt["fresh_restore"]["status"] == "fresh_restore_verified"
    assert len(archive_receipt["fresh_restore"]["members"]) == len(rt.PACKAGE_FILES)

    forged = json.loads((out / "evaluation-receipt.json").read_text())
    forged["critical_failures"] = ["forged-veto"]
    forged_body = {key: value for key, value in forged.items() if key != "receipt_sha256"}
    forged["receipt_sha256"] = rt._canonical_hash(forged_body)
    (out / "evaluation-receipt.json").write_text(json.dumps(forged, sort_keys=True) + "\n")
    manifest = json.loads((out / "manifest.json").read_text())
    manifest["evaluation_receipt_sha256"] = rt._prefixed_sha256(out / "evaluation-receipt.json")
    manifest["files"]["evaluation-receipt.json"] = rt._record(out / "evaluation-receipt.json")
    manifest_body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    manifest["manifest_sha256"] = rt._canonical_hash(manifest_body)
    (out / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
    checksum = json.loads((out / "package-checksum.json").read_text())
    checksum["manifest_sha256"] = rt._prefixed_sha256(out / "manifest.json")
    checksum["files"] = {
        name: rt._record(out / name) for name in rt.PACKAGE_FILES if name != "package-checksum.json"
    }
    checksum_body = {key: value for key, value in checksum.items() if key != "package_sha256"}
    checksum["package_sha256"] = rt._canonical_hash(checksum_body)
    (out / "package-checksum.json").write_text(json.dumps(checksum, sort_keys=True) + "\n")
    with pytest.raises(rt.RuntimeContractError, match="terminal B12"):
        rt.verify_package(out)


def test_verify_archive_rejects_unsafe_member_roster(tmp_path):
    archive = tmp_path / "unsafe.tar"
    with tarfile.open(archive, mode="w", format=tarfile.USTAR_FORMAT) as bundle:
        info = tarfile.TarInfo("metis-model1-adapter/../escape")
        info.size = 1
        bundle.addfile(info, io.BytesIO(b"x"))
    with pytest.raises(rt.RuntimeContractError, match="roster"):
        rt.verify_archive(archive)
    assert not (tmp_path / "escape").exists()


def test_evaluate_dev_never_sends_target(tmp_path, monkeypatch):
    seen = {}

    def worker(command, requests, timeout):
        seen["requests"] = requests
        return [{"source": "metis 0.43\n", "peak_metal_gb": 1.0}]

    monkeypatch.setattr(rt, "_bounded_worker", worker)
    monkeypatch.setattr(rt, "PROJECT_ROOT", tmp_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    dataset = _dataset(artifacts)
    row = {
        "example_id": "c1",
        "messages": [
            {"role": "user", "content": "author"},
            {"role": "assistant", "content": "metis 0.43\n"},
        ],
    }
    (dataset / "dev.jsonl").write_text(json.dumps(row) + "\n")
    monkeypatch.setattr(
        rt,
        "_check_receipt",
        lambda _path: {"receipt_sha256": rt._prefixed_sha256(dataset / "receipt.json")},
    )
    run_root = artifacts / "run-v1"
    monkeypatch.setattr(rt, "DEFAULT_OUTPUT_ROOT", run_root)
    report = run_root / "base-dev/generation.json"
    candidates = run_root / "base-dev/candidates.jsonl"
    result = rt.evaluate_dev(
        [row],
        ["worker"],
        report,
        candidate_jsonl=candidates,
        identity={"adapter_enabled": False},
        dataset_receipt=dataset / "receipt.json",
    )
    assert result["exact"] == 1
    assert "target_source" not in json.dumps(seen["requests"])
    assert "metis 0.43" not in json.dumps(seen["requests"])
    assert json.loads(report.read_text())["cases"][0]["source_sha256"]
    assert json.loads(report.read_text())["candidate_jsonl_sha256"] == rt._prefixed_sha256(
        candidates
    )


def test_case_id_alias_must_not_disagree():
    assert rt._case_id({"example_id": "x"}) == "x"
    with pytest.raises(rt.RuntimeContractError):
        rt._case_id({"case_id": "x", "example_id": "y"})


def test_selection_reopens_evidence_and_rejects_reforged_score(tmp_path, monkeypatch):
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "manifest.json").write_text("{}")
    (adapter / "adapters.safetensors").write_bytes(b"adapter")
    (adapter / "adapter_config.json").write_text("{}")
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "receipt.json").write_text("{}")
    training = tmp_path / "training.json"
    training.write_text("{}")
    monkeypatch.setattr(rt, "DEFAULT_TRAINING_RECEIPT", training)
    monkeypatch.setattr(
        rt,
        "verify_checkpoint",
        lambda *_args, **_kwargs: {"global_step": 25, "model_revision": "r"},
    )
    monkeypatch.setattr(
        rt,
        "_check_receipt",
        lambda _path: {"receipt_sha256": "sha256:" + "d" * 64},
    )
    monkeypatch.setattr(
        rt,
        "verify_training_receipt",
        lambda *_args, **_kwargs: {"training_sha256": "sha256:" + "e" * 64},
    )
    base = {"label": "base", "score": 10, "bundle_sha256": "sha256:" + "a" * 64}
    gate = {"label": "step25", "score": 10, "bundle_sha256": "sha256:" + "b" * 64}
    monkeypatch.setattr(
        rt,
        "_verified_dev_bundle",
        lambda label, **_kwargs: base if label == "base" else gate,
    )
    evidence = {"base": base, "gates": [gate]}
    body = {
        "schema_version": 1,
        "status": "selected",
        "wave": "INITIAL_LOCAL_QLORA_V1",
        "selection_surface": "frozen_dev16_only",
        "b12_observed": False,
        "selected_step": 25,
        "checkpoint_manifest_sha256": rt._prefixed_sha256(adapter / "manifest.json"),
        "adapter_sha256": rt._prefixed_sha256(adapter / "adapters.safetensors"),
        "adapter_config_sha256": rt._prefixed_sha256(adapter / "adapter_config.json"),
        "model_revision": "r",
        "dataset_receipt_sha256": "sha256:" + "d" * 64,
        "training_receipt_sha256": rt._prefixed_sha256(training),
        "training_self_sha256": "sha256:" + "e" * 64,
        "base_evidence": base,
        "gate_evidence": [gate],
        "evidence_roster_sha256": rt._canonical_hash(evidence),
        "base_semantic_correct": 11,
        "selected_semantic_correct": 10,
    }
    selection = tmp_path / "selection.json"
    selection.write_text(json.dumps({**body, "selection_sha256": rt._canonical_hash(body)}))
    with pytest.raises(rt.RuntimeContractError, match="gate roster"):
        rt.verify_selection_receipt(
            selection, adapter=adapter, dataset_receipt=dataset / "receipt.json"
        )


def test_restore_rejects_one_byte_candidate_drift(tmp_path, monkeypatch):
    adapter = tmp_path / "adapter"
    adapter.mkdir()
    (adapter / "adapters.safetensors").write_bytes(b"adapter")
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    (dataset / "receipt.json").write_text("{}")
    selection = tmp_path / "selection.json"
    selection.write_text("{}")
    monkeypatch.setattr(
        rt,
        "_check_receipt",
        lambda _path: {"receipt_sha256": "sha256:" + "d" * 64},
    )
    monkeypatch.setattr(
        rt,
        "verify_selection_receipt",
        lambda *_args, **_kwargs: {
            "selection_sha256": "sha256:" + "e" * 64,
            "selected_step": 25,
            "adapter_sha256": rt._prefixed_sha256(adapter / "adapters.safetensors"),
        },
    )
    initial = {
        "files": {
            "candidates": {
                "path": "base-dev/candidates.jsonl",
                "bytes": 1,
                "sha256": "sha256:" + "a" * 64,
            }
        }
    }
    restored = {
        "files": {
            "candidates": {
                "path": "base-dev-restored/candidates.jsonl",
                "bytes": 1,
                "sha256": "sha256:" + "b" * 64,
            }
        }
    }
    monkeypatch.setattr(
        rt,
        "_verified_dev_bundle",
        lambda label, **_kwargs: initial if label == "base" else restored,
    )
    body = {
        "schema_version": 1,
        "status": "verified",
        "wave": "INITIAL_LOCAL_QLORA_V1",
        "mode": "adapter_off_exact_restore",
        "dataset_receipt_sha256": "sha256:" + "d" * 64,
        "selection_receipt_sha256": rt._prefixed_sha256(selection),
        "selection_self_sha256": "sha256:" + "e" * 64,
        "selected_step": 25,
        "adapter_sha256": rt._prefixed_sha256(adapter / "adapters.safetensors"),
        "initial_base_evidence": initial,
        "restored_base_evidence": restored,
        "exact_candidate_restore": True,
    }
    receipt = tmp_path / "restore.json"
    receipt.write_text(json.dumps({**body, "restore_sha256": rt._canonical_hash(body)}))
    with pytest.raises(rt.RuntimeContractError, match="not exact"):
        rt.verify_adapter_off_restore_receipt(
            receipt,
            adapter=adapter,
            dataset_receipt=dataset / "receipt.json",
            selection_receipt=selection,
        )


def test_score_dev_candidates_uses_pinned_semantic_oracle(tmp_path, monkeypatch):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    dataset = _dataset(artifacts)
    rows = []
    families = ["F-1"] * 5 + ["F-2"] * 5 + ["F-3"] * 6
    for index, family in enumerate(families):
        source = f"metis 0.43\ncatalog public.video {{ id item_{index} }}\n"
        rows.append(
            {
                "example_id": f"e{index:02d}",
                "task_family": family,
                "messages": [
                    {"role": "user", "content": "author"},
                    {"role": "assistant", "content": source},
                ],
            }
        )
    (dataset / "dev.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    receipt = json.loads((dataset / "receipt.json").read_text())
    receipt["hashes"]["dev.jsonl"] = rt._prefixed_sha256(dataset / "dev.jsonl")
    receipt_body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    receipt["receipt_sha256"] = rt._canonical_hash(receipt_body)
    (dataset / "receipt.json").write_text(json.dumps(receipt))
    run_root = artifacts / "run-v1"
    phase = run_root / "base-dev"
    phase.mkdir(parents=True)
    candidates = phase / "candidates.jsonl"
    candidates.write_text(
        "".join(
            json.dumps({"case_id": row["example_id"], "source": row["messages"][-1]["content"]})
            + "\n"
            for row in rows
        )
    )
    generation_body = {
        "schema_version": 1,
        "status": "complete",
        "contract": "INITIAL_LOCAL_QLORA_V1",
        "identity": {
            "base_revision": rt._json(rt.CHECKPOINT_PIN)["revision"],
            "adapter_enabled": False,
            "adapter": None,
        },
        "dataset_receipt_sha256": rt._prefixed_sha256(dataset / "receipt.json"),
        "dev_jsonl_sha256": rt._prefixed_sha256(dataset / "dev.jsonl"),
        "cases": [
            {
                "case_id": row["example_id"],
                "prompt_sha256": rt._canonical_hash(rt._dev_prompt_messages(row)),
                "source_sha256": hashlib.sha256(
                    row["messages"][-1]["content"].encode()
                ).hexdigest(),
            }
            for row in rows
        ],
        "candidate_jsonl_sha256": rt._prefixed_sha256(candidates),
        "peak_metal_gb": 1.0,
    }
    generation = {**generation_body, "report_sha256": rt._canonical_hash(generation_body)}
    generation_path = phase / "generation.json"
    generation_path.write_text(json.dumps(generation))

    @contextmanager
    def snapshot(*_args):
        yield object()

    def describe(_snapshot, source):
        return {"catalogs": [{"name": "public.video", "source": source.strip()}]}, {
            "receipt_sha256": "sha256:" + "a" * 64
        }

    from metis_model1 import catalog_maintenance_probe, catalog_retrieval_refresh

    monkeypatch.setattr(catalog_retrieval_refresh, "_pinned_snapshot", snapshot)
    monkeypatch.setattr(catalog_maintenance_probe, "_describe_source_in_snapshot", describe)
    monkeypatch.setattr(rt, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(rt, "DEFAULT_OUTPUT_ROOT", run_root)
    monkeypatch.setattr(rt, "_semantic_dataset_errors", lambda _path: [])
    report = phase / "semantic.json"
    result = rt.score_dev_candidates(
        dataset,
        candidates,
        generation_path,
        report,
        metis_root=tmp_path,
        node_path=tmp_path / "node",
    )
    assert result["semantic_correct"] == 16
    assert json.loads(report.read_text())["counts"]["critical_failures"] == 0


def test_dev_oracle_replay_caches_only_successful_exact_sources(monkeypatch):
    from metis_model1 import catalog_maintenance_probe

    calls: list[str] = []
    failures = {"bad": 1}

    def describe(snapshot, source):
        assert snapshot is sentinel
        calls.append(source)
        if failures.get(source, 0):
            failures[source] -= 1
            raise catalog_maintenance_probe.CatalogMaintenanceProbeError("rejected")
        return {"catalogs": [{"source": source}]}, {"receipt_sha256": f"receipt:{source}"}

    sentinel = object()
    monkeypatch.setattr(catalog_maintenance_probe, "_describe_source_in_snapshot", describe)
    replay = rt._DevOracleReplay(sentinel, rt.DEFAULT_PINNED_METIS_ROOT, rt.DEFAULT_NODE_PATH)

    first = replay.describe("same")
    first[0]["catalogs"][0]["source"] = "mutated"
    first[1]["receipt_sha256"] = "mutated"
    assert replay.describe("same")[0]["catalogs"][0]["source"] == "same"
    assert replay.describe("same")[1]["receipt_sha256"] == "receipt:same"
    assert calls == ["same"]

    replay.describe("same\n")
    assert calls == ["same", "same\n"]

    with pytest.raises(catalog_maintenance_probe.CatalogMaintenanceProbeError):
        replay.describe("bad")
    assert replay.describe("bad")[1]["receipt_sha256"] == "receipt:bad"
    assert calls[-2:] == ["bad", "bad"]


def test_dev_observations_reuses_one_oracle_result_for_exact_duplicate_sources(monkeypatch):
    from metis_model1 import catalog_maintenance_probe, catalog_retrieval_refresh

    source = "metis 0.43\ncatalog public.video { id keyword }\n"
    families = ["F-1"] * 5 + ["F-2"] * 5 + ["F-3"] * 6
    cases = [
        {
            "example_id": f"case-{index:02d}",
            "task_family": family,
            "messages": [{"role": "assistant", "content": source}],
        }
        for index, family in enumerate(families)
    ]
    candidates = [{"case_id": f"case-{index:02d}", "source": source} for index in range(16)]
    calls = 0

    def describe(_snapshot, observed_source):
        nonlocal calls
        calls += 1
        assert observed_source == source
        return {"catalogs": [{"name": "public.video"}]}, {"receipt_sha256": "sha256:" + "a" * 64}

    monkeypatch.setattr(catalog_maintenance_probe, "_describe_source_in_snapshot", describe)
    monkeypatch.setattr(catalog_maintenance_probe, "_extract_source", lambda value: (value, None))
    monkeypatch.setattr(
        catalog_retrieval_refresh,
        "_pinned_snapshot",
        lambda *_args: (_ for _ in ()).throw(AssertionError("unexpected new snapshot")),
    )

    observations = rt._dev_observations(
        cases,
        candidates,
        metis_root=rt.DEFAULT_PINNED_METIS_ROOT,
        node_path=rt.DEFAULT_NODE_PATH,
        oracle_replay=rt._DevOracleReplay(
            object(), rt.DEFAULT_PINNED_METIS_ROOT, rt.DEFAULT_NODE_PATH
        ),
    )
    assert len(observations) == 16
    assert all(item["semantic_correct"] == 1 for item in observations)
    assert calls == 1


def test_dev_oracle_replay_closes_and_rejects_runtime_rebinding(tmp_path, monkeypatch):
    from metis_model1 import catalog_maintenance_probe, catalog_retrieval_refresh

    metis_root = tmp_path / "metis"
    metis_root.mkdir()
    node_path = tmp_path / "node"
    node_path.write_bytes(b"node")

    @contextmanager
    def snapshot(*_args):
        yield object()

    calls = 0

    def describe(_snapshot, source):
        nonlocal calls
        calls += 1
        return {"catalogs": [{"source": source}]}, {"receipt_sha256": "receipt"}

    monkeypatch.setattr(catalog_retrieval_refresh, "_pinned_snapshot", snapshot)
    monkeypatch.setattr(catalog_maintenance_probe, "_describe_source_in_snapshot", describe)

    with rt._dev_oracle_replay(metis_root, node_path) as replay:
        replay.describe("cached")
        with pytest.raises(rt.RuntimeContractError, match="runtime binding differs"):
            replay.require_active_binding(tmp_path / "other-metis", node_path)
    with pytest.raises(rt.RuntimeContractError, match="replay is closed"):
        replay.describe("cached")
    assert calls == 1


def _write_dev_score_report(tmp_path):
    families = ["F-1"] * 5 + ["F-2"] * 5 + ["F-3"] * 6
    observations = []
    for index in range(16):
        critical = int(index == 0)
        invented = int(index == 1)
        observations.append(
            {
                "case_id": f"case-{index:02d}",
                "family": families[index],
                "source_sha256": "sha256:" + f"{index + 1:064x}"[-64:],
                "extraction": "parse error" if critical else "ok",
                "oracle": "rejected" if critical else "ok",
                "oracle_failure_sha256": None,
                "candidate_receipt_sha256": None if critical else "sha256:" + "b" * 64,
                "target_receipt_sha256": "sha256:" + "c" * 64,
                "skeleton_match": not critical,
                "exact_normalized": not critical,
                "minimal": not critical,
                "invented_values": invented,
                "critical_failure": critical,
                "semantic_correct": int(not critical and not invented),
            }
        )
    counts = {
        "in": 16,
        "out": 16,
        "distinct": 16,
        "gaps": 0,
        "semantic_correct": 14,
        "critical_failures": 1,
        "invented_values": 1,
        "family_semantic_correct": {"F-1": 3, "F-2": 5, "F-3": 6},
    }
    body = {
        "schema_version": 1,
        "status": "verified",
        "wave": "INITIAL_LOCAL_QLORA_V1",
        "selection_surface": "frozen_dev16",
        "dataset_receipt_sha256": "sha256:" + "d" * 64,
        "generation_report_sha256": "sha256:" + "e" * 64,
        "generation_identity": {
            "base_revision": rt._json(rt.CHECKPOINT_PIN)["revision"],
            "adapter_enabled": False,
        },
        "candidates_sha256": "sha256:" + "f" * 64,
        "counts": counts,
        "observations": observations,
    }
    path = tmp_path / "semantic.json"
    path.write_text(json.dumps({**body, "report_sha256": rt._canonical_hash(body)}))
    return path


def test_verified_dev_score_accepts_truthful_baseline_failures(tmp_path):
    report = _write_dev_score_report(tmp_path)

    verified = rt._verified_dev_score(report)

    assert verified["counts"]["semantic_correct"] == 14
    assert verified["counts"]["critical_failures"] == 1
    assert verified["counts"]["invented_values"] == 1


@pytest.mark.parametrize("tamper", ["observation", "count"])
def test_verified_dev_score_rejects_refirmed_observation_or_count_tamper(tmp_path, tamper):
    report = _write_dev_score_report(tmp_path)
    forged = json.loads(report.read_text())
    if tamper == "observation":
        forged["observations"][2]["critical_failure"] = 1
    else:
        forged["counts"]["invented_values"] = 2
    body = {key: item for key, item in forged.items() if key != "report_sha256"}
    forged["report_sha256"] = rt._canonical_hash(body)
    report.write_text(json.dumps(forged))

    with pytest.raises(rt.RuntimeContractError, match="dev semantic score"):
        rt._verified_dev_score(report)
