from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import metis_model1.cli as cli
import metis_model1.video_private_artifacts as boundary
import metis_model1.video_private_io as private_io
from metis_model1.video_grounding_benchmark import benchmark_revision
from metis_model1.video_semantics_cli import VideoSemanticsCLIError, _benchmark_tasks

REV = "sha256:" + "1" * 64


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def private_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".gitignore").write_text("/artifacts/\n", encoding="utf-8")
    subprocess.run(
        ["git", "init", "-q"],
        cwd=root,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    monkeypatch.setattr(private_io, "PROJECT_ROOT", root)
    monkeypatch.setattr(boundary, "PROJECT_ROOT", root)
    private_io.prepare_private_store()
    return root


def _private(root: Path, namespace: str) -> Path:
    return root / "artifacts" / "video-catalog-semantics-v1" / namespace


def _projection() -> dict[str, object]:
    semantic = {
        "state": "reviewed",
        "at": {"file": "video.metis", "line": 1},
        "means": {"text": "a synthetic semantic", "at": {"file": "video.metis", "line": 2}},
    }
    return {
        "schema": 2,
        "projection_contract": "metis-model1/catalog-semantic-normalized-v1",
        "tenant": "synthetic",
        "thresholds": {},
        "catalogs": [
            {
                "name": "public.video",
                "file": "video.metis",
                "semantic": semantic,
                "fields": [
                    {
                        "name": "genre",
                        "type": "keyword",
                        "domain": {
                            "kind": "enum",
                            "size": 1,
                            "nature": "editorial",
                            "values": [{"literal": "Drama", "semantic": semantic}],
                        },
                        "semantic": semantic,
                    }
                ],
            }
        ],
    }


def test_build_index_and_ground_emit_only_to_private_store(
    tmp_path, private_store: Path, capsys
) -> None:
    projection = tmp_path / "projection.json"
    _write(projection, _projection())
    namespace = "work-items/index-run"
    assert (
        cli.main(
            [
                "video-semantics",
                "build-index",
                "--projection",
                str(projection),
                "--semantic-source-revision",
                REV,
                "--grammar-revision",
                REV,
                "--toolchain-revision",
                REV,
                "--tenant-snapshot",
                "snapshot-1",
                "--output-dir",
                namespace,
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    assert summary["payload_redacted"] is True
    assert "Drama" not in json.dumps(summary)
    out = _private(private_store, namespace)
    index = out / "index.json"
    assert "Drama" in index.read_text(encoding="utf-8")
    assert (out / "_bundle-manifest.json").is_file()
    request = tmp_path / "request.txt"
    request.write_text("Drama", encoding="utf-8")
    assert (
        cli.main(
            [
                "video-semantics",
                "ground-request",
                "--index",
                str(index),
                "--request",
                str(request),
                "--output-dir",
                str(tmp_path / "public-ground"),
            ]
        )
        == 1
    )
    # Absolute/public filesystem destinations are never accepted.
    blocked = json.loads(capsys.readouterr().out)
    assert blocked["status"] == "BLOCKED"
    assert blocked["payload_redacted"] is True

    ground_namespace = "work-items/ground-run"
    assert (
        cli.main(
            [
                "video-semantics",
                "ground-request",
                "--index",
                str(index),
                "--request",
                str(request),
                "--output-dir",
                ground_namespace,
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    assert "Drama" not in json.dumps(summary)
    ground = _private(private_store, ground_namespace)
    assert json.loads((ground / "grounding.json").read_text(encoding="utf-8"))["status"] == (
        "resolved"
    )
    assert "Drama" not in (ground / "grounding-receipt.json").read_text(encoding="utf-8")


def test_output_namespace_is_immutable_and_duplicate_json_is_blocked(
    tmp_path, private_store: Path, capsys
) -> None:
    projection = tmp_path / "projection.json"
    _write(projection, _projection())
    namespace = "work-items/immutable-run"
    args = [
        "video-semantics",
        "build-index",
        "--projection",
        str(projection),
        "--semantic-source-revision",
        REV,
        "--grammar-revision",
        REV,
        "--toolchain-revision",
        REV,
        "--tenant-snapshot",
        "snapshot-1",
        "--output-dir",
        namespace,
    ]
    assert cli.main(args) == 0
    capsys.readouterr()
    assert cli.main(args) == 1
    assert json.loads(capsys.readouterr().out)["error_code"] == "OUTPUT_PRIVATE_WRITE_BLOCKED"
    out = _private(private_store, namespace)
    assert hashlib.sha256((out / "index.json").read_bytes()).hexdigest()

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema": 2, "schema": 2}', encoding="utf-8")
    assert (
        cli.main(
            [
                "video-semantics",
                "build-index",
                "--projection",
                str(duplicate),
                "--semantic-source-revision",
                REV,
                "--grammar-revision",
                REV,
                "--toolchain-revision",
                REV,
                "--tenant-snapshot",
                "snapshot-1",
                "--output-dir",
                "work-items/duplicate-input-run",
            ]
        )
        == 1
    )
    duplicate_result = json.loads(capsys.readouterr().out)
    assert duplicate_result["error_code"] == "JSON_DUPLICATE_KEY"


def test_freeze_adaptation_requires_explicit_evaluation_pins() -> None:
    provenance = {
        "source_revision": REV,
        "constraint_revision": REV,
        "grammar_revision": REV,
        "toolchain_revision": REV,
        "base_model_ref": "base-v1",
        "tokenizer_ref": "tokenizer-v1",
        "adapter_ref": None,
    }
    freeze = {
        "status": "terminal",
        "terminal_manifest": "sha256:" + "2" * 64,
        "model_outputs_present": False,
        "tasks": {
            "dev": [{"task_id": "V-1-01", "provenance": provenance}],
            "frozen": [{"task_id": "V-1-02", "provenance": provenance}],
        },
    }
    freeze["benchmark_revision"] = benchmark_revision(
        [*freeze["tasks"]["dev"], *freeze["tasks"]["frozen"]]
    )
    with pytest.raises(VideoSemanticsCLIError) as error:
        _benchmark_tasks(freeze)
    assert error.value.code == "INPUT_EVALUATION_PINS_REQUIRED"

    freeze["evaluation_pins"] = {
        "benchmark_revision": freeze["benchmark_revision"],
        "oracle_revision": REV,
        "semantic_source_revision": REV,
        "constraint_revision": REV,
        "grammar_revision": REV,
        "toolchain_revision": REV,
        "base_model_ref": "base-v1",
        "tokenizer_ref": "tokenizer-v1",
        "adapter_ref": None,
        "decoding_profile": "temperature-0-seed-v1",
    }
    flattened = _benchmark_tasks(freeze)
    assert [task["split"] for task in flattened] == ["dev", "frozen"]
    assert all(task["pins"] == freeze["evaluation_pins"] for task in flattened)

    freeze["tasks"]["dev"][0]["task_id"] = "drifted"
    with pytest.raises(VideoSemanticsCLIError) as error:
        _benchmark_tasks(freeze)
    assert error.value.code == "INPUT_BENCHMARK_REVISION_DRIFT"


def test_blocked_weight_verdict_is_persisted_privately_and_exits_nonzero(
    tmp_path: Path, private_store: Path, capsys
) -> None:
    inputs = {}
    for name, value in (
        ("benchmark", {}),
        ("thresholds", {}),
        ("receipts", {}),
        ("scorecards", {}),
    ):
        path = tmp_path / f"{name}.json"
        _write(path, value)
        inputs[name] = path
    assert (
        cli.main(
            [
                "video-semantics",
                "weight-verdict",
                "--benchmark",
                str(inputs["benchmark"]),
                "--thresholds",
                str(inputs["thresholds"]),
                "--gate-receipts",
                str(inputs["receipts"]),
                "--scorecards",
                str(inputs["scorecards"]),
                "--output-dir",
                "receipts/blocked-verdict-run",
            ]
        )
        == 1
    )
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "BLOCKED"
    verdict = _private(private_store, "receipts/blocked-verdict-run/weight-verdict.json")
    assert json.loads(verdict.read_text(encoding="utf-8"))["verdict"] == "BLOCKED"
