"""Adversarial host/runtime gates for the dynamic CREATE-v2 decoder pin."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

import metis_model1.brain_create_decoder_v2_pin as pin


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


def _complete_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = _manifest_root(tmp_path, monkeypatch, _manifest())
    for relative in (
        Path("qualification/uv.lock"),
        Path("schemas/metis-brain-create-delta-plan-body-v2.schema.json"),
        Path("src/metis_model1/initial_local_qlora_runtime.py"),
        Path("src/metis_model1/brain_mlx_runtime.py"),
        Path("src/metis_model1/brain_typed_create_pipeline.py"),
    ):
        source = pin.PROJECT_ROOT / relative
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    return root


def _qualified_live_identity(_names: tuple[str, ...]) -> tuple[str, dict[str, str]]:
    runtime = _manifest()["runtime"]
    return runtime["python"], dict(runtime["packages"])


def test_v2_pin_contract_is_exact_dynamic_and_nonpromotional() -> None:
    manifest = pin.load_brain_create_decoder_v2_pin()

    assert manifest["status"] == "runtime_contract_ready"
    assert manifest["wire"] == {"schema_version": 6, "operation": "plan_create_v2"}
    assert manifest["authoritative_schema"]["path"].endswith("body-v2.schema.json")
    assert manifest["decoder_constraint"]["payload"]["v"] == 1
    assert (
        manifest["bound_decoder_schema"]["sample_constraint_sha256"]
        == manifest["decoder_constraint"]["canonical_sha256"]
    )
    assert manifest["decoder_cache"]["maximum_entries"] == 32
    assert set(manifest["policy"].values()) == {True}
    assert "no_source_authority" in manifest["nonclaims"]
    assert "no_private_authority_exposure" in manifest["nonclaims"]
    assert "qualified" not in manifest["status"]
    assert pin.manifest_sha256(manifest) == pin.manifest_sha256(deepcopy(manifest))


def test_host_verifier_checks_all_bindings_without_worker_packages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(_names: tuple[str, ...]) -> tuple[str, dict[str, str]]:
        raise AssertionError("host verification must not inspect worker packages")

    monkeypatch.setattr(pin, "_live_runtime_identity", unavailable)
    manifest = _manifest()

    result = pin.verify_brain_create_decoder_v2_pin()

    assert result == {
        "status": "runtime_contract_ready",
        "manifest_sha256": pin.manifest_sha256(manifest),
        "wire_schema_version": 6,
        "decoder": "llguidance-1.8.0",
        "body_schema_sha256": manifest["authoritative_schema"]["sha256"],
        "projection_sha256": manifest["decoder_projection"]["canonical_sha256"],
        "constraint_sha256": manifest["decoder_constraint"]["canonical_sha256"],
        "bound_schema_sha256": manifest["bound_decoder_schema"]["canonical_sha256"],
        "prefix_sha256": manifest["create_prefix"]["canonical_sha256"],
        "worker_sha256": manifest["worker"]["sha256"],
        "decoder_cache_entries": 32,
        "package_count": 6,
    }


def test_worker_runtime_subset_has_an_independent_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pin, "_live_runtime_identity", _qualified_live_identity)
    assert pin.verify_brain_create_decoder_v2_runtime_subset() == {
        "status": "runtime_contract_ready",
        "python": "3.12.10",
        "packages": _manifest()["runtime"]["packages"],
    }


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        ("extra top-level", lambda value: value.update(extra=True)),
        ("missing top-level", lambda value: value.pop("host_guards")),
        ("promotional status", lambda value: value.update(status="qualified")),
        ("wire", lambda value: value["wire"].update(schema_version=5)),
        ("runtime network", lambda value: value["runtime"].update(network="allowed")),
        ("runtime package", lambda value: value["runtime"]["packages"].update(mlx="0.33.0")),
        (
            "body path",
            lambda value: value["authoritative_schema"].update(path="schemas/other.json"),
        ),
        (
            "projection implementation",
            lambda value: value["decoder_projection"].update(implementation="other"),
        ),
        (
            "constraint version",
            lambda value: value["decoder_constraint"]["payload"].update(v=2),
        ),
        (
            "constraint private value",
            lambda value: value["decoder_constraint"]["payload"]["d"][0].update(n="hostref:bad"),
        ),
        (
            "constraint digest",
            lambda value: value["decoder_constraint"].update(canonical_sha256="sha256:" + "0" * 64),
        ),
        (
            "bound sample digest",
            lambda value: value["bound_decoder_schema"].update(
                sample_constraint_sha256="sha256:" + "0" * 64
            ),
        ),
        ("prefix count", lambda value: value["create_prefix"].update(message_count=3)),
        ("worker path", lambda value: value["worker"].update(path="../worker.py")),
        ("cache cap", lambda value: value["decoder_cache"].update(maximum_entries=33)),
        ("host membership", lambda value: value["host_guards"].update(membership="other")),
        ("host guard traversal", lambda value: value["host_guards"].update(path="../pipeline.py")),
        (
            "policy weakened",
            lambda value: value["policy"].update(authoritative_host_admission_required=False),
        ),
        ("nonclaim removed", lambda value: value["nonclaims"].pop()),
        ("nonclaim order", lambda value: value["nonclaims"].reverse()),
    ],
)
def test_manifest_mutations_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, label: str, mutate: Any
) -> None:
    manifest = _manifest()
    mutate(manifest)
    root = _manifest_root(tmp_path, monkeypatch, manifest)
    with pytest.raises(pin.BrainCreateDecoderV2PinError):
        pin.load_brain_create_decoder_v2_pin(root)


def test_manifest_symlink_and_hardlink_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = pin.MANIFEST_PATH.read_bytes()
    outside = tmp_path / "outside.json"
    outside.write_bytes(raw)
    manifest = tmp_path / pin.MANIFEST_PATH.relative_to(pin.PROJECT_ROOT)
    manifest.parent.mkdir(parents=True)
    manifest.symlink_to(outside)
    with pytest.raises(pin.BrainCreateDecoderV2PinError, match="symlink"):
        pin.load_brain_create_decoder_v2_pin(tmp_path)

    manifest.unlink()
    os.link(outside, manifest)
    monkeypatch.setattr(pin, "MANIFEST_FILE_SHA256", pin._sha256(raw))
    with pytest.raises(pin.BrainCreateDecoderV2PinError, match="bounded regular file"):
        pin.load_brain_create_decoder_v2_pin(tmp_path)


@pytest.mark.parametrize(
    ("label", "target"),
    [
        ("qualification lock", "lock"),
        ("authoritative body schema", "schema"),
        ("CREATE v2 worker", "worker"),
        ("CREATE v2 host guards", "host"),
    ],
)
def test_every_bound_file_mutation_fails_closed(
    monkeypatch: pytest.MonkeyPatch, label: str, target: str
) -> None:
    original = pin._read_regular

    def read(root: Path, relative: Any, *, maximum: int, label: str) -> bytes:
        raw = original(root, relative, maximum=maximum, label=label)
        if target == "schema" and label == "authoritative body schema":
            value = json.loads(raw)
            value["title"] = "mutated"
            return pin._canonical(value)
        if (
            label
            == {
                "lock": "qualification lock",
                "schema": "authoritative body schema",
                "worker": "CREATE v2 worker",
                "host": "CREATE v2 host guards",
            }[target]
        ):
            return raw + b"\n"
        return raw

    monkeypatch.setattr(pin, "_read_regular", read)
    with pytest.raises(pin.BrainCreateDecoderV2PinError, match="differ"):
        pin.verify_brain_create_decoder_v2_pin()


def test_projection_constraint_bound_schema_and_prefix_mutations_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from metis_model1 import initial_local_qlora_runtime as runtime

    original_projection = runtime._create_plan_v2_decoder_schema
    monkeypatch.setattr(
        runtime,
        "_create_plan_v2_decoder_schema",
        lambda schema: {**original_projection(schema), "title": "mutated"},
    )
    with pytest.raises(pin.BrainCreateDecoderV2PinError, match="projection differs"):
        pin.verify_brain_create_decoder_v2_pin()

    monkeypatch.setattr(runtime, "_create_plan_v2_decoder_schema", original_projection)
    original_constraint = runtime._create_plan_v2_decoder_constraint
    monkeypatch.setattr(
        runtime,
        "_create_plan_v2_decoder_constraint",
        lambda value: {**original_constraint(value), "p": "sha256:" + "0" * 64},
    )
    with pytest.raises(pin.BrainCreateDecoderV2PinError, match="constraint differs"):
        pin.verify_brain_create_decoder_v2_pin()

    monkeypatch.setattr(runtime, "_create_plan_v2_decoder_constraint", original_constraint)
    original_bound = runtime._create_plan_v2_bound_decoder_schema
    monkeypatch.setattr(
        runtime,
        "_create_plan_v2_bound_decoder_schema",
        lambda schema, constraint: {**original_bound(schema, constraint), "title": "mutated"},
    )
    with pytest.raises(pin.BrainCreateDecoderV2PinError, match="bound decoder schema differs"):
        pin.verify_brain_create_decoder_v2_pin()

    monkeypatch.setattr(runtime, "_create_plan_v2_bound_decoder_schema", original_bound)
    monkeypatch.setattr(
        pin, "_prefix_from_source", lambda *args, **kwargs: (6, [{"role": "system"}])
    )
    with pytest.raises(pin.BrainCreateDecoderV2PinError, match="prefix differs"):
        pin.verify_brain_create_decoder_v2_pin()


def test_cache_and_host_guard_call_chain_mutations_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from metis_model1 import initial_local_qlora_runtime as runtime

    monkeypatch.setattr(runtime, "MAX_CREATE_PLAN_V2_DECODER_CACHE", 31)
    with pytest.raises(pin.BrainCreateDecoderV2PinError, match="worker constants differ"):
        pin.verify_brain_create_decoder_v2_pin()

    monkeypatch.setattr(runtime, "MAX_CREATE_PLAN_V2_DECODER_CACHE", 32)
    monkeypatch.setattr(pin, "_function_call_names", lambda *args, **kwargs: frozenset())
    with pytest.raises(pin.BrainCreateDecoderV2PinError, match="call chain differs"):
        pin.verify_brain_create_decoder_v2_pin()


@pytest.mark.parametrize(
    "identity",
    [
        ("3.13.0", _manifest()["runtime"]["packages"]),
        ("3.12.10", {**_manifest()["runtime"]["packages"], "mlx": "0.33.0"}),
        (
            "3.12.10",
            {
                key: value
                for key, value in _manifest()["runtime"]["packages"].items()
                if key != "mlx"
            },
        ),
    ],
)
def test_runtime_subset_drift_fails_closed(
    monkeypatch: pytest.MonkeyPatch, identity: tuple[str, dict[str, str]]
) -> None:
    monkeypatch.setattr(pin, "_live_runtime_identity", lambda _names: identity)
    with pytest.raises(pin.BrainCreateDecoderV2PinError, match="live decoder v2 runtime differs"):
        pin.verify_brain_create_decoder_v2_runtime_subset()


@pytest.mark.parametrize(
    ("interpreter", "verifier"),
    [
        (".venv/bin/python", "verify_brain_create_decoder_v2_pin"),
        ("qualification/.venv/bin/python", "verify_brain_create_decoder_v2_runtime_subset"),
    ],
)
def test_split_verifiers_run_in_their_real_interpreters(interpreter: str, verifier: str) -> None:
    executable = pin.PROJECT_ROOT / interpreter
    if not executable.is_file():
        pytest.skip(f"interpreter unavailable: {executable}")
    completed = subprocess.run(
        [
            str(executable),
            "-c",
            "import metis_model1.brain_create_decoder_v2_pin as p; "
            f"print(p.{verifier}()['status'])",
        ],
        cwd=pin.PROJECT_ROOT,
        env={**os.environ, "PYTHONPATH": "src"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "runtime_contract_ready"
