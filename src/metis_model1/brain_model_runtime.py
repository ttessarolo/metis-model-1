"""Dependency-injected Model 1 runtime contract used by Brain turns.

The production MLX loader is deliberately not created here: loading or
downloading model payloads is a separate, explicitly authorised wave.  Brain
can nevertheless be exercised end-to-end with a qualified runtime supplied by
the host (and with deterministic test doubles).
"""

from __future__ import annotations

import math
import re
import threading
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Protocol

from metis_model1.brain_create_plan import validate_create_delta_plan_shape
from metis_model1.brain_create_plan_v2 import (
    MAX_REQUIREMENT_HANDLES,
    CompactAuthorityProjection,
    validate_create_delta_plan_v2_body_shape,
)
from metis_model1.brain_protocol import BrainError, bounded_source, canonical_json

MAX_GENERATION_TOKENS = 512
MAX_TELEMETRY_COUNT = 1_000_000
MAX_TELEMETRY_RATE = 1_000_000.0
MAX_PEAK_METAL_GB = 110.0
MAX_CREATE_PLAN_MESSAGES = 20
MAX_CREATE_PLAN_MESSAGE_BYTES = 64 * 1024
MAX_CREATE_PLAN_SURFACE_BYTES = 256 * 1024
MAX_CREATE_PLAN_REQUIREMENTS = 64
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_HOST_REF_RE = re.compile(r"^hostref:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_FORBIDDEN_CREATE_SURFACE_KEYS = frozenset(
    {
        "endpoint_template",
        "golden",
        "path",
        "previous_source",
        "raw_source",
        "reference_endpoint",
        "source",
        "source_path",
        "template",
    }
)


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
        if self.generator not in {
            "model",
            "model_create_plan_v2",
            "grounded_renderer",
            "lossless_renderer",
        }:
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


def _forbidden_create_surface_key(value: Any) -> str | None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).casefold().replace("-", "_")
            if normalized in _FORBIDDEN_CREATE_SURFACE_KEYS:
                return str(key)
            found = _forbidden_create_surface_key(nested)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _forbidden_create_surface_key(nested)
            if found is not None:
                return found
    return None


@dataclass(frozen=True)
class CreatePlanRequest:
    """Tenant-path-free model request for a compact typed CREATE plan."""

    instructions: tuple[str, ...]
    generation: int
    context_revision: str
    semantic_revision: str
    surface_revision: str
    target_ref: str
    basis_ref: str | None
    requirement_refs: tuple[str, ...]
    authority_surface: dict[str, Any]
    cancellation: threading.Event | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            type(self.instructions) is not tuple
            or not 1 <= len(self.instructions) <= MAX_CREATE_PLAN_MESSAGES
            or any(
                not isinstance(item, str)
                or not item.strip()
                or len(item.encode("utf-8")) > MAX_CREATE_PLAN_MESSAGE_BYTES
                for item in self.instructions
            )
        ):
            raise BrainError("MODEL_INPUT_INVALID", 400, "CREATE instruction history is invalid")
        if type(self.generation) is not int or not 0 <= self.generation <= MAX_CREATE_PLAN_MESSAGES:
            raise BrainError("MODEL_INPUT_INVALID", 400, "CREATE generation is invalid")
        for revision in (
            self.context_revision,
            self.semantic_revision,
            self.surface_revision,
        ):
            if not isinstance(revision, str) or _SHA256_RE.fullmatch(revision) is None:
                raise BrainError("MODEL_INPUT_INVALID", 400, "CREATE revision is invalid")
        if not isinstance(self.target_ref, str) or _HOST_REF_RE.fullmatch(self.target_ref) is None:
            raise BrainError("MODEL_INPUT_INVALID", 400, "CREATE target reference is invalid")
        if self.basis_ref is not None and (
            not isinstance(self.basis_ref, str) or _HOST_REF_RE.fullmatch(self.basis_ref) is None
        ):
            raise BrainError("MODEL_INPUT_INVALID", 400, "CREATE basis reference is invalid")
        if (self.generation == 0) != (self.basis_ref is None):
            raise BrainError("MODEL_INPUT_INVALID", 400, "CREATE basis and generation differ")
        if (
            type(self.requirement_refs) is not tuple
            or not 1 <= len(self.requirement_refs) <= MAX_CREATE_PLAN_REQUIREMENTS
            or len(self.requirement_refs) != len(set(self.requirement_refs))
            or any(
                not isinstance(ref, str) or _HOST_REF_RE.fullmatch(ref) is None
                for ref in self.requirement_refs
            )
        ):
            raise BrainError("MODEL_INPUT_INVALID", 400, "CREATE requirement roster is invalid")
        if not isinstance(self.authority_surface, dict):
            raise BrainError("MODEL_INPUT_INVALID", 400, "CREATE authority surface is invalid")
        if _forbidden_create_surface_key(self.authority_surface) is not None:
            raise BrainError(
                "MODEL_INPUT_INVALID",
                400,
                "CREATE authority surface contains forbidden source authority",
            )
        try:
            surface_bytes = canonical_json(self.authority_surface)
        except BrainError as error:
            raise BrainError(
                "MODEL_INPUT_INVALID", 400, "CREATE authority surface is invalid"
            ) from error
        if not surface_bytes or len(surface_bytes) > MAX_CREATE_PLAN_SURFACE_BYTES:
            raise BrainError(
                "MODEL_INPUT_TOO_LARGE", 413, "CREATE authority surface exceeds its bound"
            )
        object.__setattr__(self, "authority_surface", deepcopy(self.authority_surface))


@dataclass(frozen=True)
class CreatePlanCandidate:
    """Untrusted schema-constrained plan returned by a local model worker."""

    plan: dict[str, Any]
    model_revision: str = "unavailable"
    adapter_sha256: str = "unavailable"
    generator: str = "model_create_plan"
    metrics: dict[str, int | float | str | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.plan, dict) or self.generator != "model_create_plan":
            raise BrainError("MODEL_INVALID", 503, "CREATE plan candidate is invalid")
        try:
            raw = canonical_json(self.plan)
        except BrainError as error:
            raise BrainError("MODEL_INVALID", 503, "CREATE plan candidate is invalid") from error
        if not raw or len(raw) > 64 * 1024:
            raise BrainError("MODEL_INVALID", 503, "CREATE plan candidate exceeds its bound")
        if validate_create_delta_plan_shape(self.plan):
            raise BrainError("MODEL_INVALID", 503, "CREATE plan candidate schema is invalid")
        if self.metrics:
            # Reuse the already qualified telemetry contract without creating a
            # second, subtly divergent metric validator.
            ModelCandidate("metis 0.43\n", metrics=dict(self.metrics))
        object.__setattr__(self, "plan", deepcopy(self.plan))
        object.__setattr__(self, "metrics", dict(self.metrics))


@dataclass(frozen=True)
class CreatePlanV2Request:
    """Model-safe request for a compact, handle-only CREATE v2 body."""

    instructions: tuple[str, ...]
    generation: int
    context_revision: str
    semantic_revision: str
    active_requirement_handles: tuple[int, ...]
    authority_projection: CompactAuthorityProjection
    cancellation: threading.Event | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            type(self.instructions) is not tuple
            or not 1 <= len(self.instructions) <= MAX_CREATE_PLAN_MESSAGES
            or any(
                not isinstance(item, str)
                or not item.strip()
                or len(item.encode("utf-8")) > MAX_CREATE_PLAN_MESSAGE_BYTES
                for item in self.instructions
            )
        ):
            raise BrainError("MODEL_INPUT_INVALID", 400, "CREATE v2 instruction history is invalid")
        if type(self.generation) is not int or not 0 <= self.generation <= MAX_CREATE_PLAN_MESSAGES:
            raise BrainError("MODEL_INPUT_INVALID", 400, "CREATE v2 generation is invalid")
        for revision in (self.context_revision, self.semantic_revision):
            if not isinstance(revision, str) or _SHA256_RE.fullmatch(revision) is None:
                raise BrainError("MODEL_INPUT_INVALID", 400, "CREATE v2 revision is invalid")
        if (
            type(self.active_requirement_handles) is not tuple
            or not 1 <= len(self.active_requirement_handles) <= MAX_CREATE_PLAN_REQUIREMENTS
            or len(self.active_requirement_handles) != len(set(self.active_requirement_handles))
            or any(
                type(handle) is not int or not 0 <= handle < MAX_REQUIREMENT_HANDLES
                for handle in self.active_requirement_handles
            )
        ):
            raise BrainError(
                "MODEL_INPUT_INVALID", 400, "CREATE v2 active requirement roster is invalid"
            )
        if type(self.authority_projection) is not CompactAuthorityProjection:
            raise BrainError(
                "MODEL_INPUT_INVALID", 400, "CREATE v2 authority projection is invalid"
            )
        projection = deepcopy(self.authority_projection)
        try:
            payload = projection.model_projection_payload()
            projection_bytes = canonical_json(payload)
        except BrainError as error:
            raise BrainError(
                "MODEL_INPUT_INVALID", 400, "CREATE v2 authority projection is invalid"
            ) from error
        known_requirements = {
            item["h"] for item in payload.get("q", []) if isinstance(item, dict) and "h" in item
        }
        if any(handle not in known_requirements for handle in self.active_requirement_handles):
            raise BrainError(
                "MODEL_INPUT_INVALID",
                400,
                "CREATE v2 active requirement is absent from the projection",
            )
        if not projection_bytes or len(projection_bytes) > MAX_CREATE_PLAN_SURFACE_BYTES:
            raise BrainError(
                "MODEL_INPUT_TOO_LARGE", 413, "CREATE v2 authority projection exceeds its bound"
            )
        object.__setattr__(self, "authority_projection", projection)


@dataclass(frozen=True)
class CreatePlanV2Candidate:
    """Untrusted compact v2 body returned by the constrained local worker."""

    body: dict[str, Any]
    model_revision: str = "unavailable"
    adapter_sha256: str = "unavailable"
    generator: str = "model_create_plan_v2"
    metrics: dict[str, int | float | str | bool] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.body, dict) or self.generator != "model_create_plan_v2":
            raise BrainError("MODEL_INVALID", 503, "CREATE v2 candidate is invalid")
        if validate_create_delta_plan_v2_body_shape(self.body):
            raise BrainError("MODEL_INVALID", 503, "CREATE v2 candidate schema is invalid")
        if self.metrics:
            ModelCandidate("metis 0.43\n", metrics=dict(self.metrics))
        object.__setattr__(self, "body", deepcopy(self.body))
        object.__setattr__(self, "metrics", dict(self.metrics))


class BrainModelRuntime(Protocol):
    """The smallest runtime surface Brain needs for generation and repair."""

    @property
    def model_loaded(self) -> bool: ...

    @property
    def model_revision(self) -> str: ...

    @property
    def adapter_sha256(self) -> str: ...

    def generate(self, request: ModelRequest) -> ModelCandidate: ...

    def plan_create(self, request: CreatePlanRequest) -> CreatePlanCandidate: ...

    def plan_create_v2(self, request: CreatePlanV2Request) -> CreatePlanV2Candidate: ...


class UnavailableModelRuntime:
    """Safe default until the separately qualified MLX runtime is wired in."""

    model_loaded = False
    model_revision = "unavailable"
    adapter_sha256 = "unavailable"

    def generate(self, _request: ModelRequest) -> ModelCandidate:
        raise BrainError("MODEL_UNAVAILABLE", 503, "local Model 1 runtime is unavailable")

    def plan_create(self, _request: CreatePlanRequest) -> CreatePlanCandidate:
        raise BrainError("MODEL_UNAVAILABLE", 503, "local Model 1 runtime is unavailable")

    def plan_create_v2(self, _request: CreatePlanV2Request) -> CreatePlanV2Candidate:
        raise BrainError("MODEL_UNAVAILABLE", 503, "local Model 1 runtime is unavailable")


class StaticModelRuntime:
    """Small host/test adapter; it never reads tenant files or model payloads."""

    def __init__(
        self,
        source: str,
        *,
        model_revision: str = "test",
        adapter_sha256: str = "test",
        create_plan: dict[str, Any] | None = None,
        create_plan_v2: dict[str, Any] | None = None,
    ) -> None:
        self._candidate = ModelCandidate(source, model_revision, adapter_sha256)
        self._create_candidate = (
            None
            if create_plan is None
            else CreatePlanCandidate(
                create_plan,
                model_revision=model_revision,
                adapter_sha256=adapter_sha256,
            )
        )
        self._create_v2_candidate = (
            None
            if create_plan_v2 is None
            else CreatePlanV2Candidate(
                create_plan_v2,
                model_revision=model_revision,
                adapter_sha256=adapter_sha256,
            )
        )

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

    def plan_create(self, _request: CreatePlanRequest) -> CreatePlanCandidate:
        if self._create_candidate is None:
            raise BrainError("MODEL_UNAVAILABLE", 503, "local CREATE planner is unavailable")
        return self._create_candidate

    def plan_create_v2(self, _request: CreatePlanV2Request) -> CreatePlanV2Candidate:
        if self._create_v2_candidate is None:
            raise BrainError("MODEL_UNAVAILABLE", 503, "local CREATE v2 planner is unavailable")
        return self._create_v2_candidate
