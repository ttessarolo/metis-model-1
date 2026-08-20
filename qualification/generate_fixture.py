from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

TOKENS = tuple(f"QUAL_{letter}" for letter in "ABCDEFGH")
OPAQUE_KEYS = (
    "KESTREL",
    "MARBLE",
    "CEDAR",
    "ORBIT",
    "QUARTZ",
    "HARBOR",
    "LANTERN",
    "VELVET",
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = (REPOSITORY_ROOT / "artifacts").resolve()


def require_artifact_path(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(ARTIFACT_ROOT):
        raise ValueError(f"generated output must stay under {ARTIFACT_ROOT}: {resolved}")
    return resolved


def _json_line(prompt: str, token: str) -> str:
    return json.dumps(
        {
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                },
                {"role": "assistant", "content": token},
            ]
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def build_payload(variant: str = "direct") -> bytes:
    if variant == "direct":
        prompts = tuple(f"Emit exactly {token} and nothing else." for token in TOKENS)
    elif variant == "opaque":
        prompts = tuple(
            f"Return the synthetic lookup value for key {key}. Answer with one token."
            for key in OPAQUE_KEYS
        )
    else:
        raise ValueError(f"unknown fixture variant: {variant}")
    return (
        "\n".join(_json_line(prompt, token) for prompt, token in zip(prompts, TOKENS, strict=True))
        + "\n"
    ).encode()


def write_fixture(output_dir: Path, variant: str = "direct") -> dict[str, object]:
    output_dir = require_artifact_path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "train.jsonl"
    temporary = output_dir / ".train.jsonl.tmp"
    payload = build_payload(variant)
    temporary.write_bytes(payload)
    os.replace(temporary, destination)
    return {
        "schema_version": 1,
        "fixture": "w4-text-only-v1" if variant == "direct" else "w4-opaque-map-v1",
        "examples": len(TOKENS),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "path": str(destination),
        "sensitivity": "public_synthetic",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--variant", choices=("direct", "opaque"), default="direct")
    args = parser.parse_args()

    report_path = require_artifact_path(args.report)
    report = write_fixture(args.output_dir, args.variant)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, report_path)
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
