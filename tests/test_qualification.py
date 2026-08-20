from __future__ import annotations

import json
import runpy
import tomllib

import pytest

from metis_model1.contracts import repository_root

FIXTURE_MODULE = runpy.run_path(str(repository_root() / "qualification/generate_fixture.py"))
TOKENS = FIXTURE_MODULE["TOKENS"]
OPAQUE_KEYS = FIXTURE_MODULE["OPAQUE_KEYS"]
build_payload = FIXTURE_MODULE["build_payload"]
write_fixture = FIXTURE_MODULE["write_fixture"]


def test_w4_fixture_is_deterministic_public_and_text_only(tmp_path) -> None:
    first = build_payload()
    second = build_payload()

    assert first == second
    rows = [json.loads(line) for line in first.decode().splitlines()]
    assert len(rows) == 8
    assert [row["messages"][1]["content"] for row in rows] == list(TOKENS)
    assert all(set(row) == {"messages"} for row in rows)

    artifact_root = (tmp_path / "artifacts").resolve()
    write_fixture.__globals__["ARTIFACT_ROOT"] = artifact_root
    report = write_fixture(artifact_root / "fixture")
    assert report["sensitivity"] == "public_synthetic"
    assert report["examples"] == 8
    assert (artifact_root / "fixture/train.jsonl").read_bytes() == first
    with pytest.raises(ValueError, match="generated output must stay under"):
        write_fixture(tmp_path / "outside")


def test_w4_opaque_fixture_does_not_reveal_targets_in_prompts() -> None:
    rows = [json.loads(line) for line in build_payload("opaque").decode().splitlines()]

    assert len(rows) == len(OPAQUE_KEYS) == len(TOKENS)
    for row, key, target in zip(rows, OPAQUE_KEYS, TOKENS, strict=True):
        prompt = row["messages"][0]["content"]
        assert key in prompt
        assert target not in prompt
        assert row["messages"][1]["content"] == target


def test_w4_runtime_and_checkpoint_pins_are_internally_consistent() -> None:
    root = repository_root()
    runtime = json.loads((root / "qualification/runtime-pin.json").read_text())
    checkpoint = json.loads((root / "qualification/checkpoint-pin.json").read_text())
    source_manifest = json.loads((root / "manifests/source-model-revisions.json").read_text())
    project = tomllib.loads((root / "qualification/pyproject.toml").read_text())

    pins = set(project["project"]["dependencies"])
    assert f"mlx=={runtime['packages']['mlx']}" in pins
    assert f"mlx-vlm=={runtime['packages']['mlx-vlm']}" in pins
    assert f"jinja2=={runtime['packages']['jinja2']}" in pins
    assert f"numpy=={runtime['packages']['numpy']}" in pins
    assert f"safetensors=={runtime['packages']['safetensors']}" in pins
    assert f"transformers=={runtime['packages']['transformers']}" in pins
    assert runtime["status"] == "qualified"
    assert runtime["qualification_remaining"] == []
    assert checkpoint["payload_bytes"] == sum(item["bytes"] for item in checkpoint["weight_files"])
    assert len({item["sha256"] for item in checkpoint["weight_files"]}) == 3

    manifest_checkpoint = next(
        model for model in source_manifest["models"] if model["role"] == "mlx_checkpoint"
    )
    assert checkpoint["repository"] == manifest_checkpoint["id"]
    assert checkpoint["revision"] == manifest_checkpoint["revision"]
