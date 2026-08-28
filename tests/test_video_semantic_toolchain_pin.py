from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from metis_model1.video_semantic_toolchain_pin import (
    MANIFEST_PATH,
    VideoSemanticToolchainPinError,
    load_video_semantic_toolchain_pin,
    manifest_sha256,
    validate_video_semantic_toolchain_pin_contract,
    verify_video_semantic_toolchain_pin,
)


def _manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _write_manifest(root: Path, value: dict[str, Any]) -> None:
    path = root / "manifests" / MANIFEST_PATH.name
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_pin_contract_is_exact_and_deterministic() -> None:
    manifest = load_video_semantic_toolchain_pin()

    assert validate_video_semantic_toolchain_pin_contract() == []
    assert manifest["revision"] == "0b41a25d4d5eeac88975e43e18e4bc3123d51667"
    assert manifest["tree"] == "0c47611239d98020fc3a68d1efff2e213ed9df96"
    assert manifest["delivery_ancestors"]["grammar"] == ("291f0b787d85a13e7a2e77e893520c4679cd131d")
    assert len(manifest["evidence"]) == 15
    assert len({item["id"] for item in manifest["evidence"]}) == 15
    assert len(manifest["probes"]) == 7
    assert len({item["id"] for item in manifest["probes"]}) == 7
    assert manifest_sha256(manifest) == manifest_sha256(deepcopy(manifest))


@pytest.mark.skipif(
    os.environ.get("METIS_VIDEO_PIN_INTEGRATION") != "1",
    reason="requires explicitly supplied local Git-object authorities",
)
def test_real_git_objects_and_schema2_probe_roster_are_verified() -> None:
    metis_root = os.environ.get("METIS_VIDEO_PIN_METIS_ROOT")
    node_path = os.environ.get("METIS_VIDEO_PIN_NODE")
    play_demo_root = os.environ.get("METIS_VIDEO_PIN_PLAY_DEMO_ROOT")
    if not all((metis_root, node_path, play_demo_root)):
        pytest.fail("integration paths were not supplied")
    result = verify_video_semantic_toolchain_pin(
        Path(metis_root),
        Path(node_path),
        Path(play_demo_root),
        execute_probes=False,
    )

    assert result["status"] == "VERIFIED"
    assert result["retrieval_schema"] == 2
    assert (result["evidence_in"], result["evidence_out"], result["evidence_distinct"]) == (
        15,
        15,
        15,
    )
    assert result["evidence_gaps"] == 0
    assert (result["probes_in"], result["probes_out"], result["probes_gaps"]) == (7, 0, 7)


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        ("extra field", lambda m: m.update(extra=True)),
        ("missing field", lambda m: m.pop("tree")),
        ("path traversal", lambda m: m["evidence"][0].update(path="../escape")),
        (
            "line-like invalid ref",
            lambda m: m.update(remote_ref="refs/remotes/origin/main\n0"),
        ),
        (
            "boolean integer",
            lambda m: m["expected_denominators"].update(full_corpus_documents=True),
        ),
        ("probe argv drift", lambda m: m["probes"][0]["argv"].append("--pretty")),
        ("duplicate evidence id", lambda m: m["evidence"][1].update(id=m["evidence"][0]["id"])),
        (
            "duplicate evidence oid",
            lambda m: m["evidence"][1].update(blob_oid=m["evidence"][0]["blob_oid"]),
        ),
        ("control character", lambda m: m.update(pin_id="video-semantic-toolchain/\u0000v1")),
    ],
)
def test_manifest_mutations_fail_closed(tmp_path: Path, label: str, mutate: Any) -> None:
    manifest = _manifest()
    mutate(manifest)
    _write_manifest(tmp_path, manifest)

    with pytest.raises(VideoSemanticToolchainPinError):
        load_video_semantic_toolchain_pin(tmp_path)
    assert validate_video_semantic_toolchain_pin_contract(tmp_path)


def test_duplicate_json_key_is_rejected_before_projection(tmp_path: Path) -> None:
    path = tmp_path / "manifests" / MANIFEST_PATH.name
    path.parent.mkdir(parents=True)
    path.write_text('{"schema_version":1,"schema_version":1}\n', encoding="utf-8")

    with pytest.raises(VideoSemanticToolchainPinError, match="duplicate JSON keys"):
        load_video_semantic_toolchain_pin(tmp_path)


def test_unicode_surrogate_and_nonfinite_number_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "manifests" / MANIFEST_PATH.name
    path.parent.mkdir(parents=True)
    path.write_bytes(b'{"pin_id":"\\ud800"}\n')
    with pytest.raises(VideoSemanticToolchainPinError, match="Unicode"):
        load_video_semantic_toolchain_pin(tmp_path)

    path.write_bytes(b'{"pin_id":"x","schema_version":NaN}\n')
    with pytest.raises(VideoSemanticToolchainPinError, match="non-finite"):
        load_video_semantic_toolchain_pin(tmp_path)


def test_manifest_depth_bound_is_fail_closed(tmp_path: Path) -> None:
    value: Any = "x"
    for _ in range(20):
        value = [value]
    _write_manifest(tmp_path, {"x": value})

    with pytest.raises(VideoSemanticToolchainPinError, match="nesting"):
        load_video_semantic_toolchain_pin(tmp_path)
