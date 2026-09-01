"""Host-selected progressive views of Brain's runtime grammar authority.

This module is intentionally un-wired.  It never owns a second grammar pin:
every plan is a byte-prefix of the exact v3 projection that
``brain_mlx_runtime`` gives Model 1 today.  The host may advance through a
closed, monotone sequence; model output has no way to select headings, ranges,
or a different reference.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from metis_model1 import brain_mlx_runtime as runtime_reference

REFERENCE_PATH = runtime_reference.REFERENCE_PATH
PINNED_REFERENCE_SHA256 = f"sha256:{runtime_reference.REFERENCE_SHA256}"
MAX_CONTEXT_BYTES = 16 * 1024


class ContextLevel(StrEnum):
    """Ordered views of the single runtime projection."""

    MINIMAL = "minimal"
    ENDPOINT = "endpoint"
    STDLIB = "stdlib"


_LEVEL_ORDER = (ContextLevel.MINIMAL, ContextLevel.ENDPOINT, ContextLevel.STDLIB)
_SECTION_COUNTS = {
    ContextLevel.MINIMAL: 2,
    ContextLevel.ENDPOINT: 5,
    ContextLevel.STDLIB: 6,
}


class ContextPlanError(ValueError):
    """Raised when the runtime authority cannot be projected safely."""


def _runtime_sections() -> tuple[str, tuple[tuple[str, str], ...]]:
    """Return the verified runtime projection and its canonical sections.

    ``_pinned_runtime_reference`` verifies the v3 source hash before returning
    it.  Reconstructing the output from the runtime's own declared headings
    proves that every progressive level is a prefix of that exact projection,
    rather than an independently maintained grammar extract.
    """

    try:
        projection = runtime_reference._pinned_runtime_reference()
        full_reference = runtime_reference._pinned_reference()
        sections = tuple(
            (
                heading,
                runtime_reference._markdown_section(full_reference, heading),
            )
            for heading in runtime_reference._RUNTIME_REFERENCE_SECTIONS
        )
    except runtime_reference.BrainError as error:
        raise ContextPlanError("runtime reference is unavailable or differs") from error

    if (
        not projection
        or any(not section for _, section in sections)
        or "\n\n".join(section for _, section in sections) != projection
    ):
        raise ContextPlanError("runtime reference projection is invalid")
    if len(projection.encode("utf-8")) > MAX_CONTEXT_BYTES:
        raise ContextPlanError("runtime reference projection exceeds its byte bound")
    return projection, sections


@dataclass(frozen=True)
class ContextPlan:
    """An immutable, host-selected prefix of the current runtime authority."""

    level: ContextLevel
    reference_sha256: str
    sections: tuple[str, ...]
    text: str
    byte_count: int

    def expand(self, *, host_signal: str) -> ContextPlan:
        """Advance exactly one view using a closed, host-owned signal."""

        signals = {
            ContextLevel.MINIMAL: "host-needs-endpoint-surface",
            ContextLevel.ENDPOINT: "host-needs-stdlib",
        }
        expected = signals.get(self.level)
        if expected is None or host_signal != expected:
            raise ContextPlanError("context expansion is not the next host-approved level")
        return _make_plan(_LEVEL_ORDER[_LEVEL_ORDER.index(self.level) + 1])


def _make_plan(level: ContextLevel) -> ContextPlan:
    projection, sections = _runtime_sections()
    count = _SECTION_COUNTS.get(level)
    if count is None:  # pragma: no cover - Enum prevents this through the public API.
        raise ContextPlanError("unknown context level")
    chosen = sections[:count]
    text = "\n\n".join(section for _, section in chosen)
    byte_count = len(text.encode("utf-8"))
    if not text or byte_count > MAX_CONTEXT_BYTES or not projection.startswith(text):
        raise ContextPlanError("context plan is not a bounded runtime prefix")
    if level is ContextLevel.STDLIB and text != projection:
        raise ContextPlanError("complete context differs from the runtime projection")
    return ContextPlan(
        level,
        PINNED_REFERENCE_SHA256,
        tuple(heading for heading, _ in chosen),
        text,
        byte_count,
    )


def build_context_plan(
    *,
    needs_endpoint_surface: bool = False,
    needs_stdlib: bool = False,
) -> ContextPlan:
    """Build the smallest plan selected by deterministic host facts only."""

    if type(needs_endpoint_surface) is not bool or type(needs_stdlib) is not bool:
        raise ContextPlanError("context selectors must be host booleans")
    level = (
        ContextLevel.STDLIB
        if needs_stdlib
        else (ContextLevel.ENDPOINT if needs_endpoint_surface else ContextLevel.MINIMAL)
    )
    return _make_plan(level)


def context_plan_payload(plan: ContextPlan) -> dict[str, object]:
    """Return a bounded wire payload with no mutable authority fields."""

    if not isinstance(plan, ContextPlan):
        raise ContextPlanError("plan is invalid")
    return {
        "schema_version": 1,
        "level": plan.level.value,
        "reference_sha256": plan.reference_sha256,
        "sections": list(plan.sections),
        "text": plan.text,
        "byte_count": plan.byte_count,
    }


__all__ = [
    "ContextLevel",
    "ContextPlan",
    "ContextPlanError",
    "MAX_CONTEXT_BYTES",
    "PINNED_REFERENCE_SHA256",
    "REFERENCE_PATH",
    "build_context_plan",
    "context_plan_payload",
]
