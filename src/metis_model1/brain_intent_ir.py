"""Strict, non-authoritative Intent IR for Metis Brain's Flash compiler.

The Flash model may segment and paraphrase operator prose so deterministic
retrieval can retry a request that it could not understand directly.  It never
emits catalog, field, value, endpoint or DSL authority.  Every executable
choice remains owned by the admitted request, reviewed retrieval, candidate
grounding and the pinned compiler.
"""

from __future__ import annotations

import json
import math
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from jsonschema import Draft202012Validator

from metis_model1.brain_protocol import BrainError, bytes_sha256, canonical_json

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FLASH_INTENT_SCHEMA_PATH = PROJECT_ROOT / "schemas/metis-brain-flash-intent-ir.schema.json"
MAX_FLASH_CONCEPTS = 12
MAX_FLASH_TEXT = 120
MAX_FLASH_GENERATION_TOKENS = 384
MAX_FLASH_METRIC_COUNT = 1_000_000
MAX_FLASH_METRIC_RATE = 1_000_000.0
MAX_FLASH_PEAK_METAL_GB = 110.0
_OPERATIONS = frozenset({"create", "edit", "repair", "review", "migrate"})
_TARGET_SCOPE = {"create": "new", "existing": "existing"}
_FORBIDDEN_QUERY_SURFACE = re.compile(r"[@{}`\x00\r\n]")
_WORD_RE = re.compile(r"[a-zà-öø-ÿ0-9]+", re.IGNORECASE)
_FUNCTION_WORDS = frozenset(
    {
        "a",
        "al",
        "alla",
        "che",
        "con",
        "da",
        "dei",
        "del",
        "della",
        "di",
        "e",
        "gli",
        "i",
        "il",
        "in",
        "l",
        "la",
        "le",
        "lo",
        "mi",
        "o",
        "per",
        "su",
        "un",
        "una",
        "uno",
        "voglio",
    }
)
_CONTROL_ONLY_WORDS = frozenset(
    {
        "applica",
        "applicare",
        "catalog",
        "catalogo",
        "crea",
        "creare",
        "endpoint",
        "fallback",
        "formato",
        "modifica",
        "modificare",
        "pagina",
        "pagine",
        "paginazione",
        "risposta",
        "risultati",
        "risultato",
    }
)
_FORBIDDEN_CONTROL_WORDS = frozenset(
    {
        "ascending",
        "catalog",
        "catalogo",
        "crescente",
        "decrescente",
        "descending",
        "endpoint",
        "expanded",
        "fallback",
        "formato",
        "mantieni",
        "mantenere",
        "ordina",
        "ordinamento",
        "ordinare",
        "ordine",
        "pagina",
        "pagine",
        "paginazione",
        "response",
        "risposta",
        "risultati",
        "risultato",
        "sort",
        "sorting",
    }
)
_GENERIC_ONLY_WORDS = frozenset({"contenuti", "contenuto", "video"})
_INJECTION_WORDS = frozenset(
    {
        "assistant",
        "developer",
        "dsl",
        "ignora",
        "istruzione",
        "istruzioni",
        "json",
        "prompt",
        "schema",
        "stampa",
        "system",
    }
)
_COUNTED_CONTENT_RE = re.compile(
    r"^\s*(?:circa\s+)?[0-9]+\s+(film|video|contenuti?|titoli?)\s*$",
    re.IGNORECASE,
)
_PROTAGONIST_QUALIFIER_RE = re.compile(
    r"^\s*(?:il\s+|la\s+)?protagonista(?:\s+deve\s+essere)?\s+(.+?)\s*$",
    re.IGNORECASE,
)


def _load_schema() -> dict[str, Any]:
    try:
        raw = FLASH_INTENT_SCHEMA_PATH.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise BrainError(
            "FLASH_SCHEMA_INVALID", 500, "Flash Intent IR schema is unavailable"
        ) from error
    if not isinstance(value, dict):
        raise BrainError("FLASH_SCHEMA_INVALID", 500, "Flash Intent IR schema is invalid")
    try:
        Draft202012Validator.check_schema(value)
    except Exception as error:
        raise BrainError(
            "FLASH_SCHEMA_INVALID", 500, "Flash Intent IR schema is invalid"
        ) from error
    return value


FLASH_INTENT_SCHEMA = _load_schema()
FLASH_INTENT_SCHEMA_SHA256 = bytes_sha256(canonical_json(FLASH_INTENT_SCHEMA))
_FLASH_VALIDATOR = Draft202012Validator(FLASH_INTENT_SCHEMA)


def _invalid(message: str = "Flash Intent IR is invalid") -> BrainError:
    return BrainError("FLASH_INTENT_INVALID", 502, message)


def validate_intent_ir_schema(value: Any) -> None:
    """Validate only the closed JSON shape, before request-bound semantics."""

    if not isinstance(value, dict):
        raise _invalid()
    errors = sorted(_FLASH_VALIDATOR.iter_errors(value), key=lambda item: list(item.path))
    if errors:
        raise _invalid()


def validate_intent_metrics(metrics: Any) -> None:
    """Validate the complete worker telemetry envelope independently of IR semantics."""

    required = {
        "worker_load_ms",
        "generation_ms",
        "prompt_tokens",
        "generation_tokens",
        "prompt_tps",
        "generation_tps",
        "finish_reason",
        "peak_metal_gb",
    }
    if not isinstance(metrics, dict) or set(metrics) != required:
        raise _invalid("Flash telemetry is invalid")
    for key in ("worker_load_ms", "generation_ms", "prompt_tokens", "generation_tokens"):
        item = metrics[key]
        if type(item) is not int or not 0 <= item <= MAX_FLASH_METRIC_COUNT:
            raise _invalid("Flash telemetry is invalid")
    if not 1 <= metrics["generation_tokens"] <= MAX_FLASH_GENERATION_TOKENS:
        raise _invalid("Flash generation length is invalid")
    for key in ("prompt_tps", "generation_tps"):
        item = metrics[key]
        if (
            type(item) not in (int, float)
            or not math.isfinite(float(item))
            or not 0 <= float(item) <= MAX_FLASH_METRIC_RATE
        ):
            raise _invalid("Flash telemetry is invalid")
    peak = metrics["peak_metal_gb"]
    if (
        type(peak) not in (int, float)
        or not math.isfinite(float(peak))
        or not 0 <= float(peak) <= MAX_FLASH_PEAK_METAL_GB
    ):
        raise _invalid("Flash telemetry is invalid")
    if metrics["finish_reason"] != "stop":
        raise _invalid("Flash generation did not complete its constrained object")


def _admissible_operator_span(value: str) -> bool:
    """Reject control prose before an exact span can influence retrieval.

    This is deliberately lexical and conservative.  Flash is an optional
    recall aid, so a false negative merely preserves the original fail-closed
    retrieval result; accepting prompt-control or UX scaffolding would be a
    semantic authority inversion.
    """

    words = [item.casefold() for item in _WORD_RE.findall(value)]
    if not words or any(
        item in _INJECTION_WORDS or item in _FORBIDDEN_CONTROL_WORDS for item in words
    ):
        return False
    meaningful = {item for item in words if item not in _FUNCTION_WORDS}
    return (
        bool(meaningful)
        and not meaningful.issubset(_CONTROL_ONLY_WORDS)
        and not meaningful.issubset(_GENERIC_ONLY_WORDS)
    )


def _executable_operator_span(value: str) -> str | None:
    """Return a safe exact subspan without inventing a new concept.

    Count scaffolding and the generic ``protagonista`` role head carry no
    independent filter semantics.  Removing them keeps only text that already
    occurs contiguously in the operator request; reviewed retrieval still owns
    every field and value decision and may clarify or reject the remainder.
    """

    stripped = value.strip()
    counted = _COUNTED_CONTENT_RE.fullmatch(stripped)
    if counted is not None:
        stripped = counted.group(1)
    protagonist = _PROTAGONIST_QUALIFIER_RE.fullmatch(stripped)
    if protagonist is not None:
        stripped = protagonist.group(1)
    return stripped if _admissible_operator_span(stripped) else None


def strict_json_object(raw: str | bytes) -> dict[str, Any]:
    """Decode one JSON object while rejecting duplicate members and constants."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in items:
            if key in value:
                raise ValueError("duplicate JSON member")
            value[key] = item
        return value

    try:
        value = json.loads(
            raw,
            object_pairs_hook=pairs,
            parse_constant=lambda item: (_ for _ in ()).throw(ValueError(item)),
        )
    except (UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise _invalid() from error
    if not isinstance(value, dict):
        raise _invalid()
    return value


@dataclass(frozen=True)
class IntentCompileRequest:
    instruction: str
    intent: str
    target_mode: str
    cancellation: threading.Event | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.instruction, str)
            or not self.instruction.strip()
            or len(self.instruction.encode("utf-8")) > 512 * 1024
        ):
            raise BrainError("FLASH_INPUT_INVALID", 400, "Flash instruction is invalid")
        if self.intent not in _OPERATIONS:
            raise BrainError("FLASH_INPUT_INVALID", 400, "Flash operation is invalid")
        if self.target_mode not in _TARGET_SCOPE:
            raise BrainError("FLASH_INPUT_INVALID", 400, "Flash target scope is invalid")


@dataclass(frozen=True)
class IntentIR:
    value: dict[str, Any]

    @classmethod
    def parse(cls, value: Any, *, request: IntentCompileRequest) -> IntentIR:
        validate_intent_ir_schema(value)
        assert isinstance(value, dict)
        if value["operation"] != request.intent:
            raise _invalid("Flash operation differs from the admitted request")
        expected_scope = _TARGET_SCOPE[request.target_mode]
        if value["target_scope"] != expected_scope:
            raise _invalid("Flash target scope differs from the admitted request")
        ambiguities = value["ambiguities"]
        if len(ambiguities) != len(set(ambiguities)):
            raise _invalid("Flash ambiguities are duplicated")
        seen: set[tuple[str, str, str]] = set()
        for item in value["concepts"]:
            source = item["source"]
            query = item["query"]
            polarity = item["polarity"]
            if source not in request.instruction:
                raise _invalid("Flash concept is not an exact operator span")
            if _FORBIDDEN_QUERY_SURFACE.search(source) or _FORBIDDEN_QUERY_SURFACE.search(query):
                raise _invalid("Flash concept contains an authority-bearing surface")
            if not _admissible_operator_span(source):
                raise _invalid("Flash concept is operator scaffolding")
            identity = (source.casefold(), query.casefold(), polarity)
            if identity in seen:
                raise _invalid("Flash concepts are duplicated")
            seen.add(identity)
        return cls(json.loads(canonical_json(value)))

    @property
    def exact_semantic_instruction(self) -> str | None:
        """Return only exact operator spans; generated paraphrases are never authority."""

        # The current deterministic grounding/renderer contract is conjunctive.
        # Cross-concept OR must remain unsupported until it has a first-class
        # retrieval and DSL representation; silently turning it into AND would
        # change the operator's request.
        if self.value["concept_logic"] != "all":
            return None
        if any(item["polarity"] != "include" for item in self.value["concepts"]):
            return None
        sources = [_executable_operator_span(item["source"]) for item in self.value["concepts"]]
        sources = [item for item in sources if item is not None]
        if not sources:
            return None
        # Commas are an existing deterministic clause boundary in schema-2
        # retrieval.  The model cannot choose or alter this executable join.
        return ", ".join(sources)

    @property
    def expansion_queries(self) -> tuple[str, ...]:
        """Return bounded, advisory retrieval expansions for later candidate recall."""

        return tuple(item["query"] for item in self.value["concepts"])

    def payload(self) -> dict[str, Any]:
        return json.loads(canonical_json(self.value))


@dataclass(frozen=True)
class IntentCompileResult:
    intent_ir: IntentIR
    model_revision: str
    schema_sha256: str
    decoder: str
    metrics: dict[str, int | float | str]

    def __post_init__(self) -> None:
        if not isinstance(self.model_revision, str) or not self.model_revision:
            raise _invalid("Flash model identity is invalid")
        if self.schema_sha256 != FLASH_INTENT_SCHEMA_SHA256:
            raise _invalid("Flash schema identity differs")
        if self.decoder != "llguidance-1.8.0":
            raise _invalid("Flash constrained decoder is invalid")
        validate_intent_metrics(self.metrics)


class BrainIntentCompiler(Protocol):
    @property
    def model_loaded(self) -> bool: ...

    @property
    def model_revision(self) -> str: ...

    @property
    def schema_sha256(self) -> str: ...

    @property
    def decoder(self) -> str: ...

    def compile(self, request: IntentCompileRequest) -> IntentCompileResult: ...


class StaticIntentCompiler:
    """Deterministic test double with the same host-side validation boundary."""

    model_loaded = True
    model_revision = "test"
    schema_sha256 = FLASH_INTENT_SCHEMA_SHA256
    decoder = "llguidance-1.8.0"

    def __init__(self, value: dict[str, Any]) -> None:
        self._value = json.loads(canonical_json(value))

    def compile(self, request: IntentCompileRequest) -> IntentCompileResult:
        return IntentCompileResult(
            intent_ir=IntentIR.parse(self._value, request=request),
            model_revision=self.model_revision,
            schema_sha256=self.schema_sha256,
            decoder=self.decoder,
            metrics={
                "worker_load_ms": 0,
                "generation_ms": 1,
                "prompt_tokens": 1,
                "generation_tokens": 1,
                "prompt_tps": 1.0,
                "generation_tps": 1.0,
                "finish_reason": "stop",
                "peak_metal_gb": 0.0,
            },
        )


__all__ = [
    "BrainIntentCompiler",
    "FLASH_INTENT_SCHEMA",
    "FLASH_INTENT_SCHEMA_PATH",
    "FLASH_INTENT_SCHEMA_SHA256",
    "IntentCompileRequest",
    "IntentCompileResult",
    "IntentIR",
    "MAX_FLASH_GENERATION_TOKENS",
    "StaticIntentCompiler",
    "strict_json_object",
    "validate_intent_ir_schema",
    "validate_intent_metrics",
]
