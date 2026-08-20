"""Probe the pinned MLX-VLM sequence truncation boundary without training.

The fixture deliberately has a short user prompt and a long deterministic
assistant completion.  This exercises the same ``VisionDataset`` and
``iterate_batches`` path used by the qualification wrapper while proving that
completion tokens remain after the requested sequence limit is applied.

The model is always loaded from a local artifact path.  ``mlx_vlm.load`` is
called with remote code disabled and no code in this module downloads or
materializes model payloads.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import tempfile
from collections.abc import Callable, Mapping
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = (REPOSITORY_ROOT / "artifacts").resolve()
CHECKPOINT_REVISION = "3e6447f082e89cc7f0bc6e5441afd38dfce760ff"
FIXTURE_NAME = "w4-sequence-boundary-v1"


class SequenceFixtureError(RuntimeError):
    """Raised when the local sequence qualification contract cannot be met."""


def _lexical_artifact_path(path: Path, *, label: str) -> Path:
    expanded = path.expanduser()
    if not expanded.is_absolute():
        expanded = REPOSITORY_ROOT / expanded
    absolute = expanded.absolute()
    if not absolute.is_relative_to(ARTIFACT_ROOT):
        raise SequenceFixtureError(f"{label} must stay under {ARTIFACT_ROOT}: {absolute}")

    # ``resolve`` alone would silently follow an in-tree symlink.  Reject every
    # existing symlink component so an artifact cannot be redirected laterally.
    current = absolute
    while current != ARTIFACT_ROOT:
        if current.is_symlink():
            raise SequenceFixtureError(f"{label} cannot contain symlink: {current}")
        current = current.parent
    resolved = absolute.resolve(strict=False)
    if not resolved.is_relative_to(ARTIFACT_ROOT):
        raise SequenceFixtureError(f"{label} resolves outside {ARTIFACT_ROOT}: {resolved}")
    return resolved


def require_artifact_path(path: Path, *, label: str = "path") -> Path:
    """Return a safe artifact path and reject path traversal/symlinks."""

    return _lexical_artifact_path(path, label=label)


def _require_new_output(path: Path, *, label: str) -> None:
    if path.exists() or path.is_symlink():
        raise SequenceFixtureError(f"refusing existing output {label}: {path}")


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _to_nested(value: Any) -> Any:
    tolist = getattr(value, "tolist", None)
    return tolist() if callable(tolist) else value


def _flatten(value: Any) -> list[Any]:
    value = _to_nested(value)
    if isinstance(value, (list, tuple)):
        result: list[Any] = []
        for item in value:
            result.extend(_flatten(item))
        return result
    return [value]


def _shape(value: Any) -> list[int]:
    shape = getattr(value, "shape", None)
    if shape is not None:
        return [int(item) for item in shape]
    value = _to_nested(value)
    if not isinstance(value, (list, tuple)):
        return []
    if not value:
        return [0]
    return [len(value), *_shape(value[0])]


def _json_line(messages: list[dict[str, str]]) -> bytes:
    return (
        json.dumps({"messages": messages}, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def build_payload(max_seq_length: int) -> bytes:
    """Build one public-synthetic example with a short prompt.

    There are ``max_seq_length + 32`` distinct completion words.  The model
    tokenizer may encode a word as one or several tokens, so this leaves a
    deterministic margin while keeping the payload comfortably below the
    model's context limit for the qualified 1024-token probe.
    """

    if type(max_seq_length) is not int or not 2 <= max_seq_length <= 32768:
        raise ValueError("max_seq_length must be an integer in [2, 32768]")
    prompt = "Emit the synthetic sequence marker exactly."
    completion = " ".join(f"SEQ_{index:05d}" for index in range(max_seq_length + 32))
    return _json_line(
        [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": completion},
        ]
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise SequenceFixtureError(f"{label} is not a regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SequenceFixtureError(f"cannot read {label}: {path}") from exc
    if not isinstance(value, dict):
        raise SequenceFixtureError(f"{label} must be a JSON object: {path}")
    return value


def _model_config_dict(model: Any) -> dict[str, Any]:
    config = getattr(model, "config", None)
    if isinstance(config, Mapping):
        return dict(config)
    to_dict = getattr(config, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        if isinstance(result, dict):
            return result
    values = getattr(config, "__dict__", None)
    if isinstance(values, dict):
        return dict(values)
    raise SequenceFixtureError("loaded model does not expose a mapping configuration")


def _package_versions() -> dict[str, str]:
    result: dict[str, str] = {}
    for name in ("datasets", "jinja2", "mlx", "mlx-metal", "mlx-vlm", "numpy", "transformers"):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = "unavailable"
    return result


def _default_load(path: Path) -> tuple[Any, Any]:
    from mlx_vlm import load

    return load(
        str(path),
        lazy=False,
        strict=True,
        trust_remote_code=False,
        processor_config={"trust_remote_code": False},
    )


def _default_dataset_loader(path: Path, split: str) -> Any:
    from datasets import load_dataset

    return load_dataset("json", data_files={split: [str(path)]}, split=split)


def _default_vision_dataset() -> type[Any]:
    from mlx_vlm.trainer.datasets import VisionDataset

    return VisionDataset


def _default_iterate_batches() -> Callable[..., Any]:
    from mlx_vlm.trainer.sft_trainer import iterate_batches

    return iterate_batches


def _validate_checkpoint_identity(model_path: Path, report_path: Path) -> dict[str, Any]:
    report = _load_json_object(report_path, label="checkpoint verification report")
    if report.get("schema_version") != 1 or report.get("status") != "verified":
        raise SequenceFixtureError("checkpoint verification report is not a verified v1 report")
    if Path(str(report.get("checkpoint_path", ""))).resolve() != model_path:
        raise SequenceFixtureError("checkpoint verification report path does not match model path")
    if report.get("revision") != CHECKPOINT_REVISION:
        raise SequenceFixtureError("checkpoint verification report has an unexpected revision")
    config_path = model_path / "config.json"
    if config_path.is_symlink() or not config_path.is_file():
        raise SequenceFixtureError(f"model config is not a regular file: {config_path}")
    if report.get("config_sha256") != _sha256_file(config_path):
        raise SequenceFixtureError("local model config does not match checkpoint report")
    return report


def _execute_probe(
    *,
    model_path: Path,
    checkpoint_report_path: Path,
    output_dir: Path,
    report_path: Path,
    max_seq_length: int,
    load_fn: Callable[[Path], tuple[Any, Any]] | None = None,
    dataset_loader: Callable[[Path, str], Any] | None = None,
    vision_dataset_cls: type[Any] | None = None,
    iterate_batches_fn: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    if type(max_seq_length) is not int or not 2 <= max_seq_length <= 32768:
        raise ValueError("max_seq_length must be an integer in [2, 32768]")
    model_path = require_artifact_path(model_path, label="model path")
    checkpoint_report_path = require_artifact_path(
        checkpoint_report_path, label="checkpoint verification report"
    )
    output_dir = require_artifact_path(output_dir, label="output directory")
    report_path = require_artifact_path(report_path, label="qualification report")
    checkpoint_report = _validate_checkpoint_identity(model_path, checkpoint_report_path)
    config_path = model_path / "config.json"
    dataset_path = output_dir / "train.jsonl"
    _require_new_output(dataset_path, label="dataset")
    _require_new_output(report_path, label="report")

    payload = build_payload(max_seq_length)
    _atomic_write(dataset_path, payload)

    loader = load_fn or _default_load
    model, processor = loader(model_path)
    config = _model_config_dict(model)
    model_type = config.get("model_type")
    if model_type != checkpoint_report.get("model_type"):
        raise SequenceFixtureError("loaded model type differs from checkpoint report")
    image_token_index = config.get("image_token_index") or config.get("image_token_id")
    if not image_token_index:
        raise SequenceFixtureError("model config has no image_token_index/image_token_id")

    load_data = dataset_loader or _default_dataset_loader
    dataset = load_data(dataset_path, "train")
    dataset_type = vision_dataset_cls or _default_vision_dataset()
    vision_dataset = dataset_type(
        dataset,
        config,
        processor,
        train_on_completions=True,
    )
    item = vision_dataset[0]
    raw_tokens = len(_flatten(item["input_ids"]))
    conversations = dataset[0].get("messages", dataset[0].get("conversations"))
    prefix = vision_dataset._completion_prefix(conversations, 0, 0)
    if prefix is None:
        raise SequenceFixtureError("fixture does not expose an assistant completion prefix")
    prefix_tokens = int(vision_dataset._token_length(prefix, [], [], image_token_index))
    completion_tokens = raw_tokens - prefix_tokens
    raw_completion_mask = item.get("completion_mask")
    if raw_completion_mask is None:
        raise SequenceFixtureError("VisionDataset did not provide completion_mask")
    masked_completion_tokens = sum(int(value) for value in _flatten(raw_completion_mask))
    if masked_completion_tokens != completion_tokens:
        raise SequenceFixtureError(
            "completion_mask disagrees with prefix/completion token accounting"
        )
    if raw_tokens <= max_seq_length:
        raise SequenceFixtureError(
            f"rendered input is not longer than max_seq_length: {raw_tokens} <= {max_seq_length}"
        )
    if prefix_tokens >= max_seq_length:
        raise SequenceFixtureError("short prompt/prefix consumed the entire sequence budget")
    if completion_tokens <= 0:
        raise SequenceFixtureError("fixture has no assistant completion tokens")

    iterator = (iterate_batches_fn or _default_iterate_batches())(
        vision_dataset,
        batch_size=1,
        max_seq_length=max_seq_length,
        train=False,
    )
    batch = next(iter(iterator))
    batch_input_ids = batch["input_ids"]
    batch_shape = _shape(batch_input_ids)
    if not batch_shape:
        raise SequenceFixtureError("iterate_batches returned a scalar input_ids batch")
    batch_len = int(batch_shape[-1])
    completion_mask = batch.get("completion_mask", [])
    retained_completion_tokens = sum(int(value) for value in _flatten(completion_mask))
    if batch_len != max_seq_length:
        raise SequenceFixtureError(
            f"iterate_batches returned length {batch_len}, expected {max_seq_length}"
        )
    if retained_completion_tokens <= 0:
        raise SequenceFixtureError("completion_mask has no tokens after truncation")

    report = {
        "schema_version": 1,
        "status": "pass",
        "fixture": FIXTURE_NAME,
        "sensitivity": "public_synthetic",
        "max_seq_length": max_seq_length,
        "dataset_path": str(dataset_path),
        "dataset_sha256": _sha256_bytes(payload),
        "dataset_bytes": len(payload),
        "raw_token_count": raw_tokens,
        "prefix_token_count": prefix_tokens,
        "completion_token_count": completion_tokens,
        "raw_completion_mask_token_count": masked_completion_tokens,
        "truncated_token_count": min(raw_tokens, max_seq_length),
        "retained_completion_token_count": retained_completion_tokens,
        "batch_sequence_length": batch_len,
        "batch_shape": batch_shape,
        "model": {
            "checkpoint_path": str(model_path),
            "repository": checkpoint_report["repository"],
            "revision": checkpoint_report["revision"],
            "model_type": model_type,
            "config_sha256": checkpoint_report["config_sha256"],
            "local_config_sha256": _sha256_file(config_path),
            "processor_trust_remote_code": False,
        },
        "runtime": {
            "python": platform.python_version(),
            "packages": _package_versions(),
        },
        "checkpoint_report_sha256": _sha256_file(checkpoint_report_path),
    }
    report_payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write(report_path, report_payload)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--checkpoint-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--max-seq-length", type=int, default=1024)
    args = parser.parse_args()
    report = _execute_probe(
        model_path=args.model_path,
        checkpoint_report_path=args.checkpoint_report,
        output_dir=args.output_dir,
        report_path=args.report,
        max_seq_length=args.max_seq_length,
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
