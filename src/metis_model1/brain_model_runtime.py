"""Dependency-injected Model 1 runtime contract used by Brain turns.

The production MLX loader is deliberately not created here: loading or
downloading model payloads is a separate, explicitly authorised wave.  Brain
can nevertheless be exercised end-to-end with a qualified runtime supplied by
the host (and with deterministic test doubles).
"""

from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from typing import Any, Protocol

from metis_model1.brain_protocol import BrainError, bounded_source

MAX_GENERATION_TOKENS = 512
MAX_TELEMETRY_COUNT = 1_000_000
MAX_TELEMETRY_RATE = 1_000_000.0
MAX_PEAK_METAL_GB = 110.0


@dataclass(frozen=True)
class ModelRequest:
    instruction: str
    intent: str
    target_path: str
    endpoint: str | None
    context: dict[str, Any]
    grounding: dict[str, Any]
    previous_source: str | None = None
    diagnostics: tuple[dict[str, Any], ...] = ()
    cancellation: threading.Event | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class ModelCandidate:
    source: str
    model_revision: str = "unavailable"
    adapter_sha256: str = "unavailable"
    generator: str = "model"
    metrics: dict[str, int | float | str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        bounded_source(self.source)
        if self.generator not in {"model", "grounded_renderer"}:
            raise BrainError("MODEL_INVALID", 503, "candidate generator is invalid")
        allowed = {
            "worker_load_ms",
            "generation_ms",
            "prompt_tokens",
            "generation_tokens",
            "cached_tokens",
            "prompt_tps",
            "generation_tps",
            "finish_reason",
            "peak_metal_gb",
        }
        if self.metrics and set(self.metrics) != allowed:
            raise BrainError("MODEL_INVALID", 503, "candidate metrics are invalid")
        if not self.metrics:
            return
        integer_keys = {
            "worker_load_ms",
            "generation_ms",
            "prompt_tokens",
            "generation_tokens",
            "cached_tokens",
        }
        if any(
            type(self.metrics[key]) is not int or not 0 <= self.metrics[key] <= MAX_TELEMETRY_COUNT
            for key in integer_keys
        ):
            raise BrainError("MODEL_INVALID", 503, "candidate metric is invalid")
        if not 1 <= self.metrics["generation_tokens"] <= MAX_GENERATION_TOKENS:
            raise BrainError("MODEL_INVALID", 503, "candidate token count is invalid")
        if self.metrics["cached_tokens"] > self.metrics["prompt_tokens"]:
            raise BrainError("MODEL_INVALID", 503, "candidate cached token count is invalid")
        for key in ("prompt_tps", "generation_tps"):
            value = self.metrics[key]
            if (
                type(value) not in (int, float)
                or not math.isfinite(float(value))
                or not 0 <= float(value) <= MAX_TELEMETRY_RATE
            ):
                raise BrainError("MODEL_INVALID", 503, "candidate rate is invalid")
        peak = self.metrics["peak_metal_gb"]
        if (
            type(peak) not in (int, float)
            or not math.isfinite(float(peak))
            or not 0 <= float(peak) <= MAX_PEAK_METAL_GB
        ):
            raise BrainError("MODEL_INVALID", 503, "candidate memory metric is invalid")
        if self.metrics["finish_reason"] not in {"stop", "length"}:
            raise BrainError("MODEL_INVALID", 503, "candidate finish reason is invalid")


class BrainModelRuntime(Protocol):
    """The smallest runtime surface Brain needs for generation and repair."""

    @property
    def model_loaded(self) -> bool: ...

    @property
    def model_revision(self) -> str: ...

    @property
    def adapter_sha256(self) -> str: ...

    def generate(self, request: ModelRequest) -> ModelCandidate: ...


class UnavailableModelRuntime:
    """Safe default until the separately qualified MLX runtime is wired in."""

    model_loaded = False
    model_revision = "unavailable"
    adapter_sha256 = "unavailable"

    def generate(self, _request: ModelRequest) -> ModelCandidate:
        raise BrainError("MODEL_UNAVAILABLE", 503, "local Model 1 runtime is unavailable")


class StaticModelRuntime:
    """Small host/test adapter; it never reads tenant files or model payloads."""

    def __init__(
        self,
        source: str,
        *,
        model_revision: str = "test",
        adapter_sha256: str = "test",
    ) -> None:
        self._candidate = ModelCandidate(source, model_revision, adapter_sha256)

    @property
    def model_loaded(self) -> bool:
        return True

    @property
    def model_revision(self) -> str:
        return self._candidate.model_revision

    @property
    def adapter_sha256(self) -> str:
        return self._candidate.adapter_sha256

    def generate(self, _request: ModelRequest) -> ModelCandidate:
        return self._candidate
