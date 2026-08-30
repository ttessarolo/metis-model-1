"""Dependency-injected Model 1 runtime contract used by Brain turns.

The production MLX loader is deliberately not created here: loading or
downloading model payloads is a separate, explicitly authorised wave.  Brain
can nevertheless be exercised end-to-end with a qualified runtime supplied by
the host (and with deterministic test doubles).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Protocol

from metis_model1.brain_protocol import BrainError, bounded_source


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

    def __post_init__(self) -> None:
        bounded_source(self.source)


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
