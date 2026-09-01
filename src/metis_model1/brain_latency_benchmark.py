"""Fail-closed receipts for paired Metis Brain latency qualification.

The live harness deliberately stays separate from this pure receipt builder.
Only redacted identities, hashes, bounded timings and terminal gate outcomes are
admitted here; prompts, tenant source, session tokens and generated source never
belong in a benchmark receipt.
"""

from __future__ import annotations

import hashlib
import math
import os
import secrets
import stat
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from metis_model1.brain_candidate_grounding import (
    adjudicate_candidate,
    adjudicate_candidate_shape,
)
from metis_model1.brain_model_runtime import ModelCandidate
from metis_model1.brain_protocol import BrainError, canonical_json, canonical_sha256

ARMS = ("direct", "prefix")
MIN_PROMOTION_PAIRS = 6
MAX_PROMOTION_PAIRS = 32
MAX_LATENCY_MS = 600_000
MAX_EVENTS = 256
_SHA = "sha256:"
_RUNTIME_IDENTITY_KEYS = frozenset(
    {"model_revision", "adapter_sha256", "worker_sha256", "prompt_prefix_sha256"}
)
_TENANT_GUARD_KEYS = frozenset(
    {"commit", "tree", "status_sha256", "roster_sha256", "target_sha256"}
)
_OBSERVATION_KEYS = frozenset(
    {
        "pair",
        "arm",
        "ordinal",
        "request_sha256",
        "model_revision",
        "adapter_sha256",
        "worker_sha256",
        "prompt_prefix_sha256",
        "tenant_commit",
        "tenant_tree",
        "tenant_status_sha256",
        "tenant_roster_sha256",
        "target_sha256",
        "context_revision",
        "semantic_source_revision",
        "toolchain_binding",
        "source_sha256",
        "grounding_selections_sha256",
        "compiler_receipt_sha256",
        "compiled_endpoint_sha256",
        "shape_contract_sha256",
        "intent_compiler_sha256",
        "event_roster_sha256",
        "compile_clean",
        "semantic_grounded",
        "tenant_modified",
        "repair_count",
        "event_count",
        "heartbeat_count",
        "processing_route",
        "turn_ms",
        "retrieval_ms",
        "intent_ms",
        "inference_ms",
        "compile_ms",
        "host_inference_overhead_ms",
        "metrics",
    }
)
_DIRECT_EVENT_ROUTE = (
    "turn.accepted",
    "retrieval.started",
    "retrieval.completed",
    "catalog.auto_selected",
    "inference.started",
    "inference.completed",
    "compile.started",
    "compile.completed",
    "terminal",
)
_FLASH_RETRY_EVENT_ROUTE = (
    "turn.accepted",
    "retrieval.started",
    "retrieval.completed",
    "intent.started",
    "intent.completed",
    "retrieval.started",
    "retrieval.completed",
    "catalog.auto_selected",
    "inference.started",
    "inference.completed",
    "compile.started",
    "compile.completed",
    "terminal",
)
_EVENT_ROUTES = {
    "direct": _DIRECT_EVENT_ROUTE,
    "flash_retry": _FLASH_RETRY_EVENT_ROUTE,
}
_ALLOWED_EVENTS = frozenset(event for route in _EVENT_ROUTES.values() for event in route)
_OPTIONAL_EVENTS = frozenset({"heartbeat"})
_EVENT_DATA_KEYS = frozenset(
    {
        "schema_version",
        "turn_id",
        "sequence",
        "phase",
        "label",
        "attempt",
        "count",
        "bytes",
        "duration_ms",
        "elapsed_ms",
        "replayed",
    }
)


def _hash(value: Any) -> str:
    return canonical_sha256(value)


def _sha(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 71
        or not value.startswith(_SHA)
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise BrainError("BENCHMARK_INVALID", 400, f"{label} is invalid")
    return value


def _bounded_count(value: Any, *, label: str, upper: int = MAX_LATENCY_MS) -> int:
    if type(value) is not int or not 0 <= value <= upper:
        raise BrainError("BENCHMARK_INVALID", 400, f"{label} is invalid")
    return value


def _bounded_positive(value: Any, *, label: str, upper: int = MAX_LATENCY_MS) -> int:
    bounded = _bounded_count(value, label=label, upper=upper)
    if bounded < 1:
        raise BrainError("BENCHMARK_INVALID", 400, f"{label} is invalid")
    return bounded


def _nearest_rank(values: Sequence[int], percentile: float) -> int:
    if not values or not 0 < percentile <= 1:
        raise BrainError("BENCHMARK_INVALID", 400, "percentile input is invalid")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def counterbalanced_schedule_sha256(*, pairs: int, arm_order: Sequence[str]) -> str:
    """Bind the deterministic AB/BA execution schedule used by the live harness."""

    if (
        type(pairs) is not int
        or pairs < 2
        or pairs > MAX_PROMOTION_PAIRS
        or pairs % 2
        or list(arm_order) not in (["direct", "prefix"], ["prefix", "direct"])
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark schedule is invalid")
    first = list(arm_order)
    second = list(reversed(first))
    schedule = [
        {"pair": pair, "order": first if pair % 2 else second} for pair in range(1, pairs + 1)
    ]
    return _hash(schedule)


def _selection_projection(grounding: Mapping[str, Any]) -> list[dict[str, Any]]:
    selections = grounding.get("selections")
    if not isinstance(selections, list) or not selections:
        raise BrainError("BENCHMARK_INVALID", 400, "grounding selections are unavailable")
    projected: list[dict[str, Any]] = []
    for item in selections:
        if not isinstance(item, Mapping):
            raise BrainError("BENCHMARK_INVALID", 400, "grounding selection is invalid")
        value = {
            key: item[key] for key in ("catalog", "field", "literal", "literals") if key in item
        }
        if not isinstance(value.get("catalog"), str) or not isinstance(value.get("field"), str):
            raise BrainError("BENCHMARK_INVALID", 400, "grounding selection is invalid")
        projected.append(value)
    return sorted(
        projected,
        key=lambda item: (
            str(item.get("catalog", "")),
            str(item.get("field", "")),
            canonical_json(item),
        ),
    )


def selection_roster_sha256(selections: Sequence[Mapping[str, Any]]) -> str:
    """Hash the exact catalog/field/literal oracle used by a frozen case."""

    return _hash(_selection_projection({"selections": list(selections)}))


def observation_from_terminal(
    *,
    pair: int,
    arm: str,
    request_sha256: str,
    runtime_identity: Mapping[str, Any],
    tenant_before: Mapping[str, Any],
    tenant_after: Mapping[str, Any],
    terminal: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    turn_ms: int,
    shape_contract: Mapping[str, Any],
    ordinal: int | None = None,
) -> dict[str, Any]:
    """Reduce one terminal response to a redacted benchmark observation."""

    if type(pair) is not int or not 1 <= pair <= MAX_PROMOTION_PAIRS or arm not in ARMS:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark pair/arm is invalid")
    if ordinal is None:
        ordinal = (pair - 1) * len(ARMS) + ARMS.index(arm) + 1
    if type(ordinal) is not int or not 1 <= ordinal <= MAX_PROMOTION_PAIRS * len(ARMS):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark observation ordinal is invalid")
    _sha(request_sha256, label="request hash")
    if set(runtime_identity) != _RUNTIME_IDENTITY_KEYS:
        raise BrainError("BENCHMARK_INVALID", 400, "runtime identity roster is invalid")
    runtime_model_revision = runtime_identity["model_revision"]
    if (
        not isinstance(runtime_model_revision, str)
        or not runtime_model_revision
        or len(runtime_model_revision) > 128
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "runtime model revision is invalid")
    for key in ("adapter_sha256", "worker_sha256", "prompt_prefix_sha256"):
        _sha(runtime_identity[key], label=key)
    if set(tenant_before) != _TENANT_GUARD_KEYS or dict(tenant_before) != dict(tenant_after):
        raise BrainError("BENCHMARK_INVALID", 400, "tenant guard changed during observation")
    for key in ("commit", "tree"):
        value = tenant_before[key]
        if not isinstance(value, str) or not value or len(value) > 128:
            raise BrainError("BENCHMARK_INVALID", 400, "tenant guard identity is invalid")
    for key in ("status_sha256", "roster_sha256", "target_sha256"):
        _sha(tenant_before[key], label=f"tenant {key}")
    if (
        terminal.get("schema_version") != 2
        or terminal.get("status") != "completed"
        or terminal.get("outcome") != "proposed"
        or terminal.get("route") != "local"
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark turn did not produce a proposal")
    terminal_turn_id = terminal.get("turn_id")
    if not isinstance(terminal_turn_id, str) or not terminal_turn_id:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark terminal turn is invalid")
    proposal = terminal.get("proposal")
    identity = terminal.get("identity")
    grounding = terminal.get("grounding")
    validation = terminal.get("validation")
    claims = terminal.get("claims")
    if not all(
        isinstance(value, Mapping) for value in (proposal, identity, grounding, validation, claims)
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark terminal contract is invalid")
    assert isinstance(proposal, Mapping)
    assert isinstance(identity, Mapping)
    assert isinstance(grounding, Mapping)
    assert isinstance(validation, Mapping)
    assert isinstance(claims, Mapping)
    source_sha256 = _sha(proposal.get("source_sha256"), label="proposal source hash")
    source = proposal.get("source")
    if (
        not isinstance(source, str)
        or hashlib.sha256(source.encode("utf-8")).hexdigest() != source_sha256[7:]
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "proposal source hash differs")
    if not adjudicate_candidate(source, grounding).ok:
        raise BrainError("BENCHMARK_INVALID", 400, "proposal failed the grounding oracle")
    take_shape = shape_contract.get("take")
    if (
        set(shape_contract) != {"endpoint", "take", "order_field", "order_direction", "response"}
        or not isinstance(take_shape, Mapping)
        or set(take_shape) != {"mode", "value"}
        or take_shape.get("mode") != "count"
        or type(take_shape.get("value")) is not int
        or not 1 <= take_shape["value"] <= 1_000_000
        or any(
            not isinstance(shape_contract.get(key), str) or not shape_contract[key]
            for key in ("endpoint", "order_field", "order_direction", "response")
        )
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark shape oracle is invalid")
    if not adjudicate_candidate_shape(
        source,
        endpoint=shape_contract["endpoint"],
        take_mode=take_shape["mode"],
        take_value=take_shape["value"],
        order_field=shape_contract["order_field"],
        order_direction=shape_contract["order_direction"],
        response=shape_contract["response"],
    ).ok:
        raise BrainError("BENCHMARK_INVALID", 400, "proposal failed the shape oracle")
    metrics = identity.get("generation_metrics")
    if not isinstance(metrics, dict):
        raise BrainError("BENCHMARK_INVALID", 400, "model phase telemetry is unavailable")
    # Reuse the product's strict telemetry validator. Source bytes are discarded
    # immediately after validation and never copied into the returned receipt.
    ModelCandidate(
        source="metis 0.43\ntenant benchmark_receipt {}\n",
        model_revision=runtime_model_revision,
        adapter_sha256=str(runtime_identity["adapter_sha256"]),
        metrics=dict(metrics),
    )
    if (
        identity.get("model_revision") != runtime_model_revision
        or identity.get("adapter_sha256") != runtime_identity["adapter_sha256"]
        or identity.get("generation_strategy") != "model"
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "runtime identity differs from terminal")
    if metrics.get("cache_mode") != ("disabled" if arm == "direct" else "prefix"):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark cache arm differs")
    if arm == "direct" and (
        metrics.get("cache_hit") is not False or metrics.get("cached_tokens") != 0
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "direct arm reported a cache hit")
    if arm == "prefix" and metrics.get("cache_hit") is not True:
        raise BrainError("BENCHMARK_INVALID", 400, "prefix arm did not report an exact hit")
    if (
        grounding.get("status") != "resolved"
        or grounding.get("candidates") not in (None, [])
        or grounding.get("unresolved") not in (None, [])
        or validation.get("status") != "ok"
        or validation.get("diagnostics") != []
        or validation.get("attempts") != 1
        or claims.get("compile_clean") is not True
        or claims.get("semantic_grounded") is not True
        or claims.get("tenant_modified") is not False
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark semantic/compiler gate failed")
    context_revision = _sha(identity.get("context_revision"), label="observation context revision")
    semantic_revision = _sha(
        identity.get("semantic_source_revision"), label="observation semantic revision"
    )
    toolchain_binding = _sha(
        identity.get("toolchain_binding"), label="observation toolchain binding"
    )
    if not isinstance(events, Sequence) or not 1 <= len(events) <= MAX_EVENTS:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark event roster is invalid")
    sequences: list[int] = []
    event_names: list[str] = []
    durations: dict[str, int] = defaultdict(int)
    heartbeat_count = 0
    repair_count = 0
    for event in events:
        if not isinstance(event, Mapping) or not isinstance(event.get("data"), Mapping):
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark event is invalid")
        data = event["data"]
        if (
            not set(data).issubset(_EVENT_DATA_KEYS)
            or data.get("schema_version") != 1
            or not isinstance(data.get("turn_id"), str)
            or data["turn_id"] != terminal_turn_id
            or not isinstance(data.get("phase"), str)
            or not data["phase"]
            or not isinstance(data.get("label"), str)
            or not data["label"]
        ):
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark event payload is invalid")
        sequence = data.get("sequence")
        if type(sequence) is not int or sequence < 1:
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark event sequence is invalid")
        sequences.append(sequence)
        name = event.get("event")
        if not isinstance(name, str) or name not in _ALLOWED_EVENTS | _OPTIONAL_EVENTS:
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark event roster is invalid")
        event_names.append(name)
        duration = data.get("duration_ms")
        if (
            name
            in {
                "retrieval.completed",
                "intent.completed",
                "inference.completed",
                "compile.completed",
            }
            and duration is None
        ):
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark phase duration is unavailable")
        if duration is not None:
            durations[str(name)] += _bounded_count(duration, label="event duration")
        heartbeat_count += int(name == "heartbeat")
        repair_count += int(name == "repair.completed")
    if sequences != list(range(sequences[0], sequences[0] + len(sequences))):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark event sequence has a gap")
    if sequences[0] != 1:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark event roster is incomplete")
    route_events = tuple(name for name in event_names if name != "heartbeat")
    if not route_events or route_events[0] != "turn.accepted" or route_events[-1] != "terminal":
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark event roster is incomplete")
    matched_routes = [name for name, route in _EVENT_ROUTES.items() if route_events == route]
    if len(matched_routes) != 1:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark event order is invalid")
    processing_route = matched_routes[0]
    intent_identity = identity.get("intent_compiler")
    if processing_route == "flash_retry":
        if (
            not isinstance(intent_identity, Mapping)
            or set(intent_identity) != {"model_revision", "schema_sha256", "decoder"}
            or not isinstance(intent_identity.get("model_revision"), str)
            or not intent_identity["model_revision"]
            or len(intent_identity["model_revision"]) > 256
            or not isinstance(intent_identity.get("decoder"), str)
            or not intent_identity["decoder"]
            or len(intent_identity["decoder"]) > 128
        ):
            raise BrainError("BENCHMARK_INVALID", 400, "intent compiler identity is invalid")
        _sha(intent_identity.get("schema_sha256"), label="intent compiler schema hash")
        normalized_intent_identity: dict[str, Any] | None = dict(intent_identity)
    else:
        if intent_identity is not None:
            raise BrainError("BENCHMARK_INVALID", 400, "unused intent compiler identity leaked")
        normalized_intent_identity = None
    intent_compiler_sha256 = _hash(
        {"processing_route": processing_route, "identity": normalized_intent_identity}
    )
    bounded_turn_ms = _bounded_count(turn_ms, label="turn duration")
    if (
        durations["inference.completed"] < metrics["worker_request_ms"]
        or durations["inference.completed"] < 1
        or bounded_turn_ms
        < durations["retrieval.completed"]
        + durations["intent.completed"]
        + durations["inference.completed"]
        + durations["compile.completed"]
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark phase timing is incoherent")
    return {
        "pair": pair,
        "arm": arm,
        "ordinal": ordinal,
        "request_sha256": request_sha256,
        "model_revision": runtime_model_revision,
        "adapter_sha256": runtime_identity["adapter_sha256"],
        "worker_sha256": runtime_identity["worker_sha256"],
        "prompt_prefix_sha256": runtime_identity["prompt_prefix_sha256"],
        "tenant_commit": tenant_before["commit"],
        "tenant_tree": tenant_before["tree"],
        "tenant_status_sha256": tenant_before["status_sha256"],
        "tenant_roster_sha256": tenant_before["roster_sha256"],
        "target_sha256": tenant_before["target_sha256"],
        "context_revision": context_revision,
        "semantic_source_revision": semantic_revision,
        "toolchain_binding": toolchain_binding,
        "source_sha256": source_sha256,
        "grounding_selections_sha256": _hash(_selection_projection(grounding)),
        "compiler_receipt_sha256": _sha(
            validation.get("compiler_receipt_sha256"), label="compiler receipt hash"
        ),
        "compiled_endpoint_sha256": _sha(
            validation.get("compiled_endpoint_sha256"), label="compiled endpoint hash"
        ),
        "shape_contract_sha256": _hash(dict(shape_contract)),
        "intent_compiler_sha256": intent_compiler_sha256,
        "event_roster_sha256": _hash([name for name in event_names if name != "heartbeat"]),
        "compile_clean": True,
        "semantic_grounded": True,
        "tenant_modified": False,
        "repair_count": repair_count,
        "event_count": len(events),
        "heartbeat_count": heartbeat_count,
        "processing_route": processing_route,
        "turn_ms": bounded_turn_ms,
        "retrieval_ms": durations["retrieval.completed"],
        "intent_ms": durations["intent.completed"],
        "inference_ms": durations["inference.completed"],
        "compile_ms": durations["compile.completed"],
        "host_inference_overhead_ms": (
            durations["inference.completed"] - metrics["worker_request_ms"]
        ),
        "metrics": dict(metrics),
    }


def _validated_observation(item: Mapping[str, Any]) -> dict[str, Any]:
    """Revalidate every admitted field before sealing or replaying a receipt."""

    if set(item) != _OBSERVATION_KEYS:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark observation roster is invalid")
    normalized = dict(item)
    pair = normalized.get("pair")
    arm = normalized.get("arm")
    if type(pair) is not int or not 1 <= pair <= MAX_PROMOTION_PAIRS or arm not in ARMS:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark pair/arm is invalid")
    _bounded_positive(
        normalized.get("ordinal"),
        label="observation ordinal",
        upper=MAX_PROMOTION_PAIRS * len(ARMS),
    )
    for key in (
        "request_sha256",
        "adapter_sha256",
        "worker_sha256",
        "prompt_prefix_sha256",
        "tenant_status_sha256",
        "tenant_roster_sha256",
        "target_sha256",
        "context_revision",
        "semantic_source_revision",
        "toolchain_binding",
        "source_sha256",
        "grounding_selections_sha256",
        "compiler_receipt_sha256",
        "compiled_endpoint_sha256",
        "shape_contract_sha256",
        "intent_compiler_sha256",
        "event_roster_sha256",
    ):
        _sha(normalized.get(key), label=key)
    for key in ("model_revision", "tenant_commit", "tenant_tree"):
        value = normalized.get(key)
        if not isinstance(value, str) or not value or len(value) > 128:
            raise BrainError("BENCHMARK_INVALID", 400, f"{key} is invalid")
    if (
        normalized.get("compile_clean") is not True
        or normalized.get("semantic_grounded") is not True
        or normalized.get("tenant_modified") is not False
        or normalized.get("repair_count") != 0
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark terminal gate regressed")
    event_count = _bounded_positive(
        normalized.get("event_count"), label="event count", upper=MAX_EVENTS
    )
    heartbeat_count = _bounded_count(
        normalized.get("heartbeat_count"), label="heartbeat count", upper=MAX_EVENTS
    )
    processing_route = normalized.get("processing_route")
    if processing_route not in _EVENT_ROUTES:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark processing route is invalid")
    if (
        heartbeat_count > event_count
        or event_count != len(_EVENT_ROUTES[processing_route]) + heartbeat_count
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark event count is incoherent")
    turn_ms = _bounded_positive(normalized.get("turn_ms"), label="turn duration")
    retrieval_ms = _bounded_count(normalized.get("retrieval_ms"), label="retrieval duration")
    intent_ms = _bounded_count(normalized.get("intent_ms"), label="intent duration")
    inference_ms = _bounded_positive(normalized.get("inference_ms"), label="inference duration")
    compile_ms = _bounded_count(normalized.get("compile_ms"), label="compile duration")
    host_overhead_ms = _bounded_count(
        normalized.get("host_inference_overhead_ms"), label="host inference overhead"
    )
    metrics = normalized.get("metrics")
    if not isinstance(metrics, Mapping):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark phase telemetry is invalid")
    candidate = ModelCandidate(
        source="metis 0.43\ntenant benchmark_receipt {}\n",
        model_revision=str(normalized["model_revision"]),
        adapter_sha256=str(normalized["adapter_sha256"]),
        metrics=dict(metrics),
    )
    validated_metrics = dict(candidate.metrics or {})
    worker_request_ms = _bounded_positive(
        validated_metrics.get("worker_request_ms"), label="worker request duration"
    )
    expected_mode = "disabled" if arm == "direct" else "prefix"
    if (
        validated_metrics.get("cache_mode") != expected_mode
        or (arm == "direct" and validated_metrics.get("cache_hit") is not False)
        or (arm == "direct" and validated_metrics.get("cached_tokens") != 0)
        or (arm == "prefix" and validated_metrics.get("cache_hit") is not True)
        or inference_ms < worker_request_ms
        or host_overhead_ms != inference_ms - worker_request_ms
        or (processing_route == "direct" and intent_ms != 0)
        or validated_metrics.get("model_lock_queue_ms", 0) > host_overhead_ms + 2
        or turn_ms < retrieval_ms + intent_ms + inference_ms + compile_ms
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark phase timing/cache is incoherent")
    normalized["metrics"] = validated_metrics
    return normalized


def seal_latency_receipt(
    *, identity: Mapping[str, Any], observations: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Validate a complete paired roster and compute a deterministic verdict."""

    required_identity = {
        "benchmark_id",
        "case_sha256",
        "model1_commit",
        "model1_tree",
        "seed",
        "pairs",
        "arm_order",
        "schedule_sha256",
        "model_revision",
        "adapter_sha256",
        "worker_sha256",
        "prompt_prefix_sha256",
        "expected_prefix_tokens",
        "retrieval_prewarm_ms",
        "decode_preflight_count",
        "decode_preflights",
        "decode_preflight_sha256",
        "decode_preflight_source_sha256",
        "decode_preflight_compiled_endpoint_sha256",
        "tenant_commit",
        "tenant_tree",
        "tenant_roster_sha256",
        "tenant_status_sha256",
        "target_sha256",
        "context_revision",
        "semantic_source_revision",
        "toolchain_binding",
        "request_sha256",
        "expected_grounding_selections_sha256",
        "expected_shape_contract_sha256",
        "expected_processing_route",
        "expected_intent_compiler_sha256",
    }
    if set(identity) != required_identity:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark identity roster is invalid")
    if (
        not isinstance(identity["benchmark_id"], str)
        or not identity["benchmark_id"]
        or len(identity["benchmark_id"].encode()) > 128
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark identity is invalid")
    if type(identity["seed"]) is not int or identity["seed"] != 17:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark seed is invalid")
    if (
        type(identity["pairs"]) is not int
        or not MIN_PROMOTION_PAIRS <= identity["pairs"] <= MAX_PROMOTION_PAIRS
        or identity["arm_order"] not in (["direct", "prefix"], ["prefix", "direct"])
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark run roster is invalid")
    if identity["schedule_sha256"] != counterbalanced_schedule_sha256(
        pairs=identity["pairs"], arm_order=identity["arm_order"]
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark schedule identity differs")
    for key in (
        "adapter_sha256",
        "case_sha256",
        "worker_sha256",
        "prompt_prefix_sha256",
        "schedule_sha256",
        "tenant_roster_sha256",
        "tenant_status_sha256",
        "target_sha256",
        "context_revision",
        "semantic_source_revision",
        "toolchain_binding",
        "request_sha256",
        "expected_grounding_selections_sha256",
        "expected_shape_contract_sha256",
        "expected_intent_compiler_sha256",
        "decode_preflight_sha256",
        "decode_preflight_source_sha256",
        "decode_preflight_compiled_endpoint_sha256",
    ):
        _sha(identity[key], label=key)
    expected_prefix_tokens = _bounded_positive(
        identity["expected_prefix_tokens"],
        label="expected prefix tokens",
        upper=1_000_000,
    )
    _bounded_count(identity["retrieval_prewarm_ms"], label="retrieval prewarm duration")
    if identity["decode_preflight_count"] != len(ARMS):
        raise BrainError("BENCHMARK_INVALID", 400, "decode preflight roster is invalid")
    decode_preflights = identity["decode_preflights"]
    preflight_keys = {
        "arm",
        "request_sha256",
        "source_sha256",
        "compiled_endpoint_sha256",
        "grounding_selections_sha256",
        "shape_contract_sha256",
        "processing_route",
        "intent_compiler_sha256",
        "event_roster_sha256",
        "model_revision",
        "adapter_sha256",
        "worker_sha256",
        "prompt_prefix_sha256",
    }
    if (
        not isinstance(decode_preflights, list)
        or len(decode_preflights) != len(ARMS)
        or any(
            not isinstance(item, Mapping) or set(item) != preflight_keys
            for item in decode_preflights
        )
        or [item["arm"] for item in decode_preflights] != list(ARMS)
        or _hash(decode_preflights) != identity["decode_preflight_sha256"]
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "decode preflight evidence is invalid")
    preflight_expected = {
        "request_sha256": identity["request_sha256"],
        "source_sha256": identity["decode_preflight_source_sha256"],
        "compiled_endpoint_sha256": identity["decode_preflight_compiled_endpoint_sha256"],
        "grounding_selections_sha256": identity["expected_grounding_selections_sha256"],
        "shape_contract_sha256": identity["expected_shape_contract_sha256"],
        "processing_route": identity["expected_processing_route"],
        "intent_compiler_sha256": identity["expected_intent_compiler_sha256"],
        "model_revision": identity["model_revision"],
        "adapter_sha256": identity["adapter_sha256"],
        "worker_sha256": identity["worker_sha256"],
        "prompt_prefix_sha256": identity["prompt_prefix_sha256"],
    }
    if (
        any(
            item.get(key) != expected
            for item in decode_preflights
            for key, expected in preflight_expected.items()
        )
        or len({item["event_roster_sha256"] for item in decode_preflights}) != 1
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "decode preflight authority drifted")
    for item in decode_preflights:
        for key in (
            "request_sha256",
            "source_sha256",
            "compiled_endpoint_sha256",
            "grounding_selections_sha256",
            "shape_contract_sha256",
            "intent_compiler_sha256",
            "event_roster_sha256",
            "adapter_sha256",
            "worker_sha256",
            "prompt_prefix_sha256",
        ):
            _sha(item[key], label=f"decode preflight {key}")
    for key in (
        "model_revision",
        "tenant_commit",
        "tenant_tree",
        "model1_commit",
        "model1_tree",
    ):
        value = identity[key]
        if not isinstance(value, str) or not value or len(value) > 128:
            raise BrainError("BENCHMARK_INVALID", 400, f"{key} is invalid")
    for key in ("model1_commit", "model1_tree"):
        value = identity[key]
        if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
            raise BrainError("BENCHMARK_INVALID", 400, f"{key} is invalid")
    if identity["expected_processing_route"] not in _EVENT_ROUTES:
        raise BrainError("BENCHMARK_INVALID", 400, "processing route identity is invalid")
    if not isinstance(observations, Sequence) or not observations:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark observations are unavailable")
    normalized = [
        _validated_observation(item) for item in observations if isinstance(item, Mapping)
    ]
    if len(normalized) != len(observations):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark observation is invalid")
    by_pair: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    for item in normalized:
        pair = item.get("pair")
        arm = item.get("arm")
        if type(pair) is not int or not 1 <= pair <= MAX_PROMOTION_PAIRS or arm not in ARMS:
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark pair/arm is invalid")
        if arm in by_pair[pair]:
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark pair/arm is duplicated")
        by_pair[pair][arm] = item
    pair_ids = sorted(by_pair)
    if pair_ids != list(range(1, len(pair_ids) + 1)) or not all(
        set(by_pair[pair]) == set(ARMS) for pair in pair_ids
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark pair roster has gaps")
    if len(pair_ids) > MAX_PROMOTION_PAIRS:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark pair roster is oversized")
    if len(pair_ids) != identity["pairs"]:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark pair denominator differs")
    execution = sorted(normalized, key=lambda item: item["ordinal"])
    if [item["ordinal"] for item in execution] != list(range(1, len(execution) + 1)):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark execution ordinal has gaps")
    first_order = list(identity["arm_order"])
    second_order = list(reversed(first_order))
    expected_execution = [
        (pair, arm) for pair in pair_ids for arm in (first_order if pair % 2 else second_order)
    ]
    if [(item["pair"], item["arm"]) for item in execution] != expected_execution:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark execution is not counterbalanced")

    fixed_keys = {
        "request_sha256": identity["request_sha256"],
        "context_revision": identity["context_revision"],
        "semantic_source_revision": identity["semantic_source_revision"],
        "toolchain_binding": identity["toolchain_binding"],
        "model_revision": identity["model_revision"],
        "adapter_sha256": identity["adapter_sha256"],
        "worker_sha256": identity["worker_sha256"],
        "prompt_prefix_sha256": identity["prompt_prefix_sha256"],
        "tenant_commit": identity["tenant_commit"],
        "tenant_tree": identity["tenant_tree"],
        "tenant_status_sha256": identity["tenant_status_sha256"],
        "tenant_roster_sha256": identity["tenant_roster_sha256"],
        "target_sha256": identity["target_sha256"],
        "grounding_selections_sha256": identity["expected_grounding_selections_sha256"],
        "compiled_endpoint_sha256": identity["decode_preflight_compiled_endpoint_sha256"],
        "shape_contract_sha256": identity["expected_shape_contract_sha256"],
        "processing_route": identity["expected_processing_route"],
        "intent_compiler_sha256": identity["expected_intent_compiler_sha256"],
    }
    for pair in pair_ids:
        direct, prefix = (by_pair[pair][arm] for arm in ARMS)
        if any(
            item.get("source_sha256") != identity["decode_preflight_source_sha256"]
            for item in (direct, prefix)
        ):
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark semantic output differs")
        if any(
            item.get(key) != expected
            for item in (direct, prefix)
            for key, expected in fixed_keys.items()
        ):
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark authority identity drifted")
        if any(
            item.get("compile_clean") is not True
            or item.get("semantic_grounded") is not True
            or item.get("tenant_modified") is not False
            or item.get("repair_count") != 0
            for item in (direct, prefix)
        ):
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark terminal gate regressed")
        if direct.get("source_sha256") != prefix.get("source_sha256") or direct.get(
            "grounding_selections_sha256"
        ) != prefix.get("grounding_selections_sha256"):
            raise BrainError("BENCHMARK_INVALID", 400, "paired semantic output differs")
        # The full compiler receipt is session-bound and is therefore retained
        # per observation but cannot be equal across two isolated sessions.
        # Source, toolchain, status and diagnostics are already bound above.
        if direct.get("event_roster_sha256") != prefix.get("event_roster_sha256"):
            raise BrainError("BENCHMARK_INVALID", 400, "paired validation route differs")
        direct_metrics = direct.get("metrics")
        prefix_metrics = prefix.get("metrics")
        if not isinstance(direct_metrics, Mapping) or not isinstance(prefix_metrics, Mapping):
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark phase telemetry is invalid")
        if (
            direct_metrics.get("cache_mode") != "disabled"
            or direct_metrics.get("cache_hit") is not False
            or direct_metrics.get("cached_tokens") != 0
            or prefix_metrics.get("cache_mode") != "prefix"
            or prefix_metrics.get("cache_hit") is not True
            or prefix_metrics.get("cached_tokens") != expected_prefix_tokens
            or direct_metrics.get("prompt_tokens") != prefix_metrics.get("prompt_tokens")
            or direct_metrics.get("generation_tokens") != prefix_metrics.get("generation_tokens")
            or direct_metrics.get("finish_reason") != prefix_metrics.get("finish_reason")
            or direct_metrics.get("finish_reason") != "stop"
        ):
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark cache proof is invalid")

    if (
        len({item["source_sha256"] for item in normalized}) != 1
        or len({item["grounding_selections_sha256"] for item in normalized}) != 1
        or len({item["event_roster_sha256"] for item in normalized}) != 1
        or len({item["metrics"]["prompt_tokens"] for item in normalized}) != 1
        or len({item["metrics"]["generation_tokens"] for item in normalized}) != 1
        or len({item["metrics"]["finish_reason"] for item in normalized}) != 1
    ):
        raise BrainError("BENCHMARK_INVALID", 400, "frozen benchmark output drifted")

    aggregates: dict[str, Any] = {}
    for arm in ARMS:
        arm_items = [by_pair[pair][arm] for pair in pair_ids]
        aggregates[arm] = {
            key: {
                "p50": _nearest_rank([item[key] for item in arm_items], 0.50),
                "p95": _nearest_rank([item[key] for item in arm_items], 0.95),
            }
            for key in (
                "turn_ms",
                "retrieval_ms",
                "intent_ms",
                "inference_ms",
                "compile_ms",
                "host_inference_overhead_ms",
            )
        }
        aggregates[arm]["generation"] = {
            key: {
                "p50": _nearest_rank([item["metrics"][key] for item in arm_items], 0.50),
                "p95": _nearest_rank([item["metrics"][key] for item in arm_items], 0.95),
            }
            for key in (
                "worker_request_ms",
                "model_lock_queue_ms",
                "cache_prepare_ms",
                "generation_ms",
                "tokenization_ms",
                "time_to_first_token_ms",
                "decode_after_first_token_ms",
                "generation_residual_ms",
                "worker_residual_ms",
            )
        }
    direct_p50 = aggregates["direct"]["inference_ms"]["p50"]
    direct_p95 = aggregates["direct"]["inference_ms"]["p95"]
    prefix_p50 = aggregates["prefix"]["inference_ms"]["p50"]
    prefix_p95 = aggregates["prefix"]["inference_ms"]["p95"]
    promoted = (
        len(pair_ids) >= MIN_PROMOTION_PAIRS
        and prefix_p50 <= math.floor(direct_p50 * 0.60)
        and prefix_p95 <= math.floor(direct_p95 * 0.70)
        and aggregates["prefix"]["turn_ms"]["p95"] <= 25_000
    )
    body = {
        "schema_version": 1,
        "status": "PROMOTED" if promoted else "MEASURED_NOT_PROMOTED",
        "identity": dict(identity),
        "denominator": {
            "pairs": len(pair_ids),
            "observations": len(normalized),
            "in": len(normalized),
            "out": len(normalized),
            "distinct": len({(item["pair"], item["arm"]) for item in normalized}),
            "gaps": 0,
        },
        "thresholds": {
            "minimum_pairs": MIN_PROMOTION_PAIRS,
            "prefix_inference_p50_ratio_max": 0.60,
            "prefix_inference_p95_ratio_max": 0.70,
            "prefix_turn_p95_ms_max": 25_000,
        },
        "aggregates": aggregates,
        "observations": execution,
        "claims": {
            "paired_same_snapshot": True,
            "counterbalanced_schedule": True,
            "retrieval_warm_at_first_observation": True,
            "decode_preflights_excluded_from_denominator": len(ARMS),
            "exact_source_parity": True,
            "exact_grounding_parity": True,
            "shape_contract_oracle": True,
            "compiled_endpoint_parity": True,
            "compile_clean": True,
            "tenant_modified": False,
            "latency_promoted": promoted,
        },
    }
    return {**body, "receipt_sha256": _hash(body)}


class LatencyReceiptHandle:
    """Publish a pending receipt only after the caller accepts its authority."""

    def __init__(self, *, parent_fd: int, file_fd: int, pending_name: str, final_name: str) -> None:
        self._parent_fd = parent_fd
        self._file_fd = file_fd
        self._pending_name = pending_name
        self._final_name = final_name
        self._closed = False

    def _pending_matches(self) -> bool:
        opened = os.fstat(self._file_fd)
        named = os.stat(
            self._pending_name,
            dir_fd=self._parent_fd,
            follow_symlinks=False,
        )
        return (
            stat.S_ISREG(opened.st_mode)
            and stat.S_ISREG(named.st_mode)
            and opened.st_dev == named.st_dev
            and opened.st_ino == named.st_ino
            and opened.st_nlink == 1
            and named.st_nlink == 1
        )

    def _close(self) -> None:
        os.close(self._file_fd)
        os.close(self._parent_fd)
        self._closed = True

    def commit(self) -> None:
        if self._closed:
            return
        linked = False
        try:
            if not self._pending_matches():
                raise OSError("pending receipt identity changed")
            os.link(
                self._pending_name,
                self._final_name,
                src_dir_fd=self._parent_fd,
                dst_dir_fd=self._parent_fd,
                follow_symlinks=False,
            )
            linked = True
            os.fsync(self._parent_fd)
        except OSError as error:
            try:
                if linked:
                    os.unlink(self._final_name, dir_fd=self._parent_fd)
                if self._pending_matches():
                    os.unlink(self._pending_name, dir_fd=self._parent_fd)
                os.fsync(self._parent_fd)
            except OSError:
                pass
            self._close()
            raise BrainError(
                "BENCHMARK_INVALID", 500, "benchmark receipt publication failed"
            ) from error
        try:
            os.unlink(self._pending_name, dir_fd=self._parent_fd)
            os.fsync(self._parent_fd)
        except OSError:
            # The final name is already durably published after all authority
            # guards. A stale dot-pending hardlink is distinguishable and never
            # accepted as a final receipt.
            pass
        self._close()

    def discard(self) -> None:
        if self._closed:
            return
        error: OSError | None = None
        try:
            if not self._pending_matches():
                raise OSError("pending receipt identity changed")
            os.unlink(self._pending_name, dir_fd=self._parent_fd)
            os.fsync(self._parent_fd)
        except OSError as caught:
            error = caught
        finally:
            self._close()
        if error is not None:
            raise BrainError(
                "BENCHMARK_INVALID", 500, "benchmark receipt cleanup failed"
            ) from error


def _open_absolute_directory(path: Path) -> int:
    resolved = path.resolve(strict=True)
    if not resolved.is_absolute():
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark output parent is invalid")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.open("/", flags)
    try:
        for part in resolved.parts[1:]:
            if not part or part in {".", ".."}:
                raise BrainError("BENCHMARK_INVALID", 400, "benchmark output parent is invalid")
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark output parent is invalid")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_receipt_parent(path: Path, *, authority_root: Path | None) -> tuple[int, str]:
    target = Path(path)
    if not target.is_absolute() or target.name in {"", ".", ".."}:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark output path is invalid")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    if authority_root is None:
        return _open_absolute_directory(target.parent), target.name
    root = Path(authority_root)
    try:
        if root.resolve(strict=True) != root:
            raise BrainError("BENCHMARK_INVALID", 400, "benchmark output root is invalid")
        relative = target.relative_to(root)
    except (OSError, ValueError) as error:
        raise BrainError(
            "BENCHMARK_INVALID", 400, "benchmark output path is outside authority"
        ) from error
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark output path is invalid")
    descriptor = _open_absolute_directory(root)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor, relative.parts[-1]
    except BaseException:
        os.close(descriptor)
        raise


def write_latency_receipt(
    path: Path,
    receipt: Mapping[str, Any],
    *,
    authority_root: Path | None = None,
    hold_parent: bool = False,
) -> LatencyReceiptHandle | None:
    """Create one immutable receipt through no-follow directory descriptors."""

    target = Path(path)
    if not target.is_absolute():
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark output path is invalid")
    payload = canonical_json(dict(receipt)) + b"\n"
    if len(payload) > 4 * 1024 * 1024:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark receipt is oversized")
    try:
        parent_fd, name = _open_receipt_parent(target, authority_root=authority_root)
    except BrainError:
        raise
    except OSError as error:
        raise BrainError(
            "BENCHMARK_INVALID", 400, "benchmark output parent is unavailable"
        ) from error
    descriptor: int | None = None
    created = False
    handle_owns_fds = False
    pending_name = f".{name}.{secrets.token_hex(16)}.pending"
    try:
        descriptor = os.open(
            pending_name,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=parent_fd,
        )
        created = True
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written < 1:
                raise OSError("short receipt write")
            view = view[written:]
        os.fsync(descriptor)
        os.fsync(parent_fd)
        handle = LatencyReceiptHandle(
            parent_fd=parent_fd,
            file_fd=descriptor,
            pending_name=pending_name,
            final_name=name,
        )
        descriptor = None
        handle_owns_fds = True
        if hold_parent:
            return handle
        handle.commit()
        return None
    except BaseException as error:
        if handle_owns_fds:
            raise
        if descriptor is not None:
            os.close(descriptor)
        if created:
            try:
                os.unlink(pending_name, dir_fd=parent_fd)
                os.fsync(parent_fd)
            except OSError:
                pass
        os.close(parent_fd)
        if isinstance(error, BrainError):
            raise
        if isinstance(error, OSError):
            raise BrainError(
                "BENCHMARK_INVALID", 400, "benchmark receipt could not be written"
            ) from error
        raise


def verify_latency_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Recompute the complete receipt from its admitted identity/observations."""

    if not isinstance(receipt, Mapping) or set(receipt) != {
        "schema_version",
        "status",
        "identity",
        "denominator",
        "thresholds",
        "aggregates",
        "observations",
        "claims",
        "receipt_sha256",
    }:
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark receipt schema is invalid")
    rebuilt = seal_latency_receipt(
        identity=receipt["identity"], observations=receipt["observations"]
    )
    if canonical_json(rebuilt) != canonical_json(dict(receipt)):
        raise BrainError("BENCHMARK_INVALID", 400, "benchmark receipt differs on replay")
    return rebuilt


__all__ = [
    "ARMS",
    "LatencyReceiptHandle",
    "counterbalanced_schedule_sha256",
    "observation_from_terminal",
    "selection_roster_sha256",
    "seal_latency_receipt",
    "verify_latency_receipt",
    "write_latency_receipt",
]
