from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = (REPOSITORY_ROOT / "artifacts").resolve()
TELEMETRY_MODULE = runpy.run_path(str(Path(__file__).with_name("run_with_telemetry.py")))
rss_trend = TELEMETRY_MODULE["_rss_trend"]


def require_artifact_path(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(ARTIFACT_ROOT):
        raise ValueError(f"telemetry evidence must stay under {ARTIFACT_ROOT}: {resolved}")
    return resolved


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--telemetry-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    telemetry_dir = require_artifact_path(args.telemetry_dir)
    output = require_artifact_path(args.output)
    raw_path = telemetry_dir / "rss.jsonl"
    original_summary_path = telemetry_dir / "summary.json"
    original = json.loads(original_summary_path.read_text(encoding="utf-8"))
    if original["telemetry_sha256"] != sha256_file(raw_path):
        raise RuntimeError("raw telemetry no longer matches the original summary")

    samples = []
    for line in raw_path.read_text(encoding="utf-8").splitlines():
        item = json.loads(line)
        samples.append((float(item["elapsed_seconds"]), int(item["rss_bytes"])))
    corrected = dict(original)
    corrected["rss_trend"] = rss_trend(samples)
    corrected["supersedes_summary_sha256"] = sha256_file(original_summary_path)
    corrected["correction"] = "exclude_post_exit_zero_rss_samples_from_trend_only"

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(corrected, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, output)
    print(json.dumps(corrected, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
