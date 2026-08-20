from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import time
from importlib.metadata import version
from pathlib import Path

import mlx.core as mx
from mlx_vlm import generate, load
from mlx_vlm.prompt_utils import apply_chat_template

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = (REPOSITORY_ROOT / "artifacts").resolve()


def require_artifact_path(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(ARTIFACT_ROOT):
        raise ValueError(f"qualification path must stay under {ARTIFACT_ROOT}: {resolved}")
    return resolved


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", type=Path, required=True)
    parser.add_argument("--adapter-path", type=Path)
    parser.add_argument("--checkpoint-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--prompt",
        default="Reply with the single token QUAL_BASE and no other text.",
    )
    parser.add_argument("--expect-text-sha256")
    parser.add_argument(
        "--chat-template",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Render the prompt as a user message with the model chat template.",
    )
    args = parser.parse_args()

    model_path = require_artifact_path(args.model_path)
    output_path = require_artifact_path(args.output)
    checkpoint_report_path = require_artifact_path(args.checkpoint_report)
    adapter_path = require_artifact_path(args.adapter_path) if args.adapter_path else None
    checkpoint_report = json.loads(checkpoint_report_path.read_text(encoding="utf-8"))
    if checkpoint_report.get("status") != "verified":
        raise RuntimeError("checkpoint verification report is not verified")
    if Path(checkpoint_report["checkpoint_path"]).resolve() != model_path:
        raise RuntimeError("checkpoint verification report does not match model path")
    if checkpoint_report.get("revision") != "3e6447f082e89cc7f0bc6e5441afd38dfce760ff":
        raise RuntimeError("checkpoint verification report has an unexpected revision")

    started = time.time()
    model, processor = load(
        str(model_path),
        adapter_path=str(adapter_path) if adapter_path else None,
        lazy=False,
        strict=True,
        processor_config={"trust_remote_code": True},
    )
    loaded = time.time()
    config = getattr(model, "config", None)
    model_type = config.get("model_type") if isinstance(config, dict) else config.model_type
    if model_type != "qwen3_5":
        raise RuntimeError(f"unexpected model_type: {model_type}")
    rendered_prompt = (
        apply_chat_template(
            processor,
            config,
            [{"role": "user", "content": args.prompt}],
            add_generation_prompt=True,
            num_images=0,
            num_audios=0,
            enable_thinking=False,
        )
        if args.chat_template
        else args.prompt
    )
    if not isinstance(rendered_prompt, str) or not rendered_prompt:
        raise RuntimeError("chat template did not produce a non-empty string prompt")
    generation_kwargs = {
        "max_tokens": 16,
        "temperature": 0.0,
        "seed": 17,
        "enable_thinking": False,
        "verbose": False,
    }
    result = generate(model, processor, rendered_prompt, **generation_kwargs)
    repeated = generate(model, processor, rendered_prompt, **generation_kwargs)
    finished = time.time()
    text = result.text
    text_hash = _sha256_text(text)
    if repeated.text != text:
        raise RuntimeError("two deterministic generations produced different text")
    if not text or not text.encode("utf-8"):
        raise RuntimeError("generation produced empty or invalid UTF-8 text")
    numeric_metrics = (
        result.prompt_tps,
        result.generation_tps,
        result.peak_memory,
    )
    if not all(math.isfinite(value) for value in numeric_metrics):
        raise RuntimeError("generation produced a non-finite metric")
    if args.expect_text_sha256 and text_hash != args.expect_text_sha256:
        raise RuntimeError(
            f"adapter-off baseline changed: expected {args.expect_text_sha256}, got {text_hash}"
        )

    report = {
        "schema_version": 1,
        "status": "pass",
        "adapter": str(adapter_path) if adapter_path else None,
        "checkpoint_report_sha256": hashlib.sha256(checkpoint_report_path.read_bytes()).hexdigest(),
        "model_path": str(model_path),
        "model_type": model_type,
        "python": platform.python_version(),
        "packages": {
            name: version(name)
            for name in (
                "datasets",
                "jinja2",
                "mlx",
                "mlx-metal",
                "mlx-vlm",
                "transformers",
            )
        },
        "prompt_sha256": _sha256_text(args.prompt),
        "rendered_prompt_sha256": _sha256_text(rendered_prompt),
        "uses_chat_template": args.chat_template,
        "text": text,
        "text_sha256": text_hash,
        "repeat_text_sha256": _sha256_text(repeated.text),
        "prompt_tokens": result.prompt_tokens,
        "generation_tokens": result.generation_tokens,
        "finish_reason": result.finish_reason,
        "prompt_tps": result.prompt_tps,
        "generation_tps": result.generation_tps,
        "peak_metal_gb": result.peak_memory,
        "load_seconds": loaded - started,
        "generation_seconds": finished - loaded,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, output_path)
    print(json.dumps(report, sort_keys=True))
    mx.clear_cache()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
