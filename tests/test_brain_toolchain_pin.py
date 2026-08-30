from __future__ import annotations

from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

import metis_model1.brain_toolchain_pin as pin


def test_brain_pin_contract_is_exact_and_deterministic() -> None:
    manifest = pin.load_metis_brain_toolchain_pin()

    assert pin.validate_metis_brain_toolchain_pin_contract() == []
    assert manifest["revision"] == "c9f410a9b9b28e61dd1505b661ebc996e388e6e0"
    assert manifest["tree"] == "40bb657e67cf3521ca94bcc8a636031bcb50815f"
    assert manifest["tooling_version"] == "0.23.93"
    assert manifest["runtime"]["node_version"] == "v22.22.3"
    assert manifest["runtime"]["node_bytes"] == 112915776
    assert len(manifest["evidence"]) == 16
    assert len({item["id"] for item in manifest["evidence"]}) == 16
    assert len(manifest["probes"]) == 4
    assert pin.manifest_sha256(manifest) == pin.manifest_sha256(deepcopy(manifest))


def test_brain_identity_is_typed_immutable_and_binding_stable() -> None:
    identity = pin.load_metis_brain_toolchain_identity()

    assert isinstance(identity, pin.BrainToolchainIdentity)
    assert identity.revision == "c9f410a9b9b28e61dd1505b661ebc996e388e6e0"
    assert identity.tree == "40bb657e67cf3521ca94bcc8a636031bcb50815f"
    assert identity.toolchain_binding == identity.manifest_sha256
    assert identity.as_dict()["tooling_version"] == "0.23.93"
    with pytest.raises(FrozenInstanceError):
        identity.tree = "0" * 40  # type: ignore[misc]


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
