from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

import metis_model1.catalog_maintenance_pin as pin_module
from metis_model1.catalog_maintenance_pin import (
    CatalogMaintenancePinError,
    load_catalog_maintenance_pin,
    manifest_sha256,
    validate_catalog_maintenance_pin_contract,
    verify_catalog_maintenance_pin,
)
from metis_model1.contracts import repository_root

ROOT = repository_root()


def _mutate_manifest(
    monkeypatch: pytest.MonkeyPatch,
    mutation: Any,
) -> None:
    original = pin_module._load_json

    def load(path: Path, label: str) -> Any:
        value = original(path, label)
        if path.name == "catalog-maintenance-pin-v1.json":
            value = deepcopy(value)
            mutation(value)
        return value

    monkeypatch.setattr(pin_module, "_load_json", load)


def test_catalog_maintenance_pin_contract_is_exact_and_payload_free() -> None:
    assert validate_catalog_maintenance_pin_contract(ROOT) == []
    manifest = load_catalog_maintenance_pin(ROOT)

    assert manifest["revision"] == "5e112f9148f40e7e792052e896c5a9efe8eaf0a2"
    assert manifest["tree"] == "41c7a2b6890fa42d8123bd93f6560d0b9bfae8af"
    assert len(manifest["evidence"]) == 18
    assert len({item["id"] for item in manifest["evidence"]}) == 18
    assert len(manifest["probes"]) == 5
    assert manifest["nonclaims"] == [
        "no_tenant_payload",
        "no_model_output",
        "no_training_authority",
        "no_accuracy_claim",
        "nonpromotable",
    ]
    assert manifest_sha256(manifest) == (
        "sha256:0e3a4d9050f7ee9d6584fb284a0671f0e0eaf398597be29806943d7b6bffa987"
    )


def test_catalog_pin_rejects_evidence_path_role_laundering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mutate_manifest(
        monkeypatch,
        lambda manifest: manifest["evidence"][0].update(
            {"path": "docs/design/catalog-values/retrieval-api.md"}
        ),
    )

    errors = validate_catalog_maintenance_pin_contract(ROOT)

    assert "catalog pin evidence path drift for specification" in errors
    assert "catalog pin evidence paths are not distinct" in errors


def test_catalog_pin_rejects_probe_argv_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    _mutate_manifest(
        monkeypatch,
        lambda manifest: manifest["probes"][0]["argv"].append("--pretty"),
    )

    errors = validate_catalog_maintenance_pin_contract(ROOT)

    assert "catalog pin probe argv drift for typecheck" in errors


def test_live_pin_rejects_remote_that_does_not_contain_pin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = load_catalog_maintenance_pin(ROOT)

    def fake_git(_repository: Path | None, *args: str, text: bool = True) -> str | bytes:
        if args[:2] == ("rev-parse", manifest["revision"]):
            return manifest["revision"]
        if args[:2] == ("rev-parse", f"{manifest['revision']}^{{tree}}"):
            return manifest["tree"]
        if args[:2] == ("merge-base", "--is-ancestor"):
            if args[2:] == (manifest["surface_revision"], manifest["revision"]):
                return ""
            raise CatalogMaintenancePinError("not an ancestor")
        if args[:2] == ("ls-remote", manifest["remote_url"]):
            assert _repository is None
            return "0" * 40 + "\t" + manifest["remote_ref"]
        raise AssertionError(args)

    monkeypatch.setattr(pin_module, "_run_git", fake_git)

    with pytest.raises(CatalogMaintenancePinError, match="does not contain the catalog pin"):
        verify_catalog_maintenance_pin(tmp_path, tmp_path / "node")


def test_live_pin_rejects_git_blob_content_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manifest = load_catalog_maintenance_pin(ROOT)
    first = manifest["evidence"][0]

    def fake_git(_repository: Path | None, *args: str, text: bool = True) -> str | bytes:
        if args[:2] == ("rev-parse", manifest["revision"]):
            return manifest["revision"]
        if args[:2] == ("rev-parse", f"{manifest['revision']}^{{tree}}"):
            return manifest["tree"]
        if args[:2] == ("merge-base", "--is-ancestor"):
            return ""
        if args[:2] == ("ls-remote", manifest["remote_url"]):
            assert _repository is None
            return manifest["revision"] + "\t" + manifest["remote_ref"]
        if args[0] == "ls-tree":
            return f"100644 blob {first['blob_oid']}\t{first['path']}"
        if args[0] == "cat-file" and args[1] == "blob":
            return b"tampered"
        raise AssertionError(args)

    monkeypatch.setattr(pin_module, "_run_git", fake_git)

    with pytest.raises(CatalogMaintenancePinError, match="catalog evidence content drift"):
        verify_catalog_maintenance_pin(tmp_path, tmp_path / "node")


def test_live_pin_has_no_caller_controlled_authority_bypass(tmp_path: Path) -> None:
    with pytest.raises(TypeError):
        verify_catalog_maintenance_pin(
            tmp_path,
            tmp_path / "node",
            root=tmp_path,
            verify_remote=False,
            run_probes=False,
        )


def test_detached_remote_git_uses_protected_non_repository_cwd(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, Any] = {}

    def fake_run(command: list[str], **kwargs: Any) -> Any:
        observed["command"] = command
        observed.update(kwargs)

        class Completed:
            stdout = ""

        return Completed()

    monkeypatch.setattr(pin_module, "_verify_git_executable", lambda: None)
    monkeypatch.setattr(pin_module, "_verify_remote_git_cwd", lambda: None)
    monkeypatch.setattr(pin_module.subprocess, "run", fake_run)

    pin_module._run_git(None, "ls-remote", "ssh://example.invalid/repo", "refs/heads/main")

    assert observed["cwd"] == pin_module.REMOTE_GIT_CWD
    assert "-C" not in observed["command"]
    assert observed["env"]["GIT_CEILING_DIRECTORIES"] == str(pin_module.REMOTE_GIT_CWD)
