from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path

import mlx.core as mx

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = (REPOSITORY_ROOT / "artifacts").resolve()


def require_artifact_path(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(ARTIFACT_ROOT):
        raise ValueError(f"adapter evidence must stay under {ARTIFACT_ROOT}: {resolved}")
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapter-dir", type=Path, required=True)
    parser.add_argument("--expected-step", type=int, required=True)
    parser.add_argument("--expected-parameters", type=int, default=58_363_904)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    adapter_dir = require_artifact_path(args.adapter_dir)
    output = require_artifact_path(args.output)
    final_path = adapter_dir / "adapters.safetensors"
    numbered_path = adapter_dir / f"{args.expected_step:07d}_adapters.safetensors"
    config_path = adapter_dir / "adapter_config.json"
    for required in (final_path, numbered_path, config_path):
        if not required.is_file():
            raise RuntimeError(f"missing adapter artifact: {required.name}")

    final_hash = sha256_file(final_path)
    numbered_hash = sha256_file(numbered_path)
    if final_hash != numbered_hash or final_path.stat().st_size != numbered_path.stat().st_size:
        raise RuntimeError("final and numbered adapter checkpoints differ")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    lora = config.get("lora_parameters")
    if not isinstance(lora, dict):
        raise RuntimeError("adapter config has no lora_parameters")
    expected_lora = {"rank": 8, "scale": 2.0, "dropout": 0.0}
    for key, expected in expected_lora.items():
        if lora.get(key) != expected:
            raise RuntimeError(f"adapter config mismatch for {key}")

    tensors = mx.load(str(final_path))
    if not isinstance(tensors, dict) or not tensors:
        raise RuntimeError("adapter payload is not a non-empty tensor map")
    parameter_count = sum(value.size for value in tensors.values())
    if parameter_count != args.expected_parameters:
        raise RuntimeError(
            f"adapter parameter count {parameter_count} != {args.expected_parameters}"
        )
    finite_checks = [mx.all(mx.isfinite(value)) for value in tensors.values()]
    mx.eval(finite_checks)
    if not all(bool(check.item()) for check in finite_checks):
        raise RuntimeError("adapter contains a non-finite tensor")
    squared_norm = sum(
        float(mx.sum(value.astype(mx.float32) ** 2).item()) for value in tensors.values()
    )
    if not math.isfinite(squared_norm) or squared_norm <= 0:
        raise RuntimeError("adapter has an invalid or zero tensor norm")

    report = {
        "schema_version": 1,
        "status": "verified",
        "step": args.expected_step,
        "adapter_dir": str(adapter_dir),
        "adapter_bytes": final_path.stat().st_size,
        "adapter_sha256": final_hash,
        "config_sha256": sha256_file(config_path),
        "tensor_count": len(tensors),
        "parameter_count": parameter_count,
        "all_tensors_finite": True,
        "squared_l2_norm": squared_norm,
        "final_matches_numbered_checkpoint": True,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
