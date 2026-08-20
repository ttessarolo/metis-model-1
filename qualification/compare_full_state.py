"""Compare uninterrupted and resumed W4 full-state checkpoints.

The comparison is intentionally stricter than equal loss: trainable model and
optimizer tensors must have the same canonical safetensors bytes, adapter
bytes must match, and all continuation-relevant JSON state must be identical.
Wall-clock telemetry is excluded because it is observational, not resumable
state.  Inputs and the generated report stay under the ignored artifacts tree.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = (REPOSITORY_ROOT / "artifacts").resolve()
MANIFEST_FILE = "manifest.json"
STATE_FILE = "state.json"
EXACT_FILES = (
    "state.safetensors",
    "adapters.safetensors",
    "adapter_config.json",
)
PAYLOAD_FILES = (STATE_FILE, *EXACT_FILES)
SEMANTIC_STATE_FIELDS = (
    "schema_version",
    "status",
    "global_step",
    "model",
    "dataset",
    "training_config",
    "distributed",
    "optimizer",
    "model_trainable_signature",
    "optimizer_state_signature",
    "rng",
    "sampler",
    "runtime",
    "arrays_signature",
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ComparisonError(RuntimeError):
    """Raised when the full-state equivalence contract is not met."""


def require_artifact_path(path: Path, *, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise ComparisonError(f"{label} cannot be a symlink: {expanded}")
    resolved = expanded.resolve()
    if not resolved.is_relative_to(ARTIFACT_ROOT):
        raise ComparisonError(f"{label} must stay under {ARTIFACT_ROOT}: {resolved}")
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ComparisonError(f"{label} is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ComparisonError(f"cannot read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise ComparisonError(f"{label} must be a JSON object: {path}")
    return value


def inspect_checkpoint(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_dir():
        raise ComparisonError(f"checkpoint is not a regular directory: {path}")
    manifest = load_object(path / MANIFEST_FILE, label="checkpoint manifest")
    if manifest.get("schema_version") != 1 or manifest.get("status") != "complete":
        raise ComparisonError(f"checkpoint manifest is not complete v1: {path}")
    files = manifest.get("files")
    if not isinstance(files, dict) or set(files) != set(PAYLOAD_FILES):
        raise ComparisonError(f"checkpoint manifest payload set is invalid: {path}")

    actual_files: dict[str, dict[str, Any]] = {}
    for name in PAYLOAD_FILES:
        file_path = path / name
        if file_path.is_symlink() or not file_path.is_file():
            raise ComparisonError(f"checkpoint payload is missing or unsafe: {file_path}")
        actual = {"bytes": file_path.stat().st_size, "sha256": sha256_file(file_path)}
        expected = files[name]
        if (
            not isinstance(expected, dict)
            or type(expected.get("bytes")) is not int
            or not isinstance(expected.get("sha256"), str)
            or not SHA256_PATTERN.fullmatch(expected["sha256"])
            or actual != expected
        ):
            raise ComparisonError(f"checkpoint payload does not match manifest: {file_path}")
        actual_files[name] = actual

    state = load_object(path / STATE_FILE, label="checkpoint state")
    if state.get("global_step") != manifest.get("global_step"):
        raise ComparisonError(f"state/manifest global step differs: {path}")
    missing_fields = [name for name in SEMANTIC_STATE_FIELDS if name not in state]
    if missing_fields:
        raise ComparisonError(f"checkpoint state is incomplete: {missing_fields}")
    metrics = state.get("last_metrics")
    if not isinstance(metrics, dict) or metrics.get("global_step") != state["global_step"]:
        raise ComparisonError(f"checkpoint metrics are incomplete: {path}")
    loss = metrics.get("loss")
    if not isinstance(loss, (int, float)) or not math.isfinite(loss):
        raise ComparisonError(f"checkpoint loss is not finite: {path}")
    semantic_state = {name: state[name] for name in SEMANTIC_STATE_FIELDS}
    return {
        "path": str(path),
        "global_step": state["global_step"],
        "loss": float(loss),
        "files": actual_files,
        "semantic_state_sha256": canonical_sha256(semantic_state),
        "semantic_state": semantic_state,
    }


def compare(reference: Path, resumed: Path) -> dict[str, Any]:
    left = inspect_checkpoint(reference)
    right = inspect_checkpoint(resumed)
    if left["global_step"] != right["global_step"]:
        raise ComparisonError("reference and resumed checkpoints have different global steps")
    if left["loss"] != right["loss"]:
        raise ComparisonError("reference and resumed checkpoints have different final loss")
    if left["semantic_state"] != right["semantic_state"]:
        raise ComparisonError("reference and resumed continuation state differs")
    for name in EXACT_FILES:
        if left["files"][name] != right["files"][name]:
            raise ComparisonError(f"reference and resumed bytes differ: {name}")
    return {
        "schema_version": 1,
        "status": "pass",
        "comparison": "uninterrupted_vs_stop_resume_bit_exact",
        "global_step": left["global_step"],
        "final_loss": left["loss"],
        "reference_checkpoint": left["path"],
        "resumed_checkpoint": right["path"],
        "semantic_state_sha256": left["semantic_state_sha256"],
        "exact_files": {name: left["files"][name] for name in EXACT_FILES},
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise ComparisonError(f"refusing to overwrite comparison report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare uninterrupted and resumed full-state W4 checkpoints."
    )
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--resumed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        reference = require_artifact_path(args.reference, label="reference checkpoint")
        resumed = require_artifact_path(args.resumed, label="resumed checkpoint")
        output = require_artifact_path(args.output, label="comparison report")
        report = compare(reference, resumed)
        write_report(output, report)
    except ComparisonError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
