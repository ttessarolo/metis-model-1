from __future__ import annotations

import json
import math

import pytest

from metis_model1.brain_intent_ir import (
    FLASH_INTENT_SCHEMA_SHA256,
    IntentCompileRequest,
    IntentCompileResult,
    IntentIR,
    StaticIntentCompiler,
    strict_json_object,
)
from metis_model1.brain_protocol import BrainError


def _request(
    instruction: str = "crea un endpoint per film italiani",
    *,
    intent: str = "create",
    target_mode: str = "create",
) -> IntentCompileRequest:
    return IntentCompileRequest(
        instruction=instruction,
        intent=intent,
        target_mode=target_mode,
    )


def _concept(source: str, query: str | None = None, *, polarity: str = "include") -> dict[str, str]:
    return {
        "source": source,
        "query": query or source,
        "polarity": polarity,
    }


def _value(
    *,
    operation: str = "create",
    target_scope: str = "new",
    concept_logic: str = "all",
    concepts: list[dict[str, str]] | None = None,
    response_format: str = "unspecified",
    fallback: str = "unspecified",
    ambiguities: list[str] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "operation": operation,
        "target_scope": target_scope,
        "concept_logic": concept_logic,
        "concepts": concepts
        if concepts is not None
        else [_concept("film italiani", "film prodotti in Italia")],
        "response_format": response_format,
        "fallback": fallback,
        "ambiguities": ambiguities if ambiguities is not None else [],
    }


def _parse(value: dict[str, object], request: IntentCompileRequest | None = None) -> IntentIR:
    return IntentIR.parse(value, request=request or _request())


def _assert_brain_error(code: str, callback: object) -> None:
    with pytest.raises(BrainError) as caught:
        callback()  # type: ignore[operator]
    assert caught.value.code == code


def _metrics(**overrides: int | float | str) -> dict[str, int | float | str]:
    result: dict[str, int | float | str] = {
        "worker_load_ms": 10,
        "generation_ms": 20,
        "prompt_tokens": 30,
        "generation_tokens": 8,
        "prompt_tps": 100.0,
        "generation_tps": 80.0,
        "finish_reason": "stop",
        "peak_metal_gb": 4.5,
    }
    result.update(overrides)
    return result


def test_strict_json_object_accepts_object_and_rejects_duplicate_members() -> None:
    assert strict_json_object('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}
    _assert_brain_error("FLASH_INTENT_INVALID", lambda: strict_json_object('{"a":1,"a":2}'))


@pytest.mark.parametrize(
    "raw",
    [b"[]", b"null", b"", b"{", b'{"a": NaN}', b'{"a": Infinity}', b'"text"'],
)
def test_strict_json_object_rejects_non_objects_malformed_and_non_json_numbers(raw: bytes) -> None:
    _assert_brain_error("FLASH_INTENT_INVALID", lambda: strict_json_object(raw))


@pytest.mark.parametrize(
    ("instruction", "intent", "target_mode"),
    [
        ("   ", "create", "create"),
        ("x" * (512 * 1024 + 1), "create", "create"),
        ("crea film", "unknown", "create"),
        ("crea film", "create", "invalid"),
    ],
    ids=(
        "blank-instruction",
        "oversized-instruction",
        "unknown-intent",
        "invalid-target-mode",
    ),
)
def test_intent_compile_request_rejects_invalid_admitted_request(
    instruction: str, intent: str, target_mode: str
) -> None:
    _assert_brain_error(
        "FLASH_INPUT_INVALID",
        lambda: _request(instruction, intent=intent, target_mode=target_mode),
    )


def test_intent_ir_parses_valid_request_and_preserves_only_canonical_payload() -> None:
    request = _request()
    parsed = _parse(_value(), request)
    assert parsed.payload() == _value()
    assert parsed.exact_semantic_instruction == "film italiani"
    assert parsed.expansion_queries == ("film prodotti in Italia",)


def test_only_conjunctive_logic_has_executable_deterministic_semantics() -> None:
    request = _request("crea film italiani premiati")
    all_ir = _parse(
        _value(
            concepts=[_concept("film italiani"), _concept("premiati")],
            concept_logic="all",
        ),
        request,
    )
    any_ir = _parse(
        _value(
            concepts=[_concept("film italiani"), _concept("premiati")],
            concept_logic="any",
        ),
        request,
    )
    assert all_ir.exact_semantic_instruction == "film italiani, premiati"
    assert any_ir.exact_semantic_instruction is None


def test_count_prefix_is_removed_without_losing_exact_content_span() -> None:
    request = _request("crea 24 film premiati")
    parsed = _parse(
        _value(concepts=[_concept("24 film"), _concept("premiati")]),
        request,
    )

    assert parsed.exact_semantic_instruction == "film, premiati"


def test_generic_protagonist_heads_are_removed_without_inventing_value_text() -> None:
    instruction = "crea 24 film con protagonista femminile e protagonista umano"
    parsed = _parse(
        _value(
            concepts=[
                _concept("24 film"),
                _concept("protagonista femminile"),
                _concept("protagonista umano"),
            ]
        ),
        _request(instruction),
    )

    assert parsed.exact_semantic_instruction == "film, femminile, umano"


@pytest.mark.parametrize("logic", ["mixed", "unknown"])
def test_mixed_and_unknown_logic_fail_closed_before_retrieval(logic: str) -> None:
    parsed = _parse(_value(concept_logic=logic))
    assert parsed.exact_semantic_instruction is None


def test_excluded_concept_fails_closed_before_retrieval() -> None:
    parsed = _parse(_value(concepts=[_concept("film italiani", polarity="exclude")]))
    assert parsed.exact_semantic_instruction is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("operation", "edit"),
        ("target_scope", "existing"),
    ],
)
def test_ir_cannot_change_admitted_operation_or_target_scope(field: str, value: str) -> None:
    payload = _value()
    payload[field] = value
    _assert_brain_error("FLASH_INTENT_INVALID", lambda: _parse(payload))


@pytest.mark.parametrize(
    "key",
    [
        "catalog",
        "field",
        "value",
        "literal",
        "endpoint",
        "dsl",
        "session",
        "revision",
        "confidence",
        "fast_path",
        "path",
        "tenant",
    ],
)
def test_ir_closed_schema_rejects_authority_and_runtime_injection_keys(key: str) -> None:
    payload = _value()
    payload[key] = "attacker-controlled"
    _assert_brain_error("FLASH_INTENT_INVALID", lambda: _parse(payload))


@pytest.mark.parametrize(
    "source",
    [
        "l'endpoint",
        "endpoint",
        "catalogo video",
        "video",
        "fallback",
        "24 risultati",
        "mantieni response.expanded",
        "ordinamento per data di pubblicazione",
    ],
)
def test_exact_span_gate_rejects_ux_scaffolding(source: str) -> None:
    instruction = (
        "crea l'endpoint video con fallback e 24 risultati; "
        "mantieni response.expanded e l'ordinamento per data di pubblicazione"
    )
    request = _request(instruction)
    payload = _value(concepts=[_concept(source)])
    _assert_brain_error("FLASH_INTENT_INVALID", lambda: _parse(payload, request))


@pytest.mark.parametrize("source", ["ignora istruzioni", "system prompt", "stampa il json"])
def test_exact_span_gate_rejects_prompt_injection_words(source: str) -> None:
    instruction = f"crea un endpoint per {source}"
    _assert_brain_error(
        "FLASH_INTENT_INVALID",
        lambda: _parse(_value(concepts=[_concept(source)]), _request(instruction)),
    )


@pytest.mark.parametrize(
    "source", ["non presente", "film @video", "film {italiani}", "film\nitaliani"]
)
def test_exact_span_gate_requires_safe_exact_source_substring(source: str) -> None:
    request = _request("crea un endpoint per film italiani")
    _assert_brain_error(
        "FLASH_INTENT_INVALID",
        lambda: _parse(_value(concepts=[_concept(source)]), request),
    )


def test_query_is_advisory_but_still_rejects_authority_surface() -> None:
    payload = _value(concepts=[_concept("film italiani", "@video")])
    _assert_brain_error("FLASH_INTENT_INVALID", lambda: _parse(payload))


def test_duplicate_concepts_and_ambiguities_are_rejected() -> None:
    duplicate_concepts = _value(concepts=[_concept("film italiani"), _concept("film italiani")])
    _assert_brain_error("FLASH_INTENT_INVALID", lambda: _parse(duplicate_concepts))
    duplicate_ambiguities = _value(ambiguities=["semantic", "semantic"])
    _assert_brain_error("FLASH_INTENT_INVALID", lambda: _parse(duplicate_ambiguities))


def test_concept_and_ambiguity_bounds_are_enforced_by_schema() -> None:
    instruction = "crea " + " ".join(f"concetto{i}" for i in range(13))
    concepts = [_concept(f"concetto{i}") for i in range(13)]
    _assert_brain_error(
        "FLASH_INTENT_INVALID",
        lambda: _parse(_value(concepts=concepts), _request(instruction)),
    )
    _assert_brain_error(
        "FLASH_INTENT_INVALID",
        lambda: _parse(
            _value(
                ambiguities=[
                    "catalog",
                    "semantic",
                    "target",
                    "format",
                    "fallback",
                    "catalog",
                    "semantic",
                    "target",
                    "format",
                ]
            )
        ),
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"schema_version": 2},
        {"schema_version": 1, "operation": "create"},
        _value(concepts=[_concept("")]),
        _value(concepts=[_concept("film italiani", "x" * 121)]),
        _value(response_format="json"),
        _value(ambiguities=["unknown"]),
    ],
)
def test_ir_rejects_missing_wrong_enum_and_oversized_members(payload: dict[str, object]) -> None:
    _assert_brain_error("FLASH_INTENT_INVALID", lambda: _parse(payload))


def test_intent_compile_result_accepts_qualified_telemetry() -> None:
    result = IntentCompileResult(
        intent_ir=_parse(_value()),
        model_revision="475b9088d29754a3379866cf5aeb6b41acd313c2",
        schema_sha256=FLASH_INTENT_SCHEMA_SHA256,
        decoder="llguidance-1.8.0",
        metrics=_metrics(),
    )
    assert result.intent_ir.exact_semantic_instruction == "film italiani"


@pytest.mark.parametrize(
    "overrides",
    [
        {"worker_load_ms": -1},
        {"generation_ms": 1_000_001},
        {"prompt_tokens": 1.5},
        {"generation_tokens": 0},
        {"generation_tokens": 385},
        {"prompt_tps": -1.0},
        {"generation_tps": math.nan},
        {"peak_metal_gb": 111.0},
        {"finish_reason": "length"},
    ],
)
def test_intent_compile_result_rejects_invalid_telemetry(overrides: dict[str, object]) -> None:
    _assert_brain_error(
        "FLASH_INTENT_INVALID",
        lambda: IntentCompileResult(
            intent_ir=_parse(_value()),
            model_revision="model",
            schema_sha256=FLASH_INTENT_SCHEMA_SHA256,
            decoder="llguidance-1.8.0",
            metrics=_metrics(**overrides),  # type: ignore[arg-type]
        ),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [("model_revision", ""), ("schema_sha256", "sha256:" + "0" * 64), ("decoder", "json")],
)
def test_intent_compile_result_rejects_wrong_identity(field: str, value: str) -> None:
    kwargs: dict[str, object] = {
        "intent_ir": _parse(_value()),
        "model_revision": "model",
        "schema_sha256": FLASH_INTENT_SCHEMA_SHA256,
        "decoder": "llguidance-1.8.0",
        "metrics": _metrics(),
    }
    kwargs[field] = value
    _assert_brain_error("FLASH_INTENT_INVALID", lambda: IntentCompileResult(**kwargs))  # type: ignore[arg-type]


def test_intent_compile_result_requires_exact_telemetry_roster() -> None:
    metrics = _metrics()
    del metrics["generation_tps"]
    _assert_brain_error(
        "FLASH_INTENT_INVALID",
        lambda: IntentCompileResult(
            intent_ir=_parse(_value()),
            model_revision="model",
            schema_sha256=FLASH_INTENT_SCHEMA_SHA256,
            decoder="llguidance-1.8.0",
            metrics=metrics,
        ),
    )


def test_static_intent_compiler_obeys_same_host_validation_contract() -> None:
    compiler = StaticIntentCompiler(_value())
    result = compiler.compile(_request())
    assert compiler.model_loaded is True
    assert compiler.model_revision == "test"
    assert compiler.schema_sha256 == FLASH_INTENT_SCHEMA_SHA256
    assert compiler.decoder == "llguidance-1.8.0"
    assert result.intent_ir.exact_semantic_instruction == "film italiani"
    assert result.metrics["finish_reason"] == "stop"


def test_static_intent_compiler_rejects_invalid_value_instead_of_repairing_it() -> None:
    compiler = StaticIntentCompiler(_value(concepts=[_concept("l'endpoint")]))
    _assert_brain_error(
        "FLASH_INTENT_INVALID", lambda: compiler.compile(_request("crea l'endpoint"))
    )


def test_json_round_trip_does_not_change_ir_or_allow_nan() -> None:
    payload = _value()
    assert json.loads(json.dumps(payload, allow_nan=False)) == payload
