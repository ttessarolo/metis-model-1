"""Full-state SFT wrapper for the W4 qualification path.

This module deliberately keeps the training surface narrow: one process, one
example per batch, and no gradient accumulation.  The stock MLX-VLM trainer
persists adapter weights only.  This wrapper adds an atomic checkpoint with the
trainable model tree, optimizer tree, MLX/NumPy RNG state, and the sampler
cursor needed to resume the current epoch without silently changing data
order.

The module is import-safe: model loading and training happen only from
``main``.  Checkpoint payloads are intended to remain outside Git under the
repository's ignored ``artifacts/`` tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import re
import shutil
import tempfile
import time
from functools import partial
from importlib.metadata import version
from pathlib import Path
from typing import Any

import mlx.core as mx
import mlx.nn as nn
import mlx.optimizers as optim
import numpy as np
from datasets import load_dataset
from mlx.utils import tree_flatten, tree_unflatten
from mlx_vlm import load
from mlx_vlm.trainer.datasets import VisionDataset
from mlx_vlm.trainer.sft_trainer import (
    iterate_batches,
    vision_language_loss_fn,
)
from mlx_vlm.trainer.utils import (
    apply_lora_layers,
    find_all_linear_names,
    freeze_model,
    get_peft_model,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = (REPOSITORY_ROOT / "artifacts").resolve()
CHECKPOINT_SCHEMA_VERSION = 1
STATE_FILE = "state.json"
ARRAYS_FILE = "state.safetensors"
ADAPTER_FILE = "adapters.safetensors"
ADAPTER_CONFIG_FILE = "adapter_config.json"
MANIFEST_FILE = "manifest.json"
CHECKPOINT_PAYLOAD_FILES = (
    STATE_FILE,
    ARRAYS_FILE,
    ADAPTER_FILE,
    ADAPTER_CONFIG_FILE,
)
RUNTIME_PACKAGES = (
    "datasets",
    "jinja2",
    "mlx",
    "mlx-metal",
    "mlx-vlm",
    "numpy",
    "psutil",
    "safetensors",
    "transformers",
)
SAMPLER_CONTRACT = {
    "version": 1,
    "algorithm": "mlx_vlm.iterate_batches.numpy_permutation_per_epoch",
    "batch_size": 1,
    "drop_last": True,
    "world_size": 1,
}
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class FullStateError(RuntimeError):
    """Raised when a full-state checkpoint cannot be resumed safely."""


def require_artifact_path(path: Path, *, label: str) -> Path:
    """Resolve a path and keep generated/materialized data under artifacts."""

    expanded = path.expanduser()
    if expanded.is_symlink():
        raise FullStateError(f"{label} cannot be a symlink: {expanded}")
    resolved = expanded.resolve()
    if not resolved.is_relative_to(ARTIFACT_ROOT):
        raise FullStateError(f"{label} must stay under {ARTIFACT_ROOT}: {resolved}")
    return resolved


def _json_dump(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FullStateError(f"cannot read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise FullStateError(f"{label} must be a JSON object: {path}")
    return value


def _file_record(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise FullStateError(f"checkpoint payload is not a regular file: {path}")
    return {"bytes": path.stat().st_size, "sha256": _sha256_file(path)}


def _git_blob_sha1(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha1(usedforsecurity=False)
    digest.update(f"blob {size}\0".encode("ascii"))
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def runtime_identity() -> dict[str, Any]:
    """Return the exact runtime contract that must match across resume."""

    lock_path = REPOSITORY_ROOT / "qualification/uv.lock"
    pin_path = REPOSITORY_ROOT / "qualification/runtime-pin.json"
    if lock_path.is_symlink() or not lock_path.is_file():
        raise FullStateError(f"qualification lockfile is missing or unsafe: {lock_path}")
    if pin_path.is_symlink() or not pin_path.is_file():
        raise FullStateError(f"qualification runtime pin is missing or unsafe: {pin_path}")
    pin = _load_json_object(pin_path, label="qualification runtime pin")
    try:
        packages = {name: version(name) for name in RUNTIME_PACKAGES}
    except Exception as exc:
        raise FullStateError("cannot resolve the complete qualification runtime") from exc
    system = platform.system()
    machine = platform.machine()
    platform_pin = f"{'macos' if system == 'Darwin' else system.lower()}-{machine}"
    lock_sha256 = _sha256_file(lock_path)
    wrapper_sha256 = _sha256_file(Path(__file__))
    if (
        pin.get("schema_version") != 1
        or pin.get("python") != platform.python_version()
        or pin.get("platform") != platform_pin
        or pin.get("packages") != packages
        or pin.get("lock_sha256") != lock_sha256
        or pin.get("qualification_wrapper_sha256") != wrapper_sha256
        or not isinstance(pin.get("upstream_revisions"), dict)
    ):
        raise FullStateError("live runtime does not match qualification/runtime-pin.json")
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "system": system,
        "release": platform.release(),
        "machine": machine,
        "packages": packages,
        "upstream_revisions": pin["upstream_revisions"],
        "uv_lock_sha256": lock_sha256,
        "qualification_wrapper_sha256": wrapper_sha256,
    }


def verify_model_identity(model_path: Path, report_path: Path) -> dict[str, Any]:
    """Bind the run to the exact downloaded revision and every local payload."""

    if model_path.is_symlink() or not model_path.is_dir():
        raise FullStateError(f"model path is not a regular directory: {model_path}")
    if report_path.is_symlink() or not report_path.is_file():
        raise FullStateError(f"checkpoint verification report is missing or unsafe: {report_path}")
    pin_path = REPOSITORY_ROOT / "qualification/checkpoint-pin.json"
    if pin_path.is_symlink() or not pin_path.is_file():
        raise FullStateError(f"checkpoint policy pin is missing or unsafe: {pin_path}")
    pin = _load_json_object(pin_path, label="checkpoint policy pin")
    report_record = _file_record(report_path)
    report = _load_json_object(report_path, label="checkpoint verification report")
    if report.get("schema_version") != 1 or report.get("status") != "verified":
        raise FullStateError("checkpoint verification report is not a verified v1 report")
    if report.get("checkpoint_path") != str(model_path):
        raise FullStateError("checkpoint verification report path does not match --model-path")
    revision = report.get("revision")
    if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise FullStateError("checkpoint verification report has an invalid revision")
    repository = report.get("repository")
    if not isinstance(repository, str) or not repository:
        raise FullStateError("checkpoint verification report has no repository identity")
    if (
        pin.get("schema_version") != 1
        or pin.get("repository") != repository
        or pin.get("revision") != revision
        or pin.get("resolved_revision") != revision
        or pin.get("model_type") != report.get("model_type")
        or pin.get("quantization") != report.get("quantization")
        or pin.get("config_sha256") != report.get("config_sha256")
        or pin.get("tree_metadata_sha256") != report.get("tree_metadata_sha256")
        or pin.get("weight_files") != report.get("weight_files")
        or pin.get("verification_status") != "download_verified_all_weight_hashes_match"
    ):
        raise FullStateError("checkpoint verification report differs from policy pin")

    tree_path = model_path / ".cache/huggingface/trees" / f"{revision}.json"
    if tree_path.is_symlink() or not tree_path.is_file():
        raise FullStateError("exact-revision Hugging Face tree metadata is missing or unsafe")
    tree_record = _file_record(tree_path)
    if tree_record["sha256"] != report.get("tree_metadata_sha256"):
        raise FullStateError("Hugging Face tree metadata hash does not match verification report")
    tree = _load_json_object(tree_path, label="Hugging Face tree metadata")
    tree_files = tree.get("files")
    if tree.get("format_version") != 1 or not isinstance(tree_files, dict) or not tree_files:
        raise FullStateError("Hugging Face tree metadata has an unsupported structure")

    symlinks = sorted(item for item in model_path.rglob("*") if item.is_symlink())
    if symlinks:
        raise FullStateError(f"model payload contains a symlink: {symlinks[0]}")
    local_files = {
        str(item.relative_to(model_path)): item
        for item in model_path.rglob("*")
        if item.is_file() and not item.is_relative_to(model_path / ".cache")
    }
    expected_names = set(tree_files)
    if set(local_files) != expected_names:
        missing = sorted(expected_names - set(local_files))
        extra = sorted(set(local_files) - expected_names)
        raise FullStateError(
            f"model payload does not match pinned tree; missing={missing}, extra={extra}"
        )

    payload: list[dict[str, Any]] = []
    for name in sorted(expected_names):
        tree_row = tree_files[name]
        if not isinstance(tree_row, dict):
            raise FullStateError(f"invalid tree entry for model payload: {name}")
        path = local_files[name]
        record = _file_record(path)
        if record["bytes"] != tree_row.get("size"):
            raise FullStateError(f"model payload size differs from pinned tree: {name}")
        lfs_sha256 = tree_row.get("lfs_sha256")
        if lfs_sha256 is not None:
            if not isinstance(lfs_sha256, str) or not SHA256_PATTERN.fullmatch(lfs_sha256):
                raise FullStateError(f"invalid LFS identity in pinned tree: {name}")
            if record["sha256"] != lfs_sha256 or tree_row.get("lfs_size") != record["bytes"]:
                raise FullStateError(f"model payload LFS hash differs from pinned tree: {name}")
        else:
            blob_id = tree_row.get("blob_id")
            if not isinstance(blob_id, str) or not re.fullmatch(r"[0-9a-f]{40}", blob_id):
                raise FullStateError(f"invalid Git blob identity in pinned tree: {name}")
            if _git_blob_sha1(path) != blob_id:
                raise FullStateError(f"model payload Git hash differs from pinned tree: {name}")
        payload.append({"path": name, **record})

    config_path = model_path / "config.json"
    config = _load_json_object(config_path, label="model configuration")
    config_record = next(row for row in payload if row["path"] == "config.json")
    if config_record["sha256"] != report.get("config_sha256"):
        raise FullStateError("model configuration hash does not match verification report")
    if config.get("model_type") != report.get("model_type"):
        raise FullStateError("model type does not match verification report")
    if config.get("quantization") != report.get("quantization"):
        raise FullStateError("model quantization does not match verification report")

    reported_weights = report.get("weight_files")
    if not isinstance(reported_weights, list) or not reported_weights:
        raise FullStateError("checkpoint verification report has no verified weights")
    payload_by_name = {row["path"]: row for row in payload}
    for row in reported_weights:
        if not isinstance(row, dict):
            raise FullStateError("verified weight identity differs from local payload")
        name = row.get("path")
        size = row.get("bytes")
        sha256 = row.get("sha256")
        if (
            not isinstance(name, str)
            or type(size) is not int
            or not isinstance(sha256, str)
            or not SHA256_PATTERN.fullmatch(sha256)
            or payload_by_name.get(name) != {"path": name, "bytes": size, "sha256": sha256}
        ):
            raise FullStateError("verified weight identity differs from local payload")

    return {
        "checkpoint_path": str(model_path),
        "repository": repository,
        "revision": revision,
        "model_type": report["model_type"],
        "quantization": report["quantization"],
        "policy_pin": {
            "path": str(pin_path),
            "repository": repository,
            "revision": revision,
            "config_sha256": pin["config_sha256"],
            "tree_metadata_sha256": pin["tree_metadata_sha256"],
        },
        "verification_report": {"path": str(report_path), **report_record},
        "tree_metadata": {"path": str(tree_path), **tree_record},
        "payload": payload,
    }


def fingerprint_dataset(path: Path) -> dict[str, Any]:
    """Fingerprint local dataset files without embedding their payload."""

    path = path.resolve()
    if not path.exists():
        raise FullStateError(f"dataset does not exist: {path}")
    digest = hashlib.sha256()
    files: list[Path]
    if path.is_file():
        files = [path]
    elif path.is_dir():
        symlinks = sorted(item for item in path.rglob("*") if item.is_symlink())
        if symlinks:
            raise FullStateError(f"dataset contains a symlink: {symlinks[0]}")
        files = sorted(item for item in path.rglob("*") if item.is_file())
    else:
        raise FullStateError(f"dataset is not a regular file or directory: {path}")

    for item in files:
        relative = item.relative_to(path) if path.is_dir() else Path(item.name)
        digest.update(str(relative).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item.stat().st_size).encode("ascii"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(_sha256_file(item)))

    return {
        "path": str(path),
        "file_count": len(files),
        "sha256": digest.hexdigest(),
    }


def _encode_numpy_state(state: tuple[Any, ...]) -> dict[str, Any]:
    if len(state) != 5 or state[0] != "MT19937":
        raise FullStateError("unsupported NumPy RNG state")
    return {
        "bit_generator": state[0],
        "keys": np.asarray(state[1], dtype=np.uint32).tolist(),
        "position": int(state[2]),
        "has_gauss": int(state[3]),
        "cached_gaussian": float(state[4]),
    }


def _decode_numpy_state(value: Any) -> tuple[Any, ...]:
    if not isinstance(value, dict) or value.get("bit_generator") != "MT19937":
        raise FullStateError("checkpoint has an unsupported NumPy RNG state")
    raw_keys = value.get("keys")
    position = value.get("position")
    has_gauss = value.get("has_gauss")
    cached_gaussian = value.get("cached_gaussian")
    if (
        not isinstance(raw_keys, list)
        or len(raw_keys) != 624
        or not all(type(item) is int and 0 <= item <= 2**32 - 1 for item in raw_keys)
        or type(position) is not int
        or not 0 <= position <= 624
        or type(has_gauss) is not int
        or has_gauss not in (0, 1)
        or not isinstance(cached_gaussian, (int, float))
        or not np.isfinite(cached_gaussian)
    ):
        raise FullStateError("checkpoint has an invalid NumPy RNG key array")
    keys = np.asarray(raw_keys, dtype=np.uint32)
    return (
        "MT19937",
        keys,
        position,
        has_gauss,
        float(cached_gaussian),
    )


def capture_numpy_rng() -> dict[str, Any]:
    return _encode_numpy_state(np.random.get_state())


def restore_numpy_rng(value: Any) -> None:
    np.random.set_state(_decode_numpy_state(value))


def capture_python_rng() -> dict[str, Any]:
    version_number, state, gaussian = random.getstate()
    return {
        "version": int(version_number),
        "state": [int(item) for item in state],
        "gaussian": float(gaussian) if gaussian is not None else None,
    }


def restore_python_rng(value: Any) -> None:
    if not isinstance(value, dict) or value.get("version") != 3:
        raise FullStateError("checkpoint has an unsupported Python RNG state")
    state = value.get("state")
    if (
        not isinstance(state, list)
        or len(state) != 625
        or not all(type(item) is int and 0 <= item <= 2**32 - 1 for item in state[:624])
        or type(state[624]) is not int
        or not 0 <= state[624] <= 624
    ):
        raise FullStateError("checkpoint has an invalid Python RNG state")
    gaussian = value.get("gaussian")
    if gaussian is not None and (
        not isinstance(gaussian, (int, float)) or not np.isfinite(gaussian)
    ):
        raise FullStateError("checkpoint has an invalid Python Gaussian cache")
    random.setstate((3, tuple(state), gaussian))


def capture_mlx_rng() -> list[int]:
    """Capture the single MLX default-stream key as two uint32 values.

    MLX 0.32.1 exposes ``state[0]`` for the default stream but does not expose
    a pickleable state object or a public state setter.  ``mx.random.seed``
    accepts the equivalent packed uint64 seed; restore_mlx_rng verifies that
    the backend returned exactly the captured key.
    """

    key = np.asarray(mx.random.state[0], dtype=np.uint32)
    if key.shape != (2,):
        raise FullStateError(f"unsupported MLX RNG state shape: {key.shape}")
    return [int(key[0]), int(key[1])]


def restore_mlx_rng(value: Any) -> None:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(type(item) is int and 0 <= item <= 2**32 - 1 for item in value)
    ):
        raise FullStateError("checkpoint has an invalid MLX RNG state")
    packed_seed = (value[0] << 32) | value[1]
    mx.random.seed(packed_seed)
    restored = capture_mlx_rng()
    if restored != value:
        raise FullStateError(f"MLX RNG restore mismatch: expected {value}, got {restored}")


def seed_deterministically(seed: int) -> None:
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise FullStateError("seed must be an integer in [0, 2**64)")
    mx.random.seed(seed)
    np.random.seed(seed & 0xFFFFFFFF)
    random.seed(seed)


def _prefixed_arrays(prefix: str, tree: Any) -> dict[str, mx.array]:
    arrays: dict[str, mx.array] = {}
    for key, value in tree_flatten(tree):
        if not isinstance(value, mx.array):
            raise FullStateError(f"non-array leaf in {prefix}{key}: {type(value).__name__}")
        arrays[f"{prefix}{key}"] = value
    return arrays


def _tree_from_prefix(arrays: dict[str, mx.array], prefix: str) -> Any:
    rows = [(key[len(prefix) :], value) for key, value in arrays.items() if key.startswith(prefix)]
    if not rows:
        raise FullStateError(f"checkpoint is missing {prefix} state")
    return tree_unflatten(rows)


def _tree_signature(tree: Any) -> list[dict[str, Any]]:
    signature = []
    for key, value in tree_flatten(tree):
        if not isinstance(value, mx.array):
            raise FullStateError(f"non-array leaf in tree signature: {key}")
        signature.append({"key": key, "shape": list(value.shape), "dtype": str(value.dtype)})
    return sorted(signature, key=lambda item: item["key"])


def _assert_tree_compatible(expected: Any, actual: Any, label: str) -> None:
    if _tree_signature(expected) != _tree_signature(actual):
        raise FullStateError(f"{label} tree does not match the current model/runtime")


def _assert_tree_finite(
    tree: Any,
    label: str,
    *,
    require_any_nonzero: bool = False,
) -> None:
    """Evaluate every array leaf and reject NaN/Inf or an all-zero gradient tree."""

    leaves = tree_flatten(tree)
    if not leaves:
        raise FullStateError(f"{label} tree is empty")
    finite_checks: list[tuple[str, mx.array]] = []
    nonzero_checks: list[mx.array] = []
    for key, value in leaves:
        if not isinstance(value, mx.array) or value.size == 0:
            raise FullStateError(f"{label} has an invalid array leaf: {key}")
        finite_checks.append((key, mx.all(mx.isfinite(value))))
        if require_any_nonzero:
            nonzero_checks.append(mx.any(value != 0))
    mx.eval(*(check for _, check in finite_checks), *nonzero_checks)
    failed = [key for key, check in finite_checks if not bool(check.item())]
    if failed:
        raise FullStateError(f"{label} contains non-finite arrays: {failed[:5]}")
    if require_any_nonzero and not any(bool(check.item()) for check in nonzero_checks):
        raise FullStateError(f"{label} is entirely zero")


def _model_config_dict(model: Any) -> dict[str, Any]:
    config = getattr(model, "config", None)
    if isinstance(config, dict):
        return dict(config)
    values = getattr(config, "__dict__", None)
    if isinstance(values, dict):
        return dict(values)
    return {}


def _optimizer_config(optimizer: optim.Optimizer) -> dict[str, Any]:
    if not isinstance(optimizer, optim.Adam):
        raise FullStateError("W4 full-state wrapper currently supports mlx.optimizers.Adam only")
    return {
        "class": "mlx.optimizers.Adam",
        "learning_rate": float(optimizer.learning_rate.item()),
        "betas": [float(value) for value in optimizer.betas],
        "eps": float(optimizer.eps),
        "bias_correction": bool(optimizer.bias_correction),
    }


def _make_optimizer(config: dict[str, Any]) -> optim.Adam:
    if not isinstance(config, dict) or set(config) != {
        "class",
        "learning_rate",
        "betas",
        "eps",
        "bias_correction",
    }:
        raise FullStateError("checkpoint optimizer configuration is malformed")
    learning_rate = config.get("learning_rate")
    betas = config.get("betas")
    eps = config.get("eps")
    bias_correction = config.get("bias_correction")
    if (
        config.get("class") != "mlx.optimizers.Adam"
        or not isinstance(learning_rate, (int, float))
        or not np.isfinite(learning_rate)
        or learning_rate <= 0
        or not isinstance(betas, list)
        or len(betas) != 2
        or not all(isinstance(value, (int, float)) and 0 <= value < 1 for value in betas)
        or not isinstance(eps, (int, float))
        or not np.isfinite(eps)
        or eps <= 0
        or type(bias_correction) is not bool
    ):
        raise FullStateError("checkpoint optimizer configuration is not supported")
    return optim.Adam(
        learning_rate=float(learning_rate),
        betas=[float(value) for value in betas],
        eps=float(eps),
        bias_correction=bias_correction,
    )


def _write_adapter_files(model: Any, directory: Path) -> None:
    model_config = getattr(model, "config", None)
    config = (
        model_config.get("lora")
        if isinstance(model_config, dict)
        else getattr(model_config, "lora", None)
    )
    if not isinstance(config, dict):
        raise FullStateError("model has no LoRA configuration to checkpoint")
    trainable = dict(sorted(tree_flatten(model.trainable_parameters())))
    if not trainable:
        raise FullStateError("model has no trainable parameters to checkpoint")
    _json_dump(directory / ADAPTER_CONFIG_FILE, config)
    mx.save_safetensors(str(directory / ADAPTER_FILE), trainable)
    _fsync_file(directory / ADAPTER_FILE)


def _checkpoint_manifest(directory: Path, global_step: int) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "complete",
        "global_step": global_step,
        "files": {name: _file_record(directory / name) for name in CHECKPOINT_PAYLOAD_FILES},
    }


def _validate_checkpoint_manifest(checkpoint: Path) -> dict[str, Any]:
    manifest_path = checkpoint / MANIFEST_FILE
    manifest = _load_json_object(manifest_path, label="checkpoint manifest")
    if manifest.get("schema_version") != 1 or manifest.get("status") != "complete":
        raise FullStateError("checkpoint manifest is not a complete v1 manifest")
    global_step = manifest.get("global_step")
    if type(global_step) is not int or global_step < 0:
        raise FullStateError("checkpoint manifest has an invalid global step")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(CHECKPOINT_PAYLOAD_FILES):
        raise FullStateError("checkpoint manifest has an invalid payload set")
    for name in CHECKPOINT_PAYLOAD_FILES:
        expected = files[name]
        if (
            not isinstance(expected, dict)
            or type(expected.get("bytes")) is not int
            or expected["bytes"] < 0
            or not isinstance(expected.get("sha256"), str)
            or not SHA256_PATTERN.fullmatch(expected["sha256"])
        ):
            raise FullStateError(f"checkpoint manifest has an invalid record: {name}")
        actual = _file_record(checkpoint / name)
        if actual != expected:
            raise FullStateError(f"checkpoint payload hash/size mismatch: {name}")
    return manifest


def _checkpoint_metadata(
    *,
    model: Any,
    model_identity: dict[str, Any],
    runtime: dict[str, Any],
    dataset_fingerprint: dict[str, Any],
    split: str,
    training_config: dict[str, Any],
    optimizer: optim.Optimizer,
    global_step: int,
    sampler: dict[str, Any],
    last_metrics: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "status": "complete",
        "created_at_unix": time.time(),
        "global_step": int(global_step),
        "model": model_identity,
        "dataset": {"split": split, "fingerprint": dataset_fingerprint},
        "training_config": training_config,
        "distributed": {"world_size": 1, "rank": 0},
        "optimizer": _optimizer_config(optimizer),
        "model_trainable_signature": _tree_signature(model.trainable_parameters()),
        "optimizer_state_signature": _tree_signature(optimizer.state),
        "rng": {
            "mlx": capture_mlx_rng(),
            "numpy": capture_numpy_rng(),
            "python": capture_python_rng(),
        },
        "sampler": sampler,
        "last_metrics": last_metrics,
        "runtime": runtime,
    }


def save_checkpoint(
    *,
    checkpoint_root: Path,
    model: Any,
    optimizer: optim.Optimizer,
    model_identity: dict[str, Any],
    runtime: dict[str, Any],
    dataset_fingerprint: dict[str, Any],
    split: str,
    training_config: dict[str, Any],
    global_step: int,
    sampler: dict[str, Any],
    last_metrics: dict[str, Any] | None,
) -> Path:
    """Write one complete checkpoint and promote its directory atomically."""

    if type(global_step) is not int or global_step < 0:
        raise FullStateError("global_step cannot be negative")
    checkpoint_root.mkdir(parents=True, exist_ok=True)
    target = checkpoint_root / f"step-{global_step:08d}"
    if target.exists() or target.is_symlink():
        raise FullStateError(f"refusing to overwrite existing checkpoint: {target}")

    mx.eval(model, optimizer.state)
    _assert_tree_finite(model.trainable_parameters(), "trainable model state")
    _assert_tree_finite(optimizer.state, "optimizer state")
    _validate_sampler_state(sampler, global_step=global_step)
    arrays = _prefixed_arrays("model.", model.trainable_parameters())
    arrays.update(_prefixed_arrays("optimizer.", optimizer.state))
    arrays = dict(sorted(arrays.items()))
    metadata = _checkpoint_metadata(
        model=model,
        model_identity=model_identity,
        runtime=runtime,
        dataset_fingerprint=dataset_fingerprint,
        split=split,
        training_config=training_config,
        optimizer=optimizer,
        global_step=global_step,
        sampler=sampler,
        last_metrics=last_metrics,
    )
    metadata["arrays_signature"] = sorted(
        (
            {"key": key, "shape": list(value.shape), "dtype": str(value.dtype)}
            for key, value in arrays.items()
        ),
        key=lambda item: item["key"],
    )

    temporary = Path(tempfile.mkdtemp(prefix=f".step-{global_step:08d}-", dir=checkpoint_root))
    try:
        mx.save_safetensors(str(temporary / ARRAYS_FILE), arrays)
        _fsync_file(temporary / ARRAYS_FILE)
        _write_adapter_files(model, temporary)
        _json_dump(temporary / STATE_FILE, metadata)
        _json_dump(temporary / MANIFEST_FILE, _checkpoint_manifest(temporary, global_step))
        directory_fd = os.open(temporary, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        os.replace(temporary, target)
        parent_fd = os.open(checkpoint_root, os.O_RDONLY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except Exception:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return target


def _read_checkpoint(checkpoint: Path) -> tuple[dict[str, Any], dict[str, mx.array]]:
    if not checkpoint.is_dir() or checkpoint.is_symlink():
        raise FullStateError(f"checkpoint is not a directory: {checkpoint}")
    required = [*CHECKPOINT_PAYLOAD_FILES, MANIFEST_FILE]
    missing = [name for name in required if not (checkpoint / name).is_file()]
    if missing:
        raise FullStateError(f"checkpoint is incomplete; missing: {', '.join(missing)}")
    unsafe = [name for name in required if (checkpoint / name).is_symlink()]
    if unsafe:
        raise FullStateError(f"checkpoint contains symlink payloads: {', '.join(unsafe)}")
    manifest = _validate_checkpoint_manifest(checkpoint)
    metadata = _load_json_object(checkpoint / STATE_FILE, label="checkpoint metadata")
    if metadata.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
        raise FullStateError("unsupported full-state checkpoint schema")
    if metadata.get("status") != "complete":
        raise FullStateError("checkpoint is not marked complete")
    if metadata.get("global_step") != manifest["global_step"]:
        raise FullStateError("checkpoint metadata and manifest global steps differ")
    try:
        arrays = mx.load(str(checkpoint / ARRAYS_FILE))
    except Exception as exc:
        raise FullStateError(f"cannot read checkpoint tensor state: {checkpoint}") from exc
    if not isinstance(arrays, dict):
        raise FullStateError("checkpoint arrays are not a tensor dictionary")
    return metadata, arrays


def _training_config(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "batch_size": int(args.batch_size),
        "gradient_accumulation_steps": int(args.gradient_accumulation_steps),
        "max_seq_length": int(args.max_seq_length),
        "learning_rate": float(args.learning_rate),
        "lora_rank": int(args.lora_rank),
        "lora_alpha": float(args.lora_alpha),
        "lora_dropout": float(args.lora_dropout),
        "train_on_completions": bool(args.train_on_completions),
        "assistant_id": int(args.assistant_id),
        "seed": int(args.seed),
    }


def _validate_args(args: argparse.Namespace) -> None:
    if args.batch_size != 1:
        raise FullStateError("W4 full-state wrapper requires --batch-size 1")
    if args.gradient_accumulation_steps != 1:
        raise FullStateError("W4 full-state wrapper requires --gradient-accumulation-steps 1")
    if args.iters < 1:
        raise FullStateError("--iters must be positive")
    if args.checkpoint_every < 1 or args.steps_per_report < 1:
        raise FullStateError("checkpoint/report intervals must be positive")
    if args.max_seq_length < 2:
        raise FullStateError("--max-seq-length must be at least 2")
    if (
        args.lora_rank < 1
        or not np.isfinite(args.lora_alpha)
        or args.lora_alpha <= 0
        or not np.isfinite(args.lora_dropout)
        or args.lora_dropout < 0
        or not np.isfinite(args.learning_rate)
        or args.learning_rate <= 0
    ):
        raise FullStateError("invalid LoRA parameters")
    if args.lora_dropout >= 1:
        raise FullStateError("--lora-dropout must be less than 1")


def _load_local_json_dataset(path: Path, split: str) -> Any:
    if path.is_file():
        data_file = str(path)
    elif path.is_dir():
        candidates = sorted(path.glob("*.jsonl")) + sorted(path.glob("*.json"))
        if not candidates:
            raise FullStateError(f"dataset directory has no JSON/JSONL files: {path}")
        preferred = [item for item in candidates if item.name in {"train.jsonl", "train.json"}]
        if len(preferred) == 1:
            candidates = preferred
        elif len(candidates) != 1:
            raise FullStateError(
                "dataset directory must contain exactly one JSON/JSONL file "
                "or a uniquely named train.jsonl/train.json"
            )
        data_file = [str(item) for item in candidates]
    else:
        raise FullStateError(f"dataset path is not readable: {path}")
    dataset = load_dataset("json", data_files={split: data_file}, split=split)
    columns = set(dataset.column_names)
    if not ({"messages", "conversations"} & columns):
        raise FullStateError("text-only SFT dataset must contain messages or conversations")
    media_columns = columns & {"image", "images", "audio", "audios", "video", "videos"}
    if media_columns:
        raise FullStateError(
            "text-only SFT dataset contains media columns: " + ", ".join(sorted(media_columns))
        )
    return dataset


def _validate_adapter_config(
    adapter_config: Any,
    training_config: dict[str, Any],
    *,
    expected_keys: list[str] | None = None,
) -> None:
    """Ensure the adapter architecture agrees with the resumable CLI contract."""

    if not isinstance(adapter_config, dict):
        raise FullStateError("adapter configuration must be a JSON object")
    parameters = adapter_config.get("lora_parameters")
    if (
        set(adapter_config) != {"fine_tune_type", "num_layers", "lora_parameters"}
        or adapter_config.get("fine_tune_type") != "lora"
        or adapter_config.get("num_layers") != -1
        or not isinstance(parameters, dict)
        or set(parameters) != {"rank", "dropout", "scale", "keys"}
    ):
        raise FullStateError("checkpoint adapter configuration is not the supported LoRA form")
    rank = parameters.get("rank")
    dropout = parameters.get("dropout")
    scale = parameters.get("scale")
    keys = parameters.get("keys")
    expected_rank = training_config.get("lora_rank")
    expected_dropout = training_config.get("lora_dropout")
    expected_alpha = training_config.get("lora_alpha")
    if (
        type(expected_rank) is not int
        or expected_rank < 1
        or not isinstance(expected_dropout, (int, float))
        or not np.isfinite(expected_dropout)
        or not isinstance(expected_alpha, (int, float))
        or not np.isfinite(expected_alpha)
        or expected_alpha <= 0
    ):
        raise FullStateError("training configuration has invalid LoRA parameters")
    if (
        type(rank) is not int
        or rank != expected_rank
        or not isinstance(dropout, (int, float))
        or not np.isfinite(dropout)
        or float(dropout) != float(expected_dropout)
        or not isinstance(scale, (int, float))
        or not np.isfinite(scale)
        or float(scale) != float(expected_alpha) / float(expected_rank)
        or not isinstance(keys, list)
        or not keys
        or not all(isinstance(key, str) and key for key in keys)
        or len(keys) != len(set(keys))
        or (expected_keys is not None and keys != expected_keys)
    ):
        raise FullStateError("checkpoint adapter configuration does not match training config")


def _make_train_dataset(
    dataset: Any, model: Any, processor: Any, args: argparse.Namespace
) -> VisionDataset:
    config = _model_config_dict(model)
    if not (config.get("image_token_index") or config.get("image_token_id")):
        raise FullStateError(
            "MLX-VLM VisionDataset requires image_token_index/image_token_id "
            "even for its text-only path"
        )
    return VisionDataset(
        dataset,
        config,
        processor,
        train_on_completions=args.train_on_completions,
    )


def _setup_model_and_processor(
    *,
    model_path: Path,
    checkpoint: Path | None,
    expected_model_type: str,
    args: argparse.Namespace,
) -> tuple[Any, Any]:
    model, processor = load(
        str(model_path),
        lazy=False,
        strict=True,
        trust_remote_code=False,
    )
    if _model_config_dict(model).get("model_type") != expected_model_type:
        raise FullStateError("loaded model type differs from verified checkpoint identity")
    language_model = getattr(model, "language_model", None)
    if language_model is None:
        raise FullStateError("model has no language_model for LoRA setup")
    modules = find_all_linear_names(language_model)
    if not modules:
        raise FullStateError("no linear layers available for LoRA setup")
    target_names = set(modules)
    expected_keys = [
        f"language_model.{name}"
        for name, module in language_model.named_modules()
        if isinstance(module, (nn.Linear, nn.QuantizedLinear))
        and name.split(".")[-1] in target_names
    ]
    if not expected_keys:
        raise FullStateError("verified model produced no canonical LoRA target keys")
    if checkpoint is not None:
        freeze_model(model)
        adapter_config = _load_json_object(
            checkpoint / ADAPTER_CONFIG_FILE,
            label="adapter configuration",
        )
        _validate_adapter_config(
            adapter_config,
            _training_config(args),
            expected_keys=expected_keys,
        )
        model = apply_lora_layers(model, str(checkpoint))
        config = getattr(model, "config", None)
        if isinstance(config, dict):
            config["lora"] = adapter_config
        else:
            config.lora = adapter_config
    else:
        model = get_peft_model(
            model,
            modules,
            rank=args.lora_rank,
            alpha=args.lora_alpha,
            dropout=args.lora_dropout,
            verbose=False,
        )
    model.train()
    return model, processor


def _sampler_state(
    epoch: int,
    cursor: int,
    batch_count: int,
    epoch_start_numpy: dict[str, Any],
    epoch_start_python: dict[str, Any],
) -> dict[str, Any]:
    return {
        "contract": SAMPLER_CONTRACT,
        "epoch": int(epoch),
        "cursor": int(cursor),
        "batch_count": int(batch_count),
        "epoch_start_numpy": epoch_start_numpy,
        "epoch_start_python": epoch_start_python,
    }


def _validate_sampler_state(
    sampler: Any,
    *,
    global_step: int,
    expected_batch_count: int | None = None,
) -> tuple[int, int, int]:
    if not isinstance(sampler, dict) or sampler.get("contract") != SAMPLER_CONTRACT:
        raise FullStateError("checkpoint has an unsupported sampler contract")
    epoch = sampler.get("epoch")
    cursor = sampler.get("cursor")
    batch_count = sampler.get("batch_count")
    if any(type(value) is not int for value in (epoch, cursor, batch_count)):
        raise FullStateError("checkpoint sampler counters must be exact integers")
    if epoch < 0 or batch_count < 1 or cursor < 0 or cursor >= batch_count:
        raise FullStateError("checkpoint has invalid sampler counters")
    if expected_batch_count is not None and batch_count != expected_batch_count:
        raise FullStateError("checkpoint batch count does not match current dataset")
    if global_step != epoch * batch_count + cursor:
        raise FullStateError("checkpoint sampler/global-step invariant does not hold")
    _decode_numpy_state(sampler.get("epoch_start_numpy"))
    python_rng = sampler.get("epoch_start_python")
    if not isinstance(python_rng, dict):
        raise FullStateError("checkpoint sampler is missing its Python epoch-start RNG")
    version_number = python_rng.get("version")
    state = python_rng.get("state")
    gaussian = python_rng.get("gaussian")
    if (
        version_number != 3
        or not isinstance(state, list)
        or len(state) != 625
        or not all(type(item) is int and 0 <= item <= 2**32 - 1 for item in state[:624])
        or type(state[624]) is not int
        or not 0 <= state[624] <= 624
        or (
            gaussian is not None
            and (not isinstance(gaussian, (int, float)) or not np.isfinite(gaussian))
        )
    ):
        raise FullStateError("checkpoint sampler has an invalid Python epoch-start RNG")
    return epoch, cursor, batch_count


def _validate_resume(
    *,
    metadata: dict[str, Any],
    checkpoint: Path,
    model_identity: dict[str, Any],
    runtime: dict[str, Any],
    dataset_fingerprint: dict[str, Any],
    split: str,
    training_config: dict[str, Any],
    target_iters: int,
) -> None:
    if metadata.get("model") != model_identity:
        raise FullStateError("checkpoint model identity does not match verified local payload")
    if metadata.get("runtime") != runtime:
        raise FullStateError("checkpoint runtime identity does not match current environment")
    saved_dataset = metadata.get("dataset")
    if not isinstance(saved_dataset, dict) or saved_dataset.get("split") != split:
        raise FullStateError("checkpoint dataset split does not match --split")
    if saved_dataset.get("fingerprint") != dataset_fingerprint:
        raise FullStateError("checkpoint dataset fingerprint does not match input dataset")
    saved_config = metadata.get("training_config")
    if saved_config != training_config:
        raise FullStateError("checkpoint training configuration does not match current CLI")
    adapter_config = _load_json_object(
        checkpoint / ADAPTER_CONFIG_FILE,
        label="adapter configuration",
    )
    _validate_adapter_config(adapter_config, training_config)
    global_step = metadata.get("global_step")
    if type(global_step) is not int or global_step < 0 or global_step > target_iters:
        raise FullStateError("checkpoint global_step is incompatible with --iters")
    sampler = metadata.get("sampler")
    _validate_sampler_state(sampler, global_step=global_step)
    rng = metadata.get("rng")
    if not isinstance(rng, dict) or set(rng) != {"mlx", "numpy", "python"}:
        raise FullStateError("checkpoint is missing complete RNG state")
    restore_mlx_rng(rng["mlx"])
    restore_numpy_rng(rng["numpy"])
    restore_python_rng(rng["python"])
    if not isinstance(metadata.get("optimizer"), dict):
        raise FullStateError("checkpoint is missing optimizer configuration")
    if not isinstance(metadata.get("arrays_signature"), list):
        raise FullStateError("checkpoint is missing tensor-state signature")
    if metadata.get("distributed") != {"world_size": 1, "rank": 0}:
        raise FullStateError("checkpoint was not produced by the single-process wrapper")


def _restore_state(
    *,
    model: Any,
    optimizer: optim.Optimizer,
    arrays: dict[str, mx.array],
    metadata: dict[str, Any],
) -> int:
    actual_arrays_signature = sorted(
        (
            {"key": key, "shape": list(value.shape), "dtype": str(value.dtype)}
            for key, value in arrays.items()
        ),
        key=lambda item: item["key"],
    )
    expected_arrays_signature = metadata.get("arrays_signature")
    if actual_arrays_signature != expected_arrays_signature:
        raise FullStateError("checkpoint tensor-state signature does not match payload")
    model_state = _tree_from_prefix(arrays, "model.")
    optimizer_state = _tree_from_prefix(arrays, "optimizer.")
    _assert_tree_compatible(model.trainable_parameters(), model_state, "model")
    optimizer.init(model.trainable_parameters())
    _assert_tree_compatible(optimizer.state, optimizer_state, "optimizer")
    model.update(model_state, strict=False)
    optimizer.state = optimizer_state
    mx.eval(model, optimizer.state)
    _assert_tree_finite(model.trainable_parameters(), "restored trainable model state")
    _assert_tree_finite(optimizer.state, "restored optimizer state")
    restore_mlx_rng(metadata["rng"]["mlx"])
    restore_numpy_rng(metadata["rng"]["numpy"])
    restore_python_rng(metadata["rng"]["python"])
    expected_step = int(metadata["global_step"])
    actual_step = int(np.asarray(optimizer.step))
    if actual_step != expected_step:
        raise FullStateError(
            f"optimizer step {actual_step} does not match checkpoint global_step {expected_step}"
        )
    return expected_step


def run(args: argparse.Namespace) -> dict[str, Any]:
    _validate_args(args)
    model_path = require_artifact_path(args.model_path, label="model path")
    checkpoint_report = require_artifact_path(
        args.checkpoint_report,
        label="checkpoint verification report",
    )
    dataset_path = require_artifact_path(args.dataset, label="dataset path")
    checkpoint_root = require_artifact_path(args.checkpoint_root, label="checkpoint root")
    resume = require_artifact_path(args.resume, label="resume checkpoint") if args.resume else None
    telemetry_path = (
        require_artifact_path(args.telemetry_path, label="telemetry path")
        if args.telemetry_path
        else None
    )
    model_identity = verify_model_identity(model_path, checkpoint_report)
    current_runtime = runtime_identity()
    dataset_fp = fingerprint_dataset(dataset_path)
    training_config = _training_config(args)
    world = mx.distributed.init()
    if world.size() != 1 or world.rank() != 0:
        raise FullStateError("W4 full-state wrapper requires one MLX process (rank 0)")

    if resume is not None:
        metadata, arrays = _read_checkpoint(resume)
        _validate_resume(
            metadata=metadata,
            checkpoint=resume,
            model_identity=model_identity,
            runtime=current_runtime,
            dataset_fingerprint=dataset_fp,
            split=args.split,
            training_config=training_config,
            target_iters=args.iters,
        )
        checkpoint_for_adapter = resume
        seed_deterministically(args.seed)
    else:
        metadata = None
        arrays = None
        checkpoint_for_adapter = None
        seed_deterministically(args.seed)

    model, processor = _setup_model_and_processor(
        model_path=model_path,
        checkpoint=checkpoint_for_adapter,
        expected_model_type=model_identity["model_type"],
        args=args,
    )
    dataset = _load_local_json_dataset(dataset_path, args.split)
    train_dataset = _make_train_dataset(dataset, model, processor, args)
    batch_count = len(train_dataset) // args.batch_size
    if batch_count < 1:
        raise FullStateError("dataset must contain at least one complete batch")

    optimizer_config = (
        metadata["optimizer"]
        if metadata is not None
        else {
            "class": "mlx.optimizers.Adam",
            "learning_rate": args.learning_rate,
            "betas": [0.9, 0.999],
            "eps": 1e-8,
            "bias_correction": False,
        }
    )
    optimizer = _make_optimizer(optimizer_config)
    optimizer.init(model.trainable_parameters())
    if metadata is not None and arrays is not None:
        global_step = _restore_state(
            model=model,
            optimizer=optimizer,
            arrays=arrays,
            metadata=metadata,
        )
        sampler_metadata = metadata["sampler"]
        epoch, cursor, _ = _validate_sampler_state(
            sampler_metadata,
            global_step=global_step,
            expected_batch_count=batch_count,
        )
        epoch_start_numpy = sampler_metadata["epoch_start_numpy"]
        epoch_start_python = sampler_metadata["epoch_start_python"]
        restore_numpy_rng(epoch_start_numpy)
        restore_python_rng(epoch_start_python)
        iterator = iter(
            iterate_batches(
                train_dataset,
                batch_size=1,
                max_seq_length=args.max_seq_length,
                train=True,
            )
        )
        for _ in range(cursor):
            next(iterator)
        if capture_numpy_rng() != metadata["rng"]["numpy"]:
            raise FullStateError("sampler replay did not reproduce saved NumPy RNG state")
        if capture_python_rng() != metadata["rng"]["python"]:
            raise FullStateError("sampler replay did not reproduce saved Python RNG state")
        if capture_mlx_rng() != metadata["rng"]["mlx"]:
            raise FullStateError("sampler replay unexpectedly changed MLX RNG state")
        restore_numpy_rng(metadata["rng"]["numpy"])
        restore_python_rng(metadata["rng"]["python"])
    else:
        global_step = 0
        epoch = 0
        cursor = 0
        epoch_start_numpy = capture_numpy_rng()
        epoch_start_python = capture_python_rng()
        iterator = iter(
            iterate_batches(
                train_dataset,
                batch_size=1,
                max_seq_length=args.max_seq_length,
                train=True,
            )
        )

    loss_fn = partial(
        vision_language_loss_fn,
        train_on_completions=args.train_on_completions,
        assistant_id=args.assistant_id,
    )
    loss_value_and_grad = nn.value_and_grad(model, loss_fn)
    started = time.time()
    telemetry_handle = None
    if telemetry_path is not None:
        telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        if telemetry_path.exists() or telemetry_path.is_symlink():
            raise FullStateError(f"refusing to append to existing telemetry: {telemetry_path}")
        telemetry_handle = telemetry_path.open("x", encoding="utf-8")

    last_metrics: dict[str, Any] | None = None
    try:
        while global_step < args.iters:
            batch = next(iterator)
            loss_value, gradients = loss_value_and_grad(model, batch)
            mx.eval(loss_value, gradients)
            loss = float(loss_value.item())
            if not np.isfinite(loss):
                raise FullStateError("training produced a non-finite loss before update")
            _assert_tree_finite(
                gradients,
                "gradient state",
            )
            optimizer.update(model, gradients)
            mx.eval(model, optimizer.state)
            _assert_tree_finite(model.trainable_parameters(), "updated trainable model state")
            _assert_tree_finite(optimizer.state, "updated optimizer state")
            mx.clear_cache()
            global_step += 1
            cursor += 1
            if cursor == batch_count:
                epoch += 1
                cursor = 0
                epoch_start_numpy = capture_numpy_rng()
                epoch_start_python = capture_python_rng()

            last_metrics = {
                "global_step": global_step,
                "loss": loss,
                "peak_metal_gb": float(mx.get_peak_memory() / 1e9),
                "elapsed_seconds": float(time.time() - started),
            }
            if not all(
                np.isfinite(last_metrics[key])
                for key in ("loss", "peak_metal_gb", "elapsed_seconds")
            ):
                raise FullStateError("training produced a non-finite loss or telemetry value")
            if global_step % args.steps_per_report == 0 or global_step == args.iters:
                line = json.dumps(last_metrics, sort_keys=True)
                print(line, flush=True)
                if telemetry_handle is not None:
                    telemetry_handle.write(line + "\n")
                    telemetry_handle.flush()

            if global_step % args.checkpoint_every == 0 or global_step == args.iters:
                save_checkpoint(
                    checkpoint_root=checkpoint_root,
                    model=model,
                    optimizer=optimizer,
                    model_identity=model_identity,
                    runtime=current_runtime,
                    dataset_fingerprint=dataset_fp,
                    split=args.split,
                    training_config=training_config,
                    global_step=global_step,
                    sampler=_sampler_state(
                        epoch,
                        cursor,
                        batch_count,
                        epoch_start_numpy,
                        epoch_start_python,
                    ),
                    last_metrics=last_metrics,
                )
    finally:
        if telemetry_handle is not None:
            telemetry_handle.close()
    return {
        "status": "pass",
        "global_step": global_step,
        "checkpoint_root": str(checkpoint_root),
        "last_metrics": last_metrics,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run deterministic W4 text-only SFT with atomic full-state resume."
    )
    parser.add_argument(
        "--model-path",
        type=Path,
        required=True,
        help="Local MLX model directory under artifacts/",
    )
    parser.add_argument(
        "--checkpoint-report",
        type=Path,
        required=True,
        help="Verified checkpoint identity report under artifacts/",
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        required=True,
        help="Local JSON/JSONL dataset under artifacts/",
    )
    parser.add_argument("--split", default="train")
    parser.add_argument("--iters", type=int, required=True, help="Target global optimizer step")
    parser.add_argument(
        "--checkpoint-root",
        type=Path,
        required=True,
        help="Parent directory for step-* checkpoints",
    )
    parser.add_argument("--resume", type=Path, help="Complete step-* checkpoint to resume")
    parser.add_argument(
        "--telemetry-path",
        type=Path,
        help="Optional JSONL loss/peak-memory output",
    )
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument("--steps-per-report", type=int, default=1)
    parser.add_argument("--batch-size", type=int, default=1)
    parser.add_argument("--gradient-accumulation-steps", type=int, default=1)
    parser.add_argument("--max-seq-length", type=int, default=2048)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--lora-rank", type=int, default=8)
    parser.add_argument("--lora-alpha", type=float, default=16.0)
    parser.add_argument("--lora-dropout", type=float, default=0.0)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--assistant-id", type=int, default=77091)
    parser.add_argument(
        "--train-on-completions",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Mask prompt tokens and optimize assistant completions only",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        report = run(args)
    except FullStateError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
