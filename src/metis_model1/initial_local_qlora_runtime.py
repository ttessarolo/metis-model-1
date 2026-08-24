"""Fail-closed, bounded runtime helpers for INITIAL_LOCAL_QLORA_V1.

The module deliberately keeps MLX imports inside the evaluation worker.  All
validation and packaging paths are deterministic and testable without a model.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT_PIN = PROJECT_ROOT / "qualification/checkpoint-pin.json"
CHECKPOINT_REPORT = (
    PROJECT_ROOT / "artifacts/w5-xs/2026-08-24-delivery/preflight/checkpoint-verification.json"
)
BASE_CHECKPOINT = PROJECT_ROOT / "artifacts/w4/2026-08-20-qualification/checkpoint"
RUNTIME_PIN = PROJECT_ROOT / "qualification/runtime-pin.json"
RUNTIME_LOCK = PROJECT_ROOT / "qualification/uv.lock"
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "artifacts/initial-local-qlora-v1/run-v1"
DEFAULT_SELECTION_RECEIPT = DEFAULT_OUTPUT_ROOT / "selection.json"
DEFAULT_RESTORE_RECEIPT = DEFAULT_OUTPUT_ROOT / "adapter-off-restore.json"
DEFAULT_TRAINING_RECEIPT = DEFAULT_OUTPUT_ROOT / "training-receipt.json"
CONFIG = {
    "rank": 8,
    "alpha": 16,
    "learning_rate": 1e-5,
    "seed": 17,
    "max_seq_length": 1024,
    "batch_size": 1,
    "gradient_accumulation": 1,
    "dropout": 0.0,
    "completion_only": True,
}
LIMITS = {"hours": 4, "metal_gb": 110, "new_artifacts_gb": 8, "checkpoints": 4}
VERDICTS = {"LOCAL_ADAPTER_UPLIFT", "LOCAL_ADAPTER_EXPERIMENTAL"}
PACKAGE_FILES = {
    "CARD.md",
    "adapter_config.json",
    "adapters.safetensors",
    "dataset-receipt.json",
    "evaluation-receipt.json",
    "manifest.json",
    "package-checksum.json",
    "runtime.lock",
    "selection-receipt.json",
    "restore-receipt.json",
    "training-receipt.json",
}
CATEGORY_COUNTS = {"F-1": 5, "F-2": 5, "F-3": 6}
CATALOG_PIN_SHA256 = "sha256:0e3a4d9050f7ee9d6584fb284a0671f0e0eaf398597be29806943d7b6bffa987"
EXCLUSIONS_SHA256 = "sha256:e318e0af085f74dced1cb6c920608882219f5ad3154d60e60496dcd8f236c020"
B12_ROSTER_SHA256 = "sha256:1459d1fa171b9f124c016aabed559081c9d3e7ca34db6d31b7285e692b175e6d"
B12_FREEZE_FILE_SHA256 = "sha256:d61efffcca96947c23c43f956e20f49137ccd1956637be588a0886933d115c33"
B12_FREEZE_SHA256 = "sha256:5b2c59f93b3e9f9ef3474be6fdd148833ebb395289c56f79d0deb380c7ee2960"
B12_BASELINE_FILE_SHA256 = "sha256:57e5e739403ead63fd3c9463399d802f339a4a25ced4eed48cc61b4ed2355f50"
B12_BASELINE_REPORT_SHA256 = (
    "sha256:d218de259241735b348e6fe61b14af91eeddaa2afabb851c95259626ae827c8a"
)
B12_ORACLE_RUNNER_SHA256 = "sha256:772baa27e981f611681330bc463aef2ebe06b5f4a83ef2a0313ccf66b6dfef5d"
B12_FREEZE = PROJECT_ROOT / "artifacts/w5-xs/2026-08-24-delivery/freeze-v4/freeze.json"
DATASET_FILES = {
    "blueprint.json",
    "dataset-manifest.json",
    "dev.jsonl",
    "provenance.jsonl",
    "receipt.json",
    "split-manifest.json",
    "train.jsonl",
}
SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
EVALUATION_CACHE_ROOT = DEFAULT_OUTPUT_ROOT / "evaluation-cache"
_USER_ROOT = PROJECT_ROOT.parents[1]
EVALUATION_SANDBOX_POLICY = (
    "(version 1) (deny default) (deny network*) "
    "(allow process*) (allow file-read*) "
    f'(deny file-read* (subpath "{PROJECT_ROOT / ".env"}") '
    f'(subpath "{_USER_ROOT / ".aws"}") (subpath "{_USER_ROOT / ".ssh"}") '
    f'(subpath "{_USER_ROOT / "Library/Keychains"}")) '
    f'(allow file-write* (subpath "{EVALUATION_CACHE_ROOT.resolve(strict=False)}") '
    '(literal "/dev/null")) '
    "(allow sysctl-read) (allow mach-lookup) (allow iokit*) (allow ipc-posix-shm*)"
)
_BASE_CHECKPOINT_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}


class RuntimeContractError(ValueError):
    pass


def _fail(message: str) -> None:
    raise RuntimeContractError(message)


def _sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        _fail(f"not a regular file: {path}")
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _prefixed_sha256(path: Path) -> str:
    return "sha256:" + _sha256(path)


def _is_hash(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(
        value, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _atomic_write(path: Path, raw: bytes) -> None:
    if path.exists() or path.is_symlink():
        _fail(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def _json(path: Path) -> dict[str, Any]:
    if path.is_symlink():
        _fail(f"symlink forbidden: {path}")
    try:
        value = json.loads(
            path.read_text(), parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x))
        )
        if not isinstance(value, dict):
            _fail(f"json object required: {path}")
        return value
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _fail(f"invalid json {path}: {exc}")


def _jsonl_cases(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        _fail("requests JSONL must be a regular file")
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        except (ValueError, json.JSONDecodeError) as exc:
            _fail(f"invalid requests JSONL: {exc}")
        if not isinstance(row, dict):
            _fail("requests JSONL rows must be objects")
        rows.append(row)
    if not rows or len(rows) > 128:
        _fail("requests JSONL count out of bounds")
    return rows


def _under(path: Path, root: Path) -> Path:
    path, root = path.resolve(), root.resolve()
    try:
        path.relative_to(root)
    except ValueError:
        _fail(f"path outside allowed root: {path}")
    return path


def _no_symlinks(root: Path) -> None:
    if root.is_symlink():
        _fail(f"symlink forbidden: {root}")
    if root.exists():
        for p in root.rglob("*"):
            if p.is_symlink():
                _fail(f"symlink forbidden: {p}")


def _check_checkpoint(checkpoint: Path, pin_path: Path = CHECKPOINT_PIN) -> dict[str, Any]:
    pin = _json(pin_path)
    _no_symlinks(checkpoint)
    if not checkpoint.is_dir():
        _fail("base checkpoint directory is missing")
    report = _json(CHECKPOINT_REPORT)
    revision = pin.get("revision")
    tree_path = checkpoint / ".cache/huggingface/trees" / f"{revision}.json"
    tree = _json(tree_path)
    tree_files = tree.get("files")
    if (
        report.get("schema_version") != 1
        or report.get("status") != "verified"
        or report.get("checkpoint_path") != str(checkpoint)
        or report.get("repository") != pin.get("repository")
        or report.get("revision") != revision
        or report.get("model_type") != pin.get("model_type")
        or report.get("quantization") != pin.get("quantization")
        or report.get("config_sha256") != pin.get("config_sha256")
        or report.get("tree_metadata_sha256") != pin.get("tree_metadata_sha256")
        or report.get("weight_files") != pin.get("weight_files")
        or _sha256(tree_path) != pin.get("tree_metadata_sha256")
        or tree.get("format_version") != 1
        or not isinstance(tree_files, Mapping)
        or not tree_files
    ):
        _fail("base checkpoint report or exact-revision tree identity mismatch")
    local_files = {
        item.relative_to(checkpoint).as_posix(): item
        for item in checkpoint.rglob("*")
        if item.is_file() and not item.is_relative_to(checkpoint / ".cache")
    }
    if set(local_files) != set(tree_files):
        _fail("base checkpoint payload roster differs from the pinned tree")
    cache_paths = [pin_path, CHECKPOINT_REPORT, tree_path, *local_files.values()]
    cache_key = (
        str(checkpoint.resolve()),
        tuple(
            (
                str(path.resolve()),
                path.stat().st_dev,
                path.stat().st_ino,
                path.stat().st_size,
                path.stat().st_mtime_ns,
                path.stat().st_ctime_ns,
            )
            for path in cache_paths
        ),
    )
    cached = _BASE_CHECKPOINT_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)
    payload_hashes: dict[str, str] = {}
    for name, item in sorted(local_files.items()):
        row = tree_files[name]
        if (
            not isinstance(row, Mapping)
            or item.is_symlink()
            or item.stat().st_nlink != 1
            or item.stat().st_size != row.get("size")
        ):
            _fail(f"base checkpoint payload metadata mismatch: {name}")
        digest = _sha256(item)
        if row.get("lfs_sha256") is not None:
            if digest != row.get("lfs_sha256") or item.stat().st_size != row.get("lfs_size"):
                _fail(f"base checkpoint LFS identity mismatch: {name}")
        else:
            header = f"blob {item.stat().st_size}\0".encode("ascii")
            git_blob = hashlib.sha1(header + item.read_bytes()).hexdigest()  # noqa: S324
            if git_blob != row.get("blob_id"):
                _fail(f"base checkpoint Git blob identity mismatch: {name}")
        payload_hashes[name] = digest
    config = checkpoint / "config.json"
    if _sha256(config) != pin["config_sha256"]:
        _fail("checkpoint config hash mismatch")
    for item in pin["weight_files"]:
        p = checkpoint / item["path"]
        if (
            not p.is_file()
            or p.stat().st_size != item["bytes"]
            or payload_hashes.get(item["path"]) != item["sha256"]
        ):
            _fail(f"checkpoint weight mismatch: {item['path']}")
    result = {
        "revision": pin["revision"],
        "config_sha256": pin["config_sha256"],
        "weights": len(pin["weight_files"]),
        "payload_files": len(payload_hashes),
        "tree_metadata_sha256": pin["tree_metadata_sha256"],
        "verification_report_sha256": _prefixed_sha256(CHECKPOINT_REPORT),
    }
    _BASE_CHECKPOINT_CACHE.clear()
    _BASE_CHECKPOINT_CACHE[cache_key] = result
    return dict(result)


def _check_runtime(pin_path: Path = RUNTIME_PIN, lock_path: Path = RUNTIME_LOCK) -> dict[str, Any]:
    pin = _json(pin_path)
    if pin.get("status") != "qualified" or _sha256(lock_path) != pin["lock_sha256"]:
        _fail("runtime pin or lock mismatch")
    wrapper = PROJECT_ROOT / "qualification/train_full_state.py"
    if (
        pin.get("qualification_wrapper_sha256")
        and _sha256(wrapper) != pin["qualification_wrapper_sha256"]
    ):
        _fail("qualification wrapper hash mismatch")
    expected_prefix = (PROJECT_ROOT / "qualification/.venv").resolve()
    if Path(sys.prefix).resolve() != expected_prefix or sys.version.split()[0] != pin.get("python"):
        _fail("executing Python is not the pinned qualification virtualenv")
    expected_packages = pin.get("packages")
    if not isinstance(expected_packages, Mapping):
        _fail("runtime package pin is missing")
    try:
        live_packages = {name: version(name) for name in expected_packages}
    except PackageNotFoundError as exc:
        _fail(f"qualification runtime package is missing: {exc}")
    if live_packages != expected_packages:
        _fail("live qualification packages differ from the runtime pin")
    return {
        "python": pin.get("python"),
        "python_prefix": str(expected_prefix),
        "packages": live_packages,
        "lock_sha256": pin["lock_sha256"],
    }


def _check_receipt(path: Path) -> dict[str, Any]:
    d = _json(path)
    counts = d.get("counts", {})
    expected = {"train": {"F-1": 22, "F-2": 21, "F-3": 21}, "dev": {"F-1": 5, "F-2": 5, "F-3": 6}}
    if counts != expected:
        _fail(f"dataset family receipt mismatch: {counts}")
    hashes = d.get("hashes")
    if (
        d.get("schema_version") != 1
        or d.get("status") != "materialized_verified"
        or d.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or d.get("catalog_pin_sha256") != CATALOG_PIN_SHA256
        or d.get("exclusions_sha256") != EXCLUSIONS_SHA256
        or d.get("b12_roster_sha256") != B12_ROSTER_SHA256
        or not isinstance(hashes, Mapping)
        or set(hashes)
        != {
            "blueprint.json",
            "dataset-manifest.json",
            "dev.jsonl",
            "provenance.jsonl",
            "split-manifest.json",
            "train.jsonl",
        }
        or not all(_is_hash(value) for value in hashes.values())
    ):
        _fail("dataset receipt hashes missing")
    if not _is_hash(d.get("split_manifest")) or not _is_hash(d.get("dataset_manifest")):
        _fail("dataset manifest identity missing")
    receipt_body = {key: value for key, value in d.items() if key != "receipt_sha256"}
    if d.get("receipt_sha256") != _canonical_hash(receipt_body):
        _fail("dataset receipt self-hash mismatch")
    directory = path.parent
    _no_symlinks(directory)
    if not directory.is_dir() or {item.name for item in directory.iterdir()} != DATASET_FILES:
        _fail("dataset directory roster mismatch")
    if any(not item.is_file() or item.stat().st_nlink != 1 for item in directory.iterdir()):
        _fail("dataset directory contains an unsafe file")
    actual_hashes = {
        name: _prefixed_sha256(directory / name) for name in DATASET_FILES - {"receipt.json"}
    }
    if hashes != actual_hashes:
        _fail("dataset receipt does not bind the materialized files")
    semantic_errors = _semantic_dataset_errors(directory)
    if semantic_errors:
        _fail("dataset semantic verification failed: " + "; ".join(semantic_errors[:3]))
    train, dev = 64, 16
    return {
        "train": train,
        "dev": dev,
        "train_sha256": hashes["train.jsonl"],
        "receipt_sha256": _prefixed_sha256(path),
    }


def _semantic_dataset_errors(directory: Path) -> list[str]:
    try:
        from metis_model1.initial_local_qlora_dataset import verify
    except ModuleNotFoundError as exc:
        if exc.name != "jsonschema":
            raise
        verifier_python = PROJECT_ROOT / ".venv/bin/python"
        command = [
            str(SANDBOX_EXEC),
            "-p",
            "(version 1) (allow default) (deny network*) (deny file-write*)",
            str(verifier_python),
            str(PROJECT_ROOT / "src/metis_model1/initial_local_qlora_dataset.py"),
            "verify",
            "--destination",
            str(directory),
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=5 * 60,
                env={
                    "PATH": "/usr/bin:/bin",
                    "LANG": "C",
                    "LC_ALL": "C",
                    "PYTHONNOUSERSITE": "1",
                },
            )
            value = json.loads(completed.stdout)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
            return [f"isolated dataset verifier failed: {error}"]
        if completed.returncode not in (0, 1) or not isinstance(value, dict):
            return ["isolated dataset verifier returned an invalid result"]
        errors = value.get("errors")
        return errors if isinstance(errors, list) else ["isolated dataset verifier omitted errors"]
    return verify(directory)


def _dataset_fingerprint(path: Path) -> str:
    if path.is_symlink():
        _fail("dataset fingerprint path must not be a symlink")
    resolved = path.resolve(strict=True)
    is_directory = resolved.is_dir()
    if not is_directory and not resolved.is_file():
        _fail("dataset fingerprint path must be a regular file or directory")
    files = (
        sorted(item for item in resolved.rglob("*") if item.is_file())
        if is_directory
        else [resolved]
    )
    if not files or (is_directory and any(item.is_symlink() for item in resolved.rglob("*"))):
        _fail("dataset fingerprint roster is empty or unsafe")
    digest = hashlib.sha256()
    for item in files:
        relative = item.relative_to(resolved) if is_directory else Path(item.name)
        digest.update(str(relative).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item.stat().st_size).encode("ascii"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(_sha256(item)))
    return digest.hexdigest()


def _case_id(row: Mapping[str, Any]) -> str:
    case_id = row.get("case_id")
    example_id = row.get("example_id")
    if case_id is not None and example_id is not None and case_id != example_id:
        _fail("case_id and example_id disagree")
    value = case_id if case_id is not None else example_id
    if not isinstance(value, str) or not value:
        _fail("dev case ID must be a non-empty string")
    return value


def preflight(
    checkpoint: Path,
    receipt: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    config: Mapping[str, Any] = CONFIG,
) -> dict[str, Any]:
    if dict(config) != CONFIG:
        _fail("exact INITIAL_LOCAL_QLORA_V1 config required")
    output_root = _under(output_root, PROJECT_ROOT / "artifacts")
    _no_symlinks(output_root.parent)
    if output_root.exists():
        _fail(f"output must be absent: {output_root}")
    return {
        "contract": "INITIAL_LOCAL_QLORA_V1",
        "checkpoint": _check_checkpoint(checkpoint),
        "runtime": _check_runtime(),
        "dataset": _check_receipt(receipt),
        "config": CONFIG,
        "limits": LIMITS,
        "output_root": str(output_root),
    }


def _messages(row: Mapping[str, Any]) -> list[dict[str, str]]:
    messages = row.get("messages")
    if not isinstance(messages, list) or not messages:
        _fail("case messages required")
    out = []
    for m in messages:
        if (
            not isinstance(m, Mapping)
            or m.get("role") not in ("system", "user")
            or not isinstance(m.get("content"), str)
        ):
            _fail("only system/user messages are permitted")
        out.append({"role": m["role"], "content": m["content"]})
    return out


def _evaluation_environment() -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "LANG": "C",
        "LC_ALL": "C",
        "HOME": str(EVALUATION_CACHE_ROOT / "home"),
        "TMPDIR": str(EVALUATION_CACHE_ROOT / "tmp"),
        "XDG_CACHE_HOME": str(EVALUATION_CACHE_ROOT / "xdg"),
        "HF_HOME": str(EVALUATION_CACHE_ROOT / "huggingface"),
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
    }


def _terminate_process_group(process: subprocess.Popen[Any]) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, 15)
    with contextlib.suppress(subprocess.TimeoutExpired):
        process.wait(timeout=20)
    if process.poll() is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, 9)
        process.wait(timeout=20)


def _dev_prompt_messages(row: Mapping[str, Any]) -> list[dict[str, str]]:
    messages = row.get("messages")
    if (
        not isinstance(messages, list)
        or len(messages) < 2
        or not isinstance(messages[-1], Mapping)
        or messages[-1].get("role") != "assistant"
        or not isinstance(messages[-1].get("content"), str)
    ):
        _fail("dev case must end with one assistant target")
    return _messages({"messages": messages[:-1]})


def exact_normalized(candidate: str, target: str) -> bool:
    return " ".join(candidate.split()) == " ".join(target.split())


def _model_type(config: Any) -> str | None:
    value = (
        config.get("model_type")
        if isinstance(config, Mapping)
        else getattr(config, "model_type", None)
    )
    return value if isinstance(value, str) else None


def _bounded_worker(
    command: list[str], requests: list[dict[str, Any]], timeout: float
) -> list[dict[str, Any]]:
    if not 0 < timeout <= LIMITS["hours"] * 3600:
        _fail("evaluation timeout must stay within the four-hour cap")
    if len(requests) > 128 or any(len(json.dumps(x)) > 1_000_000 for x in requests):
        _fail("bounded worker request limit exceeded")
    for path in (
        EVALUATION_CACHE_ROOT,
        EVALUATION_CACHE_ROOT / "home",
        EVALUATION_CACHE_ROOT / "tmp",
    ):
        path.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_evaluation_environment(),
        start_new_session=True,
    )
    try:
        payload = "".join(json.dumps(x, separators=(",", ":")) + "\n" for x in requests)
        out, err = proc.communicate(payload, timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_process_group(proc)
        _fail("evaluation worker timeout")
    if len(err.encode("utf-8")) > 128 * 1024:
        _fail("evaluation worker stderr exceeds limit")
    if len(out.encode("utf-8")) > 128 * 1_000_000:
        _fail("evaluation worker stdout exceeds limit")
    if proc.returncode != 0:
        _fail(f"evaluation worker failed: {proc.returncode}: {err[-2000:]}")
    rows = []
    for line in out.splitlines():
        if line.strip():
            try:
                value = json.loads(
                    line, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x))
                )
            except (ValueError, json.JSONDecodeError) as exc:
                _fail(f"malformed worker JSON: {exc}")
            if not isinstance(value, dict):
                _fail("worker response must be object")
            rows.append(value)
    if len(rows) != len(requests):
        _fail("worker response count mismatch")
    for request, response in zip(requests, rows, strict=True):
        peak = response.get("peak_metal_gb")
        if (
            set(response) != {"request_id", "text", "peak_metal_gb"}
            or not isinstance(response.get("text"), str)
            or type(peak) not in (int, float)
            or not math.isfinite(peak)
            or not 0 <= peak <= LIMITS["metal_gb"]
        ):
            _fail("worker response schema mismatch")
        if response.get("request_id") != request.get("request_id"):
            _fail("worker response request id mismatch")
    return rows


def evaluate_dev(
    cases: list[Mapping[str, Any]],
    worker: list[str],
    report: Path,
    timeout: float = 4 * 3600,
    candidate_jsonl: Path | None = None,
    identity: Mapping[str, Any] | None = None,
    dataset_receipt: Path | None = None,
) -> dict[str, Any]:
    """Evaluate cases through one bounded worker; targets never cross IPC."""
    report = _under(report, PROJECT_ROOT / "artifacts")
    if report.exists() or report.is_symlink():
        _fail("evaluation report must be absent")
    if candidate_jsonl is None or identity is None or dataset_receipt is None:
        _fail("evaluation requires candidate output, dataset receipt, and model identity")
    dataset = _check_receipt(dataset_receipt)
    frozen_cases = _jsonl_cases(dataset_receipt.parent / "dev.jsonl")
    if cases != frozen_cases:
        _fail("evaluation cases differ from the receipt-bound frozen dev JSONL")
    candidate_jsonl = _under(candidate_jsonl, PROJECT_ROOT / "artifacts")
    if candidate_jsonl == report or candidate_jsonl.exists() or candidate_jsonl.is_symlink():
        _fail("candidate output must be absent and distinct from report")
    allowed_parents = {
        _fixed_dev_report(label).parent
        for label in (
            "base",
            "restored",
            "step25",
            "step50",
            "step100",
        )
    }
    if (
        report.name != "generation.json"
        or candidate_jsonl.name != "candidates.jsonl"
        or report.parent.resolve() != candidate_jsonl.parent.resolve()
        or report.parent.resolve() not in allowed_parents
    ):
        _fail("evaluation outputs must use one absent fixed dev phase directory")
    prepared = []
    case_ids: set[str] = set()
    for row in cases:
        raw = row.get("messages")
        if (
            not isinstance(raw, list)
            or len(raw) < 2
            or raw[-1].get("role") != "assistant"
            or not isinstance(raw[-1].get("content"), str)
        ):
            _fail("each dev case must end with exactly one assistant target")
        if any(m.get("role") not in ("system", "user") for m in raw[:-1]):
            _fail("assistant target must be final")
        if "target_source" in row and row["target_source"] != raw[-1]["content"]:
            _fail("target mismatch")
        case_id = _case_id(row)
        if case_id in case_ids:
            _fail("dev case IDs must be non-empty and distinct")
        case_ids.add(case_id)
        prepared.append(
            {
                **row,
                "case_id": case_id,
                "target_source": raw[-1]["content"],
                "messages": raw[:-1],
            }
        )
    requests = [
        {
            "request_id": str(row["case_id"]),
            "messages": _messages(row),
            "max_tokens": 512,
        }
        for row in prepared
    ]
    responses = _bounded_worker(worker, requests, timeout)
    if len(responses) != len(cases):
        _fail("evaluation response count mismatch")
    scored = []
    for row, response in zip(prepared, responses, strict=False):
        candidate = response.get("text", response.get("source"))
        if (
            not isinstance(candidate, str)
            or not candidate
            or len(candidate.encode("utf-8")) > 1_000_000
        ):
            _fail("worker source missing")
        target = row.get("target_source")
        if not isinstance(target, str):
            _fail("case target missing")
        scored.append(
            {
                "case_id": row["case_id"],
                "prompt_sha256": _canonical_hash(_messages(row)),
                "source_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
                "exact_normalized": exact_normalized(candidate, target),
            }
        )
    _no_symlinks(report.parent)
    _atomic_write(
        candidate_jsonl,
        "".join(
            json.dumps(
                {"case_id": x["case_id"], "source": r.get("text", r.get("source"))},
                allow_nan=False,
            )
            + "\n"
            for x, r in zip(scored, responses, strict=True)
        ).encode("utf-8"),
    )
    body = {
        "schema_version": 1,
        "status": "complete",
        "contract": "INITIAL_LOCAL_QLORA_V1",
        "identity": dict(identity),
        "dataset_receipt_sha256": dataset["receipt_sha256"],
        "dev_jsonl_sha256": _prefixed_sha256(dataset_receipt.parent / "dev.jsonl"),
        "cases": scored,
        "candidate_jsonl_sha256": _prefixed_sha256(candidate_jsonl),
        "peak_metal_gb": max(float(row["peak_metal_gb"]) for row in responses),
    }
    document = {**body, "report_sha256": _canonical_hash(body)}
    _atomic_write(
        report,
        (json.dumps(document, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"),
    )
    return {
        "cases": len(scored),
        "exact": sum(x["exact_normalized"] for x in scored),
        "peak_metal_gb": max(float(row["peak_metal_gb"]) for row in responses),
        "report": str(report),
        "report_sha256": document["report_sha256"],
    }


def evaluation_identity(model_path: Path, adapter_path: Path | None) -> dict[str, Any]:
    base = _check_checkpoint(model_path)
    identity: dict[str, Any] = {
        "base_revision": base["revision"],
        "base_config_sha256": base["config_sha256"],
        "base_tree_metadata_sha256": base["tree_metadata_sha256"],
        "base_verification_report_sha256": base["verification_report_sha256"],
        "base_payload_files": base["payload_files"],
        "adapter_enabled": adapter_path is not None,
    }
    if adapter_path is None:
        identity["adapter"] = None
    else:
        checkpoint = verify_checkpoint(adapter_path)
        identity["adapter"] = {
            "global_step": checkpoint["global_step"],
            "manifest_sha256": _prefixed_sha256(adapter_path / "manifest.json"),
            "adapter_sha256": _prefixed_sha256(adapter_path / "adapters.safetensors"),
        }
    return identity


def _candidate_rows(path: Path) -> list[dict[str, str]]:
    rows = _jsonl_cases(path)
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if set(row) != {"case_id", "source"}:
            _fail("candidate rows require exactly case_id and source")
        case_id, source = row["case_id"], row["source"]
        if (
            not isinstance(case_id, str)
            or not case_id
            or case_id in seen
            or not isinstance(source, str)
            or not source
            or len(source.encode("utf-8")) > 1_000_000
        ):
            _fail("candidate row identity or source is invalid")
        seen.add(case_id)
        result.append({"case_id": case_id, "source": source})
    return result


def score_dev_candidates(
    dataset_dir: Path,
    candidates_path: Path,
    generation_report: Path,
    report: Path,
    *,
    metis_root: Path,
    node_path: Path,
) -> dict[str, Any]:
    """Score one frozen dev16 candidate roster with the pinned catalog oracle."""
    from metis_model1.catalog_maintenance_probe import (
        _describe_source_in_snapshot,
        _extract_source,
    )
    from metis_model1.catalog_retrieval_refresh import _pinned_snapshot

    dataset_dir = _under(dataset_dir, PROJECT_ROOT / "artifacts")
    report = _under(report, PROJECT_ROOT / "artifacts")
    candidates_path = _under(candidates_path, PROJECT_ROOT / "artifacts")
    generation_report = _under(generation_report, PROJECT_ROOT / "artifacts")
    if report.exists() or report.is_symlink():
        _fail("semantic score report must be absent")
    allowed_reports = {
        _fixed_dev_report(label) for label in ("base", "restored", "step25", "step50", "step100")
    }
    if (
        report.resolve() not in allowed_reports
        or generation_report.resolve() != report.parent.resolve() / "generation.json"
        or candidates_path.resolve() != report.parent.resolve() / "candidates.jsonl"
    ):
        _fail("dev scoring must consume the exact fixed phase bundle")
    receipt = _check_receipt(dataset_dir / "receipt.json")
    generation = _json(generation_report)
    generation_body = {key: value for key, value in generation.items() if key != "report_sha256"}
    generation_cases = generation.get("cases")
    generation_identity = generation.get("identity")
    generation_peak = generation.get("peak_metal_gb")
    if (
        generation.get("schema_version") != 1
        or generation.get("status") != "complete"
        or generation.get("contract") != "INITIAL_LOCAL_QLORA_V1"
        or generation.get("report_sha256") != _canonical_hash(generation_body)
        or generation.get("candidate_jsonl_sha256") != _prefixed_sha256(candidates_path)
        or generation.get("dataset_receipt_sha256") != receipt["receipt_sha256"]
        or generation.get("dev_jsonl_sha256") != _prefixed_sha256(dataset_dir / "dev.jsonl")
        or not isinstance(generation_identity, Mapping)
        or generation_identity.get("base_revision") != _json(CHECKPOINT_PIN).get("revision")
        or type(generation_identity.get("adapter_enabled")) is not bool
        or not isinstance(generation_cases, list)
        or len(generation_cases) != 16
        or type(generation_peak) not in (int, float)
        or not math.isfinite(generation_peak)
        or not 0 <= generation_peak <= LIMITS["metal_gb"]
    ):
        _fail("dev generation report does not bind candidates and model identity")
    cases = _jsonl_cases(dataset_dir / "dev.jsonl")
    candidates = _candidate_rows(candidates_path)
    if len(cases) != 16 or len(candidates) != 16:
        _fail("semantic scoring requires exactly dev16")
    expected_ids = [_case_id(case) for case in cases]
    candidate_ids = [row["case_id"] for row in candidates]
    if candidate_ids != expected_ids or len(set(expected_ids)) != 16:
        _fail("candidate roster/order differs from frozen dev16")
    expected_generation_cases = [
        {
            "case_id": row["case_id"],
            "prompt_sha256": _canonical_hash(_dev_prompt_messages(case)),
            "source_sha256": hashlib.sha256(row["source"].encode()).hexdigest(),
        }
        for case, row in zip(cases, candidates, strict=True)
    ]
    observed_generation_cases = [
        {
            "case_id": row.get("case_id"),
            "prompt_sha256": row.get("prompt_sha256"),
            "source_sha256": row.get("source_sha256"),
        }
        for row in generation_cases
        if isinstance(row, Mapping)
    ]
    if observed_generation_cases != expected_generation_cases:
        _fail("dev generation report case roster does not bind candidate sources")
    families = {
        family: sum(case.get("task_family") == family for case in cases)
        for family in CATEGORY_COUNTS
    }
    if families != CATEGORY_COUNTS:
        _fail("dev family denominator differs from the frozen contract")
    observations: list[dict[str, Any]] = []
    with _pinned_snapshot(metis_root, node_path) as snapshot:
        for case, candidate_row in zip(cases, candidates, strict=True):
            messages = case.get("messages")
            if (
                not isinstance(messages, list)
                or not messages
                or not isinstance(messages[-1], Mapping)
                or messages[-1].get("role") != "assistant"
                or not isinstance(messages[-1].get("content"), str)
            ):
                _fail("dev target is malformed")
            target = messages[-1]["content"]
            try:
                target_skeleton, target_receipt = _describe_source_in_snapshot(snapshot, target)
            except Exception as exc:  # noqa: BLE001
                _fail(f"frozen dev target oracle failure: {type(exc).__name__}")
            source, extraction_error = _extract_source(candidate_row["source"])
            candidate_skeleton: Mapping[str, Any] | None = None
            candidate_receipt: Mapping[str, Any] | None = None
            oracle_error: str | None = None
            if source is not None:
                try:
                    candidate_skeleton, candidate_receipt = _describe_source_in_snapshot(
                        snapshot, source
                    )
                except Exception as exc:  # noqa: BLE001
                    oracle_error = f"{type(exc).__name__}:{exc}"
            family = str(case.get("task_family"))
            skeleton_match = candidate_skeleton == target_skeleton
            exact = source is not None and exact_normalized(source, target)
            minimal = exact if family in {"F-2", "F-3"} else True
            invented_values = bool(source and " values [" in source)
            critical = extraction_error is not None or oracle_error is not None
            semantic = bool(
                source is not None
                and not critical
                and skeleton_match
                and minimal
                and not invented_values
            )
            observations.append(
                {
                    "case_id": candidate_row["case_id"],
                    "family": family,
                    "source_sha256": _prefixed_text_sha256(candidate_row["source"]),
                    "extraction": "ok" if extraction_error is None else extraction_error,
                    "oracle": "ok" if oracle_error is None and source is not None else "rejected",
                    "oracle_failure_sha256": (
                        _prefixed_text_sha256(oracle_error) if oracle_error else None
                    ),
                    "candidate_receipt_sha256": (
                        candidate_receipt.get("receipt_sha256")
                        if isinstance(candidate_receipt, Mapping)
                        else None
                    ),
                    "target_receipt_sha256": target_receipt.get("receipt_sha256"),
                    "skeleton_match": skeleton_match,
                    "exact_normalized": exact,
                    "minimal": minimal,
                    "invented_values": int(invented_values),
                    "critical_failure": int(critical),
                    "semantic_correct": int(semantic),
                }
            )
    counts = {
        "in": 16,
        "out": len(observations),
        "distinct": len({row["case_id"] for row in observations}),
        "gaps": 16 - len(observations),
        "semantic_correct": sum(row["semantic_correct"] for row in observations),
        "critical_failures": sum(row["critical_failure"] for row in observations),
        "invented_values": sum(row["invented_values"] for row in observations),
        "family_semantic_correct": {
            family: sum(row["semantic_correct"] for row in observations if row["family"] == family)
            for family in CATEGORY_COUNTS
        },
    }
    body = {
        "schema_version": 1,
        "status": "verified" if counts["out"] == 16 and counts["distinct"] == 16 else "stopped",
        "wave": "INITIAL_LOCAL_QLORA_V1",
        "selection_surface": "frozen_dev16",
        "dataset_receipt_sha256": receipt["receipt_sha256"],
        "generation_report_sha256": _prefixed_sha256(generation_report),
        "generation_identity": generation["identity"],
        "candidates_sha256": _prefixed_sha256(candidates_path),
        "counts": counts,
        "observations": observations,
    }
    document = {**body, "report_sha256": _canonical_hash(body)}
    _atomic_write(
        report,
        (json.dumps(document, allow_nan=False, sort_keys=True) + "\n").encode("utf-8"),
    )
    return {"report": str(report), "report_sha256": document["report_sha256"], **counts}


def _prefixed_text_sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _verified_dev_score(path: Path) -> dict[str, Any]:
    value = _json(path)
    body = {key: item for key, item in value.items() if key != "report_sha256"}
    counts = value.get("counts")
    identity = value.get("generation_identity")
    observations = value.get("observations")
    if (
        value.get("schema_version") != 1
        or value.get("status") != "verified"
        or value.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or value.get("selection_surface") != "frozen_dev16"
        or value.get("report_sha256") != _canonical_hash(body)
        or not isinstance(counts, Mapping)
        or counts.get("in") != 16
        or counts.get("out") != 16
        or counts.get("distinct") != 16
        or counts.get("gaps") != 0
        or type(counts.get("semantic_correct")) is not int
        or not 0 <= counts["semantic_correct"] <= 16
        or counts.get("critical_failures") != 0
        or counts.get("invented_values") != 0
        or not isinstance(identity, Mapping)
        or identity.get("base_revision") != _json(CHECKPOINT_PIN).get("revision")
        or type(identity.get("adapter_enabled")) is not bool
        or not isinstance(observations, list)
        or len(observations) != 16
    ):
        _fail("dev semantic score report is not a verified dev16 result")
    ids = [item.get("case_id") for item in observations if isinstance(item, Mapping)]
    if (
        len(ids) != 16
        or len(set(ids)) != 16
        or sum(item.get("semantic_correct") == 1 for item in observations)
        != counts["semantic_correct"]
        or sum(item.get("critical_failure") == 1 for item in observations) != 0
        or sum(item.get("invented_values") == 1 for item in observations) != 0
        or any(
            item.get("oracle") != "ok"
            or not _is_hash(item.get("candidate_receipt_sha256"))
            or not _is_hash(item.get("target_receipt_sha256"))
            for item in observations
        )
    ):
        _fail("dev semantic score observation roster is incomplete or inconsistent")
    return value


def _fixed_dev_report(label: str) -> Path:
    allowed = {"base", "restored", "step25", "step50", "step100"}
    if label not in allowed:
        _fail("unknown fixed dev evidence label")
    directory = {
        "base": "base-dev",
        "restored": "base-dev-restored",
        "step25": "step25-dev",
        "step50": "step50-dev",
        "step100": "step100-dev",
    }[label]
    return (DEFAULT_OUTPUT_ROOT / directory / "semantic.json").resolve()


def _run_relative(path: Path) -> str:
    resolved = path.resolve(strict=True)
    try:
        return resolved.relative_to(DEFAULT_OUTPUT_ROOT.resolve()).as_posix()
    except ValueError:
        _fail("dev evidence path is outside the fixed run root")


def _artifact_ref(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
        _fail(f"dev evidence is missing, linked, or not regular: {path}")
    return {
        "path": _run_relative(path),
        "bytes": path.stat().st_size,
        "sha256": _prefixed_sha256(path),
    }


def _verified_dev_bundle(
    label: str,
    *,
    dataset_receipt: Path,
    adapter: Path | None,
) -> dict[str, Any]:
    """Reopen and cross-check one exact generation/candidates/semantic bundle."""
    semantic_path = _fixed_dev_report(label)
    generation_path = semantic_path.parent / "generation.json"
    candidates_path = semantic_path.parent / "candidates.jsonl"
    if semantic_path.parent.is_symlink() or not semantic_path.parent.is_dir():
        _fail(f"{label} dev evidence directory is missing or linked")
    if {item.name for item in semantic_path.parent.iterdir()} != {
        "candidates.jsonl",
        "generation.json",
        "semantic.json",
    }:
        _fail(f"{label} dev evidence roster is not exact")
    dataset = _check_receipt(dataset_receipt)
    base_checkpoint = _check_checkpoint(BASE_CHECKPOINT)
    semantic = _verified_dev_score(semantic_path)
    generation = _json(generation_path)
    generation_body = {key: item for key, item in generation.items() if key != "report_sha256"}
    candidates = _candidate_rows(candidates_path)
    dev = _jsonl_cases(dataset_receipt.parent / "dev.jsonl")
    expected_ids = [_case_id(row) for row in dev]
    candidate_ids = [row["case_id"] for row in candidates]
    candidate_sources = {row["case_id"]: row["source"] for row in candidates}
    generation_cases = generation.get("cases")
    observations = semantic.get("observations")
    if (
        generation.get("schema_version") != 1
        or generation.get("status") != "complete"
        or generation.get("contract") != "INITIAL_LOCAL_QLORA_V1"
        or generation.get("report_sha256") != _canonical_hash(generation_body)
        or generation.get("candidate_jsonl_sha256") != _prefixed_sha256(candidates_path)
        or generation.get("dataset_receipt_sha256") != dataset["receipt_sha256"]
        or generation.get("dev_jsonl_sha256")
        != _prefixed_sha256(dataset_receipt.parent / "dev.jsonl")
        or semantic.get("generation_report_sha256") != _prefixed_sha256(generation_path)
        or semantic.get("candidates_sha256") != _prefixed_sha256(candidates_path)
        or semantic.get("dataset_receipt_sha256") != dataset["receipt_sha256"]
        or candidate_ids != expected_ids
        or len(expected_ids) != 16
        or len(set(expected_ids)) != 16
        or not isinstance(generation_cases, list)
        or len(generation_cases) != 16
        or not isinstance(observations, list)
        or len(observations) != 16
    ):
        _fail(f"{label} dev evidence does not bind its raw inputs")
    dev_by_id = {_case_id(row): row for row in dev}
    expected_generation = [
        {
            "case_id": case_id,
            "prompt_sha256": _canonical_hash(_dev_prompt_messages(dev_by_id[case_id])),
            "source_sha256": hashlib.sha256(candidate_sources[case_id].encode()).hexdigest(),
        }
        for case_id in expected_ids
    ]
    observed_generation = [
        {
            "case_id": row.get("case_id"),
            "prompt_sha256": row.get("prompt_sha256"),
            "source_sha256": row.get("source_sha256"),
        }
        for row in generation_cases
        if isinstance(row, Mapping)
    ]
    expected_observations = [
        {
            "case_id": case_id,
            "source_sha256": _prefixed_text_sha256(candidate_sources[case_id]),
        }
        for case_id in expected_ids
    ]
    observed_observations = [
        {"case_id": row.get("case_id"), "source_sha256": row.get("source_sha256")}
        for row in observations
        if isinstance(row, Mapping)
    ]
    if observed_generation != expected_generation or observed_observations != expected_observations:
        _fail(f"{label} dev case/source evidence drift")
    identity = semantic["generation_identity"]
    expected_base_identity = {
        "base_revision": base_checkpoint["revision"],
        "base_config_sha256": base_checkpoint["config_sha256"],
        "base_tree_metadata_sha256": base_checkpoint["tree_metadata_sha256"],
        "base_verification_report_sha256": base_checkpoint["verification_report_sha256"],
        "base_payload_files": base_checkpoint["payload_files"],
    }
    if generation.get("identity") != identity or any(
        identity.get(key) != item for key, item in expected_base_identity.items()
    ):
        _fail(f"{label} generation/semantic identity mismatch")
    if adapter is None:
        if identity.get("adapter_enabled") is not False or identity.get("adapter") is not None:
            _fail(f"{label} dev evidence is not adapter-off")
    else:
        checkpoint = verify_checkpoint(
            adapter, expected_dataset=dataset_receipt.parent / "train.jsonl"
        )
        expected_adapter = {
            "global_step": checkpoint["global_step"],
            "manifest_sha256": _prefixed_sha256(adapter / "manifest.json"),
            "adapter_sha256": _prefixed_sha256(adapter / "adapters.safetensors"),
        }
        if (
            identity.get("adapter_enabled") is not True
            or identity.get("adapter") != expected_adapter
        ):
            _fail(f"{label} dev evidence does not bind its exact adapter")
    files = {
        "candidates": _artifact_ref(candidates_path),
        "generation": _artifact_ref(generation_path),
        "semantic": _artifact_ref(semantic_path),
    }
    body = {
        "label": label,
        "score": semantic["counts"]["semantic_correct"],
        "identity": identity,
        "files": files,
    }
    return {**body, "bundle_sha256": _canonical_hash(body)}


def verify_continuation_gate(
    target: int,
    *,
    dataset_receipt: Path,
    checkpoint_root: Path | None = None,
) -> dict[str, Any]:
    """Authorize an optimizer phase only from the fixed, replayed dev evidence."""
    if target not in {25, 50, 100}:
        _fail("continuation target must be 25, 50, or 100")
    root = checkpoint_root or (DEFAULT_OUTPUT_ROOT / "checkpoints")
    base = _verified_dev_bundle("base", dataset_receipt=dataset_receipt, adapter=None)
    prior_steps = {25: [], 50: [25], 100: [25, 50]}[target]
    gates = [
        _verified_dev_bundle(
            f"step{step}",
            dataset_receipt=dataset_receipt,
            adapter=root / f"step-{step:08d}",
        )
        for step in prior_steps
    ]
    scores = [item["score"] for item in gates]
    if target >= 50 and scores[0] < base["score"] + 1:
        _fail("step50 requires at least one semantic dev gain at step25")
    if target == 100 and scores[1] < scores[0] + 1:
        _fail("step100 requires another semantic dev gain at step50")
    body = {
        "target_step": target,
        "dataset_receipt_sha256": _check_receipt(dataset_receipt)["receipt_sha256"],
        "base": base,
        "prior_gates": gates,
    }
    return {**body, "authority_sha256": _canonical_hash(body)}


def _training_evidence(adapter: Path, dataset_receipt: Path) -> dict[str, Any]:
    from metis_model1 import initial_local_qlora_train as trainer

    checkpoint = verify_checkpoint(adapter, expected_dataset=dataset_receipt.parent / "train.jsonl")
    freeze = trainer.verify_freeze(require_remote=True)
    expected_steps = {
        25: [25],
        50: [25, 50],
        100: [25, 50, 100],
    }[checkpoint["global_step"]]
    phases = []
    for step in expected_steps:
        phase = trainer._verified_phase_receipt(step, freeze)
        marker_path = trainer.RUN_ROOT / f"phase-step{step}-started.json"
        receipt_path = trainer.RUN_ROOT / f"phase-step{step}-receipt.json"
        phases.append(
            {
                "step": step,
                "marker_sha256": _prefixed_sha256(marker_path),
                "marker_self_sha256": _json(marker_path)["marker_sha256"],
                "phase_receipt_sha256": _prefixed_sha256(receipt_path),
                "phase_receipt_self_sha256": phase["receipt_sha256"],
                "telemetry_summary_sha256": phase["telemetry_summary_sha256"],
                "continuation_authority_sha256": phase["continuation_authority_sha256"],
                "retained_checkpoints": [
                    {
                        "global_step": item["global_step"],
                        "manifest_sha256": item["manifest_sha256"],
                        "checkpoint_sha256": item["checkpoint_sha256"],
                    }
                    for item in phase["retained_checkpoints"]
                ],
            }
        )
    return {
        "freeze_file_sha256": _prefixed_sha256(trainer.FREEZE_PATH),
        "freeze_self_sha256": freeze["freeze_sha256"],
        "preimage_commit": freeze["preimage_commit"],
        "published_execution_head": trainer._published_git_identity()["head"],
        "checkpoint": {
            "global_step": checkpoint["global_step"],
            "model_revision": checkpoint["model_revision"],
            "manifest_sha256": _prefixed_sha256(adapter / "manifest.json"),
            "adapter_sha256": _prefixed_sha256(adapter / "adapters.safetensors"),
            "adapter_config_sha256": _prefixed_sha256(adapter / "adapter_config.json"),
        },
        "phases": phases,
    }


def seal_training_receipt(
    *,
    adapter: Path,
    dataset_receipt: Path,
    output: Path = DEFAULT_TRAINING_RECEIPT,
) -> dict[str, Any]:
    output = _under(output, PROJECT_ROOT / "artifacts")
    if output != DEFAULT_TRAINING_RECEIPT.resolve() or output.exists() or output.is_symlink():
        _fail("training receipt must use the absent fixed path")
    dataset = _check_receipt(dataset_receipt)
    evidence = _training_evidence(adapter, dataset_receipt)
    body = {
        "schema_version": 1,
        "status": "verified",
        "wave": "INITIAL_LOCAL_QLORA_V1",
        "mode": "single_config_no_retry_qlora",
        "dataset_receipt_sha256": dataset["receipt_sha256"],
        "evidence": evidence,
    }
    value = {**body, "training_sha256": _canonical_hash(body)}
    _atomic_write(
        output,
        (json.dumps(value, allow_nan=False, sort_keys=True) + "\n").encode("utf-8"),
    )
    return value


def verify_training_receipt(
    path: Path,
    *,
    adapter: Path,
    dataset_receipt: Path,
) -> dict[str, Any]:
    value = _json(path)
    body = {key: item for key, item in value.items() if key != "training_sha256"}
    dataset = _check_receipt(dataset_receipt)
    evidence = _training_evidence(adapter, dataset_receipt)
    if (
        value.get("training_sha256") != _canonical_hash(body)
        or value.get("schema_version") != 1
        or value.get("status") != "verified"
        or value.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or value.get("mode") != "single_config_no_retry_qlora"
        or value.get("dataset_receipt_sha256") != dataset["receipt_sha256"]
        or value.get("evidence") != evidence
    ):
        _fail("training receipt does not replay the freeze/phase/checkpoint chain")
    return value


def seal_selection(
    *,
    adapter: Path,
    dataset_receipt: Path,
    base_report: Path,
    gate_reports: list[Path],
    training_receipt: Path = DEFAULT_TRAINING_RECEIPT,
    output: Path = DEFAULT_SELECTION_RECEIPT,
) -> dict[str, Any]:
    """Seal the dev-only checkpoint decision before terminal B12 is observed."""
    output = _under(output, PROJECT_ROOT / "artifacts")
    if output != DEFAULT_SELECTION_RECEIPT.resolve() or output.exists() or output.is_symlink():
        _fail("selection receipt must use the absent fixed path")
    if training_receipt.resolve() != DEFAULT_TRAINING_RECEIPT.resolve():
        _fail("selection must use the fixed training receipt")
    dataset = _check_receipt(dataset_receipt)
    checkpoint = verify_checkpoint(adapter, expected_dataset=dataset_receipt.parent / "train.jsonl")
    training = verify_training_receipt(
        training_receipt, adapter=adapter, dataset_receipt=dataset_receipt
    )
    expected_steps = {
        25: [25],
        50: [25, 50],
        100: [25, 50, 100],
    }[checkpoint["global_step"]]
    if base_report.resolve() != _fixed_dev_report("base") or len(gate_reports) != len(
        expected_steps
    ):
        _fail("dev gate report roster does not match selected checkpoint")
    if [path.resolve() for path in gate_reports] != [
        _fixed_dev_report(f"step{step}") for step in expected_steps
    ]:
        _fail("dev gate reports must use the fixed phase paths")
    base_bundle = _verified_dev_bundle("base", dataset_receipt=dataset_receipt, adapter=None)
    gate_bundles = [
        _verified_dev_bundle(
            f"step{step}",
            dataset_receipt=dataset_receipt,
            adapter=DEFAULT_OUTPUT_ROOT / "checkpoints" / f"step-{step:08d}",
        )
        for step in expected_steps
    ]
    if gate_bundles[-1]["identity"]["adapter"] != {
        "global_step": checkpoint["global_step"],
        "manifest_sha256": _prefixed_sha256(adapter / "manifest.json"),
        "adapter_sha256": _prefixed_sha256(adapter / "adapters.safetensors"),
    }:
        _fail("selected dev report does not bind the selected adapter")
    base_score = base_bundle["score"]
    scores = [report["score"] for report in gate_bundles]
    if len(scores) >= 2 and scores[0] < base_score + 1:
        _fail("step50 was reached without the required step25 dev gain")
    if len(scores) == 3 and scores[1] < scores[0] + 1:
        _fail("step100 was reached without the required additional dev gain")
    if len(scores) == 1 and scores[0] >= base_score + 1:
        _fail("selection stopped at step25 despite the required continuation")
    if len(scores) == 2 and scores[1] >= scores[0] + 1:
        _fail("selection stopped at step50 despite the required continuation")
    evidence = {"base": base_bundle, "gates": gate_bundles}
    body = {
        "schema_version": 1,
        "status": "selected",
        "wave": "INITIAL_LOCAL_QLORA_V1",
        "selection_surface": "frozen_dev16_only",
        "b12_observed": False,
        "selected_step": checkpoint["global_step"],
        "checkpoint_manifest_sha256": _prefixed_sha256(adapter / "manifest.json"),
        "adapter_sha256": _prefixed_sha256(adapter / "adapters.safetensors"),
        "adapter_config_sha256": _prefixed_sha256(adapter / "adapter_config.json"),
        "model_revision": checkpoint["model_revision"],
        "dataset_receipt_sha256": dataset["receipt_sha256"],
        "training_receipt_sha256": _prefixed_sha256(training_receipt),
        "training_self_sha256": training["training_sha256"],
        "base_evidence": base_bundle,
        "base_semantic_correct": base_score,
        "selected_semantic_correct": scores[-1],
        "gate_evidence": gate_bundles,
        "evidence_roster_sha256": _canonical_hash(evidence),
    }
    receipt = {**body, "selection_sha256": _canonical_hash(body)}
    _atomic_write(
        output,
        (json.dumps(receipt, allow_nan=False, sort_keys=True) + "\n").encode("utf-8"),
    )
    return receipt


def verify_selection_receipt(
    path: Path,
    *,
    adapter: Path,
    dataset_receipt: Path,
) -> dict[str, Any]:
    value = _json(path)
    body = {key: item for key, item in value.items() if key != "selection_sha256"}
    checkpoint = verify_checkpoint(adapter, expected_dataset=dataset_receipt.parent / "train.jsonl")
    dataset = _check_receipt(dataset_receipt)
    training = verify_training_receipt(
        DEFAULT_TRAINING_RECEIPT,
        adapter=adapter,
        dataset_receipt=dataset_receipt,
    )
    if (
        value.get("selection_sha256") != _canonical_hash(body)
        or value.get("schema_version") != 1
        or value.get("status") != "selected"
        or value.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or value.get("selection_surface") != "frozen_dev16_only"
        or value.get("b12_observed") is not False
        or value.get("selected_step") != checkpoint["global_step"]
        or value.get("checkpoint_manifest_sha256") != _prefixed_sha256(adapter / "manifest.json")
        or value.get("adapter_sha256") != _prefixed_sha256(adapter / "adapters.safetensors")
        or value.get("adapter_config_sha256") != _prefixed_sha256(adapter / "adapter_config.json")
        or value.get("model_revision") != checkpoint["model_revision"]
        or value.get("dataset_receipt_sha256") != dataset["receipt_sha256"]
        or value.get("training_receipt_sha256") != _prefixed_sha256(DEFAULT_TRAINING_RECEIPT)
        or value.get("training_self_sha256") != training["training_sha256"]
        or type(value.get("base_semantic_correct")) is not int
        or type(value.get("selected_semantic_correct")) is not int
        or not isinstance(value.get("gate_evidence"), list)
        or not value["gate_evidence"]
    ):
        _fail("selection receipt does not bind the frozen dev-only checkpoint decision")
    expected_steps = {25: [25], 50: [25, 50], 100: [25, 50, 100]}[checkpoint["global_step"]]
    base = _verified_dev_bundle("base", dataset_receipt=dataset_receipt, adapter=None)
    gates = [
        _verified_dev_bundle(
            f"step{step}",
            dataset_receipt=dataset_receipt,
            adapter=DEFAULT_OUTPUT_ROOT / "checkpoints" / f"step-{step:08d}",
        )
        for step in expected_steps
    ]
    evidence = {"base": base, "gates": gates}
    scores = [item["score"] for item in gates]
    if (
        value.get("base_evidence") != base
        or value.get("gate_evidence") != gates
        or value.get("evidence_roster_sha256") != _canonical_hash(evidence)
        or value.get("base_semantic_correct") != base["score"]
        or value.get("selected_semantic_correct") != scores[-1]
        or (len(scores) >= 2 and scores[0] < base["score"] + 1)
        or (len(scores) == 3 and scores[1] < scores[0] + 1)
        or (len(scores) == 1 and scores[0] >= base["score"] + 1)
        or (len(scores) == 2 and scores[1] >= scores[0] + 1)
    ):
        _fail("selection receipt gate roster is incomplete or inconsistent")
    return value


def seal_adapter_off_restore(
    *,
    adapter: Path,
    dataset_receipt: Path,
    selection_receipt: Path,
    output: Path = DEFAULT_RESTORE_RECEIPT,
) -> dict[str, Any]:
    output = _under(output, PROJECT_ROOT / "artifacts")
    if output != DEFAULT_RESTORE_RECEIPT.resolve() or output.exists() or output.is_symlink():
        _fail("adapter-off restore receipt must use the absent fixed path")
    dataset = _check_receipt(dataset_receipt)
    selection = verify_selection_receipt(
        selection_receipt, adapter=adapter, dataset_receipt=dataset_receipt
    )
    initial = _verified_dev_bundle("base", dataset_receipt=dataset_receipt, adapter=None)
    restored = _verified_dev_bundle("restored", dataset_receipt=dataset_receipt, adapter=None)
    if initial["files"]["candidates"] != {
        **restored["files"]["candidates"],
        "path": initial["files"]["candidates"]["path"],
    }:
        _fail("adapter-off restored candidates differ from the initial base candidates")
    body = {
        "schema_version": 1,
        "status": "verified",
        "wave": "INITIAL_LOCAL_QLORA_V1",
        "mode": "adapter_off_exact_restore",
        "dataset_receipt_sha256": dataset["receipt_sha256"],
        "selection_receipt_sha256": _prefixed_sha256(selection_receipt),
        "selection_self_sha256": selection["selection_sha256"],
        "selected_step": selection["selected_step"],
        "adapter_sha256": selection["adapter_sha256"],
        "initial_base_evidence": initial,
        "restored_base_evidence": restored,
        "exact_candidate_restore": True,
    }
    document = {**body, "restore_sha256": _canonical_hash(body)}
    _atomic_write(
        output,
        (json.dumps(document, allow_nan=False, sort_keys=True) + "\n").encode("utf-8"),
    )
    return document


def verify_adapter_off_restore_receipt(
    path: Path,
    *,
    adapter: Path,
    dataset_receipt: Path,
    selection_receipt: Path,
) -> dict[str, Any]:
    value = _json(path)
    body = {key: item for key, item in value.items() if key != "restore_sha256"}
    dataset = _check_receipt(dataset_receipt)
    selection = verify_selection_receipt(
        selection_receipt, adapter=adapter, dataset_receipt=dataset_receipt
    )
    initial = _verified_dev_bundle("base", dataset_receipt=dataset_receipt, adapter=None)
    restored = _verified_dev_bundle("restored", dataset_receipt=dataset_receipt, adapter=None)
    candidate_match = initial["files"]["candidates"].copy()
    candidate_match["path"] = restored["files"]["candidates"]["path"]
    if (
        value.get("restore_sha256") != _canonical_hash(body)
        or value.get("schema_version") != 1
        or value.get("status") != "verified"
        or value.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or value.get("mode") != "adapter_off_exact_restore"
        or value.get("dataset_receipt_sha256") != dataset["receipt_sha256"]
        or value.get("selection_receipt_sha256") != _prefixed_sha256(selection_receipt)
        or value.get("selection_self_sha256") != selection["selection_sha256"]
        or value.get("selected_step") != selection["selected_step"]
        or value.get("adapter_sha256") != selection["adapter_sha256"]
        or value.get("initial_base_evidence") != initial
        or value.get("restored_base_evidence") != restored
        or value.get("exact_candidate_restore") is not True
        or restored["files"]["candidates"] != candidate_match
    ):
        _fail("adapter-off restore receipt is invalid or not exact")
    return value


def worker(model_path: Path, adapter_path: Path | None = None) -> int:
    """One-shot MLX-VLM JSONL worker; model loading happens exactly once."""
    _check_runtime()
    from mlx_vlm import generate, load
    from mlx_vlm.prompt_utils import apply_chat_template

    _check_checkpoint(model_path)
    if adapter_path is not None:
        verify_checkpoint(adapter_path)
    with contextlib.redirect_stdout(sys.stderr):
        model, processor = load(
            str(model_path),
            adapter_path=str(adapter_path) if adapter_path else None,
            lazy=False,
            strict=True,
            trust_remote_code=False,
            processor_config={"trust_remote_code": False},
        )
    if _model_type(model.config) != "qwen3_5":
        _fail("worker loaded an unexpected model type")
    seen: set[str] = set()
    for line in sys.stdin:
        if len(line.encode("utf-8")) > 1_000_000:
            _fail("worker request exceeds byte limit")
        request = json.loads(line, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        messages = request.get("messages")
        if (
            set(request) != {"request_id", "messages", "max_tokens"}
            or not isinstance(request.get("request_id"), str)
            or not request["request_id"]
            or request["request_id"] in seen
            or not isinstance(messages, list)
            or not messages
            or len(messages) > 64
            or request["max_tokens"] != 512
        ):
            _fail("worker request schema/limits")
        if any(
            not isinstance(message, Mapping)
            or set(message) != {"role", "content"}
            or message.get("role") not in {"system", "user"}
            or not isinstance(message.get("content"), str)
            or not message["content"]
            for message in messages
        ):
            _fail("worker accepts non-empty system/user messages only")
        if len(seen) >= 128:
            _fail("worker request count exceeds limit")
        seen.add(request["request_id"])
        prompt = apply_chat_template(
            processor,
            model.config,
            messages,
            add_generation_prompt=True,
            num_images=0,
            num_audios=0,
            enable_thinking=False,
        )
        with contextlib.redirect_stdout(sys.stderr):
            result = generate(
                model,
                processor,
                prompt,
                max_tokens=512,
                temperature=0.0,
                seed=17,
                enable_thinking=False,
                verbose=False,
            )
        source = result.text
        if not source or not all(
            math.isfinite(float(x))
            for x in (result.prompt_tps, result.generation_tps, result.peak_memory)
        ):
            _fail("worker non-finite/empty generation")
        print(
            json.dumps(
                {
                    "request_id": request.get("request_id"),
                    "text": source,
                    "peak_metal_gb": float(result.peak_memory),
                },
                allow_nan=False,
            ),
            flush=True,
        )
    import mlx.core as mx

    mx.clear_cache()
    return 0


def verify_checkpoint(
    step: Path,
    expected_config: Mapping[str, Any] = CONFIG,
    expected_dataset: Path | None = None,
    *,
    allowed_steps: tuple[int, ...] = (25, 50, 100),
) -> dict[str, Any]:
    _no_symlinks(step)
    manifest = _json(step / "manifest.json")
    if manifest.get("schema_version") != 1 or manifest.get("status") != "complete":
        _fail("checkpoint manifest status/schema")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != {
        "adapter_config.json",
        "adapters.safetensors",
        "state.json",
        "state.safetensors",
    }:
        _fail("checkpoint file records missing")
    if manifest.get("global_step") not in allowed_steps:
        _fail("checkpoint boundary is not authorized")
    for name, record in files.items():
        p = step / name
        if (
            not p.is_file()
            or p.stat().st_size != record.get("bytes")
            or _sha256(p) != record.get("sha256")
        ):
            _fail(f"checkpoint file mismatch: {name}")
    state = _json(step / "state.json")
    if (
        state.get("schema_version") != 1
        or state.get("status") != "complete"
        or state.get("global_step") != manifest.get("global_step")
    ):
        _fail("checkpoint state/manifest identity mismatch")
    telemetry = state.get("last_metrics", {})
    peak_metal = telemetry.get("peak_metal_gb") if isinstance(telemetry, dict) else None
    if (
        not isinstance(telemetry, dict)
        or type(peak_metal) not in (int, float)
        or not math.isfinite(peak_metal)
        or not 0 <= peak_metal <= LIMITS["metal_gb"]
    ):
        _fail("peak metal telemetry missing or over limit")
    for value in telemetry.values():
        if isinstance(value, int | float) and not math.isfinite(value):
            _fail("non-finite telemetry")
    training = state.get("training_config", {})
    expected = {
        "batch_size": expected_config["batch_size"],
        "gradient_accumulation_steps": expected_config["gradient_accumulation"],
        "learning_rate": expected_config["learning_rate"],
        "lora_alpha": expected_config["alpha"],
        "lora_dropout": expected_config["dropout"],
        "lora_rank": expected_config["rank"],
        "max_seq_length": expected_config["max_seq_length"],
        "seed": expected_config["seed"],
        "train_on_completions": expected_config["completion_only"],
    }
    if any(training.get(k) != v for k, v in expected.items()):
        _fail("training config mismatch")
    ident = state.get("model", {}).get("revision") or state.get("model", {}).get(
        "checkpoint_revision"
    )
    if not ident:
        _fail("model identity missing")
    pin = _json(CHECKPOINT_PIN)
    if ident != pin.get("revision") or state.get("model", {}).get("model_type") != pin.get(
        "model_type"
    ):
        _fail("checkpoint model identity mismatch")
    dataset = state.get("dataset", {})
    if dataset.get("split") != "train" or not isinstance(
        dataset.get("fingerprint", {}).get("sha256"), str
    ):
        _fail("dataset fingerprint missing")
    if expected_dataset is not None:
        expected_path = expected_dataset.resolve(strict=True)
        if Path(str(dataset["fingerprint"].get("path", ""))).resolve(
            strict=True
        ) != expected_path or dataset["fingerprint"]["sha256"] != _dataset_fingerprint(
            expected_path
        ):
            _fail("dataset fingerprint mismatch")
    runtime = state.get("runtime", {})
    if runtime.get("uv_lock_sha256") != _json(RUNTIME_PIN).get("lock_sha256"):
        _fail("runtime lock identity mismatch")
    checkpoint_identity = {
        "manifest_sha256": _prefixed_sha256(step / "manifest.json"),
        "files": files,
    }
    return {
        "step": str(step),
        "global_step": manifest.get("global_step"),
        "model_revision": ident,
        "files": len(files),
        "manifest_sha256": checkpoint_identity["manifest_sha256"],
        "file_records": files,
        "checkpoint_sha256": _canonical_hash(checkpoint_identity),
    }


def _record(path: Path) -> dict[str, Any]:
    return {"bytes": path.stat().st_size, "sha256": _prefixed_sha256(path)}


def verify_evaluation_receipt(
    path: Path,
    *,
    verdict: str,
    adapter: Path,
    dataset_receipt: Path,
    selection_receipt: Path,
    restore_receipt: Path,
) -> dict[str, Any]:
    from metis_model1.initial_local_qlora_b12 import verify_terminal_evidence

    dataset = _check_receipt(dataset_receipt)
    try:
        value = verify_terminal_evidence(
            path,
            adapter=adapter,
            selection_receipt=selection_receipt,
            dataset_receipt=dataset_receipt,
            restore_receipt=restore_receipt,
        )
    except ValueError as error:
        _fail(f"terminal B12 evidence failed replay: {error}")
    body = {key: item for key, item in value.items() if key != "receipt_sha256"}
    counts = value.get("counts")
    baseline = value.get("baseline")
    adapter_record = value.get("adapter")
    runtime = value.get("runtime")
    identity = value.get("identity")
    observations = value.get("observations")
    peak = runtime.get("peak_metal_gb") if isinstance(runtime, Mapping) else None
    selection = verify_selection_receipt(
        selection_receipt,
        adapter=adapter,
        dataset_receipt=dataset_receipt,
    )
    restore = verify_adapter_off_restore_receipt(
        restore_receipt,
        adapter=adapter,
        dataset_receipt=dataset_receipt,
        selection_receipt=selection_receipt,
    )
    if _prefixed_sha256(B12_FREEZE) != B12_FREEZE_FILE_SHA256:
        _fail("frozen B12 contract file identity drift")
    freeze = _json(B12_FREEZE)
    frozen_tasks = freeze.get("tasks")
    frozen_ids = (
        [item.get("task_id") for item in frozen_tasks if isinstance(item, Mapping)]
        if isinstance(frozen_tasks, list)
        else []
    )
    observation_ids = (
        [item.get("task_id") for item in observations if isinstance(item, Mapping)]
        if isinstance(observations, list)
        else []
    )
    if (
        value.get("receipt_sha256") != _canonical_hash(body)
        or value.get("schema_version") != 1
        or value.get("status") != "verified"
        or value.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or value.get("mode") != "adapter_on_b12_terminal_replay"
        or value.get("training_authorized") is not False
        or value.get("selection_feedback") is not False
        or value.get("verdict") != verdict
        or verdict not in VERDICTS
        or value.get("dataset_receipt_sha256") != dataset["receipt_sha256"]
        or value.get("selection_receipt_sha256") != _prefixed_sha256(selection_receipt)
        or value.get("adapter_off_restore_receipt_sha256") != _prefixed_sha256(restore_receipt)
        or value.get("adapter_off_restore_self_sha256") != restore["restore_sha256"]
        or not isinstance(counts, Mapping)
        or counts.get("in") != 12
        or counts.get("out") != 12
        or counts.get("distinct") != 12
        or counts.get("gaps") != 0
        or type(counts.get("semantic_correct")) is not int
        or counts["semantic_correct"] < 11
        or not isinstance(baseline, Mapping)
        or baseline.get("id") != "B12-v4"
        or baseline.get("file_sha256") != B12_BASELINE_FILE_SHA256
        or baseline.get("report_sha256") != B12_BASELINE_REPORT_SHA256
        or baseline.get("semantic_correct") != 11
        or value.get("critical_failures") != []
        or value.get("accepted_invented_identifiers") != 0
        or not isinstance(adapter_record, Mapping)
        or adapter_record.get("manifest_sha256") != _prefixed_sha256(adapter / "manifest.json")
        or adapter_record.get("adapter_sha256")
        != _prefixed_sha256(adapter / "adapters.safetensors")
        or adapter_record.get("global_step") != selection["selected_step"]
        or type(peak) not in (int, float)
        or not math.isfinite(peak)
        or not 0 <= peak <= LIMITS["metal_gb"]
        or not isinstance(identity, Mapping)
        or identity.get("project_before") != identity.get("project_after")
        or identity.get("metis_before") != identity.get("metis_after")
        or identity.get("roster_file_sha256") != B12_ROSTER_SHA256
        or identity.get("freeze_file_sha256") != B12_FREEZE_FILE_SHA256
        or identity.get("freeze_sha256") != B12_FREEZE_SHA256
        or identity.get("oracle_runner_sha256") != B12_ORACLE_RUNNER_SHA256
        or not isinstance(observations, list)
        or len(observations) != 12
        or frozen_ids != observation_ids
        or len(set(observation_ids)) != 12
        or sum(item.get("post_repair_success") is True for item in observations)
        != counts["semantic_correct"]
        or sum(item.get("accepted_invented_identifiers", 0) for item in observations) != 0
        or value.get("recurring_failure_categories") != []
    ):
        _fail("evaluation receipt does not prove a retainable terminal adapter verdict")
    return value


def _is_hex_digest(value: Any, length: int = 64) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _portable_file_record(value: Any, *, expected_path: str | None = None) -> bool:
    return (
        isinstance(value, Mapping)
        and set(value) == ({"path", "bytes", "sha256"} if expected_path else {"bytes", "sha256"})
        and (expected_path is None or value.get("path") == expected_path)
        and type(value.get("bytes")) is int
        and value["bytes"] >= 0
        and _is_hash(value.get("sha256"))
    )


def _verify_portable_dev_bundle(
    value: Any,
    *,
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("packaged dev evidence is not an object")
    body = {key: item for key, item in value.items() if key != "bundle_sha256"}
    directory = {
        "base": "base-dev",
        "restored": "base-dev-restored",
        "step25": "step25-dev",
        "step50": "step50-dev",
        "step100": "step100-dev",
    }.get(label)
    files = value.get("files")
    identity = value.get("identity")
    if (
        directory is None
        or set(value) != {"label", "score", "identity", "files", "bundle_sha256"}
        or value.get("label") != label
        or type(value.get("score")) is not int
        or not 0 <= value["score"] <= 16
        or value.get("bundle_sha256") != _canonical_hash(body)
        or not isinstance(files, Mapping)
        or set(files) != {"candidates", "generation", "semantic"}
        or not _portable_file_record(
            files.get("candidates"), expected_path=f"{directory}/candidates.jsonl"
        )
        or not _portable_file_record(
            files.get("generation"), expected_path=f"{directory}/generation.json"
        )
        or not _portable_file_record(
            files.get("semantic"), expected_path=f"{directory}/semantic.json"
        )
        or not isinstance(identity, Mapping)
    ):
        _fail("packaged dev evidence is malformed")
    pin = _json(CHECKPOINT_PIN)
    if (
        identity.get("base_revision") != pin.get("revision")
        or identity.get("base_config_sha256") != pin.get("config_sha256")
        or identity.get("base_tree_metadata_sha256") != pin.get("tree_metadata_sha256")
        or identity.get("base_verification_report_sha256") != _prefixed_sha256(CHECKPOINT_REPORT)
        or type(identity.get("base_payload_files")) is not int
        or identity["base_payload_files"] <= 0
    ):
        _fail("packaged dev evidence base identity drift")
    if label in {"base", "restored"}:
        if identity.get("adapter_enabled") is not False or identity.get("adapter") is not None:
            _fail("packaged adapter-off dev evidence is not adapter-off")
    else:
        step = int(label.removeprefix("step"))
        adapter = identity.get("adapter")
        if (
            identity.get("adapter_enabled") is not True
            or not isinstance(adapter, Mapping)
            or adapter.get("global_step") != step
            or not _is_hash(adapter.get("manifest_sha256"))
            or not _is_hash(adapter.get("adapter_sha256"))
        ):
            _fail("packaged adapter-on dev evidence identity drift")
    return dict(value)


def _verify_portable_package_receipts(
    package_dir: Path,
    *,
    dataset: Mapping[str, Any],
    selection: Mapping[str, Any],
    restore: Mapping[str, Any],
    training: Mapping[str, Any],
    evaluation: Mapping[str, Any],
) -> None:
    """Validate every retained claim without depending on excluded raw evidence."""
    expected_counts = {
        "train": {"F-1": 22, "F-2": 21, "F-3": 21},
        "dev": {"F-1": 5, "F-2": 5, "F-3": 6},
    }
    hashes = dataset.get("hashes")
    if (
        dataset.get("schema_version") != 1
        or dataset.get("status") != "materialized_verified"
        or dataset.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or dataset.get("catalog_pin_sha256") != CATALOG_PIN_SHA256
        or dataset.get("exclusions_sha256") != EXCLUSIONS_SHA256
        or dataset.get("b12_roster_sha256") != B12_ROSTER_SHA256
        or dataset.get("counts") != expected_counts
        or not isinstance(hashes, Mapping)
        or set(hashes) != DATASET_FILES - {"receipt.json"}
        or not all(_is_hash(item) for item in hashes.values())
        or not _is_hash(dataset.get("split_manifest"))
        or not _is_hash(dataset.get("dataset_manifest"))
    ):
        _fail("packaged dataset receipt has an invalid semantic contract")

    step = selection.get("selected_step")
    expected_steps = {25: [25], 50: [25, 50], 100: [25, 50, 100]}.get(step)
    evidence = training.get("evidence")
    checkpoint = evidence.get("checkpoint") if isinstance(evidence, Mapping) else None
    phases = evidence.get("phases") if isinstance(evidence, Mapping) else None
    if (
        expected_steps is None
        or training.get("schema_version") != 1
        or training.get("status") != "verified"
        or training.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or training.get("mode") != "single_config_no_retry_qlora"
        or training.get("dataset_receipt_sha256")
        != _prefixed_sha256(package_dir / "dataset-receipt.json")
        or not isinstance(evidence, Mapping)
        or not _is_hash(evidence.get("freeze_file_sha256"))
        or not _is_hash(evidence.get("freeze_self_sha256"))
        or not _is_hex_digest(evidence.get("preimage_commit"), 40)
        or not _is_hex_digest(evidence.get("published_execution_head"), 40)
        or not isinstance(checkpoint, Mapping)
        or checkpoint.get("global_step") != step
        or checkpoint.get("model_revision") != selection.get("model_revision")
        or checkpoint.get("manifest_sha256") != selection.get("checkpoint_manifest_sha256")
        or checkpoint.get("adapter_sha256") != selection.get("adapter_sha256")
        or checkpoint.get("adapter_config_sha256") != selection.get("adapter_config_sha256")
        or not isinstance(phases, list)
        or [phase.get("step") for phase in phases if isinstance(phase, Mapping)] != expected_steps
    ):
        _fail("packaged training receipt does not retain the bounded phase chain")
    for phase in phases:
        if not isinstance(phase, Mapping) or not all(
            _is_hash(phase.get(key))
            for key in (
                "marker_sha256",
                "marker_self_sha256",
                "phase_receipt_sha256",
                "phase_receipt_self_sha256",
                "telemetry_summary_sha256",
                "continuation_authority_sha256",
            )
        ):
            _fail("packaged training phase evidence is malformed")
        retained = phase.get("retained_checkpoints")
        expected_retained = {
            25: [25],
            50: [25, 50],
            100: [25, 50, 75, 100],
        }[phase["step"]]
        if (
            not isinstance(retained, list)
            or [item.get("global_step") for item in retained if isinstance(item, Mapping)]
            != expected_retained
            or any(
                not isinstance(item, Mapping)
                or not _is_hash(item.get("manifest_sha256"))
                or not _is_hash(item.get("checkpoint_sha256"))
                for item in retained
            )
        ):
            _fail("packaged retained-checkpoint evidence is malformed")

    base = _verify_portable_dev_bundle(selection.get("base_evidence"), label="base")
    gates_raw = selection.get("gate_evidence")
    if not isinstance(gates_raw, list) or len(gates_raw) != len(expected_steps):
        _fail("packaged selection gate roster is incomplete")
    gates = [
        _verify_portable_dev_bundle(item, label=f"step{gate_step}")
        for item, gate_step in zip(gates_raw, expected_steps, strict=True)
    ]
    scores = [item["score"] for item in gates]
    final_adapter = gates[-1]["identity"]["adapter"]
    if (
        selection.get("schema_version") != 1
        or selection.get("status") != "selected"
        or selection.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or selection.get("selection_surface") != "frozen_dev16_only"
        or selection.get("b12_observed") is not False
        or selection.get("dataset_receipt_sha256")
        != _prefixed_sha256(package_dir / "dataset-receipt.json")
        or selection.get("training_receipt_sha256")
        != _prefixed_sha256(package_dir / "training-receipt.json")
        or selection.get("training_self_sha256") != training.get("training_sha256")
        or selection.get("base_semantic_correct") != base["score"]
        or selection.get("selected_semantic_correct") != scores[-1]
        or selection.get("evidence_roster_sha256")
        != _canonical_hash({"base": base, "gates": gates})
        or final_adapter.get("global_step") != step
        or final_adapter.get("manifest_sha256") != selection.get("checkpoint_manifest_sha256")
        or final_adapter.get("adapter_sha256") != selection.get("adapter_sha256")
        or selection.get("adapter_sha256") != _prefixed_sha256(package_dir / "adapters.safetensors")
        or selection.get("adapter_config_sha256")
        != _prefixed_sha256(package_dir / "adapter_config.json")
        or (len(scores) >= 2 and scores[0] < base["score"] + 1)
        or (len(scores) == 3 and scores[1] < scores[0] + 1)
        or (len(scores) == 1 and scores[0] >= base["score"] + 1)
        or (len(scores) == 2 and scores[1] >= scores[0] + 1)
    ):
        _fail("packaged selection receipt has an invalid dev-only decision")

    initial = _verify_portable_dev_bundle(restore.get("initial_base_evidence"), label="base")
    restored = _verify_portable_dev_bundle(restore.get("restored_base_evidence"), label="restored")
    initial_candidate = initial["files"]["candidates"]
    restored_candidate = restored["files"]["candidates"]
    if (
        restore.get("schema_version") != 1
        or restore.get("status") != "verified"
        or restore.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or restore.get("mode") != "adapter_off_exact_restore"
        or restore.get("dataset_receipt_sha256")
        != _prefixed_sha256(package_dir / "dataset-receipt.json")
        or restore.get("selection_receipt_sha256")
        != _prefixed_sha256(package_dir / "selection-receipt.json")
        or restore.get("selection_self_sha256") != selection.get("selection_sha256")
        or restore.get("selected_step") != step
        or restore.get("adapter_sha256") != selection.get("adapter_sha256")
        or restore.get("exact_candidate_restore") is not True
        or initial != base
        or initial_candidate.get("bytes") != restored_candidate.get("bytes")
        or initial_candidate.get("sha256") != restored_candidate.get("sha256")
    ):
        _fail("packaged adapter-off restore evidence is invalid")

    counts = evaluation.get("counts")
    baseline = evaluation.get("baseline")
    adapter = evaluation.get("adapter")
    runtime = evaluation.get("runtime")
    identity = evaluation.get("identity")
    observations = evaluation.get("observations")
    peak = runtime.get("peak_metal_gb") if isinstance(runtime, Mapping) else None
    freeze = _json(B12_FREEZE)
    expected_task_ids = [task.get("task_id") for task in freeze.get("tasks", [])]
    observed_task_ids = (
        [item.get("task_id") for item in observations if isinstance(item, Mapping)]
        if isinstance(observations, list)
        else []
    )
    expected_verdict = (
        (
            "LOCAL_ADAPTER_UPLIFT"
            if scores[-1] > base["score"] or counts.get("semantic_correct", -1) > 11
            else "LOCAL_ADAPTER_EXPERIMENTAL"
        )
        if isinstance(counts, Mapping)
        else None
    )
    if (
        evaluation.get("schema_version") != 1
        or evaluation.get("status") != "verified"
        or evaluation.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or evaluation.get("mode") != "adapter_on_b12_terminal_replay"
        or evaluation.get("training_authorized") is not False
        or evaluation.get("selection_feedback") is not False
        or evaluation.get("verdict") != expected_verdict
        or evaluation.get("dataset_receipt_sha256")
        != _prefixed_sha256(package_dir / "dataset-receipt.json")
        or evaluation.get("selection_receipt_sha256")
        != _prefixed_sha256(package_dir / "selection-receipt.json")
        or evaluation.get("adapter_off_restore_receipt_sha256")
        != _prefixed_sha256(package_dir / "restore-receipt.json")
        or evaluation.get("adapter_off_restore_self_sha256") != restore.get("restore_sha256")
        or not isinstance(counts, Mapping)
        or counts.get("in") != 12
        or counts.get("out") != 12
        or counts.get("distinct") != 12
        or counts.get("gaps") != 0
        or type(counts.get("semantic_correct")) is not int
        or not 11 <= counts["semantic_correct"] <= 12
        or not isinstance(baseline, Mapping)
        or baseline.get("id") != "B12-v4"
        or baseline.get("file_sha256") != B12_BASELINE_FILE_SHA256
        or baseline.get("report_sha256") != B12_BASELINE_REPORT_SHA256
        or baseline.get("semantic_correct") != 11
        or evaluation.get("critical_failures") != []
        or evaluation.get("accepted_invented_identifiers") != 0
        or evaluation.get("recurring_failure_categories") != []
        or not isinstance(adapter, Mapping)
        or adapter.get("global_step") != step
        or adapter.get("manifest_sha256") != selection.get("checkpoint_manifest_sha256")
        or adapter.get("adapter_sha256") != selection.get("adapter_sha256")
        or type(peak) not in (int, float)
        or not math.isfinite(peak)
        or not 0 <= peak <= LIMITS["metal_gb"]
        or not isinstance(identity, Mapping)
        or identity.get("project_before") != identity.get("project_after")
        or identity.get("metis_before") != identity.get("metis_after")
        or identity.get("roster_file_sha256") != B12_ROSTER_SHA256
        or identity.get("freeze_file_sha256") != B12_FREEZE_FILE_SHA256
        or identity.get("freeze_sha256") != B12_FREEZE_SHA256
        or identity.get("oracle_runner_sha256") != B12_ORACLE_RUNNER_SHA256
        or observed_task_ids != expected_task_ids
        or len(set(observed_task_ids)) != 12
        or sum(item.get("post_repair_success") is True for item in observations)
        != counts.get("semantic_correct")
        or sum(item.get("accepted_invented_identifiers", 0) for item in observations) != 0
    ):
        _fail("packaged terminal B12 evidence is not retainable")
    if _sha256(package_dir / "runtime.lock") != _json(RUNTIME_PIN).get("lock_sha256"):
        _fail("packaged runtime lock differs from the qualified runtime")


def verify_package(package_dir: Path) -> dict[str, Any]:
    _no_symlinks(package_dir)
    if not package_dir.is_dir() or {item.name for item in package_dir.iterdir()} != PACKAGE_FILES:
        _fail("adapter package file roster mismatch")
    if any(not item.is_file() or item.stat().st_nlink != 1 for item in package_dir.iterdir()):
        _fail("adapter package contains a non-regular or linked file")
    manifest = _json(package_dir / "manifest.json")
    manifest_body = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    if manifest.get("manifest_sha256") != _canonical_hash(manifest_body):
        _fail("adapter package manifest self-hash mismatch")
    checksum = _json(package_dir / "package-checksum.json")
    checksum_body = {key: value for key, value in checksum.items() if key != "package_sha256"}
    if checksum.get("package_sha256") != _canonical_hash(checksum_body):
        _fail("adapter package checksum self-hash mismatch")
    expected_records = {
        name: _record(package_dir / name)
        for name in PACKAGE_FILES
        if name != "package-checksum.json"
    }
    if checksum.get("files") != expected_records:
        _fail("adapter package payload hash mismatch")
    if checksum.get("manifest_sha256") != _prefixed_sha256(package_dir / "manifest.json"):
        _fail("adapter package manifest file hash mismatch")
    dataset = _json(package_dir / "dataset-receipt.json")
    selection = _json(package_dir / "selection-receipt.json")
    restore = _json(package_dir / "restore-receipt.json")
    training = _json(package_dir / "training-receipt.json")
    evaluation = _json(package_dir / "evaluation-receipt.json")
    dataset_body = {key: item for key, item in dataset.items() if key != "receipt_sha256"}
    selection_body = {key: item for key, item in selection.items() if key != "selection_sha256"}
    restore_body = {key: item for key, item in restore.items() if key != "restore_sha256"}
    training_body = {key: item for key, item in training.items() if key != "training_sha256"}
    evaluation_body = {key: item for key, item in evaluation.items() if key != "receipt_sha256"}
    payload_manifest = {
        name: _record(package_dir / name)
        for name in PACKAGE_FILES - {"manifest.json", "package-checksum.json"}
    }
    if (
        manifest.get("schema_version") != 1
        or manifest.get("status") != "sealed"
        or manifest.get("wave") != "INITIAL_LOCAL_QLORA_V1"
        or manifest.get("verdict") not in VERDICTS
        or manifest.get("files") != payload_manifest
        or manifest.get("dataset_receipt_file_sha256")
        != _prefixed_sha256(package_dir / "dataset-receipt.json")
        or manifest.get("dataset_receipt_self_sha256") != dataset.get("receipt_sha256")
        or manifest.get("selection_receipt_sha256")
        != _prefixed_sha256(package_dir / "selection-receipt.json")
        or manifest.get("restore_receipt_sha256")
        != _prefixed_sha256(package_dir / "restore-receipt.json")
        or manifest.get("training_receipt_sha256")
        != _prefixed_sha256(package_dir / "training-receipt.json")
        or manifest.get("evaluation_receipt_sha256")
        != _prefixed_sha256(package_dir / "evaluation-receipt.json")
        or dataset.get("receipt_sha256") != _canonical_hash(dataset_body)
        or selection.get("selection_sha256") != _canonical_hash(selection_body)
        or restore.get("restore_sha256") != _canonical_hash(restore_body)
        or training.get("training_sha256") != _canonical_hash(training_body)
        or evaluation.get("receipt_sha256") != _canonical_hash(evaluation_body)
        or selection.get("dataset_receipt_sha256")
        != _prefixed_sha256(package_dir / "dataset-receipt.json")
        or restore.get("selection_receipt_sha256")
        != _prefixed_sha256(package_dir / "selection-receipt.json")
        or selection.get("training_receipt_sha256")
        != _prefixed_sha256(package_dir / "training-receipt.json")
        or evaluation.get("selection_receipt_sha256")
        != _prefixed_sha256(package_dir / "selection-receipt.json")
        or evaluation.get("adapter_off_restore_receipt_sha256")
        != _prefixed_sha256(package_dir / "restore-receipt.json")
        or selection.get("adapter_sha256") != _prefixed_sha256(package_dir / "adapters.safetensors")
        or manifest.get("global_step") != selection.get("selected_step")
        or manifest.get("verdict") != evaluation.get("verdict")
    ):
        _fail("adapter package receipt cross-links are invalid")
    _verify_portable_package_receipts(
        package_dir,
        dataset=dataset,
        selection=selection,
        restore=restore,
        training=training,
        evaluation=evaluation,
    )
    return {
        "status": "verified",
        "verdict": manifest.get("verdict"),
        "model_revision": manifest.get("model_revision"),
        "global_step": manifest.get("global_step"),
        "package_sha256": checksum["package_sha256"],
        "files": len(PACKAGE_FILES),
    }


def _deterministic_archive(package_dir: Path, archive: Path) -> dict[str, Any]:
    if archive.exists() or archive.is_symlink():
        _fail("adapter archive destination must be absent")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{archive.name}.", dir=archive.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with tarfile.open(temporary, mode="w", format=tarfile.USTAR_FORMAT) as bundle:
            for path in sorted(package_dir.iterdir(), key=lambda item: item.name):
                info = bundle.gettarinfo(str(path), arcname=f"metis-model1-adapter/{path.name}")
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mtime = 0
                info.mode = 0o644
                with path.open("rb") as stream:
                    bundle.addfile(info, stream)
        with temporary.open("rb+") as stream:
            os.fsync(stream.fileno())
        os.replace(temporary, archive)
        parent = os.open(archive.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise
    return {"path": str(archive), **_record(archive)}


def verify_archive(archive: Path) -> dict[str, Any]:
    """Restore an adapter archive into a fresh directory and verify the package."""
    if archive.is_symlink() or not archive.is_file() or archive.stat().st_nlink != 1:
        _fail("adapter archive is missing, linked, or not regular")
    expected_names = {f"metis-model1-adapter/{name}" for name in PACKAGE_FILES}
    restored_records: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix=".adapter-restore-", dir=archive.parent) as root:
        package_dir = Path(root) / "metis-model1-adapter"
        package_dir.mkdir()
        try:
            with tarfile.open(archive, mode="r:") as bundle:
                members = bundle.getmembers()
                names = [member.name for member in members]
                if len(names) != len(set(names)) or set(names) != expected_names:
                    _fail("adapter archive member roster mismatch")
                for member in members:
                    if (
                        not member.isfile()
                        or member.linkname
                        or member.uid != 0
                        or member.gid != 0
                        or member.uname
                        or member.gname
                        or member.mtime != 0
                        or member.mode != 0o644
                        or member.size < 0
                    ):
                        _fail("adapter archive contains unsafe or non-deterministic metadata")
                    relative = Path(member.name).relative_to("metis-model1-adapter")
                    if len(relative.parts) != 1 or relative.name not in PACKAGE_FILES:
                        _fail("adapter archive contains an unsafe member path")
                    target = package_dir / relative.name
                    stream = bundle.extractfile(member)
                    if stream is None:
                        _fail("adapter archive member cannot be read")
                    with target.open("xb") as destination:
                        shutil.copyfileobj(stream, destination, length=1024 * 1024)
                        destination.flush()
                        os.fsync(destination.fileno())
                    if target.stat().st_size != member.size:
                        _fail("adapter archive member size drift")
                    restored_records[member.name] = _record(target)
        except (OSError, tarfile.TarError, ValueError) as exc:
            _fail(f"invalid adapter archive: {exc}")
        verification = verify_package(package_dir)
    return {
        "status": "fresh_restore_verified",
        "archive": _record(archive),
        "members": dict(sorted(restored_records.items())),
        "package": verification,
    }


def package(
    adapter: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    verdict: str | None = None,
    evaluation_receipt: Path | None = None,
    dataset_receipt: Path | None = None,
    selection_receipt: Path | None = None,
    restore_receipt: Path | None = None,
) -> dict[str, Any]:
    output_root = _under(output_root, PROJECT_ROOT / "artifacts")
    if verdict not in VERDICTS:
        _fail("package verdict is not retainable")
    if (
        evaluation_receipt is None
        or dataset_receipt is None
        or selection_receipt is None
        or restore_receipt is None
    ):
        _fail("package requires dataset, selection, restore, and evaluation receipts")
    if not adapter.is_dir() or {item.name for item in adapter.iterdir()} != {
        "adapter_config.json",
        "adapters.safetensors",
        "manifest.json",
        "state.json",
        "state.safetensors",
    }:
        _fail("checkpoint directory contains an extra or missing file")
    _check_receipt(dataset_receipt)
    checkpoint = verify_checkpoint(adapter, expected_dataset=dataset_receipt.parent / "train.jsonl")
    verify_evaluation_receipt(
        evaluation_receipt,
        verdict=verdict,
        adapter=adapter,
        dataset_receipt=dataset_receipt,
        selection_receipt=selection_receipt,
        restore_receipt=restore_receipt,
    )
    output_root.mkdir(parents=True, exist_ok=True)
    _no_symlinks(output_root)
    dest = output_root / "package"
    archive = output_root / "metis-model1-adapter.tar"
    archive_receipt = output_root / "metis-model1-adapter-archive.json"
    if any(path.exists() or path.is_symlink() for path in (dest, archive, archive_receipt)):
        _fail("package outputs must all be absent")

    staging = Path(tempfile.mkdtemp(prefix=".package-staging-", dir=output_root))
    try:
        for name in ("adapters.safetensors", "adapter_config.json"):
            shutil.copy2(adapter / name, staging / name)
        shutil.copy2(RUNTIME_LOCK, staging / "runtime.lock")
        shutil.copy2(dataset_receipt, staging / "dataset-receipt.json")
        shutil.copy2(evaluation_receipt, staging / "evaluation-receipt.json")
        shutil.copy2(selection_receipt, staging / "selection-receipt.json")
        shutil.copy2(restore_receipt, staging / "restore-receipt.json")
        shutil.copy2(DEFAULT_TRAINING_RECEIPT, staging / "training-receipt.json")
        for copied in staging.iterdir():
            if copied.is_file():
                with copied.open("rb") as stream:
                    os.fsync(stream.fileno())
        card = (
            "# Metis Model 1 — INITIAL_LOCAL_QLORA_V1\n\n"
            f"Verdict: `{verdict}`  \n"
            f"Selected optimizer step: `{checkpoint['global_step']}`  \n"
            f"Base revision: `{checkpoint['model_revision']}`\n\n"
            "Load the pinned Qwen3.8 base with this directory as `adapter_path`. "
            "Removing `adapter_path` restores the unchanged base model. This is a local, "
            "non-promoted adapter and is not an Accuracy-99 claim.\n"
        )
        _atomic_write(staging / "CARD.md", card.encode("utf-8"))
        payload_names = {
            "CARD.md",
            "adapter_config.json",
            "adapters.safetensors",
            "dataset-receipt.json",
            "evaluation-receipt.json",
            "selection-receipt.json",
            "restore-receipt.json",
            "training-receipt.json",
            "runtime.lock",
        }
        manifest_body = {
            "schema_version": 1,
            "status": "sealed",
            "wave": "INITIAL_LOCAL_QLORA_V1",
            "verdict": verdict,
            "model_revision": checkpoint["model_revision"],
            "global_step": checkpoint["global_step"],
            "dataset_receipt_file_sha256": _prefixed_sha256(dataset_receipt),
            "dataset_receipt_self_sha256": _json(dataset_receipt)["receipt_sha256"],
            "evaluation_receipt_sha256": _prefixed_sha256(evaluation_receipt),
            "selection_receipt_sha256": _prefixed_sha256(selection_receipt),
            "restore_receipt_sha256": _prefixed_sha256(restore_receipt),
            "training_receipt_sha256": _prefixed_sha256(DEFAULT_TRAINING_RECEIPT),
            "files": {name: _record(staging / name) for name in sorted(payload_names)},
            "excludes": [
                "base_weights",
                "dataset_rows",
                "optimizer_state",
                "raw_model_output",
                "raw_oracle_text",
                "logs",
                "credentials",
                "env",
            ],
        }
        manifest = {**manifest_body, "manifest_sha256": _canonical_hash(manifest_body)}
        _atomic_write(
            staging / "manifest.json",
            (json.dumps(manifest, allow_nan=False, sort_keys=True) + "\n").encode("utf-8"),
        )
        checksum_files = {
            name: _record(staging / name)
            for name in sorted(PACKAGE_FILES - {"package-checksum.json"})
        }
        checksum_body = {
            "schema_version": 1,
            "status": "sealed",
            "manifest_sha256": _prefixed_sha256(staging / "manifest.json"),
            "files": checksum_files,
        }
        checksum = {**checksum_body, "package_sha256": _canonical_hash(checksum_body)}
        _atomic_write(
            staging / "package-checksum.json",
            (json.dumps(checksum, allow_nan=False, sort_keys=True) + "\n").encode("utf-8"),
        )
        directory = os.open(staging, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        os.replace(staging, dest)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    try:
        package_verification = verify_package(dest)
        archive_record = _deterministic_archive(dest, archive)
        fresh_restore = verify_archive(archive)
        archive_body = {
            "schema_version": 1,
            "status": "sealed",
            "package_sha256": package_verification["package_sha256"],
            "archive": archive_record,
            "fresh_restore": fresh_restore,
        }
        archive_document = {**archive_body, "receipt_sha256": _canonical_hash(archive_body)}
        _atomic_write(
            archive_receipt,
            (json.dumps(archive_document, allow_nan=False, sort_keys=True) + "\n").encode("utf-8"),
        )
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        for partial in (archive, archive_receipt):
            with contextlib.suppress(FileNotFoundError):
                partial.unlink()
        raise
    return {
        "package": str(dest),
        "archive": archive_record,
        "archive_receipt": str(archive_receipt),
        "verification": package_verification,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)
    q = sub.add_parser("preflight")
    q.add_argument("--checkpoint", type=Path, required=True)
    q.add_argument("--dataset-receipt", type=Path, required=True)
    v = sub.add_parser("verify-checkpoint")
    v.add_argument("step", type=Path)
    z = sub.add_parser("verify-package")
    z.add_argument("package_dir", type=Path)
    y = sub.add_parser("verify-archive")
    y.add_argument("archive", type=Path)
    k = sub.add_parser("package")
    k.add_argument("adapter", type=Path)
    k.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    k.add_argument("--verdict", required=True)
    k.add_argument("--evaluation-receipt", type=Path, required=True)
    k.add_argument("--dataset-receipt", type=Path, required=True)
    k.add_argument("--selection-receipt", type=Path, required=True)
    k.add_argument("--restore-receipt", type=Path, required=True)
    w = sub.add_parser("worker")
    w.add_argument("--model", type=Path, required=True)
    w.add_argument("--adapter", type=Path)
    a = sub.add_parser("evaluate-dev")
    a.add_argument("--model", type=Path, required=True)
    a.add_argument("--adapter", type=Path)
    a.add_argument("--requests", type=Path, required=True)
    a.add_argument("--dataset-receipt", type=Path, required=True)
    a.add_argument("--report", type=Path, required=True)
    a.add_argument("--candidate-jsonl", type=Path, required=True)
    a.add_argument("--timeout", type=float, default=LIMITS["hours"] * 3600)
    s = sub.add_parser("score-dev")
    s.add_argument("--dataset", type=Path, required=True)
    s.add_argument("--candidates", type=Path, required=True)
    s.add_argument("--generation-report", type=Path, required=True)
    s.add_argument("--report", type=Path, required=True)
    s.add_argument("--metis-root", type=Path, required=True)
    s.add_argument("--node-path", type=Path, required=True)
    d = sub.add_parser("seal-selection")
    d.add_argument("--adapter", type=Path, required=True)
    d.add_argument("--dataset-receipt", type=Path, required=True)
    d.add_argument("--base-report", type=Path, required=True)
    d.add_argument("--gate-report", type=Path, action="append", required=True)
    d.add_argument("--output", type=Path, default=DEFAULT_SELECTION_RECEIPT)
    t = sub.add_parser("seal-training")
    t.add_argument("--adapter", type=Path, required=True)
    t.add_argument("--dataset-receipt", type=Path, required=True)
    t.add_argument("--output", type=Path, default=DEFAULT_TRAINING_RECEIPT)
    r = sub.add_parser("seal-restore")
    r.add_argument("--adapter", type=Path, required=True)
    r.add_argument("--dataset-receipt", type=Path, required=True)
    r.add_argument("--selection-receipt", type=Path, required=True)
    r.add_argument("--output", type=Path, default=DEFAULT_RESTORE_RECEIPT)
    args = p.parse_args(argv)
    try:
        if args.command == "preflight":
            result = preflight(args.checkpoint, args.dataset_receipt)
        elif args.command == "verify-checkpoint":
            result = verify_checkpoint(args.step)
        elif args.command == "verify-package":
            result = verify_package(args.package_dir)
        elif args.command == "verify-archive":
            result = verify_archive(args.archive)
        elif args.command == "worker":
            return worker(args.model, args.adapter)
        elif args.command == "package":
            result = package(
                args.adapter,
                args.output_root,
                args.verdict,
                args.evaluation_receipt,
                args.dataset_receipt,
                args.selection_receipt,
                args.restore_receipt,
            )
        elif args.command == "score-dev":
            result = score_dev_candidates(
                args.dataset,
                args.candidates,
                args.generation_report,
                args.report,
                metis_root=args.metis_root,
                node_path=args.node_path,
            )
        elif args.command == "seal-selection":
            result = seal_selection(
                adapter=args.adapter,
                dataset_receipt=args.dataset_receipt,
                base_report=args.base_report,
                gate_reports=args.gate_report,
                output=args.output,
            )
        elif args.command == "seal-training":
            result = seal_training_receipt(
                adapter=args.adapter,
                dataset_receipt=args.dataset_receipt,
                output=args.output,
            )
        elif args.command == "seal-restore":
            result = seal_adapter_off_restore(
                adapter=args.adapter,
                dataset_receipt=args.dataset_receipt,
                selection_receipt=args.selection_receipt,
                output=args.output,
            )
        else:
            cases = _jsonl_cases(args.requests)
            worker_command = [
                str(SANDBOX_EXEC),
                "-p",
                EVALUATION_SANDBOX_POLICY,
                sys.executable,
                str(Path(__file__).resolve()),
                "worker",
                "--model",
                str(args.model),
            ]
            if args.adapter is not None:
                worker_command.extend(("--adapter", str(args.adapter)))
            result = evaluate_dev(
                cases,
                worker_command,
                args.report,
                args.timeout,
                args.candidate_jsonl,
                evaluation_identity(args.model, args.adapter),
                args.dataset_receipt,
            )
        print(json.dumps(result, sort_keys=True))
        return 0
    except RuntimeContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
