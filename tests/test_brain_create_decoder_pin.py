from __future__ import annotations

import json
import os
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

import metis_model1.brain_create_decoder_pin as pin


def _manifest() -> dict[str, Any]:
    return json.loads(pin.MANIFEST_PATH.read_text(encoding="utf-8"))


def _canonical_file(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _manifest_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: dict[str, Any]) -> Path:
    path = tmp_path / pin.MANIFEST_PATH.relative_to(pin.PROJECT_ROOT)
    path.parent.mkdir(parents=True)
    raw = _canonical_file(value)
    path.write_bytes(raw)
    monkeypatch.setattr(pin, "MANIFEST_FILE_SHA256", pin._sha256(raw))
    return tmp_path


def _complete_root(tmp_path: Path) -> Path:
    for relative in (
        pin.MANIFEST_PATH.relative_to(pin.PROJECT_ROOT),
        Path("qualification/uv.lock"),
        Path("schemas/metis-brain-create-delta-plan.schema.json"),
        Path("src/metis_model1/brain_mlx_runtime.py"),
        Path("src/metis_model1/initial_local_qlora_runtime.py"),
    ):
        source = pin.PROJECT_ROOT / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return tmp_path


def _qualified_live_identity(_names: tuple[str, ...]) -> tuple[str, dict[str, str]]:
    return "3.12.10", dict(_manifest()["runtime"]["packages"])


def test_decoder_pin_contract_is_exact_and_nonpromotional() -> None:
    manifest = pin.load_brain_create_decoder_pin()

    assert manifest["status"] == "runtime_contract_ready"
    assert manifest["wire"] == {"schema_version": 4, "operation": "plan_create"}
    assert manifest["runtime"]["packages"]["llguidance"] == "1.8.0"
    assert manifest["runtime"]["qualification_lock"]["path"] == "qualification/uv.lock"
    assert manifest["decoder_projection"]["operation_types"] == 19
    assert manifest["create_prefix"]["message_count"] == 2
    assert "no_accuracy_claim" in manifest["nonclaims"]
    assert "not_model_qualified" in manifest["nonclaims"]
    assert "qualified" not in manifest["status"]
    assert pin.manifest_sha256(manifest) == pin.manifest_sha256(deepcopy(manifest))


def test_decoder_pin_verifies_all_current_bindings_without_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(_names: tuple[str, ...]) -> tuple[str, dict[str, str]]:
        raise AssertionError("host verification must not inspect worker packages")

    monkeypatch.setattr(pin, "_live_runtime_identity", unavailable)

    result = pin.verify_brain_create_decoder_pin()

    assert result == {
        "status": "runtime_contract_ready",
        "manifest_sha256": pin.manifest_sha256(_manifest()),
        "wire_schema_version": 4,
        "decoder": "llguidance-1.8.0",
        "schema_sha256": _manifest()["authoritative_schema"]["canonical_sha256"],
        "projection_sha256": _manifest()["decoder_projection"]["canonical_sha256"],
        "prefix_sha256": _manifest()["create_prefix"]["canonical_sha256"],
        "worker_sha256": _manifest()["worker"]["sha256"],
        "package_count": 6,
    }


def test_live_runtime_subset_has_an_independent_worker_side_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pin, "_live_runtime_identity", _qualified_live_identity)

    assert pin.verify_brain_create_decoder_runtime_subset() == {
        "status": "runtime_contract_ready",
        "python": "3.12.10",
        "packages": _manifest()["runtime"]["packages"],
    }


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        ("top-level extra", lambda value: value.update(extra=True)),
        ("top-level missing", lambda value: value.pop("role")),
        ("promotional status", lambda value: value.update(status="qualified")),
        ("role", lambda value: value.update(role="source_generator")),
        ("wire version", lambda value: value["wire"].update(schema_version=3)),
        ("wire extra", lambda value: value["wire"].update(extra=True)),
        ("python", lambda value: value["runtime"].update(python="3.13.0")),
        ("decoder", lambda value: value["runtime"].update(decoder="none")),
        ("runtime extra", lambda value: value["runtime"].update(extra=True)),
        ("package missing", lambda value: value["runtime"]["packages"].pop("llguidance")),
        (
            "package extra",
            lambda value: value["runtime"]["packages"].update(torch="2.0.0"),
        ),
        (
            "package version",
            lambda value: value["runtime"]["packages"].update(llguidance="1.9.0"),
        ),
        (
            "lock traversal",
            lambda value: value["runtime"]["qualification_lock"].update(path="../uv.lock"),
        ),
        (
            "schema path",
            lambda value: value["authoritative_schema"].update(path="schemas/other.json"),
        ),
        (
            "projection implementation",
            lambda value: value["decoder_projection"].update(implementation="other"),
        ),
        (
            "projection boolean count",
            lambda value: value["decoder_projection"].update(operation_types=True),
        ),
        (
            "prefix implementation",
            lambda value: value["create_prefix"].update(implementation="other"),
        ),
        (
            "prefix boolean count",
            lambda value: value["create_prefix"].update(message_count=True),
        ),
        ("worker traversal", lambda value: value["worker"].update(path="../worker.py")),
        (
            "policy weakened",
            lambda value: value["policy"].update(delta_permit_required=False),
        ),
        ("policy extra", lambda value: value["policy"].update(extra=True)),
        ("nonclaim removed", lambda value: value["nonclaims"].pop()),
        ("nonclaim reordered", lambda value: value["nonclaims"].reverse()),
    ],
)
def test_manifest_mutations_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    label: str,
    mutate: Any,
) -> None:
    manifest = _manifest()
    mutate(manifest)
    root = _manifest_root(tmp_path, monkeypatch, manifest)

    with pytest.raises(pin.BrainCreateDecoderPinError):
        pin.load_brain_create_decoder_pin(root)


def test_duplicate_json_member_is_rejected_before_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / pin.MANIFEST_PATH.relative_to(pin.PROJECT_ROOT)
    path.parent.mkdir(parents=True)
    raw = b'{"schema_version":1,"schema_version":1}\n'
    path.write_bytes(raw)
    monkeypatch.setattr(pin, "MANIFEST_FILE_SHA256", pin._sha256(raw))

    with pytest.raises(pin.BrainCreateDecoderPinError, match="duplicate JSON keys"):
        pin.load_brain_create_decoder_pin(tmp_path)


def test_nonfinite_and_invalid_unicode_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / pin.MANIFEST_PATH.relative_to(pin.PROJECT_ROOT)
    path.parent.mkdir(parents=True)
    raw = b'{"schema_version":NaN}\n'
    path.write_bytes(raw)
    monkeypatch.setattr(pin, "MANIFEST_FILE_SHA256", pin._sha256(raw))
    with pytest.raises(pin.BrainCreateDecoderPinError, match="non-finite"):
        pin.load_brain_create_decoder_pin(tmp_path)

    raw = b'{"pin_id":"\\ud800"}\n'
    path.write_bytes(raw)
    monkeypatch.setattr(pin, "MANIFEST_FILE_SHA256", pin._sha256(raw))
    with pytest.raises(pin.BrainCreateDecoderPinError, match="Unicode"):
        pin.load_brain_create_decoder_pin(tmp_path)


def test_symlink_and_hardlink_manifest_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = pin.MANIFEST_PATH.read_bytes()
    outside = tmp_path / "outside.json"
    outside.write_bytes(raw)
    manifest = tmp_path / pin.MANIFEST_PATH.relative_to(pin.PROJECT_ROOT)
    manifest.parent.mkdir(parents=True)
    manifest.symlink_to(outside)
    with pytest.raises(pin.BrainCreateDecoderPinError, match="symlink"):
        pin.load_brain_create_decoder_pin(tmp_path)

    manifest.unlink()
    os.link(outside, manifest)
    monkeypatch.setattr(pin, "MANIFEST_FILE_SHA256", pin._sha256(raw))
    with pytest.raises(pin.BrainCreateDecoderPinError, match="bounded regular file"):
        pin.load_brain_create_decoder_pin(tmp_path)


@pytest.mark.parametrize(
    "relative",
    [
        "qualification/uv.lock",
        "schemas/metis-brain-create-delta-plan.schema.json",
        "src/metis_model1/initial_local_qlora_runtime.py",
    ],
)
def test_bound_file_symlink_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    relative: str,
) -> None:
    root = _complete_root(tmp_path)
    target = root / relative
    outside = root / (target.name + ".outside")
    target.replace(outside)
    target.symlink_to(outside)
    monkeypatch.setattr(pin, "_live_runtime_identity", _qualified_live_identity)

    with pytest.raises(pin.BrainCreateDecoderPinError, match="symlink"):
        pin.verify_brain_create_decoder_pin(root)


@pytest.mark.parametrize("target", ["lock", "schema", "worker"])
def test_bound_content_mutation_fails_closed(monkeypatch: pytest.MonkeyPatch, target: str) -> None:
    original = pin._read_regular

    def read(root: Path, relative: Any, *, maximum: int, label: str) -> bytes:
        raw = original(root, relative, maximum=maximum, label=label)
        if target == "lock" and label == "qualification lock":
            return raw + b"\n"
        if target == "worker" and label == "CREATE worker":
            return raw + b"\n"
        if target == "schema" and label == "authoritative CREATE schema":
            value = json.loads(raw)
            value["title"] = "mutated"
            return pin._canonical(value)
        return raw

    monkeypatch.setattr(pin, "_read_regular", read)
    monkeypatch.setattr(pin, "_live_runtime_identity", _qualified_live_identity)
    with pytest.raises(pin.BrainCreateDecoderPinError, match="differs"):
        pin.verify_brain_create_decoder_pin()


def test_projection_and_prefix_mutation_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    from metis_model1 import initial_local_qlora_runtime as worker_runtime

    original_projection = worker_runtime._create_plan_decoder_schema

    def mutate_projection(schema: dict[str, Any]) -> dict[str, Any]:
        value = original_projection(schema)
        value["title"] = "mutated"
        return value

    monkeypatch.setattr(worker_runtime, "_create_plan_decoder_schema", mutate_projection)
    monkeypatch.setattr(pin, "_live_runtime_identity", _qualified_live_identity)
    with pytest.raises(pin.BrainCreateDecoderPinError, match="projection differs"):
        pin.verify_brain_create_decoder_pin()

    monkeypatch.setattr(worker_runtime, "_create_plan_decoder_schema", original_projection)
    monkeypatch.setattr(pin, "_current_create_prefix", lambda: (4, [{"role": "system"}]))
    with pytest.raises(pin.BrainCreateDecoderPinError, match="prefix differs"):
        pin.verify_brain_create_decoder_pin()


@pytest.mark.parametrize(
    "identity",
    [
        ("3.13.0", _manifest()["runtime"]["packages"]),
        (
            "3.12.10",
            {**_manifest()["runtime"]["packages"], "llguidance": "1.9.0"},
        ),
        (
            "3.12.10",
            {
                key: value
                for key, value in _manifest()["runtime"]["packages"].items()
                if key != "llguidance"
            },
        ),
    ],
)
def test_live_runtime_subset_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch, identity: tuple[str, dict[str, str]]
) -> None:
    monkeypatch.setattr(pin, "_live_runtime_identity", lambda _names: identity)

    with pytest.raises(pin.BrainCreateDecoderPinError, match="live decoder runtime differs"):
        pin.verify_brain_create_decoder_runtime_subset()


@pytest.mark.parametrize(
    ("interpreter", "verifier", "expected"),
    [
        (".venv/bin/python", "verify_brain_create_decoder_pin", "runtime_contract_ready"),
        (
            "qualification/.venv/bin/python",
            "verify_brain_create_decoder_runtime_subset",
            "runtime_contract_ready",
        ),
    ],
)
def test_split_verifiers_work_in_their_real_interpreters(
    interpreter: str, verifier: str, expected: str
) -> None:
    executable = pin.PROJECT_ROOT / interpreter
    if not executable.is_file():
        pytest.skip(f"interpreter unavailable: {executable}")
    script = (
        f"import metis_model1.brain_create_decoder_pin as pin; print(pin.{verifier}()['status'])"
    )
    completed = subprocess.run(
        [str(executable), "-c", script],
        cwd=pin.PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == expected


def test_missing_live_package_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(_name: str) -> str:
        raise pin.PackageNotFoundError("llguidance")

    monkeypatch.setattr(pin, "version", missing)
    with pytest.raises(pin.BrainCreateDecoderPinError, match="package is unavailable"):
        pin._live_runtime_identity(tuple(_manifest()["runtime"]["packages"]))
