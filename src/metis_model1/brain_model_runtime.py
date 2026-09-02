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
    reference: str | None = None
    previous_source: str | None = None
    diagnostics: tuple[dict[str, Any], ...] = ()
    cancellation: threading.Event | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class ModelCandidate:
    source: str
    model_revision: str = "unavailable"
    adapter_sha256: str = "unavailable"
    generator: str = "model"
    metrics: dict[str, int | float | str | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        bounded_source(self.source)
        if self.generator not in {"model", "grounded_renderer", "lossless_renderer"}:
            raise BrainError("MODEL_INVALID", 503, "candidate generator is invalid")
        legacy_allowed = {
            "worker_load_ms",
            "generation_ms",
            "prompt_tokens",
            "generation_tokens",
            "cached_tokens",
            "cache_hit",
            "prompt_tps",
            "generation_tps",
            "finish_reason",
            "peak_metal_gb",
        }
        cache_allowed = legacy_allowed | {"cache_hit"}
        phase_allowed = cache_allowed | {
            "cache_mode",
            "worker_request_ms",
            "cache_prepare_ms",
            "tokenization_ms",
            "time_to_first_token_ms",
            "decode_after_first_token_ms",
            "generation_residual_ms",
            "worker_residual_ms",
            "model_lock_queue_ms",
            "uncached_prompt_tokens",
        }
        if self.metrics and set(self.metrics) not in (
            legacy_allowed - {"cache_hit"},
            cache_allowed,
            phase_allowed,
        ):
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
        if set(self.metrics) == phase_allowed:
            integer_keys.update(
                {
                    "tokenization_ms",
                    "worker_request_ms",
                    "cache_prepare_ms",
                    "time_to_first_token_ms",
                    "decode_after_first_token_ms",
                    "generation_residual_ms",
                    "worker_residual_ms",
                    "model_lock_queue_ms",
                    "uncached_prompt_tokens",
                }
            )
        if any(
            type(self.metrics[key]) is not int or not 0 <= self.metrics[key] <= MAX_TELEMETRY_COUNT
            for key in integer_keys
        ):
            raise BrainError("MODEL_INVALID", 503, "candidate metric is invalid")
        if not 1 <= self.metrics["generation_tokens"] <= MAX_GENERATION_TOKENS:
            raise BrainError("MODEL_INVALID", 503, "candidate token count is invalid")
        if self.metrics["cached_tokens"] > self.metrics["prompt_tokens"]:
            raise BrainError("MODEL_INVALID", 503, "candidate cached token count is invalid")
        if "cache_hit" in self.metrics and (
            type(self.metrics["cache_hit"]) is not bool
            or self.metrics["cache_hit"] != (self.metrics["cached_tokens"] > 0)
        ):
            raise BrainError("MODEL_INVALID", 503, "candidate cache hit metric is invalid")
        for key in ("prompt_tps", "generation_tps"):
            value = self.metrics[key]
            if (
                type(value) not in (int, float)
                or not math.isfinite(float(value))
                or not 0 <= float(value) <= MAX_TELEMETRY_RATE
                or (set(self.metrics) == phase_allowed and float(value) <= 0)
            ):
                raise BrainError("MODEL_INVALID", 503, "candidate rate is invalid")
        if set(self.metrics) == phase_allowed and (
            self.metrics["cache_mode"] not in {"disabled", "prefix"}
            or self.metrics["uncached_prompt_tokens"]
            != self.metrics["prompt_tokens"] - self.metrics["cached_tokens"]
            or abs(
                self.metrics["time_to_first_token_ms"]
                + self.metrics["decode_after_first_token_ms"]
                + self.metrics["generation_residual_ms"]
                - self.metrics["generation_ms"]
            )
            > 2
            or self.metrics["generation_ms"] < 1
            or self.metrics["time_to_first_token_ms"]
            != int(round(1000.0 * self.metrics["prompt_tokens"] / self.metrics["prompt_tps"]))
            or self.metrics["decode_after_first_token_ms"]
            != int(
                round(1000.0 * self.metrics["generation_tokens"] / self.metrics["generation_tps"])
            )
            or abs(
                self.metrics["cache_prepare_ms"]
                + self.metrics["tokenization_ms"]
                + self.metrics["generation_ms"]
                + self.metrics["worker_residual_ms"]
                - self.metrics["worker_request_ms"]
            )
            > 2
            or self.metrics["worker_request_ms"] < 1
            or (
                self.metrics["cache_mode"] == "disabled"
                and (self.metrics["cached_tokens"] != 0 or self.metrics["cache_hit"] is not False)
            )
        ):
            raise BrainError("MODEL_INVALID", 503, "candidate phase telemetry is invalid")
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
