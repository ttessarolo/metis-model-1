from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = (REPOSITORY_ROOT / "artifacts").resolve()
PIN_PATH = REPOSITORY_ROOT / "qualification/checkpoint-pin.json"


def require_artifact_path(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(ARTIFACT_ROOT):
        raise ValueError(f"checkpoint evidence must stay under {ARTIFACT_ROOT}: {resolved}")
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    checkpoint = require_artifact_path(args.checkpoint)
    output = require_artifact_path(args.output)
    pin = json.loads(PIN_PATH.read_text(encoding="utf-8"))
    tree_metadata = checkpoint / ".cache/huggingface/trees" / f"{pin['revision']}.json"
    if not tree_metadata.is_file():
        raise RuntimeError("exact-revision Hugging Face tree metadata is missing")
    if sha256_file(tree_metadata) != pin["tree_metadata_sha256"]:
        raise RuntimeError("exact-revision Hugging Face tree metadata hash differs from the pin")

    verified_weights = []
    for expected in pin["weight_files"]:
        weight_path = checkpoint / expected["path"]
        if not weight_path.is_file():
            raise RuntimeError(f"missing checkpoint weight: {weight_path.name}")
        actual_size = weight_path.stat().st_size
        actual_hash = sha256_file(weight_path)
        if actual_size != expected["bytes"] or actual_hash != expected["sha256"]:
            raise RuntimeError(f"checkpoint identity mismatch: {weight_path.name}")
        verified_weights.append(
            {
                "path": weight_path.name,
                "bytes": actual_size,
                "sha256": actual_hash,
            }
        )

    config_path = checkpoint / "config.json"
    if sha256_file(config_path) != pin["config_sha256"]:
        raise RuntimeError("checkpoint config hash differs from the pin")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if config.get("model_type") != pin["model_type"]:
        raise RuntimeError("checkpoint model_type does not match the pin")
    if config.get("quantization") != pin["quantization"]:
        raise RuntimeError("checkpoint quantization does not match the pin")

    report = {
        "schema_version": 1,
        "status": "verified",
        "verified_at": datetime.now(UTC).isoformat(),
        "checkpoint_path": str(checkpoint),
        "repository": pin["repository"],
        "revision": pin["revision"],
        "model_type": config["model_type"],
        "quantization": config["quantization"],
        "config_sha256": pin["config_sha256"],
        "tree_metadata_sha256": pin["tree_metadata_sha256"],
        "weight_files": verified_weights,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
