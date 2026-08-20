from __future__ import annotations

import hashlib
import json
import runpy
from pathlib import Path

import pytest

from metis_model1.contracts import repository_root

MODULE = runpy.run_path(str(repository_root() / "qualification/generate_sequence_fixture.py"))
SequenceFixtureError = MODULE["SequenceFixtureError"]
_execute_probe = MODULE["_execute_probe"]
build_payload = MODULE["build_payload"]


class _FakeProcessor:
    pass


class _FakeModel:
    config = {"model_type": "fake_qwen", "image_token_id": 1}


class _FakeVisionDataset:
    def __init__(self, dataset, config, processor, train_on_completions=False):
        assert train_on_completions is True
        self.dataset = dataset

    def __getitem__(self, index):
        completion = self.dataset[index]["messages"][1]["content"].split()
        raw = 12 + len(completion)
        return {
            "input_ids": [list(range(raw))],
            "completion_mask": [[0] * 12 + [1] * len(completion)],
        }

    def _completion_prefix(self, conversation, num_images, num_audios):
        return "short-prefix"

    def _token_length(self, prompt, images, audio, image_token_index):
        assert image_token_index == 1
        return 12


def _fake_loader(path: Path, split: str):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert split == "train"
    return rows


def _fake_batches(dataset, batch_size, max_seq_length, train=False):
    assert batch_size == 1
    assert train is False
    item = dataset[0]
    input_ids = item["input_ids"][0]
    mask = item["completion_mask"][0]
    yield {
        "input_ids": [
            input_ids[:max_seq_length]
            + [0] * (max_seq_length - min(len(input_ids), max_seq_length))
        ],
        "completion_mask": [
            mask[:max_seq_length] + [0] * (max_seq_length - min(len(mask), max_seq_length))
        ],
    }


def _fake_run(tmp_path: Path, *, max_seq_length: int = 1024, suffix: str = "run"):
    artifact_root = (tmp_path / "artifacts").resolve()
    artifact_root.mkdir(parents=True)
    _execute_probe.__globals__["ARTIFACT_ROOT"] = artifact_root
    model_path = artifact_root / "checkpoint"
    model_path.mkdir()
    config = {"model_type": "fake_qwen", "image_token_id": 1}
    config_bytes = (json.dumps(config, sort_keys=True) + "\n").encode()
    (model_path / "config.json").write_bytes(config_bytes)
    report_path = artifact_root / "checkpoint-verification.json"
    report = {
        "schema_version": 1,
        "status": "verified",
        "checkpoint_path": str(model_path),
        "repository": "fake/model",
        "revision": "3e6447f082e89cc7f0bc6e5441afd38dfce760ff",
        "model_type": "fake_qwen",
        "config_sha256": hashlib.sha256(config_bytes).hexdigest(),
    }
    report_path.write_text(json.dumps(report), encoding="utf-8")
    output_dir = artifact_root / suffix
    result_path = output_dir / "report.json"
    kwargs = {
        "model_path": model_path,
        "checkpoint_report_path": report_path,
        "output_dir": output_dir,
        "report_path": result_path,
        "max_seq_length": max_seq_length,
        "load_fn": lambda path: (_FakeModel(), _FakeProcessor()),
        "dataset_loader": _fake_loader,
        "vision_dataset_cls": _FakeVisionDataset,
        "iterate_batches_fn": _fake_batches,
    }
    return _execute_probe(**kwargs), output_dir, model_path, report_path


def test_payload_is_deterministic_and_has_one_public_synthetic_example() -> None:
    first = build_payload(1024)
    second = build_payload(1024)
    assert first == second
    rows = [json.loads(line) for line in first.decode().splitlines()]
    assert len(rows) == 1
    assert rows[0]["messages"][0]["content"] == "Emit the synthetic sequence marker exactly."
    assert rows[0]["messages"][1]["content"].startswith("SEQ_00000 SEQ_00001")


def test_fake_probe_records_truncation_and_nonzero_completion(tmp_path) -> None:
    report, output_dir, _, _ = _fake_run(tmp_path)
    assert report["status"] == "pass"
    assert report["raw_token_count"] > 1024
    assert report["prefix_token_count"] == 12
    assert report["completion_token_count"] > 0
    assert report["batch_sequence_length"] == 1024
    assert report["retained_completion_token_count"] == 1012
    assert (
        report["dataset_sha256"]
        == hashlib.sha256((output_dir / "train.jsonl").read_bytes()).hexdigest()
    )
    assert (
        json.loads((output_dir / "report.json").read_text())["model"]["processor_trust_remote_code"]
        is False
    )


def test_fake_probe_is_repeatable_across_fresh_artifact_dirs(tmp_path) -> None:
    left, left_dir, _, _ = _fake_run(tmp_path / "left", suffix="probe")
    right, right_dir, _, _ = _fake_run(tmp_path / "right", suffix="probe")
    assert (left_dir / "train.jsonl").read_bytes() == (right_dir / "train.jsonl").read_bytes()
    for key in (
        "dataset_sha256",
        "raw_token_count",
        "prefix_token_count",
        "completion_token_count",
        "batch_sequence_length",
    ):
        assert left[key] == right[key]


def test_probe_rejects_outside_paths_symlinks_and_existing_outputs(tmp_path) -> None:
    artifact_root = (tmp_path / "artifacts").resolve()
    artifact_root.mkdir()
    _execute_probe.__globals__["ARTIFACT_ROOT"] = artifact_root
    outside = tmp_path / "outside"
    with pytest.raises(SequenceFixtureError, match="must stay under"):
        MODULE["require_artifact_path"].__globals__["ARTIFACT_ROOT"] = artifact_root
        MODULE["require_artifact_path"](outside / "report.json", label="report")

    model_path = artifact_root / "checkpoint"
    model_path.mkdir()
    (model_path / "config.json").write_text("{}", encoding="utf-8")
    link = artifact_root / "link"
    link.symlink_to(model_path, target_is_directory=True)
    with pytest.raises(SequenceFixtureError, match="symlink"):
        MODULE["require_artifact_path"](link / "config.json", label="model")

    report, output_dir, model_path, checkpoint_report = _fake_run(
        tmp_path / "existing", suffix="probe"
    )
    assert report["status"] == "pass"
    with pytest.raises(SequenceFixtureError, match="existing output"):
        _execute_probe(
            model_path=model_path,
            checkpoint_report_path=checkpoint_report,
            output_dir=output_dir,
            report_path=output_dir / "report-2.json",
            max_seq_length=1024,
            load_fn=lambda path: (_FakeModel(), _FakeProcessor()),
            dataset_loader=_fake_loader,
            vision_dataset_cls=_FakeVisionDataset,
            iterate_batches_fn=_fake_batches,
        )
