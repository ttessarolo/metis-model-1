from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

import metis_model1.brain_toolchain_pin as pin


def test_brain_pin_contract_is_exact_and_deterministic() -> None:
    manifest = pin.load_metis_brain_toolchain_pin()

    assert pin.validate_metis_brain_toolchain_pin_contract() == []
    assert manifest["revision"] == "3fde0820c04244b011a2f7a9604c425891424b34"
    assert manifest["tree"] == "432bd3babd9f4c2dfe6349288b12eba917d4fe73"
    assert manifest["tooling_version"] == "0.24.1"
    assert manifest["runtime"]["node_version"] == "v22.22.3"
    assert manifest["runtime"]["langium_version"] == "4.3.0"
    assert manifest["runtime"]["metis_language_version"] == "0.43"
    assert manifest["runtime"]["grammar_sha256"].startswith("sha256:")
    assert manifest["runtime"]["node_bytes"] == 112915776
    assert len(manifest["evidence"]) == 29
    assert len({item["id"] for item in manifest["evidence"]}) == 29
    assert len(manifest["probes"]) == 9
    assert pin.manifest_sha256(manifest) == pin.manifest_sha256(deepcopy(manifest))


def test_brain_identity_is_typed_immutable_and_binding_stable() -> None:
    identity = pin.load_metis_brain_toolchain_identity()

    assert isinstance(identity, pin.BrainToolchainIdentity)
    assert identity.revision == "3fde0820c04244b011a2f7a9604c425891424b34"
    assert identity.tree == "432bd3babd9f4c2dfe6349288b12eba917d4fe73"
    assert identity.toolchain_binding == identity.manifest_sha256
    assert identity.as_dict()["tooling_version"] == "0.24.1"
    assert identity.langium_version == "4.3.0"
    assert identity.metis_language_version == "0.43"
    assert identity.grammar_sha256 == manifest_grammar_hash()
    with pytest.raises(FrozenInstanceError):
        identity.tree = "0" * 40  # type: ignore[misc]


def manifest_grammar_hash() -> str:
    return "sha256:dbbb2cf98f870d854af9082cb8ee33595054e993d7831d662170aeea0db8db01"


def test_legacy_v1_contract_files_remain_byte_identical() -> None:
    assert "sha256:" + hashlib.sha256(pin.LEGACY_SCHEMA_PATH.read_bytes()).hexdigest() == (
        pin.LEGACY_SCHEMA_FILE_SHA256
    )
    assert "sha256:" + hashlib.sha256(pin.LEGACY_MANIFEST_PATH.read_bytes()).hexdigest() == (
        pin.LEGACY_MANIFEST_FILE_SHA256
    )


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        ("schema version", lambda value: value.update(schema_version=2)),
        ("commit", lambda value: value.update(revision="0" * 40)),
        ("tree", lambda value: value.update(tree="1" * 40)),
        ("tooling version", lambda value: value.update(tooling_version="0.23.92")),
        ("node hash", lambda value: value["runtime"].update(node_sha256="sha256:" + "0" * 64)),
        (
            "package hash",
            lambda value: value["runtime"].update(package_sha256="sha256:" + "0" * 64),
        ),
        ("evidence path", lambda value: value["evidence"][0].update(path="../escape")),
        ("probe argv", lambda value: value["probes"][0]["argv"].append("--pretty")),
        ("policy", lambda value: value["policy"].update(network_denied=False)),
    ],
)
def test_manifest_tamper_fails_closed(
    monkeypatch: pytest.MonkeyPatch, label: str, mutate: Any
) -> None:
    original = pin._load_json

    def load(path: Path, expected_sha256: str, file_label: str) -> Any:
        value = original(path, expected_sha256, file_label)
        if path.name == pin.MANIFEST_PATH.name:
            value = deepcopy(value)
            mutate(value)
        return value

    monkeypatch.setattr(pin, "_load_json", load)
    with pytest.raises(pin.BrainToolchainPinError):
        pin.load_metis_brain_toolchain_pin()
    assert pin.validate_metis_brain_toolchain_pin_contract()


def test_duplicate_json_key_is_rejected_before_schema_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = pin._read_contract_file

    def read(path: Path, expected_sha256: str, label: str) -> bytes:
        raw = original(path, expected_sha256, label)
        if path.name == pin.MANIFEST_PATH.name:
            return b'{"schema_version":1,"schema_version":1}'
        return raw

    monkeypatch.setattr(pin, "_read_contract_file", read)
    with pytest.raises(pin.BrainToolchainPinError, match="duplicate JSON keys"):
        pin.load_metis_brain_toolchain_pin()


def test_schema_file_hash_tamper_fails_closed(tmp_path: Path) -> None:
    target = tmp_path / "metis-brain-toolchain-pin.schema.json"
    target.write_bytes(pin.SCHEMA_PATH.read_bytes() + b" ")

    with pytest.raises(pin.BrainToolchainPinError, match="fixed digest"):
        pin._read_contract_file(target, pin.SCHEMA_FILE_SHA256, "Brain pin schema")


def test_probe_execution_is_opt_in_by_default() -> None:
    assert pin.verify_metis_brain_toolchain_pin.__kwdefaults__ == {"execute_probes": False}


def test_probe_marker_missing_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest = {
        "revision": "r",
        "probes": [{"id": "x", "argv": ["node"], "success_marker": "OK"}],
        "runtime": {"node_version": "v"},
    }
    root = tmp_path
    (root / "tooling" / "node_modules").mkdir(parents=True)
    monkeypatch.setattr(
        pin,
        "_git",
        lambda *args, **kwargs: b"archive" if kwargs.get("text") is False else "r",
    )
    monkeypatch.setattr(
        pin._sandbox_support,
        "_safe_extract_archive",
        lambda raw, destination: (destination / "tooling" / "node_modules").mkdir(parents=True),
    )
    monkeypatch.setattr(pin._sandbox_support, "_sandbox_policy", lambda snapshot: "policy")
    monkeypatch.setattr(
        pin._sandbox_support,
        "_assert_sandbox_boundaries",
        lambda snapshot, policy: None,
    )
    monkeypatch.setattr(pin, "_node_modules_sha256", lambda path: "modules")
    monkeypatch.setattr(pin.shutil, "copytree", lambda *args, **kwargs: None)

    class Completed:
        returncode = 0
        stderr = b""

        def __init__(self, version: bool) -> None:
            self.stdout = "v" if version else b"v"

    monkeypatch.setattr(
        pin.subprocess,
        "run",
        lambda command, **kwargs: Completed("--version" in command),
    )
    with pytest.raises(pin.BrainToolchainPinError, match="probe failed"):
        pin._run_brain_archive_probes(
            manifest,
            root,
            b"node",
            remote_revision="r",
            modules_sha256="sha256:modules",
        )


def test_probe_roster_incomplete_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    original = pin._load_json

    def load(path: Path, expected_sha256: str, label: str) -> Any:
        value = original(path, expected_sha256, label)
        if path.name == pin.MANIFEST_PATH.name:
            value = deepcopy(value)
            value["probes"].pop()
        return value

    monkeypatch.setattr(pin, "_load_json", load)
    with pytest.raises(pin.BrainToolchainPinError, match="too short"):
        pin.load_metis_brain_toolchain_pin()
