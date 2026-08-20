from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import signal
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

NONFINITE = re.compile(r"(?<![A-Za-z])(nan|[-+]?inf)(?![A-Za-z])", re.IGNORECASE)
METAL_MEMORY = re.compile(
    r"(?:Peak mem\s+|[\"']peak_metal_gb[\"']:\s*)([0-9]+(?:\.[0-9]+)?)\s*(?:GB)?",
    re.IGNORECASE,
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = (REPOSITORY_ROOT / "artifacts").resolve()


def require_artifact_path(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(ARTIFACT_ROOT):
        raise ValueError(f"telemetry output must stay under {ARTIFACT_ROOT}: {resolved}")
    return resolved


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rss_tree(process: psutil.Process) -> int:
    processes = [process]
    with contextlib.suppress(psutil.NoSuchProcess, psutil.AccessDenied):
        processes.extend(process.children(recursive=True))
    total = 0
    for item in processes:
        try:
            total += item.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return total


def _terminate_process_group(child: subprocess.Popen[str]) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(child.pid, signal.SIGTERM)
    try:
        child.wait(timeout=20)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=20)


def _rss_trend(samples: list[tuple[float, int]]) -> dict[str, float | int | bool]:
    live_samples = [sample for sample in samples if sample[1] > 0]
    tail = live_samples[max(10, len(live_samples) // 3) :] if len(live_samples) >= 12 else []
    if len(tail) < 3:
        return {
            "evaluated": False,
            "samples": len(tail),
            "growth_gib": 0.0,
            "slope_mib_per_minute": 0.0,
            "nondecreasing_ratio": 0.0,
        }
    times = [sample[0] for sample in tail]
    values = [sample[1] for sample in tail]
    mean_time = statistics.fmean(times)
    mean_value = statistics.fmean(values)
    denominator = sum((value - mean_time) ** 2 for value in times)
    slope = (
        sum((at - mean_time) * (rss - mean_value) for at, rss in tail) / denominator
        if denominator
        else 0.0
    )
    nondecreasing = sum(
        current >= previous for previous, current in zip(values, values[1:], strict=False)
    )
    return {
        "evaluated": True,
        "samples": len(tail),
        "growth_gib": (values[-1] - values[0]) / 1024**3,
        "slope_mib_per_minute": slope * 60 / 1024**2,
        "nondecreasing_ratio": nondecreasing / (len(values) - 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--sample-seconds", type=float, default=1.0)
    parser.add_argument("--max-rss-gib", type=float, default=115.0)
    parser.add_argument("--max-monotonic-growth-gib", type=float, default=8.0)
    parser.add_argument("--min-metal-samples", type=int, default=0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("a command is required after --")

    output_dir = require_artifact_path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "process.log"
    telemetry_path = output_dir / "rss.jsonl"
    summary_path = output_dir / "summary.json"
    stop_reason: list[str] = []
    metal_samples: list[float] = []
    rss_samples: list[tuple[float, int]] = []
    output_lock = threading.Lock()

    started = time.time()
    with log_path.open("w", encoding="utf-8") as log_handle:
        child = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        observed = psutil.Process(child.pid)

        def relay() -> None:
            assert child.stdout is not None
            for line in child.stdout:
                with output_lock:
                    log_handle.write(line)
                    log_handle.flush()
                    sys.stdout.write(line)
                    sys.stdout.flush()
                if NONFINITE.search(line):
                    stop_reason.append("nonfinite_output")
                match = METAL_MEMORY.search(line)
                if match:
                    metal_samples.append(float(match.group(1)))

        relay_thread = threading.Thread(target=relay, daemon=True)
        relay_thread.start()
        samples = 0
        max_rss = 0
        with telemetry_path.open("w", encoding="utf-8") as telemetry_handle:
            while child.poll() is None:
                rss = _rss_tree(observed)
                elapsed = time.time() - started
                max_rss = max(max_rss, rss)
                rss_samples.append((elapsed, rss))
                telemetry_handle.write(
                    json.dumps(
                        {
                            "elapsed_seconds": elapsed,
                            "rss_bytes": rss,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
                telemetry_handle.flush()
                samples += 1
                if rss > args.max_rss_gib * 1024**3:
                    stop_reason.append("rss_limit")
                if stop_reason:
                    _terminate_process_group(child)
                    break
                time.sleep(args.sample_seconds)

        exit_code = child.wait()
        relay_thread.join(timeout=10)

    trend = _rss_trend(rss_samples)
    if (
        trend["evaluated"]
        and trend["growth_gib"] > args.max_monotonic_growth_gib
        and trend["nondecreasing_ratio"] >= 0.9
    ):
        stop_reason.append("monotonic_rss_growth")
    if len(metal_samples) < args.min_metal_samples:
        stop_reason.append("insufficient_metal_samples")

    residual_pids: list[int] = []
    with contextlib.suppress(psutil.NoSuchProcess):
        residual_pids = [process.pid for process in observed.children(recursive=True)]
    if residual_pids:
        stop_reason.append("residual_processes")

    summary = {
        "schema_version": 1,
        "status": "pass" if exit_code == 0 and not stop_reason else "fail",
        "command": command,
        "exit_code": exit_code,
        "stop_reason": stop_reason or None,
        "duration_seconds": time.time() - started,
        "samples": samples,
        "max_rss_bytes": max_rss,
        "max_rss_gib": max_rss / 1024**3,
        "rss_trend": trend,
        "metal_samples": len(metal_samples),
        "peak_metal_gb": max(metal_samples) if metal_samples else None,
        "residual_process_count": len(residual_pids),
        "process_log_sha256": _sha256(log_path),
        "telemetry_sha256": _sha256(telemetry_path),
    }
    temporary = summary_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, summary_path)
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
